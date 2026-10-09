"""Keyboard & mouse shortcut reference (Help menu)."""

from __future__ import annotations

import sys
from typing import List, Tuple

import wx

MOD = "Cmd" if sys.platform == "darwin" else "Ctrl"

# (context, action, shortcut). Keep in sync with README "Controls".
SHORTCUTS: List[Tuple[str, str, str]] = [
    ("Global", "Undo / Redo (all editors)", f"{MOD}+Z / {MOD}+Shift+Z"),
    ("Global", "New / Open / Save / Save As", f"{MOD}+N / {MOD}+O / {MOD}+S / {MOD}+Shift+S"),
    ("Global", "Switch tab", f"{MOD}+1 … {MOD}+5"),
    ("Global", "This help", f"{MOD}+/"),
    ("Every canvas", "Zoom at cursor (integer pixel steps)", "Mouse wheel / trackpad pinch"),
    ("Every canvas", "Pan", "Space+drag, Alt+drag or middle-drag"),
    ("Every canvas", "Pan horizontally / vertically", "Shift+wheel / Alt+wheel"),
    ("Every canvas", "Zoom in / out", f"{MOD}+= / {MOD}+-"),
    ("Every canvas", "Fit content / actual pixels (1×)", f"{MOD}+0 / {MOD}+Shift+0"),
    ("Every canvas", "Toggle grid", f"{MOD}+G"),
    ("Modules", "Draw a new selection rectangle", "Drag on empty area"),
    ("Modules", "Move pivot", "Shift+drag"),
    ("Modules", "Delete selected module", "Delete / Backspace"),
    ("Frames", "Select / add to selection / cycle stacked parts", "Click / Shift+click / click again"),
    ("Frames", "Nudge selection 1 px / 8 px", "Arrows / Shift+arrows"),
    ("Frames", "Flip horizontal / vertical", "H / V  (X / Y also work)"),
    ("Frames", "Rotate 90° CW / CCW", "R / Shift+R"),
    ("Frames", "Draw order forward / backward", f"{MOD}+↑ / {MOD}+↓  (Shift = to front / back)"),
    ("Frames", "Copy / Paste / Duplicate / Select all", f"{MOD}+C / {MOD}+V / {MOD}+D / {MOD}+A"),
    ("Frames", "Delete selection", "Delete / Backspace"),
    ("Frames · Collision", "Create box / move / resize corners", "Drag empty / drag box / drag corner"),
    ("Frames · Points", "Create point / move point", "Shift+click / drag"),
    ("Animations", "Play / pause", "Enter"),
    ("Animations", "Previous / next frame", ", / .  (← / → in the frame strip)"),
    ("Animations", "Nudge frame offset 1 px / 8 px", "Arrows / Shift+arrows (canvas focused)"),
    ("Animations", "Move frame offset", "Drag on canvas"),
    ("Animations", "Delete frame from animation", "Delete in the frame strip"),
    ("Timeline", "Play / pause", "Enter"),
    ("Timeline", "Previous / next frame", ", / ."),
    ("Timeline", "Flip horizontal / vertical, rotate", "H / V, R / Shift+R"),
    ("Timeline", "Zoom / pan tracks", "Wheel / Shift+wheel, Space+drag"),
    ("Mappings", "Remap a module", "Drag a source module onto a target slot"),
    ("Mappings", "Reset or hide a slot", "Right-click a target slot"),
]


class ShortcutsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="Keyboard & Mouse Shortcuts", size=(760, 640),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        listing = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES)
        listing.InsertColumn(0, "Where", width=130)
        listing.InsertColumn(1, "Action", width=320)
        listing.InsertColumn(2, "Shortcut", width=280)
        for context, action, shortcut in SHORTCUTS:
            idx = listing.InsertItem(listing.GetItemCount(), context)
            listing.SetItem(idx, 1, action)
            listing.SetItem(idx, 2, shortcut)
        sizer.Add(listing, 1, wx.EXPAND | wx.ALL, 8)
        buttons = self.CreateStdDialogButtonSizer(wx.OK)
        if buttons:
            sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(sizer)
        self.CenterOnParent()
