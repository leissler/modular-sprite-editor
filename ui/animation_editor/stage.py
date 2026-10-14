"""Stage: the current step with onion skin, the motion path of the step offsets, and offset dragging."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import wx

from models import AFrame, Animation, Project
from ui import first_steps
from ui.canvas import GHOST_NEXT, GHOST_PREVIOUS, FrameCanvas
from ui.dpi import px

ONION_MODES: List[Tuple[str, str]] = [("Off", "off"), ("Previous", "previous"), ("Next", "next"), ("Both", "both")]


class _FrameDropTarget(wx.TextDropTarget):
    def __init__(self, stage: "AnimationStage"):
        super().__init__()
        self.stage = stage

    def OnDropText(self, x: int, y: int, data: str) -> bool:
        prefix, _, rest = data.partition(":")
        if prefix.strip().upper() not in ("FRAME", "FRAME_REF") or not rest:
            return False
        ids = [i.strip() for i in rest.split(":")[-1].split(",") if i.strip()]  # several: "FRAME:id,id,..."
        if self.stage.on_drop_frames and ids:
            self.stage.on_drop_frames(ids)
        return True


class AnimationStage(FrameCanvas):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project)
        self.zoom = 4.0
        self.max_zoom = 24.0
        self.show_points = False
        self.show_collision = False
        self.animation: Optional[Animation] = None
        self.step_index = -1
        self.selected: Set[int] = set()
        self.mirror: Tuple[bool, bool] = (False, False)
        self.onion = "off"
        self.show_path = True
        self._dots: List[Tuple[int, float, float]] = []
        self._drag_origin: Optional[Tuple[float, float]] = None
        self._drag_moved = (0, 0)
        # Events of the step shown (label, colour): active while it shows; they flash when it starts in the preview.
        self.events: List[Tuple[str, Tuple[int, int, int]]] = []
        self.event_flash = 0.0  # 1 when the step just started, fading to 0

        # Callbacks (set by the panel)
        self.on_pick_step: Optional[Callable[[int, bool], None]] = None  # (index, additive)
        self.on_drag_begin: Optional[Callable[[], None]] = None
        self.on_drag: Optional[Callable[[int, int], None]] = None  # total (dx, dy) in animation space
        self.on_drag_end: Optional[Callable[[bool], None]] = None  # moved?
        self.on_drop_frames: Optional[Callable[[List[str]], None]] = None
        self.SetDropTarget(_FrameDropTarget(self))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_mouse_drag)

    # ------------------------------------------------------------------ data
    def set_project(self, project: Project) -> None:
        self.project = project
        self.clear_cache()

    def set_view(
        self,
        animation: Optional[Animation],
        step_index: int,
        selected: Set[int],
        mirror: Tuple[bool, bool],
        onion: str,
        show_path: bool,
    ) -> None:
        self.animation = animation
        self.step_index = step_index
        self.selected = set(selected)
        self.mirror = mirror
        self.onion = onion
        self.show_path = show_path
        af = self._step(step_index)
        if af:
            self.frame = self.project.get_frame(af.frame_id)
            self.frame_offset, self.render_flip_x, self.render_flip_y, self.render_rotation = self.step_transform(af)
        else:
            self.frame = None
            self.frame_offset, self.render_flip_x, self.render_flip_y, self.render_rotation = (0.0, 0.0), False, False, 0.0
        self.ghost_layers = self._ghosts()
        self.Refresh(False)

    def set_events(self, events: List[Tuple[str, Tuple[int, int, int]]], flash: float) -> None:
        if events != self.events or abs(flash - self.event_flash) > 1e-3:
            self.events = events
            self.event_flash = flash
            self.Refresh(False)

    def _draw_budget_hud(self, gc: wx.GraphicsContext) -> None:
        super()._draw_budget_hud(gc)
        self._draw_events(gc)

    def _draw_events(self, gc: wx.GraphicsContext) -> None:
        """The shown step's events as chips in the top-right corner, glowing while they have just fired."""
        if not self.events or not self.animation:
            return
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        gc.SetFont(font, wx.Colour(20, 20, 24))
        glow = max(0.0, min(1.0, self.event_flash))
        # Fired chips pop: they start a third larger and shrink back while the glow fades.
        gc.PushState()
        gc.Translate(self.GetClientSize().width - px(10), px(10))
        gc.Scale(1.0 + 0.35 * glow, 1.0 + 0.35 * glow)
        x = 0.0
        y = 0.0
        for label, rgb in reversed(self.events):
            tw, th = gc.GetTextExtent(label)
            w, h = tw + px(14), th + px(8)
            x -= w
            if glow > 0:
                gc.SetPen(wx.Pen(wx.Colour(255, 255, 255, int(220 * glow)), int(round(2 + 3 * glow))))
            else:
                gc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 120), 1))
            gc.SetBrush(wx.Brush(wx.Colour(*(int(c + (255 - c) * 0.55 * glow) for c in rgb), 235)))
            gc.DrawRoundedRectangle(x, y, w, h, h / 2)
            gc.DrawText(label, x + px(7), y + px(4))
            x -= px(6)
        gc.PopState()

    def _step(self, index: int) -> Optional[AFrame]:
        if self.animation and 0 <= index < len(self.animation.aframes):
            return self.animation.aframes[index]
        return None

    def step_transform(self, af: AFrame) -> Tuple[Tuple[float, float], bool, bool, float]:
        """Offset, flips and rotation the canvas uses to draw a step, inside the mirror preview.

        A step is drawn flip-then-rotate; mirroring it flips the image and offset and, for an odd number
        of mirror axes, reverses the rotation (M·R(a)·F = R(-a)·M·F).
        """
        mx, my = self.mirror
        ox, oy = float(af.offset[0]), float(af.offset[1])
        rotation = float(af.rotation_degrees)
        if mx ^ my:
            rotation = -rotation
        return (
            (-ox if mx else ox, -oy if my else oy),
            bool(af.flip_x) ^ mx,
            bool(af.flip_y) ^ my,
            rotation % 360.0,
        )

    def _ghosts(self) -> List[Dict[str, Any]]:
        if self.onion == "off" or not self.animation or self._step(self.step_index) is None:
            return []
        count = len(self.animation.aframes)
        wrap = self.animation.playback_type in ("loop", "backward") and count > 2
        picks: List[Tuple[int, Tuple[float, float, float, float]]] = []
        if self.onion in ("previous", "both"):
            prev = self.step_index - 1 if self.step_index > 0 else (count - 1 if wrap else -1)
            if prev >= 0 and prev != self.step_index:
                picks.append((prev, GHOST_PREVIOUS))
        if self.onion in ("next", "both"):
            nxt = self.step_index + 1 if self.step_index + 1 < count else (0 if wrap else -1)
            if nxt >= 0 and nxt != self.step_index:
                picks.append((nxt, GHOST_NEXT))
        layers = []
        for index, style in picks:
            af = self.animation.aframes[index]
            frame = self.project.get_frame(af.frame_id)
            if frame:
                offset, fx, fy, rot = self.step_transform(af)
                layers.append({"frame": frame, "offset": offset, "flip_x": fx, "flip_y": fy, "rotation": rot, "style": style})
        return layers

    def get_content_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        if not self.animation or not self.animation.aframes:
            return None
        boxes = []
        for af in self.animation.aframes:
            frame = self.project.get_frame(af.frame_id)
            if not frame:
                continue
            offset, fx, fy, rot = self.step_transform(af)
            with self.frame_transform(frame, offset, fx, fy, rot):
                box = self._frame_world_bounds()
            if box:
                boxes.append(box)
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    # ------------------------------------------------------------------ drawing
    def draw_content(self, gc: wx.GraphicsContext) -> None:
        self._dots = []
        if not self.animation:
            self._draw_hint(gc, first_steps.animations(self.project) or "Select an animation, or click + New in the list")
            return
        if not self.animation.aframes:
            self._draw_hint(gc, "Empty animation: drag frames from the library into the sequence below or onto the stage")
            return
        if self.frame is not None:
            super().draw_content(gc)
        if self.show_path:
            self._draw_path(gc)

    def _draw_hint(self, gc: wx.GraphicsContext, text: str) -> None:
        """A readable message on any backdrop (the base canvas's grey text vanishes on the checkerboard)."""
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(225, 228, 235))
        tw, th = gc.GetTextExtent(text)
        size = self.GetClientSize()
        x, y = (size.width - tw) / 2, size.height / 2 - th - px(14)
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(20, 21, 24, 210)))
        gc.DrawRoundedRectangle(x - px(12), y - px(7), tw + px(24), th + px(14), px(6))
        gc.DrawText(text, x, y)

    def _draw_path(self, gc: wx.GraphicsContext) -> None:
        anim = self.animation
        if not anim:
            return
        mx, my = self.mirror
        points = []
        for index, af in enumerate(anim.aframes):
            x, y = float(af.offset[0]), float(af.offset[1])
            sx, sy = self.world_to_screen((-x if mx else x, -y if my else y))
            points.append((index, sx, sy))
        self._dots = points
        if len(points) >= 2:
            gc.SetPen(wx.Pen(wx.Colour(110, 180, 255, 200), 1))
            path = gc.CreatePath()
            path.MoveToPoint(points[0][1], points[0][2])
            for _i, sx, sy in points[1:]:
                path.AddLineToPoint(sx, sy)
            gc.StrokePath(path)
        # Unselected first, then selected, then the current step on top.
        order = sorted(points, key=lambda p: (p[0] == self.step_index, p[0] in self.selected))
        for index, sx, sy in order:
            current = index == self.step_index
            chosen = index in self.selected
            gc.SetPen(wx.Pen(wx.Colour(255, 255, 255) if (current or chosen) else wx.Colour(20, 20, 20), 1))
            gc.SetBrush(wx.Brush(wx.Colour(255, 176, 64) if chosen else wx.Colour(110, 180, 255)))
            r = px(5) if current else px(4)
            gc.DrawEllipse(sx - r, sy - r, 2 * r, 2 * r)
            if current:
                gc.SetBrush(wx.TRANSPARENT_BRUSH)
                gc.DrawEllipse(sx - r - px(3), sy - r - px(3), 2 * r + px(6), 2 * r + px(6))

    # ------------------------------------------------------------------ interaction
    def _dot_at(self, pos: wx.Point) -> int:
        best, best_d = -1, float(px(7)) ** 2
        for index, sx, sy in self._dots:
            d = (sx - pos.x) ** 2 + (sy - pos.y) ** 2
            if d <= best_d:
                best, best_d = index, d
        return best

    def on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        if self.begin_pan_if_requested(event):
            return
        if not self.animation or not self.animation.aframes:
            return
        dot = self._dot_at(event.GetPosition())
        if dot >= 0 and self.on_pick_step:
            self.on_pick_step(dot, event.ShiftDown() or event.CmdDown())
        self._drag_origin = self.screen_to_world(event.GetPosition())
        self._drag_moved = (0, 0)
        if self.on_drag_begin:
            self.on_drag_begin()
        if not self.HasCapture():
            self.CaptureMouse()

    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return
        if self._drag_origin is None or not event.Dragging() or not event.LeftIsDown():
            return
        wx_, wy = self.screen_to_world(event.GetPosition())
        dx = round(wx_ - self._drag_origin[0])
        dy = round(wy - self._drag_origin[1])
        # Drag in screen direction, also while the mirror preview is on.
        if self.mirror[0]:
            dx = -dx
        if self.mirror[1]:
            dy = -dy
        if (dx, dy) != self._drag_moved:
            self._drag_moved = (dx, dy)
            if self.on_drag:
                self.on_drag(dx, dy)

    def on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
            self.on_pan_end(event)
            return
        if self.HasCapture():
            self.ReleaseMouse()
        if self._drag_origin is not None:
            moved = self._drag_moved != (0, 0)
            self._drag_origin = None
            if self.on_drag_end:
                self.on_drag_end(moved)
