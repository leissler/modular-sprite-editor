"""Palette swatches: a palette's slots as the console shows them, sized by the console (``consoles.py``).

``PaletteStrip`` is the small read-only row (inspectors, list rows); the Palettes tab has its own editable grid.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import wx

import consoles
import palettes
from ui.dpi import px

RGB = Tuple[int, int, int]
EMPTY_SLOT = wx.Colour(96, 100, 112)


def hex_colour(rgb: Sequence[int]) -> str:
    return f"#{int(rgb[0]):02X}{int(rgb[1]):02X}{int(rgb[2]):02X}"


def draw_empty_slot(dc: wx.DC, x: int, y: int, size: int) -> None:
    """An empty slot: an outline with a diagonal, so it reads as free, not black."""
    dc.SetBrush(wx.TRANSPARENT_BRUSH)
    dc.SetPen(wx.Pen(EMPTY_SLOT))
    dc.DrawRectangle(x, y, size, size)
    dc.DrawLine(x + 1, y + size - 2, x + size - 1, y)


class PaletteStrip(wx.Panel):
    """A palette's slots in a row as the console shows them: its colours, then its free slots."""

    def __init__(self, parent: wx.Window, swatch: int = 11, on_click: Optional[Callable[[], None]] = None):
        self.swatch = px(swatch)
        self.slots = consoles.DEFAULT.palette.visible
        super().__init__(parent, size=self._size())
        self.colours: List[RGB] = []
        self.on_click = on_click
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        if on_click is not None:
            self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
            self.Bind(wx.EVT_LEFT_UP, lambda e: self.on_click and self.on_click())

    def _size(self) -> Tuple[int, int]:
        return (self.slots * (self.swatch + 1) + 1, self.swatch + 2)

    def set_palette(self, colours: Sequence[RGB], spec: consoles.PaletteHardware, name: str = "") -> None:
        """Show these colours as ``spec``'s console shows them, in a strip as long as its palettes."""
        if spec.visible != self.slots:
            self.slots = spec.visible
            self.SetMinSize(self._size())
            self.SetSize(self._size())
        self.colours = [palettes.console_colour(spec, c) for c in colours][:self.slots]
        used = len(self.colours)
        tip = f"{name}: " if name else ""
        tip += f"{used} of {self.slots} colours" + (": " + " ".join(hex_colour(c) for c in self.colours) if used else "")
        if self.on_click is not None:
            tip += "\nClick to edit the palette in the Palettes tab."
        self.SetToolTip(tip)
        self.Refresh()

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        for index in range(self.slots):
            x = index * (self.swatch + 1)
            if index < len(self.colours):
                dc.SetPen(wx.Pen(wx.Colour(30, 30, 34)))
                dc.SetBrush(wx.Brush(wx.Colour(*self.colours[index])))
                dc.DrawRectangle(x, 0, self.swatch + 1, self.swatch + 1)
            else:
                draw_empty_slot(dc, x, 0, self.swatch + 1)
