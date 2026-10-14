"""Keyboard & mouse shortcut reference (Help menu)."""

from __future__ import annotations

import sys
from typing import List, Tuple

import wx
from ui.dpi import px

MOD = "Cmd" if sys.platform == "darwin" else "Ctrl"

# (context, action, shortcut). Keep in sync with README "Controls".
SHORTCUTS: List[Tuple[str, str, str]] = [
    ("Global", "Undo / Redo (all editors)", f"{MOD}+Z / {MOD}+Shift+Z"),
    ("Global", "New / Open / Save / Save As", f"{MOD}+N / {MOD}+O / {MOD}+S / {MOD}+Shift+S"),
    ("Global", "Switch tab", f"{MOD}+1 … {MOD}+5"),
    ("Global", "This help", f"{MOD}+/"),
    ("Every canvas", "Zoom at cursor (smooth, settles on whole pixel sizes)",
     f"Mouse wheel / two-finger scroll / pinch (View ▸ Scroll Moves the View: pinch / {MOD}+scroll)"),
    ("Every canvas", "Pan", "Space+drag, Alt+drag or middle-drag"),
    ("Every canvas", "Pan horizontally / vertically", "Shift+wheel / Alt+wheel (Scroll Moves the View: scroll)"),
    ("Every canvas", "Zoom in / out", f"{MOD}+= / {MOD}+-"),
    ("Every canvas", "Fit content / actual pixels (1×)", f"{MOD}+0 / {MOD}+Shift+0"),
    ("Every canvas", "Toggle grid", f"{MOD}+G"),
    ("Every canvas", "Mega Drive colours (View menu)", f"{MOD}+Shift+P"),
    ("Modules", "New module (on an image) / shape (on Shapes)", "Drag on empty space"),
    ("Modules", "Select / move / resize", "Click / drag a module / drag a handle"),
    ("Modules", "Add or remove from the selection / select with a marquee", f"{MOD}+click / {MOD}+drag"),
    ("Modules", "Move pivot (Shift is taken here)", "Shift+drag (or the inspector's presets)"),
    ("Modules", "Nudge selected modules 1 px / 8 px", "Arrows / Shift+arrows"),
    ("Modules", "Copy / Paste (onto any image) / Duplicate / Select all", f"{MOD}+C / {MOD}+V / {MOD}+D / {MOD}+A"),
    ("Modules", "Rename / reorder modules", "Double-click or F2 / drag in the list"),
    ("Modules", "Delete selected modules", "Delete / Backspace"),
    ("Modules", "Cancel picking the key colour / clear the selection", "Esc"),
    ("Frames", "Select / add / add or remove / cycle stacked parts",
     f"Click / Shift+click / {MOD}+click / click again"),
    ("Frames", "Select with a marquee", f"Drag on empty space (Shift or {MOD} adds)"),
    ("Frames", "Nudge selection 1 px / 8 px", "Arrows / Shift+arrows"),
    ("Frames", "Flip horizontal / vertical", "H / V  (X / Y also work)"),
    ("Frames", "Rotate 90° CW / CCW", "R / Shift+R"),
    ("Frames", "Draw order forward / backward", f"{MOD}+↑ / {MOD}+↓  (Shift = to front / back)"),
    ("Frames", "Copy / Paste / Duplicate / Select all", f"{MOD}+C / {MOD}+V / {MOD}+D / {MOD}+A"),
    ("Frames", "Delete selection", "Delete / Backspace"),
    ("Frames", "Add a part", "Drag from the library onto the stage, or double-click it (adds at the origin)"),
    ("Frames", "Nest a frame", "Drag it from the frames list or the library onto the stage"),
    ("Frames", "Rename / reorder frames", "Double-click or F2 / drag in the list"),
    ("Frames", "Clear the selection", "Esc"),
    ("Frames · Hitboxes", "Create box / move / resize corners", "Drag empty / drag box / drag corner"),
    ("Frames · Points", "Create point / move point", "Click on empty space / drag"),
    ("Frames · Points", "Add a point to the selection / add or remove", f"Shift+click / {MOD}+click"),
    ("Animations", "Play / pause", "Enter"),
    ("Animations", "Previous / next step", ", / .  (← / → in the sequence)"),
    ("Animations", "Previous / next tick", "Shift+, / Shift+."),
    ("Animations", "First / last step", "Home / End"),
    ("Animations", "Shorter / longer hold of the selected steps", "[ / ]  (or drag a step's right edge)"),
    ("Animations", "Flip horizontal / vertical, rotate selected steps", "H / V, R / Shift+R"),
    ("Animations", "Move the selected steps' offset 1 px / 8 px", "Arrows / Shift+arrows (stage focused), or drag the stage"),
    ("Animations", "Select steps / range / add or remove", f"Click / Shift+click / {MOD}+click (Shift+← / → in the sequence)"),
    ("Animations", "Reorder / copy steps", "Drag a step / Alt+drag"),
    ("Animations", "Insert a frame", "Drag from Frames into the sequence or onto the stage, or double-click it"),
    ("Animations", "Copy / Paste / Duplicate / Select all steps", f"{MOD}+C / {MOD}+V / {MOD}+D / {MOD}+A"),
    ("Animations", "Delete selected steps", "Delete / Backspace"),
    ("Animations", "Open a step's frame in the Frames tab", "Double-click the step"),
    ("Animations", "Rename / reorder animations", "Double-click or F2 / drag in the list"),
    ("Animations", "Zoom / scroll the step sequence",
     f"Wheel / Shift+wheel or trackpad sideways (Scroll Moves the View: {MOD}+wheel / wheel)"),
    ("Timeline", "Play / pause", "Enter"),
    ("Timeline", "Previous / next frame", ", / .  (← / → in the timeline)"),
    ("Timeline", "Previous / next key of the selected layer", "Shift+, / Shift+."),
    ("Timeline", "First / last frame", "Home / End"),
    ("Timeline", "Set key at playhead / add-or-remove key", "K / Shift+K"),
    ("Timeline", "Flip horizontal / vertical, rotate", "H / V, R / Shift+R"),
    ("Timeline", "Nudge selected object 1 px / 8 px", "Arrows / Shift+arrows (stage focused)"),
    ("Timeline", "Delete selected keys (else the layer)", "Delete / Backspace"),
    ("Timeline", "Copy / Paste / Duplicate / Select all keys", f"{MOD}+C / {MOD}+V / {MOD}+D / {MOD}+A"),
    ("Timeline", "Select keys / add / add or remove / box-select",
     f"Click / Shift+click / {MOD}+click / drag empty track"),
    ("Timeline", "Retime keys / add key", "Drag keys / double-click track"),
    ("Timeline", "Segment easing, swap image, layer menu", "Right-click bar / key / layer"),
    ("Timeline", "Reorder or parent a layer", "Drag the layer name (onto a layer = make child)"),
    ("Timeline", "Zoom / scroll time, scroll layers",
     f"Wheel / Shift+wheel or trackpad sideways, wheel over layers (Scroll Moves the View: {MOD}+wheel / sideways / wheel)"),
    ("Mappings", "Replace the selected modules", "Click a module under Replace with (or drag it onto a row)"),
    ("Mappings", "Original / hide the selected modules", "Delete / H"),
    ("Mappings", "Select several modules", f"{MOD}+click / Shift+click"),
    ("Mappings", "Rename / reorder mappings", "Double-click or F2 / drag in the list"),
]


class ShortcutsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="Keyboard & Mouse Shortcuts", size=(px(760), px(640)),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        listing = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES)
        listing.InsertColumn(0, "Where", width=px(130))
        listing.InsertColumn(1, "Action", width=px(320))
        listing.InsertColumn(2, "Shortcut", width=px(280))
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
