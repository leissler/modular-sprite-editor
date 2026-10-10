"""Module Mapping Editor Panel."""
from __future__ import annotations

import wx
from typing import Optional, Dict

from models import Project, ModuleMapping, generate_id
from ui import app_services
from ui.utils import ThumbnailGenerator

class MappingVisualizer(wx.ScrolledWindow):
    """Visualizes and Edits the Module Mapping using two strips."""
    def __init__(self, parent, project: Project):
        super().__init__(parent, style=wx.BORDER_SUNKEN)
        self.project = project
        self.mapping: Optional[ModuleMapping] = None
        self.SetBackgroundColour(wx.Colour(50, 50, 50))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT) # Critical Fix
        
        self.slot_size = 64
        self.gap = 4
        self.padding = 30 # Increased padding for headers
        self.generator = ThumbnailGenerator()
        
        # State
        self.highlight_idx = -1 # Index of slot being hovered
        self._drag_source_module_id: Optional[str] = None
        self._show_names = True # Match Default Checkbox State
        self._zoom_scale = 1.0
        
        self.on_change_callback = None

        self.SetScrollRate(10, 10)
        
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_RIGHT_DOWN, self.on_right_down)
        self.Bind(wx.EVT_SIZE, self.on_size)

    def on_right_down(self, event):
        idx = self._hit_test_mapped(event.GetPosition())
        if idx == -1 or not self.mapping:
            event.Skip()
            return
        source = self.project.modules[idx]
        menu = wx.Menu()
        item_reset = menu.Append(wx.ID_ANY, f"Use Original ({source.name})")
        item_hide = menu.Append(wx.ID_ANY, "Hide This Module")
        item_reset.Enable(source.id in self.mapping.map)
        item_hide.Enable(not (source.id in self.mapping.map and self.mapping.map[source.id] is None))

        def apply(target):
            if target == "reset":
                self.mapping.map.pop(source.id, None)
            else:
                self.mapping.map[source.id] = None
            self.Refresh()
            if self.on_change_callback:
                self.on_change_callback()

        self.Bind(wx.EVT_MENU, lambda e: apply("reset"), item_reset)
        self.Bind(wx.EVT_MENU, lambda e: apply("hide"), item_hide)
        self.PopupMenu(menu)
        menu.Destroy()

    def set_zoom(self, scale: float):
        self._zoom_scale = scale
        self.update_virtual_size()
        self.Refresh()

    def set_show_names(self, show: bool):
        self._show_names = show
        self.update_virtual_size()
        self.Refresh()

    def _get_slot_size(self):
        base = int(64 * self._zoom_scale)
        if self._show_names:
            return base, base + 20 # 20px for text
        return base, base

    def set_mapping(self, mapping: Optional[ModuleMapping]):
        self.mapping = mapping
        self.Refresh()
        self.update_virtual_size()

    def update_virtual_size(self):
        w, h = self.GetClientSize()
        
        if not self.mapping:
            self.SetVirtualSize(w, h)
            self.Scroll(0, 0)
            return

        count = len(self.project.modules)
        w_slot, h_slot = self._get_slot_size()
        width = self.padding * 2 + count * (w_slot + self.gap)
        height = self.padding * 2 + (h_slot * 2) + self.gap * 4 + 40 
        self.SetVirtualSize(width, height)

    def on_size(self, event):
        self.update_virtual_size()
        event.Skip()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
        dc.Clear()
        
        # Hide content if no mapping selected
        if not self.mapping:
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            dc.SetFont(font)
            dc.SetTextForeground(wx.Colour(150, 150, 150))
            
            w, h = self.GetClientSize()
            text = "Select or Create a Mapping to Edit"
            tw, th = dc.GetTextExtent(text)
            dc.DrawText(text, int((w - tw) / 2), int((h - th) / 2))
            return
 
        # Layout
        sw, sh = self._get_slot_size()
        base_sz = sw # width is always base
 
        # Calculate Global Scale
        max_mod_w, max_mod_h = 0, 0
        for m in self.project.modules:
            max_mod_w = max(max_mod_w, m.rect[2])
            max_mod_h = max(max_mod_h, m.rect[3])
            
        slot_inner = base_sz - 4
        scale = 1.0
        if max_mod_w > 0 and max_mod_h > 0:
            scale = min(slot_inner / max_mod_w, slot_inner / max_mod_h)
            
        # Draw Source Strip (Top)
        strip_y = self.padding
        
        # gc = wx.GraphicsContext.Create(dc)
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        dc.SetFont(font)
        dc.SetTextForeground(wx.Colour(200, 200, 200)) # Light Gray
        
        dc.DrawText("Source Modules", self.padding, strip_y - 20)
        
        if not self.project.modules:
            dc.DrawText("(No modules in project)", self.padding, strip_y + 10)
            return
 
        for i, mod in enumerate(self.project.modules):
            x = self.padding + i * (sw + self.gap)
            self._draw_slot(dc, x, strip_y, base_sz, mod, is_source=True, custom_scale=scale)
 
        # Draw Mapped Strip (Bottom)
        strip_y = self.padding + sh + 40
        dc.DrawText("Replacement shown for each module (drag a source module onto a slot, right-click to reset or hide)", self.padding, strip_y - 20)
        
        for i, mod in enumerate(self.project.modules):
            x = self.padding + i * (sw + self.gap)
            
            # Find target: unmapped = original module, None = hidden, unknown id = missing
            target_mod = None
            target_id = None
            is_missing = False
            is_hidden = False
            
            if self.mapping:
                if mod.id in self.mapping.map:
                    target_id = self.mapping.map.get(mod.id)
                    if target_id is None:
                        is_hidden = True
                    else:
                        target_mod = self.project.get_module(target_id)
                        if not target_mod:
                            is_missing = True
            
            is_highlight = (i == self.highlight_idx)
            self._draw_slot(
                dc, x, strip_y, base_sz, target_mod, is_source=False, highlight=is_highlight,
                custom_scale=scale, missing_id=target_id if is_missing else None, hidden=is_hidden,
            )
 
        # Draw Drag Ghost
        if self._drag_source_module_id and getattr(self, '_drag_cursor_pos', None):
             mod = self.project.get_module(self._drag_source_module_id)
             if mod:
                 pt = self.CalcUnscrolledPosition(self._drag_cursor_pos)
                 rect = wx.Rect(pt.x - 24, pt.y - 24, 48, 48)
                 self.generator.draw_thumbnail_direct(dc, self.project, mod, rect, custom_scale=scale)
                 # thumb = self.generator.render_thumbnail(self.project, mod, 48, 48, custom_scale=scale)
                 # dc.DrawBitmap(thumb, pt.x - 24, pt.y - 24)
 
    def _draw_slot(self, dc, x, y, size, module, is_source, highlight=False, custom_scale=0.0, missing_id: str = None, hidden: bool = False):
        # Background
        if highlight:
            dc.SetBrush(wx.Brush(wx.Colour(100, 100, 150)))
            dc.SetPen(wx.Pen(wx.Colour(200, 200, 255), 2))
        else:
            dc.SetBrush(wx.Brush(wx.Colour(40, 40, 40)))
            dc.SetPen(wx.Pen(wx.Colour(80, 80, 80), 1))
            
        dc.DrawRectangle(int(x), int(y), int(size), int(size))
        
        if module:
            # Draw Thumbnail
            rect = wx.Rect(int(x + 2), int(y + 2), size - 4, size - 4)
            self.generator.draw_thumbnail_direct(dc, self.project, module, rect, custom_scale=custom_scale)
            
            if self._show_names:
                font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
                dc.SetFont(font)
                dc.SetTextForeground(wx.Colour(200, 200, 200))
                # Truncate
                name = module.name
                if len(name) > 10: name = name[:8] + ".."
                tw, th = dc.GetTextExtent(name)
                dc.DrawText(name, int(x + (size - tw)/2), int(y + size + 2))
        else:
            # Draw "None" or "Missing"
            if not is_source:
                font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
                dc.SetFont(font)
                
                if missing_id:
                    dc.SetTextForeground(wx.Colour(255, 100, 100))
                    text = "Missing"
                elif hidden:
                    dc.SetTextForeground(wx.Colour(255, 170, 80))
                    text = "Hidden"
                else:
                    # Not remapped: the original module is used
                    dc.SetTextForeground(wx.Colour(120, 120, 120))
                    text = "= original"
                    
                tw, th = dc.GetTextExtent(text)
                dc.DrawText(text, int(x + (size - tw)/2), int(y + size/2 - th/2))

    def _hit_test(self, pt) -> int:
        sw, sh = self._get_slot_size()
        x, y = self.CalcUnscrolledPosition(pt)
        
        # Check if in Bottom Strip Y range
        bottom_strip_y = self.padding + sh + 40
        if bottom_strip_y <= y <= bottom_strip_y + sh:
            rel_x = x - self.padding
            if rel_x < 0: return -1
            idx = int(rel_x / (sw + self.gap))
            if 0 <= idx < len(self.project.modules):
                return idx
        return -1

    def _hit_test_source(self, pt) -> int:
        sw, sh = self._get_slot_size()
        x, y = self.CalcUnscrolledPosition(pt)
        top_strip_y = self.padding
        if top_strip_y <= y <= top_strip_y + sh:
            rel_x = x - self.padding
            if rel_x < 0: return -1
            idx = int(rel_x / (sw + self.gap))
            if 0 <= idx < len(self.project.modules):
                return idx
        return -1

    def on_left_down(self, event):
        # Start dragging from Source OR Bottom (Re-map)
        pt = event.GetPosition()
        
        # Check Top
        idx = self._hit_test_source(pt)
        if idx != -1:
            mod = self.project.modules[idx]
            self._drag_source_module_id = mod.id
            self._drag_cursor_pos = pt
            self.CaptureMouse()
            event.Skip()
            return

        # Check Bottom (Mapped Targets)
        idx_bottom = self._hit_test_mapped(pt)
        if idx_bottom != -1:
            # We are dragging what is currently mapped here?
            # Or are we dragging the TARGET module (to map it elsewhere?)
            # Usually users drag SOURCE modules.
            # If I drag from bottom strip, I likely want to move the ASSIGNED module to another slot?
            # Or invalid?
            # Let's assume we drag the module dependent on the target_id if present?
            # Implementation Plan said "useful for moving a mapping". 
            # So if Slot A maps Module X, dragging Slot A means dragging Module X.
            if self.mapping:
                target_mod_id = self.project.modules[idx_bottom].id
                mapped_id = self.mapping.map.get(target_mod_id)
                if mapped_id:
                    self._drag_source_module_id = mapped_id
                    self._drag_cursor_pos = pt
                    self.CaptureMouse()
                    event.Skip()
                    return

        event.Skip()

    def on_motion(self, event):
        if self._drag_source_module_id and event.Dragging():
            self._drag_cursor_pos = event.GetPosition()
            
            # Highlight target based on mouse exposure
            idx = self._hit_test_mapped(self._drag_cursor_pos)
            if idx != self.highlight_idx:
                self.highlight_idx = idx
            self.Refresh()
            
        elif not event.Dragging():
            # Just Hover
            idx = self._hit_test_mapped(event.GetPosition())
            if idx != self.highlight_idx:
                self.highlight_idx = idx
                self.Refresh()

    def on_left_up(self, event):
        if self.HasCapture():
            self.ReleaseMouse()
        
        if self._drag_source_module_id:
            # Drop
            idx = self._hit_test_mapped(event.GetPosition())
            if idx != -1 and self.mapping:
                # Map source[idx] -> dragged_module
                target_module = self.project.modules[idx]
                self.mapping.map[target_module.id] = self._drag_source_module_id
                self.Refresh()
                
                if self.on_change_callback:
                    self.on_change_callback()
        
        self._drag_source_module_id = None
        self._drag_cursor_pos = None
        self.highlight_idx = -1
        self.Refresh()
        
    def _hit_test_mapped(self, pt) -> int:
        # Renamed for clarity vs source
        return self._hit_test(pt)


class MappingFramePreview(wx.ScrolledWindow):
    """
    Real-time preview of all frames with the current mapping applied.
    Visually matches FramePalette (AnimationEditor) with uniform scaling and selection.
    """
    def __init__(self, parent, project: Project):
        super().__init__(parent, style=wx.BORDER_SUNKEN)
        self.project = project
        self.mapping: Optional[ModuleMapping] = None
        self.selected_frame_id: Optional[str] = None
        # Default to True to match Palette visual style, but will be controlled by parent's toggle too
        self.show_names: bool = True  
        
        self.SetBackgroundColour(wx.Colour(40, 40, 40))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetScrollRate(20, 20)
        
        self.generator = ThumbnailGenerator()
        
        # Match FramePalette dimensions
        self.item_size = (128, 128)
        self.padding = 10
        self.cols = 1
        
        self._cached_scale: float = 0.0
        self._last_mapping_id: Optional[int] = None
        
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)

    def set_mapping(self, mapping: Optional[ModuleMapping]):
        self.mapping = mapping
        # Invalidate cache if mapping changed
        mid = id(mapping) if mapping else None
        if mid != self._last_mapping_id:
            self._cached_scale = 0.0 # Force recalc
            self._last_mapping_id = mid
            
        self.Refresh()
        self.update_virtual_size()

    def set_show_names(self, show: bool):
        self.show_names = show
        self.Refresh()

    def update_virtual_size(self):
        w, h = self.GetClientSize()
        if w < 10: w = 100
        
        if not self.mapping:
            self.SetVirtualSize(w, h)
            self.Scroll(0, 0)
            return

        full_w = self.item_size[0] + self.padding
        self.cols = max(1, w // full_w)
        
        count = len(self.project.frames)
        rows = (count + self.cols - 1) // self.cols
        
        full_h = self.item_size[1] + self.padding
        virtual_h = rows * full_h + self.padding
        
        self.SetVirtualSize(w, virtual_h)

    def on_size(self, event):
        self.update_virtual_size()
        event.Skip()
        
    def _calculate_uniform_scale(self) -> float:
        """One scale for all frames (with this mapping), so their relative sizes stay visible."""
        if self._cached_scale > 0:
            return self._cached_scale
        sizes = [self.generator.frame_size(self.project, frame, self.mapping) for frame in self.project.frames]
        global_max_w = max((w for w, _h in sizes), default=0)
        global_max_h = max((h for _w, h in sizes), default=0)
        uniform_scale = 1.0
        if global_max_w > 0 and global_max_h > 0:
            uniform_scale = min(self.item_size[0] / global_max_w, self.item_size[1] / global_max_h, 32.0)
        self._cached_scale = uniform_scale
        return uniform_scale

    def _get_item_rect(self, index: int) -> wx.Rect:
        full_w = self.item_size[0] + self.padding
        full_h = self.item_size[1] + self.padding
        
        col = index % self.cols
        row = index // self.cols
        
        x = self.padding + col * full_w
        y = self.padding + row * full_h
        return wx.Rect(x, y, self.item_size[0], self.item_size[1])

    def _hit_test(self, pos: wx.Point) -> int:
        unscrolled = self.CalcUnscrolledPosition(pos)
        full_w = self.item_size[0] + self.padding
        full_h = self.item_size[1] + self.padding
        
        col = (unscrolled.x - self.padding) // full_w
        row = (unscrolled.y - self.padding) // full_h
        
        if col < 0 or col >= self.cols or row < 0:
            return -1
        
        index = row * self.cols + col
        if 0 <= index < len(self.project.frames):
            return index
        return -1

    def on_left_down(self, event):
        idx = self._hit_test(event.GetPosition())
        if idx != -1:
            frame = self.project.frames[idx]
            self.selected_frame_id = frame.id
            self.Refresh()
        else:
            self.selected_frame_id = None
            self.Refresh()
        event.Skip()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(wx.Colour(40, 40, 40)))
        dc.Clear()
        
        if not self.mapping:
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
            dc.SetFont(font)
            dc.SetTextForeground(wx.Colour(100, 100, 100))
            w, h = self.GetClientSize()
            msg = "Select a mapping applied to preview frames"
            tw, th = dc.GetTextExtent(msg)
            dc.DrawText(msg, (w - tw)//2, (h - th)//2)
            return

        if not self.project.frames:
            return

        # Calculate Uniform Scale
        scale = self._calculate_uniform_scale()
        
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        dc.SetFont(font)
        
        vs_x, vs_y = self.GetViewStart()
        pu_x, pu_y = self.GetScrollPixelsPerUnit()
        cs_w, cs_h = self.GetClientSize()
        view_rect = wx.Rect(vs_x * pu_x, vs_y * pu_y, cs_w, cs_h)

        for i, frame in enumerate(self.project.frames):
            r = self._get_item_rect(i)
            
            if not view_rect.Intersects(r):
                continue
            
            # Draw Thumbnail
            bmp = self.generator.render_thumbnail(self.project, frame, r.width, r.height, custom_scale=scale, mapping=self.mapping)
            dc.DrawBitmap(bmp, r.x, r.y)
            
            # Draw Name Overlay
            if self.show_names:
                dc.SetTextForeground(wx.Colour(255, 255, 255))
                tex_w, tex_h = dc.GetTextExtent(frame.name)
                
                # Background Bar
                dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 128)))
                dc.SetPen(wx.Pen(wx.TRANSPARENT_PEN))
                dc.DrawRectangle(r.x, r.y + r.height - tex_h - 4, r.width, tex_h + 4)
                
                # Centered Text
                dc.DrawText(frame.name, r.x + (r.width - tex_w)//2, r.y + r.height - tex_h - 2)
            
            # Selection Border
            if frame.id == self.selected_frame_id:
                dc.SetBrush(wx.Brush(wx.TRANSPARENT_BRUSH))
                dc.SetPen(wx.Pen(wx.Colour(100, 200, 255), 3))
                dc.DrawRectangle(r.x - 2, r.y - 2, r.width + 4, r.height + 4)


class MappingEditorPanel(wx.Panel):
    def __init__(self, parent, project: Project):
        super().__init__(parent)
        self.project = project
        self.current_mapping: Optional[ModuleMapping] = None
        
        # Splitter occupies the full panel
        self.splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # Left: List
        self.left_panel = wx.Panel(self.splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.list_ctrl = wx.ListCtrl(self.left_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_EDIT_LABELS)
        self.list_ctrl.InsertColumn(0, "Name", width=100)
        
        btns_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(self.left_panel, label="Add")
        self.btn_dup = wx.Button(self.left_panel, label="Duplicate")
        self.btn_del = wx.Button(self.left_panel, label="Delete")
        btns_sizer.Add(self.btn_add, 1, wx.RIGHT, 4)
        btns_sizer.Add(self.btn_dup, 1, wx.RIGHT, 4)
        btns_sizer.Add(self.btn_del, 1)
        
        left_sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 4)
        left_sizer.Add(btns_sizer, 0, wx.EXPAND | wx.ALL, 4)
        self.left_panel.SetSizer(left_sizer)
        
        # Right: Visualizer & Tools
        self.right_panel = wx.Panel(self.splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Tools

        # Top toolbar for right panel
        self.right_panel_top = wx.Panel(self.right_panel)
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Buttons
        self.btn_clear = wx.Button(self.right_panel_top, label="Reset All to Original")
        self.btn_clear.SetToolTip("Remove every replacement and hidden module from this mapping")
        top_sizer.Add(self.btn_clear, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 10)
        
        # Toolbar for zoom and names
        self.tb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Zoom Slider
        self.slider_zoom = wx.Slider(self.right_panel_top, value=100, minValue=20, maxValue=300, size=(100, -1))
        self.tb_sizer.Add(wx.StaticText(self.right_panel_top, label="Zoom:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.tb_sizer.Add(self.slider_zoom, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)
        
        # Show Names
        self.chk_names = wx.CheckBox(self.right_panel_top, label="Show Names")
        self.chk_names.SetValue(True) # Default to True to match Palette style
        self.tb_sizer.Add(self.chk_names, 0, wx.ALIGN_CENTER_VERTICAL)
        
        top_sizer.Add(self.tb_sizer, 0, wx.ALIGN_CENTER_VERTICAL)
        
        self.right_panel_top.SetSizer(top_sizer)
        right_sizer.Add(self.right_panel_top, 0, wx.EXPAND | wx.ALL, 4)
        
        # Right Splitter (Visualizer / Preview)
        self.right_splitter = wx.SplitterWindow(self.right_panel, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        self.visualizer = MappingVisualizer(self.right_splitter, self.project)
        self.visualizer.on_change_callback = self.on_mapping_changed
        
        # Preview Container with Header
        self.preview_container = wx.Panel(self.right_splitter)
        pc_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header
        header = wx.StaticText(self.preview_container, label="Frame Preview (Mapped)")
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        header.SetFont(font)
        pc_sizer.Add(header, 0, wx.ALL, 4)
        
        self.preview = MappingFramePreview(self.preview_container, self.project)
        pc_sizer.Add(self.preview, 1, wx.EXPAND)
        self.preview_container.SetSizer(pc_sizer)
        
        self.right_splitter.SplitHorizontally(self.visualizer, self.preview_container, -300) # Give it a bit more space by default? Or -250
        self.right_splitter.SetSashGravity(0.6)
        

        right_sizer.Add(self.right_splitter, 1, wx.EXPAND | wx.ALL, 4)
        self.right_panel.SetSizer(right_sizer)
        
        self.splitter.SplitVertically(self.left_panel, self.right_panel, 240)
        self.splitter.SetMinimumPaneSize(100)
        self.splitter.SetSashGravity(0.1)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        
        self.refresh_list()
        
        # Bindings
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add)
        self.btn_dup.Bind(wx.EVT_BUTTON, self.on_duplicate)
        self.btn_del.Bind(wx.EVT_BUTTON, self.on_del)
        self.list_ctrl.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        self._syncing_selection = False
        self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_deselect)
        self.list_ctrl.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.on_rename)
        
        self.chk_names.Bind(wx.EVT_CHECKBOX, self.on_toggle_names)
        self.slider_zoom.Bind(wx.EVT_SLIDER, self.on_zoom)
        
        self.list_ctrl.Bind(wx.EVT_SIZE, self.on_list_resize)

    def on_list_resize(self, event):
        width = self.list_ctrl.GetClientSize().width
        self.list_ctrl.SetColumnWidth(0, width)
        event.Skip()

    def on_mapping_changed(self):
        """Called when visualizer modifies the mapping."""
        # Mapped modules can change frame bounds, so the cached preview scale is stale.
        self.preview._cached_scale = 0.0
        self.preview.Refresh()
        app_services.request_checkpoint()

    # --- Panel interface used by the main window ---
    def get_active_canvas(self):
        return None

    def refresh_after_history(self) -> None:
        self.current_mapping = self.project.active_mapping
        self.refresh_list()
        self.visualizer.set_mapping(self.current_mapping)
        self.preview.set_mapping(self.current_mapping)
        self.preview._cached_scale = 0.0

    def on_active_mapping_changed(self) -> None:
        """Keep the list selection in sync with the global preview mapping selector."""
        if self.current_mapping is self.project.active_mapping:
            return
        self.current_mapping = self.project.active_mapping
        self._syncing_selection = True
        try:
            self.refresh_list()
        finally:
            self._syncing_selection = False
        self.visualizer.set_mapping(self.current_mapping)
        self.preview.set_mapping(self.current_mapping)

    def _set_active(self, mapping: Optional[ModuleMapping]) -> None:
        self.current_mapping = mapping
        self.visualizer.set_mapping(mapping)
        self.preview.set_mapping(mapping)
        self.project.active_mapping = mapping
        if not self._syncing_selection:
            app_services.notify_active_mapping_changed()

    def refresh_list(self):
        self.list_ctrl.DeleteAllItems()
        for i, m in enumerate(self.project.mappings):
            self.list_ctrl.InsertItem(i, m.name)
        
        if self.project.active_mapping in self.project.mappings:
            idx_to_select = self.project.mappings.index(self.project.active_mapping)
            self.list_ctrl.Select(idx_to_select)
            self.list_ctrl.EnsureVisible(idx_to_select)
        elif not self.project.mappings:
            self.visualizer.set_mapping(None)
            self.preview.set_mapping(None)
            self.project.active_mapping = None

    def on_add(self, event):
        new_map = ModuleMapping(id=generate_id("map"), name=f"Mapping {len(self.project.mappings) + 1}")
        # Empty map = every module shows its original
        self.project.mappings.append(new_map)
        idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), new_map.name)
        self.list_ctrl.Select(idx)
        self.list_ctrl.EditLabel(idx)
        app_services.request_checkpoint()

    def on_duplicate(self, event):
        idx = self.list_ctrl.GetFirstSelected()
        if not (0 <= idx < len(self.project.mappings)):
            return
        source = self.project.mappings[idx]
        copy_map = ModuleMapping(id=generate_id("map"), name=f"{source.name} copy", map=dict(source.map))
        self.project.mappings.insert(idx + 1, copy_map)
        self.project.active_mapping = copy_map
        self.refresh_list()
        self._set_active(copy_map)
        app_services.request_checkpoint()

    def on_list_key(self, event):
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_BACK):
            self.on_del(None)
            return
        event.Skip()

    def on_del(self, event):
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1:
            return
        mapping = self.project.mappings[idx]
        msg = f"Delete mapping '{mapping.name}' ({len(mapping.map)} remapped module(s))?"
        if wx.MessageBox(msg, "Delete Mapping", wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
            return
        self.project.mappings.pop(idx)
        self.list_ctrl.DeleteItem(idx)
        if idx < self.list_ctrl.GetItemCount():
            self.list_ctrl.Select(idx)
        elif self.list_ctrl.GetItemCount() > 0:
            self.list_ctrl.Select(self.list_ctrl.GetItemCount() - 1)
        else:
            self._set_active(None)
        app_services.request_checkpoint()

    def on_select(self, event):
        idx = event.GetIndex()
        if 0 <= idx < len(self.project.mappings):
            self._set_active(self.project.mappings[idx])

    def on_deselect(self, event):
        if self._syncing_selection:
            return
        # A click on another item deselects first; only clear if nothing ends up selected.
        wx.CallAfter(self._clear_if_unselected)

    def _clear_if_unselected(self):
        if self.list_ctrl.GetFirstSelected() == -1 and self.current_mapping is not None:
            self._set_active(None)

    def on_rename(self, event):
        idx = event.GetIndex()
        if not event.IsEditCancelled() and 0 <= idx < len(self.project.mappings):
            new_name = event.GetLabel().strip()
            if new_name:
                self.project.mappings[idx].name = new_name
                wx.CallAfter(app_services.notify_active_mapping_changed)
                wx.CallAfter(app_services.request_checkpoint)
        event.Skip()

    def on_clear(self, event):
        if not self.current_mapping: return
        dlg = wx.MessageDialog(
            self,
            "Reset every module of this mapping to its original (removes all replacements and hidden modules)?",
            "Reset Mapping",
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if dlg.ShowModal() == wx.ID_YES:
            self.current_mapping.map = {}
            self.visualizer.Refresh()
            self.on_mapping_changed()
        dlg.Destroy()

    def on_toggle_names(self, event):
        checked = event.IsChecked()
        self.visualizer.set_show_names(checked)
        self.preview.set_show_names(checked)

    def on_zoom(self, event):
        scale = self.slider_zoom.GetValue() / 100.0
        self.visualizer.set_zoom(scale)

    def set_project(self, project: Project):
        self.project = project
        self.visualizer.project = project
        self.preview.project = project
        self.current_mapping = None
        self.visualizer.set_mapping(None)
        self.preview.set_mapping(None)
        
        self.refresh_list()
        
        # No Auto-select first mapping by default
        pass
