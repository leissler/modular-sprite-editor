#!/usr/bin/env python3
"""Bake a Modular Sprite Editor project into a PVSnesLib (SNES) project: the data in binary chunks, one per ROM bank,
the assembler file that places them, the C header and data file the runtime (snes_demo/src/modsprite.c) reads, and
the ROM size for the Makefile.

The console-independent bake is console_bake.ConsoleBake. SNESBakeContext stores each part's picture the way the SNES
draws it: cut into the setup's two square sprite sizes (sprite_cut.cut, which the editor's budget overlay counts), as
4 bpp planar tiles, identical blocks once, packed into the two sprite tables of 256 tiles (every SNES sprite is a square
of 8, 16, 32 or 64 pixels, so blocks aligned to their size pack without gaps), with a piece list for every flip a part
uses. Everything stays in video memory, as on the Mega Drive: the runtime only writes the sprite table.

The data is little-endian, every 16-bit field on an even offset, in chunks of at most 32 KB (a LoROM bank). A table
the runtime indexes (steps, animations, scenes, ...) sits whole in one chunk; render frames come in pages of 1024; the
lists a render frame points to (its sprites, hitboxes, points) are far references (offset, chunk) and never cross a
chunk. A render frame's sprites are ready for the sprite table: in OAM order (the last part first: it is on top),
relative to where the frame is drawn, in runs of one palette entry, so the runtime's loop (modsprite_draw.asm) only
adds the position and the palette.
"""

from __future__ import annotations

import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

if getattr(sys, "frozen", False):
    REPO_ROOT = Path(sys.executable).resolve().parent
else:
    REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import consoles  # noqa: E402
import hardware_budget  # noqa: E402
import palettes  # noqa: E402
import project_check  # noqa: E402
import sprite_cut  # noqa: E402
from console_bake import (  # noqa: E402
    FIXED_ENTRY, ConsoleBake, RenderFrameSpan, copy_sources, export_arguments, print_result, resolve_mappings,
)
from models import ModuleMapping, Project  # noqa: E402
from project_check import Issue  # noqa: E402

TILE = 8
CHUNK_SIZE = 0x8000  # a LoROM bank
TABLE_TILES = 256  # a sprite name table: 16 x 16 tiles
GRID = 16
SPRITE_TILES = 2 * TABLE_TILES
SPRITE_PALETTES = 8  # CGRAM 128-255
RF_PAGE_SHIFT = 10  # render frames per page: 1024
DATA_VERSION = 2
DEFAULT_SETUP = "snes_8_16"
OBSEL_SIZES = {  # the OBSEL size select (bits 5-7) of each pair of sprite sizes
    ((8, 8), (16, 16)): 0, ((8, 8), (32, 32)): 1, ((8, 8), (64, 64)): 2,
    ((16, 16), (32, 32)): 3, ((16, 16), (64, 64)): 4, ((32, 32), (64, 64)): 5,
}

# What the exporter writes into a PVSnesLib project (paths relative to it).
CHUNK_DIR = Path("res")
CHUNK_NAME = "ms_chunk_{:02d}.bin"
ASM_FILE = Path("modsprite_chunks.asm")
HEADER_FILE = Path("inc") / "modsprite_data.h"
DATA_C_FILE = Path("src") / "modsprite_data.c"
ROM_MAKE_FILE = Path("modsprite_rom.mk")

# Records (little-endian, every 16-bit field on an even offset: the same layout packed or aligned). The ones the runtime
# indexes are padded to a power of two: 816-tcc multiplies by any other size with a library call.
# 22: sprites (offset, chunk, run count), boxes, points (offset, chunk, count), sprite count, part count, bounds
RENDER_FRAME = struct.Struct("<HBBHBBHBBBBhhhh")
RUN = struct.Struct("<BB")  # 2: palette entry, sprite count; the sprites follow
SPRITE = struct.Struct("<hhBBBB")  # 8: x, y, tile, attribute (V flip 0x80, H flip 0x40, tile bit 8 0x01), size bit, 0
HITBOX = struct.Struct("<BBHhhhh4x")  # 16: type, 0, role, x, y, w, h
POINT = struct.Struct("<BBHhh")  # 8: type, 0, role, x, y
STEP = struct.Struct("<HHHBB")  # 8: render frame, ticks, first event, event count, 0
ANIMATION = struct.Struct("<HHHBBHHH2x")  # 16: first step, steps, fps, playback, 0, loop start, next, repeat count
EVENT = struct.Struct("<Hh")  # 4: type, value
SCENE = struct.Struct("<HHHHBB6x")  # 16: first sample, samples, fps, duration ticks, loop, 0
PALETTE_ENTRY = struct.Struct("<BBHBB2x")  # 8: palette, swap, first cycle, cycle count, 0
CYCLE = struct.Struct("<BBHBB2x")  # 8: first slot, count, frames, reverse, 0
RECORDS = {"MS_RenderFrame": RENDER_FRAME, "MS_Run": RUN, "MS_Sprite": SPRITE, "MS_Hitbox": HITBOX,
           "MS_Point": POINT, "MS_AnimStep": STEP, "MS_Animation": ANIMATION, "MS_StepEvent": EVENT,
           "MS_Scene": SCENE, "MS_PaletteEntry": PALETTE_ENTRY, "MS_ColourCycle": CYCLE}

FLAG_LARGE, FLAG_HFLIP, FLAG_VFLIP = 0x01, 0x40, 0x80
SIZE_BIT = 0x02  # a large sprite's bit in the sprite table's high table


class ExportError(RuntimeError):
    """The project does not fit the SNES export (a table larger than a bank, too many parts in a frame, ...)."""


@dataclass
class Variant:
    pad_w: int  # the part padded to whole tiles: a hardware flip mirrors it in this box
    pad_h: int
    blocks: List[Tuple[int, int, bool, int, int]]  # (x, y, large, block, palette entry)


class Chunks:
    """Binary chunks of at most one bank; a piece of data goes whole into the first chunk with room."""

    def __init__(self, size: int = CHUNK_SIZE) -> None:
        self.size = size
        self.data: List[bytearray] = [bytearray()]
        self.placed: Dict[bytes, Tuple[int, int]] = {}  # identical data is placed once

    def place(self, data: bytes, what: str, share: bool = True) -> Tuple[int, int]:
        """(chunk, offset) of ``data``, aligned to 2 bytes."""
        if len(data) > self.size:
            raise ExportError(f"{what} needs {len(data)} bytes, more than a ROM bank ({self.size}) holds")
        if share and data in self.placed:
            return self.placed[data]
        for index, chunk in enumerate(self.data):
            start = len(chunk) + (len(chunk) & 1)
            if start + len(data) <= self.size:
                chunk.extend(b"\0" * (start - len(chunk)))
                chunk.extend(data)
                if share:
                    self.placed[data] = (index, start)
                return index, start
        self.data.append(bytearray(data))
        if share:
            self.placed[data] = (len(self.data) - 1, 0)
        return len(self.data) - 1, 0


class SNESBakeContext(ConsoleBake):
    """The SNES half of the export: ConsoleBake's parts as square hardware sprites of the setup's two sizes, their
    tiles in the two sprite tables, the palettes as CGRAM words, all of it in bank-sized chunks."""

    def __init__(self, project: Project, mappings: List[Optional[ModuleMapping]], setup_key: str = "") -> None:
        super().__init__(project, mappings)
        console, setup = consoles.target(project.console, project.console_setup)
        if console is not consoles.SNES or setup_key:
            setup = consoles.SNES.setup(setup_key or DEFAULT_SETUP)
        self.setup = setup
        self.profile = hardware_budget.profile_by_key(setup.key)
        assert self.profile is not None, setup.key
        self.small, self.large = setup.sizes[0][0], setup.sizes[1][0]
        self.variant_lookup: Dict[Tuple[int, int, str, str, int], int] = {}
        self.variants: List[Variant] = []
        self.blocks: List[Tuple[int, bytes]] = []  # (size in tiles, the block's palette slot per pixel)
        self.block_lookup: Dict[Tuple[int, bytes], int] = {}
        self.block_tiles: List[int] = []  # the tile number (9 bits) each block starts at, after _allocate
        self.tables = bytearray()  # the sprite tiles, 2 x 256 x 32 bytes at most
        self.piece_lists: Dict[Tuple[int, bool, bool], List[Tuple[int, int, int, int, int]]] = {}
        self.chunk_data: List[bytearray] = []
        self.tables_used = 0
        self.tile_end = 0  # the first tile number after every tile in use: the rest of the tables is free

    # ---------------------------------------------------------------- parts as hardware sprites
    def _store_part(self, image: Image.Image, palette: str, entry: int) -> int:
        """ConsoleBake's hook: a part image cut into the setup's squares, each block's pixels as palette slots (the
        same pixels in another block share its tiles)."""
        rgba = image.convert("RGBA")
        key = (rgba.width, rgba.height, hashlib.sha1(rgba.tobytes()).hexdigest(), palette, entry)
        found = self.variant_lookup.get(key)
        if found is not None:
            return found
        hardware = self.profile.hardware
        cut_w, cut_h = sprite_cut.pad(rgba.width, hardware), sprite_cut.pad(rgba.height, hardware, 1)
        padded = Image.new("RGBA", (cut_w, cut_h), (0, 0, 0, 0))
        padded.alpha_composite(rgba, (0, 0))
        slots = self._to_indexed(padded, palette).tobytes()
        blocks = []
        for bx, by, bw, bh in sprite_cut.cut(rgba, hardware):
            pixels = b"".join(slots[(by + row) * cut_w + bx:(by + row) * cut_w + bx + bw] for row in range(bh))
            block_key = (bw // TILE, pixels)
            block = self.block_lookup.get(block_key)
            if block is None:
                block = self.block_lookup[block_key] = len(self.blocks)
                self.blocks.append(block_key)
            blocks.append((bx, by, bw == self.large, block, entry))
        index = len(self.variants)
        self.variant_lookup[key] = index
        self.variants.append(Variant(max(TILE, -(-rgba.width // TILE) * TILE), max(TILE, -(-rgba.height // TILE) * TILE),
                                     blocks))
        return index

    def _allocate(self) -> None:
        """Tile numbers for the blocks: largest first, each at the first free place aligned to its size in table 0,
        then table 1 (squares of powers of two leave no gaps this way). Raises when they need more than 512 tiles."""
        free = [[[True] * GRID for _ in range(GRID)] for _ in range(2)]
        self.block_tiles = [0] * len(self.blocks)
        self.tables = bytearray(SPRITE_TILES * 32)
        need = sum(size * size for size, _pixels in self.blocks)
        if need > SPRITE_TILES:
            raise ExportError(f"The sprites need {need} tiles, more than the SNES's {SPRITE_TILES} sprite tiles "
                              "(two tables of 256, 16 KB of video memory)")
        highest = -1
        for block in sorted(range(len(self.blocks)), key=lambda b: (-self.blocks[b][0], b)):
            size, pixels = self.blocks[block]
            spot = next(((t, row, col) for t in range(2) for row in range(0, GRID, size) for col in range(0, GRID, size)
                         if all(free[t][row + r][col + c] for r in range(size) for c in range(size))), None)
            if spot is None:  # cannot happen within the capacity: aligned power-of-two squares
                raise ExportError("The sprite tiles could not be packed into the two sprite tables")
            t, row, col = spot
            for r in range(size):
                for c in range(size):
                    free[t][row + r][col + c] = False
            number = t * TABLE_TILES + row * GRID + col
            self.block_tiles[block] = number
            span = size * TILE
            for ty in range(size):
                for tx in range(size):
                    tile = number + ty * GRID + tx
                    highest = max(highest, tile)
                    self.tables[tile * 32:tile * 32 + 32] = _snes_tile(pixels, span, tx * TILE, ty * TILE)
        self.tables_used = 2 if highest >= TABLE_TILES else 1
        self.tile_end = highest + 1

    def _piece_list(self, variant: int, hflip: bool, vflip: bool) -> List[Tuple[int, int, int, int, int]]:
        """A variant's hardware sprites for one flip combination (x, y, tile, flags, palette entry): a flip mirrors
        the whole padded part, so the pieces swap places inside it and the sprites flip."""
        key = (variant, bool(hflip), bool(vflip))
        found = self.piece_lists.get(key)
        if found is not None:
            return found
        meta = self.variants[variant]
        pieces = []
        for bx, by, large, block, entry in meta.blocks:
            size = self.large if large else self.small
            x = meta.pad_w - bx - size if hflip else bx
            y = meta.pad_h - by - size if vflip else by
            flags = (FLAG_LARGE if large else 0) | (FLAG_HFLIP if hflip else 0) | (FLAG_VFLIP if vflip else 0)
            pieces.append((x, y, self.block_tiles[block], flags, entry))
        self.piece_lists[key] = pieces
        return pieces

    def render_frame_extent(self, span: RenderFrameSpan) -> Tuple[int, int, int, int, int]:
        """(sprite count, min x, min y, max x, max y) of a render frame's pieces, relative to where it is drawn."""
        count, min_x, min_y, max_x, max_y = 0, 0x7FFF, 0x7FFF, -0x8000, -0x8000
        for variant, px, py, hflip, vflip in self.parts[span.first_part:span.first_part + span.part_count]:
            for x, y, _tile, flags, _entry in self._piece_list(variant, bool(hflip), bool(vflip)):
                size = self.large if flags & FLAG_LARGE else self.small
                min_x, min_y = min(min_x, px + x), min(min_y, py + y)
                max_x, max_y = max(max_x, px + x + size), max(max_y, py + y + size)
                count += 1
        return (count, min_x, min_y, max_x, max_y) if count else (0, 0, 0, 0, 0)

    # ---------------------------------------------------------------- palettes
    def _entry_cycles(self, entry: palettes.Entry) -> List[Any]:
        visible = consoles.SNES.palette.visible
        return [c for c in entry.cycles if c.count >= 2 and 1 <= c.first and c.first + c.count - 1 <= visible]

    def palette_words(self) -> List[int]:
        """16 CGRAM words per palette entry: slot 0 (transparent), then its colours, free slots black."""
        visible = consoles.SNES.palette.visible
        words: List[int] = []
        for entry in self.palette_entries:
            words.append(0)
            words.extend(palettes.snes_word(entry.colours[slot] if slot < len(entry.colours) else (0, 0, 0))
                         for slot in range(visible))
        return words

    # ---------------------------------------------------------------- the data
    def bake(self) -> None:
        super().bake()
        self._allocate()
        for variant, _x, _y, hflip, vflip in self.parts:
            self._piece_list(variant, bool(hflip), bool(vflip))
        assert RENDER_FRAME.size == 22, "ms_render_frame and modsprite_draw.asm multiply by 22 in shifts"
        assert RF_PAGE_SHIFT == 10, "modsprite_draw.asm finds a render frame's page as (index >> 8) & 0xFC"
        for span in self.render_frames:
            if span.part_count > 255 or span.box_count > 255 or span.point_count > 255:
                raise ExportError("A frame or scene sample has more than 255 parts, hitboxes or points")
            if self.render_frame_extent(span)[0] > 255:
                raise ExportError("A frame or scene sample needs more than 255 hardware sprites")

    def build_chunks(self) -> Dict[str, Any]:
        """Lay the data out in chunks; returns where each table is (for the header)."""
        chunks = Chunks()
        where: Dict[str, Any] = {}
        # The sprite tiles first, a table each (DMA reads a bank at a time).
        tables = [bytes(self.tables[t * TABLE_TILES * 32:(t + 1) * TABLE_TILES * 32]) for t in range(self.tables_used)]
        where["tiles"] = [chunks.place(data, "a sprite table", share=False) for data in tables]

        def table(name: str, data: bytes) -> None:
            where[name] = chunks.place(data or b"\0\0", f"the {name.replace('_', ' ')} table", share=False)

        # Render frames: their lists, then the records in pages.
        records: List[bytes] = []
        for span in self.render_frames:
            sprite_bytes, run_count = self.sprite_runs(span)
            sprites_at = chunks.place(sprite_bytes, "a frame's sprites") if sprite_bytes else (0, 0)
            boxes = self.boxes[span.first_box:span.first_box + span.box_count]
            box_bytes = b"".join(HITBOX.pack(t & 0xFF, 0, r & 0xFFFF, x, y, w, h) for t, r, x, y, w, h in boxes)
            boxes_at = chunks.place(box_bytes, "a frame's hitboxes") if box_bytes else (0, 0)
            points = self.points[span.first_point:span.first_point + span.point_count]
            point_bytes = b"".join(POINT.pack(t & 0xFF, 0, r & 0xFFFF, x, y) for t, r, x, y in points)
            points_at = chunks.place(point_bytes, "a frame's points") if point_bytes else (0, 0)
            count, min_x, min_y, max_x, max_y = self.render_frame_extent(span)
            records.append(RENDER_FRAME.pack(sprites_at[1], sprites_at[0], run_count, boxes_at[1], boxes_at[0],
                                             span.box_count, points_at[1], points_at[0], span.point_count, count,
                                             span.part_count, min_x, min_y, max_x, max_y))
        page = 1 << RF_PAGE_SHIFT
        where["render_frame_pages"] = [chunks.place(b"".join(records[i:i + page]), "a page of render frames",
                                                    share=False) for i in range(0, max(1, len(records)), page)]

        u16s = lambda values: b"".join(struct.pack("<H", int(v) & 0xFFFF) for v in values)  # noqa: E731
        table("module_render_frames", u16s(self.module_render_frames))
        table("frame_render_frames", u16s(self.frame_render_frames))
        table("anim_steps", b"".join(STEP.pack(f, t, e, n, 0) for f, t, e, n in self.anim_steps))
        table("animations", b"".join(ANIMATION.pack(r.first_step, r.step_count, r.fps, r.playback, 0, r.loop_start,
                                                    r.next_animation, r.loop_count) for r in self.anim_records))
        table("step_events", b"".join(EVENT.pack(t, max(-32768, min(32767, v))) for t, v in self.step_events))
        table("scene_samples", u16s(self.scene_samples))
        table("scenes", b"".join(SCENE.pack(r.first_sample, r.sample_count, r.fps, min(0xFFFF, r.duration_ticks), r.loop, 0)
                                 for r in self.scene_records))
        table("palette", u16s(self.palette_words()))
        swap_ids = [s.id for s in self.swaps]
        entry_records, cycle_records, first = [], [], 0
        for entry in self.palette_entries:
            cycles = self._entry_cycles(entry)
            swap = 0 if entry.swap_id is None else 1 + swap_ids.index(entry.swap_id)
            entry_records.append(PALETTE_ENTRY.pack(self.palette_ids.index(entry.palette_id), swap, first, len(cycles), 0))
            cycle_records += [CYCLE.pack(int(c.first), int(c.count), max(1, min(0xFFFF, int(c.frames))),
                                         1 if c.reverse else 0, 0) for c in cycles]
            first += len(cycles)
        table("palette_entries", b"".join(entry_records))
        table("colour_cycles", b"".join(cycle_records))
        table("swap_entries", bytes(self.entry_of.get((pid, swap.id), self.entry_of[(pid, None)])
                                    for swap in self.swaps for pid in self.palette_ids))
        where["cycle_count"] = len(cycle_records)
        # Names and ids: one string table with a list of offsets each.
        lists = self.name_lists()
        strings = bytearray()
        offsets: Dict[str, List[int]] = {}
        for name, values in lists:
            offsets[name] = []
            for value in values:
                offsets[name].append(len(strings))
                strings.extend(str(value or "").encode("utf-8") + b"\0")
        names = bytearray()
        list_at: Dict[str, int] = {}
        for name, _values in lists:
            list_at[name] = len(names)
            names.extend(u16s(offsets[name]))
        string_base = len(names) + (len(names) & 1)
        names.extend(b"\0" * (string_base - len(names)))
        names.extend(strings)
        where["names"] = chunks.place(bytes(names), "the names", share=False)
        where["name_lists"] = {name: (list_at[name], string_base) for name, _values in lists}
        self.chunk_data = chunks.data
        return where

    def sprite_runs(self, span: RenderFrameSpan) -> Tuple[bytes, int]:
        """A render frame's sprites as the runtime writes them into the sprite table: in OAM order (the last part
        first, it is on top), in runs of one palette entry (a run's header, then its sprites); returns (the bytes, the
        run count)."""
        sprites = []
        for variant, x, y, hflip, vflip in reversed(self.parts[span.first_part:span.first_part + span.part_count]):
            for px, py, tile, flags, entry in self._piece_list(variant, bool(hflip), bool(vflip)):
                attribute = (flags & (FLAG_HFLIP | FLAG_VFLIP)) | ((tile >> 8) & 1)
                sprites.append((entry, SPRITE.pack(int(x) + px, int(y) + py, tile & 0xFF, attribute,
                                                   SIZE_BIT if flags & FLAG_LARGE else 0, 0)))
        data = bytearray()
        runs = start = 0
        while start < len(sprites):
            end = start
            while end < len(sprites) and sprites[end][0] == sprites[start][0]:
                end += 1
            data += RUN.pack(sprites[start][0], end - start)
            data += b"".join(packed for _entry, packed in sprites[start:end])
            runs += 1
            start = end
        return bytes(data), runs

    def name_lists(self) -> List[Tuple[str, Sequence[str]]]:
        p = self.project
        return [
            ("mapping_ids", self.mapping_ids), ("mapping_names", self.mapping_names),
            ("module_ids", [m.id for m in p.modules]), ("module_names", [m.name for m in p.modules]),
            ("frame_ids", [f.id for f in p.frames]), ("frame_names", [f.name for f in p.frames]),
            ("animation_ids", [a.id for a in p.animations]), ("animation_names", [a.name for a in p.animations]),
            ("scene_ids", [s.id for s in p.timeline_scenes]), ("scene_names", [s.name for s in p.timeline_scenes]),
            ("event_names", [t.name for t in p.event_types]),
            ("hitbox_type_names", [t.name for t in p.collision_types]),
            ("point_type_names", [t.name for t in p.point_types]), ("role_names", self.role_names),
            ("swap_ids", [""] + [s.id for s in self.swaps]), ("swap_names", ["<none>"] + [s.name for s in self.swaps]),
            ("palette_entry_names", [e.name for e in self.palette_entries]),
        ]

    # ---------------------------------------------------------------- files
    def write(self, project_dir: Path) -> List[Path]:
        where = self.build_chunks()
        project_dir = Path(project_dir)
        (project_dir / CHUNK_DIR).mkdir(parents=True, exist_ok=True)
        (project_dir / HEADER_FILE).parent.mkdir(parents=True, exist_ok=True)
        (project_dir / DATA_C_FILE).parent.mkdir(parents=True, exist_ok=True)
        files = []
        names = [CHUNK_NAME.format(i) for i in range(len(self.chunk_data))]
        for name, data in zip(names, self.chunk_data):
            path = project_dir / CHUNK_DIR / name
            path.write_bytes(bytes(data))
            files.append(path)
        for stale in (project_dir / CHUNK_DIR).glob("ms_chunk_*.bin"):  # an earlier export's extra chunks
            if stale.name not in names:
                stale.unlink()
        asm = ['; Generated by the Modular Sprite Editor (examples/snes/tools/export_snes.py): the data chunks, one '
               'section each.', '.include "hdr.asm"', '']
        for index, name in enumerate(names):
            asm += [f'.section ".ms_chunk_{index:02d}" superfree', f"ms_chunk_{index:02d}:",
                    f'.incbin "{(CHUNK_DIR / name).as_posix()}"', ".ends", ""]
        files.append(_write(project_dir / ASM_FILE, "\n".join(asm)))
        files.append(_write(project_dir / HEADER_FILE, self.header_text(where)))
        files.append(_write(project_dir / DATA_C_FILE, self.data_c_text(where)))
        files.append(_write(project_dir / ROM_MAKE_FILE, self.rom_make_text()))
        return files

    def rom_make_text(self) -> str:
        banks = 8
        while banks < len(self.chunk_data) + 4:  # the code and the library take the rest (about 2-3 banks)
            banks *= 2
        size_code = (banks * 32).bit_length() - 1  # the header's ROM size: 2^n KB
        return (f"# Generated by the Modular Sprite Editor: the ROM size the data needs ({len(self.chunk_data)} chunks)\n"
                f"export ROMBANKS := {banks}\nexport ROMSIZE := {size_code:02X}\n")

    def header_text(self, where: Dict[str, Any]) -> str:
        p = self.project
        defines = [
            ("MS_DATA_VERSION", DATA_VERSION), ("MS_CHUNK_COUNT", len(self.chunk_data)),
            ("MS_MODULE_COUNT", len(p.modules)), ("MS_FRAME_COUNT", len(p.frames)),
            ("MS_ANIMATION_COUNT", len(p.animations)), ("MS_SCENE_COUNT", len(p.timeline_scenes)),
            ("MS_MAPPING_COUNT", len(self.mappings)), ("MS_RENDER_FRAME_COUNT", len(self.render_frames)),
            ("MS_ANIM_STEP_COUNT", len(self.anim_steps)), ("MS_ANIMATION_RECORD_COUNT", len(self.anim_records)),
            ("MS_SCENE_RECORD_COUNT", len(self.scene_records)), ("MS_SCENE_SAMPLE_COUNT", len(self.scene_samples)),
            ("MS_STEP_EVENT_COUNT", len(self.step_events)), ("MS_EVENT_TYPE_COUNT", len(p.event_types)),
            ("MS_HITBOX_TYPE_COUNT", len(p.collision_types)), ("MS_POINT_TYPE_COUNT", len(p.point_types)),
            ("MS_ROLE_COUNT", len(self.role_names)), ("MS_TILE_COUNT", self.tiles_used()),
            ("MS_TILE_END", self.tile_end), ("MS_TILE_TABLES", self.tables_used), ("MS_PALETTE_ENTRY_COUNT", len(self.palette_entries)),
            ("MS_BASE_PALETTE_COUNT", len(self.palette_ids)), ("MS_PALETTE_SWAP_COUNT", len(self.swaps) + 1),
            ("MS_COLOUR_CYCLE_COUNT", where["cycle_count"]), ("MS_RF_PAGE_SHIFT", RF_PAGE_SHIFT),
            ("MS_RF_PAGE_COUNT", len(where["render_frame_pages"])),
            ("MS_SMALL_SIZE", self.small), ("MS_LARGE_SIZE", self.large),
            ("MS_OBJ_SIZE", f"({OBSEL_SIZES[tuple(self.setup.sizes)]} << 5)"),
            ("MS_FIXED_ENTRY", f"0x{FIXED_ENTRY:02X}"),
        ]
        lines = [
            "/* Generated by the Modular Sprite Editor (examples/snes/tools/export_snes.py). Do not edit. */",
            "#ifndef MODSPRITE_DATA_H", "#define MODSPRITE_DATA_H", "", "#include <snes.h>", "",
            f"/* {self.setup.name}: OBSEL's size select is MS_OBJ_SIZE. */",
        ]
        lines += [f"#define {name} {value}" for name, value in defines]
        lines += ["", "#define MS_NO_ANIMATION 0xFFFF", "#define MS_NO_ROLE 0xFFFF", "#define MS_UNKNOWN_TYPE 0xFF", ""]
        for title, symbols in (("Event types", self.event_symbols), ("Hitbox types", self.box_type_symbols),
                               ("Point types", self.point_type_symbols), ("Roles", self.role_symbols)):
            lines.append(f"/* {title}, numbered as the runtime reports them. */")
            lines += [f"#define {symbol} {index}" for index, symbol in enumerate(symbols)]
            lines.append("")
        lines += [
            "/* Records as the exporter writes them: little-endian, every 16-bit field on an even offset. A render "
            "frame's sprites",
            "   are run_count runs: an MS_Run, then its count MS_Sprites, in OAM order (the first in front); min / max: "
            "the box",
            "   around them, relative to where the frame is drawn. */",
            "typedef struct { u16 sprites_offset; u8 sprites_chunk; u8 run_count; u16 boxes_offset; u8 boxes_chunk; "
            "u8 box_count;",
            "                 u16 points_offset; u8 points_chunk; u8 point_count; u8 sprite_count; u8 part_count;",
            "                 s16 min_x; s16 min_y; s16 max_x; s16 max_y; } MS_RenderFrame;",
            "/* palette: the palette entry of the run's sprites, MS_FIXED_ENTRY set when a scene object's own swap fixes "
            "it */",
            "typedef struct { u8 palette; u8 count; } MS_Run;",
            "/* attribute: the OAM attribute byte's flips (V 0x80, H 0x40) and the tile's bit 8 (0x01); size: 2 for a "
            "large sprite",
            "   (its bit in the high table), else 0 */",
            "typedef struct { s16 x; s16 y; u8 tile; u8 attribute; u8 size; u8 reserved; } MS_Sprite;",
            "typedef struct { u8 type; u8 reserved; u16 role; s16 x; s16 y; s16 w; s16 h; u16 reserved2[2]; } MS_Hitbox;",
            "typedef struct { u8 type; u8 reserved; u16 role; s16 x; s16 y; } MS_Point;",
            "typedef struct { u16 frame_index; u16 duration_ticks; u16 first_event; u8 event_count; u8 reserved; } "
            "MS_AnimStep;",
            "typedef struct { u16 first_step; u16 step_count; u16 fps; u8 playback; u8 reserved; u16 loop_start; "
            "u16 next_animation; u16 loop_count; u16 reserved2; } MS_Animation;",
            "typedef struct { u16 type; s16 value; } MS_StepEvent;",
            "typedef struct { u16 first_sample; u16 sample_count; u16 fps; u16 duration_ticks; u8 loop; u8 reserved; "
            "u16 reserved2[3]; } MS_Scene;",
            "typedef struct { u8 palette; u8 swap; u16 first_cycle; u8 cycle_count; u8 reserved; u16 reserved2; } "
            "MS_PaletteEntry;",
            "typedef struct { u8 first; u8 count; u16 frames; u8 reverse; u8 reserved; u16 reserved2; } MS_ColourCycle;",
            "",
            "extern const u8 *const ms_chunks[];",
            "#define MS_FAR(chunk, offset) (ms_chunks[(chunk)] + (offset))",
            "",
            "extern const u8 *ms_tile_tables[2];",
            "extern const u8 *ms_rf_pages[];  /* render frames in pages of 1 << MS_RF_PAGE_SHIFT */",
            "extern const u16 *ms_module_render_frames;",
            "extern const u16 *ms_frame_render_frames;",
            "extern const MS_AnimStep *ms_anim_steps;",
            "extern const MS_Animation *ms_animations;",
            "extern const MS_StepEvent *ms_step_events;",
            "extern const u16 *ms_scene_samples;",
            "extern const MS_Scene *ms_scenes;",
            "extern const u16 *ms_palette;",
            "extern const MS_PaletteEntry *ms_palette_entries;",
            "extern const MS_ColourCycle *ms_colour_cycles;",
            "extern const u8 *ms_swap_entries;",
            "",
            "void ms_data_init(void);",
            "const MS_RenderFrame *ms_render_frame(u16 index);",
        ]
        lines += [f"const char *ms_{name}(u16 index);" for name, _values in self.name_lists()]
        lines += ["", "#endif", ""]
        return "\n".join(lines)

    def data_c_text(self, where: Dict[str, Any]) -> str:
        count = len(self.chunk_data)
        lines = [
            "/* Generated by the Modular Sprite Editor (examples/snes/tools/export_snes.py). Do not edit. */",
            '#include "modsprite_data.h"', "",
        ]
        lines += [f"extern const unsigned char ms_chunk_{i:02d}[];" for i in range(count)]
        lines += ["", "const u8 *const ms_chunks[] = {"]
        lines += [f"    ms_chunk_{i:02d}," for i in range(count)]
        lines += ["};", "", "const u8 *ms_tile_tables[2];", "const u8 *ms_rf_pages[MS_RF_PAGE_COUNT];",
                  "static const u8 *g_names;"]
        tables = [("ms_module_render_frames", "const u16 *", "module_render_frames"),
                  ("ms_frame_render_frames", "const u16 *", "frame_render_frames"),
                  ("ms_anim_steps", "const MS_AnimStep *", "anim_steps"), ("ms_animations", "const MS_Animation *", "animations"),
                  ("ms_step_events", "const MS_StepEvent *", "step_events"), ("ms_scene_samples", "const u16 *", "scene_samples"),
                  ("ms_scenes", "const MS_Scene *", "scenes"), ("ms_palette", "const u16 *", "palette"),
                  ("ms_palette_entries", "const MS_PaletteEntry *", "palette_entries"),
                  ("ms_colour_cycles", "const MS_ColourCycle *", "colour_cycles"),
                  ("ms_swap_entries", "const u8 *", "swap_entries")]
        lines += [f"{ctype}{name};" for name, ctype, _key in tables]
        lines += ["", "void ms_data_init(void)", "{"]
        for index, (chunk, offset) in enumerate(where["tiles"]):
            lines.append(f"    ms_tile_tables[{index}] = MS_FAR({chunk}, {offset});")
        for index, (chunk, offset) in enumerate(where["render_frame_pages"]):
            lines.append(f"    ms_rf_pages[{index}] = MS_FAR({chunk}, {offset});")
        for name, ctype, key in tables:
            chunk, offset = where[key]
            lines.append(f"    {name} = ({ctype.strip()})MS_FAR({chunk}, {offset});")
        chunk, offset = where["names"]
        lines += [f"    g_names = MS_FAR({chunk}, {offset});", "}", ""]
        lines += [
            "const MS_RenderFrame *ms_render_frame(u16 index)",
            "{",
            "    u16 i = index & ((1 << MS_RF_PAGE_SHIFT) - 1);",
            "",
            "    /* i * 22 (sizeof(MS_RenderFrame)) in shifts: a multiplication is a library call on the 65816 */",
            "    return (const MS_RenderFrame *)(ms_rf_pages[index >> MS_RF_PAGE_SHIFT] + (i << 4) + (i << 2) + (i << 1));",
            "}",
            "",
            "static const char *ms_name(u16 list, u16 strings, u16 count, u16 index)",
            "{",
            "    if (index >= count)",
            '        return "";',
            "    return (const char *)(g_names + strings + ((const u16 *)(g_names + list))[index]);",
            "}",
            "",
        ]
        for name, values in self.name_lists():
            list_offset, strings = where["name_lists"][name]
            lines.append(f"const char *ms_{name}(u16 index) {{ return ms_name({list_offset}, {strings}, {len(values)}, index); }}")
        lines.append("")
        return "\n".join(lines)

    def tiles_used(self) -> int:
        return sum(size * size for size, _pixels in self.blocks)


def _snes_tile(pixels: bytes, stride: int, x0: int, y0: int) -> bytes:
    """An 8x8 tile in the SNES's 4 bpp planar format: rows of bit planes 0 and 1, then rows of planes 2 and 3."""
    out = bytearray(32)
    for row in range(TILE):
        base = (y0 + row) * stride + x0
        planes = [0, 0, 0, 0]
        for col in range(TILE):
            value = pixels[base + col] & 0x0F
            for plane in range(4):
                if value & (1 << plane):
                    planes[plane] |= 0x80 >> col
        out[2 * row], out[2 * row + 1] = planes[0], planes[1]
        out[16 + 2 * row], out[17 + 2 * row] = planes[2], planes[3]
    return bytes(out)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@dataclass
class ExportResult:
    summary: Dict[str, Any]
    issues: List[Issue]
    files: List[Path]


def export_project(project: Project, project_dir: Path, mapping_selector: str = "all", setup_key: str = "",
                   project_path: Optional[Path] = None, copy_assets: bool = False) -> ExportResult:
    """Bake a project into a PVSnesLib project folder and report what the game will see (Check Project's errors and
    warnings, how the tiles and palettes fit)."""
    mappings = resolve_mappings(project, mapping_selector)
    issues = [issue for issue in project_check.check_project(project) if issue.level != project_check.INFO]
    bake = SNESBakeContext(project, mappings, setup_key)
    bake.bake()
    files = bake.write(Path(project_dir))
    if copy_assets:
        copy_sources(project, project_path, Path(project_dir))
    console = project_check.console_issue(project, consoles.SNES,
                                          f", with {bake.setup.name.split(', ', 1)[-1]}")
    if console:
        issues.append(console)
    tiles = bake.tiles_used()
    issues.append(project_check.snes_tile_issue(tiles, SPRITE_TILES))
    palette_entries = project_check.snes_palette_issue(len(bake.palette_entries), SPRITE_PALETTES)
    if palette_entries:
        issues.append(palette_entries)
    summary = {
        "setup": bake.setup.name, "mapping_count": len(mappings), "mappings": ", ".join(bake.mapping_names),
        "animations": len(project.animations), "frames": len(project.frames), "scenes": len(project.timeline_scenes),
        "tiles": tiles, "tile_tables": bake.tables_used, "blocks": len(bake.blocks), "variants": len(bake.variants),
        "palette_entries": len(bake.palette_entries), "render_frames": len(bake.render_frames),
        "parts": len(bake.parts), "anim_steps": len(bake.anim_steps), "scene_samples": len(bake.scene_samples),
        "chunks": len(bake.chunk_data), "data_bytes": sum(len(c) for c in bake.chunk_data),
        "rom_kb": int(bake.rom_make_text().split("ROMBANKS := ")[1].split()[0]) * 32,
    }
    order = project_check.LEVEL_ORDER
    return ExportResult(summary, sorted(issues, key=lambda issue: order[issue.level]), files)


def report_line(summary: Dict[str, Any]) -> str:
    """The editor's export report: the sprite sizes, the tiles they need and the data in the ROM."""
    return (f"{summary.get('setup', '')}: {summary.get('tiles', 0)} of {SPRITE_TILES} sprite tiles, "
            f"{summary.get('data_bytes', 0) / 1024:.0f} KB of data in {summary.get('chunks', 0)} ROM banks "
            f"(a {summary.get('rom_kb', 0)} KB ROM)")


def main() -> int:
    parser = export_arguments("SNES", REPO_ROOT / "examples" / "pop" / "PoP_WW.json",
                              REPO_ROOT / "examples" / "snes" / "snes_demo")
    parser.add_argument("--setup", default="", help="The two sprite sizes (snes_8_16 ... snes_32_64); default: the "
                        "project's when it is made for the SNES, else snes_8_16.")
    args = parser.parse_args()
    project_json_path = Path(args.project_json).resolve()
    project = Project.from_json(str(project_json_path))
    try:
        result = export_project(project, Path(args.output_dir), args.mapping, args.setup, project_json_path,
                                args.copy_assets)
    except ExportError as error:
        print(f"error: {error}")
        return 1
    return print_result(result, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
