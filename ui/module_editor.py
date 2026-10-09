"""Module editor panel for managing images and modules."""

from __future__ import annotations

from collections import deque
import hashlib
import os
import time
from typing import Callable, Optional, Tuple

import wx

from models import ImageAsset, Module, Project, generate_id
from ui.auto_modularize_dialog import AutoModularizeDialog
from optimization import run_auto_modularization
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.utils import load_wx_image_safely, load_wx_bitmap_safely


from ui.base_canvas import BaseCanvas

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}
IMAGE_FILE_WILDCARD = "Image files (*.png;*.jpg;*.jpeg;*.bmp)|*.png;*.jpg;*.jpeg;*.bmp"


class FolderImportOptionsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="Folder Import Options")
        main = wx.BoxSizer(wx.VERTICAL)
        main.Add(wx.StaticText(self, label="Choose how to import images from this folder:"), 0, wx.ALL, 10)

        self.chk_recursive = wx.CheckBox(self, label="Include subfolders recursively")
        self.chk_full_module = wx.CheckBox(self, label="Create one module per full imported image")
        main.Add(self.chk_recursive, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        main.Add(self.chk_full_module, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            main.Add(btns, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(main)

    def get_values(self) -> Tuple[bool, bool]:
        return self.chk_recursive.GetValue(), self.chk_full_module.GetValue()


class ModuleCanvas(BaseCanvas):
    """Top-left origin canvas for selecting module rects and pivots."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        self.max_zoom = 16.0 # Cap zoom to prevent extreme lag on large bitmaps
        self.bitmap: Optional[wx.Bitmap] = None
        self.image_size: Tuple[int, int] = (0, 0)
        self.selection: Optional[Tuple[int, int, int, int]] = None
        self.pivot: Optional[Tuple[int, int]] = None
        
        self.transparent_view: bool = True
        self.selection_style: str = "active"
        # Tuple: (rect, is_sel, id, [type, color, params])
        self.module_overlays: list = [] 
        self.active_shape_config: Optional[Tuple[str, Tuple[int, int, int], list]] = None
        
        self._selecting = False
        self._pivot_drag = False
        self._move_drag = False
        self._hover_pivot = False
        
        self.pick_mode: bool = False
        self.on_pick_color: Optional[Callable[[Tuple[float, float]], None]] = None
        self.on_module_clicked: Optional[Callable[[str], None]] = None
        self.on_deselect: Optional[Callable[[], None]] = None
        self.on_edit_end: Optional[Callable[[], None]] = None
        self.on_delete: Optional[Callable[[], None]] = None
        self._resize_handle: Optional[str] = None
        self._resize_start_rect: Optional[Tuple[int, int, int, int]] = None
        self._move_start_rect: Optional[Tuple[int, int, int, int]] = None
        self._move_start_pivot: Optional[Tuple[int, int]] = None
        
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_right_down)
        self.Bind(wx.EVT_MOTION, self.on_mouse_move)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

        self.on_selection_changed: Optional[Callable[[Optional[Tuple[int, int, int, int]]], None]] = None
        self.on_pivot_changed: Optional[Callable[[Optional[Tuple[int, int]]], None]] = None
        
    def on_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_DELETE or key == wx.WXK_BACK:
             if self.on_delete:
                 self.on_delete()
        event.Skip()

    def _is_existing_module_selected(self) -> bool:
        if not self.selection: return False
        # self.module_overlays entry: (rect, is_sel, id, ...)
        for ov in self.module_overlays:
            if ov[1]: return True
        return False



    def set_bitmap(self, bmp: Optional[wx.Bitmap], size: Tuple[int, int], reset_state: bool = True) -> None:
        self.bitmap = bmp
        self.image_size = size
        
        if reset_state:
            self.selection = None
            self.pivot = None
        self.Refresh(False)

    def set_selection_style(self, style: str) -> None:
        self.selection_style = style

    def set_module_overlays(self, overlays: list) -> None:
        self.module_overlays = overlays
        self.Refresh(False)

    def set_active_shape(self, shape_type: str, color: Tuple[int, int, int], params: list) -> None:
        self.active_shape_config = (shape_type, color, params)
        self.Refresh(False)

    def on_left_down(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        world = self.screen_to_world(pos)
        if self.pick_mode and self.on_pick_color:
            self.on_pick_color(world)
            return

        # Priority 1: Alt (Pan)
        if event.AltDown():
            self.on_pan_start(event)
            self._panning_alt = True
            return

        # Priority 2: Shift (Pivot Move) - ONLY if a module is selected AND has size
        has_size = False
        if self.selection:
            _, _, w, h = self.selection
            if abs(w) > 0 or abs(h) > 0:
                has_size = True

        if self.selection and has_size and event.ShiftDown():
            self.pivot = (int(world[0]), int(world[1]))
            if self.on_pivot_changed:
                self.on_pivot_changed(self.pivot)
            self._pivot_drag = True
            self._start = pos
            self.CaptureMouse()
            self.Refresh(False)
            return

        # Priority 3: Resize Handle
        handle = self._hit_handle(world) if self.selection else None
        if handle:
            self._resize_handle = handle
            self._resize_start_rect = self.selection
            self._start = pos
            self.CaptureMouse()
            self.Refresh(False)
            return

        # Priority 3.5: Move Selection
        if self.selection:
             x, y, w, h = self.selection
        # Priority 4: Module Overlay (Select)
        hit = self._hit_module_overlay(world)
        if hit:
            hit_id, hit_selected = hit
            # Only trigger selection if we clicked a DIFFERENT module.
            # If we clicked the selected one, we want to fall through to Move logic.
            if not hit_selected:
                if self.on_module_clicked:
                    self.on_module_clicked(hit_id)
                    return

        # Check for move (clicking inside existing selection)
        if self.selection and self._hit_rect(world, self.selection):
             self._move_drag = True
             self._move_start_rect = self.selection
             self._move_start_pivot = self.pivot
             self._start = pos
             # Clicking inside selection shouldn't deselect, but pass event?
             # Actually if we just click and release, it selects it. 
             # But if we are ALREADY selected, we just prep for move.
        else:
            # Clicking outside or starting new selection
            if self.on_deselect:
                self.on_deselect()
            
            self._selecting = True
            self.selection_style = "active"
            self.selection = (int(world[0]), int(world[1]), 0, 0)
            self._start = pos
            
            # Notify change immediately to clear old status
            if self.on_selection_changed:
                self.on_selection_changed(self.selection)
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
            if self.on_edit_end:
                self.on_edit_end()
        
        if self._resize_handle:
            self._resize_handle = None
            self._resize_start_rect = None
            if self.on_edit_end:
                self.on_edit_end()

        if self._move_drag:
            self._move_drag = False
            self._move_start_rect = None
            self._move_start_pivot = None
            if self.on_edit_end:
                 self.on_edit_end()

        if self._pivot_drag:
            if self.on_edit_end:
                self.on_edit_end()

        self._selecting = False
        self._pivot_drag = False
        self._panning_alt = False
        self._panning = False
        self.Refresh(False)

    def on_right_down(self, event: wx.MouseEvent) -> None:
        # Prevent right-click (Ctrl+Click on Mac) from moving pivot
        # Pivot movement is now strictly Shift+Left Click (Priority 2 in on_left_down)
        pass
        self._panning = False

    def on_mouse_move(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        world = self.screen_to_world(pos)
        
        # Cursor update
        # Cursor update
        if not self._panning and not self._selecting and not self._resize_handle and not self._move_drag:
            handle = self._hit_handle(world) if self.selection else None
            if handle:
                cursors = {
                    "nw": wx.CURSOR_SIZENWSE, "n": wx.CURSOR_SIZENS, "ne": wx.CURSOR_SIZENESW,
                    "w": wx.CURSOR_SIZEWE, "e": wx.CURSOR_SIZEWE,
                    "sw": wx.CURSOR_SIZENESW, "s": wx.CURSOR_SIZENS, "se": wx.CURSOR_SIZENWSE
                }
                self.SetCursor(wx.Cursor(cursors.get(handle, wx.CURSOR_DEFAULT)))
            elif self._is_over_pivot(world) and event.ShiftDown() and self.selection and (abs(self.selection[2]) > 0 or abs(self.selection[3]) > 0):
                self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
            elif self.pick_mode:
                self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
            elif self.selection and self._hit_rect(world, self.selection):
                self.SetCursor(wx.Cursor(wx.CURSOR_SIZING))
            else:
                self.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))

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
            
            # Auto-Center Pivot for New Selection
            # Find normalized dimensions
            nx, ny, nw, nh = int(x), int(y), int(w), int(h)
            if nw < 0: nx += nw; nw = -nw
            if nh < 0: ny += nh; nh = -nh
            
            self.pivot = (nx + nw // 2, ny + nh // 2)
            if self.on_pivot_changed:
                self.on_pivot_changed(self.pivot)

            if self.on_selection_changed:
                self.on_selection_changed(self.selection)
            self.Refresh(False)
        elif self._resize_handle and self.selection and self._resize_start_rect and event.Dragging():
            # Handle resizing with edge anchoring to prevent jitter
            rx, ry, rw, rh = self._resize_start_rect
            # Fixed anchors
            anchor_right = rx + rw
            anchor_bottom = ry + rh
            
            # Delta from start
            start_world = self.screen_to_world(self._start)
            dx = world[0] - start_world[0]
            dy = world[1] - start_world[1]
            
            # Calculate new potential edges
            new_left = rx
            new_top = ry
            new_right = anchor_right
            new_bottom = anchor_bottom
            
            if "w" in self._resize_handle:
                new_left = int(rx + dx)
            elif "e" in self._resize_handle:
                new_right = int(anchor_right + dx)
            
            if "n" in self._resize_handle:
                new_top = int(ry + dy)
            elif "s" in self._resize_handle:
                new_bottom = int(anchor_bottom + dy)
                
            # Normalize
            if new_right < new_left:
                new_left, new_right = new_right, new_left
            if new_bottom < new_top:
                new_top, new_bottom = new_bottom, new_top
                
            self.selection = (new_left, new_top, new_right - new_left, new_bottom - new_top)
            
            # Auto-Center Pivot if Potential Module (Not Existing)
            if not self._is_existing_module_selected():
                 cx = new_left + (new_right - new_left) // 2
                 cy = new_top + (new_bottom - new_top) // 2
                 self.pivot = (cx, cy)
                 if self.on_pivot_changed:
                     self.on_pivot_changed(self.pivot)
            
            if self.on_selection_changed:
                self.on_selection_changed(self.selection)
            self.Refresh(False)

        elif self._move_drag and self.selection and self._move_start_rect and event.Dragging():
            start_world = self.screen_to_world(self._start)
            dx = int(world[0] - start_world[0])
            dy = int(world[1] - start_world[1])
            
            x, y, w, h = self._move_start_rect
            self.selection = (x + dx, y + dy, w, h)
            if self.on_selection_changed:
                 self.on_selection_changed(self.selection)
            
            # Pivot Logic
            if not self._is_existing_module_selected():
                # Force Center for Potential Modules
                nx, ny = x + dx, y + dy
                # Normalize just in case, though move shouldn't flip
                if w < 0: nx += w; w = -w
                if h < 0: ny += h; h = -h
                self.pivot = (nx + w // 2, ny + h // 2)
                if self.on_pivot_changed:
                    self.on_pivot_changed(self.pivot)
            elif self._move_start_pivot:
                # Relative Move for Existing Modules
                px, py = self._move_start_pivot
                self.pivot = (px + dx, py + dy)
                if self.on_pivot_changed:
                    self.on_pivot_changed(self.pivot)
            
            self.Refresh(False)

        elif self._pivot_drag and self.pivot is not None and event.Dragging():
            self.pivot = (int(world[0]), int(world[1]))
            if self.on_pivot_changed:
                self.on_pivot_changed(self.pivot)
            self.Refresh(False)

    # Drawing
    # Drawing
    def on_paint(self, _: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        if self.show_transparency:
            self._draw_checkerboard(dc)
        gc = wx.GraphicsContext.Create(dc)
        
        # Revert to standard AA to match Frame Editor layout
        
        if self.bitmap:
            # Viewport Culling Optimization
            # Instead of scaling the entire image, we only scale what's visible.
            
            # 1. Get Visible World Bounds
            cw, ch = self.GetClientSize()
            
            # Screen (0,0) and (cw,ch) to World
            # We add a 1-pixel margin to avoid tearing at edges
            wx0, wy0 = self.screen_to_world(wx.Point(0, 0))
            wx1, wy1 = self.screen_to_world(wx.Point(cw, ch))
            
            # 2. Intersect with Image Bounds
            ix, iy = 0, 0
            iw, ih = self.bitmap.GetWidth(), self.bitmap.GetHeight()
            
            # Visible rectangle in Image Space
            vx0 = max(0, int(wx0))
            vy0 = max(0, int(wy0))
            vx1 = min(iw, int(wx1) + 1) # +1 ceil
            vy1 = min(ih, int(wy1) + 1)
            
            vw, vh = vx1 - vx0, vy1 - vy0
            
            if vw > 0 and vh > 0:
                # 3. Extract Sub-Image (The visible chunk)
                rect = wx.Rect(vx0, vy0, vw, vh)
                sub_img = self.bitmap.GetSubBitmap(rect).ConvertToImage()
                
                # 4. Scale Sub-Image to Screen Size
                # We need to calculate exactly where on screen this chunk lands
                # Viewport world pos (vx0, vy0) -> Screen pos
                
                screen_x, screen_y = self.world_to_screen((vx0, vy0))
                
                # Target dimensions on screen
                target_w = int(round(vw * self.zoom))
                target_h = int(round(vh * self.zoom))
                
                # Rescale only if dimensions are positive
                if target_w > 0 and target_h > 0:
                    sub_img.Rescale(target_w, target_h, wx.IMAGE_QUALITY_NEAREST)
                    scaled_sub_bmp = sub_img.ConvertToBitmap()
                    
                    # Draw at the calculated screen position
                    # Rounding screen coordinates to align with pixel grid logic
                    gc.DrawBitmap(scaled_sub_bmp, round(screen_x), round(screen_y), target_w, target_h)

        self._draw_grid(gc)
        if self.selection:
            x, y, w, h = self.selection
            if w < 0:
                x += w
                w = -w
            if h < 0:
                y += h
                h = -h
            
            # Calculate THEN round (Fixes offset on Win, matches image placement)
            raw_sx, raw_sy = self.world_to_screen((x, y))
            sx0, sy0 = round(raw_sx), round(raw_sy)
            dw, dh = round(w * self.zoom), round(h * self.zoom)

            if self.selection_style == "active":
                # Selected module: White dashed
                gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), width=2, style=wx.PENSTYLE_SHORT_DASH))
                gc.SetBrush(wx.Brush(wx.Colour(40, 120, 200, 40)))
                gc.DrawRectangle(sx0, sy0, dw, dh)
            else:
                # Dashed colorful outline for selected module
                pen = wx.Pen(wx.Colour(40, 200, 240), width=2, style=wx.PENSTYLE_SHORT_DASH)
                gc.SetPen(pen)
                gc.SetBrush(wx.TRANSPARENT_BRUSH)
                gc.DrawRectangle(sx0, sy0, dw, dh)
                # Draw handles
                self._draw_handles(gc, sx0, sy0, dw, dh)

        # Module overlays (unselected & shapes)
        if self.module_overlays:
            pen_unselected = wx.Pen(wx.Colour(200, 200, 200), width=1, style=wx.PENSTYLE_SHORT_DASH)
            
            for item in self.module_overlays:
                # Unpack potential extended data
                rect = item[0]
                is_sel = item[1]
                mid = item[2]
                
                if is_sel:
                    continue

                x, y, w, h = rect
                sx0, sy0 = self.world_to_screen((x, y))
                
                # Render Shape if data is present
                if len(item) > 3 and item[3] != "MD_IMAGE":
                     mod_type, mod_color, mod_params = item[3], item[4], item[5]
                     self._render_vector_shape(gc, mod_type, mod_color, mod_params, x, y, w, h)
                else:
                    # Default dashed box for Image modules
                    gc.SetBrush(wx.TRANSPARENT_BRUSH)
                    gc.SetPen(pen_unselected)
                    gc.DrawRectangle(round(sx0), round(sy0), round(w * self.zoom), round(h * self.zoom))

        # Active Selection
        if self.selection:
             # Render Active Shape Content underlying the selection box
             if self.active_shape_config and self.active_shape_config[0] != "MD_IMAGE":
                 s_type, s_color, s_params = self.active_shape_config
                 x, y, w, h = self.selection
                 self._render_vector_shape(gc, s_type, s_color, s_params, x, y, w, h)
             
             x, y, w, h = self.selection
             
             if self.pivot:
                # Only draw pivot if selection has size OR we are actively dragging/hovering it
                # This prevents the "red crosshair" from showing up on a simple click (empty selection)
                has_size = abs(self.selection[2]) > 0 or abs(self.selection[3]) > 0
                if has_size or self._pivot_drag or self._hover_pivot:
                    sx, sy = self.world_to_screen(self.pivot)
                    
                    # Pivot is a single pixel. Visualize it as such.
                    pixel_size = max(1, self.zoom)
                    
                    color = wx.Colour(240, 80, 80) if self._pivot_drag or self._hover_pivot else wx.Colour(200, 60, 60)
                    
                    # 1. Draw Square around the pivot pixel
                    # Use Rounding to align with grid
                    dsx = round(sx)
                    dsy = round(sy)
                    dsize = round(pixel_size)
                    
                    gc.SetPen(wx.Pen(color, width=1))
                    gc.SetBrush(wx.TRANSPARENT_BRUSH)
                    gc.DrawRectangle(dsx, dsy, dsize, dsize)
                    
                    # 2. Draw Crosshair centered on the pixel
                    # Make it slightly larger than the square
                    cx = dsx + dsize / 2
                    cy = dsy + dsize / 2
                    
                    # Extend by fixed amount (e.g. 6px) outside the square
                    ext = 6
                    half_len = (dsize / 2) + ext
                    
                    gc.SetPen(wx.Pen(color, width=2))
                    gc.StrokeLine(cx - half_len, cy, cx + half_len, cy)
                    gc.StrokeLine(cx, cy - half_len, cx, cy + half_len)

    def _render_vector_shape(self, gc: wx.GraphicsContext, type: str, color: Tuple[int, int, int], params: list, x: int, y: int, w: int, h: int) -> None:
        """Helper to render vector shapes given world bounds using pixel-perfect scaling."""
        import math
        
        # 1. Generate Bitmap using Shared Utility
        from ui.utils import render_pixel_shape_to_bitmap
        # Ceil dimensions to ensure we cover the area
        bw, bh = int(math.ceil(w)), int(math.ceil(h))
        
        bmp = render_pixel_shape_to_bitmap(type, bw, bh, color, params)
        if not bmp:
            return
            
        # 3. Scale up to Screen Size (Nearest Neighbor)
        img = bmp.ConvertToImage()
        screen_w = int(w * self.zoom)
        screen_h = int(h * self.zoom)
        
        if screen_w > 0 and screen_h > 0:
            img.Rescale(screen_w, screen_h, wx.IMAGE_QUALITY_NEAREST)
            scaled_bmp = img.ConvertToBitmap()
            
            # 4. Render to Main Canvas
            sx, sy = self.world_to_screen((x, y))
            # Round destination to snap to pixel alignment
            gc.DrawBitmap(scaled_bmp, round(sx), round(sy), screen_w, screen_h)

    def _draw_handles(self, gc: wx.GraphicsContext, x: float, y: float, w: float, h: float) -> None:
        size = 6
        half = size / 2
        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gc.SetPen(wx.Pen(wx.Colour(0, 0, 0)))
        
        # Corners
        coords = [
            (x - half, y - half), (x + w - half, y - half),
            (x + w - half, y + h - half), (x - half, y + h - half),
            (x + w/2 - half, y - half), (x + w - half, y + h/2 - half),
            (x + w/2 - half, y + h - half), (x - half, y + h/2 - half)
        ]
        for cx, cy in coords:
            gc.DrawRectangle(cx, cy, size, size)

    def _hit_handle(self, world: Tuple[float, float]) -> Optional[str]:
        if not self.selection:
            return None
        x, y, w, h = self.selection
        # Normalize
        if w < 0: x += w; w = -w
        if h < 0: y += h; h = -h
        
        tol = 8 / self.zoom # Tolerance in world units
        wx, wy = world
        
        # Check corners first
        if abs(wx - x) < tol and abs(wy - y) < tol: return "nw"
        if abs(wx - (x+w)) < tol and abs(wy - y) < tol: return "ne"
        if abs(wx - (x+w)) < tol and abs(wy - (y+h)) < tol: return "se"
        if abs(wx - x) < tol and abs(wy - (y+h)) < tol: return "sw"
        
        # Check edges
        if abs(wy - y) < tol and x < wx < x+w: return "n"
        if abs(wy - (y+h)) < tol and x < wx < x+w: return "s"
        if abs(wx - x) < tol and y < wy < y+h: return "w"
        if abs(wx - (x+w)) < tol and y < wy < y+h: return "e"
        
        return None

    def _hit_module_overlay(self, world: Tuple[float, float]) -> Optional[Tuple[str, bool]]:
        for item in reversed(self.module_overlays):
            rect, is_sel, mid = item[0], item[1], item[2]
            x, y, w, h = rect
            if x <= world[0] <= x + w and y <= world[1] <= y + h:
                return (mid, is_sel)
        return None

    def _draw_grid(self, gc: wx.GraphicsContext) -> None:
        # Infinite grid in center-origin space
        size = self.GetClientSize()
        left_world, top_world = self.screen_to_world(wx.Point(0, 0))
        right_world, bottom_world = self.screen_to_world(wx.Point(size.width, size.height))
        spacing_x, spacing_y = self.grid_spacing

        if self.show_grid:
            grid_pen = wx.Pen(wx.Colour(100, 100, 100), width=1, style=wx.PENSTYLE_SOLID)
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



    def set_transparent_view(self, enable: bool) -> None:
        self.transparent_view = enable
        self.set_show_transparency(enable)

    def _is_over_pivot(self, world: Tuple[float, float]) -> bool:
        if not self.pivot:
            return False
        px, py = self.pivot
        return abs(world[0] - px) < 6 and abs(world[1] - py) < 6

    def _hit_rect(self, world: Tuple[float, float], rect: Tuple[int, int, int, int]) -> bool:
        x, y, w, h = rect
        if w < 0: x += w; w = -w
        if h < 0: y += h; h = -h
        return x <= world[0] <= x + w and y <= world[1] <= y + h


class ModuleEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_image_id: Optional[str] = None
        self.selected_module_id: Optional[str] = None
        self._bitmap_cache: dict[str, wx.Bitmap] = {}
        self._modules_view: list[Module] = []

        # Layout: Splitter
        self.splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # Left Panel (Sidebar)
        self.left_panel = wx.Panel(self.splitter)
        sidebar = wx.BoxSizer(wx.VERTICAL)
        
        # Right Panel (Canvas)
        self.right_panel = wx.Panel(self.splitter)
        canvas_sizer = wx.BoxSizer(wx.VERTICAL)

        # Images
        img_box = wx.StaticBox(self.left_panel, label="Images")
        img_sizer = wx.StaticBoxSizer(img_box, wx.VERTICAL)
        self.image_list = wx.ListBox(img_box)
        img_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_import = wx.Button(img_box, label="Import Image")
        self.btn_import_folder = wx.Button(img_box, label="Import Folder")
        self.btn_remove_img = wx.Button(img_box, label="Remove")
        img_btns.Add(self.btn_import, 1, wx.RIGHT, 4)
        img_btns.Add(self.btn_import_folder, 1, wx.RIGHT, 4)
        img_btns.Add(self.btn_remove_img, 0)
        img_sizer.Add(self.image_list, 1, wx.EXPAND | wx.ALL, 4)
        img_sizer.Add(img_btns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Transparency controls
        trans_row = wx.BoxSizer(wx.HORIZONTAL)
        trans_lbl = wx.StaticText(img_box, label="Transparent color:")
        self.trans_swatch = wx.Panel(img_box, size=(24, 18))
        self.trans_swatch.SetBackgroundColour(wx.Colour(0, 0, 0))
        self.btn_pick_from_image = wx.Button(img_box, label="Pick from image")
        trans_row.Add(trans_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        trans_row.Add(self.trans_swatch, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        trans_row.Add(self.btn_pick_from_image, 1, wx.ALIGN_CENTER_VERTICAL)
        img_sizer.Add(trans_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        # Modules
        self.mod_box = wx.StaticBox(self.left_panel, label="Modules")
        mod_sizer = wx.StaticBoxSizer(self.mod_box, wx.VERTICAL)
        self.module_list = wx.ListCtrl(self.mod_box, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.module_list.InsertColumn(0, "Name", width=120)
        self.module_list.InsertColumn(1, "Rect", width=120)
        self.module_list.InsertColumn(2, "Pivot", width=90)
        
        # Row 0: Type & Color
        shape_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.choice_type = wx.Choice(self.mod_box, choices=[
            "MD_IMAGE", "MD_RECT", "MD_FILL_RECT", "MD_ARC", "MD_FILL_ARC", 
            "MD_MARKER", "MD_TRIANGLE", "MD_FILL_TRIANGLE", "MD_LINE"
        ])
        self.choice_type.SetSelection(0)
        self.clr_picker = wx.ColourPickerCtrl(self.mod_box, colour=wx.Colour(255, 255, 255))
        self.clr_picker.Disable() # Default is Image, so disable color
        
        shape_sizer.Add(self.choice_type, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 4)
        shape_sizer.Add(self.clr_picker, 0, wx.ALIGN_CENTER_VERTICAL)
        mod_sizer.Add(shape_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        
        self.Bind(wx.EVT_CHOICE, self.on_type_change, self.choice_type)
        self.Bind(wx.EVT_COLOURPICKER_CHANGED, self.on_color_change, self.clr_picker)

        # --- Shape Properties (Container) ---
        # Wrapper Panel to allow clean Show/Hide of the entire StaticBox group
        self.props_container = wx.Panel(self.mod_box)
        props_cont_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.props_box = wx.StaticBox(self.props_container, label="Properties")
        self.props_sizer = wx.StaticBoxSizer(self.props_box, wx.VERTICAL)
        
        # Arc Params Panel
        self.panel_arc = wx.Panel(self.props_box)
        arc_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.spin_start = wx.SpinCtrlDouble(self.panel_arc, min=0.0, max=360.0, initial=0.0, inc=15.0)
        self.spin_sweep = wx.SpinCtrlDouble(self.panel_arc, min=-360.0, max=360.0, initial=360.0, inc=15.0)
        arc_sizer.Add(wx.StaticText(self.panel_arc, label="Start:"), 0, wx.ALIGN_CENTER_VERTICAL)
        arc_sizer.Add(self.spin_start, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)
        arc_sizer.Add(wx.StaticText(self.panel_arc, label="Sweep:"), 0, wx.ALIGN_CENTER_VERTICAL)
        arc_sizer.Add(self.spin_sweep, 1, wx.EXPAND | wx.LEFT, 2)
        self.panel_arc.SetSizer(arc_sizer)
        self.props_sizer.Add(self.panel_arc, 0, wx.EXPAND | wx.ALL, 2)
        
        # Triangle/Line Params Panel
        self.panel_tri = wx.Panel(self.props_box)
        self.pts_sizer = wx.BoxSizer(wx.VERTICAL) 
        
        # Helper to create coordinate row
        def create_coord_row(parent, label, attr_lbl, attr_x, attr_y):
            row = wx.BoxSizer(wx.HORIZONTAL)
            lbl = wx.StaticText(parent, label=label, size=(30, -1))
            
            # Store label ref for dynamic updates (e.g. P2 -> End)
            if attr_lbl:
                setattr(self, attr_lbl, lbl)
            
            # Percentages: 0.0 to 100.0
            sx = wx.SpinCtrlDouble(parent, min=0.0, max=100.0, initial=0.0, inc=5.0)
            sy = wx.SpinCtrlDouble(parent, min=0.0, max=100.0, initial=0.0, inc=5.0)
            setattr(self, attr_x, sx)
            setattr(self, attr_y, sy)
            
            row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            row.Add(sx, 1, wx.EXPAND | wx.LEFT, 2)
            row.Add(sy, 1, wx.EXPAND | wx.LEFT, 2)
            return row

        # P1 (New for Triangle)
        self.row_p1 = create_coord_row(self.panel_tri, "P1%:", "lbl_p1", "spin_p1x", "spin_p1y")
        self.pts_sizer.Add(self.row_p1, 0, wx.EXPAND | wx.BOTTOM, 2)

        # P2 / End
        self.row_p2 = create_coord_row(self.panel_tri, "P2%:", "lbl_p2", "spin_p2x", "spin_p2y")
        self.pts_sizer.Add(self.row_p2, 0, wx.EXPAND | wx.BOTTOM, 2)

        # P3
        self.row_p3 = create_coord_row(self.panel_tri, "P3%:", "lbl_p3", "spin_p3x", "spin_p3y")
        self.pts_sizer.Add(self.row_p3, 0, wx.EXPAND)
        
        self.panel_tri.SetSizer(self.pts_sizer)
        self.props_sizer.Add(self.panel_tri, 0, wx.EXPAND | wx.ALL, 2)
        
        props_cont_sizer.Add(self.props_sizer, 1, wx.EXPAND | wx.ALL, 0)
        self.props_container.SetSizer(props_cont_sizer)
        
        mod_sizer.Add(self.props_container, 0, wx.EXPAND | wx.ALL, 4)
        
        # Bindings for Properties
        # Bind all spin ctrls
        spins = [self.spin_start, self.spin_sweep, 
                 self.spin_p1x, self.spin_p1y,
                 self.spin_p2x, self.spin_p2y,
                 self.spin_p3x, self.spin_p3y]
        for ctrl in spins:
            ctrl.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_shape_param_change)

        # Row 1: Create Module
        mod_create_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_create_module = wx.Button(self.mod_box, label="Create from selection")
        mod_create_sizer.Add(self.btn_create_module, 1, wx.EXPAND)
        
        # Row 2: Auto Detect + Gap
        mod_auto_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_auto_detect = wx.Button(self.mod_box, label="Auto Detect")
        mod_auto_sizer.Add(self.btn_auto_detect, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 4)
        
        # Gap setting
        gap_lbl = wx.StaticText(self.mod_box, label="Merge Gap:")
        self.spin_gap = wx.SpinCtrl(self.mod_box, min=0, max=10, initial=1, size=(60, -1))
        mod_auto_sizer.Add(gap_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        mod_auto_sizer.Add(self.spin_gap, 0, wx.ALIGN_CENTER_VERTICAL)

        mod_edit_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_rename_module = wx.Button(self.mod_box, label="Rename")
        self.btn_delete_module = wx.Button(self.mod_box, label="Delete")
        mod_edit_btns.Add(self.btn_rename_module, 1, wx.RIGHT, 4)
        mod_edit_btns.Add(self.btn_delete_module, 1)

        mod_sizer.Add(self.module_list, 1, wx.EXPAND | wx.ALL, 4)
        mod_sizer.Add(mod_create_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        mod_sizer.Add(mod_auto_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        mod_sizer.Add(mod_edit_btns, 0, wx.EXPAND | wx.ALL, 4)

        # Call initial update to hide properties for default MD_IMAGE
        self._update_property_panel("MD_IMAGE")
        
        # Grid slicing controls

        slice_box = wx.StaticBox(self.left_panel, label="Grid Slice")
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
        self.btn_auto_modularize = wx.Button(slice_box, label="Auto Modularize Sheet")
        slice_sizer.Add(self.btn_auto_modularize, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        sidebar.Add(img_sizer, 1, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(mod_sizer, 2, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(slice_sizer, 0, wx.EXPAND | wx.ALL, 4)
        
        self.left_panel.SetSizer(sidebar)

        # Canvas Pane
        self.canvas = ModuleCanvas(self.right_panel)
        canvas_sizer.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 4)
        
        self.canvas_controls = CanvasDisplayControls(
            self.right_panel,
            self.canvas,
            show_transparency=True,
            on_transparency_changed=self._on_canvas_transparency_changed,
        )
        self.grid_w = self.canvas_controls.grid_w
        self.grid_h = self.canvas_controls.grid_h
        self.chk_grid = self.canvas_controls.chk_grid
        self.chk_trans_view = self.canvas_controls.chk_transparency
        canvas_sizer.Add(self.canvas_controls, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Status labels
        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.selection_label = wx.StaticText(self.right_panel, label="Selection: -", size=(300, -1))
        self.pivot_label = wx.StaticText(self.right_panel, label="Pivot: -", size=(200, -1))
        status_sizer.Add(self.selection_label, 0, wx.RIGHT, 15)
        status_sizer.Add(self.pivot_label, 0)
        canvas_sizer.Add(status_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        self.right_panel.SetSizer(canvas_sizer)
        
        # Split
        self.splitter.SplitVertically(self.left_panel, self.right_panel, 340)
        self.splitter.SetMinimumPaneSize(200)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

        # Events
        self.btn_import.Bind(wx.EVT_BUTTON, self.on_import_image)
        self.btn_import_folder.Bind(wx.EVT_BUTTON, self.on_import_folder)
        self.btn_remove_img.Bind(wx.EVT_BUTTON, self.on_remove_image)
        self.image_list.Bind(wx.EVT_LISTBOX, self.on_select_image)
        self.btn_create_module.Bind(wx.EVT_BUTTON, self.on_create_module)
        self.btn_auto_detect.Bind(wx.EVT_BUTTON, self.on_auto_detect)
        self.btn_delete_module.Bind(wx.EVT_BUTTON, self.on_delete_module)
        self.btn_rename_module.Bind(wx.EVT_BUTTON, self.on_rename_module)
        self.module_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_module)
        self.module_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_deselect_module)
        self.btn_slice.Bind(wx.EVT_BUTTON, self.on_slice_grid)
        self.btn_auto_modularize.Bind(wx.EVT_BUTTON, self.on_auto_modularize_sheet)
        self.canvas.on_selection_changed = self._on_canvas_selection
        self.canvas.on_pivot_changed = self._on_canvas_pivot
        self.canvas.on_pick_color = self.on_canvas_pick_color
        self.canvas.on_module_clicked = lambda mid: self.select_module(mid, center_view=False)
        self.canvas.on_deselect = self.on_canvas_deselect
        self.canvas.on_edit_end = self._autosave_current_module
        self.canvas.on_delete = self.on_delete_module
        self.btn_pick_from_image.Bind(wx.EVT_BUTTON, self.on_pick_from_image)
        self._view_states: dict[str, Tuple[Tuple[float, float], float]] = {}
        self._bitmap_cache_transparent: dict[str, wx.Bitmap] = {}
        self.transparent_view: bool = True
        self._picking_transparent: bool = False
        self._suppress_module_events: bool = False
        self._modules_view: list[Module] = []
        self._last_canvas_selection: Optional[str] = None
        self.canvas_controls.set_transparency_value(self.transparent_view)

    # Image handling
    def _import_single_image_asset(self, path: str) -> Optional[ImageAsset]:
        img = load_wx_image_safely(path)
        if not img.IsOk():
            return None
        bmp = wx.Bitmap(img)
        asset = self.project.create_image(path, bmp.GetWidth(), bmp.GetHeight())
        asset.transparent_color = None
        self._bitmap_cache[asset.id] = bmp
        return asset

    def _next_module_name(self, base_name: str, used_names: set[str]) -> str:
        root = (base_name or "Module").strip() or "Module"
        candidate = root
        suffix = 2
        while candidate in used_names:
            candidate = f"{root} ({suffix})"
            suffix += 1
        used_names.add(candidate)
        return candidate

    def _create_full_image_module(self, asset: ImageAsset, used_names: set[str]) -> None:
        base_name = os.path.splitext(os.path.basename(asset.file_path))[0]
        module_name = self._next_module_name(base_name, used_names)
        self.project.create_module(
            module_name,
            asset.id,
            (0, 0, int(asset.width), int(asset.height)),
            (int(asset.width) // 2, int(asset.height) // 2),
        )

    def on_import_image(self, _: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self,
            "Open image",
            wildcard=IMAGE_FILE_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
            asset = self._import_single_image_asset(path)
            if not asset:
                wx.MessageBox("Failed to load image", "Error")
                return
            self.refresh_images(select_id=asset.id)
            self.select_image(asset.id)

    def on_import_folder(self, _: wx.CommandEvent) -> None:
        with wx.DirDialog(
            self,
            "Select folder with images",
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            folder = dlg.GetPath()

        with FolderImportOptionsDialog(self) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            import_recursive, create_full_modules = dlg.get_values()

        image_paths: list[str] = []
        try:
            if import_recursive:
                for root, dirs, files in os.walk(folder):
                    dirs.sort(key=lambda name: name.lower())
                    for filename in sorted(files, key=lambda name: name.lower()):
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in SUPPORTED_IMAGE_EXTENSIONS:
                            image_paths.append(os.path.join(root, filename))
            else:
                for entry in sorted(os.scandir(folder), key=lambda x: x.name.lower()):
                    if not entry.is_file():
                        continue
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in SUPPORTED_IMAGE_EXTENSIONS:
                        image_paths.append(entry.path)
        except OSError as exc:
            wx.MessageBox(f"Failed to read folder:\n{exc}", "Error")
            return

        if not image_paths:
            wx.MessageBox("No supported image files found in this folder.", "Info")
            return

        imported_assets: list[ImageAsset] = []
        failed_files: list[str] = []
        created_modules = 0
        used_module_names = {m.name for m in self.project.modules}

        with wx.BusyCursor():
            for path in image_paths:
                asset = self._import_single_image_asset(path)
                if not asset:
                    failed_files.append(os.path.relpath(path, folder))
                    continue
                imported_assets.append(asset)
                if create_full_modules:
                    self._create_full_image_module(asset, used_module_names)
                    created_modules += 1

        if not imported_assets:
            wx.MessageBox("No images were imported.", "Error")
            return

        selected_id = imported_assets[-1].id
        self.refresh_images(select_id=selected_id)
        self.select_image(selected_id)
        if create_full_modules:
            self.refresh_modules()

        parts = [f"Imported {len(imported_assets)} image(s)."]
        if create_full_modules:
            parts.append(f"Created {created_modules} full-image module(s).")
        if failed_files:
            parts.append(f"Skipped {len(failed_files)} file(s) that could not be loaded.")
        wx.MessageBox("\n".join(parts), "Folder Import Complete")

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

    def select_image(self, image_id: str) -> None:
        # Save current view state
        if self.selected_image_id:
            self._view_states[self.selected_image_id] = self.canvas.get_view_state()
        self.selected_image_id = image_id
        asset = self.project.get_image(image_id)
        bmp = self._bitmap_cache.get(image_id)
        if asset and not bmp and os.path.exists(asset.file_path):
            bmp = load_wx_bitmap_safely(asset.file_path)
            if bmp and bmp.IsOk():
                self._bitmap_cache[image_id] = bmp
            else:
                bmp = None
        if asset:
            if bmp and (asset.width != bmp.GetWidth() or asset.height != bmp.GetHeight()):
                asset.width = bmp.GetWidth()
                asset.height = bmp.GetHeight()
                # Refresh list labels to show correct size, but avoid re-triggering selection
                for idx in range(self.image_list.GetCount()):
                    if self.image_list.GetClientData(idx) == asset.id:
                        label = f"{os.path.basename(asset.file_path)} ({asset.width}x{asset.height})"
                        self.image_list.SetString(idx, label)
                        break
                
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
    def on_type_change(self, event):
        sel = self.choice_type.GetStringSelection()
        is_shape = sel != "MD_IMAGE"
        self.clr_picker.Enable(is_shape)
        
        if is_shape:
            self.btn_create_module.SetLabel("Create Shape")
        else:
            self.btn_create_module.SetLabel("Create from selection")
            
        self._update_property_panel(sel)
        
        # If we are changing type, set reasonable defaults in UI
        # (unless we are just reflecting a selection change, handled by select_module)
        # But wait, on_type_change is called by Choice event (User) OR manually.
        # If manually called by select_module, we might overwrite params?
        # NO, select_module sets UI values *after* calling on_type_change (if it calls it).
        # Check select_module: calls on_type_change(None).
        # We need to distinguish user event vs programmatic.
        # event is None if programmatic.
        if event is not None:
             self._set_default_ui_params(sel)
             
        # Update Canvas Preview
        c = self.clr_picker.GetColour()
        color = (c.Red(), c.Green(), c.Blue())
        # Parse current params from UI to show preview
        params = self._get_params_from_ui(sel)
        self.canvas.set_active_shape(sel, color, params)

    def _update_property_panel(self, type_str: str) -> None:
        """Show/Hide property controls based on type."""
        show_arc = type_str in ("MD_ARC", "MD_FILL_ARC")
        show_tri = type_str in ("MD_TRIANGLE", "MD_FILL_TRIANGLE")
        show_line = type_str == "MD_LINE"
        
        # Use simple Panel visibility
        self.panel_arc.Show(show_arc)
        self.panel_tri.Show(show_tri or show_line)
        
        if show_tri or show_line:
            # Handle internals of panel_tri (sizer still valid)
            self.pts_sizer.Show(0, True) # P1 (Always shown for Tri/Line)
            self.pts_sizer.Show(1, True) # P2 (Always shown)
            self.pts_sizer.Show(2, show_tri) # P3 (Only Tri)
            
            if show_line:
                self.lbl_p1.SetLabel("P1%")
                self.lbl_p2.SetLabel("P2%")
            else:
                self.lbl_p1.SetLabel("P1%")
                self.lbl_p2.SetLabel("P2%")
                self.lbl_p3.SetLabel("P3%")
            self.panel_tri.Layout() # Layout internal panel
        
        # Show entire Container (hides StaticBox too)
        self.props_container.Show(show_arc or show_tri or show_line)
        
        # Layout propagation
        self.mod_box.Layout()
        self.left_panel.Layout()
        self.Layout()

    def _get_params_from_ui(self, type_str: str) -> list:
        if type_str in ("MD_ARC", "MD_FILL_ARC"):
            return [self.spin_start.GetValue(), self.spin_sweep.GetValue()]
        elif type_str in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
            # Return 6 Percentages
            return [self.spin_p1x.GetValue(), self.spin_p1y.GetValue(), 
                    self.spin_p2x.GetValue(), self.spin_p2y.GetValue(),
                    self.spin_p3x.GetValue(), self.spin_p3y.GetValue()]
        elif type_str == "MD_LINE":
            # 4 Percentages for Line
            return [self.spin_p1x.GetValue(), self.spin_p1y.GetValue(),
                    self.spin_p2x.GetValue(), self.spin_p2y.GetValue()]
        return []

    def _set_default_ui_params(self, type_str: str) -> None:
        """Reset UI controls to default values for the given type."""
        if type_str in ("MD_ARC", "MD_FILL_ARC"):
            self.spin_start.SetValue(0.0)
            self.spin_sweep.SetValue(360.0)
        elif type_str in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
            # Default: Isosceles
            self.spin_p1x.SetValue(50.0)
            self.spin_p1y.SetValue(0.0)
            self.spin_p2x.SetValue(100.0)
            self.spin_p2y.SetValue(100.0)
            self.spin_p3x.SetValue(0.0)
            self.spin_p3y.SetValue(100.0)
        elif type_str == "MD_LINE":
            self.spin_p1x.SetValue(0.0)
            self.spin_p1y.SetValue(0.0)
            self.spin_p2x.SetValue(100.0)
            self.spin_p2y.SetValue(100.0)


    def on_shape_param_change(self, event):
        sel = self.choice_type.GetStringSelection()
        params = self._get_params_from_ui(sel)
        
        # Update Preview
        c = self.clr_picker.GetColour()
        color = (c.Red(), c.Green(), c.Blue())
        self.canvas.set_active_shape(sel, color, params)
        
        # Update Actual Module if Selected
        if self.selected_module_id:
            mod = self.project.get_module(self.selected_module_id)
            if mod and mod.type == sel:
                 mod.params = params
                 self._autosave_current_module() # Triggers refresh
                 self.refresh_modules(select_id=mod.id)

    def on_color_change(self, event):
        sel = self.choice_type.GetStringSelection()
        c = self.clr_picker.GetColour()
        color = (c.Red(), c.Green(), c.Blue())
        params = self._get_params_from_ui(sel)
        self.canvas.set_active_shape(sel, color, params)
        
        if self.selected_module_id:
            mod = self.project.get_module(self.selected_module_id)
            if mod:
                mod.color = color
                self.refresh_modules(select_id=mod.id)

    def refresh_modules(self, select_id: Optional[str] = None) -> None:
        self.module_list.DeleteAllItems()
        
        # Filter: if image selected, show its modules. 
        # If no image selected, show ALL modules (including shapes).
        # OR: Shape modules have image_id="missing" or similar.
        # User request: "When selecting an existing module..." implies we want visibility.
        # Let's show all modules if no image selected, or only compatible ones.
        
        # Default Initial Params if Creation
        if self.selected_module_id:
             # Already handled by on_select_module loading
             pass
        else:
             # Set logical defaults for creation
             # e.g. Triangle P2/P3 should default to reasonable relative vals?
             # Or 0,0 is fine, they will edit it.
             pass

        if self.selected_image_id:
            # Show modules for this image OR modules that are global shapes
            mods = [m for m in self.project.modules if m.image_id == self.selected_image_id or m.type != "MD_IMAGE"]
        else:
            mods = self.project.modules

        mods.sort(key=lambda m: m.name)
        self._modules_view = mods
        
        # Update title with count
        self.mod_box.SetLabel(f"Modules ({len(mods)})")
        
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
        self._rebuild_overlays()

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
            self._suppress_module_events = True
            # self._unselect_all_modules() # Removed to prevent scroll jump
            self._suppress_module_events = False
            # Pass center_view=True when selecting from list
            # Pass center_view=True when selecting from list, and indicate origin
            self.select_module(self._modules_view[idx].id, center_view=True, from_list=True)

    def on_deselect_module(self, idx_event: wx.ListEvent) -> None:
        if self._suppress_module_events:
            return

        self._autosave_current_module()
        self.selected_module_id = None
        self.canvas.selection = None
        self.canvas.pivot = None
        self.canvas.set_selection_style("active")
        
        # Enable Type Selection for new modules
        self.choice_type.Enable(True)
        
        # Don't full refresh list (prevents "double highlight" on switch), just canvas
        self._rebuild_overlays()
        self.canvas.Refresh()

    def select_module(self, module_id: str, center_view: bool = False, from_list: bool = False) -> None:
        if module_id != self.selected_module_id:
            self._autosave_current_module()
        self.selected_module_id = module_id
        
        # Disable Type Selection when editing existing module
        self.choice_type.Enable(False)
        
        # Sync Dropdown & Color
        if module_id:
            mod = self.project.get_module(module_id)
            if mod:
                # Type
                idx = self.choice_type.FindString(mod.type)
                if idx != wx.NOT_FOUND:
                    self.choice_type.SetSelection(idx)
                    self.on_type_change(None) # Update UI state
                
                # Color
                if "color" in mod.__dict__: # Check existence just in case
                    self.clr_picker.SetColour(wx.Colour(*mod.color))
                    
                # Params -> UI
                self._update_property_panel(mod.type)
                try:
                    p = mod.params
                    if mod.type in ("MD_ARC", "MD_FILL_ARC") and len(p) >= 2:
                        self.spin_start.SetValue(p[0])
                        self.spin_sweep.SetValue(p[1])
                    elif mod.type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
                        if len(p) >= 6:
                           # Standard 6-Point Percentage
                           self.spin_p1x.SetValue(p[0])
                           self.spin_p1y.SetValue(p[1])
                           self.spin_p2x.SetValue(p[2])
                           self.spin_p2y.SetValue(p[3])
                           self.spin_p3x.SetValue(p[4])
                           self.spin_p3y.SetValue(p[5])
                        elif len(p) == 4:
                           # Legacy Upgrade: 2 points relative to Origin(0,0)
                           # Convert to Percentages relative to Rect Size
                           # P1 = 0,0 -> 0%, 0%
                           # P2 = p[0], p[1] -> p[0]/w, p[1]/h
                           w, h = max(1, mod.rect[2]), max(1, mod.rect[3])
                           p2x_pct = (p[0] / w) * 100.0
                           p2y_pct = (p[1] / h) * 100.0
                           p3x_pct = (p[2] / w) * 100.0
                           p3y_pct = (p[3] / h) * 100.0
                           
                           # Set UI
                           self.spin_p1x.SetValue(0.0)
                           self.spin_p1y.SetValue(0.0)
                           self.spin_p2x.SetValue(p2x_pct)
                           self.spin_p2y.SetValue(p2y_pct)
                           self.spin_p3x.SetValue(p3x_pct)
                           self.spin_p3y.SetValue(p3y_pct)
                           
                           # Update Module Immediately
                           mod.params = [0.0, 0.0, p2x_pct, p2y_pct, p3x_pct, p3y_pct]
                        
                    elif mod.type == "MD_LINE":
                        if len(p) >= 4:
                            self.spin_p1x.SetValue(p[0])
                            self.spin_p1y.SetValue(p[1])
                            self.spin_p2x.SetValue(p[2])
                            self.spin_p2y.SetValue(p[3])
                        elif len(p) == 2:
                            # Legacy Upgrade: Start 0,0 -> End p[0], p[1]
                            # Convert to Percentages relative to Rect Size
                            w, h = max(1, mod.rect[2]), max(1, mod.rect[3])
                            p2x_pct = (p[0] / w) * 100.0
                            p2y_pct = (p[1] / h) * 100.0
                            
                            self.spin_p1x.SetValue(0.0)
                            self.spin_p1y.SetValue(0.0)
                            self.spin_p2x.SetValue(p2x_pct)
                            self.spin_p2y.SetValue(p2y_pct)
                            
                            # Update Module Immediately
                            mod.params = [0.0, 0.0, p2x_pct, p2y_pct]
                except Exception:
                    pass
                
                # Update Canvas active shape config to match the loaded module
                # (on_type_change set it using stale UI values, so we must overwrite it)
                self.canvas.set_active_shape(mod.type, mod.color, mod.params)

        # Focus in list
        mod = self.project.get_module(module_id)
        if mod:
            self.canvas.selection = (mod.rect[0], mod.rect[1], mod.rect[2], mod.rect[3])
            # Display pivot in canvas space (absolute) while storing it relative to rect
            p_x, p_y = mod.pivot
            if getattr(mod, 'rotated', False):
                # Logical -> Visual
                # vx = RectW - py_log
                # vy = px_log
                vx = mod.rect[2] - p_y
                vy = p_x
                self.canvas.pivot = (mod.rect[0] + vx, mod.rect[1] + vy)
            else:
                self.canvas.pivot = (mod.rect[0] + p_x, mod.rect[1] + p_y)

            self.selection_label.SetLabel(f"Selection: {mod.rect}")
            self.pivot_label.SetLabel(f"Pivot (local): {mod.pivot}")
            self.canvas.set_selection_style("module")
            
            # Auto-center view on the selected module
            if center_view:
                cx = mod.rect[0] + mod.rect[2] / 2
                cy = mod.rect[1] + mod.rect[3] / 2
                self.canvas.center_view((cx, cy))
            
            # Sync list selection
            if not from_list:
                for idx, m_view in enumerate(self._modules_view):
                    if m_view.id == module_id:
                        # Robust sync: Ensure ONLY this item is selected, clearing any others.
                        self._suppress_module_events = True
                        for i in range(self.module_list.GetItemCount()):
                            is_sel = (self.module_list.GetItemState(i, wx.LIST_STATE_SELECTED) & wx.LIST_STATE_SELECTED)
                            if i == idx:
                                if not is_sel:
                                    self.module_list.SetItemState(i, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
                                    self.module_list.EnsureVisible(i)
                            else:
                                if is_sel:
                                    self.module_list.SetItemState(i, 0, wx.LIST_STATE_SELECTED)
                        self._suppress_module_events = False
                        break
            
            self.canvas.Refresh(False)
        self._rebuild_overlays()

    def _on_canvas_selection(self, rect: Optional[Tuple[int, int, int, int]]) -> None:
        self.selection_label.SetLabel(f"Selection: {rect}" if rect else "Selection: -")

    def _on_canvas_pivot(self, pivot: Optional[Tuple[int, int]]) -> None:
        if pivot and self.canvas.selection:
            sel = self.canvas.selection
            local = (pivot[0] - sel[0], pivot[1] - sel[1])
            
            if self.selected_module_id:
                mod = self.project.get_module(self.selected_module_id)
                if mod and getattr(mod, 'rotated', False):
                     # Visual (vx, vy) -> Logical (px, py)
                     # px = vy
                     # py = RectW - vx
                     local = (local[1], sel[2] - local[0])

            self.pivot_label.SetLabel(f"Pivot (local): {local}")
        else:
            self.pivot_label.SetLabel("Pivot: -")

    def on_create_module(self, _: wx.CommandEvent) -> None:
        mod_type = self.choice_type.GetStringSelection()
        
        # 1. Validation
        if mod_type == "MD_IMAGE":
            if not self.selected_image_id:
                wx.MessageBox("Select an image first", "Info")
                return
            if not self.canvas.selection:
                wx.MessageBox("Select a rectangle on the image", "Info")
                return
        else:
            # Shape: Must have a selection to define bounds
            if not self.canvas.selection:
                wx.MessageBox("Draw a selection on the canvas defining the shape bounds.", "Info")
                return

        rect = self.canvas.selection
        pivot_abs = self.canvas.pivot
        
        # Calculate pivot relative to rect
        pivot = (
            pivot_abs[0] - rect[0],
            pivot_abs[1] - rect[1],
        ) if pivot_abs else (rect[2] // 2, rect[3] // 2)

        # Name
        count = len(self.project.modules) + 1
        name = f"Module {count}"

        # Params & Color
        color = (255, 255, 255)
        params = []
        
        if mod_type != "MD_IMAGE":
            c = self.clr_picker.GetColour()
            color = (c.Red(), c.Green(), c.Blue())
            
            # Params per type
            # Params per type (Get current from UI)
            params = self._get_params_from_ui(mod_type)
            
            # Fallback if params empty/invalid for some reason (though init defaults should handle it)
            if not params:
                if mod_type in ("MD_ARC", "MD_FILL_ARC"):
                    params = [0.0, 360.0]
                elif mod_type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
                     w, h = rect[2], rect[3]
                     params = [float(w), 0.0, 0.0, float(h)]
                elif mod_type == "MD_LINE":
                    w, h = rect[2], rect[3]
                    params = [float(w), float(h)]
        
        # Create
        img_id = self.selected_image_id if mod_type == "MD_IMAGE" else "missing"
        
        mod = Module(
            id=generate_id("md"),
            name=name,
            image_id=img_id,
            rect=rect,
            pivot=pivot,
            type=mod_type,
            color=color,
            params=params
        )
        self.project.modules.append(mod)
        self.refresh_modules(select_id=mod.id)

    def on_auto_detect(self, _: wx.CommandEvent) -> None:
        if not self.selected_image_id:
            wx.MessageBox("Select an image first", "Info")
            return
        
        bmp = self._bitmap_cache.get(self.selected_image_id)
        if not bmp:
            return

        img = bmp.ConvertToImage()
        
        # Apply transparent color if set
        asset = self.project.get_image(self.selected_image_id)
        if asset and asset.transparent_color:
            img = self._apply_transparency_to_image(img, asset.transparent_color)

        if not img.HasAlpha():
            wx.MessageBox("Image has no alpha channel. Cannot detect sprites.", "Error")
            return

        w, h = img.GetWidth(), img.GetHeight()
        alpha = img.GetAlpha() # bytes object
        
        # 0 = unvisited/transparent, 1 = visited/opaque
        visited = bytearray(w * h)
        rects: list[Tuple[int, int, int, int]] = []
        
        # Iterative scanning with Flood Fill
        with wx.BusyCursor():
            # Clear existing modules for this image first
            self.project.modules = [m for m in self.project.modules if m.image_id != self.selected_image_id]

            for y in range(h):
                for x in range(w):
                    idx = y * w + x
                    # If opaque (>10 threshold) and handling unvisited
                    if alpha[idx] > 10 and visited[idx] == 0:
                        # Start Flood Fill
                        min_x, max_x = x, x
                        min_y, max_y = y, y
                        q = deque([(x, y)])
                        visited[idx] = 1
                        
                        while q:
                            cx, cy = q.popleft()
                            
                            # Expand bounds
                            if cx < min_x: min_x = cx
                            if cx > max_x: max_x = cx
                            if cy < min_y: min_y = cy
                            if cy > max_y: max_y = cy
                            
                            # Check 8 neighbors (including diagonals)
                            neighbors = [
                                (-1, 0), (1, 0), (0, -1), (0, 1),
                                (-1, -1), (1, -1), (-1, 1), (1, 1)
                            ]
                            for dx, dy in neighbors:
                                nx, ny = cx + dx, cy + dy
                                if 0 <= nx < w and 0 <= ny < h:
                                    nidx = ny * w + nx
                                    if visited[nidx] == 0 and alpha[nidx] > 10:
                                        visited[nidx] = 1
                                        q.append((nx, ny))
                        
                        rects.append((min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))
        
        # Merge overlapping rects
        gap = self.spin_gap.GetValue()
        merged = True
        while merged:
            merged = False
            new_rects = []
            used = [False] * len(rects)
            
            for i in range(len(rects)):
                if used[i]: continue
                r1 = rects[i]
                
                # Try to merge r1 with any subsequent rect
                for j in range(i + 1, len(rects)):
                    if used[j]: continue
                    r2 = rects[j]
                    
                    # Intersect check with gap tolerance
                    # r1: x, y, w, h
                    # r2: x, y, w, h
                    x1, y1, w1, h1 = r1
                    x2, y2, w2, h2 = r2
                    
                    # Expand r1 by gap for the check
                    check_x1 = x1 - gap
                    check_y1 = y1 - gap
                    check_w1 = w1 + 2 * gap
                    check_h1 = h1 + 2 * gap
                    
                    if not (check_x1 + check_w1 <= x2 or x2 + w2 <= check_x1 or check_y1 + check_h1 <= y2 or y2 + h2 <= check_y1):
                        # Overlap/Proximity! Merge into r1 (Union of ORIGINAL rects)
                        nx = min(x1, x2)
                        ny = min(y1, y2)
                        nw = max(x1 + w1, x2 + w2) - nx
                        nh = max(y1 + h1, y2 + h2) - ny
                        r1 = (nx, ny, nw, nh)
                        used[j] = True
                        merged = True
                
                new_rects.append(r1)
            rects = new_rects

        # bulk create modules
        count = 0
        for rx, ry, rw, rh in rects:
             name = f"Module {len(self.project.modules) + 1}"
             pivot = (rw // 2, rh // 2)
             mod = self.project.create_module(name, self.selected_image_id, (rx, ry, rw, rh), pivot)
             count += 1
        
        self.refresh_modules()
        wx.MessageBox(f"Detected {count} modules.", "Success")

    def on_delete_module(self, _event: wx.CommandEvent = None) -> None:
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
            bmp = load_wx_bitmap_safely(img.file_path)
            if bmp and bmp.IsOk():
                self._bitmap_cache[img.id] = bmp
            else:
                bmp = None
        if not bmp:
            wx.MessageBox("Image bitmap not available for slicing", "Error")
            return
        # Start from fresh modules for this image
        self.project.modules = [m for m in self.project.modules if m.image_id != img.id]
        wx_image = bmp.ConvertToImage()
        if img.transparent_color:
            wx_image = self._apply_transparency_to_image(wx_image, img.transparent_color)

        w = wx_image.GetWidth()
        h = wx_image.GetHeight()
        
        # Grid loop
        count = 0
        tile_w = self.tile_w.GetValue()
        tile_h = self.tile_h.GetValue()
        
        rows = h // tile_h
        cols = w // tile_w
        
        for r in range(rows):
            for c in range(cols):
                rx = c * tile_w
                ry = r * tile_h
                # Optional: Check for empty content here to skip empty modules? 
                # For now just create them all (Grid Mode usually implies forcing structure).
                
                name = f"Module {len(self.project.modules) + 1}"
                pivot = (tile_w // 2, tile_h // 2)
                self.project.create_module(name, img.id, (rx, ry, tile_w, tile_h), pivot)
                count += 1
                
        self.refresh_modules()
        wx.MessageBox(f"Sliced {count} grid modules.", "Success")

    def on_auto_modularize_sheet(self, _event: wx.CommandEvent = None) -> None:
        if not self.selected_image_id:
            wx.MessageBox("Select a spritesheet image first.", "Info")
            return

        with AutoModularizeDialog(self) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            config = dlg.GetValues()

        before_image_ids = {img.id for img in self.project.images}
        with wx.BusyCursor():
            success, msg = run_auto_modularization(self.project, self.selected_image_id, config)

        if success:
            wx.MessageBox(msg, "Success")
            current_id = self.selected_image_id
            after_image_ids = {img.id for img in self.project.images}
            new_image_ids = [img.id for img in self.project.images if img.id in (after_image_ids - before_image_ids)]

            mode = str(config.get("modularization_mode", "freeform")).strip().lower()
            prefer_new_image = mode in ("tile", "tile_constrained", "tile-constrained")
            target_image_id = new_image_ids[-1] if (prefer_new_image and new_image_ids) else current_id
            if target_image_id and not self.project.get_image(target_image_id):
                target_image_id = current_id

            self.refresh_images(select_id=target_image_id)
            if target_image_id:
                self.select_image(target_image_id)
            else:
                self.refresh_modules()
        else:
            wx.MessageBox(f"Error: {msg}", "Error")


    def refresh_images(self, select_id: Optional[str] = None) -> None:
        self.image_list.Clear()
        
        # Validate current selection against project images
        current_valid = False
        if self.selected_image_id:
            for img in self.project.images:
                if img.id == self.selected_image_id:
                    current_valid = True
                    break
        if not current_valid:
            self.selected_image_id = None
            self.canvas.set_bitmap(None, (0,0))

        selection_idx = -1
        for idx, img in enumerate(self.project.images):
            # Check for name/file existence?
            name = os.path.basename(img.file_path)
            label = f"{name} ({img.width}x{img.height})"
            self.image_list.Append(label, img.id)
            if select_id and img.id == select_id:
                selection_idx = idx
            elif not select_id and self.selected_image_id == img.id:
                selection_idx = idx
                
        if selection_idx >= 0:
            self.image_list.SetSelection(selection_idx)
            self.image_list.EnsureVisible(selection_idx)
            # Ensure client data matches?
            # It's set in Append(label, clientData)
            
    def show_optimization_dialog(self, output_dir: str = None, name_hint: str = None) -> None:
        if not self.selected_image_id and not self.project.modules:
             wx.MessageBox("No images or modules to optimize.", "Info")
             return

        from ui.optimize_dialog import OptimizeDialog
        from optimization import optimize_modules
        
        with OptimizeDialog(self) as dlg:
            # Pre-select Scope based on current selection?
            # If image selected -> Local default?
            # Dialog Init sets defaults. Current Image is Index 0.
            
            if dlg.ShowModal() == wx.ID_OK:
                config = dlg.GetValues()
                
                scope = config.get("scope", "local")
                delete_unused = config.get("delete_unused", False)
                
                # 1. Determine Scope Modules
                scope_modules = []
                final_name_hint = name_hint
                
                if scope == "local":
                    if self.selected_image_id:
                        scope_modules = [m for m in self.project.modules if m.image_id == self.selected_image_id]
                        
                        # Name hint from selected image
                        img = self.project.get_image(self.selected_image_id)
                        if img and not final_name_hint:
                             base = os.path.splitext(os.path.basename(img.file_path))[0]
                             final_name_hint = f"{base}_optimized"
                    else:
                        # Fallback to global if nothing selected but local requested?
                        # Or warn?
                        wx.MessageBox("No image selected for Local Optimization.", "Error")
                        return

                else: # Global
                    scope_modules = self.project.modules[:] # Copy
                    # Name hint for global
                    if not final_name_hint:
                        if self.project.name:
                            final_name_hint = f"{self.project.name.replace(' ', '_')}_optimized"
                        else:
                            final_name_hint = "Global_Optimized"

                if not scope_modules:
                     wx.MessageBox("No modules found in selected scope.", "Info")
                     return

                # 2. Filter Unused (if requested)
                target_modules = scope_modules
                if delete_unused:
                    used_ids = self._get_used_module_ids()
                    target_modules = [m for m in scope_modules if m.id in used_ids]
                    
                    # Identify Unused modules to Delete
                    unused_mods = [m for m in scope_modules if m.id not in used_ids]
                    if unused_mods:
                         res = wx.MessageBox(f"Found {len(unused_mods)} unused modules in scope. Delete them permanently?", "Confirm Deletion", wx.YES_NO | wx.ICON_WARNING)
                         if res == wx.YES:
                             for m in unused_mods:
                                 if m in self.project.modules:
                                     self.project.modules.remove(m)
                    
                    if not target_modules:
                         wx.MessageBox("No Used modules found in scope to optimize.", "Info")
                         return

                with wx.BusyCursor():
                    # Pass filtered list
                    target_mod_ids = [m.id for m in target_modules]
                    success, msg = optimize_modules(self.project, target_mod_ids, config, output_dir, final_name_hint)

                if success:
                    wx.MessageBox(msg, "Success")
                    # Refresh
                    # Force a full refresh which invalidates old IDs
                    self.refresh_images()
                    self.refresh_modules()
                    
                    # Select the new image (it will be the last one added)
                    if self.project.images:
                        new_id = self.project.images[-1].id
                        self.refresh_images(select_id=new_id)
                        self.select_image(new_id)
                else:
                    wx.MessageBox(f"Optimization failed: {msg}", "Error", wx.OK | wx.ICON_ERROR)

    def _get_used_module_ids(self) -> set[str]:
        """Returns a set of all module IDs referenced in Frames or Mappings."""
        used = set()
        
        # Scan Frames
        for frame in self.project.frames:
            for fm in frame.fmodules:
                if fm.ref_type == "module":
                     used.add(fm.ref_id)
                     
        # Scan Mappings
        for mapping in self.project.mappings:
            for target_id in mapping.map.values():
                if target_id: # Might be None/Null
                    used.add(target_id)
                    
        return used




    def set_project(self, project: Project) -> None:
        self.project = project
        self.selected_image_id = None
        self.selected_module_id = None # Clear selection persistence
        self._bitmap_cache = {}
        self._view_states = {}
        self.canvas.set_bitmap(None, (0, 0))
        self.refresh_images()
        self.refresh_modules()
        
        # Select first image by default if available
        if self.project.images:
            self.select_image(self.project.images[0].id)

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
        if not getattr(self, "trans_swatch", None) or not getattr(self, "canvas_controls", None):
            return
        color = asset.transparent_color or (0, 0, 0)
        self.trans_swatch.SetBackgroundColour(wx.Colour(*color))
        self.trans_swatch.Refresh()
        self.canvas_controls.set_transparency_value(self.transparent_view)

    def _on_canvas_transparency_changed(self, enabled: bool) -> None:
        self._apply_transparency_toggle(enabled, sync_controls=False)

    def _apply_transparency_toggle(self, enabled: bool, sync_controls: bool = True) -> None:
        self.transparent_view = bool(enabled)
        if sync_controls and getattr(self, "canvas_controls", None):
            self.canvas_controls.set_transparency_value(self.transparent_view)
        self.canvas.set_transparent_view(self.transparent_view)
        if not self.selected_image_id:
            return
        asset = self.project.get_image(self.selected_image_id)
        bmp = self._bitmap_cache.get(self.selected_image_id)
        if asset:
            # Force rebuild when toggling to ensure fresh bitmap
            disp = self._get_display_bitmap(asset, bmp, force=True)
            self.canvas.set_bitmap(disp, (asset.width, asset.height), reset_state=False)
            self._rebuild_overlays()
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
        self._rebuild_overlays()
        self.canvas.Refresh(False)
        self._picking_transparent = False
        self.canvas.pick_mode = False
        self.canvas.SetCursor(wx.Cursor(wx.CURSOR_DEFAULT))

    def on_canvas_deselect(self) -> None:
        self._unselect_all_modules()
        self._autosave_current_module()
        self.selected_module_id = None
        self.canvas.selection = None
        self.canvas.pivot = None
        self.canvas.set_selection_style("active")
        
        # Re-enable Type Selection for new modules
        self.choice_type.Enable(True)
        
        self.refresh_modules()

    def _rebuild_overlays(self) -> None:
        overlays = []
        for m in self._modules_view:
            is_sel = m.id == self.selected_module_id
            # Pack extended data: (rect, is_sel, id, type, color, params)
            overlays.append((
                (m.rect[0], m.rect[1], m.rect[2], m.rect[3]),
                is_sel,
                m.id,
                m.type,
                getattr(m, 'color', (255, 255, 255)),
                getattr(m, 'params', [])
            ))
        if self.selected_module_id is None:
            # Clear selection highlight on canvas
            self.canvas.selection = None
            self.canvas.pivot = None
            self.canvas.set_selection_style("active")
        self.canvas.set_module_overlays(overlays)

    def _autosave_current_module(self) -> None:
        if not self.selected_module_id:
            return
        mod = self.project.get_module(self.selected_module_id)
        if not mod:
            return
        if self.canvas.selection:
            mod.rect = self.canvas.selection
        if self.canvas.pivot:
            vx = int(self.canvas.pivot[0] - mod.rect[0])
            vy = int(self.canvas.pivot[1] - mod.rect[1])
            
            if getattr(mod, 'rotated', False):
                 # Visual -> Logical
                 # px = vy
                 # py = RectW - vx
                 mod.pivot = (vy, mod.rect[2] - vx)
            else:
                 mod.pivot = (vx, vy)
        # Update list item
        for i in range(self.module_list.GetItemCount()):
            if self._modules_view[i].id == mod.id:
                self.module_list.SetItem(i, 1, f"{mod.rect[0]},{mod.rect[1]} {mod.rect[2]}x{mod.rect[3]}")
                self.module_list.SetItem(i, 2, f"{mod.pivot[0]},{mod.pivot[1]}")
                break
