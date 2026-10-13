"""Mega Drive colours and palettes (wx-free), shared by the SGDK exporter and the editor's console-colour preview.

A Mega Drive palette line holds 16 colours, the first of them transparent for sprites, with 3 bits per channel (512
colours in all). Every image belongs to one of four palettes (``ImageAsset.palette``, 0–3, shown as Palette 1–4): a
palette holds the 15 colours its images use most, and similar colours merge when they use more. The runtime loads the
palettes into consecutive palette lines, so a sprite's colours come from its image's palette.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

RGB = Tuple[int, int, int]

COLOURS_PER_PALETTE = 15  # plus the transparent index 0
PALETTE_COUNT = 4  # Mega Drive palette lines


def md_level(value: int) -> int:
    """A channel as the console shows it: the top 3 bits, spread over 0–255 (0, 36, 72, ... 255)."""
    return (int(value) >> 5) * 255 // 7


def md_colour(rgb: RGB) -> RGB:
    return md_level(rgb[0]), md_level(rgb[1]), md_level(rgb[2])


def md_word(rgb: RGB) -> int:
    """The colour as a Mega Drive palette (CRAM) word: 0000 BBB0 GGG0 RRR0."""
    return ((int(rgb[2]) >> 5) << 9) | ((int(rgb[1]) >> 5) << 5) | ((int(rgb[0]) >> 5) << 1)


def palette_of(asset) -> int:
    """The image's palette (0–3); anything else counts as the first."""
    value = getattr(asset, "palette", 0)
    return int(value) if isinstance(value, int) and 0 <= value < PALETTE_COUNT else 0


def image_colours(path: str, key: Optional[Sequence[int]]) -> Counter:
    """Visible colours of an image file with their pixel counts; transparent pixels and the key colour take none."""
    from PIL import Image

    counts: Counter = Counter()
    if not path or not os.path.exists(path):
        return counts
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    key_rgb = tuple(int(v) for v in key) if key else None
    for count, (r, g, b, a) in rgba.getcolors(rgba.width * rgba.height) or []:
        if a == 0 or (r, g, b) == key_rgb:
            continue
        counts[(int(r), int(g), int(b))] += int(count)
    return counts


def build_palette(counts: Counter) -> List[RGB]:
    """15 colours for these: all of them when they fit (most used first), else the image quantizer's merge."""
    from PIL import Image

    if not counts:
        return [(255, 255, 255)] + [(0, 0, 0)] * (COLOURS_PER_PALETTE - 1)
    if len(counts) <= COLOURS_PER_PALETTE:
        base = [rgb for rgb, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    else:
        canvas = Image.new("RGB", (len(counts), 1), (0, 0, 0))
        for x, rgb in enumerate(counts.keys()):
            canvas.putpixel((x, 0), rgb)
        raw = canvas.quantize(colors=COLOURS_PER_PALETTE, dither=Image.Dither.NONE).getpalette() or []
        base = [(int(raw[i]), int(raw[i + 1]), int(raw[i + 2])) for i in range(0, min(len(raw), 3 * COLOURS_PER_PALETTE), 3)]
    base = base or [(255, 255, 255)]
    while len(base) < COLOURS_PER_PALETTE:
        base.append(base[-1])
    return base[:COLOURS_PER_PALETTE]


def palette_colours(project, palette: int) -> Counter:
    """The colours of every image in one palette, with pixel counts."""
    counts: Counter = Counter()
    for asset in project.images:
        if palette_of(asset) == palette:
            counts.update(image_colours(asset.file_path, asset.transparent_color))
    return counts


def used_palettes(project) -> List[int]:
    """Palettes that hold images (the first one always counts: vector shapes use it)."""
    return sorted({0} | {palette_of(asset) for asset in project.images})


def project_palettes(project) -> Dict[int, List[RGB]]:
    """Every palette from the first to the last one used (gaps get the first one's colours: their lines are loaded
    too, the runtime loads consecutive lines)."""
    used = used_palettes(project)
    built = {index: build_palette(palette_colours(project, index)) for index in used}
    return {index: built.get(index, built[0]) for index in range(max(used) + 1)}


def nearest(rgb: RGB, palette: Sequence[RGB], cache: Optional[Dict[RGB, int]] = None) -> int:
    """Index (0–14) of the palette colour closest to ``rgb``, as the exporter picks it."""
    if cache is not None and rgb in cache:
        return cache[rgb]
    best, best_dist = 0, None
    for index, colour in enumerate(palette):
        dist = (rgb[0] - colour[0]) ** 2 + (rgb[1] - colour[1]) ** 2 + (rgb[2] - colour[2]) ** 2
        if best_dist is None or dist < best_dist:
            best, best_dist = index, dist
    if cache is not None:
        cache[rgb] = best
    return best


def console_image(rgba, palette: Sequence[RGB]):
    """The image as the Mega Drive shows it with this palette: visible pixels turn fully opaque, take the nearest
    palette colour (as the exporter picks it) and the console's 3 bits per channel. Fast: the image's own colours
    (exact up to 256, which sprite sheets stay under) are remapped, not its pixels."""
    from PIL import Image

    rgba = rgba.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda a: 255 if a else 0)
    indexed = rgba.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
    raw = indexed.getpalette() or []
    shown = [md_colour(colour) for colour in palette]
    cache: Dict[RGB, int] = {}
    remapped: List[int] = []
    for i in range(0, len(raw) - 2, 3):
        remapped.extend(shown[nearest((raw[i], raw[i + 1], raw[i + 2]), palette, cache)])
    indexed.putpalette(remapped)
    out = indexed.convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def describe(project, palette: int) -> Tuple[int, List[str]]:
    """(colours the palette's images use, the images' file names)."""
    names = [os.path.basename(a.file_path) or a.id for a in project.images if palette_of(a) == palette]
    return len(palette_colours(project, palette)), names


def palettes_label(indices: Iterable[int]) -> str:
    return ", ".join(f"Palette {i + 1}" for i in indices)
