"""Building blocks for the editors' inspectors: titled sections, label/control rows, spin helpers."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

import wx

COL_SECTION = wx.Colour(150, 156, 170)
COL_DIM = wx.Colour(150, 156, 170)
COL_WARN = wx.Colour(255, 140, 120)


def section(parent: wx.Window, sizer: wx.BoxSizer, title: str) -> Tuple[wx.Panel, wx.FlexGridSizer, wx.StaticText]:
    panel = wx.Panel(parent)
    outer = wx.BoxSizer(wx.VERTICAL)
    label = wx.StaticText(panel, label=title.upper())
    font = label.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    font.SetPointSize(max(8, font.GetPointSize() - 1))
    label.SetFont(font)
    label.SetForegroundColour(COL_SECTION)
    outer.Add(label, 0, wx.LEFT | wx.TOP, 2)
    outer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 4)
    grid = wx.FlexGridSizer(0, 2, 6, 8)
    grid.AddGrowableCol(1, 1)
    outer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)
    panel.SetSizer(outer)
    sizer.Add(panel, 0, wx.EXPAND | wx.ALL, 6)
    return panel, grid, label


def row(grid: wx.FlexGridSizer, parent: wx.Window, label: str, item: Any) -> wx.StaticText:
    text = wx.StaticText(parent, label=label)
    grid.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(item, 1, wx.EXPAND)
    return text


def full_row(grid: wx.FlexGridSizer, item: Any) -> None:
    """An item under the value column (no label)."""
    grid.Add((0, 0))
    grid.Add(item, 1, wx.EXPAND)


def hbox(*items: Any, gap: int = 4) -> wx.BoxSizer:
    """Items in a row; an int adds a spacer, a str a stretch spacer; buttons share the width."""
    box = wx.BoxSizer(wx.HORIZONTAL)
    for item in items:
        if isinstance(item, int):
            box.AddSpacer(item)
        elif isinstance(item, str):
            box.AddStretchSpacer(1)
        else:
            box.Add(item, 1 if isinstance(item, (wx.Button, wx.ToggleButton)) else 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, gap)
    return box


def dim_text(parent: wx.Window, label: str = "") -> wx.StaticText:
    text = wx.StaticText(parent, label=label)
    text.SetForegroundColour(COL_DIM)
    return text


def spin(parent: wx.Window, low: int = -9999, high: int = 9999, width: int = 60, tip: str = "") -> wx.SpinCtrl:
    ctrl = wx.SpinCtrl(parent, min=low, max=high, initial=0, size=(width, -1), style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
    if tip:
        ctrl.SetToolTip(tip)
    return ctrl


def bind_spin(ctrl: wx.SpinCtrl, handler: Callable[[int], None]) -> None:
    """Value changes from the arrows, typing + Enter, or leaving the field."""
    ctrl.Bind(wx.EVT_SPINCTRL, lambda e: handler(ctrl.GetValue()))
    ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: handler(ctrl.GetValue()))


def small_button(parent: wx.Window, label: str, tip: str, handler: Callable[[], None], width: int = -1) -> wx.Button:
    btn = wx.Button(parent, label=label, style=wx.BU_EXACTFIT, size=(width, -1))
    btn.SetToolTip(tip)
    # Rows of buttons may shrink a little in a narrow inspector, a lone button keeps its label.
    btn.SetMinSize((max(28, width) if width > 0 else min(btn.GetBestSize().width, 90), -1))
    btn.Bind(wx.EVT_BUTTON, lambda e: handler())
    return btn


def set_spin(ctrl: wx.SpinCtrl, value: Optional[int]) -> None:
    """Show a value (None = several different values: blank)."""
    if value is None:
        ctrl.SetValue("")  # type: ignore[arg-type]
    else:
        ctrl.SetValue(int(value))


def common(values: List[Any]) -> Any:
    """The shared value of a multi-selection, or None when they differ."""
    return values[0] if values and all(v == values[0] for v in values) else None


def fit_choice(choice: wx.Choice, extra: int = 44) -> None:
    """macOS sizes a Choice for its current item; leave room for the longest one plus the arrows."""
    if choice.GetCount():
        longest = max(choice.GetTextExtent(choice.GetString(i))[0] for i in range(choice.GetCount()))
        choice.SetMinSize((min(longest + extra, 220), -1))
        choice.GetParent().Layout()
