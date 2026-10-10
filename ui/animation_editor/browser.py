"""Left column: the project's animations (thumbnail, name, length) and the frames library."""

from __future__ import annotations

from typing import Callable, List, Optional

import wx

from models import Animation, Project
from ui.animation_editor import ops
from ui.animation_editor.render import StepRenderer
from ui.components.frame_palette import FramePalette

ROW_H = 46
THUMB = 38
COL_ROW = wx.Colour(40, 41, 45)
COL_ROW_ALT = wx.Colour(44, 45, 49)
COL_ROW_SELECTED = wx.Colour(56, 74, 104)
COL_TEXT = wx.Colour(226, 226, 230)
COL_TEXT_DIM = wx.Colour(140, 142, 150)
COL_DROP = wx.Colour(140, 210, 255)


def _title(parent: wx.Window, text: str) -> wx.StaticText:
    label = wx.StaticText(parent, label=text)
    font = label.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    font.SetPointSize(max(8, font.GetPointSize() - 1))
    label.SetFont(font)
    label.SetForegroundColour(wx.Colour(150, 156, 170))
    return label


class AnimationList(wx.VListBox):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.project: Optional[Project] = None
        self.renderer: Optional[StepRenderer] = None
        self.view: List[Animation] = []
        self.drop_index = -1
        self._press: Optional[wx.Point] = None
        self._press_row = -1
        self._dragging = False
        self._editor: Optional[wx.TextCtrl] = None
        self.on_move: Optional[Callable[[str, int], None]] = None  # (animation id, index in the full list)
        self.on_rename: Optional[Callable[[str, str], None]] = None
        self.SetBackgroundColour(COL_ROW)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda e: self._stop_drag())

    # ------------------------------------------------------------------ VListBox
    def OnMeasureItem(self, n: int) -> int:
        return ROW_H

    def OnDrawBackground(self, dc: wx.DC, rect: wx.Rect, n: int) -> None:
        colour = COL_ROW_SELECTED if self.IsSelected(n) else (COL_ROW_ALT if n % 2 else COL_ROW)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(colour))
        dc.DrawRectangle(rect)

    def OnDrawItem(self, dc: wx.DC, rect: wx.Rect, n: int) -> None:
        if not (0 <= n < len(self.view)) or not self.project:
            return
        anim = self.view[n]
        y = rect.y + (ROW_H - THUMB) // 2
        if anim.aframes and self.renderer:
            bmp = self.renderer.thumbnail(self.project, anim.aframes[0], self.project.active_mapping, THUMB)
            dc.DrawBitmap(bmp, rect.x + 6, y)
        else:
            dc.SetPen(wx.Pen(wx.Colour(70, 72, 80)))
            dc.SetBrush(wx.Brush(wx.Colour(36, 37, 40)))
            dc.DrawRectangle(rect.x + 6, y, THUMB, THUMB)
        x = rect.x + THUMB + 14
        font = self.GetFont()
        dc.SetFont(font)
        dc.SetTextForeground(COL_TEXT)
        dc.DrawText(_fit(dc, anim.name, rect.width - (x - rect.x) - 6), x, rect.y + 6)
        small = wx.Font(font)
        small.SetPointSize(max(7, font.GetPointSize() - 2))
        dc.SetFont(small)
        dc.SetTextForeground(COL_TEXT_DIM)
        meta = f"{ops.describe_length(anim)} · {ops.playback_label(anim.playback_type)}"
        follow = self.project.get_animation(anim.next_animation_id) if anim.next_animation_id else None
        if follow is not None:
            meta += f" → {follow.name}"
        dc.DrawText(_fit(dc, meta, rect.width - (x - rect.x) - 6), x, rect.y + ROW_H - 19)
        if self.drop_index == n or (self.drop_index == len(self.view) and n == len(self.view) - 1):
            line_y = rect.y if self.drop_index == n else rect.y + rect.height - 2
            dc.SetPen(wx.Pen(COL_DROP, 2))
            dc.DrawLine(rect.x, line_y, rect.x + rect.width, line_y)

    # ------------------------------------------------------------------ data
    def set_items(self, project: Project, renderer: StepRenderer, view: List[Animation], selected_id: Optional[str]) -> None:
        self.project = project
        self.renderer = renderer
        self.view = view
        self.SetItemCount(len(view))
        index = next((i for i, a in enumerate(view) if a.id == selected_id), -1)
        self.SetSelection(index)
        self.ensure_visible(index)
        self.Refresh()

    def ensure_visible(self, index: int) -> None:
        if 0 <= index < len(self.view) and not self.IsRowVisible(index):
            self.ScrollToRow(index)

    def selected_animation(self) -> Optional[Animation]:
        index = self.GetSelection()
        return self.view[index] if 0 <= index < len(self.view) else None

    # ------------------------------------------------------------------ rename
    def begin_rename(self) -> None:
        index = self.GetSelection()
        if not (0 <= index < len(self.view)):
            return
        self.ensure_visible(index)
        rect = self.GetItemRect(index)
        x = THUMB + 12
        self._finish_rename(commit=False)
        editor = wx.TextCtrl(self, value=self.view[index].name, pos=(x, rect.y + 4),
                             size=(max(80, rect.width - x - 6), -1), style=wx.TE_PROCESS_ENTER)
        editor.SelectAll()
        editor.SetFocus()
        anim_id = self.view[index].id
        editor.Bind(wx.EVT_TEXT_ENTER, lambda e: self._finish_rename(commit=True, anim_id=anim_id))
        editor.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), wx.CallAfter(self._finish_rename, True, anim_id)))
        editor.Bind(wx.EVT_CHAR_HOOK, lambda e: self._finish_rename(False) if e.GetKeyCode() == wx.WXK_ESCAPE else e.Skip())
        self._editor = editor

    def _finish_rename(self, commit: bool, anim_id: Optional[str] = None) -> None:
        editor, self._editor = self._editor, None
        if not editor:
            return
        name = editor.GetValue().strip()
        editor.Destroy()
        if commit and anim_id and name and self.on_rename:
            self.on_rename(anim_id, name)
        self.SetFocus()

    # ------------------------------------------------------------------ drag to reorder
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self._press = event.GetPosition()
        self._press_row = self.VirtualHitTest(event.GetPosition().y)
        event.Skip()

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if not event.Dragging() or not event.LeftIsDown() or self._press is None or self._press_row < 0:
            event.Skip()
            return
        if not self._dragging:
            if abs(event.GetPosition().y - self._press.y) < 6:
                return
            self._dragging = True
            self.CaptureMouse()
        y = event.GetPosition().y
        row = self.VirtualHitTest(y)
        if row == wx.NOT_FOUND:
            row = len(self.view)
        else:
            rect = self.GetItemRect(row)
            if y > rect.y + rect.height / 2:
                row += 1
        if row != self.drop_index:
            self.drop_index = row
            self.Refresh()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._dragging:
            source = self._press_row
            target = self.drop_index
            self._stop_drag()
            if 0 <= source < len(self.view) and target >= 0 and target not in (source, source + 1) and self.on_move:
                anim = self.view[source]
                anchor = self.view[target] if target < len(self.view) else None
                full = self.project.animations if self.project else []
                index = full.index(anchor) if anchor in full else len(full)
                if anim in full and full.index(anim) < index:
                    index -= 1
                self.on_move(anim.id, index)
            return
        self._press = None
        event.Skip()

    def _stop_drag(self) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        self._dragging = False
        self._press = None
        self.drop_index = -1
        self.Refresh()


def _fit(dc: wx.DC, text: str, width: int) -> str:
    if dc.GetTextExtent(text)[0] <= width:
        return text
    while text and dc.GetTextExtent(text + "…")[0] > width:
        text = text[:-1]
    return text + "…"


class AnimationBrowser(wx.Panel):
    """Animations list with filter and New / Duplicate / Delete."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        self.title = _title(self, "ANIMATIONS")
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Filter")
        self.search.ShowCancelButton(True)
        self.list = AnimationList(self)
        self.btn_new = wx.Button(self, label="+ New", style=wx.BU_EXACTFIT)
        self.btn_dup = wx.Button(self, label="Duplicate", style=wx.BU_EXACTFIT)
        self.btn_del = wx.Button(self, label="Delete", style=wx.BU_EXACTFIT)
        self.btn_new.SetToolTip("New animation after the selected one")
        self.btn_dup.SetToolTip("Duplicate the selected animation")
        self.btn_del.SetToolTip("Delete the selected animation")
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for btn in (self.btn_new, self.btn_dup, self.btn_del):
            buttons.Add(btn, 1, wx.RIGHT, 4)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.title, 0, wx.LEFT | wx.TOP, 8)
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(sizer)

    def filter_text(self) -> str:
        return self.search.GetValue().strip().lower()


class FrameLibrary(wx.Panel):
    """The project's frames, to drag into the sequence."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Filter")
        self.search.ShowCancelButton(True)
        self.palette = FramePalette(self, project)
        self.palette.item_size = (96, 96)  # two columns in the default column width
        hint = wx.StaticText(self, label="Drag into the sequence, or double-click to insert after the current step.")
        hint.SetForegroundColour(wx.Colour(150, 156, 170))
        hint.Wrap(230)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(_title(self, "FRAMES"), 0, wx.LEFT | wx.TOP, 8)
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.palette, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        sizer.Add(hint, 0, wx.ALL, 6)
        self.SetSizer(sizer)
        self.search.Bind(wx.EVT_TEXT, lambda e: self.palette.set_filter(self.search.GetValue()))
        self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.search.SetValue(""))

    def set_project(self, project: Project) -> None:
        self.palette.project = project
        self.search.ChangeValue("")
        self.palette.set_filter("")
        self.refresh()

    def refresh(self) -> None:
        self.palette.invalidate_scale()
        self.palette.refresh_frames()
