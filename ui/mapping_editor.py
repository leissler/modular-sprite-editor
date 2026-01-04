"""Module Mapping Editor Panel."""
from __future__ import annotations

import wx
from typing import Optional, Dict

from models import Project, ModuleMapping, generate_id
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

        self.SetScrollRate(10, 10)
        
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_SIZE, self.on_size)

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
        dc = wx.PaintDC(self)
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
        dc.DrawText("Mapped Targets (Drag Source here)", self.padding, strip_y - 20)
        
        for i, mod in enumerate(self.project.modules):
            x = self.padding + i * (sw + self.gap)
            
            # Find target
            target_mod = None
            if self.mapping:
                target_id = self.mapping.map.get(mod.id, None)
                if target_id:
                    target_mod = self.project.get_module(target_id)
            
            is_highlight = (i == self.highlight_idx)
            self._draw_slot(dc, x, strip_y, base_sz, target_mod, is_source=False, highlight=is_highlight, custom_scale=scale)
 
        # Draw Drag Ghost
        if self._drag_source_module_id and getattr(self, '_drag_cursor_pos', None):
             mod = self.project.get_module(self._drag_source_module_id)
             if mod:
                 pt = self.CalcUnscrolledPosition(self._drag_cursor_pos)
                 rect = wx.Rect(pt.x - 24, pt.y - 24, 48, 48)
                 self.generator.draw_thumbnail_direct(dc, self.project, mod, rect, custom_scale=scale)
                 # thumb = self.generator.render_thumbnail(self.project, mod, 48, 48, custom_scale=scale)
                 # dc.DrawBitmap(thumb, pt.x - 24, pt.y - 24)
 
    def _draw_slot(self, dc, x, y, size, module, is_source, highlight=False, custom_scale=0.0):
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
            # thumb = self.generator.render_thumbnail(self.project, module, size - 4, size - 4, custom_scale=custom_scale)
            # dc.DrawBitmap(thumb, int(x + 2), int(y + 2))
            
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
            # Draw "None"
            if not is_source:
                # gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(100, 100, 100))
                # gc.DrawText("None", x + 10, y + size/2 - 5)
                font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
                dc.SetFont(font)
                dc.SetTextForeground(wx.Colour(100, 100, 100))
                dc.DrawText("None", int(x + 10), int(y + size/2 - 5))

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
        # Start dragging from Source
        idx = self._hit_test_source(event.GetPosition())
        if idx != -1:
            mod = self.project.modules[idx]
            self._drag_source_module_id = mod.id
            self.CaptureMouse()
        event.Skip()

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
        # Optimization: Return cached if valid
        if self._cached_scale > 0: return self._cached_scale
        
        global_max_w = 0.0
        global_max_h = 0.0
        
        for frame in self.project.frames:
            if not frame.fmodules: continue
            
            # Calculate bounds with MAPPING applied
            min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
            has = False
            
            for fm in frame.fmodules:
                if fm.ref_type == "module":
                    ref_id = fm.ref_id
                    # APPLY MAPPING
                    if self.mapping and ref_id in self.mapping.map:
                         ref_id = self.mapping.map[ref_id]

                    if not ref_id: continue # Mapped to None or missing

                    mod = self.project.get_module(ref_id)
                    if mod:
                         mw, mh = mod.rect[2], mod.rect[3]
                         piv_x, piv_y = mod.pivot
                         x0 = fm.position[0] - piv_x
                         y0 = fm.position[1] - piv_y
                         min_x = min(min_x, x0)
                         min_y = min(min_y, y0)
                         max_x = max(max_x, x0 + mw)
                         max_y = max(max_y, y0 + mh)
                         has = True
            
            if has:
                global_max_w = max(global_max_w, max(1, max_x - min_x))
                global_max_h = max(global_max_h, max(1, max_y - min_y))

        uniform_scale = 0.0
        if global_max_w > 0 and global_max_h > 0:
             scale_x = self.item_size[0] / global_max_w
             scale_y = self.item_size[1] / global_max_h
             uniform_scale = min(scale_x, scale_y)
             # Cap scale to avoid extreme blowups
             uniform_scale = min(uniform_scale, 32.0)
        
        if uniform_scale == 0: uniform_scale = 1.0
        
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
        dc = wx.PaintDC(self)
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
        self.btn_del = wx.Button(self.left_panel, label="Del")
        btns_sizer.Add(self.btn_add, 1, wx.RIGHT, 4)
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
        self.btn_identity = wx.Button(self.right_panel_top, label="Reset Identity")
        self.btn_clear = wx.Button(self.right_panel_top, label="Clear All")
        top_sizer.Add(self.btn_identity, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 4)
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
        # Right Splitter (Visualizer / Preview)
        self.right_splitter = wx.SplitterWindow(self.right_panel, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        self.visualizer = MappingVisualizer(self.right_splitter, self.project)
        
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
        
        self.splitter.SplitVertically(self.left_panel, self.right_panel, 120) # Narrower left panel
        self.splitter.SetMinimumPaneSize(100)
        self.splitter.SetSashGravity(0.1)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        
        self.refresh_list()
        
        # Bindings
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add)
        self.btn_del.Bind(wx.EVT_BUTTON, self.on_del)
        self.btn_identity.Bind(wx.EVT_BUTTON, self.on_identity)
        self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_deselect)
        self.list_ctrl.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.on_rename)
        
        self.chk_names.Bind(wx.EVT_CHECKBOX, self.on_toggle_names)
        self.slider_zoom.Bind(wx.EVT_SLIDER, self.on_zoom)

    def set_project(self, project: Project):
        self.project = project
        self.visualizer.project = project
        self.preview.project = project
        self.current_mapping = None
        self.visualizer.set_mapping(None)
        self.preview.set_mapping(None)
        self.project.active_mapping = None # Sync global
        self.refresh_list()

    def refresh_list(self):
        self.list_ctrl.DeleteAllItems()
        for i, m in enumerate(self.project.mappings):
            self.list_ctrl.InsertItem(i, m.name)
        
        if self.project.mappings:
            # Try to restore selection
            if self.project.active_mapping in self.project.mappings:
                idx_to_select = self.project.mappings.index(self.project.active_mapping)
                self.list_ctrl.Select(idx_to_select)
                self.list_ctrl.EnsureVisible(idx_to_select)
            # If active_mapping is None, we select NOTHING.
        else:
            self.visualizer.set_mapping(None)
            self.preview.set_mapping(None)
            self.project.active_mapping = None

    def on_add(self, event):
        new_map = ModuleMapping(id=generate_id("map"), name=f"Mapping {len(self.project.mappings)}")
        # Default is Empty (empty dict means all None)
        self.project.mappings.append(new_map)
        idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), new_map.name)
        self.list_ctrl.Select(idx)
        self.list_ctrl.EditLabel(idx)

    def on_del(self, event):
        idx = self.list_ctrl.GetFirstSelected()
        if idx != -1:
            self.project.mappings.pop(idx)
            self.list_ctrl.DeleteItem(idx)
            if idx < self.list_ctrl.GetItemCount():
                self.list_ctrl.Select(idx)
            elif self.list_ctrl.GetItemCount() > 0:
                self.list_ctrl.Select(self.list_ctrl.GetItemCount() - 1)
            else:
                self.visualizer.set_mapping(None)
                self.preview.set_mapping(None)
                self.project.active_mapping = None

    def on_select(self, event):
        idx = event.GetIndex()
        if 0 <= idx < len(self.project.mappings):
            self.current_mapping = self.project.mappings[idx]
            self.visualizer.set_mapping(self.current_mapping)
            self.preview.set_mapping(self.current_mapping)
            self.project.active_mapping = self.current_mapping

    def on_deselect(self, event):
        self.current_mapping = None
        self.visualizer.set_mapping(None)
        self.preview.set_mapping(None)
        self.project.active_mapping = None


    def on_rename(self, event):
        idx = event.GetIndex()
        if not event.IsEditCancelled() and 0 <= idx < len(self.project.mappings):
            self.project.mappings[idx].name = event.GetLabel()
        event.Skip()

    def on_identity(self, event):
        if not self.current_mapping: return
        dlg = wx.MessageDialog(self, "Reset mapping to Identity (Map to Self)?", "Confirm", wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            # Identity: map module.id -> module.id
            self.current_mapping.map = {m.id: m.id for m in self.project.modules}
            self.visualizer.Refresh()
            self.preview.Refresh()
        dlg.Destroy()

    def on_clear(self, event):
        if not self.current_mapping: return
        dlg = wx.MessageDialog(self, "Clear mapping (Map all to None)?", "Confirm", wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self.current_mapping.map = {} # Empty dict implies None
            self.visualizer.Refresh()
            self.preview.Refresh()
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
        
        # Auto-select first mapping
        if self.project.mappings:
            first = self.project.mappings[0]
            # Find index
            for i in range(self.list_ctrl.GetItemCount()):
                if self.list_ctrl.GetItemText(i) == first.name:
                    self.list_ctrl.Select(i)
                    break
