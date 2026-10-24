"""Reference models of what the Mega Drive and SNES runtimes decide on their own, for their host tests: which draws
give way when a frame asks for more hardware sprites than the limit (ms_set_give_way), and where the slot cache keeps
each load list (ms_slot_cache_init). Both are written from the runtimes' documented rules, not from their code."""

from typing import Dict, List, Optional, Sequence, Set, Tuple


def given_way(costs: Sequence[int], levels: Sequence[int], limit: int) -> Set[int]:
    """The draws (indices, front to back) that give way: when the frame's sprites on the screen exceed the limit, the
    draws with a level, level 1 first, within a level the last drawn first, as many as the excess. A draw with nothing
    on the screen has nothing to give."""
    excess = sum(costs) - limit
    out: Set[int] = set()
    for level in sorted({lv for lv in levels if lv > 0}):
        for index in reversed(range(len(costs))):
            if excess <= 0:
                return out
            if levels[index] == level and costs[index] > 0:
                out.add(index)
                excess -= costs[index]
    return out


class SlotCache:
    """The slot cache: a pool of tiles, a slot per load list at the first place in tile order where its tiles fit
    (from a multiple of ``align``), the slots drawn longest ago making room (never one drawn this frame; of slots drawn
    equally long ago the last in tile order), at most ``slots`` of them. Records are reused like the runtime's (a free
    list, last freed first)."""

    NOT_DRAWN = 0xFFFF

    def __init__(self, start: int, count: int, slots: int = 48, align: int = 1, end_limit: Optional[int] = None):
        self.align = align
        self.start = -(-start // align) * align
        end = start + count
        self.end = min(end, end_limit) if end_limit is not None else end
        self.slots = slots
        self.records: List[Optional[Dict[str, int]]] = [None] * slots  # list, tile, tiles, drawn
        self.free = list(range(slots))  # the head first
        self.frame = 0
        self.slots_used = self.uploaded = self.left_out = 0
        self.evicted = 0  # slots that made room, since the cache began

    def begin(self) -> None:
        self.frame = (self.frame + 1) & 0xFFFF
        if self.frame == self.NOT_DRAWN:
            self.frame = 0
        self.slots_used = self.uploaded = self.left_out = 0

    def _by_tile(self) -> List[Dict[str, int]]:
        return sorted((r for r in self.records if r is not None), key=lambda r: r["tile"])

    def _room(self, tiles: int) -> Optional[int]:
        at = self.start
        for record in self._by_tile() + [None]:
            end = self.end if record is None else record["tile"]
            at = -(-at // self.align) * self.align
            if end >= at and end - at >= tiles:
                return at
            if record is None:
                return None
            at = record["tile"] + record["tiles"]
        return None

    def _evict(self) -> bool:
        oldest, age = None, 0
        for record in self._by_tile():  # of slots drawn equally long ago, the last in tile order goes
            if record["drawn"] != self.frame and (self.frame - record["drawn"]) & 0xFFFF >= age:
                age, oldest = (self.frame - record["drawn"]) & 0xFFFF, self.records.index(record)
        if oldest is None:
            return False
        self.records[oldest] = None
        self.free.insert(0, oldest)
        self.evicted += 1
        return True

    def draw(self, listed: int, tiles: int, upload: Optional[int] = None) -> Optional[int]:
        """A draw of a load list taking ``tiles`` tiles in a slot: the first tile of its slot, None when it is left
        out; the tiles it uploads (``upload``, else ``tiles``) count in ``uploaded``."""
        record = next((r for r in self.records if r is not None and r["list"] == listed), None)
        if record is None:
            if tiles > self.end - self.start or (not self.free and not self._evict()):
                self.left_out += 1
                return None
            while True:
                at = self._room(tiles)
                if at is not None:
                    break
                if not self._evict():
                    self.left_out += 1
                    return None
            number = self.free.pop(0)
            record = self.records[number] = {"list": listed, "tile": at, "tiles": tiles, "drawn": self.NOT_DRAWN}
            self.uploaded += tiles if upload is None else upload
        if record["drawn"] != self.frame:
            record["drawn"] = self.frame
            self.slots_used += 1
        return record["tile"]

    def clear(self) -> None:
        self.records = [None] * self.slots
        self.free = list(range(self.slots))


def crowd_draws(seed: int, count: int, frames: int, modules: int, mappings: int, width: int, height: int,
                own_sprites: int = 0) -> List[Tuple[str, int, int, int, int, int, int]]:
    """A picture of ``count`` frame and module draws (and ``own_sprites`` sprites of the game's own) across the screen
    and its edges, front to back: (kind "frame" / "module" / "sprite", index, mapping, flip, give-way level, x, y), a
    sprite's index its size or large flag. Levels 0 to 3, about half 0."""
    import random

    rng = random.Random(seed)
    draws = []
    for n in range(count):
        kind = "module" if modules and rng.random() < 0.25 else "frame"
        index = rng.randrange(modules if kind == "module" else frames)
        level = rng.choice((0, 0, 0, 1, 2, 3))
        draws.append((kind, index, rng.randrange(mappings), rng.randrange(4), level,
                      rng.randrange(-40, width + 40), rng.randrange(-40, height + 40)))
    for n in range(own_sprites):
        draws.insert(rng.randrange(len(draws) + 1), ("sprite", rng.randrange(16), 0, 0, rng.choice((0, 1, 1, 2)),
                                                     rng.randrange(-10, width + 10), rng.randrange(-10, height + 10)))
    return draws
