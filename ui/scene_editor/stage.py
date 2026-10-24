"""Stage: renders a timeline scene at the playhead and lets the user pick and drag objects."""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import wx

import consoles
from models import (
    FModule, ModuleMapping, PaletteSwap, Project, TimelineKeyframe, TimelineObject, TimelineScene, state_shows,
)
from hardware_budget import Budget, HwPart
from ui import first_steps
from ui.base_canvas import BACKDROP_COLOUR, DEFAULT_BACKDROP_COLOUR
from ui.canvas import BUDGET, FrameCanvas, whole_frames_shown
from ui.scene_editor import ops
from ui.dpi import px

# Retro screen guides from the console database: label -> (width, height), "None" first (format 7's preferences kept
# the position; the Timeline now keeps the label). The scene origin lies where the SGDK demo draws scenes
# (ops.screen_origin: centred, three quarters down).
SCREEN_GUIDES: List[Tuple[str, Optional[Tuple[int, int]]]] = [("None", None)] + list(consoles.screen_guides())


def project_screen(project: Any) -> Tuple[str, Tuple[int, int]]:
    """The screen of the project's console and setup, labelled like SCREEN_GUIDES ("SNES 256×224")."""
    console, setup = consoles.target(project.console, project.console_setup)
    width, height = consoles.target_screen(console, setup)
    return f"{console.short} {width}×{height}", (width, height)


class StageCanvas(FrameCanvas):
    """Scene preview with object picking, dragging and motion-path editing."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project)
        self.scene: Optional[TimelineScene] = None
        self.time_value: float = 0.0
        self.selected_object_id: Optional[str] = None
        self.selected_object_ids: Set[str] = set()  # every selected layer (selected_object_id among them)
        self.selected_key_ids: Set[str] = set()
        self.hidden_ids: Set[str] = set()
        self.locked_ids: Set[str] = set()
        self.screen_guide: Optional[Tuple[int, int]] = None
        self.zoom = 4.0
        self.max_zoom = 24.0
        self.backdrop = BACKDROP_COLOUR  # the scene's background colour; the view bar can pick the checkerboard
        self.show_collision = False
        self.show_points = False

        # Callbacks (set by the panel)
        self.on_select: Optional[Callable[[Optional[str]], None]] = None
        self.on_select_objects: Optional[Callable[[List[str], Optional[str]], None]] = None  # (ids, the one shown)
        self.on_drag_begin: Optional[Callable[[str], None]] = None
        self.on_drag: Optional[Callable[[str, float, float], None]] = None
        self.on_drag_end: Optional[Callable[[], None]] = None
        self.on_key_drag_begin: Optional[Callable[[str, str], None]] = None
        self.on_key_drag: Optional[Callable[[str, str, float, float], None]] = None
        self.on_handle_drag_begin: Optional[Callable[[str, str, str], None]] = None
        self.on_handle_drag: Optional[Callable[[str, str, str, float, float], None]] = None
        self.on_context_menu: Optional[Callable[[Optional[str], wx.Point], None]] = None

        self._drawn_objects: List[Dict[str, Any]] = []
        self._drawn_keys: List[Dict[str, Any]] = []
        self._drawn_handles: List[Dict[str, Any]] = []
        self._drag_kind: Optional[str] = None  # "object" | "key" | "handle" | "marquee"
        self._drag_ids: Tuple[str, ...] = ()
        self._drag_start_world: Optional[Tuple[float, float]] = None
        self._last_hit_cycle: Tuple[Optional[Tuple[int, int, Tuple[str, ...]]], int] = (None, -1)
        self._press_pos: Optional[wx.Point] = None
        self._moved = False
        self._only_on_click: Optional[str] = None  # a click (no drag) on a layer of a group selects it alone
        self._marquee: Optional[wx.Rect] = None
        self._marquee_base: List[str] = []

        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)

    # ------------------------------------------------------------------ state
    def set_project(self, project: Project) -> None:
        self.project = project
        self.clear_cache()

    def backdrop_fill_colour(self) -> Tuple[int, int, int]:
        if self.scene:
            r, g, b = self.scene.background_color[:3]
            return (int(r), int(g), int(b))
        return DEFAULT_BACKDROP_COLOUR

    def fit_to_content(self, margin_px: int = 12) -> None:
        # Tighter than the editors' default so small sprites land on the next zoom level.
        super().fit_to_content(margin_px)

    def set_view(
        self,
        scene: Optional[TimelineScene],
        time_value: float,
        selected_object_id: Optional[str],
        selected_key_ids: Set[str],
        hidden_ids: Set[str],
        locked_ids: Set[str],
        selected_object_ids: Optional[Set[str]] = None,
    ) -> None:
        self.scene = scene
        self.time_value = time_value
        self.selected_object_id = selected_object_id
        self.selected_object_ids = set(selected_object_ids or ()) | ({selected_object_id} if selected_object_id else set())
        self.selected_key_ids = set(selected_key_ids)
        self.hidden_ids = set(hidden_ids)
        self.locked_ids = set(locked_ids)
        self.Refresh(False)

    def get_content_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        rects = [item["screen_rect"] for item in self._drawn_objects]
        if self.screen_guide:
            left, top, right, bottom = ops.screen_rect(self.screen_guide)
            x0, y0 = self.world_to_screen((left, top))
            x1, y1 = self.world_to_screen((right, bottom))
            rects.append(wx.Rect(int(x0), int(y0), int(x1 - x0), int(y1 - y0)))
        if not rects:
            return None
        x0, y0 = self.screen_to_world(wx.Point(min(r.x for r in rects), min(r.y for r in rects)))
        x1, y1 = self.screen_to_world(wx.Point(max(r.x + r.width for r in rects), max(r.y + r.height for r in rects)))
        return (x0, y0, x1, y1)

    # ------------------------------------------------------------------ rendering helpers
    @staticmethod
    def _matrix_to_frame_transform(matrix: ops.Matrix) -> Tuple[Tuple[float, float], float, bool, bool]:
        a, b, c, d, tx, ty = matrix
        sx = math.hypot(a, b)
        sy = math.hypot(c, d)
        if sx <= 1e-6 or sy <= 1e-6:
            return ((tx, ty), 0.0, False, False)
        flip_y = (a / sx) * (d / sy) - (b / sx) * (c / sy) < 0.0
        rotation = math.degrees(math.atan2(b / sx, a / sx))
        # Sprites only rotate in 90° steps on screen (and on the target hardware).
        rotation = float(round(rotation / 90.0) * 90) % 360.0
        return ((tx, ty), rotation, False, flip_y)

    def _draw_source(self, gc: wx.GraphicsContext, state: Dict[str, Any], matrix: ops.Matrix) -> None:
        source_type = state.get("source_type")
        source_id = state.get("source_id")
        frame_id = state.get("frame_id") or source_id
        if source_type == "none" or not source_id and source_type == "module":
            return
        offset, rotation, flip_x, flip_y = self._matrix_to_frame_transform(matrix)
        if source_type == "module":
            temp = FModule(id="stage_module", ref_type="module", ref_id=str(source_id), position=(0, 0))
            with self.frame_transform(None, offset, flip_x, flip_y, rotation):
                self._draw_fmodule_content(gc, temp)
        elif frame_id:
            frame = self.project.get_frame(str(frame_id))
            if frame:
                with self.frame_transform(frame, offset, flip_x, flip_y, rotation):
                    for fm in frame.fmodules:
                        self._draw_fmodule_content(gc, fm)

    def _source_bounds(self, state: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
        source_type = state.get("source_type")
        source_id = state.get("source_id")
        frame_id = state.get("frame_id") or source_id
        if source_type == "module" and source_id:
            return self._fmodule_bounds(FModule(id="b", ref_type="module", ref_id=str(source_id), position=(0, 0)))
        if source_type in ("frame", "animation") and frame_id:
            frame = self.project.get_frame(str(frame_id))
            if not frame or not frame.fmodules:
                return None
            boxes = [self._fmodule_bounds(fm) for fm in frame.fmodules]
            return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        return None

    def _screen_rect(self, bounds: Tuple[float, float, float, float], matrix: ops.Matrix) -> wx.Rect:
        x0, y0, x1, y1 = bounds
        pts = [self.world_to_screen(ops.apply(matrix, x, y)) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        left = int(math.floor(min(p[0] for p in pts)))
        top = int(math.floor(min(p[1] for p in pts)))
        return wx.Rect(left, top, max(1, int(math.ceil(max(p[0] for p in pts))) - left), max(1, int(math.ceil(max(p[1] for p in pts))) - top))

    # ------------------------------------------------------------------ paint
    def on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.draw_backdrop(dc)
        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            return
        self._drawn_objects = []
        self._drawn_keys = []
        self._drawn_handles = []
        self._budget_hud = None
        self._draw_grid(gc)
        if not self.scene:
            gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), self.overlay_colour("canvas_faint"))
            gc.DrawText(first_steps.scenes(self.project) or "No scene yet: click + New in the Scenes list to make one.", px(20), px(20))
            return

        states = ops.evaluate_states(self.project, self.scene, self.time_value)
        cache: Dict[str, ops.Matrix] = {}
        self._part_rects = []
        self.colour_frame = self.time_value * 60.0  # colour cycles turn with the scene's time, in video frames
        for obj, _depth, _kids in ops.tree_rows(self.scene, set()):
            if obj.id not in states or self._is_hidden(obj):
                continue
            state = states[obj.id]
            if not state_shows(state):
                continue
            world = ops.world_matrix(self.scene, states, obj.id, cache)
            with self.drawing_mapping(self.object_mapping(obj.id)), self.drawing_palette_swap(self.object_swap(obj.id)):
                self._draw_source(gc, state, world)
                bounds = self._source_bounds(state)
            if bounds:
                self._drawn_objects.append(
                    {"object_id": obj.id, "screen_rect": self._screen_rect(bounds, world)}
                )
        if self.show_part_bounds:
            self._draw_part_bounds(gc)
        if self.budget_profile is not None:
            self._draw_budget(gc, self.compute_budget(states))

        self._draw_screen_guide(gc)
        self._draw_motion_path(gc, states)
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        for object_id in self.selected_object_ids:
            item = next((i for i in reversed(self._drawn_objects) if i["object_id"] == object_id), None)
            if item:
                r = item["screen_rect"]
                # The layer the inspector shows in white, the others selected with it in blue.
                colour = self.overlay_colour("canvas_line") if object_id == self.selected_object_id else wx.Colour(130, 190, 255)
                gc.SetPen(wx.Pen(colour, 1, wx.PENSTYLE_SHORT_DASH))
                gc.DrawRectangle(r.x, r.y, r.width, r.height)
        if self._marquee is not None:
            gc.SetPen(wx.Pen(wx.Colour(140, 200, 255), 1, wx.PENSTYLE_DOT))
            gc.SetBrush(wx.Brush(wx.Colour(140, 200, 255, 40)))
            gc.DrawRectangle(self._marquee.x, self._marquee.y, self._marquee.width, self._marquee.height)
        self._draw_budget_hud(gc)

    def compute_budget(self, states: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Budget]:
        """Hardware sprites of everything visible at the playhead (the limits are per screen and per line)."""
        if self.budget_profile is None or not self.scene:
            return None
        from ui.frame_render import transform

        if states is None:
            states = ops.evaluate_states(self.project, self.scene, self.time_value)
        cache: Dict[str, ops.Matrix] = {}
        parts: List[HwPart] = []
        whole = whole_frames_shown(self.project, self.budget_profile)
        for obj, _depth, _kids in ops.tree_rows(self.scene, set()):
            state = states.get(obj.id)
            if not state_shows(state) or self._is_hidden(obj):
                continue
            offset, rotation, flip_x, flip_y = self._matrix_to_frame_transform(ops.world_matrix(self.scene, states, obj.id, cache))
            a, b = transform(flip_x, flip_y, rotation, offset)
            source_type = state.get("source_type")
            source_id = state.get("source_id")
            frame_id = state.get("frame_id") or source_id
            mapping = self.object_mapping(obj.id)
            if source_type == "module" and source_id:
                parts += BUDGET.module_parts(self.project, str(source_id), mapping, self.budget_profile, a, b, whole)
            elif source_type in ("frame", "animation") and frame_id:
                frame = self.project.get_frame(str(frame_id))
                if frame:
                    parts += BUDGET.frame_parts(self.project, frame, mapping, self.budget_profile, a, b, whole)
        return Budget(self.budget_profile, parts)

    def object_mapping(self, object_id: str) -> Optional[ModuleMapping]:
        """The object's own mapping, else its parent's, else the preview mapping."""
        return self.scene.object_mapping(self.project, object_id, self.project.active_mapping) if self.scene else None

    def object_swap(self, object_id: str) -> Optional[PaletteSwap]:
        """The object's own palette swap, else its parent's, else the preview's."""
        if not self.scene:
            return None
        return self.scene.object_palette_swap(self.project, object_id, self.project.active_palette_swap)

    def _is_hidden(self, obj: TimelineObject) -> bool:
        current: Optional[TimelineObject] = obj
        seen: Set[str] = set()
        while current and current.id not in seen:
            if current.id in self.hidden_ids:
                return True
            seen.add(current.id)
            current = self.scene.get_object(current.parent_id) if current.parent_id else None
        return False

    def _draw_screen_guide(self, gc: wx.GraphicsContext) -> None:
        if not self.screen_guide:
            return
        w, h = self.screen_guide
        left, top, right, bottom = ops.screen_rect(self.screen_guide)
        x0, y0 = self.world_to_screen((left, top))
        x1, y1 = self.world_to_screen((right, bottom))
        cw, ch = self.GetClientSize()
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 130)))
        gc.DrawRectangle(0, 0, cw, max(0, y0))
        gc.DrawRectangle(0, y1, cw, max(0, ch - y1))
        gc.DrawRectangle(0, y0, max(0, x0), y1 - y0)
        gc.DrawRectangle(x1, y0, max(0, cw - x1), y1 - y0)
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(wx.Colour(255, 214, 102), 1))
        gc.DrawRectangle(x0, y0, x1 - x0, y1 - y0)
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(255, 214, 102))
        gc.DrawText(f"{w}×{h}", x0 + px(4), y0 - px(18) if y0 > px(20) else y0 + px(4))

    @staticmethod
    def _auto_handles(keys: List[TimelineKeyframe], index: int) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
        if len(keys) < 2:
            return (None, None)
        key = keys[index]
        kx, ky = float(key.x), float(key.y)
        if 0 < index < len(keys) - 1:
            tx = (float(keys[index + 1].x) - float(keys[index - 1].x)) / 6.0
            ty = (float(keys[index + 1].y) - float(keys[index - 1].y)) / 6.0
            return ((kx - tx, ky - ty), (kx + tx, ky + ty))
        if index == 0:
            nxt = keys[1]
            return (None, (kx + (float(nxt.x) - kx) / 3.0, ky + (float(nxt.y) - ky) / 3.0))
        prev = keys[-2]
        return ((kx - (kx - float(prev.x)) / 3.0, ky - (ky - float(prev.y)) / 3.0), None)

    def _draw_motion_path(self, gc: wx.GraphicsContext, states_now: Dict[str, Dict[str, Any]]) -> None:
        obj = self.scene.get_object(self.selected_object_id) if self.selected_object_id else None
        if not obj or self._is_hidden(obj):
            return
        keys = obj.sorted_keyframes()
        fps = self.scene.fps
        parent_cache: Dict[int, ops.Matrix] = {}

        def parent_at(frame: int) -> ops.Matrix:
            """Where the keys live at a frame: the parent's space (on its point when the object follows one)."""
            if frame not in parent_cache:
                parent_cache[frame] = (
                    ops.key_space_matrix(self.project, self.scene, obj, ops.time_of(frame, fps)) if obj.parent_id else ops.IDENTITY
                )
            return parent_cache[frame]

        if len(keys) >= 2:
            first = ops.frame_of(keys[0].time, fps)
            last = ops.frame_of(keys[-1].time, fps)
            points = []
            for frame in range(first, last + 1):
                state = self.scene.evaluate_object_state(self.project, obj.id, ops.time_of(frame, fps))
                if state:
                    points.append(self.world_to_screen(ops.apply(parent_at(frame), float(state["x"]), float(state["y"]))))
            if len(points) >= 2:
                gc.SetPen(wx.Pen(wx.Colour(110, 180, 255), 1))
                path = gc.CreatePath()
                path.MoveToPoint(*points[0])
                for p in points[1:]:
                    path.AddLineToPoint(*p)
                gc.StrokePath(path)
                # One dot per frame shows spacing (where the motion is fast or slow).
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.SetBrush(wx.Brush(wx.Colour(110, 180, 255, 160)))
                for qx, qy in points:
                    gc.DrawEllipse(qx - 1.5, qy - 1.5, 3, 3)

        # Selected keys last, so a key sitting on top of another one cannot hide the highlight.
        order = sorted(range(len(keys)), key=lambda i: keys[i].id in self.selected_key_ids)
        for index in order:
            key = keys[index]
            frame = ops.frame_of(key.time, fps)
            parent = parent_at(frame)
            sx, sy = self.world_to_screen(ops.apply(parent, float(key.x), float(key.y)))
            self._drawn_keys.append({"key_id": key.id, "screen_pos": (sx, sy)})
            selected = key.id in self.selected_key_ids
            gc.SetPen(wx.Pen(wx.Colour(255, 255, 255) if selected else wx.Colour(20, 20, 20), 1))
            gc.SetBrush(wx.Brush(wx.Colour(255, 176, 64) if selected else wx.Colour(110, 180, 255)))
            r = px(5) if selected else px(4)
            gc.DrawEllipse(sx - r, sy - r, 2 * r, 2 * r)

            if selected and obj.path_mode == "spline":
                auto_in, auto_out = self._auto_handles(keys, index)
                for kind, explicit, auto, colour in (
                    ("in", key.path_in, auto_in, wx.Colour(255, 160, 80)),
                    ("out", key.path_out, auto_out, wx.Colour(120, 220, 255)),
                ):
                    point = tuple(explicit) if explicit is not None else auto
                    if point is None:
                        continue
                    hx, hy = self.world_to_screen(ops.apply(parent, float(point[0]), float(point[1])))
                    gc.SetPen(wx.Pen(colour, 1, wx.PENSTYLE_SOLID if explicit is not None else wx.PENSTYLE_DOT))
                    gc.StrokeLine(sx, sy, hx, hy)
                    gc.SetBrush(wx.Brush(colour) if explicit is not None else wx.TRANSPARENT_BRUSH)
                    gc.DrawRectangle(hx - px(4), hy - px(4), px(8), px(8))
                    self._drawn_handles.append(
                        {"key_id": key.id, "kind": kind, "screen_pos": (hx, hy), "local": (float(point[0]), float(point[1]))}
                    )

    # ------------------------------------------------------------------ hit tests
    @staticmethod
    def _nearest(items: List[Dict[str, Any]], pos: wx.Point, radius: float) -> Optional[Dict[str, Any]]:
        best, best_d = None, radius * radius
        for item in items:
            dx = item["screen_pos"][0] - pos.x
            dy = item["screen_pos"][1] - pos.y
            d = dx * dx + dy * dy
            if d <= best_d:
                best, best_d = item, d
        return best

    def hit_object(self, pos: wx.Point) -> Optional[str]:
        hits = [i["object_id"] for i in self._drawn_objects if i["screen_rect"].Contains(pos) and i["object_id"] not in self.locked_ids]
        if not hits:
            self._last_hit_cycle = (None, -1)
            return None
        # Front-most first; clicking the same spot again cycles to the objects underneath.
        hits = list(reversed(hits))
        cycle_key = (pos.x // 3, pos.y // 3, tuple(hits))
        last_key, last_idx = self._last_hit_cycle
        idx = (last_idx + 1) % len(hits) if cycle_key == last_key else 0
        self._last_hit_cycle = (cycle_key, idx)
        return hits[idx]

    # ------------------------------------------------------------------ mouse
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        if self.begin_pan_if_requested(event):
            return
        pos = event.GetPosition()
        handle = self._nearest(self._drawn_handles, pos, px(8))
        key = None if handle else self._nearest(self._drawn_keys, pos, px(8))
        if handle and self.selected_object_id:
            self._drag_kind = "handle"
            self._drag_ids = (self.selected_object_id, handle["key_id"], handle["kind"])
            if self.on_handle_drag_begin:
                self.on_handle_drag_begin(*self._drag_ids)
        elif key and self.selected_object_id:
            self._drag_kind = "key"
            self._drag_ids = (self.selected_object_id, key["key_id"])
            if self.on_key_drag_begin:
                self.on_key_drag_begin(*self._drag_ids)
        else:
            object_id = self.hit_object(pos)
            additive = event.ShiftDown() or event.CmdDown()
            self._press_pos = pos
            self._moved = False
            self._only_on_click = None
            if not object_id:  # empty space: a marquee (Shift or Cmd keeps the selection)
                self._drag_kind = "marquee"
                self._marquee_base = list(self.selected_object_ids) if additive else []
                if not additive and self.on_select:
                    self.on_select(None)
                if not self.HasCapture():
                    self.CaptureMouse()
                return
            if additive:  # Shift adds the layer, Cmd adds or removes it
                ids = [i for i in self.selected_object_ids if i != self.selected_object_id]
                ids += [self.selected_object_id] if self.selected_object_id else []
                if object_id in ids and event.CmdDown():
                    ids.remove(object_id)
                    primary = self.selected_object_id if self.selected_object_id != object_id else (ids[-1] if ids else None)
                else:
                    ids = [i for i in ids if i != object_id] + [object_id]
                    primary = object_id
                if self.on_select_objects:
                    self.on_select_objects(ids, primary)
                if object_id not in ids:
                    return
            elif object_id in self.selected_object_ids and len(self.selected_object_ids) > 1:
                self._only_on_click = object_id  # the group stays selected for a drag
            elif self.on_select:
                self.on_select(object_id)
            self._drag_kind = "object"
            self._drag_ids = (object_id,)
            if self.on_drag_begin:
                self.on_drag_begin(object_id)
        self._drag_start_world = self.screen_to_world(pos)
        if not self.HasCapture():
            self.CaptureMouse()

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return
        pos = event.GetPosition()
        if self._press_pos is not None and abs(pos.x - self._press_pos.x) + abs(pos.y - self._press_pos.y) > 3:
            self._moved = True
        if self._drag_kind == "marquee" and event.Dragging() and self._press_pos is not None:
            if not self._moved:
                return
            x0, y0 = self._press_pos.x, self._press_pos.y
            self._marquee = wx.Rect(min(x0, pos.x), min(y0, pos.y), abs(pos.x - x0) + 1, abs(pos.y - y0) + 1)
            found = [i["object_id"] for i in self._drawn_objects
                     if i["screen_rect"].Intersects(self._marquee) and i["object_id"] not in self.locked_ids]
            ids = list(dict.fromkeys(self._marquee_base + found))
            if self.on_select_objects:
                self.on_select_objects(ids, found[-1] if found else (ids[-1] if ids else None))
            self.Refresh(False)
            return
        if not (event.Dragging() and event.LeftIsDown() and self._drag_kind and self._drag_start_world):
            return
        wx_, wy_ = self.screen_to_world(event.GetPosition())
        dx = wx_ - self._drag_start_world[0]
        dy = wy_ - self._drag_start_world[1]
        if self._drag_kind == "object" and self.on_drag:
            self.on_drag(self._drag_ids[0], dx, dy)
        elif self._drag_kind == "key" and self.on_key_drag:
            self.on_key_drag(self._drag_ids[0], self._drag_ids[1], dx, dy)
        elif self._drag_kind == "handle" and self.on_handle_drag:
            self.on_handle_drag(self._drag_ids[0], self._drag_ids[1], self._drag_ids[2], dx, dy)

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
            self.on_pan_end(event)
            return
        if self.HasCapture():
            self.ReleaseMouse()
        kind = self._drag_kind
        self._drag_kind = None
        self._drag_ids = ()
        self._drag_start_world = None
        self._press_pos = None
        if kind == "marquee":
            self._marquee = None
            self.Refresh(False)
            return
        if kind == "object" and self._only_on_click and not self._moved and self.on_select:
            self.on_select(self._only_on_click)  # a click on one of several selected layers: it alone
        self._only_on_click = None
        if kind is not None and self.on_drag_end:
            self.on_drag_end()

    def _on_right_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        object_id = self.hit_object(event.GetPosition())
        if object_id and object_id not in self.selected_object_ids and self.on_select:
            self.on_select(object_id)  # (a selected layer keeps the group selected for its menu)
        if self.on_context_menu:
            self.on_context_menu(object_id, event.GetPosition())
