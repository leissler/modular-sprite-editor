"""Auto-modularisation: cut whole sprites into hardware-sized parts that several sprites share.

Input: sprites (RGBA images, e.g. the modules of a sheet that each hold a whole frame). Output: parts (new images)
and, for every sprite, the placements of parts that rebuild it pixel for pixel.

Cost model: what the console pays for the result (``Settings.hardware``, the Mega Drive by default, as the SGDK
exporter bakes it): video memory holds every part's tiles once, and every placement of a part costs its hardware
sprites. The engine minimises

    cost = unique tiles + sprite_weight * hardware sprites drawn (summed over all sprites)

sprite_weight is how many tiles one more hardware sprite in one frame is worth: low = fewest tiles (more, smaller
parts), high = fewest sprites (fewer, larger parts). Parts are cut in the console's sprite sizes (8 to 32 px on the
Mega Drive, the GBA's shapes, the SNES's squares, the NES's and Game Boy's one size), so one part is one hardware
sprite. Tiles and sprites are counted the way the budget overlay and the export count them (``sprite_cut``).

Method:
1. Identical sprites (also mirrored) are built once.
2. Every 8x8 window of every sprite (and of its mirror images) is hashed; equal windows in two sprites vote for the
   offset between them. Offsets with enough votes are compared pixel for pixel (agreement masks).
3. Greedy cover: the shared region that saves the most cost is cut into hardware sprites (see 4) and placed in
   every sprite that contains it exactly, at any offset, mirrored or not, as long as each placement pays for
   itself; also where some of its pixels differ, if those are opaque in that sprite and not yet covered: parts
   placed later (the leftovers at the latest) are drawn over them (``Settings.underdraw``). Candidates are
   re-evaluated lazily, only when they reach the top.
4. Hardware cut (``sprite_cut.tight_cut``): pixels are covered with rectangles of the console's sprite sizes in
   bands: dynamic programming picks the band heights, a second one the rectangles in each band; rows and columns
   are both tried.
5. What no shared part covers is cut the same way. Equal parts (also mirrored) are stored once.

Exact by construction: a part is placed only where all of its pixels equal the sprite's, or are opaque there and
drawn over by later placements (a sprite's placements are in draw order); every opaque pixel of a sprite is covered
last by its own colour. Transparent pixels never draw.
"""
from __future__ import annotations

import hashlib
import heapq
import itertools
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Collection, Dict, List, Optional, Sequence, Set, Tuple

from PIL import Image, ImageChops

import sprite_cut
from sprite_cut import MEGA_DRIVE, TILE, Hardware
from sprite_cut import bits_of as _bits
from sprite_cut import mask_of as _mask
from sprite_cut import opaque_mask as _opaque

CELL = 4  # granularity at which shared regions are kept together

FLIP_X, FLIP_Y = 1, 2

Rect = Tuple[int, int, int, int]


@dataclass
class Settings:
    sprite_weight: float = 2.0  # tiles one more hardware sprite in one frame is worth
    flip_x: bool = True  # find parts mirrored horizontally
    flip_y: bool = True  # ... and vertically (the Mega Drive flips both ways)
    share: bool = True  # look for parts several sprites share (off: only cut each sprite tightly)
    window: int = 8  # side of the hashed windows that find shared content (4 finds smaller parts, slower)
    min_shared_px: int = 16  # smallest shared region worth a part
    min_votes: int = 2  # matching 8x8 windows needed before two sprites are compared at an offset
    max_window_matches: int = 64  # windows that occur more often are too common to tell anything
    underdraw: bool = True  # place a part where other parts drawn later cover some of its pixels
    hardware: Hardware = MEGA_DRIVE  # the console whose sprite sizes and costs count


@dataclass
class Placement:
    part: int
    x: int  # top-left of the part's bounds in the sprite
    y: int
    flip_x: bool = False
    flip_y: bool = False


@dataclass
class Plan:
    parts: List[Image.Image]  # RGBA, cropped to their pixels
    placements: Dict[str, List[Placement]]  # by sprite key
    seconds: float = 0.0
    hardware: Hardware = MEGA_DRIVE  # what tiles and sprites are counted on

    def uses(self) -> Dict[int, int]:
        """Sprites each part appears in."""
        out: Dict[int, int] = {}
        for pls in self.placements.values():
            for part in {pl.part for pl in pls}:
                out[part] = out.get(part, 0) + 1
        return out

    def tiles(self) -> int:
        return sum(part_tiles(p, self.hardware)[0] for p in self.parts)

    def sprite_counts(self) -> Dict[str, int]:
        per_part = [part_tiles(p, self.hardware)[1] for p in self.parts]
        return {key: sum(per_part[pl.part] for pl in pls) for key, pls in self.placements.items()}


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- the hardware cut (sprite_cut)
def part_tiles(image: Image.Image, hardware: Hardware = MEGA_DRIVE) -> Tuple[int, int]:
    """(tiles, hardware sprites) of a part as the console shows it (the export's cut on the Mega Drive)."""
    return sprite_cut.tiles_and_sprites(image, hardware)


def hardware_cut(bits: int, w: int, h: int, weight: float, hardware: Hardware = MEGA_DRIVE) -> Tuple[float, List[Rect]]:
    """Rectangles of the console's sprite sizes that cover the mask's pixels for the least tiles + weight * count:
    (cost, rects in the mask's coordinates)."""
    return sprite_cut.tight_cut(bits, w, h, weight, hardware.sizes)


# --------------------------------------------------------------------------- images
def _normalised(image: Image.Image) -> Image.Image:
    """RGBA with every transparent pixel (0, 0, 0, 0), so equal pixels mean equal bytes."""
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    clear = Image.new("RGBA", image.size, (0, 0, 0, 0))
    return Image.composite(image, clear, alpha.point(lambda v: 255 if v else 0))


def _variant(image: Image.Image, v: int) -> Image.Image:
    if v & FLIP_X:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if v & FLIP_Y:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return image


def _digest(image: Image.Image) -> bytes:
    return hashlib.blake2b(image.tobytes() + bytes(str(image.size), "ascii"), digest_size=16).digest()


def _agreement_mask(a: Image.Image, b: Image.Image, dx: int, dy: int) -> Optional[Tuple[Image.Image, Image.Image]]:
    """Mode "1" masks over a: opaque pixels with a(x, y) == b(x + dx, y + dy), and opaque pixels where b is opaque
    too (equal or not)."""
    x0, y0 = max(0, -dx), max(0, -dy)
    x1, y1 = min(a.width, b.width - dx), min(a.height, b.height - dy)
    if x1 <= x0 or y1 <= y0:
        return None
    ca = a.crop((x0, y0, x1, y1))
    cb = b.crop((x0 + dx, y0 + dy, x1 + dx, y1 + dy))
    r, g, bl, al = ImageChops.difference(ca, cb).split()
    differ = ImageChops.lighter(ImageChops.lighter(r, g), ImageChops.lighter(bl, al))
    equal = differ.point(lambda v: 255 if v == 0 else 0, "1")
    opaque_a = _opaque(ca)
    equal = ImageChops.logical_and(equal, opaque_a)
    both = ImageChops.logical_and(opaque_a, _opaque(cb))
    out, overlap = Image.new("1", a.size, 0), Image.new("1", a.size, 0)
    out.paste(equal, (x0, y0))
    overlap.paste(both, (x0, y0))
    return out, overlap


def _region_bits(w: int, h: int, rects: Sequence[Rect]) -> List[int]:
    out = []
    for x, y, rw, rh in rects:
        m = Image.new("1", (w, h), 0)
        m.paste(1, (x, y, min(w, x + rw), min(h, y + rh)))
        out.append(_bits(m))
    return out


# --------------------------------------------------------------------------- the engine
@dataclass
class _Sprite:
    index: int
    image: Image.Image  # normalised RGBA, trimmed
    variants: Dict[int, Image.Image] = field(default_factory=dict)
    opaque: int = 0
    residual: int = 0
    cells: List[Tuple[int, int, int]] = field(default_factory=list)  # (bits, cx, cy) of CELL x CELL cells
    agreements: Dict[Tuple[int, int, int, int], Tuple[int, int]] = field(default_factory=dict)  # (equal, overlap)
    unfinished: Dict[Tuple[int, int, int, int], Tuple[int, int]] = field(default_factory=dict)  # (u's residual, over s)

    @property
    def w(self) -> int:
        return self.image.width

    @property
    def h(self) -> int:
        return self.image.height


class _Engine:
    def __init__(self, images: List[Image.Image], settings: Settings,
                 progress: Callable[[str, float], None], cancelled: Callable[[], bool]):
        self.settings = settings
        self.weight = settings.sprite_weight
        self.hardware = settings.hardware
        self.progress = progress
        self.cancelled = cancelled
        self.variants = [0]
        if settings.flip_x:
            self.variants.append(FLIP_X)
        if settings.flip_y:
            self.variants.append(FLIP_Y)
        if settings.flip_x and settings.flip_y:
            self.variants.append(FLIP_X | FLIP_Y)
        self.sprites: List[_Sprite] = []
        for i, image in enumerate(images):
            s = _Sprite(i, image)
            s.opaque = s.residual = _bits(_opaque(image))
            grid = [(x, y, CELL, CELL) for y in range(0, image.height, CELL) for x in range(0, image.width, CELL)]
            s.cells = [(bits, x // CELL, y // CELL) for bits, (x, y, _w, _h) in zip(_region_bits(image.width, image.height, grid), grid)]
            for v in self.variants:
                s.variants[v] = _variant(image, v)
            self.sprites.append(s)
        self.parts: List[Image.Image] = []
        self.part_index: Dict[bytes, Tuple[int, int]] = {}
        self.placements: List[List[Placement]] = [[] for _ in self.sprites]
        self.entries: List[List[Tuple[int, int, int, int, int]]] = [[] for _ in self.sprites]
        self.cut_costs: Dict[Tuple[int, int], float] = {}
        self.mapped: Dict[Tuple[int, int, int, int, int, int], int] = {}

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled()

    # ---------------------------------------------------------------- costs
    def residual_cost(self, s: _Sprite, bits: int) -> float:
        """What the pixels still to cover will cost, cut into hardware sprites."""
        if not bits:
            return 0.0
        key = (s.index, bits)
        cost = self.cut_costs.get(key)
        if cost is None:
            cost = hardware_cut(bits, s.w, s.h, self.weight, self.hardware)[0]
            self.cut_costs[key] = cost
        return cost

    # ---------------------------------------------------------------- 2. votes
    def vote(self) -> None:
        index: Dict[int, List[Tuple[int, int, int, int]]] = {}
        k = self.settings.window
        min_opaque = k * k // 2
        total = len(self.sprites)
        for n, s in enumerate(self.sprites):
            if n % 8 == 0:
                self.check()
                self.progress("Looking for shared pixels", 0.25 * n / max(1, total))
            for v in self.variants:
                image = s.variants[v]
                w, h = image.size
                if w < k or h < k:
                    continue
                data = image.tobytes()
                alpha = image.getchannel("A").point(lambda a: 1 if a else 0).tobytes()
                seg_hash: List[List[int]] = []
                seg_opaque: List[List[int]] = []
                for y in range(h):
                    row = data[y * w * 4:(y + 1) * w * 4]
                    arow = alpha[y * w:(y + 1) * w]
                    seg_hash.append([hash(row[x * 4:(x + k) * 4]) for x in range(w - k + 1)])
                    run = sum(arow[:k])
                    counts = [run]
                    for x in range(1, w - k + 1):
                        run += arow[x + k - 1] - arow[x - 1]
                        counts.append(run)
                    seg_opaque.append(counts)
                for x in range(w - k + 1):
                    col_hash = [seg_hash[y][x] for y in range(h)]
                    col_op = [seg_opaque[y][x] for y in range(h)]
                    run = sum(col_op[:k])
                    for y in range(h - k + 1):
                        if y:
                            run += col_op[y + k - 1] - col_op[y - 1]
                        if run < min_opaque:
                            continue
                        index.setdefault(hash(tuple(col_hash[y:y + k])), []).append((s.index, v, x, y))
        self.progress("Comparing sprites", 0.25)
        votes: Dict[Tuple[int, int, int, int, int], int] = {}
        cap = self.settings.max_window_matches
        for occurrences in index.values():
            if len(occurrences) < 2 or len(occurrences) > cap:
                continue
            for a in occurrences:
                if a[1]:
                    continue
                for b in occurrences:
                    if b[0] == a[0]:
                        continue  # repeats inside one sprite are left out
                    key = (a[0], b[0], b[1], b[2] - a[2], b[3] - a[3])
                    votes[key] = votes.get(key, 0) + 1
        for (s, u, v, dx, dy), count in votes.items():
            if count >= self.settings.min_votes:
                self.entries[s].append((count, u, v, dx, dy))
        for e in self.entries:
            e.sort(reverse=True)

    def agreement(self, s: _Sprite, u: int, v: int, dx: int, dy: int) -> int:
        return self._masks(s, u, v, dx, dy)[0]

    def overlap(self, s: _Sprite, u: int, v: int, dx: int, dy: int) -> int:
        """Pixels of s where u (its variant v at (dx, dy)) is opaque too, whether equal or not."""
        return self._masks(s, u, v, dx, dy)[1]

    def _masks(self, s: _Sprite, u: int, v: int, dx: int, dy: int) -> Tuple[int, int]:
        key = (u, v, dx, dy)
        found = s.agreements.get(key)
        if found is None:
            masks = _agreement_mask(s.image, self.sprites[u].variants[v], dx, dy)
            found = (_bits(masks[0]), _bits(masks[1])) if masks is not None else (0, 0)
            s.agreements[key] = found
        return found

    def map_mask(self, s: _Sprite, bits: int, u: _Sprite, v: int, dx: int, dy: int) -> int:
        """A mask over s as it lies in u (u's variant v shifted by (dx, dy) matches s). Regions come back for
        another look many times, so the answers are kept."""
        key = (s.index, bits, u.index, v, dx, dy)
        found = self.mapped.get(key)
        if found is not None:
            return found
        mask = _mask(bits, s.w, s.h)
        box = mask.getbbox()
        if not box:
            return 0
        bx, by, bx1, by1 = box
        x, y = self.map_box(u, v, dx, dy, bx, by, bx1 - bx, by1 - by)
        out = Image.new("1", (u.w, u.h), 0)
        out.paste(_variant(mask.crop(box), v), (x, y))
        if len(self.mapped) > 200_000:
            self.mapped.clear()
        found = self.mapped[key] = _bits(out)
        return found

    def unmap_mask(self, u: _Sprite, bits: int, s: _Sprite, v: int, dx: int, dy: int) -> int:
        """A mask over u as it lies in s (the inverse of ``map_mask``)."""
        return _bits(_variant(_mask(bits, u.w, u.h), v).crop((dx, dy, dx + s.w, dy + s.h)))

    def still_open(self, s: _Sprite, u: int, v: int, dx: int, dy: int, residual: int) -> int:
        """Pixels of s whose counterparts in u are still to be covered (``residual`` of u), kept until it changes."""
        key = (u, v, dx, dy)
        found = s.unfinished.get(key)
        if found is None or found[0] is not residual:
            found = s.unfinished[key] = (residual, self.unmap_mask(self.sprites[u], residual, s, v, dx, dy))
        return found[1]

    @staticmethod
    def map_box(u: _Sprite, v: int, dx: int, dy: int, x: int, y: int, w: int, h: int) -> Tuple[int, int]:
        """Top-left in u of the box (x, y, w, h) of s."""
        return (u.w - (x + dx) - w if v & FLIP_X else x + dx), (u.h - (y + dy) - h if v & FLIP_Y else y + dy)

    # ---------------------------------------------------------------- 3. greedy cover
    def evaluate(self, s: _Sprite, region: int):
        """(saving in cost units, pieces [(image, x, y)] over s, occurrences [(u, v, dx, dy, new bits over u)])."""
        _cost, rects = hardware_cut(region, s.w, s.h, self.weight, self.hardware)
        pieces = self.pieces(s, region, rects)
        tiles = sum(part_tiles(im, self.hardware)[0] for im, _x, _y in pieces)
        per_use = self.weight * len(pieces)
        saving = self.residual_cost(s, s.residual) - self.residual_cost(s, s.residual & ~region) - per_use
        occurrences = []
        pending: Dict[int, int] = {}
        for _count, u, v, dx, dy in self.entries[s.index]:
            agree = self.agreement(s, u, v, dx, dy)
            target = self.sprites[u]
            residual = pending.get(u, target.residual)
            differ = region & ~agree
            if differ:
                # Drawn under what comes later: allowed where u is opaque and its pixels are still to be covered
                # (the parts placed after it, the leftovers at the latest, paint them in u's colours).
                if not self.settings.underdraw or differ & ~self.overlap(s, u, v, dx, dy):
                    continue
                if differ & ~self.still_open(s, u, v, dx, dy, residual):
                    continue
            new = self.map_mask(s, region & agree, target, v, dx, dy) & residual
            if not new:
                continue
            gain = self.residual_cost(target, residual) - self.residual_cost(target, residual & ~new) - per_use
            if gain <= 0:
                continue  # this placement would cost more than it saves
            pending[u] = residual & ~new
            saving += gain
            occurrences.append((u, v, dx, dy, new))
        return saving - tiles, pieces, occurrences

    def pieces(self, s: _Sprite, region: int, rects: List[Rect]) -> List[Tuple[Image.Image, int, int]]:
        """The region's pixels in each rectangle, cropped: (image, x, y) over s."""
        mask = _mask(region, s.w, s.h)
        out = []
        for x, y, w, h in rects:
            piece_mask = Image.new("1", s.image.size, 0)
            piece_mask.paste(mask.crop((x, y, x + w, y + h)), (x, y))
            box = piece_mask.getbbox()
            if not box:
                continue
            image = Image.new("RGBA", s.image.size, (0, 0, 0, 0))
            image.paste(s.image, (0, 0), piece_mask)
            out.append((image.crop(box), box[0], box[1]))
        return out

    def add_part(self, image: Image.Image) -> Tuple[int, int]:
        """(part, flip) that draws the image, reusing an equal part (also mirrored)."""
        for v in self.variants:
            found = self.part_index.get(_digest(_variant(image, v)))
            if found is not None:
                return found[0], found[1] ^ v
        index = len(self.parts)
        self.parts.append(image)
        self.part_index[_digest(image)] = (index, 0)
        return index, 0

    def place(self, s: _Sprite, region: int, pieces, occurrences) -> None:
        for image, x, y in pieces:
            part, flip = self.add_part(image)
            self.placements[s.index].append(Placement(part, x, y, bool(flip & FLIP_X), bool(flip & FLIP_Y)))
            for u, v, dx, dy, _new in occurrences:
                tx, ty = self.map_box(self.sprites[u], v, dx, dy, x, y, image.width, image.height)
                f = flip ^ v
                self.placements[u].append(Placement(part, tx, ty, bool(f & FLIP_X), bool(f & FLIP_Y)))
        s.residual &= ~region
        for u, _v, _dx, _dy, new in occurrences:
            self.sprites[u].residual &= ~new

    def cover(self) -> None:
        counter = itertools.count()
        heap: List[Tuple[float, int, Tuple]] = []
        for s in self.sprites:
            for count, u, v, dx, dy in self.entries[s.index]:
                estimate = (count ** 0.5 + self.settings.window - 1) ** 2 / (TILE * TILE)
                heapq.heappush(heap, (-estimate, next(counter), ("pair", s.index, u, v, dx, dy)))
        total = max(1, len(heap))
        done = 0
        min_px = self.settings.min_shared_px
        while heap:
            _neg, _n, item = heapq.heappop(heap)
            done += 1
            if done % 32 == 0:
                self.check()
                self.progress("Finding shared parts", 0.25 + 0.65 * min(1.0, done / (total * 1.5)))
            if item[0] == "pair":
                _kind, si, u, v, dx, dy = item
                s = self.sprites[si]
                shared = self.agreement(s, u, v, dx, dy) & s.residual
                if shared.bit_count() < min_px:
                    continue
                for region in self.regions(s, shared):
                    if region.bit_count() >= min_px:
                        estimate = region.bit_count() / (TILE * TILE)
                        heapq.heappush(heap, (-estimate, next(counter), ("region", si, region)))
                continue
            _kind, si, region = item
            s = self.sprites[si]
            region &= s.residual
            if region.bit_count() < min_px:
                continue
            value, pieces, occurrences = self.evaluate(s, region)
            if value <= 0 or not occurrences:
                continue
            if heap and value < -heap[0][0]:
                heapq.heappush(heap, (-value, next(counter), ("region", si, region)))
                continue
            self.place(s, region, pieces, occurrences)

    def regions(self, s: _Sprite, shared: int) -> List[int]:
        """Shared pixels grouped into regions: cells holding enough shared pixels, connected (8-way)."""
        keep: Dict[Tuple[int, int], int] = {}
        for bits, cx, cy in s.cells:
            here = (shared & bits).bit_count()
            if not here:
                continue
            opaque = (s.opaque & bits).bit_count()
            if here * 3 >= opaque or here >= CELL * CELL // 2:
                keep[(cx, cy)] = shared & bits
        out = []
        seen = set()
        for start in keep:
            if start in seen:
                continue
            seen.add(start)
            stack, bits = [start], 0
            while stack:
                cx, cy = stack.pop()
                bits |= keep[(cx, cy)]
                for nx in (cx - 1, cx, cx + 1):
                    for ny in (cy - 1, cy, cy + 1):
                        if (nx, ny) in keep and (nx, ny) not in seen:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
            out.append(bits)
        return out

    # ---------------------------------------------------------------- 5. the rest
    def leftovers(self) -> None:
        for n, s in enumerate(self.sprites):
            if n % 16 == 0:
                self.check()
                self.progress("Cutting the rest", 0.9 + 0.1 * n / max(1, len(self.sprites)))
            if not s.residual:
                continue
            _cost, rects = hardware_cut(s.residual, s.w, s.h, self.weight, self.hardware)
            for image, x, y in self.pieces(s, s.residual, rects):
                part, flip = self.add_part(image)
                self.placements[s.index].append(Placement(part, x, y, bool(flip & FLIP_X), bool(flip & FLIP_Y)))
            s.residual = 0


def plan(sprites: Dict[str, Image.Image], settings: Optional[Settings] = None,
         progress: Optional[Callable[[str, float], None]] = None,
         cancelled: Optional[Callable[[], bool]] = None, own: Optional[Collection[str]] = None) -> Plan:
    """Cut the sprites (key -> RGBA image) into parts. The sprites in ``own`` get parts of their own, which no other
    sprite uses (``apply_plan`` gives mappings of them a part-level form). Raises Cancelled when ``cancelled()``
    turns true."""
    started = time.perf_counter()
    settings = settings or Settings()
    alone = [key for key in sprites if key in set(own or ())]
    if alone:
        shared = plan({k: v for k, v in sprites.items() if k not in alone}, settings, progress, cancelled)
        parts, placements = list(shared.parts), dict(shared.placements)
        for key in alone:
            single = plan({key: sprites[key]}, replace(settings, share=False), None, cancelled)
            placements[key] = [replace(pl, part=pl.part + len(parts)) for pl in single.placements[key]]
            parts += single.parts
        result = Plan(parts, {key: placements[key] for key in sprites}, hardware=settings.hardware)
        result.seconds = time.perf_counter() - started
        return result
    progress = progress or (lambda _text, _fraction: None)
    keys = list(sprites)
    # 1. Identical sprites (after trimming, also mirrored) are built once.
    flips = [0] + ([FLIP_X] if settings.flip_x else []) + ([FLIP_Y] if settings.flip_y else []) + \
        ([FLIP_X | FLIP_Y] if settings.flip_x and settings.flip_y else [])
    unique: List[Image.Image] = []
    seen: Dict[bytes, int] = {}
    alias: List[Optional[Tuple[int, int, int, int]]] = []  # sprite -> (unique sprite, flip, x, y) or None if empty
    for key in keys:
        image = _normalised(sprites[key])
        box = image.getchannel("A").getbbox()
        if not box:
            alias.append(None)
            continue
        image = image.crop(box)
        found = None
        for v in flips:
            hit = seen.get(_digest(_variant(image, v)))
            if hit is not None:
                found = (hit, v, box[0], box[1])
                break
        if found is None:
            seen[_digest(image)] = len(unique)
            found = (len(unique), 0, box[0], box[1])
            unique.append(image)
        alias.append(found)

    engine = _Engine(unique, settings, progress, cancelled or (lambda: False))
    if settings.share:
        engine.vote()
        engine.cover()
    engine.leftovers()

    placements: Dict[str, List[Placement]] = {}
    for key, found in zip(keys, alias):
        if found is None:
            placements[key] = []
            continue
        u, v, ox, oy = found
        uw, uh = unique[u].size
        out = []
        for pl in engine.placements[u]:
            pw, ph = engine.parts[pl.part].size
            x = uw - pl.x - pw if v & FLIP_X else pl.x
            y = uh - pl.y - ph if v & FLIP_Y else pl.y
            out.append(Placement(pl.part, x + ox, y + oy, pl.flip_x ^ bool(v & FLIP_X), pl.flip_y ^ bool(v & FLIP_Y)))
        placements[key] = out
    result = Plan(engine.parts, placements, hardware=settings.hardware)
    result.seconds = time.perf_counter() - started
    progress("Done", 1.0)
    return result


def compose(plan_: Plan, key: str, size: Tuple[int, int]) -> Image.Image:
    """The sprite rebuilt from its parts (for checks and previews)."""
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    for pl in plan_.placements[key]:
        out.alpha_composite(_variant(plan_.parts[pl.part], (FLIP_X if pl.flip_x else 0) | (FLIP_Y if pl.flip_y else 0)),
                            (pl.x, pl.y))
    return out


# --------------------------------------------------------------------------- applying a plan to a project
def pack(parts: List[Image.Image], gutter: int = 1) -> Tuple[Image.Image, List[Tuple[int, int]]]:
    """Parts on one sheet (rows, tallest first), and where each went."""
    order = sorted(range(len(parts)), key=lambda i: (-parts[i].height, -parts[i].width, i))
    area = sum((p.width + gutter) * (p.height + gutter) for p in parts) or 1
    widest = max((p.width for p in parts), default=1)
    row_w = max(widest, int((area ** 0.5) * 1.15))
    places: List[Tuple[int, int]] = [(0, 0)] * len(parts)
    x = y = row_h = used_w = 0
    for i in order:
        w, h = parts[i].size
        if x and x + w > row_w:
            x, y, row_h = 0, y + row_h + gutter, 0
        places[i] = (x, y)
        used_w = max(used_w, x + w)
        x += w + gutter
        row_h = max(row_h, h)
    sheet = Image.new("RGBA", (max(1, used_w), max(1, y + row_h)), (0, 0, 0, 0))
    for i, part in enumerate(parts):
        sheet.paste(part, places[i])
    return sheet, places


def _rotate(vx: int, vy: int, degrees: float) -> Tuple[int, int]:
    """(vx, vy) turned like the editor turns parts (90-degree steps, exact)."""
    for _ in range(int(round(degrees / 90.0)) % 4):
        vx, vy = -vy, vx
    return vx, vy


def mapping_roles(project, module_ids: Collection[str]) -> Tuple[Set[str], Set[str]]:
    """(replaced, shown instead): the modules among ``module_ids`` that mappings replace (or hide), and those that
    mappings show in place of others."""
    ids = set(module_ids)
    replaced = {key for mapping in project.mappings for key in mapping.map if key in ids}
    shown = {dest for mapping in project.mappings for dest in mapping.map.values() if dest in ids}
    return replaced, shown


def mapping_only(project, module_ids: Collection[str]) -> Set[str]:
    """Modules among ``module_ids`` that only mappings show (no frame uses them): Auto Modularize leaves them whole."""
    used = {fm.ref_id for frame in project.frames for fm in frame.fmodules if fm.ref_type == "module"}
    return {mid for mid in mapping_roles(project, module_ids)[1] if mid not in used}


@dataclass
class Applied:
    image_id: str
    sheet_path: str
    parts: int
    rewritten_refs: int
    new_frames: int
    removed_modules: int
    kept_modules: int  # used with a free rotation somewhere: kept whole there
    stand_ins: int  # modules mappings replace, now an empty stand-in next to their parts
    kept_for_mappings: int  # modules mappings show in place of others, kept whole for them


def apply_plan(project, image_id: str, module_ids: Sequence[str], plan_: Plan, sheet_path: str,
               part_prefix: str = "Part") -> Applied:
    """Put the parts on a new image (saved to sheet_path), rebuild the frames that use the modules from the
    parts, give modules no frame uses a frame of their own, and remove the modules that are no longer used.

    Mappings keep working: a module that mappings show in place of others stays as it is; a module that mappings
    replace (plan it with ``own``, so its parts are its own) is drawn by its parts plus an empty stand-in module where
    it was (same place, flips and turn), and each mapping hides those parts and shows its replacement in place of the
    stand-in."""
    from models import FModule, generate_id

    sheet, places = pack(plan_.parts)
    sheet.save(sheet_path)
    asset = project.create_image(sheet_path, sheet.width, sheet.height)
    used_names = {m.name for m in project.modules}

    def unique_name(name: str) -> str:
        found, k = name, 2
        while found in used_names:
            found = f"{name} ({k})"
            k += 1
        used_names.add(found)
        return found

    part_modules = []
    for n, (part, (px, py)) in enumerate(zip(plan_.parts, places), start=1):
        part_modules.append(project.create_module(unique_name(f"{part_prefix} {n:03d}"), asset.id,
                                                  (px, py, part.width, part.height), (part.width // 2, part.height // 2)))

    sources = {mid: project.get_module(mid) for mid in module_ids
               if project.get_module(mid) is not None and mid in plan_.placements}
    replaced, shown_instead = mapping_roles(project, sources)
    stand_ins = {mid: project.create_module(unique_name(f"{sources[mid].name} (stand-in)"), asset.id, (0, 0, 0, 0),
                                            tuple(sources[mid].pivot))
                 for mid in sources if mid in replaced}

    def parts_for(fm, src) -> List:
        """FModules that draw src's parts like fm draws src (flips in place, rotation about the pivot), and its
        stand-in where mappings replace it."""
        w, h = src.rect[2], src.rect[3]
        if getattr(src, "rotated", False):
            w, h = h, w
        px, py = src.pivot
        out = []
        for pl in plan_.placements[src.id]:
            mod = part_modules[pl.part]
            pw, ph = mod.rect[2], mod.rect[3]
            x = w - pl.x - pw if fm.flip_x else pl.x
            y = h - pl.y - ph if fm.flip_y else pl.y
            vx, vy = _rotate(x + mod.pivot[0] - px, y + mod.pivot[1] - py, fm.rotation_degrees)
            out.append(FModule(id=generate_id("fm"), ref_type="module", ref_id=mod.id,
                               position=(int(fm.position[0]) + vx, int(fm.position[1]) + vy),
                               flip_x=bool(fm.flip_x) ^ pl.flip_x, flip_y=bool(fm.flip_y) ^ pl.flip_y,
                               rotation_degrees=float(fm.rotation_degrees)))
        if src.id in stand_ins:
            out.append(FModule(id=generate_id("fm"), ref_type="module", ref_id=stand_ins[src.id].id,
                               position=tuple(fm.position), flip_x=bool(fm.flip_x), flip_y=bool(fm.flip_y),
                               rotation_degrees=float(fm.rotation_degrees)))
        return out

    rewritten = 0
    kept: set = set()
    referenced: set = set()
    for frame in project.frames:
        new_list = []
        for fm in frame.fmodules:
            src = sources.get(fm.ref_id) if fm.ref_type == "module" else None
            if src is None:
                new_list.append(fm)
                continue
            referenced.add(src.id)
            if abs(fm.rotation_degrees / 90.0 - round(fm.rotation_degrees / 90.0)) > 1e-6:
                kept.add(src.id)  # a free rotation is not pixel-exact in parts: keep the whole sprite there
                new_list.append(fm)
                continue
            new_list.extend(parts_for(fm, src))
            rewritten += 1
        frame.fmodules = new_list

    new_frames = 0
    for mid, src in sources.items():
        if mid in referenced or mid in shown_instead:
            continue  # (a module only mappings show stays a module, it needs no frame)
        frame = project.create_frame(src.name)
        frame.fmodules = parts_for(FModule(id="", ref_type="module", ref_id=mid, position=(0, 0)), src)
        new_frames += 1

    for mapping in project.mappings:
        for key in [k for k in mapping.map if k in stand_ins]:
            dest = mapping.map[key] if key in kept else mapping.map.pop(key)  # a kept module is still drawn whole
            for pl in plan_.placements[key]:
                mapping.map[part_modules[pl.part].id] = None
            if dest is not None:
                mapping.map[stand_ins[key].id] = dest
    removed = {mid for mid in sources if mid not in kept and mid not in shown_instead}
    project.modules = [m for m in project.modules if m.id not in removed]
    return Applied(asset.id, sheet_path, len(part_modules), rewritten, new_frames, len(removed), len(kept),
                   len(stand_ins), len(shown_instead & set(sources)))
