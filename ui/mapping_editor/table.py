"""The module map: one row per module, what it shows under the mapping (original, a replacement, hidden)."""

from __future__ import annotations

from typing import Callable, List, Optional

import wx

from models import ModuleMapping, Project
from ui.components.module_palette import THUMBNAILS
from ui.components.thumb_list import fit_text
from ui.mapping_editor import ops
from ui.dpi import px
from ui.theme import T

ROW_H = px(44)
THUMB = px(34)


class _ModuleDrop(wx.TextDropTarget):
    def __init__(self, table: "MapTable"):
        super().__init__()
        self.table = table

    def OnDragOver(self, x: int, y: int, default: int) -> int:
        row = self.table.VirtualHitTest(y)
        if row != self.table.drop_row:
            self.table.drop_row = row
            self.table.Refresh()
        return wx.DragCopy if row != wx.NOT_FOUND else wx.DragNone

    def OnLeave(self) -> None:
        self.table.drop_row = -1
        self.table.Refresh()

    def OnDropText(self, x: int, y: int, data: str) -> bool:
        self.table.drop_row = -1
        self.table.Refresh()
        if not data.startswith("MODULE:"):
            return False
        row = self.table.VirtualHitTest(y)
        if row == wx.NOT_FOUND or not self.table.on_drop:
            return False
        self.table.on_drop(self.table.module_ids[row], data.split(":", 1)[1])
        return True


class MapTable(wx.VListBox):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS | wx.LB_MULTIPLE)
        self.project: Optional[Project] = None
        self.mapping: Optional[ModuleMapping] = None
        self.module_ids: List[str] = []
        self.drop_row = -1
        self.on_drop: Optional[Callable[[str, str], None]] = None  # (source module id, dropped module id)
        T.style(self, bg="row")
        self.SetDropTarget(_ModuleDrop(self))

    def set_rows(self, project: Project, mapping: Optional[ModuleMapping], module_ids: List[str], selected: List[str]) -> None:
        self.project, self.mapping, self.module_ids = project, mapping, list(module_ids)
        self.SetItemCount(len(self.module_ids))
        self.set_selected(selected)

    def set_selected(self, ids: List[str], ensure_visible: bool = True) -> None:
        wanted = set(ids)
        self.DeselectAll()
        first = -1
        for i, module_id in enumerate(self.module_ids):
            if module_id in wanted:
                self.Select(i, True)
                first = i if first < 0 else first
        if ensure_visible and first >= 0 and not self.IsRowVisible(first):
            self.ScrollToRow(first)
        self.Refresh()

    def selected_ids(self) -> List[str]:
        ids = []
        item, cookie = self.GetFirstSelected()
        while item != wx.NOT_FOUND:
            if 0 <= item < len(self.module_ids):
                ids.append(self.module_ids[item])
            item, cookie = self.GetNextSelected(cookie)
        return ids

    # ------------------------------------------------------------------ drawing
    def OnMeasureItem(self, n: int) -> int:
        return ROW_H

    def OnDrawBackground(self, dc: wx.DC, rect: wx.Rect, n: int) -> None:
        colour = T.selected if self.IsSelected(n) else (T.row_alt if n % 2 else T.row)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(colour))
        dc.DrawRectangle(rect)
        if n == self.drop_row:
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.SetPen(wx.Pen(T.drop, 2))
            dc.DrawRectangle(rect.x + 1, rect.y + 1, rect.width - 2, rect.height - 2)

    def OnDrawItem(self, dc: wx.DC, rect: wx.Rect, n: int) -> None:
        if self.project is None or not (0 <= n < len(self.module_ids)):
            return
        source = self.project.get_module(self.module_ids[n])
        if source is None:
            return
        half = rect.width // 2
        y = rect.y + (ROW_H - THUMB) // 2
        font = self.GetFont()
        small = wx.Font(font)
        small.SetPointSize(max(7, font.GetPointSize() - 2))
        dc.DrawBitmap(THUMBNAILS.bitmap(self.project, source, THUMB, THUMB), rect.x + px(6), y)
        self._texts(dc, font, small, rect.x + THUMB + px(14), rect.y, half - THUMB - px(34), source.name, f"{source.rect[2]}×{source.rect[3]}", T.text_dim)

        state = ops.state(self.project, self.mapping, source.id) if self.mapping else ops.ORIGINAL
        arrow_x = rect.x + half - px(18)
        dc.SetFont(font)
        dc.SetTextForeground(T.text_dim if state == ops.ORIGINAL else T.replaced)
        dc.DrawText("→", arrow_x, rect.y + (ROW_H - dc.GetTextExtent("→")[1]) // 2)
        x = rect.x + half + px(6)
        if state == ops.REPLACED:
            target = self.project.get_module(self.mapping.map[source.id])  # type: ignore[union-attr]
            dc.DrawBitmap(THUMBNAILS.bitmap(self.project, target, THUMB, THUMB), x, y)
            self._texts(dc, font, small, x + THUMB + px(8), rect.y, rect.right - x - THUMB - px(14), target.name, "replaced", T.replaced)
        else:
            dc.SetPen(wx.Pen(T.border))
            dc.SetBrush(wx.Brush(T.thumb))
            dc.DrawRectangle(x, y, THUMB, THUMB)
            title, detail, colour = {
                ops.ORIGINAL: ("= original", "", T.text_dim),
                ops.HIDDEN: ("Hidden", "not drawn", T.accent),
                ops.MISSING: ("Missing", "the replacement was deleted", T.error),
            }[state]
            if state == ops.HIDDEN:
                dc.SetPen(wx.Pen(T.accent, 2))
                dc.DrawLine(x + px(4), y + px(4), x + THUMB - px(4), y + THUMB - px(4))
            self._texts(dc, font, small, x + THUMB + px(8), rect.y, rect.right - x - THUMB - px(14), title, detail, colour, title_colour=colour)

    def _texts(self, dc: wx.DC, font: wx.Font, small: wx.Font, x: int, top: int, width: int, title: str, detail: str,
               detail_colour: wx.Colour, title_colour: Optional[wx.Colour] = None) -> None:
        dc.SetFont(font)
        th = dc.GetTextExtent("Ag")[1]
        dc.SetFont(small)
        dh = dc.GetTextExtent("Ag")[1] if detail else 0
        y = top + (ROW_H - th - (dh + 1 if detail else 0)) // 2
        dc.SetFont(font)
        dc.SetTextForeground(title_colour or T.text)
        dc.DrawText(fit_text(dc, title, max(10, width)), x, y)
        if detail:
            dc.SetFont(small)
            dc.SetTextForeground(detail_colour)
            dc.DrawText(fit_text(dc, detail, max(10, width)), x, y + th + 1)
