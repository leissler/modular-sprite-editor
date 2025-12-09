"""Canvas widgets used by the frame and animation editors."""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

import wx

from models import Frame, FModule, Module, Project
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
        self.show_collision = True
        self.show_control_points = True
        self.on_selection_changed: Optional[Callable[[list[str]], None]] = None
        
        self._dragging_ids: list[str] = []
        self._drag_start_world: Optional[Tuple[float, float]] = None
        self._drag_start_positions: dict[str, Tuple[int, int]] = {}
        
        self.frame_offset: Tuple[float, float] = (0.0, 0.0)
        self._bitmap_cache: dict[str, wx.Bitmap] = {}
        
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
        
        # Draw modules in list order (first in list = back, drawn first)
        for fm in self.frame.fmodules:
            self._draw_fmodule_content(gc, fm)
            
        # Pas 2: Draw Selection Overlays (on top of all content)
        for fm in self.frame.fmodules:
            if fm.id in self.selected_fmodules:
                self._draw_fmodule_overlay(gc, fm)
            
        if self.show_collision:
            for rect in self.frame.collision_rects:
                self._draw_collision(gc, rect)
        if self.show_control_points:
            for cp in self.frame.control_points:
                self._draw_control_point(gc, cp)

    def _draw_message(self, gc: wx.GraphicsContext, text: str) -> None:
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(80, 80, 80))
        tw, th = gc.GetTextExtent(text)
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        gc.DrawText(text, cx - tw / 2, cy - th / 2)

    def _draw_fmodule_content(self, gc: wx.GraphicsContext, fm: FModule) -> None:
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
        
    def _draw_collision(self, gc: wx.GraphicsContext, rect) -> None:
        x0, y0 = rect.x + self.frame_offset[0], rect.y + self.frame_offset[1]
        x1, y1 = x0 + rect.width, y0 + rect.height
        sx0, sy0 = self.world_to_screen((x0, y0))
        sx1, sy1 = self.world_to_screen((x1, y1))
        gc.SetPen(wx.Pen(wx.Colour(200, 60, 60), style=wx.PENSTYLE_LONG_DASH))
        gc.SetBrush(wx.Brush(wx.Colour(200, 60, 60, 40)))
        gc.DrawRectangle(sx0, sy0, sx1 - sx0, sy1 - sy0)

    def _draw_control_point(self, gc: wx.GraphicsContext, cp) -> None:
        sx, sy = self.world_to_screen((cp.x + self.frame_offset[0], cp.y + self.frame_offset[1]))
        gc.SetBrush(wx.Brush(wx.Colour(40, 150, 60)))
        gc.SetPen(wx.Pen(wx.Colour(20, 90, 40)))
        size = 6
        gc.DrawEllipse(sx - size / 2, sy - size / 2, size, size)

    # Interaction
    def on_left_down(self, event: wx.MouseEvent) -> None:
        if self._panning or event.AltDown(): # Handled by BaseCanvas or caller? Base handles Middle.
             # BaseCanvas doesn't handle Left+Alt by default, needs override or call
             if event.AltDown():
                 self.on_pan_start(event) # Reuse pan logic
                 return
        
        if not self.frame:
            return
            
        pos_world = self.screen_to_world(event.GetPosition())
        clicked = self._hit_test(pos_world)
        
        if clicked:
            self.selected_fmodules = [clicked.id]
            self._dragging_ids = [clicked.id]
            self._drag_start_world = pos_world
            self._drag_start_positions = {clicked.id: clicked.position}
            self.CaptureMouse()
            if self.on_selection_changed:
                self.on_selection_changed(self.selected_fmodules)
        else:
            self.selected_fmodules = []
            if self.on_selection_changed:
                self.on_selection_changed([])
        self.Refresh(False)

    def on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
            self.on_pan_end(event)
        
        if self.HasCapture():
            self.ReleaseMouse()
        self._dragging_ids = []
        self._drag_start_world = None

    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        # Check BaseCanvas pan first
        if self.handle_pan_motion(event):
            return

        if not self.frame or not self._dragging_ids or not event.Dragging():
            return
            
        current_world = self.screen_to_world(event.GetPosition())
        dx = current_world[0] - self._drag_start_world[0]
        dy = current_world[1] - self._drag_start_world[1]
        
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
        
        # Fallback or Frame ref
        sz = 32
        return (
            fm.position[0] - sz / 2,
            fm.position[1] - sz / 2,
            fm.position[0] + sz / 2,
            fm.position[1] + sz / 2,
        )

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

    def handle_dropped_module(self, module_id: str, pos: wx.Point):
        if not self.frame:
            if hasattr(self, 'on_create_frame_needed') and self.on_create_frame_needed:
                self.frame = self.on_create_frame_needed()
            
            if not self.frame:
                return
        
        world_pt = self.screen_to_world(pos)
        
        # New FModule
        fm = FModule(
            id=f"fm_{int(math.floor(math.fabs(hash(module_id + str(len(self.frame.fmodules))))))}", 
            # Simple ID gen, ideally use models.generate_id if available or inject
            ref_type="module",
            ref_id=module_id,
            position=(int(world_pt[0]), int(world_pt[1])),
            flip_x=False, flip_y=False, rotation_degrees=0.0
        )
        self.frame.fmodules.append(fm)
        self.Refresh(False)


class ModuleDropTarget(wx.TextDropTarget):
    def __init__(self, canvas: FrameCanvas):
        super().__init__()
        self.canvas = canvas

    def OnDropText(self, x, y, data):
        # We expect data to be "MODULE:<id>"
        if data.startswith("MODULE:"):
            mid = data.split(":", 1)[1]
            self.canvas.handle_dropped_module(mid, wx.Point(x, y))
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
