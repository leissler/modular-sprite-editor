"""PalettePreview: one of a palette's images as a draw shows it (the selected palette swap, colour cycles turning), with
the pixels of the selected slots picked out; a click selects the slot of the pixel under the mouse."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

import palettes
from models import ImageAsset, PaletteSwap, Project
from ui.base_canvas import BaseCanvas
from ui.console_colours import CONSOLE
from ui.frame_render import SHARED, to_wx_image

RGB = Tuple[int, int, int]


class PalettePreview(BaseCanvas):
    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        self.zoom = 2.0
        self.min_zoom = 0.25
        self.max_zoom = 32.0
        self.show_grid = False
        self.project: Optional[Project] = None
        self.asset: Optional[ImageAsset] = None
        self.swap: Optional[PaletteSwap] = None
        self.frame: Optional[float] = None
        self.highlight: List[int] = []
        self.on_pick: Optional[Callable[[int], None]] = None
        self._image: Optional[wx.Image] = None
        self._image_key: Any = None
        self._scaled: Optional[Tuple[Any, wx.Bitmap]] = None
        self._slots: Dict[Any, Any] = {}  # (image, colours) -> image of slot numbers ("L", 0 = transparent)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)

    def show(self, project: Project, asset: Optional[ImageAsset], swap: Optional[PaletteSwap],
             frame: Optional[float], highlight: Sequence[int]) -> None:
        self.project, self.asset, self.swap, self.frame = project, asset, swap, frame
        self.highlight = list(highlight)
        key = self._key()
        if key != self._image_key:
            self._image_key = key
            self._image = self._build()
            self._scaled = None
        self.Refresh(False)

    def forget(self) -> None:
        """Image files changed: build everything again."""
        self._image_key = None
        self._slots.clear()

    # ------------------------------------------------------------------ the picture
    def _base(self) -> List[RGB]:
        return palettes.colours_of(self.project, self.project.image_palette(self.asset)) if self.asset else []

    def _key(self) -> Any:
        if self.project is None or self.asset is None:
            return None
        return (self.asset.id, CONSOLE.image_key(self.project, self.asset, self.swap, self.frame), tuple(self.highlight),
                tuple(self._base()), CONSOLE.generation)

    def _slot_image(self, rgba: Any, base: Sequence[RGB]) -> Any:
        """The slot number (1-based, 0 transparent) of every pixel, as palettes.nearest picks it."""
        from PIL import Image

        key = (self.asset.id if self.asset else "", rgba.size, tuple(base), CONSOLE.generation)
        found = self._slots.get(key)
        if found is not None:
            return found
        alpha = rgba.getchannel("A")
        indexed = rgba.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
        raw = indexed.getpalette() or []
        cache: Dict[RGB, int] = {}
        lut = [palettes.nearest((raw[i], raw[i + 1], raw[i + 2]), base, cache) + 1 if base else 0
               for i in range(0, len(raw) - 2, 3)]
        lut += [0] * (256 - len(lut))
        slots = Image.frombytes("L", indexed.size, indexed.tobytes().translate(bytes(lut[:256])))
        slots.paste(0, mask=alpha.point(lambda a: 255 if a == 0 else 0))
        if len(self._slots) > 16:
            self._slots.clear()
        self._slots[key] = slots
        return slots

    def _build(self) -> Optional[wx.Image]:
        if self.project is None or self.asset is None:
            return None
        shown = CONSOLE.image(self.project, self.asset, self.swap, self.frame)
        if shown is None:
            shown = SHARED.sheet(self.project, self.asset, keyed=True)
        if shown is None:
            return None
        if self.highlight:  # the pixels of the selected slots stay, the rest dims
            from PIL import Image

            keyed = SHARED.sheet(self.project, self.asset, keyed=True)
            slots = self._slot_image(keyed, self._base())
            wanted = {s + 1 for s in self.highlight}
            mask = slots.point(lambda v: 255 if v in wanted else 0)
            dim = Image.blend(shown.convert("RGBA"), Image.new("RGBA", shown.size, (24, 25, 28, 255)), 0.5)
            dim.putalpha(shown.getchannel("A"))
            shown = Image.composite(shown.convert("RGBA"), dim, mask)
        return to_wx_image(shown)

    def slot_at(self, pos: wx.Point) -> Optional[int]:
        """The palette slot (0-based) of the pixel under the mouse, None for a transparent one."""
        if self.project is None or self.asset is None:
            return None
        keyed = SHARED.sheet(self.project, self.asset, keyed=True)
        if keyed is None:
            return None
        x, y = self.screen_to_world(pos)
        ix, iy = int(x // 1), int(y // 1)
        if not (0 <= ix < keyed.width and 0 <= iy < keyed.height):
            return None
        value = self._slot_image(keyed, self._base()).getpixel((ix, iy))
        return value - 1 if value else None

    # ------------------------------------------------------------------ canvas
    def get_content_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        if self._image is None:
            return None
        return (0.0, 0.0, float(self._image.GetWidth()), float(self._image.GetHeight()))

    def on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.draw_backdrop(dc)
        if self._image is None:
            return
        gc = wx.GraphicsContext.Create(dc)
        cw, ch = self.GetClientSize()
        wx0, wy0 = self.screen_to_world(wx.Point(0, 0))
        wx1, wy1 = self.screen_to_world(wx.Point(cw, ch))
        iw, ih = self._image.GetWidth(), self._image.GetHeight()
        vx0, vy0 = max(0, int(wx0)), max(0, int(wy0))
        vx1, vy1 = min(iw, int(wx1) + 1), min(ih, int(wy1) + 1)
        if vx1 <= vx0 or vy1 <= vy0:
            return
        tw, th = int(round((vx1 - vx0) * self.zoom)), int(round((vy1 - vy0) * self.zoom))
        if tw <= 0 or th <= 0:
            return
        key = (self._image_key, vx0, vy0, vx1, vy1, tw, th)
        if self._scaled is None or self._scaled[0] != key:
            sub = self._image.GetSubImage(wx.Rect(vx0, vy0, vx1 - vx0, vy1 - vy0))
            sub.Rescale(tw, th, wx.IMAGE_QUALITY_NEAREST)
            self._scaled = (key, sub.ConvertToBitmap())
        sx, sy = self.world_to_screen((vx0, vy0))
        gc.DrawBitmap(self._scaled[1], round(sx), round(sy), tw, th)
        x0, y0 = self.world_to_screen((0, 0))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(self.overlay_colour("canvas_faint", 160), 1))
        gc.DrawRectangle(x0 - 0.5, y0 - 0.5, iw * self.zoom + 1, ih * self.zoom + 1)

    # ------------------------------------------------------------------ mouse
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        if self.begin_pan_if_requested(event):
            return
        self.SetFocus()
        slot = self.slot_at(event.GetPosition())
        if slot is not None and self.on_pick:
            self.on_pick(slot)

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
            self.on_pan_end(event)
            return
        event.Skip()
