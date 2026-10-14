"""Palettes tab operations (wx-free): palettes, palette swaps and colour cycles as the editor changes them.

A palette's colours come from its images: slots their pixels use exactly stay as they are (recolour with a swap);
free slots and slots no pixel uses can take any colour, snapped to what the console can show. The project's console
decides how many colours a palette holds and which colours it can show.
"""

from __future__ import annotations

import copy
from typing import List, Optional, Sequence, Tuple

import consoles
import palettes
from models import ColourCycle, Palette, PaletteChange, PaletteSwap, Project, generate_id

RGB = Tuple[int, int, int]


# ---------------------------------------------------------------------------- the console
def longer_palettes(project: Project, console_key: str) -> List[Palette]:
    """Palettes that store more colours than a palette of this console holds."""
    room = consoles.console_by_key(console_key).palette.visible
    return [p for p in project.palettes if p.colours is not None and len(p.colours) > room]


def set_console(project: Project, console_key: str, keep_most_used: bool = False) -> int:
    """Make the project's palettes follow another console. ``keep_most_used`` fits palettes that store more colours
    than it shows to its palette size (each keeps the colours its images use most); otherwise the console shows their
    first colours and the others wait. Returns how many slots went."""
    project.console = consoles.console_by_key(console_key).key
    if not keep_most_used:
        return 0
    return sum(palettes.keep_most_used(project, palette) for palette in palettes.over_capacity(project))


# ---------------------------------------------------------------------------- palettes
def new_palette(project: Project) -> Palette:
    palette = Palette(id=generate_id("pal"), name=palettes.new_palette_name(project), colours=[])
    project.palettes.append(palette)
    return palette


def duplicate_palette(project: Project, palette: Palette) -> Palette:
    """A copy with the same colours and cycles (no images use it yet)."""
    copied = Palette(id=generate_id("pal"), name=_copy_name(palette.name, {p.name for p in project.palettes}),
                     colours=palettes.stored_colours(project, palette), cycles=copy.deepcopy(palette.cycles))
    project.palettes.insert(project.palettes.index(palette) + 1, copied)
    return copied


def palette_uses(project: Project, palette: Palette) -> Tuple[int, int]:
    """(images in the palette, swaps that change it)."""
    images = sum(1 for a in project.images if project.image_palette(a).id == palette.id)
    swaps = sum(1 for s in project.palette_swaps if palette.id in s.palettes)
    return images, swaps


def delete_palette(project: Project, palette: Palette) -> Optional[Palette]:
    """Remove a palette: its images go into the first palette left (the colours it lacks into free slots), swaps
    forget what they changed in it. The last palette stays. Returns the palette the images went into."""
    if len(project.palettes) <= 1 or palette not in project.palettes:
        return None
    project.palettes.remove(palette)
    target = project.palettes[0]
    moved = False
    for asset in project.images:
        if asset.palette_id == palette.id:
            asset.palette_id = target.id
            moved = True
    for swap in project.palette_swaps:
        swap.palettes.pop(palette.id, None)
    if moved:
        palettes.add_missing_colours(project, target)
    return target


def move_palette(project: Project, palette_id: str, before_id: Optional[str]) -> None:
    """Put a palette before another (None: at the end): the order of the export's palette lines."""
    palette = project.get_palette(palette_id)
    if palette is None or palette_id == before_id:
        return
    project.palettes.remove(palette)
    before = project.get_palette(before_id) if before_id else None
    project.palettes.insert(project.palettes.index(before) if before else len(project.palettes), palette)


def snapped(project: Project, rgb: Sequence[int]) -> RGB:
    """A colour as the project's console shows it (what a picked colour turns into)."""
    return palettes.console_colour(palettes.hardware(project), rgb)


def art_slots(project: Project, palette: Palette) -> List[int]:
    """Slots whose colour pixels of the palette's images have exactly (the art decides those)."""
    used = set(palettes.palette_usage(project, palette))
    return [slot for slot, rgb in enumerate(palette.colours or []) if rgb in used]


def add_colour(project: Project, palette: Palette, rgb: Sequence[int]) -> Optional[int]:
    """Append a colour (snapped) to a free slot; its slot, or None when the palette is full."""
    if palette.colours is None:
        palette.colours = palettes.colours_of(project, palette)
    if len(palette.colours) >= palettes.capacity(project):
        return None
    palette.colours.append(snapped(project, rgb))
    return len(palette.colours) - 1


def set_colour(project: Project, palette: Palette, slot: int, rgb: Sequence[int]) -> bool:
    """Give a slot no pixel uses another colour (snapped). Slots of the art stay: recolour those with a swap."""
    colours = palette.colours or []
    if not 0 <= slot < len(colours) or slot in art_slots(project, palette):
        return False
    colours[slot] = snapped(project, rgb)
    return True


# ---------------------------------------------------------------------------- swaps
def new_swap(project: Project) -> PaletteSwap:
    swap = PaletteSwap(id=generate_id("swap"), name=_free_name("Palette swap", {s.name for s in project.palette_swaps}))
    project.palette_swaps.append(swap)
    return swap


def duplicate_swap(project: Project, swap: PaletteSwap) -> PaletteSwap:
    copied = PaletteSwap(id=generate_id("swap"), name=_copy_name(swap.name, {s.name for s in project.palette_swaps}),
                         palettes=copy.deepcopy(swap.palettes))
    project.palette_swaps.insert(project.palette_swaps.index(swap) + 1, copied)
    return copied


def swap_uses(project: Project, swap: PaletteSwap) -> int:
    """Scene objects that choose this swap."""
    return sum(1 for scene in project.timeline_scenes for obj in scene.objects if obj.palette_swap_id == swap.id)


def delete_swap(project: Project, swap: PaletteSwap) -> int:
    """Remove a swap; scene objects that chose it inherit theirs again. Returns how many objects that was."""
    if swap not in project.palette_swaps:
        return 0
    project.palette_swaps.remove(swap)
    if project.active_palette_swap is swap:
        project.active_palette_swap = None
    changed = 0
    for scene in project.timeline_scenes:
        for obj in scene.objects:
            if obj.palette_swap_id == swap.id:
                obj.palette_swap_id = None
                changed += 1
    return changed


def move_swap(project: Project, swap_id: str, before_id: Optional[str]) -> None:
    swap = project.get_palette_swap(swap_id)
    if swap is None or swap_id == before_id:
        return
    project.palette_swaps.remove(swap)
    before = project.get_palette_swap(before_id) if before_id else None
    project.palette_swaps.insert(project.palette_swaps.index(before) if before else len(project.palette_swaps), swap)


def replacement(swap: PaletteSwap, palette: Palette, slot: int) -> Optional[RGB]:
    change = swap.palettes.get(palette.id)
    if change is None or slot >= len(change.colours):
        return None
    return change.colours[slot]


def set_replacement(project: Project, swap: PaletteSwap, palette: Palette, slot: int,
                    rgb: Optional[Sequence[int]]) -> None:
    """What a slot shows under the swap (snapped); None keeps the palette's colour."""
    change = swap.palettes.setdefault(palette.id, PaletteChange())
    if rgb is not None:
        while len(change.colours) <= slot:
            change.colours.append(None)
        change.colours[slot] = snapped(project, rgb)
    elif slot < len(change.colours):
        change.colours[slot] = None
    palettes.trim(change.colours)
    _drop_if_empty(swap, palette)


def changed_slots(swap: PaletteSwap, palette: Palette) -> List[int]:
    change = swap.palettes.get(palette.id)
    return [slot for slot, rgb in enumerate(change.colours) if rgb is not None] if change else []


def _drop_if_empty(swap: PaletteSwap, palette: Palette) -> None:
    change = swap.palettes.get(palette.id)
    if change is not None and not any(rgb is not None for rgb in change.colours) and change.cycles is None:
        del swap.palettes[palette.id]


# ---------------------------------------------------------------------------- colour cycles
def cycles_owner(swap: Optional[PaletteSwap], palette: Palette) -> List[ColourCycle]:
    """The cycle list an edit changes: the palette's, or the swap's own for this palette (made on first use)."""
    if swap is None:
        return palette.cycles
    change = swap.palettes.setdefault(palette.id, PaletteChange())
    if change.cycles is None:
        change.cycles = copy.deepcopy(palette.cycles)
    return change.cycles


def own_cycles(swap: Optional[PaletteSwap], palette: Palette) -> bool:
    """Whether the swap runs cycles of its own for this palette."""
    change = swap.palettes.get(palette.id) if swap is not None else None
    return change is not None and change.cycles is not None


def follow_palette_cycles(swap: PaletteSwap, palette: Palette) -> None:
    """The swap runs the palette's cycles again."""
    change = swap.palettes.get(palette.id)
    if change is not None:
        change.cycles = None
        _drop_if_empty(swap, palette)


def add_cycle(project: Project, swap: Optional[PaletteSwap], palette: Palette, slots: Sequence[int],
              frames: int = 8) -> Optional[ColourCycle]:
    """A cycle over the run of slots from the lowest to the highest selected one (at least two)."""
    if not slots:
        return None
    first, last = min(slots), max(slots)
    if last <= first or last >= len(palettes.colours_of(project, palette)):
        return None
    cycle = ColourCycle(first=first + 1, count=last - first + 1, frames=max(1, int(frames)))
    cycles_owner(swap, palette).append(cycle)
    return cycle


def remove_cycle(swap: Optional[PaletteSwap], palette: Palette, index: int) -> None:
    owner = cycles_owner(swap, palette)
    if 0 <= index < len(owner):
        del owner[index]


# ---------------------------------------------------------------------------- names
def _free_name(base: str, taken: set) -> str:
    if base not in taken:
        return base
    number = 2
    while f"{base} {number}" in taken:
        number += 1
    return f"{base} {number}"


def _copy_name(name: str, taken: set) -> str:
    return _free_name(f"{name} copy", taken)
