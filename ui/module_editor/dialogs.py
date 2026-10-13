"""Dialogs of the Modules tab: grid slice, sprite detection and folder import options."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

import wx

from ui.components.inspector_kit import dim_text


def _spin(parent: wx.Window, value: int, low: int, high: int) -> wx.SpinCtrl:
    return wx.SpinCtrl(parent, min=low, max=high, initial=value, size=(72, -1), style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)


class _OptionsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, title: str, intro: str, existing: int):
        super().__init__(parent, title=title)
        self.root = wx.BoxSizer(wx.VERTICAL)
        text = wx.StaticText(self, label=intro)
        text.Wrap(360)
        self.root.Add(text, 0, wx.ALL, 12)
        self.grid = wx.FlexGridSizer(0, 2, 8, 10)
        self.root.Add(self.grid, 0, wx.LEFT | wx.RIGHT, 12)
        self.existing = existing
        self.mode: Optional[wx.RadioBox] = None
        self.preview = dim_text(self)

    def _finish(self) -> None:
        if self.existing:
            self.mode = wx.RadioBox(
                self, label=f"The image already has {self.existing} module{'s' if self.existing != 1 else ''}",
                choices=["Keep them, add only new areas", "Replace them (parts using them break)"],
                style=wx.RA_SPECIFY_ROWS,
            )
            self.root.Add(self.mode, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        self.root.Add(self.preview, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            self.root.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(self.root)
        self.CenterOnParent()

    def replace(self) -> bool:
        return bool(self.mode and self.mode.GetSelection() == 1)


class GridSliceDialog(_OptionsDialog):
    def __init__(self, parent: wx.Window, values: Dict[str, int], existing: int,
                 count: Callable[[Dict[str, int], bool], Tuple[int, int]]):
        super().__init__(parent, "Grid Slice", "Cut the image into equal tiles. On the Mega Drive, multiples of 8 match the hardware tiles.", existing)
        self._count = count
        self.spins: Dict[str, wx.SpinCtrl] = {}
        for label, keys in (("Tile size", ("tile_w", "tile_h")), ("Offset", ("offset_x", "offset_y")), ("Gap", ("gap_x", "gap_y"))):
            box = wx.BoxSizer(wx.HORIZONTAL)
            for index, key in enumerate(keys):
                low = 1 if key.startswith("tile") else 0
                ctrl = _spin(self, values.get(key, 16 if low else 0), low, 4096)
                ctrl.Bind(wx.EVT_SPINCTRL, lambda e: self._update())
                ctrl.Bind(wx.EVT_TEXT, lambda e: self._update())
                self.spins[key] = ctrl
                if index:
                    box.Add(wx.StaticText(self, label="×" if key.startswith("tile") else ","), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 4)
                box.Add(ctrl, 0)
            self.grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            self.grid.Add(box, 0)
        self.skip_empty = wx.CheckBox(self, label="Skip empty tiles")
        self.skip_empty.SetValue(bool(values.get("skip_empty", 1)))
        self.skip_empty.Bind(wx.EVT_CHECKBOX, lambda e: self._update())
        self.grid.Add((0, 0))
        self.grid.Add(self.skip_empty, 0)
        self.row_animations = wx.CheckBox(self, label="Make a frame for every tile and an animation for every row")
        self.row_animations.SetToolTip("For a sheet of whole sprites with one action per row (idle, run, jump...): "
                                       "each row becomes an animation of its tiles, left to right")
        self.row_animations.SetValue(bool(values.get("row_animations", 0)))
        self.grid.Add((0, 0))
        self.grid.Add(self.row_animations, 0)
        self._finish()
        self._update()

    def values(self) -> Dict[str, int]:
        data = {key: int(ctrl.GetValue()) for key, ctrl in self.spins.items()}
        data["skip_empty"] = int(self.skip_empty.GetValue())
        data["row_animations"] = int(self.row_animations.GetValue())
        return data

    def _update(self) -> None:
        total, kept = self._count(self.values(), self.skip_empty.GetValue())
        skipped = total - kept
        self.preview.SetLabel(f"{kept} tile{'s' if kept != 1 else ''}" + (f" ({skipped} empty skipped)" if skipped else ""))


class DetectDialog(_OptionsDialog):
    def __init__(self, parent: wx.Window, merge_gap: int, existing: int, count: Callable[[int], int]):
        super().__init__(parent, "Detect Sprites",
                         "One module per separate sprite: pixels that touch (also diagonally) belong together. "
                         "Sprites closer than the merge gap become one module.", existing)
        self._count = count
        self.gap = _spin(self, merge_gap, 0, 64)
        self.gap.Bind(wx.EVT_SPINCTRL, lambda e: self._update())
        self.gap.Bind(wx.EVT_TEXT, lambda e: self._update())
        self.grid.Add(wx.StaticText(self, label="Merge gap (px)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.grid.Add(self.gap, 0)
        self._finish()
        self._update()

    def merge_gap(self) -> int:
        return int(self.gap.GetValue())

    def _update(self) -> None:
        found = self._count(self.merge_gap())
        self.preview.SetLabel(f"{found} sprite{'s' if found != 1 else ''} found")


class FolderImportDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, folder: str, count: Callable[[bool], int]):
        super().__init__(parent, title="Add Folder")
        self._count = count
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label=folder), 0, wx.ALL, 12)
        self.recursive = wx.CheckBox(self, label="Include subfolders")
        self.full_modules = wx.CheckBox(self, label="Make each image one module (single-sprite files)")
        root.Add(self.recursive, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        root.Add(self.full_modules, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.preview = dim_text(self)
        root.Add(self.preview, 0, wx.LEFT | wx.RIGHT, 12)
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            root.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(root)
        self.recursive.Bind(wx.EVT_CHECKBOX, lambda e: self._update())
        self._update()
        self.CenterOnParent()

    def _update(self) -> None:
        found = self._count(self.recursive.GetValue())
        self.preview.SetLabel(f"{found} image file{'s' if found != 1 else ''}")

    def values(self) -> Tuple[bool, bool]:
        return self.recursive.GetValue(), self.full_modules.GetValue()
