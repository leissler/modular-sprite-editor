"""File ▸ Export ▸ Mega Drive (SGDK), SNES (PVSnesLib), ...: bake the project into a game's project folder for a console
with an export (console_exports.py) and report what the game gets.

One dialog serves every console: the folder, the mappings and, where the export bakes for one of the console's setups
(the SNES's two sprite sizes), the setups with the tiles each needs (the budget model counts them as the export stores
them), and where its runtime can stream (``ConsoleExport.modes``), how to store the sprites. Below them it shows what
each way would cost, measured on the project for the chosen mappings and setup (export_modes). The exporters are
examples/<console>/tools/export_<console>.py, the same code as their command lines; the built editor carries them
inside (the editor specs bundle every one console_exports lists).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import wx

import consoles
import export_modes
import project_check as pc
from console_bake import resolve_mappings
from console_exports import ConsoleExport
from models import Project
from ui.check_dialog import LEVEL_LABELS, describe_counts, level_icons
from ui.dpi import px

ID_CHECK_PROJECT = wx.NewIdRef()  # the report's Check Project button ends the dialog with this
MODE_COLUMNS = ("Stored as", "Video memory", "Cartridge", "Hardware sprites", "Busiest line", "Upload a step")
SCENE_COLUMN = "Busiest scene line"


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


def line_limit(export: ConsoleExport, project: Project, setup_key: str) -> int:
    """The hardware sprites a line can show in the setup (an export without setups: the project's, if it is made for
    the console, else the console's first)."""
    console = export.console
    if setup_key:
        setup = console.setup(setup_key)
    else:
        target, setup = consoles.target(project.console, project.console_setup)
        if target is not console:
            setup = console.budgets[0]
    return (console.mode(setup.mode) or console.modes[0]).sprites_per_line


def mode_rows(costs: Sequence[export_modes.Costs], limit: int, scenes: bool, chosen: str = "parts") -> List[List[str]]:
    """A row of MODE_COLUMNS (and SCENE_COLUMN with ``scenes``) per way to store the sprites, the ``chosen`` one marked
    as the one exported."""
    rows = []
    for cost in costs:
        each = "a step" if cost.shown == "animation steps" else "a frame"
        row = [
            cost.mode.name + (" (exported)" if cost.mode.key == chosen else ""),
            f"{cost.video_tiles} tiles" + (" a player" if cost.mode.streamed else ""),
            f"{cost.cartridge_bytes / 1024:.1f} KB of tiles",
            f"{cost.sprites_avg:.1f} {each}, {cost.sprites_max} at most",
            f"{cost.line_max} of {limit}",
            f"{cost.upload_avg:.0f} B, {cost.upload_max} B at most" if cost.mode.streamed else "nothing",
        ]
        if scenes:
            row.append(f"{cost.scene_line_max} of {limit}")
        rows.append(row)
    return rows


class ConsoleExportDialog(wx.Dialog):
    """Where the data goes (the game's project folder), which mappings it holds and, for an export with setups, the
    setup (``tiles``: what the project needs with each); and what other ways to store the sprites would cost."""

    def __init__(self, parent: Optional[wx.Window], export: ConsoleExport, project: Project, folder: str,
                 selector: str, setup_key: str = "", tiles: Optional[Dict[str, int]] = None, mode: str = "parts"):
        super().__init__(parent, title=f"Export for the {export.title}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._export, self._project = export, project
        self._measured: Dict[Tuple[str, str], Any] = {}  # (mappings, setup) -> its costs, or why they are not known
        self.costs: List[export_modes.Costs] = []  # the ways measured for the chosen mappings and setup
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
        self._modes = [m for m in export_modes.MODES if m.key in export.modes] if len(export.modes) > 1 else []
        grid = wx.FlexGridSizer(2 + bool(self._setups) + bool(self._modes), 2, 8, 10)
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
            self.setup.Bind(wx.EVT_CHOICE, lambda event: self._show_costs())
        self.mapping.Bind(wx.EVT_CHOICE, lambda event: self._show_costs())
        self.mode: Optional[wx.Choice] = None
        if self._modes:
            self.mode = wx.Choice(self, choices=[m.name for m in self._modes])
            keys = [m.key for m in self._modes]
            self.mode.SetSelection(keys.index(mode) if mode in keys else 0)
            grid.Add(wx.StaticText(self, label="Store as"), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.mode, 0)
            self.mode.Bind(wx.EVT_CHOICE, lambda event: self._show_costs())

        title = wx.StaticText(self, label="Ways to store the sprites")
        title.SetFont(title.GetFont().Bold())
        how = ("Streamed, video memory holds only what each player shows, and a step uploads its tiles when it starts; "
               "the game draws each thing on screen through a slot of its own (modsprite.h). Whole frames need the "
               "fewest hardware sprites and the most cartridge space.")
        note = wx.StaticText(self, label=(
            ("Measured on this project. " if self._modes else
             "Measured on this project, for comparison: the export stores parts and keeps every tile in video "
             "memory. ") + how))
        note.Wrap(px(560))
        columns = list(MODE_COLUMNS) + ([SCENE_COLUMN] if project.timeline_scenes else [])
        table = wx.FlexGridSizer(len(export_modes.MODES) + 1, len(columns), px(4), px(14))
        for name in columns:
            heading = wx.StaticText(self, label=name)
            heading.SetFont(heading.GetFont().Bold())
            table.Add(heading)
        self.mode_cells = [[wx.StaticText(self) for _column in columns] for _mode in export_modes.MODES]
        for row in self.mode_cells:
            for cell in row:
                table.Add(cell)
        self._show_costs(fit=False)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindow(wx.ID_OK).SetLabel("Export")  # this dialog's button (FindWindowById searches every window)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(intro, 0, wx.EXPAND | wx.ALL, 12)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        sizer.Add(title, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        sizer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        sizer.Add(table, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(sizer)

    def values(self) -> Tuple[str, str, str, str]:
        """(folder, the exporter's --mapping value, the setup's key: "" for an export without setups, the mode:
        "parts" for an export with one way to store the sprites)."""
        setup = self._setups[max(0, self.setup.GetSelection())].key if self.setup is not None else ""
        mode = self._modes[max(0, self.mode.GetSelection())].key if self.mode is not None else "parts"
        return self.folder.GetPath(), self._choices[max(0, self.mapping.GetSelection())][1], setup, mode

    def _show_costs(self, fit: bool = True) -> None:
        """Each way to store the sprites, measured for the chosen mappings and setup (once each)."""
        _folder, selector, setup_key, mode = self.values()
        found = self._measured.get((selector, setup_key))
        if found is None:
            try:
                with wx.BusyCursor():
                    found = export_modes.measure(self._project, self._export, setup_key,
                                                 resolve_mappings(self._project, selector))
            except Exception as exc:  # measuring only informs: the export goes on without it
                found = f"Not measured: {exc}"
            self._measured[(selector, setup_key)] = found
        self.costs = found if isinstance(found, list) else []
        width = len(self.mode_cells[0])
        if self.costs:
            rows = mode_rows(self.costs, line_limit(self._export, self._project, setup_key), width > len(MODE_COLUMNS),
                             mode)
        else:
            rows = [[str(found)] + [""] * (width - 1)] + [[""] * width for _row in self.mode_cells[1:]]
        for cells, row in zip(self.mode_cells, rows):
            for cell, text in zip(cells, row):
                cell.SetLabel(text)
        if fit:
            self.Layout()
            self.Fit()


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
