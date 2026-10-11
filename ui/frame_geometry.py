"""Where frame parts sit (wx-free): the bounds the editor canvas draws, hit-tests and flips parts with.

Nested frames are a geometric transform about their anchor (flip, then rotate); module parts rotate about
the module pivot. A module mapped to "hidden" (or missing) falls back to a 32 px box around the part's
position, so the part can still be selected.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from models import FModule, Frame, ModuleMapping, Project

Bounds = Tuple[float, float, float, float]  # x0, y0, x1, y1
FALLBACK_SIZE = 32


def orthogonal_cos_sin(degrees: float) -> Tuple[float, float]:
    """Exact cos/sin for 90° multiples (raw math.cos leaves 6e-17 residues that shift pixels)."""
    import math

    quarter = float(degrees) / 90.0
    if abs(quarter - round(quarter)) < 1e-9:
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(round(quarter)) % 4]
    rad = math.radians(float(degrees))
    return math.cos(rad), math.sin(rad)


def resolve_module_id(module_id: str, mapping: Optional[ModuleMapping]) -> Optional[str]:
    if mapping and module_id in mapping.map:
        return mapping.map[module_id]
    return module_id


def part_bounds(project: Project, fm: FModule, mapping: Optional[ModuleMapping], depth: int = 0) -> Bounds:
    """Axis-aligned bounds of a part in its frame's space."""
    if depth <= 32 and fm.ref_type == "module":
        ref_id = resolve_module_id(fm.ref_id, mapping)
        mod = project.get_module(ref_id) if ref_id else None
        if mod:
            w, h = mod.rect[2], mod.rect[3]
            if getattr(mod, "rotated", False):
                w, h = h, w
            px, py = mod.pivot
            cos_a, sin_a = orthogonal_cos_sin(fm.rotation_degrees)
            xs: List[float] = []
            ys: List[float] = []
            for cx, cy in ((-px, -py), (w - px, -py), (-px, h - py), (w - px, h - py)):
                xs.append(cx * cos_a - cy * sin_a)
                ys.append(cx * sin_a + cy * cos_a)
            return (min(xs) + fm.position[0], min(ys) + fm.position[1], max(xs) + fm.position[0], max(ys) + fm.position[1])
    elif depth <= 32 and fm.ref_type == "frame":
        ref_frame = project.get_frame(fm.ref_id)
        if ref_frame:
            cos_a, sin_a = orthogonal_cos_sin(fm.rotation_degrees)
            box: Optional[List[float]] = None
            for child in ref_frame.fmodules:
                cx0, cy0, cx1, cy1 = part_bounds(project, child, mapping, depth + 1)
                for px, py in ((cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1)):
                    if fm.flip_x:
                        px = -px
                    if fm.flip_y:
                        py = -py
                    rx = px * cos_a - py * sin_a
                    ry = px * sin_a + py * cos_a
                    if box is None:
                        box = [rx, ry, rx, ry]
                    else:
                        box = [min(box[0], rx), min(box[1], ry), max(box[2], rx), max(box[3], ry)]
            if box is not None:
                return (box[0] + fm.position[0], box[1] + fm.position[1], box[2] + fm.position[0], box[3] + fm.position[1])
    half = FALLBACK_SIZE / 2
    return (fm.position[0] - half, fm.position[1] - half, fm.position[0] + half, fm.position[1] + half)


def union(boxes: List[Bounds]) -> Optional[Bounds]:
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def frame_bounds(project: Project, frame: Frame, mapping: Optional[ModuleMapping], include_markers: bool = True) -> Optional[Bounds]:
    """Bounds of everything in a frame: parts and (optionally) hitboxes and points."""
    boxes = [part_bounds(project, fm, mapping) for fm in frame.fmodules]
    if include_markers:
        for cr in frame.collision_rects:
            x, y, w, h = cr.rect
            boxes.append((x, y, x + w, y + h))
        for cp in frame.control_points:
            boxes.append((cp.x, cp.y, cp.x + 1, cp.y + 1))
    return union(boxes)
