"""List rows with a thumbnail, a title and a detail line: rename in place, drag to reorder or out.

The browsers of the Modules, Frames and Mappings tabs use it (the Animations tab has its own, older
variant with the same look).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

import wx
from ui.dpi import px

COL_ROW = wx.Colour(40, 41, 45)
COL_ROW_ALT = wx.Colour(44, 45, 49)
COL_ROW_SELECTED = wx.Colour(56, 74, 104)
COL_TEXT = wx.Colour(226, 226, 230)
COL_TEXT_DIM = wx.Colour(140, 142, 150)
COL_WARN = wx.Colour(255, 140, 120)
COL_ACCENT = wx.Colour(255, 176, 64)
COL_DROP = wx.Colour(140, 210, 255)


@dataclass
class Row:
    id: str
    title: str
    meta: str = ""
    warn: bool = False       # detail line in red (missing file, broken reference)
    dim: bool = False        # title greyed (unused)
    badge: str = ""          # short text at the right edge (e.g. "×12", "●")


def title_label(parent: wx.Window, text: str) -> wx.StaticText:
    label = wx.StaticText(parent, label=text)
    font = label.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    font.SetPointSize(max(8, font.GetPointSize() - 1))
    label.SetFont(font)
    label.SetForegroundColour(wx.Colour(150, 156, 170))
    return label


def fit_text(dc: wx.DC, text: str, width: int) -> str:
    if dc.GetTextExtent(text)[0] <= width:
        return text
    while text and dc.GetTextExtent(text + "…")[0] > width:
        text = text[:-1]
    return text + "…"


class ThumbList(wx.VListBox):
    def __init__(self, parent: wx.Window, row_h: int = 46, thumb: int = 38, multiple: bool = False, reorder: bool = False):
        style = wx.BORDER_NONE | wx.WANTS_CHARS | (wx.LB_MULTIPLE if multiple else 0)
        super().__init__(parent, style=style)
        self.row_h = px(row_h)  # row_h and thumb at 100 % display scaling
        self.thumb = px(thumb)
        self.multiple = multiple
        self.reorder = reorder
        self.rows: List[Row] = []
        self.drop_index = -1
        self._press: Optional[wx.Point] = None
        self._press_row = -1
        self._dragging = False
        self._editor: Optional[wx.TextCtrl] = None

        # Callbacks (set by the owner)
        self.thumbnail: Optional[Callable[[str, int], Optional[wx.Bitmap]]] = None
        self.on_move: Optional[Callable[[str, Optional[str]], None]] = None   # (row id, insert before row id or None = end)
        self.on_rename: Optional[Callable[[str, str], None]] = None
        self.drag_out_text: Optional[Callable[[str], Optional[str]]] = None   # text for an OS drag (e.g. onto a canvas)

        self.SetBackgroundColour(COL_ROW)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda e: self._stop_drag())

    # ------------------------------------------------------------------ VListBox
    def OnMeasureItem(self, n: int) -> int:
        return self.row_h

    def OnDrawBackground(self, dc: wx.DC, rect: wx.Rect, n: int) -> None:
        colour = COL_ROW_SELECTED if self.IsSelected(n) else (COL_ROW_ALT if n % 2 else COL_ROW)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(colour))
        dc.DrawRectangle(rect)

    def OnDrawItem(self, dc: wx.DC, rect: wx.Rect, n: int) -> None:
        if not (0 <= n < len(self.rows)):
            return
        row = self.rows[n]
        x = rect.x + px(6)
        if self.thumb > 0:
            y = rect.y + (self.row_h - self.thumb) // 2
            bmp = self.thumbnail(row.id, self.thumb) if self.thumbnail else None
            if bmp is not None and bmp.IsOk():
                dc.DrawBitmap(bmp, x, y)
            else:
                dc.SetPen(wx.Pen(wx.Colour(70, 72, 80)))
                dc.SetBrush(wx.Brush(wx.Colour(36, 37, 40)))
                dc.DrawRectangle(x, y, self.thumb, self.thumb)
            x += self.thumb + px(8)
        right = rect.x + rect.width - px(6)
        font = self.GetFont()
        small = wx.Font(font)
        small.SetPointSize(max(7, font.GetPointSize() - 2))
        if row.badge:
            dc.SetFont(small)
            dc.SetTextForeground(COL_ACCENT)
            bw = dc.GetTextExtent(row.badge)[0]
            dc.DrawText(row.badge, right - bw, rect.y + px(6))
            right -= bw + px(6)
        dc.SetFont(font)
        title_h = dc.GetTextExtent("Ag")[1]
        dc.SetFont(small)
        meta_h = dc.GetTextExtent("Ag")[1] if row.meta else 0
        top = rect.y + (self.row_h - (title_h + (meta_h + 1 if row.meta else 0))) // 2
        dc.SetFont(font)
        dc.SetTextForeground(COL_TEXT_DIM if row.dim else COL_TEXT)
        dc.DrawText(fit_text(dc, row.title, right - x), x, top)
        if row.meta:
            dc.SetFont(small)
            dc.SetTextForeground(COL_WARN if row.warn else COL_TEXT_DIM)
            dc.DrawText(fit_text(dc, row.meta, rect.x + rect.width - px(6) - x), x, top + title_h + 1)
        if self.drop_index == n or (self.drop_index == len(self.rows) and n == len(self.rows) - 1):
            line_y = rect.y if self.drop_index == n else rect.y + rect.height - 2
            dc.SetPen(wx.Pen(COL_DROP, 2))
            dc.DrawLine(rect.x, line_y, rect.x + rect.width, line_y)

    # ------------------------------------------------------------------ data
    def set_rows(self, rows: Sequence[Row], selected_ids: Sequence[str] = ()) -> None:
        self.rows = list(rows)
        self.SetItemCount(len(self.rows))
        self.set_selected(selected_ids)
        self.Refresh()

    def set_selected(self, selected_ids: Sequence[str], ensure_visible: bool = True) -> None:
        wanted = set(selected_ids)
        indices = [i for i, row in enumerate(self.rows) if row.id in wanted]
        if self.multiple:
            self.DeselectAll()
            for i in indices:
                self.Select(i, True)
        else:
            self.SetSelection(indices[0] if indices else -1)
        if ensure_visible and indices:
            self.ensure_visible(indices[0])
        self.Refresh()

    def selected_ids(self) -> List[str]:
        if not self.multiple:
            index = self.GetSelection()
            return [self.rows[index].id] if 0 <= index < len(self.rows) else []
        ids = []
        item, cookie = self.GetFirstSelected()
        while item != wx.NOT_FOUND:
            if 0 <= item < len(self.rows):
                ids.append(self.rows[item].id)
            item, cookie = self.GetNextSelected(cookie)
        return ids

    def index_of(self, row_id: str) -> int:
        return next((i for i, row in enumerate(self.rows) if row.id == row_id), -1)

    def ensure_visible(self, index: int) -> None:
        if 0 <= index < len(self.rows) and not self.IsRowVisible(index):
            self.ScrollToRow(index)

    def refresh_row(self, row: Row) -> None:
        index = self.index_of(row.id)
        if index >= 0:
            self.rows[index] = row
            self.RefreshRow(index)

    # ------------------------------------------------------------------ rename
    def begin_rename(self, row_id: Optional[str] = None) -> None:
        ids = [row_id] if row_id else self.selected_ids()
        index = self.index_of(ids[0]) if ids else -1
        if index < 0 or not self.on_rename:
            return
        self.ensure_visible(index)
        rect = self.GetItemRect(index)
        x = self.thumb + px(12) if self.thumb > 0 else px(4)
        self._finish_rename(commit=False)
        editor = wx.TextCtrl(self, value=self.rows[index].title, pos=(x, rect.y + px(4)),
                             size=(max(px(80), rect.width - x - px(6)), -1), style=wx.TE_PROCESS_ENTER)
        editor.SelectAll()
        editor.SetFocus()
        target = self.rows[index].id
        editor.Bind(wx.EVT_TEXT_ENTER, lambda e: self._finish_rename(commit=True, row_id=target))
        editor.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), wx.CallAfter(self._finish_rename, True, target)))
        editor.Bind(wx.EVT_CHAR_HOOK, lambda e: self._finish_rename(False) if e.GetKeyCode() == wx.WXK_ESCAPE else e.Skip())
        self._editor = editor

    def is_renaming(self) -> bool:
        return self._editor is not None

    def _finish_rename(self, commit: bool, row_id: Optional[str] = None) -> None:
        editor, self._editor = self._editor, None
        if not editor:
            return
        name = editor.GetValue().strip()
        editor.Destroy()
        if commit and row_id and name and self.on_rename:
            self.on_rename(row_id, name)
        self.SetFocus()

    # ------------------------------------------------------------------ drag (reorder inside, drag out to a canvas)
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self._press = event.GetPosition()
        self._press_row = self.VirtualHitTest(event.GetPosition().y)
        event.Skip()

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if not event.Dragging() or not event.LeftIsDown() or self._press is None or self._press_row < 0:
            event.Skip()
            return
        pos = event.GetPosition()
        if not self._dragging:
            if abs(pos.y - self._press.y) < 6 and abs(pos.x - self._press.x) < 6:
                return
            if not self.reorder:
                self._drag_out()
                return
            self._dragging = True
            if not self.HasCapture():
                self.CaptureMouse()
        if not wx.Rect(self.GetClientSize()).Contains(pos) and self.drag_out_text:
            self._stop_drag()
            self._drag_out()
            return
        row = self.VirtualHitTest(pos.y)
        if row == wx.NOT_FOUND:
            row = len(self.rows)
        else:
            rect = self.GetItemRect(row)
            if pos.y > rect.y + rect.height / 2:
                row += 1
        if row != self.drop_index:
            self.drop_index = row
            self.Refresh()

    def _drag_out(self) -> None:
        index, self._press = self._press_row, None
        if not self.drag_out_text or not (0 <= index < len(self.rows)):
            return
        text = self.drag_out_text(self.rows[index].id)
        if text:
            source = wx.DropSource(self)
            source.SetData(wx.TextDataObject(text))
            source.DoDragDrop(wx.Drag_CopyOnly)

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._dragging:
            source, target = self._press_row, self.drop_index
            self._stop_drag()
            if 0 <= source < len(self.rows) and target >= 0 and target not in (source, source + 1) and self.on_move:
                anchor = self.rows[target].id if target < len(self.rows) else None
                self.on_move(self.rows[source].id, anchor)
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


class Browser(wx.Panel):
    """Title, filter, a ThumbList and a row of buttons (the owner adds them)."""

    def __init__(self, parent: wx.Window, title: str, row_h: int = 46, thumb: int = 38,
                 multiple: bool = False, reorder: bool = False, filter_hint: str = "Filter"):
        super().__init__(parent)
        self._title_text = title
        self.title = title_label(self, title.upper())
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText(filter_hint)
        self.search.ShowCancelButton(True)
        self.list = ThumbList(self, row_h=row_h, thumb=thumb, multiple=multiple, reorder=reorder)
        self.buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.title, 0, wx.LEFT | wx.TOP, 8)
        self.sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 6)
        self.sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self.sizer.Add(self.buttons, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(self.sizer)
        self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.search.SetValue(""))

    def add_button(self, label: str, tooltip: str, handler: Callable[[], None], proportion: int = 1) -> wx.Button:
        btn = wx.Button(self, label=label, style=wx.BU_EXACTFIT)
        btn.SetToolTip(tooltip)
        btn.Bind(wx.EVT_BUTTON, lambda e: handler())
        self.buttons.Add(btn, proportion, wx.RIGHT, 4)
        return btn

    def filter_text(self) -> str:
        return self.search.GetValue().strip().lower()

    def set_count(self, shown: int, total: int) -> None:
        name = self._title_text.upper()
        self.title.SetLabel(f"{name} ({shown} OF {total})" if shown != total else f"{name} ({total})")
