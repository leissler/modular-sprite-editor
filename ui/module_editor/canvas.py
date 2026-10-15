"""Sheet canvas: the image with its modules; draw, select, move, resize and set pivots directly."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import wx

from models import Module, Project
from ui.base_canvas import BaseCanvas
from ui.module_editor import ops
from ui.utils import render_pixel_shape_to_bitmap
from ui.dpi import px

Rect = Tuple[int, int, int, int]

COL_SELECTED = wx.Colour(64, 200, 255)
COL_PIVOT = wx.Colour(255, 90, 80)
COL_MARQUEE = wx.Colour(90, 170, 255)
HANDLE_PX = px(7)
HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
CURSORS = {
    "nw": wx.CURSOR_SIZENWSE, "se": wx.CURSOR_SIZENWSE, "ne": wx.CURSOR_SIZENESW, "sw": wx.CURSOR_SIZENESW,
    "n": wx.CURSOR_SIZENS, "s": wx.CURSOR_SIZENS, "e": wx.CURSOR_SIZEWE, "w": wx.CURSOR_SIZEWE,
}


class SheetCanvas(BaseCanvas):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.zoom = 2.0
        self.min_zoom = 0.25
        self.max_zoom = 24.0
        self.grid_spacing = (8, 8)
        self.show_grid = False
        self.sheet_key: Optional[str] = None
        self.image: Optional[wx.Image] = None  # the sheet as shown (key colour hidden or not)
        self.image_size: Tuple[int, int] = (0, 0)
        self.missing_file: Optional[str] = None
        self.modules: List[Module] = []
        self.selected: List[str] = []
        self.show_names = False
        self.show_pivots = False
        self.snap = False
        self.pick_mode = False
        self._scaled: Optional[Tuple[Tuple[int, ...], wx.Bitmap]] = None
        self._shape_cache: Dict[tuple, wx.Bitmap] = {}

        # Drag state
        self._mode: Optional[str] = None  # draw / move / resize / pivot / marquee
        self._origin: Tuple[float, float] = (0.0, 0.0)
        self._draft: Optional[Rect] = None
        self._start_rects: Dict[str, Rect] = {}
        self._handle: Optional[str] = None
        self._pivot_anchor: Tuple[int, int] = (0, 0)
        self._marquee_base: List[str] = []
        self._moved = False

        # Callbacks (set by the panel)
        self.on_select: Optional[Callable[[List[str]], None]] = None
        self.on_create: Optional[Callable[[Rect], None]] = None
        self.on_changed: Optional[Callable[[], None]] = None  # live, while dragging
        self.on_edit_end: Optional[Callable[[], None]] = None
        self.on_pick: Optional[Callable[[int, int], None]] = None
        self.on_activate: Optional[Callable[[str], None]] = None
        self.on_context_menu: Optional[Callable[[wx.Point], None]] = None

        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_double_click)
        self.Bind(wx.EVT_MOTION, self._on_motion)
        self.Bind(wx.EVT_RIGHT_DOWN, self._on_right_down)

    # ------------------------------------------------------------------ data
    def set_sheet(self, key: Optional[str], image: Optional[wx.Image], size: Tuple[int, int], missing_file: Optional[str] = None) -> None:
        self.sheet_key = key
        self.image = image if image is not None and image.IsOk() else None
        self.image_size = size
        self.missing_file = missing_file
        self._scaled = None
        self.Refresh(False)

    def set_modules(self, modules: List[Module], selected: List[str]) -> None:
        self.modules = modules
        self.selected = [i for i in selected if any(m.id == i for m in modules)]
        self.Refresh(False)

    def selected_modules(self) -> List[Module]:
        by_id = {m.id: m for m in self.modules}
        return [by_id[i] for i in self.selected if i in by_id]

    def is_dragging(self) -> bool:
        return self._mode is not None

    def get_content_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        boxes = [(0.0, 0.0, float(self.image_size[0]), float(self.image_size[1]))] if self.image is not None else []
        boxes += [(m.rect[0], m.rect[1], m.rect[0] + m.rect[2], m.rect[1] + m.rect[3]) for m in self.modules]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    def reveal(self, rect: Rect) -> None:
        """Pan so a module rect is in view (keeps the zoom)."""
        w, h = self.GetClientSize()
        x0, y0 = self.world_to_screen((rect[0], rect[1]))
        x1, y1 = self.world_to_screen((rect[0] + rect[2], rect[1] + rect[3]))
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
            self.center_view((rect[0] + rect[2] / 2, rect[1] + rect[3] / 2))

    # ------------------------------------------------------------------ geometry helpers
    def _screen_rect(self, rect: Rect) -> Tuple[float, float, float, float]:
        x0, y0 = self.world_to_screen((rect[0], rect[1]))
        x1, y1 = self.world_to_screen((rect[0] + rect[2], rect[1] + rect[3]))
        return round(x0), round(y0), round(x1 - x0), round(y1 - y0)

    def _handle_points(self, rect: Rect) -> Dict[str, Tuple[float, float]]:
        x, y, w, h = self._screen_rect(rect)
        return {
            "nw": (x, y), "n": (x + w / 2, y), "ne": (x + w, y), "e": (x + w, y + h / 2),
            "se": (x + w, y + h), "s": (x + w / 2, y + h), "sw": (x, y + h), "w": (x, y + h / 2),
        }

    def _hit_handle(self, pos: wx.Point) -> Optional[str]:
        sel = self.selected_modules()
        if len(sel) != 1:
            return None
        for name, (hx, hy) in self._handle_points(tuple(sel[0].rect)).items():
            if abs(pos.x - hx) <= HANDLE_PX and abs(pos.y - hy) <= HANDLE_PX:
                return name
        return None

    def module_at(self, world: Tuple[float, float]) -> Optional[Module]:
        """Selected modules first, then the smallest module under the point (small ones sit inside big ones)."""
        hits = [m for m in self.modules if ops.contains(tuple(m.rect), world[0], world[1])]
        if not hits:
            return None
        chosen = [m for m in hits if m.id in self.selected]
        pool = chosen or hits
        return min(pool, key=lambda m: m.rect[2] * m.rect[3])

    def _snap_xy(self, world: Tuple[float, float]) -> Tuple[int, int]:
        gx, gy = self.grid_spacing
        return ops.snap(world[0], int(gx)), ops.snap(world[1], int(gy))

    def _draw_rect(self, a: Tuple[float, float], b: Tuple[float, float]) -> Rect:
        if self.snap:
            (x0, y0), (x1, y1) = self._snap_xy(a), self._snap_xy(b)
            return ops.normalize((x0, y0, x1 - x0, y1 - y0))
        return ops.rect_from_points(a, b)

    # ------------------------------------------------------------------ mouse
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        if self.begin_pan_if_requested(event):
            return
        pos = event.GetPosition()
        world = self.screen_to_world(pos)
        if self.pick_mode:
            if self.on_pick:
                self.on_pick(int(world[0] // 1), int(world[1] // 1))
            return
        self._origin = world
        self._moved = False
        sel = self.selected_modules()
        if len(sel) == 1 and event.ShiftDown() and not (event.CmdDown() or event.ControlDown()):
            self._mode = "pivot"
            self._set_pivot(sel[0], world)
        elif self._hit_handle(pos):
            self._mode = "resize"
            self._handle = self._hit_handle(pos)
            self._start_rects = {sel[0].id: tuple(sel[0].rect)}  # type: ignore[dict-item]
            self._pivot_anchor = ops.pivot_on_sheet(sel[0])
        else:
            hit = self.module_at(world)
            additive = event.CmdDown() or event.ControlDown()
            if hit is not None:
                if additive:
                    self.selected = [i for i in self.selected if i != hit.id] if hit.id in self.selected else self.selected + [hit.id]
                    self._notify_select()
                    self._mode = None
                    self.Refresh(False)
                    return
                if hit.id not in self.selected:
                    self.selected = [hit.id]
                    self._notify_select()
                self._mode = "move"
                self._start_rects = {m.id: tuple(m.rect) for m in self.selected_modules()}  # type: ignore[misc]
            elif additive:
                self._mode = "marquee"
                self._marquee_base = list(self.selected)
                self._draft = None
            elif self.sheet_key is not None:
                self._mode = "draw"
                self._draft = None
        if self._mode and not self.HasCapture():
            self.CaptureMouse()
        self.Refresh(False)

    def _on_motion(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return
        pos = event.GetPosition()
        world = self.screen_to_world(pos)
        if self._mode is None or not event.LeftIsDown():
            self._update_cursor(pos, world, event.ShiftDown())
            return
        dx_px = abs(world[0] - self._origin[0]) * self.zoom
        dy_px = abs(world[1] - self._origin[1]) * self.zoom
        if not self._moved and dx_px < px(3) and dy_px < px(3) and self._mode in ("draw", "move", "marquee"):
            return
        self._moved = True
        if self._mode == "draw":
            self._draft = self._draw_rect(self._origin, world)
        elif self._mode == "marquee":
            self._draft = self._draw_rect(self._origin, world)
            inside = [m.id for m in self.modules if ops.overlaps(tuple(m.rect), self._draft)]
            self.selected = self._marquee_base + [i for i in inside if i not in self._marquee_base]
            self._notify_select()
        elif self._mode == "move":
            dx = int(round(world[0] - self._origin[0]))
            dy = int(round(world[1] - self._origin[1]))
            for module in self.selected_modules():
                sx, sy, w, h = self._start_rects.get(module.id, tuple(module.rect))
                x, y = sx + dx, sy + dy
                if self.snap:
                    x, y = ops.snap(x, int(self.grid_spacing[0])), ops.snap(y, int(self.grid_spacing[1]))
                module.rect = (x, y, w, h)
            self._changed()
        elif self._mode == "resize":
            sel = self.selected_modules()
            if sel:
                self._resize(sel[0], world)
                self._changed()
        elif self._mode == "pivot":
            sel = self.selected_modules()
            if sel:
                self._set_pivot(sel[0], world)
        self.Refresh(False)

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._panning:
            self.on_pan_end(event)
            return
        if self.HasCapture():
            self.ReleaseMouse()
        mode, draft, moved = self._mode, self._draft, self._moved
        self._mode = None
        self._draft = None
        if mode == "draw":
            if moved and draft and draft[2] > 0 and draft[3] > 0 and self.on_create:
                self.on_create(draft)
            elif not moved and self.selected:
                self.selected = []
                self._notify_select()
        elif mode in ("move", "resize") and moved:
            self._edit_end()
        elif mode == "pivot":
            self._edit_end()
        self.Refresh(False)

    def _on_double_click(self, event: wx.MouseEvent) -> None:
        hit = self.module_at(self.screen_to_world(event.GetPosition()))
        if hit is not None and self.on_activate:
            self.on_activate(hit.id)

    def _on_right_down(self, event: wx.MouseEvent) -> None:
        hit = self.module_at(self.screen_to_world(event.GetPosition()))
        if hit is not None and hit.id not in self.selected:
            self.selected = [hit.id]
            self._notify_select()
            self.Refresh(False)
        if self.on_context_menu:
            self.on_context_menu(event.GetPosition())

    def _update_cursor(self, pos: wx.Point, world: Tuple[float, float], shift: bool) -> None:
        if self.pick_mode:
            cursor = wx.CURSOR_CROSS
        elif shift and len(self.selected) == 1:
            cursor = wx.CURSOR_CROSS
        else:
            handle = self._hit_handle(pos)
            if handle:
                cursor = CURSORS[handle]
            elif self.module_at(world) is not None:
                cursor = wx.CURSOR_SIZING
            else:
                cursor = wx.CURSOR_ARROW
        self.SetCursor(wx.Cursor(cursor))

    def _resize(self, module: Module, world: Tuple[float, float]) -> None:
        x, y, w, h = self._start_rects.get(module.id, tuple(module.rect))
        left, top, right, bottom = x, y, x + w, y + h
        if self.snap:
            gx, gy = self._snap_xy(world)
        else:
            gx, gy = int(round(world[0])), int(round(world[1]))
        handle = self._handle or ""
        if "w" in handle:
            left = gx
        if "e" in handle:
            right = gx
        if "n" in handle:
            top = gy
        if "s" in handle:
            bottom = gy
        rect = ops.normalize((left, top, right - left, bottom - top))
        rect = (rect[0], rect[1], max(1, rect[2]), max(1, rect[3]))
        ops.resize_keeping_pivot(module, rect, self._pivot_anchor)

    def _set_pivot(self, module: Module, world: Tuple[float, float]) -> None:
        vx = int(world[0] // 1) - module.rect[0]
        vy = int(world[1] // 1) - module.rect[1]
        pivot = ops.logical_pivot(module, (vx, vy))
        if tuple(module.pivot) != pivot:
            module.pivot = pivot
            self._changed()

    def _notify_select(self) -> None:
        if self.on_select:
            self.on_select(list(self.selected))

    def _changed(self) -> None:
        if self.on_changed:
            self.on_changed()

    def _edit_end(self) -> None:
        if self.on_edit_end:
            self.on_edit_end()

    # ------------------------------------------------------------------ paint
    def on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.draw_backdrop(dc)
        gc = wx.GraphicsContext.Create(dc)
        self._draw_sheet(gc)
        self._draw_grid(gc)
        self._draw_sheet_border(gc)
        if self.sheet_key == ops.SHAPES_KEY:
            self._draw_shapes(gc)
        self._draw_modules(gc)
        if self._draft is not None:
            self._draw_draft(gc)
        self._draw_hints(gc)

    def _draw_sheet(self, gc: wx.GraphicsContext) -> None:
        if self.image is None:
            return
        cw, ch = self.GetClientSize()
        wx0, wy0 = self.screen_to_world(wx.Point(0, 0))
        wx1, wy1 = self.screen_to_world(wx.Point(cw, ch))
        iw, ih = self.image.GetWidth(), self.image.GetHeight()
        vx0, vy0 = max(0, int(wx0)), max(0, int(wy0))
        vx1, vy1 = min(iw, int(wx1) + 1), min(ih, int(wy1) + 1)
        if vx1 <= vx0 or vy1 <= vy0:
            return
        tw, th = int(round((vx1 - vx0) * self.zoom)), int(round((vy1 - vy0) * self.zoom))
        if tw <= 0 or th <= 0:
            return
        key = (vx0, vy0, vx1, vy1, tw, th)
        if self._scaled is None or self._scaled[0] != key:
            sub = self.image.GetSubImage(wx.Rect(vx0, vy0, vx1 - vx0, vy1 - vy0))
            sub.Rescale(tw, th, wx.IMAGE_QUALITY_NEAREST)
            self._scaled = (key, sub.ConvertToBitmap())
        sx, sy = self.world_to_screen((vx0, vy0))
        gc.DrawBitmap(self._scaled[1], round(sx), round(sy), tw, th)

    def _draw_sheet_border(self, gc: wx.GraphicsContext) -> None:
        if self.image is None:
            return
        x, y, w, h = self._screen_rect((0, 0, self.image_size[0], self.image_size[1]))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(self.overlay_colour("canvas_faint", 160), 1))
        gc.DrawRectangle(x - 0.5, y - 0.5, w + 1, h + 1)

    def _draw_shapes(self, gc: wx.GraphicsContext) -> None:
        for module in self.modules:
            x, y, w, h = self._screen_rect(tuple(module.rect))
            if w <= 0 or h <= 0:
                continue
            key = (module.type, tuple(module.rect[2:]), tuple(module.color), tuple(module.params), w, h)
            bmp = self._shape_cache.get(key)
            if bmp is None:
                base = render_pixel_shape_to_bitmap(module.type, module.rect[2], module.rect[3], module.color, module.params)
                if base is None:
                    continue
                img = base.ConvertToImage()
                img.Rescale(w, h, wx.IMAGE_QUALITY_NEAREST)
                bmp = img.ConvertToBitmap()
                if len(self._shape_cache) > 400:
                    self._shape_cache.clear()
                self._shape_cache[key] = bmp
            gc.DrawBitmap(bmp, x, y, w, h)

    def _draw_modules(self, gc: wx.GraphicsContext) -> None:
        selected = set(self.selected)
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font.SetPointSize(max(7, font.GetPointSize() - 2))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(self.overlay_colour("canvas_faint", 150), 1))
        for module in self.modules:
            if module.id in selected:
                continue
            x, y, w, h = self._screen_rect(tuple(module.rect))
            gc.DrawRectangle(x + 0.5, y + 0.5, max(0, w - 1), max(0, h - 1))
        if self.show_names and self.zoom >= 1:
            gc.SetFont(font, wx.Colour(235, 238, 245))
            for module in self.modules:
                x, y, w, h = self._screen_rect(tuple(module.rect))
                tw, th = gc.GetTextExtent(module.name)
                if tw + px(4) > w and w < px(40):
                    continue
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.SetBrush(wx.Brush(wx.Colour(15, 16, 20, 190)))
                gc.DrawRectangle(x + 1, y + 1, min(w - 2, tw + px(4)), th + 1)
                gc.Clip(x + 1, y + 1, max(1, w - 2), max(1, h - 2))
                gc.DrawText(module.name, x + px(3), y + 1)
                gc.ResetClip()
        if self.show_pivots:
            for module in self.modules:
                if module.id not in selected:
                    self._draw_pivot(gc, module, small=True)
        sel = self.selected_modules()
        for module in sel:
            x, y, w, h = self._screen_rect(tuple(module.rect))
            gc.SetBrush(wx.Brush(wx.Colour(64, 200, 255, 28)))
            gc.SetPen(wx.Pen(COL_SELECTED, 2))
            gc.DrawRectangle(x, y, w, h)
        if len(sel) == 1:
            gc.SetPen(wx.Pen(wx.Colour(10, 10, 12), 1))
            gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
            for hx, hy in self._handle_points(tuple(sel[0].rect)).values():
                gc.DrawRectangle(hx - HANDLE_PX / 2, hy - HANDLE_PX / 2, HANDLE_PX, HANDLE_PX)
        for module in sel:
            self._draw_pivot(gc, module, small=len(sel) > 1)

    def _draw_pivot(self, gc: wx.GraphicsContext, module: Module, small: bool) -> None:
        pvx, pvy = ops.pivot_on_sheet(module)
        sx, sy = self.world_to_screen((pvx, pvy))
        size = max(1.0, self.zoom)
        colour = COL_PIVOT if not small else wx.Colour(255, 120, 110, 190)
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(colour, 1))
        gc.DrawRectangle(round(sx), round(sy), round(size), round(size))
        cx, cy = round(sx) + size / 2, round(sy) + size / 2
        arm = size / 2 + px(3 if small else 6)
        gc.SetPen(wx.Pen(colour, 1 if small else 2))
        gc.StrokeLine(cx - arm, cy, cx + arm, cy)
        gc.StrokeLine(cx, cy - arm, cx, cy + arm)

    def _draw_draft(self, gc: wx.GraphicsContext) -> None:
        x, y, w, h = self._screen_rect(self._draft)  # type: ignore[arg-type]
        if self._mode == "marquee":
            gc.SetBrush(wx.Brush(wx.Colour(90, 170, 255, 40)))
            gc.SetPen(wx.Pen(COL_MARQUEE, 1))
            gc.DrawRectangle(x, y, w, h)
            return
        gc.SetBrush(wx.Brush(self.overlay_colour("canvas_line", 30)))
        gc.SetPen(wx.Pen(self.overlay_colour("canvas_line"), 1, wx.PENSTYLE_SHORT_DASH))
        gc.DrawRectangle(x + 0.5, y + 0.5, max(0, w - 1), max(0, h - 1))
        label = f"{self._draft[2]}×{self._draft[3]}"  # type: ignore[index]
        self._label(gc, label, x + w + px(6), y + h + px(4))

    def _label(self, gc: wx.GraphicsContext, text: str, x: float, y: float) -> None:
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        gc.SetFont(font, wx.Colour(235, 238, 245))
        tw, th = gc.GetTextExtent(text)
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(15, 16, 20, 210)))
        gc.DrawRoundedRectangle(x - px(4), y - px(2), tw + px(8), th + px(4), px(3))
        gc.DrawText(text, x, y)

    def _draw_hints(self, gc: wx.GraphicsContext) -> None:
        text = ""
        if self.pick_mode:
            text = "Click a pixel to use its colour as the key colour  •  Esc cancels"
        elif self.sheet_key is None:
            text = "Add an image (Images ▸ + Add) to cut modules from it"
        elif self.missing_file:
            text = f"Image file not found: {self.missing_file}  •  use Locate… in the inspector"
        elif not self.modules:
            text = ("Drag to draw a shape" if self.sheet_key == ops.SHAPES_KEY
                    else "Drag over a sprite to cut a module, or use Slice ▾ to cut many at once")
        if not text:
            return
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(225, 228, 235))
        tw, th = gc.GetTextExtent(text)
        width = self.GetClientSize().width
        x, y = (width - tw) / 2, px(14)
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(20, 21, 24, 215)))
        gc.DrawRoundedRectangle(x - px(12), y - px(6), tw + px(24), th + px(12), px(6))
        gc.DrawText(text, x, y)
