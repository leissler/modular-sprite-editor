"""SwatchGrid: a palette's slots as big swatches to select, reorder and edit.

Slot 0 (transparent) comes first, then every slot the console's palettes have: the palette's colours, then its free
slots. Colours a palette stores past the console's palette size (kept from a console with bigger palettes) follow,
crossed out. With a palette swap, a swatch shows what the slot shows under the swap and keeps the original in a
corner. Colour cycles are brackets under their run of slots.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import wx

from models import ColourCycle
from ui.components.palette_swatches import draw_empty_slot, hex_colour
from ui.dpi import px

RGB = Tuple[int, int, int]
CYCLE_COLOURS = (wx.Colour(255, 176, 64), wx.Colour(120, 210, 255), wx.Colour(170, 230, 120), wx.Colour(240, 130, 220))
COL_SELECTED = wx.Colour(255, 255, 255)
COL_DROP = wx.Colour(140, 210, 255)
COL_WAITING = wx.Colour(235, 70, 70)  # the cross over a colour the console does not show


class SwatchGrid(wx.Panel):
    def __init__(self, parent: wx.Window, swatch: int = 24, columns: int = 8):
        super().__init__(parent)
        self.swatch = px(swatch)
        self.gap = px(3)
        self.columns = columns
        self.capacity = 15
        self.colours: List[RGB] = []
        self.replacements: Optional[List[Optional[RGB]]] = None  # a swap's colours per slot (None: the palette's)
        self.cycles: List[ColourCycle] = []
        self.usage: List[int] = []  # pixels per slot
        self.art: List[int] = []  # slots the images' pixels have exactly
        self.selected: List[int] = []
        self.reorder = True
        self._anchor: Optional[int] = None
        self._press: Optional[Tuple[int, wx.Point]] = None
        self._drop: Optional[int] = None
        self.on_select: Optional[Callable[[List[int]], None]] = None
        self.on_activate: Optional[Callable[[int], None]] = None
        self.on_move: Optional[Callable[[int, int], None]] = None  # (slot, the slot it goes to)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_double)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda e: self._end_drag())
        self._resize()

    # ------------------------------------------------------------------ data
    def set_palette(self, colours: Sequence[RGB], capacity: int, replacements: Optional[Sequence[Optional[RGB]]] = None,
                    cycles: Sequence[ColourCycle] = (), usage: Sequence[int] = (), art: Sequence[int] = ()) -> None:
        self.colours = list(colours)
        self.capacity = capacity
        self.replacements = list(replacements) if replacements is not None else None
        self.cycles = list(cycles)
        self.usage = list(usage)
        self.art = list(art)
        self.selected = [s for s in self.selected if s < len(self.colours)]
        self._resize()
        self.Refresh()

    def set_selected(self, slots: Sequence[int]) -> None:
        self.selected = [s for s in slots if 0 <= s < len(self.colours)]
        self._anchor = self.selected[0] if self.selected else None
        self.Refresh()

    # ------------------------------------------------------------------ geometry
    def _slots(self) -> int:
        """The console's slots, and the colours stored past them."""
        return max(self.capacity, len(self.colours))

    def _cells(self) -> int:
        return self._slots() + 1  # slot 0 (transparent) first

    def _rows(self) -> int:
        return (self._cells() + self.columns - 1) // self.columns

    def _row_height(self) -> int:
        return self.swatch + self.gap + px(4) * 2  # room for cycle brackets under each row

    def _resize(self) -> None:
        width = self.columns * (self.swatch + self.gap) + self.gap
        height = self._rows() * self._row_height() + self.gap
        self.SetMinSize((width, height))

    def _cell_rect(self, cell: int) -> wx.Rect:
        row, col = divmod(cell, self.columns)
        return wx.Rect(self.gap + col * (self.swatch + self.gap), self.gap + row * self._row_height(),
                       self.swatch, self.swatch)

    def _slot_at(self, pos: wx.Point) -> Optional[int]:
        """The palette slot (0-based colour index) under the mouse; None for slot 0 or between swatches."""
        for cell in range(1, self._cells()):
            if self._cell_rect(cell).Contains(pos):
                return cell - 1
        return None

    def _gap_at(self, pos: wx.Point) -> int:
        """Where a dragged colour would go: before the swatch under the mouse (or after the last colour)."""
        slot = self._slot_at(pos)
        if slot is None:
            return len(self.colours)
        rect = self._cell_rect(slot + 1)
        return min(len(self.colours), slot + (1 if pos.x > rect.x + rect.width // 2 else 0))

    # ------------------------------------------------------------------ painting
    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        self._draw_transparent(dc, self._cell_rect(0))
        for slot in range(self._slots()):
            rect = self._cell_rect(slot + 1)
            if slot >= len(self.colours):
                draw_empty_slot(dc, rect.x, rect.y, rect.width)
                continue
            original = self.colours[slot]
            swapped = self.replacements[slot] if self.replacements and slot < len(self.replacements) else None
            shown = swapped if swapped is not None else original
            dc.SetPen(wx.Pen(wx.Colour(30, 30, 34)))
            dc.SetBrush(wx.Brush(wx.Colour(*shown)))
            dc.DrawRectangle(rect)
            if swapped is not None:  # the original in a corner
                corner = max(px(6), rect.width // 3)
                dc.SetBrush(wx.Brush(wx.Colour(*original)))
                dc.DrawPolygon([wx.Point(rect.x + rect.width, rect.y + rect.height - corner),
                                wx.Point(rect.x + rect.width, rect.y + rect.height),
                                wx.Point(rect.x + rect.width - corner, rect.y + rect.height)])
            if slot >= self.capacity:  # the console does not show it
                dc.SetPen(wx.Pen(COL_WAITING, 2))
                dc.DrawLine(rect.x + 2, rect.y + 2, rect.x + rect.width - 2, rect.y + rect.height - 2)
                dc.DrawLine(rect.x + rect.width - 2, rect.y + 2, rect.x + 2, rect.y + rect.height - 2)
            elif self.usage and slot < len(self.usage) and self.usage[slot] == 0:  # nothing uses it
                dc.SetPen(wx.Pen(wx.Colour(150, 156, 170)))
                dc.DrawLine(rect.x + 2, rect.y + 2, rect.x + px(6), rect.y + 2)
            if slot in self.selected:
                dc.SetBrush(wx.TRANSPARENT_BRUSH)
                dc.SetPen(wx.Pen(COL_SELECTED, 2))
                dc.DrawRectangle(rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4)
        for index, cycle in enumerate(self.cycles):
            self._draw_cycle(dc, cycle, CYCLE_COLOURS[index % len(CYCLE_COLOURS)], index)
        if self._drop is not None:
            rect = self._cell_rect(self._drop + 1) if self._drop < self._slots() else self._cell_rect(self._slots())
            x = rect.x - self.gap // 2 - 1 if self._drop < len(self.colours) else rect.x + rect.width + 1
            dc.SetPen(wx.Pen(COL_DROP, 2))
            dc.DrawLine(x, rect.y - 2, x, rect.y + rect.height + 2)

    def _draw_transparent(self, dc: wx.DC, rect: wx.Rect) -> None:
        half = rect.width // 2
        for i, (dx, dy) in enumerate(((0, 0), (half, 0), (0, half), (half, half))):
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(wx.Colour(120, 120, 124) if i in (0, 3) else wx.Colour(80, 80, 84)))
            dc.DrawRectangle(rect.x + dx, rect.y + dy, half, half)

    def _draw_cycle(self, dc: wx.DC, cycle: ColourCycle, colour: wx.Colour, index: int) -> None:
        """A bracket under the cycle's slots (row by row when it wraps)."""
        first, last = cycle.first, cycle.first + cycle.count - 1
        if first < 1 or last > self.capacity:
            return
        dc.SetPen(wx.Pen(colour, 2))
        y_off = px(3) + (index % 2) * px(3)
        cell = first
        while cell <= last:
            row = cell // self.columns
            end = min(last, (row + 1) * self.columns - 1)
            a, b = self._cell_rect(cell), self._cell_rect(end)
            y = a.y + a.height + y_off
            dc.DrawLine(a.x, y, b.x + b.width, y)
            if cell == first:
                dc.DrawLine(a.x, y - px(3), a.x, y)
            if end == last:
                dc.DrawLine(b.x + b.width, y - px(3), b.x + b.width, y)
            cell = end + 1

    # ------------------------------------------------------------------ mouse
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        slot = self._slot_at(event.GetPosition())
        if slot is None or slot >= len(self.colours):
            return
        if event.ShiftDown() and self._anchor is not None:
            low, high = sorted((self._anchor, slot))
            self.selected = list(range(low, high + 1))
        elif event.CmdDown():
            self.selected = [s for s in self.selected if s != slot] if slot in self.selected else self.selected + [slot]
            self._anchor = slot
        else:
            self.selected = [slot]
            self._anchor = slot
            self._press = (slot, event.GetPosition())
            self.CaptureMouse()
        self.Refresh()
        if self.on_select:
            self.on_select(list(self.selected))

    def _on_motion(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        slot = self._slot_at(pos)
        if slot is not None and slot < len(self.colours):
            self.SetToolTip(self._describe(slot))
        elif slot is not None:
            self.SetToolTip("A free slot")
        else:
            self.UnsetToolTip()
        if self._press is None or not event.LeftIsDown() or not self.reorder:
            return
        start = self._press[1]
        if self._drop is None and abs(pos.x - start.x) + abs(pos.y - start.y) < px(5):
            return
        self._drop = self._gap_at(pos)
        self.Refresh()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        press, drop = self._press, self._drop
        self._end_drag()
        if press is None or drop is None or not self.on_move:
            return
        slot = press[0]
        target = drop - 1 if drop > slot else drop
        if target != slot:
            self.on_move(slot, target)

    def _end_drag(self) -> None:
        self._press = None
        self._drop = None
        if self.HasCapture():
            self.ReleaseMouse()
        self.Refresh()

    def _on_double(self, event: wx.MouseEvent) -> None:
        slot = self._slot_at(event.GetPosition())
        if slot is not None and self.on_activate:
            self.on_activate(slot)

    def _describe(self, slot: int) -> str:
        original = self.colours[slot]
        lines = [f"Slot {slot + 1}: {hex_colour(original)}"]
        swapped = self.replacements[slot] if self.replacements and slot < len(self.replacements) else None
        if swapped is not None:
            lines.append(f"The swap shows {hex_colour(swapped)}")
        if self.usage and slot < len(self.usage):
            used = self.usage[slot]
            lines.append(f"{used} pixel{'s' if used != 1 else ''}" if used else "No pixel uses it")
        if slot >= self.capacity:
            lines.append(f"Past the console's {self.capacity} colours a palette: not shown, it waits for a console "
                         "with bigger palettes (drag it to an earlier slot, or Remove unused)")
        elif slot in self.art:
            lines.append("The images have this colour: recolour it with a palette swap")
        return "\n".join(lines)
