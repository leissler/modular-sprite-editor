"""The colours canvases draw with: View ▸ Console Colours (the art through the export's palettes, as the console shows
it), palette swaps and colour cycles.

One shared state: whether the console view is on, plus a cache of each image as a draw shows it, keyed by the exact
colours (the image's palette, and what the swap, the cycles at that moment and the console view make of them), so
cycle phases that come round again find their picture. ``image_key`` is None when a draw shows the image's own colours;
canvases put it into their cache keys and ask ``image`` / ``colour``.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import palettes
from ui.frame_render import key_out

RGB = Tuple[int, int, int]


class ConsoleColours:
    def __init__(self, max_images: int = 64) -> None:
        self.enabled = False
        self.generation = 0  # bumped when image files change (reload, edited elsewhere)
        self.max_images = max_images
        self._images: "OrderedDict[Any, Any]" = OrderedDict()
        self._bases: Dict[Any, List[RGB]] = {}

    def touch(self) -> None:
        """Image files changed: build every picture again when it is next asked for."""
        self.generation += 1
        self._images.clear()
        self._bases.clear()

    def _base(self, project: Any, palette: Any) -> List[RGB]:
        """The palette's colours as the console holds them (one not built yet takes its images', computed once per
        state of the images)."""
        if palette.colours is not None:
            return palettes.colours_of(project, palette)
        key = (palette.id, self.generation, tuple((a.id, a.file_path, a.palette_id, tuple(a.transparent_color or ()))
                                                  for a in project.images))
        found = self._bases.get(key)
        if found is None:
            found = self._bases[key] = palettes.colours_of(project, palette)
        return found

    def _colours(self, project: Any, palette: Any, swap: Any, frame: Optional[float]) -> Optional[Tuple[List[RGB], List[RGB]]]:
        """(the palette's colours, what this draw shows instead), or None when it shows them as they are."""
        base = self._base(project, palette)
        if not self.enabled and not palettes.recolours(palette, swap, frame, base):
            return None
        return base, palettes.shown_colours(project, palette, swap, frame, self.enabled, base)

    def image_key(self, project: Any, asset: Any, swap: Any = None, frame: Optional[float] = None) -> Any:
        """None when the image shows its own colours in this draw; otherwise a key for the picture it shows."""
        if asset is None:
            return None
        colours = self._colours(project, project.image_palette(asset), swap, frame)
        if colours is None:
            return None
        return (asset.id, asset.file_path, tuple(asset.transparent_color or ()), self.generation, self.enabled,
                tuple(colours[0]), tuple(colours[1]))

    def image(self, project: Any, asset: Any, swap: Any = None, frame: Optional[float] = None) -> Optional[Any]:
        """The whole image as this draw shows it (RGBA; the key colour and empty pixels transparent), or None when it
        shows its own colours (or its file is missing)."""
        key = self.image_key(project, asset, swap, frame)
        if key is None or not asset.file_path or not os.path.exists(asset.file_path):
            return None
        cached = self._images.get(key)
        if cached is not None:
            self._images.move_to_end(key)
            return cached
        from PIL import Image

        base, shown = list(key[5]), list(key[6])
        try:
            with Image.open(asset.file_path) as source:
                rgba = key_out(source.convert("RGBA"), asset.transparent_color)
        except (OSError, ValueError):
            return None
        cached = self._images[key] = palettes.recolour(rgba, base, shown, opaque=self.enabled)
        while len(self._images) > self.max_images:
            self._images.popitem(last=False)
        return cached

    def colour(self, project: Any, rgb: RGB, swap: Any = None, frame: Optional[float] = None) -> RGB:
        """A vector shape's colour in this draw (shapes use the first palette)."""
        colours = self._colours(project, project.default_palette(), swap, frame)
        if colours is None or not colours[0]:
            return rgb
        base, shown = colours
        return tuple(shown[palettes.nearest(tuple(int(v) for v in rgb[:3]), base)])  # type: ignore[return-value]

    def shape_key(self, project: Any, swap: Any = None, frame: Optional[float] = None) -> Any:
        """None when shapes show their own colours in this draw."""
        colours = self._colours(project, project.default_palette(), swap, frame)
        return None if colours is None else (self.enabled, tuple(colours[0]), tuple(colours[1]))


CONSOLE = ConsoleColours()
