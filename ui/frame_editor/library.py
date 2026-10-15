"""Frames library: modules (by image) and frames, to drag onto the stage or double-click to add."""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import wx

from models import Project
from ui.components.frame_palette import FramePalette
from ui.components.module_palette import SHAPES_KEY, ModulePalette
from ui.components.inspector_kit import fit_choice
from ui.components.thumb_list import title_label
from ui.module_editor import ops as module_ops
from ui.dpi import px
from ui.theme import T


class PartLibrary(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.on_add: Optional[Callable[[str, str], None]] = None  # (ref type, id): double-click
        self._sheet_keys: List[Optional[str]] = [None]

        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Filter")
        self.search.ShowCancelButton(True)
        self.book = wx.Notebook(self)
        modules_page = wx.Panel(self.book)
        self.sheet_choice = wx.Choice(modules_page)
        self.sheet_choice.SetToolTip("Show the modules of one image")
        self.modules = ModulePalette(modules_page, project, item_size=60)
        page_sizer = wx.BoxSizer(wx.VERTICAL)
        page_sizer.Add(self.sheet_choice, 0, wx.EXPAND | wx.ALL, 4)
        page_sizer.Add(self.modules, 1, wx.EXPAND)
        modules_page.SetSizer(page_sizer)
        self.frames = FramePalette(self.book, project)
        self.frames.item_size = (px(72), px(72))
        self.book.AddPage(modules_page, "Modules")
        self.book.AddPage(self.frames, "Frames")
        hint = wx.StaticText(self, label="Drag onto the stage, or double-click to add at the origin.")
        T.style(hint, fg="hint")
        hint.Wrap(px(240))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(title_label(self, "LIBRARY"), 0, wx.LEFT | wx.TOP, 8)
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        sizer.Add(hint, 0, wx.ALL, 6)
        self.SetSizer(sizer)

        self.search.Bind(wx.EVT_TEXT, lambda e: self._apply_filter())
        self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.search.SetValue(""))
        self.sheet_choice.Bind(wx.EVT_CHOICE, lambda e: self.modules.set_sheet(self._sheet_keys[max(0, self.sheet_choice.GetSelection())]))
        self.modules.on_module_double_click = lambda module_id: self.on_add and self.on_add("module", module_id)
        self.frames.on_frame_double_click = lambda frame_id: self.on_add and self.on_add("frame", frame_id)

    def _apply_filter(self) -> None:
        text = self.search.GetValue()
        self.modules.set_filter(text)
        self.frames.set_filter(text)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.modules.project = project
        self.frames.project = project
        self.search.ChangeValue("")
        self.modules.filter_text = ""
        self.frames.filter_text = ""
        self.refresh()

    def refresh(self) -> None:
        current = self._sheet_keys[self.sheet_choice.GetSelection()] if self.sheet_choice.GetSelection() >= 0 else None
        self._sheet_keys = [None] + [img.id for img in self.project.images]
        labels = ["All images"] + [module_ops.image_label(img) for img in self.project.images]
        if any(m.type != "MD_IMAGE" for m in self.project.modules):
            self._sheet_keys.append(SHAPES_KEY)
            labels.append("Shapes")
        self.sheet_choice.SetItems(labels)
        fit_choice(self.sheet_choice)
        index = self._sheet_keys.index(current) if current in self._sheet_keys else 0
        self.sheet_choice.SetSelection(index)
        self.modules.sheet = self._sheet_keys[index]
        self.modules.refresh_modules()
        self.frames.refresh_frames()

    def picked(self) -> Optional[Tuple[str, str]]:
        """What is selected on the visible page: ("module" | "frame", id)."""
        if self.book.GetSelection() == 0 and self.modules.selected_module_id:
            return ("module", self.modules.selected_module_id)
        if self.book.GetSelection() == 1 and self.frames.selected_frame_id:
            return ("frame", self.frames.selected_frame_id)
        return None
