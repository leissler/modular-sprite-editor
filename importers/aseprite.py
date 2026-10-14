"""Aseprite import: a ``.aseprite`` / ``.ase`` file, or a sprite sheet with its JSON (Aseprite's export, or
TexturePacker's hash / array layout).

An Aseprite file is read and every frame flattened the way Aseprite exports it (visible layers, cel and layer
opacity, Aseprite's normal blending); the distinct pictures are cut to their pixels and packed into one PNG next to
the file (``<name>.sheet.png``, never over an existing file). A sheet with JSON keeps its PNG: its rectangles become the
modules. Either way every frame becomes a frame showing one module, every tag an animation (direction and repeats as
playback, durations as holds at the tick rate that fits them best), and Auto Modularize can cut the pictures into
shared parts afterwards. The origin is the bottom centre of the canvas, unless the JSON gives one (a frame's
``pivot``, or this editor's ``meta.origin``). Whatever is left out is listed in ``Project.load_notes``.
"""

from __future__ import annotations

import json
import math
import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from importers.notes import Notes
from models import AFrame, Animation, FModule, Project, generate_id

RGBA = Tuple[int, int, int, int]


# ---------------------------------------------------------------------------- reading .aseprite files
@dataclass
class AseLayer:
    name: str
    flags: int
    kind: int  # 0 image, 1 group, 2 tilemap
    level: int
    blend: int
    opacity: int
    parent: Optional[int] = None

    @property
    def visible(self) -> bool:
        return bool(self.flags & 1)

    @property
    def background(self) -> bool:
        return bool(self.flags & 8)

    @property
    def reference(self) -> bool:
        return bool(self.flags & 64)


@dataclass
class AseCel:
    layer: int
    x: int
    y: int
    opacity: int
    z_index: int
    image: Any  # PIL RGBA, or None (tilemaps)


@dataclass
class AseTag:
    name: str
    first: int
    last: int
    direction: int  # 0 forward, 1 reverse, 2 ping-pong, 3 ping-pong reverse
    repeat: int  # 0 = forever


@dataclass
class AseDocument:
    width: int
    height: int
    depth: int
    layers: List[AseLayer]
    frames: List[Any]  # flattened RGBA images, the canvas' size
    durations: List[int]  # ms
    tags: List[AseTag]
    notes: Notes = field(default_factory=Notes)


def _string(data: bytes, pos: int) -> Tuple[str, int]:
    (length,) = struct.unpack_from("<H", data, pos)
    return data[pos + 2:pos + 2 + length].decode("utf-8", "replace"), pos + 2 + length


def _mul_un8(a: int, b: int) -> int:
    """Aseprite's rounded a × b / 255."""
    t = a * b + 0x80
    return ((t >> 8) + t) >> 8


def read_aseprite(path: str) -> AseDocument:
    """Read an Aseprite file and flatten every frame (raises ValueError when it is not one)."""
    from PIL import Image

    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < 128:
        raise ValueError("not an Aseprite file (too short)")
    (_size, magic, frame_count, width, height, depth, flags, _speed, _a, _b, transparent) = struct.unpack_from(
        "<IHHHHHIHIIB", data, 0)
    if magic != 0xA5E0:
        raise ValueError("not an Aseprite file")
    if depth not in (8, 16, 32):
        raise ValueError(f"unknown colour depth {depth}")
    notes = Notes()
    opacity_valid = bool(flags & 1)
    layers: List[AseLayer] = []
    palette: List[RGBA] = [(0, 0, 0, 255)] * 256
    tags: List[AseTag] = []
    cels_per_frame: List[List[AseCel]] = []
    raw_cels: Dict[Tuple[int, int], AseCel] = {}  # (frame, layer) -> cel, for linked cels
    durations: List[int] = []
    new_palette = False  # files with the new palette chunk carry the old one only for old readers
    pos = 128
    for frame_index in range(frame_count):
        frame_size, frame_magic, old_chunks, duration = struct.unpack_from("<IHHH", data, pos)
        if frame_magic != 0xF1FA:
            raise ValueError(f"frame {frame_index + 1} is damaged")
        (new_chunks,) = struct.unpack_from("<I", data, pos + 12)
        chunks = new_chunks if new_chunks else old_chunks
        durations.append(max(1, duration))
        cels: List[AseCel] = []
        chunk_pos = pos + 16
        for _ in range(chunks):
            chunk_size, chunk_type = struct.unpack_from("<IH", data, chunk_pos)
            body = data[chunk_pos + 6:chunk_pos + chunk_size]
            chunk_pos += chunk_size
            if chunk_type == 0x2004:  # layer
                lflags, kind, level, _w, _h, blend = struct.unpack_from("<HHHHHH", body, 0)
                name, _end = _string(body, 16)
                layers.append(AseLayer(name, lflags, kind, level, blend, body[12] if opacity_valid else 255))
            elif chunk_type == 0x2005:  # cel
                cel = _read_cel(body, depth, palette, transparent, layers, raw_cels, frame_index, notes)
                if cel is not None:
                    raw_cels[(frame_index, cel.layer)] = cel
                    cels.append(cel)
            elif chunk_type == 0x2018:  # tags
                (count,) = struct.unpack_from("<H", body, 0)
                tag_pos = 10
                for _t in range(count):
                    first, last, direction, repeat = struct.unpack_from("<HHBH", body, tag_pos)
                    name, tag_pos = _string(body, tag_pos + 17)
                    tags.append(AseTag(name, first, last, direction, repeat))
            elif chunk_type == 0x2019:  # palette
                new_palette = True
                _count, first, last = struct.unpack_from("<III", body, 0)
                entry_pos = 20
                for index in range(first, last + 1):
                    (entry_flags,) = struct.unpack_from("<H", body, entry_pos)
                    r, g, b, a = body[entry_pos + 2:entry_pos + 6]
                    entry_pos += 6
                    if entry_flags & 1:
                        _name, entry_pos = _string(body, entry_pos)
                    if 0 <= index < 256:
                        palette[index] = (r, g, b, a)
            elif chunk_type in (0x0004, 0x0011) and not new_palette:  # old palettes (0x0011: 6 bits a channel)
                _read_old_palette(body, palette, 4 if chunk_type == 0x0011 else 1)
        cels_per_frame.append(cels)
        pos += frame_size

    # Which layer is in which group (child levels in file order), visible only if every group around it is.
    stack: List[int] = []
    for index, layer in enumerate(layers):
        del stack[layer.level:]
        layer.parent = stack[-1] if stack else None
        stack.append(index)

    def shown(index: int) -> bool:
        layer: Optional[AseLayer] = layers[index] if 0 <= index < len(layers) else None
        while layer is not None:
            if not layer.visible:
                return False
            layer = layers[layer.parent] if layer.parent is not None else None
        return True

    def opacity(index: int) -> int:
        value = 255
        layer: Optional[AseLayer] = layers[index] if 0 <= index < len(layers) else None
        while layer is not None:
            value = _mul_un8(value, layer.opacity)
            layer = layers[layer.parent] if layer.parent is not None else None
        return value

    for layer in layers:
        if layer.blend != 0 and layer.kind == 0 and layer.visible and not layer.reference:
            notes.add("Layers with a blend mode other than Normal are drawn with Normal", layer.name)
        if layer.reference and layer.visible:
            notes.add("Reference layers are left out (Aseprite leaves them out of exports too)", layer.name)
    frames = []
    for cels in cels_per_frame:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        order = sorted((c for c in cels if c.image is not None), key=lambda c: (c.layer + c.z_index, c.z_index))
        for cel in order:
            if 0 <= cel.layer < len(layers) and shown(cel.layer) and not layers[cel.layer].reference \
                    and layers[cel.layer].kind == 0:
                _blend_normal(canvas, cel.image, cel.x, cel.y, _mul_un8(cel.opacity, opacity(cel.layer)))
        frames.append(canvas)
    return AseDocument(width, height, depth, layers, frames, durations, tags, notes)


def _read_old_palette(body: bytes, palette: List[RGBA], scale: int) -> None:
    (packets,) = struct.unpack_from("<H", body, 0)
    pos, index = 2, 0
    for _ in range(packets):
        index += body[pos]
        count = body[pos + 1] or 256
        pos += 2
        for _c in range(count):
            r, g, b = body[pos:pos + 3]
            pos += 3
            if index < 256:
                palette[index] = (min(255, r * scale), min(255, g * scale), min(255, b * scale), 255)
            index += 1


def _read_cel(body: bytes, depth: int, palette: List[RGBA], transparent: int, layers: List[AseLayer],
              raw_cels: Dict[Tuple[int, int], AseCel], frame_index: int, notes: Notes) -> Optional[AseCel]:
    from PIL import Image

    layer, x, y, opacity, kind, z_index = struct.unpack_from("<HhhBHh", body, 0)
    if kind == 1:  # linked: the same cel as in another frame
        (linked,) = struct.unpack_from("<H", body, 16)
        source = raw_cels.get((linked, layer))
        return AseCel(layer, source.x, source.y, source.opacity, z_index, source.image) if source else None
    if kind == 3:
        notes.add("Tilemap layers are left out", layers[layer].name if layer < len(layers) else str(layer))
        return AseCel(layer, x, y, opacity, z_index, None)
    if kind not in (0, 2):
        return None
    w, h = struct.unpack_from("<HH", body, 16)
    pixels = body[20:] if kind == 0 else zlib.decompress(body[20:])
    if depth == 32:
        image = Image.frombytes("RGBA", (w, h), pixels[:w * h * 4])
    elif depth == 16:
        image = Image.frombytes("LA", (w, h), pixels[:w * h * 2]).convert("RGBA")
    else:
        indexed = Image.frombytes("P", (w, h), pixels[:w * h])
        entries = list(palette)
        background = 0 <= layer < len(layers) and layers[layer].background
        if not background and 0 <= transparent < 256:
            entries[transparent] = (0, 0, 0, 0)
        indexed.putpalette([v for entry in entries for v in entry], rawmode="RGBA")
        image = indexed.convert("RGBA")
    return AseCel(layer, x, y, opacity, z_index, image)


def _blend_normal(canvas: Any, image: Any, x: int, y: int, opacity: int) -> None:
    """Draw ``image`` at (x, y) the way Aseprite's normal blend does (rgba_blender_normal)."""
    left, top = max(0, x), max(0, y)
    right, bottom = min(canvas.size[0], x + image.size[0]), min(canvas.size[1], y + image.size[1])
    if right <= left or bottom <= top or opacity <= 0:
        return
    source = image.crop((left - x, top - y, right - x, bottom - y))
    alphas = source.getchannel("A").getextrema()
    if opacity == 255 and alphas[0] in (0, 255) and alphas[1] in (0, 255):
        canvas.paste(source, (left, top), source.getchannel("A"))  # opaque pixel art: exact and fast
        return
    region = canvas.crop((left, top, right, bottom))
    back = bytearray(region.tobytes())
    src = source.tobytes()
    for i in range(0, len(src), 4):
        sa = src[i + 3]
        if sa == 0:
            continue
        sa = _mul_un8(sa, opacity)
        ba = back[i + 3]
        if ba == 0:
            back[i:i + 3] = src[i:i + 3]
            back[i + 3] = sa
            continue
        ra = sa + ba - _mul_un8(ba, sa)
        for c in range(3):
            b = back[i + c]
            back[i + c] = b + (src[i + c] - b) * sa // ra if src[i + c] >= b else b - (b - src[i + c]) * sa // ra
        back[i + 3] = ra
    from PIL import Image

    canvas.paste(Image.frombytes("RGBA", region.size, bytes(back)), (left, top))


# ---------------------------------------------------------------------------- building the project
TIMING_TOLERANCE_MS = 2.0  # far below a video frame (16.7 ms): nobody sees it


def tick_rate_for(durations_ms: Sequence[int]) -> int:
    """The tick rate (1–60 a second) for these durations: of the rates that hit every duration within
    TIMING_TOLERANCE_MS, the one with the fewest ticks (simple holds), then the closest; else the closest of all."""
    best: Optional[Tuple[Any, ...]] = None
    for rate in range(1, 61):
        holds = _holds(durations_ms, rate)
        error = max((abs(h * 1000.0 / rate - d) for h, d in zip(holds, durations_ms)), default=0.0)
        score = (0, sum(holds), error, rate) if error <= TIMING_TOLERANCE_MS else (1, error, rate)
        if best is None or score < best:
            best = score
    return int(best[-1]) if best else 10


def _holds(durations_ms: Sequence[int], rate: int) -> List[int]:
    return [max(1, int(math.floor(d * rate / 1000.0 + 0.5))) for d in durations_ms]


def _playback(direction: int, repeat: int) -> Tuple[str, int, bool]:
    """(playback type, repeat count, steps reversed) for an Aseprite tag."""
    if direction in (2, 3):
        return "ping_pong", repeat, direction == 3
    if direction == 1:
        return ("backward", repeat, False) if repeat != 1 else ("forward", 0, True)
    if repeat == 1:
        return "forward", 0, False
    return "loop", repeat, False


def _unique_path(path: str) -> str:
    stem, ext = os.path.splitext(path)
    candidate, number = path, 2
    while os.path.exists(candidate):
        candidate = f"{stem}_{number}{ext}"
        number += 1
    return candidate


def parse_aseprite(path: str, sheet_path: Optional[str] = None) -> Project:
    """A project from an Aseprite file: the flattened frames packed into ``sheet_path`` (default
    ``<name>.sheet.png`` next to the file, numbered rather than written over an existing file)."""
    from PIL import Image

    from optimization import pack_rects

    doc = read_aseprite(path)
    notes = doc.notes
    stem = os.path.splitext(os.path.basename(path))[0]
    project = Project()
    project.name = stem
    origin = (doc.width // 2, doc.height)  # the bottom centre: feet on the origin
    pictures: List[Tuple[Any, int, int]] = []  # (trimmed image, left, top) per Aseprite frame (None: empty)
    unique: Dict[Tuple[bytes, Tuple[int, int]], int] = {}
    order: List[int] = []
    for image in doc.frames:
        box = image.getbbox()
        if box is None:
            pictures.append((None, 0, 0))
            order.append(-1)
            continue
        cut = image.crop(box)
        key = (cut.tobytes(), cut.size)
        if key not in unique:
            unique[key] = len(unique)
        pictures.append((cut, box[0], box[1]))
        order.append(unique[key])
    images = {index: None for index in range(len(unique))}
    for (cut, _l, _t), index in zip(pictures, order):
        if index >= 0 and images[index] is None:
            images[index] = cut

    names = _frame_names(doc)
    if images:
        rects = [(img.size[0] + 1, img.size[1] + 1, index, None) for index, img in images.items()]
        side = max(64, int(math.ceil(math.sqrt(sum(w * h for w, h, _i, _n in rects)) * 1.5)) + 64)
        packed = pack_rects(rects, max(side, 16384), max(side, 16384), allow_rotation=False) or []
        places = {index: (rect.x + 1, rect.y + 1) for rect, (_w, _h, index, _n) in packed}
        width = max(x + images[i].size[0] for i, (x, _y) in places.items()) + 1
        height = max(y + images[i].size[1] for i, (_x, y) in places.items()) + 1
        sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for index, (x, y) in places.items():
            sheet.paste(images[index], (x, y))
        target = sheet_path or _unique_path(os.path.join(os.path.dirname(os.path.abspath(path)), f"{stem}.sheet.png"))
        sheet.save(target)
        asset = project.create_image(target, width, height)
        modules = {}
        for index, (x, y) in places.items():
            first = order.index(index)
            img = images[index]
            modules[index] = project.create_module(names[first], asset.id, (x, y, img.size[0], img.size[1]), (0, 0))
        notes.add(f"The frames are packed into {os.path.basename(target)} next to the Aseprite file "
                  "(Auto Modularize can cut them into shared parts)")
    frame_ids = []
    for number, ((cut, left, top), index) in enumerate(zip(pictures, order)):
        frame = project.create_frame(names[number])
        if index >= 0:
            frame.fmodules.append(FModule(id=generate_id("fm"), ref_type="module", ref_id=modules[index].id,
                                          position=(left - origin[0], top - origin[1])))
        frame_ids.append(frame.id)
    _animations(project, frame_ids, doc.durations,
                [(t.name, t.first, t.last, t.direction, t.repeat) for t in doc.tags], stem, notes)
    project.load_notes = notes.lines()
    return project


def _frame_names(doc: AseDocument) -> List[str]:
    names = [f"Frame {i + 1}" for i in range(len(doc.frames))]
    for tag in doc.tags:
        for number, index in enumerate(range(tag.first, min(tag.last, len(names) - 1) + 1)):
            if names[index].startswith("Frame "):
                names[index] = f"{tag.name} {number + 1}"
    return names


def _animations(project: Project, frame_ids: List[str], durations: List[int],
                tags: List[Tuple[str, int, int, int, int]], stem: str, notes: Notes) -> None:
    """One animation per tag (or one of everything without tags)."""
    if not tags and frame_ids:
        tags = [(stem, 0, len(frame_ids) - 1, 0, 0)]
    for name, first, last, direction, repeat in tags:
        last = min(last, len(frame_ids) - 1)
        if first > last or first < 0:
            notes.add("Tags outside the frames are left out", name)
            continue
        indices = list(range(first, last + 1))
        kind, loops, reverse = _playback(direction, repeat)
        if reverse:
            indices.reverse()
        rate = tick_rate_for([durations[i] for i in indices])
        holds = _holds([durations[i] for i in indices], rate)
        exact = all(abs(h * 1000.0 / rate - durations[i]) <= TIMING_TOLERANCE_MS for h, i in zip(holds, indices))
        if not exact:
            notes.add("Durations rounded to whole ticks", f"{name} at {rate} ticks/s")
        project.animations.append(Animation(
            id=generate_id("anim"), name=name, playback_type=kind, loop_count=loops, fps=rate,
            aframes=[AFrame(frame_id=frame_ids[i], duration_frames=h) for i, h in zip(indices, holds)]))


# ---------------------------------------------------------------------------- sheets with JSON
def parse_sheet_json(path: str) -> Project:
    """A project from a sprite sheet and its JSON (Aseprite or TexturePacker, hash or array; this editor's export
    too): the PNG stays, its rectangles become the modules."""
    from PIL import Image

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "frames" not in data:
        raise ValueError("not a sprite sheet JSON (no \"frames\")")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    base = os.path.dirname(os.path.abspath(path))
    image_name = str(meta.get("image") or os.path.splitext(os.path.basename(path))[0] + ".png")
    image_path = os.path.normpath(os.path.join(base, image_name))
    if not os.path.isfile(image_path):
        raise ValueError(f"the sheet image {image_name} is not next to the JSON")
    with Image.open(image_path) as image:
        width, height = image.size
    raw = data["frames"]
    entries = list(raw.items()) if isinstance(raw, dict) else [(str(f.get("filename", i)), f) for i, f in enumerate(raw)]
    notes = Notes()
    stem = os.path.splitext(os.path.basename(path))[0]
    project = Project()
    project.name = stem
    asset = project.create_image(image_path, width, height)
    stored_origin = meta.get("origin") if isinstance(meta.get("origin"), dict) else None
    modules: Dict[Tuple[int, int, int, int], Any] = {}
    frame_ids: List[str] = []
    durations: List[int] = []
    for name, entry in entries:
        rect = entry.get("frame") or {}
        x, y, w, h = (int(rect.get(k, 0)) for k in ("x", "y", "w", "h"))
        label = os.path.splitext(str(name))[0]
        frame = project.create_frame(label)
        frame_ids.append(frame.id)
        durations.append(max(1, int(entry.get("duration", 100) or 100)))
        if entry.get("rotated"):
            notes.add("Frames stored turned in the sheet are left empty (export the sheet without rotation)", label)
            continue
        if w <= 0 or h <= 0:
            continue
        source = entry.get("spriteSourceSize") or {"x": 0, "y": 0}
        size = entry.get("sourceSize") or {"w": w, "h": h}
        pivot = entry.get("pivot")
        if isinstance(pivot, dict):
            origin = (float(pivot.get("x", 0.5)) * int(size.get("w", w)), float(pivot.get("y", 1.0)) * int(size.get("h", h)))
        elif stored_origin:
            origin = (float(stored_origin.get("x", 0)), float(stored_origin.get("y", 0)))
        else:
            origin = (int(size.get("w", w)) // 2, int(size.get("h", h)))
        key = (x, y, w, h)
        if key not in modules:
            modules[key] = project.create_module(label, asset.id, key, (0, 0))
        frame.fmodules.append(FModule(id=generate_id("fm"), ref_type="module", ref_id=modules[key].id,
                                      position=(int(round(int(source.get("x", 0)) - origin[0])),
                                                int(round(int(source.get("y", 0)) - origin[1])))))
    directions = {"forward": 0, "reverse": 1, "pingpong": 2, "pingpong_reverse": 3}
    tags = []
    for tag in meta.get("frameTags") or []:
        if isinstance(tag, dict):
            try:
                repeat = int(tag.get("repeat", 0) or 0)
            except (TypeError, ValueError):
                repeat = 0
            tags.append((str(tag.get("name", "Animation")), int(tag.get("from", 0)), int(tag.get("to", 0)),
                         directions.get(str(tag.get("direction", "forward")), 0), repeat))
    _animations(project, frame_ids, durations, tags, stem, notes)
    project.load_notes = notes.lines()
    return project
