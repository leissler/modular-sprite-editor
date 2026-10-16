#!/usr/bin/env python3
"""Bake editor JSON into an SGDK example project (resources + binary data blob).

The console-independent bake (parts through nested frames, animations, scenes, mappings, hitboxes and points) is
console_bake.ConsoleBake; MegaDriveBakeContext adds what the Mega Drive needs: VDP tiles, the hardware sprite cut, CRAM
palettes, the blob and its C side."""

from __future__ import annotations

import hashlib
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

# The repo root; for the packaged exporter (export_megadrive.exe) the folder it sits in, which holds the same
# examples/ layout, so the defaults below work there too.
if getattr(sys, "frozen", False):
    REPO_ROOT = Path(sys.executable).resolve().parent
else:
    REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import consoles  # noqa: E402
from console_bake import (  # noqa: E402
    ConsoleBake, RenderFrameSpan, copy_sources, export_arguments, print_result, resolve_mappings,
)
import sprite_cut  # noqa: E402
from models import ModuleMapping, Project  # noqa: E402
import palettes  # noqa: E402
import project_check  # noqa: E402
from project_check import Issue  # noqa: E402




@dataclass(frozen=True)
class VariantMeta:
    tile_w: int
    tile_h: int
    first_piece: int
    piece_count: int


# (dx, dy, VDP size code, tile offset, palette entry byte): one hardware sprite of a variant. The entry byte names the
# palette entry the sprite's colours come from; FIXED_ENTRY set: as it is, not recoloured by the swap the game draws with.
PieceEntry = Tuple[int, int, int, int, int]
# 2: step events, loop-from step, follow-up animation, repeat count
# 3: tiles, pieces and palette in the blob (VRAM-resident runtime, no SGDK sprite resources),
#    hitboxes and points per render frame, type and role names, sprite count and bounds per render frame
# 4: a palette per image group (the header's former spare field counts them); a piece's tile offset carries its
#    palette in bits 13-14, so drawing adds it to the sprite attribute like the tile index
# 5: palette entries (every palette, then every swap's version of the palettes it changes) with names and colour
#    cycles, the swaps' entry table; a piece names its palette entry in its spare byte (the runtime turns entries into
#    palette lines at draw time), its tile offset has no palette bits any more
BLOB_VERSION = 5
BLOB_COUNT_FIELDS = 23
BLOB_SECTION_COUNT = 36
BLOB_HEADER_SIZE = 4 + 2 + 2 + BLOB_COUNT_FIELDS * 2 + 4 + BLOB_SECTION_COUNT * 4 + 4
TILE = 8
MD_PALETTE = consoles.MEGA_DRIVE.palette  # every palette entry is a CRAM line: transparent + 15 colours

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


class MegaDriveBakeContext(ConsoleBake):
    """The Mega Drive (SGDK) half of the export: ConsoleBake's parts as VDP tiles and hardware sprites (variants and
    their pieces, one list per flip), the palettes as CRAM words, and all of it in one blob with its C record types and
    parser."""

    def __init__(self, project: Project, mappings: List[Optional[ModuleMapping]], output_dir: Path) -> None:
        super().__init__(project, mappings)
        self.output_dir = output_dir
        self.output_gen_dir = output_dir / "res" / "gen"

        self.variant_lookup: Dict[Tuple[int, int, str], int] = {}
        self.variants: List[VariantMeta] = []
        self.pieces: List[PieceEntry] = []
        self.piece_lists: Dict[Tuple[int, int, int], Tuple[int, int]] = {}  # (variant, hflip, vflip) -> (first, count)
        self.tile_data = bytearray()
        self.piece_tiles_lookup: Dict[bytes, int] = {}
        self.variant_blocks: List[List[PieceEntry]] = []  # unflipped hardware sprites of each variant
        self.blob_size_bytes: int = 0

    def bake(self) -> None:
        self._prepare_output_dirs()
        super().bake()
        self._finalize_pieces()

    def _prepare_output_dirs(self) -> None:
        """Create res/gen and remove older exporters' sprite sheets from it; the game's own files there stay."""
        self.output_gen_dir.mkdir(parents=True, exist_ok=True)
        for child in self.output_gen_dir.iterdir():
            if child.is_file() and LEGACY_VARIANT_FILE.fullmatch(child.name):
                child.unlink()

    def _store_part(self, image: Image.Image, palette: str, entry: int) -> int:
        """ConsoleBake's hook: a part image's hardware sprites (a variant), stored in its palette's slots and drawn
        from palette entry ``entry`` (pieces of one image with another entry share its tiles)."""
        rgba = image.convert("RGBA")
        digest = hashlib.sha1(rgba.tobytes()).hexdigest()
        key = (rgba.width, rgba.height, digest, palette, entry)
        found = self.variant_lookup.get(key)
        if found is not None:
            return found

        out_w = max(TILE, ((rgba.width + TILE - 1) // TILE) * TILE)
        out_h = max(TILE, ((rgba.height + TILE - 1) // TILE) * TILE)
        padded = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        padded.alpha_composite(rgba, (0, 0))
        indexed = self._to_indexed(padded, palette)
        pixels = indexed.tobytes()

        # Hardware sprites of at most 32×32: the fewest, then the fewest tiles, at any pixel of the padded part
        # (sprite_cut.export_cut, which hardware_budget counts too).
        blocks: List[PieceEntry] = []
        for bx, by, bw, bh in sprite_cut.export_cut(rgba):
            tiles = self._block_tiles(pixels, out_w, bx, by, bw // TILE, bh // TILE)
            offset = self.piece_tiles_lookup.get(tiles)
            if offset is None:
                offset = len(self.tile_data) // 32
                self.tile_data.extend(tiles)
                self.piece_tiles_lookup[tiles] = offset
            size_code = (((bw // TILE) - 1) << 2) | ((bh // TILE) - 1)
            blocks.append((bx, by, size_code, offset, entry))

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
        for bx, by, size_code, offset, entry in self.variant_blocks[variant_index]:
            w, h = (((size_code >> 2) & 3) + 1) * TILE, ((size_code & 3) + 1) * TILE
            x = pad_w - bx - w if hflip else bx
            y = pad_h - by - h if vflip else by
            self.pieces.append((x, y, size_code, offset, entry))
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
            for dx, dy, size_code, _offset, _entry in self.pieces[first:first + n]:
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

    def _entry_cycles(self, entry: palettes.Entry) -> List[Any]:
        visible = MD_PALETTE.visible
        return [c for c in entry.cycles if c.count >= 2 and 1 <= c.first and c.first + c.count - 1 <= visible]

    def packed_palette_words(self) -> List[int]:
        """16 CRAM words per palette entry: slot 0 (transparent), then its colours with rescomp's rounding (3 bits
        per channel, truncated), free slots black. A project whose palettes follow another console (fewer colours)
        fills the rest with black too."""
        visible = MD_PALETTE.visible
        words: List[int] = []
        for entry in self.palette_entries:
            words.append(0)
            words.extend(palettes.md_word(entry.colours[slot] if slot < len(entry.colours) else (0, 0, 0))
                         for slot in range(visible))
        return words

    def packed_palette_entries(self) -> List[Tuple[int, int, int, int]]:
        """(palette, swap number (0 = none), first cycle, cycle count) per palette entry."""
        swap_ids = [s.id for s in self.swaps]
        out, first = [], 0
        for entry in self.palette_entries:
            count = len(self._entry_cycles(entry))
            swap = 0 if entry.swap_id is None else 1 + swap_ids.index(entry.swap_id)
            out.append((self.palette_ids.index(entry.palette_id), swap, first, count))
            first += count
        return out

    def packed_colour_cycles(self) -> List[Tuple[int, int, int, int]]:
        """(first slot, count, frames per step, reverse) of every entry's cycles, in entry order."""
        return [(int(c.first), int(c.count), max(1, min(0xFFFF, int(c.frames))), 1 if c.reverse else 0)
                for entry in self.palette_entries for c in self._entry_cycles(entry)]

    def packed_swap_entries(self) -> List[int]:
        """For each swap (from swap 1), the entry each palette is drawn from."""
        return [self.entry_of.get((pid, swap.id), self.entry_of[(pid, None)])
                for swap in self.swaps for pid in self.palette_ids]

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
            "palette_entries",
            "colour_cycles",
            "swap_entries",
            "swap_ids",
            "swap_names",
            "palette_names",
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
        for dx, dy, size_code, tile_offset, entry in self.pieces:
            pieces_raw.extend(struct.pack(">hhBBH", int(dx), int(dy), int(size_code), int(entry), int(tile_offset)))

        palette_raw = bytearray()
        for word in self.packed_palette_words():
            palette_raw.extend(self._be16(word))
        entries_raw = bytearray()
        for record in self.packed_palette_entries():
            entries_raw.extend(struct.pack(">BBHBB", *record, 0))
        cycles_raw = bytearray()
        cycle_records = self.packed_colour_cycles()
        cycle_count = len(cycle_records)
        for record in cycle_records:
            cycles_raw.extend(struct.pack(">BBHBB", *record, 0))
        swap_entries_raw = bytearray(self.packed_swap_entries())
        swap_ids_rel = append_string_list([""] + [swap.id for swap in self.swaps])
        swap_names_rel = append_string_list(["<none>"] + [swap.name for swap in self.swaps])
        palette_names_rel = append_string_list([entry.name for entry in self.palette_entries])

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
        append_section("palette_entries", bytes(entries_raw))
        append_section("colour_cycles", bytes(cycles_raw))
        append_section("swap_entries", bytes(swap_entries_raw))
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
        append_section("swap_ids", build_string_offset_section(swap_ids_rel))
        append_section("swap_names", build_string_offset_section(swap_names_rel))
        append_section("palette_names", build_string_offset_section(palette_names_rel))

        header = bytearray()
        header.extend(b"MSB1")
        header.extend(self._be16(BLOB_VERSION))
        header.extend(self._be16(len(self.palette_entries)))  # palette entries (one line each when loaded)
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
        header.extend(self._be16(len(self.palette_ids)))  # the first entries: the palettes themselves
        header.extend(self._be16(len(self.swaps) + 1))  # palette swaps, 0 = none
        header.extend(self._be16(cycle_count))
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
    u8 palette;       /* the palette entry its colours come from; MS_FIXED_ENTRY set: not recoloured by the swap */
    u16 tile_offset;  /* first tile, from the runtime's tile base */
} MS_Piece;

#define MS_FIXED_ENTRY 0x80u

/* A palette entry: one of the editor's palettes, or what a palette swap makes of one. Its 16 colours are at
   ms_palette[entry * 16]; ms_init() loads entries into consecutive palette lines as far as they fit. */
typedef struct MS_RECORD
{
    u8 palette;       /* the editor's palette it is, or recolours */
    u8 swap;          /* the palette swap that made it, 0 = the palette itself */
    u16 first_cycle;  /* its colour cycles: ms_colour_cycles[first_cycle .. + cycle_count - 1] */
    u8 cycle_count;
    u8 reserved0;
} MS_PaletteEntry;

/* A colour cycle: count slots from first rotate one slot up (down if reverse) every frames video frames. */
typedef struct MS_RECORD
{
    u8 first;
    u8 count;
    u16 frames;
    u8 reverse;
    u8 reserved0;
} MS_ColourCycle;

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
extern u16 ms_palette_entry_count;
extern u16 ms_base_palette_count;
extern u16 ms_palette_swap_count;
extern u16 ms_colour_cycle_count;
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
#define MS_PALETTE_ENTRY_COUNT (ms_palette_entry_count) /* palette entries, 16 colours each in ms_palette */
#define MS_BASE_PALETTE_COUNT (ms_base_palette_count)   /* the first entries are the editor's palettes */
#define MS_PALETTE_SWAP_COUNT (ms_palette_swap_count)   /* palette swaps, 0 = none */
#define MS_COLOUR_CYCLE_COUNT (ms_colour_cycle_count)

extern const MS_Variant *ms_variants;
extern const MS_Piece *ms_pieces;
extern const u32 *ms_tiles;
extern const u16 *ms_palette;
extern const MS_PaletteEntry *ms_palette_entries;
extern const MS_ColourCycle *ms_colour_cycles;
extern const u8 *ms_swap_entries;  /* swap s (from 1): ms_swap_entries[(s - 1) * MS_BASE_PALETTE_COUNT + palette] */
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
const char *ms_palette_swap_id(u16 index);
const char *ms_palette_swap_name_data(u16 index);
const char *ms_palette_entry_name_data(u16 index);

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
    MS_SEC_PALETTE_ENTRIES = 30,
    MS_SEC_COLOUR_CYCLES = 31,
    MS_SEC_SWAP_ENTRIES = 32,
    MS_SEC_SWAP_IDS = 33,
    MS_SEC_SWAP_NAMES = 34,
    MS_SEC_PALETTE_NAMES = 35,
    MS_SEC_COUNT = 36
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
u16 ms_palette_entry_count = 0;
u16 ms_base_palette_count = 0;
u16 ms_palette_swap_count = 0;
u16 ms_colour_cycle_count = 0;
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
const MS_PaletteEntry *ms_palette_entries = NULL;
const MS_ColourCycle *ms_colour_cycles = NULL;
const u8 *ms_swap_entries = NULL;
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
static const u8 *g_swap_id_offsets = NULL;
static const u8 *g_swap_name_offsets = NULL;
static const u8 *g_palette_name_offsets = NULL;

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
    ms_palette_entry_count = 0;
    ms_base_palette_count = 0;
    ms_palette_swap_count = 0;
    ms_colour_cycle_count = 0;
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
    ms_palette_entries = NULL;
    ms_colour_cycles = NULL;
    ms_swap_entries = NULL;
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
    g_swap_id_offsets = NULL;
    g_swap_name_offsets = NULL;
    g_palette_name_offsets = NULL;
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
    ms_palette_entry_count = ms_read_be16(ptr); ptr += 2;

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
    ms_base_palette_count = ms_read_be16(ptr); ptr += 2;
    ms_palette_swap_count = ms_read_be16(ptr); ptr += 2;
    ms_colour_cycle_count = ms_read_be16(ptr); ptr += 2;
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
    ms_palette_entries = (const MS_PaletteEntry *)(g_blob + g_section_offsets[MS_SEC_PALETTE_ENTRIES]);
    ms_colour_cycles = (const MS_ColourCycle *)(g_blob + g_section_offsets[MS_SEC_COLOUR_CYCLES]);
    ms_swap_entries = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SWAP_ENTRIES]);
    ms_hitboxes = (const MS_Hitbox *)(g_blob + g_section_offsets[MS_SEC_HITBOXES]);
    ms_points = (const MS_Point *)(g_blob + g_section_offsets[MS_SEC_POINTS]);
    g_hitbox_type_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_HITBOX_TYPE_NAMES]);
    g_point_type_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_POINT_TYPE_NAMES]);
    g_role_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_ROLE_NAMES]);
    g_swap_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SWAP_IDS]);
    g_swap_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SWAP_NAMES]);
    g_palette_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_PALETTE_NAMES]);

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
const char *ms_palette_swap_id(u16 index) {{ return ms_lookup_string(g_swap_id_offsets, ms_palette_swap_count, index); }}
const char *ms_palette_swap_name_data(u16 index) {{ return ms_lookup_string(g_swap_name_offsets, ms_palette_swap_count, index); }}
const char *ms_palette_entry_name_data(u16 index) {{ return ms_lookup_string(g_palette_name_offsets, ms_palette_entry_count, index); }}
"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@dataclass
class ExportResult:
    summary: Dict[str, Any]           # counts: tiles, sprites, steps, blob size, ...
    issues: List[Issue]               # Check Project's errors and warnings, the colours and the tiles
    files: List[Path]                 # what was written


def export_project(
    project: Project,
    output_dir: Path,
    mapping_selector: str = "all",
    project_path: Optional[Path] = None,
    copy_assets: bool = False,
) -> ExportResult:
    """Bake a project into an SGDK project folder (its res/, inc/ and src/ get the data files) and report what the
    game will see: Check Project's errors and warnings, merged colours and how the tiles fit in video memory."""
    output_dir = Path(output_dir).resolve()
    mappings = resolve_mappings(project, mapping_selector)
    issues = [issue for issue in project_check.check_project(project) if issue.level != project_check.INFO]

    bake = MegaDriveBakeContext(project=project, mappings=mappings, output_dir=output_dir)
    bake.bake()
    files = [output_dir / BLOB_FILE, output_dir / HEADER_FILE, output_dir / DATA_C_FILE,
             output_dir / RESOURCE_FILE]
    bake._emit_blob(files[0])
    bake._emit_header(files[1])
    bake._emit_data_c(files[2])
    bake._emit_resources(files[3])

    if copy_assets:
        copy_sources(project, project_path, output_dir)

    console = project_check.console_issue(project, consoles.MEGA_DRIVE)
    if console is not None:
        issues.append(console)
    tiles = len(bake.tile_data) // 32
    issues.append(project_check.megadrive_tile_issue(tiles))
    lines = project_check.megadrive_palette_issue(len(bake.palette_entries))
    if lines is not None:
        issues.append(lines)
    summary = {
        "mapping_count": len(mappings),
        "mappings": ", ".join(bake.mapping_names),
        "variants": len(bake.variants),
        "hardware_sprite_pieces": len(bake.pieces),
        "tiles": tiles,
        "palettes": len(bake.palette_ids),
        "palette_swaps": len(bake.swaps),
        "palette_entries": len(bake.palette_entries),
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
    parser = export_arguments("Mega Drive", REPO_ROOT / "examples" / "pop" / "PoP_WW.json",
                              REPO_ROOT / "examples" / "megadrive" / "megadrive_demo")
    args = parser.parse_args()
    project_json_path = Path(args.project_json).resolve()
    project = Project.from_json(str(project_json_path))
    result = export_project(project, Path(args.output_dir), args.mapping, project_json_path, args.copy_assets)
    return print_result(result, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
