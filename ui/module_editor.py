"""Module editor panel for managing images and modules."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Callable, Optional, Tuple

import wx

from models import ImageAsset, Module, Project, generate_id


class ModuleCanvas(wx.Panel):
    """Top-left origin canvas for selecting module rects and pivots."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.bitmap: Optional[wx.Bitmap] = None
        self.image_size: Tuple[int, int] = (0, 0)
        self.selection: Optional[Tuple[int, int, int, int]] = None
        self.pivot: Optional[Tuple[int, int]] = None
        self.zoom: float = 1.0
        self.pan: Tuple[float, float] = (0.0, 0.0)  # screen center equals world (0,0)
        self.transparent_view: bool = True
        self.selection_style: str = "active"  # "active" (filled) or "module" (outline only)
        self.module_overlays: list[Tuple[Tuple[int, int, int, int], bool, str]] = []  # (rect, is_selected, id)
        self._selecting = False
        self._panning = False
        self._panning_alt = False
        self._pivot_drag = False
        self._hover_pivot = False
        self._last_clamp_time: float = 0.0
        self._last_clamp_dir: int = 0  # 1 for max, -1 for min
        self.show_grid: bool = True
        self.grid_spacing: Tuple[int, int] = (32, 32)
        self.transparent_view: bool = True
        self.pick_mode: bool = False
        self.on_pick_color: Optional[Callable[[Tuple[float, float]], None]] = None
        self.on_module_clicked: Optional[Callable[[str], None]] = None
        self.on_module_clicked: Optional[Callable[[str], None]] = None
        self._start = wx.Point()
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_right_down)
        self.Bind(wx.EVT_MIDDLE_DOWN, self.on_pan_start)
        self.Bind(wx.EVT_MIDDLE_UP, self.on_pan_end)
        self.Bind(wx.EVT_MOTION, self.on_mouse_move)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mousewheel)
        self.on_selection_changed: Optional[Callable[[Optional[Tuple[int, int, int, int]]], None]] = None
        self.on_pivot_changed: Optional[Callable[[Optional[Tuple[int, int]]], None]] = None

    # Transform helpers
    def world_to_screen(self, pt: Tuple[float, float]) -> Tuple[float, float]:
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        return (cx + (pt[0] + self.pan[0]) * self.zoom, cy + (pt[1] + self.pan[1]) * self.zoom)

    def screen_to_world(self, pt: wx.Point) -> Tuple[float, float]:
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        return (
            (pt.x - cx) / self.zoom - self.pan[0],
            (pt.y - cy) / self.zoom - self.pan[1],
        )

    def set_bitmap(self, bmp: Optional[wx.Bitmap], size: Tuple[int, int]) -> None:
        self.bitmap = bmp
        self.image_size = size
        self.selection = None
        self.pivot = None
        self.Refresh(False)

    def set_selection_style(self, style: str) -> None:
        self.selection_style = style

    def set_module_overlays(
        self, overlays: list[Tuple[Tuple[int, int, int, int], bool, str]]
    ) -> None:
        self.module_overlays = overlays
        self.Refresh(False)

    def set_view_state(self, pan: Tuple[float, float], zoom: float) -> None:
        self.pan = pan
        self.zoom = zoom
        self.Refresh(False)

    def get_view_state(self) -> Tuple[Tuple[float, float], float]:
        return (self.pan, self.zoom)

    def set_grid_spacing(self, spacing: Tuple[int, int]) -> None:
        self.grid_spacing = spacing
        self.Refresh(False)

    def set_show_grid(self, show: bool) -> None:
        self.show_grid = show
        self.Refresh(False)

    # Events
    def on_mousewheel(self, event: wx.MouseEvent) -> None:
        rotation = event.GetWheelRotation()
        factor = 1.1 if rotation > 0 else 0.9
        now = time.monotonic()
        max_zoom = 16.0
        min_zoom = 0.2
        # Ignore if already clamped and trying to go further, and swallow quick bounce-back
        if rotation > 0 and self.zoom >= max_zoom - 1e-5:
            self._last_clamp_time = now
            self._last_clamp_dir = 1
            return
        if rotation < 0 and self.zoom <= min_zoom + 1e-5:
            self._last_clamp_time = now
            self._last_clamp_dir = -1
            return
        if self._last_clamp_dir == 1 and rotation < 0 and (now - self._last_clamp_time) < 0.2:
            return
        if self._last_clamp_dir == -1 and rotation > 0 and (now - self._last_clamp_time) < 0.2:
            return

        old_zoom = self.zoom
        new_zoom = max(min_zoom, min(max_zoom, self.zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-6:
            return
        mouse_pos = event.GetPosition()
        world_before = self.screen_to_world(mouse_pos)
        self.zoom = new_zoom
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        self.pan = (
            (mouse_pos.x - cx) / new_zoom - world_before[0],
            (mouse_pos.y - cy) / new_zoom - world_before[1],
        )
        if self.zoom >= max_zoom - 1e-5 and rotation > 0:
            self._last_clamp_time = now
            self._last_clamp_dir = 1
        elif self.zoom <= min_zoom + 1e-5 and rotation < 0:
            self._last_clamp_time = now
            self._last_clamp_dir = -1
        else:
            self._last_clamp_dir = 0
        self.Refresh(False)

    def on_left_down(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        world = self.screen_to_world(pos)
        if self.pick_mode and self.on_pick_color:
            self.on_pick_color(world)
            return
        if event.AltDown():
            self.on_pan_start(event)
            self._panning_alt = True
            return
        # Hit-test module overlays first
        hit = self._hit_module_overlay(world) if not event.AltDown() else None
        if hit:
            hit_id, hit_selected = hit
            # If clicked on the current selection, move pivot
            if hit_selected and self.selection:
                self.pivot = (int(world[0]), int(world[1]))
                if self.on_pivot_changed:
                    self.on_pivot_changed(self.pivot)
                self.Refresh(False)
                return
            # Otherwise select the clicked module
            if self.on_module_clicked:
                self.on_module_clicked(hit_id)
                return
        # Move pivot if a module is already selected and we didn't click another module
        if self.selection and not hit:
            self.pivot = (int(world[0]), int(world[1]))
            if self.on_pivot_changed:
                self.on_pivot_changed(self.pivot)
            self.Refresh(False)
            return
        if self._is_over_pivot(world):
            self._pivot_drag = True
        else:
            self._selecting = True
            self.selection_style = "active"
            self.selection = (int(world[0]), int(world[1]), 0, 0)
        self._start = pos
        self.CaptureMouse()

    def on_left_up(self, _: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        if self._selecting and self.selection:
            # Normalize selection
            x, y, w, h = self.selection
            if w < 0:
                x += w
                w = -w
            if h < 0:
                y += h
                h = -h
            self.selection = (int(x), int(y), int(w), int(h))
            if self.selection_style == "active":
                # Reset pivot to selection center for new cuts
                self.pivot = (int(x + w // 2), int(y + h // 2))
            if self.on_selection_changed:
                self.on_selection_changed(self.selection)
        self._selecting = False
        self._pivot_drag = False
        self._panning_alt = False
        self._panning = False
        self.Refresh(False)

    def on_right_down(self, event: wx.MouseEvent) -> None:
        world = self.screen_to_world(event.GetPosition())
        self.pivot = (int(world[0]), int(world[1]))
        if self.on_pivot_changed:
            self.on_pivot_changed(self.pivot)
        self.Refresh(False)

    def on_pan_start(self, event: wx.MouseEvent) -> None:
        self._panning = True
        self._start = event.GetPosition()
        self.CaptureMouse()

    def on_pan_end(self, _: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._panning = False

    def on_mouse_move(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        world = self.screen_to_world(pos)
        hovering = self._is_over_pivot(world)
        if hovering != self._hover_pivot and not self.pick_mode:
            self._hover_pivot = hovering
            self.SetCursor(wx.Cursor(wx.CURSOR_CROSS if hovering else wx.CURSOR_DEFAULT))
        if self.pick_mode:
            self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        if self._panning and event.Dragging():
            dx = (pos.x - self._start.x) / self.zoom
            dy = (pos.y - self._start.y) / self.zoom
            self.pan = (self.pan[0] + dx, self.pan[1] + dy)
            self._start = pos
            self.Refresh(False)
        elif self._selecting and self.selection and event.Dragging():
            x, y, _, _ = self.selection
            w = world[0] - x
            h = world[1] - y
            self.selection = (int(x), int(y), int(w), int(h))
            self.Refresh(False)
        elif self._pivot_drag and self.pivot is not None and event.Dragging():
            self.pivot = (int(world[0]), int(world[1]))
            if self.on_pivot_changed:
                self.on_pivot_changed(self.pivot)
            self.Refresh(False)

    # Drawing
    def on_paint(self, _: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        if self.transparent_view:
            self._draw_checkerboard(dc)
        gc = wx.GraphicsContext.Create(dc)
        if hasattr(gc, "SetAntialiasMode"):
            gc.SetAntialiasMode(wx.ANTIALIAS_NONE)
        if hasattr(gc, "SetInterpolationQuality"):
            gc.SetInterpolationQuality(wx.INTERPOLATION_NONE)
        if self.bitmap:
            sx, sy = self.world_to_screen((0, 0))
            w = self.bitmap.GetWidth() * self.zoom
            h = self.bitmap.GetHeight() * self.zoom
            gc.DrawBitmap(self.bitmap, sx, sy, w, h)
        self._draw_grid(gc)
        if self.selection:
            x, y, w, h = self.selection
            if w < 0:
                x += w
                w = -w
            if h < 0:
                y += h
                h = -h
            sx0, sy0 = self.world_to_screen((x, y))
            if self.selection_style == "active":
                gc.SetPen(wx.Pen(wx.Colour(40, 120, 200), width=2))
                gc.SetBrush(wx.Brush(wx.Colour(40, 120, 200, 40)))
                gc.DrawRectangle(sx0, sy0, w * self.zoom, h * self.zoom)
            else:
                # Dashed colorful outline for selected module
                pen = wx.Pen(wx.Colour(40, 200, 240), width=2, style=wx.PENSTYLE_SHORT_DASH)
                gc.SetPen(pen)
                gc.SetBrush(wx.TRANSPARENT_BRUSH)
                gc.DrawRectangle(sx0, sy0, w * self.zoom, h * self.zoom)
        # Module overlays (unselected)
        if self.module_overlays:
            pen_unselected = wx.Pen(wx.Colour(80, 170, 220, 90), width=1, style=wx.PENSTYLE_SHORT_DASH)
            for rect, is_sel, _mid in self.module_overlays:
                if is_sel:
                    # Selected module is already highlighted separately; skip overlay here
                    continue
                x, y, w, h = rect
                sx0, sy0 = self.world_to_screen((x, y))
                gc.SetBrush(wx.TRANSPARENT_BRUSH)
                gc.SetPen(pen_unselected)
                gc.DrawRectangle(sx0, sy0, w * self.zoom, h * self.zoom)
        if self.pivot and self.selection:
            sx, sy = self.world_to_screen(self.pivot)
            color = wx.Colour(240, 80, 80) if self._pivot_drag or self._hover_pivot else wx.Colour(200, 60, 60)
            gc.SetPen(wx.Pen(color, width=2))
            gc.StrokeLine(sx - 8, sy, sx + 8, sy)
            gc.StrokeLine(sx, sy - 8, sx, sy + 8)
            gc.SetPen(wx.Pen(color.ChangeLightness(130), width=1))
            gc.DrawEllipse(sx - 4, sy - 4, 8, 8)

    def _hit_module_overlay(self, world: Tuple[float, float]) -> Optional[Tuple[str, bool]]:
        for rect, is_sel, mid in reversed(self.module_overlays):
            x, y, w, h = rect
            if x <= world[0] <= x + w and y <= world[1] <= y + h:
                return (mid, is_sel)
        return None
        if self.pivot and self.selection:
            sx, sy = self.world_to_screen(self.pivot)
            color = wx.Colour(240, 80, 80) if self._pivot_drag or self._hover_pivot else wx.Colour(200, 60, 60)
            gc.SetPen(wx.Pen(color, width=2))
            gc.StrokeLine(sx - 8, sy, sx + 8, sy)
            gc.StrokeLine(sx, sy - 8, sx, sy + 8)
            gc.SetPen(wx.Pen(color.ChangeLightness(130), width=1))
            gc.DrawEllipse(sx - 4, sy - 4, 8, 8)

    def _draw_grid(self, gc: wx.GraphicsContext) -> None:
        # Infinite grid in center-origin space
        size = self.GetClientSize()
        left_world, top_world = self.screen_to_world(wx.Point(0, 0))
        right_world, bottom_world = self.screen_to_world(wx.Point(size.width, size.height))
        spacing_x, spacing_y = self.grid_spacing

        if self.show_grid:
            grid_pen = wx.Pen(wx.Colour(80, 80, 80), width=1, style=wx.PENSTYLE_SOLID)
            gc.SetPen(grid_pen)
            start_x = int((left_world // spacing_x) * spacing_x)
            start_y = int((top_world // spacing_y) * spacing_y)
            x = start_x
            while x <= right_world + spacing_x:
                sx, _ = self.world_to_screen((x, 0))
                gc.StrokeLine(round(sx), 0, round(sx), size.height)
                x += spacing_x
            y = start_y
            while y <= bottom_world + spacing_y:
                _, sy = self.world_to_screen((0, y))
                gc.StrokeLine(0, round(sy), size.width, round(sy))
                y += spacing_y

        # Origin axes
        axis_pen = wx.Pen(wx.Colour(150, 150, 180), width=2)
        gc.SetPen(axis_pen)
        cx, cy = self.world_to_screen((0, 0))
        gc.StrokeLine(0, round(cy), size.width, round(cy))
        gc.StrokeLine(round(cx), 0, round(cx), size.height)

        # If an image is loaded, outline its bounds for context
        if self.bitmap:
            max_x, max_y = self.image_size
            outline_pen = wx.Pen(wx.Colour(190, 190, 190), width=1)
            gc.SetPen(outline_pen)
            x0, y0 = self.world_to_screen((0, 0))
            x1, y1 = self.world_to_screen((max_x, max_y))
            gc.StrokeLine(round(x0), round(y0), round(x1), round(y0))
            gc.StrokeLine(round(x0), round(y1), round(x1), round(y1))
            gc.StrokeLine(round(x0), round(y0), round(x0), round(y1))
            gc.StrokeLine(round(x1), round(y0), round(x1), round(y1))

    def _draw_checkerboard(self, dc: wx.DC) -> None:
        size = self.GetClientSize()
        step = 8
        c1 = wx.Colour(60, 60, 60)
        c2 = wx.Colour(80, 80, 80)
        for y in range(0, size.height, step):
            for x in range(0, size.width, step):
                dc.SetBrush(wx.Brush(c1 if (x // step + y // step) % 2 == 0 else c2))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawRectangle(x, y, step, step)

    def set_transparent_view(self, enable: bool) -> None:
        self.transparent_view = enable
        self.Refresh(False)

    def _is_over_pivot(self, world: Tuple[float, float]) -> bool:
        if not self.pivot:
            return False
        px, py = self.pivot
        return abs(world[0] - px) < 6 and abs(world[1] - py) < 6


class ModuleEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_image_id: Optional[str] = None
        self.selected_module_id: Optional[str] = None
        self._bitmap_cache: dict[str, wx.Bitmap] = {}
        self._modules_view: list[Module] = []

        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sidebar = wx.BoxSizer(wx.VERTICAL)
        canvas_sizer = wx.BoxSizer(wx.VERTICAL)

        # Images
        img_box = wx.StaticBox(self, label="Images")
        img_sizer = wx.StaticBoxSizer(img_box, wx.VERTICAL)
        self.image_list = wx.ListBox(img_box)
        img_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_import = wx.Button(img_box, label="Import Image")
        self.btn_remove_img = wx.Button(img_box, label="Remove")
        img_btns.Add(self.btn_import, 1, wx.RIGHT, 4)
        img_btns.Add(self.btn_remove_img, 0)
        img_sizer.Add(self.image_list, 1, wx.EXPAND | wx.ALL, 4)
        img_sizer.Add(img_btns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        # Transparency controls
        trans_row = wx.BoxSizer(wx.HORIZONTAL)
        self.trans_swatch = wx.Panel(img_box, size=(24, 18))
        self.trans_swatch.SetBackgroundColour(wx.Colour(0, 0, 0))
        self.chk_trans_view = wx.CheckBox(img_box, label="Transparent view")
        self.chk_trans_view.SetValue(True)
        self.btn_pick_from_image = wx.Button(img_box, label="Pick from image")
        trans_row.Add(self.btn_pick_from_image, 1, wx.RIGHT, 6)
        trans_row.Add(self.trans_swatch, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
        trans_row.Add(self.chk_trans_view, 0, wx.ALIGN_CENTER_VERTICAL)
        img_sizer.Add(trans_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        # Modules
        mod_box = wx.StaticBox(self, label="Modules")
        mod_sizer = wx.StaticBoxSizer(mod_box, wx.VERTICAL)
        self.module_list = wx.ListCtrl(mod_box, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.module_list.InsertColumn(0, "Name", width=120)
        self.module_list.InsertColumn(1, "Rect", width=120)
        self.module_list.InsertColumn(2, "Pivot", width=90)
        mod_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_create_module = wx.Button(mod_box, label="Create from selection")
        self.btn_update_module = wx.Button(mod_box, label="Update module")
        mod_btns.Add(self.btn_create_module, 1, wx.RIGHT, 4)
        mod_btns.Add(self.btn_update_module, 1)
        mod_edit_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_rename_module = wx.Button(mod_box, label="Rename")
        self.btn_delete_module = wx.Button(mod_box, label="Delete")
        mod_edit_btns.Add(self.btn_rename_module, 1, wx.RIGHT, 4)
        mod_edit_btns.Add(self.btn_delete_module, 1)
        mod_sizer.Add(self.module_list, 1, wx.EXPAND | wx.ALL, 4)
        mod_sizer.Add(mod_btns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        mod_sizer.Add(mod_edit_btns, 0, wx.EXPAND | wx.ALL, 4)

        # Grid slicing controls
        slice_box = wx.StaticBox(self, label="Grid Slice")
        slice_sizer = wx.StaticBoxSizer(slice_box, wx.VERTICAL)
        grid = wx.FlexGridSizer(rows=0, cols=2, vgap=4, hgap=4)
        grid.Add(wx.StaticText(slice_box, label="Tile Width"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tile_w = wx.SpinCtrl(slice_box, min=1, max=4096, initial=32)
        grid.Add(self.tile_w, 1, wx.EXPAND)
        grid.Add(wx.StaticText(slice_box, label="Tile Height"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tile_h = wx.SpinCtrl(slice_box, min=1, max=4096, initial=32)
        grid.Add(self.tile_h, 1, wx.EXPAND)
        slice_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 4)
        self.btn_slice = wx.Button(slice_box, label="Slice Image")
        slice_sizer.Add(self.btn_slice, 0, wx.EXPAND | wx.ALL, 4)

        sidebar.Add(img_sizer, 1, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(mod_sizer, 2, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(slice_sizer, 0, wx.EXPAND | wx.ALL, 4)

        # Canvas
        self.canvas = ModuleCanvas(self)
        canvas_sizer.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 4)
        # Compact view grid controls
        controls = wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(wx.StaticText(self, label="Grid X"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.grid_w = wx.SpinCtrl(self, min=4, max=512, initial=32)
        controls.Add(self.grid_w, 0, wx.RIGHT, 8)
        controls.Add(wx.StaticText(self, label="Grid Y"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.grid_h = wx.SpinCtrl(self, min=4, max=512, initial=32)
        controls.Add(self.grid_h, 0, wx.RIGHT, 12)
        self.chk_grid = wx.CheckBox(self, label="Show Grid")
        self.chk_grid.SetValue(True)
        controls.Add(self.chk_grid, 0, wx.ALIGN_CENTER_VERTICAL)
        canvas_sizer.Add(controls, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self.selection_label = wx.StaticText(self, label="Selection: -")
        self.pivot_label = wx.StaticText(self, label="Pivot: -")
        canvas_sizer.Add(self.selection_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        canvas_sizer.Add(self.pivot_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        main_sizer.Add(sidebar, 0, wx.EXPAND)
        main_sizer.Add(canvas_sizer, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

        # Events
        self.btn_import.Bind(wx.EVT_BUTTON, self.on_import_image)
        self.btn_remove_img.Bind(wx.EVT_BUTTON, self.on_remove_image)
        self.image_list.Bind(wx.EVT_LISTBOX, self.on_select_image)
        self.btn_create_module.Bind(wx.EVT_BUTTON, self.on_create_module)
        self.btn_update_module.Bind(wx.EVT_BUTTON, self.on_update_module)
        self.btn_delete_module.Bind(wx.EVT_BUTTON, self.on_delete_module)
        self.btn_rename_module.Bind(wx.EVT_BUTTON, self.on_rename_module)
        self.module_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_module)
        self.module_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_deselect_module)
        self.btn_slice.Bind(wx.EVT_BUTTON, self.on_slice_grid)
        self.canvas.on_selection_changed = self._on_canvas_selection
        self.canvas.on_pivot_changed = self._on_canvas_pivot
        self.canvas.on_pick_color = self.on_canvas_pick_color
        self.canvas.on_module_clicked = self.on_canvas_module_clicked
        self.chk_grid.Bind(wx.EVT_CHECKBOX, self.on_toggle_grid)
        self.grid_w.Bind(wx.EVT_SPINCTRL, self.on_change_grid_spacing)
        self.grid_h.Bind(wx.EVT_SPINCTRL, self.on_change_grid_spacing)
        self.chk_trans_view.Bind(wx.EVT_CHECKBOX, self.on_toggle_trans_view)
        self.btn_pick_from_image.Bind(wx.EVT_BUTTON, self.on_pick_from_image)
        self._view_states: dict[str, Tuple[Tuple[float, float], float]] = {}
        self._bitmap_cache_transparent: dict[str, wx.Bitmap] = {}
        self.transparent_view: bool = True
        self._picking_transparent: bool = False
        self._suppress_module_events: bool = False
        self._modules_view: list[Module] = []
        # Initialize visual grid spacing from controls
        self.on_change_grid_spacing(wx.CommandEvent())

    # Image handling
    def on_import_image(self, _: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self,
            "Open image",
            wildcard="Image files (*.png;*.jpg;*.bmp)|*.png;*.jpg;*.bmp",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
            img = wx.Image(path)
            if not img.IsOk():
                wx.MessageBox("Failed to load image", "Error")
                return
            bmp = wx.Bitmap(img)
            asset = self.project.create_image(path, bmp.GetWidth(), bmp.GetHeight())
            asset.transparent_color = None
            self._bitmap_cache[asset.id] = bmp
            self.refresh_images(select_id=asset.id)
            self.select_image(asset.id)

    def on_remove_image(self, _: wx.CommandEvent) -> None:
        if not self.selected_image_id:
            return
        self.project.images = [img for img in self.project.images if img.id != self.selected_image_id]
        self.project.modules = [m for m in self.project.modules if m.image_id != self.selected_image_id]
        self._bitmap_cache.pop(self.selected_image_id, None)
        self._view_states.pop(self.selected_image_id, None)
        self.selected_image_id = None
        self.refresh_images()
        self.refresh_modules()
        self.canvas.set_bitmap(None, (0, 0))

    def refresh_images(self, select_id: Optional[str] = None) -> None:
        self.image_list.Clear()
        for img in self.project.images:
            label = f"{os.path.basename(img.file_path)} ({img.width}x{img.height})"
            self.image_list.Append(label, clientData=img.id)
        if select_id:
            for idx in range(self.image_list.GetCount()):
                if self.image_list.GetClientData(idx) == select_id:
                    self.image_list.SetSelection(idx)
                    self.select_image(select_id)
                    break
        elif self.image_list.GetCount() > 0:
            self.image_list.SetSelection(0)
            self.select_image(self.image_list.GetClientData(0))

    def select_image(self, image_id: str) -> None:
        # Save current view state
        if self.selected_image_id:
            self._view_states[self.selected_image_id] = self.canvas.get_view_state()
        self.selected_image_id = image_id
        asset = self.project.get_image(image_id)
        bmp = self._bitmap_cache.get(image_id)
        if asset and not bmp and os.path.exists(asset.file_path):
            bmp = wx.Bitmap(asset.file_path)
            self._bitmap_cache[image_id] = bmp
        if asset:
            self._update_transparency_controls(asset)
            display_bmp = self._get_display_bitmap(asset, bmp)
            self.canvas.set_bitmap(display_bmp, (asset.width, asset.height))
            self.canvas.set_transparent_view(self.transparent_view)
        else:
            self.canvas.set_bitmap(None, (0, 0))
        # Restore view state if available
        if image_id in self._view_states:
            pan, zoom = self._view_states[image_id]
            self.canvas.set_view_state(pan, zoom)
        else:
            self.canvas.set_view_state((0.0, 0.0), 1.0)
        self.refresh_modules()

    def on_select_image(self, event: wx.CommandEvent) -> None:
        idx = event.GetSelection()
        image_id = self.image_list.GetClientData(idx)
        self.select_image(image_id)

    # Module handling
    def refresh_modules(self, select_id: Optional[str] = None) -> None:
        self.module_list.DeleteAllItems()
        mods = (
            [m for m in self.project.modules if m.image_id == self.selected_image_id]
            if self.selected_image_id
            else self.project.modules
        )
        self._modules_view = mods
        if select_id is None and self.selected_module_id and self.selected_module_id not in [m.id for m in mods]:
            self.selected_module_id = None
        for m in self._modules_view:
            idx = self.module_list.InsertItem(self.module_list.GetItemCount(), m.name)
            self.module_list.SetItem(idx, 1, f"{m.rect[0]},{m.rect[1]} {m.rect[2]}x{m.rect[3]}")
            self.module_list.SetItem(idx, 2, f"{m.pivot[0]},{m.pivot[1]}")
        # Clear list selection, then select the requested one
        self._unselect_all_modules()
        if select_id:
            for i in range(self.module_list.GetItemCount()):
                m_obj = self._modules_view[i]
                if m_obj.id == select_id:
                    self._suppress_module_events = True
                    self.module_list.SetItemState(i, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
                    self.module_list.EnsureVisible(i)
                    self._suppress_module_events = False
                    self.select_module(m_obj.id)
                    break
        # Update overlays on canvas
        overlays = []
        for m in self._modules_view:
            is_sel = m.id == self.selected_module_id
            overlays.append(((m.rect[0], m.rect[1], m.rect[2], m.rect[3]), is_sel, m.id))
        if self.selected_module_id is None:
            # Clear selection highlight on canvas
            self.canvas.selection = None
            self.canvas.pivot = None
            self.canvas.set_selection_style("active")
        self.canvas.set_module_overlays(overlays)

    def _unselect_all_modules(self) -> None:
        self._suppress_module_events = True
        for i in range(self.module_list.GetItemCount()):
            self.module_list.SetItemState(i, 0, wx.LIST_STATE_SELECTED)
        self._suppress_module_events = False

    def on_select_module(self, event: wx.ListEvent) -> None:
        if self._suppress_module_events:
            return
        idx = event.GetIndex()
        if 0 <= idx < len(self._modules_view):
            self._unselect_all_modules()
            self._suppress_module_events = True
            self.module_list.SetItemState(idx, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
            self._suppress_module_events = False
            self.select_module(self._modules_view[idx].id)

    def on_deselect_module(self, _: wx.ListEvent) -> None:
        if self._suppress_module_events:
            return
        self.selected_module_id = None
        self.canvas.selection = None
        self.canvas.pivot = None
        self.canvas.set_selection_style("active")
        self.refresh_modules()

    def select_module(self, module_id: str) -> None:
        self.selected_module_id = module_id
        mod = self.project.get_module(module_id)
        if mod:
            self.canvas.selection = (mod.rect[0], mod.rect[1], mod.rect[2], mod.rect[3])
            # Display pivot in canvas space (absolute) while storing it relative to rect
            self.canvas.pivot = (mod.rect[0] + mod.pivot[0], mod.rect[1] + mod.pivot[1])
            self.selection_label.SetLabel(f"Selection: {mod.rect}")
            self.pivot_label.SetLabel(f"Pivot (local): {mod.pivot}")
            self.canvas.set_selection_style("module")
            self.canvas.Refresh(False)

    def _on_canvas_selection(self, rect: Optional[Tuple[int, int, int, int]]) -> None:
        self.selection_label.SetLabel(f"Selection: {rect}" if rect else "Selection: -")

    def _on_canvas_pivot(self, pivot: Optional[Tuple[int, int]]) -> None:
        if pivot and self.canvas.selection:
            sel = self.canvas.selection
            local = (pivot[0] - sel[0], pivot[1] - sel[1])
            self.pivot_label.SetLabel(f"Pivot (local): {local}")
        else:
            self.pivot_label.SetLabel("Pivot: -")

    def on_create_module(self, _: wx.CommandEvent) -> None:
        if not self.selected_image_id:
            wx.MessageBox("Select an image first", "Info")
            return
        if not self.canvas.selection:
            wx.MessageBox("Select a rectangle on the image", "Info")
            return
        rect = self.canvas.selection
        name = f"Module {len(self.project.modules)+1}"
        pivot_abs = self.canvas.pivot
        pivot = (
            pivot_abs[0] - rect[0],
            pivot_abs[1] - rect[1],
        ) if pivot_abs else (rect[2] // 2, rect[3] // 2)
        mod = self.project.create_module(name, self.selected_image_id, rect, pivot)
        self.refresh_modules(select_id=mod.id)

    def on_update_module(self, _: wx.CommandEvent) -> None:
        if not self.selected_module_id:
            return
        mod = self.project.get_module(self.selected_module_id)
        if not mod:
            return
        if self.canvas.selection:
            mod.rect = self.canvas.selection
        if self.canvas.pivot:
            mod.pivot = (
                int(self.canvas.pivot[0] - mod.rect[0]),
                int(self.canvas.pivot[1] - mod.rect[1]),
            )
        self.refresh_modules(select_id=mod.id)

    def on_delete_module(self, _: wx.CommandEvent) -> None:
        if not self.selected_module_id:
            return
        self.project.modules = [m for m in self.project.modules if m.id != self.selected_module_id]
        self.selected_module_id = None
        self.refresh_modules()

    def on_rename_module(self, _: wx.CommandEvent) -> None:
        if not self.selected_module_id:
            return
        mod = self.project.get_module(self.selected_module_id)
        if not mod:
            return
        with wx.TextEntryDialog(self, "New name", value=mod.name) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                mod.name = dlg.GetValue()
                self.refresh_modules(select_id=mod.id)

    def on_slice_grid(self, _: wx.CommandEvent) -> None:
        if not self.selected_image_id:
            return
        img = self.project.get_image(self.selected_image_id)
        if not img:
            return
        bmp = self._bitmap_cache.get(img.id)
        if not bmp and os.path.exists(img.file_path):
            bmp = wx.Bitmap(img.file_path)
            self._bitmap_cache[img.id] = bmp
        if not bmp:
            wx.MessageBox("Image bitmap not available for slicing", "Error")
            return
        # Start from fresh modules for this image
        self.project.modules = [m for m in self.project.modules if m.image_id != img.id]
        wx_image = bmp.ConvertToImage()
        if img.transparent_color:
            wx_image = self._apply_transparency_to_image(wx_image, img.transparent_color)
        tw, th = self.tile_w.GetValue(), self.tile_h.GetValue()
        count = 0
        seen_hashes: set[str] = set()
        for y in range(0, img.height, th):
            for x in range(0, img.width, tw):
                rect = (x, y, min(tw, img.width - x), min(th, img.height - y))
                sub = wx_image.GetSubImage(wx.Rect(*rect))
                # Check emptiness
                data = bytes(sub.GetData())
                alpha = bytes(sub.GetAlphaBuffer()) if sub.HasAlpha() else b""
                if alpha:
                    if all(a == 0 for a in alpha):
                        continue
                else:
                    if all(v == 0 for v in data):
                        continue
                digest = hashlib.sha1(data + alpha).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                name = f"Tile {x//tw},{y//th}"
                pivot = (rect[2] // 2, rect[3] // 2)
                self.project.create_module(name, img.id, rect, pivot)
                count += 1
        # Update visual grid to match the slice grid
        self.grid_w.SetValue(tw)
        self.grid_h.SetValue(th)
        self.canvas.set_grid_spacing((tw, th))
        self.refresh_modules(select_id=self.selected_module_id)
        wx.MessageBox(f"Created {count} unique non-empty modules", "Grid Slice")

    def on_toggle_grid(self, event: wx.CommandEvent) -> None:
        self.canvas.set_show_grid(event.IsChecked())

    def on_change_grid_spacing(self, _: wx.CommandEvent) -> None:
        spacing = (max(4, self.grid_w.GetValue()), max(4, self.grid_h.GetValue()))
        self.canvas.set_grid_spacing(spacing)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.selected_image_id = None
        self.selected_module_id = None
        self._bitmap_cache = {}
        self._view_states = {}
        self.canvas.set_bitmap(None, (0, 0))
        self.refresh_images()
        self.refresh_modules()

    # Transparency helpers
    def _apply_transparency_to_image(
        self, image: wx.Image, color: Tuple[int, int, int]
    ) -> wx.Image:
        img = image.Copy()
        if not img.HasAlpha():
            img.InitAlpha()
        data = memoryview(img.GetDataBuffer())
        alpha = memoryview(img.GetAlphaBuffer())
        r_t, g_t, b_t = color
        for i in range(0, len(data), 3):
            idx = i // 3
            if data[i] == r_t and data[i + 1] == g_t and data[i + 2] == b_t:
                alpha[idx] = 0
            elif alpha[idx] == 0:
                alpha[idx] = 255
        return img

    def _get_display_bitmap(
        self, asset: ImageAsset, bmp: Optional[wx.Bitmap], force: bool = False
    ) -> Optional[wx.Bitmap]:
        if not bmp:
            return None
        if not self.transparent_view or not asset.transparent_color:
            return bmp
        key = f"{asset.id}_{asset.transparent_color}"
        cached = self._bitmap_cache_transparent.get(key)
        if cached and not force:
            return cached
        img = bmp.ConvertToImage()
        img = self._apply_transparency_to_image(img, asset.transparent_color)
        tbmp = wx.Bitmap(img, depth=-1)
        self._bitmap_cache_transparent[key] = tbmp
        return tbmp

    def _update_transparency_controls(self, asset: ImageAsset) -> None:
        if not getattr(self, "trans_swatch", None) or not getattr(self, "chk_trans_view", None):
            return
        color = asset.transparent_color or (0, 0, 0)
        self.trans_swatch.SetBackgroundColour(wx.Colour(*color))
        self.trans_swatch.Refresh()
        self.chk_trans_view.SetValue(self.transparent_view)

    def on_pick_transparent_color(self, _: wx.CommandEvent) -> None:
        if not self.selected_image_id:
            return
        with wx.ColourDialog(self) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            c = dlg.GetColourData().GetColour()
            color = (c.Red(), c.Green(), c.Blue())
            asset = self.project.get_image(self.selected_image_id)
            if asset:
                asset.transparent_color = color
                self._bitmap_cache_transparent = {
                    k: v for k, v in self._bitmap_cache_transparent.items() if not k.startswith(f"{asset.id}_")
                }
                self._update_transparency_controls(asset)
                bmp = self._bitmap_cache.get(asset.id)
                disp = self._get_display_bitmap(asset, bmp, force=True)
                self.canvas.set_bitmap(disp, (asset.width, asset.height))
                self.canvas.set_transparent_view(self.transparent_view)

    def on_toggle_trans_view(self, event: wx.CommandEvent) -> None:
        self.transparent_view = event.IsChecked()
        self.canvas.set_transparent_view(self.transparent_view)
        if not self.selected_image_id:
            return
        asset = self.project.get_image(self.selected_image_id)
        bmp = self._bitmap_cache.get(self.selected_image_id)
        if asset:
            # Force rebuild when toggling to ensure fresh bitmap
            disp = self._get_display_bitmap(asset, bmp, force=True)
            self.canvas.set_bitmap(disp, (asset.width, asset.height))
            # Restore overlays and selection
            overlays = [((m.rect[0], m.rect[1], m.rect[2], m.rect[3]), m.id == self.selected_module_id, m.id) for m in self._modules_view]
            self.canvas.set_module_overlays(overlays)
            if self.selected_module_id:
                mod = self.project.get_module(self.selected_module_id)
                if mod:
                    self.canvas.selection = (mod.rect[0], mod.rect[1], mod.rect[2], mod.rect[3])
                    self.canvas.pivot = (mod.rect[0] + mod.pivot[0], mod.rect[1] + mod.pivot[1])
                    self.canvas.set_selection_style("module")
            self.canvas.Refresh(False)

    def on_pick_from_image(self, _: wx.CommandEvent) -> None:
        if not self.selected_image_id:
            return
        self._picking_transparent = True
        self.canvas.pick_mode = True
        self.canvas.SetCursor(wx.Cursor(wx.CURSOR_CROSS))

    def on_canvas_pick_color(self, world: Tuple[float, float]) -> None:
        if not self._picking_transparent or not self.selected_image_id:
            return
        bmp = self._bitmap_cache.get(self.selected_image_id)
        asset = self.project.get_image(self.selected_image_id)
        if not bmp or not asset:
            return
        x, y = int(world[0]), int(world[1])
        if x < 0 or y < 0 or x >= bmp.GetWidth() or y >= bmp.GetHeight():
            self._picking_transparent = False
            self.canvas.pick_mode = False
            self.canvas.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))
            return
        img = bmp.ConvertToImage()
        color = (img.GetRed(x, y), img.GetGreen(x, y), img.GetBlue(x, y))
        asset.transparent_color = color
        self._bitmap_cache_transparent = {
            k: v for k, v in self._bitmap_cache_transparent.items() if not k.startswith(f"{asset.id}_")
        }
        self._update_transparency_controls(asset)
        disp = self._get_display_bitmap(asset, bmp, force=True)
        self.canvas.set_bitmap(disp, (asset.width, asset.height))
        self.canvas.set_transparent_view(self.transparent_view)
        # Restore overlays and selection after picking
        overlays = [((m.rect[0], m.rect[1], m.rect[2], m.rect[3]), m.id == self.selected_module_id, m.id) for m in self._modules_view]
        self.canvas.set_module_overlays(overlays)
        if self.selected_module_id:
            mod = self.project.get_module(self.selected_module_id)
            if mod:
                self.canvas.selection = (mod.rect[0], mod.rect[1], mod.rect[2], mod.rect[3])
                self.canvas.pivot = (mod.rect[0] + mod.pivot[0], mod.rect[1] + mod.pivot[1])
                self.canvas.set_selection_style("module")
        self.canvas.Refresh(False)
        self._picking_transparent = False
        self.canvas.pick_mode = False
        self.canvas.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))

    def on_canvas_module_clicked(self, module_id: str) -> None:
        if self._suppress_module_events:
            return
        # Find module in current view and select it
        for idx, m in enumerate(self._modules_view):
            if m.id == module_id:
                self._suppress_module_events = True
                self._unselect_all_modules()
                self.module_list.SetItemState(idx, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
                self.module_list.EnsureVisible(idx)
                self._suppress_module_events = False
                self.select_module(module_id)
                break
