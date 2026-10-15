"""Preferences (Cmd+, / Edit ▸ Preferences): the editor-wide settings in one place.

The window edits a dict of values; the main window reads them from where each setting lives (``MainFrame.preference
_values``) and applies the result (``MainFrame.apply_preferences``), so the View menu and the view bars stay in step.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Tuple

import wx

from ui import theme
from ui.components.inspector_kit import dim_text
from ui.dpi import px

AUTOSAVE_CHOICES: List[Tuple[str, int]] = [("15 seconds", 15), ("30 seconds", 30), ("1 minute", 60),
                                          ("2 minutes", 120), ("5 minutes", 300)]


def _heading(parent: wx.Window, text: str) -> wx.StaticText:
    label = wx.StaticText(parent, label=text)
    font = label.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    label.SetFont(font)
    return label


class PreferencesDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, values: Dict[str, Any], on_clear_recent: Callable[[], None]):
        super().__init__(parent, title="Preferences")
        self.on_clear_recent = on_clear_recent
        root = wx.BoxSizer(wx.VERTICAL)

        def heading(text: str) -> None:
            root.Add(_heading(self, text), 0, wx.LEFT | wx.RIGHT | wx.TOP, px(14))

        def add(item: Any, top: int = 6) -> None:  # a row under its heading, indented
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.AddSpacer(px(28))
            row.Add(item, 0, wx.ALIGN_CENTER_VERTICAL)
            row.AddSpacer(px(16))
            root.AddSpacer(px(top))
            root.Add(row, 0)

        heading("Views")
        theme_row = wx.BoxSizer(wx.HORIZONTAL)
        self.theme = wx.Choice(self, choices=[theme.LABELS[mode] for mode in theme.MODES])
        self.theme.SetSelection(theme.MODES.index(values["theme"]) if values["theme"] in theme.MODES else 0)
        longest = max(self.GetTextExtent(label)[0] for label in theme.LABELS.values())
        self.theme.SetMinSize((longest + px(44), -1))  # macOS sizes a choice for its current item
        theme_row.Add(wx.StaticText(self, label="Theme"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        theme_row.Add(self.theme, 0, wx.ALIGN_CENTER_VERTICAL)
        if sys.platform != "darwin":  # wx 3.2 draws Windows' and GTK's controls in the system's look
            theme_row.Add(dim_text(self, "lists, views and canvases; buttons and fields keep the system's look"), 0,
                          wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        add(theme_row)
        self.scroll_moves = wx.CheckBox(self, label="Scrolling moves the view (pinch or ⌘ / Ctrl + scroll zooms)")
        self.scroll_moves.SetValue(bool(values["scroll_moves"]))
        self.play_50hz = wx.CheckBox(self, label="Play previews at 50 Hz, as a PAL console shows the game")
        self.play_50hz.SetValue(bool(values["play_50hz"]))
        self.play_50hz.SetToolTip("Animations, scenes and colour cycles play at 5/6 of the speed (View menu too)")
        colour_row = wx.BoxSizer(wx.HORIZONTAL)
        self.backdrop = wx.ColourPickerCtrl(self, colour=wx.Colour(*values["backdrop_colour"]))
        colour_row.Add(wx.StaticText(self, label="Backdrop colour"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        colour_row.Add(self.backdrop, 0, wx.ALIGN_CENTER_VERTICAL)
        colour_row.Add(dim_text(self, "behind the art when a view bar's backdrop is Colour"), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        for item in (self.scroll_moves, self.play_50hz, colour_row):
            add(item)

        heading("New animations")
        rate_row = wx.BoxSizer(wx.HORIZONTAL)
        self.tick_rate = wx.SpinCtrl(self, min=1, max=60, initial=int(values["tick_rate"]), size=(px(64), -1))
        rate_row.Add(wx.StaticText(self, label="Tick rate"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        rate_row.Add(self.tick_rate, 0, wx.ALIGN_CENTER_VERTICAL)
        rate_row.Add(dim_text(self, "ticks a second (10, 12, 15, 20 or 30 give the game the exact timing)"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        add(rate_row)

        heading("Safety")
        autosave_row = wx.BoxSizer(wx.HORIZONTAL)
        self.autosave = wx.Choice(self, choices=[label for label, _seconds in AUTOSAVE_CHOICES])
        seconds = [s for _label, s in AUTOSAVE_CHOICES]
        self.autosave.SetSelection(seconds.index(values["autosave_seconds"])
                                   if values["autosave_seconds"] in seconds else 1)
        # macOS sizes a choice for its current item: room for the longest one and the arrows.
        longest = max(self.GetTextExtent(label)[0] for label, _seconds in AUTOSAVE_CHOICES)
        self.autosave.SetMinSize((longest + px(44), -1))
        autosave_row.Add(wx.StaticText(self, label="Keep a recovery copy of unsaved changes every"), 0,
                         wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        autosave_row.Add(self.autosave, 0, wx.ALIGN_CENTER_VERTICAL)
        add(autosave_row)
        note = dim_text(self, "Offered at the next start if the editor quits unexpectedly. Saving removes it.")
        add(note, top=4)

        heading("Start")
        self.welcome = wx.CheckBox(self, label="Show the welcome screen when no project opens")
        self.welcome.SetValue(bool(values["welcome"]))
        add(self.welcome)
        self.btn_clear_recent = wx.Button(self, label="Clear Recent Projects")
        self.btn_clear_recent.Enable(bool(values["recent_count"]))
        self.btn_clear_recent.SetToolTip("Empty File ▸ Open Recent and the welcome screen's list (the files stay)")
        self.btn_clear_recent.Bind(wx.EVT_BUTTON, self._clear_recent)
        add(self.btn_clear_recent, top=8)

        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            root.Add(buttons, 0, wx.EXPAND | wx.ALL, px(14))
        self.SetSizerAndFit(root)
        self.CenterOnParent()

    def _clear_recent(self, _event: wx.CommandEvent) -> None:
        self.on_clear_recent()
        self.btn_clear_recent.Disable()

    def values(self) -> Dict[str, Any]:
        colour = self.backdrop.GetColour()
        return {
            "theme": theme.MODES[max(0, self.theme.GetSelection())],
            "scroll_moves": self.scroll_moves.GetValue(),
            "play_50hz": self.play_50hz.GetValue(),
            "backdrop_colour": (colour.Red(), colour.Green(), colour.Blue()),
            "tick_rate": self.tick_rate.GetValue(),
            "autosave_seconds": AUTOSAVE_CHOICES[max(0, self.autosave.GetSelection())][1],
            "welcome": self.welcome.GetValue(),
        }
