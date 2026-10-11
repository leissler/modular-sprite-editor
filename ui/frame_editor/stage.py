"""Frames stage: the frame canvas plus marquee selection, an origin marker and drop handling."""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import wx

from models import Project
from ui.canvas import FrameCanvas


class FrameStage(FrameCanvas):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project)
        self.zoom = 4.0
        self.max_zoom = 32.0
        self.show_collision = False
        self.show_points = True
        self.empty_hint = ""
        self._marquee: Optional[Tuple[wx.Point, wx.Point]] = None
        self._marquee_base: List[str] = []

        # Callbacks (set by the panel)
        self.on_interaction: Optional[Callable[[], None]] = None  # a click or drag ended: selection / data may differ
        self.on_live: Optional[Callable[[], None]] = None         # while dragging
        self.on_drop: Optional[Callable[[str, str, Tuple[float, float]], None]] = None  # (ref type, id, world point)

    # ------------------------------------------------------------------ drop (library, frame list)
    def handle_dropped_module(self, ref_id: str, pos: wx.Point, ref_type: str = "module") -> None:
        if self.on_drop:
            self.on_drop(ref_type, ref_id, self.screen_to_world(pos))

    # ------------------------------------------------------------------ mouse
    def on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        if self.begin_pan_if_requested(event):
            return
        if self.frame is not None and self.edit_mode == "module":
            if not self.hit_test_all(self.screen_to_world(event.GetPosition())):
                pos = event.GetPosition()
                self._marquee = (pos, pos)
                self._marquee_base = list(self.selected_fmodules) if (event.ShiftDown() or event.CmdDown()) else []
                self.selected_fmodules = list(self._marquee_base)
                if not self.HasCapture():
                    self.CaptureMouse()
                self._notify()
                self.Refresh(False)
                return
        super().on_left_down(event)
        self._notify()

    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        if self._marquee is not None:
            if self.handle_pan_motion(event):
                return
            if event.Dragging() and event.LeftIsDown():
                self._marquee = (self._marquee[0], event.GetPosition())
                rect = self._marquee_rect()
                hits = []
                for fm in self.frame.fmodules if self.frame else []:
                    x0, y0, x1, y1 = self._fmodule_bounds(fm)
                    a = self.world_to_screen(self.local_to_world((x0, y0)))
                    b = self.world_to_screen(self.local_to_world((x1, y1)))
                    box = wx.Rect(wx.Point(int(min(a[0], b[0])), int(min(a[1], b[1]))),
                                  wx.Point(int(max(a[0], b[0])), int(max(a[1], b[1]))))
                    if rect.Intersects(box):
                        hits.append(fm.id)
                selection = self._marquee_base + [i for i in hits if i not in self._marquee_base]
                if selection != self.selected_fmodules:
                    self.selected_fmodules = selection
                    self._notify(live=True)
                self.Refresh(False)
            return
        super().on_mouse_drag(event)
        if event.Dragging() and event.LeftIsDown() and self.on_live:
            self.on_live()

    def on_left_up(self, event: wx.MouseEvent) -> None:
        if self._marquee is not None:
            if self.HasCapture():
                self.ReleaseMouse()
            self._marquee = None
            self.Refresh(False)
            self._notify()
            return
        if self.edit_mode == "collision" and self._col_drag_mode == "create" and self.frame is not None:
            box = next((cr for cr in self.frame.collision_rects if cr.id == self._col_drag_rect_id), None)
            if box is not None and (box.rect[2] <= 0 or box.rect[3] <= 0):
                # A click without a drag: no box (the old editor left an invisible 0×0 one behind).
                self.frame.collision_rects.remove(box)
                self.selected_collision_rects = []
        super().on_left_up(event)
        self._notify()

    def _notify(self, live: bool = False) -> None:
        callback = self.on_live if live else self.on_interaction
        if callback:
            callback()

    def _marquee_rect(self) -> wx.Rect:
        a, b = self._marquee  # type: ignore[misc]
        return wx.Rect(wx.Point(min(a.x, b.x), min(a.y, b.y)), wx.Point(max(a.x, b.x), max(a.y, b.y)))

    # ------------------------------------------------------------------ paint
    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if self.frame is None:
            self._draw_hint(gc, self.empty_hint or "Select a frame, or click + New in the list")
            return
        super().draw_content(gc)
        if not self.show_grid:
            self._draw_origin(gc)
        if not self.frame.fmodules and self.edit_mode == "module":
            self._draw_hint(gc, "Empty frame: drag modules or frames from the library onto the stage")
        if self._marquee is not None:
            rect = self._marquee_rect()
            gc.SetBrush(wx.Brush(wx.Colour(90, 170, 255, 40)))
            gc.SetPen(wx.Pen(wx.Colour(90, 170, 255), 1))
            gc.DrawRectangle(rect.x, rect.y, rect.width, rect.height)

    def _draw_origin(self, gc: wx.GraphicsContext) -> None:
        sx, sy = self.world_to_screen((0, 0))
        gc.SetPen(wx.Pen(wx.Colour(200, 200, 210, 150), 1))
        arm = 10
        gc.StrokeLine(sx - arm, sy, sx + arm, sy)
        gc.StrokeLine(sx, sy - arm, sx, sy + arm)

    def _draw_hint(self, gc: wx.GraphicsContext, text: str) -> None:
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(225, 228, 235))
        tw, th = gc.GetTextExtent(text)
        size = self.GetClientSize()
        x, y = (size.width - tw) / 2, 18
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(20, 21, 24, 210)))
        gc.DrawRoundedRectangle(x - 12, y - 7, tw + 24, th + 14, 6)
        gc.DrawText(text, x, y)
