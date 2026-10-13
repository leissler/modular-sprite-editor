from __future__ import annotations
import math
import time
from typing import Optional, Tuple
import wx

from ui import app_services

# Integer levels keep every source pixel the same size on screen (nearest-neighbour scaling).
ZOOM_LEVELS = (0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 24.0, 32.0)

# Smooth wheel zoom: x1.1 per mouse notch (rotation is normalised by the platform's wheel
# delta: 120 on Windows/GTK, 10 on macOS, where trackpads send small precise deltas).
WHEEL_ZOOM_PER_NOTCH = math.log(1.1)
MAX_ZOOM_FACTOR_PER_EVENT = 1.6
# Pause after the last wheel/pinch event before the zoom snaps to an integer level.
ZOOM_SNAP_DELAY_MS = 180
# A gesture that changed the zoom by more than this always ends at least one level away.
MIN_DELIBERATE_ZOOM = math.log(1.02)


def wheel_zoom_factor(rotation: float, wheel_delta: float = 120.0) -> float:
    """Continuous zoom factor for one wheel event."""
    notches = float(rotation) / max(1.0, float(wheel_delta))
    limit = math.log(MAX_ZOOM_FACTOR_PER_EVENT)
    return math.exp(max(-limit, min(limit, notches * WHEEL_ZOOM_PER_NOTCH)))


def nearest_zoom_level(zoom: float, levels) -> float:
    """Closest level on a logarithmic scale (3.4 -> 3, 3.6 -> 4, 0.7 -> 0.5 or 1)."""
    target = math.log(max(1e-6, float(zoom)))
    return min(levels, key=lambda level: abs(math.log(level) - target))


def snap_zoom_level(zoom: float, gesture_start: float, levels) -> float:
    """
    Level to settle on when a zoom gesture stops: the nearest level, but a deliberate gesture
    (e.g. a single mouse notch, only x1.1) never snaps back to the level it started from.
    """
    target = nearest_zoom_level(zoom, levels)
    start_level = nearest_zoom_level(gesture_start, levels)
    moved = math.log(max(1e-6, float(zoom))) - math.log(max(1e-6, float(gesture_start)))
    if target == start_level and abs(moved) > MIN_DELIBERATE_ZOOM:
        ordered = sorted(levels)
        idx = ordered.index(start_level)
        idx = min(len(ordered) - 1, idx + 1) if moved > 0 else max(0, idx - 1)
        target = ordered[idx]
    return target


class WheelGestureFilter:
    """
    Locks a scroll gesture to one axis.

    Two-finger scrolling on a trackpad emits small sideways events while the fingers move
    vertically (and vertical ones during a sideways swipe). The first events of a gesture decide
    its axis; events on the other axis are ignored until the gesture pauses. A full mouse-wheel
    notch (``wheel_delta``: 120 on Windows/GTK, 10 on macOS) decides immediately.
    """

    GESTURE_GAP_SECONDS = 0.25
    DECIDE_UNITS = 12.0

    def __init__(self) -> None:
        self._axis: Optional[str] = None
        self._last_time = float("-inf")
        self._acc_h = 0.0
        self._acc_v = 0.0
        self._start_pending = False
        # True for the first accepted event of a gesture (reset per-gesture accumulators then).
        self.gesture_started = False

    def accept(
        self,
        horizontal: bool,
        rotation: float,
        now: Optional[float] = None,
        wheel_delta: Optional[float] = None,
    ) -> bool:
        """True if this event belongs to the gesture's axis and should be handled."""
        now = time.monotonic() if now is None else float(now)
        if now - self._last_time > self.GESTURE_GAP_SECONDS:
            self._axis = None
            self._acc_h = 0.0
            self._acc_v = 0.0
            self._start_pending = True
        self._last_time = now
        self.gesture_started = False

        if self._axis is None:
            if horizontal:
                self._acc_h += abs(float(rotation))
            else:
                self._acc_v += abs(float(rotation))
            threshold = self.DECIDE_UNITS
            if wheel_delta and wheel_delta > 0:
                threshold = min(threshold, float(wheel_delta))
            if self._acc_h + self._acc_v < threshold:
                return False
            self._axis = "h" if self._acc_h > self._acc_v else "v"
        if self._axis != ("h" if horizontal else "v"):
            return False
        self.gesture_started = self._start_pending
        self._start_pending = False
        return True


# What shows behind the artwork. Hiding a sheet's transparent key colour is a separate switch
# (BaseCanvas.apply_key_colour): composition editors always hide it, only the Modules tab can show it.
BACKDROP_CHECKER = "checker"
BACKDROP_COLOUR = "colour"
DEFAULT_BACKDROP_COLOUR: Tuple[int, int, int] = (32, 32, 32)


CHECKER_STEP = 8  # checkerboard tile size in screen pixels
CHECKER_COLOURS = ((60, 60, 60), (80, 80, 80))


def _checker_bitmap(width: int, height: int, scale: float = 1.0) -> wx.Bitmap:
    """A checkerboard of CHECKER_STEP tiles (logical pixels), starting with a CHECKER_COLOURS[0] tile at the
    top-left, made at the display's scale factor so its edges stay sharp on HiDPI screens."""
    tile = max(1, int(round(CHECKER_STEP * scale)))
    columns = -(-width // CHECKER_STEP)
    bands = -(-height // CHECKER_STEP)
    band = [
        b"".join(bytes(CHECKER_COLOURS[(column + parity) % 2]) * tile for column in range(columns)) * tile
        for parity in (0, 1)
    ]
    data = b"".join(band[index % 2] for index in range(bands))
    bitmap = wx.Bitmap(wx.Image(columns * tile, bands * tile, data))
    bitmap.SetScaleFactor(tile / CHECKER_STEP)
    return bitmap


class BaseCanvas(wx.Panel):
    """
    Shared canvas providing:
    - Infinite workspace (pan/zoom) with one interaction model for every editor:
        wheel = zoom at cursor, Shift+wheel / horizontal wheel = pan horizontally,
        Alt+wheel = pan vertically, pinch = zoom,
        Space+drag, Alt+drag or middle-drag = pan
    - Pixel-art friendly integer zoom levels, fit-to-content
    - Coordinate transformation
    - Checkerboard background and grid rendering
    """

    def __init__(self, parent: wx.Window, style=wx.BORDER_SIMPLE):
        super().__init__(parent, style=style | wx.WANTS_CHARS)

        # View State
        self.zoom: float = 10.0
        self.pan: Tuple[float, float] = (0, 0)
        self.grid_spacing: Tuple[int, int] = (32, 32)
        self.show_grid: bool = True
        self.backdrop: str = BACKDROP_CHECKER
        self.backdrop_colour: Tuple[int, int, int] = DEFAULT_BACKDROP_COLOUR
        self.apply_key_colour: bool = True
        self.min_zoom: float = 0.5
        self.max_zoom: float = 32.0

        # Internal Interaction State
        self._wheel_filter = WheelGestureFilter()
        self._zoom_snap_call: Optional[wx.CallLater] = None
        self._zoom_snap_anchor: Optional[wx.Point] = None
        self._zoom_gesture_start: Optional[float] = None
        self._checker: Optional[Tuple[float, wx.Bitmap]] = None  # (scale, bitmap): the backdrop in one call
        self._panning = False
        self._start = wx.Point()
        self._fit_pending = False

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        # Event Bindings
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mousewheel)
        self.Bind(wx.EVT_MIDDLE_DOWN, self.on_pan_start)
        self.Bind(wx.EVT_MIDDLE_UP, self.on_pan_end)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.Bind(wx.EVT_KEY_DOWN, self._on_base_key_down)
        self.Bind(wx.EVT_SIZE, self._on_base_size)
        if hasattr(wx, "EVT_MAGNIFY"):
            self.Bind(wx.EVT_MAGNIFY, self.on_magnify)
        # Derived classes bind LEFT_DOWN/UP and MOTION and start with:
        #   if self.begin_pan_if_requested(event): return
        #   if self.handle_pan_motion(event): return

    # --- Coordinate Systems ---
    def world_to_screen(self, pt: Tuple[float, float]) -> Tuple[float, float]:
        cx, cy = self.GetClientSize().width // 2, self.GetClientSize().height // 2
        return (cx + (pt[0] + self.pan[0]) * self.zoom, cy + (pt[1] + self.pan[1]) * self.zoom)

    def screen_to_world(self, pt: wx.Point) -> Tuple[float, float]:
        cx, cy = self.GetClientSize().width // 2, self.GetClientSize().height // 2
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
        self._notify_zoom()
        self.Refresh(False)

    def get_view_state(self) -> Tuple[Tuple[float, float], float]:
        return (self.pan, self.zoom)

    def set_grid_spacing(self, spacing: Tuple[int, int]) -> None:
        self.grid_spacing = spacing
        self.Refresh(False)

    def set_show_grid(self, show: bool) -> None:
        self.show_grid = show
        self.Refresh(False)

    def set_backdrop(self, mode: str, colour: Optional[Tuple[int, int, int]] = None) -> None:
        self.backdrop = mode if mode in (BACKDROP_CHECKER, BACKDROP_COLOUR) else BACKDROP_CHECKER
        if colour is not None:
            self.backdrop_colour = (int(colour[0]), int(colour[1]), int(colour[2]))
        self.Refresh(False)

    def set_apply_key_colour(self, apply: bool) -> None:
        self.apply_key_colour = bool(apply)
        self.Refresh(False)

    def backdrop_fill_colour(self) -> Tuple[int, int, int]:
        """The solid backdrop colour (the scene stage uses its scene's background instead)."""
        return self.backdrop_colour

    def draw_backdrop(self, dc: wx.DC) -> None:
        if self.backdrop == BACKDROP_COLOUR:
            dc.SetBackground(wx.Brush(wx.Colour(*self.backdrop_fill_colour())))
            dc.Clear()
        else:
            dc.Clear()
            self._draw_checkerboard(dc)

    def _notify_zoom(self) -> None:
        if self.IsShownOnScreen():
            app_services.show_zoom(self.zoom)

    def _zoom_levels(self) -> Tuple[float, ...]:
        return tuple(z for z in ZOOM_LEVELS if self.min_zoom - 1e-6 <= z <= self.max_zoom + 1e-6)

    def set_zoom_level(self, zoom: float, anchor: Optional[wx.Point] = None) -> None:
        """Set zoom, keeping the world point under ``anchor`` (default: view centre) fixed."""
        new_zoom = max(self.min_zoom, min(self.max_zoom, float(zoom)))
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        if anchor is None:
            size = self.GetClientSize()
            anchor = wx.Point(size.width // 2, size.height // 2)
        world_before = self.screen_to_world(anchor)
        self.zoom = new_zoom
        cx, cy = self.GetClientSize().width // 2, self.GetClientSize().height // 2
        self.pan = (
            (anchor.x - cx) / new_zoom - world_before[0],
            (anchor.y - cy) / new_zoom - world_before[1],
        )
        self._notify_zoom()
        self.Refresh(False)

    def zoom_step(self, direction: int, anchor: Optional[wx.Point] = None) -> None:
        """Move one integer zoom level in or out (direction > 0 zooms in)."""
        levels = self._zoom_levels()
        if not levels:
            return
        if direction > 0:
            target = next((z for z in levels if z > self.zoom + 1e-6), levels[-1])
        else:
            target = next((z for z in reversed(levels) if z < self.zoom - 1e-6), levels[0])
        self.set_zoom_level(target, anchor)

    def get_content_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        """World-space (x0, y0, x1, y1) of what this canvas shows. Override per canvas."""
        return None

    def fit_to_content(self, margin_px: int = 24) -> None:
        bounds = self.get_content_bounds()
        size = self.GetClientSize()
        if bounds and (size.width <= 1 or size.height <= 1):
            # Not laid out yet (hidden tab): fit once the canvas gets a real size.
            self._fit_pending = True
            return
        self._fit_pending = False
        if not bounds:
            self.pan = (0.0, 0.0)
            self.Refresh(False)
            return
        x0, y0, x1, y1 = bounds
        w = max(1.0, x1 - x0)
        h = max(1.0, y1 - y0)
        avail_w = max(1, size.width - 2 * margin_px)
        avail_h = max(1, size.height - 2 * margin_px)
        fitting = [z for z in self._zoom_levels() if w * z <= avail_w and h * z <= avail_h]
        self.zoom = fitting[-1] if fitting else self._zoom_levels()[0]
        self.pan = (-(x0 + x1) / 2.0, -(y0 + y1) / 2.0)
        self._notify_zoom()
        self.Refresh(False)

    # --- Drawing Helpers ---
    def _draw_checkerboard(self, dc: wx.DC) -> None:
        """8 px tiles anchored at the world origin, from a cached bitmap: one draw call instead of one per tile
        (thousands of GDI calls made every repaint slow on Windows, so playback starved the event queue)."""
        size = self.GetClientSize()
        period = 2 * CHECKER_STEP
        width, height = size.width + period, size.height + period
        scale = self.GetContentScaleFactor()
        cached = self._checker
        if cached is None or cached[0] != scale or cached[1].GetScaledWidth() < width or cached[1].GetScaledHeight() < height:
            cached = self._checker = (scale, _checker_bitmap(width, height, scale))
        bitmap = cached[1]
        ox, oy = self.world_to_screen((0, 0))
        # Shift the pattern so its first tile lies at the world origin (tiles stay anchored while panning).
        dc.DrawBitmap(bitmap, int(math.floor(ox)) % period - period, int(math.floor(oy)) % period - period)

    def _draw_grid(self, gc: wx.GraphicsContext) -> None:
        if not self.show_grid:
            return

        w, h = self.GetClientSize()

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
        current_x = int((left_world // spacing_x) * spacing_x)
        while current_x <= right_world + spacing_x:
            sx, _ = self.world_to_screen((current_x, 0))
            sx = round(sx)
            if 0 <= sx <= w:
                gc.StrokeLine(sx, 0, sx, h)
            current_x += spacing_x

        # Horizontal lines
        current_y = int((top_world // spacing_y) * spacing_y)
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
        gc.StrokeLine(0, round(cy), w, round(cy))
        gc.StrokeLine(round(cx), 0, round(cx), h)

    def on_paint(self, event: wx.PaintEvent) -> None:
        # Override this but call base or use helper methods
        pass

    # --- Interaction ---
    def on_mousewheel(self, event: wx.MouseEvent) -> None:
        if event.LeftIsDown() or event.MiddleIsDown() or event.RightIsDown():
            return
        rotation = event.GetWheelRotation()
        if rotation == 0:
            return

        horizontal = event.GetWheelAxis() == wx.MOUSE_WHEEL_HORIZONTAL
        if not self._wheel_filter.accept(horizontal, rotation, wheel_delta=event.GetWheelDelta()):
            return
        if horizontal or event.ShiftDown() or event.AltDown():
            # Pan: one notch moves ~48 screen pixels.
            delta_px = (rotation / 120.0) * 48.0
            if horizontal:
                delta_px = -delta_px
            if horizontal or event.ShiftDown():
                self.pan = (self.pan[0] + delta_px / self.zoom, self.pan[1])
            else:
                self.pan = (self.pan[0], self.pan[1] + delta_px / self.zoom)
            self.Refresh(False)
            return

        # Zoom smoothly while the gesture runs; snap to an integer level once it stops.
        self._zoom_smoothly(wheel_zoom_factor(rotation, event.GetWheelDelta()), event.GetPosition())

    def on_magnify(self, event) -> None:
        factor = 1.0 + float(event.GetMagnification())
        if factor > 0.0:
            self._zoom_smoothly(min(MAX_ZOOM_FACTOR_PER_EVENT, factor), event.GetPosition())
        if hasattr(event, "IsGestureEnd") and event.IsGestureEnd():
            self._snap_zoom_now()

    def _zoom_smoothly(self, factor: float, anchor: wx.Point) -> None:
        if self._zoom_gesture_start is None:
            self._zoom_gesture_start = self.zoom
        self.set_zoom_level(self.zoom * factor, anchor)
        self._zoom_snap_anchor = wx.Point(anchor.x, anchor.y)
        if self._zoom_snap_call is not None and self._zoom_snap_call.IsRunning():
            self._zoom_snap_call.Restart(ZOOM_SNAP_DELAY_MS)
        else:
            self._zoom_snap_call = wx.CallLater(ZOOM_SNAP_DELAY_MS, self._snap_zoom_now)

    def _snap_zoom_now(self) -> None:
        if not self:  # canvas destroyed while the snap was pending
            return
        if self._zoom_snap_call is not None and self._zoom_snap_call.IsRunning():
            self._zoom_snap_call.Stop()
        self._zoom_snap_call = None
        start = self._zoom_gesture_start if self._zoom_gesture_start is not None else self.zoom
        self._zoom_gesture_start = None
        levels = self._zoom_levels()
        if levels:
            self.set_zoom_level(snap_zoom_level(self.zoom, start, levels), self._zoom_snap_anchor)

    def _space_held(self) -> bool:
        try:
            return bool(wx.GetKeyState(wx.WXK_SPACE))
        except wx.wxAssertionError:  # some ports only report modifier keys
            return False

    def begin_pan_if_requested(self, event: wx.MouseEvent) -> bool:
        """Start panning for Space+drag, Alt+drag or middle-drag. Returns True if panning started."""
        if event.MiddleDown() or event.AltDown() or self._space_held():
            self.on_pan_start(event)
            return True
        return False

    def on_pan_start(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        self._panning = True
        self._start = event.GetPosition()
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        if not self.HasCapture():
            self.CaptureMouse()

    def on_pan_end(self, _: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._panning = False
        self.SetCursor(wx.NullCursor)

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

    def _on_base_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        size = event.GetSize()
        if self._fit_pending and size.width > 1 and size.height > 1:
            wx.CallAfter(self.fit_to_content)
        self.Refresh(False)

    def _on_capture_lost(self, _event: wx.MouseCaptureLostEvent) -> None:
        self._panning = False

    def _on_base_key_down(self, event: wx.KeyEvent) -> None:
        # Space is the pan modifier: swallow it so it does not beep.
        if event.GetKeyCode() == wx.WXK_SPACE:
            return
        event.Skip()
