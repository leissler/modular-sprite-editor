"""View ▸ Mega Drive Colours: the canvases show the art as the console will, through the export's palettes.

One shared state: whether the view is on, and the console version of each image (rebuilt when an image's palette, key
colour or file changes). Canvases put ``state(project)`` into their cache keys and ask ``image`` / ``colour``.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import palettes
from ui.frame_render import key_out

RGB = Tuple[int, int, int]


class ConsoleColours:
    def __init__(self) -> None:
        self.enabled = False
        self.generation = 0  # bumped when image files change (reload, edited elsewhere)
        self._built_for: Any = None
        self._palettes: Dict[int, List[RGB]] = {}
        self._images: Dict[str, Any] = {}

    def touch(self) -> None:
        """Image files changed: rebuild the palettes and console images when they are next asked for."""
        self.generation += 1

    def state(self, project: Any) -> Any:
        """None while the view is off; otherwise a key that changes whenever what it shows can change."""
        if not self.enabled:
            return None
        return self.generation, tuple(
            (a.id, palettes.palette_of(a), tuple(a.transparent_color or ())) for a in project.images
        )

    def _refresh(self, project: Any) -> None:
        state = self.state(project)
        if state != self._built_for:
            self._built_for = state
            self._palettes = palettes.project_palettes(project)
            self._images = {}

    def palette(self, project: Any, index: int) -> List[RGB]:
        self._refresh(project)
        return self._palettes.get(index) or self._palettes.get(0) or []

    def image(self, project: Any, asset: Any) -> Optional[Any]:
        """The whole image as the console shows it (RGBA; the key colour and empty pixels transparent)."""
        if not asset or not asset.file_path or not os.path.exists(asset.file_path):
            return None
        self._refresh(project)
        cached = self._images.get(asset.id)
        if cached is None:
            from PIL import Image

            with Image.open(asset.file_path) as source:
                rgba = key_out(source.convert("RGBA"), asset.transparent_color)
            cached = self._images[asset.id] = palettes.console_image(rgba, self.palette(project, palettes.palette_of(asset)))
        return cached

    def colour(self, project: Any, rgb: RGB) -> RGB:
        """A vector shape's colour on the console (shapes use the first palette)."""
        palette = self.palette(project, 0)
        return palettes.md_colour(palette[palettes.nearest(tuple(int(v) for v in rgb[:3]), palette)]) if palette else rgb


CONSOLE = ConsoleColours()
