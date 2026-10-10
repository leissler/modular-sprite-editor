"""Pixel-exact step images for thumbnails and GIF export.

Uses the RetroAnimator exporter's renderer, which tools/check_export_parity.py keeps identical to the
editor canvas, so nested frames, part rotation, shape modules and the preview mapping all show correctly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import wx

from models import AFrame, Animation, ModuleMapping, Project, RetroAnimatorExporter as _RA
from ui.animation_editor import ops

Matrix = Tuple[Tuple[float, float], Tuple[float, float]]


def step_affine(af: AFrame, mirror_x: bool = False, mirror_y: bool = False, with_offset: bool = True) -> Tuple[Matrix, Tuple[float, float]]:
    """Step transform (flip, then rotate, then offset), optionally inside a whole-view mirror."""
    a = _RA._mat_mul(_RA._rotation_matrix(float(af.rotation_degrees)), _RA._flip_matrix(bool(af.flip_x), bool(af.flip_y)))
    b = (float(af.offset[0]), float(af.offset[1])) if with_offset else (0.0, 0.0)
    if mirror_x or mirror_y:
        m = _RA._flip_matrix(mirror_x, mirror_y)
        a = _RA._mat_mul(m, a)
        b = _RA._mat_vec_mul(m, b)
    return a, b


class StepRenderer:
    """Renders steps to PIL images, caching sheets, modules and finished images."""

    def __init__(self) -> None:
        self._images: Dict[str, Any] = {}
        self._modules: Dict[str, Any] = {}
        self._steps: Dict[Tuple[Any, ...], Tuple[Any, int, int]] = {}
        self._bitmaps: Dict[Tuple[Any, ...], wx.Bitmap] = {}

    def clear(self) -> None:
        """Forget everything (frames, modules or images may have changed)."""
        self._images.clear()
        self._modules.clear()
        self._steps.clear()
        self._bitmaps.clear()

    @staticmethod
    def _mapping_key(mapping: Optional[ModuleMapping]) -> Any:
        return (mapping.id, tuple(sorted((k, v or "") for k, v in mapping.map.items()))) if mapping else None

    def render(
        self,
        project: Project,
        af: AFrame,
        mapping: Optional[ModuleMapping],
        mirror: Tuple[bool, bool] = (False, False),
        with_offset: bool = True,
    ) -> Tuple[Any, int, int]:
        """(RGBA image, x, y): the step's pixels and where their top-left lands in animation space."""
        key = (
            af.frame_id, bool(af.flip_x), bool(af.flip_y), int(round(af.rotation_degrees)) % 360,
            tuple(af.offset) if with_offset else None, mirror, self._mapping_key(mapping),
        )
        cached = self._steps.get(key)
        if cached is not None:
            return cached
        frame = project.get_frame(af.frame_id)
        if frame is None:
            from PIL import Image as PILImage

            result = (PILImage.new("RGBA", (1, 1), (0, 0, 0, 0)), 0, 0)
        else:
            a, b = step_affine(af, mirror[0], mirror[1], with_offset)
            image, hx, hy, _collisions = _RA._render_frame_variant(project, frame, mapping, a, b, self._images, self._modules)
            result = (image, int(hx), int(hy))
        self._steps[key] = result
        return result

    def thumbnail(
        self,
        project: Project,
        af: AFrame,
        mapping: Optional[ModuleMapping],
        size: int,
        background: Tuple[int, int, int] = (50, 50, 50),
    ) -> wx.Bitmap:
        """Square thumbnail of a step's frame with its flip/rotation (no offset), pixel-art scaled."""
        key = (af.frame_id, bool(af.flip_x), bool(af.flip_y), int(round(af.rotation_degrees)) % 360,
               self._mapping_key(mapping), int(size), background)
        bmp = self._bitmaps.get(key)
        if bmp is not None:
            return bmp
        image, _x, _y = self.render(project, af, mapping, with_offset=False)
        bmp = fit_bitmap(image, size, size, background)
        self._bitmaps[key] = bmp
        return bmp


def fit_bitmap(image: Any, width: int, height: int, background: Tuple[int, int, int]) -> wx.Bitmap:
    """Centre an RGBA image in a box: whole-number upscaling when it fits, nearest-neighbour down otherwise."""
    from PIL import Image as PILImage

    width, height = max(1, int(width)), max(1, int(height))
    canvas = PILImage.new("RGBA", (width, height), background + (255,))
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


def export_gif(
    project: Project,
    anim: Animation,
    path: str,
    mapping: Optional[ModuleMapping],
    mirror: Tuple[bool, bool] = (False, False),
    scale: int = 1,
) -> int:
    """Write one cycle of the animation (in its playback order) to an animated GIF. Returns the frame count."""
    from PIL import Image as PILImage

    renderer = StepRenderer()
    rendered: List[Tuple[Any, int, int, int]] = []
    for index in cycle_order(anim):
        af = anim.aframes[index]
        image, x, y = renderer.render(project, af, mapping, mirror)
        rendered.append((image, x, y, ops.hold(af)))
    if not rendered:
        return 0
    min_x = min(x for _img, x, _y, _t in rendered)
    min_y = min(y for _img, _x, y, _t in rendered)
    max_x = max(x + img.size[0] for img, x, _y, _t in rendered)
    max_y = max(y + img.size[1] for img, _x, y, _t in rendered)
    width, height = max(1, max_x - min_x), max(1, max_y - min_y)
    frames: List[Any] = []
    durations: List[int] = []
    tick_ms = 1000.0 / float(ops.tick_rate(anim))
    for image, x, y, ticks in rendered:
        canvas = PILImage.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.alpha_composite(image, (x - min_x, y - min_y))
        if scale > 1:
            canvas = canvas.resize((width * scale, height * scale), PILImage.NEAREST)
        frames.append(canvas)
        durations.append(max(10, int(round(ticks * tick_ms))))
    options: Dict[str, Any] = {}
    if anim.playback_type in ops.REPEATING_MODES:
        options["loop"] = max(0, int(anim.loop_count or 0))  # 0 = forever
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, disposal=2, **options)
    return len(frames)


def cycle_order(anim: Animation) -> List[int]:
    """Step indices of one playback cycle: backwards for "Loop backwards", there and back for ping-pong."""
    count = len(anim.aframes)
    forward = list(range(count))
    if anim.playback_type == "backward":
        return forward[::-1]
    if anim.playback_type == "ping_pong" and count > 2:
        return forward + forward[-2:0:-1]
    return forward
