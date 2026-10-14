"""Palettes (wx-free): a project's palettes and palette swaps as its console shows them, shared by the editor's
previews, the budget and the exporters. Design: docs/PALETTES.md.

A palette (``models.Palette``) lists its colours in hardware order, slot 1 first (slot 0 is the transparent one), at
most as many as the console shows per palette (``consoles.PaletteHardware.visible``: 15 on the Mega Drive). Every
image belongs to one (``Project.image_palette``); vector shapes use the first. A pixel takes the first slot with
exactly its colour, else the nearest one, in the console view, the swaps, the budget's tile count and the export alike.

A palette swap (``models.PaletteSwap``) replaces slots' colours and can give a palette colour cycles of its own;
a colour cycle rotates a run of slots every few video frames.

Format 6 built the palettes from the images every time; ``build_colours`` keeps its rules for the projects it wrote.
"""

from __future__ import annotations

import colorsys
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import consoles
from models import ColourCycle, Palette, PaletteChange, PaletteSwap

RGB = Tuple[int, int, int]


# ---------------------------------------------------------------------------- the console's colours
def hardware(project: Any) -> consoles.PaletteHardware:
    """The palette hardware of the project's console."""
    return consoles.console_by_key(getattr(project, "console", None)).palette


def capacity(project: Any) -> int:
    """Colours a palette can hold (the transparent slot not counted)."""
    return hardware(project).visible


def _level(value: int, bits: int) -> int:
    """A channel kept to ``bits`` bits, spread over 0-255 again."""
    return (int(value) >> (8 - bits)) * 255 // ((1 << bits) - 1)


def md_level(value: int) -> int:
    """A channel as the Mega Drive shows it: the top 3 bits, spread over 0-255 (0, 36, 72, ... 255)."""
    return _level(value, 3)


def md_colour(rgb: Sequence[int]) -> RGB:
    return md_level(rgb[0]), md_level(rgb[1]), md_level(rgb[2])


def md_word(rgb: Sequence[int]) -> int:
    """The colour as a Mega Drive palette (CRAM) word: 0000 BBB0 GGG0 RRR0."""
    return ((int(rgb[2]) >> 5) << 9) | ((int(rgb[1]) >> 5) << 5) | ((int(rgb[0]) >> 5) << 1)


def console_colour(spec: consoles.PaletteHardware, rgb: Sequence[int]) -> RGB:
    """A colour as the console shows it: 3 or 5 bits a channel, or the nearest of its fixed colours."""
    if spec.colour_model == "rgb333":
        return md_colour(rgb)
    if spec.colour_model == "bgr555":
        return _level(rgb[0], 5), _level(rgb[1], 5), _level(rgb[2], 5)
    if spec.colour_model == "fixed" and spec.fixed_colours:
        return spec.fixed_colours[nearest(tuple(int(v) for v in rgb[:3]), spec.fixed_colours)]  # type: ignore[arg-type]
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


# ---------------------------------------------------------------------------- pixels and slots
def nearest(rgb: RGB, colours: Sequence[RGB], cache: Optional[Dict[RGB, int]] = None) -> int:
    """The position in ``colours`` of the first exact match, else of the closest colour (squared RGB distance); 0 for
    an empty list. The export stores it plus 1 (slot 0 is transparent)."""
    if cache is not None and rgb in cache:
        return cache[rgb]
    best, best_dist = 0, None
    for index, colour in enumerate(colours):
        dist = (rgb[0] - colour[0]) ** 2 + (rgb[1] - colour[1]) ** 2 + (rgb[2] - colour[2]) ** 2
        if best_dist is None or dist < best_dist:
            best, best_dist = index, dist
            if dist == 0:
                break
    if cache is not None:
        cache[rgb] = best
    return best


def rotate(colours: Sequence[RGB], cycles: Sequence[ColourCycle], frame: Optional[float]) -> List[RGB]:
    """The colours after the cycles have run for ``frame`` video frames (None: as they are). A cycle moves each
    colour of its run one slot up per step (down when ``reverse``); runs outside the palette are skipped."""
    out = list(colours)
    if frame is None:
        return out
    for cycle in cycles:
        start, count = int(cycle.first) - 1, int(cycle.count)
        if count < 2 or start < 0 or start + count > len(out):
            continue
        steps = (int(frame) // max(1, int(cycle.frames))) % count
        if steps:
            run = out[start:start + count]
            shift = -steps if cycle.reverse else steps
            out[start:start + count] = [run[(i - shift) % count] for i in range(count)]
    return out


def colours_of(project: Any, palette: Palette) -> List[RGB]:
    """The palette's colours; one not built yet (None) takes its images' colours with format 6's rules."""
    if palette.colours is not None:
        return list(palette.colours)
    return build_colours(palette_usage(project, palette), capacity(project))


def change_of(swap: Optional[PaletteSwap], palette: Palette) -> Optional[PaletteChange]:
    return swap.palettes.get(palette.id) if swap is not None else None


def cycles_of(palette: Palette, swap: Optional[PaletteSwap] = None) -> List[ColourCycle]:
    """The cycles a draw runs: the swap's own for this palette, else the palette's."""
    change = change_of(swap, palette)
    return list(change.cycles if change is not None and change.cycles is not None else palette.cycles)


def swapped_colours(palette: Palette, swap: Optional[PaletteSwap] = None,
                    base: Optional[Sequence[RGB]] = None) -> List[RGB]:
    """The palette's colours (``base``, else its stored ones) with the swap's replacements, before any cycling."""
    shown = list(base if base is not None else (palette.colours or []))
    change = change_of(swap, palette)
    if change is not None:
        for i, rgb in enumerate(change.colours[:len(shown)]):
            if rgb is not None:
                shown[i] = tuple(rgb)  # type: ignore[assignment]
    return shown


def shown_colours(project: Any, palette: Palette, swap: Optional[PaletteSwap] = None, frame: Optional[float] = None,
                  console_view: bool = False, base: Optional[Sequence[RGB]] = None) -> List[RGB]:
    """The palette's colours as a draw shows them: swapped, cycled at video frame ``frame``, and as the console shows
    them if ``console_view``."""
    base = list(base) if base is not None else colours_of(project, palette)
    shown = rotate(swapped_colours(palette, swap, base), cycles_of(palette, swap), frame)
    if console_view:
        spec = hardware(project)
        shown = [console_colour(spec, rgb) for rgb in shown]
    return shown


def recolours(palette: Palette, swap: Optional[PaletteSwap], frame: Optional[float],
              base: Optional[Sequence[RGB]] = None) -> bool:
    """Whether a draw with this swap at this frame shows the palette's images in other colours than their own."""
    base = list(base if base is not None else (palette.colours or []))
    if swapped_colours(palette, swap, base) != base:
        return True
    return frame is not None and rotate(base, cycles_of(palette, swap), frame) != base


def recolour(rgba: Any, base: Sequence[RGB], shown: Sequence[RGB], opaque: bool = False) -> Any:
    """The image with every pixel in ``shown``'s colour of its slot in ``base`` (the first exact match, else the
    nearest). ``opaque`` makes every visible pixel fully opaque, as the console shows it. Fast: the image's own
    colours (exact up to 256, which sprite sheets stay under) are remapped, not its pixels."""
    from PIL import Image

    rgba = rgba.convert("RGBA")
    alpha = rgba.getchannel("A")
    if opaque:
        alpha = alpha.point(lambda a: 255 if a else 0)
    indexed = rgba.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
    raw = indexed.getpalette() or []
    if not base:
        out = indexed.convert("RGB").convert("RGBA")
        out.putalpha(alpha)
        return out
    cache: Dict[RGB, int] = {}
    remapped: List[int] = []
    for i in range(0, len(raw) - 2, 3):
        slot = nearest((raw[i], raw[i + 1], raw[i + 2]), base, cache)
        remapped.extend(shown[slot] if slot < len(shown) else base[slot])
    indexed.putpalette(remapped)
    out = indexed.convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def console_image(rgba: Any, palette: Sequence[RGB], spec: consoles.PaletteHardware = consoles.MEGA_DRIVE.palette) -> Any:
    """The image as the console shows it with these colours: visible pixels turn fully opaque and take the nearest
    palette colour, as the console shows it."""
    return recolour(rgba, palette, [console_colour(spec, rgb) for rgb in palette], opaque=True)


# ---------------------------------------------------------------------------- what a palette holds
def image_colours(path: str, key: Optional[Sequence[int]]) -> Counter:
    """Visible colours of an image file with their pixel counts; transparent pixels and the key colour take none.
    Empty for a file that is missing or can't be read."""
    return _read_colours(path, key) or Counter()


def _read_colours(path: str, key: Optional[Sequence[int]]) -> Optional[Counter]:
    """An image file's visible colours, or None if it is missing or can't be read."""
    from PIL import Image

    counts: Counter = Counter()
    if not path or not os.path.exists(path):
        return None
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
    except (OSError, ValueError):
        return None
    key_rgb = tuple(int(v) for v in key) if key else None
    for count, (r, g, b, a) in rgba.getcolors(rgba.width * rgba.height) or []:
        if a == 0 or (r, g, b) == key_rgb:
            continue
        counts[(int(r), int(g), int(b))] += int(count)
    return counts


def palette_images(project: Any, palette: Palette) -> List[Any]:
    return [asset for asset in project.images if project.image_palette(asset).id == palette.id]


def palette_usage(project: Any, palette: Palette) -> Counter:
    """The colours of the palette's images with pixel counts; the first palette also counts the vector shapes'."""
    counts: Counter = Counter()
    for asset in palette_images(project, palette):
        counts.update(image_colours(asset.file_path, asset.transparent_color))
    if project.palettes and project.palettes[0].id == palette.id:
        for mod in project.modules:
            if mod.type != "MD_IMAGE" and mod.color:
                counts[tuple(int(v) for v in mod.color[:3])] += max(1, int(mod.rect[2]) * int(mod.rect[3]))
    return counts


def build_colours(counts: Counter, room: int) -> List[RGB]:
    """Format 6's palette for these colours: all of them when they fit (most used first), else the image quantizer's
    merge of them into ``room`` colours."""
    from PIL import Image

    if not counts:
        return []
    if len(counts) <= room:
        return [rgb for rgb, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    canvas = Image.new("RGB", (len(counts), 1), (0, 0, 0))
    for x, rgb in enumerate(counts.keys()):
        canvas.putpixel((x, 0), rgb)
    raw = canvas.quantize(colors=room, dither=Image.Dither.NONE).getpalette() or []
    return [(int(raw[i]), int(raw[i + 1]), int(raw[i + 2])) for i in range(0, min(len(raw), 3 * room), 3)]


def build_missing(project: Any) -> List[Palette]:
    """Palettes without colours (from a format 6 project) get them from their images with format 6's rules, so the
    project draws and exports as it did. One whose images can't be read waits until they can. Returns those built."""
    built = []
    for palette in project.palettes:
        if palette.colours is not None:
            continue
        if any(_read_colours(asset.file_path, asset.transparent_color) is None
               for asset in palette_images(project, palette)):
            continue  # an image can't be read (yet): build once it can
        palette.colours = build_colours(palette_usage(project, palette), capacity(project))
        built.append(palette)
    return built


def missing_colours(project: Any, palette: Palette) -> List[RGB]:
    """Colours the palette's images use that it doesn't hold, most used first."""
    held = set(colours_of(project, palette))
    usage = palette_usage(project, palette)
    return [rgb for rgb, _count in sorted(usage.items(), key=lambda item: (-item[1], item[0])) if rgb not in held]


def add_missing_colours(project: Any, palette: Palette) -> int:
    """Put the images' colours the palette lacks into its free slots, most used first. Returns how many went in."""
    if palette.colours is None:
        palette.colours = colours_of(project, palette)
    room = capacity(project) - len(palette.colours)
    added = missing_colours(project, palette)[:max(0, room)]
    palette.colours.extend(added)
    return len(added)


def slot_usage(project: Any, palette: Palette) -> List[int]:
    """Pixels each slot draws (exact matches and the colours that fall back to it)."""
    colours = list(palette.colours or [])
    used = [0] * len(colours)
    cache: Dict[RGB, int] = {}
    for rgb, count in palette_usage(project, palette).items():
        if colours:
            used[nearest(rgb, colours, cache)] += count
    return used


def unused_slots(project: Any, palette: Palette) -> List[int]:
    return [slot for slot, count in enumerate(slot_usage(project, palette)) if count == 0]


def duplicate_slots(palette: Palette) -> List[int]:
    """Slots whose colour an earlier slot has too (pixels never take them)."""
    seen: set = set()
    found = []
    for slot, rgb in enumerate(palette.colours or []):
        if rgb in seen:
            found.append(slot)
        seen.add(rgb)
    return found


def reorder(project: Any, palette: Palette, order: Sequence[int]) -> int:
    """Put the slots in a new order (``order[i]`` = the old slot that goes to slot i). The swaps' replacements move
    with their slots; a colour cycle stays if its slots still follow each other, and the rest are removed. Returns
    how many cycles were removed."""
    old = list(palette.colours or [])
    order = [i for i in order if 0 <= i < len(old)]
    palette.colours = [old[i] for i in order]
    new_slot = {old_slot: new for new, old_slot in enumerate(order)}

    def moved(cycles: List[ColourCycle]) -> Tuple[List[ColourCycle], int]:
        kept, dropped = [], 0
        for cycle in cycles:
            slots = [new_slot.get(cycle.first - 1 + i) for i in range(cycle.count)]
            if None not in slots and all(b == a + 1 for a, b in zip(slots, slots[1:])):  # type: ignore[operator]
                kept.append(ColourCycle(first=slots[0] + 1, count=cycle.count, frames=cycle.frames,  # type: ignore[operator]
                                        reverse=cycle.reverse))
            else:
                dropped += 1
        return kept, dropped

    palette.cycles, dropped = moved(palette.cycles)
    for swap in project.palette_swaps:
        change = swap.palettes.get(palette.id)
        if change is None:
            continue
        change.colours = trim([change.colours[i] if i < len(change.colours) else None for i in order])
        if change.cycles is not None:
            change.cycles, lost = moved(change.cycles)
            dropped += lost
    return dropped


def remove_slots(project: Any, palette: Palette, slots: Sequence[int]) -> int:
    """Remove these slots (the swaps' replacements go with them); returns how many cycles had to go."""
    gone = set(slots)
    return reorder(project, palette, [i for i in range(len(palette.colours or [])) if i not in gone])


def trim(colours: List[Optional[RGB]]) -> List[Optional[RGB]]:
    """A swap's replacements without the unchanged slots at the end."""
    while colours and colours[-1] is None:
        colours.pop()
    return colours


SORTS = ("brightness", "hue", "usage")


def sort_order(project: Any, palette: Palette, how: str) -> List[int]:
    """Slots ordered dark to light, by hue, or most used first."""
    colours = list(palette.colours or [])
    if how == "usage":
        used = slot_usage(project, palette)
        return sorted(range(len(colours)), key=lambda i: (-used[i], i))
    if how == "hue":
        def hue(i: int) -> Tuple[float, float, float]:
            h, l, s = colorsys.rgb_to_hls(*(v / 255.0 for v in colours[i]))
            return (h if s > 0.08 else -1.0, l, s)  # greys first
        return sorted(range(len(colours)), key=hue)
    return sorted(range(len(colours)), key=lambda i: (luma(colours[i]), i))


def luma(rgb: Sequence[int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


# ---------------------------------------------------------------------------- the export's palette entries
@dataclass(frozen=True)
class Entry:
    """A palette as an export loads it into the console: a project palette, or what a swap makes of one."""
    palette_id: str
    swap_id: Optional[str]
    name: str
    colours: Tuple[RGB, ...]
    cycles: Tuple[ColourCycle, ...] = field(default=())


def export_entries(project: Any) -> List[Entry]:
    """Every palette (in project order), then every swap's version of each palette it changes."""
    project.default_palette()
    base = {p.id: colours_of(project, p) for p in project.palettes}
    entries = [Entry(p.id, None, p.name, tuple(base[p.id]), tuple(p.cycles)) for p in project.palettes]
    for swap in project.palette_swaps:
        for palette in project.palettes:
            if palette.id in swap.palettes:
                entries.append(Entry(palette.id, swap.id, f"{palette.name}: {swap.name}",
                                     tuple(swapped_colours(palette, swap, base[palette.id])),
                                     tuple(cycles_of(palette, swap))))
    return entries


# ---------------------------------------------------------------------------- for the editor
def new_palette_name(project: Any) -> str:
    """"Palette N" with the first N no palette has."""
    taken = {p.name for p in project.palettes}
    number = 1
    while f"Palette {number}" in taken:
        number += 1
    return f"Palette {number}"


def signature(project: Any) -> Any:
    """Everything about the palettes that decides how art shows (not the image files' contents: callers bump a
    generation when those change)."""
    return (
        getattr(project, "console", ""),
        tuple((p.id, tuple(p.colours or ()), tuple((c.first, c.count, c.frames, c.reverse) for c in p.cycles))
              for p in project.palettes),
        tuple((s.id, tuple((pid, tuple(ch.colours), None if ch.cycles is None else
                            tuple((c.first, c.count, c.frames, c.reverse) for c in ch.cycles))
                           for pid, ch in sorted(s.palettes.items())))
              for s in project.palette_swaps),
        tuple((a.id, a.palette_id, a.file_path, tuple(a.transparent_color or ())) for a in project.images),
    )


def describe(project: Any, palette: Palette) -> Tuple[int, List[str]]:
    """(colours the palette's images use, the images' file names)."""
    names = [os.path.basename(a.file_path) or a.id for a in palette_images(project, palette)]
    return len(palette_usage(project, palette)), names
