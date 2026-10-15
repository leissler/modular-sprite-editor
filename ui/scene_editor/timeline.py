"""Timeline: layer tree on the left, frame-based dopesheet on the right, in one widget."""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Set, Tuple

import wx

from models import TimelineObject, TimelineScene
from ui.base_canvas import SCROLL, WheelGestureFilter
from ui.scene_editor import ops
from ui.dpi import px, pxf
from ui.theme import T

Selection = Dict[str, Set[str]]  # object id -> selected key ids


TYPE_COLOURS = {
    "module": wx.Colour(96, 156, 230),
    "frame": wx.Colour(96, 196, 120),
    "animation": wx.Colour(236, 160, 64),
    "none": wx.Colour(150, 150, 160),
}

LABEL_STEPS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)


def _fit_text(dc: wx.DC, text: str, width: float) -> str:
    """``text``, shortened with "…" until it fits ``width`` pixels ("" when not even that fits)."""
    while text and dc.GetTextExtent(text)[0] > width:
        text = text[:-2] + "…" if len(text) > 2 else ""
    return text


class TimelineWidget(wx.Panel):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.WANTS_CHARS | wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((px(200), px(120)))

        # Data (set by the panel)
        self.scene: Optional[TimelineScene] = None
        self.rows: List[Tuple[TimelineObject, int, bool]] = []
        self.frame = 0
        self.selected_object_id: Optional[str] = None
        self.selected_object_ids: Set[str] = set()  # every selected layer
        self.selection: Selection = {}
        self.hidden_ids: Set[str] = set()
        self.locked_ids: Set[str] = set()
        self.collapsed_ids: Set[str] = set()
        self.anim_ticks: Dict[str, List[int]] = {}
        self.source_labels: Dict[str, str] = {}  # key id -> source name (swap keys)

        # Geometry
        self.left_w = px(240)
        self.header_h = px(28)
        self.row_h = px(26)
        self.frame_w = pxf(12.0)
        self.min_frame_w = pxf(2.0)
        self.max_frame_w = pxf(80.0)
        self.scroll_x = 0.0
        self.scroll_y = 0.0

        # Callbacks
        self.on_seek: Optional[Callable[[int], None]] = None
        self.on_select_object: Optional[Callable[[Optional[str]], None]] = None
        self.on_select_objects: Optional[Callable[[List[str], Optional[str]], None]] = None  # (ids, the one shown)
        self.on_select_keys: Optional[Callable[[Selection, bool], None]] = None
        self.on_move_keys: Optional[Callable[[int, Dict[Tuple[str, str], int]], int]] = None
        self.on_move_keys_end: Optional[Callable[[], None]] = None
        self.on_add_key: Optional[Callable[[str, int], None]] = None
        self.on_toggle_collapse: Optional[Callable[[str], None]] = None
        self.on_toggle_hidden: Optional[Callable[[str], None]] = None
        self.on_toggle_locked: Optional[Callable[[str], None]] = None
        self.on_rename: Optional[Callable[[str, str], None]] = None
        self.on_move_layer: Optional[Callable[[str, Optional[str], Optional[str]], None]] = None
        self.on_context_menu: Optional[Callable[[str, Optional[str], Optional[str], int, wx.Point], None]] = None
        self.on_view_changed: Optional[Callable[[], None]] = None

        # Interaction state
        self._mode: Optional[str] = None  # scrub | keys | marquee | layer | divider | pan
        self._press_pos: Optional[wx.Point] = None
        self._press_object: Optional[str] = None
        self._press_frame = 0
        self._key_origins: Dict[Tuple[str, str], int] = {}
        self._keys_moved = False
        self._stack_cycle: Optional[Tuple[str, str]] = None  # (object id, next key id) on a plain re-click
        self._marquee_base: Selection = {}
        self._marquee_rect: Optional[wx.Rect] = None
        self._drop_target: Optional[Tuple[str, Optional[str], Optional[str], int]] = None
        self._pan_start: Optional[Tuple[wx.Point, float, float]] = None
        self._rename_ctrl: Optional[wx.TextCtrl] = None
        self._wheel_filter = WheelGestureFilter()
        self._tip = ""  # the tooltip set now (a mark of a layer's animation poses explains itself)

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_left_dclick)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MIDDLE_DOWN, self._on_middle_down)
        self.Bind(wx.EVT_MIDDLE_UP, self._on_left_up)
        self.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)

    # ------------------------------------------------------------------ data
    def set_data(
        self,
        scene: Optional[TimelineScene],
        rows: List[Tuple[TimelineObject, int, bool]],
        frame: int,
        selected_object_id: Optional[str],
        selection: Selection,
        hidden_ids: Set[str],
        locked_ids: Set[str],
        collapsed_ids: Set[str],
        anim_ticks: Dict[str, List[int]],
        source_labels: Dict[str, str],
        selected_object_ids: Optional[Set[str]] = None,
    ) -> None:
        self.scene = scene
        self.rows = rows
        self.frame = frame
        self.selected_object_id = selected_object_id
        self.selected_object_ids = set(selected_object_ids or ()) | ({selected_object_id} if selected_object_id else set())
        self.selection = {k: set(v) for k, v in selection.items()}
        self.hidden_ids = set(hidden_ids)
        self.locked_ids = set(locked_ids)
        self.collapsed_ids = set(collapsed_ids)
        self.anim_ticks = anim_ticks
        self.source_labels = source_labels
        self._clamp_scroll()
        self.Refresh(False)

    # ------------------------------------------------------------------ geometry
    def length(self) -> int:
        return ops.scene_length_frames(self.scene) if self.scene else 0

    def track_w(self) -> int:
        return max(1, self.GetClientSize().width - self.left_w)

    def rows_h(self) -> int:
        return max(1, self.GetClientSize().height - self.header_h)

    def content_w(self) -> float:
        return (self.length() + 1) * self.frame_w + pxf(60.0)

    def content_h(self) -> float:
        return len(self.rows) * self.row_h + 8.0

    def max_scroll_x(self) -> float:
        return max(0.0, self.content_w() - self.track_w())

    def max_scroll_y(self) -> float:
        return max(0.0, self.content_h() - self.rows_h())

    def _clamp_scroll(self) -> None:
        self.scroll_x = max(0.0, min(self.scroll_x, self.max_scroll_x()))
        self.scroll_y = max(0.0, min(self.scroll_y, self.max_scroll_y()))

    def set_scroll(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        if x is not None:
            self.scroll_x = float(x)
        if y is not None:
            self.scroll_y = float(y)
        self._clamp_scroll()
        self.Refresh(False)
        if self.on_view_changed:
            self.on_view_changed()

    def frame_x(self, frame: float) -> float:
        """Left edge of a frame cell in client coordinates."""
        return self.left_w + frame * self.frame_w - self.scroll_x

    def frame_center_x(self, frame: int) -> float:
        return self.frame_x(frame) + self.frame_w / 2.0

    def frame_at(self, x: float) -> int:
        frame = int(math.floor((x - self.left_w + self.scroll_x) / self.frame_w))
        return max(0, min(self.length(), frame))

    def row_y(self, row: int) -> float:
        return self.header_h + row * self.row_h - self.scroll_y

    def row_at(self, y: float) -> int:
        if y < self.header_h:
            return -1
        return int((y - self.header_h + self.scroll_y) // self.row_h)

    def set_frame_width(self, width: float, anchor_x: Optional[float] = None) -> None:
        width = max(self.min_frame_w, min(self.max_frame_w, float(width)))
        if anchor_x is None:
            anchor_x = self.left_w + self.track_w() / 2.0
        anchor_frame = (anchor_x - self.left_w + self.scroll_x) / self.frame_w
        self.frame_w = width
        self.scroll_x = anchor_frame * width - (anchor_x - self.left_w)
        self.set_scroll()

    def fit_scene(self) -> None:
        if not self.scene:
            return
        self.frame_w = max(self.min_frame_w, min(self.max_frame_w, (self.track_w() - px(24)) / float(self.length() + 1)))
        self.set_scroll(x=0.0)

    def ensure_frame_visible(self, frame: int) -> None:
        x = self.frame_x(frame)
        if x < self.left_w + 8:
            self.set_scroll(x=self.scroll_x - (self.left_w + 8 - x))
        elif x + self.frame_w > self.left_w + self.track_w() - 8:
            self.set_scroll(x=self.scroll_x + (x + self.frame_w - (self.left_w + self.track_w() - 8)))

    def ensure_row_visible(self, object_id: str) -> None:
        index = next((i for i, row in enumerate(self.rows) if row[0].id == object_id), -1)
        if index < 0:
            return
        top = index * self.row_h
        if top < self.scroll_y:
            self.set_scroll(y=top)
        elif top + self.row_h > self.scroll_y + self.rows_h():
            self.set_scroll(y=top + self.row_h - self.rows_h())

    # ------------------------------------------------------------------ layer column layout
    def _layer_parts(self, row: int, depth: int) -> Dict[str, wx.Rect]:
        y = int(self.row_y(row))
        h = self.row_h
        mid = y + h // 2
        x = px(6) + depth * px(14)
        parts = {
            "disclosure": wx.Rect(x, mid - px(6), px(12), px(12)),
            "eye": wx.Rect(self.left_w - px(46), mid - px(8), px(18), px(16)),
            "lock": wx.Rect(self.left_w - px(24), mid - px(8), px(18), px(16)),
        }
        parts["glyph"] = wx.Rect(x + px(16), mid - px(5), px(10), px(10))
        parts["name"] = wx.Rect(x + px(32), y, max(px(10), self.left_w - px(52) - (x + px(32))), h)
        return parts

    # ------------------------------------------------------------------ hit testing
    def _key_at(self, pos: wx.Point) -> Optional[Tuple[str, str, int]]:
        row = self.row_at(pos.y)
        if not (0 <= row < len(self.rows)) or pos.x < self.left_w or not self.scene:
            return None
        obj = self.rows[row][0]
        fps = self.scene.fps
        best_frame, best_d = None, max(pxf(6.0), min(pxf(10.0), self.frame_w / 2.0 + pxf(2.0)))
        for frame in ops.key_frames(obj, fps):
            d = abs(self.frame_center_x(frame) - pos.x)
            if d <= best_d:
                best_frame, best_d = frame, d
        if best_frame is None:
            return None
        key = ops.key_at_frame(obj, best_frame, fps, self.selection.get(obj.id))
        return (obj.id, key.id, best_frame) if key else None

    def _segment_at(self, pos: wx.Point) -> Optional[Tuple[str, str]]:
        row = self.row_at(pos.y)
        if not (0 <= row < len(self.rows)) or not self.scene:
            return None
        obj = self.rows[row][0]
        keys = obj.sorted_keyframes()
        fps = self.scene.fps
        for a, b in zip(keys, keys[1:]):
            x0 = self.frame_center_x(ops.frame_of(a.time, fps))
            x1 = self.frame_center_x(ops.frame_of(b.time, fps))
            if x0 < pos.x < x1:
                return (obj.id, a.id)
        return None

    def _keys_in_rect(self, rect: wx.Rect) -> Selection:
        found: Selection = {}
        if not self.scene:
            return found
        for row, (obj, _depth, _kids) in enumerate(self.rows):
            cy = self.row_y(row) + self.row_h / 2.0
            if not (rect.y <= cy <= rect.y + rect.height):
                continue
            for key in obj.keyframes:
                cx = self.frame_center_x(ops.frame_of(key.time, self.scene.fps))
                if rect.x <= cx <= rect.x + rect.width:
                    found.setdefault(obj.id, set()).add(key.id)
        return found

    def _drop_target_at(self, pos: wx.Point, dragged_id: str) -> Optional[Tuple[str, Optional[str], Optional[str], int]]:
        """(mode, parent_id, before_id, indicator_row) where mode is 'into' or 'between'."""
        if not self.scene:
            return None
        row = self.row_at(pos.y)
        if row >= len(self.rows) or row < 0:
            return ("between", None, None, len(self.rows))
        obj, _depth, _kids = self.rows[row]
        top = self.row_y(row)
        frac = (pos.y - top) / float(self.row_h)
        if obj.id == dragged_id or ops.is_descendant(self.scene, dragged_id, obj.id):
            return None
        parent = self.scene.get_object(obj.parent_id) if obj.parent_id else None
        parent_id = parent.id if parent else None
        if frac < 0.28:
            return ("between", parent_id, obj.id, row)
        if frac > 0.72 and obj.id in self.collapsed_ids or frac > 0.72 and not self.rows[row][2]:
            siblings = ops.children_of(self.scene, parent_id)
            idx = siblings.index(obj)
            before = siblings[idx + 1].id if idx + 1 < len(siblings) else None
            if before == dragged_id:
                before = siblings[idx + 2].id if idx + 2 < len(siblings) else None
            return ("between", parent_id, before, row + 1)
        return ("into", obj.id, None, row)

    # ------------------------------------------------------------------ mouse
    def _capture(self) -> None:
        if not self.HasCapture():
            self.CaptureMouse()

    def _release(self) -> None:
        if self.HasCapture():
            self.ReleaseMouse()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        self._finish_rename(commit=True)
        pos = event.GetPosition()
        self._press_pos = pos
        self._keys_moved = False
        if wx.GetKeyState(wx.WXK_SPACE):
            self._start_pan(pos)
            return
        if abs(pos.x - self.left_w) <= px(3):
            self._mode = "divider"
            self._capture()
            return
        if not self.scene:
            return
        if pos.y < self.header_h:
            if pos.x > self.left_w:
                self._mode = "scrub"
                self._capture()
                if self.on_seek:
                    self.on_seek(self.frame_at(pos.x))
            return
        row = self.row_at(pos.y)
        in_rows = 0 <= row < len(self.rows)
        if pos.x < self.left_w:
            if not in_rows:
                if self.on_select_object:
                    self.on_select_object(None)
                return
            obj, depth, has_kids = self.rows[row]
            parts = self._layer_parts(row, depth)
            if has_kids and parts["disclosure"].Contains(pos):
                if self.on_toggle_collapse:
                    self.on_toggle_collapse(obj.id)
                return
            if parts["eye"].Contains(pos):
                if self.on_toggle_hidden:
                    self.on_toggle_hidden(obj.id)
                return
            if parts["lock"].Contains(pos):
                if self.on_toggle_locked:
                    self.on_toggle_locked(obj.id)
                return
            if (event.ShiftDown() or event.CmdDown()) and self.on_select_objects:
                self.on_select_objects(*self._extend_selection(obj.id, event.ShiftDown()))
                return
            if self.on_select_object:
                self.on_select_object(obj.id)
            self._mode = "layer-pending"
            self._press_object = obj.id
            self._capture()
            return

        key = self._key_at(pos)
        if key:
            obj_id, key_id, frame = key
            additive = event.ShiftDown() or event.CmdDown()
            selected = key_id in self.selection.get(obj_id, set())
            self._stack_cycle = None
            stack_obj = self.scene.get_object(obj_id)
            stack = [k.id for k in ops.keys_at_frame(stack_obj, frame, self.scene.fps)] if stack_obj else []
            if selected and not additive and len(stack) > 1:
                self._stack_cycle = (obj_id, stack[(stack.index(key_id) + 1) % len(stack)])
            if additive:  # Shift adds the key, Cmd adds or removes it
                new_sel = {k: set(v) for k, v in self.selection.items()}
                if selected and event.CmdDown():
                    new_sel[obj_id].discard(key_id)
                else:
                    new_sel.setdefault(obj_id, set()).add(key_id)
                if self.on_select_keys:
                    self.on_select_keys(new_sel, False)
            else:
                if not selected and self.on_select_keys:
                    self.on_select_keys({obj_id: {key_id}}, False)
                if self.on_select_object:
                    self.on_select_object(obj_id)
                if self.on_seek:
                    self.on_seek(frame)
            self._key_origins = {}
            for sel_obj, key_ids in self.selection.items():
                obj = self.scene.get_object(sel_obj)
                if obj:
                    for k in obj.keyframes:
                        if k.id in key_ids:
                            self._key_origins[(sel_obj, k.id)] = ops.frame_of(k.time, self.scene.fps)
            self._press_frame = self.frame_at(pos.x)
            self._mode = "keys-pending"
            self._capture()
            return

        self._mode = "marquee-pending"
        self._press_object = self.rows[row][0].id if in_rows else None
        self._press_frame = self.frame_at(pos.x)
        additive = event.ShiftDown() or event.CmdDown()
        self._marquee_base = {k: set(v) for k, v in self.selection.items()} if additive else {}
        self._capture()

    def _extend_selection(self, object_id: str, extend_range: bool) -> Tuple[List[str], Optional[str]]:
        """Shift+click: the rows from the shown layer to this one. Cmd+click: this one in or out of the selection."""
        order = [obj.id for obj, _depth, _kids in self.rows]
        chosen = [i for i in order if i in self.selected_object_ids]
        if extend_range and self.selected_object_id in order:
            a, b = sorted((order.index(self.selected_object_id), order.index(object_id)))
            chosen = list(dict.fromkeys(chosen + order[a:b + 1]))
            return chosen, object_id
        if object_id in chosen:
            chosen.remove(object_id)
            primary = self.selected_object_id if self.selected_object_id in chosen else (chosen[-1] if chosen else None)
            return chosen, primary
        return chosen + [object_id], object_id

    def _on_motion(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        if self._mode == "pan" and self._pan_start:
            start, sx, sy = self._pan_start
            self.set_scroll(x=sx - (pos.x - start.x), y=sy - (pos.y - start.y))
            return
        if not event.Dragging():
            self._update_cursor(pos)
            self._update_tip(pos)
            return
        if self._mode == "divider":
            self.left_w = max(px(140), min(pos.x, self.GetClientSize().width - px(160)))
            self.set_scroll()
            return
        if self._mode == "scrub":
            if self.on_seek:
                self.on_seek(self.frame_at(pos.x))
            return
        moved = self._press_pos is not None and abs(pos.x - self._press_pos.x) + abs(pos.y - self._press_pos.y) > 3
        if self._mode == "keys-pending" and moved:
            self._mode = "keys"
        if self._mode == "keys" and self._press_pos is not None:
            delta = int(round((pos.x - self._press_pos.x) / self.frame_w))
            if self.on_move_keys and self._key_origins:
                self.on_move_keys(delta, self._key_origins)
                self._keys_moved = True
            return
        if self._mode == "marquee-pending" and moved:
            self._mode = "marquee"
        if self._mode == "marquee" and self._press_pos is not None:
            x0, y0 = self._press_pos.x, self._press_pos.y
            self._marquee_rect = wx.Rect(min(x0, pos.x), min(y0, pos.y), abs(pos.x - x0), abs(pos.y - y0))
            found = self._keys_in_rect(self._marquee_rect)
            merged = {k: set(v) for k, v in self._marquee_base.items()}
            for obj_id, ids in found.items():
                merged.setdefault(obj_id, set()).update(ids)
            if self.on_select_keys:
                self.on_select_keys(merged, True)
            self.Refresh(False)
            return
        if self._mode == "layer-pending" and moved:
            self._mode = "layer"
        if self._mode == "layer" and self._press_object:
            self._drop_target = self._drop_target_at(pos, self._press_object)
            self.Refresh(False)

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        mode = self._mode
        self._mode = None
        self._release()
        pos = event.GetPosition()
        if mode == "pan":
            self._pan_start = None
            self.SetCursor(wx.NullCursor)
            return
        if mode == "keys" and self._keys_moved and self.on_move_keys_end:
            self.on_move_keys_end()
        elif mode == "keys-pending" and self._stack_cycle and self.on_select_keys:
            # Clicking a selected key that shares its frame with others picks the next one.
            obj_id, next_id = self._stack_cycle
            self.on_select_keys({obj_id: {next_id}}, False)
        elif mode == "marquee-pending":
            # A plain click on a track: select that layer, clear keys, move the playhead.
            if self.on_select_keys:
                self.on_select_keys(self._marquee_base, False)
            if self.on_select_object:
                self.on_select_object(self._press_object)
            if self.on_seek:
                self.on_seek(self._press_frame)
        elif mode == "layer" and self._press_object and self._drop_target:
            target_mode, parent_id, before_id, _row = self._drop_target
            if self.on_move_layer:
                self.on_move_layer(self._press_object, parent_id, before_id)
        self._marquee_rect = None
        self._drop_target = None
        self._key_origins = {}
        self._stack_cycle = None
        self.Refresh(False)
        self._update_cursor(pos)

    def _on_left_dclick(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        row = self.row_at(pos.y)
        if not (0 <= row < len(self.rows)) or not self.scene:
            return
        obj, depth, _kids = self.rows[row]
        if pos.x < self.left_w:
            if self._layer_parts(row, depth)["name"].Contains(pos):
                self._start_rename(obj, row, depth)
            return
        if not self._key_at(pos) and obj.id not in self.locked_ids and self.on_add_key:
            self.on_add_key(obj.id, self.frame_at(pos.x))

    def _on_middle_down(self, event: wx.MouseEvent) -> None:
        self._start_pan(event.GetPosition())

    def _start_pan(self, pos: wx.Point) -> None:
        self._mode = "pan"
        self._pan_start = (pos, self.scroll_x, self.scroll_y)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self._capture()

    def _on_right_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        pos = event.GetPosition()
        if not self.scene or pos.y < self.header_h:
            return
        row = self.row_at(pos.y)
        obj_id = self.rows[row][0].id if 0 <= row < len(self.rows) else None
        frame = self.frame_at(pos.x)
        if pos.x < self.left_w:
            if obj_id and obj_id not in self.selected_object_ids and self.on_select_object:
                self.on_select_object(obj_id)  # (a selected layer keeps the group selected for its menu)
            if self.on_context_menu:
                self.on_context_menu("layer", obj_id, None, frame, pos)
            return
        key = self._key_at(pos)
        if key:
            obj_id, key_id, frame = key
            if key_id not in self.selection.get(obj_id, set()) and self.on_select_keys:
                self.on_select_keys({obj_id: {key_id}}, False)
            if self.on_context_menu:
                self.on_context_menu("key", obj_id, key_id, frame, pos)
            return
        segment = self._segment_at(pos)
        if segment and self.on_context_menu:
            self.on_context_menu("segment", segment[0], segment[1], frame, pos)
            return
        if self.on_context_menu:
            self.on_context_menu("track", obj_id, None, frame, pos)

    def _on_wheel(self, event: wx.MouseEvent) -> None:
        rotation = event.GetWheelRotation()
        if rotation == 0:
            return
        horizontal = event.GetWheelAxis() == wx.MOUSE_WHEEL_HORIZONTAL
        pos = event.GetPosition()
        moves = SCROLL.moves  # View ▸ Scroll Moves the View: scrolling scrolls, Cmd+scroll zooms
        if moves:
            zooming = event.CmdDown() and not horizontal and pos.x >= self.left_w
        else:
            zooming = not (horizontal or event.ShiftDown() or event.AltDown() or pos.x < self.left_w)
        if (zooming or not moves) and not self._wheel_filter.accept(horizontal, rotation, wheel_delta=event.GetWheelDelta()):
            return
        notches = rotation / float(max(1, event.GetWheelDelta()))
        if zooming:
            self.set_frame_width(self.frame_w * math.pow(1.1, notches), anchor_x=pos.x)
        elif horizontal or event.ShiftDown():
            self.set_scroll(x=self.scroll_x + notches * max(pxf(48.0), self.frame_w * 3.0))
        else:
            self.set_scroll(y=self.scroll_y - notches * self.row_h)

    def _on_capture_lost(self, _event: wx.MouseCaptureLostEvent) -> None:
        self._mode = None
        self._marquee_rect = None
        self._drop_target = None
        self.Refresh(False)

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_SPACE:
            return  # pan modifier; avoid the system beep
        event.Skip()

    def _on_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        self._clamp_scroll()
        self.Refresh(False)
        if self.on_view_changed:
            self.on_view_changed()

    def _update_cursor(self, pos: wx.Point) -> None:
        if abs(pos.x - self.left_w) <= px(3):
            self.SetCursor(wx.Cursor(wx.CURSOR_SIZEWE))
        elif pos.y < self.header_h and pos.x > self.left_w:
            self.SetCursor(wx.Cursor(wx.CURSOR_SIZEWE))
        else:
            self.SetCursor(wx.NullCursor)

    def _pose_marks_shown(self) -> bool:
        """The marks of the animations' pose changes are drawn only while frames are wide enough to tell apart."""
        return self.frame_w >= pxf(3.0)

    def pose_mark_at(self, pos: wx.Point) -> Optional[Tuple[TimelineObject, int]]:
        """The mark under the pointer at the bottom of a track: (its layer, the scene frame), else None."""
        if pos.x < self.left_w or not self._pose_marks_shown():
            return None
        row = self.row_at(pos.y)
        if not 0 <= row < len(self.rows):
            return None
        bottom = self.row_y(row) + self.row_h
        if not bottom - px(8) <= pos.y < bottom:
            return None
        obj = self.rows[row][0]
        frame = int(round((pos.x - self.left_w + self.scroll_x) / self.frame_w))  # the nearest mark's place
        if abs(self.frame_x(frame) - pos.x) <= px(3) and frame in self.anim_ticks.get(obj.id, ()):
            return obj, frame
        return None

    def _update_tip(self, pos: wx.Point) -> None:
        mark = self.pose_mark_at(pos)
        tip = ""
        if mark:
            obj, frame = mark
            tip = (f"Frame {frame}: '{obj.name}' shows the next pose of its animation.\n"
                   "The marks under a layer show every pose change as the scene plays its animation: "
                   "put keys on them to time a move to a pose.")
        if tip != self._tip:
            self._tip = tip
            if tip:
                self.SetToolTip(tip)
            else:
                self.UnsetToolTip()

    # ------------------------------------------------------------------ rename
    def _start_rename(self, obj: TimelineObject, row: int, depth: int) -> None:
        self._finish_rename(commit=True)
        rect = self._layer_parts(row, depth)["name"]
        ctrl = wx.TextCtrl(self, value=obj.name, pos=(rect.x - 2, rect.y + 2), size=(rect.width + 4, rect.height - 4), style=wx.TE_PROCESS_ENTER)
        ctrl.SetSelection(-1, -1)
        ctrl.SetFocus()
        ctrl.object_id = obj.id  # type: ignore[attr-defined]
        ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: self._finish_rename(commit=True))
        ctrl.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), wx.CallAfter(self._finish_rename, True)))
        ctrl.Bind(wx.EVT_CHAR_HOOK, self._on_rename_key)
        self._rename_ctrl = ctrl

    def _on_rename_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._finish_rename(commit=False)
            return
        event.Skip()

    def _finish_rename(self, commit: bool) -> None:
        ctrl = self._rename_ctrl
        if not ctrl:
            return
        self._rename_ctrl = None
        if commit and self.on_rename:
            name = ctrl.GetValue().strip()
            if name:
                self.on_rename(ctrl.object_id, name)  # type: ignore[attr-defined]
        ctrl.Destroy()
        self.SetFocus()

    # ------------------------------------------------------------------ paint
    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(T.track))
        dc.Clear()
        width, height = self.GetClientSize()
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        small = wx.Font(font)
        small.SetPointSize(max(8, font.GetPointSize() - 2))
        dc.SetFont(font)

        if not self.scene:
            dc.SetTextForeground(T.text_dim)
            dc.DrawText("No scene selected", 16, 16)
            return

        length = self.length()
        fps = self.scene.fps

        # ---- tracks
        dc.SetClippingRegion(self.left_w, self.header_h, max(1, width - self.left_w), max(1, height - self.header_h))
        first_frame = max(0, self.frame_at(self.left_w))
        last_frame = min(length, self.frame_at(width) + 1)
        end_x = self.frame_x(length + 1)
        for row, (obj, _depth, _kids) in enumerate(self.rows):
            y = self.row_y(row)
            if y + self.row_h < self.header_h or y > height:
                continue
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(self._row_colour(obj.id, row)))
            dc.DrawRectangle(self.left_w, int(y), width - self.left_w, self.row_h)
        # frame grid
        if self.frame_w >= pxf(5.0):
            for frame in range(first_frame, last_frame + 2):
                x = int(self.frame_x(frame))
                dc.SetPen(wx.Pen(T.grid_strong if frame % fps == 0 else T.grid))
                dc.DrawLine(x, self.header_h, x, height)
        # outside the scene
        if end_x < width:
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(T.outside))
            dc.DrawRectangle(int(end_x), self.header_h, int(width - end_x) + 1, height - self.header_h)

        # playhead column
        cur_x = self.frame_x(self.frame)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(wx.Colour(*T.palette.rgb("playhead"), 40)))
        dc.DrawRectangle(int(cur_x), self.header_h, max(1, int(math.ceil(self.frame_w))), height - self.header_h)

        for row, (obj, _depth, _kids) in enumerate(self.rows):
            y = self.row_y(row)
            if y + self.row_h < self.header_h or y > height:
                continue
            self._paint_track(dc, obj, int(y), small)
        dc.DestroyClippingRegion()

        # ---- ruler
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(T.ruler))
        dc.DrawRectangle(0, 0, width, self.header_h)
        dc.SetClippingRegion(self.left_w, 0, max(1, width - self.left_w), self.header_h)
        step = next((s for s in LABEL_STEPS if s * self.frame_w >= px(44)), LABEL_STEPS[-1])
        dc.SetFont(small)
        for frame in range(first_frame, last_frame + 1):
            x = int(self.frame_x(frame))
            is_second = frame % fps == 0
            if frame % step == 0:
                dc.SetPen(wx.Pen(T.text_dim))
                dc.DrawLine(x, self.header_h - px(10), x, self.header_h)
                dc.SetTextForeground(T.text if is_second else T.text_dim)
                label = str(frame)
                if is_second and frame:
                    label += f"  {frame // fps}s"
                dc.DrawText(label, x + 3, 3)
            elif self.frame_w >= pxf(5.0):
                dc.SetPen(wx.Pen(T.grid_strong))
                dc.DrawLine(x, self.header_h - px(4), x, self.header_h)
        # playhead marker + line
        cx = int(self.frame_center_x(self.frame))
        dc.SetPen(wx.Pen(T.playhead))
        dc.SetBrush(wx.Brush(T.playhead))
        label = str(self.frame)
        tw, th = dc.GetTextExtent(label)
        dc.DrawRoundedRectangle(cx - tw // 2 - 4, self.header_h - th - 6, tw + 8, th + 4, 3)
        dc.SetTextForeground(wx.Colour(255, 255, 255))
        dc.DrawText(label, cx - tw // 2, self.header_h - th - 4)
        dc.DestroyClippingRegion()
        dc.SetClippingRegion(self.left_w, self.header_h, max(1, width - self.left_w), max(1, height - self.header_h))
        dc.SetPen(wx.Pen(T.playhead, 1))
        dc.DrawLine(cx, self.header_h, cx, height)
        dc.DestroyClippingRegion()
        dc.SetFont(font)

        # ---- layer column
        dc.SetClippingRegion(0, self.header_h, self.left_w, max(1, height - self.header_h))
        for row, (obj, depth, kids) in enumerate(self.rows):
            y = self.row_y(row)
            if y + self.row_h < self.header_h or y > height:
                continue
            self._paint_layer(dc, obj, row, depth, kids)
        if not self.rows:
            dc.SetTextForeground(T.text_dim)
            dc.DrawText("Drag modules, frames or", px(12), self.header_h + px(10))
            dc.DrawText("animations onto the stage", px(12), self.header_h + px(28))
        dc.DestroyClippingRegion()
        dc.SetTextForeground(T.text_dim)
        dc.DrawText("Layers", px(10), px(6))
        dc.SetFont(small)
        dc.DrawText("lower rows draw on top", px(64), px(8))
        dc.SetFont(font)
        dc.SetPen(wx.Pen(T.tick))
        dc.DrawLine(self.left_w, 0, self.left_w, height)
        dc.DrawLine(0, self.header_h - 1, width, self.header_h - 1)

        # ---- overlays
        if self._marquee_rect:
            dc.SetPen(wx.Pen(T.drop, 1, wx.PENSTYLE_SHORT_DASH))
            dc.SetBrush(wx.Brush(wx.Colour(*T.palette.rgb("drop"), 30)))
            r = self._marquee_rect
            dc.DrawRectangle(r.x, r.y, r.width, r.height)
        if self._drop_target:
            mode, _parent, _before, row = self._drop_target
            dc.SetPen(wx.Pen(T.drop, 2))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            if mode == "into":
                y = int(self.row_y(row))
                dc.DrawRectangle(2, y + 1, self.left_w - 4, self.row_h - 2)
            else:
                y = int(self.row_y(row))
                depth = self.rows[min(row, len(self.rows) - 1)][1] if self.rows and row < len(self.rows) else 0
                dc.DrawLine(px(6) + depth * px(14), y, self.left_w - 4, y)

    def _row_colour(self, object_id: str, row: int) -> wx.Colour:
        if object_id == self.selected_object_id:
            return T.selected
        if object_id in self.selected_object_ids:
            return T.also_selected
        return T.row_alt if row % 2 == 0 else T.row

    def _paint_layer(self, dc: wx.DC, obj: TimelineObject, row: int, depth: int, kids: bool) -> None:
        y = int(self.row_y(row))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(self._row_colour(obj.id, row)))
        dc.DrawRectangle(0, y, self.left_w, self.row_h)
        parts = self._layer_parts(row, depth)
        if kids:
            r = parts["disclosure"]
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(T.text_dim))
            if obj.id in self.collapsed_ids:
                dc.DrawPolygon([wx.Point(r.x + px(3), r.y + px(2)), wx.Point(r.x + px(9), r.y + px(6)),
                                wx.Point(r.x + px(3), r.y + px(10))])
            else:
                dc.DrawPolygon([wx.Point(r.x + px(2), r.y + px(3)), wx.Point(r.x + px(10), r.y + px(3)),
                                wx.Point(r.x + px(6), r.y + px(9))])
        g = parts["glyph"]
        colour = TYPE_COLOURS.get(obj.source_type, TYPE_COLOURS["none"])
        dc.SetBrush(wx.Brush(colour))
        dc.SetPen(wx.Pen(colour))
        if obj.source_type == "animation":
            dc.DrawPolygon([wx.Point(g.x, g.y), wx.Point(g.Right + 1, g.y + g.height // 2), wx.Point(g.x, g.Bottom + 1)])
        elif obj.source_type == "none":
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(g.x, g.y + px(2), g.width, g.height - px(2))
        else:
            dc.DrawRectangle(g.x, g.y, g.width, g.height)
        hidden = obj.id in self.hidden_ids
        locked = obj.id in self.locked_ids
        dc.SetTextForeground(T.text_dim if hidden else T.text)
        name_rect = parts["name"]
        text = _fit_text(dc, obj.name, name_rect.width)
        dc.DrawText(text, name_rect.x, y + (self.row_h - dc.GetTextExtent("Ag")[1]) // 2)

        # eye
        e = parts["eye"]
        dc.SetPen(wx.Pen(T.text_dim if hidden else T.text, 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        if hidden:
            dc.DrawLine(e.x + 3, e.y + e.height // 2, e.x + e.width - 3, e.y + e.height // 2)
        else:
            dc.DrawEllipse(e.x + 1, e.y + px(4), e.width - 2, e.height - px(8))
            dc.SetBrush(wx.Brush(T.text))
            dc.DrawCircle(e.x + e.width // 2, e.y + e.height // 2, px(2))
        # lock
        lk = parts["lock"]
        dc.SetPen(wx.Pen(T.accent if locked else T.cell_border, 1))
        dc.SetBrush(wx.Brush(T.accent) if locked else wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(lk.x + px(4), lk.y + px(7), px(10), px(7))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawArc(lk.x + px(12), lk.y + px(7), lk.x + px(6), lk.y + px(7), lk.x + px(9), lk.y + px(7))

    def _paint_track(self, dc: wx.DC, obj: TimelineObject, y: int, small: wx.Font) -> None:
        fps = self.scene.fps
        mid = y + self.row_h // 2
        keys = obj.sorted_keyframes()
        selected_keys = self.selection.get(obj.id, set())

        # animation frame changes (timing reference; hovering one explains it: pose_mark_at)
        ticks = self.anim_ticks.get(obj.id, [])
        if ticks and self._pose_marks_shown():
            dc.SetPen(wx.Pen(T.ok, 1))
            for frame in ticks:
                x = int(self.frame_x(frame))
                dc.DrawLine(x, y + self.row_h - px(6), x, y + self.row_h - 1)

        # segments
        dc.SetFont(small)
        for a, b in zip(keys, keys[1:]):
            x0 = self.frame_center_x(ops.frame_of(a.time, fps))
            x1 = self.frame_center_x(ops.frame_of(b.time, fps))
            if x1 <= x0:
                continue
            easing = b.easing
            if easing == "step":
                dc.SetPen(wx.Pen(T.hold, 1, wx.PENSTYLE_SHORT_DASH))
                dc.DrawLine(int(x0), mid, int(x1), mid)
                continue
            colour = T.tween if easing == "linear" else T.tween_eased
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(colour))
            dc.DrawRectangle(int(x0), mid - px(4), int(x1 - x0), px(8))
            if x1 - x0 > px(70):
                label = ops.easing_label(easing)
                tw, th = dc.GetTextExtent(label)
                if tw < x1 - x0 - px(16):
                    dc.SetTextForeground(T.tween_text)
                    dc.DrawText(label, int((x0 + x1 - tw) / 2), mid - th // 2)

        # keys (selected last so they stay visible when keys share a frame)
        stack_sizes: Dict[int, int] = {}
        # A swap label runs up to the next swap key (shortened with "…"), so close swaps stay readable.
        swap_xs = sorted({self.frame_center_x(ops.frame_of(k.time, fps)) for k in keys if k.source_type is not None})
        for key in keys:
            frame = ops.frame_of(key.time, fps)
            stack_sizes[frame] = stack_sizes.get(frame, 0) + 1
        for key in sorted(keys, key=lambda k: k.id in selected_keys):
            frame = ops.frame_of(key.time, fps)
            cx = self.frame_center_x(frame)
            selected = key.id in selected_keys
            fill = T.accent if selected else T.key
            dc.SetPen(wx.Pen(T.swatch_selected if selected else T.outline, 1))
            dc.SetBrush(wx.Brush(fill))
            r = px(6) if selected else px(5)
            if key.source_type is not None:
                dc.DrawRectangle(int(cx - r), mid - r, 2 * r, 2 * r)
                label = self.source_labels.get(key.id)
                next_x = next((x for x in swap_xs if x > cx), None)
                if label and next_x is not None:
                    label = _fit_text(dc, label, next_x - 9 - (cx + r + 3))
                if label:
                    dc.SetTextForeground(T.text)
                    dc.DrawText(label, int(cx + r + 3), y + 1)
            else:
                dc.DrawPolygon([
                    wx.Point(int(cx), mid - r), wx.Point(int(cx + r), mid),
                    wx.Point(int(cx), mid + r), wx.Point(int(cx - r), mid),
                ])
        # Several keys on one frame (old files): flag them so they are not mistaken for one key.
        dc.SetTextForeground(T.key_stack)
        for frame, count in stack_sizes.items():
            if count > 1:
                dc.DrawText(f"×{count}", int(self.frame_center_x(frame) + px(6)), y)


class TimelineView(wx.Panel):
    """TimelineWidget plus scrollbars kept in sync with it."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        self.widget = TimelineWidget(self)
        self.vbar = wx.ScrollBar(self, style=wx.SB_VERTICAL)
        self.hbar = wx.ScrollBar(self, style=wx.SB_HORIZONTAL)
        grid = wx.FlexGridSizer(2, 2, 0, 0)
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableRow(0, 1)
        grid.Add(self.widget, 1, wx.EXPAND)
        grid.Add(self.vbar, 0, wx.EXPAND)
        grid.Add(self.hbar, 0, wx.EXPAND)
        grid.AddSpacer(1)
        self.SetSizer(grid)
        self._syncing = False
        self.widget.on_view_changed = self.sync_scrollbars
        for evt in (wx.EVT_SCROLL_THUMBTRACK, wx.EVT_SCROLL_CHANGED, wx.EVT_SCROLL_LINEUP,
                    wx.EVT_SCROLL_LINEDOWN, wx.EVT_SCROLL_PAGEUP, wx.EVT_SCROLL_PAGEDOWN):
            self.hbar.Bind(evt, self._on_hbar)
            self.vbar.Bind(evt, self._on_vbar)

    def sync_scrollbars(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            w = self.widget
            page_x = max(1, w.track_w())
            page_y = max(1, w.rows_h())
            self.hbar.SetScrollbar(int(w.scroll_x), page_x, int(max(page_x, w.content_w())), max(1, page_x // 2), True)
            self.vbar.SetScrollbar(int(w.scroll_y), page_y, int(max(page_y, w.content_h())), max(1, page_y // 2), True)
            self.hbar.Enable(w.max_scroll_x() > 0)
            self.vbar.Enable(w.max_scroll_y() > 0)
        finally:
            self._syncing = False

    def _on_hbar(self, event: wx.ScrollEvent) -> None:
        if not self._syncing:
            self.widget.set_scroll(x=float(event.GetPosition()))
        event.Skip()

    def _on_vbar(self, event: wx.ScrollEvent) -> None:
        if not self._syncing:
            self.widget.set_scroll(y=float(event.GetPosition()))
        event.Skip()
