"""Pixel-exact frame images for every preview (thumbnails, lists, GIF export).

Renders with the compositor (compositor.py, also behind the exports), which tools/check_export_parity.py keeps
identical to the editor canvas: nested frames, part rotation, shape modules and the preview mapping all come out right.
Results are cached by *content* (the frame's parts, nested frames, modules and mapping), so edits in any tab
show up without anyone having to clear a cache.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Optional, Set, Tuple

import wx

import compositor
import palettes
from models import Frame, ImageAsset, Module, ModuleMapping, PaletteSwap, Project

Matrix = Tuple[Tuple[float, float], Tuple[float, float]]
IDENTITY: Matrix = ((1.0, 0.0), (0.0, 1.0))


def transform(
    flip_x: bool = False,
    flip_y: bool = False,
    rotation: float = 0.0,
    offset: Tuple[float, float] = (0.0, 0.0),
    mirror: Tuple[bool, bool] = (False, False),
) -> Tuple[Matrix, Tuple[float, float]]:
    """Frame-level transform (flip, then rotate, then offset), optionally inside a whole-view mirror."""
    a = compositor.mat_mul(compositor.rotation_matrix(float(rotation)), compositor.flip_matrix(bool(flip_x), bool(flip_y)))
    b = (float(offset[0]), float(offset[1]))
    if mirror[0] or mirror[1]:
        m = compositor.flip_matrix(bool(mirror[0]), bool(mirror[1]))
        a = compositor.mat_mul(m, a)
        b = compositor.mat_vec_mul(m, b)
    return a, b


def key_out(image: Any, colour: Optional[Tuple[int, int, int]]) -> Any:
    """Make every pixel of the key colour transparent (same result as the exporter, done in C)."""
    if not colour:
        return image
    from PIL import ImageChops

    rgba = image.convert("RGBA")
    r, g, b, a = rgba.split()
    hits = [band.point([255 if v == int(c) else 0 for v in range(256)]) for band, c in zip((r, g, b), colour)]
    is_key = ImageChops.multiply(ImageChops.multiply(hits[0], hits[1]), hits[2])
    out = rgba.copy()
    out.putalpha(ImageChops.subtract(a, is_key))
    return out


def mapping_key(mapping: Optional[ModuleMapping]) -> Any:
    return (mapping.id, tuple(sorted((k, v or "") for k, v in mapping.map.items()))) if mapping else None


def swap_key(project: Project, swap: Optional[PaletteSwap]) -> Any:
    """What decides how a palette swap recolours (hashable), None for no swap."""
    if swap is None:
        return None
    return (swap.id, tuple((p.id, tuple(p.colours or ()), tuple(palettes.swapped_colours(p, swap)))
                           for p in project.palettes if p.id in swap.palettes))


def _module_key(project: Project, module_id: str, mapping: Optional[ModuleMapping]) -> Any:
    mod = compositor.resolve_module(project, module_id, mapping)
    if mod is None:
        return None
    asset = project.get_image(mod.image_id) if mod.type == "MD_IMAGE" else None
    return (
        mod.id, mod.type, tuple(mod.rect), tuple(mod.pivot), bool(getattr(mod, "rotated", False)),
        tuple(mod.color) if mod.color else None, tuple(mod.params) if mod.params else None,
        asset.file_path if asset else None,
        tuple(asset.transparent_color) if asset and asset.transparent_color else None,
    )


def module_signature(project: Project, module_id: str) -> Any:
    """Everything that decides how a module looks (geometry, pixels source, key colour, shape), hashable."""
    return _module_key(project, module_id, None)


def frame_signature(project: Project, frame_id: str, mapping: Optional[ModuleMapping], _stack: Optional[Set[str]] = None) -> Any:
    """Everything that decides how a frame looks, as a hashable value."""
    frame = project.get_frame(frame_id)
    stack = _stack if _stack is not None else set()
    if frame is None or frame_id in stack or len(stack) > 48:
        return None
    stack.add(frame_id)
    parts = []
    for fm in frame.fmodules:
        if fm.ref_type == "frame":
            content = frame_signature(project, fm.ref_id, mapping, stack)
        else:
            content = _module_key(project, fm.ref_id, mapping)
        parts.append((fm.ref_type, content, tuple(fm.position), bool(fm.flip_x), bool(fm.flip_y), float(fm.rotation_degrees)))
    stack.discard(frame_id)
    return (frame_id, tuple(parts))


class FrameRenderer:
    """Renders frames to PIL images (RGBA + top-left position), cached by content (LRU)."""

    def __init__(self, max_items: int = 2000) -> None:
        self.max_items = max_items
        self._images: Dict[Any, Any] = {}  # sheets, by path + key colour (and a swap's colours)
        self._modules: Dict[Any, Any] = {}  # cut-out modules, by module id (and a swap's colours)
        self._module_keys: Dict[str, Any] = {}
        self._results: "OrderedDict[Any, Tuple[Any, int, int]]" = OrderedDict()

    def clear(self) -> None:
        """Forget everything, e.g. when image files on disk may have changed."""
        self._images.clear()
        self._modules.clear()
        self._module_keys.clear()
        self._results.clear()

    def _forget_changed_modules(self, project: Project, signature: Any) -> None:
        """The exporter caches cut-outs by module id; drop those whose geometry changed."""
        stack = [signature]
        while stack:
            node = stack.pop()
            if not node:
                continue
            for ref_type, content, *_rest in node[1]:
                if ref_type == "frame":
                    stack.append(content)
                elif content is not None:
                    mod_id = content[0]
                    if self._module_keys.get(mod_id) != content:
                        self._forget_module(mod_id)
                        self._module_keys[mod_id] = content

    def _forget_module(self, mod_id: str) -> None:
        """Drop a module's cut-outs, its swapped ones too."""
        for key in [k for k in self._modules if k == mod_id or (isinstance(k, tuple) and k[0] == mod_id)]:
            del self._modules[key]

    def render(
        self,
        project: Project,
        frame: Frame,
        mapping: Optional[ModuleMapping],
        a: Matrix = IDENTITY,
        b: Tuple[float, float] = (0.0, 0.0),
        swap: Optional[PaletteSwap] = None,
    ) -> Tuple[Any, int, int]:
        signature = frame_signature(project, frame.id, mapping)
        key = (signature, swap_key(project, swap), a, b)
        cached = self._results.get(key)
        if cached is not None:
            self._results.move_to_end(key)
            return cached
        self._forget_changed_modules(project, signature)
        image, hx, hy, _collisions = compositor.render_frame(project, frame, mapping, a, b, self._images, self._modules,
                                                             swap)
        result = (image, int(hx), int(hy))
        self._results[key] = result
        while len(self._results) > self.max_items:
            self._results.popitem(last=False)
        return result

    def module(self, project: Project, module: Module, swap: Optional[PaletteSwap] = None) -> Any:
        """A module's pixels (RGBA, key colour removed, packed rotation undone, recoloured by ``swap``), cached by
        content."""
        content = _module_key(project, module.id, None)
        if self._module_keys.get(module.id) != content:
            self._forget_module(module.id)
            self._module_keys[module.id] = content
        return compositor.load_module_rgba(project, module, self._images, self._modules, swap)

    def sheet(self, project: Project, asset: ImageAsset, keyed: bool = True) -> Any:
        """A whole image asset as RGBA (with its key colour removed unless ``keyed`` is False), or None."""
        import os

        from PIL import Image as PILImage

        if not asset or not os.path.exists(asset.file_path):
            return None
        key_colour = tuple(int(c) for c in asset.transparent_color) if (keyed and asset.transparent_color) else None
        cache_key = f"{os.path.abspath(asset.file_path)}|key={key_colour}"
        cached = self._images.get(cache_key)
        if cached is None:
            try:
                cached = key_out(PILImage.open(asset.file_path).convert("RGBA"), key_colour)
            except OSError:
                return None
            self._images[cache_key] = cached
        return cached


# One renderer for all thumbnail users, so every list shares its cache.
SHARED = FrameRenderer()


def to_bitmap(image: Any, scale: float, background: Optional[Tuple[int, int, int]] = None) -> wx.Bitmap:
    """Nearest-neighbour scaled bitmap; keeps transparency unless a background colour is given."""
    from PIL import Image as PILImage

    w, h = image.size
    tw, th = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    scaled = image.resize((tw, th), PILImage.NEAREST) if (tw, th) != (w, h) else image
    if background is not None:
        flat = PILImage.new("RGBA", (tw, th), tuple(background) + (255,))
        flat.alpha_composite(scaled.convert("RGBA"))
        scaled = flat
    return wx.Bitmap.FromBufferRGBA(tw, th, scaled.convert("RGBA").tobytes())


def fit_bitmap(
    image: Any, width: int, height: int, background: Tuple[int, int, int], max_scale: Optional[int] = None
) -> wx.Bitmap:
    """Centre an image in a box: whole-number upscaling when it fits (up to ``max_scale``), nearest-neighbour down otherwise."""
    from PIL import Image as PILImage

    width, height = max(1, int(width)), max(1, int(height))
    canvas = PILImage.new("RGBA", (width, height), tuple(background) + (255,))
    w, h = image.size
    if w > 1 or h > 1:
        margin = 2
        fit = min((width - margin) / max(1, w), (height - margin) / max(1, h))
        scale = max(1, int(fit)) if fit >= 1 else fit
        if max_scale and scale > max_scale:
            scale = max_scale
        tw, th = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        scaled = image.resize((tw, th), PILImage.NEAREST) if (tw, th) != (w, h) else image
        canvas.alpha_composite(scaled, ((width - tw) // 2, (height - th) // 2))
    rgb = canvas.convert("RGB")
    wx_image = wx.Image(width, height)
    wx_image.SetData(rgb.tobytes())
    return wx_image.ConvertToBitmap()


def to_wx_image(image: Any) -> wx.Image:
    """PIL RGBA → wx.Image with alpha (full size, no scaling)."""
    rgba = image.convert("RGBA")
    w, h = rgba.size
    out = wx.Image(w, h)
    out.SetData(rgba.convert("RGB").tobytes())
    out.SetAlpha(rgba.getchannel("A").tobytes())
    return out
