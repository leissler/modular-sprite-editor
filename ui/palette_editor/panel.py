"""Palettes tab: Palettes and palette swaps | one of a palette's images as it shows | the palette inspector.

A palette holds its colours in the console's slots, in the artist's order. A palette swap recolours without touching an
image (a guard in other clothes) and is chosen per draw like a mapping: above the tabs for every preview, per object on
the Timeline, per draw in the game. Colour cycles move a run of slots along while things play.
"""

from __future__ import annotations

import os
import time
from typing import List, Optional, Sequence

import wx

import palettes
from models import Palette, PaletteSwap, Project
from ui import app_services, first_steps
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.components.palette_swatches import draw_empty_slot
from ui.components.thumb_list import Browser, Row
from ui.dpi import px
from ui.palette_editor import ops
from ui.palette_editor.inspector import PaletteInspector
from ui.palette_editor.preview import PalettePreview

ORIGINAL = "__original__"  # the swap list's first row: the palettes as they are
FRAME_MS = 33  # the cycle preview's timer


class PaletteEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.palette_id: Optional[str] = None
        self.swap_id: Optional[str] = None
        self.slots: List[int] = []
        self.image_id: Optional[str] = None
        self.animate = True
        self.highlight = True
        self._fitted = False
        self.cycle_frame = 0.0
        self._last_tick = 0.0
        self._thumbs: dict = {}
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self.timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self._build_ui()
        self.set_project(project)

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        self.outer_split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        left = wx.Panel(self.outer_split)
        lsizer = wx.BoxSizer(wx.VERTICAL)
        self.palette_browser = Browser(left, "Palettes", row_h=44, thumb=36, reorder=True)
        self.palette_browser.search.Hide()
        self.palette_browser.add_button("+ New", "New palette (empty: put images into it in the Modules tab)", self.new_palette)
        self.palette_browser.add_button("Duplicate", "Duplicate the selected palette", self.duplicate_palette)
        self.palette_browser.add_button("Delete", "Delete the selected palette (its images go into the first one)",
                                        self.delete_palette)
        self.palette_browser.list.thumbnail = self._palette_thumb
        self.palette_browser.list.on_rename = self._rename_palette
        self.palette_browser.list.on_move = self._move_palette
        lsizer.Add(self.palette_browser, 3, wx.EXPAND)
        self.swap_browser = Browser(left, "Palette swaps", row_h=36, thumb=0, reorder=True)
        self.swap_browser.search.Hide()
        self.swap_browser.add_button("+ New", "New palette swap (changes nothing until you recolour slots)", self.new_swap)
        self.swap_browser.add_button("Duplicate", "Duplicate the selected swap", self.duplicate_swap)
        self.swap_browser.add_button("Delete", "Delete the selected swap (scene objects that use it inherit theirs)",
                                     self.delete_swap)
        self.swap_browser.list.on_rename = self._rename_swap_row
        self.swap_browser.list.on_move = self._move_swap
        info = wx.StaticText(self.swap_browser, label="A swap recolours without touching an image. Choose it for "
                                                      "every preview above the tabs, or per object on the Timeline.")
        info.SetForegroundColour(wx.Colour(150, 156, 170))
        info.Wrap(px(220))
        self.swap_browser.sizer.Add(info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        lsizer.Add(self.swap_browser, 2, wx.EXPAND)
        left.SetSizer(lsizer)

        self.inner_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        centre = wx.Panel(self.inner_split)
        csizer = wx.BoxSizer(wx.VERTICAL)
        self.preview = PalettePreview(centre)
        self.preview.on_pick = self._picked
        self.canvas_controls = CanvasDisplayControls(centre, self.preview, view_key="palettes")
        self.image_choice = wx.Choice(self.canvas_controls)
        self.image_choice.SetToolTip("The palette's image to show")
        self.image_choice.Bind(wx.EVT_CHOICE, self._on_image_choice)
        self.canvas_controls.add_control(self.image_choice, "Image")
        self.chk_animate = self.canvas_controls.add_toggle("Cycles", True, self._set_animate,
                                                           "Let the colour cycles turn, at 60 video frames a second (50 with View ▸ Play at 50 Hz)")
        self.chk_highlight = self.canvas_controls.add_toggle("Highlight", True, self._set_highlight,
                                                             "Dim every pixel but those of the selected slots")
        self.hint = wx.StaticText(centre, label="")
        self.hint.SetForegroundColour(wx.Colour(150, 156, 170))
        csizer.Add(self.preview, 1, wx.EXPAND)
        csizer.Add(self.hint, 0, wx.ALL, 6)
        csizer.Add(self.canvas_controls, 0, wx.EXPAND)
        centre.SetSizer(csizer)
        self.inspector = PaletteInspector(self.inner_split)
        self.inspector.on_command = self._command
        self.inspector.on_rename_palette = lambda name: self._rename_palette(self.palette_id, name)
        self.inspector.on_rename_swap = lambda name: self._rename_swap(self.swap_id, name)
        self.inspector.on_cycle = self._cycle_changed
        self.inspector.grid.on_select = self._slots_selected
        self.inspector.grid.on_activate = self._edit_slot
        self.inspector.grid.on_move = self._move_slot
        self.inner_split.SplitVertically(centre, self.inspector, -px(310))
        self.inner_split.SetSashGravity(1.0)
        self.inner_split.SetMinimumPaneSize(px(200))
        self.outer_split.SplitVertically(left, self.inner_split, px(240))
        self.outer_split.SetMinimumPaneSize(px(180))
        root.Add(self.outer_split, 1, wx.EXPAND)
        self.SetSizer(root)
        self.palette_browser.list.Bind(wx.EVT_LISTBOX, lambda e: self._palette_chosen())
        self.swap_browser.list.Bind(wx.EVT_LISTBOX, lambda e: self._swap_chosen())
        self.palette_browser.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.palette_browser.list.begin_rename())
        self.swap_browser.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._begin_swap_rename())
        for lst, delete in ((self.palette_browser.list, self.delete_palette), (self.swap_browser.list, self.delete_swap)):
            lst.Bind(wx.EVT_KEY_DOWN, lambda e, d=delete, l=lst: self._list_key(e, d, l))

    # ================================================================== panel interface
    def set_project(self, project: Project) -> None:
        self.project = project
        self.palette_id = project.palettes[0].id if project.palettes else None
        self.swap_id = None
        self.slots = []
        self.image_id = None
        self.preview.forget()
        self._fitted = False
        self.refresh()

    def on_tab_activated(self) -> None:
        self.refresh()
        if not self._fitted:
            self._fitted = True
            wx.CallAfter(self._fit)

    def refresh_after_history(self) -> None:
        if self.project.get_palette(self.palette_id) is None:
            self.palette_id = self.project.palettes[0].id if self.project.palettes else None
        if self.swap_id and self.project.get_palette_swap(self.swap_id) is None:
            self.swap_id = None
        self._thumbs.clear()
        self.preview.forget()
        self.refresh()

    def get_active_canvas(self):
        return self.preview

    def on_active_mapping_changed(self) -> None:
        self.refresh()

    def stop_playback(self) -> None:
        self.timer.Stop()

    def edit_copy(self) -> None:
        pass

    def edit_cut(self) -> None:
        pass

    def edit_paste(self) -> None:
        pass

    def edit_duplicate(self) -> None:
        self.duplicate_swap() if self.swap_id else self.duplicate_palette()

    def edit_select_all(self) -> None:
        palette = self.palette()
        if palette is not None:
            self._slots_selected(list(range(len(palettes.colours_of(self.project, palette)))))

    def select_palette(self, palette_id: str) -> None:
        if self.project.get_palette(palette_id) is not None:
            self.palette_id = palette_id
            self.slots = []
            self.image_id = None
            self.refresh()

    def select_swap(self, swap_id: Optional[str]) -> None:
        self.swap_id = swap_id if swap_id and self.project.get_palette_swap(swap_id) else None
        self.refresh()

    # ================================================================== state
    def palette(self) -> Optional[Palette]:
        return self.project.get_palette(self.palette_id)

    def swap(self) -> Optional[PaletteSwap]:
        return self.project.get_palette_swap(self.swap_id) if self.swap_id else None

    def _images(self) -> List:
        palette = self.palette()
        return palettes.palette_images(self.project, palette) if palette else []

    def refresh(self) -> None:
        palette, swap = self.palette(), self.swap()
        rows = []
        for p in self.project.palettes:
            images = len(palettes.palette_images(self.project, p))
            colours = len(palettes.colours_of(self.project, p))
            lacking = len(palettes.missing_colours(self.project, p))
            rows.append(Row(p.id, p.name, f"{images} image{'s' if images != 1 else ''} · {colours} of "
                                          f"{palettes.capacity(self.project)}" + (f" · {lacking} missing" if lacking else ""),
                            warn=bool(lacking)))
        self._thumbs.clear()
        self.palette_browser.list.set_rows(rows, [self.palette_id] if self.palette_id else [])
        preview_swap = self.project.active_palette_swap
        swap_rows = [Row(ORIGINAL, "Original", "the palettes as they are", badge="●" if preview_swap is None else "")]
        for s in self.project.palette_swaps:
            changed = [p.name for p in self.project.palettes if p.id in s.palettes]
            swap_rows.append(Row(s.id, s.name, ("changes " + ", ".join(changed)) if changed else "changes nothing yet",
                                 dim=not changed, badge="●" if preview_swap is s else ""))
        self.swap_browser.list.set_rows(swap_rows, [self.swap_id or ORIGINAL])
        images = self._images()
        if self.image_id not in [a.id for a in images]:
            self.image_id = images[0].id if images else None
        self.image_choice.Set([os.path.basename(a.file_path) or a.id for a in images] or ["(no image)"])
        self.image_choice.SetSelection(max(0, [a.id for a in images].index(self.image_id)) if self.image_id else 0)
        self.image_choice.Enable(len(images) > 1)
        self.inspector.show(self.project, palette, swap, self.slots, self.inspector.selected_cycle())
        self._update_preview()
        self._update_timer()
        needs = first_steps.palettes(self.project)
        if needs:
            self.hint.SetLabel(needs)
        elif palette is not None and not images:
            self.hint.SetLabel("No image uses this palette: choose it as an image's Palette in the Modules tab.")
        else:
            self.hint.SetLabel("Click a pixel to select its slot. Shift+click slots to select a run for a colour cycle.")

    def _update_preview(self) -> None:
        asset = self.project.get_image(self.image_id) if self.image_id else None
        frame = self.cycle_frame if self.animate else None
        self.preview.show(self.project, asset, self.swap(), frame, self.slots if self.highlight else [])

    def _has_cycles(self) -> bool:
        palette = self.palette()
        return palette is not None and bool(palettes.cycles_of(palette, self.swap()))

    def _update_timer(self) -> None:
        running = self.animate and self._has_cycles() and self.IsShownOnScreen()
        if running and not self.timer.IsRunning():
            self._last_tick = time.monotonic()
            self.timer.Start(FRAME_MS)
        elif not running and self.timer.IsRunning():
            self.timer.Stop()

    def _on_timer(self, _event: wx.TimerEvent) -> None:
        if not self or not self.IsShownOnScreen():
            self.timer.Stop()
            return
        now = time.monotonic()
        self.cycle_frame += (now - self._last_tick) * 60.0  # video frames
        self._last_tick = now
        self._update_preview()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self.timer.Stop()
        event.Skip()

    def _set_highlight(self, on: bool) -> None:
        self.highlight = on
        self._update_preview()

    def _set_animate(self, on: bool) -> None:
        self.animate = on
        self._update_preview()
        self._update_timer()

    # ================================================================== lists
    def _palette_thumb(self, palette_id: str, size: int) -> Optional[wx.Bitmap]:
        palette = self.project.get_palette(palette_id)
        if palette is None:
            return None
        key = (palette_id, size, tuple(palettes.colours_of(self.project, palette)))
        found = self._thumbs.get(key)
        if found is not None:
            return found
        capacity = palettes.capacity(self.project)
        side = 1
        while side * side < capacity + 1:
            side += 1
        cell = max(2, size // side)
        bmp = wx.Bitmap(size, size)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(36, 37, 40)))
        dc.Clear()
        spec = palettes.hardware(self.project)
        colours = palettes.colours_of(self.project, palette)
        for index in range(1, capacity + 1):
            row, col = divmod(index, side)
            x, y = col * cell, row * cell
            if index - 1 < len(colours):
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.SetBrush(wx.Brush(wx.Colour(*palettes.console_colour(spec, colours[index - 1]))))
                dc.DrawRectangle(x, y, cell, cell)
            else:
                draw_empty_slot(dc, x, y, cell)
        dc.SelectObject(wx.NullBitmap)
        self._thumbs[key] = bmp
        return bmp

    def _palette_chosen(self) -> None:
        ids = self.palette_browser.list.selected_ids()
        if ids and ids[0] != self.palette_id:
            self.palette_id = ids[0]
            self.slots = []
            self.image_id = None
            self.refresh()
            wx.CallAfter(self._fit)

    def _swap_chosen(self) -> None:
        ids = self.swap_browser.list.selected_ids()
        chosen = None if not ids or ids[0] == ORIGINAL else ids[0]
        if chosen != self.swap_id:
            self.swap_id = chosen
            self.refresh()

    def _fit(self) -> None:
        if not self:
            return
        self.preview.fit_to_content()

    def _begin_swap_rename(self) -> None:
        if self.swap_id:
            self.swap_browser.list.begin_rename(self.swap_id)

    def _list_key(self, event: wx.KeyEvent, delete, lst) -> None:
        if lst.is_renaming():
            event.Skip()
            return
        key = event.GetKeyCode()
        if key in (wx.WXK_DELETE, wx.WXK_BACK) and not app_services.text_entry_has_focus():
            delete()
        elif key == wx.WXK_F2:
            lst.begin_rename()
        else:
            event.Skip()

    def _done(self, message: str = "") -> None:
        """An edit happened: one undo step, everything shows it."""
        app_services.request_checkpoint()
        self.refresh()
        if message:
            app_services.show_status(message)

    # ---- palettes
    def new_palette(self) -> None:
        palette = ops.new_palette(self.project)
        self.palette_id = palette.id
        self.slots = []
        self._done(f"New palette '{palette.name}': choose it as an image's Palette in the Modules tab")

    def duplicate_palette(self) -> None:
        palette = self.palette()
        if palette is not None:
            copied = ops.duplicate_palette(self.project, palette)
            self.palette_id = copied.id
            self._done(f"Duplicated as '{copied.name}'")

    def delete_palette(self) -> None:
        palette = self.palette()
        if palette is None:
            return
        if len(self.project.palettes) <= 1:
            app_services.show_status("A project keeps at least one palette")
            return
        images, swaps = ops.palette_uses(self.project, palette)
        if images or swaps:
            first = next(p for p in self.project.palettes if p is not palette)
            parts = ([f"its {images} image{'s' if images != 1 else ''} go into '{first.name}'"] if images else []) + \
                    ([f"{swaps} palette swap{'s' if swaps != 1 else ''} forget what they change in it"] if swaps else [])
            if wx.MessageBox(f"Delete the palette '{palette.name}'? " + " and ".join(parts) + ".", "Delete Palette",
                             wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
                return
        target = ops.delete_palette(self.project, palette)
        self.palette_id = target.id if target else None
        self.slots = []
        self._done(f"Deleted '{palette.name}'")

    def _rename_palette(self, palette_id: Optional[str], name: str) -> None:
        palette = self.project.get_palette(palette_id)
        if palette is not None and name.strip() and name.strip() != palette.name:
            palette.name = name.strip()
            self._done()

    def _move_palette(self, palette_id: str, before_id: Optional[str]) -> None:
        ops.move_palette(self.project, palette_id, before_id)
        self._done("The palettes' order is the order the export loads them in")

    # ---- swaps
    def new_swap(self) -> None:
        swap = ops.new_swap(self.project)
        self.swap_id = swap.id
        self._done(f"New palette swap '{swap.name}': select a slot (or click a pixel) and choose Change…")

    def duplicate_swap(self) -> None:
        swap = self.swap()
        if swap is not None:
            copied = ops.duplicate_swap(self.project, swap)
            self.swap_id = copied.id
            self._done(f"Duplicated as '{copied.name}'")

    def delete_swap(self) -> None:
        swap = self.swap()
        if swap is None:
            return
        uses = ops.swap_uses(self.project, swap)
        if uses and wx.MessageBox(f"Delete the palette swap '{swap.name}'? {uses} scene object(s) use it and will inherit "
                                  "theirs instead.", "Delete Palette Swap", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        preview = self.project.active_palette_swap is swap
        ops.delete_swap(self.project, swap)
        self.swap_id = None
        if preview:
            app_services.notify_active_palette_swap_changed()
        self._done(f"Deleted '{swap.name}'")

    def _rename_swap_row(self, row_id: str, name: str) -> None:
        if row_id != ORIGINAL:
            self._rename_swap(row_id, name)

    def _rename_swap(self, swap_id: Optional[str], name: str) -> None:
        swap = self.project.get_palette_swap(swap_id) if swap_id else None
        if swap is not None and name.strip() and name.strip() != swap.name:
            swap.name = name.strip()
            self._done()
            app_services.notify_active_palette_swap_changed()  # the choice above the tabs shows the name

    def _move_swap(self, swap_id: str, before_id: Optional[str]) -> None:
        if swap_id == ORIGINAL:
            return
        ops.move_swap(self.project, swap_id, None if before_id == ORIGINAL else before_id)
        self._done()

    # ================================================================== slots
    def _slots_selected(self, slots: Sequence[int]) -> None:
        self.slots = list(slots)
        self.inspector.show(self.project, self.palette(), self.swap(), self.slots, self.inspector.selected_cycle())
        self._update_preview()

    def _picked(self, slot: int) -> None:
        self._slots_selected([slot])

    def _pick_colour(self, initial) -> Optional[tuple]:
        data = wx.ColourData()
        data.SetChooseFull(True)
        if initial is not None:
            data.SetColour(wx.Colour(*initial))
        with wx.ColourDialog(self, data) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            colour = dlg.GetColourData().GetColour()
        return (colour.Red(), colour.Green(), colour.Blue())

    def _edit_slot(self, slot: int) -> None:
        palette, swap = self.palette(), self.swap()
        if palette is None:
            return
        colours = palettes.colours_of(self.project, palette)
        if slot >= len(colours):
            return
        if swap is None and slot in ops.art_slots(self.project, palette):
            app_services.show_status("The images have this colour: select a palette swap to recolour it")
            return
        current = (ops.replacement(swap, palette, slot) if swap else None) or colours[slot]
        picked = self._pick_colour(current)
        if picked is None:
            return
        if swap is not None:
            ops.set_replacement(self.project, swap, palette, slot, picked)
            self._swap_edited()
            self._done(f"'{swap.name}' shows slot {slot + 1} as #{picked[0]:02X}{picked[1]:02X}{picked[2]:02X} "
                       "(as the console shows it)")
        elif ops.set_colour(self.project, palette, slot, picked):
            self._done(f"Slot {slot + 1} changed")

    def _move_slot(self, slot: int, target: int) -> None:
        palette = self.palette()
        if palette is None or self.swap() is not None:
            return
        order = list(range(len(palettes.colours_of(self.project, palette))))
        order.insert(target, order.pop(slot))
        if palette.colours is None:
            palette.colours = palettes.colours_of(self.project, palette)
        dropped = palettes.reorder(self.project, palette, order)
        self.slots = [target]
        self._done(f"Moved slot {slot + 1} to {target + 1}" + (f"; {dropped} colour cycle(s) split apart and removed"
                                                                 if dropped else ""))

    def _swap_edited(self) -> None:
        """A swap that previews everywhere changed: every canvas draws it again."""
        if self.swap() is not None and self.project.active_palette_swap is self.swap():
            app_services.notify_active_palette_swap_changed()

    # ================================================================== inspector commands
    def _command(self, name: str) -> None:
        palette, swap = self.palette(), self.swap()
        if palette is None:
            return
        if palette.colours is None:  # the first edit stores the colours the palette had from its images
            palette.colours = palettes.colours_of(self.project, palette)
        if name == "add_colour":
            picked = self._pick_colour(None)
            if picked is not None:
                slot = ops.add_colour(self.project, palette, picked)
                if slot is not None:
                    self.slots = [slot]
                    self._done(f"Added slot {slot + 1}")
        elif name == "change" and len(self.slots) == 1:
            self._edit_slot(self.slots[0])
        elif name == "original" and swap is not None:
            for slot in self.slots:
                ops.set_replacement(self.project, swap, palette, slot, None)
            self._swap_edited()
            self._done("Original colours again")
        elif name == "remove_slots":
            palettes.remove_slots(self.project, palette, self.slots)
            self.slots = []
            self._done("Removed")
        elif name == "add_missing":
            added = palettes.add_missing_colours(self.project, palette)
            self._done(f"{added} colour(s) went into free slots")
        elif name == "remove_unused":
            unused = palettes.unused_slots(self.project, palette)
            dropped = palettes.remove_slots(self.project, palette, unused)
            self.slots = []
            self._done(f"Removed {len(unused)} unused slot(s)" + (f"; {dropped} colour cycle(s) went with them" if dropped else ""))
        elif name.startswith("sort:"):
            dropped = palettes.reorder(self.project, palette, palettes.sort_order(self.project, palette, name[5:]))
            self.slots = []
            self._done("Sorted" + (f"; {dropped} colour cycle(s) split apart and removed" if dropped else ""))
        elif name == "add_cycle":
            cycle = ops.add_cycle(self.project, swap, palette, self.slots)
            if cycle is not None:
                self._swap_edited()
                self._done(f"Colour cycle over slots {cycle.first}–{cycle.first + cycle.count - 1}")
        elif name == "remove_cycle":
            ops.remove_cycle(swap, palette, self.inspector.selected_cycle())
            self._swap_edited()
            self._done("Colour cycle removed")
        elif name.startswith("own_cycles:") and swap is not None:
            if name.endswith("1"):
                ops.cycles_owner(swap, palette)
            else:
                ops.follow_palette_cycles(swap, palette)
            self._swap_edited()
            self._done()
        elif name.startswith("preview:") and swap is not None:
            self.project.active_palette_swap = swap if name.endswith("1") else None
            app_services.notify_active_palette_swap_changed()
            self.refresh()
        elif name == "reset_swap" and swap is not None:
            swap.palettes.pop(palette.id, None)
            self._swap_edited()
            self._done(f"'{swap.name}' leaves '{palette.name}' as it is")

    def _cycle_changed(self, index: int, frames: int, reverse: bool) -> None:
        palette, swap = self.palette(), self.swap()
        if palette is None:
            return
        cycles = ops.cycles_owner(swap, palette)
        if 0 <= index < len(cycles):
            cycles[index].frames = max(1, int(frames))
            cycles[index].reverse = bool(reverse)
            self._swap_edited()
            self._done()

    def _on_image_choice(self, _event: wx.CommandEvent) -> None:
        images = self._images()
        index = self.image_choice.GetSelection()
        if 0 <= index < len(images):
            self.image_id = images[index].id
            self._update_preview()
            wx.CallAfter(self._fit)
