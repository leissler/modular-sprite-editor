"""Module editor panel for managing images and modules."""

from __future__ import annotations

import os
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
        self._selecting = False
        self._panning = False
        self._panning_alt = False
        self._pivot_drag = False
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
        self.pan = (0.0, 0.0)
        self.zoom = 1.0
        self.Refresh(False)

    # Events
    def on_mousewheel(self, event: wx.MouseEvent) -> None:
        factor = 1.1 if event.GetWheelRotation() > 0 else 0.9
        self.zoom = max(0.2, min(16.0, self.zoom * factor))
        self.Refresh(False)

    def on_left_down(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        world = self.screen_to_world(pos)
        if event.AltDown():
            self.on_pan_start(event)
            self._panning_alt = True
            return
        if self._is_over_pivot(world):
            self._pivot_drag = True
        else:
            self._selecting = True
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
            if self.on_selection_changed:
                self.on_selection_changed(self.selection)
        self._selecting = False
        self._pivot_drag = False
        self._panning_alt = False
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
            gc.SetPen(wx.Pen(wx.Colour(40, 120, 200), width=2))
            gc.SetBrush(wx.Brush(wx.Colour(40, 120, 200, 40)))
            gc.DrawRectangle(sx0, sy0, w * self.zoom, h * self.zoom)
        if self.pivot:
            sx, sy = self.world_to_screen(self.pivot)
            gc.SetPen(wx.Pen(wx.Colour(200, 60, 60), width=2))
            gc.StrokeLine(sx - 6, sy, sx + 6, sy)
            gc.StrokeLine(sx, sy - 6, sx, sy + 6)

    def _draw_grid(self, gc: wx.GraphicsContext) -> None:
        # Infinite grid in top-left origin space
        spacing = 32
        grid_pen = wx.Pen(wx.Colour(90, 90, 90), width=1, style=wx.PENSTYLE_SOLID)
        gc.SetPen(grid_pen)
        size = self.GetClientSize()
        left_world, top_world = self.screen_to_world(wx.Point(0, 0))
        right_world, bottom_world = self.screen_to_world(wx.Point(size.width, size.height))
        start_x = int((left_world // spacing) * spacing)
        start_y = int((top_world // spacing) * spacing)
        x = start_x
        while x <= right_world + spacing:
            sx, _ = self.world_to_screen((x, 0))
            gc.StrokeLine(round(sx), 0, round(sx), size.height)
            x += spacing
        y = start_y
        while y <= bottom_world + spacing:
            _, sy = self.world_to_screen((0, y))
            gc.StrokeLine(0, round(sy), size.width, round(sy))
            y += spacing

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
        grid = wx.FlexGridSizer(2, 2, 4, 4)
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
        self.btn_slice.Bind(wx.EVT_BUTTON, self.on_slice_grid)
        self.canvas.on_selection_changed = self._on_canvas_selection
        self.canvas.on_pivot_changed = self._on_canvas_pivot

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
            self._bitmap_cache[asset.id] = bmp
            self.refresh_images(select_id=asset.id)
            self.select_image(asset.id)

    def on_remove_image(self, _: wx.CommandEvent) -> None:
        if not self.selected_image_id:
            return
        self.project.images = [img for img in self.project.images if img.id != self.selected_image_id]
        self.project.modules = [m for m in self.project.modules if m.image_id != self.selected_image_id]
        self._bitmap_cache.pop(self.selected_image_id, None)
        self.selected_image_id = None
        self.refresh_images()
        self.refresh_modules()
        self.canvas.set_bitmap(None, (0, 0))

    def refresh_images(self, select_id: Optional[str] = None) -> None:
        self.image_list.Clear()
        for img in self.project.images:
            self.image_list.Append(f"{img.id}: {os.path.basename(img.file_path)}", clientData=img.id)
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
        self.selected_image_id = image_id
        asset = self.project.get_image(image_id)
        bmp = self._bitmap_cache.get(image_id)
        if asset and not bmp and os.path.exists(asset.file_path):
            bmp = wx.Bitmap(asset.file_path)
            self._bitmap_cache[image_id] = bmp
        if asset and bmp:
            self.canvas.set_bitmap(bmp, (asset.width, asset.height))
        elif asset:
            self.canvas.set_bitmap(None, (asset.width, asset.height))
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
        for m in self._modules_view:
            idx = self.module_list.InsertItem(self.module_list.GetItemCount(), m.name)
            self.module_list.SetItem(idx, 1, f"{m.rect[0]},{m.rect[1]} {m.rect[2]}x{m.rect[3]}")
            self.module_list.SetItem(idx, 2, f"{m.pivot[0]},{m.pivot[1]}")
        if select_id:
            for i in range(self.module_list.GetItemCount()):
                m_obj = self._modules_view[i]
                if m_obj.id == select_id:
                    self.module_list.Select(i)
                    self.select_module(m_obj.id)
                    break

    def on_select_module(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self._modules_view):
            self.select_module(self._modules_view[idx].id)

    def select_module(self, module_id: str) -> None:
        self.selected_module_id = module_id
        mod = self.project.get_module(module_id)
        if mod:
            self.canvas.selection = (mod.rect[0], mod.rect[1], mod.rect[2], mod.rect[3])
            self.canvas.pivot = mod.pivot
            self.selection_label.SetLabel(f"Selection: {mod.rect}")
            self.pivot_label.SetLabel(f"Pivot: {mod.pivot}")
            self.canvas.Refresh(False)

    def _on_canvas_selection(self, rect: Optional[Tuple[int, int, int, int]]) -> None:
        self.selection_label.SetLabel(f"Selection: {rect}" if rect else "Selection: -")

    def _on_canvas_pivot(self, pivot: Optional[Tuple[int, int]]) -> None:
        self.pivot_label.SetLabel(f"Pivot: {pivot}" if pivot else "Pivot: -")

    def on_create_module(self, _: wx.CommandEvent) -> None:
        if not self.selected_image_id:
            wx.MessageBox("Select an image first", "Info")
            return
        if not self.canvas.selection:
            wx.MessageBox("Select a rectangle on the image", "Info")
            return
        rect = self.canvas.selection
        name = f"Module {len(self.project.modules)+1}"
        pivot = self.canvas.pivot or (rect[2] // 2, rect[3] // 2)
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
            mod.pivot = self.canvas.pivot
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
        tw, th = self.tile_w.GetValue(), self.tile_h.GetValue()
        count = 0
        for y in range(0, img.height, th):
            for x in range(0, img.width, tw):
                rect = (x, y, min(tw, img.width - x), min(th, img.height - y))
                name = f"Tile {x//tw},{y//th}"
                pivot = (rect[2] // 2, rect[3] // 2)
                self.project.create_module(name, img.id, rect, pivot)
                count += 1
        self.refresh_modules()
        wx.MessageBox(f"Created {count} modules", "Grid Slice")

    def set_project(self, project: Project) -> None:
        self.project = project
        self.selected_image_id = None
        self.selected_module_id = None
        self._bitmap_cache = {}
        self.canvas.set_bitmap(None, (0, 0))
        self.refresh_images()
        self.refresh_modules()
