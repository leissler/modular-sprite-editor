"""Pixel-exact frame images for every preview (thumbnails, lists, GIF export).

Renders with the RetroAnimator exporter's renderer, which tools/check_export_parity.py keeps identical to
the editor canvas: nested frames, part rotation, shape modules and the preview mapping all come out right.
Results are cached by *content* (the frame's parts, nested frames, modules and mapping), so edits in any tab
show up without anyone having to clear a cache.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Optional, Set, Tuple

import wx

from models import Frame, ModuleMapping, Project, RetroAnimatorExporter as _RA

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
    a = _RA._mat_mul(_RA._rotation_matrix(float(rotation)), _RA._flip_matrix(bool(flip_x), bool(flip_y)))
    b = (float(offset[0]), float(offset[1]))
    if mirror[0] or mirror[1]:
        m = _RA._flip_matrix(bool(mirror[0]), bool(mirror[1]))
        a = _RA._mat_mul(m, a)
        b = _RA._mat_vec_mul(m, b)
    return a, b


def mapping_key(mapping: Optional[ModuleMapping]) -> Any:
    return (mapping.id, tuple(sorted((k, v or "") for k, v in mapping.map.items()))) if mapping else None


def _module_key(project: Project, module_id: str, mapping: Optional[ModuleMapping]) -> Any:
    mod = _RA._resolve_module(project, module_id, mapping)
    if mod is None:
        return None
    asset = project.get_image(mod.image_id) if mod.type == "MD_IMAGE" else None
    return (
        mod.id, mod.type, tuple(mod.rect), tuple(mod.pivot), bool(getattr(mod, "rotated", False)),
        tuple(mod.color) if mod.color else None, tuple(mod.params) if mod.params else None,
        asset.file_path if asset else None,
        tuple(asset.transparent_color) if asset and asset.transparent_color else None,
    )


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
        self._images: Dict[str, Any] = {}  # sheets, by path + key colour
        self._modules: Dict[str, Any] = {}  # cut-out modules, by module id
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
                        self._modules.pop(mod_id, None)
                        self._module_keys[mod_id] = content

    def render(
        self,
        project: Project,
        frame: Frame,
        mapping: Optional[ModuleMapping],
        a: Matrix = IDENTITY,
        b: Tuple[float, float] = (0.0, 0.0),
    ) -> Tuple[Any, int, int]:
        signature = frame_signature(project, frame.id, mapping)
        key = (signature, a, b)
        cached = self._results.get(key)
        if cached is not None:
            self._results.move_to_end(key)
            return cached
        self._forget_changed_modules(project, signature)
        image, hx, hy, _collisions = _RA._render_frame_variant(project, frame, mapping, a, b, self._images, self._modules)
        result = (image, int(hx), int(hy))
        self._results[key] = result
        while len(self._results) > self.max_items:
            self._results.popitem(last=False)
        return result


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


def fit_bitmap(image: Any, width: int, height: int, background: Tuple[int, int, int]) -> wx.Bitmap:
    """Centre an image in a box: whole-number upscaling when it fits, nearest-neighbour down otherwise."""
    from PIL import Image as PILImage

    width, height = max(1, int(width)), max(1, int(height))
    canvas = PILImage.new("RGBA", (width, height), tuple(background) + (255,))
    w, h = image.size
    if w > 1 or h > 1:
        margin = 2
        fit = min((width - margin) / max(1, w), (height - margin) / max(1, h))
        scale = max(1, int(fit)) if fit >= 1 else fit
        tw, th = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        scaled = image.resize((tw, th), PILImage.NEAREST) if (tw, th) != (w, h) else image
        canvas.alpha_composite(scaled, ((width - tw) // 2, (height - th) // 2))
    rgb = canvas.convert("RGB")
    wx_image = wx.Image(width, height)
    wx_image.SetData(rgb.tobytes())
    return wx_image.ConvertToBitmap()
