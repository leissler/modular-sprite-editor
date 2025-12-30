"""Canvas widgets used by the frame and animation editors."""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

import wx

from models import Frame, FModule, Module, Project, CollisionRect, ControlPoint, generate_id
from ui.base_canvas import BaseCanvas

Color = Tuple[int, int, int]


def _color_from_id(identifier: str) -> Color:
    seed = sum(ord(c) for c in identifier)
    return ((seed * 37) % 200 + 30, (seed * 57) % 200 + 30, (seed * 97) % 200 + 30)

class FrameCanvas(BaseCanvas):
    """Canvas that can render a Frame and support selection/move of FModules."""

    def __init__(self, parent: wx.Window, project: Project, read_only: bool = False):
        super().__init__(parent)
        self.project = project
        self.read_only = read_only
        self.frame: Optional[Frame] = None
        self.selected_fmodules: list[str] = []
        self.show_collision = False # Default hidden in module mode
        self.show_control_points = True
        self.on_selection_changed: Optional[Callable[[list[str]], None]] = None
        
        self._dragging_ids: list[str] = []
        self._drag_start_world: Optional[Tuple[float, float]] = None
        self._drag_start_positions: dict[str, Tuple[int, int]] = {}
        
        self.frame_offset: Tuple[float, float] = (0.0, 0.0)
        self.render_flip_x = False
        self.render_flip_y = False
        self.render_rotation = 0.0
        self._bitmap_cache: dict[str, wx.Bitmap] = {}
        
        # Interaction Modes
        self.edit_mode = "module" # "module" or "collision"
        self.active_collision_type_id: Optional[str] = None
        self.selected_collision_rects: list[str] = []
        self.collision_type_colors: dict[str, tuple] = {}
        
        self.grid_size = 16 # Default
        
        # Collision Drag State
        self._col_drag_mode: str = "none" # "none", "move", "resize", "create"
        self._col_drag_handle: int = -1 # 0=TL, 1=TR, 2=BL, 3=BR
        self._col_drag_rect_id: Optional[str] = None
        self._col_drag_start_rect: Tuple[int, int, int, int] = (0,0,0,0)
        self._col_drag_start_screen: Tuple[int, int] = (0,0)

        # Point Interaction State
        self.show_points = True
        self.active_point_type_id: Optional[str] = None
        self.selected_points: list[str] = []
        self.point_type_colors: dict[str, tuple] = {}
        self._pt_drag_mode: str = "none" # "none", "move"
        self._pt_drag_id: Optional[str] = None
        
        # Enable Drop Target
        self.SetDropTarget(ModuleDropTarget(self))

        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_mouse_drag)
        # Mousewheel handled by BaseCanvas

    def set_frame(self, frame: Optional[Frame]) -> None:
        self.frame = frame
        self.Refresh(False)

    def set_frame_offset(self, offset: Tuple[float, float]) -> None:
        self.frame_offset = offset
        self.Refresh(False)
        
    def clear_cache(self) -> None:
        self._bitmap_cache.clear()
        self.Refresh(False)

    # --- Frame-level Transforms (Local -> World) ---
    def local_to_world(self, pt: Tuple[float, float]) -> Tuple[float, float]:
        # Sequence: Flip around Origin -> Rotate -> Offset
        # 1. Flip
        fx = pt[0] * (-1.0 if self.render_flip_x else 1.0)
        fy = pt[1] * (-1.0 if self.render_flip_y else 1.0)
        
        # 2. Rotate (cw=positive? check coordinate system)
        # wx coordinates: y down.
        # Standard rot: x' = x cos - y sin, y' = x sin + y cos
        # For 90 deg steps:
        rot = int(self.render_rotation) % 360
        if rot == 90:
            rx, ry = -fy, fx
        elif rot == 180:
            rx, ry = -fx, -fy
        elif rot == 270:
            rx, ry = fy, -fx
        else:
            rx, ry = fx, fy
            
        # 3. Offset
        wx = rx + self.frame_offset[0]
        wy = ry + self.frame_offset[1]
        return (wx, wy)

    def world_to_local(self, pt: Tuple[float, float]) -> Tuple[float, float]:
        # Reverse: Offset -> Un-Rotate -> Un-Flip
        
        # 1. Un-Offset
        ox = pt[0] - self.frame_offset[0]
        oy = pt[1] - self.frame_offset[1]
        
        # 2. Un-Rotate (Reverse of local_to_world rotation)
        rot = int(self.render_rotation) % 360
        if rot == 90:
            # Reverse of (-fy, fx) is (ry, -rx)
            rx, ry = oy, -ox
        elif rot == 180:
            rx, ry = -ox, -oy
        elif rot == 270:
            # Reverse of (fy, -fx) is (-ry, rx)
            rx, ry = -oy, ox
        else:
            rx, ry = ox, oy
            
        # 3. Un-Flip
        lx = rx * (-1.0 if self.render_flip_x else 1.0)
        ly = ry * (-1.0 if self.render_flip_y else 1.0)
        return (lx, ly)
        
    def on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        if self.show_grid:
            self._draw_checkerboard(dc)
            
        gc = wx.GraphicsContext.Create(dc)
        self._draw_grid(gc)
        self.draw_content(gc)

    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if not self.frame:
            self._draw_message(gc, "No frame selected")
            return
        
        # Draw modules (dimmed if in collision mode)
        gc.PushState()
        # If collision mode, we might want to fade modules?
        # Visual dimming: done by drawing overlay after modules, or just accept full brightness.
        # Let's draw modules first.
        for fm in self.frame.fmodules:
            self._draw_fmodule_content(gc, fm)
        gc.PopState()
            
        if self.edit_mode in ("collision", "point"):
             # Dim modules
             gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 100))) # Darken (softer now)
             gc.SetPen(wx.TRANSPARENT_PEN)
             vis_rect = self.GetClientSize()
             gc.DrawRectangle(0, 0, vis_rect.width, vis_rect.height)
             
        # Selection Overlays for Modules (only in module mode AND NOT showing collisions)
        # User requested: "When collrects in the module mode are shown, the module selection rects should be hidden"
        if self.edit_mode == "module" and not self.show_collision:
            for fm in self.frame.fmodules:
                if fm.id in self.selected_fmodules:
                    self._draw_fmodule_overlay(gc, fm)
            
        # Draw Collision Rects
        # Always visible if show_collision or in collision mode
        if self.show_collision or self.edit_mode == "collision":
            for cr in self.frame.collision_rects:
                # Check visibility map
                # If id not in map, it's hidden. If in map, we get color.
                if cr.type_id not in self.collision_type_colors:
                     continue
                     
                self._draw_collision(gc, cr)
                
        if self.show_points or self.edit_mode == "point":
            for cp in self.frame.control_points:
                # Check visibility
                if getattr(cp, 'type_id', None) and cp.type_id not in self.point_type_colors:
                    continue
                self._draw_control_point(gc, cp)

    def _draw_message(self, gc: wx.GraphicsContext, text: str) -> None:
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(80, 80, 80))
        tw, th = gc.GetTextExtent(text)
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        gc.DrawText(text, cx - tw / 2, cy - th / 2)

    def _draw_fmodule_content(self, gc: wx.GraphicsContext, fm: FModule, depth: int = 0) -> None:
        if depth > 16:  # Recursion guard
            return

        bounds = self._fmodule_bounds(fm)
        x0, y0, x1, y1 = bounds
        
        # 1. Local -> World
        w0 = self.local_to_world((x0, y0))
        w1 = self.local_to_world((x1, y1))
        
        # 2. World -> Screen
        p0 = self.world_to_screen(w0)
        p1 = self.world_to_screen(w1)
        
        sx0, sy0 = min(p0[0], p1[0]), min(p0[1], p1[1])
        w, h = abs(p1[0] - p0[0]), abs(p1[1] - p0[1])
        
        # Draw image content if module ref
        # Draw image content if module ref
        if fm.ref_type == "module":
             ref_id = fm.ref_id
             if self.project.active_mapping and ref_id in self.project.active_mapping.map:
                 ref_id = self.project.active_mapping.map[ref_id]
             
             if not ref_id: return

             mod = self.project.get_module(ref_id)
             if mod:
                 bmp = self._get_module_bitmap(mod)
                 if bmp:
                     # High Quality (Nearest Neighbor) Scaling hack for GraphicsContext
                     target_w, target_h = int(round(w)), int(round(h))
                     if target_w > 0 and target_h > 0:
                         img = bmp.ConvertToImage()
                         
                         # Apply flipping (Combine local flip with frame-level flip)
                         final_flip_x = fm.flip_x ^ self.render_flip_x
                         final_flip_y = fm.flip_y ^ self.render_flip_y
                         
                         if final_flip_x:
                             img = img.Mirror(horizontally=True)
                         if final_flip_y:
                             img = img.Mirror(horizontally=False) # Vertical flip

                         # Apply Rotation (Pixel perfect 90 deg steps)
                         rot = int(fm.rotation_degrees + self.render_rotation) % 360
                         if rot == 90:
                             img = img.Rotate90(clockwise=True)
                             # target_w/h already matches rotated bounds from _fmodule_bounds
                         elif rot == 180:
                             img = img.Rotate180()
                         elif rot == 270:
                             img = img.Rotate90(clockwise=False)

                         img.Rescale(target_w, target_h, wx.IMAGE_QUALITY_NEAREST)
                         scaled_bmp = img.ConvertToBitmap()
                         
                         gc.DrawBitmap(scaled_bmp, sx0, sy0, target_w, target_h)
        
        elif fm.ref_type == "frame":
             # Nested support logic stays essentially the same
             # But it should be cleaned up later if needed
             ref_frame = self.project.get_frame(fm.ref_id)
             if ref_frame:
                 for child_fm in ref_frame.fmodules:
                    cx, cy = child_fm.position
                    if fm.flip_x:
                        cx = -cx
                    if fm.flip_y:
                        cy = -cy

                    final_flip_x = child_fm.flip_x ^ fm.flip_x
                    final_flip_y = child_fm.flip_y ^ fm.flip_y
                    
                    nx = fm.position[0] + cx
                    ny = fm.position[1] + cy
                    
                    temp_fm = FModule(
                        id="temp",
                        ref_type=child_fm.ref_type,
                        ref_id=child_fm.ref_id,
                        position=(nx, ny),
                        flip_x=final_flip_x,
                        flip_y=final_flip_y
                    )
                    self._draw_fmodule_content(gc, temp_fm, depth + 1)

    def _draw_fmodule_overlay(self, gc: wx.GraphicsContext, fm: FModule) -> None:
        bounds = self._fmodule_bounds(fm)
        x0, y0, x1, y1 = bounds
        
        # Local -> World -> Screen
        p0 = self.world_to_screen(self.local_to_world((x0, y0)))
        p1 = self.world_to_screen(self.local_to_world((x1, y1)))
        sx0, sy0 = min(p0[0], p1[0]), min(p0[1], p1[1])
        w, h = abs(p1[0] - p0[0]), abs(p1[1] - p0[1])

        # Selection Outline
        if fm.id in self.selected_fmodules:
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            # White dashed pen (SHORT_DASH for fine dash)
            gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), width=1, style=wx.PENSTYLE_SHORT_DASH))
            gc.DrawRectangle(sx0, sy0, w, h)
            
            # Draw label
            gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(255, 255, 255))
            # gc.DrawText(label, sx0 + 4, sy0 - 20) # Draw above?

    def _get_pivot_offset(self, fm: FModule) -> Tuple[int, int]:
        if fm.ref_type == "module":
            mod = self.project.get_module(fm.ref_id)
            if mod: return mod.pivot
        return (0, 0)
        
    def _draw_collision(self, gc: wx.GraphicsContext, cr) -> None:
        # cr is CollisionRect(id, type_id, rect=(x,y,w,h))
        rx, ry, rw, rh = cr.rect
        
        # Local -> World
        w0 = self.local_to_world((rx, ry))
        w1 = self.local_to_world((rx + rw, ry + rh))
        
        # World -> Screen
        p0 = self.world_to_screen(w0)
        p1 = self.world_to_screen(w1)
        
        sx0, sy0 = min(p0[0], p1[0]), min(p0[1], p1[1])
        w, h = abs(p1[0] - p0[0]), abs(p1[1] - p0[1])
        
        # Get Color from map
        col = self.collision_type_colors.get(cr.type_id, (200, 60, 60))

        # Draw
        # Fill
        # Use explicit r,g,b,a and Ensure INT
        try:
            r, g, b = int(col[0]), int(col[1]), int(col[2])
        except (ValueError, IndexError):
            r, g, b = 200, 60, 60 # Fallback
            
        gc.SetBrush(wx.Brush(wx.Colour(r, g, b, 80))) # Semi-transparent
        
        # Outline
        pen_col = wx.Colour(r, g, b)
        # Handle Selection
        if self.edit_mode == "collision" and cr.id in self.selected_collision_rects:
            gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 2, style=wx.PENSTYLE_SOLID))
            # Draw handles?
        else:
            gc.SetPen(wx.Pen(pen_col, 1, style=wx.PENSTYLE_SOLID))
            
        gc.DrawRectangle(sx0, sy0, w, h)
        
        # If selected, draw corner handles
        if self.edit_mode == "collision" and cr.id in self.selected_collision_rects:
            self._draw_resize_handles(gc, sx0, sy0, w, h)
            
    def _draw_resize_handles(self, gc: wx.GraphicsContext, x, y, w, h):
        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gc.SetPen(wx.Pen(wx.Colour(0, 0, 0)))
        sz = 6
        # Draw corners
        corners = [
            (x, y), (x+w, y), (x, y+h), (x+w, y+h)
        ]
        for cx, cy in corners:
            gc.DrawRectangle(cx - sz/2, cy - sz/2, sz, sz)

    def _draw_control_point(self, gc: wx.GraphicsContext, cp) -> None:
        if not hasattr(cp, 'type_id'): return # Safety
        
        # Local -> World -> Screen
        sx, sy = self.world_to_screen(self.local_to_world((cp.x, cp.y)))
        
        # Color from type or default
        col = self.point_type_colors.get(cp.type_id, (0, 255, 0))
        r, g, b = int(col[0]), int(col[1]), int(col[2])
        
        # Draw Crosshair + Circle
        # Fill: Solid type color
        gc.SetBrush(wx.Brush(wx.Colour(r, g, b, 255)))
        
        # Outline: White if selected, None otherwise
        if cp.id in self.selected_points:
            gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 2))
        else:
            gc.SetPen(wx.TRANSPARENT_PEN)
            
        gc.DrawEllipse(sx - 4, sy - 4, 8, 8)
        
        gc.DrawEllipse(sx - 4, sy - 4, 8, 8)
        
        # Crosshair removed as per user request

    # Interaction
    def on_left_down(self, event: wx.MouseEvent) -> None:
        if self._panning or event.AltDown(): # Handled by BaseCanvas or caller? Base handles Middle.
             # BaseCanvas doesn't handle Left+Alt by default, needs override or call
             if event.AltDown():
                 self.on_pan_start(event) # Reuse pan logic
                 return
        
        if not self.frame:
            return

        if self.read_only:
             return
            
        pos_screen = event.GetPosition()
        pos_world = self.screen_to_world(pos_screen)
        # Collision Interaction
        if self.edit_mode == "collision":
            # on_collision_left_down expects screen coordinates for hit-testing handles
            # but world coordinates for other things?
            # actually it's a bit mixed. let's stay with screen first.
            self.on_collision_left_down(event, pos_screen)
            return
            
        # Point Interaction
        if self.edit_mode == "point":
            self.on_point_left_down(event, pos_screen)
            return

        # Module Selection Logic (Default)
        # We must hit-test in LOCAL space
        local_pos = self.world_to_local(pos_world)
        clicked = self._hit_test(local_pos)
        
        if clicked:
            if event.ShiftDown():
                if clicked.id in self.selected_fmodules:
                    self.selected_fmodules.remove(clicked.id)
                else:
                    self.selected_fmodules.append(clicked.id)
            else:
                if clicked.id not in self.selected_fmodules:
                    self.selected_fmodules = [clicked.id]
                # If already selected, do not clear others (allows group drag)
                
            self._dragging_ids = self.selected_fmodules[:]
            self._drag_start_world = pos_world
            
            # Record start positions for ALL dragging modules
            self._drag_start_positions = {}
            for mid in self._dragging_ids:
                fm = next((f for f in self.frame.fmodules if f.id == mid), None)
                if fm:
                    self._drag_start_positions[mid] = fm.position
                    
            self.CaptureMouse()
            if self.on_selection_changed:
                self.on_selection_changed(self.selected_fmodules)
        else:
            if not event.ShiftDown():
                self.selected_fmodules = []
                if self.on_selection_changed:
                    self.on_selection_changed([])
        self.Refresh(False)

    def on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
            self.on_pan_end(event)
            
        if self.edit_mode == "collision":
             self._col_drag_mode = "none"
             self.ReleaseMouse()
             return

        if self.edit_mode == "point":
             self._pt_drag_mode = "none"
             self.ReleaseMouse()
             return

        # Check if this was a click (not a drag) on a multi-selection
        if self._drag_start_world and not self._panning and not event.ShiftDown():
            pos_world = self.screen_to_world(event.GetPosition())
            dx = pos_world[0] - self._drag_start_world[0]
            dy = pos_world[1] - self._drag_start_world[1]
            dist_sq = dx*dx + dy*dy
            
            # If moved less than ~3 pixels, treat as click
            if dist_sq < 9: 
                clicked = self._hit_test(pos_world)
                if clicked and len(self.selected_fmodules) > 1:
                     self.selected_fmodules = [clicked.id]
                     if self.on_selection_changed:
                         self.on_selection_changed(self.selected_fmodules)
                     self.Refresh(False)

        if self.HasCapture():
            self.ReleaseMouse()
        self._dragging_ids = []
        self._drag_start_world = None

    # Interaction
    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        # 1. Handle Hover Cursor (always, even if not dragging, unless dragging overrides)
        if self.edit_mode == "collision" and not event.Dragging():
            # Check for resize handles
            cursor = wx.CURSOR_ARROW
            
            # Helper to find if over any selected rect handle
            handle_found = False
            for cid in self.selected_collision_rects:
                cr = next((r for r in self.frame.collision_rects if r.id == cid), None)
                if cr:
                    # _hit_test_handle uses screen coordinates
                    handle = self._hit_test_handle(cr, event.GetPosition())
                    if handle != -1:
                        # 0=TL, 1=TR, 2=BL, 3=BR
                        if handle == 0 or handle == 3:
                            cursor = wx.CURSOR_SIZENWSE
                        else:
                            cursor = wx.CURSOR_SIZENESW
                        handle_found = True
                        break
            
            if handle_found:
                self.SetCursor(wx.Cursor(cursor))
            else:
                self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        elif not self._dragging_ids and not self._col_drag_mode != "none":
             self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))

        if self._panning:
            self.handle_pan_motion(event)
            return
            
        if not event.Dragging() or not event.LeftIsDown():
            return

        if self.read_only:
             return
            
        pos_screen = event.GetPosition()
        pos_world = self.screen_to_world(pos_screen)
        
        if self.edit_mode == "collision":
            self._handle_collision_drag(pos_screen, pos_world)
            self.Refresh(False)
            return

        if self.edit_mode == "point":
             self._handle_point_drag(pos_screen)
             self.Refresh(False)
             return

        # Module Drag Logic
        if not self._dragging_ids:
            return
            
        current_world = self.screen_to_world(event.GetPosition())
        # We need local delta
        curr_local = self.world_to_local(current_world)
        start_local = self.world_to_local(self._drag_start_world)
        
        dx = curr_local[0] - start_local[0]
        dy = curr_local[1] - start_local[1]
        
        # Snap to grid: REMOVED
            
        for mid in self._dragging_ids:
            fm = next((f for f in self.frame.fmodules if f.id == mid), None)
            if fm:
                start_pos = self._drag_start_positions.get(mid, (0,0))
                fm.position = (int(start_pos[0] + dx), int(start_pos[1] + dy))
                
        self.Refresh(False)

    # Helpers
    def hit_test(self, transformed_world_pt: Tuple[float, float]) -> Optional[FModule]:
        # This one is called from outside, usually with a point that is already in local space?
        # No, hit_test typically takes a point that came from the screen.
        # But FrameEditorPanel calls it with screen_to_world(pos).
        # So we must convert to local.
        return self._hit_test(self.world_to_local(transformed_world_pt))

    def _hit_test(self, local_pt: Tuple[float, float]) -> Optional[FModule]:
        if not self.frame:
            return None
            
        # Iterate reversed (last in list = top, check timestamps first)
        for fm in reversed(self.frame.fmodules):
            x0, y0, x1, y1 = self._fmodule_bounds(fm)
            if x0 <= local_pt[0] <= x1 and y0 <= local_pt[1] <= y1:
                return fm
        return None

    def hit_test_all(self, transformed_world_pt: Tuple[float, float]) -> List[FModule]:
        """Returns all modules under the cursor, sorted top-to-bottom."""
        local_pt = self.world_to_local(transformed_world_pt)
        hits = []
        if not self.frame:
            return hits
            
        for fm in reversed(self.frame.fmodules):
            x0, y0, x1, y1 = self._fmodule_bounds(fm)
            if x0 <= local_pt[0] <= x1 and y0 <= local_pt[1] <= y1:
                hits.append(fm)
        return hits

    def _fmodule_bounds(self, fm: FModule) -> Tuple[float, float, float, float]:
        if fm.ref_type == "module":
            ref_id = fm.ref_id
            if self.project.active_mapping and ref_id in self.project.active_mapping.map:
                 ref_id = self.project.active_mapping.map[ref_id]
            
            mod: Optional[Module] = None
            if ref_id:
                mod = self.project.get_module(ref_id)
            
            if mod:
                w, h = mod.rect[2], mod.rect[3]
                piv_x, piv_y = mod.pivot
                
                # Apply Rotation to Bounds Logic
                # If rotated 90 or 270, w/h swap.
                # Pivot handling is complex since drawing rotates around pivot?
                # Actually, our draw logic rotates the bitmap.
                # The visual pivot point on screen is (pos_x, pos_y).
                # The bitmap is drawn such that the pivot is at (pos_x, pos_y).
                # So we just need to know the dimensions of the ROTATED bitmap
                # and finding the top-left relative to the pivot.
                
                rot = int(fm.rotation_degrees) % 360
                
                # Calculate dimensions of the rotated sprite
                if rot == 90 or rot == 270:
                    rw, rh = h, w
                else:
                    rw, rh = w, h
                    
                # The pivot in the unrotated sprite is (px, py).
                # In the rotated sprite, the "pivot pixel" is still the anchor.
                # We need to find the Top-Left of the bounding box relative to the anchor.
                
                # 0 deg: TL = (-px, -py)
                # 90 deg (CW): TL = (- (h - 1 - py), - px) ?
                # Let's derive:
                # Source pixel (u,v). Center (px, py).
                # 90 Rot: u' = h - 1 - v, v' = u.
                # Anchor (px, py) maps to (h-1-py, px) in the new image space.
                # So the new pivot inside the new image is (h-1-py, px).
                # The new bounds are 0..rw, 0..rh.
                # Top-Left relative to anchor is (-new_piv_x, -new_piv_y).
                
                if rot == 90:
                    # New W=h, H=w.
                    # Pivot maps to (h - py, px) roughly.
                    new_px = h - piv_y
                    new_py = piv_x
                elif rot == 180:
                    # New W=w, H=h.
                    # Pivot maps to (w - px, h - py)
                    new_px = w - piv_x
                    new_py = h - piv_y
                elif rot == 270:
                    # New W=h, H=w.
                    # Pivot maps to (py, w - px)
                    new_px = piv_y
                    new_py = w - piv_x
                else:
                    new_px, new_py = piv_x, piv_y
                
                top_left = (
                    fm.position[0] - new_px,
                    fm.position[1] - new_py,
                )
                
                # Note: we DON'T add self.frame_offset here because world_to_screen/local_to_world handles it.
                # Bounds represent LOCAL coordinates.
                return (top_left[0], top_left[1], top_left[0] + rw, top_left[1] + rh)
        
        elif fm.ref_type == "frame":
            # For frames, we ideally calculate the bounding box of all its children.
            # Avoid infinite recursion if possible.
            # Simplified: treat frame as having (0,0) as its pivot/origin.
            # Bounds = Union of child bounds relative to (0,0).
            # If expensive, cache it? For now, recompute.
            
            ref_frame = self.project.get_frame(fm.ref_id)
            if ref_frame:
                # We need bounds of ref_frame relative to ITS origin.
                # A frame's content is simply its fmodules positioned relative to (0,0).
                # So we iterate children, get their bounds (assuming 0,0 offset), and unite.
                
                min_x, min_y, max_x, max_y = 0, 0, 0, 0
                first = True
                
                for child_fm in ref_frame.fmodules:
                     # Get child bounds assuming NO parent offset (just local position)
                     # We can't safely call _fmodule_bounds directly because it adds self.frame_offset
                     # We need a helper that returns LOCAL bounds.
                     
                     # HACK: Temporarily set offset to 0? No, thread unsafe (if threaded).
                     # Duplicate logic for local calculation.
                     
                     # 1. Local Position
                     cx, cy = child_fm.position
                     cw, ch = 32, 32 # Default
                     piv_x, piv_y = 0, 0
                     
                     if child_fm.ref_type == "module":
                         m = self.project.get_module(child_fm.ref_id)
                         if m:
                             cw, ch = m.rect[2], m.rect[3]
                             piv_x, piv_y = m.pivot
                     elif child_fm.ref_type == "frame":
                          # Recursion? Limit depth.
                          # For now, approximate frames as 32x32 to avoid deep recalc lag
                          pass 

                     # Child Bounds = (cx - piv_x, cy - piv_y, cx - piv_x + cw, cy - piv_y + ch)
                     l = cx - piv_x
                     t = cy - piv_y
                     r = l + cw
                     b = t + ch
                     
                     if first:
                         min_x, min_y, max_x, max_y = l, t, r, b
                         first = False
                     else:
                         min_x = min(min_x, l)
                         min_y = min(min_y, t)
                         max_x = max(max_x, r)
                         max_y = max(max_y, b)
                
                if not first:
                     # LOCAL Bounds
                     return (min_x + fm.position[0], min_y + fm.position[1], max_x + fm.position[0], max_y + fm.position[1])

        # Fallback
        sz = 32
        return (
            fm.position[0] - sz / 2,
            fm.position[1] - sz / 2,
            fm.position[0] + sz / 2,
            fm.position[1] + sz / 2,
        )

    def _get_width(self, fm: FModule) -> int:
        bounds = self._fmodule_bounds(fm)
        # _fmodule_bounds uses offset, but width is invariant
        return int(bounds[2] - bounds[0])

    def _get_module_bitmap(self, mod: Module) -> Optional[wx.Bitmap]:
        if mod.id in self._bitmap_cache:
            return self._bitmap_cache[mod.id]
            
        asset = self.project.get_image(mod.image_id)
        if not asset:
            return None
            
        try:
            # Can we share cache with Palette? 
            # Ideally Project should hold the Asset cache (Images).
            # But we need Module-specific cropped bitmaps.
            
            # Load full image (cached? We'll rely on FS cache for now or add one later if slow)
            # Optimization: Cache logic is duplicate of Palette. Consolidate later.
            full_img = wx.Image(asset.file_path)
            if asset.transparent_color:
                full_img.SetMaskColour(*asset.transparent_color)
                
            rx, ry, rw, rh = mod.rect
            img_w, img_h = full_img.GetWidth(), full_img.GetHeight()
            
            if rx + rw <= img_w and ry + rh <= img_h:
                sub_img = full_img.GetSubImage(wx.Rect(rx, ry, rw, rh))
                bmp = sub_img.ConvertToBitmap()
                self._bitmap_cache[mod.id] = bmp
                return bmp
        except Exception as e:
            print(f"Canvas bmp load fail: {e}")
            return None
        return None

    def handle_dropped_module(self, ref_id: str, pos: wx.Point, ref_type: str = "module"):
        if not self.frame:
            if hasattr(self, 'on_create_frame_needed') and self.on_create_frame_needed:
                self.frame = self.on_create_frame_needed()
            
            if not self.frame:
                return
        
        # Cycle Detection for Frames
        if ref_type == "frame":
             if ref_id == self.frame.id:
                 wx.MessageBox("Cannot add a frame to itself!", "Loop Detected", wx.OK | wx.ICON_ERROR)
                 return
             
             if self.project.frame_has_cycle(self.frame.id, ref_id):
                 wx.MessageBox("Adding this frame would create a cycle!", "Loop Detected", wx.OK | wx.ICON_ERROR)
                 return

        world_pt = self.screen_to_world(pos)
        
        # New FModule
        fm = FModule(
            id=generate_id("fmod"), 
            ref_type=ref_type,
            ref_id=ref_id,
            position=(int(world_pt[0]), int(world_pt[1])),
            flip_x=False, flip_y=False
        )
        self.frame.fmodules.append(fm)
        self.Refresh(False)

    # --- Collision Logic ---
    def on_collision_left_down(self, event, pos_screen):
        pos_world = self.screen_to_world(pos_screen)
        # 1. Handle Resize?
        if len(self.selected_collision_rects) == 1:
            cid = self.selected_collision_rects[0]
            cr = next((r for r in self.frame.collision_rects if r.id == cid), None)
            if cr:
                handle = self._hit_test_handle(cr, pos_screen)
                if handle != -1:
                    self._col_drag_mode = "resize"
                    self._col_drag_handle = handle
                    self._col_drag_rect_id = cid
                    self._col_drag_start_rect = cr.rect
                    self._col_drag_start_screen = pos_screen # track delta
                    self._drag_start_world = pos_world # For delta calc mapping
                    self.CaptureMouse()
                    return

        # 2. Hit Test Rect
        hit_cr = self._hit_test_collision_rect(pos_world)
        if hit_cr:
             self.selected_collision_rects = [hit_cr.id]
             self._col_drag_mode = "move"
             self._col_drag_rect_id = hit_cr.id
             self._col_drag_start_rect = hit_cr.rect
             self._drag_start_world = pos_world
             self.CaptureMouse()
             self.Refresh(False)
             return
        
        # 3. Create
        # Fallback: If no active type set, try to pick first one
        if not self.active_collision_type_id and self.project.collision_types:
             first_type = self.project.collision_types[0]
             self.active_collision_type_id = first_type.id
             # Ensure valid locally for rendering immediately
             if first_type.id not in self.collision_type_colors:
                 self.collision_type_colors[first_type.id] = first_type.color

        if self.active_collision_type_id:
             # Create new rect
             new_id = generate_id("crect")
             # Start with 0 size
             x, y = int(pos_world[0] - self.frame_offset[0]), int(pos_world[1] - self.frame_offset[1])
             new_rect = CollisionRect(id=new_id, type_id=self.active_collision_type_id, rect=(x, y, 0, 0))
             self.frame.collision_rects.append(new_rect)
             self.selected_collision_rects = [new_id]
             
             self._col_drag_mode = "create"
             self._col_drag_rect_id = new_id
             # Store origin for creation
             self._col_drag_start_rect = (x, y, 0, 0) 
             self._drag_start_world = pos_world
             self.CaptureMouse()
             self.Refresh(False)
             
    def _handle_collision_drag(self, pos_screen, pos_world):
        if self._col_drag_mode == "none": return
        
        cr = next((r for r in self.frame.collision_rects if r.id == self._col_drag_rect_id), None)
        if not cr: return

        if self._col_drag_mode == "move":
             dx = int(pos_world[0] - self._drag_start_world[0])
             dy = int(pos_world[1] - self._drag_start_world[1])
             
             ox, oy, ow, oh = self._col_drag_start_rect
             cr.rect = (ox + dx, oy + dy, ow, oh)
             
        elif self._col_drag_mode == "create":
             # Origin was stored in start_rect (x, y)
             ox, oy = self._col_drag_start_rect[0], self._col_drag_start_rect[1]
             # Current world pos
             curr_x = int(pos_world[0] - self.frame_offset[0])
             curr_y = int(pos_world[1] - self.frame_offset[1])
             
             # Calculate top-left and size
             x = min(ox, curr_x)
             y = min(oy, curr_y)
             w = abs(curr_x - ox)
             h = abs(curr_y - oy)
             cr.rect = (x, y, w, h)
             
        elif self._col_drag_mode == "resize":
             dx = int(pos_world[0] - self._drag_start_world[0])
             dy = int(pos_world[1] - self._drag_start_world[1])
             ox, oy, ow, oh = self._col_drag_start_rect
             
             nx, ny, nw, nh = ox, oy, ow, oh
             
             h_idx = self._col_drag_handle
             if h_idx == 0: # TL
                 nx += dx; ny += dy; nw -= dx; nh -= dy
             elif h_idx == 1: # TR
                 ny += dy; nw += dx; nh -= dy
             elif h_idx == 2: # BL
                 nx += dx; nw -= dx; nh += dy
             elif h_idx == 3: # BR
                 nw += dx; nh += dy
                 
             if nw < 0: nw = 1 # Prevent flip for now
             if nh < 0: nh = 1
             
             cr.rect = (nx, ny, nw, nh)

    def _hit_test_collision_rect(self, world_pos):
        x, y = world_pos
        off_x, off_y = self.frame_offset
        for cr in reversed(self.frame.collision_rects):
             rx, ry, rw, rh = cr.rect
             r_world = wx.Rect(int(rx + off_x), int(ry + off_y), rw, rh)
             if r_world.Contains(int(x), int(y)):
                 return cr
        return None

    def _hit_test_handle(self, cr, screen_pos):
        # 0=TL, 1=TR, 2=BL, 3=BR
        rx, ry, rw, rh = cr.rect
        x0, y0 = rx + self.frame_offset[0], ry + self.frame_offset[1]
        
        corners = [
            (x0, y0), (x0+rw, y0), (x0, y0+rh), (x0+rw, y0+rh)
        ]
        
        mx, my = screen_pos
        sz = 8 
        for i, (wx_pt, wy_pt) in enumerate(corners):
            sx, sy = self.world_to_screen((wx_pt, wy_pt))
            if abs(mx - sx) <= sz and abs(my - sy) <= sz:
                return i
        return -1

    # Point Helpers
    def _hit_test_point(self, world_pos):
        x, y = world_pos
        off_x, off_y = self.frame_offset
        sz = 4.0 # Smaller radius for precision
        
        best_cp = None
        best_dist = float('inf')
        
        for cp in self.frame.control_points:
            # Simple dist check
            cpx, cpy = cp.x + off_x, cp.y + off_y
            dx = cpx - x
            dy = cpy - y
            dist_sq = dx*dx + dy*dy
            
            if dist_sq <= sz*sz:
                if dist_sq < best_dist:
                    best_dist = dist_sq
                    best_cp = cp
                    
        return best_cp

    def on_point_left_down(self, event, pos_screen):
        pos_world = self.screen_to_world(pos_screen)
        
        # Interaction Logic Split (User Request REVERSED):
        # Shift+Click: Force Creation (Place new point)
        # Click: Interaction (Select/Move existing)
        
        if not event.ShiftDown():
            # SELECTION / INTERACTION MODE
            cp = self._hit_test_point(pos_world)
            if cp:
                # If Cmd/Ctrl, toggle. Else replace.
                if event.CmdDown() or event.ControlDown():
                     if cp.id in self.selected_points:
                         self.selected_points.remove(cp.id)
                     else:
                         self.selected_points.append(cp.id)
                else:
                     if cp.id not in self.selected_points:
                         self.selected_points = [cp.id]
                         
                self._pt_drag_mode = "move"
                self._pt_drag_id = cp.id 
                self._drag_start_world = pos_world
                
                # Store start positions
                self._drag_start_positions = {}
                for pid in self.selected_points:
                     p = next((x for x in self.frame.control_points if x.id == pid), None)
                     if p:
                         self._drag_start_positions[pid] = (p.x, p.y)
                         
                self.CaptureMouse()
                self.Refresh()
            else:
                self.selected_points = []
                self.Refresh()
        else:
            # CREATION MODE (Shift held)
            if self.active_point_type_id:
                wx, wy = pos_world
                # Usage of math.floor ensures consistent Top-Left behavior 
                # even for negative coordinates, solving the 'bottom-left' bias issue.
                wx = int(math.floor(wx - self.frame_offset[0]))
                wy = int(math.floor(wy - self.frame_offset[1]))
                     
                new_cp = ControlPoint(
                    id=generate_id("pt"),
                    type_id=self.active_point_type_id,
                    x=wx,
                    y=wy
                )
                self.frame.control_points.append(new_cp)
                self.selected_points = [new_cp.id]
                
                # Enable immediate dragging for the new point
                self._pt_drag_mode = "move"
                self._pt_drag_id = new_cp.id
                self._drag_start_world = pos_world
                self._drag_start_positions = {new_cp.id: (wx, wy)}
                
                self.CaptureMouse()
                self.Refresh()
            else:
                self.selected_points = []
                self.Refresh()

    def _handle_point_drag(self, pos_screen):
        if self._pt_drag_mode == "move" and self._drag_start_world:
             pos_world = self.screen_to_world(pos_screen)
             
             dx = pos_world[0] - self._drag_start_world[0]
             dy = pos_world[1] - self._drag_start_world[1]
             
             # Snap REMOVED
             
             for pid in self.selected_points:
                 cp = next((p for p in self.frame.control_points if p.id == pid), None)
                 start = self._drag_start_positions.get(pid)
                 if cp and start:
                     cp.x = int(start[0] + dx)
                     cp.y = int(start[1] + dy)


class ModuleDropTarget(wx.TextDropTarget):
    def __init__(self, canvas: FrameCanvas):
        super().__init__()
        self.canvas = canvas

    def OnDropText(self, x, y, data):
        # We expect data to be "MODULE:<id>" or "FRAME_REF:<idx>:<id>"
        if data.startswith("MODULE:"):
            mid = data.split(":", 1)[1]
            self.canvas.handle_dropped_module(mid, wx.Point(x, y), ref_type="module")
            return True
        elif data.startswith("FRAME_REF:"):
            # FRAME_REF:<idx>:<id>
            parts = data.split(":")
            if len(parts) >= 3:
                fid = parts[2]
                self.canvas.handle_dropped_module(fid, wx.Point(x, y), ref_type="frame")
                return True
        return False

class AnimationCanvas(FrameCanvas):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project, read_only=True)
        self.animation: Optional[Animation] = None
        self.current_aframe: Optional[AFrame] = None
        self.show_trajectory: bool = True
        
        # Interaction State
        self._drag_start_offset: Optional[Tuple[int, int]] = None
        self.drag_start: Optional[Tuple[float, float]] = None
        # Interaction State
        self._drag_start_offset: Optional[Tuple[int, int]] = None
        self.drag_start: Optional[Tuple[float, float]] = None
        self.on_offset_change: Optional[Callable[[int, int], None]] = None # Callback (x, y)
        
        self.global_flip_x = False
        self.global_flip_y = False

    def set_animation(self, anim: Optional[Animation], aframe: Optional[AFrame] = None):
        self.animation = anim
        self.current_aframe = aframe
        self._update_frame()
        self.Refresh()

    def set_current_index(self, idx: int) -> None:
        if self.animation and self.animation.aframes and 0 <= idx < len(self.animation.aframes):
            self.current_aframe = self.animation.aframes[idx]
        else:
            self.current_aframe = None
        self._update_frame()
        self.Refresh()

    def _update_frame(self):
        if self.current_aframe:
            self.frame = self.project.get_frame(self.current_aframe.frame_id)
            
            # Apply Global Flip to Offset
            ox, oy = self.current_aframe.offset
            if self.global_flip_x: ox = -ox
            if self.global_flip_y: oy = -oy
            self.frame_offset = (ox, oy)
            
            # Apply Global Flip to Render (XOR)
            self.render_flip_x = self.current_aframe.flip_x != self.global_flip_x
            self.render_flip_y = self.current_aframe.flip_y != self.global_flip_y
            self.render_rotation = getattr(self.current_aframe, "rotation_degrees", 0.0)
        else:
            self.frame = None
            self.frame_offset = (0, 0)
            self.render_flip_x = False
            self.render_flip_y = False

    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if self.show_trajectory and self.animation:
            self._draw_trajectory(gc)
             
        if self.current_aframe and self.frame:
            # Note: FrameCanvas.draw_content now uses world_to_screen/screen_to_world
            # which we overridden in FrameCanvas to handle flip and offset.
            super().draw_content(gc)

    def _draw_trajectory(self, gc: wx.GraphicsContext) -> None:
        if not self.animation or not self.animation.aframes:
            return
        pts = []
        for af in self.animation.aframes:
            # Apply Global Flip to trajectory points
            ox, oy = af.offset
            if self.global_flip_x: ox = -ox
            if self.global_flip_y: oy = -oy
            world = (ox, oy)
            
            # We want the trajectory in RAW world space, NOT affected by current frame's flipping/offsetting.
            pts.append(BaseCanvas.world_to_screen(self, world))
        if len(pts) < 2:
            return
        gc.SetPen(wx.Pen(wx.Colour(100, 120, 220), width=2))
        
        path = gc.CreatePath()
        path.MoveToPoint(*pts[0])
        for pt in pts[1:]:
            path.AddLineToPoint(*pt)
        gc.StrokePath(path)
        
        # Highlight points
        # Draw points (inactive first, then active)
        active_pt = None
        
        # Inactive points
        gc.SetBrush(wx.Brush(wx.Colour(80, 80, 80)))
        for idx, (sx, sy) in enumerate(pts):
            if self.current_aframe == self.animation.aframes[idx]:
                active_pt = (sx, sy)
                continue
            gc.DrawEllipse(sx - 4, sy - 4, 8, 8)
            
        # Active point (on top)
        if active_pt:
            gc.SetBrush(wx.Brush(wx.Colour(40, 160, 80)))
            gc.DrawEllipse(active_pt[0] - 4, active_pt[1] - 4, 8, 8)
            
            # Additional visual indicator for selected frame (white ring)
            gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 2))
            gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 0))) # Transparent
            gc.DrawEllipse(active_pt[0] - 6, active_pt[1] - 6, 12, 12)

    def on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus() # Steal focus from inputs to trigger validation
        # Allow panning if Alt is down (standard Mac behavior) or Control or Middle button
        if event.AltDown() or event.ControlDown() or event.MiddleIsDown():
            self._panning = True
            self._start = event.GetPosition() # MUST match BaseCanvas.handle_pan_motion expected attr
            self.CaptureMouse()
            return

        pos = self.screen_to_world(event.GetPosition())
        if self.current_aframe:
            self.drag_start = pos
            self._drag_start_offset = self.current_aframe.offset
            try:
                self.CaptureMouse()
            except: pass
        else:
            event.Skip()

    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        if self._panning:
             self.handle_pan_motion(event)
             return

        # Reset cursor if not dragging collision handles (managed by Base/FrameCanvas logic usually)
        # But we are overriding here.
        
        if not event.Dragging() or not event.LeftIsDown():
             return
        
        if self.current_aframe and self.drag_start and self._drag_start_offset:
            curr = self.screen_to_world(event.GetPosition())
            
            # Use ROUND to properly snap to nearest integer world coordinate
            # instead of int() truncation which feels slippery/deadzony
            dx = round(curr[0] - self.drag_start[0])
            dy = round(curr[1] - self.drag_start[1])
            
            # Apply Global Flip Drag Correction
            # If we are viewing mirrored X, dragging right (positive dx) means we want the object 
            # to move visually right.
            # But visually right is negative X in model space if flipped.
            # So we invert dx.
            if self.global_flip_x: dx = -dx
            if self.global_flip_y: dy = -dy
            
            new_x = self._drag_start_offset[0] + dx
            new_y = self._drag_start_offset[1] + dy
            
            # CRITICAL: Sync both the AFrame model AND the FrameCanvas transform state
            self.current_aframe.offset = (new_x, new_y)
            
            # For render state, we must re-apply the global flip to the new model offset
            render_ox = new_x
            render_oy = new_y
            if self.global_flip_x: render_ox = -render_ox
            if self.global_flip_y: render_oy = -render_oy
            
            self.frame_offset = (render_ox, render_oy)
            
            if self.on_offset_change:
                self.on_offset_change(new_x, new_y)
                
            self.Refresh()
            return
            
        event.Skip()

    def on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
             self.on_pan_end(event) # Resets _panning and ReleaseMouse
             return

        if self.HasCapture():
            self.ReleaseMouse()
        self.drag_start = None
        self._drag_start_offset = None
        event.Skip()
