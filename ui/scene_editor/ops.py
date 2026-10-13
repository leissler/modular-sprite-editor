"""Scene (timeline) editing operations, independent of wx so they can be unit tested.

Time in the UI is measured in whole frames at the scene FPS. The data model keeps seconds
(``TimelineKeyframe.time``), so every edit converts with ``time_of(frame, fps)``.

Conventions used by the editor:
- The layer list is a tree; siblings are ordered back-to-front (lower rows draw on top) and
  ``draw_order`` always holds the depth-first index, so exporters that sort globally by
  ``draw_order`` paint in the same order as the stage.
- The easing of the motion from key *k* to key *k+1* is stored on key *k+1*
  (``TimelineScene.evaluate_object_state`` reads it from the segment's end key);
  ``segment_easing``/``set_segment_easing`` hide that detail.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from models import (
    TIMELINE_EASINGS,
    TIMELINE_SOURCE_TYPES,
    Project,
    TimelineKeyframe,
    TimelineObject,
    TimelineScene,
    generate_id,
)

Matrix = Tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
Row = Tuple[TimelineObject, int, bool]  # (object, depth, has_children)

# (label, TimelineObject.playback_mode): play the animation as set in the Animations tab, or override how it plays.
PLAYBACK_MODES: List[Tuple[str, str]] = [
    ("As animated", "as_animated"),
    ("Loop", "loop"),
    ("Play once", "once"),
    ("Ping-pong", "ping_pong"),
    ("Loop backwards", "backward"),
]


# --------------------------------------------------------------------------- time
def time_of(frame: int, fps: int) -> float:
    return float(frame) / float(max(1, int(fps)))


def frame_of(time_value: float, fps: int) -> int:
    return int(round(float(time_value) * float(max(1, int(fps)))))


def scene_length_frames(scene: TimelineScene) -> int:
    return max(1, frame_of(scene.duration_seconds, scene.fps))


def set_scene_length_frames(scene: TimelineScene, frames: int) -> None:
    scene.duration_seconds = time_of(max(1, int(frames)), scene.fps)


# --------------------------------------------------------------------------- screen guide
def screen_origin(size: Tuple[int, int]) -> Tuple[int, int]:
    """Where the scene origin lies on a console screen: centred, three quarters down. That is where the SGDK demo
    draws scenes (SPRITE_DRAW_X / SPRITE_DRAW_Y in sgdk_demo/src/main.c: 160, 168 on the Mega Drive's 320×224)."""
    width, height = size
    return (int(width) // 2, int(height) * 3 // 4)


def screen_rect(size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """The screen in scene coordinates: (x0, y0, x1, y1)."""
    ox, oy = screen_origin(size)
    return (-ox, -oy, int(size[0]) - ox, int(size[1]) - oy)


def set_scene_fps(scene: TimelineScene, fps: int) -> None:
    """Change FPS keeping the scene length and every key at the same moment in time."""
    scene.fps = max(1, int(fps))


# --------------------------------------------------------------------------- keys
def keys_at_frame(obj: TimelineObject, frame: int, fps: int) -> List[TimelineKeyframe]:
    """Keys that land on one frame, in evaluation order. More than one only happens with files from the
    old editor, whose free snapping could put keys at the same (or a sub-frame) time."""
    return [k for k in obj.sorted_keyframes() if frame_of(k.time, fps) == frame]


def key_at_frame(
    obj: TimelineObject, frame: int, fps: int, prefer: Optional[Iterable[str]] = None
) -> Optional[TimelineKeyframe]:
    """The key on this frame; when several share it, the preferred (selected) one, else the first."""
    stack = keys_at_frame(obj, frame, fps)
    if prefer:
        preferred = set(prefer)
        chosen = next((k for k in stack if k.id in preferred), None)
        if chosen:
            return chosen
    return stack[0] if stack else None


def key_frames(obj: TimelineObject, fps: int) -> List[int]:
    return sorted({frame_of(k.time, fps) for k in obj.keyframes})


def neighbour_key_frame(scene: TimelineScene, obj: Optional[TimelineObject], frame: int, direction: int) -> Optional[int]:
    """Previous/next key frame of an object (or of all objects when obj is None)."""
    objects = [obj] if obj else scene.objects
    frames = sorted({f for o in objects for f in key_frames(o, scene.fps)})
    if direction > 0:
        return next((f for f in frames if f > frame), None)
    return next((f for f in reversed(frames) if f < frame), None)


def _state_to_key(key: TimelineKeyframe, state: Optional[Dict[str, Any]]) -> None:
    if not state:
        return
    key.x = float(state["x"])
    key.y = float(state["y"])
    key.rotation_degrees = float(state["rotation_degrees"])
    key.flip_x = bool(state["flip_x"])
    key.flip_y = bool(state["flip_y"])
    key.visible = bool(state["visible"])
    key.source_offset = tuple(float(v) for v in state.get("source_key_offset", (0.0, 0.0)))  # type: ignore[assignment]


def ensure_key(project: Project, scene: TimelineScene, obj: TimelineObject, frame: int) -> TimelineKeyframe:
    """Return the key at ``frame``, creating it from the evaluated pose if needed."""
    existing = key_at_frame(obj, frame, scene.fps)
    if existing:
        return existing
    time_value = time_of(frame, scene.fps)
    state = scene.evaluate_object_state(project, obj.id, time_value)
    key = TimelineKeyframe(id=generate_id("tlk"), time=time_value)
    _state_to_key(key, state)
    # Keep the motion into the new key shaped like the segment it splits.
    following = next((k for k in obj.sorted_keyframes() if k.time > time_value), None)
    if following:
        key.easing = following.easing
    obj.keyframes.append(key)
    obj.keyframes.sort(key=lambda k: (k.time, k.id))
    return key


def delete_keys(obj: TimelineObject, key_ids: Iterable[str]) -> int:
    """Delete keys; an object always keeps at least one key. Returns the number removed."""
    ids = set(key_ids)
    remaining = [k for k in obj.keyframes if k.id not in ids]
    if not remaining:
        # Keep the earliest selected key so the object still has a pose.
        keep = obj.sorted_keyframes()[0]
        remaining = [keep]
    removed = len(obj.keyframes) - len(remaining)
    obj.keyframes = remaining
    return removed


def move_keys(
    scene: TimelineScene,
    selection: Dict[str, Set[str]],
    delta_frames: int,
    origin_frames: Optional[Dict[Tuple[str, str], int]] = None,
) -> int:
    """
    Retime selected keys by ``delta_frames`` (clamped to the scene). ``origin_frames`` holds the
    frames at drag start so repeated calls during a drag stay exact. Unselected keys that end up
    on the same frame as a moved key are replaced (the moved key wins). Returns the applied delta.
    """
    length = scene_length_frames(scene)
    fps = scene.fps
    origins: Dict[Tuple[str, str], int] = dict(origin_frames or {})
    moving: List[Tuple[TimelineObject, TimelineKeyframe, int]] = []
    for obj_id, key_ids in selection.items():
        obj = scene.get_object(obj_id)
        if not obj:
            continue
        for key in obj.keyframes:
            if key.id in key_ids:
                start = origins.get((obj_id, key.id), frame_of(key.time, fps))
                moving.append((obj, key, start))
    if not moving:
        return 0
    lo = min(start for _o, _k, start in moving)
    hi = max(start for _o, _k, start in moving)
    delta = max(-lo, min(length - hi, int(delta_frames)))
    for obj, key, start in moving:
        key.time = time_of(start + delta, fps)
    for obj in {id(o): o for o, _k, _s in moving}.values():
        moved_ids = selection.get(obj.id, set())
        moved_frames = {frame_of(k.time, fps) for k in obj.keyframes if k.id in moved_ids}
        obj.keyframes = [
            k for k in obj.keyframes if k.id in moved_ids or frame_of(k.time, fps) not in moved_frames
        ]
        obj.keyframes.sort(key=lambda k: (k.time, k.id))
    return delta


def copy_keys(scene: TimelineScene, selection: Dict[str, Set[str]]) -> List[Dict[str, Any]]:
    """Serialise selected keys relative to the earliest one (for paste at the playhead)."""
    entries: List[Tuple[str, TimelineKeyframe]] = []
    for obj_id, key_ids in selection.items():
        obj = scene.get_object(obj_id)
        if obj:
            entries.extend((obj_id, k) for k in obj.keyframes if k.id in key_ids)
    if not entries:
        return []
    first = min(frame_of(k.time, scene.fps) for _o, k in entries)
    return [
        {"object_id": obj_id, "offset": frame_of(k.time, scene.fps) - first, "key": k.to_dict()}
        for obj_id, k in entries
    ]


def paste_keys(
    scene: TimelineScene,
    clipboard: List[Dict[str, Any]],
    frame: int,
    target_object_id: Optional[str] = None,
) -> Dict[str, Set[str]]:
    """Paste copied keys at ``frame``. Keys copied from one object can go to another object."""
    source_ids = {entry["object_id"] for entry in clipboard}
    pasted: Dict[str, Set[str]] = {}
    length = scene_length_frames(scene)
    for entry in clipboard:
        obj_id = entry["object_id"]
        if target_object_id and len(source_ids) == 1:
            obj_id = target_object_id
        obj = scene.get_object(obj_id)
        if not obj:
            continue
        key = TimelineKeyframe.from_dict(dict(entry["key"]))
        key.id = generate_id("tlk")
        target_frame = max(0, min(length, frame + int(entry["offset"])))
        key.time = time_of(target_frame, scene.fps)
        obj.keyframes = [k for k in obj.keyframes if frame_of(k.time, scene.fps) != target_frame]
        obj.keyframes.append(key)
        obj.keyframes.sort(key=lambda k: (k.time, k.id))
        pasted.setdefault(obj.id, set()).add(key.id)
    return pasted


# --------------------------------------------------------------------------- easing
EASING_SHAPES: List[Tuple[str, str]] = [
    ("Linear", "linear"),
    ("Hold", "step"),
    ("Gentle", "sine"),
    ("Normal", "quad"),
    ("Strong", "cubic"),
    ("Stronger", "quart"),
    ("Strongest", "quint"),
    ("Exponential", "expo"),
    ("Circular", "circ"),
    ("Overshoot", "back"),
    ("Elastic", "elastic"),
    ("Bounce", "bounce"),
]
EASING_DIRECTIONS: List[Tuple[str, str]] = [
    ("Ease in", "in"),
    ("Ease out", "out"),
    ("Ease in & out", "in_out"),
]


def split_easing(name: str) -> Tuple[str, str]:
    """'cubic_in_out' -> ('cubic', 'in_out'); 'linear' -> ('linear', 'in_out')."""
    name = str(name or "linear")
    if name in ("linear", "step"):
        return name, "in_out"
    for direction in ("in_out", "in", "out"):
        if name.endswith("_" + direction):
            return name[: -len(direction) - 1], direction
    return "linear", "in_out"


def join_easing(shape: str, direction: str) -> str:
    if shape in ("linear", "step"):
        return shape
    name = f"{shape}_{direction}"
    return name if name in TIMELINE_EASINGS else "linear"


def easing_label(name: str) -> str:
    shape, direction = split_easing(name)
    shape_label = next((label for label, key in EASING_SHAPES if key == shape), shape)
    if shape in ("linear", "step"):
        return shape_label
    direction_label = {"in": "in", "out": "out", "in_out": "in & out"}[direction]
    return f"{shape_label} ease {direction_label}"


def segment_end_key(obj: TimelineObject, key_id: str) -> Optional[TimelineKeyframe]:
    """The key that ends the segment starting at ``key_id`` (holds that segment's easing)."""
    keys = obj.sorted_keyframes()
    for idx, key in enumerate(keys):
        if key.id == key_id:
            return keys[idx + 1] if idx + 1 < len(keys) else None
    return None


def segment_easing(obj: TimelineObject, key_id: str) -> Optional[str]:
    end = segment_end_key(obj, key_id)
    return end.easing if end else None


def set_segment_easing(obj: TimelineObject, key_id: str, easing: str) -> bool:
    end = segment_end_key(obj, key_id)
    if not end or easing not in TIMELINE_EASINGS:
        return False
    end.easing = easing
    return True


def key_before_or_at(obj: TimelineObject, frame: int, fps: int) -> Optional[TimelineKeyframe]:
    keys = [k for k in obj.sorted_keyframes() if frame_of(k.time, fps) <= frame]
    return keys[-1] if keys else None


# --------------------------------------------------------------------------- tree / order
def children_of(scene: TimelineScene, parent_id: Optional[str]) -> List[TimelineObject]:
    valid = {o.id for o in scene.objects}
    kids = [o for o in scene.objects if (o.parent_id if o.parent_id in valid else None) == parent_id]
    kids.sort(key=lambda o: (o.draw_order, o.name.lower(), o.id))
    return kids


def tree_rows(scene: Optional[TimelineScene], collapsed: Set[str]) -> List[Row]:
    if not scene:
        return []
    rows: List[Row] = []

    def walk(parent_id: Optional[str], depth: int) -> None:
        for obj in children_of(scene, parent_id):
            kids = children_of(scene, obj.id)
            rows.append((obj, depth, bool(kids)))
            if obj.id not in collapsed:
                walk(obj.id, depth + 1)

    walk(None, 0)
    return rows


def normalize_draw_order(scene: TimelineScene) -> None:
    """Make draw_order the depth-first index of the layer tree (back to front)."""
    order: List[TimelineObject] = []

    def walk(parent_id: Optional[str]) -> None:
        for obj in children_of(scene, parent_id):
            order.append(obj)
            walk(obj.id)

    walk(None)
    for idx, obj in enumerate(order):
        obj.draw_order = idx


def is_descendant(scene: TimelineScene, object_id: str, maybe_ancestor_id: Optional[str]) -> bool:
    """True if ``object_id`` is ``maybe_ancestor_id`` or below it (i.e. parenting would loop)."""
    current = scene.get_object(maybe_ancestor_id) if maybe_ancestor_id else None
    seen: Set[str] = set()
    while current:
        if current.id == object_id:
            return True
        if current.id in seen:
            return True
        seen.add(current.id)
        current = scene.get_object(current.parent_id) if current.parent_id else None
    return False


# --------------------------------------------------------------------------- transforms
def pose_matrix(x: float, y: float, rotation: float, flip_x: bool, flip_y: bool) -> Matrix:
    """Flip, then rotate, then move (exact at 90° steps)."""
    quarter = float(rotation) / 90.0
    if abs(quarter - round(quarter)) < 1e-9:
        cos_a, sin_a = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(round(quarter)) % 4]
    else:
        rad = math.radians(float(rotation))
        cos_a, sin_a = math.cos(rad), math.sin(rad)
    sx = -1.0 if flip_x else 1.0
    sy = -1.0 if flip_y else 1.0
    return (cos_a * sx, sin_a * sx, -sin_a * sy, cos_a * sy, float(x), float(y))


def source_matrix(state: Dict[str, Any]) -> Matrix:
    """What the source adds inside the object: root motion (the step's offset, flips and rotation) and the swap offset."""
    source_offset = state.get("source_offset", (0.0, 0.0))
    return pose_matrix(
        float(source_offset[0]), float(source_offset[1]), float(state.get("source_rotation", 0.0)),
        bool(state.get("source_flip_x", False)), bool(state.get("source_flip_y", False)),
    )


def local_matrix(state: Dict[str, Any]) -> Matrix:
    """Object transform for an evaluated state: the key's pose applied to what the source adds, so a mirrored or
    turned object also mirrors or turns where its animation moves it (like a mirrored parent its children)."""
    pose = pose_matrix(
        float(state.get("x", 0.0)), float(state.get("y", 0.0)), float(state.get("rotation_degrees", 0.0)),
        bool(state.get("flip_x", False)), bool(state.get("flip_y", False)),
    )
    return compose(pose, source_matrix(state))


def compose(parent: Matrix, child: Matrix) -> Matrix:
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


def invert(matrix: Matrix) -> Matrix:
    a, b, c, d, tx, ty = matrix
    det = a * d - b * c
    if abs(det) <= 1e-8:
        return IDENTITY
    inv = 1.0 / det
    return (d * inv, -b * inv, -c * inv, a * inv, (c * ty - d * tx) * inv, (b * tx - a * ty) * inv)


def apply(matrix: Matrix, x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, tx, ty = matrix
    return (a * x + c * y + tx, b * x + d * y + ty)


def apply_vector(matrix: Matrix, x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, _tx, _ty = matrix
    return (a * x + c * y, b * x + d * y)


def decompose(matrix: Matrix, flip_hint: Tuple[bool, bool] = (False, False)) -> Tuple[Tuple[float, float], float, bool, bool]:
    """Split a matrix into (translation, rotation°, flip_x, flip_y), preferring the hinted flips."""
    a, b, c, d, tx, ty = matrix
    best: Optional[Tuple[float, bool, bool, float]] = None
    for flip_x in (False, True):
        for flip_y in (False, True):
            sx = -1.0 if flip_x else 1.0
            sy = -1.0 if flip_y else 1.0
            theta = math.atan2(b / sx, a / sx)
            ca, sa = math.cos(theta), math.sin(theta)
            err = abs(ca * sx - a) + abs(sa * sx - b) + abs(-sa * sy - c) + abs(ca * sy - d)
            err += 1e-5 * ((flip_x != flip_hint[0]) + (flip_y != flip_hint[1]))
            if best is None or err < best[0]:
                best = (err, flip_x, flip_y, theta)
    assert best is not None
    _err, flip_x, flip_y, theta = best
    degrees = math.degrees(theta)
    if abs(degrees / 90.0 - round(degrees / 90.0)) < 1e-6:
        degrees = float(round(degrees / 90.0) * 90)
    return ((tx, ty), degrees, flip_x, flip_y)


def evaluate_states(project: Project, scene: TimelineScene, time_value: float) -> Dict[str, Dict[str, Any]]:
    states: Dict[str, Dict[str, Any]] = {}
    for obj in scene.objects:
        state = scene.evaluate_object_state(project, obj.id, time_value)
        if state is not None:
            states[obj.id] = state
    return states


def world_matrix(
    scene: TimelineScene,
    states: Dict[str, Dict[str, Any]],
    object_id: Optional[str],
    cache: Optional[Dict[str, Matrix]] = None,
) -> Matrix:
    if not object_id or object_id not in states:
        return IDENTITY
    cache = {} if cache is None else cache
    if object_id in cache:
        return cache[object_id]
    obj = scene.get_object(object_id)
    parent_world = IDENTITY
    if obj and obj.parent_id and obj.parent_id != object_id and scene.get_object(obj.parent_id):
        parent_world = world_matrix(scene, states, obj.parent_id, cache)
    world = compose(parent_world, local_matrix(states[object_id]))
    cache[object_id] = world
    return world


def parent_world_matrix(project: Project, scene: TimelineScene, obj: TimelineObject, time_value: float) -> Matrix:
    states = evaluate_states(project, scene, time_value)
    return world_matrix(scene, states, obj.parent_id) if obj.parent_id else IDENTITY


def world_to_parent_delta(parent: Matrix, dx: float, dy: float) -> Tuple[float, float]:
    """Convert a world-space drag delta into the parent's local space."""
    inv = invert((parent[0], parent[1], parent[2], parent[3], 0.0, 0.0))
    return apply_vector(inv, dx, dy)


def set_parent_keep_world(
    project: Project, scene: TimelineScene, obj: TimelineObject, new_parent_id: Optional[str]
) -> bool:
    """Re-parent an object; every key is rewritten so the object stays where it is on stage."""
    if new_parent_id == obj.id or (new_parent_id and not scene.get_object(new_parent_id)):
        return False
    if new_parent_id and is_descendant(scene, obj.id, new_parent_id):
        return False
    if new_parent_id == obj.parent_id:
        return False
    for key in obj.keyframes:
        states = evaluate_states(project, scene, float(key.time))
        if obj.id not in states:
            continue
        cache: Dict[str, Matrix] = {}
        old_world = world_matrix(scene, states, obj.id, cache)
        new_parent_world = world_matrix(scene, states, new_parent_id, cache) if new_parent_id else IDENTITY
        desired_local = compose(invert(new_parent_world), old_world)
        state = states[obj.id]
        # local = pose · source, so the key's pose is desired_local · source⁻¹
        (tx, ty), rotation, flip_x, flip_y = decompose(
            compose(desired_local, invert(source_matrix(state))),
            (bool(state.get("flip_x", False)), bool(state.get("flip_y", False))),
        )
        key.x = float(tx)
        key.y = float(ty)
        key.rotation_degrees = float(rotation)
        key.flip_x = bool(flip_x)
        key.flip_y = bool(flip_y)
    obj.parent_id = new_parent_id
    return True


def move_layer(
    project: Project,
    scene: TimelineScene,
    object_id: str,
    new_parent_id: Optional[str],
    before_sibling_id: Optional[str],
) -> bool:
    """
    Move a layer in the tree: re-parent (keeping its world pose) and place it before
    ``before_sibling_id`` among the new siblings (None = last, i.e. front-most).
    """
    obj = scene.get_object(object_id)
    if not obj:
        return False
    if new_parent_id and is_descendant(scene, obj.id, new_parent_id):
        return False
    if new_parent_id != obj.parent_id:
        if not set_parent_keep_world(project, scene, obj, new_parent_id):
            return False
    siblings = [o for o in children_of(scene, new_parent_id) if o.id != obj.id]
    index = len(siblings)
    if before_sibling_id:
        index = next((i for i, o in enumerate(siblings) if o.id == before_sibling_id), len(siblings))
    siblings.insert(index, obj)
    for i, sibling in enumerate(siblings):
        sibling.draw_order = i
    normalize_draw_order(scene)
    return True


def step_layer(project: Project, scene: TimelineScene, object_id: str, direction: int) -> bool:
    """Move a layer one place forward (direction > 0, drawn later) or backward among siblings."""
    obj = scene.get_object(object_id)
    if not obj:
        return False
    siblings = children_of(scene, obj.parent_id if scene.get_object(obj.parent_id or "") else None)
    idx = siblings.index(obj)
    target = idx + (1 if direction > 0 else -1)
    if not (0 <= target < len(siblings)):
        return False
    siblings[idx], siblings[target] = siblings[target], siblings[idx]
    for i, sibling in enumerate(siblings):
        sibling.draw_order = i
    normalize_draw_order(scene)
    return True


# --------------------------------------------------------------------------- objects
def source_name(project: Project, source_type: Optional[str], source_id: Optional[str]) -> str:
    if source_type == "module":
        item = project.get_module(source_id or "")
    elif source_type == "frame":
        item = project.get_frame(source_id or "")
    elif source_type == "animation":
        item = project.get_animation(source_id or "")
    else:
        return "Group (no image)"
    return item.name if item else "Missing"


def add_object(
    project: Project,
    scene: TimelineScene,
    source_type: str,
    source_id: Optional[str],
    frame: int,
    position: Tuple[float, float] = (0.0, 0.0),
    parent_id: Optional[str] = None,
) -> TimelineObject:
    source_type = source_type if source_type in TIMELINE_SOURCE_TYPES else "none"
    name = source_name(project, source_type, source_id) if source_type != "none" else "Group"
    taken = {o.name for o in scene.objects}
    base, n = name, 2
    while name in taken:
        name = f"{base} {n}"
        n += 1
    obj = scene.create_object(name, source_type=source_type, source_id=source_id, parent_id=parent_id)
    key = obj.keyframes[0]
    key.time = time_of(frame, scene.fps)
    key.x, key.y = float(position[0]), float(position[1])
    obj.draw_order = 10**6  # newest goes in front of its siblings
    normalize_draw_order(scene)
    return obj


def duplicate_object(scene: TimelineScene, object_id: str) -> Optional[TimelineObject]:
    """Duplicate an object and its whole subtree; the copy is placed directly in front."""
    obj = scene.get_object(object_id)
    if not obj:
        return None
    id_map: Dict[str, str] = {}

    def copy_subtree(source: TimelineObject, new_parent: Optional[str]) -> TimelineObject:
        clone = source.clone()
        clone.id = generate_id("tlo")
        id_map[source.id] = clone.id
        clone.parent_id = new_parent
        for key in clone.keyframes:
            key.id = generate_id("tlk")
        scene.objects.append(clone)
        for child in children_of(scene, source.id):
            if child.id not in id_map.values():
                copy_subtree(child, clone.id)
        return clone

    top = copy_subtree(obj, obj.parent_id)
    top.name = f"{obj.name} copy"
    top.draw_order = obj.draw_order
    # Insert right after the original among its siblings.
    siblings = [o for o in children_of(scene, obj.parent_id) if o.id != top.id]
    index = siblings.index(obj) + 1
    siblings.insert(index, top)
    for i, sibling in enumerate(siblings):
        sibling.draw_order = i
    normalize_draw_order(scene)
    return top


def source_uses(project: Project, source_type: str, ids: Iterable[str]) -> int:
    """How many objects show one of these modules / frames / animations, as their source or at a key."""
    ids = set(ids)
    return sum(
        1 for scene in project.timeline_scenes for obj in scene.objects
        if (obj.source_type == source_type and obj.source_id in ids)
        or any(key.source_id in ids and (key.source_type or obj.source_type) == source_type for key in obj.keyframes)
    )


def clear_sources(project: Project, source_type: str, ids: Iterable[str]) -> int:
    """Objects and key swaps that show one of these (deleted) modules / frames / animations show nothing instead;
    keys and motion stay. Returns how many objects and keys changed."""
    ids = set(ids)
    cleared = 0
    for scene in project.timeline_scenes:
        for obj in scene.objects:
            for key in obj.keyframes:
                if key.source_id in ids and (key.source_type or obj.source_type) == source_type:
                    key.source_type, key.source_id = None, None
                    cleared += 1
            if obj.source_type == source_type and obj.source_id in ids:
                obj.source_type, obj.source_id = "none", None
                cleared += 1
    return cleared


def delete_object(project: Project, scene: TimelineScene, object_id: str) -> None:
    """Delete an object; its children move up to its parent and keep their world pose."""
    obj = scene.get_object(object_id)
    if not obj:
        return
    for child in [o for o in scene.objects if o.parent_id == object_id]:
        set_parent_keep_world(project, scene, child, obj.parent_id)
    scene.objects = [o for o in scene.objects if o.id != object_id]
    normalize_draw_order(scene)


def shift_all_keys(obj: TimelineObject, dx: float = 0.0, dy: float = 0.0, drot: float = 0.0) -> None:
    for key in obj.keyframes:
        key.x += dx
        key.y += dy
        key.rotation_degrees += drot


def playback_signature(project: Project, obj: TimelineObject) -> Tuple[Any, ...]:
    """Everything that decides which animation frames an object shows: its animations (source, swaps and every
    follow-up they hand over to) with their timing. Caches of what an object shows compare it."""
    pending = [obj.source_id] + [key.source_id for key in obj.keyframes]
    seen: Set[str] = set()
    signature = []
    while pending:
        anim_id = pending.pop()
        anim = project.get_animation(anim_id) if anim_id else None
        if anim is None or anim.id in seen:
            continue
        seen.add(anim.id)
        signature.append((anim.id, anim.playback_type, anim.loop_count, anim.loop_start, anim.next_animation_id,
                          anim.fps, tuple((af.frame_id, af.duration_frames) for af in anim.aframes)))
        pending.append(anim.next_animation_id)
    return tuple(sorted(signature, key=lambda entry: entry[0]))


def animation_frame_changes(project: Project, scene: TimelineScene, obj: TimelineObject) -> List[int]:
    """Scene frames where an animation-sourced object shows a new animation frame."""
    if obj.source_type != "animation" and not any(k.source_type == "animation" for k in obj.keyframes):
        return []
    changes: List[int] = []
    previous: Optional[str] = None
    for frame in range(scene_length_frames(scene) + 1):
        state = scene.evaluate_object_state(project, obj.id, time_of(frame, scene.fps))
        current = state.get("frame_id") if state else None
        if frame > 0 and current != previous:
            changes.append(frame)
        previous = current
    return changes
