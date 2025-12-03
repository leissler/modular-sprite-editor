"""Canvas widgets used by the frame and animation editors."""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

import wx

from models import Frame, FModule, Module, Project

Color = Tuple[int, int, int]


def _color_from_id(identifier: str) -> Color:
    seed = sum(ord(c) for c in identifier)
    return ((seed * 37) % 200 + 30, (seed * 57) % 200 + 30, (seed * 97) % 200 + 30)


class GridCanvasBase(wx.Panel):
    """Shared grid canvas with pan/zoom and center-origin coordinates."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.zoom: float = 1.0
        self.pan: Tuple[float, float] = (0.0, 0.0)
        self.show_grid = True
        self._panning = False
        self._last_mouse = wx.Point()
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mousewheel)
        self.Bind(wx.EVT_MIDDLE_DOWN, self.on_pan_start)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_pan_start)
        self.Bind(wx.EVT_MIDDLE_UP, self.on_pan_end)
        self.Bind(wx.EVT_RIGHT_UP, self.on_pan_end)
        self.Bind(wx.EVT_MOTION, self.on_mouse_move)

    # Coordinate transforms
    def world_to_screen(self, pt: Tuple[float, float]) -> Tuple[float, float]:
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        return (
            cx + (pt[0] + self.pan[0]) * self.zoom,
            cy + (pt[1] + self.pan[1]) * self.zoom,
        )

    def screen_to_world(self, pt: wx.Point) -> Tuple[float, float]:
        cx, cy = self.GetClientSize().width / 2, self.GetClientSize().height / 2
        return (
            (pt.x - cx) / self.zoom - self.pan[0],
            (pt.y - cy) / self.zoom - self.pan[1],
        )

    # Event handlers
    def on_mousewheel(self, event: wx.MouseEvent) -> None:
        factor = 1.1 if event.GetWheelRotation() > 0 else 0.9
        new_zoom = max(0.2, min(8.0, self.zoom * factor))
        self.zoom = new_zoom
        self.Refresh(False)

    def on_pan_start(self, event: wx.MouseEvent) -> None:
        self._panning = True
        self._last_mouse = event.GetPosition()
        self.CaptureMouse()

    def on_pan_end(self, _: wx.MouseEvent) -> None:
        if self._panning and self.HasCapture():
            self.ReleaseMouse()
        self._panning = False

    def on_mouse_move(self, event: wx.MouseEvent) -> None:
        if self._panning and event.Dragging() and event.Moving():
            pos = event.GetPosition()
            dx = (pos.x - self._last_mouse.x) / self.zoom
            dy = (pos.y - self._last_mouse.y) / self.zoom
            self.pan = (self.pan[0] + dx, self.pan[1] + dy)
            self._last_mouse = pos
            self.Refresh(False)

    # Drawing helpers
    def on_paint(self, _: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        self.draw_background(gc)
        self.draw_content(gc)

    def draw_background(self, gc: wx.GraphicsContext) -> None:
        if not self.show_grid:
            return
        size = self.GetClientSize()
        cx, cy = size.width / 2, size.height / 2
        spacing = 16 * self.zoom
        if spacing < 4:
            spacing = 4
        # Grid lines
        pen = wx.Pen(wx.Colour(230, 230, 230))
        gc.SetPen(pen)
        left_world, top_world = self.screen_to_world(wx.Point(0, 0))
        right_world, bottom_world = self.screen_to_world(wx.Point(size.width, size.height))
        start_x = math.floor(left_world / 16) * 16
        start_y = math.floor(top_world / 16) * 16
        x = start_x
        while x <= right_world:
            sx, _ = self.world_to_screen((x, 0))
            gc.StrokeLine(sx, 0, sx, size.height)
            x += 16
        y = start_y
        while y <= bottom_world:
            _, sy = self.world_to_screen((0, y))
            gc.StrokeLine(0, sy, size.width, sy)
            y += 16
        # Axes
        gc.SetPen(wx.Pen(wx.Colour(120, 120, 120), width=2))
        gc.StrokeLine(0, cy + self.pan[1] * self.zoom, size.width, cy + self.pan[1] * self.zoom)
        gc.StrokeLine(cx + self.pan[0] * self.zoom, 0, cx + self.pan[0] * self.zoom, size.height)

    def draw_content(self, gc: wx.GraphicsContext) -> None:
        """Override in subclasses."""


class FrameCanvas(GridCanvasBase):
    """Canvas that can render a Frame and support selection/move of FModules."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.frame: Optional[Frame] = None
        self.selected_fmodule_id: Optional[str] = None
        self.show_collision = True
        self.show_control_points = True
        self.on_selection_changed: Optional[Callable[[Optional[str]], None]] = None
        self._dragging: Optional[Tuple[str, Tuple[float, float]]] = None
        self.frame_offset: Tuple[float, float] = (0.0, 0.0)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_mouse_drag)

    def set_frame(self, frame: Optional[Frame]) -> None:
        self.frame = frame
        self.Refresh(False)

    def set_frame_offset(self, offset: Tuple[float, float]) -> None:
        self.frame_offset = offset
        self.Refresh(False)

    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if not self.frame:
            self._draw_message(gc, "No frame selected")
            return
        for fm in sorted(self.frame.fmodules, key=lambda f: f.z_order):
            self._draw_fmodule(gc, fm)
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

    def _draw_fmodule(self, gc: wx.GraphicsContext, fm: FModule) -> None:
        bounds = self._fmodule_bounds(fm)
        x0, y0, x1, y1 = bounds
        sx0, sy0 = self.world_to_screen((x0, y0))
        sx1, sy1 = self.world_to_screen((x1, y1))
        w, h = sx1 - sx0, sy1 - sy0
        color = _color_from_id(fm.ref_id)
        brush = wx.Brush(wx.Colour(*color, 80))
        gc.SetBrush(brush)
        pen_color = wx.Colour(*color)
        if fm.id == self.selected_fmodule_id:
            pen_color = wx.Colour(20, 120, 240)
        gc.SetPen(wx.Pen(pen_color, width=2))
        gc.DrawRectangle(sx0, sy0, w, h)
        label = f"{fm.ref_type}:{fm.ref_id}"
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(30, 30, 30))
        tw, th = gc.GetTextExtent(label)
        gc.DrawText(label, sx0 + 4, sy0 + 4)

    def _draw_collision(self, gc: wx.GraphicsContext, rect) -> None:
        x0, y0 = rect.x + self.frame_offset[0], rect.y + self.frame_offset[1]
        x1, y1 = x0 + rect.width, y0 + rect.height
        sx0, sy0 = self.world_to_screen((x0, y0))
        sx1, sy1 = self.world_to_screen((x1, y1))
        gc.SetPen(wx.Pen(wx.Colour(200, 60, 60), style=wx.PENSTYLE_LONG_DASH))
        gc.SetBrush(wx.Brush(wx.Colour(200, 60, 60, 40)))
        gc.DrawRectangle(sx0, sy0, sx1 - sx0, sy1 - sy0)
        if rect.name:
            gc.DrawText(rect.name, sx0 + 2, sy0 + 2)

    def _draw_control_point(self, gc: wx.GraphicsContext, cp) -> None:
        sx, sy = self.world_to_screen((cp.x + self.frame_offset[0], cp.y + self.frame_offset[1]))
        gc.SetBrush(wx.Brush(wx.Colour(40, 150, 60)))
        gc.SetPen(wx.Pen(wx.Colour(20, 90, 40)))
        size = 6
        gc.DrawEllipse(sx - size / 2, sy - size / 2, size, size)
        gc.DrawText(cp.name, sx + 6, sy - 6)

    # Interaction
    def on_left_down(self, event: wx.MouseEvent) -> None:
        if not self.frame:
            return
        pos_world = self.screen_to_world(event.GetPosition())
        clicked = self._hit_test(pos_world)
        if clicked:
            self.selected_fmodule_id = clicked.id
            self._dragging = (clicked.id, pos_world)
            self.CaptureMouse()
            if self.on_selection_changed:
                self.on_selection_changed(clicked.id)
        else:
            self.selected_fmodule_id = None
            if self.on_selection_changed:
                self.on_selection_changed(None)
        self.Refresh(False)

    def on_left_up(self, _: wx.MouseEvent) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._dragging = None

    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        if not self.frame or not self._dragging or not event.Dragging():
            return
        fm_id, start_world = self._dragging
        fm = next((f for f in self.frame.fmodules if f.id == fm_id), None)
        if not fm:
            return
        current_world = self.screen_to_world(event.GetPosition())
        dx = current_world[0] - start_world[0]
        dy = current_world[1] - start_world[1]
        fm.position = (int(fm.position[0] + dx), int(fm.position[1] + dy))
        self._dragging = (fm_id, current_world)
        self.Refresh(False)

    # Helpers
    def _hit_test(self, world_pt: Tuple[float, float]) -> Optional[FModule]:
        for fm in reversed(sorted(self.frame.fmodules, key=lambda f: f.z_order)):
            x0, y0, x1, y1 = self._fmodule_bounds(fm)
            if x0 <= world_pt[0] <= x1 and y0 <= world_pt[1] <= y1:
                return fm
        return None

    def _fmodule_bounds(self, fm: FModule) -> Tuple[float, float, float, float]:
        if fm.ref_type == "module":
            mod: Optional[Module] = self.project.get_module(fm.ref_id)
            if mod:
                w, h = mod.rect[2], mod.rect[3]
                top_left = (
                    fm.position[0] + self.frame_offset[0] - mod.pivot[0],
                    fm.position[1] + self.frame_offset[1] - mod.pivot[1],
                )
                return (top_left[0], top_left[1], top_left[0] + w, top_left[1] + h)
        elif fm.ref_type == "frame":
            frame_ref = self.project.get_frame(fm.ref_id)
            if frame_ref and not self.project.frame_has_cycle(frame_ref.id):
                bounds = compute_frame_bounds(self.project, frame_ref, depth=2)
                x0, y0, x1, y1 = bounds
                return (
                    fm.position[0] + self.frame_offset[0] + x0,
                    fm.position[1] + self.frame_offset[1] + y0,
                    fm.position[0] + self.frame_offset[0] + x1,
                    fm.position[1] + self.frame_offset[1] + y1,
                )
        # Fallback size
        sz = 32
        return (
            fm.position[0] - sz / 2,
            fm.position[1] - sz / 2,
            fm.position[0] + sz / 2,
            fm.position[1] + sz / 2,
        )


class AnimationCanvas(FrameCanvas):
    """Canvas that renders the currently selected animation frame and trajectory."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project)
        self.animation: Optional["Animation"] = None
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


def compute_frame_bounds(
    project: Project, frame: Frame, depth: int = 3, visited: Optional[List[str]] = None
) -> Tuple[float, float, float, float]:
    """Estimate bounds for a frame, following nested frames up to depth."""
    visited = visited or []
    if depth < 0 or frame.id in visited:
        return (-16, -16, 16, 16)
    visited.append(frame.id)
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for fm in frame.fmodules:
        if fm.ref_type == "module":
            mod = project.get_module(fm.ref_id)
            if mod:
                x0 = fm.position[0] - mod.pivot[0]
                y0 = fm.position[1] - mod.pivot[1]
                x1 = x0 + mod.rect[2]
                y1 = y0 + mod.rect[3]
            else:
                continue
        else:
            ref = project.get_frame(fm.ref_id)
            if ref:
                bx0, by0, bx1, by1 = compute_frame_bounds(project, ref, depth - 1, visited[:])
                x0 = fm.position[0] + bx0
                y0 = fm.position[1] + by0
                x1 = fm.position[0] + bx1
                y1 = fm.position[1] + by1
            else:
                continue
        min_x = min(min_x, x0)
        min_y = min(min_y, y0)
        max_x = max(max_x, x1)
        max_y = max(max_y, y1)
    if min_x == float("inf"):
        return (-16, -16, 16, 16)
    return (min_x, min_y, max_x, max_y)
