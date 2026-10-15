"""Grid of module thumbnails: drag one out (``MODULE:<id>``), click or double-click to pick it.

Used by the Frames library, the Timeline library and the Mappings picker. Each module is fitted into its
cell on its own (whole-number zoom up to 4×), so small modules stay recognisable next to big ones; the
size is printed under the name.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable, List, Optional

import wx

from models import Module, Project
from ui.dpi import px
from ui.theme import T

SHAPES_KEY = "@shapes"  # sheet filter value for vector shape modules



def sheet_of(module: Module) -> str:
    """The sheet key a module belongs to: its image id, or SHAPES_KEY for vector shapes."""
    return SHAPES_KEY if module.type != "MD_IMAGE" else module.image_id


class ModuleThumbnails:
    """wx bitmaps of modules fitted into a box, cached by module content."""

    def __init__(self, max_items: int = 3000) -> None:
        self.max_items = max_items
        self._cache: "OrderedDict[Any, wx.Bitmap]" = OrderedDict()

    def clear(self) -> None:
        self._cache.clear()

    def bitmap(self, project: Project, module: Module, width: int, height: int, background=None, max_scale: int = 4) -> wx.Bitmap:
        """The module fitted into a box on ``background`` (the theme's tile colour unless given)."""
        from ui.frame_render import SHARED, fit_bitmap, module_signature

        background = background or T.palette.rgb("tile")
        key = (module_signature(project, module.id), width, height, tuple(background), max_scale)
        bmp = self._cache.get(key)
        if bmp is not None:
            self._cache.move_to_end(key)
            return bmp
        image = SHARED.module(project, module)
        bmp = fit_bitmap(image, width, height, tuple(background), max_scale=max_scale)
        self._cache[key] = bmp
        while len(self._cache) > self.max_items:
            self._cache.popitem(last=False)
        return bmp


# One cache for every module list and palette.
THUMBNAILS = ModuleThumbnails()


class ModulePalette(wx.ScrolledWindow):
    def __init__(self, parent: wx.Window, project: Project, item_size: int = 72):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.project = project
        self.item_size = px(item_size)  # at 100 % display scaling
        self.label_h = px(30)
        self.padding = px(6)
        self.cols = 1
        self.filter_text = ""
        self.sheet: Optional[str] = None  # image id, SHAPES_KEY, or None for every module
        self.selected_module_id: Optional[str] = None
        self.marked: set = set()  # e.g. the current mapping target
        self.module_ids: List[str] = []
        self._hover = -1
        self._press: Optional[wx.Point] = None
        self._press_index = -1

        # Callbacks
        self.on_module_click: Optional[Callable[[str], None]] = None
        self.on_module_double_click: Optional[Callable[[str], None]] = None

        T.style(self, bg="row")
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetScrollRate(0, px(20))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_double_click)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

    # ------------------------------------------------------------------ data
    def visible_modules(self) -> List[Module]:
        mods = list(self.project.modules)
        if self.sheet is not None:
            mods = [m for m in mods if sheet_of(m) == self.sheet]
        if self.filter_text:
            mods = [m for m in mods if self.filter_text in m.name.lower()]
        return mods

    def set_filter(self, text: str) -> None:
        self.filter_text = (text or "").strip().lower()
        self.Scroll(0, 0)
        self.refresh_modules()

    def set_sheet(self, sheet: Optional[str]) -> None:
        self.sheet = sheet
        self.Scroll(0, 0)
        self.refresh_modules()

    def refresh_modules(self) -> None:
        self.module_ids = [m.id for m in self.visible_modules()]
        self._layout()
        self.Refresh()

    def select_module(self, module_id: Optional[str], ensure_visible: bool = True) -> None:
        self.selected_module_id = module_id
        if ensure_visible and module_id in self.module_ids:
            rect = self._item_rect(self.module_ids.index(module_id))
            _vx, vy = self.GetViewStart()
            _px, py = self.GetScrollPixelsPerUnit()
            top = vy * max(1, py)
            height = self.GetClientSize().height
            if rect.y < top or rect.y + rect.height > top + height:
                self.Scroll(0, max(0, (rect.y - self.padding) // max(1, py)))
        self.Refresh()

    # ------------------------------------------------------------------ layout
    def _cell(self) -> wx.Size:
        return wx.Size(self.item_size, self.item_size + self.label_h)

    def _layout(self) -> None:
        width = max(10, self.GetClientSize().width)
        cell = self._cell()
        self.cols = max(1, (width - self.padding) // (cell.width + self.padding))
        rows = (len(self.module_ids) + self.cols - 1) // self.cols
        self.SetVirtualSize(width, rows * (cell.height + self.padding) + self.padding)

    def _item_rect(self, index: int) -> wx.Rect:
        cell = self._cell()
        used = self.cols * (cell.width + self.padding) - self.padding
        left = max(self.padding, (self.GetClientSize().width - used) // 2)
        col, row = index % self.cols, index // self.cols
        return wx.Rect(left + col * (cell.width + self.padding), self.padding + row * (cell.height + self.padding), cell.width, cell.height)

    def _hit(self, pos: wx.Point) -> int:
        pt = self.CalcUnscrolledPosition(pos)
        for index in range(len(self.module_ids)):
            if self._item_rect(index).Contains(pt):
                return index
        return -1

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._layout()
        self.Refresh()
        event.Skip()

    # ------------------------------------------------------------------ paint
    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(T.row))
        dc.Clear()
        if not self.module_ids:
            dc.SetTextForeground(T.text_dim)
            dc.SetFont(self.GetFont())
            dc.DrawText("No modules" if not self.filter_text else "No match", 10, 10)
            return
        x0, y0 = self.CalcUnscrolledPosition(0, 0)
        view = wx.Rect(x0, y0, *self.GetClientSize())
        font = self.GetFont()
        small = wx.Font(font)
        small.SetPointSize(max(7, font.GetPointSize() - 2))
        for index, module_id in enumerate(self.module_ids):
            rect = self._item_rect(index)
            if not view.Intersects(rect):
                continue
            mod = self.project.get_module(module_id)
            if mod is None:
                continue
            tile = wx.Rect(rect.x, rect.y, self.item_size, self.item_size)
            dc.DrawBitmap(THUMBNAILS.bitmap(self.project, mod, tile.width, tile.height), tile.x, tile.y)
            selected = module_id == self.selected_module_id
            if selected or index == self._hover or module_id in self.marked:
                dc.SetBrush(wx.TRANSPARENT_BRUSH)
                colour = T.focus if selected else (T.accent if module_id in self.marked else T.hover)
                dc.SetPen(wx.Pen(colour, 2))
                dc.DrawRectangle(tile.x - 1, tile.y - 1, tile.width + 2, tile.height + 2)
            dc.SetFont(small)
            dc.SetTextForeground(T.text)
            name = _fit(dc, mod.name, rect.width)
            tw = dc.GetTextExtent(name)[0]
            dc.DrawText(name, rect.x + (rect.width - tw) // 2, tile.bottom + px(3))
            dc.SetTextForeground(T.text_dim)
            size = f"{mod.rect[2]}×{mod.rect[3]}"
            tw = dc.GetTextExtent(size)[0]
            dc.DrawText(size, rect.x + (rect.width - tw) // 2, tile.bottom + px(15))

    # ------------------------------------------------------------------ mouse
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        index = self._hit(event.GetPosition())
        self._press = event.GetPosition() if index >= 0 else None
        self._press_index = index
        if index >= 0:
            self.selected_module_id = self.module_ids[index]
            self.Refresh()
            if self.on_module_click:
                self.on_module_click(self.module_ids[index])

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        self._press = None
        event.Skip()

    def _on_double_click(self, event: wx.MouseEvent) -> None:
        index = self._hit(event.GetPosition())
        if index >= 0 and self.on_module_double_click:
            self.on_module_double_click(self.module_ids[index])

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if event.Dragging() and event.LeftIsDown() and self._press is not None and self._press_index >= 0:
            delta = event.GetPosition() - self._press
            if abs(delta.x) > 5 or abs(delta.y) > 5:
                module_id = self.module_ids[self._press_index]
                self._press = None
                source = wx.DropSource(self)
                source.SetData(wx.TextDataObject(f"MODULE:{module_id}"))
                source.DoDragDrop(wx.Drag_CopyOnly)
            return
        index = self._hit(event.GetPosition())
        if index != self._hover:
            self._hover = index
            self.Refresh()

    def _on_leave(self, _event: wx.MouseEvent) -> None:
        if self._hover != -1:
            self._hover = -1
            self.Refresh()


def _fit(dc: wx.DC, text: str, width: int) -> str:
    if dc.GetTextExtent(text)[0] <= width:
        return text
    while text and dc.GetTextExtent(text + "…")[0] > width:
        text = text[:-1]
    return text + "…"
