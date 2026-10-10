"""Canvas widgets used by the frame and animation editors."""

from __future__ import annotations

import math
from collections import OrderedDict
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import wx

from models import AFrame, Animation, Frame, FModule, Module, Project, CollisionRect, ControlPoint, generate_id
from ui.base_canvas import BaseCanvas
from ui.utils import render_pixel_shape_to_bitmap, load_wx_image_safely

Color = Tuple[int, int, int]

# Onion-skin styles: (red, green, blue, alpha) channel factors applied to ghost images.
GHOST_PREVIOUS = (1.0, 0.55, 0.55, 0.38)
GHOST_NEXT = (0.55, 0.75, 1.0, 0.38)
GHOST_REFERENCE = (1.0, 1.0, 1.0, 0.35)

# Upper bound for cached zoomed bitmaps, in screen pixels (~4 bytes each).
SCALED_CACHE_PIXEL_BUDGET = 24_000_000


def _orthogonal_cos_sin(degrees: float) -> Tuple[float, float]:
    """cos/sin with exact values at 90° steps (avoids off-by-one pixels from float residue)."""
    quarter = float(degrees) / 90.0
    if abs(quarter - round(quarter)) < 1e-9:
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(round(quarter)) % 4]
    rad = math.radians(float(degrees))
    return math.cos(rad), math.sin(rad)


def _mask_to_alpha(img: wx.Image) -> wx.Image:
    """Fold a mask colour into the alpha channel (tinting would otherwise un-mask it)."""
    if not img.HasMask():
        if not img.HasAlpha():
            img.InitAlpha()
        return img
    if not img.HasAlpha():
        img.InitAlpha()  # converts the mask
        return img
    mr, mg, mb = img.GetMaskRed(), img.GetMaskGreen(), img.GetMaskBlue()
    data = img.GetData()
    alpha = bytearray(img.GetAlpha())
    for i in range(len(alpha)):
        j = i * 3
        if data[j] == mr and data[j + 1] == mg and data[j + 2] == mb:
            alpha[i] = 0
    img.SetAlpha(bytes(alpha))
    img.SetMask(False)
    return img


def _color_from_id(identifier: str) -> Color:
    seed = sum(ord(c) for c in identifier)
    return ((seed * 37) % 200 + 30, (seed * 57) % 200 + 30, (seed * 97) % 200 + 30)

class FrameCanvas(BaseCanvas):
    """Canvas that can render a Frame and support selection/move of FModules."""

    def __init__(self, parent: wx.Window, project: Project, read_only: bool = False):
        super().__init__(parent)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT) # Critical for Mac/Win behavior
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
        self._last_module_hit_cycle_key: Optional[Tuple[int, int, Tuple[str, ...]]] = None
        self._last_module_hit_cycle_index: int = -1
        self._selected_hit_on_mouse_down_id: Optional[str] = None
        
        self.on_modify_started: Optional[Callable[[], None]] = None
        self.on_modify_ended: Optional[Callable[[], None]] = None
        
        self.frame_offset: Tuple[float, float] = (0.0, 0.0)
        self.render_flip_x = False
        self.render_flip_y = False
        self.render_rotation = 0.0
        self._bitmap_cache: dict[str, wx.Bitmap] = {}
        self._asset_image_cache: dict[str, wx.Image] = {}
        # Zoomed/flipped/rotated module bitmaps, so paints during drags do not rescale images.
        self._scaled_cache: "OrderedDict[Any, wx.Bitmap]" = OrderedDict()
        self._scaled_cache_pixels = 0
        # Active ghost style while drawing onion-skin layers (None = normal drawing).
        self._ghost_style: Optional[Tuple[float, float, float, float]] = None
        # Onion-skin layers drawn under the current frame:
        # dicts with frame, offset, flip_x, flip_y, rotation, style.
        self.ghost_layers: List[Dict[str, Any]] = []
        
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
        self._reset_module_hit_cycle()
        self._selected_hit_on_mouse_down_id = None
        self.Refresh(False)

    def set_frame_offset(self, offset: Tuple[float, float]) -> None:
        self.frame_offset = offset
        self.Refresh(False)
        
    def clear_cache(self) -> None:
        self._bitmap_cache.clear()
        self._asset_image_cache.clear()
        self._scaled_cache.clear()
        self._scaled_cache_pixels = 0
        self.Refresh(False)

    def _remember_scaled(self, key: Any, bmp: wx.Bitmap) -> None:
        pixels = bmp.GetWidth() * bmp.GetHeight()
        self._scaled_cache[key] = bmp
        self._scaled_cache_pixels += pixels
        while self._scaled_cache_pixels > SCALED_CACHE_PIXEL_BUDGET and len(self._scaled_cache) > 1:
            _old_key, old_bmp = self._scaled_cache.popitem(last=False)
            self._scaled_cache_pixels -= old_bmp.GetWidth() * old_bmp.GetHeight()

    @contextmanager
    def frame_transform(
        self,
        frame: Optional[Frame],
        offset: Tuple[float, float] = (0.0, 0.0),
        flip_x: bool = False,
        flip_y: bool = False,
        rotation: float = 0.0,
        ghost_style: Optional[Tuple[float, float, float, float]] = None,
    ) -> Iterator[None]:
        """Temporarily render another frame with its own transform (onion skin, bounds)."""
        saved = (self.frame, self.frame_offset, self.render_flip_x, self.render_flip_y, self.render_rotation, self._ghost_style)
        self.frame = frame
        self.frame_offset = offset
        self.render_flip_x = flip_x
        self.render_flip_y = flip_y
        self.render_rotation = rotation
        self._ghost_style = ghost_style
        try:
            yield
        finally:
            (self.frame, self.frame_offset, self.render_flip_x, self.render_flip_y,
             self.render_rotation, self._ghost_style) = saved

    def _draw_ghost_layers(self, gc: wx.GraphicsContext) -> None:
        for layer in self.ghost_layers:
            frame = layer.get("frame")
            if not frame:
                continue
            with self.frame_transform(
                frame,
                layer.get("offset", (0.0, 0.0)),
                bool(layer.get("flip_x", False)),
                bool(layer.get("flip_y", False)),
                float(layer.get("rotation", 0.0)),
                layer.get("style", GHOST_REFERENCE),
            ):
                for fm in frame.fmodules:
                    self._draw_fmodule_content(gc, fm)

    def _frame_world_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        if not self.frame:
            return None
        points: List[Tuple[float, float]] = []
        for fm in self.frame.fmodules:
            x0, y0, x1, y1 = self._fmodule_bounds(fm)
            points.append(self.local_to_world((x0, y0)))
            points.append(self.local_to_world((x1, y1)))
        for cr in self.frame.collision_rects:
            rx, ry, rw, rh = cr.rect
            points.append(self.local_to_world((rx, ry)))
            points.append(self.local_to_world((rx + rw, ry + rh)))
        for cp in self.frame.control_points:
            points.append(self.local_to_world((cp.x, cp.y)))
            points.append(self.local_to_world((cp.x + 1, cp.y + 1)))
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (min(xs), min(ys), max(xs), max(ys))

    def get_content_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        return self._frame_world_bounds()

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
        rot = int(round(self.render_rotation)) % 360
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
        rot = int(round(self.render_rotation)) % 360
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
        if self.show_transparency:
            self._draw_checkerboard(dc)
            
        gc = wx.GraphicsContext.Create(dc)
        self._draw_grid(gc)
        self.draw_content(gc)

    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if not self.frame:
            self._draw_message(gc, "No frame selected")
            return
        
        self._draw_ghost_layers(gc)

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
             
        # Draw Collision Rects
        # Always visible if show_collision or in collision mode
        if self.show_collision or self.edit_mode == "collision":
            for cr in self.frame.collision_rects:
                # Check visibility map
                # If id not in map, it's hidden. If in map, we get color.
                if cr.type_id not in self.collision_type_colors:
                     continue
                     
                self._draw_collision(gc, cr)
                
        # Selection Overlays for Modules (Drawn ON TOP of collision rects)
        if self.edit_mode == "module":
            for fm in self.frame.fmodules:
                if fm.id in self.selected_fmodules:
                    self._draw_fmodule_overlay(gc, fm)
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
                     # Nearest-neighbour scaling done on the image (GraphicsContext would smooth).
                     target_w, target_h = int(round(w)), int(round(h))
                     if target_w > 0 and target_h > 0:
                         # Combine local flip with frame-level flip; pixel-perfect 90° steps.
                         # A mirrored frame transform reverses the direction of the part's rotation.
                         final_flip_x = fm.flip_x ^ self.render_flip_x
                         final_flip_y = fm.flip_y ^ self.render_flip_y
                         frame_mirrored = self.render_flip_x ^ self.render_flip_y
                         part_rot = -fm.rotation_degrees if frame_mirrored else fm.rotation_degrees
                         rot = int(round(part_rot + self.render_rotation)) % 360
                         cache_key = (
                             self._module_bitmap_key(mod), final_flip_x, final_flip_y, rot,
                             target_w, target_h, self._ghost_style,
                         )
                         scaled_bmp = self._scaled_cache.get(cache_key)
                         if scaled_bmp is None:
                             img = bmp.ConvertToImage()
                             if final_flip_x:
                                 img = img.Mirror(horizontally=True)
                             if final_flip_y:
                                 img = img.Mirror(horizontally=False)
                             if rot == 90:
                                 img = img.Rotate90(clockwise=True)
                             elif rot == 180:
                                 img = img.Rotate180()
                             elif rot == 270:
                                 img = img.Rotate90(clockwise=False)
                             if self._ghost_style:
                                 img = _mask_to_alpha(img)
                                 r, g, b, a = self._ghost_style
                                 img = img.AdjustChannels(r, g, b, a)
                             img.Rescale(target_w, target_h, wx.IMAGE_QUALITY_NEAREST)
                             scaled_bmp = img.ConvertToBitmap()
                             self._remember_scaled(cache_key, scaled_bmp)
                         else:
                             self._scaled_cache.move_to_end(cache_key)

                         gc.DrawBitmap(scaled_bmp, sx0, sy0, target_w, target_h)
                     
        elif fm.ref_type == "frame":
             ref_frame = self.project.get_frame(fm.ref_id)
             if ref_frame:
                 # A nested frame is a geometric transform (flip, then rotate) about its anchor.
                 # Each child is re-expressed as a part of this frame with the combined
                 # transform, placed so its bounds land where the transformed child bounds are
                 # (the same rule _fmodule_bounds and hit-testing use).
                 p_flip_x = fm.flip_x
                 p_flip_y = fm.flip_y
                 p_rot = fm.rotation_degrees
                 p_pos_x, p_pos_y = fm.position
                 cos_a, sin_a = _orthogonal_cos_sin(p_rot)
                 is_parent_flipped = p_flip_x ^ p_flip_y

                 for child_fm in ref_frame.fmodules:
                    cx0, cy0, cx1, cy1 = self._fmodule_bounds(child_fm)
                    ts_x: List[float] = []
                    ts_y: List[float] = []
                    for px, py in ((cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1)):
                        if p_flip_x:
                            px = -px
                        if p_flip_y:
                            py = -py
                        ts_x.append(px * cos_a - py * sin_a)
                        ts_y.append(px * sin_a + py * cos_a)

                    child_rot = child_fm.rotation_degrees
                    final_rot = p_rot + (-child_rot if is_parent_flipped else child_rot)
                    final_flip_x = child_fm.flip_x ^ p_flip_x
                    final_flip_y = child_fm.flip_y ^ p_flip_y

                    probe = FModule(
                        id="temp",
                        ref_type=child_fm.ref_type,
                        ref_id=child_fm.ref_id,
                        position=(0, 0),
                        flip_x=final_flip_x,
                        flip_y=final_flip_y,
                        rotation_degrees=final_rot,
                    )
                    local_min_x, local_min_y, _x1, _y1 = self._fmodule_bounds(probe)
                    probe.position = (
                        int(round(p_pos_x + min(ts_x) - local_min_x)),
                        int(round(p_pos_y + min(ts_y) - local_min_y)),
                    )
                    self._draw_fmodule_content(gc, probe, depth + 1)

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

        role = str(getattr(cr, "role", "") or "").strip()
        if role and self.edit_mode == "collision":
            gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(255, 255, 255))
            gc.DrawText(role, sx0 + 3, max(0, sy0 - 16))
        
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
        
        # Visual Config
        pixel_size = max(1, self.zoom)
        
        # 1. Draw Square around the pixel
        # Use Rounding to align with grid
        dsx = round(sx)
        dsy = round(sy)
        dsize = round(pixel_size)
        
        # Fill with semi-transparent color if unselected, solid if selected?
        # Module editor uses transparent brush for pivot.
        # But for control points, we might want them visible.
        # Let's use transparent brush but solid pen for the square, same as pivot.
        
        gc.SetBrush(wx.Brush(wx.Colour(r, g, b, 80))) # Slight tint
        
        is_selected = cp.id in self.selected_points
        
        if is_selected:
             gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), width=2))
        else:
             gc.SetPen(wx.Pen(wx.Colour(r, g, b), width=1))
             
        gc.DrawRectangle(dsx, dsy, dsize, dsize)
        
        # 2. Draw Crosshair centered on the pixel
        # Make it slightly larger than the square
        cx = dsx + dsize / 2
        cy = dsy + dsize / 2
        
        # Extend by fixed amount (e.g. 6px) outside the square
        ext = 6
        half_len = (dsize / 2) + ext
        
        if is_selected:
            gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), width=2))
        else:
            gc.SetPen(wx.Pen(wx.Colour(r, g, b), width=2))
            
        gc.StrokeLine(cx - half_len, cy, cx + half_len, cy)
        gc.StrokeLine(cx, cy - half_len, cx, cy + half_len)

        role = str(getattr(cp, "role", "") or "").strip()
        if role and self.edit_mode == "point":
            gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(255, 255, 255))
            gc.DrawText(role, dsx + dsize + 4, dsy - 2)

    # Interaction
    def on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        if self.begin_pan_if_requested(event):
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
        hits = self._hit_test_all_local(local_pos)
        clicked: Optional[FModule] = None
        if hits:
            if event.ShiftDown():
                clicked = hits[0]
                self._reset_module_hit_cycle()
                self._selected_hit_on_mouse_down_id = None
            else:
                selected_hit = next((fm for fm in hits if fm.id in self.selected_fmodules), None)
                if selected_hit:
                    # Preserve selected target for immediate drag; click-cycle is handled on mouse-up.
                    clicked = selected_hit
                    self._selected_hit_on_mouse_down_id = selected_hit.id
                else:
                    self._selected_hit_on_mouse_down_id = None
                    cycle_key = (
                        int(math.floor(local_pos[0])),
                        int(math.floor(local_pos[1])),
                        tuple(fm.id for fm in hits),
                    )
                    if cycle_key == self._last_module_hit_cycle_key:
                        self._last_module_hit_cycle_index = (self._last_module_hit_cycle_index + 1) % len(hits)
                    else:
                        self._last_module_hit_cycle_key = cycle_key
                        self._last_module_hit_cycle_index = 0
                    clicked = hits[self._last_module_hit_cycle_index]
        else:
            self._reset_module_hit_cycle()
            self._selected_hit_on_mouse_down_id = None
        
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
            
            # Snapshot before potential drag
            if self.on_modify_started:
                self.on_modify_started()
                
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
        was_modifying = False
        
        if self._panning:
            self.on_pan_end(event)
            return
            
        if self.edit_mode == "collision":
             if self._col_drag_mode != "none":
                 was_modifying = True
             self._col_drag_mode = "none"
             self._col_drag_rect_id = None
             self._col_drag_handle = -1
             self._drag_start_world = None
             if self.HasCapture():
                 self.ReleaseMouse()
             if was_modifying and self.on_modify_ended: self.on_modify_ended()
             return

        if self.edit_mode == "point":
             if self._pt_drag_mode != "none":
                 was_modifying = True
             self._pt_drag_mode = "none"
             self._pt_drag_id = None
             self._drag_start_world = None
             self._drag_start_positions = {}
             if self.HasCapture():
                 self.ReleaseMouse()
             if was_modifying and self.on_modify_ended: self.on_modify_ended()
             return

        # Check if this was a click (not a drag) on a multi-selection
        if self._drag_start_world and not self._panning and not event.ShiftDown():
            pos_world = self.screen_to_world(event.GetPosition())
            dx = pos_world[0] - self._drag_start_world[0]
            dy = pos_world[1] - self._drag_start_world[1]
            dist_sq = dx*dx + dy*dy
            
            # If moved less than ~3 pixels, treat as click
            if dist_sq < 9: 
                local_pos = self.world_to_local(pos_world)
                hits = self._hit_test_all_local(local_pos)
                if (
                    self._selected_hit_on_mouse_down_id
                    and hits
                    and any(fm.id == self._selected_hit_on_mouse_down_id for fm in hits)
                ):
                    current_idx = next(
                        (idx for idx, fm in enumerate(hits) if fm.id == self._selected_hit_on_mouse_down_id),
                        -1,
                    )
                    if current_idx >= 0 and len(hits) > 1:
                        next_hit = hits[(current_idx + 1) % len(hits)]
                        self.selected_fmodules = [next_hit.id]
                        if self.on_selection_changed:
                            self.on_selection_changed(self.selected_fmodules)
                        self._selected_hit_on_mouse_down_id = next_hit.id
                        self.Refresh(False)
                else:
                    clicked = hits[0] if hits else None
                    if clicked and len(self.selected_fmodules) > 1:
                         self.selected_fmodules = [clicked.id]
                         if self.on_selection_changed:
                             self.on_selection_changed(self.selected_fmodules)
                         self.Refresh(False)

        if self._dragging_ids:
            was_modifying = True

        if self.HasCapture():
            self.ReleaseMouse()
        self._dragging_ids = []
        self._drag_start_world = None
        self._selected_hit_on_mouse_down_id = None
        
        if was_modifying and self.on_modify_ended:
            self.on_modify_ended()

    # Interaction
    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return
        if not self.frame:
            return
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
        hits = self._hit_test_all_local(local_pt)
        return hits[0] if hits else None

    def hit_test_all(self, transformed_world_pt: Tuple[float, float]) -> List[FModule]:
        """Returns all modules under the cursor, sorted top-to-bottom."""
        return self._hit_test_all_local(self.world_to_local(transformed_world_pt))

    def hit_test_collision_rect(self, world_pt: Tuple[float, float]) -> Optional[CollisionRect]:
        if not self.frame:
            return None
        return self._hit_test_collision_rect(world_pt)

    def hit_test_control_point(self, world_pt: Tuple[float, float]) -> Optional[ControlPoint]:
        if not self.frame:
            return None
        return self._hit_test_point(world_pt)

    def _reset_module_hit_cycle(self) -> None:
        self._last_module_hit_cycle_key = None
        self._last_module_hit_cycle_index = -1

    def _hit_test_all_local(self, local_pt: Tuple[float, float]) -> List[FModule]:
        hits: List[FModule] = []
        if not self.frame:
            return hits
        for fm in reversed(self.frame.fmodules):
            if self._fmodule_contains_local_point(fm, local_pt):
                hits.append(fm)
        return hits

    def _fmodule_contains_local_point(
        self, fm: FModule, local_pt: Tuple[float, float], depth: int = 0
    ) -> bool:
        if depth > 16:
            return False
        x0, y0, x1, y1 = self._fmodule_bounds(fm)
        min_x, min_y = min(x0, x1), min(y0, y1)
        max_x, max_y = max(x0, x1), max(y0, y1)

        # Half-open interval avoids double-hits on exact border pixels.
        if not (min_x <= local_pt[0] < max_x and min_y <= local_pt[1] < max_y):
            return False

        if fm.ref_type == "frame":
            ref_frame = self.project.get_frame(fm.ref_id)
            if not ref_frame:
                return True

            # Undo this frame-reference transform to test children in their own local space.
            test_x = local_pt[0] - fm.position[0]
            test_y = local_pt[1] - fm.position[1]

            cos_a, sin_a = _orthogonal_cos_sin(-float(fm.rotation_degrees))
            rot_x = test_x * cos_a - test_y * sin_a
            rot_y = test_x * sin_a + test_y * cos_a

            if fm.flip_x:
                rot_x = -rot_x
            if fm.flip_y:
                rot_y = -rot_y

            for child_fm in reversed(ref_frame.fmodules):
                if self._fmodule_contains_local_point(child_fm, (rot_x, rot_y), depth + 1):
                    return True
            return False

        if fm.ref_type != "module":
            return True

        ref_id = fm.ref_id
        if self.project.active_mapping and ref_id in self.project.active_mapping.map:
            ref_id = self.project.active_mapping.map[ref_id]
        if not ref_id:
            return False

        mod = self.project.get_module(ref_id)
        if not mod:
            return True

        target_w = max(1, int(round(max_x - min_x)))
        target_h = max(1, int(round(max_y - min_y)))
        px = int(math.floor(local_pt[0] - min_x))
        py = int(math.floor(local_pt[1] - min_y))
        if not (0 <= px < target_w and 0 <= py < target_h):
            return False

        if mod.type == "MD_IMAGE":
            base_img = self._get_module_source_image(mod)
        else:
            bmp = self._get_module_bitmap(mod)
            if not bmp or not bmp.IsOk():
                return True
            base_img = bmp.ConvertToImage()

        if not base_img or not base_img.IsOk():
            return True

        img = base_img.Copy()
        if fm.flip_x:
            img = img.Mirror(horizontally=True)
        if fm.flip_y:
            img = img.Mirror(horizontally=False)

        rot = int(fm.rotation_degrees) % 360
        if rot == 90:
            img = img.Rotate90(clockwise=True)
        elif rot == 180:
            img = img.Rotate180()
        elif rot == 270:
            img = img.Rotate90(clockwise=False)

        if img.GetWidth() != target_w or img.GetHeight() != target_h:
            img.Rescale(target_w, target_h, wx.IMAGE_QUALITY_NEAREST)

        if mod.type == "MD_IMAGE" and self.show_transparency:
            asset = self.project.get_image(mod.image_id)
            if asset and asset.transparent_color:
                tr, tg, tb = asset.transparent_color
                if (
                    img.GetRed(px, py) == tr
                    and img.GetGreen(px, py) == tg
                    and img.GetBlue(px, py) == tb
                ):
                    return False

        if img.HasAlpha():
            return img.GetAlpha(px, py) > 0
        if img.HasMask():
            return not (
                img.GetRed(px, py) == img.GetMaskRed()
                and img.GetGreen(px, py) == img.GetMaskGreen()
                and img.GetBlue(px, py) == img.GetMaskBlue()
            )
        return True

    def _get_asset_source_image(self, asset_id: str) -> Optional[wx.Image]:
        cached = self._asset_image_cache.get(asset_id)
        if cached and cached.IsOk():
            return cached
        asset = self.project.get_image(asset_id)
        if not asset:
            return None
        img = load_wx_image_safely(asset.file_path)
        if not img or not img.IsOk():
            return None
        self._asset_image_cache[asset_id] = img
        return img

    def _get_module_source_image(self, mod: Module) -> Optional[wx.Image]:
        if mod.type != "MD_IMAGE":
            return None
        full_img = self._get_asset_source_image(mod.image_id)
        if not full_img:
            return None

        rx, ry, rw, rh = mod.rect
        if rw <= 0 or rh <= 0:
            return None
        if rx < 0 or ry < 0 or rx + rw > full_img.GetWidth() or ry + rh > full_img.GetHeight():
            return None

        sub_img = full_img.GetSubImage(wx.Rect(int(rx), int(ry), int(rw), int(rh)))
        if getattr(mod, "rotated", False):
            sub_img = sub_img.Rotate90(clockwise=False)
        return sub_img

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
                if getattr(mod, 'rotated', False):
                    w, h = h, w

                piv_x, piv_y = mod.pivot
                
                # Base corners relative to pivot
                corners = [
                    (0 - piv_x, 0 - piv_y),
                    (w - piv_x, 0 - piv_y),
                    (0 - piv_x, h - piv_y),
                    (w - piv_x, h - piv_y)
                ]
                
                # Apply Rotation
                cos_a, sin_a = _orthogonal_cos_sin(fm.rotation_degrees)
                
                final_points = []
                for cx, cy in corners:
                    rx = cx * cos_a - cy * sin_a
                    ry = cx * sin_a + cy * cos_a
                    final_points.append((rx, ry))
                    
                # Find Bounds from corners
                xs = [p[0] for p in final_points]
                ys = [p[1] for p in final_points]
                
                return (
                    min(xs) + fm.position[0],
                    min(ys) + fm.position[1],
                    max(xs) + fm.position[0],
                    max(ys) + fm.position[1]
                )
        
        elif fm.ref_type == "frame":
            ref_frame = self.project.get_frame(fm.ref_id)
            if ref_frame:
                # Parent Transform Props
                p_flip_x = fm.flip_x
                p_flip_y = fm.flip_y
                p_rot = fm.rotation_degrees
                cos_a, sin_a = _orthogonal_cos_sin(p_rot)

                min_x, min_y, max_x, max_y = 0, 0, 0, 0
                first = True
                
                for child_fm in ref_frame.fmodules:
                     # 1. Get Child Bounds in valid Frame Space
                     cx0, cy0, cx1, cy1 = self._fmodule_bounds(child_fm)
                     
                     # 2. Transform corners by Parent Transform
                     # Child bounds are relative to Frame Origin (0,0)
                     child_corners = [
                         (cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1)
                     ]
                     
                     for px, py in child_corners:
                          # Flip
                          if p_flip_x: px = -px
                          if p_flip_y: py = -py
                          
                          # Rotate
                          rx = px * cos_a - py * sin_a
                          ry = px * sin_a + py * cos_a
                          
                          if first:
                              min_x, min_y, max_x, max_y = rx, ry, rx, ry
                              first = False
                          else:
                              min_x = min(min_x, rx)
                              min_y = min(min_y, ry)
                              max_x = max(max_x, rx)
                              max_y = max(max_y, ry)
                
                if not first:
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

    def _module_bitmap_key(self, mod: Module) -> str:
        if mod.type == "MD_IMAGE":
            asset = self.project.get_image(mod.image_id)
            transparent_color = asset.transparent_color if asset else None
            return (
                f"{mod.id}_{mod.rect}_{getattr(mod, 'rotated', False)}"
                f"_{self.show_transparency}_{transparent_color}"
            )
        # For shapes, include visual properties in key
        return f"{mod.id}_{mod.type}_{mod.color}_{mod.params}"

    def _get_module_bitmap(self, mod: Module) -> Optional[wx.Bitmap]:
        key = self._module_bitmap_key(mod)
        if key in self._bitmap_cache:
            return self._bitmap_cache[key]
            
        if mod.type == "MD_IMAGE":
            asset = self.project.get_image(mod.image_id)
            if not asset:
                return None
                
            try:
                full_img = self._get_asset_source_image(asset.id)
                if not full_img:
                    return None
                    
                rx, ry, rw, rh = mod.rect
                img_w, img_h = full_img.GetWidth(), full_img.GetHeight()
                
                if rx >= 0 and ry >= 0 and rw > 0 and rh > 0 and rx + rw <= img_w and ry + rh <= img_h:
                    sub_img = full_img.GetSubImage(wx.Rect(rx, ry, rw, rh))
                    if self.show_transparency and asset.transparent_color:
                        sub_img.SetMaskColour(*asset.transparent_color)
                    
                    if getattr(mod, 'rotated', False):
                        sub_img = sub_img.Rotate90(clockwise=False)
                        
                    bmp = sub_img.ConvertToBitmap()
                    self._bitmap_cache[key] = bmp
                    return bmp
            except Exception as e:
                print(f"Canvas bmp load fail: {e}")
                return None
        else:
             # Shape Rendering
             w, h = mod.rect[2], mod.rect[3]
             bmp = render_pixel_shape_to_bitmap(mod.type, w, h, mod.color, mod.params)
             if bmp:
                 self._bitmap_cache[key] = bmp
                 return bmp
                 
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
        
        if self.on_modify_started:
            self.on_modify_started()
        
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
        
        if self.on_modify_ended:
            self.on_modify_ended()

    # --- Collision Logic ---
    def _resolve_active_collision_type_id(self) -> Optional[str]:
        if not self.project.collision_types:
            self.active_collision_type_id = None
            return None
        valid_ids = {ct.id for ct in self.project.collision_types}
        if self.active_collision_type_id not in valid_ids:
            self.active_collision_type_id = self.project.collision_types[0].id
        return self.active_collision_type_id

    def _resolve_active_point_type_id(self) -> Optional[str]:
        if not self.project.point_types:
            self.active_point_type_id = None
            return None
        valid_ids = {pt.id for pt in self.project.point_types}
        if self.active_point_type_id not in valid_ids:
            self.active_point_type_id = self.project.point_types[0].id
        return self.active_point_type_id

    def on_collision_left_down(self, event, pos_screen):
        pos_world = self.screen_to_world(pos_screen)
        # 1. Handle Resize?
        if len(self.selected_collision_rects) == 1:
            cid = self.selected_collision_rects[0]
            cr = next((r for r in self.frame.collision_rects if r.id == cid), None)
            if cr:
                handle = self._hit_test_handle(cr, pos_screen)
                if handle != -1:
                    if self.on_modify_started: self.on_modify_started()
                    self._col_drag_mode = "resize"
                    self._col_drag_handle = handle
                    self._col_drag_rect_id = cid
                    self._col_drag_start_rect = cr.rect
                    self._drag_start_world = pos_world
                    self.CaptureMouse()
                    return
                    
        # 2. Hit Test Rect
        hit_cr = self._hit_test_collision_rect(pos_world)
        if hit_cr:
             # If we clicked, select it.
             # Only start drag if we actually move, but we prep here.
             if self.on_modify_started: self.on_modify_started()
             self.selected_collision_rects = [hit_cr.id]
             self._col_drag_mode = "move"
             self._col_drag_rect_id = hit_cr.id
             self._col_drag_start_rect = hit_cr.rect
             self._drag_start_world = pos_world
             self.CaptureMouse()
             self.Refresh(False)
             return
             
        # 3. Create
        active_type_id = self._resolve_active_collision_type_id()
        if active_type_id:
             if self.on_modify_started: self.on_modify_started()
             # Create new rect
             new_id = generate_id("crect")
             # Start with 0 size
             x, y = int(pos_world[0] - self.frame_offset[0]), int(pos_world[1] - self.frame_offset[1])
             new_rect = CollisionRect(id=new_id, type_id=active_type_id, rect=(x, y, 0, 0))
             self.frame.collision_rects.append(new_rect)
             self.selected_collision_rects = [new_id]
             
             self._col_drag_mode = "create"
             self._col_drag_rect_id = new_id
             # Store origin for creation
             self._col_drag_start_rect = (x, y, 0, 0) 
             self._drag_start_world = pos_world
             self.CaptureMouse()
             self.Refresh(False)
        else:
             self.selected_collision_rects = []
             self._col_drag_mode = "none"
             self._col_drag_rect_id = None
             self._drag_start_world = None
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
                if self.on_modify_started: self.on_modify_started()
                
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
            active_type_id = self._resolve_active_point_type_id()
            if active_type_id:
                if self.on_modify_started: self.on_modify_started()
                wx, wy = pos_world
                # Usage of math.floor ensures consistent Top-Left behavior 
                # even for negative coordinates, solving the 'bottom-left' bias issue.
                wx = int(math.floor(wx - self.frame_offset[0]))
                wy = int(math.floor(wy - self.frame_offset[1]))
                     
                new_cp = ControlPoint(
                    id=generate_id("pt"),
                    type_id=active_type_id,
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
                self._pt_drag_mode = "none"
                self._pt_drag_id = None
                self._drag_start_world = None
                self._drag_start_positions = {}
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
        self.on_offset_change: Optional[Callable[[int, int], None]] = None # Callback (x, y)
        
        self.global_flip_x = False
        self.global_flip_y = False
        # Onion skin: "off", "previous", "next" or "both" (neighbouring animation frames).
        self.onion_mode = "off"

    def _aframe_render_transform(self, af: AFrame) -> Tuple[Tuple[float, float], bool, bool, float]:
        """Offset/flip/rotation for an animation frame, including the global mirror preview."""
        ox, oy = af.offset
        if self.global_flip_x:
            ox = -ox
        if self.global_flip_y:
            oy = -oy
        return (
            (ox, oy),
            af.flip_x != self.global_flip_x,
            af.flip_y != self.global_flip_y,
            float(getattr(af, "rotation_degrees", 0.0)),
        )

    def _onion_indices(self) -> List[Tuple[int, Tuple[float, float, float, float]]]:
        if self.onion_mode == "off" or not self.animation or not self.current_aframe:
            return []
        frames = self.animation.aframes
        try:
            idx = next(i for i, af in enumerate(frames) if af is self.current_aframe)
        except StopIteration:
            return []
        wrap = self.animation.playback_type == "loop" and len(frames) > 2
        result: List[Tuple[int, Tuple[float, float, float, float]]] = []
        if self.onion_mode in ("previous", "both"):
            prev_idx = idx - 1
            if prev_idx < 0 and wrap:
                prev_idx = len(frames) - 1
            if 0 <= prev_idx < len(frames) and prev_idx != idx:
                result.append((prev_idx, GHOST_PREVIOUS))
        if self.onion_mode in ("next", "both"):
            next_idx = idx + 1
            if next_idx >= len(frames) and wrap:
                next_idx = 0
            if 0 <= next_idx < len(frames) and next_idx != idx:
                result.append((next_idx, GHOST_NEXT))
        return result

    def _rebuild_ghost_layers(self) -> None:
        layers: List[Dict[str, Any]] = []
        if self.animation:
            for ghost_idx, style in self._onion_indices():
                af = self.animation.aframes[ghost_idx]
                frame = self.project.get_frame(af.frame_id)
                if not frame:
                    continue
                offset, flip_x, flip_y, rotation = self._aframe_render_transform(af)
                layers.append(
                    {"frame": frame, "offset": offset, "flip_x": flip_x, "flip_y": flip_y,
                     "rotation": rotation, "style": style}
                )
        self.ghost_layers = layers

    def set_onion_mode(self, mode: str) -> None:
        self.onion_mode = mode if mode in ("off", "previous", "next", "both") else "off"
        self._rebuild_ghost_layers()
        self.Refresh(False)

    def get_content_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        if not self.animation or not self.animation.aframes:
            return super().get_content_bounds()
        boxes = []
        for af in self.animation.aframes:
            frame = self.project.get_frame(af.frame_id)
            if not frame:
                continue
            offset, flip_x, flip_y, rotation = self._aframe_render_transform(af)
            with self.frame_transform(frame, offset, flip_x, flip_y, rotation, self._ghost_style):
                box = self._frame_world_bounds()
            if box:
                boxes.append(box)
        if not boxes:
            return None
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )

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
            (
                self.frame_offset,
                self.render_flip_x,
                self.render_flip_y,
                self.render_rotation,
            ) = self._aframe_render_transform(self.current_aframe)
        else:
            self.frame = None
            self.frame_offset = (0, 0)
            self.render_flip_x = False
            self.render_flip_y = False
            self.render_rotation = 0.0
        self._rebuild_ghost_layers()

    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if self.show_trajectory and self.animation:
            self._draw_trajectory(gc)
             
        if self.current_aframe and self.frame:
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
        if self.begin_pan_if_requested(event):
            return

        pos = self.screen_to_world(event.GetPosition())
        if self.current_aframe:
            if self.on_modify_started: self.on_modify_started()
            self.drag_start = pos
            self._drag_start_offset = self.current_aframe.offset
            try:
                self.CaptureMouse()
            except: pass
        else:
            event.Skip()

    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return

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
             
        was_dragging = self.drag_start is not None

        if self.HasCapture():
            self.ReleaseMouse()
        self.drag_start = None
        self._drag_start_offset = None
        
        if was_dragging and self.on_modify_ended:
            self.on_modify_ended()
            
        event.Skip()
