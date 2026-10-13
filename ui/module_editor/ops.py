"""Modules tab operations without wx: sheets, module geometry, pivots, slicing and sprite detection."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from models import ImageAsset, Module, Project, generate_id

Rect = Tuple[int, int, int, int]  # x, y, w, h

SHAPES_KEY = "@shapes"    # pseudo sheet: vector shape modules
ORPHANS_KEY = "@orphans"  # pseudo sheet: image modules whose image is gone

SHAPE_TYPES: List[Tuple[str, str]] = [
    ("MD_RECT", "Rectangle"),
    ("MD_FILL_RECT", "Filled rectangle"),
    ("MD_ARC", "Ellipse / arc"),
    ("MD_FILL_ARC", "Filled ellipse / pie"),
    ("MD_TRIANGLE", "Triangle"),
    ("MD_FILL_TRIANGLE", "Filled triangle"),
    ("MD_LINE", "Line"),
    ("MD_MARKER", "Marker (X)"),
]
SHAPE_LABELS = dict(SHAPE_TYPES)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")

# Pivot presets: fractions of the module size (0 = left/top edge, 1 = right/bottom edge).
PIVOT_PRESETS: List[Tuple[str, Tuple[float, float]]] = [
    ("Top left", (0.0, 0.0)), ("Top", (0.5, 0.0)), ("Top right", (1.0, 0.0)),
    ("Left", (0.0, 0.5)), ("Centre", (0.5, 0.5)), ("Right", (1.0, 0.5)),
    ("Bottom left", (0.0, 1.0)), ("Bottom", (0.5, 1.0)), ("Bottom right", (1.0, 1.0)),
]


# ---------------------------------------------------------------------------- rects
def normalize(rect: Sequence[float]) -> Rect:
    x, y, w, h = (int(round(v)) for v in rect)
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return (x, y, w, h)


def rect_from_points(a: Tuple[float, float], b: Tuple[float, float]) -> Rect:
    """Pixel rect covering both points (each point is a pixel; the rect includes the end pixel)."""
    x0, x1 = sorted((int(a[0] // 1), int(b[0] // 1)))
    y0, y1 = sorted((int(a[1] // 1), int(b[1] // 1)))
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def overlaps(a: Rect, b: Rect) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def contains(rect: Rect, x: float, y: float) -> bool:
    return rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]


def snap(value: float, step: int) -> int:
    return int(round(value / step) * step) if step > 1 else int(round(value))


def reading_order(rects: Iterable[Rect]) -> List[Rect]:
    """Top-to-bottom rows, left to right within a row (rows group rects whose tops are close)."""
    rects = sorted(rects, key=lambda r: (r[1], r[0]))
    rows: List[List[Rect]] = []
    for r in rects:
        if rows and r[1] < rows[-1][0][1] + max(1, rows[-1][0][3]) // 2:
            rows[-1].append(r)
        else:
            rows.append([r])
    return [r for row in rows for r in sorted(row, key=lambda r: r[0])]


# ---------------------------------------------------------------------------- sheets
def sheet_key(module: Module, project: Optional[Project] = None) -> str:
    if module.type != "MD_IMAGE":
        return SHAPES_KEY
    if project is not None and project.get_image(module.image_id) is None:
        return ORPHANS_KEY
    return module.image_id


def modules_of_sheet(project: Project, key: Optional[str]) -> List[Module]:
    if key is None:
        return []
    return [m for m in project.modules if sheet_key(m, project) == key]


def has_orphans(project: Project) -> bool:
    return any(sheet_key(m, project) == ORPHANS_KEY for m in project.modules)


def image_label(asset: ImageAsset) -> str:
    return os.path.basename(asset.file_path) or asset.id


def image_missing(asset: ImageAsset) -> bool:
    return not asset.file_path or not os.path.exists(asset.file_path)


def scan_image_files(folder: str, recursive: bool) -> List[str]:
    paths: List[str] = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs.sort(key=str.lower)
            paths.extend(os.path.join(root, f) for f in sorted(files, key=str.lower) if f.lower().endswith(IMAGE_EXTENSIONS))
    else:
        for entry in sorted(os.scandir(folder), key=lambda e: e.name.lower()):
            if entry.is_file() and entry.name.lower().endswith(IMAGE_EXTENSIONS):
                paths.append(entry.path)
    return paths


def remove_image(project: Project, image_id: str) -> int:
    """Remove an image and its modules; returns how many modules went with it."""
    before = len(project.modules)
    project.images = [img for img in project.images if img.id != image_id]
    project.modules = [m for m in project.modules if not (m.type == "MD_IMAGE" and m.image_id == image_id)]
    return before - len(project.modules)


# ---------------------------------------------------------------------------- usage
def part_counts(project: Project) -> Dict[str, int]:
    """How many frame parts use each module."""
    counts: Dict[str, int] = {}
    for frame in project.frames:
        for fm in frame.fmodules:
            if fm.ref_type == "module":
                counts[fm.ref_id] = counts.get(fm.ref_id, 0) + 1
    return counts


def usage(project: Project, module_ids: Iterable[str]) -> Tuple[int, int, int]:
    """(parts, frames, mapping entries) that reference any of the modules."""
    ids = set(module_ids)
    parts = frames = 0
    for frame in project.frames:
        hits = sum(1 for fm in frame.fmodules if fm.ref_type == "module" and fm.ref_id in ids)
        if hits:
            parts += hits
            frames += 1
    entries = sum(
        1 for mapping in project.mappings for src, dst in mapping.map.items() if src in ids or (dst is not None and dst in ids)
    )
    return parts, frames, entries


def frames_using(project: Project, module_id: str) -> List[str]:
    return [f.id for f in project.frames if any(fm.ref_type == "module" and fm.ref_id == module_id for fm in f.fmodules)]


def describe_usage(parts: int, frames: int, entries: int = 0, objects: int = 0) -> str:
    bits = []
    if parts:
        bits.append(f"{parts} part{'s' if parts != 1 else ''} in {frames} frame{'s' if frames != 1 else ''}")
    if entries:
        bits.append(f"{entries} mapping entr{'ies' if entries != 1 else 'y'}")
    if objects:
        bits.append(f"{objects} timeline object{'s' if objects != 1 else ''}")
    return ", ".join(bits) if bits else "not used"


def scene_uses(project: Project, module_ids: Iterable[str]) -> int:
    """Timeline objects that show one of the modules directly (as their source or at a key)."""
    from ui.scene_editor.ops import source_uses

    return source_uses(project, "module", module_ids)


# ---------------------------------------------------------------------------- names
def unique_name(base: str, used: Set[str]) -> str:
    base = (base or "Module").strip() or "Module"
    name, n = base, 2
    while name in used:
        name = f"{base} ({n})"
        n += 1
    used.add(name)
    return name


def numbered_names(prefix: str, count: int, used: Set[str]) -> List[str]:
    """prefix_01, prefix_02, … skipping names already taken."""
    width = max(2, len(str(count)))
    names, n = [], 1
    while len(names) < count:
        name = f"{prefix}_{n:0{width}d}"
        if name not in used:
            used.add(name)
            names.append(name)
        n += 1
    return names


def sheet_prefix(asset: Optional[ImageAsset]) -> str:
    if asset is None:
        return "module"
    base = os.path.splitext(os.path.basename(asset.file_path))[0]
    return re.sub(r"\s+", "_", base.strip()) or "module"


# ---------------------------------------------------------------------------- pivots
def visual_pivot(module: Module) -> Tuple[int, int]:
    """Pivot relative to the rect as it lies on the sheet (packed modules are stored rotated)."""
    px, py = module.pivot
    if getattr(module, "rotated", False):
        return (module.rect[2] - py, px)
    return (px, py)


def logical_pivot(module: Module, visual: Tuple[int, int]) -> Tuple[int, int]:
    vx, vy = int(visual[0]), int(visual[1])
    if getattr(module, "rotated", False):
        return (vy, module.rect[2] - vx)
    return (vx, vy)


def pivot_on_sheet(module: Module) -> Tuple[int, int]:
    vx, vy = visual_pivot(module)
    return (module.rect[0] + vx, module.rect[1] + vy)


def preset_pivot(width: int, height: int, fractions: Tuple[float, float]) -> Tuple[int, int]:
    """Pivot for a preset: edges sit on the module border (a bottom pivot stands the sprite on y = 0)."""
    fx, fy = fractions
    return (int(width * fx) if fx != 0.5 else width // 2, int(height * fy) if fy != 0.5 else height // 2)


def apply_pivot_preset(module: Module, fractions: Tuple[float, float]) -> None:
    w, h = module.rect[2], module.rect[3]
    if getattr(module, "rotated", False):
        w, h = h, w  # the preset is meant for the module as it is used, not as it is packed
    module.pivot = preset_pivot(w, h, fractions)


def matching_preset(module: Module) -> Optional[str]:
    w, h = module.rect[2], module.rect[3]
    if getattr(module, "rotated", False):
        w, h = h, w
    for name, fractions in PIVOT_PRESETS:
        if tuple(module.pivot) == preset_pivot(w, h, fractions):
            return name
    return None


# ---------------------------------------------------------------------------- create / edit
def default_shape_params(shape_type: str) -> List[float]:
    if shape_type in ("MD_ARC", "MD_FILL_ARC"):
        return [0.0, 360.0]
    if shape_type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
        return [50.0, 0.0, 100.0, 100.0, 0.0, 100.0]
    if shape_type == "MD_LINE":
        return [0.0, 0.0, 100.0, 100.0]
    return []


def shape_points(module: Module) -> List[float]:
    """Triangle / line corner points in percent of the size (older projects stored pixels)."""
    p = [float(v) for v in module.params]
    w, h = max(1, module.rect[2]), max(1, module.rect[3])
    if module.type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
        if len(p) >= 6:
            return p[:6]
        if len(p) == 4:
            return [0.0, 0.0, p[0] / w * 100, p[1] / h * 100, p[2] / w * 100, p[3] / h * 100]
        return default_shape_params(module.type)
    if module.type == "MD_LINE":
        if len(p) >= 4:
            return p[:4]
        if len(p) >= 2:
            return [0.0, 0.0, p[0] / w * 100, p[1] / h * 100]
        return default_shape_params(module.type)
    return p


def create_image_module(project: Project, image_id: str, rect: Rect, name: Optional[str] = None,
                        pivot: Optional[Tuple[int, int]] = None, index: Optional[int] = None) -> Module:
    rect = normalize(rect)
    used = {m.name for m in project.modules}
    module = Module(
        id=generate_id("mod"),
        name=name if name and name not in used else unique_name(name or sheet_prefix(project.get_image(image_id)), used),
        image_id=image_id,
        rect=rect,
        pivot=pivot if pivot is not None else (rect[2] // 2, rect[3] // 2),
    )
    _insert(project, module, index)
    return module


def create_shape_module(project: Project, shape_type: str, rect: Rect, color: Tuple[int, int, int],
                        name: Optional[str] = None, index: Optional[int] = None) -> Module:
    rect = normalize(rect)
    used = {m.name for m in project.modules}
    module = Module(
        id=generate_id("mod"),
        name=unique_name(name or SHAPE_LABELS.get(shape_type, "Shape"), used),
        image_id="missing",
        rect=rect,
        pivot=(rect[2] // 2, rect[3] // 2),
        type=shape_type,
        color=tuple(color),  # type: ignore[arg-type]
        params=default_shape_params(shape_type),
    )
    _insert(project, module, index)
    return module


def _insert(project: Project, module: Module, index: Optional[int]) -> None:
    if index is None or not (0 <= index <= len(project.modules)):
        project.modules.append(module)
    else:
        project.modules.insert(index, module)


def duplicate_modules(project: Project, module_ids: Sequence[str], offset: Tuple[int, int] = (0, 0)) -> List[Module]:
    """Copies placed right after each original (same rect shifted by ``offset``)."""
    used = {m.name for m in project.modules}
    copies: List[Module] = []
    for module_id in module_ids:
        source = project.get_module(module_id)
        if source is None:
            continue
        data = source.to_dict()
        data["id"] = generate_id("mod")
        data["name"] = unique_name(f"{source.name} copy", used)
        copy = Module.from_dict(data)
        x, y, w, h = copy.rect
        copy.rect = (x + offset[0], y + offset[1], w, h)
        project.modules.insert(project.modules.index(source) + 1, copy)
        copies.append(copy)
    return copies


def delete_modules(project: Project, module_ids: Iterable[str]) -> int:
    ids = set(module_ids)
    before = len(project.modules)
    project.modules = [m for m in project.modules if m.id not in ids]
    return before - len(project.modules)


def remove_module_uses(project: Project, module_ids: Iterable[str]) -> Tuple[int, int, int]:
    """Remove what shows these modules: frame parts, mapping entries (a module replaced by one of them shows its
    original again) and scene objects / key swaps (they show nothing). Returns (parts, mapping entries, scene uses)."""
    from ui.scene_editor.ops import clear_sources

    ids = set(module_ids)
    parts = 0
    for frame in project.frames:
        kept = [fm for fm in frame.fmodules if not (fm.ref_type == "module" and fm.ref_id in ids)]
        parts += len(frame.fmodules) - len(kept)
        frame.fmodules = kept
    entries = 0
    for mapping in project.mappings:
        for source in [src for src, dst in mapping.map.items() if src in ids or (dst is not None and dst in ids)]:
            del mapping.map[source]
            entries += 1
    return parts, entries, clear_sources(project, "module", ids)


def move_modules(project: Project, module_ids: Iterable[str], dx: int, dy: int) -> None:
    for module_id in module_ids:
        module = project.get_module(module_id)
        if module is not None:
            x, y, w, h = module.rect
            module.rect = (x + dx, y + dy, w, h)


def resize_keeping_pivot(module: Module, rect: Rect, pivot_on_sheet_xy: Tuple[int, int]) -> None:
    """New rect; the pivot stays on the same sheet pixel (clamped to the new rect's border)."""
    rect = normalize(rect)
    module.rect = rect
    vx = min(max(pivot_on_sheet_xy[0] - rect[0], 0), rect[2])
    vy = min(max(pivot_on_sheet_xy[1] - rect[1], 0), rect[3])
    module.pivot = logical_pivot(module, (vx, vy))


# ---------------------------------------------------------------------------- pixels
def opaque_bbox(sheet: Any, rect: Rect, threshold: int = 0) -> Optional[Rect]:
    """Bounding box of the pixels with alpha above ``threshold`` inside ``rect`` of an RGBA sheet."""
    x, y, w, h = normalize(rect)
    left, top = max(0, x), max(0, y)
    right, bottom = min(sheet.width, x + w), min(sheet.height, y + h)
    if right <= left or bottom <= top:
        return None
    alpha = sheet.crop((left, top, right, bottom)).getchannel("A")
    if threshold > 0:
        alpha = alpha.point([255 if v > threshold else 0 for v in range(256)])
    box = alpha.getbbox()
    if not box:
        return None
    return (left + box[0], top + box[1], box[2] - box[0], box[3] - box[1])


def grid_rects(width: int, height: int, tile_w: int, tile_h: int, offset_x: int = 0, offset_y: int = 0,
               gap_x: int = 0, gap_y: int = 0) -> List[Rect]:
    """Whole tiles of a regular grid inside the image."""
    rects: List[Rect] = []
    tile_w, tile_h = max(1, int(tile_w)), max(1, int(tile_h))
    y = int(offset_y)
    while y + tile_h <= height:
        x = int(offset_x)
        while x + tile_w <= width:
            rects.append((x, y, tile_w, tile_h))
            x += tile_w + max(0, int(gap_x))
        y += tile_h + max(0, int(gap_y))
    return rects


def detect_regions(alpha: bytes, width: int, height: int, threshold: int = 10) -> List[Rect]:
    """Bounding boxes of 8-connected opaque regions (alpha > threshold), in reading order.

    Works on runs of opaque pixels per row (union-find), so big sheets take milliseconds.
    """
    table = bytes(1 if v > threshold else 0 for v in range(256))
    mask = bytes(alpha).translate(table)
    run_pattern = re.compile(rb"\x01+")
    parent: List[int] = []
    runs: List[Tuple[int, int, int]] = []  # (y, x0, x1) inclusive

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    previous: List[int] = []
    for y in range(height):
        row = mask[y * width:(y + 1) * width]
        current: List[int] = []
        j = 0
        for match in run_pattern.finditer(row):
            x0, x1 = match.start(), match.end() - 1
            rid = len(runs)
            runs.append((y, x0, x1))
            parent.append(rid)
            while j < len(previous) and runs[previous[j]][2] < x0 - 1:
                j += 1
            k = j
            while k < len(previous) and runs[previous[k]][1] <= x1 + 1:
                a, b = find(rid), find(previous[k])
                if a != b:
                    parent[max(a, b)] = min(a, b)
                k += 1
            current.append(rid)
        previous = current

    boxes: Dict[int, List[int]] = {}
    for rid, (y, x0, x1) in enumerate(runs):
        root = find(rid)
        box = boxes.get(root)
        if box is None:
            boxes[root] = [x0, y, x1, y]
        else:
            box[0] = min(box[0], x0)
            box[2] = max(box[2], x1)
            box[3] = max(box[3], y)
    return reading_order((b[0], b[1], b[2] - b[0] + 1, b[3] - b[1] + 1) for b in boxes.values())


def merge_regions(rects: Sequence[Rect], gap: int) -> List[Rect]:
    """Union rects that overlap or lie within ``gap`` pixels of each other, until nothing changes."""
    current = [tuple(r) for r in rects]
    changed = True
    while changed:
        changed = False
        merged: List[Tuple[int, int, int, int]] = []
        used = [False] * len(current)
        for i, a in enumerate(current):
            if used[i]:
                continue
            x0, y0, x1, y1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
            for j in range(i + 1, len(current)):
                if used[j]:
                    continue
                b = current[j]
                if x0 - gap < b[0] + b[2] and b[0] < x1 + gap and y0 - gap < b[1] + b[3] and b[1] < y1 + gap:
                    x0, y0 = min(x0, b[0]), min(y0, b[1])
                    x1, y1 = max(x1, b[0] + b[2]), max(y1, b[1] + b[3])
                    used[j] = True
                    changed = True
            merged.append((x0, y0, x1 - x0, y1 - y0))
        current = merged
    return reading_order(current)  # type: ignore[arg-type]


def add_sheet_modules(project: Project, image_id: str, rects: Sequence[Rect], replace: bool) -> List[Module]:
    """Create modules for ``rects`` on a sheet. Replace drops the sheet's modules first; otherwise rects
    that overlap an existing module of the sheet are skipped. Returns the new modules."""
    asset = project.get_image(image_id)
    if replace:
        project.modules = [m for m in project.modules if not (m.type == "MD_IMAGE" and m.image_id == image_id)]
        existing: List[Rect] = []
    else:
        existing = [tuple(m.rect) for m in project.modules if m.type == "MD_IMAGE" and m.image_id == image_id]  # type: ignore[misc]
    rects = [normalize(r) for r in rects if not any(overlaps(normalize(r), e) for e in existing)]
    names = numbered_names(sheet_prefix(asset), len(rects), {m.name for m in project.modules})
    created = []
    for rect, name in zip(rects, names):
        created.append(create_image_module(project, image_id, rect, name=name))
    return created
