"""Sequence: the animation's steps as cells on a tick ruler; a cell is as wide as its hold."""

from __future__ import annotations

import colorsys
import zlib
from typing import Callable, Dict, List, Optional, Set, Tuple

import wx

from models import Animation, ModuleMapping, Project
from ui.animation_editor import ops
from ui.animation_editor.render import StepRenderer
from ui.base_canvas import WheelGestureFilter

COL_BG = wx.Colour(34, 35, 38)
COL_RULER = wx.Colour(30, 31, 34)
COL_TEXT = wx.Colour(226, 226, 230)
COL_TEXT_DIM = wx.Colour(140, 142, 150)
COL_TICK = wx.Colour(70, 72, 80)
COL_SECOND = wx.Colour(120, 124, 136)
COL_CELL = wx.Colour(46, 47, 52)
COL_CELL_CURRENT = wx.Colour(56, 74, 104)
COL_BORDER = wx.Colour(80, 82, 90)
COL_SELECTED = wx.Colour(255, 176, 64)
COL_PLAYHEAD = wx.Colour(255, 92, 92)
COL_HOLD = wx.Colour(96, 100, 112)
COL_DROP = wx.Colour(140, 210, 255)
COL_WARN = wx.Colour(255, 110, 90)
COL_LOOP = wx.Colour(120, 210, 140)

LABEL_STEPS = (1, 2, 5, 10, 20, 50, 100, 200, 500)
RULER_H = 22
EVENT_LANE = 12  # coloured event chips between the ruler and the cells
CELL_TOP = RULER_H + EVENT_LANE + 4
THUMB = 64
CELL_H = THUMB + 22
LEFT_PAD = 10
EDGE_GRAB = 5


def frame_colour(frame_id: str) -> wx.Colour:
    """A stable colour per frame, so repeated frames (cycles) are easy to spot."""
    hue = (zlib.crc32(frame_id.encode("utf-8")) % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.85)
    return wx.Colour(int(r * 255), int(g * 255), int(b * 255))


class SequenceWidget(wx.Panel):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.WANTS_CHARS | wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((200, CELL_TOP + CELL_H + 10))
        self.project: Optional[Project] = None
        self.animation: Optional[Animation] = None
        self.mapping: Optional[ModuleMapping] = None
        self.renderer: Optional[StepRenderer] = None
        self.tick = 0
        self.step = -1
        self.selected: Set[int] = set()
        self.tick_w = 72.0
        self.scroll_x = 0.0

        self._mode: Optional[str] = None
        self._press: Optional[wx.Point] = None
        self._press_step = -1
        self._press_was_selected = False
        self._anchor = -1
        self._drop_index = -1
        self._copy_drag = False
        self._hold_base_x = 0
        self._wheel = WheelGestureFilter()

        # Callbacks (set by the panel)
        self.on_seek_tick: Optional[Callable[[int], None]] = None
        self.on_select_steps: Optional[Callable[[Set[int], int], None]] = None  # (selection, current step)
        self.on_hold_drag_begin: Optional[Callable[[int], None]] = None
        self.on_hold_drag: Optional[Callable[[int], None]] = None  # delta ticks since the press
        self.on_hold_drag_end: Optional[Callable[[], None]] = None
        self.on_move_steps: Optional[Callable[[List[int], int, bool], None]] = None  # (indices, insert_at, copy)
        self.on_insert_frame: Optional[Callable[[str, int], None]] = None
        self.on_open_frame: Optional[Callable[[int], None]] = None
        self.on_context_menu: Optional[Callable[[int, wx.Point], None]] = None
        self.on_view_changed: Optional[Callable[[], None]] = None

        self.SetDropTarget(_SequenceDropTarget(self))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self.set_scroll(), e.Skip()))
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_double_click)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda e: self._end_mode())

    # ------------------------------------------------------------------ data / geometry
    def set_data(
        self,
        project: Project,
        animation: Optional[Animation],
        renderer: StepRenderer,
        tick: int,
        step: int,
        selected: Set[int],
    ) -> None:
        self.project = project
        self.mapping = project.active_mapping
        self.renderer = renderer
        if animation is not self.animation:
            self.scroll_x = 0.0
        self.animation = animation
        self.tick = tick
        self.step = step
        self.selected = set(selected)
        self.set_scroll()
        self.Refresh(False)

    def _starts(self) -> List[int]:
        return ops.step_starts(self.animation) if self.animation else []

    def x_of_tick(self, tick: float) -> float:
        return LEFT_PAD + tick * self.tick_w - self.scroll_x

    def tick_at(self, x: float) -> int:
        return int((x + self.scroll_x - LEFT_PAD) // self.tick_w)

    def content_w(self) -> float:
        ticks = ops.total_ticks(self.animation) if self.animation else 0
        return LEFT_PAD * 2 + (ticks + 3) * self.tick_w

    def max_scroll_x(self) -> float:
        return max(0.0, self.content_w() - self.GetClientSize().width)

    def set_scroll(self, x: Optional[float] = None) -> None:
        if x is not None:
            self.scroll_x = float(x)
        self.scroll_x = max(0.0, min(self.scroll_x, self.max_scroll_x()))
        if self.on_view_changed:
            self.on_view_changed()
        self.Refresh(False)

    def cell_rect(self, index: int, starts: Optional[List[int]] = None) -> wx.Rect:
        starts = starts if starts is not None else self._starts()
        af = self.animation.aframes[index]
        x0 = self.x_of_tick(starts[index])
        return wx.Rect(int(x0) + 1, CELL_TOP, max(6, int(ops.hold(af) * self.tick_w) - 2), CELL_H)

    def cell_at(self, pos: wx.Point) -> int:
        if not self.animation or not (CELL_TOP <= pos.y <= CELL_TOP + CELL_H):
            return -1
        starts = self._starts()
        for index in range(len(self.animation.aframes)):
            r = self.cell_rect(index, starts)
            if r.x - 1 <= pos.x <= r.x + r.width + 1:
                return index
        return -1

    def edge_at(self, pos: wx.Point) -> int:
        """Step whose right edge (hold handle) is under the pointer."""
        if not self.animation or not (CELL_TOP <= pos.y <= CELL_TOP + CELL_H):
            return -1
        starts = self._starts()
        for index in range(len(self.animation.aframes)):
            r = self.cell_rect(index, starts)
            if abs(pos.x - (r.x + r.width)) <= EDGE_GRAB:
                return index
        return -1

    def insertion_at(self, x: float) -> int:
        """Index a drop at x inserts before (between cells, by their middles)."""
        if not self.animation:
            return 0
        starts = self._starts()
        for index, af in enumerate(self.animation.aframes):
            middle = self.x_of_tick(starts[index] + ops.hold(af) / 2.0)
            if x < middle:
                return index
        return len(self.animation.aframes)

    def ensure_tick_visible(self, tick: int) -> None:
        width = self.GetClientSize().width
        x = self.x_of_tick(tick)
        if x < LEFT_PAD:
            self.set_scroll(self.scroll_x + x - LEFT_PAD)
        elif x + self.tick_w > width - LEFT_PAD:
            self.set_scroll(self.scroll_x + (x + self.tick_w) - (width - LEFT_PAD))

    def fit(self) -> None:
        if not self.animation or not self.animation.aframes:
            return
        width = max(100, self.GetClientSize().width - 2 * LEFT_PAD)
        self.tick_w = max(12.0, min(96.0, width / float(ops.total_ticks(self.animation) + 1)))
        self.set_scroll(0)

    def zoom_at(self, factor: float, x: float) -> None:
        tick = (x + self.scroll_x - LEFT_PAD) / self.tick_w
        self.tick_w = max(12.0, min(160.0, self.tick_w * factor))
        self.set_scroll(LEFT_PAD + tick * self.tick_w - x)

    # ------------------------------------------------------------------ paint
    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        dc.SetBackground(wx.Brush(COL_BG))
        dc.Clear()
        font = self.GetFont()
        small = wx.Font(font)
        small.SetPointSize(max(7, font.GetPointSize() - 3))
        dc.SetFont(small)
        anim = self.animation
        if not anim:
            dc.SetTextForeground(COL_TEXT_DIM)
            dc.DrawText("No animation selected", LEFT_PAD, CELL_TOP + 8)
            return
        self._paint_ruler(dc, w, anim)
        if not anim.aframes:
            dc.SetTextForeground(COL_TEXT_DIM)
            dc.DrawText("Drag frames here from the library, or double-click a frame there.", LEFT_PAD + 4, CELL_TOP + CELL_H // 2 - 6)
        starts = self._starts()
        for index, af in enumerate(anim.aframes):
            r = self.cell_rect(index, starts)
            if r.x > w or r.x + r.width < 0:
                continue
            self._paint_cell(dc, index, af, r)
        self._paint_loop_and_follow_up(dc, anim, starts, w)
        # Playhead through the middle of the tick being shown
        if anim.aframes:
            px = int(self.x_of_tick(self.tick + 0.5))
            dc.SetPen(wx.Pen(COL_PLAYHEAD, 1))
            dc.DrawLine(px, RULER_H - 6, px, CELL_TOP + CELL_H + 4)
        if self._drop_index >= 0:
            if self._drop_index < len(anim.aframes):
                x = int(self.x_of_tick(starts[self._drop_index]))
            else:
                x = int(self.x_of_tick(ops.total_ticks(anim)))
            dc.SetPen(wx.Pen(COL_DROP, 3))
            dc.DrawLine(x, CELL_TOP - 4, x, CELL_TOP + CELL_H + 4)

    def _paint_ruler(self, dc: wx.DC, w: int, anim: Animation) -> None:
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(COL_RULER))
        dc.DrawRectangle(0, 0, w, RULER_H)
        total = ops.total_ticks(anim)
        rate = ops.tick_rate(anim)
        label_every = next((s for s in LABEL_STEPS if s * self.tick_w >= 26), LABEL_STEPS[-1])
        first = max(0, self.tick_at(0))
        last = min(total + 2, self.tick_at(w) + 1)
        for tick in range(first, last + 1):
            x = int(self.x_of_tick(tick))
            second = tick % rate == 0
            dc.SetPen(wx.Pen(COL_SECOND if second else COL_TICK, 1))
            dc.DrawLine(x, RULER_H - (10 if second else 5), x, RULER_H)
            if tick % label_every == 0 or second:
                label = f"{tick}" + (f"  {tick // rate}s" if second and tick else "")
                dc.SetTextForeground(COL_TEXT if second else COL_TEXT_DIM)
                dc.DrawText(label, x + 3, 3)
        if total:
            end_x = int(self.x_of_tick(total))
            dc.SetPen(wx.Pen(COL_SECOND, 1, wx.PENSTYLE_SHORT_DASH))
            dc.DrawLine(end_x, 0, end_x, CELL_TOP + CELL_H + 4)
        if anim.aframes:
            px = int(self.x_of_tick(self.tick + 0.5))
            label = str(self.tick)
            tw, th = dc.GetTextExtent(label)
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(COL_PLAYHEAD))
            dc.DrawRoundedRectangle(px - tw // 2 - 4, RULER_H - th - 4, tw + 8, th + 2, 3)
            dc.SetTextForeground(wx.WHITE)
            dc.DrawText(label, px - tw // 2, RULER_H - th - 3)

    def _paint_cell(self, dc: wx.DC, index: int, af, r: wx.Rect) -> None:
        current = index == self.step
        chosen = index in self.selected
        dc.SetPen(wx.Pen(COL_SELECTED if chosen else COL_BORDER, 2 if chosen else 1))
        dc.SetBrush(wx.Brush(COL_CELL_CURRENT if current else COL_CELL))
        dc.DrawRectangle(r)
        # Same size for every cell (longer holds do not get bigger pictures), shared scale per animation.
        side = max(8, min(THUMB, int(self.tick_w) - 8, r.width - 6))
        if self.renderer and self.project and self.animation:
            bmp = self.renderer.strip_thumbnail(self.project, self.animation, index, self.mapping, side)
            dc.DrawBitmap(bmp, r.x + 3, r.y + 3)
        # Hold band: the rest of a long cell shows that the drawing holds.
        band_x = r.x + side + 6
        if af.duration_frames > 1 and r.width - side > 18:
            band_w = r.x + r.width - 4 - band_x
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(COL_HOLD))
            dc.DrawRectangle(band_x, r.y + 3 + side // 2 - 2, band_w, 4)
            label = f"hold {ops.hold(af)}"
            tw, th = dc.GetTextExtent(label)
            if tw < band_w - 4:
                dc.SetTextForeground(COL_TEXT_DIM)
                dc.DrawText(label, band_x + (band_w - tw) // 2, r.y + 3 + side // 2 - th - 4)
        # Bottom line: step number, frame name, hold
        frame = self.project.get_frame(af.frame_id) if self.project else None
        name = (frame.name.strip() if frame else "missing frame") or af.frame_id
        y = r.y + r.height - 17
        dc.SetTextForeground(COL_TEXT)
        number = str(index + 1)
        dc.DrawText(number, r.x + 3, y)
        nw = dc.GetTextExtent(number)[0]
        # Only holds other than one tick get a number, so they stand out (0 is flagged: it plays as 1).
        hold_label = f"×{af.duration_frames}" if af.duration_frames != 1 else ""
        hw = dc.GetTextExtent(hold_label)[0] if hold_label else 0
        room = r.width - nw - hw - 14
        if room > 16:
            dc.SetTextForeground(COL_TEXT_DIM if frame else COL_WARN)
            dc.DrawText(_fit_text(dc, name, room), r.x + nw + 7, y)
        if hold_label and r.width > nw + hw + 8:
            dc.SetTextForeground(COL_WARN if af.duration_frames < 1 else COL_SELECTED)
            dc.DrawText(hold_label, r.x + r.width - hw - 4, y)
        # Transform badges (flip / rotation) on the thumbnail
        badges = []
        if af.flip_x:
            badges.append("H")
        if af.flip_y:
            badges.append("V")
        rot = int(round(af.rotation_degrees)) % 360
        if rot:
            badges.append(f"{rot}°")
        bx = r.x + 3 + side
        for badge in reversed(badges):
            tw, th = dc.GetTextExtent(badge)
            bx -= tw + 5
            if bx < r.x + 3:
                break
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(wx.Colour(20, 20, 24)))
            dc.DrawRectangle(bx, r.y + 4, tw + 4, th)
            dc.SetTextForeground(COL_SELECTED)
            dc.DrawText(badge, bx + 2, r.y + 4)
        self._paint_events(dc, af, r)
        # Frame identity stripe: same colour = same frame.
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(frame_colour(af.frame_id)))
        dc.DrawRectangle(r.x + 2, r.y + r.height - 3, r.width - 4, 2)

    def _paint_events(self, dc: wx.DC, af, r: wx.Rect) -> None:
        """Event chips in the lane above the cell: one per event, labelled while there is room."""
        if not af.events or not self.project:
            return
        x = r.x + 1
        right = r.x + r.width
        y = CELL_TOP - EVENT_LANE - 2
        for event in af.events:
            etype = self.project.get_event_type(event.type_id)
            colour = wx.Colour(*(etype.color if etype else (150, 150, 150)))
            label = (etype.name if etype else "?") + (f"={event.value}" if event.value else "")
            tw, th = dc.GetTextExtent(label)
            width = tw + 8 if x + tw + 8 <= right else 8
            if x + width > right:
                break
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(colour))
            dc.DrawRoundedRectangle(x, y, width, EVENT_LANE, 3)
            if width > 8:
                dc.SetTextForeground(wx.Colour(20, 20, 24))
                dc.DrawText(label, x + 4, y + (EVENT_LANE - th) // 2)
            x += width + 2

    def _paint_loop_and_follow_up(self, dc: wx.DC, anim: Animation, starts: List[int], width: int) -> None:
        loop_from = ops.loop_start(anim)
        if loop_from > 0 and anim.aframes:
            # The intro before the loop point plays once: shade it, mark where later passes start.
            x = int(self.x_of_tick(starts[loop_from]))
            intro_x = int(self.x_of_tick(0))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 90)))
            dc.DrawRectangle(intro_x, CELL_TOP, max(0, x - intro_x), CELL_H)
            dc.SetPen(wx.Pen(COL_LOOP, 2))
            dc.DrawLine(x, RULER_H - 8, x, CELL_TOP + CELL_H + 4)
            dc.SetTextForeground(COL_LOOP)
            dc.DrawText("↺ loop", x + 4, RULER_H - 2 - dc.GetTextExtent("↺ loop")[1] // 2 + 6)
        follow = self.project.get_animation(anim.next_animation_id) if self.project and anim.next_animation_id else None
        if follow is not None and anim.aframes:
            end_x = int(self.x_of_tick(ops.total_ticks(anim))) + 8
            label = f"then → {follow.name}"
            dc.SetTextForeground(COL_LOOP if ops.can_finish(anim) else COL_TEXT_DIM)
            dc.DrawText(label, end_x, CELL_TOP + CELL_H // 2 - dc.GetTextExtent(label)[1] // 2)

    # ------------------------------------------------------------------ mouse
    def _capture(self) -> None:
        if not self.HasCapture():
            self.CaptureMouse()

    def _release(self) -> None:
        if self.HasCapture():
            self.ReleaseMouse()

    def _end_mode(self) -> None:
        self._mode = None
        self._drop_index = -1
        self.Refresh(False)

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        pos = event.GetPosition()
        self._press = pos
        anim = self.animation
        if not anim:
            return
        if pos.y < RULER_H:
            self._mode = "scrub"
            self._capture()
            self._seek_x(pos.x)
            return
        edge = self.edge_at(pos)
        if edge >= 0:
            if edge not in self.selected and self.on_select_steps:
                self.on_select_steps({edge}, edge)
            self._mode = "hold"
            self._hold_base_x = pos.x
            self._capture()
            if self.on_hold_drag_begin:
                self.on_hold_drag_begin(edge)
            return
        index = self.cell_at(pos)
        if index < 0:
            # Empty space: drop the selection, move the playhead there.
            if self.on_select_steps:
                self.on_select_steps(set(), -1)
            self._seek_x(pos.x)
            return
        self._press_step = index
        self._press_was_selected = index in self.selected
        if event.ShiftDown() and self._anchor >= 0:
            lo, hi = sorted((self._anchor, index))
            selection = set(range(lo, hi + 1))
        elif event.CmdDown():
            selection = set(self.selected)
            selection.symmetric_difference_update({index})
            self._anchor = index
        elif self._press_was_selected:
            selection = set(self.selected)  # keep a multi-selection for dragging
        else:
            selection = {index}
            self._anchor = index
        if self.on_select_steps:
            self.on_select_steps(selection, index)
        self._mode = "cells-pending"
        self._capture()

    def _seek_x(self, x: int) -> None:
        if not self.animation or not self.animation.aframes or not self.on_seek_tick:
            return
        total = ops.total_ticks(self.animation)
        self.on_seek_tick(max(0, min(self.tick_at(x), total - 1)))

    def _on_motion(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        if not event.Dragging():
            self.SetCursor(wx.Cursor(wx.CURSOR_SIZEWE) if self.edge_at(pos) >= 0 else wx.NullCursor)
            return
        if self._mode == "scrub":
            self._seek_x(pos.x)
            return
        if self._mode == "hold" and self._press is not None:
            delta = int(round((pos.x - self._hold_base_x) / self.tick_w))
            if self.on_hold_drag:
                self.on_hold_drag(delta)
            return
        moved = self._press is not None and abs(pos.x - self._press.x) + abs(pos.y - self._press.y) > 4
        if self._mode == "cells-pending" and moved:
            self._mode = "cells"
        if self._mode == "cells":
            self._copy_drag = event.AltDown()
            self._drop_index = self.insertion_at(pos.x)
            self.SetCursor(wx.Cursor(wx.CURSOR_COPY_ARROW if self._copy_drag else wx.CURSOR_HAND))
            width = self.GetClientSize().width
            if pos.x > width - 20:
                self.set_scroll(self.scroll_x + self.tick_w / 2)
            elif pos.x < 20:
                self.set_scroll(self.scroll_x - self.tick_w / 2)
            self.Refresh(False)

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        mode = self._mode
        self._release()
        self.SetCursor(wx.NullCursor)
        if mode == "hold" and self.on_hold_drag_end:
            self.on_hold_drag_end()
        elif mode == "cells" and self._drop_index >= 0 and self.on_move_steps:
            self.on_move_steps(sorted(self.selected), self._drop_index, self._copy_drag or event.AltDown())
        elif mode == "cells-pending" and self._press_was_selected and not (event.ShiftDown() or event.CmdDown()):
            # A plain click on an already selected step narrows the selection to it.
            if self.on_select_steps:
                self.on_select_steps({self._press_step}, self._press_step)
            self._anchor = self._press_step
        self._mode = None
        self._drop_index = -1
        self.Refresh(False)

    def _on_double_click(self, event: wx.MouseEvent) -> None:
        index = self.cell_at(event.GetPosition())
        if index >= 0 and self.on_open_frame:
            self.on_open_frame(index)

    def _on_right_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        pos = event.GetPosition()
        index = self.cell_at(pos)
        if index >= 0 and index not in self.selected and self.on_select_steps:
            self.on_select_steps({index}, index)
            self._anchor = index
        if self.on_context_menu:
            self.on_context_menu(index, pos)

    def _on_wheel(self, event: wx.MouseEvent) -> None:
        rotation = event.GetWheelRotation()
        if rotation == 0:
            return
        horizontal = event.GetWheelAxis() == wx.MOUSE_WHEEL_HORIZONTAL
        if not self._wheel.accept(horizontal, rotation, wheel_delta=event.GetWheelDelta()):
            return
        notches = rotation / float(max(1, event.GetWheelDelta()))
        if horizontal or event.ShiftDown():
            self.set_scroll(self.scroll_x + notches * max(48.0, self.tick_w))
        else:
            self.zoom_at(1.1 ** notches, event.GetPosition().x)

    # ------------------------------------------------------------------ drops from the library
    def drag_over(self, x: int) -> None:
        self._drop_index = self.insertion_at(x) if self.animation is not None else -1
        self.Refresh(False)

    def drop_frame(self, x: int, frame_id: str) -> None:
        index = self.insertion_at(x)
        self._drop_index = -1
        self.Refresh(False)
        if self.animation is not None and self.on_insert_frame:
            self.on_insert_frame(frame_id, index)


def _fit_text(dc: wx.DC, text: str, width: int) -> str:
    if dc.GetTextExtent(text)[0] <= width:
        return text
    while text and dc.GetTextExtent(text + "…")[0] > width:
        text = text[:-1]
    return text + "…" if text else ""


class _SequenceDropTarget(wx.TextDropTarget):
    def __init__(self, widget: SequenceWidget):
        super().__init__()
        self.widget = widget

    def OnDragOver(self, x: int, y: int, default: int) -> int:
        self.widget.drag_over(x)
        return wx.DragCopy

    def OnLeave(self) -> None:
        self.widget._drop_index = -1
        self.widget.Refresh(False)

    def OnDropText(self, x: int, y: int, data: str) -> bool:
        prefix, _, rest = data.partition(":")
        if prefix.strip().upper() not in ("FRAME", "FRAME_REF") or not rest:
            self.OnLeave()
            return False
        self.widget.drop_frame(x, rest.split(":")[-1].strip())
        return True


class SequenceView(wx.Panel):
    """SequenceWidget plus a horizontal scrollbar kept in sync with it."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        self.widget = SequenceWidget(self)
        self.hbar = wx.ScrollBar(self, style=wx.SB_HORIZONTAL)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.widget, 1, wx.EXPAND)
        sizer.Add(self.hbar, 0, wx.EXPAND)
        self.SetSizer(sizer)
        self._syncing = False
        self.widget.on_view_changed = self.sync_scrollbar
        for evt in (wx.EVT_SCROLL_THUMBTRACK, wx.EVT_SCROLL_CHANGED, wx.EVT_SCROLL_LINEUP,
                    wx.EVT_SCROLL_LINEDOWN, wx.EVT_SCROLL_PAGEUP, wx.EVT_SCROLL_PAGEDOWN):
            self.hbar.Bind(evt, self._on_hbar)

    def sync_scrollbar(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            w = self.widget
            page = max(1, w.GetClientSize().width)
            self.hbar.SetScrollbar(int(w.scroll_x), page, int(max(page, w.content_w())), max(1, page // 2), True)
            self.hbar.Enable(w.max_scroll_x() > 0)
        finally:
            self._syncing = False

    def _on_hbar(self, event: wx.ScrollEvent) -> None:
        if not self._syncing:
            self.widget.set_scroll(float(event.GetPosition()))
        event.Skip()
