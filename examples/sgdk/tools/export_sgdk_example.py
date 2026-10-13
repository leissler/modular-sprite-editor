#!/usr/bin/env python3
"""Bake editor JSON into an SGDK example project (resources + binary data blob)."""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

# The repo root; for the packaged exporter (export_sgdk.exe) the folder it sits in, which holds the same
# examples/ layout, so the defaults below work there too.
if getattr(sys, "frozen", False):
    REPO_ROOT = Path(sys.executable).resolve().parent
else:
    REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import Frame, Module, ModuleMapping, Project, RetroAnimatorExporter, TimelineScene  # noqa: E402
import project_check  # noqa: E402
from project_check import Issue  # noqa: E402


Matrix2 = Tuple[Tuple[float, float], Tuple[float, float]]
Vec2 = Tuple[float, float]
Matrix2x3 = Tuple[float, float, float, float, float, float]
PartEntry = Tuple[int, int, int, int, int]


@dataclass(frozen=True)
class VariantMeta:
    tile_w: int
    tile_h: int
    first_piece: int
    piece_count: int


@dataclass(frozen=True)
class RenderFrameSpan:
    first_part: int
    part_count: int
    first_box: int = 0
    box_count: int = 0
    first_point: int = 0
    point_count: int = 0


PieceEntry = Tuple[int, int, int, int]  # (dx, dy, VDP size code, tile offset): one hardware sprite of a variant
BoxEntry = Tuple[int, int, int, int, int, int]  # (type, role, x, y, w, h)
PointEntry = Tuple[int, int, int, int]  # (type, role, x, y)


@dataclass(frozen=True)
class AnimRecord:
    first_step: int
    step_count: int
    fps: int
    playback: int
    loop_start: int = 0  # exported step index later loop passes start at
    next_animation: int = 0xFFFF  # animation index to continue with when this one ends (0xFFFF = none)
    loop_count: int = 0  # 0 = repeat forever


NO_ANIMATION = 0xFFFF
NO_ROLE = 0xFFFF
UNKNOWN_TYPE = 0xFF
# 2: step events, loop-from step, follow-up animation, repeat count
# 3: tiles, pieces and palette in the blob (VRAM-resident runtime, no SGDK sprite resources),
#    hitboxes and points per render frame, type and role names, sprite count and bounds per render frame
BLOB_VERSION = 3
BLOB_COUNT_FIELDS = 20
BLOB_SECTION_COUNT = 30
BLOB_HEADER_SIZE = 4 + 2 + 2 + BLOB_COUNT_FIELDS * 2 + 4 + BLOB_SECTION_COUNT * 4 + 4
SPRITE_BLOCK = 32  # largest Mega Drive sprite: 4×4 tiles (hardware_budget cuts parts the same way)
TILE = 8

# What the exporter writes into an SGDK project (paths relative to it).
BLOB_FILE = Path("res") / "gen" / "modsprite_blob.bin"
RESOURCE_FILE = Path("res") / "resources.res"
HEADER_FILE = Path("inc") / "modsprite_data.h"
DATA_C_FILE = Path("src") / "modsprite_data.c"
RESOURCE_LINE = 'BIN MS_BLOB "gen/modsprite_blob.bin" 2 2 0 NONE FALSE'
# Exporters before blob version 3 wrote one sprite sheet per variant (res/gen/var_0000.png ...) and a SPRITE line for
# each; an export removes those, and only those, from the game's folder.
LEGACY_VARIANT_FILE = re.compile(r"var_\d+\.png")
LEGACY_RESOURCE_LINE = re.compile(r'\s*SPRITE\s+MS_VAR_\d+\s+"gen/var_\d+\.png"')


def merged_resources(existing: Optional[str]) -> str:
    """The game's resource file with the blob's line in it: an earlier MS_BLOB line is replaced and older exporters'
    SPRITE lines are dropped; every other line (the game's own resources) stays as it is."""
    lines = [line for line in (existing.splitlines() if existing else []) if not LEGACY_RESOURCE_LINE.match(line)]
    blob_lines = [i for i, line in enumerate(lines) if line.split()[:2] == ["BIN", "MS_BLOB"]]
    if blob_lines:
        lines[blob_lines[0]] = RESOURCE_LINE
        lines = [line for i, line in enumerate(lines) if i not in blob_lines[1:]]
    else:
        lines.append(RESOURCE_LINE)
    return "\n".join(lines) + "\n"


def _event_symbols(names: Sequence[str], prefix: str = "MS_EVENT_", fallback: str = "EVENT") -> List[str]:
    """C identifiers for names: MS_EVENT_HIT_ON, unique, never starting with a digit (Check Project warns about
    names that clash)."""
    return project_check.c_symbols(names, prefix, fallback)


@dataclass(frozen=True)
class SceneRecord:
    first_sample: int
    sample_count: int
    fps: int
    duration_ticks: int
    loop: int


class SGDKBakeContext:
    def __init__(self, project: Project, mappings: List[Optional[ModuleMapping]], output_demo_dir: Path) -> None:
        self.project = project
        self.mappings = mappings
        self.mapping = mappings[0] if mappings else None
        self.mapping_key = self.mapping.id if self.mapping else "none"
        self.output_demo_dir = output_demo_dir
        self.output_gen_dir = output_demo_dir / "res" / "gen"

        self.full_image_cache: Dict[str, Any] = {}
        self.module_cache: Dict[str, Any] = {}

        self.variant_lookup: Dict[Tuple[int, int, str], int] = {}
        self.variants: List[VariantMeta] = []
        self.pieces: List[PieceEntry] = []
        self.piece_lists: Dict[Tuple[int, int, int], Tuple[int, int]] = {}  # (variant, hflip, vflip) -> (first, count)
        self.tile_data = bytearray()
        self.piece_tiles_lookup: Dict[bytes, int] = {}
        self.variant_blocks: List[List[PieceEntry]] = []  # unflipped hardware sprites of each variant

        self.parts: List[PartEntry] = []
        self.boxes: List[BoxEntry] = []
        self.points: List[PointEntry] = []
        self.render_frames: List[RenderFrameSpan] = []
        self.render_frame_lookup: Dict[Tuple[Any, ...], int] = {}
        self.box_type_index: Dict[str, int] = {t.id: i for i, t in enumerate(project.collision_types)}
        self.point_type_index: Dict[str, int] = {t.id: i for i, t in enumerate(project.point_types)}
        self.box_type_symbols: List[str] = _event_symbols([t.name for t in project.collision_types], "MS_HITBOX_", "HITBOX")
        self.point_type_symbols: List[str] = _event_symbols([t.name for t in project.point_types], "MS_POINT_", "POINT")
        self.role_names: List[str] = project_check.role_names(project)
        self.role_index: Dict[str, int] = {name: i for i, name in enumerate(self.role_names)}
        self.role_symbols: List[str] = _event_symbols(self.role_names, "MS_ROLE_", "ROLE")
        self.transformed_frame_parts_cache: Dict[Tuple[Any, ...], Tuple[PartEntry, ...]] = {}

        self.module_render_frames: List[int] = []
        self.frame_render_frames: List[int] = []

        self.anim_steps: List[Tuple[int, int, int, int]] = []  # (render frame, ticks, first event, event count)
        self.anim_records: List[AnimRecord] = []
        self.step_events: List[Tuple[int, int]] = []  # (event type index, value)
        self.event_type_index: Dict[str, int] = {t.id: i for i, t in enumerate(project.event_types)}
        self.event_symbols: List[str] = _event_symbols([t.name for t in project.event_types])

        self.scene_samples: List[int] = []
        self.scene_records: List[SceneRecord] = []
        self.blob_size_bytes: int = 0

        self.mapping_ids: List[str] = [m.id if m else "" for m in self.mappings]
        self.mapping_names: List[str] = [m.name if m else "<none>" for m in self.mappings]

        self.master_palette_15: List[Tuple[int, int, int]] = self._build_master_palette()
        self.palette_lookup_cache: Dict[Tuple[int, int, int], int] = {}

    @staticmethod
    def _identity_matrix() -> Matrix2:
        return ((1.0, 0.0), (0.0, 1.0))

    @staticmethod
    def _identity_offset() -> Vec2:
        return (0.0, 0.0)

    @staticmethod
    def _roundf(value: float, digits: int = 4) -> float:
        return round(float(value), digits)

    @staticmethod
    def _c_string(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _playback_code(playback_type: str) -> int:
        mode = str(playback_type or "loop").strip().lower()
        if mode in ("once", "forward"):
            return 1
        if mode == "ping_pong":
            return 2
        if mode == "backward":
            return 3
        return 0

    def _prepare_output_dirs(self) -> None:
        """Create res/gen and remove older exporters' sprite sheets from it; the game's own files there stay."""
        self.output_gen_dir.mkdir(parents=True, exist_ok=True)
        for child in self.output_gen_dir.iterdir():
            if child.is_file() and LEGACY_VARIANT_FILE.fullmatch(child.name):
                child.unlink()

    def _set_current_mapping(self, mapping: Optional[ModuleMapping]) -> None:
        self.mapping = mapping
        self.mapping_key = mapping.id if mapping else "none"

    @staticmethod
    def _is_hidden_module(mod: Optional[Module]) -> bool:
        if mod is None:
            return True
        return int(mod.rect[2]) <= 0 or int(mod.rect[3]) <= 0

    def _resolve_module(self, module_id: str) -> Optional[Module]:
        mod = RetroAnimatorExporter._resolve_module(self.project, module_id, self.mapping)
        if self._is_hidden_module(mod):
            return None
        return mod

    def _ensure_variant(self, image: Image.Image) -> int:
        rgba = image.convert("RGBA")
        digest = hashlib.sha1(rgba.tobytes()).hexdigest()
        key = (rgba.width, rgba.height, digest)
        found = self.variant_lookup.get(key)
        if found is not None:
            return found

        out_w = max(TILE, ((rgba.width + TILE - 1) // TILE) * TILE)
        out_h = max(TILE, ((rgba.height + TILE - 1) // TILE) * TILE)
        padded = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        padded.alpha_composite(rgba, (0, 0))
        indexed = self._to_indexed_4bpp(padded)
        pixels = indexed.tobytes()
        alpha = rgba.getchannel("A")

        # Hardware sprites of at most 32×32 on a 32 px grid, empty blocks skipped (as hardware_budget counts them).
        blocks: List[PieceEntry] = []
        for by in range(0, out_h, SPRITE_BLOCK):
            for bx in range(0, out_w, SPRITE_BLOCK):
                bw, bh = min(SPRITE_BLOCK, out_w - bx), min(SPRITE_BLOCK, out_h - by)
                crop = alpha.crop((bx, by, min(bx + bw, rgba.width), min(by + bh, rgba.height)))
                if crop.size[0] <= 0 or crop.size[1] <= 0 or not crop.getbbox():
                    continue
                tiles = self._block_tiles(pixels, out_w, bx, by, bw // TILE, bh // TILE)
                offset = self.piece_tiles_lookup.get(tiles)
                if offset is None:
                    offset = len(self.tile_data) // 32
                    self.tile_data.extend(tiles)
                    self.piece_tiles_lookup[tiles] = offset
                size_code = (((bw // TILE) - 1) << 2) | ((bh // TILE) - 1)
                blocks.append((bx, by, size_code, offset))

        idx = len(self.variants)
        self.variant_lookup[key] = idx
        self.variants.append(VariantMeta(tile_w=out_w // TILE, tile_h=out_h // TILE, first_piece=0, piece_count=len(blocks)))
        self.variant_blocks.append(blocks)
        return idx

    def _piece_list(self, variant_index: int, hflip: bool, vflip: bool) -> Tuple[int, int]:
        """The variant's hardware sprites for one flip combination: a flip mirrors the whole padded
        variant, so the pieces swap places inside it. Each combination is laid out once, the runtime
        only adds the part's position."""
        key = (int(variant_index), int(bool(hflip)), int(bool(vflip)))
        found = self.piece_lists.get(key)
        if found is not None:
            return found
        meta = self.variants[variant_index]
        pad_w, pad_h = meta.tile_w * TILE, meta.tile_h * TILE
        first = len(self.pieces)
        for bx, by, size_code, offset in self.variant_blocks[variant_index]:
            w, h = (((size_code >> 2) & 3) + 1) * TILE, ((size_code & 3) + 1) * TILE
            x = pad_w - bx - w if hflip else bx
            y = pad_h - by - h if vflip else by
            self.pieces.append((x, y, size_code, offset))
        found = (first, len(self.pieces) - first)
        self.piece_lists[key] = found
        return found

    def _finalize_pieces(self) -> None:
        """Piece lists for every part (and the unflipped list of every variant, for tools)."""
        for variant_index in range(len(self.variants)):
            first, count = self._piece_list(variant_index, False, False)
            meta = self.variants[variant_index]
            self.variants[variant_index] = VariantMeta(meta.tile_w, meta.tile_h, first, count)
        for variant_index, _x, _y, hflip, vflip in self.parts:
            self._piece_list(variant_index, bool(hflip), bool(vflip))

    def render_frame_extent(self, span: RenderFrameSpan) -> Tuple[int, int, int, int, int]:
        """(hardware sprite count, min x, min y, max x, max y) of a render frame's pieces, relative to the
        position it is drawn at; the runtime skips its per-sprite tests when all of it is on screen."""
        count = 0
        min_x = min_y = 0x7FFF
        max_x = max_y = -0x8000
        for variant_index, px, py, hflip, vflip in self.parts[span.first_part:span.first_part + span.part_count]:
            first, n = self._piece_list(variant_index, bool(hflip), bool(vflip))
            for dx, dy, size_code, _offset in self.pieces[first:first + n]:
                x, y = int(px) + dx, int(py) + dy
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x = max(max_x, x + (((size_code >> 2) & 3) + 1) * TILE)
                max_y = max(max_y, y + ((size_code & 3) + 1) * TILE)
                count += 1
        if not count:
            return 0, 0, 0, 0, 0
        return count, min_x, min_y, max_x, max_y

    def packed_parts(self) -> List[Tuple[int, int, int, int, int]]:
        """Parts as the runtime reads them: (first piece, piece count, flip bits, x, y)."""
        out = []
        for variant_index, x, y, hflip, vflip in self.parts:
            first, count = self._piece_list(variant_index, bool(hflip), bool(vflip))
            out.append((first, count, (1 if hflip else 0) | (2 if vflip else 0), x, y))
        return out

    @staticmethod
    def _block_tiles(pixels: bytes, stride: int, bx: int, by: int, tiles_w: int, tiles_h: int) -> bytes:
        """4 bpp tiles of a block in VDP sprite order: down each column, then the next column."""
        out = bytearray()
        for tx in range(tiles_w):
            for ty in range(tiles_h):
                for row in range(TILE):
                    base = (by + ty * TILE + row) * stride + bx + tx * TILE
                    line = pixels[base:base + TILE]
                    for i in range(0, TILE, 2):
                        out.append(((line[i] & 0x0F) << 4) | (line[i + 1] & 0x0F))
        return bytes(out)

    @staticmethod
    def _rgb_distance_sq(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
        dr = int(a[0]) - int(b[0])
        dg = int(a[1]) - int(b[1])
        db = int(a[2]) - int(b[2])
        return dr * dr + dg * dg + db * db

    def _build_master_palette(self) -> List[Tuple[int, int, int]]:
        counts: Dict[Tuple[int, int, int], int] = {}

        for asset in self.project.images:
            path = Path(asset.file_path)
            if not path.exists():
                continue

            image = Image.open(path).convert("RGBA")
            transparent = tuple(int(v) for v in asset.transparent_color) if asset.transparent_color else None
            for count, px in image.getcolors(maxcolors=image.width * image.height) or []:
                rgb = (int(px[0]), int(px[1]), int(px[2]))
                if px[3] == 0 or (transparent is not None and rgb == transparent):
                    continue  # transparent pixels take no palette entry
                counts[rgb] = counts.get(rgb, 0) + int(count)

        if not counts:
            return [(255, 255, 255)] + [(0, 0, 0)] * 14

        self.palette_note = ""
        if len(counts) > 15:
            self.palette_note = (f"warning: the images use {len(counts)} colours; the Mega Drive palette holds 15 "
                                 "(plus transparent), so similar colours were merged")
        if len(counts) <= 15:
            ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            base = [rgb for rgb, _count in ordered]
        else:
            canvas = Image.new("RGB", (len(counts), 1), (0, 0, 0))
            for x, rgb in enumerate(counts.keys()):
                canvas.putpixel((x, 0), rgb)
            quant = canvas.quantize(colors=15, dither=Image.Dither.NONE)
            raw_pal = quant.getpalette() or []
            base = []
            for i in range(15):
                off = i * 3
                if off + 2 >= len(raw_pal):
                    break
                base.append((int(raw_pal[off]), int(raw_pal[off + 1]), int(raw_pal[off + 2])))

        if not base:
            base = [(255, 255, 255)]
        while len(base) < 15:
            base.append(base[-1])
        return base[:15]

    def _nearest_master_palette_index(self, rgb: Tuple[int, int, int]) -> int:
        cached = self.palette_lookup_cache.get(rgb)
        if cached is not None:
            return cached

        best_index = 0
        best_dist = self._rgb_distance_sq(rgb, self.master_palette_15[0])
        for idx in range(1, 15):
            dist = self._rgb_distance_sq(rgb, self.master_palette_15[idx])
            if dist < best_dist:
                best_dist = dist
                best_index = idx

        self.palette_lookup_cache[rgb] = best_index
        return best_index

    def _to_indexed_4bpp(self, rgba: Image.Image) -> Image.Image:
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        src_rgb = rgb.tobytes()
        src_alpha = alpha.tobytes()
        out_idx = bytearray(len(src_alpha))
        for i in range(len(src_alpha)):
            if src_alpha[i] != 0:
                j = i * 3
                nearest = self._nearest_master_palette_index((src_rgb[j], src_rgb[j + 1], src_rgb[j + 2]))
                out_idx[i] = int(nearest + 1)

        palette = [0] * (256 * 3)
        for i, rgb_color in enumerate(self.master_palette_15):
            dst_off = (i + 1) * 3
            palette[dst_off] = int(rgb_color[0])
            palette[dst_off + 1] = int(rgb_color[1])
            palette[dst_off + 2] = int(rgb_color[2])

        out = Image.frombytes("P", rgba.size, bytes(out_idx))
        out.putpalette(palette)
        return out

    def _intern_render_frame(
        self,
        part_list: Sequence[PartEntry],
        boxes: Sequence[BoxEntry] = (),
        points: Sequence[PointEntry] = (),
    ) -> int:
        parts_key = tuple((int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4])) for p in part_list)
        key = (parts_key, tuple(boxes), tuple(points))
        found = self.render_frame_lookup.get(key)
        if found is not None:
            return found

        span = RenderFrameSpan(
            first_part=len(self.parts), part_count=len(parts_key),
            first_box=len(self.boxes), box_count=len(boxes),
            first_point=len(self.points), point_count=len(points),
        )
        self.parts.extend(parts_key)
        self.boxes.extend(boxes)
        self.points.extend(points)
        idx = len(self.render_frames)
        self.render_frames.append(span)
        self.render_frame_lookup[key] = idx
        return idx

    def _frame_markers(
        self, frame: Frame, offset: Vec2, rotation_degrees: float, flip_x: bool, flip_y: bool
    ) -> Tuple[Tuple[BoxEntry, ...], Tuple[PointEntry, ...]]:
        """The frame's own hitboxes and points, moved like the frame (flip, then rotate, then offset)."""
        a_mat = RetroAnimatorExporter._mat_mul(
            RetroAnimatorExporter._rotation_matrix(rotation_degrees),
            RetroAnimatorExporter._flip_matrix(flip_x, flip_y),
        )

        def move(x: float, y: float) -> Vec2:
            tx, ty = RetroAnimatorExporter._mat_vec_mul(a_mat, (float(x), float(y)))
            return (tx + float(offset[0]), ty + float(offset[1]))

        boxes: List[BoxEntry] = []
        for cr in frame.collision_rects:
            x, y, w, h = (int(v) for v in cr.rect)
            if w <= 0 or h <= 0:
                continue
            corners = [move(x, y), move(x + w, y + h)]
            x0 = int(round(min(c[0] for c in corners)))
            y0 = int(round(min(c[1] for c in corners)))
            x1 = int(round(max(c[0] for c in corners)))
            y1 = int(round(max(c[1] for c in corners)))
            role = self.role_index.get(str(cr.role or "").strip(), NO_ROLE)
            boxes.append((self.box_type_index.get(cr.type_id, UNKNOWN_TYPE), role, x0, y0, x1 - x0, y1 - y0))
        points: List[PointEntry] = []
        for cp in frame.control_points:
            # A point marks a pixel: move the pixel's centre and take the pixel it lands in, so a mirrored or turned
            # step marks the same pixel of the art (like hitboxes, which move pixel-exactly).
            px, py = move(cp.x + 0.5, cp.y + 0.5)
            role = self.role_index.get(str(cp.role or "").strip(), NO_ROLE)
            points.append((self.point_type_index.get(cp.type_id, UNKNOWN_TYPE), role, math.floor(px), math.floor(py)))
        return tuple(boxes), tuple(points)

    @staticmethod
    def _effective_hw_flip(rotation_degrees: float, flip_x: bool, flip_y: bool) -> Optional[Tuple[bool, bool]]:
        rot_norm = float(rotation_degrees) % 360.0
        rot_int = int(round(rot_norm)) % 360
        if abs(rot_norm - float(rot_int)) > 1e-5:
            return None
        if rot_int not in (0, 180):
            return None

        hflip = bool(flip_x)
        vflip = bool(flip_y)
        if rot_int == 180:
            hflip = not hflip
            vflip = not vflip
        return (hflip, vflip)

    @staticmethod
    def _extract_geom_axis_flip(a_mat: Matrix2) -> Optional[Tuple[bool, bool]]:
        a = float(a_mat[0][0])
        b = float(a_mat[0][1])
        c = float(a_mat[1][0])
        d = float(a_mat[1][1])
        eps = 1e-5

        # Hardware flip path can represent only axis-aligned transforms here
        # (identity / 180deg equivalent with optional geometric mirror).
        if abs(b) > eps or abs(c) > eps:
            return None
        if abs(abs(a) - 1.0) > eps or abs(abs(d) - 1.0) > eps:
            return None
        return (a < 0.0, d < 0.0)

    def _render_leaf_part(
        self,
        mod: Module,
        a_mat: Matrix2,
        b_vec: Vec2,
        rotation_degrees: float,
        flip_x: bool,
        flip_y: bool,
        local_flip_x: bool = False,
        local_flip_y: bool = False,
    ) -> Optional[PartEntry]:
        base = RetroAnimatorExporter._load_module_rgba(
            project=self.project,
            mod=mod,
            full_image_cache=self.full_image_cache,
            module_cache=self.module_cache,
        )
        w, h = base.size
        if w <= 0 or h <= 0:
            return None

        geom = self._extract_geom_axis_flip(a_mat)
        if geom is not None:
            geom_hflip, geom_vflip = geom
            hflip = bool(geom_hflip) ^ bool(local_flip_x)
            vflip = bool(geom_vflip) ^ bool(local_flip_y)

            # Local (module-level) flip in the editor is an in-place pixel mirror.
            # In geometric form this is equivalent to flipping with shifted pivot.
            px = int(mod.pivot[0])
            py = int(mod.pivot[1])
            px_eff = (int(w) - px) if local_flip_x else px
            py_eff = (int(h) - py) if local_flip_y else py

            bx = int(round(float(b_vec[0])))
            by = int(round(float(b_vec[1])))
            pad_w = max(8, ((int(w) + 7) // 8) * 8)
            pad_h = max(8, ((int(h) + 7) // 8) * 8)

            if hflip:
                draw_x = bx + px_eff - pad_w
            else:
                draw_x = bx - px_eff
            if vflip:
                draw_y = by + py_eff - pad_h
            else:
                draw_y = by - py_eff

            variant_index = self._ensure_variant(base)
            return (variant_index, int(draw_x), int(draw_y), int(hflip), int(vflip))

        rendered = self._render_transformed_instance_with_local_flip(
            mod=mod,
            a_mat=a_mat,
            b_vec=(float(b_vec[0]), float(b_vec[1])),
            local_flip_x=bool(local_flip_x),
            local_flip_y=bool(local_flip_y),
        )
        if not rendered:
            return None
        img, draw_x, draw_y = rendered
        variant_index = self._ensure_variant(img)
        return (variant_index, int(draw_x), int(draw_y), 0, 0)

    def _render_transformed_instance_with_local_flip(
        self,
        mod: Module,
        a_mat: Matrix2,
        b_vec: Vec2,
        local_flip_x: bool,
        local_flip_y: bool,
    ) -> Optional[Tuple[Image.Image, int, int]]:
        base = RetroAnimatorExporter._load_module_rgba(
            project=self.project,
            mod=mod,
            full_image_cache=self.full_image_cache,
            module_cache=self.module_cache,
        )

        if local_flip_x:
            base = base.transpose(Image.FLIP_LEFT_RIGHT)
        if local_flip_y:
            base = base.transpose(Image.FLIP_TOP_BOTTOM)

        w, h = base.size
        if w <= 0 or h <= 0:
            return None

        piv = (float(mod.pivot[0]), float(mod.pivot[1]))
        ap = RetroAnimatorExporter._mat_vec_mul(a_mat, piv)
        c_vec = (float(b_vec[0]) - ap[0], float(b_vec[1]) - ap[1])

        corners = (
            (0.0, 0.0),
            (float(w), 0.0),
            (0.0, float(h)),
            (float(w), float(h)),
        )
        xs: List[float] = []
        ys: List[float] = []
        for u, v in corners:
            tx, ty = RetroAnimatorExporter._mat_vec_mul(a_mat, (u, v))
            xs.append(tx + c_vec[0])
            ys.append(ty + c_vec[1])

        min_x = int(math.floor(min(xs)))
        min_y = int(math.floor(min(ys)))
        max_x = int(math.ceil(max(xs)))
        max_y = int(math.ceil(max(ys)))
        out_w = max_x - min_x
        out_h = max_y - min_y
        if out_w <= 0 or out_h <= 0:
            return None

        inv = RetroAnimatorExporter._invert(a_mat)
        if not inv:
            return None

        dx = float(min_x) - c_vec[0]
        dy = float(min_y) - c_vec[1]
        coeff = (
            inv[0][0],
            inv[0][1],
            inv[0][0] * dx + inv[0][1] * dy,
            inv[1][0],
            inv[1][1],
            inv[1][0] * dx + inv[1][1] * dy,
        )
        transformed = base.transform(
            (out_w, out_h),
            Image.AFFINE,
            coeff,
            resample=Image.NEAREST,
            fillcolor=(0, 0, 0, 0),
        )
        if not transformed.getbbox():
            return None

        return transformed, min_x, min_y

    def _collect_leaf_instances_canvas_like(
        self,
        frame_id: str,
        parent_a: Matrix2,
        parent_b: Vec2,
        parent_rot: float,
        parent_flip_x: bool,
        parent_flip_y: bool,
        out: List[
            Tuple[
                Module,
                Matrix2,
                Vec2,
                float,
                bool,
                bool,
                bool,
                bool,
            ]
        ],
        depth: int,
        stack: set[str],
    ) -> None:
        if depth > 48:
            return
        frame = self.project.get_frame(frame_id)
        if not frame or frame_id in stack:
            return

        stack.add(frame_id)
        for fm in frame.fmodules:
            local_rot = float(getattr(fm, "rotation_degrees", 0.0))
            local_flip_x = bool(getattr(fm, "flip_x", False))
            local_flip_y = bool(getattr(fm, "flip_y", False))
            local_b = (float(fm.position[0]), float(fm.position[1]))
            rot_a = RetroAnimatorExporter._rotation_matrix(local_rot)
            flip_a = RetroAnimatorExporter._flip_matrix(local_flip_x, local_flip_y)

            # Match editor behavior: module-local flips mirror pixels in-place and
            # do not change module bounds/anchor placement.
            if fm.ref_type == "frame":
                local_a = RetroAnimatorExporter._mat_mul(rot_a, flip_a)
            else:
                local_a = rot_a

            a_next, b_next = RetroAnimatorExporter._compose(parent_a, parent_b, local_a, local_b)
            parent_flipped = bool(parent_flip_x) ^ bool(parent_flip_y)
            rot_next = float(parent_rot) + (-local_rot if parent_flipped else local_rot)
            flip_x_next = bool(parent_flip_x) ^ local_flip_x
            flip_y_next = bool(parent_flip_y) ^ local_flip_y

            if fm.ref_type == "module":
                mod = self._resolve_module(fm.ref_id)
                if mod:
                    out.append((mod, a_next, b_next, rot_next, flip_x_next, flip_y_next, local_flip_x, local_flip_y))
            elif fm.ref_type == "frame":
                self._collect_leaf_instances_canvas_like(
                    frame_id=fm.ref_id,
                    parent_a=a_next,
                    parent_b=b_next,
                    parent_rot=rot_next,
                    parent_flip_x=flip_x_next,
                    parent_flip_y=flip_y_next,
                    out=out,
                    depth=depth + 1,
                    stack=stack,
                )
        stack.remove(frame_id)

    def _render_module_parts(
        self,
        module_id: str,
        offset: Vec2,
        rotation_degrees: float,
        flip_x: bool,
        flip_y: bool,
    ) -> Tuple[PartEntry, ...]:
        mod = self._resolve_module(module_id)
        if not mod:
            return tuple()

        a_mat = RetroAnimatorExporter._mat_mul(
            RetroAnimatorExporter._rotation_matrix(rotation_degrees),
            RetroAnimatorExporter._flip_matrix(flip_x, flip_y),
        )
        part = self._render_leaf_part(
            mod=mod,
            a_mat=a_mat,
            b_vec=(float(offset[0]), float(offset[1])),
            rotation_degrees=float(rotation_degrees),
            flip_x=bool(flip_x),
            flip_y=bool(flip_y),
        )
        if not part:
            return tuple()
        return (part,)

    def _render_frame_parts(
        self,
        frame: Frame,
        offset: Vec2,
        rotation_degrees: float,
        flip_x: bool,
        flip_y: bool,
    ) -> Tuple[PartEntry, ...]:
        key = (
            "frame",
            self.mapping_key,
            frame.id,
            self._roundf(offset[0]),
            self._roundf(offset[1]),
            self._roundf(rotation_degrees),
            int(bool(flip_x)),
            int(bool(flip_y)),
        )
        cached = self.transformed_frame_parts_cache.get(key)
        if cached is not None:
            return cached

        parent_a = RetroAnimatorExporter._mat_mul(
            RetroAnimatorExporter._rotation_matrix(rotation_degrees),
            RetroAnimatorExporter._flip_matrix(flip_x, flip_y),
        )
        parent_b = (float(offset[0]), float(offset[1]))

        instances: List[
            Tuple[
                Module,
                Matrix2,
                Vec2,
                float,
                bool,
                bool,
                bool,
                bool,
            ]
        ] = []
        self._collect_leaf_instances_canvas_like(
            frame_id=frame.id,
            parent_a=parent_a,
            parent_b=parent_b,
            parent_rot=float(rotation_degrees),
            parent_flip_x=bool(flip_x),
            parent_flip_y=bool(flip_y),
            out=instances,
            depth=0,
            stack=set(),
        )

        out_parts: List[PartEntry] = []
        for mod, a_mat, b_vec, rot_deg, part_flip_x, part_flip_y, local_flip_x, local_flip_y in instances:
            part = self._render_leaf_part(
                mod=mod,
                a_mat=a_mat,
                b_vec=b_vec,
                rotation_degrees=float(rot_deg),
                flip_x=bool(part_flip_x),
                flip_y=bool(part_flip_y),
                local_flip_x=bool(local_flip_x),
                local_flip_y=bool(local_flip_y),
            )
            if not part:
                continue
            out_parts.append(part)

        baked = tuple(out_parts)
        self.transformed_frame_parts_cache[key] = baked
        return baked

    @staticmethod
    def _build_local_matrix(state: Dict[str, Any]) -> Matrix2x3:
        """The key's pose applied to what the source adds (root motion, swap offset): a mirrored or turned object
        mirrors or turns where its animation moves it, like the Timeline stage (ui/scene_editor/ops.local_matrix)."""
        source_offset = state.get("source_offset", (0.0, 0.0))
        pose = SGDKBakeContext._pose_matrix(
            float(state.get("x", 0.0)), float(state.get("y", 0.0)), float(state.get("rotation_degrees", 0.0)),
            bool(state.get("flip_x", False)), bool(state.get("flip_y", False)),
        )
        source = SGDKBakeContext._pose_matrix(
            float(source_offset[0]), float(source_offset[1]), float(state.get("source_rotation", 0.0)),
            bool(state.get("source_flip_x", False)), bool(state.get("source_flip_y", False)),
        )
        return SGDKBakeContext._compose_matrix(pose, source)

    @staticmethod
    def _pose_matrix(tx: float, ty: float, rotation: float, flip_x: bool, flip_y: bool) -> Matrix2x3:
        """Flip, then rotate, then move (exact at 90° steps)."""
        quarter = rotation / 90.0
        if abs(quarter - round(quarter)) < 1e-9:
            cos_a, sin_a = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(round(quarter)) % 4]
        else:
            rad = math.radians(rotation)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
        sx = -1.0 if flip_x else 1.0
        sy = -1.0 if flip_y else 1.0
        return (cos_a * sx, sin_a * sx, -sin_a * sy, cos_a * sy, tx, ty)

    @staticmethod
    def _compose_matrix(parent: Matrix2x3, child: Matrix2x3) -> Matrix2x3:
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
    def _decompose_matrix_to_frame_transform(matrix: Matrix2x3) -> Tuple[Vec2, float, bool, bool]:
        a, b, c, d, tx, ty = matrix
        sx = math.hypot(a, b)
        sy = math.hypot(c, d)
        if sx <= 1e-6 or sy <= 1e-6:
            return ((tx, ty), 0.0, False, False)

        an = a / sx
        bn = b / sx
        cn = c / sy
        dn = d / sy
        det = an * dn - bn * cn

        render_flip_x = False
        render_flip_y = det < 0.0
        if render_flip_y:
            cn = -cn
            dn = -dn

        render_rotation = math.degrees(math.atan2(bn, an))
        return ((tx, ty), render_rotation, render_flip_x, render_flip_y)

    def _world_matrix_for_object(
        self,
        scene: TimelineScene,
        state_map: Dict[str, Dict[str, Any]],
        object_id: str,
        cache: Dict[str, Matrix2x3],
    ) -> Matrix2x3:
        if object_id in cache:
            return cache[object_id]

        state = state_map.get(object_id)
        if state is None:
            cache[object_id] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            return cache[object_id]

        local = self._build_local_matrix(state)
        obj = scene.get_object(object_id)
        parent_id = obj.parent_id if obj else None
        if parent_id and (parent_id in state_map) and scene.get_object(parent_id):
            parent = self._world_matrix_for_object(scene, state_map, parent_id, cache)
            world = self._compose_matrix(parent, local)
        else:
            world = local

        cache[object_id] = world
        return world

    def _render_scene_parts(self, scene: TimelineScene, time_seconds: float) -> Tuple[PartEntry, ...]:
        state_map: Dict[str, Dict[str, Any]] = {}
        for obj in scene.objects:
            state = scene.evaluate_object_state(self.project, obj.id, time_seconds)
            if state is not None:
                state_map[obj.id] = state

        ordered_objects = sorted(scene.objects, key=lambda item: (item.draw_order, item.name.lower(), item.id))
        world_cache: Dict[str, Matrix2x3] = {}
        scene_parts: List[PartEntry] = []
        baked_mapping = self.mapping
        try:
            for obj in ordered_objects:
                # Objects with their own mapping keep it; the others follow the mapping being baked.
                self._set_current_mapping(scene.object_mapping(self.project, obj.id, baked_mapping))
                scene_parts.extend(self._render_scene_object_parts(scene, state_map, obj.id, world_cache))
        finally:
            self._set_current_mapping(baked_mapping)
        return tuple(scene_parts)

    def _render_scene_object_parts(
        self,
        scene: TimelineScene,
        state_map: Dict[str, Dict[str, Any]],
        object_id: str,
        world_cache: Dict[str, Matrix2x3],
    ) -> Tuple[PartEntry, ...]:
        state = state_map.get(object_id)
        if not state or not bool(state.get("visible", True)):
            return ()
        world_matrix = self._world_matrix_for_object(scene, state_map, object_id, world_cache)
        offset, rotation, flip_x, flip_y = self._decompose_matrix_to_frame_transform(world_matrix)

        source_type = str(state.get("source_type", "none") or "none").strip().lower()
        if source_type == "module":
            source_id = state.get("source_id")
            if source_id is None:
                return ()
            return self._render_module_parts(
                module_id=str(source_id),
                offset=offset,
                rotation_degrees=float(rotation),
                flip_x=bool(flip_x),
                flip_y=bool(flip_y),
            )

        if source_type not in ("frame", "animation"):
            return ()
        frame_id = state.get("frame_id") or state.get("source_id")
        frame = self.project.get_frame(str(frame_id)) if frame_id is not None else None
        if not frame:
            return ()
        return self._render_frame_parts(
            frame=frame,
            offset=offset,
            rotation_degrees=float(rotation),
            flip_x=bool(flip_x),
            flip_y=bool(flip_y),
        )

    def bake(self) -> None:
        self._prepare_output_dirs()

        empty_render = self._intern_render_frame(())

        for mapping in self.mappings:
            frame_render_by_id: Dict[str, int] = {}
            self._set_current_mapping(mapping)

            # 1) Module render entries.
            for mod in self.project.modules:
                parts = self._render_module_parts(mod.id, self._identity_offset(), 0.0, False, False)
                render_idx = self._intern_render_frame(parts)
                self.module_render_frames.append(render_idx)

            # 2) Base frame render entries.
            for frame in self.project.frames:
                parts = self._render_frame_parts(frame, self._identity_offset(), 0.0, False, False)
                boxes, points = self._frame_markers(frame, self._identity_offset(), 0.0, False, False)
                render_idx = self._intern_render_frame(parts, boxes, points)
                self.frame_render_frames.append(render_idx)
                frame_render_by_id[frame.id] = render_idx

            # 3) Animations.
            animation_index = {a.id: i for i, a in enumerate(self.project.animations)}
            for anim in self.project.animations:
                first_step = len(self.anim_steps)
                source_fps = int(anim.fps) if int(anim.fps) > 0 else 10
                exported_step_of: List[int] = []  # editor step index -> exported step index (-1: skipped)
                for af in anim.aframes:
                    frame = self.project.get_frame(af.frame_id)
                    if not frame:
                        exported_step_of.append(-1)
                        continue

                    off = (float(af.offset[0]), float(af.offset[1]))
                    rot = float(getattr(af, "rotation_degrees", 0.0))
                    fx = bool(getattr(af, "flip_x", False))
                    fy = bool(getattr(af, "flip_y", False))
                    is_identity = (off == (0.0, 0.0)) and (not fx) and (not fy) and (abs(rot) <= 1e-9)
                    if is_identity:
                        render_idx = frame_render_by_id.get(frame.id, empty_render)
                    else:
                        parts = self._render_frame_parts(frame, off, rot, fx, fy)
                        boxes, points = self._frame_markers(frame, off, rot, fx, fy)
                        render_idx = self._intern_render_frame(parts, boxes, points)

                    duration_ticks = max(
                        1,
                        int(round((max(1.0, float(af.duration_frames)) / float(source_fps)) * 60.0)),
                    )
                    first_event = len(self.step_events)
                    for event in getattr(af, "events", []) or []:
                        type_index = self.event_type_index.get(event.type_id)
                        if type_index is None:
                            continue  # event type no longer exists
                        self.step_events.append((type_index, max(-32768, min(32767, int(event.value)))))
                    event_count = min(255, len(self.step_events) - first_event)
                    exported_step_of.append(len(self.anim_steps) - first_step)
                    self.anim_steps.append((render_idx, duration_ticks, first_event, event_count))

                step_count = len(self.anim_steps) - first_step
                if step_count <= 0:
                    first_step = len(self.anim_steps)
                    self.anim_steps.append((empty_render, 1, 0, 0))
                    step_count = 1

                # "Loop from" points at an editor step; use the first exported step at or after it.
                loop_start = 0
                if str(anim.playback_type) == "loop" and int(getattr(anim, "loop_start", 0) or 0) > 0:
                    later = [i for i in exported_step_of[int(anim.loop_start):] if i >= 0]
                    loop_start = later[0] if later else 0
                next_id = getattr(anim, "next_animation_id", None)
                self.anim_records.append(
                    AnimRecord(
                        first_step=first_step,
                        step_count=step_count,
                        fps=source_fps,
                        playback=self._playback_code(str(anim.playback_type)),
                        loop_start=loop_start,
                        next_animation=animation_index.get(next_id, NO_ANIMATION) if next_id else NO_ANIMATION,
                        loop_count=max(0, min(0xFFFF, int(anim.loop_count or 0))),
                    )
                )

            # 4) Scenes sampled at scene FPS.
            for scene in self.project.timeline_scenes:
                first_sample = len(self.scene_samples)
                duration_frames = max(1, scene.duration_in_frames())
                fps = max(1, int(scene.fps))

                for frame_idx in range(duration_frames):
                    t = float(frame_idx) / float(fps)
                    parts = self._render_scene_parts(scene, t)
                    render_idx = self._intern_render_frame(parts)
                    self.scene_samples.append(render_idx)

                sample_count = len(self.scene_samples) - first_sample
                if sample_count <= 0:
                    first_sample = len(self.scene_samples)
                    self.scene_samples.append(empty_render)
                    sample_count = 1

                duration_ticks = max(1, int(round(float(scene.duration_seconds) * 60.0)))
                self.scene_records.append(
                    SceneRecord(
                        first_sample=first_sample,
                        sample_count=sample_count,
                        fps=fps,
                        duration_ticks=duration_ticks,
                        loop=1 if scene.loop else 0,
                    )
                )

        self._finalize_pieces()

    @staticmethod
    def _be16(value: int) -> bytes:
        return struct.pack(">H", int(value) & 0xFFFF)

    @staticmethod
    def _be32(value: int) -> bytes:
        return struct.pack(">I", int(value) & 0xFFFFFFFF)

    @staticmethod
    def _append_align(buf: bytearray, align: int) -> None:
        if align <= 1:
            return
        while len(buf) % align:
            buf.append(0)

    def _emit_blob(self, path: Path) -> None:
        section_offsets: Dict[str, int] = {}
        section_names = [
            "parts",
            "render_frames",
            "module_render_frames",
            "frame_render_frames",
            "anim_steps",
            "animations",
            "scene_samples",
            "scenes",
            "mapping_ids",
            "mapping_names",
            "module_ids",
            "module_names",
            "frame_ids",
            "frame_names",
            "animation_ids",
            "animation_names",
            "scene_ids",
            "scene_names",
            "strings",
            "step_events",
            "event_names",
            "variants",
            "pieces",
            "tiles",
            "palette",
            "boxes",
            "points",
            "box_type_names",
            "point_type_names",
            "role_names",
        ]
        if len(section_names) != BLOB_SECTION_COUNT:
            raise RuntimeError("Internal SGDK blob section list mismatch")

        strings_blob = bytearray()

        def append_string_list(values: Sequence[str]) -> List[int]:
            rel_offsets: List[int] = []
            for value in values:
                rel_offsets.append(len(strings_blob))
                encoded = str(value if value is not None else "").encode("utf-8")
                strings_blob.extend(encoded)
                strings_blob.append(0)
            return rel_offsets

        mapping_ids_rel = append_string_list(self.mapping_ids)
        mapping_names_rel = append_string_list(self.mapping_names)
        module_ids_rel = append_string_list([mod.id for mod in self.project.modules])
        module_names_rel = append_string_list([mod.name for mod in self.project.modules])
        frame_ids_rel = append_string_list([frm.id for frm in self.project.frames])
        frame_names_rel = append_string_list([frm.name for frm in self.project.frames])
        anim_ids_rel = append_string_list([anim.id for anim in self.project.animations])
        anim_names_rel = append_string_list([anim.name for anim in self.project.animations])
        scene_ids_rel = append_string_list([scene.id for scene in self.project.timeline_scenes])
        scene_names_rel = append_string_list([scene.name for scene in self.project.timeline_scenes])
        event_names_rel = append_string_list([t.name for t in self.project.event_types])
        box_type_names_rel = append_string_list([t.name for t in self.project.collision_types])
        point_type_names_rel = append_string_list([t.name for t in self.project.point_types])
        role_names_rel = append_string_list(self.role_names)

        parts_raw = bytearray()
        for first_piece, piece_count, flip, px, py in self.packed_parts():
            parts_raw.extend(struct.pack(">HBBhh", int(first_piece), int(piece_count), int(flip), int(px), int(py)))

        render_frames_raw = bytearray()
        for rf in self.render_frames:
            render_frames_raw.extend(
                struct.pack(">IHHIIHHhhhh", int(rf.first_part), int(rf.part_count), int(rf.box_count), int(rf.first_box),
                            int(rf.first_point), int(rf.point_count), *self.render_frame_extent(rf))
            )

        variants_raw = bytearray()
        for v in self.variants:
            variants_raw.extend(struct.pack(">HHBB", int(v.first_piece), int(v.piece_count), int(v.tile_w), int(v.tile_h)))

        pieces_raw = bytearray()
        for dx, dy, size_code, tile_offset in self.pieces:
            pieces_raw.extend(struct.pack(">hhBBH", int(dx), int(dy), int(size_code), 0, int(tile_offset)))

        palette_raw = bytearray(self._be16(0))  # index 0 is transparent
        for r, g, b in self.master_palette_15:
            # Same rounding as rescomp: 3 bits per channel, truncated.
            palette_raw.extend(self._be16(((int(b) >> 5) << 9) | ((int(g) >> 5) << 5) | ((int(r) >> 5) << 1)))

        boxes_raw = bytearray()
        for box_type, role, x, y, w, h in self.boxes:
            boxes_raw.extend(struct.pack(">BBHhhhh", int(box_type) & 0xFF, 0, int(role) & 0xFFFF, int(x), int(y), int(w), int(h)))

        points_raw = bytearray()
        for point_type, role, x, y in self.points:
            points_raw.extend(struct.pack(">BBHhh", int(point_type) & 0xFF, 0, int(role) & 0xFFFF, int(x), int(y)))

        module_render_raw = bytearray()
        for idx in self.module_render_frames:
            module_render_raw.extend(self._be16(int(idx)))

        frame_render_raw = bytearray()
        for idx in self.frame_render_frames:
            frame_render_raw.extend(self._be16(int(idx)))

        if len(self.step_events) > 0xFFFF:
            raise RuntimeError(f"Too many animation step events for the blob: {len(self.step_events)} > 65535")
        anim_steps_raw = bytearray()
        for frame_index, duration_ticks, first_event, event_count in self.anim_steps:
            anim_steps_raw.extend(
                struct.pack(">HHHBB", int(frame_index), int(duration_ticks), int(first_event) & 0xFFFF, int(event_count), 0)
            )

        animations_raw = bytearray()
        for rec in self.anim_records:
            animations_raw.extend(
                struct.pack(
                    ">IHHBBHHH",
                    int(rec.first_step), int(rec.step_count), int(rec.fps), int(rec.playback), 0,
                    int(rec.loop_start), int(rec.next_animation), int(rec.loop_count),
                )
            )

        step_events_raw = bytearray()
        for type_index, value in self.step_events:
            step_events_raw.extend(struct.pack(">Hh", int(type_index), int(value)))

        scene_samples_raw = bytearray()
        for idx in self.scene_samples:
            scene_samples_raw.extend(self._be16(int(idx)))

        scenes_raw = bytearray()
        for rec in self.scene_records:
            scenes_raw.extend(
                struct.pack(
                    ">IHHHBBBB",
                    int(rec.first_sample),
                    int(rec.sample_count),
                    int(rec.fps),
                    int(rec.duration_ticks),
                    int(rec.loop),
                    0,
                    0,
                    0,
                )
            )

        blob = bytearray()
        header_size = BLOB_HEADER_SIZE
        blob.extend(b"\0" * header_size)

        def append_section(name: str, data: bytes, align: int = 2) -> None:
            self._append_align(blob, align)
            section_offsets[name] = len(blob)
            blob.extend(data)

        append_section("parts", bytes(parts_raw))
        append_section("render_frames", bytes(render_frames_raw))
        append_section("module_render_frames", bytes(module_render_raw))
        append_section("frame_render_frames", bytes(frame_render_raw))
        append_section("anim_steps", bytes(anim_steps_raw))
        append_section("animations", bytes(animations_raw))
        append_section("scene_samples", bytes(scene_samples_raw))
        append_section("scenes", bytes(scenes_raw))
        append_section("step_events", bytes(step_events_raw))
        append_section("variants", bytes(variants_raw))
        append_section("pieces", bytes(pieces_raw))
        append_section("tiles", bytes(self.tile_data), align=4)
        append_section("palette", bytes(palette_raw))
        append_section("boxes", bytes(boxes_raw))
        append_section("points", bytes(points_raw))
        append_section("strings", bytes(strings_blob), align=1)

        strings_base = section_offsets["strings"]

        def build_string_offset_section(rel_offsets: Sequence[int]) -> bytes:
            out = bytearray()
            for rel in rel_offsets:
                out.extend(self._be32(strings_base + int(rel)))
            return bytes(out)

        append_section("mapping_ids", build_string_offset_section(mapping_ids_rel))
        append_section("mapping_names", build_string_offset_section(mapping_names_rel))
        append_section("module_ids", build_string_offset_section(module_ids_rel))
        append_section("module_names", build_string_offset_section(module_names_rel))
        append_section("frame_ids", build_string_offset_section(frame_ids_rel))
        append_section("frame_names", build_string_offset_section(frame_names_rel))
        append_section("animation_ids", build_string_offset_section(anim_ids_rel))
        append_section("animation_names", build_string_offset_section(anim_names_rel))
        append_section("scene_ids", build_string_offset_section(scene_ids_rel))
        append_section("scene_names", build_string_offset_section(scene_names_rel))
        append_section("event_names", build_string_offset_section(event_names_rel))
        append_section("box_type_names", build_string_offset_section(box_type_names_rel))
        append_section("point_type_names", build_string_offset_section(point_type_names_rel))
        append_section("role_names", build_string_offset_section(role_names_rel))

        header = bytearray()
        header.extend(b"MSB1")
        header.extend(self._be16(BLOB_VERSION))
        header.extend(self._be16(0))
        header.extend(self._be16(len(self.variants)))
        header.extend(self._be16(len(self.project.modules)))
        header.extend(self._be16(len(self.project.frames)))
        header.extend(self._be16(len(self.project.animations)))
        header.extend(self._be16(len(self.project.timeline_scenes)))
        header.extend(self._be16(len(self.mappings)))
        header.extend(self._be16(len(self.render_frames)))
        header.extend(self._be16(len(self.anim_steps)))
        header.extend(self._be16(len(self.scene_samples)))
        header.extend(self._be16(len(self.anim_records)))
        header.extend(self._be16(len(self.scene_records)))
        header.extend(self._be16(len(self.project.event_types)))
        header.extend(self._be16(len(self.step_events)))
        header.extend(self._be16(len(self.tile_data) // 32))
        header.extend(self._be16(len(self.pieces)))
        header.extend(self._be16(len(self.boxes)))
        header.extend(self._be16(len(self.points)))
        header.extend(self._be16(len(self.project.collision_types)))
        header.extend(self._be16(len(self.project.point_types)))
        header.extend(self._be16(len(self.role_names)))
        header.extend(self._be32(len(self.parts)))

        for section in section_names:
            header.extend(self._be32(section_offsets.get(section, 0)))

        header.extend(self._be32(len(strings_blob)))

        for limit, count, what in ((0xFFFF, len(self.pieces), "hardware sprite pieces"), (0xFFFF, len(self.boxes), "hitboxes"),
                                   (0xFFFF, len(self.points), "points"), (0xFFFF, len(self.render_frames), "render frames")):
            if count > limit:
                raise RuntimeError(f"Too many {what} for the blob: {count} > {limit}")
        if len(header) != header_size:
            raise RuntimeError(f"Internal SGDK blob header size mismatch: {len(header)} != {header_size}")

        blob[0:header_size] = header
        self.blob_size_bytes = len(blob)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(blob))

    def _emit_header(self, path: Path) -> None:
        text = """#ifndef MODSPRITE_DATA_H
#define MODSPRITE_DATA_H

#include <genesis.h>

/* Blob records: no padding, but every record starts on an even address (the blob keeps them aligned),
   so the 68000 can read 16 / 32-bit fields with single word / long moves. */
#define MS_RECORD __attribute__((packed, aligned(2)))

/* A part shows the pieces first_piece .. first_piece + piece_count - 1 (already laid out for its flips)
   at (x, y) from the position it is drawn at; flip: bit 0 = horizontal, bit 1 = vertical. */
typedef struct MS_RECORD
{
    u16 first_piece;
    u8 piece_count;
    u8 flip;
    s16 x;
    s16 y;
} MS_Part;

typedef struct MS_RECORD
{
    u32 first_part;
    u16 part_count;
    u16 hitbox_count;
    u32 first_hitbox;
    u32 first_point;
    u16 point_count;
    u16 sprite_count;  /* hardware sprites, inside min..max (relative to the draw position) */
    s16 min_x;
    s16 min_y;
    s16 max_x;
    s16 max_y;
} MS_RenderFrame;

/* A variant is one baked module image; it shows as one or more hardware sprites (pieces).
   The runtime does not need it (parts point at their pieces); tools can use it. */
typedef struct MS_RECORD
{
    u16 first_piece;
    u16 piece_count;
    u8 tile_w;  /* padded size in tiles: flips mirror the pieces inside it */
    u8 tile_h;
} MS_Variant;

typedef struct MS_RECORD
{
    s16 x;            /* offset from the part's position */
    s16 y;
    u8 size;          /* VDP sprite size: SPRITE_SIZE(w, h) */
    u8 reserved0;
    u16 tile_offset;  /* first tile, from the runtime's tile base */
} MS_Piece;

/* Hitboxes and points of a frame, already moved like the frame (step offset, flips, rotation).
   Coordinates are relative to the position the frame is drawn at. */
typedef struct MS_RECORD
{
    u8 type;      /* MS_HITBOX_*, MS_UNKNOWN_TYPE if its type was deleted */
    u8 reserved0;
    u16 role;     /* MS_ROLE_*, MS_NO_ROLE */
    s16 x;
    s16 y;
    s16 w;
    s16 h;
} MS_Hitbox;

typedef struct MS_RECORD
{
    u8 type;      /* MS_POINT_* */
    u8 reserved0;
    u16 role;     /* MS_ROLE_*, MS_NO_ROLE */
    s16 x;
    s16 y;
} MS_Point;

#define MS_NO_ROLE 0xFFFFu
#define MS_UNKNOWN_TYPE 0xFFu

typedef struct MS_RECORD
{
    u16 frame_index;
    u16 duration_ticks;
    u16 first_event;
    u8 event_count;
    u8 reserved0;
} MS_AnimStep;

typedef struct MS_RECORD
{
    u32 first_step;
    u16 step_count;
    u16 fps;
    u8 playback;
    u8 reserved0;
    u16 loop_start;      /* MS_PLAY_LOOP: later passes start at this step */
    u16 next_animation;  /* continue with this animation when it ends, MS_NO_ANIMATION = none */
    u16 loop_count;      /* repeats before it ends, 0 = forever */
} MS_Animation;

typedef struct MS_RECORD
{
    u16 type;   /* MS_EVENT_* */
    s16 value;  /* free parameter, e.g. which sound */
} MS_StepEvent;

#define MS_NO_ANIMATION 0xFFFFu

typedef struct MS_RECORD
{
    u32 first_sample;
    u16 sample_count;
    u16 fps;
    u16 duration_ticks;
    u8 loop;
    u8 reserved0;
    u8 reserved1;
    u8 reserved2;
} MS_Scene;

extern u16 ms_variant_count;
extern u32 ms_part_count;
extern u16 ms_render_frame_count;

extern u16 ms_module_count;
extern u16 ms_frame_count;
extern u16 ms_animation_count;
extern u16 ms_scene_count;
extern u16 ms_mapping_count;

extern u16 ms_anim_step_count;
extern u16 ms_scene_sample_count;
extern u16 ms_animation_record_count;
extern u16 ms_scene_record_count;
extern u16 ms_event_type_count;
extern u16 ms_step_event_count;
extern u16 ms_tile_count;
extern u16 ms_piece_count;
extern u16 ms_hitbox_count;
extern u16 ms_point_count;
extern u16 ms_hitbox_type_count;
extern u16 ms_point_type_count;
extern u16 ms_role_count;

#define MS_VARIANT_COUNT (ms_variant_count)
#define MS_PART_COUNT (ms_part_count)
#define MS_RENDER_FRAME_COUNT (ms_render_frame_count)
#define MS_MODULE_COUNT (ms_module_count)
#define MS_FRAME_COUNT (ms_frame_count)
#define MS_ANIMATION_COUNT (ms_animation_count)
#define MS_SCENE_COUNT (ms_scene_count)
#define MS_MAPPING_COUNT (ms_mapping_count)
#define MS_ANIM_STEP_COUNT (ms_anim_step_count)
#define MS_SCENE_SAMPLE_COUNT (ms_scene_sample_count)
#define MS_ANIMATION_RECORD_COUNT (ms_animation_record_count)
#define MS_SCENE_RECORD_COUNT (ms_scene_record_count)
#define MS_EVENT_TYPE_COUNT (ms_event_type_count)
#define MS_STEP_EVENT_COUNT (ms_step_event_count)
#define MS_TILE_COUNT (ms_tile_count)

extern const MS_Variant *ms_variants;
extern const MS_Piece *ms_pieces;
extern const u32 *ms_tiles;
extern const u16 *ms_palette;
extern const MS_Hitbox *ms_hitboxes;
extern const MS_Point *ms_points;
extern const MS_Part *ms_parts;
extern const MS_RenderFrame *ms_render_frames;
extern const u16 *ms_module_render_frames;
extern const u16 *ms_frame_render_frames;
extern const MS_AnimStep *ms_anim_steps;
extern const MS_Animation *ms_animations;
extern const u16 *ms_scene_samples;
extern const MS_Scene *ms_scenes;
extern const MS_StepEvent *ms_step_events;

void ms_data_init(void);
u8 ms_data_is_ready(void);

const char *ms_mapping_id(u16 index);
const char *ms_mapping_name_data(u16 index);
const char *ms_module_id(u16 index);
const char *ms_module_name_data(u16 index);
const char *ms_frame_id(u16 index);
const char *ms_frame_name_data(u16 index);
const char *ms_animation_id(u16 index);
const char *ms_animation_name_data(u16 index);
const char *ms_scene_id(u16 index);
const char *ms_scene_name_data(u16 index);
const char *ms_event_name_data(u16 index);
const char *ms_hitbox_type_name_data(u16 index);
const char *ms_point_type_name_data(u16 index);
const char *ms_role_name_data(u16 index);

/* Animation events (project event types, in the editor's order). */
@EVENT_DEFINES@

/* Hitbox types and point types (the editor's lists, in order). */
@TYPE_DEFINES@

/* Roles of hitboxes and points (sorted by name). */
@ROLE_DEFINES@

#endif
"""
        def define_lines(symbols: Sequence[str]) -> str:
            return "\n".join(f"#define {symbol} {i}u" for i, symbol in enumerate(symbols)) or "/* none */"

        text = text.replace("@EVENT_DEFINES@", define_lines(self.event_symbols))
        text = text.replace("@TYPE_DEFINES@", define_lines(self.box_type_symbols) + "\n" + define_lines(self.point_type_symbols))
        text = text.replace("@ROLE_DEFINES@", define_lines(self.role_symbols))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _emit_resources(self, path: Path) -> None:
        """Put the blob's line into the resource file. Tiles, pieces and palette live in the blob: the runtime loads
        them into VRAM once. The game's other resources in the file stay (older exporters replaced the whole file)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        path.write_text(merged_resources(existing), encoding="utf-8")

    def _emit_data_c(self, path: Path) -> None:
        text = f"""#include <genesis.h>
#include <string.h>
#include "modsprite_data.h"
#include "resources.h"

#define MS_BLOB_MAGIC 0x4D534231u
#define MS_BLOB_VERSION {BLOB_VERSION}u
#define MS_BLOB_HEADER_SIZE {BLOB_HEADER_SIZE}u

enum
{{
    MS_SEC_PARTS = 0,
    MS_SEC_RENDER_FRAMES = 1,
    MS_SEC_MODULE_RENDER_FRAMES = 2,
    MS_SEC_FRAME_RENDER_FRAMES = 3,
    MS_SEC_ANIM_STEPS = 4,
    MS_SEC_ANIMATIONS = 5,
    MS_SEC_SCENE_SAMPLES = 6,
    MS_SEC_SCENES = 7,
    MS_SEC_MAPPING_IDS = 8,
    MS_SEC_MAPPING_NAMES = 9,
    MS_SEC_MODULE_IDS = 10,
    MS_SEC_MODULE_NAMES = 11,
    MS_SEC_FRAME_IDS = 12,
    MS_SEC_FRAME_NAMES = 13,
    MS_SEC_ANIMATION_IDS = 14,
    MS_SEC_ANIMATION_NAMES = 15,
    MS_SEC_SCENE_IDS = 16,
    MS_SEC_SCENE_NAMES = 17,
    MS_SEC_STRINGS = 18,
    MS_SEC_STEP_EVENTS = 19,
    MS_SEC_EVENT_NAMES = 20,
    MS_SEC_VARIANTS = 21,
    MS_SEC_PIECES = 22,
    MS_SEC_TILES = 23,
    MS_SEC_PALETTE = 24,
    MS_SEC_HITBOXES = 25,
    MS_SEC_POINTS = 26,
    MS_SEC_HITBOX_TYPE_NAMES = 27,
    MS_SEC_POINT_TYPE_NAMES = 28,
    MS_SEC_ROLE_NAMES = 29,
    MS_SEC_COUNT = 30
}};

u16 ms_variant_count = 0;
u32 ms_part_count = 0;
u16 ms_render_frame_count = 0;
u16 ms_module_count = 0;
u16 ms_frame_count = 0;
u16 ms_animation_count = 0;
u16 ms_scene_count = 0;
u16 ms_mapping_count = 0;
u16 ms_anim_step_count = 0;
u16 ms_scene_sample_count = 0;
u16 ms_animation_record_count = 0;
u16 ms_scene_record_count = 0;
u16 ms_event_type_count = 0;
u16 ms_step_event_count = 0;
u16 ms_tile_count = 0;
u16 ms_piece_count = 0;
u16 ms_hitbox_count = 0;
u16 ms_point_count = 0;
u16 ms_hitbox_type_count = 0;
u16 ms_point_type_count = 0;
u16 ms_role_count = 0;

const MS_Variant *ms_variants = NULL;
const MS_Piece *ms_pieces = NULL;
const u32 *ms_tiles = NULL;
const u16 *ms_palette = NULL;
const MS_Hitbox *ms_hitboxes = NULL;
const MS_Point *ms_points = NULL;
const MS_Part *ms_parts = NULL;
const MS_RenderFrame *ms_render_frames = NULL;
const u16 *ms_module_render_frames = NULL;
const u16 *ms_frame_render_frames = NULL;
const MS_AnimStep *ms_anim_steps = NULL;
const MS_Animation *ms_animations = NULL;
const u16 *ms_scene_samples = NULL;
const MS_Scene *ms_scenes = NULL;
const MS_StepEvent *ms_step_events = NULL;

static const u8 *g_blob = NULL;
static u32 g_blob_size = 0;
static u8 g_data_ready = FALSE;
static u8 g_data_attempted = FALSE;
static u32 g_section_offsets[MS_SEC_COUNT];
static u32 g_strings_base = 0;
static u32 g_strings_size = 0;
static const u8 *g_mapping_id_offsets = NULL;
static const u8 *g_mapping_name_offsets = NULL;
static const u8 *g_module_id_offsets = NULL;
static const u8 *g_module_name_offsets = NULL;
static const u8 *g_frame_id_offsets = NULL;
static const u8 *g_frame_name_offsets = NULL;
static const u8 *g_animation_id_offsets = NULL;
static const u8 *g_animation_name_offsets = NULL;
static const u8 *g_scene_id_offsets = NULL;
static const u8 *g_scene_name_offsets = NULL;
static const u8 *g_event_name_offsets = NULL;
static const u8 *g_hitbox_type_name_offsets = NULL;
static const u8 *g_point_type_name_offsets = NULL;
static const u8 *g_role_name_offsets = NULL;

static u16 ms_read_be16(const u8 *ptr)
{{
    return (u16)(((u16)ptr[0] << 8) | (u16)ptr[1]);
}}

static u32 ms_read_be32(const u8 *ptr)
{{
    return ((u32)ptr[0] << 24) | ((u32)ptr[1] << 16) | ((u32)ptr[2] << 8) | (u32)ptr[3];
}}

static void ms_reset_data(void)
{{
    ms_variant_count = 0;
    ms_part_count = 0;
    ms_render_frame_count = 0;
    ms_module_count = 0;
    ms_frame_count = 0;
    ms_animation_count = 0;
    ms_scene_count = 0;
    ms_mapping_count = 0;
    ms_anim_step_count = 0;
    ms_scene_sample_count = 0;
    ms_animation_record_count = 0;
    ms_scene_record_count = 0;
    ms_event_type_count = 0;
    ms_step_event_count = 0;
    ms_tile_count = 0;
    ms_piece_count = 0;
    ms_hitbox_count = 0;
    ms_point_count = 0;
    ms_hitbox_type_count = 0;
    ms_point_type_count = 0;
    ms_role_count = 0;

    ms_variants = NULL;
    ms_pieces = NULL;
    ms_tiles = NULL;
    ms_palette = NULL;
    ms_hitboxes = NULL;
    ms_points = NULL;
    ms_parts = NULL;
    ms_render_frames = NULL;
    ms_module_render_frames = NULL;
    ms_frame_render_frames = NULL;
    ms_anim_steps = NULL;
    ms_animations = NULL;
    ms_scene_samples = NULL;
    ms_scenes = NULL;
    ms_step_events = NULL;

    g_mapping_id_offsets = NULL;
    g_mapping_name_offsets = NULL;
    g_module_id_offsets = NULL;
    g_module_name_offsets = NULL;
    g_frame_id_offsets = NULL;
    g_frame_name_offsets = NULL;
    g_animation_id_offsets = NULL;
    g_animation_name_offsets = NULL;
    g_scene_id_offsets = NULL;
    g_scene_name_offsets = NULL;
    g_event_name_offsets = NULL;
    g_hitbox_type_name_offsets = NULL;
    g_point_type_name_offsets = NULL;
    g_role_name_offsets = NULL;
    g_strings_base = 0;
    g_strings_size = 0;
    g_data_ready = FALSE;
}}

static u8 ms_blob_range_ok(u32 offset, u32 size)
{{
    if (offset > g_blob_size)
        return FALSE;
    if (size > (g_blob_size - offset))
        return FALSE;
    return TRUE;
}}

u8 ms_data_is_ready(void)
{{
    return g_data_ready;
}}

void ms_data_init(void)
{{
    const u8 *ptr;
    u16 i;

    if (g_data_attempted)
        return;

    g_data_attempted = TRUE;
    ms_reset_data();

    g_blob = MS_BLOB;
    g_blob_size = (u32)sizeof(MS_BLOB);
    if (g_blob_size < MS_BLOB_HEADER_SIZE)
        return;

    ptr = g_blob;
    if (ms_read_be32(ptr) != MS_BLOB_MAGIC)
        return;
    ptr += 4;
    if (ms_read_be16(ptr) != MS_BLOB_VERSION)
        return;
    ptr += 2;
    ptr += 2; /* reserved */

    ms_variant_count = ms_read_be16(ptr); ptr += 2;
    ms_module_count = ms_read_be16(ptr); ptr += 2;
    ms_frame_count = ms_read_be16(ptr); ptr += 2;
    ms_animation_count = ms_read_be16(ptr); ptr += 2;
    ms_scene_count = ms_read_be16(ptr); ptr += 2;
    ms_mapping_count = ms_read_be16(ptr); ptr += 2;
    ms_render_frame_count = ms_read_be16(ptr); ptr += 2;
    ms_anim_step_count = ms_read_be16(ptr); ptr += 2;
    ms_scene_sample_count = ms_read_be16(ptr); ptr += 2;
    ms_animation_record_count = ms_read_be16(ptr); ptr += 2;
    ms_scene_record_count = ms_read_be16(ptr); ptr += 2;
    ms_event_type_count = ms_read_be16(ptr); ptr += 2;
    ms_step_event_count = ms_read_be16(ptr); ptr += 2;
    ms_tile_count = ms_read_be16(ptr); ptr += 2;
    ms_piece_count = ms_read_be16(ptr); ptr += 2;
    ms_hitbox_count = ms_read_be16(ptr); ptr += 2;
    ms_point_count = ms_read_be16(ptr); ptr += 2;
    ms_hitbox_type_count = ms_read_be16(ptr); ptr += 2;
    ms_point_type_count = ms_read_be16(ptr); ptr += 2;
    ms_role_count = ms_read_be16(ptr); ptr += 2;
    ms_part_count = ms_read_be32(ptr); ptr += 4;

    for (i = 0; i < MS_SEC_COUNT; i++)
    {{
        g_section_offsets[i] = ms_read_be32(ptr);
        ptr += 4;
    }}
    g_strings_size = ms_read_be32(ptr);

    ms_parts = (const MS_Part *)(g_blob + g_section_offsets[MS_SEC_PARTS]);
    ms_render_frames = (const MS_RenderFrame *)(g_blob + g_section_offsets[MS_SEC_RENDER_FRAMES]);
    ms_module_render_frames = (const u16 *)(g_blob + g_section_offsets[MS_SEC_MODULE_RENDER_FRAMES]);
    ms_frame_render_frames = (const u16 *)(g_blob + g_section_offsets[MS_SEC_FRAME_RENDER_FRAMES]);
    ms_anim_steps = (const MS_AnimStep *)(g_blob + g_section_offsets[MS_SEC_ANIM_STEPS]);
    ms_animations = (const MS_Animation *)(g_blob + g_section_offsets[MS_SEC_ANIMATIONS]);
    ms_scene_samples = (const u16 *)(g_blob + g_section_offsets[MS_SEC_SCENE_SAMPLES]);
    ms_scenes = (const MS_Scene *)(g_blob + g_section_offsets[MS_SEC_SCENES]);
    g_mapping_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_MAPPING_IDS]);
    g_mapping_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_MAPPING_NAMES]);
    g_module_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_MODULE_IDS]);
    g_module_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_MODULE_NAMES]);
    g_frame_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_FRAME_IDS]);
    g_frame_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_FRAME_NAMES]);
    g_animation_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_ANIMATION_IDS]);
    g_animation_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_ANIMATION_NAMES]);
    g_scene_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SCENE_IDS]);
    g_scene_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SCENE_NAMES]);
    ms_step_events = (const MS_StepEvent *)(g_blob + g_section_offsets[MS_SEC_STEP_EVENTS]);
    g_event_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_EVENT_NAMES]);
    ms_variants = (const MS_Variant *)(g_blob + g_section_offsets[MS_SEC_VARIANTS]);
    ms_pieces = (const MS_Piece *)(g_blob + g_section_offsets[MS_SEC_PIECES]);
    ms_tiles = (const u32 *)(g_blob + g_section_offsets[MS_SEC_TILES]);
    ms_palette = (const u16 *)(g_blob + g_section_offsets[MS_SEC_PALETTE]);
    ms_hitboxes = (const MS_Hitbox *)(g_blob + g_section_offsets[MS_SEC_HITBOXES]);
    ms_points = (const MS_Point *)(g_blob + g_section_offsets[MS_SEC_POINTS]);
    g_hitbox_type_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_HITBOX_TYPE_NAMES]);
    g_point_type_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_POINT_TYPE_NAMES]);
    g_role_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_ROLE_NAMES]);

    g_strings_base = g_section_offsets[MS_SEC_STRINGS];

    g_data_ready = TRUE;
}}

static const char *ms_lookup_string(const u8 *offsets, u16 count, u16 index)
{{
    u32 off;

    if (!g_data_ready || !offsets || index >= count)
        return "";
    off = ms_read_be32(offsets + ((u32)index * 4u));
    if (!ms_blob_range_ok(off, 1u))
        return "";
    return (const char *)(g_blob + off);
}}

const char *ms_mapping_id(u16 index) {{ return ms_lookup_string(g_mapping_id_offsets, ms_mapping_count, index); }}
const char *ms_mapping_name_data(u16 index) {{ return ms_lookup_string(g_mapping_name_offsets, ms_mapping_count, index); }}
const char *ms_module_id(u16 index) {{ return ms_lookup_string(g_module_id_offsets, ms_module_count, index); }}
const char *ms_module_name_data(u16 index) {{ return ms_lookup_string(g_module_name_offsets, ms_module_count, index); }}
const char *ms_frame_id(u16 index) {{ return ms_lookup_string(g_frame_id_offsets, ms_frame_count, index); }}
const char *ms_frame_name_data(u16 index) {{ return ms_lookup_string(g_frame_name_offsets, ms_frame_count, index); }}
const char *ms_animation_id(u16 index) {{ return ms_lookup_string(g_animation_id_offsets, ms_animation_count, index); }}
const char *ms_animation_name_data(u16 index) {{ return ms_lookup_string(g_animation_name_offsets, ms_animation_count, index); }}
const char *ms_scene_id(u16 index) {{ return ms_lookup_string(g_scene_id_offsets, ms_scene_count, index); }}
const char *ms_scene_name_data(u16 index) {{ return ms_lookup_string(g_scene_name_offsets, ms_scene_count, index); }}
const char *ms_event_name_data(u16 index) {{ return ms_lookup_string(g_event_name_offsets, ms_event_type_count, index); }}
const char *ms_hitbox_type_name_data(u16 index) {{ return ms_lookup_string(g_hitbox_type_name_offsets, ms_hitbox_type_count, index); }}
const char *ms_point_type_name_data(u16 index) {{ return ms_lookup_string(g_point_type_name_offsets, ms_point_type_count, index); }}
const char *ms_role_name_data(u16 index) {{ return ms_lookup_string(g_role_name_offsets, ms_role_count, index); }}
"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _resolve_mappings(project: Project, mapping_selector: str) -> List[Optional[ModuleMapping]]:
    selector = str(mapping_selector or "auto").strip()
    lower = selector.lower()

    if lower in ("none", "off", "null"):
        return [None]

    if lower in ("auto", "all", "*"):
        return [None] + list(project.mappings)

    for item in project.mappings:
        if item.id == selector:
            return [None, item]
        if item.name.strip().lower() == lower:
            return [None, item]
    raise ValueError(f"Mapping '{mapping_selector}' was not found. Available: {[m.name for m in project.mappings]}")


def _copy_if_needed(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


@dataclass
class ExportResult:
    summary: Dict[str, Any]           # counts: tiles, sprites, steps, blob size, ...
    issues: List[Issue]               # Check Project's errors and warnings, the colours and the tiles
    files: List[Path]                 # what was written


def export_project(
    project: Project,
    output_demo_dir: Path,
    mapping_selector: str = "all",
    project_path: Optional[Path] = None,
    copy_assets: bool = False,
) -> ExportResult:
    """Bake a project into an SGDK project folder (its res/, inc/ and src/ get the data files) and report what the
    game will see: Check Project's errors and warnings, merged colours and how the tiles fit in video memory."""
    output_demo_dir = Path(output_demo_dir).resolve()
    mappings = _resolve_mappings(project, mapping_selector)
    issues = [issue for issue in project_check.check_project(project) if issue.level != project_check.INFO]

    bake = SGDKBakeContext(project=project, mappings=mappings, output_demo_dir=output_demo_dir)
    bake.bake()
    files = [output_demo_dir / BLOB_FILE, output_demo_dir / HEADER_FILE, output_demo_dir / DATA_C_FILE,
             output_demo_dir / RESOURCE_FILE]
    bake._emit_blob(files[0])
    bake._emit_header(files[1])
    bake._emit_data_c(files[2])
    bake._emit_resources(files[3])

    if copy_assets and project_path is not None:
        _copy_if_needed(Path(project_path), output_demo_dir / "source" / Path(project_path).name)
        for asset in project.images:
            image_path = Path(asset.file_path)
            if image_path.exists():
                _copy_if_needed(image_path, output_demo_dir / "source" / image_path.name)

    tiles = len(bake.tile_data) // 32
    if getattr(bake, "palette_note", "") and not any(issue.code == "too-many-colours" for issue in issues):
        issues.append(Issue(project_check.WARNING, "too-many-colours", bake.palette_note.replace("warning: ", "", 1)))
    issues.append(project_check.tile_issue(tiles))
    summary = {
        "mapping_count": len(mappings),
        "mappings": ", ".join(bake.mapping_names),
        "variants": len(bake.variants),
        "hardware_sprite_pieces": len(bake.pieces),
        "tiles": tiles,
        "hitboxes": len(bake.boxes),
        "points": len(bake.points),
        "parts": len(bake.parts),
        "render_frames": len(bake.render_frames),
        "modules": len(project.modules),
        "frames": len(project.frames),
        "animations": len(project.animations),
        "scenes": len(project.timeline_scenes),
        "anim_steps": len(bake.anim_steps),
        "scene_samples": len(bake.scene_samples),
        "blob_size_bytes": bake.blob_size_bytes,
    }
    order = project_check.LEVEL_ORDER
    return ExportResult(summary, sorted(issues, key=lambda issue: order[issue.level]), files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bake modular sprite project JSON into SGDK demo assets.")
    parser.add_argument(
        "--project-json",
        default=str((REPO_ROOT / "examples" / "sgdk" / "PoP_WW.json").resolve()),
        help="Path to source project JSON.",
    )
    parser.add_argument(
        "--output-demo-dir",
        default=str((REPO_ROOT / "examples" / "sgdk" / "sgdk_demo").resolve()),
        help="Target SGDK demo directory.",
    )
    parser.add_argument(
        "--mapping",
        default="all",
        help="Mapping name/id, 'all' (default), 'auto', or 'none'.",
    )
    parser.add_argument(
        "--copy-assets",
        action="store_true",
        help="Copy source JSON and source atlas image into the demo directory for reference.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with 1 when the project has errors (Check Project), e.g. steps whose frame was deleted.",
    )

    args = parser.parse_args()
    project_json_path = Path(args.project_json).resolve()
    project = Project.from_json(str(project_json_path))
    result = export_project(project, Path(args.output_demo_dir), args.mapping, project_json_path, args.copy_assets)

    for key, value in result.summary.items():
        print(f"{key}: {value}")
    for issue in result.issues:
        print(f"{'note' if issue.level == project_check.INFO else issue.level}: {issue.text}")
    if args.strict and any(issue.level == project_check.ERROR for issue in result.issues):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
