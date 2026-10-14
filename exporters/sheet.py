"""Sprite sheets and PNG sequences for other engines and tools (wx-free).

The animations' steps (and, if asked, the frames no animation shows) are drawn the way the editor draws them (the
shared compositor, with a mapping and a palette swap), cut to their pixels, packed into one PNG, and described in the
format an engine reads:

- JSON in the Aseprite / TexturePacker "hash" layout: every step a frame entry with its rectangle, where it sits on a
  canvas shared by all of them (``spriteSourceSize`` / ``sourceSize``), its duration, and the origin as ``pivot``;
  every animation a ``frameTags`` entry (direction, repeats);
- for Godot 4 (``exporters/godot.py``): a SpriteFrames resource (``.tres``, one animation per animation, every
  texture padded to the shared canvas so the origin stays put) and a scene (``.tscn``) that plays the clips with an
  AnimationPlayer, hitboxes and points included;
- for Unity (``exporters/unity.py``): the texture's import file (``.png.meta``: the sheet cut into sprites, each pivot
  on the editor's origin), an animation clip per clip, an Animator Controller and a prefab, hitboxes and points
  included.

Steps keep their offsets, flips and turns (what the Animations tab shows); identical pictures are stored once. Each
step also carries its frame's hitboxes and points, moved like the picture (as the SGDK export moves them), and its
events. An animation becomes one clip per engine, or two when it plays an intro before its loop (``clips``): the
clips play the steps exactly as the editor does (``playback.Player``), loop-from, repeat counts and follow-ups
included.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import compositor
import playback
from models import AFrame, Animation, Frame, ModuleMapping, PaletteSwap, Project
from safe_files import write_text_atomically

FORMATS = ("json", "godot", "unity")
DIRECTIONS = {"backward": "reverse", "ping_pong": "pingpong"}  # anything else plays forward


@dataclass(frozen=True)
class Box:
    """A hitbox of a step, in sheet pixels from the origin (after the step's flips, turn and offset)."""
    kind: str  # the hitbox type's name ("Hurt")
    role: str
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Point:
    """A point of a step: the pixel it marks, in sheet pixels from the origin (``size``: a pixel's side on the
    sheet, more than 1 when scaled), so its centre is (x + size / 2, y + size / 2)."""
    kind: str
    role: str
    x: float
    y: float
    size: float = 1.0


@dataclass
class Cell:
    """One picture on the sheet: its pixels (cut to what shows) and where their top-left sits from the origin."""
    image: Any
    left: int
    top: int
    name: str
    x: int = 0  # place on the sheet
    y: int = 0

    @property
    def size(self) -> Tuple[int, int]:
        return self.image.size


@dataclass
class Entry:
    """What an engine reads as one frame: an animation step (or a frame on its own)."""
    name: str
    cell: int
    duration_ms: int
    hold: int = 1  # ticks (at the animation's tick rate)
    boxes: Tuple[Box, ...] = ()
    points: Tuple[Point, ...] = ()
    events: Tuple[Tuple[str, int], ...] = ()  # (event name, value) fired when the step starts


@dataclass
class Tag:
    name: str  # unique among the tags (engines key animations by name)
    first: int  # entry indices, inclusive
    last: int
    direction: str  # "forward", "reverse" or "pingpong"
    repeats: int  # 0 = forever
    fps: int
    playback: str
    loop_start: int = 0  # loop: the tag's entry later passes start at
    follow_up: Optional[str] = None  # the tag that plays when this one ends (if it can end)


@dataclass
class Clip:
    """An engine animation: the entries it shows in play order, whether it loops, and the clip after it."""
    name: str  # unique among the clips
    tag: int  # index in Sheet.tags
    entries: List[int]
    loops: bool
    next: Optional[str] = None

    def times(self, sheet: "Sheet") -> List[float]:
        """When each entry starts, in seconds, and the clip's length last."""
        rate = float(sheet.tags[self.tag].fps)
        out, ticks = [], 0
        for index in self.entries:
            out.append(ticks / rate)
            ticks += sheet.entries[index].hold
        return out + [ticks / rate]


@dataclass
class Sheet:
    image: Any
    cells: List[Cell]
    entries: List[Entry]
    tags: List[Tag]
    canvas: Tuple[int, int, int, int]  # (left, top, width, height) around the origin, holding every cell
    notes: List[str] = field(default_factory=list)


def step_transform(af: AFrame) -> Tuple[compositor.Matrix, compositor.Vector]:
    """A step's transform (flip, then turn, then offset), as the Animations tab draws it."""
    a = compositor.mat_mul(compositor.rotation_matrix(float(af.rotation_degrees)),
                           compositor.flip_matrix(bool(af.flip_x), bool(af.flip_y)))
    return a, (float(af.offset[0]), float(af.offset[1]))


def _drawn(project: Project, frame: Frame, mapping: Optional[ModuleMapping], swap: Optional[PaletteSwap],
           a: compositor.Matrix, b: compositor.Vector, caches: Tuple[dict, dict]) -> Tuple[Any, int, int]:
    """The frame's pixels cut to what shows, and where their top-left lands (a 1×1 clear picture when empty)."""
    image, left, top, _boxes = compositor.render_frame(project, frame, mapping, a, b, caches[0], caches[1], swap)
    image = image.convert("RGBA")
    box = image.getbbox()
    if box is None:
        from PIL import Image

        return Image.new("RGBA", (1, 1), (0, 0, 0, 0)), int(left), int(top)
    return image.crop(box), int(left) + box[0], int(top) + box[1]


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip()).strip("_") or "sprite"


def unique(name: str, taken: Dict[str, int]) -> str:
    """``name`` (stripped; "Animation" when empty), or with " 2", " 3"... when an earlier one has it."""
    base = name.strip() or "Animation"
    found, number = base, 1
    while found in taken:
        number += 1
        found = f"{base} {number}"
    taken[found] = 1
    return found


def step_markers(project: Project, frame: Frame, a: compositor.Matrix,
                 b: compositor.Vector) -> Tuple[Tuple[Box, ...], Tuple[Point, ...]]:
    """The frame's own hitboxes and points under a step's transform: a box's corners move, a point marks the pixel
    its pixel's centre lands in (as the SGDK export's ``_frame_markers``)."""
    def move(x: float, y: float) -> Tuple[float, float]:
        tx, ty = compositor.mat_vec_mul(a, (float(x), float(y)))
        return tx + float(b[0]), ty + float(b[1])

    kinds = {t.id: t.name for t in project.collision_types}
    boxes = []
    for cr in frame.collision_rects:
        x, y, w, h = (int(v) for v in cr.rect)
        if w <= 0 or h <= 0:
            continue
        corners = [move(x, y), move(x + w, y + h)]
        x0, x1 = sorted(round(c[0]) for c in corners)
        y0, y1 = sorted(round(c[1]) for c in corners)
        boxes.append(Box(kinds.get(cr.type_id, "Hitbox"), str(cr.role or "").strip(), x0, y0, x1 - x0, y1 - y0))
    point_kinds = {t.id: t.name for t in project.point_types}
    points = []
    for cp in frame.control_points:
        px, py = move(cp.x + 0.5, cp.y + 0.5)
        points.append(Point(point_kinds.get(cp.type_id, "Point"), str(cp.role or "").strip(),
                            math.floor(px), math.floor(py)))
    return tuple(boxes), tuple(points)


def cycle(anim: Animation) -> List[int]:
    """Step indices of one pass in the order they play (what engines without these modes get)."""
    count = len(anim.aframes)
    forward = list(range(count))
    kind = playback.playback_of(anim)
    if kind == "backward":
        return forward[::-1]
    if kind == "ping_pong" and count > 2:
        return forward + forward[-2:0:-1]
    return forward


def build_sheet(project: Project, mapping: Optional[ModuleMapping] = None, swap: Optional[PaletteSwap] = None,
                animations: Optional[Sequence[Animation]] = None, loose_frames: bool = False,
                padding: int = 1) -> Sheet:
    """Draw and pack the steps of ``animations`` (default: all), plus the frames none of them shows when
    ``loose_frames``."""
    from PIL import Image

    anims = list(project.animations if animations is None else animations)
    caches: Tuple[dict, dict] = ({}, {})
    cells: List[Cell] = []
    seen: Dict[Tuple[str, int, int], int] = {}
    entries: List[Entry] = []
    tags: List[Tag] = []
    notes: List[str] = []

    def cell_for(image: Any, left: int, top: int, name: str) -> int:
        key = (hashlib.sha1(image.tobytes() + repr(image.size).encode()).hexdigest(), left, top)
        if key not in seen:
            seen[key] = len(cells)
            cells.append(Cell(image, left, top, name))
        return seen[key]

    used_frames = set()
    event_names = {e.id: e.name for e in project.event_types}
    tag_of: Dict[str, int] = {}  # animation id -> its tag
    taken: Dict[str, int] = {}
    for anim in anims:
        first = len(entries)
        rate = playback.tick_rate(anim)
        entry_of_step: List[int] = []  # step -> the tag's entry it is (or the next one, for a step left out)
        for index, af in enumerate(anim.aframes):
            entry_of_step.append(len(entries) - first)
            frame = project.get_frame(af.frame_id)
            if frame is None:
                continue
            used_frames.add(frame.id)
            a, b = step_transform(af)
            image, left, top = _drawn(project, frame, mapping, swap, a, b, caches)
            name = f"{anim.name} {index}"
            hold = playback.hold(af)
            boxes, points = step_markers(project, frame, a, b)
            events = tuple((event_names[e.type_id], int(e.value)) for e in af.events if e.type_id in event_names)
            entries.append(Entry(name, cell_for(image, left, top, f"{safe_name(anim.name)}_{index}"),
                                 max(1, int(round(hold * 1000.0 / rate))), hold, boxes, points, events))
        count = len(entries) - first
        if count:
            kind = playback.playback_of(anim)
            start = playback.loop_start(anim)
            tag_of[anim.id] = len(tags)
            tags.append(Tag(unique(anim.name, taken), first, len(entries) - 1, DIRECTIONS.get(kind, "forward"),
                            max(0, int(anim.loop_count or 0)) if kind != "forward" else 1, rate, kind,
                            min(entry_of_step[start], count - 1) if start else 0))
        else:
            notes.append(f"'{anim.name}' has no steps that show a frame: left out.")
    for anim in anims:  # follow-ups, once every tag has its name
        follow = tag_of.get(anim.next_animation_id or "")
        if anim.id in tag_of and follow is not None and playback.can_finish(anim):
            tags[tag_of[anim.id]].follow_up = tags[follow].name
    if loose_frames:
        identity = ((1.0, 0.0), (0.0, 1.0))
        for frame in project.frames:
            if frame.id not in used_frames:
                image, left, top = _drawn(project, frame, mapping, swap, identity, (0.0, 0.0), caches)
                boxes, points = step_markers(project, frame, identity, (0.0, 0.0))
                entries.append(Entry(frame.name, cell_for(image, left, top, safe_name(frame.name)),
                                     int(round(1000.0 / playback.DEFAULT_TICK_RATE)), 1, boxes, points))

    if not cells:
        return Sheet(Image.new("RGBA", (1, 1), (0, 0, 0, 0)), [], [], [], (0, 0, 1, 1), notes + ["Nothing to export."])
    _place(cells, padding)
    width = max(c.x + c.size[0] for c in cells) + padding
    height = max(c.y + c.size[1] for c in cells) + padding
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for cell in cells:
        sheet.paste(cell.image, (cell.x, cell.y))
    left = min(c.left for c in cells)
    top = min(c.top for c in cells)
    right = max(c.left + c.size[0] for c in cells)
    bottom = max(c.top + c.size[1] for c in cells)
    return Sheet(sheet, cells, entries, tags, (left, top, right - left, bottom - top), notes)


def clips(sheet: Sheet) -> List[Clip]:
    """The clips the engines play, as ``playback.Player`` plays each animation: an animation that loops forever is
    one looping clip of its cycle, or an intro clip followed by a looping one when later passes start at its loop
    step; one that ends (once, or after its repeats) is one clip of every step it shows, followed by its follow-up's
    clip. Ping-pong turns without showing its end steps twice."""
    out: List[Clip] = []
    taken: Dict[str, int] = {tag.name: 1 for tag in sheet.tags}
    for index, tag in enumerate(sheet.tags):
        steps = list(range(tag.first, tag.last + 1))
        count, repeats = len(steps), tag.repeats
        if tag.playback == "forward":
            out.append(Clip(tag.name, index, steps, False, tag.follow_up))
            continue
        if tag.playback == "backward":
            cycle, first = steps[::-1], steps[::-1]
        elif tag.playback == "ping_pong" and count > 1:
            back = steps[-2::-1]
            cycle, first = steps[1:] + back, steps + back  # later passes start one step on: the turn shows once
        elif tag.playback == "ping_pong":
            out.append(Clip(tag.name, index, steps, True))  # one step: it never turns, so it never ends
            continue
        else:  # loop
            cycle, first = steps[tag.loop_start:], steps
        if repeats:
            out.append(Clip(tag.name, index, first + cycle * (repeats - 1), False, tag.follow_up))
        elif tag.playback == "loop" and tag.loop_start:
            loop = unique(f"{tag.name} loop", taken)
            out.append(Clip(tag.name, index, steps[:tag.loop_start], False, loop))
            out.append(Clip(loop, index, cycle, True))
        elif tag.playback == "ping_pong":
            out.append(Clip(tag.name, index, steps + back[:-1], True))  # 0..n-1, n-2..1, and round again
        else:
            out.append(Clip(tag.name, index, cycle, True))
    return out


def slot_names(markers: Sequence[Any]) -> List[str]:
    """A name for each hitbox or point of a step that stays the same from step to step: its type and role
    ("Hurt head"), and " 2", " 3"... for more of the same kind. Engines animate the slot of that name."""
    taken: Dict[str, int] = {}
    names = []
    for marker in markers:
        base = re.sub(r'[/:.@%"\\]+', "_", f"{marker.kind} {marker.role}".strip()) or "Slot"
        names.append(unique(base, taken))
    return names


def slots(sheet: Sheet, kind: str) -> List[str]:
    """Every slot name of ``kind`` ("boxes" or "points") the entries use, in the order they first appear."""
    found: Dict[str, None] = {}
    for entry in sheet.entries:
        for name in slot_names(getattr(entry, kind)):
            found.setdefault(name, None)
    return list(found)


def _place(cells: List[Cell], padding: int) -> None:
    """Pack the cells (no turning: engines read the rectangles as they are), ``padding`` clear pixels around each."""
    from optimization import pack_rects

    rects = [(c.size[0] + padding, c.size[1] + padding, index, None) for index, c in enumerate(cells)]
    side = max(64, int(math.ceil(math.sqrt(sum(w * h for w, h, _i, _n in rects)) * 1.5)) + 64)
    packed = pack_rects(rects, max(side, 16384), max(side, 16384), allow_rotation=False)
    if packed is None:  # far beyond any sheet size an engine takes: one row per cell
        y = padding
        for cell in cells:
            cell.x, cell.y = padding, y
            y += cell.size[1] + padding
        return
    for rect, (_w, _h, index, _none) in packed:
        cells[index].x, cells[index].y = rect.x + padding, rect.y + padding


# ---------------------------------------------------------------------------- formats
def sheet_json(sheet: Sheet, image_name: str) -> Dict[str, Any]:
    """The Aseprite / TexturePacker hash layout (frames by name, meta with frameTags)."""
    left, top, width, height = sheet.canvas
    frames: Dict[str, Any] = {}
    for entry in sheet.entries:
        cell = sheet.cells[entry.cell]
        w, h = cell.size
        frames[entry.name] = {
            "frame": {"x": cell.x, "y": cell.y, "w": w, "h": h},
            "rotated": False,
            "trimmed": (w, h) != (width, height),
            "spriteSourceSize": {"x": cell.left - left, "y": cell.top - top, "w": w, "h": h},
            "sourceSize": {"w": width, "h": height},
            "pivot": {"x": round(-left / float(width), 6), "y": round(-top / float(height), 6)},
            "duration": entry.duration_ms,
        }
        # The editor's game data, in pixels from the origin (readers of the Aseprite layout skip what they don't know).
        if entry.boxes:
            frames[entry.name]["hitboxes"] = [{"type": b.kind, "role": b.role, "x": b.x, "y": b.y, "w": b.w, "h": b.h}
                                              for b in entry.boxes]
        if entry.points:
            frames[entry.name]["points"] = [{"type": p.kind, "role": p.role, "x": p.x, "y": p.y} for p in entry.points]
        if entry.events:
            frames[entry.name]["events"] = [{"name": name, "value": value} for name, value in entry.events]
    tags = []
    for tag in sheet.tags:
        item: Dict[str, Any] = {"name": tag.name, "from": tag.first, "to": tag.last, "direction": tag.direction,
                                "color": "#000000ff"}
        if tag.repeats:
            item["repeat"] = str(tag.repeats)
        tags.append(item)
    return {
        "frames": frames,
        "meta": {
            "app": "Modular Sprite Editor",
            "version": "1.0",
            "image": image_name,
            "format": "RGBA8888",
            "size": {"w": sheet.image.size[0], "h": sheet.image.size[1]},
            "scale": "1",
            "frameTags": tags,
            "origin": {"x": -left, "y": -top},  # where the editor's origin sits on the shared canvas
        },
    }


def export_sheet(project: Project, png_path: str, fmt: str = "json", mapping: Optional[ModuleMapping] = None,
                 swap: Optional[PaletteSwap] = None, animations: Optional[Sequence[Animation]] = None,
                 loose_frames: bool = False, padding: int = 1, scale: int = 1) -> Dict[str, Any]:
    """Write the sheet PNG and the files an engine reads next to it: ``name.json``; for Godot ``name.tres``,
    ``name.tscn`` (and ``name.gd`` when steps have events); for Unity ``name.png.meta``, the clips in
    ``name Animations/``, ``name.controller`` and ``name.prefab`` (each with its meta). Returns a report: the files
    written (``data`` is the main one), counts and notes."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    sheet = build_sheet(project, mapping, swap, animations, loose_frames, padding)
    if scale > 1:
        sheet = _scaled(sheet, scale)
    image_name = os.path.basename(png_path)
    sheet.image.save(png_path)
    stem = os.path.splitext(png_path)[0]
    files: List[str] = []

    def write(path: str, text: str) -> None:
        write_text_atomically(path, text)
        files.append(path)

    if fmt == "json":
        data_path = stem + ".json"
        write(data_path, json.dumps(sheet_json(sheet, image_name), indent=1))
    elif fmt == "godot":
        from exporters import godot

        data_path = stem + ".tres"
        write(data_path, godot.spriteframes(sheet, image_name))
        script = None
        if any(entry.events for entry in sheet.entries):
            script = os.path.basename(stem) + ".gd"
            write(stem + ".gd", godot.SCRIPT)
        write(stem + ".tscn", godot.scene(sheet, os.path.basename(stem), os.path.basename(data_path), script))
    else:
        from exporters import unity

        data_path = png_path + ".meta"
        unity.export(sheet, png_path, lambda path, text: write(path, text))
    return {"image": png_path, "data": data_path, "files": files, "cells": len(sheet.cells),
            "entries": len(sheet.entries), "animations": len(sheet.tags), "clips": len(clips(sheet)),
            "size": sheet.image.size, "notes": sheet.notes}


def _scaled(sheet: Sheet, scale: int) -> Sheet:
    """The sheet with every pixel ``scale`` × ``scale`` (nearest neighbour; rectangles and origins scale along)."""
    from PIL import Image

    image = sheet.image.resize((sheet.image.size[0] * scale, sheet.image.size[1] * scale), Image.NEAREST)
    cells = [Cell(c.image.resize((c.size[0] * scale, c.size[1] * scale), Image.NEAREST), c.left * scale,
                  c.top * scale, c.name, c.x * scale, c.y * scale) for c in sheet.cells]
    entries = [replace(e, boxes=tuple(replace(b, x=b.x * scale, y=b.y * scale, w=b.w * scale, h=b.h * scale)
                                      for b in e.boxes),
                       points=tuple(replace(p, x=p.x * scale, y=p.y * scale, size=p.size * scale) for p in e.points))
               for e in sheet.entries]
    left, top, width, height = sheet.canvas
    return Sheet(image, cells, entries, sheet.tags, (left * scale, top * scale, width * scale, height * scale),
                 sheet.notes)


# ---------------------------------------------------------------------------- PNG sequences
def export_png_sequence(project: Project, anim: Animation, folder: str, mapping: Optional[ModuleMapping] = None,
                        swap: Optional[PaletteSwap] = None, per_tick: bool = False, scale: int = 1) -> List[str]:
    """One PNG per step (or per tick) of one pass of the animation, all on one canvas so the origin stays put:
    ``<name>_000.png``…. Returns the files written."""
    from PIL import Image

    caches: Tuple[dict, dict] = ({}, {})
    drawn = []
    for index in cycle(anim):
        af = anim.aframes[index]
        frame = project.get_frame(af.frame_id)
        if frame is None:
            continue
        a, b = step_transform(af)
        image, left, top = _drawn(project, frame, mapping, swap, a, b, caches)
        drawn.extend([(image, left, top)] * (playback.hold(af) if per_tick else 1))
    if not drawn:
        return []
    left = min(x for _i, x, _y in drawn)
    top = min(y for _i, _x, y in drawn)
    width = max(x + i.size[0] for i, x, _y in drawn) - left
    height = max(y + i.size[1] for i, _x, y in drawn) - top
    os.makedirs(folder, exist_ok=True)
    stem = safe_name(anim.name)
    digits = max(3, len(str(len(drawn) - 1)))
    paths = []
    for number, (image, x, y) in enumerate(drawn):
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.alpha_composite(image, (x - left, y - top))
        if scale > 1:
            canvas = canvas.resize((width * scale, height * scale), Image.NEAREST)
        path = os.path.join(folder, f"{stem}_{number:0{digits}d}.png")
        canvas.save(path)
        paths.append(path)
    return paths
