from __future__ import annotations
import time
from typing import Tuple, Optional
import wx

class BaseCanvas(wx.Panel):
    """
    Shared canvas providing:
    - Infinite workspace (pan/zoom)
    - Coordinate transformation
    - Checkerboard background
    - Grid rendering
    """

    def __init__(self, parent: wx.Window, style=wx.BORDER_SIMPLE):
        super().__init__(parent, style=style)
        
        # View State
        self.zoom: float = 10.0
        self.pan: Tuple[float, float] = (0, 0)
        self.grid_spacing: Tuple[int, int] = (32, 32)
        self.show_grid: bool = True
        
        # Internal Interaction State
        self._wheel_accumulator = 0
        self._panning = False
        self._last_pan_pos: Optional[wx.Point] = None
        self._last_clamp_time: float = 0.0
        self._last_clamp_dir: int = 0
        self._start = wx.Point()

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        
        # Event Bindings
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mousewheel)
        self.Bind(wx.EVT_MIDDLE_DOWN, self.on_pan_start)
        self.Bind(wx.EVT_MIDDLE_UP, self.on_pan_end)
        # Note: Derived classes should likely override ON_LEFT_DOWN/UP and MOTION,
        # but call base handlers or implement panning hooks if needed.

    # --- Coordinate Systems ---
    def world_to_screen(self, pt: Tuple[float, float]) -> Tuple[float, float]:
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        return (cx + (pt[0] + self.pan[0]) * self.zoom, cy + (pt[1] + self.pan[1]) * self.zoom)

    def screen_to_world(self, pt: wx.Point) -> Tuple[float, float]:
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        return (
            (pt.x - cx) / self.zoom - self.pan[0],
            (pt.y - cy) / self.zoom - self.pan[1],
        )

    # --- View Control ---
    def center_view(self, world_pt: Tuple[float, float]) -> None:
        self.pan = (-world_pt[0], -world_pt[1])
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

    # --- Drawing Helpers ---
    def _draw_checkerboard(self, dc: wx.DC) -> None:
        size = self.GetClientSize()
        step = 8
        c1 = wx.Colour(60, 60, 60)
        c2 = wx.Colour(80, 80, 80)
        
        b1, b2 = wx.Brush(c1), wx.Brush(c2)
        dc.SetPen(wx.TRANSPARENT_PEN)
        
        # Get screen position of world origin (0, 0)
        ox, oy = self.world_to_screen((0, 0))
        
        # Determine the range of tiles that are visible on screen.
        # Screen coordinate x mapping to world-relative tile index ix: sx = ox + ix * step
        # Solving for ix at screen 0: ix = (0 - ox) // step
        first_ix = int((0 - ox) // step)
        first_iy = int((0 - oy) // step)
        last_ix = int((size.width - ox) // step)
        last_iy = int((size.height - oy) // step)
        
        for iy in range(first_iy, last_iy + 1):
            sy = int(oy + iy * step)
            for ix in range(first_ix, last_ix + 1):
                sx = int(ox + ix * step)
                dc.SetBrush(b1 if (ix + iy) % 2 == 0 else b2)
                dc.DrawRectangle(sx, sy, step, step)

    def _draw_grid(self, gc: wx.GraphicsContext) -> None:
        if not self.show_grid:
            return
            
        w, h = self.GetClientSize()
        
        # Calculate visible grid lines
        top_left = self.screen_to_world(wx.Point(0, 0))
        bottom_right = self.screen_to_world(wx.Point(w, h))
        
        left_world = top_left[0]
        top_world = top_left[1]
        right_world = bottom_right[0]
        bottom_world = bottom_right[1]
        
        spacing_x, spacing_y = self.grid_spacing
        
        grid_pen = wx.Pen(wx.Colour(100, 100, 100), width=1, style=wx.PENSTYLE_SOLID)
        gc.SetPen(grid_pen)

        # Vertical lines
        start_x = int((left_world // spacing_x) * spacing_x)
        current_x = start_x
        while current_x <= right_world + spacing_x:
            sx, _ = self.world_to_screen((current_x, 0))
            # Round to align with pixels
            sx = round(sx)
            if 0 <= sx <= w:
                gc.StrokeLine(sx, 0, sx, h)
            current_x += spacing_x

        # Horizontal lines
        start_y = int((top_world // spacing_y) * spacing_y)
        current_y = start_y
        while current_y <= bottom_world + spacing_y:
            _, sy = self.world_to_screen((0, current_y))
            sy = round(sy)
            if 0 <= sy <= h:
                gc.StrokeLine(0, sy, w, sy)
            current_y += spacing_y

        # Origin axes
        axis_pen = wx.Pen(wx.Colour(200, 200, 200, 100), width=2)
        gc.SetPen(axis_pen)
        cx, cy = self.world_to_screen((0, 0))
        # Draw infinite axes? Just current screen view
        gc.StrokeLine(0, round(cy), w, round(cy))
        gc.StrokeLine(round(cx), 0, round(cx), h)

    def on_paint(self, event: wx.PaintEvent) -> None:
        # Override this but call base or use helper methods
        pass

    # --- Interaction ---
    def on_mousewheel(self, event: wx.MouseEvent) -> None:
        if event.LeftIsDown() or event.MiddleIsDown() or event.RightIsDown():
             return

        # Accumulate rotation to handle high-res trackpads
        self._wheel_accumulator += event.GetWheelRotation()
        
        # Threshold for zoom step. 
        # Standard mouse is 120 per notch. Trackpads can send tiny amounts.
        # We process in chunks to avoid jitter.
        step_size = 10 # Smaller than 120 to be responsive, but large enough to eat jitter
        
        if abs(self._wheel_accumulator) < step_size:
            return
            
        steps = int(self._wheel_accumulator / step_size)
        remainder = self._wheel_accumulator % step_size
        
        # Keep the sign of remainder consistent with accumulator if simple modulo fails logic
        # Actually simple truncation is fine, we just update accumulator to remainder
        self._wheel_accumulator -= (steps * step_size)
        
        # Avoid huge jumps if events stacked up
        steps = max(-5, min(5, steps))
        
        if steps == 0:
            return

        factor = 1.1 ** steps # Exponential zoom for multiple steps
        now = time.monotonic()
        max_zoom = 32.0
        min_zoom = 1.0

        # Bounce protection logic
        # We use 'steps' as proxy for rotation direction
        if steps > 0 and self.zoom >= max_zoom - 1e-5:
            self._last_clamp_time = now
            self._last_clamp_dir = 1
            return
        if steps < 0 and self.zoom <= min_zoom + 1e-5:
            self._last_clamp_time = now
            self._last_clamp_dir = -1
            return
        if self._last_clamp_dir == 1 and steps < 0 and (now - self._last_clamp_time) < 0.2:
            return
        if self._last_clamp_dir == -1 and steps > 0 and (now - self._last_clamp_time) < 0.2:
            return


        old_zoom = self.zoom
        new_zoom = max(min_zoom, min(max_zoom, self.zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-6:
            return

        mouse_pos = event.GetPosition()
        world_before = self.screen_to_world(mouse_pos)
        self.zoom = new_zoom
        
        # Adjust pan to zoom towards mouse
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        self.pan = (
            (mouse_pos.x - cx) / new_zoom - world_before[0],
            (mouse_pos.y - cy) / new_zoom - world_before[1],
        )
        
            
        self.Refresh(False)

    def on_pan_start(self, event: wx.MouseEvent) -> None:
        self._panning = True
        self._start = event.GetPosition()
        self.CaptureMouse()

    def on_pan_end(self, _: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._panning = False
        self._panning_alt = False

    def handle_pan_motion(self, event: wx.MouseEvent) -> bool:
        """Helper for mouse move. Returns True if handled (panning)."""
        if self._panning:
            pos = event.GetPosition()
            dx = pos.x - self._start.x
            dy = pos.y - self._start.y
            self.pan = (self.pan[0] + dx / self.zoom, self.pan[1] + dy / self.zoom)
            self._start = pos
            self.Refresh(False)
            return True
        return False
