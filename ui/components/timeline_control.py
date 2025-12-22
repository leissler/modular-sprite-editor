import wx
from typing import Optional, List, Callable
from models import Animation, AFrame, Project
from ui.utils import ThumbnailGenerator

class TimelineDropTarget(wx.TextDropTarget):
    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline

    def OnDragOver(self, x, y, defResult):
        # Calculate insertion index
        idx = self.timeline._hit_test_insertion(x)
        self.timeline.set_drop_marker(idx)
        return defResult

    def OnDropText(self, x, y, text):
        idx = self.timeline._hit_test_insertion(x)
        self.timeline.set_drop_marker(-1)
        
        if text.startswith("FRAME:"):
            frame_id = text.split(":", 1)[1]
            if self.timeline.on_insert_frame:
                self.timeline.on_insert_frame(frame_id, idx)
        elif text.startswith("INDEX:"):
            try:
                from_idx = int(text.split(":", 1)[1])
                if self.timeline.on_reorder_frame:
                    self.timeline.on_reorder_frame(from_idx, idx)
            except ValueError:
                pass
                
        return True

    def OnLeave(self):
        self.timeline.set_drop_marker(-1)

class TimelineControl(wx.Panel):
    """
    A horizontal timeline visualization of the animation frames.
    Allows clicking to seek to a specific frame.
    Supports Drag-and-Drop (Source & Target).
    """
    def __init__(self, parent, project: Project):
        super().__init__(parent, style=wx.BORDER_SUNKEN | wx.WANTS_CHARS)
        self.project = project
        self.animation: Optional[Animation] = None

        self.current_index: int = 0
        self.on_seek: Optional[Callable[[int], None]] = None
        self.generator = ThumbnailGenerator()
        
        # Callbacks for modification
        self.on_remove: Optional[Callable[[int], None]] = None
        self.on_reorder: Optional[Callable[[int, int], None]] = None 
        # New D&D Callbacks
        self.on_insert_frame: Optional[Callable[[str, int], None]] = None # (frame_id, insert_idx)
        self.on_reorder_frame: Optional[Callable[[int, int], None]] = None # (from_idx, to_idx)
        self.on_edit_frame: Optional[Callable[[str], None]] = None # (frame_id)

        self.drop_marker_index: int = -1
        self._drag_start_pos: Optional[wx.Point] = None

        self.SetBackgroundColour(wx.Colour(40, 40, 40))
        self.SetDropTarget(TimelineDropTarget(self))
        
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_right_down)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mousewheel)
        self.Bind(wx.EVT_SIZE, lambda e: self.Refresh(False))

    def on_key_down(self, event) -> None:
        if not self.animation:
            event.Skip()
            return
            
        code = event.GetKeyCode()
        
        if code == wx.WXK_LEFT:
            new_idx = max(0, self.current_index - 1)
            if new_idx != self.current_index:
                self.current_index = new_idx
                self._ensure_visible(new_idx)
                self.Refresh(False)
                if self.on_seek: self.on_seek(new_idx)
        
        elif code == wx.WXK_RIGHT:
            new_idx = min(len(self.animation.aframes) - 1, self.current_index + 1)
            if new_idx != self.current_index:
                self.current_index = new_idx
                self._ensure_visible(new_idx)
                self.Refresh(False)
                if self.on_seek: self.on_seek(new_idx)
                
        elif code == wx.WXK_DELETE or code == wx.WXK_BACK:
             if 0 <= self.current_index < len(self.animation.aframes):
                 self._do_remove(self.current_index)
                 
        else:
            event.Skip()

    def set_animation(self, anim: Optional[Animation]) -> None:
        self.animation = anim
        self.current_index = 0
        self.scroll_x = 0
        self.Refresh(False)

    def set_current_index(self, idx: int) -> None:
        if self.animation and self.animation.aframes:
             self.current_index = max(0, min(idx, len(self.animation.aframes) - 1))
             self._ensure_visible(self.current_index)
        else:
             self.current_index = 0
        self.Refresh(False)

    def set_drop_marker(self, idx: int) -> None:
        if self.drop_marker_index != idx:
            self.drop_marker_index = idx
            self.Refresh(False)

    def _get_metrics(self):
        w, h = self.GetClientSize()
        slot_h = h - 10
        slot_w = slot_h
        start_x = 10
        gap = 2
        return w, h, slot_w, slot_h, start_x, gap

    def _clamp_scroll(self):
        if not self.animation: return
        w, h, slot_w, slot_h, start_x, gap = self._get_metrics()
        count = len(self.animation.aframes)
        total_w = start_x + count * (slot_w + gap) + start_x
        max_scroll = max(0, total_w - w)
        self.scroll_x = max(0, min(self.scroll_x, max_scroll))

    def _ensure_visible(self, idx: int):
        w, h, slot_w, slot_h, start_x, gap = self._get_metrics()
        item_x = start_x + idx * (slot_w + gap)
        item_w = slot_w + gap
        
        # Determine strict visibility bounds
        # Left edge of item < scroll_x -> scroll left
        # Right edge of item > scroll_x + w -> scroll right
        
        if item_x < self.scroll_x:
            self.scroll_x = item_x - start_x # Add a bit of padding? No, start_x is padding
        elif item_x + item_w > self.scroll_x + w:
            self.scroll_x = item_x + item_w - w + start_x
        
        self._clamp_scroll()

    def on_mousewheel(self, event: wx.MouseEvent) -> None:
        # Horizontal scroll usually comes from Shift+Wheel or horizontal wheel
        # But we maps vertical wheel to horizontal scroll if no vertical scroll
        delta = event.GetWheelRotation()
        # Typical delta is 120. Map to ~1 item width?
        # Let's say 120 -> 50px
        move = delta * 0.5
        self.scroll_x -= move
        self._clamp_scroll()
        self.Refresh(False)

    def on_paint(self, event) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.Clear()
        
        if not self.animation:
            return

        w, h, slot_w, slot_h, start_x, gap = self._get_metrics()
        self._clamp_scroll()
        
        gc = wx.GraphicsContext.Create(dc)
        
        # Apply translation? No, I'll calculate X manually to control culling easily
        
        for i, af in enumerate(self.animation.aframes):
            x = start_x + i * (slot_w + gap) - self.scroll_x
            
            # Culling
            if x + slot_w < 0: continue
            if x > w: break
            
            frame_id = af.frame_id
            frame = self.project.get_frame(frame_id)
            
            # Draw Slot Background
            is_selected = (i == self.current_index)
            if is_selected:
                gc.SetBrush(wx.Brush(wx.Colour(100, 120, 220))) # Highlight
                gc.SetPen(wx.Pen(wx.Colour(200, 200, 250), 2))
            else:
                gc.SetBrush(wx.Brush(wx.Colour(60, 60, 60)))
                gc.SetPen(wx.Pen(wx.Colour(100, 100, 100), 1))
                
            gc.DrawRoundedRectangle(x, 5, slot_w, slot_h, 4)
            
            # Draw Thumbnail
            if frame:
                thumb = self.generator.render_thumbnail(self.project, frame, slot_w - 4, slot_h - 4, flip_x=af.flip_x, flip_y=af.flip_y)
                gc.DrawBitmap(thumb, x + 2, 5 + 2, slot_w - 4, slot_h - 4)
            
            # Draw Frame Number Overlay
            text = f"{i}"
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            gc.SetFont(font, wx.Colour(255, 255, 255))
            gc.SetFont(font, wx.Colour(0, 0, 0))
            gc.DrawText(text, x + 4, 5 + 2)
            gc.SetFont(font, wx.Colour(255, 255, 255))
            gc.DrawText(text, x + 3, 5 + 2)
            
        # Draw Drop Marker
        if self.drop_marker_index != -1:
            mx = start_x + self.drop_marker_index * (slot_w + gap) - (gap / 2) - self.scroll_x
            if 0 < mx < w:
                gc.SetPen(wx.Pen(wx.Colour(255, 255, 0), 3))
                gc.StrokeLine(mx, 5 - 2, mx, 5 + slot_h + 2)

    def _hit_test(self, x) -> int:
        w, h, slot_w, slot_h, start_x, gap = self._get_metrics()
        
        # Adjust x for scroll
        # x_screen = x_world - scroll
        # x_world = x_screen + scroll
        x_world = x + self.scroll_x
        
        if x_world < start_x: return -1
        idx = int((x_world - start_x) / (slot_w + gap))
        if 0 <= idx < len(self.animation.aframes):
            return idx
        return -1

    def _hit_test_insertion(self, x) -> int:
        # Determine closest insertion index (between frames)
        if not self.animation: return 0
        w, h, slot_w, slot_h, start_x, gap = self._get_metrics()
        
        x_world = x + self.scroll_x
        
        # Relative x
        rel_x = x_world - start_x
        idx = round(rel_x / (slot_w + gap))
        return max(0, min(idx, len(self.animation.aframes)))

    def on_left_down(self, event) -> None:
        self.SetFocus()
        if not self.animation: return
        idx = self._hit_test(event.GetX())
        if idx != -1:
            self.current_index = idx
            self.Refresh(False)
            if self.on_seek: self.on_seek(idx)
            # Start Drag potential
            self._drag_start_pos = event.GetPosition()
        else:
            self._drag_start_pos = None

    def on_left_up(self, event) -> None:
        self._drag_start_pos = None

    def on_motion(self, event) -> None:
        if event.Dragging() and event.LeftIsDown() and self._drag_start_pos:
            drag_vec = event.GetPosition() - self._drag_start_pos
            if abs(drag_vec.x) > 5 or abs(drag_vec.y) > 5:
                # Start Drag Reorder
                idx = self._hit_test(self._drag_start_pos.x) # _hit_test uses scroll_x, so it needs screen pos
                if idx != -1:
                    data = wx.TextDataObject(f"INDEX:{idx}")
                    source = wx.DropSource(self)
                    source.SetData(data)
                    source.DoDragDrop(wx.Drag_DefaultMove)
                    self._drag_start_pos = None
        event.Skip()

    def on_right_down(self, event) -> None:
        self.SetFocus()
        if not self.animation or not self.animation.aframes: return
        idx = self._hit_test(event.GetX())
        if idx != -1:
            self.current_index = idx
            self.Refresh(False)
            if self.on_seek: self.on_seek(idx)
            
            menu = wx.Menu()
            item_move_left = menu.Append(wx.ID_ANY, "Move Left")
            item_move_right = menu.Append(wx.ID_ANY, "Move Right")
            menu.AppendSeparator()
            item_edit = menu.Append(wx.ID_ANY, "Edit Frame")
            menu.AppendSeparator()
            item_delete = menu.Append(wx.ID_ANY, "Delete Frame")
            
            if idx == 0: item_move_left.Enable(False)
            if idx == len(self.animation.aframes) - 1: item_move_right.Enable(False)
            
            self.Bind(wx.EVT_MENU, lambda e: self._do_reorder(idx, -1), item_move_left)
            self.Bind(wx.EVT_MENU, lambda e: self._do_reorder(idx, 1), item_move_right)
            self.Bind(wx.EVT_MENU, lambda e: self._do_edit(idx), item_edit)
            self.Bind(wx.EVT_MENU, lambda e: self._do_remove(idx), item_delete)
            
            self.PopupMenu(menu)
            menu.Destroy()

    def _do_reorder(self, idx, direction):
        if self.on_reorder: self.on_reorder(idx, direction)

    def _do_remove(self, idx):
        if self.on_remove: self.on_remove(idx)

    def _do_edit(self, idx):
        if self.on_edit_frame and self.animation:
            fid = self.animation.aframes[idx].frame_id
            self.on_edit_frame(fid)
