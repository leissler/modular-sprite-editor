"""Timeline editor panel for scene-based composited animations."""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

import wx

from models import (
    FModule,
    TIMELINE_EASINGS,
    TIMELINE_PATH_MODES,
    TIMELINE_SOURCE_TYPES,
    TimelineKeyframe,
    TimelineObject,
    TimelineScene,
    Project,
    apply_timeline_easing,
    generate_id,
)
from ui.canvas import FrameCanvas
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.components.frame_palette import FramePalette
from ui.frame_editor import ModulePalette
from ui.utils import ThumbnailGenerator

RULER_MODE_TIME = "Time"
RULER_MODE_FRAMES = "Frames"
SNAP_FREE = "Free"
SNAP_FRAMES = "Frames"
SNAP_TENTHS = "0.1s"
SNAP_CUSTOM = "Custom"
KEY_SOURCE_NO_CHANGE = "<no change>"


class AnimationPalette(wx.ListCtrl):
    """Visual palette for classic animations using the first frame as an icon."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, style=wx.LC_ICON | wx.LC_SINGLE_SEL | wx.LC_AUTOARRANGE)
        self.project = project
        self.generator = ThumbnailGenerator()
        self.image_list = wx.ImageList(96, 96)
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.animation_ids: List[str] = []
        self.on_animation_double_click: Optional[Callable[[str], None]] = None

        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.on_begin_drag)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_activated)

    def refresh_animations(self) -> None:
        self.DeleteAllItems()
        self.image_list = wx.ImageList(96, 96)
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.animation_ids = []
        self.generator.clear_cache()

        for anim in self.project.animations:
            preview = None
            if anim.aframes:
                preview = self.project.get_frame(anim.aframes[0].frame_id)
            if preview:
                bmp = self.generator.render_thumbnail(
                    self.project,
                    preview,
                    96,
                    96,
                    mapping=self.project.active_mapping,
                )
            else:
                bmp = wx.Bitmap(96, 96)
                dc = wx.MemoryDC(bmp)
                dc.SetBackground(wx.Brush(wx.Colour(50, 50, 50)))
                dc.Clear()
                dc.SetTextForeground(wx.Colour(180, 180, 180))
                dc.DrawLabel("Empty", wx.Rect(0, 0, 96, 96), alignment=wx.ALIGN_CENTER)
                dc.SelectObject(wx.NullBitmap)
            img_idx = self.image_list.Add(bmp)
            item_idx = self.InsertItem(self.GetItemCount(), anim.name, img_idx)
            self.SetItemData(item_idx, item_idx)
            self.animation_ids.append(anim.id)

    def on_item_activated(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.animation_ids) and self.on_animation_double_click:
            self.on_animation_double_click(self.animation_ids[idx])

    def on_begin_drag(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.animation_ids):
            text_data = wx.TextDataObject(f"ANIMATION:{self.animation_ids[idx]}")
            source = wx.DropSource(self)
            source.SetData(text_data)
            source.DoDragDrop(wx.Drag_CopyOnly)


class TimelineCanvasDropTarget(wx.TextDropTarget):
    """Accept palette drags on the timeline canvas and create scene objects."""

    def __init__(self, editor: "TimelineEditorPanel"):
        super().__init__()
        self.editor = editor

    def OnDropText(self, x: int, y: int, data: str) -> bool:
        if ":" not in data:
            return False
        prefix, asset_id = data.split(":", 1)
        source_type = prefix.strip().lower()
        if source_type == "animation":
            source_type = "animation"
        elif source_type == "frame":
            source_type = "frame"
        elif source_type == "module":
            source_type = "module"
        else:
            return False
        self.editor.add_object_from_palette(source_type, asset_id.strip(), wx.Point(x, y))
        return True


class TimelineCanvas(FrameCanvas):
    """Preview canvas for timeline scenes."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project, read_only=True)
        self.scene: Optional[TimelineScene] = None
        self.current_time: float = 0.0
        self.selected_object_id: Optional[str] = None
        self.selected_key_id: Optional[str] = None
        self.on_select_object: Optional[Callable[[str], None]] = None
        self.on_select_key: Optional[Callable[[str, str], None]] = None
        self.on_begin_drag_object: Optional[Callable[[str], None]] = None
        self.on_drag_object: Optional[Callable[[str, float, float], None]] = None
        self.on_begin_drag_keyframe: Optional[Callable[[str, str], None]] = None
        self.on_drag_keyframe: Optional[Callable[[str, str, float, float], None]] = None
        self.on_begin_drag_key_handle: Optional[Callable[[str, str, str, float, float], None]] = None
        self.on_drag_key_handle: Optional[Callable[[str, str, str, float, float], None]] = None
        self.on_flip_object_x: Optional[Callable[[str], None]] = None
        self.on_flip_object_y: Optional[Callable[[str], None]] = None
        self.on_rotate_object_90_cw: Optional[Callable[[str], None]] = None
        self.on_rotate_object_90_ccw: Optional[Callable[[str], None]] = None
        self.zoom = 4.0
        self.max_zoom = 24.0
        self.show_grid = True
        self.grid_spacing = (32, 32)
        self.show_collision = False
        self.show_points = False
        self.selected_fmodules = []
        self._drawn_objects: List[Dict[str, Any]] = []
        self._drawn_key_markers: List[Dict[str, Any]] = []
        self._drawn_path_handles: List[Dict[str, Any]] = []
        self._drag_object_id: Optional[str] = None
        self._drag_parent_matrix: Tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self._drag_start_world: Optional[Tuple[float, float]] = None
        self._drag_key_object_id: Optional[str] = None
        self._drag_key_id: Optional[str] = None
        self._drag_key_parent_matrix: Tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self._drag_key_start_world: Optional[Tuple[float, float]] = None
        self._drag_handle_object_id: Optional[str] = None
        self._drag_handle_key_id: Optional[str] = None
        self._drag_handle_kind: Optional[str] = None
        self._drag_handle_parent_matrix: Tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self._drag_handle_start_world: Optional[Tuple[float, float]] = None
        self._key_marker_radius = 4
        self._key_marker_hit_radius = 8
        self._path_handle_radius = 4
        self._path_handle_hit_radius = 8
        self._last_hit_cycle_key: Optional[Tuple[int, int, Tuple[str, ...]]] = None
        self._last_hit_cycle_idx: int = -1

        # Override FrameCanvas edit handlers with timeline pan behavior.
        self.Unbind(wx.EVT_LEFT_DOWN)
        self.Unbind(wx.EVT_LEFT_UP)
        self.Unbind(wx.EVT_MOTION)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_mouse_drag)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_right_down)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.clear_cache()
        self.Refresh(False)

    def set_scene(self, scene: Optional[TimelineScene]) -> None:
        self.scene = scene
        self.Refresh(False)

    def set_time(self, time_value: float) -> None:
        self.current_time = max(0.0, float(time_value))
        self.Refresh(False)

    def set_selected_object(self, object_id: Optional[str]) -> None:
        self.selected_object_id = object_id
        self.Refresh(False)

    def set_selected_key(self, key_id: Optional[str]) -> None:
        self.selected_key_id = key_id
        self.Refresh(False)

    def _build_local_matrix(self, state: Dict[str, Any]) -> Tuple[float, float, float, float, float, float]:
        source_offset = state.get("source_offset", (0.0, 0.0))
        tx = float(state.get("x", 0.0)) + float(source_offset[0])
        ty = float(state.get("y", 0.0)) + float(source_offset[1])

        total_rotation = float(state.get("rotation_degrees", 0.0)) + float(state.get("source_rotation", 0.0))
        rot_rad = math.radians(total_rotation)
        cos_a = math.cos(rot_rad)
        sin_a = math.sin(rot_rad)

        flip_x = bool(state.get("flip_x", False)) ^ bool(state.get("source_flip_x", False))
        flip_y = bool(state.get("flip_y", False)) ^ bool(state.get("source_flip_y", False))
        sx = -1.0 if flip_x else 1.0
        sy = -1.0 if flip_y else 1.0

        # Matrix for Rotate * Scale with translation.
        a = cos_a * sx
        b = sin_a * sx
        c = -sin_a * sy
        d = cos_a * sy
        return (a, b, c, d, tx, ty)

    @staticmethod
    def _compose_matrix(
        parent: Tuple[float, float, float, float, float, float],
        child: Tuple[float, float, float, float, float, float],
    ) -> Tuple[float, float, float, float, float, float]:
        ap, bp, cp, dp, txp, typ = parent
        ac, bc, cc, dc, txc, tyc = child
        return (
            ap * ac + cp * bc,
            bp * ac + dp * bc,
            ap * cc + cp * dc,
            bp * cc + dp * dc,
            ap * txc + cp * tyc + txp,
            bp * txc + dp * tyc + typ,
        )

    @staticmethod
    def _decompose_matrix_to_frame_transform(
        matrix: Tuple[float, float, float, float, float, float],
    ) -> Tuple[Tuple[float, float], float, bool, bool]:
        a, b, c, d, tx, ty = matrix
        sx = math.hypot(a, b)
        sy = math.hypot(c, d)
        if sx <= 1e-6 or sy <= 1e-6:
            return ((tx, ty), 0.0, False, False)
        an, bn = a / sx, b / sx
        cn, dn = c / sy, d / sy
        det = an * dn - bn * cn

        render_flip_x = False
        render_flip_y = det < 0.0
        if render_flip_y:
            cn = -cn
            dn = -dn

        render_rotation = math.degrees(math.atan2(bn, an))
        return ((tx, ty), render_rotation, render_flip_x, render_flip_y)

    def _draw_source_with_matrix(self, gc: wx.GraphicsContext, state: Dict[str, Any], matrix: Tuple[float, float, float, float, float, float]) -> None:
        source_type = state.get("source_type")
        source_id = state.get("source_id")
        frame_id = state.get("frame_id") or source_id

        if source_type == "none":
            return
        if source_type == "module" and not source_id:
            return
        if source_type in ("frame", "animation") and not frame_id:
            return

        old_frame = self.frame
        old_offset = self.frame_offset
        old_flip_x = self.render_flip_x
        old_flip_y = self.render_flip_y
        old_rot = self.render_rotation

        offset, rot, flip_x, flip_y = self._decompose_matrix_to_frame_transform(matrix)
        self.frame_offset = offset
        self.render_rotation = rot
        self.render_flip_x = flip_x
        self.render_flip_y = flip_y

        if source_type == "module" and source_id:
            self.frame = None
            temp_fm = FModule(
                id="tl_temp_module",
                ref_type="module",
                ref_id=str(source_id),
                position=(0, 0),
                flip_x=False,
                flip_y=False,
                rotation_degrees=0.0,
            )
            self._draw_fmodule_content(gc, temp_fm)
        elif frame_id:
            frame = self.project.get_frame(str(frame_id))
            self.frame = frame
            if frame:
                for fm in frame.fmodules:
                    self._draw_fmodule_content(gc, fm)

        self.frame = old_frame
        self.frame_offset = old_offset
        self.render_flip_x = old_flip_x
        self.render_flip_y = old_flip_y
        self.render_rotation = old_rot

    @staticmethod
    def _apply_matrix(matrix: Tuple[float, float, float, float, float, float], x: float, y: float) -> Tuple[float, float]:
        a, b, c, d, tx, ty = matrix
        return (a * x + c * y + tx, b * x + d * y + ty)

    def _source_local_bounds(self, state: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
        source_type = state.get("source_type")
        source_id = state.get("source_id")
        frame_id = state.get("frame_id") or source_id

        if source_type == "module" and source_id:
            fm = FModule(
                id="tl_bounds_module",
                ref_type="module",
                ref_id=str(source_id),
                position=(0, 0),
                flip_x=False,
                flip_y=False,
                rotation_degrees=0.0,
            )
            return self._fmodule_bounds(fm)

        if source_type in ("frame", "animation") and frame_id:
            frame = self.project.get_frame(str(frame_id))
            if not frame or not frame.fmodules:
                return None
            first = True
            min_x = min_y = max_x = max_y = 0.0
            for fm in frame.fmodules:
                x0, y0, x1, y1 = self._fmodule_bounds(fm)
                if first:
                    min_x, min_y, max_x, max_y = x0, y0, x1, y1
                    first = False
                else:
                    min_x = min(min_x, x0)
                    min_y = min(min_y, y0)
                    max_x = max(max_x, x1)
                    max_y = max(max_y, y1)
            return (min_x, min_y, max_x, max_y)

        return None

    def _screen_rect_for_object(
        self,
        state: Dict[str, Any],
        world_matrix: Tuple[float, float, float, float, float, float],
    ) -> Optional[wx.Rect]:
        bounds = self._source_local_bounds(state)
        if bounds is None:
            return None
        x0, y0, x1, y1 = bounds
        corners_world = [
            self._apply_matrix(world_matrix, x0, y0),
            self._apply_matrix(world_matrix, x1, y0),
            self._apply_matrix(world_matrix, x0, y1),
            self._apply_matrix(world_matrix, x1, y1),
        ]
        corners_screen = [self.world_to_screen((wxv, wyv)) for wxv, wyv in corners_world]
        sx_vals = [p[0] for p in corners_screen]
        sy_vals = [p[1] for p in corners_screen]
        left = int(math.floor(min(sx_vals)))
        top = int(math.floor(min(sy_vals)))
        right = int(math.ceil(max(sx_vals)))
        bottom = int(math.ceil(max(sy_vals)))
        width = max(1, right - left)
        height = max(1, bottom - top)
        return wx.Rect(left, top, width, height)

    def _record_drawn_object(
        self,
        object_id: str,
        state: Dict[str, Any],
        parent_matrix: Tuple[float, float, float, float, float, float],
        world_matrix: Tuple[float, float, float, float, float, float],
    ) -> None:
        rect = self._screen_rect_for_object(state, world_matrix)
        if rect is None:
            return
        self._drawn_objects.append(
            {
                "object_id": object_id,
                "parent_matrix": parent_matrix,
                "world_matrix": world_matrix,
                "screen_rect": rect,
            }
        )

    def _hit_test_object(self, pos: wx.Point) -> Optional[Dict[str, Any]]:
        hits = [item for item in self._drawn_objects if item["screen_rect"].Contains(pos)]
        if not hits:
            self._last_hit_cycle_key = None
            self._last_hit_cycle_idx = -1
            return None

        cycle_key = (int(pos.x), int(pos.y), tuple(item["object_id"] for item in hits))
        if cycle_key == self._last_hit_cycle_key:
            self._last_hit_cycle_idx = (self._last_hit_cycle_idx + 1) % len(hits)
        else:
            self._last_hit_cycle_key = cycle_key
            self._last_hit_cycle_idx = 0
        return hits[len(hits) - 1 - self._last_hit_cycle_idx]

    def _hit_test_key_marker(self, pos: wx.Point) -> Optional[Dict[str, Any]]:
        hits: List[Tuple[float, Dict[str, Any]]] = []
        hit_r2 = float(self._key_marker_hit_radius * self._key_marker_hit_radius)
        for marker in self._drawn_key_markers:
            mx, my = marker["screen_pos"]
            dx = float(pos.x) - float(mx)
            dy = float(pos.y) - float(my)
            d2 = dx * dx + dy * dy
            if d2 <= hit_r2:
                hits.append((d2, marker))
        if not hits:
            return None
        hits.sort(key=lambda item: (0 if item[1]["key_id"] == self.selected_key_id else 1, item[0]))
        return hits[0][1]

    def _hit_test_path_handle(self, pos: wx.Point) -> Optional[Dict[str, Any]]:
        hits: List[Tuple[float, Dict[str, Any]]] = []
        hit_r2 = float(self._path_handle_hit_radius * self._path_handle_hit_radius)
        for handle in self._drawn_path_handles:
            hx, hy = handle["screen_pos"]
            dx = float(pos.x) - float(hx)
            dy = float(pos.y) - float(hy)
            d2 = dx * dx + dy * dy
            if d2 <= hit_r2:
                hits.append((d2, handle))
        if not hits:
            return None
        hits.sort(
            key=lambda item: (
                0 if item[1]["key_id"] == self.selected_key_id else 1,
                0 if item[1]["explicit"] else 1,
                item[0],
            )
        )
        return hits[0][1]

    def _auto_tangent_handles_for_key(
        self, keys: List[TimelineKeyframe], index: int
    ) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
        if index < 0 or index >= len(keys):
            return (None, None)
        if len(keys) <= 1:
            return (None, None)
        key = keys[index]
        px, py = float(key.x), float(key.y)

        if 0 < index < len(keys) - 1:
            prev_key = keys[index - 1]
            next_key = keys[index + 1]
            tx = (float(next_key.x) - float(prev_key.x)) / 6.0
            ty = (float(next_key.y) - float(prev_key.y)) / 6.0
            return ((px - tx, py - ty), (px + tx, py + ty))

        if index == 0 and len(keys) >= 2:
            next_key = keys[1]
            return (
                None,
                (
                    px + (float(next_key.x) - px) / 3.0,
                    py + (float(next_key.y) - py) / 3.0,
                ),
            )

        prev_key = keys[-2]
        return (
            (
                px - (px - float(prev_key.x)) / 3.0,
                py - (py - float(prev_key.y)) / 3.0,
            ),
            None,
        )

    def _sample_object_world_position(
        self,
        obj: TimelineObject,
        time_value: float,
        sample_cache: Optional[Dict[float, Optional[Tuple[Tuple[float, float], Tuple[float, float, float, float, float, float]]]]] = None,
    ) -> Optional[Tuple[float, float]]:
        sampled = self._sample_object_world_and_parent_matrix(obj, time_value, sample_cache)
        if sampled is None:
            return None
        return sampled[0]

    def _sample_object_world_and_parent_matrix(
        self,
        obj: TimelineObject,
        time_value: float,
        sample_cache: Optional[Dict[float, Optional[Tuple[Tuple[float, float], Tuple[float, float, float, float, float, float]]]]] = None,
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float, float, float, float, float]]]:
        if not self.scene:
            return None
        time_key = round(float(time_value), 6)
        if sample_cache is not None and time_key in sample_cache:
            return sample_cache[time_key]

        scene = self.scene
        identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        state_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        world_cache: Dict[str, Tuple[float, float, float, float, float, float]] = {}

        def sample_state(object_id: str) -> Optional[Dict[str, Any]]:
            if object_id not in state_cache:
                state_cache[object_id] = scene.evaluate_object_state(self.project, object_id, float(time_key))
            return state_cache[object_id]

        def sample_world(object_id: str) -> Tuple[float, float, float, float, float, float]:
            if object_id in world_cache:
                return world_cache[object_id]
            current_obj = scene.get_object(object_id)
            current_state = sample_state(object_id)
            if current_obj is None or current_state is None:
                world_cache[object_id] = identity
                return identity
            parent_id = current_obj.parent_id
            if parent_id and scene.get_object(parent_id):
                parent_world = sample_world(parent_id)
            else:
                parent_world = identity
            world = self._compose_matrix(parent_world, self._build_local_matrix(current_state))
            world_cache[object_id] = world
            return world

        state = sample_state(obj.id)
        if state is None:
            if sample_cache is not None:
                sample_cache[time_key] = None
            return None
        parent_id = obj.parent_id
        parent_world = sample_world(parent_id) if parent_id and scene.get_object(parent_id) else identity
        result = (self._apply_matrix(parent_world, float(state["x"]), float(state["y"])), parent_world)
        if sample_cache is not None:
            sample_cache[time_key] = result
        return result

    def _draw_state_recursive(
        self,
        gc: wx.GraphicsContext,
        state_map: Dict[str, Dict[str, Any]],
        children_map: Dict[Optional[str], List[str]],
        object_id: str,
        parent_matrix: Tuple[float, float, float, float, float, float],
    ) -> None:
        state = state_map.get(object_id)
        if not state or not state.get("visible", True):
            return

        local_matrix = self._build_local_matrix(state)
        world_matrix = self._compose_matrix(parent_matrix, local_matrix)
        self._draw_source_with_matrix(gc, state, world_matrix)
        self._record_drawn_object(object_id, state, parent_matrix, world_matrix)

        for child_id in children_map.get(object_id, []):
            self._draw_state_recursive(gc, state_map, children_map, child_id, world_matrix)

    def _draw_path_for_selected(self, gc: wx.GraphicsContext) -> None:
        self._drawn_key_markers = []
        self._drawn_path_handles = []
        if not self.scene or not self.selected_object_id:
            return
        obj = self.scene.get_object(self.selected_object_id)
        if not obj:
            return

        keys = obj.sorted_keyframes()
        sample_cache: Dict[
            float,
            Optional[Tuple[Tuple[float, float], Tuple[float, float, float, float, float, float]]],
        ] = {}
        points: List[Tuple[float, float]] = []
        if len(keys) >= 2:
            for idx in range(len(keys) - 1):
                start_t = float(keys[idx].time)
                end_t = float(keys[idx + 1].time)
                span = end_t - start_t
                if span <= 1e-9:
                    continue

                probe_count = 6
                probe_screen: List[Tuple[float, float]] = []
                for probe_idx in range(probe_count + 1):
                    ratio = float(probe_idx) / float(probe_count)
                    probe_t = start_t + span * ratio
                    pos = self._sample_object_world_position(obj, probe_t, sample_cache)
                    if pos is None:
                        continue
                    probe_screen.append(self.world_to_screen(pos))

                length_px = 0.0
                for probe_idx in range(1, len(probe_screen)):
                    dx = float(probe_screen[probe_idx][0]) - float(probe_screen[probe_idx - 1][0])
                    dy = float(probe_screen[probe_idx][1]) - float(probe_screen[probe_idx - 1][1])
                    length_px += math.hypot(dx, dy)

                time_based = int(math.ceil(span * float(max(1, self.scene.fps)) * 1.5))
                distance_based = int(math.ceil(length_px / 8.0))
                segments = max(2, time_based, distance_based)
                segments = max(2, min(120, segments))

                for seg_idx in range(segments + 1):
                    if idx > 0 and seg_idx == 0:
                        continue
                    ratio = float(seg_idx) / float(segments)
                    sample_t = start_t + span * ratio
                    pos = self._sample_object_world_position(obj, sample_t, sample_cache)
                    if pos is not None:
                        points.append(pos)
        elif len(keys) == 1:
            single_pos = self._sample_object_world_position(obj, float(keys[0].time), sample_cache)
            if single_pos is not None:
                points.append(single_pos)

        if points:
            gc.PushState()
            gc.SetPen(wx.Pen(wx.Colour(110, 180, 255), 1))
            path = gc.CreatePath()
            p0 = self.world_to_screen(points[0])
            path.MoveToPoint(p0[0], p0[1])
            for px, py in points[1:]:
                sx, sy = self.world_to_screen((px, py))
                path.AddLineToPoint(sx, sy)
            gc.StrokePath(path)
            gc.PopState()

        gc.PushState()
        for index, key in enumerate(keys):
            sampled = self._sample_object_world_and_parent_matrix(obj, float(key.time), sample_cache)
            if sampled is None:
                continue
            key_pos, parent_world = sampled
            wx_pos, wy_pos = key_pos
            sx, sy = self.world_to_screen((wx_pos, wy_pos))
            marker = {
                "object_id": obj.id,
                "key_id": key.id,
                "parent_matrix": parent_world,
                "screen_pos": (float(sx), float(sy)),
            }
            self._drawn_key_markers.append(marker)
            is_selected = key.id == self.selected_key_id
            radius = self._key_marker_radius + (1 if is_selected else 0)
            fill = wx.Colour(255, 194, 102) if is_selected else wx.Colour(110, 180, 255)
            outline = wx.Colour(255, 255, 255) if is_selected else wx.Colour(20, 20, 20)
            gc.SetPen(wx.Pen(outline, 1))
            gc.SetBrush(wx.Brush(fill))
            gc.DrawEllipse(float(sx) - radius, float(sy) - radius, radius * 2, radius * 2)

            if is_selected and (obj.path_mode or "linear") == "spline":
                auto_in, auto_out = self._auto_tangent_handles_for_key(keys, index)
                in_local = tuple(float(v) for v in key.path_in) if key.path_in is not None else auto_in
                out_local = tuple(float(v) for v in key.path_out) if key.path_out is not None else auto_out
                for kind, local_pt, explicit, color in (
                    ("in", in_local, key.path_in is not None, wx.Colour(255, 160, 80)),
                    ("out", out_local, key.path_out is not None, wx.Colour(120, 220, 255)),
                ):
                    if local_pt is None:
                        continue
                    handle_wx, handle_wy = self._apply_matrix(parent_world, float(local_pt[0]), float(local_pt[1]))
                    hsx, hsy = self.world_to_screen((handle_wx, handle_wy))
                    gc.SetPen(wx.Pen(color, 1, style=wx.PENSTYLE_SOLID if explicit else wx.PENSTYLE_DOT))
                    gc.StrokeLine(float(sx), float(sy), float(hsx), float(hsy))
                    gc.SetPen(wx.Pen(color, 1))
                    if explicit:
                        gc.SetBrush(wx.Brush(color))
                    else:
                        gc.SetBrush(wx.TRANSPARENT_BRUSH)
                    hr = self._path_handle_radius
                    gc.DrawRectangle(float(hsx) - hr, float(hsy) - hr, hr * 2, hr * 2)
                    self._drawn_path_handles.append(
                        {
                            "object_id": obj.id,
                            "key_id": key.id,
                            "handle_kind": kind,
                            "parent_matrix": parent_world,
                            "local_pos": (float(local_pt[0]), float(local_pt[1])),
                            "screen_pos": (float(hsx), float(hsy)),
                            "explicit": bool(explicit),
                        }
                    )
        gc.PopState()

    def on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        self._drawn_objects = []
        self._drawn_key_markers = []
        self._drawn_path_handles = []
        if self.scene:
            bg = wx.Colour(*self.scene.background_color)
            dc.SetBackground(wx.Brush(bg))
            dc.Clear()
        if self.show_transparency:
            self._draw_checkerboard(dc)
        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            return
        self._draw_grid(gc)
        if not self.scene:
            gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(180, 180, 180))
            gc.DrawText("No scene selected", 20, 20)
            return

        self._draw_path_for_selected(gc)

        state_map = {
            state["object_id"]: state
            for state in self.scene.sample_draw_list(self.project, self.current_time)
        }
        children_map: Dict[Optional[str], List[str]] = {}
        for obj in self.scene.objects:
            if obj.id not in state_map:
                continue
            parent_id = obj.parent_id if obj.parent_id in state_map else None
            children_map.setdefault(parent_id, []).append(obj.id)
        for child_ids in children_map.values():
            child_ids.sort(key=lambda oid: state_map[oid].get("draw_order", 0))
        identity_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        for root_id in children_map.get(None, []):
            self._draw_state_recursive(gc, state_map, children_map, root_id, identity_matrix)

        if self.selected_object_id:
            selected_item = next(
                (item for item in reversed(self._drawn_objects) if item["object_id"] == self.selected_object_id),
                None,
            )
            if selected_item:
                rect = selected_item["screen_rect"]
                gc.SetBrush(wx.TRANSPARENT_BRUSH)
                gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), width=1, style=wx.PENSTYLE_SHORT_DASH))
                gc.DrawRectangle(rect.x, rect.y, rect.width, rect.height)

    def on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        if event.AltDown() or event.ControlDown():
            self.on_pan_start(event)
            return
        handle_hit = self._hit_test_path_handle(event.GetPosition())
        if handle_hit:
            object_id = str(handle_hit["object_id"])
            key_id = str(handle_hit["key_id"])
            handle_kind = str(handle_hit["handle_kind"])
            self.selected_object_id = object_id
            self.selected_key_id = key_id
            if self.on_select_key:
                self.on_select_key(object_id, key_id)
            self._drag_object_id = None
            self._drag_start_world = None
            self._drag_key_object_id = None
            self._drag_key_id = None
            self._drag_key_start_world = None
            self._drag_handle_object_id = object_id
            self._drag_handle_key_id = key_id
            self._drag_handle_kind = handle_kind
            self._drag_handle_parent_matrix = handle_hit["parent_matrix"]
            self._drag_handle_start_world = self.screen_to_world(event.GetPosition())
            if self.on_begin_drag_key_handle:
                local_pos = handle_hit["local_pos"]
                self.on_begin_drag_key_handle(
                    object_id, key_id, handle_kind, float(local_pos[0]), float(local_pos[1])
                )
            if not self.HasCapture():
                self.CaptureMouse()
            event.Skip()
            return
        key_hit = self._hit_test_key_marker(event.GetPosition())
        if key_hit:
            object_id = str(key_hit["object_id"])
            key_id = str(key_hit["key_id"])
            self.selected_object_id = object_id
            self.selected_key_id = key_id
            if self.on_select_key:
                self.on_select_key(object_id, key_id)
            self._drag_object_id = None
            self._drag_start_world = None
            self._drag_key_object_id = object_id
            self._drag_key_id = key_id
            self._drag_key_parent_matrix = key_hit["parent_matrix"]
            self._drag_key_start_world = self.screen_to_world(event.GetPosition())
            self._drag_handle_object_id = None
            self._drag_handle_key_id = None
            self._drag_handle_kind = None
            self._drag_handle_start_world = None
            if self.on_begin_drag_keyframe:
                self.on_begin_drag_keyframe(object_id, key_id)
            if not self.HasCapture():
                self.CaptureMouse()
            event.Skip()
            return
        hit = self._hit_test_object(event.GetPosition())
        if not hit:
            event.Skip()
            return
        object_id = str(hit["object_id"])
        self.selected_object_id = object_id
        if self.on_select_object:
            self.on_select_object(object_id)

        self._drag_key_object_id = None
        self._drag_key_id = None
        self._drag_key_start_world = None
        self._drag_handle_object_id = None
        self._drag_handle_key_id = None
        self._drag_handle_kind = None
        self._drag_handle_start_world = None
        self._drag_object_id = object_id
        self._drag_parent_matrix = hit["parent_matrix"]
        self._drag_start_world = self.screen_to_world(event.GetPosition())
        if self.on_begin_drag_object:
            self.on_begin_drag_object(object_id)
        if not self.HasCapture():
            self.CaptureMouse()
        event.Skip()

    def on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
            self.on_pan_end(event)
            return
        if self._drag_handle_object_id is not None:
            self._drag_handle_object_id = None
            self._drag_handle_key_id = None
            self._drag_handle_kind = None
            self._drag_handle_start_world = None
            if self.HasCapture():
                self.ReleaseMouse()
            event.Skip()
            return
        if self._drag_key_object_id is not None:
            self._drag_key_object_id = None
            self._drag_key_id = None
            self._drag_key_start_world = None
            if self.HasCapture():
                self.ReleaseMouse()
            event.Skip()
            return
        if self._drag_object_id is not None:
            self._drag_object_id = None
            self._drag_start_world = None
            if self.HasCapture():
                self.ReleaseMouse()
        event.Skip()

    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return
        if (
            event.Dragging()
            and event.LeftIsDown()
            and self._drag_handle_object_id
            and self._drag_handle_key_id
            and self._drag_handle_kind
            and self._drag_handle_start_world
        ):
            curr_world = self.screen_to_world(event.GetPosition())
            dx_world = curr_world[0] - self._drag_handle_start_world[0]
            dy_world = curr_world[1] - self._drag_handle_start_world[1]

            ap, bp, cp, dp, _txp, _typ = self._drag_handle_parent_matrix
            det = ap * dp - bp * cp
            if abs(det) > 1e-6:
                dx_local = (dp * dx_world - cp * dy_world) / det
                dy_local = (-bp * dx_world + ap * dy_world) / det
            else:
                dx_local = dx_world
                dy_local = dy_world
            if self.on_drag_key_handle:
                self.on_drag_key_handle(
                    self._drag_handle_object_id,
                    self._drag_handle_key_id,
                    self._drag_handle_kind,
                    dx_local,
                    dy_local,
                )
            event.Skip()
            return
        if (
            event.Dragging()
            and event.LeftIsDown()
            and self._drag_key_object_id
            and self._drag_key_id
            and self._drag_key_start_world
        ):
            curr_world = self.screen_to_world(event.GetPosition())
            dx_world = curr_world[0] - self._drag_key_start_world[0]
            dy_world = curr_world[1] - self._drag_key_start_world[1]

            ap, bp, cp, dp, _txp, _typ = self._drag_key_parent_matrix
            det = ap * dp - bp * cp
            if abs(det) > 1e-6:
                dx_local = (dp * dx_world - cp * dy_world) / det
                dy_local = (-bp * dx_world + ap * dy_world) / det
            else:
                dx_local = dx_world
                dy_local = dy_world
            if self.on_drag_keyframe:
                self.on_drag_keyframe(self._drag_key_object_id, self._drag_key_id, dx_local, dy_local)
            event.Skip()
            return
        if not event.Dragging() or not event.LeftIsDown() or not self._drag_object_id or not self._drag_start_world:
            event.Skip()
            return

        curr_world = self.screen_to_world(event.GetPosition())
        dx_world = curr_world[0] - self._drag_start_world[0]
        dy_world = curr_world[1] - self._drag_start_world[1]

        ap, bp, cp, dp, _txp, _typ = self._drag_parent_matrix
        det = ap * dp - bp * cp
        if abs(det) > 1e-6:
            dx_local = (dp * dx_world - cp * dy_world) / det
            dy_local = (-bp * dx_world + ap * dy_world) / det
        else:
            dx_local = dx_world
            dy_local = dy_world

        if self.on_drag_object:
            self.on_drag_object(self._drag_object_id, dx_local, dy_local)
        event.Skip()

    def on_right_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        hit = self._hit_test_object(event.GetPosition())
        if not hit:
            event.Skip()
            return
        object_id = str(hit["object_id"])
        self.selected_object_id = object_id
        if self.on_select_object:
            self.on_select_object(object_id)

        menu = wx.Menu()
        item_flip_x = menu.Append(wx.ID_ANY, "Flip Horizontal")
        item_flip_y = menu.Append(wx.ID_ANY, "Flip Vertical")
        menu.AppendSeparator()
        item_rot_cw = menu.Append(wx.ID_ANY, "Rotate 90 CW")
        item_rot_ccw = menu.Append(wx.ID_ANY, "Rotate 90 CCW")

        menu.Bind(wx.EVT_MENU, lambda _e, oid=object_id: self.on_flip_object_x and self.on_flip_object_x(oid), item_flip_x)
        menu.Bind(wx.EVT_MENU, lambda _e, oid=object_id: self.on_flip_object_y and self.on_flip_object_y(oid), item_flip_y)
        menu.Bind(wx.EVT_MENU, lambda _e, oid=object_id: self.on_rotate_object_90_cw and self.on_rotate_object_90_cw(oid), item_rot_cw)
        menu.Bind(wx.EVT_MENU, lambda _e, oid=object_id: self.on_rotate_object_90_ccw and self.on_rotate_object_90_ccw(oid), item_rot_ccw)

        self.PopupMenu(menu, event.GetPosition())
        menu.Destroy()

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.AltDown() or event.ControlDown() or event.CmdDown():
            event.Skip()
            return
        if not self.selected_object_id:
            event.Skip()
            return

        keycode = event.GetKeyCode()
        if keycode in (ord("H"), ord("h")):
            if self.on_flip_object_x:
                self.on_flip_object_x(self.selected_object_id)
            return
        if keycode in (ord("V"), ord("v")):
            if self.on_flip_object_y:
                self.on_flip_object_y(self.selected_object_id)
            return
        if keycode in (ord("R"), ord("r")):
            if event.ShiftDown():
                if self.on_rotate_object_90_ccw:
                    self.on_rotate_object_90_ccw(self.selected_object_id)
            else:
                if self.on_rotate_object_90_cw:
                    self.on_rotate_object_90_cw(self.selected_object_id)
            return

        event.Skip()


class TimelineDopesheet(wx.ScrolledWindow):
    """Compact object-track dopesheet for timeline scenes."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.BORDER_SUNKEN | wx.WANTS_CHARS)
        self.scene: Optional[TimelineScene] = None
        self.rows: List[Tuple[TimelineObject, int, bool]] = []
        self.current_time: float = 0.0
        self.selected_object_id: Optional[str] = None
        self.selected_key_id: Optional[str] = None
        self.on_seek: Optional[Callable[[float], None]] = None
        self.on_select_key: Optional[Callable[[Optional[str], Optional[str]], None]] = None
        self.on_select_object: Optional[Callable[[Optional[str]], None]] = None
        self.on_toggle_object: Optional[Callable[[str], None]] = None
        self.on_reparent_object: Optional[Callable[[str, Optional[str]], None]] = None

        self.left_w = 260
        self.min_left_w = 160
        self.row_h = 24
        self.frame_w = 18
        self.header_h = 24
        self.scene_fps = 12
        self.duration_seconds = 10.0
        self.ruler_mode = RULER_MODE_FRAMES
        self.snap_mode = SNAP_FRAMES
        self.custom_snap_step = 0.25
        self.scroll_x = 0.0
        self._collapsed_ids: set[str] = set()
        self._resizing_divider = False
        self._divider_hit_slop = 5
        self._dragging_playhead = False
        self._playhead_marker_half_w = 7
        self._playhead_marker_h = 8
        self._playhead_hit_slop = 5
        self._playhead_footer_h = 16
        self._drag_track_object_id: Optional[str] = None
        self._drag_track_start_pos: Optional[wx.Point] = None
        self._drag_track_active = False
        self._drag_target_parent_id: Optional[str] = None
        self._drag_target_row: Optional[int] = None
        self._drag_target_valid = False

        self.SetScrollRate(0, self.row_h)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mousewheel)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.on_capture_lost)
        self.Bind(wx.EVT_SIZE, lambda e: self.Refresh(False))

    def set_scene(self, scene: Optional[TimelineScene]) -> None:
        self.scene = scene
        self.selected_object_id = None
        self.selected_key_id = None
        self.scene_fps = scene.fps if scene else 12
        self.duration_seconds = scene.duration_seconds if scene else 10.0
        self._update_virtual_size()
        self.Refresh(False)

    def set_rows(self, rows: List[Tuple[TimelineObject, int, bool]], duration_seconds: float, scene_fps: int) -> None:
        self.rows = list(rows)
        self.duration_seconds = max(1.0 / float(max(1, scene_fps)), float(duration_seconds))
        self.scene_fps = max(1, int(scene_fps))
        self._update_virtual_size()
        self.Refresh(False)

    def set_current_time(self, time_value: float) -> None:
        self.current_time = max(0.0, float(time_value))
        self.Refresh(False)

    def set_selection(self, object_id: Optional[str], key_id: Optional[str]) -> None:
        self.selected_object_id = object_id
        self.selected_key_id = key_id
        self.Refresh(False)

    def set_collapsed_ids(self, collapsed_ids: set[str]) -> None:
        self._collapsed_ids = set(collapsed_ids)
        self.Refresh(False)

    def set_timeline_options(self, ruler_mode: str, snap_mode: str, custom_snap_step: float) -> None:
        self.ruler_mode = ruler_mode if ruler_mode in (RULER_MODE_TIME, RULER_MODE_FRAMES) else RULER_MODE_FRAMES
        self.snap_mode = snap_mode if snap_mode in (SNAP_FREE, SNAP_FRAMES, SNAP_TENTHS, SNAP_CUSTOM) else SNAP_FRAMES
        self.custom_snap_step = max(0.001, float(custom_snap_step))
        self.Refresh(False)

    def _frame_duration(self) -> float:
        return 1.0 / float(max(1, self.scene_fps))

    def _duration_frames(self) -> int:
        return max(1, int(round(float(self.duration_seconds) * float(max(1, self.scene_fps)))))

    def _update_virtual_size(self) -> None:
        rows = len(self.rows)
        width = self.left_w + self._duration_frames() * self.frame_w + 80
        height = self.header_h + rows * self.row_h + 20
        self.SetVirtualSize((width, height))

    def _time_x(self, time_value_seconds: float) -> int:
        frame_pos = float(time_value_seconds) * float(max(1, self.scene_fps))
        return int(round(frame_pos * self.frame_w))

    def _frame_index_x(self, frame_idx: int) -> int:
        return int(round(int(frame_idx) * self.frame_w))

    def _snap_time(self, raw_time: float) -> float:
        duration = float(self.duration_seconds)
        if self.snap_mode == SNAP_FREE:
            snapped = raw_time
        elif self.snap_mode == SNAP_FRAMES:
            snapped = round(raw_time * float(max(1, self.scene_fps))) / float(max(1, self.scene_fps))
        elif self.snap_mode == SNAP_TENTHS:
            snapped = round(raw_time * 10.0) / 10.0
        else:
            step = max(0.001, float(self.custom_snap_step))
            snapped = round(raw_time / step) * step
        return max(0.0, min(duration, snapped))

    def _time_from_x(self, x: int) -> float:
        raw_frames = (x - self.left_w + self.scroll_x) / float(self.frame_w)
        raw_time = raw_frames / float(max(1, self.scene_fps))
        return self._snap_time(raw_time)

    def _content_width(self) -> int:
        return self._duration_frames() * self.frame_w + 80

    def _max_scroll_x(self) -> float:
        viewport_w = max(1, self.GetClientSize().width - self.left_w)
        return max(0.0, float(self._content_width() - viewport_w))

    def _clamp_scroll_x(self) -> None:
        self.scroll_x = max(0.0, min(self.scroll_x, self._max_scroll_x()))

    def _disclosure_rect(self, row: int, depth: int) -> wx.Rect:
        y = self.header_h + row * self.row_h
        x = 8 + depth * 18
        return wx.Rect(x, y + (self.row_h - 12) // 2, 12, 12)

    def _divider_rect(self, header_y: int) -> wx.Rect:
        return wx.Rect(self.left_w - self._divider_hit_slop, header_y, self._divider_hit_slop * 2, self.header_h)

    def _divider_hit_test(self, pos: wx.Point) -> bool:
        return self._divider_rect(0).Contains(pos)

    def _set_left_width(self, width: int) -> None:
        client_w = max(self.min_left_w + 80, self.GetClientSize().width)
        max_left_w = max(self.min_left_w, client_w - 80)
        new_width = max(self.min_left_w, min(int(width), max_left_w))
        if new_width == self.left_w:
            return
        self.left_w = new_width
        self._update_virtual_size()
        self._clamp_scroll_x()
        self.Refresh(False)

    def _playhead_x(self) -> int:
        return int(round(self.left_w + self._time_x(self.current_time) - self.scroll_x))

    def _playhead_marker_positions(self) -> Tuple[int, int, int]:
        self._update_virtual_size()
        _total_w, total_h = self.GetVirtualSize()
        _view_x, view_y = self.GetViewStart()
        _ppu_x, ppu_y = self.GetScrollPixelsPerUnit()
        _client_w, client_h = self.GetClientSize()
        header_y = view_y * ppu_y
        top_y = header_y
        visible_bottom = header_y + max(self.header_h, client_h)
        footer_top = max(header_y + self.header_h + 1, visible_bottom - self._playhead_footer_h)
        bottom_y = min(total_h, footer_top + (self._playhead_footer_h // 2))
        return (self._playhead_x(), top_y, bottom_y)

    def _is_over_playhead_marker(self, pos: wx.Point) -> bool:
        x, y = self.CalcUnscrolledPosition(pos)
        playhead_x, top_y, bottom_y = self._playhead_marker_positions()
        if x < self.left_w - (self._playhead_marker_half_w + self._playhead_hit_slop):
            return False
        near_x = abs(x - playhead_x) <= (self._playhead_marker_half_w + self._playhead_hit_slop)
        if not near_x:
            return False
        near_top = abs(y - top_y) <= (self._playhead_marker_h + self._playhead_hit_slop)
        near_bottom = abs(y - bottom_y) <= (self._playhead_marker_h + self._playhead_hit_slop)
        return near_top or near_bottom

    def _update_cursor(self, pos: wx.Point) -> None:
        if self._resizing_divider or self._divider_hit_test(pos):
            self.SetCursor(wx.Cursor(wx.CURSOR_SIZEWE))
        elif self._dragging_playhead or self._is_over_playhead_marker(pos):
            self.SetCursor(wx.Cursor(wx.CURSOR_SIZEWE))
        else:
            self.SetCursor(wx.NullCursor)

    def _tick_kind(self, frame_idx: int) -> str:
        if self.ruler_mode == RULER_MODE_TIME:
            frames_per_second = max(1, self.scene_fps)
            if frame_idx % frames_per_second == 0:
                return "major"
            if frames_per_second > 1:
                half_second = max(1, int(round(frames_per_second / 2.0)))
                if frame_idx % half_second == 0:
                    return "medium"
        else:
            if frame_idx % 10 == 0:
                return "major"
            if frame_idx % 5 == 0:
                return "medium"
        return "minor"

    def _tick_label(self, frame_idx: int) -> str:
        if self.ruler_mode == RULER_MODE_TIME:
            seconds = float(frame_idx) / float(max(1, self.scene_fps))
            if abs(seconds - round(seconds)) < 1e-6:
                return str(int(round(seconds)))
            return f"{seconds:.1f}"
        return str(frame_idx)

    def _reparent_target_from_pos(self, pos: wx.Point, dragged_object_id: str) -> Tuple[bool, Optional[str], Optional[int]]:
        x, y = self.CalcUnscrolledPosition(pos)
        if x >= self.left_w:
            return (False, None, None)

        # Left gutter and areas outside rows represent root drop.
        if x <= 16:
            return (True, None, None)
        row = -1 if y < self.header_h else (y - self.header_h) // self.row_h
        if row < 0 or row >= len(self.rows):
            return (True, None, None)
        target_obj = self.rows[row][0]
        if target_obj.id == dragged_object_id:
            return (False, None, row)
        return (True, target_obj.id, row)

    def _hit_test(self, pos: wx.Point) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        x, y = self.CalcUnscrolledPosition(pos)
        if y < self.header_h:
            return (None, None, self._time_from_x(x))
        row = (y - self.header_h) // self.row_h
        if row < 0 or row >= len(self.rows):
            return (None, None, None)
        obj = self.rows[row][0]
        for key in obj.sorted_keyframes():
            key_x = self.left_w + self._time_x(key.time) - self.scroll_x
            key_y = self.header_h + row * self.row_h + self.row_h // 2
            if abs(x - key_x) <= 8 and abs(y - key_y) <= 8:
                return (obj.id, key.id, key.time)
        return (obj.id, None, self._time_from_x(x))

    def on_mousewheel(self, event: wx.MouseEvent) -> None:
        if event.ShiftDown():
            self.scroll_x -= (event.GetWheelRotation() / 120.0) * 72.0
            self._clamp_scroll_x()
            self.Refresh(False)
            return
        event.Skip()

    def on_left_down(self, event: wx.MouseEvent) -> None:
        self._drag_track_object_id = None
        self._drag_track_start_pos = None
        self._drag_track_active = False
        self._drag_target_parent_id = None
        self._drag_target_row = None
        self._drag_target_valid = False
        if self._divider_hit_test(event.GetPosition()):
            self._resizing_divider = True
            if not self.HasCapture():
                self.CaptureMouse()
            self._update_cursor(event.GetPosition())
            return
        if self._is_over_playhead_marker(event.GetPosition()):
            self._dragging_playhead = True
            if not self.HasCapture():
                self.CaptureMouse()
            x, _y = self.CalcUnscrolledPosition(event.GetPosition())
            if self.on_seek:
                self.on_seek(self._time_from_x(x))
            self._update_cursor(event.GetPosition())
            return
        x, y = self.CalcUnscrolledPosition(event.GetPosition())
        row = -1 if y < self.header_h else (y - self.header_h) // self.row_h
        object_id, key_id, time_value = self._hit_test(event.GetPosition())
        if 0 <= row < len(self.rows):
            obj, depth, has_children = self.rows[row]
            if x < self.left_w:
                if has_children and self._disclosure_rect(row, depth).Contains(wx.Point(x, y)):
                    if self.on_toggle_object:
                        self.on_toggle_object(obj.id)
                    return
                self._drag_track_object_id = obj.id
                self._drag_track_start_pos = event.GetPosition()
                self._drag_track_active = False
                self._drag_target_parent_id = None
                self._drag_target_row = None
                self._drag_target_valid = False
                if self.on_select_object:
                    self.on_select_object(obj.id)
                if self.on_select_key:
                    self.on_select_key(obj.id, None)
                return
        if object_id and self.on_select_object:
            self.on_select_object(object_id)
        if self.on_select_key:
            self.on_select_key(object_id, key_id)
        if time_value is not None and self.on_seek:
            self.on_seek(time_value)

    def on_left_up(self, event: wx.MouseEvent) -> None:
        if self._drag_track_active:
            if self._drag_target_valid and self._drag_track_object_id and self.on_reparent_object:
                self.on_reparent_object(self._drag_track_object_id, self._drag_target_parent_id)
            self._drag_track_active = False
            self._drag_track_object_id = None
            self._drag_track_start_pos = None
            self._drag_target_parent_id = None
            self._drag_target_row = None
            self._drag_target_valid = False
            if self.HasCapture():
                self.ReleaseMouse()
            self._update_cursor(event.GetPosition())
            self.Refresh(False)
            event.Skip()
            return
        if self._drag_track_object_id:
            self._drag_track_object_id = None
            self._drag_track_start_pos = None
            self._drag_target_parent_id = None
            self._drag_target_row = None
            self._drag_target_valid = False
        if self._dragging_playhead:
            self._dragging_playhead = False
            if self.HasCapture():
                self.ReleaseMouse()
            self._update_cursor(event.GetPosition())
            event.Skip()
            return
        if self._resizing_divider:
            self._resizing_divider = False
            if self.HasCapture():
                self.ReleaseMouse()
        self._update_cursor(event.GetPosition())
        event.Skip()

    def on_motion(self, event: wx.MouseEvent) -> None:
        if (
            self._drag_track_object_id
            and self._drag_track_start_pos
            and event.LeftIsDown()
        ):
            if not self._drag_track_active:
                dx = abs(event.GetPosition().x - self._drag_track_start_pos.x)
                dy = abs(event.GetPosition().y - self._drag_track_start_pos.y)
                if dx + dy >= 4:
                    self._drag_track_active = True
                    if not self.HasCapture():
                        self.CaptureMouse()
            if self._drag_track_active:
                valid, parent_id, row = self._reparent_target_from_pos(
                    event.GetPosition(), self._drag_track_object_id
                )
                changed = (
                    valid != self._drag_target_valid
                    or parent_id != self._drag_target_parent_id
                    or row != self._drag_target_row
                )
                self._drag_target_valid = valid
                self._drag_target_parent_id = parent_id
                self._drag_target_row = row
                self._update_cursor(event.GetPosition())
                if changed:
                    self.Refresh(False)
                return
        if self._dragging_playhead:
            x, _y = self.CalcUnscrolledPosition(event.GetPosition())
            if self.on_seek:
                self.on_seek(self._time_from_x(x))
            self._update_cursor(event.GetPosition())
            return
        if self._resizing_divider:
            self._set_left_width(event.GetPosition().x)
            self._update_cursor(event.GetPosition())
            return
        self._update_cursor(event.GetPosition())
        event.Skip()

    def on_capture_lost(self, event: wx.MouseCaptureLostEvent) -> None:
        self._resizing_divider = False
        self._dragging_playhead = False
        self._drag_track_active = False
        self._drag_track_object_id = None
        self._drag_track_start_pos = None
        self._drag_target_parent_id = None
        self._drag_target_row = None
        self._drag_target_valid = False
        self.SetCursor(wx.NullCursor)
        event.Skip()

    def on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(wx.Colour(36, 36, 36)))
        dc.Clear()

        if not self.scene:
            dc.SetTextForeground(wx.Colour(180, 180, 180))
            dc.DrawText("No scene selected", 20, 20)
            return

        self._update_virtual_size()
        self._clamp_scroll_x()
        total_w, total_h = self.GetVirtualSize()
        _client_w, client_h = self.GetClientSize()
        _view_x, view_y = self.GetViewStart()
        _px_per_unit_x, px_per_unit_y = self.GetScrollPixelsPerUnit()
        visible = wx.Rect(0, view_y * px_per_unit_y, total_w, client_h)
        header_y = visible.y
        header_bottom = header_y + self.header_h

        for frame_idx in range(0, self._duration_frames() + 1):
            x = int(round(self.left_w + self._frame_index_x(frame_idx) - self.scroll_x))
            if x < self.left_w - self.frame_w or x > total_w + self.frame_w:
                continue
            tick_kind = self._tick_kind(frame_idx)
            if tick_kind == "major":
                color = wx.Colour(76, 96, 138)
            elif tick_kind == "medium":
                color = wx.Colour(62, 70, 88)
            else:
                color = wx.Colour(48, 52, 60)
            dc.SetPen(wx.Pen(color))
            dc.DrawLine(x, header_bottom, x, total_h)

        for row, (obj, depth, has_children) in enumerate(self.rows):
            y = self.header_h + row * self.row_h
            if y + self.row_h < header_bottom or y > visible.y + visible.height:
                continue
            bg = wx.Colour(44, 44, 44) if row % 2 == 0 else wx.Colour(39, 39, 39)
            if obj.id == self.selected_object_id:
                bg = wx.Colour(58, 78, 106)
            dc.SetBrush(wx.Brush(bg))
            dc.SetPen(wx.Pen(wx.Colour(50, 50, 50)))
            dc.DrawRectangle(0, y, self.left_w, self.row_h)
            dc.DrawRectangle(self.left_w, y, total_w - self.left_w, self.row_h)

            if has_children:
                rect = self._disclosure_rect(row, depth)
                mid_x = rect.x + rect.width // 2
                mid_y = rect.y + rect.height // 2
                dc.SetPen(wx.Pen(wx.Colour(210, 210, 210), 1))
                dc.DrawLine(rect.x + 2, mid_y, rect.x + rect.width - 2, mid_y)
                if obj.id in self._collapsed_ids:
                    dc.DrawLine(mid_x, rect.y + 2, mid_x, rect.y + rect.height - 2)

            text_x = 8 + depth * 18 + 18
            dc.SetTextForeground(wx.Colour(232, 232, 232))
            dc.DrawText(obj.name, text_x, y + 4)

            for key in obj.sorted_keyframes():
                key_x = int(round(self.left_w + self._time_x(key.time) - self.scroll_x))
                key_y = y + self.row_h // 2
                points = [
                    wx.Point(key_x, key_y - 6),
                    wx.Point(key_x + 6, key_y),
                    wx.Point(key_x, key_y + 6),
                    wx.Point(key_x - 6, key_y),
                ]
                fill = wx.Colour(255, 200, 80) if key.id == self.selected_key_id else wx.Colour(210, 210, 210)
                dc.SetBrush(wx.Brush(fill))
                dc.SetPen(wx.Pen(wx.Colour(20, 20, 20)))
                dc.DrawPolygon(points)

        if self._drag_track_active and self._drag_target_valid:
            dc.SetPen(wx.Pen(wx.Colour(140, 210, 255), 2))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            if self._drag_target_parent_id is None:
                dc.DrawRectangle(2, header_y + 1, max(10, self.left_w - 4), self.header_h - 2)
            elif self._drag_target_row is not None and 0 <= self._drag_target_row < len(self.rows):
                target_y = self.header_h + self._drag_target_row * self.row_h
                dc.DrawRectangle(2, target_y + 1, max(10, self.left_w - 4), self.row_h - 2)

        playhead_x = self._playhead_x()
        dc.SetPen(wx.Pen(wx.Colour(255, 92, 92), 2))
        footer_top = max(header_bottom, visible.y + visible.height - self._playhead_footer_h)
        dc.DrawLine(playhead_x, header_y, playhead_x, footer_top)
        marker_color = wx.Colour(255, 92, 92)
        dc.SetPen(wx.Pen(marker_color, 1))
        dc.SetBrush(wx.Brush(marker_color))
        top_marker_tip_y = header_y
        bottom_marker_tip_y = footer_top + (self._playhead_footer_h // 2)
        top_points = [
            wx.Point(playhead_x, top_marker_tip_y),
            wx.Point(playhead_x - self._playhead_marker_half_w, top_marker_tip_y - self._playhead_marker_h),
            wx.Point(playhead_x + self._playhead_marker_half_w, top_marker_tip_y - self._playhead_marker_h),
        ]
        dc.DrawPolygon(top_points)
        dc.SetPen(wx.Pen(wx.Colour(58, 58, 58), 1))
        dc.SetBrush(wx.Brush(wx.Colour(46, 46, 46)))
        dc.DrawRectangle(self.left_w, footer_top, max(0, total_w - self.left_w), self._playhead_footer_h)
        dc.SetPen(wx.Pen(marker_color, 1))
        dc.SetBrush(wx.Brush(marker_color))
        bottom_points = [
            wx.Point(playhead_x, bottom_marker_tip_y),
            wx.Point(playhead_x - self._playhead_marker_half_w, bottom_marker_tip_y + self._playhead_marker_h),
            wx.Point(playhead_x + self._playhead_marker_half_w, bottom_marker_tip_y + self._playhead_marker_h),
        ]
        dc.DrawPolygon(bottom_points)

        dc.SetPen(wx.Pen(wx.Colour(66, 66, 66)))
        dc.SetBrush(wx.Brush(wx.Colour(42, 42, 42)))
        dc.DrawRectangle(0, header_y, self.left_w, self.header_h)
        dc.DrawRectangle(self.left_w, header_y, total_w - self.left_w, self.header_h)
        dc.SetTextForeground(wx.Colour(180, 180, 180))
        dc.DrawText("Tracks", 8, header_y + 4)

        for frame_idx in range(0, self._duration_frames() + 1):
            x = int(round(self.left_w + self._frame_index_x(frame_idx) - self.scroll_x))
            if x < self.left_w - self.frame_w or x > total_w + self.frame_w:
                continue
            tick_kind = self._tick_kind(frame_idx)
            if tick_kind == "major":
                color = wx.Colour(124, 142, 184)
                tick_top = header_y + 2
            elif tick_kind == "medium":
                color = wx.Colour(88, 98, 120)
                tick_top = header_y + 8
            else:
                color = wx.Colour(74, 78, 88)
                tick_top = header_y + 13
            dc.SetPen(wx.Pen(color))
            dc.DrawLine(x, tick_top, x, header_bottom)
            if tick_kind == "major":
                dc.SetTextForeground(wx.Colour(206, 212, 226))
                dc.DrawText(self._tick_label(frame_idx), x + 3, header_y + 2)

        dc.SetPen(wx.Pen(wx.Colour(78, 78, 78), 1))
        dc.DrawLine(self.left_w, header_y, self.left_w, total_h)


class TimelineTrackList(wx.ScrolledWindow):
    """Custom hierarchical track list aligned to the dopesheet rows."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.BORDER_SUNKEN | wx.WANTS_CHARS)
        self.rows: List[Tuple[TimelineObject, int, bool]] = []
        self.selected_object_id: Optional[str] = None
        self.row_h = 24
        self.header_h = 24
        self.indent_w = 18
        self.disclosure_w = 12
        self.on_select_object: Optional[Callable[[str], None]] = None
        self.on_toggle_object: Optional[Callable[[str], None]] = None
        self.on_scroll_vertical: Optional[Callable[[int], None]] = None

        self.SetScrollRate(0, self.row_h)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_SCROLLWIN, self.on_scrollwin)
        self.Bind(wx.EVT_SIZE, self.on_size)

    def set_rows(self, rows: List[Tuple[TimelineObject, int, bool]]) -> None:
        self.rows = list(rows)
        self._update_virtual_size()
        self.Refresh(False)

    def set_selection(self, object_id: Optional[str]) -> None:
        self.selected_object_id = object_id
        self.Refresh(False)

    def set_collapsed_ids(self, collapsed_ids: set[str]) -> None:
        self._collapsed_ids = set(collapsed_ids)
        self.Refresh(False)

    def set_vertical_scroll(self, units: int) -> None:
        current_x, current_y = self.GetViewStart()
        if current_y != int(units):
            self.Scroll(current_x, int(units))

    def _update_virtual_size(self) -> None:
        width = max(220, self.GetClientSize().width)
        height = self.header_h + len(self.rows) * self.row_h + 20
        self.SetVirtualSize((width, height))

    def _row_at_y(self, y: int) -> int:
        if y < self.header_h:
            return -1
        return (y - self.header_h) // self.row_h

    def _disclosure_rect(self, row: int, depth: int) -> wx.Rect:
        y = self.header_h + row * self.row_h
        x = 8 + depth * self.indent_w
        return wx.Rect(x, y + (self.row_h - self.disclosure_w) // 2, self.disclosure_w, self.disclosure_w)

    def on_size(self, event: wx.SizeEvent) -> None:
        self._update_virtual_size()
        event.Skip()

    def on_scrollwin(self, event: wx.ScrollWinEvent) -> None:
        event.Skip()
        if self.on_scroll_vertical:
            wx.CallAfter(self.on_scroll_vertical, self.GetViewStart()[1])

    def on_left_down(self, event: wx.MouseEvent) -> None:
        x, y = self.CalcUnscrolledPosition(event.GetPosition())
        row = self._row_at_y(y)
        if row < 0 or row >= len(self.rows):
            return
        obj, depth, has_children = self.rows[row]
        if has_children and self._disclosure_rect(row, depth).Contains(wx.Point(x, y)):
            if self.on_toggle_object:
                self.on_toggle_object(obj.id)
            return
        if self.on_select_object:
            self.on_select_object(obj.id)

    def on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(wx.Colour(40, 40, 40)))
        dc.Clear()
        self._update_virtual_size()

        total_w, total_h = self.GetVirtualSize()
        client_w, client_h = self.GetClientSize()
        _view_x, view_y = self.GetViewStart()
        _ppu_x, ppu_y = self.GetScrollPixelsPerUnit()
        visible = wx.Rect(0, view_y * ppu_y, client_w, client_h)

        dc.SetPen(wx.Pen(wx.Colour(66, 66, 66)))
        dc.SetBrush(wx.Brush(wx.Colour(42, 42, 42)))
        dc.DrawRectangle(0, 0, total_w, self.header_h)
        dc.SetTextForeground(wx.Colour(180, 180, 180))
        dc.DrawText("Tracks", 8, 4)

        for row, (obj, depth, has_children) in enumerate(self.rows):
            y = self.header_h + row * self.row_h
            if y + self.row_h < visible.y or y > visible.y + visible.height:
                continue
            bg = wx.Colour(44, 44, 44) if row % 2 == 0 else wx.Colour(39, 39, 39)
            if obj.id == self.selected_object_id:
                bg = wx.Colour(58, 78, 106)
            dc.SetBrush(wx.Brush(bg))
            dc.SetPen(wx.Pen(wx.Colour(50, 50, 50)))
            dc.DrawRectangle(0, y, total_w, self.row_h)

            if has_children:
                rect = self._disclosure_rect(row, depth)
                mid_x = rect.x + rect.width // 2
                mid_y = rect.y + rect.height // 2
                dc.SetPen(wx.Pen(wx.Colour(210, 210, 210), 1))
                dc.StrokeLine(rect.x + 2, mid_y, rect.x + rect.width - 2, mid_y)
                if obj.id in getattr(self, "_collapsed_ids", set()):
                    dc.StrokeLine(mid_x, rect.y + 2, mid_x, rect.y + rect.height - 2)

            text_x = 8 + depth * self.indent_w + self.disclosure_w + 8
            dc.SetTextForeground(wx.Colour(232, 232, 232))
            dc.DrawText(obj.name, text_x, y + 4)


class TimelineEditorPanel(wx.Panel):
    """Scene-oriented timeline editor."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_scene_id: Optional[str] = None
        self.selected_object_id: Optional[str] = None
        self.selected_key_id: Optional[str] = None
        self.current_time: float = 0.0
        self.is_playing = False
        self.ui_updating = False
        self.ruler_mode = RULER_MODE_FRAMES
        self.snap_mode = SNAP_FRAMES
        self.custom_snap_step = 0.25
        self._canvas_drag_start: Optional[Tuple[str, str, float, float]] = None
        self._canvas_key_drag_start: Optional[Tuple[str, str, float, float]] = None
        self._canvas_key_handle_drag_start: Optional[Tuple[str, str, str, float, float]] = None
        self.timer = wx.Timer(self)
        self._source_choice_ids: List[Optional[str]] = []
        self._key_source_choice_ids: List[Optional[str]] = []
        self._parent_choice_ids: List[Optional[str]] = []
        self.collapsed_object_ids: set[str] = set()

        root = wx.BoxSizer(wx.VERTICAL)
        self.main_splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)

        self.left_panel = wx.Panel(self.main_splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        scene_box = wx.StaticBox(self.left_panel, label="Scenes")
        scene_sizer = wx.StaticBoxSizer(scene_box, wx.VERTICAL)
        self.scene_list = wx.ListCtrl(scene_box, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL)
        self.scene_list.InsertColumn(0, "Scene")
        scene_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add_scene = wx.Button(scene_box, label="Add")
        self.btn_del_scene = wx.Button(scene_box, label="Del")
        scene_btns.Add(self.btn_add_scene, 1, wx.RIGHT, 4)
        scene_btns.Add(self.btn_del_scene, 1)
        scene_sizer.Add(self.scene_list, 1, wx.EXPAND | wx.ALL, 4)
        scene_sizer.Add(scene_btns, 0, wx.EXPAND | wx.ALL, 4)

        palette_box = wx.StaticBox(self.left_panel, label="Source Palette")
        palette_sizer = wx.StaticBoxSizer(palette_box, wx.VERTICAL)
        self.palette_book = wx.Notebook(palette_box)
        self.module_palette = ModulePalette(self.palette_book, self.project)
        self.frame_palette = FramePalette(self.palette_book, self.project)
        self.animation_palette = AnimationPalette(self.palette_book, self.project)
        self.palette_book.AddPage(self.module_palette, "Modules")
        self.palette_book.AddPage(self.frame_palette, "Frames")
        self.palette_book.AddPage(self.animation_palette, "Animations")
        palette_sizer.Add(self.palette_book, 1, wx.EXPAND | wx.ALL, 4)

        left_sizer.Add(scene_sizer, 0, wx.EXPAND | wx.ALL, 4)
        left_sizer.Add(palette_sizer, 1, wx.EXPAND | wx.ALL, 4)
        self.left_panel.SetSizer(left_sizer)

        self.right_panel = wx.Panel(self.main_splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        self.top_splitter = wx.SplitterWindow(self.right_panel, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        self.canvas = TimelineCanvas(self.top_splitter, self.project)
        self.canvas.SetDropTarget(TimelineCanvasDropTarget(self))
        self.inspector_panel = wx.Panel(self.top_splitter)
        inspector_sizer = wx.BoxSizer(wx.VERTICAL)

        props_box = wx.StaticBox(self.inspector_panel, label="Object & Key")
        props_sizer = wx.StaticBoxSizer(props_box, wx.VERTICAL)
        self.object_name = wx.TextCtrl(props_box)
        self.parent_choice = wx.Choice(props_box)
        self.source_type_choice = wx.Choice(props_box, choices=["none", "module", "frame", "animation"])
        self.source_choice = wx.Choice(props_box)
        self.draw_order_spin = wx.SpinCtrl(props_box, min=0, max=9999, initial=0)
        self.playback_mode_choice = wx.Choice(props_box, choices=["loop", "once", "ping_pong"])
        self.path_mode_choice = wx.Choice(props_box, choices=list(TIMELINE_PATH_MODES))
        self.playback_speed = wx.SpinCtrlDouble(props_box, min=0.05, max=16.0, initial=1.0, inc=0.05)
        self.playback_offset = wx.SpinCtrlDouble(props_box, min=-9999.0, max=9999.0, initial=0.0, inc=0.1)
        self.chk_source_root = wx.CheckBox(props_box, label="Use Source Root Motion")
        self.key_time = wx.SpinCtrlDouble(props_box, min=0.0, max=9999.0, initial=0.0, inc=0.1)
        self.key_x = wx.SpinCtrlDouble(props_box, min=-4096.0, max=4096.0, initial=0.0, inc=1.0)
        self.key_y = wx.SpinCtrlDouble(props_box, min=-4096.0, max=4096.0, initial=0.0, inc=1.0)
        self.key_rot = wx.SpinCtrlDouble(props_box, min=-3600.0, max=3600.0, initial=0.0, inc=90.0)
        self.key_scale_x = wx.SpinCtrlDouble(props_box, min=-16.0, max=16.0, initial=1.0, inc=0.05)
        self.key_scale_y = wx.SpinCtrlDouble(props_box, min=-16.0, max=16.0, initial=1.0, inc=0.05)
        self.key_source_type_choice = wx.Choice(
            props_box, choices=[KEY_SOURCE_NO_CHANGE, "none", "module", "frame", "animation"]
        )
        self.key_source_choice = wx.Choice(props_box)
        self.key_source_offset_x = wx.SpinCtrlDouble(props_box, min=-4096.0, max=4096.0, initial=0.0, inc=1.0)
        self.key_source_offset_y = wx.SpinCtrlDouble(props_box, min=-4096.0, max=4096.0, initial=0.0, inc=1.0)
        self.key_easing = wx.Choice(props_box, choices=list(TIMELINE_EASINGS))
        self.key_path_in_x = wx.SpinCtrlDouble(props_box, min=-4096.0, max=4096.0, initial=0.0, inc=1.0)
        self.key_path_in_y = wx.SpinCtrlDouble(props_box, min=-4096.0, max=4096.0, initial=0.0, inc=1.0)
        self.key_path_out_x = wx.SpinCtrlDouble(props_box, min=-4096.0, max=4096.0, initial=0.0, inc=1.0)
        self.key_path_out_y = wx.SpinCtrlDouble(props_box, min=-4096.0, max=4096.0, initial=0.0, inc=1.0)
        self.chk_key_visible = wx.CheckBox(props_box, label="Visible")
        self.chk_key_flip_x = wx.CheckBox(props_box, label="Flip X")
        self.chk_key_flip_y = wx.CheckBox(props_box, label="Flip Y")
        self.btn_add_key = wx.Button(props_box, label="Add Key")
        self.btn_del_key = wx.Button(props_box, label="Delete Key")

        form = wx.FlexGridSizer(0, 2, 4, 6)
        form.AddGrowableCol(1, 1)
        rows = [
            ("Name", self.object_name),
            ("Parent", self.parent_choice),
            ("Source", self.source_type_choice),
            ("Asset", self.source_choice),
            ("Draw Order", self.draw_order_spin),
            ("Playback", self.playback_mode_choice),
            ("Path", self.path_mode_choice),
            ("Speed", self.playback_speed),
            ("Offset (s)", self.playback_offset),
            ("Key Time (s)", self.key_time),
            ("X", self.key_x),
            ("Y", self.key_y),
            ("Rotation", self.key_rot),
            ("Scale X", self.key_scale_x),
            ("Scale Y", self.key_scale_y),
            ("Key Source", self.key_source_type_choice),
            ("Key Asset", self.key_source_choice),
            ("Source Off X", self.key_source_offset_x),
            ("Source Off Y", self.key_source_offset_y),
            ("Easing", self.key_easing),
            ("Path In X", self.key_path_in_x),
            ("Path In Y", self.key_path_in_y),
            ("Path Out X", self.key_path_out_x),
            ("Path Out Y", self.key_path_out_y),
        ]
        for label, ctrl in rows:
            form.Add(wx.StaticText(props_box, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(ctrl, 1, wx.EXPAND)
        props_sizer.Add(form, 0, wx.EXPAND | wx.ALL, 4)
        flags = wx.BoxSizer(wx.HORIZONTAL)
        flags.Add(self.chk_source_root, 0, wx.RIGHT, 12)
        flags.Add(self.chk_key_visible, 0, wx.RIGHT, 12)
        flags.Add(self.chk_key_flip_x, 0, wx.RIGHT, 8)
        flags.Add(self.chk_key_flip_y, 0)
        props_sizer.Add(flags, 0, wx.ALL, 4)
        key_btns = wx.BoxSizer(wx.HORIZONTAL)
        key_btns.Add(self.btn_add_key, 1, wx.RIGHT, 4)
        key_btns.Add(self.btn_del_key, 1)
        props_sizer.Add(key_btns, 0, wx.EXPAND | wx.ALL, 4)

        inspector_sizer.Add(props_sizer, 1, wx.EXPAND | wx.ALL, 4)
        self.inspector_panel.SetSizer(inspector_sizer)

        self.top_splitter.SplitVertically(self.canvas, self.inspector_panel, 760)
        self.top_splitter.SetMinimumPaneSize(220)

        bottom_box = wx.StaticBox(self.right_panel, label="Timeline")
        bottom_sizer = wx.StaticBoxSizer(bottom_box, wx.VERTICAL)
        self.dopesheet = TimelineDopesheet(bottom_box)
        transport = wx.BoxSizer(wx.VERTICAL)
        transport_row_1 = wx.BoxSizer(wx.HORIZONTAL)
        transport_row_2 = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add_null = wx.Button(bottom_box, label="Null")
        self.btn_del_object = wx.Button(bottom_box, label="Delete")
        self.btn_prev = wx.Button(bottom_box, label="<")
        self.btn_play = wx.Button(bottom_box, label="Play")
        self.btn_stop = wx.Button(bottom_box, label="Stop")
        self.btn_next = wx.Button(bottom_box, label=">")
        self.current_time_spin = wx.SpinCtrlDouble(bottom_box, min=0.0, max=9999.0, initial=0.0, inc=0.1)
        self.scene_name = wx.TextCtrl(bottom_box)
        self.scene_fps = wx.SpinCtrl(bottom_box, min=1, max=120, initial=12)
        self.scene_duration = wx.SpinCtrlDouble(bottom_box, min=0.1, max=10000.0, initial=10.0, inc=0.1)
        self.ruler_mode_choice = wx.Choice(bottom_box, choices=[RULER_MODE_TIME, RULER_MODE_FRAMES])
        self.snap_mode_choice = wx.Choice(bottom_box, choices=[SNAP_FREE, SNAP_FRAMES, SNAP_TENTHS, SNAP_CUSTOM])
        self.custom_snap_spin = wx.SpinCtrlDouble(bottom_box, min=0.01, max=1000.0, initial=0.25, inc=0.01)
        self.scene_loop = wx.CheckBox(bottom_box, label="Loop")
        for ctrl, digits in (
            (self.playback_offset, 2),
            (self.key_time, 3),
            (self.current_time_spin, 3),
            (self.scene_duration, 3),
            (self.custom_snap_spin, 3),
        ):
            ctrl.SetDigits(digits)
        self.key_scale_x.Disable()
        self.key_scale_y.Disable()
        transport_row_1.Add(self.btn_add_null, 0, wx.RIGHT, 4)
        transport_row_1.Add(self.btn_del_object, 0, wx.RIGHT, 12)
        transport_row_1.Add(self.btn_prev, 0, wx.RIGHT, 4)
        transport_row_1.Add(self.btn_play, 0, wx.RIGHT, 4)
        transport_row_1.Add(self.btn_stop, 0, wx.RIGHT, 4)
        transport_row_1.Add(self.btn_next, 0, wx.RIGHT, 12)
        transport_row_1.Add(wx.StaticText(bottom_box, label="Time (s)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        transport_row_1.Add(self.current_time_spin, 0, wx.RIGHT, 12)
        transport_row_1.Add(wx.StaticText(bottom_box, label="Ruler"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        transport_row_1.Add(self.ruler_mode_choice, 0, wx.RIGHT, 12)
        transport_row_1.Add(wx.StaticText(bottom_box, label="Snap"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        transport_row_1.Add(self.snap_mode_choice, 0, wx.RIGHT, 8)
        transport_row_1.Add(self.custom_snap_spin, 0)

        transport_row_2.Add(wx.StaticText(bottom_box, label="Scene"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        transport_row_2.Add(self.scene_name, 1, wx.RIGHT, 12)
        transport_row_2.Add(wx.StaticText(bottom_box, label="FPS"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        transport_row_2.Add(self.scene_fps, 0, wx.RIGHT, 12)
        transport_row_2.Add(wx.StaticText(bottom_box, label="Length (s)"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        transport_row_2.Add(self.scene_duration, 0, wx.RIGHT, 12)
        transport_row_2.Add(self.scene_loop, 0, wx.ALIGN_CENTER_VERTICAL)

        transport.Add(transport_row_1, 0, wx.EXPAND | wx.BOTTOM, 4)
        transport.Add(transport_row_2, 0, wx.EXPAND)

        bottom_sizer.Add(self.dopesheet, 1, wx.EXPAND | wx.ALL, 4)
        bottom_sizer.Add(transport, 0, wx.EXPAND | wx.ALL, 4)

        right_sizer.Add(self.top_splitter, 1, wx.EXPAND | wx.ALL, 4)
        self.canvas_controls = CanvasDisplayControls(self.right_panel, self.canvas, show_transparency=True)
        right_sizer.Add(self.canvas_controls, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        right_sizer.Add(bottom_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self.right_panel.SetSizer(right_sizer)

        self.main_splitter.SplitVertically(self.left_panel, self.right_panel, 340)
        self.main_splitter.SetMinimumPaneSize(220)
        root.Add(self.main_splitter, 1, wx.EXPAND)
        self.SetSizer(root)

        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_scene, self.scene_list)
        self.Bind(wx.EVT_BUTTON, self.on_add_scene, self.btn_add_scene)
        self.Bind(wx.EVT_BUTTON, self.on_delete_scene, self.btn_del_scene)
        self.Bind(wx.EVT_BUTTON, self.on_add_null_object, self.btn_add_null)
        self.Bind(wx.EVT_BUTTON, self.on_delete_object, self.btn_del_object)
        self.Bind(wx.EVT_BUTTON, lambda e: self.seek_relative(-1.0), self.btn_prev)
        self.Bind(wx.EVT_BUTTON, lambda e: self.seek_relative(1.0), self.btn_next)
        self.Bind(wx.EVT_BUTTON, self.on_play, self.btn_play)
        self.Bind(wx.EVT_BUTTON, self.on_stop, self.btn_stop)
        self.Bind(wx.EVT_BUTTON, self.on_add_key, self.btn_add_key)
        self.Bind(wx.EVT_BUTTON, self.on_delete_key, self.btn_del_key)
        self.scene_list.Bind(wx.EVT_SIZE, self.on_scene_list_size)

        self.frame_palette.on_frame_double_click = lambda frame_id: self.add_object_from_palette("frame", frame_id)
        self.animation_palette.on_animation_double_click = lambda anim_id: self.add_object_from_palette("animation", anim_id)
        self.module_palette.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_module_palette_activated)

        self.dopesheet.on_seek = self.on_seek
        self.dopesheet.on_select_key = self.on_dopesheet_select_key
        self.dopesheet.on_select_object = self.on_dopesheet_select_object
        self.dopesheet.on_toggle_object = self.on_dopesheet_toggle_object
        self.dopesheet.on_reparent_object = self.on_dopesheet_reparent_object
        self.canvas.on_select_object = self.on_canvas_select_object
        self.canvas.on_select_key = self.on_canvas_select_key
        self.canvas.on_begin_drag_object = self.on_canvas_begin_drag_object
        self.canvas.on_drag_object = self.on_canvas_drag_object
        self.canvas.on_begin_drag_keyframe = self.on_canvas_begin_drag_keyframe
        self.canvas.on_drag_keyframe = self.on_canvas_drag_keyframe
        self.canvas.on_begin_drag_key_handle = self.on_canvas_begin_drag_key_handle
        self.canvas.on_drag_key_handle = self.on_canvas_drag_key_handle
        self.canvas.on_flip_object_x = self.on_canvas_flip_object_x
        self.canvas.on_flip_object_y = self.on_canvas_flip_object_y
        self.canvas.on_rotate_object_90_cw = self.on_canvas_rotate_object_90_cw
        self.canvas.on_rotate_object_90_ccw = self.on_canvas_rotate_object_90_ccw

        for ctrl in (
            self.object_name,
            self.parent_choice,
            self.source_type_choice,
            self.source_choice,
            self.draw_order_spin,
            self.playback_mode_choice,
            self.path_mode_choice,
            self.playback_speed,
            self.playback_offset,
            self.chk_source_root,
            self.key_time,
            self.key_x,
            self.key_y,
            self.key_rot,
            self.key_scale_x,
            self.key_scale_y,
            self.key_source_type_choice,
            self.key_source_choice,
            self.key_source_offset_x,
            self.key_source_offset_y,
            self.key_easing,
            self.key_path_in_x,
            self.key_path_in_y,
            self.key_path_out_x,
            self.key_path_out_y,
            self.chk_key_visible,
            self.chk_key_flip_x,
            self.chk_key_flip_y,
            self.current_time_spin,
            self.ruler_mode_choice,
            self.snap_mode_choice,
            self.custom_snap_spin,
            self.scene_name,
            self.scene_fps,
            self.scene_duration,
            self.scene_loop,
        ):
            self._bind_value_ctrl(ctrl)

        self.refresh_choices()
        self.refresh_scenes()

    def _bind_value_ctrl(self, ctrl: wx.Window) -> None:
        if isinstance(ctrl, wx.TextCtrl):
            ctrl.Bind(wx.EVT_TEXT, self.on_any_property_changed)
        elif isinstance(ctrl, wx.Choice):
            ctrl.Bind(wx.EVT_CHOICE, self.on_any_property_changed)
        elif isinstance(ctrl, wx.CheckBox):
            ctrl.Bind(wx.EVT_CHECKBOX, self.on_any_property_changed)
        elif isinstance(ctrl, wx.SpinCtrlDouble):
            ctrl.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_any_property_changed)
            ctrl.Bind(wx.EVT_KILL_FOCUS, self._on_spin_commit)
        elif isinstance(ctrl, wx.SpinCtrl):
            ctrl.Bind(wx.EVT_SPINCTRL, self.on_any_property_changed)
            ctrl.Bind(wx.EVT_KILL_FOCUS, self._on_spin_commit)

    def _on_spin_commit(self, event: wx.FocusEvent) -> None:
        self.on_any_property_changed(event)

    def _update_selected_scene_label(self) -> None:
        scene = self.get_selected_scene()
        if not scene:
            return
        for idx, candidate in enumerate(self.project.timeline_scenes):
            if candidate.id == scene.id:
                self.scene_list.SetItem(idx, 0, scene.name)
                break

    def on_scene_list_size(self, event: wx.SizeEvent) -> None:
        width = self.scene_list.GetClientSize().width
        if width > 0:
            self.scene_list.SetColumnWidth(0, width)
        event.Skip()

    def _scene_frame_step(self, scene: Optional[TimelineScene] = None) -> float:
        target_scene = scene or self.get_selected_scene()
        fps = target_scene.fps if target_scene else 12
        return 1.0 / float(max(1, fps))

    def _apply_snap(self, time_value: float, scene: Optional[TimelineScene] = None) -> float:
        target_scene = scene or self.get_selected_scene()
        duration = target_scene.duration_seconds if target_scene else 10.0
        if self.snap_mode == SNAP_FREE:
            snapped = float(time_value)
        elif self.snap_mode == SNAP_FRAMES:
            step = self._scene_frame_step(target_scene)
            snapped = round(float(time_value) / step) * step
        elif self.snap_mode == SNAP_TENTHS:
            snapped = round(float(time_value) * 10.0) / 10.0
        else:
            step = max(0.001, float(self.custom_snap_step))
            snapped = round(float(time_value) / step) * step
        return max(0.0, min(float(duration), snapped))

    def _update_snap_ui(self) -> None:
        self.custom_snap_spin.Enable(self.snap_mode == SNAP_CUSTOM)

    def _update_path_handle_ui_enabled(self) -> None:
        obj = self.get_selected_object()
        enabled = bool(obj) and (obj.path_mode or "linear") == "spline"
        for ctrl in (
            self.key_path_in_x,
            self.key_path_in_y,
            self.key_path_out_x,
            self.key_path_out_y,
        ):
            ctrl.Enable(enabled)

    def refresh_choices(self) -> None:
        self.module_palette.project = self.project
        self.module_palette.refresh_modules()
        self.frame_palette.project = self.project
        self.frame_palette.refresh_frames()
        self.animation_palette.project = self.project
        self.animation_palette.refresh_animations()

    def set_project(self, project: Project) -> None:
        self.project = project
        self.canvas.set_project(project)
        self.refresh_choices()
        self.selected_scene_id = None
        self.selected_object_id = None
        self.selected_key_id = None
        self.current_time = 0.0
        self.refresh_scenes()

    def get_selected_scene(self) -> Optional[TimelineScene]:
        if not self.selected_scene_id:
            return None
        return self.project.get_timeline_scene(self.selected_scene_id)

    def get_selected_object(self) -> Optional[TimelineObject]:
        scene = self.get_selected_scene()
        if not scene or not self.selected_object_id:
            return None
        return scene.get_object(self.selected_object_id)

    def get_selected_key(self) -> Optional[TimelineKeyframe]:
        obj = self.get_selected_object()
        if not obj or not self.selected_key_id:
            return None
        return next((key for key in obj.keyframes if key.id == self.selected_key_id), None)

    def _would_create_parent_cycle(
        self, scene: TimelineScene, object_id: str, parent_id: Optional[str]
    ) -> bool:
        current_id = parent_id
        visited: set[str] = set()
        while current_id:
            if current_id == object_id:
                return True
            if current_id in visited:
                return True
            visited.add(current_id)
            current_obj = scene.get_object(current_id)
            if not current_obj:
                return False
            current_id = current_obj.parent_id
        return False

    def _evaluate_state_map_at_time(
        self, scene: TimelineScene, time_value: float
    ) -> Dict[str, Dict[str, Any]]:
        state_map: Dict[str, Dict[str, Any]] = {}
        for obj in scene.objects:
            state = scene.evaluate_object_state(self.project, obj.id, time_value)
            if state is not None:
                state_map[obj.id] = state
        return state_map

    def _world_matrix_for_object(
        self,
        scene: TimelineScene,
        state_map: Dict[str, Dict[str, Any]],
        object_id: str,
        cache: Dict[str, Tuple[float, float, float, float, float, float]],
    ) -> Tuple[float, float, float, float, float, float]:
        if object_id in cache:
            return cache[object_id]
        state = state_map.get(object_id)
        if state is None:
            cache[object_id] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            return cache[object_id]
        local_matrix = self.canvas._build_local_matrix(state)
        obj = scene.get_object(object_id)
        parent_id = obj.parent_id if obj else None
        if parent_id and parent_id in state_map and scene.get_object(parent_id):
            parent_world = self._world_matrix_for_object(scene, state_map, parent_id, cache)
            world = self.canvas._compose_matrix(parent_world, local_matrix)
        else:
            world = local_matrix
        cache[object_id] = world
        return world

    @staticmethod
    def _invert_matrix(
        matrix: Tuple[float, float, float, float, float, float]
    ) -> Tuple[float, float, float, float, float, float]:
        a, b, c, d, tx, ty = matrix
        det = a * d - b * c
        if abs(det) <= 1e-8:
            return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        inv_det = 1.0 / det
        ai = d * inv_det
        bi = -b * inv_det
        ci = -c * inv_det
        di = a * inv_det
        txi = (c * ty - d * tx) * inv_det
        tyi = (b * tx - a * ty) * inv_det
        return (ai, bi, ci, di, txi, tyi)

    @staticmethod
    def _decompose_matrix_to_key(
        matrix: Tuple[float, float, float, float, float, float],
        flip_hint: Tuple[bool, bool] = (False, False),
    ) -> Tuple[Tuple[float, float], float, bool, bool]:
        a, b, c, d, tx, ty = matrix
        best: Optional[Tuple[float, bool, bool, float]] = None
        for flip_x in (False, True):
            for flip_y in (False, True):
                sx = -1.0 if flip_x else 1.0
                sy = -1.0 if flip_y else 1.0
                theta = math.atan2(b / sx, a / sx)
                ca = math.cos(theta)
                sa = math.sin(theta)
                ra = ca * sx
                rb = sa * sx
                rc = -sa * sy
                rd = ca * sy
                err = abs(ra - a) + abs(rb - b) + abs(rc - c) + abs(rd - d)
                if flip_x != flip_hint[0]:
                    err += 1e-5
                if flip_y != flip_hint[1]:
                    err += 1e-5
                if best is None or err < best[0]:
                    best = (err, flip_x, flip_y, theta)
        assert best is not None
        _err, flip_x, flip_y, theta = best
        return ((tx, ty), math.degrees(theta), flip_x, flip_y)

    def _reparent_object_preserve_world(
        self, scene: TimelineScene, obj: TimelineObject, new_parent_id: Optional[str]
    ) -> None:
        identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        obj_id = obj.id
        for key in obj.keyframes:
            t = float(key.time)
            state_map = self._evaluate_state_map_at_time(scene, t)
            if obj_id not in state_map:
                continue
            cache: Dict[str, Tuple[float, float, float, float, float, float]] = {}
            old_world = self._world_matrix_for_object(scene, state_map, obj_id, cache)
            if new_parent_id and new_parent_id in state_map:
                parent_world = self._world_matrix_for_object(scene, state_map, new_parent_id, cache)
            else:
                parent_world = identity
            parent_inv = self._invert_matrix(parent_world)
            desired_local = self.canvas._compose_matrix(parent_inv, old_world)
            state = state_map[obj_id]
            source_offset = state.get("source_offset", (0.0, 0.0))
            source_rotation = float(state.get("source_rotation", 0.0))
            source_flip_x = bool(state.get("source_flip_x", False))
            source_flip_y = bool(state.get("source_flip_y", False))
            local_flip_hint = (bool(state.get("flip_x", False)), bool(state.get("flip_y", False)))
            offset, rotation, local_flip_x, local_flip_y = self._decompose_matrix_to_key(
                desired_local, local_flip_hint
            )
            key.x = float(offset[0] - float(source_offset[0]))
            key.y = float(offset[1] - float(source_offset[1]))
            key.rotation_degrees = float(rotation - source_rotation)
            key.flip_x = bool(local_flip_x) ^ source_flip_x
            key.flip_y = bool(local_flip_y) ^ source_flip_y
        obj.parent_id = new_parent_id

    def _ensure_key_at_current_time(self, obj: TimelineObject) -> TimelineKeyframe:
        scene = self.get_selected_scene()
        for key in obj.keyframes:
            if abs(float(key.time) - float(self.current_time)) <= 1e-6:
                return key

        state = scene.evaluate_object_state(self.project, obj.id, self.current_time) if scene else None
        key = TimelineKeyframe(
            id=generate_id("tlk"),
            time=self.current_time,
            x=float(state["x"]) if state else 0.0,
            y=float(state["y"]) if state else 0.0,
            rotation_degrees=float(state["rotation_degrees"]) if state else 0.0,
            scale_x=1.0,
            scale_y=1.0,
            flip_x=bool(state["flip_x"]) if state else False,
            flip_y=bool(state["flip_y"]) if state else False,
            visible=bool(state["visible"]) if state else True,
            easing="linear",
            source_type=(
                str(state["source_type"])
                if state
                and state.get("source_type") in TIMELINE_SOURCE_TYPES
                and (
                    str(state.get("source_type")) != str(obj.source_type)
                    or (state.get("source_id") or None) != (obj.source_id or None)
                )
                else None
            ),
            source_id=(
                str(state["source_id"])
                if state
                and state.get("source_id") is not None
                and (
                    str(state.get("source_type")) != str(obj.source_type)
                    or (state.get("source_id") or None) != (obj.source_id or None)
                )
                else None
            ),
            source_offset=(
                tuple(float(v) for v in state.get("source_key_offset", (0.0, 0.0)))
                if state
                else (0.0, 0.0)
            ),
        )
        obj.keyframes.append(key)
        obj.keyframes.sort(key=lambda item: (item.time, item.id))
        return key

    def refresh_scenes(self, select_id: Optional[str] = None) -> None:
        self.scene_list.DeleteAllItems()
        target_idx = -1
        for idx, scene in enumerate(self.project.timeline_scenes):
            self.scene_list.InsertItem(idx, scene.name)
            if (select_id and scene.id == select_id) or (select_id is None and scene.id == self.selected_scene_id):
                target_idx = idx
        if target_idx >= 0:
            self.scene_list.Select(target_idx)
            self.scene_list.EnsureVisible(target_idx)
            self.select_scene(self.project.timeline_scenes[target_idx].id)
        elif self.project.timeline_scenes:
            self.scene_list.Select(0)
            self.select_scene(self.project.timeline_scenes[0].id)
        else:
            self.select_scene(None)

    def select_scene(self, scene_id: Optional[str]) -> None:
        self.selected_scene_id = scene_id
        scene = self.get_selected_scene()
        self.canvas.set_scene(scene)
        self.dopesheet.set_scene(scene)
        self.dopesheet.set_timeline_options(self.ruler_mode, self.snap_mode, self.custom_snap_step)
        valid_ids = {obj.id for obj in scene.objects} if scene else set()
        self.collapsed_object_ids = {obj_id for obj_id in self.collapsed_object_ids if obj_id in valid_ids}
        if scene:
            self.current_time = max(0.0, min(self.current_time, float(scene.duration_seconds)))
        else:
            self.current_time = 0.0
        if not scene or not scene.get_object(self.selected_object_id or ""):
            self.selected_object_id = scene.objects[0].id if scene and scene.objects else None
        obj = self.get_selected_object()
        if not obj or not any(key.id == self.selected_key_id for key in obj.keyframes):
            self.selected_key_id = obj.sorted_keyframes()[0].id if obj and obj.keyframes else None
        self.refresh_track_rows()
        self.refresh_parent_choices()
        self.refresh_source_choices()
        self.update_scene_ui()
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()

    def _build_visible_rows(self) -> List[Tuple[TimelineObject, int, bool]]:
        scene = self.get_selected_scene()
        if not scene:
            return []
        by_parent: Dict[Optional[str], List[TimelineObject]] = {}
        for obj in scene.objects:
            parent_id = obj.parent_id if scene.get_object(obj.parent_id or "") else None
            by_parent.setdefault(parent_id, []).append(obj)
        for objs in by_parent.values():
            objs.sort(key=lambda item: (item.draw_order, item.name.lower(), item.id))
        rows: List[Tuple[TimelineObject, int, bool]] = []

        def walk(parent_id: Optional[str], depth: int) -> None:
            for obj in by_parent.get(parent_id, []):
                has_children = len(by_parent.get(obj.id, [])) > 0
                rows.append((obj, depth, has_children))
                if obj.id not in self.collapsed_object_ids:
                    walk(obj.id, depth + 1)

        walk(None, 0)
        return rows

    def refresh_track_rows(self) -> None:
        scene = self.get_selected_scene()
        rows = self._build_visible_rows()
        self.dopesheet.set_collapsed_ids(self.collapsed_object_ids)
        self.dopesheet.set_timeline_options(self.ruler_mode, self.snap_mode, self.custom_snap_step)
        self.dopesheet.set_rows(rows, scene.duration_seconds if scene else 10.0, scene.fps if scene else 12)
        self.dopesheet.set_selection(self.selected_object_id, self.selected_key_id)

    def refresh_parent_choices(self) -> None:
        scene = self.get_selected_scene()
        self.parent_choice.Clear()
        self._parent_choice_ids = [None]
        self.parent_choice.Append("<root>")
        if scene:
            for obj in scene.objects:
                if obj.id == self.selected_object_id:
                    continue
                self._parent_choice_ids.append(obj.id)
                self.parent_choice.Append(obj.name)

    def refresh_source_choices(self) -> None:
        obj = self.get_selected_object()
        source_type = obj.source_type if obj else self.source_type_choice.GetStringSelection() or "none"
        self.source_choice.Clear()
        self._source_choice_ids = [None]
        self.source_choice.Append("<none>")
        if source_type == "module":
            for mod in self.project.modules:
                self._source_choice_ids.append(mod.id)
                self.source_choice.Append(mod.name)
        elif source_type == "frame":
            for frame in self.project.frames:
                self._source_choice_ids.append(frame.id)
                self.source_choice.Append(frame.name)
        elif source_type == "animation":
            for anim in self.project.animations:
                self._source_choice_ids.append(anim.id)
                self.source_choice.Append(anim.name)

    def refresh_key_source_choices(self, preferred_id: Optional[str] = None) -> None:
        selected_type = self.key_source_type_choice.GetStringSelection() or KEY_SOURCE_NO_CHANGE
        if preferred_id is None:
            preferred_id = self._selected_key_source_id()
        self.key_source_choice.Clear()
        self._key_source_choice_ids = [None]
        if selected_type == KEY_SOURCE_NO_CHANGE:
            self.key_source_choice.Append(KEY_SOURCE_NO_CHANGE)
            self.key_source_choice.SetSelection(0)
            self.key_source_choice.Enable(False)
            return

        self.key_source_choice.Enable(selected_type in ("module", "frame", "animation"))
        self.key_source_choice.Append("<none>")
        if selected_type == "module":
            for mod in self.project.modules:
                self._key_source_choice_ids.append(mod.id)
                self.key_source_choice.Append(mod.name)
        elif selected_type == "frame":
            for frame in self.project.frames:
                self._key_source_choice_ids.append(frame.id)
                self.key_source_choice.Append(frame.name)
        elif selected_type == "animation":
            for anim in self.project.animations:
                self._key_source_choice_ids.append(anim.id)
                self.key_source_choice.Append(anim.name)

        selected_index = 0
        for idx, candidate in enumerate(self._key_source_choice_ids):
            if candidate == preferred_id:
                selected_index = idx
                break
        self.key_source_choice.SetSelection(selected_index)

    def update_scene_ui(self) -> None:
        scene = self.get_selected_scene()
        self.ui_updating = True
        try:
            if not scene:
                self.scene_name.SetValue("")
                self.scene_fps.SetValue(12)
                self.scene_duration.SetValue(10.0)
                self.scene_loop.SetValue(True)
            else:
                self.scene_name.SetValue(scene.name)
                self.scene_fps.SetValue(scene.fps)
                self.scene_duration.SetValue(scene.duration_seconds)
                self.scene_loop.SetValue(scene.loop)
            self.ruler_mode_choice.SetStringSelection(self.ruler_mode)
            self.snap_mode_choice.SetStringSelection(self.snap_mode)
            self.custom_snap_spin.SetValue(self.custom_snap_step)
            self._update_snap_ui()
            self.current_time_spin.SetValue(self.current_time)
        finally:
            self.ui_updating = False

    def update_object_ui(self) -> None:
        obj = self.get_selected_object()
        self.ui_updating = True
        try:
            self.refresh_parent_choices()
            self.refresh_source_choices()
            if not obj:
                self.object_name.SetValue("")
                self.source_type_choice.SetSelection(0)
                self.source_choice.SetSelection(0)
                self.draw_order_spin.SetValue(0)
                self.playback_mode_choice.SetSelection(0)
                self.path_mode_choice.SetStringSelection("linear")
                self.playback_speed.SetValue(1.0)
                self.playback_offset.SetValue(0.0)
                self.chk_source_root.SetValue(False)
                self.parent_choice.SetSelection(0)
                self._update_path_handle_ui_enabled()
                return
            self.object_name.SetValue(obj.name)
            self.source_type_choice.SetStringSelection(obj.source_type)
            parent_idx = 0
            for idx, candidate in enumerate(self._parent_choice_ids):
                if candidate == obj.parent_id:
                    parent_idx = idx
                    break
            self.parent_choice.SetSelection(parent_idx)
            self.refresh_source_choices()
            source_idx = 0
            for idx, candidate in enumerate(self._source_choice_ids):
                if candidate == obj.source_id:
                    source_idx = idx
                    break
            self.source_choice.SetSelection(source_idx)
            self.draw_order_spin.SetValue(obj.draw_order)
            self.playback_mode_choice.SetStringSelection(obj.playback_mode)
            self.path_mode_choice.SetStringSelection(obj.path_mode or "linear")
            self.playback_speed.SetValue(obj.playback_speed)
            self.playback_offset.SetValue(obj.playback_offset)
            self.chk_source_root.SetValue(obj.use_source_root_motion)
            self._update_path_handle_ui_enabled()
        finally:
            self.ui_updating = False

    def update_key_ui(self) -> None:
        key = self.get_selected_key()
        self.ui_updating = True
        try:
            if not key:
                self.key_time.SetValue(self.current_time)
                self.key_x.SetValue(0.0)
                self.key_y.SetValue(0.0)
                self.key_rot.SetValue(0.0)
                self.key_scale_x.SetValue(1.0)
                self.key_scale_y.SetValue(1.0)
                self.key_source_type_choice.SetStringSelection(KEY_SOURCE_NO_CHANGE)
                self.refresh_key_source_choices(preferred_id=None)
                self.key_source_offset_x.SetValue(0.0)
                self.key_source_offset_y.SetValue(0.0)
                self.key_easing.SetStringSelection("linear")
                self.key_path_in_x.SetValue(0.0)
                self.key_path_in_y.SetValue(0.0)
                self.key_path_out_x.SetValue(0.0)
                self.key_path_out_y.SetValue(0.0)
                self.chk_key_visible.SetValue(True)
                self.chk_key_flip_x.SetValue(False)
                self.chk_key_flip_y.SetValue(False)
                return
            self.key_time.SetValue(key.time)
            self.key_x.SetValue(key.x)
            self.key_y.SetValue(key.y)
            self.key_rot.SetValue(key.rotation_degrees)
            self.key_scale_x.SetValue(key.scale_x)
            self.key_scale_y.SetValue(key.scale_y)
            key_source_type = key.source_type if key.source_type in TIMELINE_SOURCE_TYPES else KEY_SOURCE_NO_CHANGE
            self.key_source_type_choice.SetStringSelection(key_source_type)
            self.refresh_key_source_choices(preferred_id=key.source_id)
            self.key_source_offset_x.SetValue(float(key.source_offset[0]))
            self.key_source_offset_y.SetValue(float(key.source_offset[1]))
            self.key_easing.SetStringSelection(key.easing)
            self.key_path_in_x.SetValue(key.path_in[0] if key.path_in else key.x)
            self.key_path_in_y.SetValue(key.path_in[1] if key.path_in else key.y)
            self.key_path_out_x.SetValue(key.path_out[0] if key.path_out else key.x)
            self.key_path_out_y.SetValue(key.path_out[1] if key.path_out else key.y)
            self.chk_key_visible.SetValue(key.visible)
            self.chk_key_flip_x.SetValue(key.flip_x)
            self.chk_key_flip_y.SetValue(key.flip_y)
            self.current_time_spin.SetValue(self.current_time)
        finally:
            self.ui_updating = False
        self.dopesheet.set_selection(self.selected_object_id, self.selected_key_id)

    def sync_preview(self) -> None:
        scene = self.get_selected_scene()
        self.current_time_spin.SetValue(self.current_time)
        self.canvas.set_scene(scene)
        self.canvas.set_time(self.current_time)
        self.canvas.set_selected_object(self.selected_object_id)
        self.canvas.set_selected_key(self.selected_key_id)
        self.dopesheet.set_scene(scene)
        self.dopesheet.set_timeline_options(self.ruler_mode, self.snap_mode, self.custom_snap_step)
        self.refresh_track_rows()
        self.dopesheet.set_current_time(self.current_time)
        self.dopesheet.set_selection(self.selected_object_id, self.selected_key_id)

    def add_object_from_palette(self, source_type: str, source_id: str, drop_pos: Optional[wx.Point] = None) -> None:
        scene = self.get_selected_scene()
        if not scene:
            scene = self.project.create_timeline_scene("Scene 1")
            self.refresh_scenes(select_id=scene.id)
        name = source_id
        if source_type == "module":
            mod = self.project.get_module(source_id)
            name = mod.name if mod else "Module"
        elif source_type == "frame":
            frame = self.project.get_frame(source_id)
            name = frame.name if frame else "Frame"
        elif source_type == "animation":
            anim = self.project.get_animation(source_id)
            name = anim.name if anim else "Animation"
        obj = scene.create_object(name=name, source_type=source_type, source_id=source_id)
        state = scene.evaluate_object_state(self.project, obj.id, self.current_time)
        if state and obj.keyframes:
            obj.keyframes[0].time = self.current_time
        if drop_pos is not None and obj.keyframes:
            world_x, world_y = self.canvas.screen_to_world(drop_pos)
            obj.keyframes[0].x = float(world_x)
            obj.keyframes[0].y = float(world_y)
        self.selected_object_id = obj.id
        self.selected_key_id = obj.keyframes[0].id if obj.keyframes else None
        self.collapsed_object_ids.discard(obj.id)
        self.refresh_track_rows()
        self.refresh_parent_choices()
        self.refresh_source_choices()
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()

    def on_module_palette_activated(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.module_palette.module_ids):
            self.add_object_from_palette("module", self.module_palette.module_ids[idx])

    def on_add_scene(self, event: wx.CommandEvent) -> None:
        scene = self.project.create_timeline_scene(f"Scene {len(self.project.timeline_scenes) + 1}")
        self.refresh_scenes(select_id=scene.id)

    def on_delete_scene(self, event: wx.CommandEvent) -> None:
        if not self.selected_scene_id:
            return
        self.project.timeline_scenes = [
            scene for scene in self.project.timeline_scenes if scene.id != self.selected_scene_id
        ]
        self.selected_scene_id = None
        self.refresh_scenes()

    def on_select_scene(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.project.timeline_scenes):
            self.select_scene(self.project.timeline_scenes[idx].id)

    def on_dopesheet_toggle_object(self, object_id: str) -> None:
        if object_id in self.collapsed_object_ids:
            self.collapsed_object_ids.remove(object_id)
        else:
            self.collapsed_object_ids.add(object_id)
        self.refresh_track_rows()

    def on_dopesheet_reparent_object(self, object_id: str, parent_id: Optional[str]) -> None:
        scene = self.get_selected_scene()
        if not scene:
            return
        obj = scene.get_object(object_id)
        if not obj:
            return
        if parent_id == obj.id:
            return
        if parent_id and not scene.get_object(parent_id):
            parent_id = None
        if parent_id == obj.parent_id:
            return
        if self._would_create_parent_cycle(scene, obj.id, parent_id):
            return
        self._reparent_object_preserve_world(scene, obj, parent_id)
        self.selected_object_id = obj.id
        if self.selected_key_id and not any(k.id == self.selected_key_id for k in obj.keyframes):
            self.selected_key_id = obj.sorted_keyframes()[0].id if obj.keyframes else None
        self.refresh_track_rows()
        self.refresh_parent_choices()
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()

    def on_dopesheet_select_object(self, object_id: Optional[str]) -> None:
        if object_id:
            self.selected_object_id = object_id
            self._canvas_drag_start = None
            self._canvas_key_drag_start = None
            self._canvas_key_handle_drag_start = None
            self.refresh_track_rows()
            self.update_object_ui()
            self.sync_preview()

    def on_dopesheet_select_key(self, object_id: Optional[str], key_id: Optional[str]) -> None:
        if object_id:
            self.selected_object_id = object_id
        self.selected_key_id = key_id
        self._canvas_drag_start = None
        self._canvas_key_drag_start = None
        self._canvas_key_handle_drag_start = None
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()

    def on_canvas_select_object(self, object_id: str) -> None:
        self.selected_object_id = object_id
        self._canvas_drag_start = None
        self._canvas_key_drag_start = None
        self._canvas_key_handle_drag_start = None
        obj = self.get_selected_object()
        if obj and any(abs(float(key.time) - float(self.current_time)) <= 1e-6 for key in obj.keyframes):
            key = next(key for key in obj.keyframes if abs(float(key.time) - float(self.current_time)) <= 1e-6)
            self.selected_key_id = key.id
        else:
            self.selected_key_id = None
        self.refresh_track_rows()
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()

    def on_canvas_select_key(self, object_id: str, key_id: str) -> None:
        self.selected_object_id = object_id
        self.selected_key_id = key_id
        self._canvas_drag_start = None
        self._canvas_key_drag_start = None
        self._canvas_key_handle_drag_start = None
        self.refresh_track_rows()
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()

    def on_canvas_begin_drag_object(self, object_id: str) -> None:
        self.selected_object_id = object_id
        self._canvas_key_drag_start = None
        self._canvas_key_handle_drag_start = None
        obj = self.get_selected_object()
        if not obj:
            return
        key = self._ensure_key_at_current_time(obj)
        self.selected_key_id = key.id
        self._canvas_drag_start = (object_id, key.id, float(key.x), float(key.y))
        self.refresh_track_rows()
        self.update_object_ui()
        self.update_key_ui()

    def on_canvas_drag_object(self, object_id: str, dx_local: float, dy_local: float) -> None:
        if not self._canvas_drag_start or self._canvas_drag_start[0] != object_id:
            self.on_canvas_begin_drag_object(object_id)
        if not self._canvas_drag_start:
            return
        _oid, key_id, base_x, base_y = self._canvas_drag_start
        obj = self.get_selected_object()
        if not obj:
            return
        key = next((item for item in obj.keyframes if item.id == key_id), None)
        if not key:
            key = self._ensure_key_at_current_time(obj)
            self.selected_key_id = key.id
            self._canvas_drag_start = (object_id, key.id, float(key.x), float(key.y))
            base_x, base_y = float(key.x), float(key.y)
        key.x = float(base_x + dx_local)
        key.y = float(base_y + dy_local)
        self.update_key_ui()
        self.sync_preview()

    def on_canvas_begin_drag_keyframe(self, object_id: str, key_id: str) -> None:
        self.selected_object_id = object_id
        self.selected_key_id = key_id
        self._canvas_drag_start = None
        self._canvas_key_handle_drag_start = None
        obj = self.get_selected_object()
        if not obj:
            return
        key = next((item for item in obj.keyframes if item.id == key_id), None)
        if not key:
            return
        self._canvas_key_drag_start = (object_id, key_id, float(key.x), float(key.y))
        self.refresh_track_rows()
        self.update_object_ui()
        self.update_key_ui()

    def on_canvas_drag_keyframe(self, object_id: str, key_id: str, dx_local: float, dy_local: float) -> None:
        if not self._canvas_key_drag_start or self._canvas_key_drag_start[0] != object_id or self._canvas_key_drag_start[1] != key_id:
            self.on_canvas_begin_drag_keyframe(object_id, key_id)
        if not self._canvas_key_drag_start:
            return
        _oid, drag_key_id, base_x, base_y = self._canvas_key_drag_start
        obj = self.get_selected_object()
        if not obj:
            return
        key = next((item for item in obj.keyframes if item.id == drag_key_id), None)
        if not key:
            return
        key.x = float(base_x + dx_local)
        key.y = float(base_y + dy_local)
        self.update_key_ui()
        self.sync_preview()

    def on_canvas_begin_drag_key_handle(
        self, object_id: str, key_id: str, handle_kind: str, start_x: float, start_y: float
    ) -> None:
        self.selected_object_id = object_id
        self.selected_key_id = key_id
        self._canvas_drag_start = None
        self._canvas_key_drag_start = None
        obj = self.get_selected_object()
        if not obj:
            return
        if (obj.path_mode or "linear") != "spline":
            return
        key = next((item for item in obj.keyframes if item.id == key_id), None)
        if not key:
            return
        if handle_kind not in ("in", "out"):
            return
        self._canvas_key_handle_drag_start = (
            object_id,
            key_id,
            handle_kind,
            float(start_x),
            float(start_y),
        )
        self.refresh_track_rows()
        self.update_object_ui()
        self.update_key_ui()

    def on_canvas_drag_key_handle(
        self, object_id: str, key_id: str, handle_kind: str, dx_local: float, dy_local: float
    ) -> None:
        if handle_kind not in ("in", "out"):
            return
        obj = self.get_selected_object()
        if not obj:
            return
        if (obj.path_mode or "linear") != "spline":
            return
        if (
            not self._canvas_key_handle_drag_start
            or self._canvas_key_handle_drag_start[0] != object_id
            or self._canvas_key_handle_drag_start[1] != key_id
            or self._canvas_key_handle_drag_start[2] != handle_kind
        ):
            key = self.get_selected_key()
            if key is None:
                return
            fallback = key.path_in if handle_kind == "in" else key.path_out
            if fallback is None:
                fallback = (float(key.x), float(key.y))
            self.on_canvas_begin_drag_key_handle(
                object_id, key_id, handle_kind, float(fallback[0]), float(fallback[1])
            )
        if not self._canvas_key_handle_drag_start:
            return
        _oid, drag_key_id, drag_kind, base_x, base_y = self._canvas_key_handle_drag_start
        key = next((item for item in obj.keyframes if item.id == drag_key_id), None)
        if not key:
            return
        target = (float(base_x + dx_local), float(base_y + dy_local))
        is_default = abs(target[0] - float(key.x)) <= 1e-6 and abs(target[1] - float(key.y)) <= 1e-6
        if drag_kind == "in":
            key.path_in = None if is_default else target
        else:
            key.path_out = None if is_default else target
        self.update_key_ui()
        self.sync_preview()

    def _apply_canvas_transform(self, object_id: str, apply_fn: Callable[[TimelineKeyframe], None]) -> None:
        self.selected_object_id = object_id
        obj = self.get_selected_object()
        if not obj:
            return
        key = self._ensure_key_at_current_time(obj)
        self.selected_key_id = key.id
        apply_fn(key)
        self.update_key_ui()
        self.sync_preview()

    def on_canvas_flip_object_x(self, object_id: str) -> None:
        self._apply_canvas_transform(object_id, lambda key: setattr(key, "flip_x", not key.flip_x))

    def on_canvas_flip_object_y(self, object_id: str) -> None:
        self._apply_canvas_transform(object_id, lambda key: setattr(key, "flip_y", not key.flip_y))

    def on_canvas_rotate_object_90_cw(self, object_id: str) -> None:
        def apply(key: TimelineKeyframe) -> None:
            key.rotation_degrees = float((int(round(key.rotation_degrees / 90.0)) + 1) * 90)

        self._apply_canvas_transform(object_id, apply)

    def on_canvas_rotate_object_90_ccw(self, object_id: str) -> None:
        def apply(key: TimelineKeyframe) -> None:
            key.rotation_degrees = float((int(round(key.rotation_degrees / 90.0)) - 1) * 90)

        self._apply_canvas_transform(object_id, apply)

    def on_seek(self, time_value: float) -> None:
        scene = self.get_selected_scene()
        if not scene:
            return
        self.current_time = max(0.0, min(self._apply_snap(float(time_value), scene), float(scene.duration_seconds)))
        self.sync_preview()

    def seek_relative(self, delta: float) -> None:
        self.on_seek(self.current_time + float(delta) * self._scene_frame_step())

    def on_play(self, event: wx.CommandEvent) -> None:
        scene = self.get_selected_scene()
        if not scene:
            return
        self.is_playing = True
        self.timer.Start(max(16, int(round(1000.0 / max(1, scene.fps)))))

    def on_stop(self, event: wx.CommandEvent) -> None:
        self.is_playing = False
        self.timer.Stop()

    def on_timer(self, event: wx.TimerEvent) -> None:
        scene = self.get_selected_scene()
        if not scene:
            self.on_stop(wx.CommandEvent())
            return
        next_time = self.current_time + self._scene_frame_step(scene)
        if next_time > scene.duration_seconds:
            if scene.loop:
                next_time = 0.0
            else:
                next_time = float(scene.duration_seconds)
                self.on_stop(wx.CommandEvent())
        self.on_seek(next_time)

    def on_add_null_object(self, event: wx.CommandEvent) -> None:
        scene = self.get_selected_scene()
        if not scene:
            scene = self.project.create_timeline_scene("Scene 1")
            self.refresh_scenes(select_id=scene.id)
        obj = scene.create_object("Null", source_type="none", source_id=None)
        if obj.keyframes:
            obj.keyframes[0].time = self.current_time
        self.selected_object_id = obj.id
        self.selected_key_id = obj.keyframes[0].id if obj.keyframes else None
        self.collapsed_object_ids.discard(obj.id)
        self.refresh_track_rows()
        self.refresh_parent_choices()
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()

    def on_delete_object(self, event: wx.CommandEvent) -> None:
        scene = self.get_selected_scene()
        if not scene or not self.selected_object_id:
            return
        scene.delete_object(self.selected_object_id)
        self.selected_object_id = scene.objects[0].id if scene.objects else None
        obj = self.get_selected_object()
        self.selected_key_id = obj.sorted_keyframes()[0].id if obj and obj.keyframes else None
        self.refresh_track_rows()
        self.refresh_parent_choices()
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()

    def on_add_key(self, event: wx.CommandEvent) -> None:
        scene = self.get_selected_scene()
        obj = self.get_selected_object()
        if not scene or not obj:
            return
        state = scene.evaluate_object_state(self.project, obj.id, self.current_time)
        key = TimelineKeyframe(
            id=generate_id("tlk"),
            time=self.current_time,
            x=float(state["x"]) if state else 0.0,
            y=float(state["y"]) if state else 0.0,
            rotation_degrees=float(state["rotation_degrees"]) if state else 0.0,
            scale_x=1.0,
            scale_y=1.0,
            flip_x=bool(state["flip_x"]) if state else False,
            flip_y=bool(state["flip_y"]) if state else False,
            visible=bool(state["visible"]) if state else True,
            easing="linear",
            source_type=(
                str(state["source_type"])
                if state
                and state.get("source_type") in TIMELINE_SOURCE_TYPES
                and (
                    str(state.get("source_type")) != str(obj.source_type)
                    or (state.get("source_id") or None) != (obj.source_id or None)
                )
                else None
            ),
            source_id=(
                str(state["source_id"])
                if state
                and state.get("source_id") is not None
                and (
                    str(state.get("source_type")) != str(obj.source_type)
                    or (state.get("source_id") or None) != (obj.source_id or None)
                )
                else None
            ),
            source_offset=(
                tuple(float(v) for v in state.get("source_key_offset", (0.0, 0.0)))
                if state
                else (0.0, 0.0)
            ),
        )
        obj.keyframes.append(key)
        obj.keyframes.sort(key=lambda item: (item.time, item.id))
        self.selected_key_id = key.id
        self.update_key_ui()
        self.sync_preview()

    def on_delete_key(self, event: wx.CommandEvent) -> None:
        obj = self.get_selected_object()
        if not obj or not self.selected_key_id or len(obj.keyframes) <= 1:
            return
        obj.keyframes = [key for key in obj.keyframes if key.id != self.selected_key_id]
        self.selected_key_id = obj.sorted_keyframes()[0].id if obj.keyframes else None
        self.update_key_ui()
        self.sync_preview()

    def _selected_parent_id(self) -> Optional[str]:
        idx = self.parent_choice.GetSelection()
        if idx < 0 or idx >= len(self._parent_choice_ids):
            return None
        return self._parent_choice_ids[idx]

    def _selected_source_id(self) -> Optional[str]:
        idx = self.source_choice.GetSelection()
        if idx < 0 or idx >= len(self._source_choice_ids):
            return None
        return self._source_choice_ids[idx]

    def _selected_key_source_id(self) -> Optional[str]:
        idx = self.key_source_choice.GetSelection()
        if idx < 0 or idx >= len(self._key_source_choice_ids):
            return None
        return self._key_source_choice_ids[idx]

    def on_any_property_changed(self, event: wx.Event) -> None:
        if self.ui_updating:
            event.Skip()
            return

        scene = self.get_selected_scene()
        obj = self.get_selected_object()
        key = self.get_selected_key()

        if scene:
            scene.name = self.scene_name.GetValue().strip() or scene.name
            scene.fps = max(1, self.scene_fps.GetValue())
            scene.duration_seconds = max(1.0 / float(scene.fps), float(self.scene_duration.GetValue()))
            scene.loop = self.scene_loop.GetValue()
            self.current_time = min(self.current_time, float(scene.duration_seconds))

        self.ruler_mode = self.ruler_mode_choice.GetStringSelection() or RULER_MODE_FRAMES
        self.snap_mode = self.snap_mode_choice.GetStringSelection() or SNAP_FRAMES
        self.custom_snap_step = max(0.001, float(self.custom_snap_spin.GetValue()))
        self._update_snap_ui()

        if obj:
            obj.name = self.object_name.GetValue().strip() or obj.name
            source_type = self.source_type_choice.GetStringSelection() or "none"
            if source_type not in TIMELINE_SOURCE_TYPES:
                source_type = "none"
            if obj.source_type != source_type:
                obj.source_type = source_type
                self.refresh_source_choices()
            obj.source_id = self._selected_source_id()
            old_parent_id = obj.parent_id
            new_parent_id = self._selected_parent_id()
            if new_parent_id == obj.id:
                new_parent_id = None
            if scene and self._would_create_parent_cycle(scene, obj.id, new_parent_id):
                new_parent_id = old_parent_id
            if scene and new_parent_id != old_parent_id:
                self._reparent_object_preserve_world(scene, obj, new_parent_id)
            else:
                obj.parent_id = new_parent_id
            obj.draw_order = self.draw_order_spin.GetValue()
            obj.playback_mode = self.playback_mode_choice.GetStringSelection() or "loop"
            obj.path_mode = self.path_mode_choice.GetStringSelection() or "linear"
            if obj.path_mode not in TIMELINE_PATH_MODES:
                obj.path_mode = "linear"
            obj.playback_speed = float(self.playback_speed.GetValue())
            obj.playback_offset = float(self.playback_offset.GetValue())
            obj.use_source_root_motion = self.chk_source_root.GetValue()

        if key:
            if event.GetEventObject() is self.key_source_type_choice:
                self.refresh_key_source_choices(preferred_id=None)
            key.time = self._apply_snap(float(self.key_time.GetValue()), scene)
            key.x = float(self.key_x.GetValue())
            key.y = float(self.key_y.GetValue())
            key.rotation_degrees = float(int(round(float(self.key_rot.GetValue()) / 90.0)) * 90)
            key.scale_x = 1.0
            key.scale_y = 1.0
            key.flip_x = self.chk_key_flip_x.GetValue()
            key.flip_y = self.chk_key_flip_y.GetValue()
            key.visible = self.chk_key_visible.GetValue()
            key_source_type = self.key_source_type_choice.GetStringSelection() or KEY_SOURCE_NO_CHANGE
            if key_source_type == KEY_SOURCE_NO_CHANGE:
                key.source_type = None
                key.source_id = None
            else:
                if key_source_type not in TIMELINE_SOURCE_TYPES:
                    key_source_type = "none"
                key.source_type = key_source_type
                key.source_id = self._selected_key_source_id()
            key.source_offset = (
                float(self.key_source_offset_x.GetValue()),
                float(self.key_source_offset_y.GetValue()),
            )
            key.easing = self.key_easing.GetStringSelection() or "linear"
            path_in = (float(self.key_path_in_x.GetValue()), float(self.key_path_in_y.GetValue()))
            path_out = (float(self.key_path_out_x.GetValue()), float(self.key_path_out_y.GetValue()))
            key.path_in = None if path_in == (key.x, key.y) else path_in
            key.path_out = None if path_out == (key.x, key.y) else path_out
            if obj:
                obj.keyframes.sort(key=lambda item: (item.time, item.id))

        self.current_time = float(self.current_time_spin.GetValue())
        if scene:
            self.current_time = max(0.0, min(self._apply_snap(self.current_time, scene), float(scene.duration_seconds)))
            self._update_selected_scene_label()
        self.update_object_ui()
        self.update_key_ui()
        self.sync_preview()
        event.Skip()
