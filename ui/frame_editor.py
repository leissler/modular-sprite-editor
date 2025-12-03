"""Frame editor panel for assembling modules and collision data."""

from __future__ import annotations

from typing import Optional

import wx

from models import CollisionRect, ControlPoint, FModule, Frame, Project, generate_id
from ui.canvas import FrameCanvas


class FrameEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_frame_id: Optional[str] = None
        self.selected_fmodule_id: Optional[str] = None

        main = wx.BoxSizer(wx.HORIZONTAL)
        sidebar = wx.BoxSizer(wx.VERTICAL)
        right = wx.BoxSizer(wx.VERTICAL)

        # Frame list
        frame_box = wx.StaticBox(self, label="Frames")
        frame_sizer = wx.StaticBoxSizer(frame_box, wx.VERTICAL)
        self.frame_list = wx.ListBox(frame_box)
        frame_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add_frame = wx.Button(frame_box, label="Add")
        self.btn_rename_frame = wx.Button(frame_box, label="Rename")
        self.btn_delete_frame = wx.Button(frame_box, label="Delete")
        frame_btns.Add(self.btn_add_frame, 1, wx.RIGHT, 4)
        frame_btns.Add(self.btn_rename_frame, 1, wx.RIGHT, 4)
        frame_btns.Add(self.btn_delete_frame, 1)
        frame_sizer.Add(self.frame_list, 1, wx.EXPAND | wx.ALL, 4)
        frame_sizer.Add(frame_btns, 0, wx.EXPAND | wx.ALL, 4)

        # FModules
        fm_box = wx.StaticBox(self, label="Frame Modules")
        fm_sizer = wx.StaticBoxSizer(fm_box, wx.VERTICAL)
        self.fmodule_list = wx.ListCtrl(fm_box, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.fmodule_list.InsertColumn(0, "ID", width=70)
        self.fmodule_list.InsertColumn(1, "Ref", width=110)
        self.fmodule_list.InsertColumn(2, "Pos", width=90)
        self.fmodule_list.InsertColumn(3, "Z", width=40)
        add_row = wx.BoxSizer(wx.HORIZONTAL)
        self.choice_module = wx.Choice(fm_box)
        self.choice_frame = wx.Choice(fm_box)
        self.btn_add_module = wx.Button(fm_box, label="Add Module")
        self.btn_add_frame_ref = wx.Button(fm_box, label="Add Frame Ref")
        add_row.Add(self.choice_module, 1, wx.RIGHT, 4)
        add_row.Add(self.btn_add_module, 0, wx.RIGHT, 4)
        add_row2 = wx.BoxSizer(wx.HORIZONTAL)
        add_row2.Add(self.choice_frame, 1, wx.RIGHT, 4)
        add_row2.Add(self.btn_add_frame_ref, 0)
        self.btn_delete_fmodule = wx.Button(fm_box, label="Delete")
        fm_sizer.Add(self.fmodule_list, 1, wx.EXPAND | wx.ALL, 4)
        fm_sizer.Add(add_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        fm_sizer.Add(add_row2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        fm_sizer.Add(self.btn_delete_fmodule, 0, wx.EXPAND | wx.ALL, 4)

        # Properties
        prop_box = wx.StaticBox(self, label="Selected Module Properties")
        prop_sizer = wx.StaticBoxSizer(prop_box, wx.VERTICAL)
        grid = wx.FlexGridSizer(3, 4, 4, 4)
        grid.Add(wx.StaticText(prop_box, label="X"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_x = wx.SpinCtrl(prop_box, min=-4096, max=4096, initial=0)
        grid.Add(self.spin_x, 1, wx.EXPAND)
        grid.Add(wx.StaticText(prop_box, label="Flip X"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.chk_flip_x = wx.CheckBox(prop_box)
        grid.Add(self.chk_flip_x, 0)
        grid.Add(wx.StaticText(prop_box, label="Y"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_y = wx.SpinCtrl(prop_box, min=-4096, max=4096, initial=0)
        grid.Add(self.spin_y, 1, wx.EXPAND)
        grid.Add(wx.StaticText(prop_box, label="Flip Y"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.chk_flip_y = wx.CheckBox(prop_box)
        grid.Add(self.chk_flip_y, 0)
        grid.Add(wx.StaticText(prop_box, label="Z Order"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_z = wx.SpinCtrl(prop_box, min=-128, max=128, initial=0)
        grid.Add(self.spin_z, 1, wx.EXPAND)
        grid.Add(wx.StaticText(prop_box, label=""), 0)
        grid.Add(wx.StaticText(prop_box, label=""), 0)
        prop_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 4)

        # Collision rects
        col_box = wx.StaticBox(self, label="Collision Rects")
        col_sizer = wx.StaticBoxSizer(col_box, wx.VERTICAL)
        self.collision_list = wx.ListCtrl(col_box, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.collision_list.InsertColumn(0, "Name", width=90)
        self.collision_list.InsertColumn(1, "Rect", width=140)
        col_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add_collision = wx.Button(col_box, label="Add")
        self.btn_edit_collision = wx.Button(col_box, label="Edit")
        self.btn_delete_collision = wx.Button(col_box, label="Delete")
        col_btns.Add(self.btn_add_collision, 1, wx.RIGHT, 4)
        col_btns.Add(self.btn_edit_collision, 1, wx.RIGHT, 4)
        col_btns.Add(self.btn_delete_collision, 1)
        col_sizer.Add(self.collision_list, 1, wx.EXPAND | wx.ALL, 4)
        col_sizer.Add(col_btns, 0, wx.EXPAND | wx.ALL, 4)

        # Control points
        cp_box = wx.StaticBox(self, label="Control Points")
        cp_sizer = wx.StaticBoxSizer(cp_box, wx.VERTICAL)
        self.control_list = wx.ListCtrl(cp_box, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.control_list.InsertColumn(0, "Name", width=90)
        self.control_list.InsertColumn(1, "Pos", width=120)
        cp_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add_cp = wx.Button(cp_box, label="Add")
        self.btn_edit_cp = wx.Button(cp_box, label="Edit")
        self.btn_delete_cp = wx.Button(cp_box, label="Delete")
        cp_btns.Add(self.btn_add_cp, 1, wx.RIGHT, 4)
        cp_btns.Add(self.btn_edit_cp, 1, wx.RIGHT, 4)
        cp_btns.Add(self.btn_delete_cp, 1)
        cp_sizer.Add(self.control_list, 1, wx.EXPAND | wx.ALL, 4)
        cp_sizer.Add(cp_btns, 0, wx.EXPAND | wx.ALL, 4)

        sidebar.Add(frame_sizer, 0, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(fm_sizer, 1, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(prop_sizer, 0, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(col_sizer, 0, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(cp_sizer, 0, wx.EXPAND | wx.ALL, 4)

        self.canvas = FrameCanvas(self, self.project)
        toggle_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_grid = wx.CheckBox(self, label="Grid")
        self.chk_grid.SetValue(True)
        self.chk_collision = wx.CheckBox(self, label="Collisions")
        self.chk_collision.SetValue(True)
        self.chk_control = wx.CheckBox(self, label="Control Points")
        self.chk_control.SetValue(True)
        toggle_sizer.Add(self.chk_grid, 0, wx.RIGHT, 8)
        toggle_sizer.Add(self.chk_collision, 0, wx.RIGHT, 8)
        toggle_sizer.Add(self.chk_control, 0)
        right.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 4)
        right.Add(toggle_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        main.Add(sidebar, 0, wx.EXPAND)
        main.Add(right, 1, wx.EXPAND)
        self.SetSizer(main)

        # Events
        self.btn_add_frame.Bind(wx.EVT_BUTTON, self.on_add_frame)
        self.btn_rename_frame.Bind(wx.EVT_BUTTON, self.on_rename_frame)
        self.btn_delete_frame.Bind(wx.EVT_BUTTON, self.on_delete_frame)
        self.frame_list.Bind(wx.EVT_LISTBOX, self.on_select_frame)
        self.btn_add_module.Bind(wx.EVT_BUTTON, self.on_add_module_ref)
        self.btn_add_frame_ref.Bind(wx.EVT_BUTTON, self.on_add_frame_ref)
        self.btn_delete_fmodule.Bind(wx.EVT_BUTTON, self.on_delete_fmodule)
        self.fmodule_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_fmodule)
        self.spin_x.Bind(wx.EVT_SPINCTRL, self.on_prop_changed)
        self.spin_y.Bind(wx.EVT_SPINCTRL, self.on_prop_changed)
        self.spin_z.Bind(wx.EVT_SPINCTRL, self.on_prop_changed)
        self.chk_flip_x.Bind(wx.EVT_CHECKBOX, self.on_prop_changed)
        self.chk_flip_y.Bind(wx.EVT_CHECKBOX, self.on_prop_changed)
        self.btn_add_collision.Bind(wx.EVT_BUTTON, self.on_add_collision)
        self.btn_edit_collision.Bind(wx.EVT_BUTTON, self.on_edit_collision)
        self.btn_delete_collision.Bind(wx.EVT_BUTTON, self.on_delete_collision)
        self.btn_add_cp.Bind(wx.EVT_BUTTON, self.on_add_cp)
        self.btn_edit_cp.Bind(wx.EVT_BUTTON, self.on_edit_cp)
        self.btn_delete_cp.Bind(wx.EVT_BUTTON, self.on_delete_cp)
        self.control_list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: None)
        self.chk_grid.Bind(wx.EVT_CHECKBOX, self.on_toggle_grid)
        self.chk_collision.Bind(wx.EVT_CHECKBOX, self.on_toggle_collision)
        self.chk_control.Bind(wx.EVT_CHECKBOX, self.on_toggle_control)
        self.canvas.on_selection_changed = self.on_canvas_selection

        self.refresh_choices()

    # Frame list handling
    def refresh_frames(self, select_id: Optional[str] = None) -> None:
        self.frame_list.Clear()
        for frame in self.project.frames:
            self.frame_list.Append(f"{frame.name} ({frame.id})", clientData=frame.id)
        if not self.project.frames:
            self.canvas.set_frame(None)
            return
        if select_id:
            for idx in range(self.frame_list.GetCount()):
                if self.frame_list.GetClientData(idx) == select_id:
                    self.frame_list.SetSelection(idx)
                    self.select_frame(select_id)
                    return
        if self.project.frames and self.frame_list.GetCount() > 0:
            self.frame_list.SetSelection(0)
            self.select_frame(self.frame_list.GetClientData(0))

    def on_add_frame(self, _: wx.CommandEvent) -> None:
        name = f"Frame {len(self.project.frames)+1}"
        frame = self.project.create_frame(name)
        self.refresh_frames(select_id=frame.id)

    def on_rename_frame(self, _: wx.CommandEvent) -> None:
        if not self.selected_frame_id:
            return
        frame = self.project.get_frame(self.selected_frame_id)
        if not frame:
            return
        with wx.TextEntryDialog(self, "New name", value=frame.name) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                frame.name = dlg.GetValue()
                self.refresh_frames(select_id=frame.id)

    def on_delete_frame(self, _: wx.CommandEvent) -> None:
        if not self.selected_frame_id:
            return
        removed_id = self.selected_frame_id
        self.project.frames = [f for f in self.project.frames if f.id != self.selected_frame_id]
        for f in self.project.frames:
            f.fmodules = [fm for fm in f.fmodules if not (fm.ref_type == "frame" and fm.ref_id == removed_id)]
        for anim in self.project.animations:
            anim.aframes = [af for af in anim.aframes if af.frame_id != removed_id]
        self.selected_frame_id = None
        self.refresh_frames()
        self.canvas.set_frame(None)

    def on_select_frame(self, event: wx.CommandEvent) -> None:
        idx = event.GetSelection()
        frame_id = self.frame_list.GetClientData(idx)
        self.select_frame(frame_id)

    def select_frame(self, frame_id: str) -> None:
        self.selected_frame_id = frame_id
        frame = self.project.get_frame(frame_id)
        self.canvas.set_frame_offset((0.0, 0.0))
        self.canvas.set_frame(frame)
        self.refresh_fmodules()
        self.refresh_collisions()
        self.refresh_control_points()
        self.refresh_choices()

    # FModule handling
    def refresh_fmodules(self, select_id: Optional[str] = None) -> None:
        self.fmodule_list.DeleteAllItems()
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        for fm in frame.fmodules:
            idx = self.fmodule_list.InsertItem(self.fmodule_list.GetItemCount(), fm.id)
            self.fmodule_list.SetItem(idx, 1, f"{fm.ref_type}:{fm.ref_id}")
            self.fmodule_list.SetItem(idx, 2, f"{fm.position[0]},{fm.position[1]}")
            self.fmodule_list.SetItem(idx, 3, str(fm.z_order))
        if select_id:
            for i in range(self.fmodule_list.GetItemCount()):
                if self.fmodule_list.GetItemText(i) == select_id:
                    self.fmodule_list.Select(i)
                    self.select_fmodule(select_id)
                    break

    def on_add_module_ref(self, _: wx.CommandEvent) -> None:
        if not self.selected_frame_id:
            return
        frame = self.project.get_frame(self.selected_frame_id)
        if not frame or self.choice_module.GetSelection() == wx.NOT_FOUND:
            return
        mod_id = self.choice_module.GetClientData(self.choice_module.GetSelection())
        fm = FModule(
            id=generate_id("fm"),
            ref_type="module",
            ref_id=mod_id,
            position=(0, 0),
            flip_x=False,
            flip_y=False,
            rotation_degrees=0.0,
            z_order=len(frame.fmodules),
        )
        frame.fmodules.append(fm)
        self.refresh_fmodules(select_id=fm.id)
        self.canvas.Refresh(False)

    def on_add_frame_ref(self, _: wx.CommandEvent) -> None:
        if not self.selected_frame_id:
            return
        frame = self.project.get_frame(self.selected_frame_id)
        if not frame or self.choice_frame.GetSelection() == wx.NOT_FOUND:
            return
        ref_id = self.choice_frame.GetClientData(self.choice_frame.GetSelection())
        fm = FModule(
            id=generate_id("fm"),
            ref_type="frame",
            ref_id=ref_id,
            position=(0, 0),
            flip_x=False,
            flip_y=False,
            rotation_degrees=0.0,
            z_order=len(frame.fmodules),
        )
        frame.fmodules.append(fm)
        if self.project.frame_has_cycle(frame.id):
            wx.MessageBox("Adding this frame reference creates a cycle. Reverting.", "Cycle detected")
            frame.fmodules.pop()
            return
        self.refresh_fmodules(select_id=fm.id)
        self.canvas.Refresh(False)

    def on_delete_fmodule(self, _: wx.CommandEvent) -> None:
        if not self.selected_frame_id or not self.selected_fmodule_id:
            return
        frame = self.project.get_frame(self.selected_frame_id)
        if not frame:
            return
        frame.fmodules = [fm for fm in frame.fmodules if fm.id != self.selected_fmodule_id]
        self.selected_fmodule_id = None
        self.refresh_fmodules()
        self.canvas.Refresh(False)

    def on_select_fmodule(self, event: wx.ListEvent) -> None:
        fm_id = event.GetText()
        self.select_fmodule(fm_id)

    def on_canvas_selection(self, fm_id: Optional[str]) -> None:
        if fm_id:
            for i in range(self.fmodule_list.GetItemCount()):
                if self.fmodule_list.GetItemText(i) == fm_id:
                    self.fmodule_list.Select(i)
                    break
        self.select_fmodule(fm_id)

    def select_fmodule(self, fm_id: Optional[str]) -> None:
        self.selected_fmodule_id = fm_id
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        fm = next((f for f in frame.fmodules if f.id == fm_id), None) if frame and fm_id else None
        if fm:
            self.spin_x.SetValue(int(fm.position[0]))
            self.spin_y.SetValue(int(fm.position[1]))
            self.spin_z.SetValue(int(fm.z_order))
            self.chk_flip_x.SetValue(fm.flip_x)
            self.chk_flip_y.SetValue(fm.flip_y)
            self.canvas.selected_fmodule_id = fm_id
            self.canvas.Refresh(False)

    def on_prop_changed(self, _: wx.CommandEvent) -> None:
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        fm = next((f for f in frame.fmodules if f.id == self.selected_fmodule_id), None) if frame else None
        if not fm:
            return
        fm.position = (self.spin_x.GetValue(), self.spin_y.GetValue())
        fm.z_order = self.spin_z.GetValue()
        fm.flip_x = self.chk_flip_x.GetValue()
        fm.flip_y = self.chk_flip_y.GetValue()
        self.refresh_fmodules(select_id=fm.id)
        self.canvas.Refresh(False)

    # Collision handling
    def refresh_collisions(self) -> None:
        self.collision_list.DeleteAllItems()
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        for rect in frame.collision_rects:
            idx = self.collision_list.InsertItem(self.collision_list.GetItemCount(), rect.name or "(unnamed)")
            self.collision_list.SetItem(idx, 1, f"{rect.x},{rect.y} {rect.width}x{rect.height}")

    def on_add_collision(self, _: wx.CommandEvent) -> None:
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        frame.collision_rects.append(CollisionRect("collision", -16, -16, 32, 32))
        self.refresh_collisions()
        self.canvas.Refresh(False)

    def on_edit_collision(self, _: wx.CommandEvent) -> None:
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        idx = self.collision_list.GetNextItem(-1, state=wx.LIST_STATE_SELECTED)
        if idx == -1:
            return
        rect = frame.collision_rects[idx]
        dlg = wx.TextEntryDialog(self, "name,x,y,width,height", value=f"{rect.name},{rect.x},{rect.y},{rect.width},{rect.height}")
        if dlg.ShowModal() == wx.ID_OK:
            parts = dlg.GetValue().split(",")
            if len(parts) == 5:
                rect.name = parts[0]
                rect.x = int(parts[1])
                rect.y = int(parts[2])
                rect.width = int(parts[3])
                rect.height = int(parts[4])
                self.refresh_collisions()
                self.canvas.Refresh(False)
        dlg.Destroy()

    def on_delete_collision(self, _: wx.CommandEvent) -> None:
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        idx = self.collision_list.GetNextItem(-1, state=wx.LIST_STATE_SELECTED)
        if idx == -1:
            return
        del frame.collision_rects[idx]
        self.refresh_collisions()
        self.canvas.Refresh(False)

    # Control point handling
    def refresh_control_points(self) -> None:
        self.control_list.DeleteAllItems()
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        for cp in frame.control_points:
            idx = self.control_list.InsertItem(self.control_list.GetItemCount(), cp.name)
            self.control_list.SetItem(idx, 1, f"{cp.x},{cp.y}")

    def on_add_cp(self, _: wx.CommandEvent) -> None:
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        frame.control_points.append(ControlPoint("cp", 0, 0))
        self.refresh_control_points()
        self.canvas.Refresh(False)

    def on_edit_cp(self, _: wx.CommandEvent) -> None:
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        idx = self.control_list.GetNextItem(-1, state=wx.LIST_STATE_SELECTED)
        if idx == -1:
            return
        cp = frame.control_points[idx]
        dlg = wx.TextEntryDialog(self, "name,x,y", value=f"{cp.name},{cp.x},{cp.y}")
        if dlg.ShowModal() == wx.ID_OK:
            parts = dlg.GetValue().split(",")
            if len(parts) == 3:
                cp.name = parts[0]
                cp.x = int(parts[1])
                cp.y = int(parts[2])
                self.refresh_control_points()
                self.canvas.Refresh(False)
        dlg.Destroy()

    def on_delete_cp(self, _: wx.CommandEvent) -> None:
        frame = self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None
        if not frame:
            return
        idx = self.control_list.GetNextItem(-1, state=wx.LIST_STATE_SELECTED)
        if idx == -1:
            return
        del frame.control_points[idx]
        self.refresh_control_points()
        self.canvas.Refresh(False)

    # Toggles
    def on_toggle_grid(self, event: wx.CommandEvent) -> None:
        self.canvas.show_grid = event.IsChecked()
        self.canvas.Refresh(False)

    def on_toggle_collision(self, event: wx.CommandEvent) -> None:
        self.canvas.show_collision = event.IsChecked()
        self.canvas.Refresh(False)

    def on_toggle_control(self, event: wx.CommandEvent) -> None:
        self.canvas.show_control_points = event.IsChecked()
        self.canvas.Refresh(False)

    def refresh_choices(self) -> None:
        # Modules
        self.choice_module.Clear()
        for m in self.project.modules:
            self.choice_module.Append(f"{m.name} ({m.id})", clientData=m.id)
        # Frames (excluding current)
        self.choice_frame.Clear()
        for f in self.project.frames:
            if f.id != self.selected_frame_id:
                self.choice_frame.Append(f"{f.name} ({f.id})", clientData=f.id)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.canvas.project = project
        self.selected_frame_id = None
        self.selected_fmodule_id = None
        self.canvas.set_frame(None)
        self.refresh_choices()
        self.refresh_frames()
