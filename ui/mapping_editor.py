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
        
        self.slot_size = 64
        self.gap = 4
        self.padding = 30 # Increased padding for headers
        self.generator = ThumbnailGenerator()
        
        # State
        self.highlight_idx = -1 # Index of slot being hovered
        self._drag_source_module_id: Optional[str] = None

        self.SetScrollRate(10, 10)
        
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_SIZE, self.on_size)

    def set_mapping(self, mapping: Optional[ModuleMapping]):
        self.mapping = mapping
        self.Refresh()
        self.update_virtual_size()

    def update_virtual_size(self):
        count = len(self.project.modules)
        width = self.padding * 2 + count * (self.slot_size + self.gap)
        height = self.padding * 2 + (self.slot_size * 2) + self.gap * 4 + 40 # 2 strips + text
        self.SetVirtualSize(width, height)

    def on_size(self, event):
        self.update_virtual_size()
        event.Skip()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.Clear()
        
        # Draw Source Strip (Top)
        strip_y = self.padding
        
        gc = wx.GraphicsContext.Create(dc)
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        gc.SetFont(font, wx.Colour(200, 200, 200))
        
        gc.DrawText("Source Modules", self.padding, strip_y - 20)
        
        if not self.project.modules:
            gc.DrawText("(No modules in project)", self.padding, strip_y + 10)
            return

        for i, mod in enumerate(self.project.modules):
            x = self.padding + i * (self.slot_size + self.gap)
            self._draw_slot(gc, x, strip_y, mod, is_source=True)

        # Draw Mapped Strip (Bottom)
        strip_y = self.padding + self.slot_size + 40
        gc.DrawText("Mapped Targets (Drag Source here)", self.padding, strip_y - 20)
        
        for i, mod in enumerate(self.project.modules):
            x = self.padding + i * (self.slot_size + self.gap)
            
            # Find target
            target_mod = None
            if self.mapping:
                target_id = self.mapping.map.get(mod.id, None) # Default is None (Empty)
                if target_id:
                    target_mod = self.project.get_module(target_id)
            
            is_highlight = (i == self.highlight_idx)
            self._draw_slot(gc, x, strip_y, target_mod, is_source=False, highlight=is_highlight)

    def _draw_slot(self, gc, x, y, module, is_source, highlight=False):
        # Background
        if highlight:
            gc.SetBrush(wx.Brush(wx.Colour(100, 100, 150)))
            gc.SetPen(wx.Pen(wx.Colour(200, 200, 255), 2))
        else:
            gc.SetBrush(wx.Brush(wx.Colour(40, 40, 40)))
            gc.SetPen(wx.Pen(wx.Colour(80, 80, 80), 1))
            
        gc.DrawRectangle(x, y, self.slot_size, self.slot_size)
        
        if module:
            # Draw Thumbnail
            thumb = self.generator.render_thumbnail(self.project, module, self.slot_size - 4, self.slot_size - 4)
            gc.DrawBitmap(thumb, x + 2, y + 2, self.slot_size - 4, self.slot_size - 4)
        else:
            # Draw "None" cross or text
            if not is_source:
                gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(100, 100, 100))
                gc.DrawText("None", x + 10, y + 20)

    def _hit_test(self, pt) -> int:
        # Returns module index based on X coordinate provided we are in a strip Y range
        # Only checks X really for simplicity as columns are aligned
        x, y = self.CalcUnscrolledPosition(pt)
        
        # Check if in Bottom Strip Y range
        bottom_strip_y = self.padding + self.slot_size + 40
        if bottom_strip_y <= y <= bottom_strip_y + self.slot_size:
            rel_x = x - self.padding
            if rel_x < 0: return -1
            idx = int(rel_x / (self.slot_size + self.gap))
            if 0 <= idx < len(self.project.modules):
                return idx
        
        return -1

    def _hit_test_source(self, pt) -> int:
        x, y = self.CalcUnscrolledPosition(pt)
        top_strip_y = self.padding
        if top_strip_y <= y <= top_strip_y + self.slot_size:
            rel_x = x - self.padding
            if rel_x < 0: return -1
            idx = int(rel_x / (self.slot_size + self.gap))
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

    def on_motion(self, event):
        if self._drag_source_module_id and event.Dragging():
            # Highlight target
            idx = self._hit_test(event.GetPosition())
            if idx != self.highlight_idx:
                self.highlight_idx = idx
                self.Refresh()
        elif not event.Dragging():
            # Just Hover
            idx = self._hit_test(event.GetPosition())
            if idx != self.highlight_idx:
                self.highlight_idx = idx
                self.Refresh()

    def on_left_up(self, event):
        if self.HasCapture():
            self.ReleaseMouse()
        
        if self._drag_source_module_id:
            # Drop
            idx = self._hit_test(event.GetPosition())
            if idx != -1 and self.mapping:
                # Map source[idx] -> dragged_module
                # We are mapping the module at index 'idx' (which corresponds to project.modules[idx])
                # to the module ID we dragged.
                target_module = self.project.modules[idx]
                self.mapping.map[target_module.id] = self._drag_source_module_id
                self.Refresh()
        
        self._drag_source_module_id = None
        self.highlight_idx = -1
        self.Refresh()


class MappingEditorPanel(wx.Panel):
    def __init__(self, parent, project: Project):
        super().__init__(parent)
        self.project = project
        self.current_mapping: Optional[ModuleMapping] = None
        
        # Splitter
        self.splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # Left: List
        self.left_panel = wx.Panel(self.splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.list_ctrl = wx.ListCtrl(self.left_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_EDIT_LABELS)
        self.list_ctrl.InsertColumn(0, "Name", width=200)
        
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
        tb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_identity = wx.Button(self.right_panel, label="Reset to Identity")
        self.btn_clear = wx.Button(self.right_panel, label="Clear All")
        tb_sizer.Add(self.btn_identity, 0, wx.RIGHT, 4)
        tb_sizer.Add(self.btn_clear, 0)
        
        self.visualizer = MappingVisualizer(self.right_panel, self.project)
        
        right_sizer.Add(tb_sizer, 0, wx.EXPAND | wx.ALL, 4)
        right_sizer.Add(self.visualizer, 1, wx.EXPAND | wx.ALL, 4)
        self.right_panel.SetSizer(right_sizer)
        
        self.splitter.SplitVertically(self.left_panel, self.right_panel, 250)
        self.splitter.SetMinimumPaneSize(150)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        
        # Bindings
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add)
        self.btn_del.Bind(wx.EVT_BUTTON, self.on_del)
        self.btn_identity.Bind(wx.EVT_BUTTON, self.on_identity)
        self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.list_ctrl.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.on_rename)
        
        self.refresh_list()

    def set_project(self, project: Project):
        self.project = project
        self.visualizer.project = project
        self.current_mapping = None
        self.visualizer.set_mapping(None)
        self.refresh_list()

    def refresh_list(self):
        self.list_ctrl.DeleteAllItems()
        for i, m in enumerate(self.project.mappings):
            self.list_ctrl.InsertItem(i, m.name)
        
        if self.project.mappings:
            self.list_ctrl.Select(0)
        else:
            self.visualizer.set_mapping(None)

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

    def on_select(self, event):
        idx = event.GetIndex()
        if 0 <= idx < len(self.project.mappings):
            self.current_mapping = self.project.mappings[idx]
            self.visualizer.set_mapping(self.current_mapping)

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
        dlg.Destroy()

    def on_clear(self, event):
        if not self.current_mapping: return
        dlg = wx.MessageDialog(self, "Clear mapping (Map all to None)?", "Confirm", wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self.current_mapping.map = {} # Empty dict implies None
            self.visualizer.Refresh()
        dlg.Destroy()
