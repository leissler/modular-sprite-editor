"""Library: everything that can be placed into a scene (animations, frames, modules)."""

from __future__ import annotations

from typing import Callable, List, Optional

import wx

from models import Project
from ui.components.frame_palette import FramePalette
from ui.frame_editor import ModulePalette
from ui.utils import ThumbnailGenerator


class AnimationPalette(wx.ListCtrl):
    """Animations shown with their first frame as the icon."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, style=wx.LC_ICON | wx.LC_SINGLE_SEL | wx.LC_AUTOARRANGE)
        self.project = project
        self.generator = ThumbnailGenerator()
        self.image_list = wx.ImageList(96, 96, mask=False)  # opaque thumbnails; a mask costs ~6 ms per Add on macOS
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.animation_ids: List[str] = []
        self.filter_text = ""
        self.on_activate: Optional[Callable[[str], None]] = None
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self._on_begin_drag)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activated)

    def set_filter(self, text: str) -> None:
        self.filter_text = (text or "").strip().lower()
        self.refresh_animations()

    def refresh_animations(self) -> None:
        self.DeleteAllItems()
        self.image_list = wx.ImageList(96, 96, mask=False)  # opaque thumbnails; a mask costs ~6 ms per Add on macOS
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.animation_ids = []
        self.generator.clear_cache()
        for anim in self.project.animations:
            if self.filter_text and self.filter_text not in anim.name.lower():
                continue
            preview = self.project.get_frame(anim.aframes[0].frame_id) if anim.aframes else None
            if preview:
                bmp = self.generator.render_thumbnail(self.project, preview, 96, 96, mapping=self.project.active_mapping)
            else:
                bmp = wx.Bitmap(96, 96)
                dc = wx.MemoryDC(bmp)
                dc.SetBackground(wx.Brush(wx.Colour(50, 50, 50)))
                dc.Clear()
                dc.SetTextForeground(wx.Colour(180, 180, 180))
                dc.DrawLabel("Empty", wx.Rect(0, 0, 96, 96), alignment=wx.ALIGN_CENTER)
                dc.SelectObject(wx.NullBitmap)
            index = self.InsertItem(self.GetItemCount(), anim.name, self.image_list.Add(bmp))
            self.SetItemData(index, index)
            self.animation_ids.append(anim.id)

    def _on_activated(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.animation_ids) and self.on_activate:
            self.on_activate(self.animation_ids[idx])

    def _on_begin_drag(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.animation_ids):
            source = wx.DropSource(self)
            source.SetData(wx.TextDataObject(f"ANIMATION:{self.animation_ids[idx]}"))
            source.DoDragDrop(wx.Drag_CopyOnly)


class SceneLibrary(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.on_add: Optional[Callable[[str, str], None]] = None  # (source_type, source_id)

        sizer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label="LIBRARY")
        font = title.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        font.SetPointSize(max(8, font.GetPointSize() - 1))
        title.SetFont(font)
        title.SetForegroundColour(wx.Colour(150, 156, 170))
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Filter")
        self.search.ShowCancelButton(True)
        self.book = wx.Notebook(self)
        self.animations = AnimationPalette(self.book, project)
        self.frames = FramePalette(self.book, project)
        self.modules = ModulePalette(self.book, project)
        self.book.AddPage(self.animations, "Animations")
        self.book.AddPage(self.frames, "Frames")
        self.book.AddPage(self.modules, "Modules")
        hint = wx.StaticText(self, label="Drag onto the stage, or double-click to add it in the middle of the view.")
        hint.SetForegroundColour(wx.Colour(150, 156, 170))
        hint.Wrap(220)
        sizer.Add(title, 0, wx.LEFT | wx.TOP, 8)
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        sizer.Add(hint, 0, wx.ALL, 6)
        self.SetSizer(sizer)

        self.search.Bind(wx.EVT_TEXT, lambda e: self._apply_filter())
        self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.search.SetValue(""))
        self.animations.on_activate = lambda anim_id: self._add("animation", anim_id)
        self.frames.on_frame_double_click = lambda frame_id: self._add("frame", frame_id)
        self.modules.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_module_activated)

    def _add(self, source_type: str, source_id: str) -> None:
        if self.on_add:
            self.on_add(source_type, source_id)

    def _on_module_activated(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.modules.module_ids):
            self._add("module", self.modules.module_ids[idx])

    def _apply_filter(self) -> None:
        text = self.search.GetValue()
        self.animations.set_filter(text)
        self.frames.set_filter(text)
        self.modules.set_filter(text)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.animations.project = project
        self.frames.project = project
        self.modules.project = project
        self.refresh()

    def refresh(self) -> None:
        self.animations.refresh_animations()
        self.frames.refresh_frames()
        self.modules.refresh_modules()
