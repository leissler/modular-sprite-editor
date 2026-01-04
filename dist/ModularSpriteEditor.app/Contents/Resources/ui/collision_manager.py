import wx
import wx.lib.scrolledpanel as scrolled
from typing import List, Optional, Callable
from models import Project, CollisionType, generate_id

class CollisionManagerPanel(wx.Panel):
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
        for ct in self.project.collision_types:
            self.visibility[ct.id] = True
            
        if self.project.collision_types:
            self.active_type_id = self.project.collision_types[0].id
            
        # Layout
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header / Toolbar
        tb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(self, label="+", size=(30, -1))
        self.btn_del = wx.Button(self, label="-", size=(30, -1))
        
        tb_sizer.Add(wx.StaticText(self, label="Collision Types"), 1, wx.ALIGN_CENTER_VERTICAL)
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
        
        for ct in self.project.collision_types:
            # Row Panel
            row = wx.Panel(self.list_panel)
            # visual selection
            if ct.id == self.active_type_id:
                row.SetBackgroundColour(wx.Colour(60, 60, 80))
            
            row_sizer = wx.BoxSizer(wx.HORIZONTAL)
            
            # 1. Visibility Checkbox
            chk = wx.CheckBox(row)
            chk.SetValue(self.visibility.get(ct.id, True))
            chk.Bind(wx.EVT_CHECKBOX, lambda e, cid=ct.id: self.on_toggle_vis(e, cid))
            row_sizer.Add(chk, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            
            # 2. Color Swatch (Button)
            col_btn = wx.Button(row, size=(20, 20), label="")
            col_btn.SetBackgroundColour(wx.Colour(*ct.color))
            col_btn.Bind(wx.EVT_BUTTON, lambda e, c=ct: self.on_edit_color(e, c))
            row_sizer.Add(col_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            
            # 3. Name (Clickable to select, Double-click to rename)
            if ct.id == self.editing_type_id:
                txt = wx.TextCtrl(row, value=ct.name, style=wx.TE_PROCESS_ENTER)
                txt.Bind(wx.EVT_TEXT_ENTER, lambda e, c=ct: self.on_rename_enter(e, c))
                txt.Bind(wx.EVT_KILL_FOCUS, lambda e, c=ct: self.on_rename_kill_focus(e, c))
                
                row_sizer.Add(txt, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
                # Auto focus
                wx.CallAfter(txt.SetFocus)
                wx.CallAfter(txt.SelectAll)
            else:
                lbl = wx.StaticText(row, label=ct.name)
                # Bind click on label and row background to select
                lbl.Bind(wx.EVT_LEFT_DOWN, lambda e, cid=ct.id: self.on_select(cid))
                lbl.Bind(wx.EVT_LEFT_DCLICK, lambda e, cid=ct.id: self.on_label_dclick(e, cid))
                row.Bind(wx.EVT_LEFT_DOWN, lambda e, cid=ct.id: self.on_select(cid))
                
                row_sizer.Add(lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
            
            row.SetSizer(row_sizer)
            self.list_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, 2)
            
        self.list_panel.Layout()
        self.list_panel.SetupScrolling() # Re-adjust scrollbars

    def on_label_dclick(self, event, type_id):
        self.editing_type_id = type_id
        self.refresh_list()

    def on_rename_enter(self, event, ctype):
        new_name = event.GetEventObject().GetValue()
        if new_name:
            ctype.name = new_name
            self.editing_type_id = None
            self.refresh_list()
            if self.on_change: self.on_change()
            
    def on_rename_kill_focus(self, event, ctype):
        # Commit on blur as well? Or cancel?
        # Usually commit.
        new_name = event.GetEventObject().GetValue()
        if new_name:
            ctype.name = new_name
        self.editing_type_id = None
        self.refresh_list()
        if self.on_change: self.on_change() # Name change doesn't deeply affect canvas but good for consistency

    def on_add(self, event):
        # Create new type
        import random
        color = (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200))
        new_type = CollisionType(
            id=generate_id("ctype"),
            name=f"Type {len(self.project.collision_types) + 1}",
            color=color
        )
        self.project.collision_types.append(new_type)
        self.visibility[new_type.id] = True
        self.active_type_id = new_type.id
        self.refresh_list()
        if self.on_change: self.on_change()

    def on_delete(self, event):
        if not self.active_type_id: return
        
        # Confirm?
        # Remove from project
        self.project.collision_types = [t for t in self.project.collision_types if t.id != self.active_type_id]
        if self.active_type_id in self.visibility:
            del self.visibility[self.active_type_id]
            
        # Reset active
        if self.project.collision_types:
            self.active_type_id = self.project.collision_types[0].id
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

    def on_edit_color(self, event, ctype: CollisionType):
        data = wx.ColourData()
        data.SetColour(wx.Colour(*ctype.color))
        dlg = wx.ColourDialog(self, data)
        if dlg.ShowModal() == wx.ID_OK:
            col = dlg.GetColourData().GetColour()
            ctype.color = (col.Red(), col.Green(), col.Blue())
            self.refresh_list()
            if self.on_change: self.on_change()
        dlg.Destroy()
