"""Frames tab operations without wx: frames, parts, hitboxes, points and their types."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from models import CollisionRect, CollisionType, ControlPoint, FModule, Frame, ModuleMapping, PointType, Project, generate_id
from ui.frame_geometry import frame_bounds, part_bounds, union

# Edit modes: key, label, FrameCanvas.edit_mode
MODES: List[Tuple[str, str, str]] = [
    ("parts", "Parts", "module"),
    ("hitboxes", "Hitboxes", "collision"),
    ("points", "Points", "point"),
]
CANVAS_MODE = {key: canvas for key, _label, canvas in MODES}
MODE_OF_CANVAS = {canvas: key for key, _label, canvas in MODES}

TYPE_COLOURS = [
    (255, 80, 80), (80, 200, 255), (120, 230, 110), (255, 200, 60), (210, 120, 255),
    (255, 140, 200), (90, 230, 210), (255, 150, 70),
]


# ---------------------------------------------------------------------------- frames
def unique_frame_name(project: Project, base: str) -> str:
    used = {f.name for f in project.frames}
    name, n = base, 2
    while name in used:
        name = f"{base} ({n})"
        n += 1
    return name


def new_frame(project: Project, after_id: Optional[str] = None, name: Optional[str] = None) -> Frame:
    frame = Frame(id=generate_id("frm"), name=unique_frame_name(project, name or f"Frame {len(project.frames) + 1}"))
    after = project.get_frame(after_id) if after_id else None
    index = project.frames.index(after) + 1 if after else len(project.frames)
    project.frames.insert(index, frame)
    return frame


def duplicate_frame(project: Project, frame_id: str) -> Optional[Frame]:
    source = project.get_frame(frame_id)
    if source is None:
        return None
    copy = Frame.from_dict(source.to_dict())
    copy.id = generate_id("frm")
    copy.name = unique_frame_name(project, f"{source.name} copy")
    for fm in copy.fmodules:
        fm.id = generate_id("fmod")
    for cr in copy.collision_rects:
        cr.id = generate_id("crect")
    for cp in copy.control_points:
        cp.id = generate_id("pt")
    project.frames.insert(project.frames.index(source) + 1, copy)
    return copy


def frame_references(project: Project, frame_id: str) -> Dict[str, int]:
    """How often a frame is used by animations (steps), other frames (as a nested part) and timeline objects."""
    steps = sum(1 for a in project.animations for af in a.aframes if af.frame_id == frame_id)
    animations = sum(1 for a in project.animations if any(af.frame_id == frame_id for af in a.aframes))
    nested = sum(1 for f in project.frames if any(fm.ref_type == "frame" and fm.ref_id == frame_id for fm in f.fmodules))
    objects = 0
    for scene in project.timeline_scenes:
        for obj in scene.objects:
            if (obj.source_type == "frame" and obj.source_id == frame_id) or any(
                getattr(k, "source_type", None) == "frame" and getattr(k, "source_id", None) == frame_id for k in obj.keyframes
            ):
                objects += 1
    return {"animations": animations, "steps": steps, "frames": nested, "scene_objects": objects}


def describe_references(refs: Dict[str, int]) -> str:
    bits = []
    if refs.get("animations"):
        n = refs["animations"]
        bits.append(f"{n} animation{'s' if n != 1 else ''}")
    if refs.get("frames"):
        n = refs["frames"]
        bits.append(f"{n} other frame{'s' if n != 1 else ''}")
    if refs.get("scene_objects"):
        n = refs["scene_objects"]
        bits.append(f"{n} timeline object{'s' if n != 1 else ''}")
    return ", ".join(bits) if bits else "not used"


def animation_counts(project: Project) -> Dict[str, int]:
    """How many animations use each frame (for the list)."""
    counts: Dict[str, int] = {}
    for anim in project.animations:
        for frame_id in {af.frame_id for af in anim.aframes}:
            counts[frame_id] = counts.get(frame_id, 0) + 1
    return counts


def delete_frame(project: Project, frame_id: str) -> None:
    project.frames = [f for f in project.frames if f.id != frame_id]


def remove_frame_uses(project: Project, frame_id: str) -> Tuple[int, int, int]:
    """Remove what shows a frame: animation steps ("loop from" stays on its step), nested parts in other frames and
    scene objects / key swaps (they show nothing). Returns (steps, nested parts, scene uses)."""
    from ui.scene_editor.ops import clear_sources

    steps = 0
    for anim in project.animations:
        if not any(af.frame_id == frame_id for af in anim.aframes):
            continue
        before_loop = sum(1 for af in anim.aframes[: anim.loop_start] if af.frame_id == frame_id)
        kept = [af for af in anim.aframes if af.frame_id != frame_id]
        steps += len(anim.aframes) - len(kept)
        anim.aframes = kept
        anim.loop_start = max(0, min(anim.loop_start - before_loop, len(kept) - 1)) if kept else 0
    parts = 0
    for frame in project.frames:
        kept_parts = [fm for fm in frame.fmodules if not (fm.ref_type == "frame" and fm.ref_id == frame_id)]
        parts += len(frame.fmodules) - len(kept_parts)
        frame.fmodules = kept_parts
    return steps, parts, clear_sources(project, "frame", [frame_id])


def move_frame(project: Project, frame_id: str, before_id: Optional[str]) -> None:
    frame = project.get_frame(frame_id)
    if frame is None or frame_id == before_id:
        return
    project.frames.remove(frame)
    anchor = project.get_frame(before_id) if before_id else None
    project.frames.insert(project.frames.index(anchor) if anchor else len(project.frames), frame)


def summary(frame: Frame) -> str:
    bits = [f"{len(frame.fmodules)} part{'s' if len(frame.fmodules) != 1 else ''}"]
    if frame.collision_rects:
        bits.append(f"{len(frame.collision_rects)} box{'es' if len(frame.collision_rects) != 1 else ''}")
    if frame.control_points:
        bits.append(f"{len(frame.control_points)} point{'s' if len(frame.control_points) != 1 else ''}")
    return " · ".join(bits)


# ---------------------------------------------------------------------------- items (parts / hitboxes / points)
def items(frame: Frame, mode: str) -> List[Any]:
    if mode == "hitboxes":
        return frame.collision_rects
    if mode == "points":
        return frame.control_points
    return frame.fmodules


def insert_items(project: Project, frame: Frame, mode: str, item_dicts: Sequence[Dict[str, Any]]) -> List[str]:
    """Paste copies (fresh ids). Nested frames that would contain themselves are skipped."""
    new_ids: List[str] = []
    for data in item_dicts:
        data = dict(data)
        if mode == "hitboxes":
            data["id"] = generate_id("crect")
            frame.collision_rects.append(CollisionRect.from_dict(data))
        elif mode == "points":
            data["id"] = generate_id("pt")
            frame.control_points.append(ControlPoint.from_dict(data))
        else:
            if data.get("ref_type") == "frame" and (data.get("ref_id") == frame.id or project.frame_has_cycle(frame.id, data.get("ref_id"))):
                continue
            data["id"] = generate_id("fmod")
            frame.fmodules.append(FModule.from_dict(data))
        new_ids.append(data["id"])
    return new_ids


def delete_items(frame: Frame, mode: str, ids: Iterable[str]) -> int:
    ids = set(ids)
    before = len(items(frame, mode))
    if mode == "hitboxes":
        frame.collision_rects = [c for c in frame.collision_rects if c.id not in ids]
    elif mode == "points":
        frame.control_points = [c for c in frame.control_points if c.id not in ids]
    else:
        frame.fmodules = [p for p in frame.fmodules if p.id not in ids]
    return before - len(items(frame, mode))


def nudge(frame: Frame, mode: str, ids: Iterable[str], dx: int, dy: int) -> None:
    ids = set(ids)
    for item in items(frame, mode):
        if item.id not in ids:
            continue
        if mode == "hitboxes":
            x, y, w, h = item.rect
            item.rect = (x + dx, y + dy, w, h)
        elif mode == "points":
            item.x += dx
            item.y += dy
        else:
            x, y = item.position
            item.position = (x + dx, y + dy)


def add_part(project: Project, frame: Frame, ref_type: str, ref_id: str, position: Tuple[int, int]) -> Optional[FModule]:
    if ref_type == "frame" and (ref_id == frame.id or project.frame_has_cycle(frame.id, ref_id)):
        return None
    part = FModule(id=generate_id("fmod"), ref_type=ref_type, ref_id=ref_id, position=(int(position[0]), int(position[1])))
    frame.fmodules.append(part)
    return part


def swap_source(project: Project, frame: Frame, part_ids: Iterable[str], ref_type: str, ref_id: str) -> int:
    """Point parts at another module / frame (position, flips and rotation stay)."""
    if ref_type == "frame" and (ref_id == frame.id or project.frame_has_cycle(frame.id, ref_id)):
        return 0
    ids = set(part_ids)
    changed = 0
    for fm in frame.fmodules:
        if fm.id in ids and (fm.ref_type, fm.ref_id) != (ref_type, ref_id):
            fm.ref_type, fm.ref_id = ref_type, ref_id
            changed += 1
    return changed


def part_name(project: Project, fm: FModule) -> str:
    if fm.ref_type == "frame":
        ref = project.get_frame(fm.ref_id)
        return f"▣ {ref.name}" if ref else "▣ (missing frame)"
    mod = project.get_module(fm.ref_id)
    return mod.name if mod else "(missing module)"


def part_details(fm: FModule) -> str:
    bits = [f"{fm.position[0]}, {fm.position[1]}"]
    if fm.flip_x or fm.flip_y:
        bits.append("flip " + ("H" if fm.flip_x else "") + ("V" if fm.flip_y else ""))
    rotation = int(round(fm.rotation_degrees)) % 360
    if rotation:
        bits.append(f"{rotation}°")
    return " · ".join(bits)


# ---------------------------------------------------------------------------- transforms
def flip_parts(project: Project, frame: Frame, part_ids: Optional[Sequence[str]], axis: str,
               mapping: Optional[ModuleMapping]) -> int:
    """Flip parts on the screen axis: each part mirrors in place (rotation-aware) and the group mirrors
    about its centre. ``part_ids`` None flips every part about the frame origin."""
    if part_ids is None:
        targets = list(frame.fmodules)
        group_centre: Optional[Tuple[float, float]] = (0.0, 0.0)
    else:
        wanted = set(part_ids)
        targets = [fm for fm in frame.fmodules if fm.id in wanted]
        group_centre = None
    if not targets:
        return 0
    centres: Dict[str, Tuple[float, float]] = {}
    boxes = []
    for fm in targets:
        b = part_bounds(project, fm, mapping)
        centres[fm.id] = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
        boxes.append(b)
    if group_centre is None:
        box = union(boxes)
        group_centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)  # type: ignore[index]
    gx, gy = group_centre
    for fm in targets:
        old_cx, old_cy = centres[fm.id]
        # A part turned by 90° shows its other image axis on this screen axis.
        quarter = int(round(fm.rotation_degrees)) % 180 == 90
        if (axis == "x") != quarter:
            fm.flip_x = not fm.flip_x
        else:
            fm.flip_y = not fm.flip_y
        b = part_bounds(project, fm, mapping)
        cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
        fm.position = (int(fm.position[0] + old_cx - cx), int(fm.position[1] + old_cy - cy))
        tx = gx - (old_cx - gx) if axis == "x" else old_cx
        ty = gy - (old_cy - gy) if axis == "y" else old_cy
        fm.position = (int(fm.position[0] + tx - old_cx), int(fm.position[1] + ty - old_cy))
    return len(targets)


def rotate_parts(frame: Frame, part_ids: Iterable[str], degrees: float) -> int:
    ids = set(part_ids)
    changed = 0
    for fm in frame.fmodules:
        if fm.id in ids:
            fm.rotation_degrees = (fm.rotation_degrees + degrees) % 360.0
            changed += 1
    return changed


def mirror_frame(project: Project, frame: Frame, axis: str, mapping: Optional[ModuleMapping]) -> None:
    """Mirror the whole frame about its origin: parts, hitboxes and points (a point marks a pixel: pixel x mirrors to
    pixel -x - 1, like a hitbox's edge pixels)."""
    flip_parts(project, frame, None, axis, mapping)
    for cr in frame.collision_rects:
        x, y, w, h = cr.rect
        cr.rect = (-x - w, y, w, h) if axis == "x" else (x, -y - h, w, h)
    for cp in frame.control_points:
        if axis == "x":
            cp.x = -cp.x - 1
        else:
            cp.y = -cp.y - 1


def turn_pixel(x: int, y: int, quarter_turns: int) -> Tuple[int, int]:
    """The pixel a pixel lands on when the frame turns about its origin by quarter turns (clockwise, y down)."""
    for _ in range(quarter_turns % 4):
        x, y = -y - 1, x
    return x, y


def rotate_frame(frame: Frame, degrees: int) -> None:
    """Turn the whole frame about its origin in 90° steps (clockwise for positive degrees)."""
    steps = int(round(degrees / 90.0)) % 4
    if steps == 0:
        return

    def turn(x: float, y: float) -> Tuple[float, float]:
        for _ in range(steps):
            x, y = -y, x
        return x, y

    for fm in frame.fmodules:
        fm.rotation_degrees = (fm.rotation_degrees + 90.0 * steps) % 360.0
        fm.position = tuple(int(v) for v in turn(*fm.position))  # type: ignore[assignment]
    for cr in frame.collision_rects:
        x, y, w, h = cr.rect
        corners = [turn(x, y), turn(x + w, y + h)]
        x0, x1 = sorted(c[0] for c in corners)
        y0, y1 = sorted(c[1] for c in corners)
        cr.rect = (int(x0), int(y0), int(x1 - x0), int(y1 - y0))
    for cp in frame.control_points:
        cp.x, cp.y = turn_pixel(int(cp.x), int(cp.y), steps)


def offset_frame(frame: Frame, dx: int, dy: int) -> None:
    """Move everything in the frame (the origin stays where it is)."""
    for fm in frame.fmodules:
        fm.position = (fm.position[0] + dx, fm.position[1] + dy)
    for cr in frame.collision_rects:
        x, y, w, h = cr.rect
        cr.rect = (x + dx, y + dy, w, h)
    for cp in frame.control_points:
        cp.x += dx
        cp.y += dy


def origin_offset(project: Project, frame: Frame, mapping: Optional[ModuleMapping], anchor: str) -> Tuple[int, int]:
    """Move that puts the parts' bottom centre ("feet") or centre on the origin."""
    box = union([part_bounds(project, fm, mapping) for fm in frame.fmodules])
    if box is None:
        return (0, 0)
    cx = (box[0] + box[2]) / 2.0
    target_y = box[3] if anchor == "feet" else (box[1] + box[3]) / 2.0
    return (int(round(-cx)), int(round(-target_y)))


def reorder_parts(frame: Frame, part_ids: Iterable[str], direction: str) -> bool:
    """Change the draw order of parts: up / down one step, top / bottom (later parts draw on top)."""
    ids = set(part_ids)
    parts = frame.fmodules
    before = [fm.id for fm in parts]
    if direction == "up":
        for i in range(len(parts) - 2, -1, -1):
            if parts[i].id in ids and parts[i + 1].id not in ids:
                parts[i], parts[i + 1] = parts[i + 1], parts[i]
    elif direction == "down":
        for i in range(1, len(parts)):
            if parts[i].id in ids and parts[i - 1].id not in ids:
                parts[i], parts[i - 1] = parts[i - 1], parts[i]
    elif direction == "top":
        frame.fmodules = [fm for fm in parts if fm.id not in ids] + [fm for fm in parts if fm.id in ids]
    elif direction == "bottom":
        frame.fmodules = [fm for fm in parts if fm.id in ids] + [fm for fm in parts if fm.id not in ids]
    return [fm.id for fm in frame.fmodules] != before


def move_item(frame: Frame, mode: str, item_id: str, before_id: Optional[str]) -> None:
    """Reorder one item in its list (the contents list shows parts top-most first)."""
    seq = items(frame, mode)
    item = next((i for i in seq if i.id == item_id), None)
    if item is None or item_id == before_id:
        return
    seq.remove(item)
    anchor = next((i for i in seq if i.id == before_id), None) if before_id else None
    seq.insert(seq.index(anchor) if anchor else len(seq), item)


# ---------------------------------------------------------------------------- hitboxes & points across frames
def copy_markers_to(project: Project, source: Frame, mode: str, targets: Iterable[Frame], replace: bool = False) -> int:
    """Copy the source's hitboxes or points into other frames (fresh ids). Returns how many frames got them."""
    data = [item.to_dict() for item in items(source, mode)]
    count = 0
    for frame in targets:
        if frame.id == source.id:
            continue
        if replace:
            if mode == "hitboxes":
                frame.collision_rects = []
            else:
                frame.control_points = []
        insert_items(project, frame, mode, data)
        count += 1
    return count


# ---------------------------------------------------------------------------- types
def types(project: Project, mode: str) -> List[Any]:
    return project.collision_types if mode == "hitboxes" else project.point_types


def add_type(project: Project, mode: str, name: Optional[str] = None) -> Any:
    existing = types(project, mode)
    used = {t.name for t in existing}
    base = name or ("Hitbox" if mode == "hitboxes" else "Point")
    label, n = base, 2
    while label in used:
        label = f"{base} {n}"
        n += 1
    colour = TYPE_COLOURS[len(existing) % len(TYPE_COLOURS)]
    if mode == "hitboxes":
        new = CollisionType(id=generate_id("ctype"), name=label, color=colour)
    else:
        new = PointType(id=generate_id("ptype"), name=label, color=colour)
    existing.append(new)
    return new


def type_usage(project: Project, mode: str, type_id: str) -> Tuple[int, int]:
    """(items, frames) of a hitbox / point type."""
    count = frames = 0
    for frame in project.frames:
        hits = sum(1 for item in items(frame, mode) if item.type_id == type_id)
        if hits:
            count += hits
            frames += 1
    return count, frames


def delete_type(project: Project, mode: str, type_id: str) -> int:
    """Remove a type and every hitbox / point of it; one default type always remains."""
    if mode == "hitboxes":
        removed = project.remove_collision_type(type_id)
        project.ensure_default_collision_type()
    else:
        removed = project.remove_point_type(type_id)
        project.ensure_default_point_type()
    return removed


def empty_hitboxes(project: Project) -> int:
    """Boxes without an area (a click in the old editor's hitbox mode left one behind every time)."""
    return sum(1 for f in project.frames for cr in f.collision_rects if cr.rect[2] <= 0 or cr.rect[3] <= 0)


def remove_empty_hitboxes(project: Project) -> int:
    removed = 0
    for frame in project.frames:
        keep = [cr for cr in frame.collision_rects if cr.rect[2] > 0 and cr.rect[3] > 0]
        removed += len(frame.collision_rects) - len(keep)
        frame.collision_rects = keep
    return removed


def content_size(project: Project, frame: Frame, mapping: Optional[ModuleMapping]) -> Optional[Tuple[int, int]]:
    box = frame_bounds(project, frame, mapping, include_markers=False) if frame.fmodules else None
    if box is None:
        return None
    return (int(round(box[2] - box[0])), int(round(box[3] - box[1])))
