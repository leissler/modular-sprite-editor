import wx
from typing import Optional, Callable, List, Tuple
from models import Project, Frame
from ui.components.thumb_list import fit_text
from ui.utils import ThumbnailGenerator

class FramePalette(wx.ScrolledWindow):
    """
    Shows a grid of available frames in the project.
    Allows selection, double-click to add, and dragging to timeline.
    """
    def __init__(self, parent, project: Project):
        super().__init__(parent, style=wx.BORDER_SUNKEN)
        self.project = project
        self.generator = ThumbnailGenerator()
        
        # Interaction Callbacks
        self.on_frame_double_click: Optional[Callable[[str], None]] = None
        
        # State
        self.selected_frame_id: Optional[str] = None
        self.hovered_frame_id: Optional[str] = None
        
        # Layout
        self.item_size = (128, 128)
        self.padding = 10
        self.cols = 1
        
        # Drag State
        self._drag_start_pos: Optional[wx.Point] = None
        self.filter_text = ""
        self._cached_scale = 0.0
        
        self.SetBackgroundColour(wx.Colour(40, 40, 40))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetScrollRate(20, 20)
        
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_LEFT_DCLICK, self.on_double_click)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.on_leave)

    def refresh_frames(self) -> None:
        """Call this when project frames change."""
        self.invalidate_scale()
        self.layout_items()
        self.Refresh()

    def invalidate_scale(self) -> None:
        self._cached_scale = 0.0

    def set_filter(self, text: str) -> None:
        self.filter_text = (text or "").strip().lower()
        self.Scroll(0, 0)
        self.layout_items()
        self.Refresh()

    def visible_frames(self) -> List[Frame]:
        if not self.filter_text:
            return list(self.project.frames)
        return [f for f in self.project.frames if self.filter_text in f.name.lower()]

    def layout_items(self) -> None:
        """Calculate virtual size based on item count and client width."""
        w, h = self.GetClientSize()
        if w < 10: w = 100 # Safety
        
        full_w = self.item_size[0] + self.padding
        self.cols = max(1, w // full_w)
        
        count = len(self.visible_frames())
        rows = (count + self.cols - 1) // self.cols
        
        full_h = self.item_size[1] + self.padding
        virtual_h = rows * full_h + self.padding
        
        self.SetVirtualSize(w, virtual_h)

    def on_size(self, event) -> None:
        self.layout_items()
        event.Skip()

    def _get_item_rect(self, index: int) -> wx.Rect:
        full_w = self.item_size[0] + self.padding
        full_h = self.item_size[1] + self.padding
        
        col = index % self.cols
        row = index // self.cols
        
        x = self.padding + col * full_w
        y = self.padding + row * full_h
        return wx.Rect(x, y, self.item_size[0], self.item_size[1])

    def _hit_test(self, pos: wx.Point) -> int:
        """Returns index of frame at pos, or -1."""
        unscrolled = self.CalcUnscrolledPosition(pos)
        
        # Optimized approximate hit test or precise? 
        # Precise iteration is fine for < 1000 items usually, but calculation is faster.
        full_w = self.item_size[0] + self.padding
        full_h = self.item_size[1] + self.padding
        
        col = (unscrolled.x - self.padding) // full_w
        row = (unscrolled.y - self.padding) // full_h
        
        if col < 0 or col >= self.cols or row < 0:
            return -1
            
        # Refine check inside inner rect
        # x_in_cell = (unscrolled.x - padding) % full_w
        # if x_in_cell > item_size[0]: return -1
        
        index = row * self.cols + col
        if 0 <= index < len(self.visible_frames()):
            return index
        return -1

    def on_paint(self, event) -> None:
        dc = wx.PaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(wx.Colour(40, 40, 40)))
        dc.Clear()
        
        frames = self.visible_frames()
        if not frames:
            return

        vs_x, vs_y = self.GetViewStart()
        pu_x, pu_y = self.GetScrollPixelsPerUnit()
        cs_w, cs_h = self.GetClientSize()
        view_rect = wx.Rect(vs_x * pu_x, vs_y * pu_y, cs_w, cs_h)

        current_map_id = id(self.project.active_mapping) if self.project.active_mapping else None
        if getattr(self, '_last_map_id', None) != current_map_id:
            self._cached_scale = 0.0
            self._last_map_id = current_map_id

        scale = self._calculate_uniform_scale()

        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        dc.SetFont(font)

        for i, frame in enumerate(frames):
            r = self._get_item_rect(i)
            
            # Visibility Check
            if not view_rect.Intersects(r):
                continue
                
            # Draw Thumbnail
            bmp = self.generator.render_thumbnail(self.project, frame, r.width, r.height, custom_scale=scale, mapping=self.project.active_mapping)
            dc.DrawBitmap(bmp, r.x, r.y)
            
            # Draw Name Overlay (Bottom)
            dc.SetTextForeground(wx.Colour(255, 255, 255))
            name = fit_text(dc, frame.name, r.width - 6)  # long names would run into the next cell
            tex_w, tex_h = dc.GetTextExtent(name)
            # Semi-transparent bar?
            dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 128)))
            dc.SetPen(wx.Pen(wx.TRANSPARENT_PEN))
            dc.DrawRectangle(r.x, r.y + r.height - tex_h - 4, r.width, tex_h + 4)
            dc.DrawText(name, r.x + (r.width - tex_w)//2, r.y + r.height - tex_h - 2)
            
            # Selection Border
            if frame.id == self.selected_frame_id:
                # Outer Glow Look
                dc.SetBrush(wx.Brush(wx.TRANSPARENT_BRUSH))
                dc.SetPen(wx.Pen(wx.Colour(100, 200, 255), 3))
                dc.DrawRectangle(r.x - 2, r.y - 2, r.width + 4, r.height + 4)

    def _calculate_uniform_scale(self) -> float:
        """One scale for all frames, so their relative sizes stay visible."""
        if self._cached_scale > 0:
            return self._cached_scale
        mapping = self.project.active_mapping
        sizes = [self.generator.frame_size(self.project, frame, mapping) for frame in self.project.frames]
        global_max_w = max((w for w, _h in sizes), default=0)
        global_max_h = max((h for _w, h in sizes), default=0)
        uniform_scale = 1.0
        if global_max_w > 0 and global_max_h > 0:
            uniform_scale = min(self.item_size[0] / global_max_w, self.item_size[1] / global_max_h, 32.0)
        self._cached_scale = uniform_scale
        return uniform_scale

    def on_left_down(self, event) -> None:
        idx = self._hit_test(event.GetPosition())
        if idx != -1:
            fid = self.visible_frames()[idx].id
            self.selected_frame_id = fid
            self._drag_start_pos = event.GetPosition()
            self.Refresh()
        else:
            self.selected_frame_id = None
            self._drag_start_pos = None
            self.Refresh()
        event.Skip()

    def on_left_up(self, event) -> None:
        self._drag_start_pos = None
        event.Skip()

    def on_motion(self, event) -> None:
        if event.Dragging() and event.LeftIsDown() and self._drag_start_pos:
            # Threshold Check
            drag_vec = event.GetPosition() - self._drag_start_pos
            if abs(drag_vec.x) > 5 or abs(drag_vec.y) > 5:
                # Start Drag
                if self.selected_frame_id:
                    self._do_drag(self.selected_frame_id)
                    self._drag_start_pos = None # Reset
        event.Skip()

    def _do_drag(self, frame_id: str) -> None:
        # Create Drag Source
        data = wx.TextDataObject("FRAME:" + frame_id)
        source = wx.DropSource(self)
        source.SetData(data)
        res = source.DoDragDrop(wx.Drag_DefaultMove)

    def on_double_click(self, event) -> None:
        idx = self._hit_test(event.GetPosition())
        if idx != -1:
            fid = self.visible_frames()[idx].id
            if self.on_frame_double_click:
                self.on_frame_double_click(fid)

    def on_leave(self, event) -> None:
        # self.hovered_frame_id = None
        # self.Refresh()
        pass
