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

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.frame: Optional[Frame] = None
        self.selected_fmodules: list[str] = []
        self.show_collision = False # Default hidden in module mode
        self.show_control_points = True
        self.on_selection_changed: Optional[Callable[[list[str]], None]] = None
        
        self._dragging_ids: list[str] = []
        self._drag_start_world: Optional[Tuple[float, float]] = None
        self._drag_start_positions: dict[str, Tuple[int, int]] = {}
        
        self.frame_offset: Tuple[float, float] = (0.0, 0.0)
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
        sx0, sy0 = self.world_to_screen((x0, y0))
        sx1, sy1 = self.world_to_screen((x1, y1))
        w, h = sx1 - sx0, sy1 - sy0
        
        # Draw image content if module ref
        if fm.ref_type == "module":
             mod = self.project.get_module(fm.ref_id)
             if mod:
                 bmp = self._get_module_bitmap(mod)
                 if bmp:
                     # High Quality (Nearest Neighbor) Scaling hack for GraphicsContext
                     target_w, target_h = int(round(w)), int(round(h))
                     if target_w > 0 and target_h > 0:
                         img = bmp.ConvertToImage()
                         
                         # Apply flipping
                         if fm.flip_x:
                             img = img.Mirror(horizontally=True)
                         if fm.flip_y:
                             img = img.Mirror(horizontally=False) # Vertical flip
                             
                         img.Rescale(target_w, target_h, wx.IMAGE_QUALITY_NEAREST)
                         scaled_bmp = img.ConvertToBitmap()
                         
                         gc.DrawBitmap(scaled_bmp, sx0, sy0, target_w, target_h)
        
        elif fm.ref_type == "frame":
            # Nested Frame Rendering
            # This is complex because we need to apply the parent's transformation AND screen projection.
            # Ideally, we'd use GC transforms, but our "world_to_screen" is custom.
            # So we pass "recursive offset" ? 
            # OR we just use a temporary override of frame_offset?
            # Actually, reusing _draw_fmodule_content recursively is tricky because it assumes "self.frame" context?
            # No, it effectively renders "fm" which HAS position.
            
            # To render child frame's modules, we need to iterate them.
            # But they are relative to child frame origin.
            # "fm" places that origin at (fm.x, fm.y) in CURRENT frame.
            # So child module at (cx, cy) becomes (fm.x + cx, fm.y + cy) (ignoring flip for a moment).
            
            ref_frame = self.project.get_frame(fm.ref_id)
            if ref_frame:
                # Iterate children
                for child_fm in ref_frame.fmodules:
                    # CLONE child_fm to apply local transform
                    # This avoids modifying the actual model
                    # Position = ParentPos + ApplyFlip(ChildPos)
                    
                    cx, cy = child_fm.position
                    
                    # Apply parent flip
                    if fm.flip_x:
                        cx = -cx - self._get_width(child_fm) # Reflect around 0? No, around center?
                        # Wait, pivot handling for frames is implicit (0,0).
                        # If a frame is flipped X, the X-axis is inverted.
                        # (10, 10) becomes (-10, 10) ?
                        # And we must also ACCOUNT FOR MODULE WIDTH if pivoting at topleft?
                        # NO, our coordinate system seems to be center-based or top-left?
                        # Modules have Pivots. FModules have Position (offset from Frame Origin).
                        # If I flip a Frame, I flip all its children positions.
                        cx = -cx
                        # AND I might need to offset if specific pivot logic applies?
                        # Standard "Flip around Y axis" = x -> -x.
                        
                    if fm.flip_y:
                        cy = -cy

                    # Combine flips
                    final_flip_x = child_fm.flip_x ^ fm.flip_x
                    final_flip_y = child_fm.flip_y ^ fm.flip_y
                    
                    # Create temporary proxy
                    # We need to construct a "Visual FModule" that is effectively
                    # "fm" merged with "child_fm".
                    nx = fm.position[0] + cx
                    ny = fm.position[1] + cy
                    
                    # Note: Rotation not supported yet per model?
                    
                    # We can't easily instantiate FModule without ID etc.
                    # But _draw_fmodule_content takes an FModule.
                    # Let's mock it or create a temporary one.
                    
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
        sx0, sy0 = self.world_to_screen((x0, y0))
        sx1, sy1 = self.world_to_screen((x1, y1))
        w, h = sx1 - sx0, sy1 - sy0

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
        x0, y0 = rx + self.frame_offset[0], ry + self.frame_offset[1]
        
        sx0, sy0 = self.world_to_screen((x0, y0))
        sx1, sy1 = self.world_to_screen((x0 + rw, y0 + rh))
        w, h = sx1 - sx0, sy1 - sy0
        
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
        
        # FIX: Add frame offset!
        sx, sy = self.world_to_screen((cp.x + self.frame_offset[0], cp.y + self.frame_offset[1]))
        
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
            
        pos_screen = event.GetPosition()
        pos_world = self.screen_to_world(pos_screen)
        # Collision Interaction
        if self.edit_mode == "collision":
            self.on_collision_left_down(event, pos_screen)
            return
            
        # Point Interaction
        if self.edit_mode == "point":
            self.on_point_left_down(event, pos_screen)
            return

        # Module Selection Logic (Default)
        clicked = self._hit_test(pos_world)
        
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
        dx = current_world[0] - self._drag_start_world[0]
        dy = current_world[1] - self._drag_start_world[1]
        
        # Snap to grid: REMOVED
            
        for mid in self._dragging_ids:
            fm = next((f for f in self.frame.fmodules if f.id == mid), None)
            if fm:
                start_pos = self._drag_start_positions.get(mid, (0,0))
                fm.position = (int(start_pos[0] + dx), int(start_pos[1] + dy))
                
        self.Refresh(False)

    # Helpers
    def hit_test(self, world_pt: Tuple[float, float]) -> Optional[FModule]:
        return self._hit_test(world_pt)

    def _hit_test(self, world_pt: Tuple[float, float]) -> Optional[FModule]:
        if not self.frame:
            return None
            
        # Iterate reversed (last in list = top, check timestamps first)
        for fm in reversed(self.frame.fmodules):
            x0, y0, x1, y1 = self._fmodule_bounds(fm)
            if x0 <= world_pt[0] <= x1 and y0 <= world_pt[1] <= y1:
                return fm
        return None

    def _fmodule_bounds(self, fm: FModule) -> Tuple[float, float, float, float]:
        if fm.ref_type == "module":
            mod: Optional[Module] = self.project.get_module(fm.ref_id)
            if mod:
                w, h = mod.rect[2], mod.rect[3]
                # Pivot aligned
                top_left = (
                    fm.position[0] + self.frame_offset[0] - mod.pivot[0],
                    fm.position[1] + self.frame_offset[1] - mod.pivot[1],
                )
                return (top_left[0], top_left[1], top_left[0] + w, top_left[1] + h)
        
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
                     # Translate by current FM position + offset
                     off_x = fm.position[0] + self.frame_offset[0]
                     off_y = fm.position[1] + self.frame_offset[1]
                     return (min_x + off_x, min_y + off_y, max_x + off_x, max_y + off_y)

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
    """Canvas that renders the currently selected animation frame and trajectory."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project)
        self.animation = None
        self.current_index = 0
        self.show_trajectory = True

    def set_animation(self, animation) -> None:
        self.animation = animation
        self.current_index = 0
        self._update_current_frame()

    def set_current_index(self, idx: int) -> None:
        self.current_index = max(0, idx)
        self._update_current_frame()

    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if self.show_trajectory and self.animation:
            self._draw_trajectory(gc)
        super().draw_content(gc)

    def _draw_trajectory(self, gc: wx.GraphicsContext) -> None:
        if not self.animation or not self.animation.aframes:
            return
        pts = []
        for af in self.animation.aframes:
            world = (af.offset[0], af.offset[1])
            pts.append(self.world_to_screen(world))
        if len(pts) < 2:
            return
        gc.SetPen(wx.Pen(wx.Colour(100, 120, 220), width=2))
        gc.DrawLines(pts)
        for idx, (sx, sy) in enumerate(pts):
            color = wx.Colour(40, 160, 80) if idx == self.current_index else wx.Colour(80, 80, 80)
            gc.SetBrush(wx.Brush(color))
            gc.DrawEllipse(sx - 4, sy - 4, 8, 8)

    def _update_current_frame(self) -> None:
        if not self.animation or not self.animation.aframes:
            self.set_frame_offset((0.0, 0.0))
            self.set_frame(None)
            return
        idx = self.current_index % len(self.animation.aframes)
        aframe = self.animation.aframes[idx]
        frame = self.project.get_frame(aframe.frame_id)
        if frame:
            self.set_frame_offset((aframe.offset[0], aframe.offset[1]))
            self.set_frame(frame)
        else:
            self.set_frame(None)
