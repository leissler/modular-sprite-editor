"""Tools ▸ Check Project: what exports would drop, show differently or get wrong, with Go to and Fix."""

from __future__ import annotations

from typing import Callable, List, Optional

import wx

import console_exports
import project_check as pc
from models import Project
from ui.dpi import px

LEVEL_LABELS = {pc.ERROR: "Error", pc.WARNING: "Warning", pc.INFO: "Note"}
LEVEL_COLOURS = {pc.ERROR: (232, 88, 88), pc.WARNING: (236, 184, 64), pc.INFO: (140, 146, 160)}


def level_icons() -> wx.ImageList:
    """A coloured dot per level, in LEVEL_LABELS order."""
    icons = wx.ImageList(px(12), px(12), mask=False)  # opaque bitmaps: a masked list costs ~6 ms per Add on macOS
    for level in LEVEL_LABELS:
        bmp = wx.Bitmap(px(12), px(12))
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOX)))
        dc.Clear()
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(wx.Colour(*LEVEL_COLOURS[level])))
        dc.DrawCircle(px(6), px(6), px(5))
        dc.SelectObject(wx.NullBitmap)
        icons.Add(bmp)
    return icons


def memory_issues(project: Project, mode: str = "parts") -> List[pc.Issue]:
    """Video memory as the export for the project's console (with every mapping) fills it, once it gets tight (the
    export report and the budget readout always show it): the console's tile check (console_exports), or for a
    streamed ``mode`` (the one chosen last for the project) its slots; nothing for a console without an export."""
    import hardware_budget
    from ui.canvas import BUDGET

    export = console_exports.for_console(project.console)
    profile = hardware_budget.project_profile(project)
    if export is None or not profile.vram_tiles:
        return []
    if mode != "parts" and mode in export.modes:
        import export_modes

        costs = export_modes.measure_mode(project, export, export_modes.mode_by_key(mode),
                                          profile.key if export.setups else "")
        return [issue for issue in export.stream_issues(costs.video_tiles, costs.scene_video_tiles,
                                                        costs.upload_cost_max)
                if issue.level != pc.INFO]
    issue = export.tile_issue(BUDGET.export_tiles(project, [None] + list(project.mappings), profile))
    return [issue] if issue.level != pc.INFO else []


def describe_counts(issues: List[pc.Issue]) -> str:
    found = pc.counts(issues)
    if not any(found.values()):
        return "No problems found: exports will show what the editor shows."
    bits = []
    for level, word in ((pc.ERROR, "error"), (pc.WARNING, "warning"), (pc.INFO, "note")):
        if found[level]:
            bits.append(f"{found[level]} {word}{'s' if found[level] != 1 else ''}")
    return ", ".join(bits) + ". Errors lose something in exports, warnings look different on the console."


class CheckProjectDialog(wx.Dialog):
    """Lists the issues; Go to closes the dialog and shows the item (``target``), Fix repairs in place."""

    def __init__(self, parent: Optional[wx.Window], project: Project, after_fix: Callable[[str], None],
                 export_mode: str = "parts"):
        super().__init__(parent, title="Check Project", size=(px(860), px(540)),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.project = project
        self.export_mode = export_mode  # how the export for the project's console stores the sprites
        self._after_fix = after_fix
        self.issues: List[pc.Issue] = []
        self.target: Optional[pc.Target] = None  # the item Go to chose

        self.summary = wx.StaticText(self)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL)
        self._icons = level_icons()
        self.list.SetImageList(self._icons, wx.IMAGE_LIST_SMALL)
        self.list.InsertColumn(0, "", width=px(100))
        self.list.InsertColumn(1, "", width=px(700))
        self.details = wx.StaticText(self, style=wx.ST_NO_AUTORESIZE)
        self.details.SetMinSize((-1, px(54)))

        self.btn_go = wx.Button(self, label="Go to")
        self.btn_fix = wx.Button(self, label="Fix")
        self.btn_fix_all = wx.Button(self, label="Fix All")
        self.btn_again = wx.Button(self, label="Check Again")
        btn_close = wx.Button(self, wx.ID_CANCEL, label="Close")

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for button in (self.btn_go, self.btn_fix):
            buttons.Add(button, 0, wx.RIGHT, 6)
        buttons.AddStretchSpacer(1)
        for button in (self.btn_fix_all, self.btn_again, btn_close):
            buttons.Add(button, 0, wx.LEFT, 6)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.summary, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.details, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(sizer)

        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._show_selected())
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda e: self._show_selected())
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.go_to())
        self.list.Bind(wx.EVT_SIZE, self._on_list_size)
        self.btn_go.Bind(wx.EVT_BUTTON, lambda e: self.go_to())
        self.btn_fix.Bind(wx.EVT_BUTTON, lambda e: self.fix_selected())
        self.btn_fix_all.Bind(wx.EVT_BUTTON, lambda e: self.fix_everything())
        self.btn_again.Bind(wx.EVT_BUTTON, lambda e: self.refresh())
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.refresh()

    # ------------------------------------------------------------------ list
    def refresh(self) -> None:
        self.issues = sorted(pc.check_project(self.project) + memory_issues(self.project, self.export_mode),
                             key=lambda issue: pc.LEVEL_ORDER[issue.level])
        self.list.DeleteAllItems()
        levels = list(LEVEL_LABELS)
        for row, issue in enumerate(self.issues):
            self.list.InsertItem(row, LEVEL_LABELS[issue.level], levels.index(issue.level))
            self.list.SetItem(row, 1, issue.text)
        self.summary.SetLabel(describe_counts(self.issues))
        fixable = sum(1 for issue in self.issues if issue.fix)
        self.btn_fix_all.SetLabel(f"Fix All ({fixable})" if fixable else "Fix All")
        self.btn_fix_all.Enable(bool(fixable))
        if self.issues:
            self.list.Select(0)
            self.list.Focus(0)
        self._show_selected()
        self.Layout()

    def selected(self) -> Optional[pc.Issue]:
        row = self.list.GetFirstSelected()
        return self.issues[row] if 0 <= row < len(self.issues) else None

    def _show_selected(self) -> None:
        issue = self.selected()
        self.details.SetLabel(issue.text if issue else "")
        self._wrap_details()
        self.btn_go.Enable(bool(issue and issue.target))
        label = pc.FIXES[issue.fix][0] if issue and issue.fix in pc.FIXES else "Fix"
        self.btn_fix.SetLabel(label)
        self.btn_fix.Enable(bool(issue and issue.fix in pc.FIXES))
        self.Layout()

    def _wrap_details(self) -> None:
        width = self.GetClientSize().width - 20
        if width > 50:
            self.details.Wrap(width)

    def _on_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        wx.CallAfter(self._wrap_details)

    def _on_list_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        width = self.list.GetClientSize().width - self.list.GetColumnWidth(0) - 4
        if width > 100:
            self.list.SetColumnWidth(1, width)

    # ------------------------------------------------------------------ actions
    def go_to(self) -> None:
        issue = self.selected()
        if issue is None or issue.target is None:
            return
        self.target = issue.target
        if self.IsModal():
            self.EndModal(wx.ID_OK)

    def fix_selected(self) -> int:
        issue = self.selected()
        if issue is None or issue.fix not in pc.FIXES:
            return 0
        changed = pc.fix(self.project, issue)
        self._after_fix(f"{pc.FIXES[issue.fix][0]}: {changed} change{'s' if changed != 1 else ''}")
        self.refresh()
        return changed

    def fix_everything(self) -> int:
        changed = pc.fix_all(self.project, self.issues)
        self._after_fix(f"Fixed {changed} thing{'s' if changed != 1 else ''}")
        self.refresh()
        return changed
