"""Modules inspector: the sheet (file, key colour, slicing tools) or the selected module(s)."""

from __future__ import annotations

import os
from typing import Any, Callable, List, Optional, Tuple

import wx

from models import ImageAsset, Module, Project
from ui.components.inspector_kit import bind_spin, dim_text, hbox, row, section, set_spin, small_button, spin
from ui.module_editor import ops

PRESET_GLYPHS = ("◤", "▲", "◥", "◀", "●", "▶", "◣", "▼", "◢")


class ModuleInspector(wx.ScrolledWindow):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.SetScrollRate(0, 12)
        self.SetMinSize((280, -1))
        self.project: Optional[Project] = None
        self.modules: List[Module] = []
        self._updating = False
        self._shape_types: List[str] = [key for key, _label in ops.SHAPE_TYPES]

        # Callbacks (set by the panel)
        self.on_field: Optional[Callable[[str, Any], None]] = None     # name / x / y / w / h / px / py / shape / color / params
        self.on_preset: Optional[Callable[[Tuple[float, float]], None]] = None
        self.on_tool: Optional[Callable[[str], None]] = None           # see the buttons below
        self.on_draw_shape: Optional[Callable[[str, Tuple[int, int, int]], None]] = None

        root = wx.BoxSizer(wx.VERTICAL)
        self.hint = dim_text(self)
        root.Add(self.hint, 0, wx.ALL, 8)

        # --- Sheet
        self.sheet_panel, grid, self.sheet_title = section(self, root, "Sheet")
        p = self.sheet_panel
        self.file_name = wx.StaticText(p, label="")
        row(grid, p, "File", self.file_name)
        self.file_info = dim_text(p)
        grid.Add((0, 0))
        grid.Add(self.file_info, 0)
        self.btn_locate = small_button(p, "Locate…", "Point this image to its file on disk (keeps every module)", lambda: self._tool("locate"))
        self.btn_reload = small_button(p, "Reload", "Read the image file again (after editing it in a paint program)", lambda: self._tool("reload"))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_locate, self.btn_reload), 0, wx.EXPAND)
        self.key_swatch = wx.Panel(p, size=(28, 18), style=wx.BORDER_SIMPLE)
        self.key_info = dim_text(p)
        self.btn_pick = small_button(p, "Pick", "Click a pixel of the image to make its colour transparent (Esc cancels)", lambda: self._tool("pick_key"))
        self.btn_clear_key = small_button(p, "None", "No key colour: only the image's own transparency counts", lambda: self._tool("clear_key"))
        row(grid, p, "Key colour", hbox(self.key_swatch, 4, self.key_info, "stretch"))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_pick, self.btn_clear_key), 0, wx.EXPAND)
        self.btn_grid = small_button(p, "Grid slice…", "Cut the image into equal tiles", lambda: self._tool("grid"))
        self.btn_detect = small_button(p, "Detect…", "Detect sprites: one module per separate sprite on the sheet", lambda: self._tool("detect"))
        self.btn_auto = small_button(p, "Modularize…", "Auto modularize: cut this image's sprites into hardware-sized parts they share (with a preview)", lambda: self._tool("automod"))
        self.btn_optimize = small_button(p, "Optimize…", "Optimize sheet: repack the modules into a smaller sheet (Tools ▸ Optimize Sprite Sheet)", lambda: self._tool("optimize"))
        row(grid, p, "Cut", hbox(self.btn_grid, self.btn_detect))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_auto, self.btn_optimize), 0, wx.EXPAND)

        # --- Shapes (the pseudo sheet)
        self.shapes_panel, grid, _ = section(self, root, "Shapes")
        p = self.shapes_panel
        self.draw_type = wx.Choice(p, choices=[label for _key, label in ops.SHAPE_TYPES])
        self.draw_type.SetSelection(0)
        self.draw_colour = wx.ColourPickerCtrl(p, colour=wx.Colour(255, 255, 255))
        row(grid, p, "New shape", hbox(self.draw_type, self.draw_colour))
        info = dim_text(p, "Drag on the canvas to draw one. Shapes are drawn pixel-exact and need no image.")
        info.Wrap(240)
        grid.Add((0, 0))
        grid.Add(info, 0)

        # --- Module(s)
        self.module_panel, grid, self.module_title = section(self, root, "Module")
        p = self.module_panel
        self.name = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.name_label = row(grid, p, "Name", self.name)
        self.kind = wx.StaticText(p, label="")
        self.shape_type = wx.Choice(p, choices=[label for _key, label in ops.SHAPE_TYPES])
        self.shape_colour = wx.ColourPickerCtrl(p)
        self.kind_label = row(grid, p, "Kind", hbox(self.kind, self.shape_type, self.shape_colour))
        self.x = spin(p, tip="Left edge on the sheet")
        self.y = spin(p, tip="Top edge on the sheet")
        self.w = spin(p, 1, 9999, tip="Width in pixels")
        self.h = spin(p, 1, 9999, tip="Height in pixels")
        self.pos_label = row(grid, p, "Position", hbox(self.x, self.y))
        self.size_label = row(grid, p, "Size", hbox(self.w, self.h))
        self.px = spin(p, tip="Pivot from the module's left edge: the point that lands on a part's position")
        self.py = spin(p, tip="Pivot from the module's top edge")
        self.pivot_label = row(grid, p, "Pivot", hbox(self.px, self.py))
        self.preset_buttons: List[wx.Button] = []
        presets = wx.GridSizer(3, 3, 2, 2)
        for (label, fractions), glyph in zip(ops.PIVOT_PRESETS, PRESET_GLYPHS):
            btn = wx.Button(p, label=glyph, size=(30, 22), style=wx.BU_EXACTFIT)
            btn.SetToolTip(f"Pivot: {label.lower()}")
            btn.Bind(wx.EVT_BUTTON, lambda e, f=fractions: self.on_preset and self.on_preset(f))
            presets.Add(btn, 0)
            self.preset_buttons.append(btn)
        self.preset_info = dim_text(p)
        preset_row = wx.BoxSizer(wx.HORIZONTAL)
        preset_row.Add(presets, 0)
        preset_row.Add(self.preset_info, 1, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 8)
        self.preset_label = row(grid, p, "Presets", preset_row)
        self.rotated_info = dim_text(p, "Stored rotated on the sheet (packed); the pivot is for the module as used.")
        self.rotated_info.Wrap(220)
        grid.Add((0, 0))
        grid.Add(self.rotated_info, 0)

        # Shape parameters
        self.arc_start = wx.SpinCtrlDouble(p, min=-360, max=360, inc=15, size=(70, -1))
        self.arc_sweep = wx.SpinCtrlDouble(p, min=-360, max=360, inc=15, size=(70, -1))
        self.arc_label = row(grid, p, "Arc", hbox(self.arc_start, self.arc_sweep))
        self.arc_start.SetToolTip("Start angle (degrees, clockwise from 3 o'clock)")
        self.arc_sweep.SetToolTip("Sweep (degrees); 360 = full ellipse")
        self.point_spins: List[wx.SpinCtrlDouble] = []
        self.point_labels: List[wx.StaticText] = []
        for index in range(3):
            sx = wx.SpinCtrlDouble(p, min=0, max=100, inc=5, size=(70, -1))
            sy = wx.SpinCtrlDouble(p, min=0, max=100, inc=5, size=(70, -1))
            sx.SetToolTip("Across, in % of the width")
            sy.SetToolTip("Down, in % of the height")
            self.point_labels.append(row(grid, p, f"Point {index + 1}", hbox(sx, sy)))
            self.point_spins += [sx, sy]

        self.usage = dim_text(p)
        self.usage_label = row(grid, p, "Used by", self.usage)
        self.btn_show_usage = small_button(p, "Go to frame", "Open the first frame that uses this module in the Frames tab", lambda: self._tool("show_usage"))
        self.btn_new_frame = small_button(p, "New frame", "Create a frame that shows this module (pivot on the origin)", lambda: self._tool("new_frame"))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_show_usage, self.btn_new_frame), 0, wx.EXPAND)
        self.btn_trim = small_button(p, "Trim to content", "Shrink to the opaque pixels (the pivot stays on its pixel)", lambda: self._tool("trim"))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_trim), 0, wx.EXPAND)

        self.SetSizer(root)
        self._bind()
        self.show(None, None, [], None)

    # ------------------------------------------------------------------ events
    def _tool(self, name: str) -> None:
        if self.on_tool:
            self.on_tool(name)

    def _field(self, name: str, value: Any) -> None:
        if not self._updating and self.on_field:
            self.on_field(name, value)

    def _bind(self) -> None:
        self.name.Bind(wx.EVT_TEXT_ENTER, lambda e: self._field("name", self.name.GetValue()))
        self.name.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), self._commit_name()))
        for key, ctrl in (("x", self.x), ("y", self.y), ("w", self.w), ("h", self.h), ("px", self.px), ("py", self.py)):
            bind_spin(ctrl, lambda v, k=key: self._field(k, v))
        self.shape_type.Bind(wx.EVT_CHOICE, lambda e: self._field("shape", self._shape_types[self.shape_type.GetSelection()]))
        self.shape_colour.Bind(wx.EVT_COLOURPICKER_CHANGED, lambda e: self._field("color", _rgb(self.shape_colour.GetColour())))
        for ctrl in [self.arc_start, self.arc_sweep] + self.point_spins:
            ctrl.Bind(wx.EVT_SPINCTRLDOUBLE, lambda e: self._field("params", self._params()))
            ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: self._field("params", self._params()))
        self.draw_type.Bind(wx.EVT_CHOICE, lambda e: self._draw_changed())
        self.draw_colour.Bind(wx.EVT_COLOURPICKER_CHANGED, lambda e: self._draw_changed())

    def _commit_name(self) -> None:
        if len(self.modules) == 1 and self.name.GetValue().strip() and self.name.GetValue() != self.modules[0].name:
            self._field("name", self.name.GetValue())

    def _draw_changed(self) -> None:
        if self.on_draw_shape:
            self.on_draw_shape(*self.draw_shape())

    def draw_shape(self) -> Tuple[str, Tuple[int, int, int]]:
        return self._shape_types[max(0, self.draw_type.GetSelection())], _rgb(self.draw_colour.GetColour())

    def _params(self) -> List[float]:
        if len(self.modules) != 1:
            return []
        kind = self.modules[0].type
        if kind in ("MD_ARC", "MD_FILL_ARC"):
            return [float(self.arc_start.GetValue()), float(self.arc_sweep.GetValue())]
        values = [float(s.GetValue()) for s in self.point_spins]
        if kind in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
            return values[:6]
        if kind == "MD_LINE":
            return values[:4]
        return list(self.modules[0].params)

    # ------------------------------------------------------------------ fill
    def show(self, project: Optional[Project], sheet_key: Optional[str], modules: List[Module], asset: Optional[ImageAsset]) -> None:
        self.project = project
        self.modules = modules
        self._updating = True
        self.Freeze()
        try:
            has_sheet = sheet_key is not None and project is not None
            self.sheet_panel.Show(has_sheet and not modules and asset is not None)
            self.shapes_panel.Show(has_sheet and sheet_key == ops.SHAPES_KEY and not modules)
            self.module_panel.Show(bool(modules))
            if not has_sheet:
                self.hint.SetLabel("Add an image to the project (Images ▸ + Add) to start cutting modules.")
            elif sheet_key == ops.ORPHANS_KEY and not modules:
                self.hint.SetLabel("These modules belong to an image that is no longer in the project.")
            elif not modules and asset is not None:
                self.hint.SetLabel("Drag over a sprite to cut a module. Click to select, Cmd+drag to select several.")
            else:
                self.hint.SetLabel("")
            self.hint.Wrap(260)
            if asset is not None and not modules:
                self._fill_sheet(project, asset)
            if modules:
                self._fill_modules(project, modules)
        finally:
            self._updating = False
            self.Thaw()
        self.Layout()
        self.FitInside()

    def _fill_sheet(self, project: Project, asset: ImageAsset) -> None:
        missing = ops.image_missing(asset)
        self.file_name.SetLabel(_short(ops.image_label(asset), 30))
        self.file_name.SetToolTip(asset.file_path)
        count = len(ops.modules_of_sheet(project, asset.id))
        self.file_info.SetLabel("File not found" if missing else f"{asset.width} × {asset.height} px · {count} module{'s' if count != 1 else ''}")
        self.file_info.SetForegroundColour(wx.Colour(255, 140, 120) if missing else wx.Colour(150, 156, 170))
        self.btn_locate.Show(missing)
        self.btn_reload.Show(not missing)
        key = asset.transparent_color
        self.key_swatch.SetBackgroundColour(wx.Colour(*key) if key else wx.Colour(60, 60, 64))
        self.key_swatch.Refresh()
        self.key_info.SetLabel(f"#{key[0]:02X}{key[1]:02X}{key[2]:02X}" if key else "none")
        self.btn_clear_key.Enable(bool(key))
        for btn in (self.btn_pick, self.btn_grid, self.btn_detect, self.btn_auto):
            btn.Enable(not missing)

    def _fill_modules(self, project: Project, modules: List[Module]) -> None:
        single = modules[0] if len(modules) == 1 else None
        self.module_title.SetLabel("MODULE" if single else f"{len(modules)} MODULES")
        for widget in (self.name_label, self.name, self.kind_label, self.pos_label, self.x, self.y,
                       self.size_label, self.w, self.h, self.pivot_label, self.px, self.py,
                       self.btn_show_usage, self.btn_new_frame):
            widget.Show(single is not None)
        is_shape = single is not None and single.type != "MD_IMAGE"
        self.kind.Show(single is not None and not is_shape)
        self.shape_type.Show(is_shape)
        self.shape_colour.Show(is_shape)
        self.rotated_info.Show(single is not None and bool(getattr(single, "rotated", False)))
        self.btn_trim.Enable(any(m.type == "MD_IMAGE" for m in modules))
        parts, frames, entries = ops.usage(project, [m.id for m in modules])
        self.usage.SetLabel(ops.describe_usage(parts, frames, entries))
        self.usage.Wrap(190)
        if single is not None:
            if not self.name.HasFocus():
                self.name.ChangeValue(single.name)
            self.kind.SetLabel("Image region")
            if is_shape:
                self.shape_type.SetSelection(self._shape_types.index(single.type) if single.type in self._shape_types else 0)
                self.shape_colour.SetColour(wx.Colour(*single.color))
            x, y, w, h = single.rect
            set_spin(self.x, x)
            set_spin(self.y, y)
            set_spin(self.w, w)
            set_spin(self.h, h)
            set_spin(self.px, single.pivot[0])
            set_spin(self.py, single.pivot[1])
            self.btn_show_usage.Enable(parts > 0)
        preset = ops.matching_preset(single) if single is not None else None
        self.preset_info.SetLabel(preset or ("custom" if single is not None else "apply to all"))
        self._fill_shape_params(single)

    def _fill_shape_params(self, single: Optional[Module]) -> None:
        kind = single.type if single is not None else ""
        arc = kind in ("MD_ARC", "MD_FILL_ARC")
        points = 3 if kind in ("MD_TRIANGLE", "MD_FILL_TRIANGLE") else (2 if kind == "MD_LINE" else 0)
        self.arc_label.Show(arc)
        self.arc_start.Show(arc)
        self.arc_sweep.Show(arc)
        if arc and single is not None:
            params = list(single.params) + [0.0, 360.0][len(single.params):]
            self.arc_start.SetValue(float(params[0]))
            self.arc_sweep.SetValue(float(params[1]))
        values = ops.shape_points(single) if points and single is not None else []
        for index in range(3):
            shown = index < points
            self.point_labels[index].Show(shown)
            for spin_ctrl in self.point_spins[index * 2:index * 2 + 2]:
                spin_ctrl.Show(shown)
            if shown and len(values) >= index * 2 + 2:
                self.point_spins[index * 2].SetValue(values[index * 2])
                self.point_spins[index * 2 + 1].SetValue(values[index * 2 + 1])


def _rgb(colour: wx.Colour) -> Tuple[int, int, int]:
    return (colour.Red(), colour.Green(), colour.Blue())


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
