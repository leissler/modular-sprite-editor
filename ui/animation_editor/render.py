"""Step images for the Animations tab (thumbnails, list icons, GIF export), via the shared frame renderer."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import wx

from models import AFrame, Animation, ModuleMapping, PaletteSwap, Project
from ui.animation_editor import ops
from ui.frame_render import SHARED, FrameRenderer, fit_bitmap, frame_signature, mapping_key, swap_key, transform

Matrix = Tuple[Tuple[float, float], Tuple[float, float]]


def step_affine(af: AFrame, mirror_x: bool = False, mirror_y: bool = False, with_offset: bool = True) -> Tuple[Matrix, Tuple[float, float]]:
    """Step transform (flip, then rotate, then offset), optionally inside a whole-view mirror."""
    offset = (float(af.offset[0]), float(af.offset[1])) if with_offset else (0.0, 0.0)
    return transform(af.flip_x, af.flip_y, af.rotation_degrees, offset, (mirror_x, mirror_y))


class StepRenderer:
    """Renders animation steps (content-cached through the shared FrameRenderer) and their thumbnails."""

    def __init__(self, frames: Optional[FrameRenderer] = None) -> None:
        self.frames = frames or SHARED
        self._bitmaps: Dict[Tuple[Any, ...], wx.Bitmap] = {}
        self._layouts: Dict[Tuple[Any, ...], Tuple[int, int, float, int, int]] = {}

    def clear(self) -> None:
        self._bitmaps.clear()
        self._layouts.clear()

    def render(
        self,
        project: Project,
        af: AFrame,
        mapping: Optional[ModuleMapping],
        mirror: Tuple[bool, bool] = (False, False),
        with_offset: bool = True,
        swap: Optional[PaletteSwap] = None,
    ) -> Tuple[Any, int, int]:
        """(RGBA image, x, y): the step's pixels (recoloured by ``swap``) and where their top-left lands in animation
        space."""
        frame = project.get_frame(af.frame_id)
        if frame is None:
            from PIL import Image as PILImage

            return (PILImage.new("RGBA", (1, 1), (0, 0, 0, 0)), 0, 0)
        a, b = step_affine(af, mirror[0], mirror[1], with_offset)
        return self.frames.render(project, frame, mapping, a, b, swap)

    def thumbnail(
        self,
        project: Project,
        af: AFrame,
        mapping: Optional[ModuleMapping],
        size: int,
        background: Tuple[int, int, int] = (50, 50, 50),
        swap: Optional[PaletteSwap] = None,
    ) -> wx.Bitmap:
        """Square thumbnail of a step's frame with its flip/rotation (no offset), pixel-art scaled."""
        key = (frame_signature(project, af.frame_id, mapping), bool(af.flip_x), bool(af.flip_y),
               int(round(af.rotation_degrees)) % 360, mapping_key(mapping), swap_key(project, swap), int(size), background)
        bmp = self._bitmaps.get(key)
        if bmp is None:
            image, _x, _y = self.render(project, af, mapping, with_offset=False, swap=swap)
            bmp = fit_bitmap(image, size, size, background)
            if len(self._bitmaps) > 3000:
                self._bitmaps.clear()
            self._bitmaps[key] = bmp
        return bmp


    @staticmethod
    def _step_key(project: Project, af: AFrame, mapping: Optional[ModuleMapping]) -> Tuple[Any, ...]:
        return (frame_signature(project, af.frame_id, mapping), bool(af.flip_x), bool(af.flip_y),
                int(round(af.rotation_degrees)) % 360)

    def strip_layout(
        self, project: Project, anim: Animation, mapping: Optional[ModuleMapping], size: int,
        swap: Optional[PaletteSwap] = None,
    ) -> Tuple[int, int, float, int, int]:
        """(x0, y0, scale, left, top): one scale and one origin for every step of an animation.

        Fitting each step on its own would zoom a slightly smaller pose 2× and its neighbour 1×; with a shared
        layout the strip shows real size differences and how the pose moves around the frame origin.
        """
        key = (tuple(self._step_key(project, af, mapping) for af in anim.aframes), mapping_key(mapping), int(size))
        layout = self._layouts.get(key)
        if layout is not None:
            return layout
        boxes = []
        for af in anim.aframes:
            image, x, y = self.render(project, af, mapping, with_offset=False, swap=swap)
            if image.getbbox():
                boxes.append((x, y, x + image.size[0], y + image.size[1]))
        if not boxes:
            layout = (0, 0, 1.0, 0, 0)
        else:
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            w = max(1, max(b[2] for b in boxes) - x0)
            h = max(1, max(b[3] for b in boxes) - y0)
            fit = min((size - 2) / w, (size - 2) / h)
            scale = float(max(1, int(fit))) if fit >= 1 else fit
            layout = (x0, y0, scale, int((size - w * scale) // 2), int((size - h * scale) // 2))
        if len(self._layouts) > 500:
            self._layouts.clear()
        self._layouts[key] = layout
        return layout

    def strip_thumbnail(
        self,
        project: Project,
        anim: Animation,
        index: int,
        mapping: Optional[ModuleMapping],
        size: int,
        background: Tuple[int, int, int] = (50, 50, 50),
        layout: Optional[Tuple[int, int, float, int, int]] = None,
        swap: Optional[PaletteSwap] = None,
    ) -> wx.Bitmap:
        """A step's thumbnail in its animation's shared layout (same scale and origin for every step).

        Pass the strip_layout() when drawing many steps at once: working it out looks at every step.
        """
        from PIL import Image as PILImage

        af = anim.aframes[index]
        if layout is None:
            layout = self.strip_layout(project, anim, mapping, size, swap)
        key = ("strip",) + self._step_key(project, af, mapping) + (mapping_key(mapping), swap_key(project, swap), int(size),
                                                                   background, layout)
        bmp = self._bitmaps.get(key)
        if bmp is None:
            x0, y0, scale, left, top = layout
            image, x, y = self.render(project, af, mapping, with_offset=False, swap=swap)
            canvas = PILImage.new("RGBA", (int(size), int(size)), tuple(background) + (255,))
            if image.getbbox():
                tw, th = max(1, int(round(image.size[0] * scale))), max(1, int(round(image.size[1] * scale)))
                scaled = image.resize((tw, th), PILImage.NEAREST) if (tw, th) != image.size else image
                canvas.alpha_composite(scaled, (left + int(round((x - x0) * scale)), top + int(round((y - y0) * scale))))
            rgb = canvas.convert("RGB")
            wx_image = wx.Image(int(size), int(size))
            wx_image.SetData(rgb.tobytes())
            bmp = wx_image.ConvertToBitmap()
            if len(self._bitmaps) > 3000:
                self._bitmaps.clear()
            self._bitmaps[key] = bmp
        return bmp


def export_gif(
    project: Project,
    anim: Animation,
    path: str,
    mapping: Optional[ModuleMapping],
    mirror: Tuple[bool, bool] = (False, False),
    scale: int = 1,
    swap: Optional[PaletteSwap] = None,
) -> int:
    """Write one cycle of the animation (in its playback order, recoloured by ``swap``) to an animated GIF. Returns the
    frame count."""
    from PIL import Image as PILImage

    renderer = StepRenderer()
    rendered: List[Tuple[Any, int, int, int]] = []
    for index in cycle_order(anim):
        af = anim.aframes[index]
        image, x, y = renderer.render(project, af, mapping, mirror, swap=swap)
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
