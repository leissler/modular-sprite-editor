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

class TimelineControl(wx.ScrolledWindow):
    """
    A horizontal timeline visualization of the animation frames.
    Allows clicking to seek to a specific frame.
    Supports Drag-and-Drop (Source & Target).
    """
    def __init__(self, parent, project: Project):
        super().__init__(parent, style=wx.BORDER_SUNKEN | wx.WANTS_CHARS)
        self.SetScrollRate(0, 0) # Disable native scrolling logic interference
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
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT) # Critical for Mac custom paint
        self.SetDropTarget(TimelineDropTarget(self))
        
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_right_down)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mousewheel)
        self.Bind(wx.EVT_SIZE, lambda e: self.Refresh(False))

    def set_project(self, project: Project):
        self.project = project
        self.animation = None
        self.current_index = 0
        self.generator.clear_cache()
        self.Refresh(False)

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

    def on_paint(self, event):
        try:
             # Use standard PaintDC to be safe
             dc = wx.PaintDC(self)
             self.DoPrepareDC(dc)
             
             width = self.GetVirtualSize()[0]
             height = self.GetClientSize().height
             
             w, h, slot_w, slot_h, start_x, gap = self._get_metrics()

             # Fill Background
             dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
             dc.Clear()
        except Exception as e:
             # print(f"Paint Error: {e}")
             pass
             return

        if not self.animation:
             # Draw "No Animation" text
             font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
             dc.SetFont(font)
             dc.SetTextForeground(wx.Colour(150, 150, 150))
             dc.DrawText("No Animation Selected", 20, 20)
             return

        # Draw Slots
        for i, af in enumerate(self.animation.aframes):
            # Adjust x for scroll_x
            x = start_x + i * (slot_w + gap) - self.scroll_x
            y = (h - slot_h) // 2
            
            rect = wx.Rect(x, y, slot_w, slot_h)
            
            # Culling - Use Rect Intersection
            # For wx.Panel with manual scroll_x, view_rect is simply the client area.
            view_rect = wx.Rect(0, 0, w, h)
            
            if not view_rect.Intersects(rect):
                continue

            # Selection Highlight
            if i == self.current_index:
                dc.SetBrush(wx.Brush(wx.Colour(60, 100, 160)))
                dc.SetPen(wx.Pen(wx.Colour(100, 150, 220), width=2))
                dc.DrawRectangle(rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4)
            
            # Draw Thumbnail Background
            dc.SetBrush(wx.Brush(wx.Colour(50, 50, 50)))
            dc.SetPen(wx.Pen(wx.Colour(100, 100, 100)))
            dc.DrawRectangle(rect)

            # Render Content - USE BITMAP METHOD LIKE FRAME PALETTE
            frame = self.project.get_frame(af.frame_id)
            
            if frame:
                rot = getattr(af, "rotation_degrees", 0.0)
                bmp = self.generator.render_thumbnail(
                    self.project, 
                    frame, 
                    rect.width, 
                    rect.height, 
                    flip_x=af.flip_x, 
                    flip_y=af.flip_y, 
                    rotation=rot, 
                    mapping=self.project.active_mapping
                )
                dc.DrawBitmap(bmp, rect.x, rect.y)
            
            # Frame Number
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            dc.SetFont(font)
            dc.SetTextForeground(wx.Colour(200, 200, 200))
            dc.DrawText(str(i), rect.x + 2, rect.y + 2)
            
            # Drop Marker
            if i == self.drop_marker_index:
                dc.SetPen(wx.Pen(wx.Colour(255, 255, 0), width=3))
                dc.DrawLine(rect.x - gap // 2 - 2, rect.y - 10, rect.x - gap // 2 - 2, rect.y + rect.height + 10)

        # Draw Drop Marker at end
        if self.animation and self.drop_marker_index == len(self.animation.aframes):
             last_x = start_x + len(self.animation.aframes) * (slot_w + gap) - self.scroll_x
             y = (h - slot_h) // 2
             dc.SetPen(wx.Pen(wx.Colour(255, 255, 0), width=3))
             dc.DrawLine(int(last_x - gap // 2 - 2), 0, int(last_x - gap // 2 - 2), h)


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
