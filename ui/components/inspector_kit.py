"""Building blocks for the editors' inspectors: titled sections, label/control rows, spin helpers."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

import wx

from ui.preferences import config as _config

COL_SECTION = wx.Colour(150, 156, 170)
COL_DIM = wx.Colour(150, 156, 170)
COL_WARN = wx.Colour(255, 140, 120)
CONFIG_FOLDED = "View/Folded/{}/{}"  # (inspector, section title): "1" while the section is folded away



class Section(wx.Panel):
    """A titled inspector section. Its rows live in ``body`` (their parent) and ``grid``; Show / Hide on the section
    act on all of it. With a ``scope`` (the inspector's name) a click on the title folds the rows away, and the
    section remembers that for the next start."""

    def __init__(self, parent: wx.Window, title: str, scope: str = ""):
        super().__init__(parent)
        self.key = CONFIG_FOLDED.format(scope, title) if scope else ""
        cfg = _config()
        self.folded = bool(self.key and cfg and cfg.ReadBool(self.key, False))
        outer = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        self.arrow: Optional[wx.StaticText] = None
        if self.key:
            self.arrow = wx.StaticText(self, label="", size=(12, -1))
            self.arrow.SetForegroundColour(COL_SECTION)
            header.Add(self.arrow, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        self.title = wx.StaticText(self, label=title.upper())
        font = self.title.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        font.SetPointSize(max(8, font.GetPointSize() - 1))
        self.title.SetFont(font)
        self.title.SetForegroundColour(COL_SECTION)
        header.Add(self.title, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(header, 0, wx.EXPAND | wx.LEFT | wx.TOP, 2)
        outer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 4)
        self.body = wx.Panel(self)
        self.grid = wx.FlexGridSizer(0, 2, 6, 8)
        self.grid.AddGrowableCol(1, 1)
        body_sizer = wx.BoxSizer(wx.VERTICAL)
        body_sizer.Add(self.grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)
        self.body.SetSizer(body_sizer)
        outer.Add(self.body, 0, wx.EXPAND)
        self.SetSizer(outer)
        if self.key:
            for widget in (self.arrow, self.title):
                widget.SetCursor(wx.Cursor(wx.CURSOR_HAND))
                widget.SetToolTip("Click to fold this section away or open it again")
                widget.Bind(wx.EVT_LEFT_DOWN, lambda e: self.set_folded(not self.folded))
        self._show_folded()

    def set_title(self, text: str) -> None:
        self.title.SetLabel(text.upper())

    def set_folded(self, folded: bool) -> None:
        self.folded = bool(folded)
        cfg = _config()
        if self.key and cfg:
            cfg.WriteBool(self.key, self.folded)
            cfg.Flush()
        self._show_folded()
        top = self.GetParent()
        relayout(top)

    def _show_folded(self) -> None:
        if self.arrow is not None:
            self.arrow.SetLabel("▸" if self.folded else "▾")
        self.body.Show(not self.folded)


def section(
    parent: wx.Window, sizer: wx.BoxSizer, title: str, scope: str = ""
) -> Tuple[Section, wx.FlexGridSizer, wx.StaticText]:
    """A section under ``sizer``: (section, its grid, its title). Create the rows' widgets on ``section.body``."""
    panel = Section(parent, title, scope)
    sizer.Add(panel, 0, wx.EXPAND | wx.ALL, 6)
    return panel, panel.grid, panel.title


def relayout(inspector: wx.Window) -> None:
    """Lay out an inspector after rows were shown, hidden or folded: every section, then the scrolled whole."""
    for child in inspector.GetChildren():
        if isinstance(child, Section):
            child.body.Layout()
            child.Layout()
    inspector.Layout()
    if isinstance(inspector, wx.ScrolledWindow):
        inspector.FitInside()


def row(grid: wx.FlexGridSizer, parent: wx.Window, label: str, item: Any) -> wx.StaticText:
    text = wx.StaticText(parent, label=label)
    grid.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(item, 1, wx.EXPAND)
    return text


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
