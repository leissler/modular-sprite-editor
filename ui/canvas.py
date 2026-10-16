"""FrameCanvas: draws a frame for the Frames, Animations and Timeline stages, which add their own editing."""

from __future__ import annotations

import math
from collections import OrderedDict
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

import wx

import console_exports
from hardware_budget import Budget, BudgetCalculator, HardwareProfile
from ui import app_services
from models import CollisionRect, ControlPoint, FModule, Frame, Module, ModuleMapping, PaletteSwap, Project
from ui.base_canvas import BaseCanvas
from ui.console_colours import CONSOLE
from ui.frame_geometry import orthogonal_cos_sin, part_bounds
from ui.utils import render_pixel_shape_to_bitmap, load_wx_image_safely
from ui.dpi import px


# Onion-skin styles: (red, green, blue, alpha) channel factors applied to ghost images.
GHOST_PREVIOUS = (1.0, 0.55, 0.55, 0.38)
GHOST_NEXT = (0.55, 0.75, 1.0, 0.38)
GHOST_REFERENCE = (1.0, 1.0, 1.0, 0.35)

# Upper bound for cached zoomed bitmaps, in screen pixels (~4 bytes each).
SCALED_CACHE_PIXEL_BUDGET = 24_000_000


_orthogonal_cos_sin = orthogonal_cos_sin


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


# One calculator for every canvas: it caches module images and their 8×8 block masks.
BUDGET = BudgetCalculator()


class ExportTiles:
    """The whole project's tiles in the export for a profile's console (with every mapping, the export's default) for
    the budget readouts: worked out again only after the project changed (a new undo checkpoint) or its images did."""

    def __init__(self) -> None:
        self._key: Any = None
        self._tiles = 0

    def get(self, project: Project, profile: Any = None) -> int:
        revision = app_services.project_revision()
        model = (profile.vram_model, profile.shapes) if profile is not None and profile.vram_model else None
        key = (id(project), revision, BUDGET.generation, model)
        if revision is None or key != self._key:
            self._tiles = BUDGET.export_tiles(project, [None] + list(project.mappings), profile)
            self._key = key
        return self._tiles


EXPORT_TILES = ExportTiles()


def memory_text(here: int, total: int, capacity: int, about: bool = True) -> str:
    """The budget readout's video memory line (``about``: the capacity depends on the game's layout)."""
    left = f"{capacity - total} left" if total <= capacity else f"{total - capacity} too many"
    return f"Video memory: {here} tiles here · the whole project {total} of {'~' if about else ''}{capacity} ({left})"


class FrameCanvas(BaseCanvas):
    """Draws a frame: its parts (nested frames, the mapping, flips and quarter turns), hitboxes and points, onion-skin
    ghosts, part bounds and the hardware budget, under a frame-level offset / flip / rotation. Drawing only: the
    Frames stage (ui/frame_editor/stage.py) edits, the Animations and Timeline stages pick and drag their own way."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT) # Critical for Mac/Win behavior
        self.project = project
        self.frame: Optional[Frame] = None
        # Hitboxes and points are drawn when shown, in their type's colour; types without a colour stay hidden.
        self.show_collision = False
        self.show_points = True
        self.collision_type_colors: dict[str, tuple] = {}
        self.point_type_colors: dict[str, tuple] = {}

        self.frame_offset: Tuple[float, float] = (0.0, 0.0)
        self.render_flip_x = False
        self.render_flip_y = False
        self.render_rotation = 0.0
        # (mapping,) while drawing_mapping() overrides the preview mapping, e.g. for a scene object with its own.
        self._mapping_override: Optional[Tuple[Optional[ModuleMapping]]] = None
        self._swap_override: Optional[Tuple[Optional[PaletteSwap]]] = None
        # Video frames into playback: colour cycles turn (None: they stand still, as when not playing).
        self.colour_frame: Optional[float] = None
        self._bitmap_cache: dict[str, wx.Bitmap] = {}
        self._asset_image_cache: dict[Any, wx.Image] = {}  # (image id, the colours it shows) -> the whole image
        # Zoomed/flipped/rotated module bitmaps, so paints during drags do not rescale images.
        self._scaled_cache: "OrderedDict[Any, wx.Bitmap]" = OrderedDict()
        self._scaled_cache_pixels = 0
        # Active ghost style while drawing onion-skin layers (None = normal drawing).
        self._ghost_style: Optional[Tuple[float, float, float, float]] = None
        # "Part bounds" view: outline the screen rect of every module part (what each hardware
        # sprite covers). Rects are collected while drawing, so nested frames and the stage get it too.
        self.show_part_bounds: bool = False
        self._part_rects: List[Tuple[float, float, float, float]] = []
        # "Budget" view: hardware sprites of what is shown, scanlines that would drop sprites, and a readout.
        self.budget_profile: Optional[HardwareProfile] = None
        self._budget_hud: Optional[Budget] = None  # drawn last, over everything else
        self.budget_hud_rect: Optional[Tuple[float, float, float, float]] = None  # where the readout was drawn
        # Onion-skin layers drawn under the current frame:
        # dicts with frame, offset, flip_x, flip_y, rotation, style.
        self.ghost_layers: List[Dict[str, Any]] = []

    def set_frame(self, frame: Optional[Frame]) -> None:
        self.frame = frame
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

    @property
    def mapping(self) -> Optional[ModuleMapping]:
        """The mapping parts are drawn with: the preview mapping unless drawing_mapping overrides it."""
        if self._mapping_override is not None:
            return self._mapping_override[0]
        return self.project.active_mapping

    @contextmanager
    def drawing_mapping(self, mapping: Optional[ModuleMapping]) -> Iterator[None]:
        """Temporarily draw, measure and hit-test with another mapping (``None`` = original modules)."""
        saved = self._mapping_override
        self._mapping_override = (mapping,)
        try:
            yield
        finally:
            self._mapping_override = saved

    @property
    def palette_swap(self) -> Optional[PaletteSwap]:
        """The palette swap parts are drawn with: the preview's unless drawing_palette_swap overrides it."""
        if self._swap_override is not None:
            return self._swap_override[0]
        return self.project.active_palette_swap if self.project else None

    @contextmanager
    def drawing_palette_swap(self, swap: Optional[PaletteSwap]) -> Iterator[None]:
        """Temporarily draw with another palette swap (``None`` = the palettes as they are)."""
        saved = self._swap_override
        self._swap_override = (swap,)
        try:
            yield
        finally:
            self._swap_override = saved

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
        self.draw_backdrop(dc)
        gc = wx.GraphicsContext.Create(dc)
        self._budget_hud = None
        self._draw_grid(gc)
        self.draw_content(gc)
        self._draw_budget_hud(gc)

    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if not self.frame:
            self._draw_message(gc, "No frame selected")
            return
        self._draw_ghost_layers(gc)
        self.draw_parts(gc)
        self.draw_markers(gc)

    def draw_parts(self, gc: wx.GraphicsContext) -> None:
        """The frame's parts, then the part bounds and the budget overlay when they are on."""
        gc.PushState()
        self._part_rects = []
        for fm in self.frame.fmodules:
            self._draw_fmodule_content(gc, fm)
        gc.PopState()
        if self.show_part_bounds:
            self._draw_part_bounds(gc)
        if self.budget_profile is not None:
            self._draw_budget(gc, self.compute_budget())

    def draw_markers(self, gc: wx.GraphicsContext) -> None:
        """Hitboxes and points, when shown."""
        if self.show_collision:
            for cr in self.visible_hitboxes():
                self.draw_hitbox(gc, cr)
        if self.show_points:
            for cp in self.visible_points():
                self.draw_point(gc, cp)

    def visible_hitboxes(self) -> List[CollisionRect]:
        return [cr for cr in self.frame.collision_rects if cr.type_id in self.collision_type_colors]

    def visible_points(self) -> List[ControlPoint]:
        return [cp for cp in self.frame.control_points if not cp.type_id or cp.type_id in self.point_type_colors]

    def _draw_message(self, gc: wx.GraphicsContext, text: str) -> None:
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), self.overlay_colour("canvas_faint"))
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
             mapping = self.mapping
             if mapping and ref_id in mapping.map:
                 ref_id = mapping.map[ref_id]
             
             if not ref_id: return

             mod = self.project.get_module(ref_id)
             if mod and self._ghost_style is None:
                 self._part_rects.append((sx0, sy0, w, h))
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
                    for qx, qy in ((cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1)):
                        if p_flip_x:
                            qx = -qx
                        if p_flip_y:
                            qy = -qy
                        ts_x.append(qx * cos_a - qy * sin_a)
                        ts_y.append(qx * sin_a + qy * cos_a)

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

    def set_budget_profile(self, profile: Optional[HardwareProfile]) -> None:
        self.budget_profile = profile
        self.Refresh(False)

    def compute_budget(self) -> Optional[Budget]:
        """Hardware sprites for the frame as currently drawn (with its offset / flips / rotation)."""
        if self.budget_profile is None or self.frame is None:
            return None
        from ui.frame_render import transform

        a, b = transform(self.render_flip_x, self.render_flip_y, self.render_rotation, self.frame_offset)
        return BUDGET.frame_budget(self.project, self.frame, self.mapping, self.budget_profile, a, b)

    def _draw_budget(self, gc: wx.GraphicsContext, budget: Optional[Budget]) -> None:
        """Overlay (red scanlines, hardware sprite outlines); the readout follows in _draw_budget_hud."""
        self._budget_hud = budget
        if budget is None:
            return
        width, height = self.GetClientSize()
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(255, 60, 60, 80)))
        for first, last in budget.over_lines():
            top = self.world_to_screen((0, first))[1]
            bottom = self.world_to_screen((0, last + 1))[1]
            gc.DrawRectangle(0, top, width, max(1.0, bottom - top))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(wx.Colour(255, 214, 102, 220), 1))
        for s in budget.sprites:
            x0, y0 = self.world_to_screen((s.x, s.y))
            x1, y1 = self.world_to_screen((s.x + s.w, s.y + s.h))
            gc.DrawRectangle(round(x0) + 0.5, round(y0) + 0.5, max(0, round(x1 - x0) - 1), max(0, round(y1 - y0) - 1))

    def _draw_budget_hud(self, gc: wx.GraphicsContext) -> None:
        """Readout in the top-left corner; red when sprites would drop out."""
        budget = self._budget_hud
        if budget is None or self.budget_profile is None:
            return
        over = budget.over_budget()
        lines = [budget.profile.name, budget.summary()]
        capacity = budget.profile.vram_tiles
        if capacity:
            total = EXPORT_TILES.get(self.project, budget.profile)
            export = console_exports.for_console(budget.profile.vram_model)
            lines.append(memory_text(budget.unique_tiles, total, capacity, bool(export and export.tiles_about)))
            if total > capacity:
                over = True
                lines.append("Too many tiles: the game could not load the sprites (Check Project)")
        if budget.over_budget():
            lines.append("Over the limit: sprites on the red lines would flicker or vanish")
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        gc.SetFont(font, wx.Colour(255, 150, 150) if over else wx.Colour(235, 235, 240))
        extents = [gc.GetTextExtent(line) for line in lines]
        box_w = max(w for w, _h in extents) + px(16)
        box_h = sum(h for _w, h in extents) + px(10) + px(2) * (len(lines) - 1)
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(18, 19, 22, 215)))
        gc.DrawRoundedRectangle(px(8), px(8), box_w, box_h, px(5))
        self.budget_hud_rect = (float(px(8)), float(px(8)), float(box_w), float(box_h))
        y = float(px(13))
        for line, (_w, h) in zip(lines, extents):
            gc.DrawText(line, px(16), y)
            y += h + px(2)

    def set_show_part_bounds(self, show: bool) -> None:
        self.show_part_bounds = bool(show)
        self.Refresh(False)

    def _draw_part_bounds(self, gc: wx.GraphicsContext) -> None:
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(wx.Colour(90, 210, 255, 220), 1))
        for x, y, w, h in self._part_rects:
            gc.DrawRectangle(round(x) + 0.5, round(y) + 0.5, max(0, round(w) - 1), max(0, round(h) - 1))

    def draw_hitbox(self, gc: wx.GraphicsContext, cr: CollisionRect, selected: bool = False) -> Tuple[float, float, float, float]:
        """A hitbox in its type's colour (outlined white when selected); returns its screen rect (x, y, w, h)."""
        rx, ry, rw, rh = cr.rect
        p0 = self.world_to_screen(self.local_to_world((rx, ry)))
        p1 = self.world_to_screen(self.local_to_world((rx + rw, ry + rh)))
        sx0, sy0 = min(p0[0], p1[0]), min(p0[1], p1[1])
        w, h = abs(p1[0] - p0[0]), abs(p1[1] - p0[1])

        col = self.collision_type_colors.get(cr.type_id, (200, 60, 60))
        try:
            r, g, b = int(col[0]), int(col[1]), int(col[2])
        except (ValueError, IndexError):
            r, g, b = 200, 60, 60
        gc.SetBrush(wx.Brush(wx.Colour(r, g, b, 80)))  # semi-transparent fill
        if selected:
            gc.SetPen(wx.Pen(self.overlay_colour("canvas_line"), 2, style=wx.PENSTYLE_SOLID))
        else:
            gc.SetPen(wx.Pen(wx.Colour(r, g, b), 1, style=wx.PENSTYLE_SOLID))
        gc.DrawRectangle(sx0, sy0, w, h)
        return sx0, sy0, w, h

    def draw_point(self, gc: wx.GraphicsContext, cp: ControlPoint, selected: bool = False) -> Tuple[int, int, int]:
        """A point: the pixel it marks, outlined, under a crosshair (white when selected); returns the pixel's screen
        square (x, y, size)."""
        # A point marks a pixel: move the pixel's centre like the frame and draw the pixel it lands in (on a mirrored
        # or turned step that is the mirrored / turned pixel, as in the export).
        cx, cy = self.local_to_world((cp.x + 0.5, cp.y + 0.5))
        sx, sy = self.world_to_screen((math.floor(cx), math.floor(cy)))

        col = self.point_type_colors.get(cp.type_id, (0, 255, 0))
        r, g, b = int(col[0]), int(col[1]), int(col[2])
        # The pixel's square, aligned to the zoomed pixel grid.
        dsx = round(sx)
        dsy = round(sy)
        dsize = round(max(1, self.zoom))
        gc.SetBrush(wx.Brush(wx.Colour(r, g, b, 80)))  # slight tint
        if selected:
            gc.SetPen(wx.Pen(self.overlay_colour("canvas_line"), width=2))
        else:
            gc.SetPen(wx.Pen(wx.Colour(r, g, b), width=1))
        gc.DrawRectangle(dsx, dsy, dsize, dsize)

        # The crosshair reaches 6 px (at 100 %) beyond the square.
        cx = dsx + dsize / 2
        cy = dsy + dsize / 2
        half_len = (dsize / 2) + px(6)
        gc.SetPen(wx.Pen(self.overlay_colour("canvas_line") if selected else wx.Colour(r, g, b), width=2))
        gc.StrokeLine(cx - half_len, cy, cx + half_len, cy)
        gc.StrokeLine(cx, cy - half_len, cx, cy + half_len)
        return dsx, dsy, dsize

    def _colour_key(self, asset: Any) -> Any:
        """What decides the colours an image shows in this draw (None: its own)."""
        return CONSOLE.image_key(self.project, asset, self.palette_swap, self.colour_frame)

    def _get_asset_source_image(self, asset_id: str) -> Optional[wx.Image]:
        asset = self.project.get_image(asset_id)
        if not asset:
            return None
        colours = self._colour_key(asset)
        cached = self._asset_image_cache.get((asset_id, colours))
        if cached and cached.IsOk():
            return cached
        if colours is not None:  # console view, a palette swap or turning colour cycles
            from ui.frame_render import to_wx_image

            shown = CONSOLE.image(self.project, asset, self.palette_swap, self.colour_frame)
            img = to_wx_image(shown) if shown is not None else None
        else:
            img = load_wx_image_safely(asset.file_path)
        if not img or not img.IsOk():
            return None
        if len(self._asset_image_cache) > 64:
            self._asset_image_cache.clear()  # cycles and swaps add pictures; start over now and then
        self._asset_image_cache[(asset_id, colours)] = img
        return img

    def _fmodule_bounds(self, fm: FModule) -> Tuple[float, float, float, float]:
        return part_bounds(self.project, fm, self.mapping)

    def _module_bitmap_key(self, mod: Module) -> str:
        if mod.type == "MD_IMAGE":
            asset = self.project.get_image(mod.image_id)
            transparent_color = asset.transparent_color if asset else None
            return (
                f"{mod.id}_{mod.rect}_{getattr(mod, 'rotated', False)}"
                f"_{self.apply_key_colour}_{transparent_color}_{self._colour_key(asset) if asset else None}"
            )
        # For shapes, include visual properties in key
        shape_colours = CONSOLE.shape_key(self.project, self.palette_swap, self.colour_frame)
        return f"{mod.id}_{mod.type}_{mod.color}_{mod.params}_{shape_colours}"

    def _get_module_bitmap(self, mod: Module) -> Optional[wx.Bitmap]:
        key = self._module_bitmap_key(mod)
        if key in self._bitmap_cache:
            return self._bitmap_cache[key]
        if len(self._bitmap_cache) > 4000:
            self._bitmap_cache.clear()  # colour cycles add a bitmap per phase; start over now and then
            
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
                    # Recoloured pictures come with the key colour cut out already (alpha); a mask on top of the
                    # alpha would win on macOS and show the cut-out pixels in their new colour.
                    keyed = self._colour_key(asset) is not None
                    if self.apply_key_colour and asset.transparent_color and not keyed:
                        sub_img.SetMaskColour(*asset.transparent_color)
                    
                    if getattr(mod, 'rotated', False):
                        sub_img = sub_img.Rotate90(clockwise=False)
                        
                    bmp = sub_img.ConvertToBitmap()
                    self._bitmap_cache[key] = bmp
                    return bmp
            except (OSError, ValueError, wx.wxAssertionError):
                return None  # an unreadable image: the part is not drawn (Check Project names the image)
        else:
             # Shape Rendering (on the console: its colour from the first palette)
             w, h = mod.rect[2], mod.rect[3]
             colour = (CONSOLE.colour(self.project, mod.color, self.palette_swap, self.colour_frame)
                       if mod.color else mod.color)
             bmp = render_pixel_shape_to_bitmap(mod.type, w, h, colour, mod.params)
             if bmp:
                 self._bitmap_cache[key] = bmp
                 return bmp
                 
        return None
