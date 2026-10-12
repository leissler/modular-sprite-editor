"""Auto Modularize: preview how an image's sprites cut into shared hardware-sized parts, then apply.

The plan is computed by ``modularize.plan`` in a worker thread whenever a setting changes; the dialog shows each
sprite cut into its parts (shared parts in their own colour), the packed parts sheet and the Mega Drive cost before
and after. Applying is left to the caller (``ModuleEditorPanel.auto_modularize``) with ``plan`` and ``sheet_path``.
"""
from __future__ import annotations

import colorsys
import os
import threading
from typing import Dict, List, Optional, Tuple

import wx

import modularize as mz
from models import ImageAsset, Module, Project
from ui.base_canvas import BaseCanvas
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.components.inspector_kit import dim_text, fit_choice, section
from ui.components.thumb_list import Browser, Row
from ui.frame_render import SHARED, fit_bitmap, to_wx_image

# Goal slider stops: how many tiles one more hardware sprite (in one sprite) is worth.
GOALS: List[Tuple[float, str]] = [
    (0.25, "Fewest tiles: many small parts"),
    (0.5, "Fewer tiles"),
    (1.0, "Leaning to fewer tiles"),
    (2.0, "Balanced: 1 sprite = 2 tiles"),
    (4.0, "Leaning to fewer sprites"),
    (8.0, "Fewer hardware sprites"),
    (16.0, "Fewest sprites: few, large parts"),
]
DEFAULT_GOAL = 3
VIEW_PARTS, VIEW_ORIGINAL, VIEW_SHEET = "Parts", "Original", "Parts sheet"
THUMB_BG = (30, 31, 34)
WRAP = 280  # width of the explanatory texts in the settings column


def part_colour(index: int) -> wx.Colour:
    r, g, b = colorsys.hsv_to_rgb((index * 0.618033988749895) % 1.0, 0.65, 1.0)
    return wx.Colour(int(r * 255), int(g * 255), int(b * 255))


class PlanCanvas(BaseCanvas):
    """A sprite with its parts outlined (shared parts in their colour), or the packed parts sheet."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        self.view = VIEW_PARTS
        self.image = None  # PIL image shown
        self.boxes: List[Tuple[int, int, int, int, int, bool, bool]] = []  # x, y, w, h, part, flip_x, flip_y
        self.uses: Dict[int, int] = {}
        self.hover_part: Optional[int] = None
        self.on_hover = None
        self._bitmap: Optional[Tuple[Tuple[int, int, float], wx.Bitmap]] = None
        self._wx_image: Optional[wx.Image] = None
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(None))

    def show(self, image, boxes, uses, fit: bool = False) -> None:
        if image is not self.image:
            self._wx_image = to_wx_image(image) if image is not None else None
            self._bitmap = None
        self.image = image
        self.boxes = boxes
        self.uses = uses
        if fit:
            self.fit_to_content()
        self.Refresh(False)

    def get_content_bounds(self):
        if self.image is None:
            return None
        return (0, 0, self.image.width, self.image.height)

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        if self.begin_pan_if_requested(event):
            return
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
            self.on_pan_end(event)
        event.Skip()

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return
        wx_, wy = self.screen_to_world(event.GetPosition())
        hit = None
        for x, y, w, h, part, _fx, _fy in reversed(self.boxes):
            if x <= wx_ < x + w and y <= wy < y + h:
                hit = part
                break
        self._set_hover(hit)

    def _set_hover(self, part: Optional[int]) -> None:
        if part != self.hover_part:
            self.hover_part = part
            if self.on_hover:
                self.on_hover(part)
            self.Refresh(False)

    def on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.draw_backdrop(dc)
        gc = wx.GraphicsContext.Create(dc)
        if self.image is None or self._wx_image is None:
            return
        w, h = self.image.size
        tw, th = max(1, int(round(w * self.zoom))), max(1, int(round(h * self.zoom)))
        key = (tw, th, self.zoom)
        if self._bitmap is None or self._bitmap[0] != key:
            scaled = self._wx_image.Copy()
            scaled.Rescale(tw, th, wx.IMAGE_QUALITY_NEAREST)
            self._bitmap = (key, scaled.ConvertToBitmap())
        sx, sy = self.world_to_screen((0, 0))
        gc.DrawBitmap(self._bitmap[1], round(sx), round(sy), tw, th)
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(wx.Colour(190, 190, 196, 120), 1))
        gc.DrawRectangle(round(sx) - 0.5, round(sy) - 0.5, tw + 1, th + 1)
        if self.view == VIEW_ORIGINAL:
            return
        for x, y, bw, bh, part, flip_x, flip_y in self.boxes:
            shared = self.uses.get(part, 0) > 1
            colour = part_colour(part) if shared else wx.Colour(200, 200, 205)
            hovered = part == self.hover_part
            x0, y0 = self.world_to_screen((x, y))
            rw, rh = bw * self.zoom, bh * self.zoom
            if shared or hovered:
                gc.SetBrush(wx.Brush(wx.Colour(colour.Red(), colour.Green(), colour.Blue(), 70 if hovered else 34)))
            else:
                gc.SetBrush(wx.TRANSPARENT_BRUSH)
            gc.SetPen(wx.Pen(colour if (shared or hovered) else wx.Colour(200, 200, 205, 150), 3 if hovered else 1))
            gc.DrawRectangle(round(x0) + 0.5, round(y0) + 0.5, rw - 1, rh - 1)
            if (flip_x or flip_y) and self.zoom >= 3:
                gc.SetFont(wx.Font(wx.FontInfo(8).Bold()), colour)
                gc.DrawText(("↔" if flip_x else "") + ("↕" if flip_y else ""), round(x0) + 3, round(y0) + 1)


class ModularizeDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, project: Project, asset: ImageAsset, modules: List[Module]):
        super().__init__(parent, title=f"Auto Modularize — {os.path.basename(asset.file_path)}",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        self.project = project
        self.asset = asset
        self.modules = modules
        self.plan: Optional[mz.Plan] = None
        self._run = 0
        self._closing = False
        self._restart: Optional[wx.CallLater] = None
        self._last_progress = (None, -1.0)
        self._sheet_cache: Optional[Tuple[int, object, List[Tuple[int, int]]]] = None
        self._selected: Optional[str] = modules[0].id if modules else None
        self._thumbs: Dict[Tuple[str, int], wx.Bitmap] = {}

        self.sprites: Dict[str, object] = {m.id: SHARED.module(project, m) for m in modules}
        self.frame_uses = {m.id: 0 for m in modules}
        for frame in project.frames:
            for fm in frame.fmodules:
                if fm.ref_type == "module" and fm.ref_id in self.frame_uses:
                    self.frame_uses[fm.ref_id] += 1
        self.before = self._before_costs()

        root = wx.BoxSizer(wx.VERTICAL)
        body = wx.BoxSizer(wx.HORIZONTAL)

        # Sprites
        self.browser = Browser(self, "Sprites", row_h=46, thumb=38, filter_hint="Filter sprites")
        self.browser.list.thumbnail = self._thumbnail
        self.browser.list.Bind(wx.EVT_LISTBOX, self._on_select_sprite)
        self.browser.search.Bind(wx.EVT_TEXT, lambda e: self._refresh_rows())
        self.browser.SetMinSize((230, -1))
        body.Add(self.browser, 0, wx.EXPAND)

        # Preview
        middle = wx.BoxSizer(wx.VERTICAL)
        self.canvas = PlanCanvas(self)
        self.canvas.on_hover = self._on_hover
        self.canvas.show_grid = False  # a sprite-aligned grid would look like part outlines
        self.controls = CanvasDisplayControls(self, self.canvas, view_key="modularize")
        self.view_choice = wx.Choice(self.controls, choices=[VIEW_PARTS, VIEW_ORIGINAL, VIEW_SHEET])
        self.view_choice.SetSelection(0)
        fit_choice(self.view_choice)
        self.view_choice.SetToolTip("Parts: the sprite cut into its parts (shared parts in colour, ↔ ↕ = mirrored). "
                                    "Original: the sprite as it is. Parts sheet: the new image with every part.")
        self.view_choice.Bind(wx.EVT_CHOICE, lambda e: self._show_selected(fit=True))
        self.controls.add_control(self.view_choice, "Show")
        middle.Add(self.canvas, 1, wx.EXPAND)
        middle.Add(self.controls, 0, wx.EXPAND)
        body.Add(middle, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # Settings and result
        side = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        panel, grid, _ = section(side, sizer, "Goal")
        self.goal = wx.Slider(panel, value=DEFAULT_GOAL, minValue=0, maxValue=len(GOALS) - 1, style=wx.SL_HORIZONTAL)
        self.goal.SetToolTip("What matters more on the console: video memory (tiles) or hardware sprites per frame "
                             "(the Mega Drive shows 80 per screen and 20 per line).")
        ends = wx.BoxSizer(wx.HORIZONTAL)
        ends.Add(dim_text(panel, "Fewer tiles"), 0)
        ends.AddStretchSpacer(1)
        ends.Add(dim_text(panel, "Fewer sprites"), 0)
        self.goal_text = wx.StaticText(panel, label=max((text for _w, text in GOALS), key=len))
        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(self.goal, 0, wx.EXPAND)
        column.Add(ends, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        column.Add(self.goal_text, 0, wx.TOP, 4)
        grid.Add((0, 0))
        grid.Add(column, 1, wx.EXPAND)
        self.goal.Bind(wx.EVT_SLIDER, lambda e: self._settings_changed())

        panel, grid, _ = section(side, sizer, "Parts")
        self.chk_share = wx.CheckBox(panel, label="Share parts between sprites")
        self.chk_share.SetValue(True)
        self.chk_share.SetToolTip("Find pixels that several sprites have in common (at any position) and store them once. "
                                  "Off: every sprite is only cut into tightly fitting hardware sprites.")
        self.chk_flip_x = wx.CheckBox(panel, label="Mirrored horizontally")
        self.chk_flip_y = wx.CheckBox(panel, label="Mirrored vertically")
        for chk in (self.chk_flip_x, self.chk_flip_y):
            chk.SetValue(True)
            chk.SetToolTip("Also reuse parts that appear mirrored (the Mega Drive flips hardware sprites for free).")
        self.chk_thorough = wx.CheckBox(panel, label="Thorough search (slower)")
        self.chk_thorough.SetToolTip("Also look for small shared parts (4×4 pixel matches instead of 8×8). "
                                     "Helps with sprites built from many small pieces; takes much longer.")
        for chk in (self.chk_share, self.chk_flip_x, self.chk_flip_y, self.chk_thorough):
            grid.Add((0, 0))
            grid.Add(chk, 0)
            chk.Bind(wx.EVT_CHECKBOX, lambda e: self._settings_changed())

        panel, grid, _ = section(side, sizer, "Result (Mega Drive)")
        table = wx.FlexGridSizer(0, 3, 4, 12)
        table.AddGrowableCol(0, 1)
        for text in ("", "Now", "Result"):
            label = dim_text(panel, text)
            table.Add(label, 0, wx.ALIGN_RIGHT if text else 0)
        self.result_cells: Dict[str, Tuple[wx.StaticText, wx.StaticText]] = {}
        for key, label, tip in (
            ("tiles", "VRAM tiles", "8×8 tiles in video memory for these sprites, as the SGDK exporter bakes them"),
            ("sprites", "Hardware sprites", "Hardware sprites one sprite needs: average / worst"),
            ("parts", "Parts per sprite", "Parts that rebuild one sprite: average / worst"),
            ("modules", "Modules", "Modules on the image now / parts on the new image"),
            ("shared", "Shared parts", "Parts that appear in more than one sprite"),
        ):
            name = wx.StaticText(panel, label=label)
            name.SetToolTip(tip)
            now, after = wx.StaticText(panel, label="–"), wx.StaticText(panel, label="…")
            table.Add(name, 0)
            table.Add(now, 0, wx.ALIGN_RIGHT)
            table.Add(after, 0, wx.ALIGN_RIGHT)
            self.result_cells[key] = (now, after)
        grid.Add((0, 0))
        grid.Add(table, 1, wx.EXPAND)
        self.saving_text = wx.StaticText(panel, label="")
        grid.Add((0, 0))
        grid.Add(self.saving_text, 0)
        note = dim_text(panel, "Parts are at most 32×32, so each is one hardware sprite.")
        note.Wrap(WRAP)
        panel.GetSizer().Add(note, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)

        panel, grid, _ = section(side, sizer, "Output")
        stem = os.path.splitext(os.path.basename(asset.file_path))[0] or "sheet"
        self.sheet_name = wx.TextCtrl(panel, value=f"{stem}_parts.png")
        self.sheet_name.SetToolTip("The parts go on this new image, next to the current one.")
        grid.Add(wx.StaticText(panel, label="New image"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.sheet_name, 1, wx.EXPAND)
        self.output_text = dim_text(panel, "")
        panel.GetSizer().Add(self.output_text, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)

        side.SetSizer(sizer)
        self._side = side
        body.Add(side, 0, wx.EXPAND)
        root.Add(body, 1, wx.EXPAND | wx.ALL, 6)

        # Status and buttons
        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.status = wx.StaticText(self, label="")
        self.gauge = wx.Gauge(self, range=1000, size=(160, -1))
        bottom.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        bottom.Add(self.gauge, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
        self.apply_button = wx.Button(self, wx.ID_OK, "Apply")
        self.apply_button.SetDefault()
        self.apply_button.Enable(False)
        bottom.Add(cancel, 0, wx.RIGHT, 6)
        bottom.Add(self.apply_button, 0)
        root.Add(bottom, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(root)
        self.SetSize((1300, 800))
        self.SetMinSize((1000, 600))
        self.CentreOnParent()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self._on_apply, id=wx.ID_OK)

        self._fill_before()
        self._describe_output()
        side.Fit()
        self.Layout()
        self._refresh_rows()
        self._settings_changed(delay=1)
        wx.CallAfter(self._show_selected, True)

    # ---------------------------------------------------------------- settings and the worker
    def settings(self) -> mz.Settings:
        return mz.Settings(sprite_weight=GOALS[self.goal.GetValue()][0], flip_x=self.chk_flip_x.GetValue(),
                           flip_y=self.chk_flip_y.GetValue(), share=self.chk_share.GetValue(),
                           window=4 if self.chk_thorough.GetValue() else 8)

    def _settings_changed(self, delay: int = 250) -> None:
        self.goal_text.SetLabel(GOALS[self.goal.GetValue()][1])
        for chk in (self.chk_flip_x, self.chk_flip_y, self.chk_thorough):
            chk.Enable(self.chk_share.GetValue())
        self._run += 1  # the running plan (if any) stops at its next check
        self.plan = None
        self.apply_button.Enable(False)
        for _now, after in self.result_cells.values():
            after.SetLabel("…")
        self.saving_text.SetLabel("")
        if self._restart is not None:
            self._restart.Stop()
        self._restart = wx.CallLater(delay, self._start)

    def _start(self) -> None:
        self._run += 1
        run = self._run
        settings = self.settings()
        sprites = dict(self.sprites)
        self._last_progress = (None, -1.0)

        def progress(text: str, fraction: float) -> None:
            last_text, last_fraction = self._last_progress
            if text != last_text or fraction - last_fraction >= 0.02 or fraction >= 1.0:
                self._last_progress = (text, fraction)
                wx.CallAfter(self._on_progress, run, text, fraction)

        def cancelled() -> bool:
            return self._closing or run != self._run

        def work() -> None:
            try:
                result = mz.plan(sprites, settings, progress, cancelled)
            except mz.Cancelled:
                return
            except Exception as exc:  # shown to the user, the dialog stays usable
                wx.CallAfter(self._on_failed, run, exc)
                return
            wx.CallAfter(self._on_plan, run, result)

        threading.Thread(target=work, name="modularize", daemon=True).start()

    def _alive(self, run: int) -> bool:
        try:
            return bool(self) and not self._closing and run == self._run
        except RuntimeError:
            return False

    def _on_progress(self, run: int, text: str, fraction: float) -> None:
        if self._alive(run):
            self.status.SetLabel(f"{text}…" if fraction < 1.0 else "")
            self.gauge.SetValue(int(1000 * max(0.0, min(1.0, fraction))))

    def _on_failed(self, run: int, exc: Exception) -> None:
        if self._alive(run):
            self.status.SetLabel(f"Could not modularize: {exc}")
            self.gauge.SetValue(0)

    def _on_plan(self, run: int, plan: mz.Plan) -> None:
        if not self._alive(run):
            return
        self.plan = plan
        self._sheet_cache = None
        self.gauge.SetValue(0)
        self.status.SetLabel(f"Planned in {plan.seconds:.1f} s. Hover a part to see where else it is used.")
        self._fill_result()
        self._refresh_rows()
        self._show_selected(fit=False)
        self.apply_button.Enable(True)

    # ---------------------------------------------------------------- figures
    def _before_costs(self) -> Dict[str, float]:
        tiles = 0
        seen = set()
        sprites = []
        for image in self.sprites.values():
            image = mz._normalised(image)
            box = image.getchannel("A").getbbox()
            if not box:
                continue
            image = image.crop(box)
            t, s = mz.part_tiles(image)
            sprites.append(s)
            digest = mz._digest(image)
            if digest not in seen:
                seen.add(digest)
                tiles += t
        n = max(1, len(sprites))
        return {"tiles": tiles, "sprites": sum(sprites) / n, "sprites_max": max(sprites, default=0)}

    def _fill_before(self) -> None:
        b = self.before
        self.result_cells["tiles"][0].SetLabel(str(b["tiles"]))
        self.result_cells["sprites"][0].SetLabel(f"{b['sprites']:.1f} / {b['sprites_max']}")
        self.result_cells["parts"][0].SetLabel("1.0 / 1")
        self.result_cells["modules"][0].SetLabel(str(len(self.modules)))
        self.result_cells["shared"][0].SetLabel("–")

    def _fill_result(self) -> None:
        plan = self.plan
        if plan is None:
            return
        tiles = plan.tiles()
        counts = [c for key, c in plan.sprite_counts().items() if plan.placements[key]]
        parts = [len(p) for p in plan.placements.values() if p]
        n = max(1, len(counts))
        uses = plan.uses()
        cells = self.result_cells
        cells["tiles"][1].SetLabel(str(tiles))
        cells["sprites"][1].SetLabel(f"{sum(counts) / n:.1f} / {max(counts, default=0)}")
        cells["parts"][1].SetLabel(f"{sum(parts) / max(1, len(parts)):.1f} / {max(parts, default=0)}")
        cells["modules"][1].SetLabel(str(len(plan.parts)))
        cells["shared"][1].SetLabel(str(sum(1 for c in uses.values() if c > 1)))
        before = self.before["tiles"]
        if before:
            change = 100.0 * (tiles - before) / before
            self.saving_text.SetLabel(f"{abs(change):.0f} % {'fewer' if change <= 0 else 'more'} tiles in VRAM")
        self.Layout()

    def _describe_output(self) -> None:
        unused = sum(1 for n in self.frame_uses.values() if not n)
        frames = {f.id for f in self.project.frames for fm in f.fmodules
                  if fm.ref_type == "module" and fm.ref_id in self.frame_uses}
        text = (f"The {len(self.modules)} modules of this image are replaced by the parts. "
                f"{len(frames)} frame{'s' if len(frames) != 1 else ''} using them "
                f"{'are' if len(frames) != 1 else 'is'} rebuilt from the parts")
        text += f"; {unused} sprite{'s' if unused != 1 else ''} no frame uses get{'' if unused != 1 else 's'} a frame." if unused else "."
        ids = set(self.frame_uses)
        entries = sum(1 for mapping in self.project.mappings for key, target in mapping.map.items()
                      if key in ids or target in ids)
        if entries:
            text += (f" {entries} mapping entr{'ies' if entries != 1 else 'y'} that re-skin these modules "
                     f"{'are' if entries != 1 else 'is'} removed (a part-level mapping cannot be derived).")
        text += " Undo restores everything."
        self.output_text.SetLabel(text)
        self.output_text.Wrap(WRAP)

    # ---------------------------------------------------------------- list and preview
    def _refresh_rows(self) -> None:
        needle = self.browser.filter_text().lower() if hasattr(self.browser, "filter_text") else ""
        uses = self.plan.uses() if self.plan else {}
        rows = []
        for mod in self.modules:
            if needle and needle not in mod.name.lower():
                continue
            meta = f"{self.frame_uses[mod.id]} frame{'s' if self.frame_uses[mod.id] != 1 else ''}" if self.frame_uses[mod.id] else "no frame yet"
            badge = ""
            if self.plan is not None:
                pls = self.plan.placements.get(mod.id, [])
                shared = sum(1 for pl in pls if uses.get(pl.part, 0) > 1)
                meta = f"{len(pls)} part{'s' if len(pls) != 1 else ''}" + (f", {shared} shared" if shared else "") + " · " + meta
                badge = "●" if shared else ""
            rows.append(Row(mod.id, mod.name, meta, dim=not self.frame_uses[mod.id], badge=badge))
        self.browser.list.set_rows(rows, [self._selected] if self._selected else [])
        self.browser.set_count(len(rows), len(self.modules))
        self.browser.list.Refresh()

    def _thumbnail(self, module_id: str, size: int) -> Optional[wx.Bitmap]:
        key = (module_id, size)
        bmp = self._thumbs.get(key)
        if bmp is None:
            image = self.sprites.get(module_id)
            if image is None:
                return None
            bmp = fit_bitmap(image, size, size, THUMB_BG)
            self._thumbs[key] = bmp
        return bmp

    def _on_select_sprite(self, _event: wx.CommandEvent) -> None:
        ids = self.browser.list.selected_ids()
        if ids:
            self._selected = ids[0]
            if self.view_choice.GetStringSelection() == VIEW_SHEET:
                self.view_choice.SetStringSelection(VIEW_PARTS)
            self._show_selected(fit=True)

    def _show_selected(self, fit: bool = False) -> None:
        view = self.view_choice.GetStringSelection()
        self.canvas.view = view
        uses = self.plan.uses() if self.plan else {}
        if view == VIEW_SHEET:
            if self.plan is None:
                self.canvas.show(None, [], {}, fit)
                return
            if self._sheet_cache is None or self._sheet_cache[0] is not self.plan:
                sheet, places = mz.pack(self.plan.parts)
                self._sheet_cache = (self.plan, sheet, places)
            _plan, sheet, places = self._sheet_cache
            boxes = [(x, y, p.width, p.height, i, False, False) for i, (p, (x, y)) in enumerate(zip(self.plan.parts, places))]
            self.canvas.show(sheet, boxes, uses, fit)
            return
        image = self.sprites.get(self._selected) if self._selected else None
        boxes = []
        if self.plan is not None and self._selected in self.plan.placements:
            for pl in self.plan.placements[self._selected]:
                part = self.plan.parts[pl.part]
                boxes.append((pl.x, pl.y, part.width, part.height, pl.part, pl.flip_x, pl.flip_y))
        self.canvas.show(image, boxes, uses, fit)

    def _on_hover(self, part: Optional[int]) -> None:
        if part is None or self.plan is None:
            if self.plan is not None:
                self.status.SetLabel(f"Planned in {self.plan.seconds:.1f} s. Hover a part to see where else it is used.")
            return
        image = self.plan.parts[part]
        users = [m.name for m in self.modules if any(pl.part == part for pl in self.plan.placements.get(m.id, []))]
        tiles, _sprites = mz.part_tiles(image)
        where = ", ".join(users[:6]) + (f" and {len(users) - 6} more" if len(users) > 6 else "")
        self.status.SetLabel(f"Part {part + 1}: {image.width}×{image.height}, {tiles} tile{'s' if tiles != 1 else ''}, "
                             f"in {len(users)} sprite{'s' if len(users) != 1 else ''}: {where}")

    # ---------------------------------------------------------------- closing
    def sheet_path(self) -> str:
        """Where the parts image goes: next to the current image, never over an existing file."""
        name = os.path.basename(self.sheet_name.GetValue().strip()) or "parts.png"
        if not name.lower().endswith(".png"):
            name += ".png"
        folder = os.path.dirname(self.asset.file_path) or os.getcwd()
        stem, ext = os.path.splitext(name)
        path, n = os.path.join(folder, name), 2
        while os.path.exists(path):
            path = os.path.join(folder, f"{stem}_{n}{ext}")
            n += 1
        return path

    def _on_apply(self, _event: wx.CommandEvent) -> None:
        if self.plan is None:
            return
        self._closing = True
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, _event: wx.CommandEvent) -> None:
        self._closing = True
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._closing = True
        event.Skip()
