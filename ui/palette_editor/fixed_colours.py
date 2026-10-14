"""FixedColourDialog: pick one of a console's fixed colours (the NES's 64, the Game Boy's four shades) instead of any
colour: a palette on those consoles holds entries of that list, not colours of its own."""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

import wx

import palettes
from ui.components.palette_swatches import hex_colour
from ui.dpi import px

RGB = Tuple[int, int, int]


class FixedColourGrid(wx.Panel):
    """The colours in hardware order, 16 to a row (the NES's four rows of brightness)."""

    def __init__(self, parent: wx.Window, colours: Sequence[RGB], selected: int):
        super().__init__(parent)
        self.colours = list(colours)
        self.selected = selected
        self.on_select: Optional[Callable[[int], None]] = None
        self.columns = min(16, len(self.colours))
        self.swatch = px(26 if len(self.colours) <= 16 else 22)
        self.gap = px(3)
        rows = (len(self.colours) + self.columns - 1) // self.columns
        self.SetMinSize((self.columns * (self.swatch + self.gap) + self.gap, rows * (self.swatch + self.gap) + self.gap))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_click)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_double)
        self.Bind(wx.EVT_MOTION, self._on_motion)

    def _rect(self, index: int) -> wx.Rect:
        row, col = divmod(index, self.columns)
        return wx.Rect(self.gap + col * (self.swatch + self.gap), self.gap + row * (self.swatch + self.gap),
                       self.swatch, self.swatch)

    def _index_at(self, pos: wx.Point) -> Optional[int]:
        return next((i for i in range(len(self.colours)) if self._rect(i).Contains(pos)), None)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        for index, rgb in enumerate(self.colours):
            rect = self._rect(index)
            dc.SetPen(wx.Pen(wx.Colour(30, 30, 34)))
            dc.SetBrush(wx.Brush(wx.Colour(*rgb)))
            dc.DrawRectangle(rect)
        if 0 <= self.selected < len(self.colours):
            rect = self._rect(self.selected)
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 2))
            dc.DrawRectangle(rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4)

    def describe(self, index: int) -> str:
        """"$2A #58D854": the entry's number (as games write it) and its colour."""
        return f"${index:02X}  {hex_colour(self.colours[index])}"

    def _on_click(self, event: wx.MouseEvent) -> None:
        index = self._index_at(event.GetPosition())
        if index is not None:
            self.selected = index
            self.Refresh()
            if self.on_select:
                self.on_select(index)

    def _on_double(self, event: wx.MouseEvent) -> None:
        if self._index_at(event.GetPosition()) is not None:
            self.GetTopLevelParent().EndModal(wx.ID_OK)

    def _on_motion(self, event: wx.MouseEvent) -> None:
        index = self._index_at(event.GetPosition())
        if index is None:
            self.UnsetToolTip()
        else:
            self.SetToolTip(self.describe(index))


class FixedColourDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, console_name: str, colours: Sequence[RGB], initial: Optional[RGB]):
        super().__init__(parent, title=f"{console_name} Colour")
        start = palettes.nearest(tuple(int(v) for v in initial[:3]), list(colours)) if initial is not None else 0  # type: ignore[arg-type]
        root = wx.BoxSizer(wx.VERTICAL)
        hint = wx.StaticText(self, label=f"A {console_name} palette takes its colours from this list.")
        root.Add(hint, 0, wx.ALL, px(10))
        self.grid = FixedColourGrid(self, colours, start)
        self.grid.on_select = lambda _index: self._show_selected()
        root.Add(self.grid, 0, wx.LEFT | wx.RIGHT, px(10))
        self.info = wx.StaticText(self, label="")
        root.Add(self.info, 0, wx.ALL, px(10))
        root.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, px(10))
        self.SetSizerAndFit(root)
        self._show_selected()
        self.CentreOnParent()

    def _show_selected(self) -> None:
        self.info.SetLabel(f"Selected: {self.grid.describe(self.grid.selected)}")

    def colour(self) -> RGB:
        return self.grid.colours[self.grid.selected]


def pick(parent: wx.Window, console_name: str, colours: Sequence[RGB], initial: Optional[RGB]) -> Optional[RGB]:
    """The fixed colour the user picks, or None when cancelled."""
    with FixedColourDialog(parent, console_name, colours, initial) as dialog:
        return dialog.colour() if dialog.ShowModal() == wx.ID_OK else None
