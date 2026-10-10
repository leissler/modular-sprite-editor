"""Animation editor panel with timeline and playback."""

from __future__ import annotations

from typing import List, Optional, Tuple

import wx

from models import AFrame, Animation, Project, generate_id
from ui.canvas import AnimationCanvas
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.components.timeline_control import TimelineControl
from ui.components.frame_palette import FramePalette
from ui import app_services
from ui.utils import load_wx_image_safely

class AnimationEditorPanel(wx.Panel):
    PLAYBACK_TYPES = ["forward", "backward", "loop", "ping_pong"]
    ONION_CHOICES = ("Off", "Previous", "Next", "Both")

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_animation_id: Optional[str] = None
        self.current_index: int = 0
        self.play_direction = 1
        self.remaining_loops: Optional[int] = None
        self.is_playing = False
        self.timer = wx.Timer(self)
        self.current_animation: Optional[Animation] = None
        self._anim_view: List[Animation] = []
        self.ui_updating = False
        
        # Splitter occupies the full panel
        self.splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # --- LEFT PANEL: Manager ---
        self.left_panel = wx.Panel(self.splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 1. Animation List
        self.anim_box = wx.StaticBox(self.left_panel, label="Animations")
        anim_sizer = wx.StaticBoxSizer(self.anim_box, wx.VERTICAL)
        self.anim_filter = wx.SearchCtrl(self.anim_box, style=wx.TE_PROCESS_ENTER)
        self.anim_filter.SetDescriptiveText("Filter animations")
        self.anim_filter.ShowCancelButton(True)
        
        # List of Animations (Editable Labels for renaming)
        self.anim_list = wx.ListCtrl(self.anim_box, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.LC_EDIT_LABELS)
        self.anim_list.InsertColumn(0, "Name", width=200)
        self.anim_list.Bind(wx.EVT_SIZE, self.on_anim_list_size)
        
        anim_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add_anim = wx.Button(self.anim_box, label="Add")
        self.btn_dup_anim = wx.Button(self.anim_box, label="Duplicate")
        self.btn_delete_anim = wx.Button(self.anim_box, label="Delete")
        anim_btns.Add(self.btn_add_anim, 1, wx.RIGHT, 4)
        anim_btns.Add(self.btn_dup_anim, 1, wx.RIGHT, 4)
        anim_btns.Add(self.btn_delete_anim, 1)
        
        anim_sizer.Add(self.anim_filter, 0, wx.EXPAND | wx.ALL, 4)
        anim_sizer.Add(self.anim_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
        anim_sizer.Add(anim_btns, 0, wx.EXPAND | wx.ALL, 4)
        
        # 2. Frame Palette (Bottom Left)
        pal_box = wx.StaticBox(self.left_panel, label="Frame Palette")
        pal_sizer = wx.StaticBoxSizer(pal_box, wx.VERTICAL)
        self.palette_filter = wx.SearchCtrl(pal_box, style=wx.TE_PROCESS_ENTER)
        self.palette_filter.SetDescriptiveText("Filter frames")
        self.palette_filter.ShowCancelButton(True)
        self.frame_palette = FramePalette(pal_box, self.project)
        self.frame_palette.SetToolTip("Double-click or drag a frame into the strip below")
        pal_sizer.Add(self.palette_filter, 0, wx.EXPAND | wx.ALL, 4)
        pal_sizer.Add(self.frame_palette, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        left_sizer.Add(anim_sizer, 1, wx.EXPAND | wx.ALL, 4)
        left_sizer.Add(pal_sizer, 1, wx.EXPAND | wx.ALL, 4)
        self.left_panel.SetSizer(left_sizer)
        
        # --- RIGHT PANEL: Workspace ---
        self.right_panel = wx.Panel(self.splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 1. Canvas + view bar
        self.canvas = AnimationCanvas(self.right_panel, self.project)
        self.canvas_controls = CanvasDisplayControls(self.right_panel, self.canvas, view_key="animations", part_bounds=True)
        self.canvas_controls.add_separator()
        self.chk_trajectory = self.canvas_controls.add_toggle(
            "Path", True, self.on_toggle_trajectory, "Show the offset trajectory of all frames"
        )
        self.chk_mirror_x = self.canvas_controls.add_toggle(
            "Mirror X", False, lambda _v: self.on_toggle_global_flip(None), "Preview the animation mirrored horizontally"
        )
        self.chk_mirror_y = self.canvas_controls.add_toggle(
            "Mirror Y", False, lambda _v: self.on_toggle_global_flip(None), "Preview the animation mirrored vertically"
        )
        self.chk_vis_col = self.canvas_controls.add_toggle("Collision", False, self.on_toggle_vis_col)
        self.chk_vis_pts = self.canvas_controls.add_toggle("Points", False, self.on_toggle_vis_pts)
        self.onion_choice = wx.Choice(self.canvas_controls, choices=list(self.ONION_CHOICES))
        self.onion_choice.SetSelection(0)
        self.onion_choice.SetMinSize((110, -1))
        self.onion_choice.SetToolTip("Ghost the previous (red) / next (blue) frame of the animation")
        self.canvas_controls.add_control(self.onion_choice, "Onion")
        
        # 2. Timeline & Controls (Bottom Right)
        bottom_box = wx.StaticBox(self.right_panel, label="Frames && Playback")
        # Catch background clicks on the static box
        bottom_box.Bind(wx.EVT_LEFT_DOWN, self.on_panel_click)
        bottom_sizer = wx.StaticBoxSizer(bottom_box, wx.VERTICAL)
        
        # Timeline Widget
        self.timeline = TimelineControl(bottom_box, self.project)
        self.timeline.SetMinSize((-1, 72))
        
        # Transport
        pb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_first = wx.Button(bottom_box, label="|◀", size=(36, -1))
        self.btn_prev = wx.Button(bottom_box, label="◀", size=(36, -1))
        self.btn_play = wx.Button(bottom_box, label="Play")
        self.btn_stop = wx.Button(bottom_box, label="Stop")
        self.btn_next = wx.Button(bottom_box, label="▶", size=(36, -1))
        self.btn_last = wx.Button(bottom_box, label="▶|", size=(36, -1))
        self.btn_first.SetToolTip("First frame")
        self.btn_prev.SetToolTip("Previous frame (,)")
        self.btn_play.SetToolTip("Play / pause (Enter)")
        self.btn_stop.SetToolTip("Stop and rewind")
        self.btn_next.SetToolTip("Next frame (.)")
        self.btn_last.SetToolTip("Last frame")
        for btn in (self.btn_first, self.btn_prev, self.btn_play, self.btn_stop, self.btn_next, self.btn_last):
            pb_sizer.Add(btn, 0, wx.RIGHT, 2)
        self.info_label = wx.StaticText(bottom_box, label="")
        pb_sizer.Add(self.info_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        
        # Selected frame properties
        frame_box = wx.StaticBox(bottom_box, label="Selected Frame")
        frame_sizer = wx.StaticBoxSizer(frame_box, wx.HORIZONTAL)
        frame_sizer.Add(wx.StaticText(frame_box, label="Duration"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.spin_duration = wx.SpinCtrl(frame_box, min=1, max=10000, initial=1, size=(64, -1))
        self.spin_duration.SetToolTip("Hold time in animation ticks (1 tick = 1 / FPS seconds)")
        frame_sizer.Add(self.spin_duration, 0, wx.RIGHT, 12)
        frame_sizer.Add(wx.StaticText(frame_box, label="Offset"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.spin_off_x = wx.SpinCtrl(frame_box, min=-2048, max=2048, initial=0, size=(64, -1), style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
        frame_sizer.Add(self.spin_off_x, 0, wx.RIGHT, 2)
        self.spin_off_y = wx.SpinCtrl(frame_box, min=-2048, max=2048, initial=0, size=(64, -1), style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
        frame_sizer.Add(self.spin_off_y, 0, wx.RIGHT, 12)
        self.chk_flip_x = wx.CheckBox(frame_box, label="Flip X")
        self.chk_flip_y = wx.CheckBox(frame_box, label="Flip Y")
        frame_sizer.Add(self.chk_flip_x, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        frame_sizer.Add(self.chk_flip_y, 0, wx.ALIGN_CENTER_VERTICAL)

        # Animation-wide properties
        anim_props_box = wx.StaticBox(bottom_box, label="Animation")
        anim_row = wx.StaticBoxSizer(anim_props_box, wx.HORIZONTAL)
        anim_row.Add(wx.StaticText(anim_props_box, label="Playback"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.playback_choice = wx.Choice(anim_props_box, choices=self.PLAYBACK_TYPES)
        self.playback_choice.SetSelection(2)
        anim_row.Add(self.playback_choice, 0, wx.RIGHT, 12)
        anim_row.Add(wx.StaticText(anim_props_box, label="Loops"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.loop_spin = wx.SpinCtrl(anim_props_box, min=0, max=9999, initial=0, size=(60, -1))
        self.loop_spin.SetToolTip("0 = loop forever")
        anim_row.Add(self.loop_spin, 0, wx.RIGHT, 12)
        anim_row.Add(wx.StaticText(anim_props_box, label="FPS"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.fps_spin = wx.SpinCtrl(anim_props_box, min=1, max=60, initial=10, size=(56, -1))
        self.fps_spin.SetToolTip("Ticks per second (Mega Drive / SNES NTSC run at 60 Hz, PAL at 50 Hz)")
        anim_row.Add(self.fps_spin, 0)

        props_row = wx.BoxSizer(wx.HORIZONTAL)
        props_row.Add(frame_sizer, 0, wx.RIGHT, 8)
        props_row.Add(anim_row, 0)

        # Layout
        bottom_sizer.Add(self.timeline, 0, wx.EXPAND | wx.ALL, 4)
        bottom_sizer.Add(pb_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)
        bottom_sizer.Add(props_row, 0, wx.ALL, 4)

        right_sizer.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 4)
        right_sizer.Add(self.canvas_controls, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        right_sizer.Add(bottom_sizer, 0, wx.EXPAND | wx.ALL, 4)
        self.right_panel.SetSizer(right_sizer)
        
        # Splitter Setup
        self.splitter.SplitVertically(self.left_panel, self.right_panel, 380)
        self.splitter.SetMinimumPaneSize(200)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)

        # Event Binding
        self.btn_add_anim.Bind(wx.EVT_BUTTON, self.on_add_animation)
        self.btn_dup_anim.Bind(wx.EVT_BUTTON, self.on_duplicate_animation)
        self.btn_delete_anim.Bind(wx.EVT_BUTTON, self.on_delete_animation)
        self.anim_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_animation)
        self.anim_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.anim_list.EditLabel(e.GetIndex()))
        self.anim_list.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.on_rename_animation_end)
        self.anim_list.Bind(wx.EVT_KEY_DOWN, self.on_anim_list_key_down)
        self.anim_list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_anim_list_right_click)
        self.anim_list.Bind(wx.EVT_LIST_BEGIN_DRAG, self.on_begin_drag_anim)
        self.anim_list.SetDropTarget(AnimationListDropTarget(self))
        self.anim_filter.Bind(wx.EVT_TEXT, lambda e: self.refresh_animations(self.selected_animation_id))
        self.anim_filter.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.anim_filter.SetValue(""))
        self.palette_filter.Bind(wx.EVT_TEXT, lambda e: self.frame_palette.set_filter(self.palette_filter.GetValue()))
        self.palette_filter.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.palette_filter.SetValue(""))
        self.onion_choice.Bind(wx.EVT_CHOICE, self.on_onion_changed)

        self.playback_choice.Bind(wx.EVT_CHOICE, self.on_change_playback)
        self.loop_spin.Bind(wx.EVT_SPINCTRL, self.on_change_playback)
        self.fps_spin.Bind(wx.EVT_SPINCTRL, self.on_change_playback)
        
        self.btn_first.Bind(wx.EVT_BUTTON, lambda _: self.jump_to(0))
        self.btn_last.Bind(wx.EVT_BUTTON, lambda _: self.jump_to_last())
        self.btn_prev.Bind(wx.EVT_BUTTON, lambda _: self.step(-1))
        self.btn_next.Bind(wx.EVT_BUTTON, lambda _: self.step(1))
        self.btn_play.Bind(wx.EVT_BUTTON, self.on_play)
        self.btn_stop.Bind(wx.EVT_BUTTON, self.on_stop_manual)
        
        self.spin_duration.Bind(wx.EVT_SPINCTRL, self.on_change_aframe_props)
        self.spin_off_x.Bind(wx.EVT_SPINCTRL, self.on_change_aframe_props)
        self.spin_off_x.Bind(wx.EVT_TEXT_ENTER, self.on_change_aframe_props)
        self.spin_off_x.Bind(wx.EVT_KILL_FOCUS, self.on_spin_kill_focus)
        
        self.spin_off_y.Bind(wx.EVT_SPINCTRL, self.on_change_aframe_props)
        self.spin_off_y.Bind(wx.EVT_TEXT_ENTER, self.on_change_aframe_props)
        self.spin_off_y.Bind(wx.EVT_KILL_FOCUS, self.on_spin_kill_focus)
        
        self.chk_flip_x.Bind(wx.EVT_CHECKBOX, self.on_change_aframe_props)
        self.chk_flip_y.Bind(wx.EVT_CHECKBOX, self.on_change_aframe_props)
        
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

        # Catch background clicks to steal focus (triggering Input commit)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_panel_click)
        self.right_panel.Bind(wx.EVT_LEFT_DOWN, self.on_panel_click)
        self.left_panel.Bind(wx.EVT_LEFT_DOWN, self.on_panel_click)
        self.splitter.Bind(wx.EVT_LEFT_DOWN, self.on_panel_click)
        
        # Power-User Bindings for SpinCtrls
        # Mac wx.SpinCtrl logic is complex; we try to bind to children if possible
        def safe_bind(ctrl):
            ctrl.Bind(wx.EVT_KEY_DOWN, self.on_spin_key_down)
            ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_spin_enter_press)
            # Try binding to internal TextCtrl if available (common fix for Mac)
            if hasattr(ctrl, "GetTextCtrl"):
                tc = ctrl.GetTextCtrl()
                if tc:
                    tc.Bind(wx.EVT_KEY_DOWN, self.on_spin_key_down)
        
        safe_bind(self.spin_off_x)
        safe_bind(self.spin_off_y)
        safe_bind(self.spin_duration)

        # Component Wiring
        self.frame_palette.on_frame_double_click = self.on_add_frame_from_palette
        self.timeline.on_seek = self.on_timeline_seek
        self.timeline.on_remove = self.on_timeline_remove
        self.timeline.on_reorder = self.on_timeline_reorder
        self.timeline.on_insert_frame = self.on_timeline_insert
        self.timeline.on_reorder_frame = self.on_timeline_drag_reorder
        self.canvas.on_offset_change = self.on_canvas_offset_change
        self.canvas.on_modify_ended = self.snapshot
        self.canvas.on_modify_started = self.snapshot

        self.refresh_animations()
        self.frame_palette.refresh_frames()
        self._update_info_label()

    def snapshot(self):
        """Mark an undo step (project-wide history lives in the main window)."""
        app_services.request_checkpoint()

    # --- Panel interface used by the main window ---
    def get_active_canvas(self):
        return self.canvas

    def on_active_mapping_changed(self) -> None:
        self.frame_palette.invalidate_scale()
        self.frame_palette.Refresh()
        self.timeline.Refresh(False)
        self.canvas._update_frame()
        self.canvas.Refresh(False)

    def refresh_after_history(self) -> None:
        anim_id = self.selected_animation_id if self.project.get_animation(self.selected_animation_id or "") else None
        self.ui_updating = True
        try:
            self.refresh_animations(select_id=anim_id)
        finally:
            self.ui_updating = False
        anim = self.project.get_animation(anim_id) if anim_id else None
        self.selected_animation_id = anim_id
        self.canvas.set_animation(anim)
        self.timeline.set_animation(anim)
        self._load_animation_props(anim)
        if anim and anim.aframes:
            self.current_index = max(0, min(self.current_index, len(anim.aframes) - 1))
        else:
            self.current_index = 0
        self.frame_palette.invalidate_scale()
        self.frame_palette.refresh_frames()
        self.update_aframe_ui()

    def on_onion_changed(self, _event: wx.CommandEvent) -> None:
        self.canvas.set_onion_mode(self.ONION_CHOICES[self.onion_choice.GetSelection()].lower())

    def _update_info_label(self) -> None:
        anim = self.get_selected_anim()
        if not anim or not anim.aframes:
            self.info_label.SetLabel("No frames" if anim else "")
            return
        fps = anim.fps if anim.fps > 0 else 10
        total = sum(max(1, af.duration_frames) for af in anim.aframes)
        idx = max(0, min(self.current_index, len(anim.aframes) - 1))
        start = sum(max(1, af.duration_frames) for af in anim.aframes[:idx])
        self.info_label.SetLabel(
            f"Frame {idx + 1}/{len(anim.aframes)}  •  tick {start}/{total}  •  "
            f"length {total / float(fps):.2f}s @ {fps} fps"
        )

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        if not self.IsShownOnScreen():
            event.Skip()
            return
        focus = wx.Window.FindFocus()
        keycode = event.GetKeyCode()
        if app_services.text_entry_has_focus() or event.CmdDown() or event.ControlDown() or event.AltDown():
            event.Skip()
            return
        if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and focus is not self.anim_list:
            self.on_play(None)
            return
        if keycode == ord(','):
            self.step(-1)
            return
        if keycode == ord('.'):
            self.step(1)
            return
        if focus is self.canvas and keycode in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN):
            self._nudge_offset(keycode, 8 if event.ShiftDown() else 1)
            return
        event.Skip()

    def _nudge_offset(self, keycode: int, step: int) -> None:
        anim = self.get_selected_anim()
        if not anim or not anim.aframes or not (0 <= self.current_index < len(anim.aframes)):
            return
        dx = {wx.WXK_LEFT: -step, wx.WXK_RIGHT: step}.get(keycode, 0)
        dy = {wx.WXK_UP: -step, wx.WXK_DOWN: step}.get(keycode, 0)
        # Nudge in screen direction, also while the mirror preview is on.
        if self.canvas.global_flip_x:
            dx = -dx
        if self.canvas.global_flip_y:
            dy = -dy
        af = anim.aframes[self.current_index]
        af.offset = (af.offset[0] + dx, af.offset[1] + dy)
        self.update_aframe_ui()
        self.timeline.Refresh(False)

    def stop_playback_if_running(self) -> None:
        if self.is_playing:
            self.stop_playback()

    def _load_animation_props(self, anim: Optional[Animation]) -> None:
        if not anim:
            return
        self.fps_spin.SetValue(anim.fps if anim.fps > 0 else 10)
        self.loop_spin.SetValue(anim.loop_count if anim.loop_count is not None else 0)
        if anim.playback_type in self.PLAYBACK_TYPES:
            self.playback_choice.SetSelection(self.PLAYBACK_TYPES.index(anim.playback_type))
        else:
            self.playback_choice.SetSelection(2)

    def on_anim_list_size(self, event):
        width = self.anim_list.GetClientSize().width
        if width > 0:
            self.anim_list.SetColumnWidth(0, width)
        event.Skip()

    def refresh_choices(self) -> None:
        """Called by app.py when switching to this tab."""
        self.frame_palette.refresh_frames()

    def set_project(self, project: Project) -> None:
        self.project = project
        self.canvas.project = project
        self.canvas.clear_cache()
        self.frame_palette.project = project
        self.timeline.set_project(project)
        
        # Init canvas visibility maps (Show All by default)
        self.canvas.collision_type_colors = {ct.id: ct.color for ct in project.collision_types}
        self.canvas.point_type_colors = {pt.id: pt.color for pt in project.point_types}
        
        # Sync Visibility Defaults (Hide points by default in animation mode)
        self.canvas.show_points = False
        self.canvas.show_collision = False
        self.chk_vis_col.SetValue(False)
        self.chk_vis_pts.SetValue(False)
        
        self.stop_playback()
        self.selected_animation_id = None
        self.current_index = 0
        self.canvas.set_animation(None)
        self.anim_filter.ChangeValue("")
        self.palette_filter.ChangeValue("")
        self.frame_palette.set_filter("")
        
        # Auto-select first animation if available
        if self.project.animations:
            first_anim = self.project.animations[0]
            self.refresh_animations(select_id=first_anim.id)
            self.on_select_animation_by_id(first_anim.id)
        else:
            self.refresh_animations()
            
        self.frame_palette.refresh_frames()

    def on_select_animation_by_id(self, anim_id: str):
        """Helper to simulate selection logic without event."""
        anim = self.project.get_animation(anim_id)
        if not anim: return
        
        self.selected_animation_id = anim.id
        self.canvas.set_animation(anim)
        self.timeline.set_animation(anim)
        self._load_animation_props(anim)
        self.current_index = 0
        self.canvas.set_current_index(0)
        self.timeline.set_current_index(0)
        self.update_aframe_ui()

    def refresh_animations(self, select_id: Optional[str] = None) -> None:
        query = self.anim_filter.GetValue().strip().lower()
        if query:
            self._anim_view = [a for a in self.project.animations if query in a.name.lower()]
            self.anim_box.SetLabel(f"Animations ({len(self._anim_view)} of {len(self.project.animations)})")
        else:
            self._anim_view = list(self.project.animations)
            self.anim_box.SetLabel(f"Animations ({len(self.project.animations)})")
        self.anim_list.DeleteAllItems()
        target_idx = -1
        for i, anim in enumerate(self._anim_view):
            self.anim_list.InsertItem(i, anim.name)
            if select_id and anim.id == select_id:
                target_idx = i
        
        if target_idx != -1:
             self.anim_list.Select(target_idx)
             self.anim_list.EnsureVisible(target_idx)

    def anim_filter_active(self) -> bool:
        return bool(self.anim_filter.GetValue().strip())

    def get_selected_anim(self) -> Optional[Animation]:
        idx = self.anim_list.GetFirstSelected()
        if 0 <= idx < len(self._anim_view):
            return self._anim_view[idx]
        return None

    def on_select_animation(self, event) -> None:
        if self.ui_updating: return

        anim = self.get_selected_anim()
        if not anim:
            self.selected_animation_id = None
            self.canvas.set_animation(None)
            self.timeline.set_animation(None)
            self._update_info_label()
            return
            
        self.selected_animation_id = anim.id
        self.canvas.set_animation(anim)
        self.timeline.set_animation(anim)
        self._load_animation_props(anim)
        self.current_index = 0
        self.canvas.set_current_index(0)
        self.timeline.set_current_index(0)
        self.update_aframe_ui()

    def _unique_animation_name(self, base: str) -> str:
        used = {a.name for a in self.project.animations}
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base} {suffix}"
            suffix += 1
        return candidate

    def on_add_animation(self, event) -> None:
        new_anim = Animation(
            id=generate_id("anim"),
            name=self._unique_animation_name("New Animation"),
            playback_type="loop",
            fps=10
        )
        current = self.get_selected_anim()
        insert_at = self.project.animations.index(current) + 1 if current else len(self.project.animations)
        self.project.animations.insert(insert_at, new_anim)
        if self.anim_filter_active():
            self.anim_filter.ChangeValue("")
        self.refresh_animations(new_anim.id)
        self.on_select_animation(None)
        self.snapshot()
        wx.CallAfter(self._edit_selected_label)

    def _edit_selected_label(self) -> None:
        idx = self.anim_list.GetFirstSelected()
        if idx != -1:
            self.anim_list.EditLabel(idx)

    def on_delete_animation(self, event) -> None:
        anim = self.get_selected_anim()
        if not anim: return

        scene_uses = sum(
            1
            for scene in self.project.timeline_scenes
            for obj in scene.objects
            if (obj.source_type == "animation" and obj.source_id == anim.id)
            or any(k.source_type == "animation" and k.source_id == anim.id for k in obj.keyframes)
        )
        msg = f"Delete animation '{anim.name}'?"
        if scene_uses:
            msg += f"\n\nIt is used by {scene_uses} timeline object(s)."
        if wx.MessageBox(msg, "Delete Animation", wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
            return
        view_idx = self._anim_view.index(anim) if anim in self._anim_view else 0
        self.stop_playback()
        self.project.animations.remove(anim)
        self.selected_animation_id = None
        self.refresh_animations()
        if self._anim_view:
            neighbour = self._anim_view[min(view_idx, len(self._anim_view) - 1)]
            self.refresh_animations(neighbour.id)
            self.on_select_animation(None)
        else:
            self.canvas.set_animation(None)
            self.timeline.set_animation(None)
            self._update_info_label()
        self.snapshot()

    def on_rename_animation_end(self, event) -> None:
        # Handles edit label completion
        if event.IsEditCancelled():
            return
        new_name = event.GetLabel().strip()
        idx = event.GetIndex()
        if new_name and 0 <= idx < len(self._anim_view):
            self._anim_view[idx].name = new_name
            wx.CallAfter(self.snapshot)

    def on_anim_list_key_down(self, event) -> None:
        kc = event.GetKeyCode()
        if kc == wx.WXK_DELETE or kc == wx.WXK_BACK:
            self.on_delete_animation(None)
        else:
            event.Skip()

    # --- Frame & Playback Logic ---

    def on_add_frame_from_palette(self, frame_id: str) -> None:
        anim = self.get_selected_anim()
        if not anim:
            wx.MessageBox("Please select an animation first!", "No Animation Selected")
            return
            
        self.snapshot()
        
        new_aframe = AFrame(
            frame_id=frame_id,
            duration_frames=1, # Default 1 frame duration
            offset=(0, 0)
        )
        anim.aframes.append(new_aframe)
        self.timeline.Refresh(False)
        self.canvas.Refresh(False)
        # Maybe jump to end?
        self.jump_to_last()
        self.snapshot()


    def on_change_playback(self, event) -> None:
        anim = self.get_selected_anim()
        if not anim: return
        
        ptype_idx = self.playback_choice.GetSelection()
        types = ["forward", "backward", "loop", "ping_pong"]
        if 0 <= ptype_idx < len(types):
            anim.playback_type = types[ptype_idx]
            
        anim.fps = self.fps_spin.GetValue()
        anim.loop_count = self.loop_spin.GetValue()
        self._update_info_label()
        self.canvas._update_frame()
        self.canvas.Refresh(False)
        self.snapshot()

    def update_aframe_ui(self) -> None:
        # Pushes current frame props to UI
        anim = self.get_selected_anim()
        self._update_info_label()
        if not anim or not anim.aframes or self.current_index >= len(anim.aframes):
            self.canvas.set_current_index(-1)
            return
        
        self.ui_updating = True
        try:
            af = anim.aframes[self.current_index]
            self.spin_duration.SetValue(af.duration_frames)
            
            self.spin_off_x.SetValue(af.offset[0])
            self.spin_off_y.SetValue(af.offset[1])
            
            self.chk_flip_x.SetValue(af.flip_x)
            self.chk_flip_y.SetValue(af.flip_y)
        finally:
            self.ui_updating = False
        
        self.canvas.set_current_index(self.current_index)
        self.timeline.set_current_index(self.current_index)

    def on_panel_click(self, event) -> None:
        # Steal focus when clicking empty area
        self.SetFocus()
        event.Skip()

    # --- GIF Export & Context Menu ---
    def on_anim_list_right_click(self, event) -> None:
        idx = event.GetIndex()
        if idx != -1:
            self.anim_list.Select(idx)
        else:
            return # Clicked on empty space?
            
        menu = wx.Menu()
        item_disp_id = menu.Append(wx.ID_ANY, "Duplicate")
        item_del_id = menu.Append(wx.ID_ANY, "Delete")
        menu.AppendSeparator()
        item_flip_h = menu.Append(wx.ID_ANY, "Flip Horizontally")
        item_flip_v = menu.Append(wx.ID_ANY, "Flip Vertically")
        menu.AppendSeparator()
        item_rot_cw = menu.Append(wx.ID_ANY, "Rotate CW (90°)")
        item_rot_ccw = menu.Append(wx.ID_ANY, "Rotate CCW (90°)")
        menu.AppendSeparator()
        item_export = menu.Append(wx.ID_ANY, "Export GIF...")
        
        self.Bind(wx.EVT_MENU, self.on_duplicate_animation, item_disp_id)
        self.Bind(wx.EVT_MENU, self.on_delete_animation, item_del_id)
        self.Bind(wx.EVT_MENU, self.on_flip_anim_h, item_flip_h)
        self.Bind(wx.EVT_MENU, self.on_flip_anim_v, item_flip_v)
        

        self.Bind(wx.EVT_MENU, lambda e: self._rotate_animation(90), item_rot_cw)
        self.Bind(wx.EVT_MENU, lambda e: self._rotate_animation(-90), item_rot_ccw)
        
        self.Bind(wx.EVT_MENU, self.on_export_gif, item_export)
        
        self.PopupMenu(menu)
        menu.Destroy()

    def on_duplicate_animation(self, event) -> None:
        anim = self.get_selected_anim()
        if not anim: return
        
        new_anim = anim.clone()
        new_anim.id = generate_id("anim")
        new_anim.name = self._unique_animation_name(f"{anim.name} copy")
        self.project.animations.insert(self.project.animations.index(anim) + 1, new_anim)
        if self.anim_filter_active():
            self.anim_filter.ChangeValue("")
        self.refresh_animations(select_id=new_anim.id)
        self.on_select_animation(None)
        self.snapshot()

    def on_flip_anim_h(self, event) -> None:
        anim = self.get_selected_anim()
        if not anim: return
        
        self.snapshot()
        
        for af in anim.aframes:
            # Axis Swap Check
            rot = 0
            if hasattr(af, "rotation_degrees"):
                rot = int(round(af.rotation_degrees)) % 180
                
            if rot == 90:
                af.flip_y = not af.flip_y
            else:
                af.flip_x = not af.flip_x
                
            # Offset is Post-Rotation (Global), so always flip X
            af.offset = (-af.offset[0], af.offset[1])
            
        self.update_aframe_ui()
        self.canvas.Refresh()
        self.snapshot()

    def on_flip_anim_v(self, event) -> None:
        anim = self.get_selected_anim()
        if not anim: return
        
        self.snapshot()
        
        for af in anim.aframes:
            # Axis Swap Check
            rot = 0
            if hasattr(af, "rotation_degrees"):
                rot = int(round(af.rotation_degrees)) % 180

            if rot == 90:
                af.flip_x = not af.flip_x
            else:
                af.flip_y = not af.flip_y

            # Offset is Post-Rotation (Global), so always flip Y
            af.offset = (af.offset[0], -af.offset[1])
            
        self.update_aframe_ui()
        self.canvas.Refresh()
        self.snapshot()

    def _rotate_animation(self, degrees: float) -> None:
        anim = self.get_selected_anim()
        if not anim: return
        
        self.snapshot()
        
        rot_steps = int(degrees / 90) % 4
        if rot_steps == 0: return

        for af in anim.aframes:
            # 1. Update Rotation
            # Assuming AFrame has rotation_degrees field now
            old_rot = getattr(af, "rotation_degrees", 0.0)
            af.rotation_degrees = (old_rot + degrees) % 360.0
            
            # 2. Update Offset (Rotate vector)
            ox, oy = af.offset
            
            if degrees == 90 or degrees == -270: # CW
                # (x, y) -> (-y, x)
                af.offset = (-oy, ox)
            elif degrees == -90 or degrees == 270: # CCW
                # (x, y) -> (y, -x)
                af.offset = (oy, -ox)
            elif degrees == 180 or degrees == -180:
                af.offset = (-ox, -oy)
                
        self.update_aframe_ui()
        self.canvas._update_frame() # Update render state
        self.canvas.Refresh()
        self.snapshot()

    def on_begin_drag_anim(self, event):
        idx = event.GetIndex()
        if idx != wx.NOT_FOUND:
             data = wx.TextDataObject(f"ANIM_MOVE:{idx}")
             source = wx.DropSource(self.anim_list)
             source.SetData(data)
             source.DoDragDrop(wx.Drag_DefaultMove)

    def move_animation(self, from_idx: int, to_idx: int):
        if from_idx == to_idx: return
        if self.anim_filter_active():
            app_services.show_status("Clear the animation filter to reorder animations.")
            return
        
        item = self.project.animations.pop(from_idx)
        self.project.animations.insert(to_idx, item)
        
        self.refresh_animations(select_id=item.id)
        self.snapshot()

    def on_export_gif(self, event) -> None:
        anim = self.get_selected_anim()
        if not anim or not anim.aframes:
            wx.MessageBox("No animation or frames to export.", "Export GIF", wx.OK | wx.ICON_WARNING)
            return

        try:
            from PIL import Image as PilImage
        except ImportError:
            wx.MessageBox("Pillow library is required for GIF export.\nPlease install it: pip install Pillow", "Export GIF", wx.OK | wx.ICON_ERROR)
            return

        default_name = f"{anim.name}.gif"
        with wx.FileDialog(self, "Export GIF", defaultFile=default_name, wildcard="GIF files (*.gif)|*.gif", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            path = dlg.GetPath()

        # Capture Global Flip State
        global_flip_x = self.canvas.global_flip_x
        global_flip_y = self.canvas.global_flip_y

        # 1. Calc Bounds of the entire animation
        # We need the union of all frames' bounding boxes
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        
        has_content = False
        
        for af in anim.aframes:
            for fm in self.project.get_frame(af.frame_id).fmodules if self.project.get_frame(af.frame_id) else []:
                if fm.ref_type != "module": continue
                mod = self.project.get_module(fm.ref_id)
                if not mod: continue
                
                # Local Bounds
                w, h = mod.rect[2], mod.rect[3]
                l = fm.position[0] - mod.pivot[0]
                t = fm.position[1] - mod.pivot[1]
                r = l + w
                b = t + h
                
                # Transform to World (Frame Level)
                fx = -1 if af.flip_x else 1
                fy = -1 if af.flip_y else 1
                ox, oy = af.offset
                
                # Apply Global Flip Logic to Bounds
                # World = (Local * FrameFlip + Offset) * GlobalFlip? 
                # NO. View logic is: Output = (Local * FrameFlip + Offset) * GlobalFlip (for position only?)
                # Actually:
                # Frame Canvas: local_to_world(pos) -> pos * render_flip + frame_offset
                # (Where render_flip = frame_flip ^ global_flip)
                # AND frame_offset = raw_offset * global_flip_sign.
                
                # Replicating that:
                gfx = -1 if global_flip_x else 1
                gfy = -1 if global_flip_y else 1
                
                final_ox = ox * gfx
                final_oy = oy * gfy
                
                # The bounds logic in FrameCanvas uses world_to_screen which scales.
                # Here we just want the RAW world coordinates of the corners.
                
                # Corner Transform:
                # 1. Local Flip/Pivot is handled by l,t,r,b relative to origin.
                # 2. Frame Flip: Scale(fx, fy)
                # 3. Frame Offset (Modified by Global): Translate(final_ox, final_oy)
                # 4. Global Flip (affects local coordinates too?):
                #    In Canvas, render_flip_x = frame_flip ^ global_flip.
                #    So use `final_fx` instead of `fx`.
                
                final_fx = -1 if (af.flip_x ^ global_flip_x) else 1
                final_fy = -1 if (af.flip_y ^ global_flip_y) else 1
                
                corners = [(l, t), (r, t), (l, b), (r, b)]
                for cx, cy in corners:
                    wx_val = cx * final_fx + final_ox
                    wy_val = cy * final_fy + final_oy
                    
                    min_x = min(min_x, wx_val)
                    min_y = min(min_y, wy_val)
                    max_x = max(max_x, wx_val)
                    max_y = max(max_y, wy_val)
                    has_content = True
                    
        if not has_content:
            min_x, min_y = 0, 0
            max_x, max_y = 32, 32

        # Add margin
        margin = 2
        min_x -= margin
        min_y -= margin
        max_x += margin
        max_y += margin
        
        width = int(max_x - min_x)
        height = int(max_y - min_y)
        
        if width <= 0 or height <= 0:
             wx.MessageBox("Invalid animation bounds.", "Export Error", wx.OK | wx.ICON_ERROR)
             return

        # 2. Render Frames
        pil_images = []
        fps = anim.fps if anim.fps > 0 else 10
        duration_per_frame_base = 1000.0 / fps # ms
        durations = [] # ms list
        
        # We need a thumbnail generator that supports full offset rendering?
        from ui.utils import ThumbnailGenerator
        gen = ThumbnailGenerator() # Re-use for cache
        
        # Use a temporary bitmap/DC
        bmp = wx.Bitmap(width, height)

        for af in anim.aframes:
            dc = wx.MemoryDC(bmp)
            
            # Use GC for drawing
            gc = wx.GraphicsContext.Create(dc)
            
            # Clear with transparent
            gc.SetCompositionMode(wx.COMPOSITION_SOURCE)
            gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 0))) # Transparent
            gc.DrawRectangle(0, 0, width, height)
            gc.SetCompositionMode(wx.COMPOSITION_OVER)
            
            frame = self.project.get_frame(af.frame_id)
            if frame:
                 for fm in frame.fmodules:
                     mod = self.project.get_module(fm.ref_id)
                     if not mod: continue

                     # 1. Bounds Calculation (Local)
                     w, h = mod.rect[2], mod.rect[3]
                     l = fm.position[0] - mod.pivot[0]
                     t = fm.position[1] - mod.pivot[1]
                     r = l + w
                     b = t + h
                     
                     # 2. Global + Frame Logic
                     gfx = -1 if global_flip_x else 1
                     gfy = -1 if global_flip_y else 1
                     final_ox = af.offset[0] * gfx
                     final_oy = af.offset[1] * gfy
                     
                     final_fx = -1 if (af.flip_x ^ global_flip_x) else 1
                     final_fy = -1 if (af.flip_y ^ global_flip_y) else 1
                     
                     # Corner Calc Matching Bounds
                     # We need to find top-left of the transformed rect to draw bitmap there
                     # BUT Bitmap drawing with negative scale is tricky or unsupported via DrawBitmap directly?
                     # Actually we are doing Mirror() on image, so we draw unscaled bitmap at transformed top-left?
                     # No. If we mirror the image, we draw it at the new Top-Left.
                     
                     # Let's compute projected corners again
                     corners = [(l, t), (r, t), (l, b), (r, b)]
                     w_points = []
                     for cx, cy in corners:
                         wx_val = cx * final_fx + final_ox
                         wy_val = cy * final_fy + final_oy
                         w_points.append((wx_val, wy_val))
                         
                     # Find top-left of this projected polygon (it's a rect aligned with axes because scaling 1/-1)
                     # (Rotation not supported yet in GIF logic refactor, consistent with previous step)
                     mod_min_x = min(p[0] for p in w_points)
                     mod_min_y = min(p[1] for p in w_points)
                     
                     # 3. Adjust for GIF Canvas Origin
                     dest_x = mod_min_x - min_x
                     dest_y = mod_min_y - min_y
                     
                     # 4. Prepare Bitmap
                     img = self.project.get_image(mod.image_id)
                     if img:
                         if img.id not in gen.asset_cache:
                             loaded = load_wx_image_safely(img.file_path)
                             if img.transparent_color:
                                 loaded.SetMaskColour(*img.transparent_color)
                             gen.asset_cache[img.id] = loaded
                             
                         full_img = gen.asset_cache[img.id]
                         rx, ry, rw, rh = mod.rect
                         if rx + rw <= full_img.GetWidth() and ry + rh <= full_img.GetHeight():
                             sub = full_img.GetSubImage(wx.Rect(int(rx), int(ry), int(rw), int(rh)))
                             
                             # 5. Handle Flips
                             # Module Flip XOR Frame Flip XOR Global Flip
                             # Wait, we used final_fx for positioning. 
                             # final_fx includes Frame^Global.
                             # Module flip is local to module.
                             # If we flip the bitmap, does it match the position calc?
                             
                             # Logic check:
                             # Position was calculated assuming we flipped the coordinate space.
                             # So the "Left" of the module became "Right" etc.
                             # If we flip the bitmap, the pixel content mirrors.
                             # The position `mod_min_x` is the visual top-left of the module in the exported image.
                             
                             render_flip_x = fm.flip_x ^ (af.flip_x ^ global_flip_x)
                             render_flip_y = fm.flip_y ^ (af.flip_y ^ global_flip_y)
                             
                             if render_flip_x:
                                 sub = sub.Mirror(horizontally=True)
                             if render_flip_y:
                                 sub = sub.Mirror(horizontally=False)
                             
                             dest_bmp = wx.Bitmap(sub)
                             gc.DrawBitmap(dest_bmp, dest_x, dest_y, rw, rh)
            
            dc.SelectObject(wx.NullBitmap)
            del dc
            
            # Convert to PIL
            img_data = bmp.ConvertToImage() # wx.Image
            
            # Handle Transparency
            # wx.Image doesn't fully preserve alpha channel when converting from Bitmap if not careful?
            # Actually ConvertToImage() usually creates RGB + Alpha if present.
            
            has_alpha = img_data.HasAlpha()
            w_img, h_img = img_data.GetWidth(), img_data.GetHeight()
            
            buffer = img_data.GetData()
            pil_img = PilImage.frombuffer("RGB", (w_img, h_img), buffer)
            
            if has_alpha:
                 alpha_buffer = img_data.GetAlpha()
                 pil_alpha = PilImage.frombuffer("L", (w_img, h_img), alpha_buffer)
                 pil_img.putalpha(pil_alpha)
            
            pil_images.append(pil_img)
            
            # Handling Duration: Frame duration is in "frames/ticks"
            # af.duration_frames * duration_per_frame_base
            ms = int(af.duration_frames * duration_per_frame_base)
            durations.append(ms)

        # 3. Save
        if pil_images:
            # Loop: 0 = infinite (standard GIF)
            loop_count = 0 if anim.loop_count == 0 else anim.loop_count
            
            pil_images[0].save(
                path,
                save_all=True,
                append_images=pil_images[1:],
                duration=durations,
                loop=loop_count, 
                disposal=2 # Restore to background (clears previous frame)
            )
            wx.MessageBox(f"Successfully exported {len(pil_images)} frames to:\n{path}", "Export Success", wx.OK)

    def on_spin_enter_press(self, event) -> None:
        # Explicit Enter Press handler (CommandEvent)
        # Navigate away to trigger focus loss -> commit
        obj = event.GetEventObject()
        if hasattr(obj, 'Navigate'):
            obj.Navigate()
        else:
            self.SetFocus() # Fallback

    def on_spin_key_down(self, event) -> None:
        # Check for Enter key
        if event.GetKeyCode() == wx.WXK_RETURN or event.GetKeyCode() == wx.WXK_NUMPAD_ENTER:
            # Shift focus to next control
            obj = event.GetEventObject()
            if hasattr(obj, 'Navigate'):
                obj.Navigate()
            else:
                self.SetFocus()
        else:
            event.Skip()

    def on_spin_kill_focus(self, event) -> None:
        event.Skip()
        # Call change handler after focus loss allows native control to commit text to value
        wx.CallAfter(self.on_change_aframe_props, None)

    def on_change_aframe_props(self, event=None) -> None:
        if self.ui_updating: return
        
        anim = self.get_selected_anim()
        if not anim or not anim.aframes: return
        
        af = anim.aframes[self.current_index]
        
        # Duration
        # Update if event is None (Focus loss / Enter) or explicitly Duration spin
        if event is None or event.GetEventObject() == self.spin_duration:
            af.duration_frames = self.spin_duration.GetValue()
            
        # Offsets
        # Always update offsets if called (safe to overwrite with current UI value)
        af.offset = (self.spin_off_x.GetValue(), self.spin_off_y.GetValue())
        af.flip_x = self.chk_flip_x.GetValue()
        af.flip_y = self.chk_flip_y.GetValue()

        # Re-derive the canvas transform (respects the mirror preview and onion skin)
        self.canvas._update_frame()
        self.canvas.Refresh(False)
        self.timeline.Refresh(False) # Update thumbnail
        self._update_info_label()

    def on_timeline_seek(self, idx: int) -> None:
        self.current_index = idx
        self.update_aframe_ui()
        self.canvas.Refresh(False)

    def on_timeline_remove(self, idx: int) -> None:
        anim = self.get_selected_anim()
        if not anim or not anim.aframes: return
        
        if 0 <= idx < len(anim.aframes):
            anim.aframes.pop(idx)
            # Adjust index if needed
            if self.current_index >= len(anim.aframes):
                self.current_index = max(0, len(anim.aframes)-1)
            elif self.current_index == idx:
                 # We removed the current one, stay at same index or decr?
                 pass 
            
            self.update_aframe_ui()
            self.timeline.Refresh(False)
            self.canvas.Refresh(False)
            self.snapshot()

    def on_timeline_reorder(self, idx: int, direction: int) -> None:
        anim = self.get_selected_anim()
        if not anim or not anim.aframes: return
        
        new_idx = idx + direction
        if 0 <= new_idx < len(anim.aframes):
            # Swap
            anim.aframes[idx], anim.aframes[new_idx] = anim.aframes[new_idx], anim.aframes[idx]
            
            # Follow selection if we moved the selected one
            if self.current_index == idx:
                self.current_index = new_idx
            elif self.current_index == new_idx:
                self.current_index = idx
                
            self.update_aframe_ui()
            self.timeline.Refresh(False)
            self.canvas.Refresh(False)
            self.snapshot()

    def on_timeline_insert(self, frame_id: str, idx: int) -> None:
        anim = self.get_selected_anim()
        if not anim: return
        
        new_af = AFrame(frame_id=frame_id, duration_frames=1)
        # Validate idx
        if idx < 0: idx = 0
        if idx > len(anim.aframes): idx = len(anim.aframes)
        
        anim.aframes.insert(idx, new_af)
        
        # Update selection to new frame?
        self.current_index = idx
        
        self.update_aframe_ui()
        self.timeline.Refresh(False)
        self.canvas.Refresh(False)
        self.snapshot()

    def on_timeline_drag_reorder(self, from_idx: int, to_idx: int) -> None:
        anim = self.get_selected_anim()
        if not anim or not anim.aframes: return
        
        # List Move Logic:
        # If moving item at 0 to 2:
        # [A, B, C, D] -> pop 0 (A) -> [B, C, D]. insert at 2.
        # But wait, insert index logic in drop target might be "between B and C".
        # If dragging forward, insertion index might need adjustment if it's based on "before removal".
        # But DragOver usually returns "insert before currently at idx".
        
        if from_idx < 0 or from_idx >= len(anim.aframes): return
        
        item = anim.aframes.pop(from_idx)
        
        # If moving forward, to_idx corresponds to index in OLD list.
        # After pop, indices shift.
        # Example: [0, 1, 2, 3]. Move 0 to 2 (between 1 and 2).
        # Pop 0. [1, 2, 3]. Insert at 2-1 = 1? No.
        # Standard implementation:
        if to_idx > from_idx:
            to_idx -= 1
            
        if to_idx < 0: to_idx = 0
        if to_idx > len(anim.aframes): to_idx = len(anim.aframes)
        
        anim.aframes.insert(to_idx, item)
        
        self.current_index = to_idx
        self.update_aframe_ui()
        self.timeline.Refresh(False)
        self.canvas.Refresh(False)
        self.snapshot()

    def on_toggle_trajectory(self, checked: bool) -> None:
        self.canvas.show_trajectory = checked
        self.canvas.Refresh(False)

    def on_toggle_global_flip(self, event) -> None:
        self.canvas.global_flip_x = self.chk_mirror_x.GetValue()
        self.canvas.global_flip_y = self.chk_mirror_y.GetValue()
        # Force re-evaluation of frame properties (offset/flip)
        self.canvas.set_current_index(self.current_index)

    def on_toggle_vis_col(self, checked: bool) -> None:
        self.canvas.show_collision = checked
        self.canvas.Refresh(False)

    def on_toggle_vis_pts(self, checked: bool) -> None:
        self.canvas.show_points = checked
        self.canvas.Refresh(False)

    def on_canvas_offset_change(self, x: int, y: int) -> None:
        # Called when dragging in canvas
        # Update spin ctrls without triggering event loop issues
        self.ui_updating = True
        try:
            self.spin_off_x.SetValue(int(x))
            self.spin_off_y.SetValue(int(y))
        finally:
             self.ui_updating = False

    # --- Timer Playback (Same Logic as Before) ---
    def on_play(self, event) -> None:
        anim = self.get_selected_anim()
        if not anim or not anim.aframes: return
        
        if not self.is_playing:
            self.is_playing = True
            self.btn_play.SetLabel("Pause")
            self.remaining_loops = anim.loop_count
            
            # Context-aware start position with UI Update to prevent skipping first frame visually
            last_idx = len(anim.aframes) - 1
            mode = anim.playback_type
            
            # Reset checks
            should_reset = False
            target_rst = 0
            
            if mode in ("forward", "loop") and self.current_index >= last_idx:
                should_reset = True
                target_rst = 0
            elif mode == "backward" and self.current_index <= 0:
                should_reset = True
                target_rst = last_idx
            elif mode == "ping_pong":
                # If at end, reset to start. If at start, stayed at start.
                if self.current_index >= last_idx:
                    should_reset = True
                    target_rst = 0
            
            if should_reset:
                self.current_index = target_rst
                self.update_aframe_ui() # CRITICAL: Show the start frame immediately!
                self.canvas.Refresh(False)
                
            self.play_direction = -1 if mode == "backward" else 1
            self.schedule_timer()
        else:
            # Handle Pause (Maintain current position)
            self.is_playing = False
            self.btn_play.SetLabel("Play")
            self.timer.Stop()

    def on_stop(self, event) -> None:
        """Handler for Auto-Stop (End of Playback). Does NOT rewind."""
        self.stop_playback()

    def on_stop_manual(self, event) -> None:
        """Handler for Manual Stop Button. Rewinds to start."""
        self.stop_playback()
        
        # Rewind logic
        anim = self.get_selected_anim()
        if anim:
            if anim.playback_type == "backward":
                self.jump_to(len(anim.aframes) - 1)
            else:
                self.jump_to(0)
        self.canvas.Refresh(False)

    def stop_playback(self) -> None:
        """Internal helper to stop timer and update button state."""
        self.is_playing = False
        self.btn_play.SetLabel("Play")
        self.timer.Stop()

    def schedule_timer(self) -> None:
        anim = self.get_selected_anim()
        if not anim or not anim.aframes: return
        
        af = anim.aframes[self.current_index]
        fps = anim.fps if anim.fps > 0 else 10
        ms_delay = int(af.duration_frames * (1000.0 / fps))
        ms_delay = max(10, ms_delay)
        
        self.timer.Start(ms_delay, wx.TIMER_ONE_SHOT)

    def on_timer(self, event) -> None:
        anim = self.get_selected_anim()
        if not anim: return
        self.advance_playback(anim)

    def advance_playback(self, anim: Animation) -> None:
        if not self.is_playing: return
        
        mode = anim.playback_type
        last_idx = len(anim.aframes) - 1
        if last_idx < 0: return
        
        if mode == "forward":
            if self.current_index < last_idx:
                self.current_index += 1
            else:
                self.on_stop(None)
                return
                
        elif mode == "backward":
            if self.current_index > 0:
                self.current_index -= 1
            else:
                self.on_stop(None)
                return
                
        elif mode == "loop":
            if self.current_index < last_idx:
                self.current_index += 1
            else:
                # Finished one full pass
                if anim.loop_count == 0: # Infinite
                    self.current_index = 0
                else:
                    if self.remaining_loops > 1:
                        self.remaining_loops -= 1
                        self.current_index = 0
                    else:
                        self.on_stop(None)
                        return
                        
        elif mode == "ping_pong":
            if last_idx == 0:
                # 1-frame ping-pong is just that frame
                self.current_index = 0
            else:
                # Determine NEXT index
                next_val = self.current_index + self.play_direction
                
                if next_val > last_idx:
                    self.play_direction = -1
                    self.current_index = last_idx - 1
                elif next_val < 0:
                    self.play_direction = 1
                    self.current_index = 1
                    
                    # We returned to start, this is a full cycle loop
                    if anim.loop_count > 0:
                        if self.remaining_loops > 1:
                            self.remaining_loops -= 1
                        else:
                            self.current_index = 0 # Explicitly stay at 0
                            self.on_stop(None)
                            return
                else:
                    self.current_index = next_val
        
        self.update_aframe_ui()
        if self.is_playing:
            self.schedule_timer()

    def jump_to(self, idx: int) -> None:
        self.current_index = idx
        # Ensure Play button label resets if we jumped while stopped (handled by on_stop usually, but good for safety)
        if not self.is_playing:
            self.btn_play.SetLabel("Play")
        self.update_aframe_ui()

    def jump_to_last(self) -> None:
        anim = self.get_selected_anim()
        if anim:
            self.jump_to(len(anim.aframes) - 1)

    def step(self, delta: int) -> None:
        anim = self.get_selected_anim()
        if anim:
            new_idx = max(0, min(len(anim.aframes)-1, self.current_index + delta))
            self.jump_to(new_idx)


class AnimationListDropTarget(wx.TextDropTarget):
    def __init__(self, editor: "AnimationEditorPanel"):
        super().__init__()
        self.editor = editor
        self.last_item = -1
        self.overlay = wx.Overlay()

    def _get_insertion_point(self, x, y) -> Tuple[int, int]:
        """Calculates (insert_index, y_coord) for the insertion line."""
        list_ctrl = self.editor.anim_list
        idx, flags = list_ctrl.HitTest(wx.Point(x, y))
        
        if idx != wx.NOT_FOUND:
            rect = list_ctrl.GetItemRect(idx)
            mid = rect.y + rect.height // 2
            
            if y < mid:
                # Insert Before
                return idx, rect.y
            else:
                # Insert After
                return idx + 1, rect.y + rect.height
        else:
            # Below limits?
            count = list_ctrl.GetItemCount()
            if count > 0:
                rect = list_ctrl.GetItemRect(count - 1)
                if y > rect.y + rect.height:
                    return count, rect.y + rect.height
            elif count == 0:
                return 0, 0
                
            return wx.NOT_FOUND, -1
        
    def OnDragOver(self, x, y, defResult):
        # We process drag over to draw the insertion line
        insert_idx, line_y = self._get_insertion_point(x, y)
        
        list_ctrl = self.editor.anim_list
        
        # Draw Overlay
        dc = wx.ClientDC(list_ctrl)
        odc = wx.DCOverlay(self.overlay, dc)
        odc.Clear()
        
        if insert_idx != wx.NOT_FOUND and line_y != -1:
            dc.SetPen(wx.Pen(wx.Colour(0, 120, 215), 2))
            w = list_ctrl.GetClientSize().width
            dc.DrawLine(0, line_y, w, line_y)
            
        del odc
        
        return defResult

    def OnLeave(self):
        list_ctrl = self.editor.anim_list
        dc = wx.ClientDC(list_ctrl)
        odc = wx.DCOverlay(self.overlay, dc)
        odc.Clear()
        del odc

    def OnDrop(self, x, y):
        return True

    def OnDropText(self, x, y, data):
        if data.startswith("ANIM_MOVE:"):
            # "ANIM_MOVE:<idx>"
            try:
                from_idx = int(data.split(":")[1])
                insert_idx, _ = self._get_insertion_point(x, y)
                
                if insert_idx != wx.NOT_FOUND:
                    # Adjust index if moving downwards
                    target = insert_idx
                    if from_idx < target:
                        target -= 1
                        
                    self.editor.move_animation(from_idx, target)
                    return True
                    
            except ValueError:
                pass
    
        self.OnLeave() # Clear overlay
        return False
        
    def OnData(self, x, y, defResult):
        # Delegate to default behavior which calls OnDropText
        if not self.GetData():
            return wx.DragNone
        
        self.OnLeave() # Ensure overlay is cleared even if drop fails/succeeds
        
        # Super OnData calls OnDropText
        return super().OnData(x, y, defResult)
