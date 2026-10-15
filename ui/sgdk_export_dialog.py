"""File ▸ Export ▸ Mega Drive (SGDK): bake the project into an SGDK project folder and report what the game gets.

The exporter is examples/sgdk/tools/export_sgdk_example.py, the same code as the export_sgdk command line tool; the
built editor carries it inside (see the build specs).
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, List, Optional, Tuple

import wx

import project_check as pc
from models import Project
from ui.check_dialog import LEVEL_LABELS, describe_counts, level_icons
from ui.dpi import px

RUNTIME_FILES = (os.path.join("src", "modsprite.c"), os.path.join("inc", "modsprite.h"))
ID_CHECK_PROJECT = wx.NewIdRef()  # the report's Check Project button ends the dialog with this


def load_exporter() -> Any:
    """The SGDK exporter module (bundled in builds; from the source tree otherwise)."""
    tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "sgdk", "tools")
    if os.path.isdir(tools) and tools not in sys.path:
        sys.path.insert(0, tools)
    return importlib.import_module("export_sgdk_example")


def has_runtime(folder: str) -> bool:
    """Whether the folder holds the Mega Drive runtime the exported data is for."""
    return all(os.path.exists(os.path.join(folder, path)) for path in RUNTIME_FILES)


def mapping_choices(project: Project) -> List[Tuple[str, str]]:
    """(label, the exporter's --mapping value)."""
    return [("All mappings", "all"), ("No mapping (original modules)", "none")] + [
        (f"{m.name} only", m.id) for m in project.mappings
    ]


class MegaDriveExportDialog(wx.Dialog):
    """Where the data goes (the game's SGDK project folder) and which mappings it holds."""

    def __init__(self, parent: Optional[wx.Window], project: Project, folder: str, selector: str):
        super().__init__(parent, title="Export for the Mega Drive (SGDK)", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._choices = mapping_choices(project)
        intro = wx.StaticText(self, label=(
            "The data goes into the game's SGDK project folder: res/gen/modsprite_blob.bin, inc/modsprite_data.h, "
            "src/modsprite_data.c and one line in res/resources.res (the game's other resources stay). The folder "
            "needs the runtime, src/modsprite.c and inc/modsprite.h; the SGDK demo in the source code has it."
        ))
        intro.Wrap(px(560))
        self.folder = wx.DirPickerCtrl(self, path=folder, message="Choose the game's SGDK project folder",
                                       style=wx.DIRP_USE_TEXTCTRL | wx.DIRP_DIR_MUST_EXIST)
        self.folder.SetMinSize((px(560), -1))
        self.mapping = wx.Choice(self, choices=[label for label, _value in self._choices])
        values = [value for _label, value in self._choices]
        self.mapping.SetSelection(values.index(selector) if selector in values else 0)
        grid = wx.FlexGridSizer(2, 2, 8, 10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="Folder"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.folder, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Mappings"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.mapping, 0)
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindowById(wx.ID_OK).SetLabel("Export")
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(intro, 0, wx.EXPAND | wx.ALL, 12)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(sizer)

    def values(self) -> Tuple[str, str]:
        return self.folder.GetPath(), self._choices[max(0, self.mapping.GetSelection())][1]


def short_path(path: str) -> str:
    """The path with the home folder as ~."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def summary_lines(folder: str, summary: dict) -> List[str]:
    steps = summary.get("anim_steps", 0)
    return [
        f"Written to {short_path(folder)}",
        f"{summary.get('animations', 0)} animations ({steps} steps), {summary.get('frames', 0)} frames, "
        f"{summary.get('scenes', 0)} scenes; mappings: {summary.get('mappings', '')}",
        f"{summary.get('tiles', 0)} tiles of video memory, {summary.get('hardware_sprite_pieces', 0)} hardware sprite "
        f"pieces, {summary.get('blob_size_bytes', 0) / 1024:.0f} KB of data",
    ]


class ExportReportDialog(wx.Dialog):
    """What an export wrote and every issue the game would notice; Check Project ends it with ID_CHECK_PROJECT. The
    Mega Drive's by default; the SNES export passes its title and summary lines."""

    def __init__(self, parent: Optional[wx.Window], folder: str, result: Any, title: str = "Mega Drive Export",
                 lines: Optional[List[str]] = None):
        super().__init__(parent, title=title, size=(px(820), px(460)), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.folder = folder
        problems = [issue for issue in result.issues if issue.level != pc.INFO]
        headline = "Exported." if not problems else f"Exported, with {describe_counts(problems).split('.')[0]}."
        head = wx.StaticText(self, label=headline)
        head.SetFont(head.GetFont().Bold())
        self.lines = wx.StaticText(self, label="\n".join(lines if lines is not None else summary_lines(folder, result.summary)))
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL)
        self._icons = level_icons()
        self.list.SetImageList(self._icons, wx.IMAGE_LIST_SMALL)
        self.list.InsertColumn(0, "", width=px(100))
        self.list.InsertColumn(1, "", width=px(680))
        levels = list(LEVEL_LABELS)
        for row, issue in enumerate(result.issues):
            self.list.InsertItem(row, LEVEL_LABELS[issue.level], levels.index(issue.level))
            self.list.SetItem(row, 1, issue.text)
        show = wx.Button(self, label="Show Folder")
        close = wx.Button(self, wx.ID_OK, label="Close")
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(show)
        buttons.AddStretchSpacer(1)
        if problems:
            check = wx.Button(self, ID_CHECK_PROJECT, label="Check Project...")
            check.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(ID_CHECK_PROJECT))
            buttons.Add(check, 0, wx.RIGHT, 6)
        buttons.Add(close)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(head, 0, wx.ALL, 10)
        sizer.Add(self.lines, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(sizer)
        show.Bind(wx.EVT_BUTTON, lambda e: wx.LaunchDefaultApplication(self.folder))
        self.list.Bind(wx.EVT_SIZE, self._on_list_size)

    def _on_list_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        width = self.list.GetClientSize().width - self.list.GetColumnWidth(0) - 4
        if width > 100:
            self.list.SetColumnWidth(1, width)
