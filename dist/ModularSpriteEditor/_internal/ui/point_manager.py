import wx
import wx.lib.scrolledpanel as scrolled
from typing import List, Optional, Callable
from models import Project, PointType, generate_id

class PointManagerPanel(wx.Panel):
    def __init__(self, parent, project: Project, on_change: Callable = None):
        super().__init__(parent)
        self.project = project
        self.on_change = on_change
        
        # State
        self.active_type_id: Optional[str] = None
        self.editing_type_id: Optional[str] = None
        # Visibility mapping: type_id -> bool
        self.visibility: dict[str, bool] = {} 
        
        # Initialize visibility for existing
        for pt in self.project.point_types:
            self.visibility[pt.id] = True
            
        if self.project.point_types:
            self.active_type_id = self.project.point_types[0].id
            
        # Layout
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header / Toolbar
        tb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(self, label="+", size=(30, -1))
        self.btn_del = wx.Button(self, label="-", size=(30, -1))
        
        tb_sizer.Add(wx.StaticText(self, label="Control Points"), 1, wx.ALIGN_CENTER_VERTICAL)
        tb_sizer.Add(self.btn_add, 0, wx.RIGHT, 5)
        tb_sizer.Add(self.btn_del, 0)
        
        main_sizer.Add(tb_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # List Area
        self.list_panel = scrolled.ScrolledPanel(self)
        self.list_panel.SetupScrolling()
        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_panel.SetSizer(self.list_sizer)
        
        main_sizer.Add(self.list_panel, 1, wx.EXPAND | wx.ALL, 5)
        
        self.SetSizer(main_sizer)
        
        # Bindings
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add)
        self.btn_del.Bind(wx.EVT_BUTTON, self.on_delete)
        
        self.refresh_list()

    def refresh_list(self):
        self.list_sizer.Clear(True)
        
        for pt in self.project.point_types:
            # Row Panel
            row = wx.Panel(self.list_panel)
            # visual selection
            if pt.id == self.active_type_id:
                row.SetBackgroundColour(wx.Colour(60, 60, 80))
            
            row_sizer = wx.BoxSizer(wx.HORIZONTAL)
            
            # 1. Visibility Checkbox
            chk = wx.CheckBox(row)
            chk.SetValue(self.visibility.get(pt.id, True))
            chk.Bind(wx.EVT_CHECKBOX, lambda e, pid=pt.id: self.on_toggle_vis(e, pid))
            row_sizer.Add(chk, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            
            # 2. Color Swatch (Button)
            col_btn = wx.Button(row, size=(20, 20), label="")
            col_btn.SetBackgroundColour(wx.Colour(*pt.color))
            col_btn.Bind(wx.EVT_BUTTON, lambda e, p=pt: self.on_edit_color(e, p))
            row_sizer.Add(col_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            
            # 3. Name (Clickable to select, Double-click to rename)
            if pt.id == self.editing_type_id:
                txt = wx.TextCtrl(row, value=pt.name, style=wx.TE_PROCESS_ENTER)
                txt.Bind(wx.EVT_TEXT_ENTER, lambda e, p=pt: self.on_rename_enter(e, p))
                txt.Bind(wx.EVT_KILL_FOCUS, lambda e, p=pt: self.on_rename_kill_focus(e, p))
                
                row_sizer.Add(txt, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
                # Auto focus
                wx.CallAfter(txt.SetFocus)
                wx.CallAfter(txt.SelectAll)
            else:
                lbl = wx.StaticText(row, label=pt.name)
                if pt.id == self.active_type_id:
                     lbl.SetForegroundColour(wx.Colour(255, 255, 255))
                # Bind click on label and row background to select
                lbl.Bind(wx.EVT_LEFT_DOWN, lambda e, pid=pt.id: self.on_select(pid))
                lbl.Bind(wx.EVT_LEFT_DCLICK, lambda e, pid=pt.id: self.on_label_dclick(e, pid))
                row.Bind(wx.EVT_LEFT_DOWN, lambda e, pid=pt.id: self.on_select(pid))
                
                row_sizer.Add(lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            
            row.SetSizer(row_sizer)
            self.list_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, 2)
            
        self.list_panel.Layout()
        self.list_panel.SetupScrolling() # Re-adjust scrollbars

    def on_label_dclick(self, event, type_id):
        self.editing_type_id = type_id
        self.refresh_list()

    def on_rename_enter(self, event, ptype):
        new_name = event.GetEventObject().GetValue()
        if new_name:
            ptype.name = new_name
            self.editing_type_id = None
            self.refresh_list()
            if self.on_change: self.on_change()
            
    def on_rename_kill_focus(self, event, ptype):
        new_name = event.GetEventObject().GetValue()
        if new_name:
            ptype.name = new_name
        self.editing_type_id = None
        self.refresh_list()
        if self.on_change: self.on_change() 

    def on_add(self, event):
        # Create new type
        import random
        color = (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200))
        new_type = PointType(
            id=generate_id("ptype"),
            name=f"Point {len(self.project.point_types) + 1}",
            color=color
        )
        self.project.point_types.append(new_type)
        self.visibility[new_type.id] = True
        self.active_type_id = new_type.id
        self.refresh_list()
        if self.on_change: self.on_change()

    def on_delete(self, event):
        if not self.active_type_id: return
        
        # Confirm?
        # Remove from project
        self.project.point_types = [t for t in self.project.point_types if t.id != self.active_type_id]
        if self.active_type_id in self.visibility:
            del self.visibility[self.active_type_id]
            
        # Reset active
        if self.project.point_types:
            self.active_type_id = self.project.point_types[0].id
        else:
            self.active_type_id = None
            
        self.refresh_list()
        if self.on_change: self.on_change()

    def on_select(self, type_id):
        self.active_type_id = type_id
        self.refresh_list()
        if self.on_change: self.on_change()

    def on_toggle_vis(self, event, type_id):
        self.visibility[type_id] = event.IsChecked()
        if self.on_change: self.on_change()

    def on_edit_color(self, event, ptype: PointType):
        data = wx.ColourData()
        data.SetColour(wx.Colour(*ptype.color))
        dlg = wx.ColourDialog(self, data)
        if dlg.ShowModal() == wx.ID_OK:
            col = dlg.GetColourData().GetColour()
            ptype.color = (col.Red(), col.Green(), col.Blue())
            self.refresh_list()
            if self.on_change: self.on_change()
        dlg.Destroy()
