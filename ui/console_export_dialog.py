"""File ▸ Export ▸ Mega Drive (SGDK), SNES (PVSnesLib), ...: bake the project into a game's project folder for a console
with an export (console_exports.py) and report what the game gets.

One dialog serves every console: the folder, the mappings and, where the export bakes for one of the console's setups
(the SNES's two sprite sizes), the setups with the tiles each needs (the budget model counts them as the export stores
them). The exporters are examples/<console>/tools/export_<console>.py, the same code as their command lines; the built
editor carries them inside (the editor specs bundle every one console_exports lists).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import wx

import consoles
import project_check as pc
from console_exports import ConsoleExport
from models import Project
from ui.check_dialog import LEVEL_LABELS, describe_counts, level_icons
from ui.dpi import px

ID_CHECK_PROJECT = wx.NewIdRef()  # the report's Check Project button ends the dialog with this


def mapping_choices(project: Project) -> List[Tuple[str, str]]:
    """(label, the exporter's --mapping value)."""
    return [("All mappings", "all"), ("No mapping (original modules)", "none")] + [
        (f"{m.name} only", m.id) for m in project.mappings
    ]


def default_setup(export: ConsoleExport, project: Project, remembered: str) -> str:
    """The setup to offer first: the project's when it is made for the console, else the last export's, else the
    console's first (the SNES's 8×8 and 16×16)."""
    console, setup = consoles.target(project.console, project.console_setup)
    if console is export.console:
        return setup.key
    keys = [s.key for s in export.console.budgets]
    return remembered if remembered in keys else keys[0]


def setup_label(export: ConsoleExport, setup: consoles.BudgetSetup, tiles: Optional[int]) -> str:
    """"8×8 and 16×16 (300 of 512 tiles)": the setup and what the project needs with it."""
    name = setup.name.split(", ", 1)[-1].replace(" sprites", "")
    capacity = export.console.sprites.tiles
    if tiles is None:
        return name
    if tiles > capacity:
        return f"{name} ({tiles} tiles: too many)"
    return f"{name} ({tiles} of {'~' if export.tiles_about else ''}{capacity} tiles)"


class ConsoleExportDialog(wx.Dialog):
    """Where the data goes (the game's project folder), which mappings it holds and, for an export with setups, the
    setup (``tiles``: what the project needs with each)."""

    def __init__(self, parent: Optional[wx.Window], export: ConsoleExport, project: Project, folder: str,
                 selector: str, setup_key: str = "", tiles: Optional[Dict[str, int]] = None):
        super().__init__(parent, title=f"Export for the {export.title}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._choices = mapping_choices(project)
        self._setups = list(export.console.budgets) if export.setups else []
        intro = wx.StaticText(self, label=export.intro_text())
        intro.Wrap(px(560))
        self.folder = wx.DirPickerCtrl(self, path=folder, message=f"Choose the game's {export.sdk} project folder",
                                       style=wx.DIRP_USE_TEXTCTRL | wx.DIRP_DIR_MUST_EXIST)
        self.folder.SetMinSize((px(560), -1))
        self.mapping = wx.Choice(self, choices=[label for label, _value in self._choices])
        values = [value for _label, value in self._choices]
        self.mapping.SetSelection(values.index(selector) if selector in values else 0)
        grid = wx.FlexGridSizer(3 if self._setups else 2, 2, 8, 10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="Folder"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.folder, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Mappings"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.mapping, 0)
        self.setup: Optional[wx.Choice] = None
        if self._setups:
            self.setup = wx.Choice(self, choices=[setup_label(export, s, (tiles or {}).get(s.key)) for s in self._setups])
            keys = [s.key for s in self._setups]
            self.setup.SetSelection(keys.index(setup_key) if setup_key in keys else 0)
            grid.Add(wx.StaticText(self, label=export.setups), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.setup, 0)
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindowById(wx.ID_OK).SetLabel("Export")
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(intro, 0, wx.EXPAND | wx.ALL, 12)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(sizer)

    def values(self) -> Tuple[str, str, str]:
        """(folder, the exporter's --mapping value, the setup's key: "" for an export without setups)."""
        setup = self._setups[max(0, self.setup.GetSelection())].key if self.setup is not None else ""
        return self.folder.GetPath(), self._choices[max(0, self.mapping.GetSelection())][1], setup


def short_path(path: str) -> str:
    """The path with the home folder as ~."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def summary_lines(export: ConsoleExport, folder: str, summary: Dict[str, Any]) -> List[str]:
    steps = summary.get("anim_steps", 0)
    return [
        f"Written to {short_path(folder)}",
        f"{summary.get('animations', 0)} animations ({steps} steps), {summary.get('frames', 0)} frames, "
        f"{summary.get('scenes', 0)} scenes; mappings: {summary.get('mappings', '')}",
        export.report_line(summary),
    ]


class ExportReportDialog(wx.Dialog):
    """What an export wrote and every issue the game would notice; Check Project ends it with ID_CHECK_PROJECT."""

    def __init__(self, parent: Optional[wx.Window], export: ConsoleExport, folder: str, result: Any):
        super().__init__(parent, title=f"{export.name} Export", size=(px(820), px(460)),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.folder = folder
        problems = [issue for issue in result.issues if issue.level != pc.INFO]
        headline = "Exported." if not problems else f"Exported, with {describe_counts(problems).split('.')[0]}."
        head = wx.StaticText(self, label=headline)
        head.SetFont(head.GetFont().Bold())
        self.lines = wx.StaticText(self, label="\n".join(summary_lines(export, folder, result.summary)))
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
