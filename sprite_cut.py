"""How console hardware sprites cover a part (wx-free, Pillow only): one implementation for the Mega Drive export, the
budget overlay and Auto Modularize, so what one of them counts the others count too.

A part's opaque pixels are covered with hardware sprites of the sizes the console has (``Hardware``):

- ``export_cut``: the Mega Drive as the SGDK export cuts a part: the fewest hardware sprites, and with that the fewest
  tiles. Rectangles of 8 to 32 px in steps of 8 may sit at any pixel of the part (``tight_cut``, inside the part
  padded to whole tiles); the part's own 32 px grid (``grid_cut``, empty blocks skipped) is kept when the tight cut
  is not strictly better, so no part needs more sprites or tiles than it did with the grid alone.
- ``cut``: what the budget overlay counts for each console: the export cut on the Mega Drive; cells of one size on
  the NES and the Game Boy, small and large squares on the SNES, the cheapest cover with its shapes on the GBA, all on
  the part's own grid (models of what a game would do: those consoles have no exporter yet).
- ``tight_cut``: the cheapest cover of a mask with a console's sizes, ``tiles + weight * sprites``: dynamic
  programming over bands of rows (their heights), then runs in each band (their widths); rows and columns are both
  tried. Auto Modularize cuts its parts this way.

Masks are ints: a mode "1" image's bytes, big-endian, rows padded to whole bytes (column 0 is a row's highest bit).
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

TILE = 8
BLOCK = 32  # the Mega Drive's largest hardware sprite side
EXPORT_WEIGHT = 1024.0  # the export's tight cut: a sprite outweighs any tiles one part can save (sprites first)
SHAPE_CELL = 64  # the GBA cover works on 64x64 px cells of a part (its largest sprite)
SPRITE_WEIGHT = 8  # tiles a GBA sprite counts as in the budget's shape cover: 1024 sprite tiles for 128 sprites

Size = Tuple[int, int]
Rect = Tuple[int, int, int, int]  # x, y, w, h in px

# How a console's hardware sprites cover a part (see the module docstring).
GRID = "grid"  # any width and height in tiles up to the largest (Mega Drive)
SQUARES = "squares"  # two square sizes (SNES)
CELLS = "cells"  # one size (NES, Game Boy)
SHAPES = "shapes"  # a few shapes (GBA)


@dataclass(frozen=True)
class Hardware:
    """A console's hardware sprites as a cut sees them: how it covers a part, and the sizes it may use (GRID: the
    largest, every multiple of 8 up to it is allowed)."""
    cut: str = GRID
    shapes: Tuple[Size, ...] = ((BLOCK, BLOCK),)

    @property
    def sizes(self) -> Tuple[Size, ...]:
        """Every (width, height) a hardware sprite can have."""
        if self.cut == GRID:
            largest = max(max(w, h) for w, h in self.shapes)
            steps = range(TILE, largest + 1, TILE)
            return tuple((w, h) for h in steps for w in steps)
        return tuple(self.shapes)

    @property
    def largest(self) -> int:
        return max(max(w, h) for w, h in self.shapes)


MEGA_DRIVE = Hardware()


# ---------------------------------------------------------------------------- masks
def bits_of(mask: Image.Image) -> int:
    return int.from_bytes(mask.tobytes(), "big")


def mask_of(bits: int, w: int, h: int) -> Image.Image:
    stride = (w + 7) // 8
    return Image.frombytes("1", (w, h), bits.to_bytes(stride * h, "big"))


def opaque_mask(image: Image.Image) -> Image.Image:
    return image.convert("RGBA").getchannel("A").point(lambda v: 255 if v else 0, "1")


def rows_of(bits: int, w: int, h: int) -> Tuple[List[int], int]:
    """The mask's rows as ints (column x at bit width - 1 - x) and that bit width."""
    width = ((w + 7) // 8) * 8
    full = (1 << width) - 1
    return [(bits >> ((h - 1 - y) * width)) & full for y in range(h)], width


def tiles_of(rects: Sequence[Rect]) -> int:
    return sum((w // TILE) * (h // TILE) for _x, _y, w, h in rects)


# ---------------------------------------------------------------------------- the tight cut
@lru_cache(maxsize=1 << 16)
def _cover_1d(occupied: int, width: int, band: int, weight: float, widths: Tuple[int, ...]) -> Tuple[float, Tuple[Tuple[int, int], ...]]:
    """Cheapest cover of a band's occupied columns with runs of the allowed widths: (cost, ((x, w), ...)). Covering
    fewer columns never costs more, so for each width only its longest reach is a candidate."""
    xs = []
    m = occupied
    while m:
        top = m.bit_length() - 1
        xs.append(width - 1 - top)
        m ^= 1 << top
    n = len(xs)
    if not n:
        return 0.0, ()
    rows = band // TILE
    best = [0.0] * (n + 1)
    choice: List[Tuple[int, int]] = [(0, 0)] * n  # (last column index covered, run width)
    for i in range(n - 1, -1, -1):
        best_cost, best_choice = float("inf"), (i, widths[-1])
        for w in widths:
            j = bisect_left(xs, xs[i] + w, i) - 1  # the farthest occupied column a run of w px reaches
            need = next(v for v in widths if v >= xs[j] - xs[i] + 1)  # what that reach really needs
            cost = (need // TILE) * rows + weight + best[j + 1]
            if cost < best_cost:
                best_cost, best_choice = cost, (j, need)
        best[i], choice[i] = best_cost, best_choice
    runs = []
    i = 0
    while i < n:
        j, w = choice[i]
        runs.append((xs[i], w))
        i = j + 1
    return best[0], tuple(runs)


def _cut_rows(rows: List[int], width: int, weight: float, sizes: Sequence[Size]) -> List[Rect]:
    h = len(rows)
    heights = sorted({sh for _sw, sh in sizes})
    widths_of = {band: tuple(sorted({sw for sw, sh in sizes if sh == band})) for band in heights}

    @lru_cache(maxsize=None)
    def best(y: int) -> Tuple[float, Tuple[Rect, ...]]:
        while y < h and not rows[y]:
            y += 1
        if y >= h:
            return 0.0, ()
        out: Tuple[float, Tuple[Rect, ...]] = (float("inf"), ())
        occupied = 0
        reached = y
        for band in heights:
            for r in rows[reached:y + band]:
                occupied |= r
            reached = max(reached, y + band)
            cost, runs = _cover_1d(occupied, width, band, weight, widths_of[band])
            rest = best(y + band)
            if cost + rest[0] < out[0]:
                out = (cost + rest[0], tuple((x, y, w, band) for x, w in runs) + rest[1])
        return out

    rects = []
    # Each rectangle shrinks to the rows its pixels use, in a height its width allows.
    for x, y, w, band in best(0)[1]:
        cols = ((1 << w) - 1) << (width - x - w) if width - x - w >= 0 else ((1 << (width - x)) - 1)
        used = [yy for yy in range(y, min(h, y + band)) if rows[yy] & cols]
        top, bottom = used[0], used[-1]
        tall = next((sh for sw, sh in sorted(sizes, key=lambda s: s[1]) if sw == w and sh >= bottom - top + 1), band)
        rects.append((x, top, w, tall))
    return rects


def tight_cut(bits: int, w: int, h: int, weight: float, sizes: Optional[Sequence[Size]] = None) -> Tuple[float, List[Rect]]:
    """Rectangles of the allowed sizes (default: the Mega Drive's, 8 to 32 px in steps of 8) that cover the mask's
    pixels for the least tiles + weight * count, in bands of rows or of columns, whichever is cheaper: (cost, rects
    in the mask's coordinates; they may reach past its right and bottom edges)."""
    if not bits:
        return 0.0, []
    sizes = tuple(sizes or MEGA_DRIVE.sizes)
    rows, width = rows_of(bits, w, h)
    by_rows = _cut_rows(rows, width, weight, sizes)
    flipped = mask_of(bits, w, h).transpose(Image.Transpose.TRANSPOSE)
    cols, cwidth = rows_of(bits_of(flipped), h, w)
    by_cols = [(y, x, bh, bw) for x, y, bw, bh in _cut_rows(cols, cwidth, weight, tuple((sh, sw) for sw, sh in sizes))]

    def cost(rects: List[Rect]) -> float:
        return tiles_of(rects) + weight * len(rects)

    a, b = cost(by_rows), cost(by_cols)
    return (a, by_rows) if a <= b else (b, by_cols)


# ---------------------------------------------------------------------------- what the consoles cut
def pad(size: int, hardware: Hardware = MEGA_DRIVE, axis: int = 0) -> int:
    """A width (``axis`` 0) or height (1) in whole tiles (the export's padding); in whole sprites for a console whose
    sprites have one size, or two square ones (padded to the large one)."""
    grid = TILE
    if hardware.cut == SQUARES:
        grid = hardware.shapes[-1][axis]
    elif hardware.cut == CELLS:
        grid = hardware.shapes[0][axis]
    return max(grid, ((int(size) + grid - 1) // grid) * grid)


def grid_cut(image: Image.Image, step: int = BLOCK) -> List[Rect]:
    """The part's own grid of ``step`` px blocks (padded to whole tiles), each block that holds a pixel."""
    alpha = image.convert("RGBA").getchannel("A")
    width, height = image.size
    pad_w, pad_h = pad(width), pad(height)
    blocks = []
    for by in range(0, pad_h, step):
        for bx in range(0, pad_w, step):
            bw, bh = min(step, pad_w - bx), min(step, pad_h - by)
            if alpha.crop((bx, by, min(bx + bw, width), min(by + bh, height))).getbbox():
                blocks.append((bx, by, bw, bh))
    return blocks


def export_cut(image: Image.Image) -> List[Rect]:
    """The Mega Drive export's hardware sprites for a part (x, y, w, h in the part padded to whole tiles): the tight
    cut, moved inside the padded part, when it needs fewer sprites, or as many and fewer tiles; else the grid."""
    width, height = image.size
    grid = grid_cut(image)
    pad_w, pad_h = pad(width), pad(height)
    if width <= BLOCK and height <= BLOCK:
        # One sprite holds it all: the tight cut is one rectangle over its pixels' box.
        box = image.convert("RGBA").getchannel("A").getbbox()
        if box is None:
            return grid
        w, h = pad(box[2] - box[0]), pad(box[3] - box[1])
        tight = [(max(0, min(box[0], pad_w - w)), max(0, min(box[1], pad_h - h)), w, h)]
        return tight if (len(tight), tiles_of(tight)) < (len(grid), tiles_of(grid)) else grid
    bits = bits_of(opaque_mask(image))
    if not bits:
        return grid
    _cost, tight = tight_cut(bits, width, height, EXPORT_WEIGHT)
    # A rectangle that reaches past the padded part moves back in: it still covers its pixels (its width is the
    # smallest step that holds them, and they lie inside the part).
    tight = [(max(0, min(x, pad_w - w)), max(0, min(y, pad_h - h)), w, h) for x, y, w, h in tight]
    if (len(tight), tiles_of(tight)) < (len(grid), tiles_of(grid)):
        return tight
    return grid


def cover_with_shapes(occupied: Sequence[Sequence[bool]], shapes: Sequence[Size], weight: int = SPRITE_WEIGHT,
                      open_edges: Tuple[bool, bool] = (True, True)) -> List[Tuple[int, int, int, int]]:
    """Sprites (x, y, w, h in tiles) of the given shapes (w, h in tiles) that cover every occupied tile of the grid
    (rows of booleans), costing least: the tiles they hold plus ``weight`` per sprite, then fewer sprites.

    Guillotine cuts: every piece is trimmed to its occupied tiles and either takes the smallest shape that holds it or
    is cut in two along a tile line. A shape bigger than its piece sits at one of the piece's corners, never over
    another piece's tiles: inside the grid, or sticking out past its right or bottom edge where that is open
    (``open_edges``: the image ends there, no other cell's sprites lie beyond)."""
    Box = Tuple[int, int, int, int]
    Cover = Tuple[int, int, Tuple[Box, ...]]  # (cost, sprites, the sprites)
    height = len(occupied)
    width = max((len(row) for row in occupied), default=0)
    rows = [sum(1 << x for x, used in enumerate(row) if used) for row in occupied]
    memo: Dict[Box, Cover] = {}
    by_area = sorted(shapes, key=lambda s: (s[0] * s[1], s[1], s[0]))

    def span(x0: int, x1: int) -> int:
        return ((1 << x1) - 1) ^ ((1 << max(0, x0)) - 1)

    def trimmed(x0: int, y0: int, x1: int, y1: int) -> Optional[Box]:
        mask = span(x0, x1)
        used = [y for y in range(y0, y1) if rows[y] & mask]
        if not used:
            return None
        either = 0
        for y in used:
            either |= rows[y] & mask
        return (either & -either).bit_length() - 1, used[0], either.bit_length(), used[-1] + 1

    def anchors(low: int, high: int, size: int, limit: int, open_edge: bool) -> List[int]:
        inside = [a for a in dict.fromkeys((low, high - size)) if 0 <= a and a + size <= limit]
        return inside + ([low] if open_edge and low + size > limit else [])

    def covers_others(box: Box, x: int, y: int, w: int, h: int) -> bool:
        x0, y0, x1, y1 = box
        for row in range(max(0, y), min(height, y + h)):
            others = rows[row] & span(x, x + w)
            if y0 <= row < y1:
                others &= ~span(x0, x1)
            if others:
                return True
        return False

    def one_sprite(box: Box) -> Optional[Box]:
        x0, y0, x1, y1 = box
        for w, h in by_area:
            if w < x1 - x0 or h < y1 - y0:
                continue
            for y in anchors(y0, y1, h, height, open_edges[1]):
                for x in anchors(x0, x1, w, width, open_edges[0]):
                    if not covers_others(box, x, y, w, h):
                        return x, y, w, h
        return None

    def best(x0: int, y0: int, x1: int, y1: int) -> Cover:
        box = trimmed(x0, y0, x1, y1)
        if box is None:
            return 0, 0, ()
        found = memo.get(box)
        if found is not None:
            return found
        x0, y0, x1, y1 = box
        options: List[Cover] = []
        sprite = one_sprite(box)
        if sprite is not None:
            options.append((sprite[2] * sprite[3] + weight, 1, (sprite,)))
        halves = [(best(x0, y0, x, y1), best(x, y0, x1, y1)) for x in range(x0 + 1, x1)]
        halves += [(best(x0, y0, x1, y), best(x0, y, x1, y1)) for y in range(y0 + 1, y1)]
        options += [(a[0] + b[0], a[1] + b[1], a[2] + b[2]) for a, b in halves]
        found = memo[box] = min(options, key=lambda option: option[:2])  # the first of equals: one sprite, then cuts
        return found

    return list(best(0, 0, width, height)[2])


def cut(image: Image.Image, hardware: Hardware = MEGA_DRIVE) -> List[Rect]:
    """The hardware sprites (x, y, w, h in px, in the part padded as ``pad`` pads it) that show a part image on a
    console: the export cut on the Mega Drive, the part's own grid of cells, squares or shapes elsewhere."""
    if hardware.cut == GRID:
        return export_cut(image)
    alpha: Any = image.convert("RGBA").getchannel("A")
    width, height = image.size

    def filled(x: int, y: int, w: int, h: int) -> bool:
        if x >= width or y >= height:
            return False
        return bool(alpha.crop((x, y, min(x + w, width), min(y + h, height))).getbbox())

    pad_w, pad_h = pad(width, hardware), pad(height, hardware, 1)
    blocks: List[Rect] = []
    if hardware.cut == SQUARES:
        # A large square per cell, or small ones where the pixels fill at most half of the cell.
        small, large = hardware.shapes[0][0], hardware.shapes[-1][0]
        for by in range(0, pad_h, large):
            for bx in range(0, pad_w, large):
                squares = [(bx + sx, by + sy) for sy in range(0, large, small) for sx in range(0, large, small)]
                used = [(x, y) for x, y in squares if filled(x, y, small, small)]
                if not used:
                    continue
                if 2 * len(used) <= len(squares):
                    blocks += [(x, y, small, small) for x, y in used]
                else:
                    blocks.append((bx, by, large, large))
    elif hardware.cut == CELLS:
        cell_w, cell_h = hardware.shapes[0]
        blocks = [(bx, by, cell_w, cell_h) for by in range(0, pad_h, cell_h) for bx in range(0, pad_w, cell_w)
                  if filled(bx, by, cell_w, cell_h)]
    else:
        shapes = [(w // TILE, h // TILE) for w, h in hardware.shapes]
        for by in range(0, pad_h, SHAPE_CELL):
            for bx in range(0, pad_w, SHAPE_CELL):
                cols, rows = min(SHAPE_CELL, pad_w - bx) // TILE, min(SHAPE_CELL, pad_h - by) // TILE
                occupied = [[filled(bx + tx * TILE, by + ty * TILE, TILE, TILE) for tx in range(cols)]
                            for ty in range(rows)]
                edges = (bx + SHAPE_CELL >= pad_w, by + SHAPE_CELL >= pad_h)  # the last cells end the image
                blocks += [(bx + tx * TILE, by + ty * TILE, tw * TILE, th * TILE)
                           for tx, ty, tw, th in cover_with_shapes(occupied, shapes, open_edges=edges)]
    return blocks


def tiles_and_sprites(image: Image.Image, hardware: Hardware = MEGA_DRIVE) -> Tuple[int, int]:
    """(tiles, hardware sprites) a part image needs on the console (``cut``)."""
    rects = cut(image, hardware)
    return tiles_of(rects), len(rects)
