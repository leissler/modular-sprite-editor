"""Animation editor panel with timeline and playback."""

from __future__ import annotations

from typing import Optional

import wx

from models import AFrame, Animation, Project, generate_id
from ui.canvas import AnimationCanvas


class AnimationEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_animation_id: Optional[str] = None
        self.current_index: int = 0
        self.play_direction = 1
        self.remaining_loops: Optional[int] = None
        self.timer = wx.Timer(self)

        main = wx.BoxSizer(wx.HORIZONTAL)
        sidebar = wx.BoxSizer(wx.VERTICAL)
        right = wx.BoxSizer(wx.VERTICAL)

        # Animation list
        anim_box = wx.StaticBox(self, label="Animations")
        anim_sizer = wx.StaticBoxSizer(anim_box, wx.VERTICAL)
        self.anim_list = wx.ListBox(anim_box)
        anim_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add_anim = wx.Button(anim_box, label="Add")
        self.btn_rename_anim = wx.Button(anim_box, label="Rename")
        self.btn_delete_anim = wx.Button(anim_box, label="Delete")
        anim_btns.Add(self.btn_add_anim, 1, wx.RIGHT, 4)
        anim_btns.Add(self.btn_rename_anim, 1, wx.RIGHT, 4)
        anim_btns.Add(self.btn_delete_anim, 1)
        anim_sizer.Add(self.anim_list, 1, wx.EXPAND | wx.ALL, 4)
        anim_sizer.Add(anim_btns, 0, wx.EXPAND | wx.ALL, 4)

        # Playback settings
        playback_box = wx.StaticBox(self, label="Playback")
        playback_sizer = wx.StaticBoxSizer(playback_box, wx.VERTICAL)
        pb_grid = wx.FlexGridSizer(2, 2, 4, 4)
        pb_grid.Add(wx.StaticText(playback_box, label="Type"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.playback_choice = wx.Choice(playback_box, choices=["forward", "backward", "loop", "loop_n", "ping_pong", "ping_pong_n"])
        self.playback_choice.SetSelection(2)  # loop by default
        pb_grid.Add(self.playback_choice, 1, wx.EXPAND)
        pb_grid.Add(wx.StaticText(playback_box, label="Loop Count"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.loop_spin = wx.SpinCtrl(playback_box, min=-1, max=1000, initial=-1)
        pb_grid.Add(self.loop_spin, 1, wx.EXPAND)
        playback_sizer.Add(pb_grid, 0, wx.EXPAND | wx.ALL, 4)
        playback_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_first = wx.Button(playback_box, label="|<")
        self.btn_prev = wx.Button(playback_box, label="<")
        self.btn_play = wx.Button(playback_box, label="Play")
        self.btn_stop = wx.Button(playback_box, label="Stop")
        self.btn_next = wx.Button(playback_box, label=">")
        self.btn_last = wx.Button(playback_box, label=">|")
        playback_buttons.Add(self.btn_first, 0, wx.RIGHT, 2)
        playback_buttons.Add(self.btn_prev, 0, wx.RIGHT, 2)
        playback_buttons.Add(self.btn_play, 0, wx.RIGHT, 2)
        playback_buttons.Add(self.btn_stop, 0, wx.RIGHT, 2)
        playback_buttons.Add(self.btn_next, 0, wx.RIGHT, 2)
        playback_buttons.Add(self.btn_last, 0)
        playback_sizer.Add(playback_buttons, 0, wx.ALL, 4)

        # AFrames list
        af_box = wx.StaticBox(self, label="Frames in Animation")
        af_sizer = wx.StaticBoxSizer(af_box, wx.VERTICAL)
        self.aframe_list = wx.ListCtrl(af_box, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.aframe_list.InsertColumn(0, "Frame", width=130)
        self.aframe_list.InsertColumn(1, "Duration", width=70)
        self.aframe_list.InsertColumn(2, "Offset", width=80)
        add_row = wx.BoxSizer(wx.HORIZONTAL)
        self.choice_frame = wx.Choice(af_box)
        self.btn_add_frame = wx.Button(af_box, label="Add Frame")
        add_row.Add(self.choice_frame, 1, wx.RIGHT, 4)
        add_row.Add(self.btn_add_frame, 0)
        edit_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_remove_frame = wx.Button(af_box, label="Remove")
        self.btn_move_up = wx.Button(af_box, label="Up")
        self.btn_move_down = wx.Button(af_box, label="Down")
        edit_row.Add(self.btn_remove_frame, 1, wx.RIGHT, 4)
        edit_row.Add(self.btn_move_up, 1, wx.RIGHT, 4)
        edit_row.Add(self.btn_move_down, 1)
        prop_grid = wx.FlexGridSizer(rows=0, cols=2, vgap=4, hgap=4)
        prop_grid.Add(wx.StaticText(af_box, label="Duration (ms)"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_duration = wx.SpinCtrl(af_box, min=1, max=10000, initial=100)
        prop_grid.Add(self.spin_duration, 1, wx.EXPAND)
        prop_grid.Add(wx.StaticText(af_box, label="Trajectory"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.chk_trajectory = wx.CheckBox(af_box)
        self.chk_trajectory.SetValue(True)
        prop_grid.Add(self.chk_trajectory, 0)
        prop_grid.Add(wx.StaticText(af_box, label="Offset X"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_off_x = wx.SpinCtrl(af_box, min=-2048, max=2048, initial=0)
        prop_grid.Add(self.spin_off_x, 1, wx.EXPAND)
        prop_grid.Add(wx.StaticText(af_box, label="Offset Y"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.spin_off_y = wx.SpinCtrl(af_box, min=-2048, max=2048, initial=0)
        prop_grid.Add(self.spin_off_y, 1, wx.EXPAND)
        prop_grid.AddGrowableCol(1, 1)
        af_sizer.Add(self.aframe_list, 1, wx.EXPAND | wx.ALL, 4)
        af_sizer.Add(add_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        af_sizer.Add(edit_row, 0, wx.EXPAND | wx.ALL, 4)
        af_sizer.Add(prop_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        sidebar.Add(anim_sizer, 0, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(playback_sizer, 0, wx.EXPAND | wx.ALL, 4)
        sidebar.Add(af_sizer, 1, wx.EXPAND | wx.ALL, 4)

        self.canvas = AnimationCanvas(self, self.project)
        right.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 4)

        main.Add(sidebar, 0, wx.EXPAND)
        main.Add(right, 1, wx.EXPAND)
        self.SetSizer(main)

        # Events
        self.btn_add_anim.Bind(wx.EVT_BUTTON, self.on_add_animation)
        self.btn_rename_anim.Bind(wx.EVT_BUTTON, self.on_rename_animation)
        self.btn_delete_anim.Bind(wx.EVT_BUTTON, self.on_delete_animation)
        self.anim_list.Bind(wx.EVT_LISTBOX, self.on_select_animation)
        self.playback_choice.Bind(wx.EVT_CHOICE, self.on_change_playback)
        self.loop_spin.Bind(wx.EVT_SPINCTRL, self.on_change_playback)
        self.btn_first.Bind(wx.EVT_BUTTON, lambda _: self.jump_to(0))
        self.btn_last.Bind(wx.EVT_BUTTON, lambda _: self.jump_to_last())
        self.btn_prev.Bind(wx.EVT_BUTTON, lambda _: self.step(-1))
        self.btn_next.Bind(wx.EVT_BUTTON, lambda _: self.step(1))
        self.btn_play.Bind(wx.EVT_BUTTON, self.on_play)
        self.btn_stop.Bind(wx.EVT_BUTTON, self.on_stop)
        self.btn_add_frame.Bind(wx.EVT_BUTTON, self.on_add_aframe)
        self.btn_remove_frame.Bind(wx.EVT_BUTTON, self.on_remove_aframe)
        self.btn_move_up.Bind(wx.EVT_BUTTON, lambda _: self.reorder(-1))
        self.btn_move_down.Bind(wx.EVT_BUTTON, lambda _: self.reorder(1))
        self.aframe_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_aframe)
        self.spin_duration.Bind(wx.EVT_SPINCTRL, self.on_change_aframe_props)
        self.spin_off_x.Bind(wx.EVT_SPINCTRL, self.on_change_aframe_props)
        self.spin_off_y.Bind(wx.EVT_SPINCTRL, self.on_change_aframe_props)
        self.chk_trajectory.Bind(wx.EVT_CHECKBOX, self.on_toggle_trajectory)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)

        self.refresh_choices()

    # Animation handling
    def refresh_animations(self, select_id: Optional[str] = None) -> None:
        self.anim_list.Clear()
        for anim in self.project.animations:
            self.anim_list.Append(f"{anim.name} ({anim.id})", clientData=anim.id)
        if self.anim_list.GetCount() == 0:
            self.canvas.set_animation(None)
            return
        if select_id:
            for idx in range(self.anim_list.GetCount()):
                if self.anim_list.GetClientData(idx) == select_id:
                    self.anim_list.SetSelection(idx)
                    self.select_animation(select_id)
                    return
        if self.anim_list.GetCount() > 0:
            self.anim_list.SetSelection(0)
            self.select_animation(self.anim_list.GetClientData(0))

    def on_add_animation(self, _: wx.CommandEvent) -> None:
        name = f"Animation {len(self.project.animations)+1}"
        anim = self.project.create_animation(name)
        self.refresh_animations(select_id=anim.id)

    def on_rename_animation(self, _: wx.CommandEvent) -> None:
        if not self.selected_animation_id:
            return
        anim = self.project.get_animation(self.selected_animation_id)
        if not anim:
            return
        with wx.TextEntryDialog(self, "New name", value=anim.name) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                anim.name = dlg.GetValue()
                self.refresh_animations(select_id=anim.id)

    def on_delete_animation(self, _: wx.CommandEvent) -> None:
        if not self.selected_animation_id:
            return
        self.project.animations = [a for a in self.project.animations if a.id != self.selected_animation_id]
        self.selected_animation_id = None
        self.refresh_animations()
        self.canvas.set_animation(None)

    def on_select_animation(self, event: wx.CommandEvent) -> None:
        idx = event.GetSelection()
        anim_id = self.anim_list.GetClientData(idx)
        self.select_animation(anim_id)

    def select_animation(self, anim_id: str) -> None:
        self.selected_animation_id = anim_id
        anim = self.project.get_animation(anim_id)
        if not anim:
            return
        self.playback_choice.SetStringSelection(anim.playback_type)
        self.loop_spin.SetValue(anim.loop_count if anim.loop_count is not None else -1)
        self.canvas.set_animation(anim)
        self.refresh_aframes()
        self.current_index = 0
        self.update_duration_fields()

    # AFrame handling
    def refresh_aframes(self, select_idx: Optional[int] = None) -> None:
        self.aframe_list.DeleteAllItems()
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim:
            return
        for i, af in enumerate(anim.aframes):
            frame = self.project.get_frame(af.frame_id)
            label = frame.name if frame else af.frame_id
            idx = self.aframe_list.InsertItem(self.aframe_list.GetItemCount(), label)
            self.aframe_list.SetItem(idx, 1, str(af.duration_ms))
            self.aframe_list.SetItem(idx, 2, f"{af.offset[0]},{af.offset[1]}")
        if select_idx is not None and 0 <= select_idx < self.aframe_list.GetItemCount():
            self.aframe_list.Select(select_idx)
            self.select_aframe(select_idx)

    def on_add_aframe(self, _: wx.CommandEvent) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or self.choice_frame.GetSelection() == wx.NOT_FOUND:
            return
        frame_id = self.choice_frame.GetClientData(self.choice_frame.GetSelection())
        af = AFrame(frame_id=frame_id, duration_ms=100, offset=(0, 0))
        anim.aframes.append(af)
        self.refresh_aframes(select_idx=len(anim.aframes) - 1)
        self.canvas.Refresh(False)

    def on_remove_aframe(self, _: wx.CommandEvent) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim:
            return
        idx = self.aframe_list.GetNextItem(-1, state=wx.LIST_STATE_SELECTED)
        if idx == -1:
            return
        del anim.aframes[idx]
        self.refresh_aframes()
        self.canvas.Refresh(False)

    def reorder(self, direction: int) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim:
            return
        idx = self.aframe_list.GetNextItem(-1, state=wx.LIST_STATE_SELECTED)
        if idx == -1:
            return
        new_idx = max(0, min(len(anim.aframes) - 1, idx + direction))
        if new_idx == idx:
            return
        af = anim.aframes.pop(idx)
        anim.aframes.insert(new_idx, af)
        self.refresh_aframes(select_idx=new_idx)
        self.canvas.Refresh(False)

    def on_select_aframe(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        self.select_aframe(idx)

    def select_aframe(self, idx: int) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or not anim.aframes:
            return
        self.current_index = max(0, min(idx, len(anim.aframes) - 1))
        af = anim.aframes[self.current_index]
        self.spin_duration.SetValue(af.duration_ms)
        self.spin_off_x.SetValue(int(af.offset[0]))
        self.spin_off_y.SetValue(int(af.offset[1]))
        self.canvas.set_current_index(self.current_index)
        self.canvas.Refresh(False)

    def on_change_aframe_props(self, _: wx.CommandEvent) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or not anim.aframes:
            return
        idx = self.aframe_list.GetNextItem(-1, state=wx.LIST_STATE_SELECTED)
        if idx == -1:
            idx = self.current_index
        idx = max(0, min(idx, len(anim.aframes) - 1))
        af = anim.aframes[idx]
        af.duration_ms = self.spin_duration.GetValue()
        af.offset = (self.spin_off_x.GetValue(), self.spin_off_y.GetValue())
        self.refresh_aframes(select_idx=idx)
        self.canvas.Refresh(False)

    def update_duration_fields(self) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if anim and anim.aframes:
            af = anim.aframes[self.current_index]
            self.spin_duration.SetValue(af.duration_ms)
            self.spin_off_x.SetValue(int(af.offset[0]))
            self.spin_off_y.SetValue(int(af.offset[1]))

    # Playback controls
    def on_change_playback(self, _: wx.CommandEvent) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim:
            return
        anim.playback_type = self.playback_choice.GetStringSelection()
        anim.loop_count = self.loop_spin.GetValue()

    def on_play(self, _: wx.CommandEvent) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or not anim.aframes:
            return
        self.play_direction = 1
        self.remaining_loops = anim.loop_count if anim.loop_count is not None and anim.loop_count >= 0 else None
        self.current_index = min(self.current_index, len(anim.aframes) - 1)
        self.canvas.set_current_index(self.current_index)
        self.refresh_aframes(select_idx=self.current_index)
        self.update_duration_fields()
        self.schedule_timer()

    def on_stop(self, _: wx.CommandEvent) -> None:
        self.timer.Stop()

    def step(self, delta: int) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or not anim.aframes:
            return
        self.current_index = (self.current_index + delta) % len(anim.aframes)
        self.canvas.set_current_index(self.current_index)
        self.refresh_aframes(select_idx=self.current_index)
        self.update_duration_fields()

    def jump_to(self, idx: int) -> None:
        self.step_to_index(idx)

    def jump_to_last(self) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or not anim.aframes:
            return
        self.step_to_index(len(anim.aframes) - 1)

    def step_to_index(self, idx: int) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or not anim.aframes:
            return
        self.current_index = max(0, min(idx, len(anim.aframes) - 1))
        self.canvas.set_current_index(self.current_index)
        self.refresh_aframes(select_idx=self.current_index)
        self.update_duration_fields()

    def on_timer(self, _: wx.TimerEvent) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or not anim.aframes:
            return
        self.advance_playback(anim)

    def schedule_timer(self) -> None:
        anim = self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None
        if not anim or not anim.aframes:
            return
        duration = anim.aframes[self.current_index].duration_ms
        self.timer.Start(duration)

    def advance_playback(self, anim: Animation) -> None:
        mode = anim.playback_type
        last_idx = len(anim.aframes) - 1
        if mode in ("forward", "backward"):
            self.current_index += 1 if mode == "forward" else -1
            if self.current_index < 0 or self.current_index > last_idx:
                self.timer.Stop()
                self.current_index = max(0, min(self.current_index, last_idx))
        elif mode in ("loop", "loop_n"):
            next_idx = self.current_index + 1
            if next_idx > last_idx:
                if mode == "loop_n":
                    if self.remaining_loops is None:
                        self.remaining_loops = anim.loop_count
                    if self.remaining_loops is not None:
                        self.remaining_loops -= 1
                        if self.remaining_loops < 0:
                            self.timer.Stop()
                            next_idx = last_idx
                        else:
                            next_idx = 0
                else:
                    next_idx = 0
            self.current_index = next_idx
        elif mode in ("ping_pong", "ping_pong_n"):
            next_idx = self.current_index + self.play_direction
            bounced = False
            if next_idx > last_idx or next_idx < 0:
                self.play_direction *= -1
                bounced = True
                next_idx = self.current_index + self.play_direction
            if bounced and mode == "ping_pong_n":
                if self.remaining_loops is None:
                    self.remaining_loops = anim.loop_count
                if self.remaining_loops is not None:
                    self.remaining_loops -= 1
                    if self.remaining_loops < 0:
                        self.timer.Stop()
                        next_idx = max(0, min(next_idx, last_idx))
            self.current_index = max(0, min(next_idx, last_idx))
        self.canvas.set_current_index(self.current_index)
        self.refresh_aframes(select_idx=self.current_index)
        self.update_duration_fields()
        if self.timer.IsRunning():
            self.schedule_timer()

    def on_toggle_trajectory(self, event: wx.CommandEvent) -> None:
        self.canvas.show_trajectory = event.IsChecked()
        self.canvas.Refresh(False)

    # Data refresh
    def refresh_choices(self) -> None:
        self.choice_frame.Clear()
        for f in self.project.frames:
            self.choice_frame.Append(f"{f.name} ({f.id})", clientData=f.id)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.canvas.project = project
        self.selected_animation_id = None
        self.current_index = 0
        self.canvas.set_animation(None)
        self.refresh_choices()
        self.refresh_animations()
