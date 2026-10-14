"""Sprite sheets and PNG sequences for other engines and tools (wx-free).

The animations' steps (and, if asked, the frames no animation shows) are drawn the way the editor draws them (the
shared compositor, with a mapping and a palette swap), cut to their pixels, packed into one PNG, and described in the
format an engine reads:

- JSON in the Aseprite / TexturePacker "hash" layout: every step a frame entry with its rectangle, where it sits on a
  canvas shared by all of them (``spriteSourceSize`` / ``sourceSize``), its duration, and the origin as ``pivot``;
  every animation a ``frameTags`` entry (direction, repeats);
- a Godot 4 SpriteFrames resource (``.tres``): one animation per animation (speed = tick rate, each step's duration
  = its hold), every texture padded to the shared canvas so the origin stays put;
- a Unity texture import file (``.png.meta``): the sheet cut into sprites, each pivot on the editor's origin.

Steps keep their offsets, flips and turns (what the Animations tab shows); identical pictures are stored once.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import compositor
import playback
from models import AFrame, Animation, Frame, ModuleMapping, PaletteSwap, Project
from safe_files import write_text_atomically

FORMATS = ("json", "godot", "unity")
DIRECTIONS = {"backward": "reverse", "ping_pong": "pingpong"}  # anything else plays forward


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


@dataclass
class Tag:
    name: str
    first: int  # entry indices, inclusive
    last: int
    direction: str  # "forward", "reverse" or "pingpong"
    repeats: int  # 0 = forever
    fps: int
    playback: str


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
    for anim in anims:
        first = len(entries)
        rate = playback.tick_rate(anim)
        for index, af in enumerate(anim.aframes):
            frame = project.get_frame(af.frame_id)
            if frame is None:
                continue
            used_frames.add(frame.id)
            a, b = step_transform(af)
            image, left, top = _drawn(project, frame, mapping, swap, a, b, caches)
            name = f"{anim.name} {index}"
            hold = playback.hold(af)
            entries.append(Entry(name, cell_for(image, left, top, f"{safe_name(anim.name)}_{index}"),
                                 max(1, int(round(hold * 1000.0 / rate))), hold))
        if len(entries) > first:
            tags.append(Tag(anim.name, first, len(entries) - 1, DIRECTIONS.get(playback.playback_of(anim), "forward"),
                            max(0, int(anim.loop_count or 0)) if playback.playback_of(anim) != "forward" else 1,
                            rate, playback.playback_of(anim)))
        else:
            notes.append(f"'{anim.name}' has no steps that show a frame: left out.")
    if loose_frames:
        for frame in project.frames:
            if frame.id not in used_frames:
                image, left, top = _drawn(project, frame, mapping, swap, ((1.0, 0.0), (0.0, 1.0)), (0.0, 0.0), caches)
                entries.append(Entry(frame.name, cell_for(image, left, top, safe_name(frame.name)),
                                     int(round(1000.0 / playback.DEFAULT_TICK_RATE))))

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


def godot_spriteframes(sheet: Sheet, image_name: str) -> str:
    """A Godot 4 SpriteFrames resource; textures padded to the shared canvas (AtlasTexture margins)."""
    left, top, width, height = sheet.canvas
    lines = [
        f'[gd_resource type="SpriteFrames" load_steps={len(sheet.cells) + 2} format=3]',
        "",
        f'; Made by the Modular Sprite Editor. Every texture is {width}×{height} px with the editor\'s origin at '
        f'({-left}, {-top}): on a centred AnimatedSprite2D set offset = ({width / 2.0 + left:g}, {height / 2.0 + top:g}).',
        "",
        f'[ext_resource type="Texture2D" path="{image_name}" id="1_sheet"]',
        "",
    ]
    for index, cell in enumerate(sheet.cells):
        w, h = cell.size
        lines += [
            f'[sub_resource type="AtlasTexture" id="AtlasTexture_{index}"]',
            'atlas = ExtResource("1_sheet")',
            f"region = Rect2({cell.x}, {cell.y}, {w}, {h})",
            f"margin = Rect2({cell.left - left}, {cell.top - top}, {width - w}, {height - h})",
            "",
        ]
    animations = []
    for tag in sheet.tags:
        entries = sheet.entries[tag.first:tag.last + 1]
        order = list(range(len(entries)))
        if tag.direction == "reverse":
            order.reverse()
        elif tag.direction == "pingpong" and len(order) > 2:
            order = order + order[-2:0:-1]
        frames = ",\n".join(
            "{\n" f'"duration": {float(entries[i].hold):g},\n' f'"texture": SubResource("AtlasTexture_{entries[i].cell}")\n' "}"
            for i in order)
        animations.append(
            "{\n" f'"frames": [{frames}],\n' f'"loop": {"true" if tag.repeats == 0 else "false"},\n'
            f'"name": &"{_godot_string(tag.name)}",\n' f'"speed": {float(tag.fps):g}\n' "}")
    lines += ["[resource]", "animations = [" + ", ".join(animations) + "]", ""]
    return "\n".join(lines)


def _godot_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def unity_meta(sheet: Sheet, seed: str) -> str:
    """A Unity TextureImporter (.png.meta): sprite mode Multiple, point filtering, every cell a sprite whose pivot is
    the editor's origin (Unity counts y from the bottom)."""
    def guid(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    sheet_h = sheet.image.size[1]
    names: Dict[str, int] = {}
    sprites = []
    for index, cell in enumerate(sheet.cells):
        w, h = cell.size
        name = cell.name
        names[name] = names.get(name, 0) + 1
        if names[name] > 1:
            name = f"{name}_{names[name]}"
        pivot_x = -cell.left / float(w)
        pivot_y = (cell.top + h) / float(h)
        internal = int(guid(f"{seed}/{index}")[:15], 16)
        sprites.append("\n".join([
            "    - serializedVersion: 2",
            f"      name: {name}",
            "      rect:",
            "        serializedVersion: 2",
            f"        x: {cell.x}",
            f"        y: {sheet_h - cell.y - h}",
            f"        width: {w}",
            f"        height: {h}",
            "      alignment: 9",
            f"      pivot: {{x: {pivot_x:.6g}, y: {pivot_y:.6g}}}",
            "      border: {x: 0, y: 0, z: 0, w: 0}",
            "      outline: []",
            "      physicsShape: []",
            "      tessellationDetail: 0",
            "      bones: []",
            f"      spriteID: {guid(f'{seed}/sprite/{index}')}",
            f"      internalID: {internal}",
            "      vertices: []",
            "      indices: ",
            "      edges: []",
            "      weights: []",
        ]))
    return "\n".join([
        "fileFormatVersion: 2",
        f"guid: {guid(seed)}",
        "TextureImporter:",
        "  serializedVersion: 12",
        "  mipmaps:",
        "    enableMipMap: 0",
        "  isReadable: 0",
        "  textureFormat: 1",
        "  maxTextureSize: 8192",
        "  textureSettings:",
        "    serializedVersion: 2",
        "    filterMode: 0",
        "    aniso: 1",
        "    mipBias: 0",
        "    wrapU: 1",
        "    wrapV: 1",
        "    wrapW: 1",
        "  nPOTScale: 0",
        "  spriteMode: 2",
        "  spriteExtrude: 1",
        "  spriteMeshType: 0",
        "  alignment: 9",
        "  spritePivot: {x: 0.5, y: 0.5}",
        "  spritePixelsToUnits: 100",
        "  alphaUsage: 1",
        "  alphaIsTransparency: 1",
        "  textureType: 8",
        "  textureShape: 1",
        "  platformSettings:",
        "  - serializedVersion: 3",
        "    buildTarget: DefaultTexturePlatform",
        "    maxTextureSize: 8192",
        "    textureCompression: 0",
        "  spriteSheet:",
        "    serializedVersion: 2",
        "    sprites:",
        *sprites,
        "    outline: []",
        "    physicsShape: []",
        "  spritePackingTag: ",
        "  userData: ",
        "  assetBundleName: ",
        "  assetBundleVariant: ",
        "",
    ])


def export_sheet(project: Project, png_path: str, fmt: str = "json", mapping: Optional[ModuleMapping] = None,
                 swap: Optional[PaletteSwap] = None, animations: Optional[Sequence[Animation]] = None,
                 loose_frames: bool = False, padding: int = 1, scale: int = 1) -> Dict[str, Any]:
    """Write the sheet PNG and its data file next to it (``name.json``, ``name.tres`` or ``name.png.meta``).
    Returns a report: the files written, counts and notes."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    sheet = build_sheet(project, mapping, swap, animations, loose_frames, padding)
    if scale > 1:
        sheet = _scaled(sheet, scale)
    image_name = os.path.basename(png_path)
    sheet.image.save(png_path)
    stem = os.path.splitext(png_path)[0]
    if fmt == "json":
        data_path = stem + ".json"
        write_text_atomically(data_path, json.dumps(sheet_json(sheet, image_name), indent=1))
    elif fmt == "godot":
        data_path = stem + ".tres"
        write_text_atomically(data_path, godot_spriteframes(sheet, image_name))
    else:
        data_path = png_path + ".meta"
        write_text_atomically(data_path, unity_meta(sheet, os.path.abspath(png_path)))
    return {"image": png_path, "data": data_path, "cells": len(sheet.cells), "entries": len(sheet.entries),
            "animations": len(sheet.tags), "size": sheet.image.size, "notes": sheet.notes}


def _scaled(sheet: Sheet, scale: int) -> Sheet:
    """The sheet with every pixel ``scale`` × ``scale`` (nearest neighbour; rectangles and origins scale along)."""
    from PIL import Image

    image = sheet.image.resize((sheet.image.size[0] * scale, sheet.image.size[1] * scale), Image.NEAREST)
    cells = [Cell(c.image.resize((c.size[0] * scale, c.size[1] * scale), Image.NEAREST), c.left * scale,
                  c.top * scale, c.name, c.x * scale, c.y * scale) for c in sheet.cells]
    left, top, width, height = sheet.canvas
    return Sheet(image, cells, sheet.entries, sheet.tags, (left * scale, top * scale, width * scale, height * scale),
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
