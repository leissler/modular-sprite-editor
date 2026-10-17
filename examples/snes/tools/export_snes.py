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

Streamed exports (``--mode parts_streamed`` or ``frames_streamed``, docs/EXPORT_MODES.md) keep only what is on screen in
video memory, in slots of whole rows of a sprite table (16 tiles). The cartridge holds the squares in strips: each
render frame's new squares, in the order frames first use them, side by side in rows of at most 16 tiles, row after
row, so the squares a frame uses mostly lie together. Every render frame names a load list: its strips' pieces placed
in a slot (aligned to their size, as the PPU finds a square's tiles 16 to a row), as DMA runs (a row of a piece each,
neighbours merged), identical lists once; its sprites count their tiles from the slot. ``frames_streamed`` stores whole
frames (ConsoleBake.whole_frames) instead of parts.
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
    FIXED_ENTRY, ConsoleBake, RenderFrameSpan, StoredPart, copy_sources, export_arguments, print_result,
    resolve_mappings,
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
STREAMED_DATA_VERSION = 3  # load lists, sprites counted from a slot (a resident export stays version 2)
DEFAULT_SETUP = "snes_8_16"
MODES = ("parts", "parts_streamed", "frames_streamed")
# What a load list costs to upload in vertical blank, in bytes of DMA (8 master cycles each, about 170 a scanline): its
# bytes, and the 65816's time in ms_send_uploads (modsprite_draw.asm) per run (setting up a DMA), per group of runs from
# one chunk and per list, measured in Mesen 2 (533, 611 and 939 master cycles; tools/check_snes_rom.py --timings).
RUN_COST = 67
GROUP_COST = 76
LIST_COST = 117
UPLOAD_BUDGET = project_check.SNES_UPLOAD_CAPACITY  # the default per vertical blank (ms_set_upload_budget)
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
# Streamed exports: a render frame's load list (8: its entries (offset, chunk), group count, tiles, upload cost) and the
# entries, in groups of one chunk (2: the chunk, entry count), each a DMA run (6: VRAM word offset in the slot, offset
# in the chunk, bytes).
LOAD_LIST = struct.Struct("<HBBHH")
LOAD_GROUP = struct.Struct("<BB")
LOAD_ENTRY = struct.Struct("<HHH")
STREAM_RECORDS = {"MS_LoadList": LOAD_LIST, "MS_LoadGroup": LOAD_GROUP, "MS_LoadEntry": LOAD_ENTRY}

FLAG_LARGE, FLAG_HFLIP, FLAG_VFLIP = 0x01, 0x40, 0x80
SIZE_BIT = 0x02  # a large sprite's bit in the sprite table's high table
NO_LIST = 0xFFFF  # a render frame that shows nothing loads nothing


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

    def __init__(self, project: Project, mappings: List[Optional[ModuleMapping]], setup_key: str = "",
                 mode: str = "parts") -> None:
        super().__init__(project, mappings)
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}: one of {', '.join(MODES)}")
        self.mode = mode
        self.streamed = mode != "parts"
        self.whole_frames = mode == "frames_streamed"
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
        self.block_pieces: Dict[Tuple[int, bool, bool], List[Tuple[int, int, int, int, int]]] = {}
        self.piece_lists: Dict[Tuple[int, bool, bool], List[Tuple[int, int, int, int, int]]] = {}
        self.chunk_data: List[bytearray] = []
        self.tables_used = 0
        self.tile_end = 0  # the first tile number after every tile in use: the rest of the tables is free
        # Streamed exports (_stream): the strips of squares in the cartridge, in pieces of at most a chunk, each
        # render frame's load list and its squares' tiles in the slot, the lists, and the slots' sizes in tiles.
        self.strips: List[Tuple[int, List[int]]] = []  # (square side in tiles, its squares' blocks)
        self.store_pieces: List[bytes] = []
        self.render_frame_loads: List[int] = []
        self.render_frame_slot_tiles: List[Dict[int, int]] = []  # block -> its first tile in the slot
        self.load_lists: List[Tuple[Tuple[Tuple[int, int, int, int], ...], int, int]] = []  # (runs, tiles, cost)
        self.slot_tiles = 0
        self.scene_slot_tiles = 0
        self.slot_align = 0  # tiles: a slot starts on a row a large square's tiles may start on
        self.streamed_layout = False

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

    def _stored_part(self, stored: int) -> StoredPart:
        """ConsoleBake's measuring hook: a variant's padded size and its squares; a square's tiles are its block."""
        meta = self.variants[stored]
        sprites = []
        for bx, by, large, block, _entry in meta.blocks:
            size = self.large if large else self.small
            sprites.append((bx, by, size, size, block, (size // TILE) ** 2))
        return StoredPart(meta.pad_w, meta.pad_h, tuple(sprites))

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

    def _block_pieces(self, variant: int, hflip: bool, vflip: bool) -> List[Tuple[int, int, int, int, int]]:
        """A variant's hardware sprites for one flip combination (x, y, block, flags, palette entry): a flip mirrors
        the whole padded part, so the pieces swap places inside it and the sprites flip."""
        key = (variant, bool(hflip), bool(vflip))
        found = self.block_pieces.get(key)
        if found is not None:
            return found
        meta = self.variants[variant]
        pieces = []
        for bx, by, large, block, entry in meta.blocks:
            size = self.large if large else self.small
            x = meta.pad_w - bx - size if hflip else bx
            y = meta.pad_h - by - size if vflip else by
            flags = (FLAG_LARGE if large else 0) | (FLAG_HFLIP if hflip else 0) | (FLAG_VFLIP if vflip else 0)
            pieces.append((x, y, block, flags, entry))
        self.block_pieces[key] = pieces
        return pieces

    def _piece_list(self, variant: int, hflip: bool, vflip: bool) -> List[Tuple[int, int, int, int, int]]:
        """The pieces with their tile numbers in the sprite tables (x, y, tile, flags, palette entry): every tile in
        video memory."""
        key = (variant, bool(hflip), bool(vflip))
        found = self.piece_lists.get(key)
        if found is None:
            found = self.piece_lists[key] = [(x, y, self.block_tiles[block], flags, entry)
                                             for x, y, block, flags, entry in self._block_pieces(variant, hflip, vflip)]
        return found

    def render_frame_extent(self, span: RenderFrameSpan) -> Tuple[int, int, int, int, int]:
        """(sprite count, min x, min y, max x, max y) of a render frame's pieces, relative to where it is drawn."""
        count, min_x, min_y, max_x, max_y = 0, 0x7FFF, 0x7FFF, -0x8000, -0x8000
        for variant, px, py, hflip, vflip in self.parts[span.first_part:span.first_part + span.part_count]:
            for x, y, _block, flags, _entry in self._block_pieces(variant, bool(hflip), bool(vflip)):
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

    # ---------------------------------------------------------------- streamed exports
    def _stream_order(self) -> List[int]:
        """Render frames in the order a game first shows them: frames, animation steps, scene samples, modules on their
        own, then the rest."""
        order: List[int] = []
        seen = set()
        for renders in (self.frame_render_frames, [step[0] for step in self.anim_steps], self.scene_samples,
                        self.module_render_frames, range(len(self.render_frames))):
            for render in renders:
                if render not in seen:
                    seen.add(render)
                    order.append(render)
        return order

    def _render_blocks(self, render: int) -> List[int]:
        """The squares a render frame shows, each once, in the order its parts first use them."""
        blocks: Dict[int, None] = {}
        for variant, *_placement in self.render_frame_parts(render):
            for _bx, _by, _large, block, _entry in self.variants[variant].blocks:
                blocks.setdefault(block, None)
        return list(blocks)

    def _stream(self) -> None:
        """Streamed exports: the squares in strips (each render frame's new ones, in the order frames first use them, at
        most 16 tiles a row), the cartridge's pieces of them, and every render frame's load list and slot tiles."""
        self.streamed_layout = True
        self.slot_align = (self.large // TILE) * GRID
        strip_of: Dict[int, Tuple[int, int]] = {}  # block -> (strip, position in it)
        for render in self._stream_order():
            new: Dict[int, List[int]] = {}
            for block in self._render_blocks(render):
                if block not in strip_of:
                    new.setdefault(self.blocks[block][0], []).append(block)
            for side in sorted(new, reverse=True):
                per = GRID // side
                for start in range(0, len(new[side]), per):
                    blocks = new[side][start:start + per]
                    for position, block in enumerate(blocks):
                        strip_of[block] = (len(self.strips), position)
                    self.strips.append((side, blocks))
        # The cartridge: each strip a row of tiles after the other, its squares side by side, in pieces of a chunk at
        # most (a DMA run reads one bank).
        strip_at: List[Tuple[int, int]] = []  # (chunk, offset)
        piece = bytearray()
        for side, blocks in self.strips:
            data = b"".join(_snes_tile(self.blocks[block][1], side * TILE, tx * TILE, ty * TILE)
                            for ty in range(side) for block in blocks for tx in range(side))
            if len(piece) + len(data) > CHUNK_SIZE:
                self.store_pieces.append(bytes(piece))
                piece = bytearray()
            strip_at.append((len(self.store_pieces), len(piece)))
            piece.extend(data)
        if piece:
            self.store_pieces.append(bytes(piece))
        lists: Dict[Tuple[Tuple[int, int, int, int], ...], int] = {}
        players = set(self.module_render_frames) | set(self.frame_render_frames) | {step[0] for step in self.anim_steps}
        scenes = set(self.scene_samples)
        player_rows = scene_rows = 0
        for render in range(len(self.render_frames)):
            runs, in_slot, rows = self._slot_layout(self._render_blocks(render), strip_of, strip_at)
            self.render_frame_slot_tiles.append(in_slot)
            if not runs:
                self.render_frame_loads.append(NO_LIST)
                continue
            if runs not in lists:
                lists[runs] = len(self.load_lists)
                tiles = sum(run[3] for run in runs)
                cost = tiles * 32 + len(runs) * RUN_COST + len({run[0] for run in runs}) * GROUP_COST + LIST_COST
                self.load_lists.append((runs, tiles, min(0xFFFF, cost)))
            self.render_frame_loads.append(lists[runs])
            if render in players:
                player_rows = max(player_rows, rows)
            if render in scenes:
                scene_rows = max(scene_rows, rows)
        if len(self.load_lists) >= NO_LIST:
            raise ExportError("More than 65534 different load lists")
        align = self.large // TILE
        self.slot_tiles = -(-player_rows // align) * align * GRID
        self.scene_slot_tiles = -(-scene_rows // align) * align * GRID
        self.tile_end = max(self.slot_tiles, self.scene_slot_tiles)  # the default slot's end
        if self.tile_end > SPRITE_TILES:
            raise ExportError(f"A frame or scene sample needs a slot of {max(self.slot_tiles, self.scene_slot_tiles)} "
                              f"tiles, more than the SNES's {SPRITE_TILES} sprite tiles")

    def stream_slots(self) -> Tuple[int, int]:
        """ConsoleBake's measuring hook: the slots in tiles, whole rows of the sprite tables (_stream works them out
        when the bake has not)."""
        if not self.streamed_layout:
            self._stream()
        return self.slot_tiles, self.scene_slot_tiles

    def stream_upload_cost(self, tile_bytes: int = 32) -> int:
        """ConsoleBake's measuring hook: the most a load list costs in vertical blank (its bytes and its runs, as
        ms_send_uploads spends them)."""
        if not self.streamed_layout:
            self._stream()
        return max((cost for _runs, _tiles, cost in self.load_lists), default=0)

    def _slot_layout(self, blocks: Sequence[int], strip_of: Dict[int, Tuple[int, int]], strip_at: List[Tuple[int, int]]
                     ) -> Tuple[Tuple[Tuple[int, int, int, int], ...], Dict[int, int], int]:
        """Where a render frame's squares go in a slot: the neighbouring squares of a strip it shows (a segment) stay
        side by side, segments of the largest squares first, longest first, each at the first free place aligned to its
        squares (rows of 16 tiles). Returns the DMA runs (chunk, offset, slot tile, tiles: a row of a segment each, runs
        that follow each other in the chunk and in the slot merged), each square's first tile in the slot and the rows
        used."""
        by_strip: Dict[int, List[int]] = {}
        for block in blocks:
            strip, position = strip_of[block]
            by_strip.setdefault(strip, []).append(position)
        segments: List[Tuple[int, int, int]] = []  # (strip, first position, squares)
        for strip in sorted(by_strip):
            positions = sorted(by_strip[strip])
            first = last = positions[0]
            for position in positions[1:]:
                if position != last + 1:
                    segments.append((strip, first, last - first + 1))
                    first = position
                last = position
            segments.append((strip, first, last - first + 1))
        taken = set()
        rows = 0
        runs: List[Tuple[int, int, int, int]] = []
        in_slot: Dict[int, int] = {}
        for strip, first, count in sorted(segments, key=lambda s: (-self.strips[s[0]][0], -s[2], s[0], s[1])):
            side, strip_blocks = self.strips[strip]
            width = side * count
            row = 0
            while True:
                col = next((c for c in range(0, GRID - width + 1, side)
                            if not any((row + r, c + k) in taken for r in range(side) for k in range(width))), None)
                if col is not None:
                    break
                row += side
            taken.update((row + r, col + k) for r in range(side) for k in range(width))
            rows = max(rows, row + side)
            chunk, offset = strip_at[strip]
            strip_width = side * len(strip_blocks)
            for r in range(side):
                runs.append((chunk, offset + (r * strip_width + first * side) * 32, (row + r) * GRID + col, width))
            for k in range(count):
                in_slot[strip_blocks[first + k]] = row * GRID + col + k * side
        runs.sort()
        merged: List[List[int]] = []
        for chunk, source, tile, tiles in runs:
            last = merged[-1] if merged else None
            if last and last[0] == chunk and last[1] + last[3] * 32 == source and last[2] + last[3] == tile:
                last[3] += tiles
            else:
                merged.append([chunk, source, tile, tiles])
        return tuple(tuple(run) for run in merged), in_slot, rows

    # ---------------------------------------------------------------- the data
    def bake(self) -> None:
        super().bake()
        if self.streamed:
            self._stream()
        else:
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
        # The sprite tiles first, a table each (DMA reads a bank at a time); a streamed export's strips in their pieces.
        tables = [bytes(self.tables[t * TABLE_TILES * 32:(t + 1) * TABLE_TILES * 32]) for t in range(self.tables_used)]
        where["tiles"] = [chunks.place(data, "a sprite table", share=False) for data in tables]
        for index, piece in enumerate(self.store_pieces):
            assert chunks.place(piece, "the sprite tiles", share=False) == (index, 0), "the strips start the chunks"

        def table(name: str, data: bytes) -> None:
            where[name] = chunks.place(data or b"\0\0", f"the {name.replace('_', ' ')} table", share=False)

        # Render frames: their lists, then the records in pages.
        records: List[bytes] = []
        for index, span in enumerate(self.render_frames):
            sprite_bytes, run_count = self.sprite_runs(span, self.render_frame_slot_tiles[index] if self.streamed
                                                       else None)
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
        if self.streamed:
            list_records = []
            for runs, tiles, cost in self.load_lists:
                data = bytearray()
                groups = start = 0
                while start < len(runs):
                    end = start
                    while end < len(runs) and runs[end][0] == runs[start][0] and end - start < 255:
                        end += 1
                    data += LOAD_GROUP.pack(runs[start][0], end - start)
                    data += b"".join(LOAD_ENTRY.pack(tile * 16, source, count * 32)
                                     for _chunk, source, tile, count in runs[start:end])
                    groups += 1
                    start = end
                if groups > 255:
                    raise ExportError("A frame or scene sample's tiles come from more than 255 places")
                at = chunks.place(bytes(data), "a load list")
                list_records.append(LOAD_LIST.pack(at[1], at[0], groups, tiles, cost))
            table("load_lists", b"".join(list_records))
            table("render_frame_loads", u16s(self.render_frame_loads))
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

    def sprite_runs(self, span: RenderFrameSpan, slot_tiles: Optional[Dict[int, int]] = None) -> Tuple[bytes, int]:
        """A render frame's sprites as the runtime writes them into the sprite table: in OAM order (the last part
        first, it is on top), in runs of one palette entry (a run's header, then its sprites); returns (the bytes, the
        run count). ``slot_tiles``: a streamed export's squares' first tiles in the slot (block -> tile)."""
        sprites = []
        for variant, x, y, hflip, vflip in reversed(self.parts[span.first_part:span.first_part + span.part_count]):
            if slot_tiles is None:
                pieces = self._piece_list(variant, bool(hflip), bool(vflip))
            else:
                pieces = [(px, py, slot_tiles[block], flags, entry)
                          for px, py, block, flags, entry in self._block_pieces(variant, bool(hflip), bool(vflip))]
            for px, py, tile, flags, entry in pieces:
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
            ("MS_DATA_VERSION", STREAMED_DATA_VERSION if self.streamed else DATA_VERSION),
            ("MS_CHUNK_COUNT", len(self.chunk_data)),
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
        if self.streamed:
            lines += [
                "",
                "/* A streamed export (modsprite.h): video memory holds slots of MS_SLOT_TILES tiles a player and",
                "   MS_SCENE_SLOT_TILES a scene, each starting on a multiple of MS_SLOT_ALIGN tiles; MS_TILE_COUNT tiles "
                "in the cartridge. */",
                "#define MS_STREAMED 1",
                f"#define MS_SLOT_TILES {self.slot_tiles}",
                f"#define MS_SCENE_SLOT_TILES {self.scene_slot_tiles}",
                f"#define MS_SLOT_ALIGN {self.slot_align}",
                f"#define MS_LOAD_LIST_COUNT {len(self.load_lists)}",
                f"#define MS_UPLOAD_BUDGET {UPLOAD_BUDGET}",
                "#define MS_NO_LIST 0xFFFF",
            ]
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
        ]
        if self.streamed:
            lines += [
                "/* A render frame's load list (ms_render_frame_loads, MS_NO_LIST when it shows nothing): group_count "
                "groups of DMA runs,",
                "   each an MS_LoadGroup (the chunk its runs read) and its count MS_LoadEntrys; what they upload and "
                "what that costs in",
                "   vertical blank, in bytes of DMA (ms_set_upload_budget). An entry copies bytes from its chunk to "
                "the slot's VRAM",
                "   word address + vram. */",
                "typedef struct { u16 entries_offset; u8 entries_chunk; u8 group_count; u16 tile_count; u16 cost; } "
                "MS_LoadList;",
                "typedef struct { u8 chunk; u8 count; } MS_LoadGroup;",
                "typedef struct { u16 vram; u16 source; u16 bytes; } MS_LoadEntry;",
            ]
        lines += [
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
        ]
        if self.streamed:
            lines += ["extern const MS_LoadList *ms_load_lists;", "extern const u16 *ms_render_frame_loads;"]
        lines += [
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
        if self.streamed:
            tables += [("ms_load_lists", "const MS_LoadList *", "load_lists"),
                       ("ms_render_frame_loads", "const u16 *", "render_frame_loads")]
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
                   project_path: Optional[Path] = None, copy_assets: bool = False, mode: str = "parts") -> ExportResult:
    """Bake a project into a PVSnesLib project folder and report what the game will see (Check Project's errors and
    warnings, how the tiles and palettes fit). ``mode``: one of MODES (docs/EXPORT_MODES.md)."""
    mappings = resolve_mappings(project, mapping_selector)
    issues = [issue for issue in project_check.check_project(project) if issue.level != project_check.INFO]
    bake = SNESBakeContext(project, mappings, setup_key, mode)
    bake.bake()
    files = bake.write(Path(project_dir))
    if copy_assets:
        copy_sources(project, project_path, Path(project_dir))
    console = project_check.console_issue(project, consoles.SNES,
                                          f", with {bake.setup.name.split(', ', 1)[-1]}")
    if console:
        issues.append(console)
    tiles = bake.tiles_used()
    if bake.streamed:
        issues.extend(project_check.snes_stream_issues(bake.slot_tiles, bake.scene_slot_tiles,
                                                       bake.stream_upload_cost()))
    else:
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
    if bake.streamed:
        summary.update(mode=mode, slot_tiles=bake.slot_tiles, scene_slot_tiles=bake.scene_slot_tiles,
                       load_lists=len(bake.load_lists))
    order = project_check.LEVEL_ORDER
    return ExportResult(summary, sorted(issues, key=lambda issue: order[issue.level]), files)


def bake_context(project: Project, mappings: List[Optional[ModuleMapping]], setup_key: str = "") -> SNESBakeContext:
    """The bake for a pair of sprite sizes as export_modes measures it (ConsoleBake.bake: the sprite tables are not
    filled, so whole frames over 512 tiles can be measured too; nothing is written)."""
    return SNESBakeContext(project, mappings, setup_key)


def report_line(summary: Dict[str, Any]) -> str:
    """The editor's export report: the sprite sizes, the tiles they need and the data in the ROM."""
    if "slot_tiles" in summary:
        return (f"{summary.get('setup', '')}. Streamed: {summary.get('tiles', 0)} tiles in the cartridge, a slot of "
                f"{summary['slot_tiles']} sprite tiles a player and {summary.get('scene_slot_tiles', 0)} a scene, "
                f"{summary.get('data_bytes', 0) / 1024:.0f} KB of data in {summary.get('chunks', 0)} ROM banks "
                f"(a {summary.get('rom_kb', 0)} KB ROM)")
    return (f"{summary.get('setup', '')}: {summary.get('tiles', 0)} of {SPRITE_TILES} sprite tiles, "
            f"{summary.get('data_bytes', 0) / 1024:.0f} KB of data in {summary.get('chunks', 0)} ROM banks "
            f"(a {summary.get('rom_kb', 0)} KB ROM)")


def main() -> int:
    parser = export_arguments("SNES", REPO_ROOT / "examples" / "pop" / "PoP_WW.json",
                              REPO_ROOT / "examples" / "snes" / "snes_demo", MODES)
    parser.add_argument("--setup", default="", help="The two sprite sizes (snes_8_16 ... snes_32_64); default: the "
                        "project's when it is made for the SNES, else snes_8_16.")
    args = parser.parse_args()
    project_json_path = Path(args.project_json).resolve()
    project = Project.from_json(str(project_json_path))
    try:
        result = export_project(project, Path(args.output_dir), args.mapping, args.setup, project_json_path,
                                args.copy_assets, args.mode)
    except ExportError as error:
        print(f"error: {error}")
        return 1
    return print_result(result, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
