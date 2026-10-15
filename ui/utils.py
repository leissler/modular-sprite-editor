import math
import wx
from typing import TYPE_CHECKING, Any, Optional, Tuple
from PIL import Image as PILImage
from ui.theme import T

if TYPE_CHECKING:
    from models import ModuleMapping, Project

def load_wx_image_safely(path: str) -> wx.Image:
    """Load image robustly; prefer Pillow decode to avoid libpng ICC warnings."""
    try:
        with PILImage.open(path) as pil_img:
            rgba = pil_img.convert("RGBA")
            w, h = rgba.size
            wx_img = wx.Image(w, h)
            wx_img.SetData(rgba.convert("RGB").tobytes())
            wx_img.SetAlpha(rgba.getchannel("A").tobytes())
            return wx_img
    except (OSError, ValueError):  # not an image Pillow reads: let wx try
        pass

    # Fallback to wx decoder with warnings suppressed.
    with wx.LogNull():
        return wx.Image(path)

def render_pixel_shape_to_bitmap(mod_type: str, w: int, h: int, color: Tuple[int, int, int], params: list) -> Optional[wx.Bitmap]:
    """
    Renders a vector shape into a transparent bitmap at native resolution (1x).
    This allows for pixel-perfect scaling (Nearest Neighbor) later.
    """
    if w <= 0 or h <= 0:
        return None
        
    # Use FromRGBA to ensure alpha channel exists and is cleared to 0 (transparent)
    try:
         bmp = wx.Bitmap.FromRGBA(w, h, red=0, green=0, blue=0, alpha=0)
    except AttributeError:
         # Fallback
         bmp = wx.Bitmap(w, h, 32)
    
    mem = wx.MemoryDC(bmp)
    
    # Check fallback transparency if needed (usually FromRGBA handles it)
    if not bmp.HasAlpha():
         mem.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 0)))
         mem.Clear()

    wx_color = wx.Colour(*color)
    filled = "FILL" in mod_type
    
    mem.SetPen(wx.Pen(wx_color, width=1))
    if filled:
        mem.SetBrush(wx.Brush(wx_color))
    else:
        mem.SetBrush(wx.TRANSPARENT_BRUSH)
        
    # Note: We draw at (0,0) in the bitmap space.
    # The 'rect' passed in is just for size.
    # The params for Triangle/Line usually are relative to TopLeft.
    
    if mod_type in ("MD_RECT", "MD_FILL_RECT", "MD_MARKER"):
        if not filled and mod_type != "MD_MARKER":
            mem.DrawRectangle(0, 0, w, h)
        elif mod_type == "MD_MARKER":
            mem.DrawLine(0, 0, w - 1, h - 1)
            mem.DrawLine(w - 1, 0, 0, h - 1)
        else:
             mem.DrawRectangle(0, 0, w, h)
             
    elif mod_type in ("MD_ARC", "MD_FILL_ARC"):
        start, sweep = params if len(params) >= 2 else (0, 360)
        
        # SSAA (Super Sampling) to fix asymmetry/cutoff issues:
        # Render at 4x resolution then downscale.
        scale_f = 4
        ss_w, ss_h = w * scale_f, h * scale_f
        
        # Custom GraphicsContext SSAA rendering for Isotropic Stroke Width
        # (DrawEllipticArc scales the pen width anisotropically if implicit scaling is used, 
        #  or if the underlying API fits to rect by scaling. GCDC gives us explicit control).
        
        # Temp Bitmap with Explicit Alpha (Crucial for MemoryDC)
        # Using wx.Image to guarantee alpha channel is allocated and zeroed
        init_img = wx.Image(ss_w, ss_h)
        init_img.InitAlpha() # Allocates buffer
        
        # FORCE Alpha to 0 (Transparent) - InitAlpha defaults vary across platforms
        # This fixes the "Black Rectangle" (Opaque default) issue
        init_img.SetAlphaBuffer(b'\x00' * (ss_w * ss_h))
        
        ss_bmp = init_img.ConvertToBitmap()
        ss_mem = wx.MemoryDC(ss_bmp)
        
        gc = wx.GraphicsContext.Create(ss_mem)
        
        if gc:
            # 1. Clear to Transparent using GC (Reliable across platforms)
            gc.SetAntialiasMode(wx.ANTIALIAS_NONE)
            gc.SetCompositionMode(wx.COMPOSITION_SOURCE)
            gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 0)))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawRectangle(0, 0, ss_w, ss_h)
            
            # 2. Reset Compassion for Drawing
            gc.SetCompositionMode(wx.COMPOSITION_OVER)
            gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT) # Restore AA
            
            # Manual Bezier Approximation (Proper Isotropic Curve)
            # Replacing Polyline with Cubic Beziers to avoid rasterization artifacts ("caterpillar effect" from tiny segments)
            # while maintaining isotropic stroke width (by transforming points, not the path).
            
            ss_pen_width = 1 * scale_f
            half_pen = ss_pen_width / 2.0
            
            # GEOMETRY FIX: Inset radius by half pen width to prevent clipping
            # Previous logic put center of stroke on edge, clipping 50% of the line.
            cx, cy = ss_w / 2.0, ss_h / 2.0
            rx = (ss_w / 2.0) - half_pen
            ry = (ss_h / 2.0) - half_pen
            
            # Check for degenerate negative radius
            rx = max(0.1, rx)
            ry = max(0.1, ry)
            
            path = gc.CreatePath()
            
            # Start/End in Radians (CCW from East)
            start_rad = math.radians(start)
            sweep_rad = math.radians(sweep)
            
            # Helper: Get point on ellipse for angle
            def get_pt(theta):
                eff_theta = -theta # Correct for Y-Down/CCW visual
                return cx + rx * math.cos(eff_theta), cy + ry * math.sin(eff_theta)
            
            # Move to start
            p0 = get_pt(start_rad)
            if filled:
                path.MoveToPoint(cx, cy)
                path.AddLineToPoint(p0[0], p0[1])
            else:
                path.MoveToPoint(p0[0], p0[1])
            
            # Split into segments (max 45 degrees for good approximation)
            # Bezier approx error is negligible for < 90 deg, 45 is safe.
            max_seg = math.radians(45)
            num_segs = max(1, int(math.ceil(abs(sweep_rad) / max_seg)))
            seg_span = sweep_rad / num_segs
            
            # Kappa for unit circle approx
            # L = 4/3 * tan(delta / 4)
            # Control points extend L * Radius along tangent.
            # Since we handle non-unit radius and elliptical transform manually:
            # CP = P + Tangent_Dir * (Length?)
            # Wait, derivative magnitude varies.
            # Better Formula:
            # P0, P3 are endpoints.
            # P1 = P0 + alpha * T0.
            # P2 = P3 - alpha * T3.
            # alpha = sin(delta/2) / (cos(delta/2) + 1) * 4/3 ? No that's for circle.
            # For general Bezier approx of Arc:
            # k = 4.0/3.0 * math.tan(abs(seg_span)/4.0)
            # But T0 and T3 must be normalized?
            # On ellipse, calculating offset vector is tricky if not uniform.
            # Solution: Calculate Unit Circle Control Points, THEN Scale/Translate.
            
            k = 4.0/3.0 * math.tan(abs(seg_span)/4.0)
            # Sign of k follows sweep direction? 
            # Tangent points in direction of sweep.
            # If sweep positive (CCW): Tangent is CCW.
            
            current_angle = start_rad
            
            for i in range(num_segs):
                angle_a = current_angle
                angle_b = current_angle + seg_span
                current_angle = angle_b
                
                # Unit Circle Points for this segment (using eff_angle logic)
                # We do calculations in "Logical CCW Unit Space" then map to Screen
                # Map Input Angle -> Unit Circle Angle
                # Input + -> Visual CCW.
                # Unit Circle Standard: + is CCW.
                # So we can treat input angles as Standard Unit Circle angles.
                # AND THEN apply the (rx, -ry) or whatever map.
                # Map: x_screen = cx + rx * cos(theta)
                #      y_screen = cy + ry * sin(-theta)  <-- The flip is here.
                
                # Unit Circle coords (u, v)
                ua = math.cos(angle_a)
                va = math.sin(angle_a)
                ub = math.cos(angle_b)
                vb = math.sin(angle_b)
                
                # Unit Tangents (Standard CCW)
                # T = (-sin, cos)
                uta = -math.sin(angle_a)
                vta = math.cos(angle_a)
                utb = -math.sin(angle_b)
                vtb = math.cos(angle_b)
                
                # Tangent Magnitude adjustment for Sweep Direction
                # If sweep is negative, we move "backwards" along tangent?
                # Formula k depends on abs(span).
                # P1 = P0 + k * T0 * sign(span)?
                # Or simply: Tangent follows curve.
                # If span > 0, we go in T direction.
                # If span < 0, we go in -T direction.
                direction = 1.0 if seg_span > 0 else -1.0
                
                # Control Points (Unit Space)
                ucp1 = (ua + k * direction * uta, va + k * direction * vta)
                ucp2 = (ub - k * direction * utb, vb - k * direction * vtb)
                
                # Transform to Ellipse Screen Space
                # Map (u, v) -> (cx + rx*u, cy + ry*sin(-theta)? No use the same map)
                # My map was: returns cx + rx*cos(-t), cy + ry*sin(-t).
                # cos(-t) = cos(t) = u.
                # sin(-t) = -sin(t) = -v.
                # So the map is: (u, v) -> (cx + rx*u, cy - ry*v)
                
                def transform_unit(u, v):
                    return cx + rx * u, cy - ry * v
                
                cp1 = transform_unit(ucp1[0], ucp1[1])
                cp2 = transform_unit(ucp2[0], ucp2[1])
                p2 = transform_unit(ub, vb)
                
                path.AddCurveToPoint(cp1[0], cp1[1], cp2[0], cp2[1], p2[0], p2[1])

            # Draw (Isotropic Stroke)
            ss_pen = wx.Pen(wx_color, width=1 * scale_f)
            ss_pen.SetCap(wx.CAP_ROUND)
            ss_pen.SetJoin(wx.JOIN_ROUND)

            if filled:
                path.CloseSubpath()
            
            # Draw
            ss_pen = wx.Pen(wx_color, width=1 * scale_f)
            gc.SetPen(ss_pen)
            
            if filled:
                ss_brush = wx.Brush(wx_color)
                gc.SetBrush(ss_brush)
                gc.FillPath(path)
                # FillPath usually handles the area?
                # If outline too? Usually Fill doesn't stroke.
                # If we want both (or just fill): MD_FILL_ARC usually implies filling slice.
                # Does it have outline? Typically yes or no depending on pen.
                # Let's Stroke it too to match `DrawEllipticArc` behavior (which usually draws outline with pen).
                gc.StrokePath(path)
            else:
                gc.StrokePath(path)
                
        # Fallback if GC fails (rare)
            ss_mem.SetPen(wx.Pen(wx_color, width=1 * scale_f))
            if filled:
                ss_mem.SetBrush(wx.Brush(wx_color))
            else:
                ss_mem.SetBrush(wx.TRANSPARENT_BRUSH)
            # Use w-1 logic for fallback? No, high res.
            ss_mem.DrawEllipticArc(0, 0, ss_w, ss_h, start, start + sweep)
            
        # Critical Flush: Must delete GC and unselect bitmap to ensure drawing is committed
        if 'gc' in locals():
             del gc
        
        ss_mem.SelectObject(wx.NullBitmap)
        del ss_mem
        
        # Downscale High Quality
        img = ss_bmp.ConvertToImage()
        img.Rescale(w, h, wx.IMAGE_QUALITY_HIGH)
        bmp = img.ConvertToBitmap()
        
        # Copy to target DC (mem)
        mem.DrawBitmap(bmp, 0, 0, True)
        
    elif mod_type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
        # 3-Point Percentage System (0-100 relative to bounding box)
        # Allows full freedom for all 3 vertices.
        if len(params) >= 6:
            p1x, p1y, p2x, p2y, p3x, p3y = params
        else:
            # Default: Upward Isosceles Triangle
            p1x, p1y = 50.0, 0.0
            p2x, p2y = 100.0, 100.0
            p3x, p3y = 0.0, 100.0
            
        # SS_W/H specific logic (similar to Arc inset)
        # Inset by half_pen to prevent clipping on edges (0% or 100%)
        # Note: If no SSAA, w/h are used (scale_f=1).
        ss_pen_width = 1 * 4 # Hardcoded generic ss_scale or passed? 
        # Wait, render_pixel_shape_to_bitmap doesn't have scale_f in this scope?
        # Ah, scale_f was local to MD_ARC.
        # But MD_TRIANGLE block is OUTSIDE MD_ARC block.
        # It's rendering to 'mem' (w/h) OR 'ss_mem' (ss_w/ss_h)?
        # Let's check lines 270-300: 
        # Line 275: mem.DrawBitmap(bmp, 0, 0, True) <-- This is drawing the Arc result.
        # MD_TRIANGLE is drawing DIRECTLY to `mem`.
        # `mem` size is `w, h`.
        # So we are drawing at 1x scale?
        # Yes, lines 290: mem.DrawPolygon(points).
        # So pen width is 1.
        
        pen_w = 1
        half_pen = 0.5
        
        # Calculate Inset Coordinates
        # 0% -> 0.5
        # 100% -> size - 0.5
        # Range = size - 1
        
        def to_px(pct, size):
            return int(half_pen + (pct / 100.0) * (size - pen_w))

        points = [
            (to_px(p1x, w), to_px(p1y, h)),
            (to_px(p2x, w), to_px(p2y, h)),
            (to_px(p3x, w), to_px(p3y, h))
        ]
        mem.DrawPolygon(points)
        
    elif mod_type == "MD_LINE":
        # 4-Point Percentage System (0-100 relative to w/h)
        # Reusing the Inset Logic from Triangle
        ss_pen_width = 1 * 4 # See comment above for Triangle (pen_w=1, scale=1)
        pen_w = 1
        half_pen = 0.5
        
        def to_px(pct, size):
            return int(half_pen + (pct / 100.0) * (size - pen_w))

        if len(params) >= 4:
            x1, y1, x2, y2 = params
        elif len(params) == 2:
            # Legacy fallback (Shouldn't happen if Parser/Selector upgrades it, but for safety)
            # Legacy: Start 0,0, End params[0], params[1]
            x1, y1 = 0.0, 0.0
            # Convert pixels to pct? No, legacy params hold pixels in old format...
            # BUT if we upgraded the parser, the params in memory ARE PERCENTAGES.
            # So if we see 2 params, what are they?
            # If the AuroraGT import (importers/aurora.py) ran, it has 4 params.
            # If we load old JSON, it has 2 params (Pixels).
            # We must detect if params are likely pixels or percentages?
            # Or just assume 2 params = Pixels (old raw params).
            # Let's map pixels to percentages, OR just map pixels to pixels.
            endX, endY = params
            mem.DrawLine(0, 0, int(endX), int(endY))
            mem.SelectObject(wx.NullBitmap)
            return bmp
            
        else:
             x1, y1, x2, y2 = 0.0, 0.0, 100.0, 100.0

        p1 = (to_px(x1, w), to_px(y1, h))
        p2 = (to_px(x2, w), to_px(y2, h))
        mem.DrawLine(p1[0], p1[1], p2[0], p2[1])

    mem.SelectObject(wx.NullBitmap)
    return bmp

class ThumbnailGenerator:
    def __init__(self):
        self.asset_cache = {} # image_id -> wx.Image

    def clear_cache(self):
        self.asset_cache = {}

    def render_thumbnail(self, project: 'Project', item, width: int, height: int, custom_scale: float = 0.0, flip_x: bool = False, flip_y: bool = False, rotation: float = 0.0, mapping: Optional['ModuleMapping'] = None, swap: Any = None) -> wx.Bitmap:
        bmp = wx.Bitmap(width, height)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(T.thumb))
        dc.Clear()
        
        self.draw_thumbnail_direct(dc, project, item, wx.Rect(0, 0, width, height), custom_scale, flip_x, flip_y, rotation, mapping, swap)
        
        dc.SelectObject(wx.NullBitmap)
        return bmp

    def draw_thumbnail_direct(self, dc: wx.DC, project: 'Project', item, rect: wx.Rect, custom_scale: float = 0.0, flip_x: bool = False, flip_y: bool = False, rotation: float = 0.0, mapping: Optional['ModuleMapping'] = None, swap: Any = None):
        """Draws the item directly onto the provided DC within the target rect."""
        width, height = rect.width, rect.height
        x_off, y_off = rect.x, rect.y
        
        
         # Handle Module Rendering
        if getattr(item, 'image_id', None) is not None and getattr(item, 'rect', None) is not None and not hasattr(item, 'fmodules'):
            mod = item
            mw, mh = mod.rect[2], mod.rect[3]
            if getattr(mod, 'rotated', False):
                mw, mh = mh, mw

            
            # Scale calculation
            content_w = max(1, mw)
            content_h = max(1, mh)
            if custom_scale > 0:
                scale = custom_scale
            else:
                scale = min(width / content_w, height / content_h)
            
            # Center in rect
            off_x = x_off + (width - content_w * scale) / 2
            off_y = y_off + (height - content_h * scale) / 2
            
            # Direct Draw
            if mod.type == "MD_IMAGE":
                asset = project.get_image(mod.image_id)
                if asset:
                     try:
                        if asset.id not in self.asset_cache:
                            full_img = load_wx_image_safely(asset.file_path)
                            if asset.transparent_color:
                                full_img.SetMaskColour(*asset.transparent_color)
                            self.asset_cache[asset.id] = full_img
                        
                        full_img = self.asset_cache[asset.id]
                        rx, ry, rw, rh = mod.rect
                        if rx + rw <= full_img.GetWidth() and ry + rh <= full_img.GetHeight():
                            sub = full_img.GetSubImage(wx.Rect(int(rx), int(ry), int(rw), int(rh)))
                            
                            if getattr(mod, 'rotated', False):
                                sub = sub.Rotate90(clockwise=False)
                                rw, rh = rh, rw
                            
                            if flip_x: sub = sub.Mirror(True)
                            if flip_y: sub = sub.Mirror(False)
                            
                            w_scaled = int(rw * scale)
                            h_scaled = int(rh * scale)
                            
                            if w_scaled > 0 and h_scaled > 0:
                                sub = sub.Scale(w_scaled, h_scaled, wx.IMAGE_QUALITY_NEAREST)
                                sub_bmp = sub.ConvertToBitmap()
                                dc.DrawBitmap(sub_bmp, int(off_x), int(off_y), True) 
                     except wx.wxAssertionError:
                         pass  # an image wx cannot cut: the thumbnail stays empty
            else:
                 # Shape Module
                 shape_bmp = render_pixel_shape_to_bitmap(mod.type, mw, mh, mod.color, mod.params)
                 if shape_bmp:
                     # Flatten to scaled size
                     img = shape_bmp.ConvertToImage()
                     w_scaled = int(mw * scale)
                     h_scaled = int(mh * scale)
                     if w_scaled > 0 and h_scaled > 0:
                         img.Rescale(w_scaled, h_scaled, wx.IMAGE_QUALITY_NEAREST)
                         final_bmp = img.ConvertToBitmap()
                         dc.DrawBitmap(final_bmp, int(off_x), int(off_y), True)
            return

        # Frames (nested frames, part rotation, shapes, mapping) go through the parity-checked renderer.
        if not hasattr(item, 'fmodules') or not item.fmodules:
            return
        from ui.frame_render import SHARED, to_bitmap, transform

        a, b = transform(flip_x, flip_y, rotation)
        image, _x, _y = SHARED.render(project, item, mapping, a, b, swap)
        iw, ih = image.size
        if iw <= 1 and ih <= 1 and not image.getbbox():
            return
        if custom_scale > 0:
            scale = custom_scale
        else:
            scale = min(32.0, width / max(1, iw), height / max(1, ih))
        bmp = to_bitmap(image, scale)
        dc.DrawBitmap(bmp, int(x_off + (width - bmp.GetWidth()) / 2), int(y_off + (height - bmp.GetHeight()) / 2), True)

    def frame_size(self, project: 'Project', frame, mapping: Optional['ModuleMapping'] = None, swap: Any = None) -> Tuple[int, int]:
        """Pixel size of a frame as drawn (for palettes that scale all frames alike)."""
        if not getattr(frame, 'fmodules', None):
            return (0, 0)
        from ui.frame_render import SHARED

        image, _x, _y = SHARED.render(project, frame, mapping, swap=swap)
        return image.size if image.getbbox() else (0, 0)
