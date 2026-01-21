"""Module editor panel for managing images and modules."""

from __future__ import annotations

from collections import deque
import hashlib
import os
import time
from typing import Callable, Optional, Tuple

import wx

from models import ImageAsset, Module, Project, generate_id


from ui.base_canvas import BaseCanvas

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
        if self.transparent_view:
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
        self.Refresh(False)

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
        self.btn_remove_img = wx.Button(img_box, label="Remove")
        img_btns.Add(self.btn_import, 1, wx.RIGHT, 4)
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

        sidebar.Add(img_sizer, 1, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(mod_sizer, 2, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(slice_sizer, 0, wx.EXPAND | wx.ALL, 4)
        
        self.left_panel.SetSizer(sidebar)

        # Canvas Pane
        self.canvas = ModuleCanvas(self.right_panel)
        canvas_sizer.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 4)
        
        # Compact view grid controls
        controls = wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(wx.StaticText(self.right_panel, label="Grid X"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.grid_w = wx.SpinCtrl(self.right_panel, min=4, max=512, initial=32)
        controls.Add(self.grid_w, 0, wx.RIGHT, 8)
        controls.Add(wx.StaticText(self.right_panel, label="Grid Y"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.grid_h = wx.SpinCtrl(self.right_panel, min=4, max=512, initial=32)
        controls.Add(self.grid_h, 0, wx.RIGHT, 12)
        self.chk_grid = wx.CheckBox(self.right_panel, label="Show Grid")
        self.chk_grid.SetValue(True)
        controls.Add(self.chk_grid, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.chk_trans_view = wx.CheckBox(self.right_panel, label="Transparency")
        self.chk_trans_view.SetValue(True)
        controls.Add(self.chk_trans_view, 0, wx.ALIGN_CENTER_VERTICAL)
        canvas_sizer.Add(controls, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
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
        self.btn_remove_img.Bind(wx.EVT_BUTTON, self.on_remove_image)
        self.image_list.Bind(wx.EVT_LISTBOX, self.on_select_image)
        self.btn_create_module.Bind(wx.EVT_BUTTON, self.on_create_module)
        self.btn_auto_detect.Bind(wx.EVT_BUTTON, self.on_auto_detect)
        self.btn_delete_module.Bind(wx.EVT_BUTTON, self.on_delete_module)
        self.btn_rename_module.Bind(wx.EVT_BUTTON, self.on_rename_module)
        self.module_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_module)
        self.module_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_deselect_module)
        self.btn_slice.Bind(wx.EVT_BUTTON, self.on_slice_grid)
        self.canvas.on_selection_changed = self._on_canvas_selection
        self.canvas.on_pivot_changed = self._on_canvas_pivot
        self.canvas.on_pick_color = self.on_canvas_pick_color
        self.canvas.on_pick_color = self.on_canvas_pick_color
        self.canvas.on_module_clicked = lambda mid: self.select_module(mid, center_view=False)
        self.canvas.on_deselect = self.on_canvas_deselect
        self.canvas.on_edit_end = self._autosave_current_module
        self.canvas.on_delete = self.on_delete_module
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
        self._last_canvas_selection: Optional[str] = None
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

    def on_deselect_module(self, _: wx.ListEvent) -> None:
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
            self.canvas.pivot = (mod.rect[0] + mod.pivot[0], mod.rect[1] + mod.pivot[1])
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
        self.selected_module_id = None # Clear selection persistence
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
                display_bmp = self._get_display_bitmap(asset, bmp)
                self.canvas.set_bitmap(display_bmp, (asset.width, asset.height), reset_state=False)
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
            mod.pivot = (
                int(self.canvas.pivot[0] - mod.rect[0]),
                int(self.canvas.pivot[1] - mod.rect[1]),
            )
        # Update list item
        for i in range(self.module_list.GetItemCount()):
            if self._modules_view[i].id == mod.id:
                self.module_list.SetItem(i, 1, f"{mod.rect[0]},{mod.rect[1]} {mod.rect[2]}x{mod.rect[3]}")
                self.module_list.SetItem(i, 2, f"{mod.pivot[0]},{mod.pivot[1]}")
                break
