"""Scene editor tab: Library | Stage | Inspector on top, layers + dopesheet timeline below."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import wx

from models import Project, TimelineKeyframe, TimelineObject, TimelineScene, generate_id
from ui import app_services
from ui.base_canvas import BACKDROP_COLOUR
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.scene_editor import ops
from ui.scene_editor.inspector import SceneInspector
from ui.scene_editor.library import SceneLibrary
from ui.scene_editor.stage import SCREEN_GUIDES, StageCanvas
from ui.scene_editor.timeline import TimelineView

Selection = Dict[str, Set[str]]

QUICK_EASINGS: List[Tuple[str, str]] = [
    ("Linear", "linear"),
    ("Hold (jump at next key)", "step"),
    ("Ease in (start slow)", "quad_in"),
    ("Ease out (end slow)", "quad_out"),
    ("Ease in & out", "quad_in_out"),
    ("Strong ease in & out", "cubic_in_out"),
    ("Overshoot", "back_out"),
    ("Bounce", "bounce_out"),
    ("Elastic", "elastic_out"),
]

# Shared between scenes/projects for the session.
_KEY_CLIPBOARD: List[Dict[str, Any]] = []
_OBJECT_CLIPBOARD: List[Dict[str, Any]] = []

CONFIG_SCREEN_GUIDE = "SceneEditor/ScreenGuide"


class _StageDropTarget(wx.TextDropTarget):
    def __init__(self, panel: "SceneEditorPanel"):
        super().__init__()
        self.panel = panel

    def OnDropText(self, x: int, y: int, data: str) -> bool:
        prefix, _, rest = data.partition(":")
        kinds = {"MODULE": "module", "FRAME": "frame", "ANIMATION": "animation", "FRAME_REF": "frame"}
        source_type = kinds.get(prefix.strip().upper())
        if not source_type or not rest:
            return False
        source_id = rest.split(":")[-1].strip()
        world = self.panel.stage.screen_to_world(wx.Point(x, y))
        self.panel.add_object(source_type, source_id, (round(world[0]), round(world[1])))
        return True


class SceneEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_scene_id: Optional[str] = None
        self.selected_object_id: Optional[str] = None
        self.selection: Selection = {}
        self.frame = 0
        self.auto_key = True
        self.is_playing = False
        self.hidden_ids: Set[str] = set()
        self.locked_ids: Set[str] = set()
        self.collapsed_ids: Set[str] = set()
        self._scene_ids: List[Optional[str]] = []
        self._tick_cache: Dict[str, Tuple[Any, List[int]]] = {}
        self._drag: Dict[str, Any] = {}
        self._play_start: Tuple[float, int] = (0.0, 0)
        self._fitted_scene_id: Optional[str] = None
        self.timer = wx.Timer(self)
        self._arm_timer_when_idle = False  # see _on_timer
        self._frame_time = 0.0  # when the last playback frame started

        self._build_ui()
        self._bind()
        self.refresh_scenes()

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)

        # Scene bar
        bar = wx.BoxSizer(wx.HORIZONTAL)
        bar.Add(wx.StaticText(self, label="Scene"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.scene_choice = wx.Choice(self)
        self.scene_choice.SetMinSize((200, -1))
        self.btn_scene_add = wx.Button(self, label="New", style=wx.BU_EXACTFIT)
        self.btn_scene_dup = wx.Button(self, label="Duplicate", style=wx.BU_EXACTFIT)
        self.btn_scene_del = wx.Button(self, label="Delete", style=wx.BU_EXACTFIT)
        self.btn_scene_settings = wx.Button(self, label="Scene Settings", style=wx.BU_EXACTFIT)
        self.btn_scene_settings.SetToolTip("Show the scene's frame rate, length and background in the inspector")
        for item, flag in (
            (self.scene_choice, wx.RIGHT),
            (self.btn_scene_add, wx.RIGHT),
            (self.btn_scene_dup, wx.RIGHT),
            (self.btn_scene_del, wx.RIGHT),
        ):
            bar.Add(item, 0, flag | wx.ALIGN_CENTER_VERTICAL, 4)
        bar.AddSpacer(12)
        bar.Add(self.btn_scene_settings, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(bar, 0, wx.EXPAND | wx.ALL, 6)

        self.vsplit = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        top = wx.Panel(self.vsplit)
        self.outer_split = wx.SplitterWindow(top, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.library = SceneLibrary(self.outer_split, self.project)
        self.inner_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)

        stage_panel = wx.Panel(self.inner_split)
        stage_sizer = wx.BoxSizer(wx.VERTICAL)
        self.stage = StageCanvas(stage_panel, self.project)
        self.stage.SetDropTarget(_StageDropTarget(self))
        self.canvas_controls = CanvasDisplayControls(
            stage_panel, self.stage, view_key="timeline", default_backdrop=BACKDROP_COLOUR,
            scene_backdrop=True, part_bounds=True, budget=True,
        )
        self.screen_choice = wx.Choice(self.canvas_controls, choices=[label for label, _ in SCREEN_GUIDES])
        self.screen_choice.SetToolTip(
            "Outline of a console screen, placed like the SGDK demo shows scenes: the scene origin centred, three quarters down"
        )
        self.canvas_controls.add_control(self.screen_choice, "Screen")
        stage_sizer.Add(self.stage, 1, wx.EXPAND | wx.ALL, 2)
        stage_sizer.Add(self.canvas_controls, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        stage_panel.SetSizer(stage_sizer)

        self.inspector = SceneInspector(self.inner_split)
        self.inner_split.SplitVertically(stage_panel, self.inspector, -320)
        self.inner_split.SetSashGravity(1.0)
        self.inner_split.SetMinimumPaneSize(240)
        self.outer_split.SplitVertically(self.library, self.inner_split, 250)
        self.outer_split.SetMinimumPaneSize(180)
        top_sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer.Add(self.outer_split, 1, wx.EXPAND)
        top.SetSizer(top_sizer)

        bottom = wx.Panel(self.vsplit)
        bottom_sizer = wx.BoxSizer(wx.VERTICAL)
        transport = wx.BoxSizer(wx.HORIZONTAL)

        def tbutton(label: str, tip: str, width: int = 34) -> wx.Button:
            btn = wx.Button(bottom, label=label, size=(width, -1))
            btn.SetToolTip(tip)
            transport.Add(btn, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 2)
            return btn

        self.btn_first = tbutton("|◀", "First frame (Home)")
        self.btn_prev_key = tbutton("◆◀", "Previous key (Shift+,)")
        self.btn_prev = tbutton("◀", "Previous frame (,)")
        self.btn_play = tbutton("▶", "Play / pause (Enter)", 44)
        self.btn_next = tbutton("▶", "Next frame (.)")
        self.btn_next_key = tbutton("▶◆", "Next key (Shift+.)")
        self.btn_last = tbutton("▶|", "Last frame (End)")
        transport.AddSpacer(10)
        transport.Add(wx.StaticText(bottom, label="Frame"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.frame_spin = wx.SpinCtrl(bottom, min=0, max=100000, initial=0, size=(70, -1), style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
        transport.Add(self.frame_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.frame_info = wx.StaticText(bottom, label="", size=(190, -1), style=wx.ST_NO_AUTORESIZE)
        transport.Add(self.frame_info, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.chk_loop = wx.CheckBox(bottom, label="Loop")
        transport.Add(self.chk_loop, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        self.btn_autokey = wx.ToggleButton(bottom, label="● Auto-Key")
        self.btn_autokey.SetValue(True)
        self.btn_autokey.SetToolTip(
            "On: moving, rotating or flipping an object sets a key at the playhead.\n"
            "Off: edits between keys move the object's whole animation."
        )
        transport.Add(self.btn_autokey, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        self.btn_add_key = tbutton("◆ Key", "Add a key at the playhead for the selected layer (K)", 64)
        self.btn_del = tbutton("Delete", "Delete the selected keys, or the selected layer (Delete)", 64)
        self.btn_group = tbutton("+ Group", "Add an empty group — useful as a parent to move things together", 72)
        transport.AddStretchSpacer(1)
        self.btn_fit_time = tbutton("Fit", "Show the whole scene in the timeline", 44)
        bottom_sizer.Add(transport, 0, wx.EXPAND | wx.ALL, 4)
        self.timeline_view = TimelineView(bottom)
        self.timeline = self.timeline_view.widget
        bottom_sizer.Add(self.timeline_view, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        bottom.SetSizer(bottom_sizer)

        self.vsplit.SplitHorizontally(top, bottom, -260)
        self.vsplit.SetSashGravity(1.0)
        self.vsplit.SetMinimumPaneSize(160)
        root.Add(self.vsplit, 1, wx.EXPAND)
        self.SetSizer(root)

        guide = wx.Config.Get().ReadInt(CONFIG_SCREEN_GUIDE, 0)
        guide = guide if 0 <= guide < len(SCREEN_GUIDES) else 0
        self.screen_choice.SetSelection(guide)
        self.stage.screen_guide = SCREEN_GUIDES[guide][1]
        self._update_autokey_button()

    def _bind(self) -> None:
        self.scene_choice.Bind(wx.EVT_CHOICE, self._on_scene_choice)
        self.btn_scene_add.Bind(wx.EVT_BUTTON, lambda e: self.new_scene())
        self.btn_scene_dup.Bind(wx.EVT_BUTTON, lambda e: self.duplicate_scene())
        self.btn_scene_del.Bind(wx.EVT_BUTTON, lambda e: self.delete_scene())
        self.btn_scene_settings.Bind(wx.EVT_BUTTON, lambda e: self.select_object(None))
        self.screen_choice.Bind(wx.EVT_CHOICE, self._on_screen_choice)

        self.btn_first.Bind(wx.EVT_BUTTON, lambda e: self.seek(0))
        self.btn_last.Bind(wx.EVT_BUTTON, lambda e: self.seek(self._length()))
        self.btn_prev.Bind(wx.EVT_BUTTON, lambda e: self.step(-1))
        self.btn_next.Bind(wx.EVT_BUTTON, lambda e: self.step(1))
        self.btn_prev_key.Bind(wx.EVT_BUTTON, lambda e: self.jump_key(-1))
        self.btn_next_key.Bind(wx.EVT_BUTTON, lambda e: self.jump_key(1))
        self.btn_play.Bind(wx.EVT_BUTTON, lambda e: self.toggle_play())
        self.frame_spin.Bind(wx.EVT_SPINCTRL, lambda e: self.seek(self.frame_spin.GetValue()))
        self.frame_spin.Bind(wx.EVT_TEXT_ENTER, lambda e: self.seek(self.frame_spin.GetValue()))
        self.chk_loop.Bind(wx.EVT_CHECKBOX, self._on_loop)
        self.btn_autokey.Bind(wx.EVT_TOGGLEBUTTON, self._on_autokey)
        self.btn_add_key.Bind(wx.EVT_BUTTON, lambda e: self.add_key_at_playhead())
        self.btn_del.Bind(wx.EVT_BUTTON, lambda e: self.delete_selection())
        self.btn_group.Bind(wx.EVT_BUTTON, lambda e: self.add_object("none", None))
        self.btn_fit_time.Bind(wx.EVT_BUTTON, lambda e: self.timeline.fit_scene())
        self.Bind(wx.EVT_TIMER, self._on_timer, self.timer)
        self.Bind(wx.EVT_IDLE, self._on_idle)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self.library.on_add = lambda source_type, source_id: self.add_object(source_type, source_id)

        st = self.stage
        st.on_select = self.select_object
        st.on_drag_begin = self._stage_drag_begin
        st.on_drag = self._stage_drag
        st.on_drag_end = self._stage_drag_end
        st.on_key_drag_begin = self._stage_key_drag_begin
        st.on_key_drag = self._stage_key_drag
        st.on_handle_drag_begin = self._stage_handle_drag_begin
        st.on_handle_drag = self._stage_handle_drag
        st.on_context_menu = self._stage_context_menu

        tl = self.timeline
        tl.on_seek = self.seek
        tl.on_select_object = self.select_object
        tl.on_select_keys = self.set_key_selection
        tl.on_move_keys = self._timeline_move_keys
        tl.on_move_keys_end = self._commit
        tl.on_add_key = self._timeline_add_key
        tl.on_toggle_collapse = lambda oid: self._toggle(self.collapsed_ids, oid)
        tl.on_toggle_hidden = lambda oid: self._toggle(self.hidden_ids, oid)
        tl.on_toggle_locked = lambda oid: self._toggle(self.locked_ids, oid)
        tl.on_rename = self._rename_object
        tl.on_move_layer = self._move_layer
        tl.on_context_menu = self._timeline_context_menu

        ins = self.inspector
        ins.on_scene_change = self._on_scene_field
        ins.on_object_change = self._on_object_field
        ins.on_transform_change = self._on_transform_field
        ins.on_toggle_key = self.toggle_key_at_playhead
        ins.on_easing_change = self._on_easing
        ins.on_swap_change = self._on_swap_field
        ins.on_reset_handles = self._reset_handles

    # ================================================================== main-window interface
    def get_active_canvas(self):
        return self.stage

    def set_project(self, project: Project) -> None:
        self.stop_playback()
        self.project = project
        self.stage.set_project(project)
        self.library.set_project(project)
        self.selected_scene_id = None
        self.selected_object_id = None
        self.selection = {}
        self.hidden_ids.clear()
        self.locked_ids.clear()
        self.collapsed_ids.clear()
        self._tick_cache.clear()
        self.frame = 0
        self.refresh_scenes()

    def refresh_after_history(self) -> None:
        self._tick_cache.clear()
        self.stage.clear_cache()
        self.library.refresh()
        self.refresh_scenes()

    def on_tab_activated(self) -> None:
        self.library.refresh()
        self.refresh_scenes()

    def on_active_mapping_changed(self) -> None:
        self.library.refresh()
        self.refresh(timeline=False)  # the stage, and the inspector's "Inherit (preview: …)"

    def stop_playback(self) -> None:
        if self.is_playing:
            self.toggle_play()

    # ================================================================== helpers
    def scene(self) -> Optional[TimelineScene]:
        return self.project.get_timeline_scene(self.selected_scene_id) if self.selected_scene_id else None

    def obj(self) -> Optional[TimelineObject]:
        scene = self.scene()
        return scene.get_object(self.selected_object_id) if scene and self.selected_object_id else None

    def _length(self) -> int:
        scene = self.scene()
        return ops.scene_length_frames(scene) if scene else 0

    def _commit(self) -> None:
        """An edit finished: refresh everything and mark an undo step."""
        self.refresh()
        app_services.request_checkpoint()

    def _toggle(self, target: Set[str], object_id: str) -> None:
        if object_id in target:
            target.discard(object_id)
        else:
            target.add(object_id)
        self.refresh()

    def _selected_key_count(self) -> int:
        return sum(len(v) for v in self.selection.values())

    def _anim_ticks(self, scene: TimelineScene) -> Dict[str, List[int]]:
        result: Dict[str, List[int]] = {}
        for obj in scene.objects:
            if obj.source_type != "animation" and not any(k.source_type == "animation" for k in obj.keyframes):
                continue
            signature = (
                obj.source_type, obj.source_id, obj.playback_mode, obj.playback_speed, obj.playback_offset,
                tuple((round(k.time, 6), k.source_type, k.source_id) for k in obj.sorted_keyframes()),
                scene.fps, scene.duration_seconds,
            )
            cached = self._tick_cache.get(obj.id)
            if not cached or cached[0] != signature:
                cached = (signature, ops.animation_frame_changes(self.project, scene, obj))
                self._tick_cache[obj.id] = cached
            result[obj.id] = cached[1]
        return result

    def _source_labels(self, scene: TimelineScene) -> Dict[str, str]:
        labels: Dict[str, str] = {}
        for obj in scene.objects:
            for key in obj.keyframes:
                if key.source_type is not None:
                    labels[key.id] = ops.source_name(self.project, key.source_type, key.source_id)
        return labels

    # ================================================================== refresh
    def refresh_scenes(self, select_id: Optional[str] = None) -> None:
        scenes = self.project.timeline_scenes
        target = select_id or self.selected_scene_id
        if not any(s.id == target for s in scenes):
            target = scenes[0].id if scenes else None
        self._scene_ids = [s.id for s in scenes]
        self.scene_choice.SetItems([s.name for s in scenes] or ["(no scenes)"])
        self.scene_choice.SetSelection(self._scene_ids.index(target) if target in self._scene_ids else 0)
        self.scene_choice.Enable(bool(scenes))
        self.btn_scene_dup.Enable(bool(scenes))
        self.btn_scene_del.Enable(bool(scenes))
        if target != self.selected_scene_id:
            self.selected_scene_id = target
            self.selected_object_id = None
            self.selection = {}
            self.frame = 0
            self._fitted_scene_id = None
        self.refresh()
        if self._fitted_scene_id != self.selected_scene_id:
            wx.CallAfter(self._fit_views)

    def _fit_views(self) -> None:
        """Fit stage and timeline once per scene, as soon as they have a real size."""
        if not self or self._fitted_scene_id == self.selected_scene_id:
            return
        if self.timeline.GetClientSize().width < self.timeline.left_w + 60 or not self.IsShownOnScreen():
            return  # retried from on_tab_activated / the next refresh_scenes
        self.refresh()
        self.timeline.fit_scene()
        self.stage.fit_to_content()
        self._fitted_scene_id = self.selected_scene_id

    def refresh(self, stage: bool = True, timeline: bool = True, inspector: bool = True) -> None:
        scene = self.scene()
        if scene:
            self.frame = max(0, min(self.frame, ops.scene_length_frames(scene)))
            valid = {o.id for o in scene.objects}
            if self.selected_object_id not in valid:
                self.selected_object_id = None
            self.selection = {
                oid: {k.id for k in scene.get_object(oid).keyframes if k.id in ids}
                for oid, ids in self.selection.items()
                if oid in valid
            }
            self.selection = {k: v for k, v in self.selection.items() if v}
        else:
            self.frame = 0
            self.selected_object_id = None
            self.selection = {}
        key_ids = set().union(*self.selection.values()) if self.selection else set()
        time_value = ops.time_of(self.frame, scene.fps) if scene else 0.0
        if stage:
            self.stage.set_view(scene, time_value, self.selected_object_id, key_ids, self.hidden_ids, self.locked_ids)
        if timeline:
            rows = ops.tree_rows(scene, self.collapsed_ids)
            self.timeline.set_data(
                scene, rows, self.frame, self.selected_object_id, self.selection,
                self.hidden_ids, self.locked_ids, self.collapsed_ids,
                self._anim_ticks(scene) if scene else {}, self._source_labels(scene) if scene else {},
            )
            self.timeline_view.sync_scrollbars()
        if inspector:
            obj = self.obj()
            self.inspector.show_context(
                self.project, scene, obj, self.frame, self.auto_key, self._selected_key_count(),
                self.selection.get(obj.id) if obj else None,
            )
        self._update_transport()

    def _update_transport(self) -> None:
        scene = self.scene()
        length = self._length()
        self.frame_spin.SetRange(0, max(0, length))
        if self.frame_spin.GetValue() != self.frame:
            self.frame_spin.SetValue(self.frame)
        if scene:
            self.frame_info.SetLabel(f"/ {length}   {self.frame / float(scene.fps):.2f} s @ {scene.fps} fps")
            self.chk_loop.SetValue(scene.loop)
        else:
            self.frame_info.SetLabel("")
        has_obj = self.obj() is not None
        self.btn_add_key.Enable(has_obj)
        self.btn_del.Enable(has_obj or bool(self.selection))
        for ctrl in (self.btn_first, self.btn_prev, self.btn_play, self.btn_next, self.btn_last,
                     self.btn_prev_key, self.btn_next_key, self.frame_spin, self.chk_loop, self.btn_group):
            ctrl.Enable(scene is not None)
        self.btn_play.SetLabel("❚❚" if self.is_playing else "▶")

    def _update_autokey_button(self) -> None:
        self.btn_autokey.SetValue(self.auto_key)
        self.btn_autokey.SetForegroundColour(wx.Colour(230, 70, 70) if self.auto_key else wx.NullColour)
        self.btn_autokey.SetLabel("● Auto-Key" if self.auto_key else "○ Auto-Key")

    # ================================================================== scenes
    def _on_scene_choice(self, _event: wx.CommandEvent) -> None:
        idx = self.scene_choice.GetSelection()
        if 0 <= idx < len(self._scene_ids):
            self.stop_playback()
            self.refresh_scenes(self._scene_ids[idx])

    def new_scene(self) -> None:
        scene = self.project.create_timeline_scene(f"Scene {len(self.project.timeline_scenes) + 1}")
        scene.fps = 60
        scene.duration_seconds = 2.0
        self.refresh_scenes(scene.id)
        app_services.request_checkpoint()

    def duplicate_scene(self) -> None:
        scene = self.scene()
        if not scene:
            return
        copy = scene.clone()
        copy.id = generate_id("scene")
        copy.name = f"{scene.name} copy"
        self.project.timeline_scenes.insert(self.project.timeline_scenes.index(scene) + 1, copy)
        self.refresh_scenes(copy.id)
        app_services.request_checkpoint()

    def delete_scene(self) -> None:
        scene = self.scene()
        if not scene:
            return
        msg = f"Delete scene '{scene.name}' with {len(scene.objects)} layer(s)? (Undo with Ctrl/Cmd+Z.)"
        if wx.MessageBox(msg, "Delete Scene", wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
            return
        self.stop_playback()
        self.project.timeline_scenes = [s for s in self.project.timeline_scenes if s.id != scene.id]
        self.selected_scene_id = None
        self.refresh_scenes()
        app_services.request_checkpoint()

    def _on_scene_field(self, field: str, value: Any) -> None:
        scene = self.scene()
        if not scene:
            return
        if field == "name" and value:
            scene.name = str(value)
            self.refresh_scenes(scene.id)
        elif field == "fps":
            ops.set_scene_fps(scene, int(value))
        elif field == "length":
            ops.set_scene_length_frames(scene, int(value))
        elif field == "loop":
            scene.loop = bool(value)
        elif field == "background":
            scene.background_color = tuple(int(v) for v in value)[:3]  # type: ignore[assignment]
        self._commit()

    def _on_screen_choice(self, _event: wx.CommandEvent) -> None:
        idx = self.screen_choice.GetSelection()
        self.stage.screen_guide = SCREEN_GUIDES[idx][1]
        config = wx.Config.Get()
        config.WriteInt(CONFIG_SCREEN_GUIDE, idx)
        config.Flush()
        self.stage.Refresh(False)

    def _on_loop(self, event: wx.CommandEvent) -> None:
        scene = self.scene()
        if scene:
            scene.loop = event.IsChecked()
            self._commit()

    # ================================================================== selection & time
    def select_object(self, object_id: Optional[str]) -> None:
        self.selected_object_id = object_id
        if object_id:
            self.selection = {k: v for k, v in self.selection.items() if k == object_id}
            self.timeline.ensure_row_visible(object_id)
        else:
            self.selection = {}
        self.refresh()

    def set_key_selection(self, selection: Selection, live: bool = False) -> None:
        self.selection = {k: set(v) for k, v in selection.items() if v}
        if len(self.selection) == 1:
            self.selected_object_id = next(iter(self.selection))
        self.refresh(inspector=not live)

    def seek(self, frame: int) -> None:
        self.frame = max(0, min(int(frame), self._length()))
        self.timeline.ensure_frame_visible(self.frame)
        self.refresh()

    def step(self, delta: int) -> None:
        length = self._length()
        scene = self.scene()
        target = self.frame + delta
        if scene and scene.loop and length:
            target %= length + 1
        self.seek(target)

    def jump_key(self, direction: int) -> None:
        scene = self.scene()
        if not scene:
            return
        target = ops.neighbour_key_frame(scene, self.obj(), self.frame, direction)
        if target is not None:
            self.seek(target)

    def toggle_play(self) -> None:
        scene = self.scene()
        if self.is_playing or not scene:
            self.is_playing = False
            self.timer.Stop()
        else:
            if self.frame >= self._length():
                self.frame = 0
            self.is_playing = True
            self._play_start = (time.monotonic(), self.frame)
            self._frame_time = time.monotonic()
            self._arm_timer_when_idle = True
        self._update_transport()

    @staticmethod
    def _play_interval(scene: TimelineScene) -> int:
        return max(8, int(1000 / max(1, scene.fps) / 2))

    def _on_timer(self, _event: wx.TimerEvent) -> None:
        self._frame_time = time.monotonic()
        self._play_frame()
        # One-shot, armed again once this frame has been drawn (see animation_editor.panel.PLAY_INTERVAL_MS).
        self._arm_timer_when_idle = self.is_playing

    def _on_idle(self, event: wx.IdleEvent) -> None:
        event.Skip()
        if self._arm_timer_when_idle:
            self._arm_timer_when_idle = False
            scene = self.scene()
            if self.is_playing and scene:
                spent = int((time.monotonic() - self._frame_time) * 1000)
                self.timer.StartOnce(max(1, self._play_interval(scene) - spent))

    def _play_frame(self) -> None:
        scene = self.scene()
        if not scene:
            self.stop_playback()
            return
        start_time, start_frame = self._play_start
        length = ops.scene_length_frames(scene)
        frame = start_frame + int((time.monotonic() - start_time) * scene.fps)
        if frame > length:
            if scene.loop:
                frame %= length + 1
            else:
                frame = length
                self.is_playing = False
                self.timer.Stop()
        if frame != self.frame or not self.is_playing:
            self.frame = frame
            self.timeline.ensure_frame_visible(frame)
            self.refresh(inspector=not self.is_playing)

    # ================================================================== objects
    def add_object(self, source_type: str, source_id: Optional[str], position: Optional[Tuple[float, float]] = None) -> None:
        scene = self.scene()
        if not scene:
            self.new_scene()
            scene = self.scene()
        if position is None:
            size = self.stage.GetClientSize()
            cx, cy = self.stage.screen_to_world(wx.Point(size.width // 2, size.height // 2))
            position = (round(cx), round(cy))
        obj = ops.add_object(self.project, scene, source_type, source_id, self.frame, position)
        self.selected_object_id = obj.id
        self.selection = {}
        self._commit()
        self.timeline.ensure_row_visible(obj.id)
        app_services.show_status(f"Added '{obj.name}' at frame {self.frame}")

    def _rename_object(self, object_id: str, name: str) -> None:
        scene = self.scene()
        obj = scene.get_object(object_id) if scene else None
        if obj and name:
            obj.name = name
            self._commit()

    def _move_layer(self, object_id: str, parent_id: Optional[str], before_id: Optional[str]) -> None:
        scene = self.scene()
        if scene and ops.move_layer(self.project, scene, object_id, parent_id, before_id):
            if parent_id:
                self.collapsed_ids.discard(parent_id)
            self.selected_object_id = object_id
            self._commit()

    def delete_selection(self) -> None:
        scene = self.scene()
        if not scene:
            return
        if self.selection:
            removed = 0
            for obj_id, key_ids in self.selection.items():
                obj = scene.get_object(obj_id)
                if obj:
                    removed += ops.delete_keys(obj, key_ids)
            self.selection = {}
            self._commit()
            app_services.show_status(f"Deleted {removed} key(s)")
            return
        obj = self.obj()
        if obj:
            name = obj.name
            ops.delete_object(self.project, scene, obj.id)
            self.selected_object_id = None
            self._commit()
            app_services.show_status(f"Deleted layer '{name}'")

    def duplicate_selected_object(self) -> None:
        scene, obj = self.scene(), self.obj()
        if scene and obj:
            copy = ops.duplicate_object(scene, obj.id)
            if copy:
                self.selected_object_id = copy.id
                self._commit()

    # ================================================================== keys
    def add_key_at_playhead(self) -> None:
        scene, obj = self.scene(), self.obj()
        if scene and obj:
            key = ops.ensure_key(self.project, scene, obj, self.frame)
            self.selection = {obj.id: {key.id}}
            self._commit()

    def _key_here(self, obj: TimelineObject) -> Optional[TimelineKeyframe]:
        scene = self.scene()
        if not scene:
            return None
        return ops.key_at_frame(obj, self.frame, scene.fps, self.selection.get(obj.id))

    def toggle_key_at_playhead(self) -> None:
        scene, obj = self.scene(), self.obj()
        if not scene or not obj:
            return
        key = self._key_here(obj)
        if key:
            if len(obj.keyframes) == 1:
                app_services.show_status("A layer needs at least one key")
                self.refresh()
                return
            ops.delete_keys(obj, [key.id])
            self.selection.get(obj.id, set()).discard(key.id)
            self._commit()
        else:
            self.add_key_at_playhead()

    def _timeline_add_key(self, object_id: str, frame: int) -> None:
        scene = self.scene()
        obj = scene.get_object(object_id) if scene else None
        if not obj:
            return
        self.frame = frame
        key = ops.ensure_key(self.project, scene, obj, frame)
        self.selected_object_id = obj.id
        self.selection = {obj.id: {key.id}}
        self._commit()

    def _timeline_move_keys(self, delta: int, origins: Dict[Tuple[str, str], int]) -> int:
        scene = self.scene()
        if not scene:
            return 0
        applied = ops.move_keys(scene, self.selection, delta, origins)
        self.refresh(inspector=False)
        return applied

    # ================================================================== editing the pose
    def _apply_pose_change(self, obj: TimelineObject, field: str, value: Any) -> None:
        """Auto-Key on (or a key at the playhead): edit that key. Off between keys: edit every key."""
        scene = self.scene()
        fps = scene.fps
        key = self._key_here(obj)
        if key is None and self.auto_key:
            key = ops.ensure_key(self.project, scene, obj, self.frame)
        targets = [key] if key else list(obj.keyframes)
        state = scene.evaluate_object_state(self.project, obj.id, ops.time_of(self.frame, fps)) or {}
        for target in targets:
            if field in ("x", "y"):
                current = float(state.get(field, 0.0))
                if key:
                    setattr(target, field, float(value))
                else:
                    setattr(target, field, getattr(target, field) + float(value) - current)
            elif field == "rotate":
                target.rotation_degrees = float(int(round((target.rotation_degrees + float(value)) / 90.0)) * 90)
            elif field in ("flip_x", "flip_y", "visible"):
                setattr(target, field, bool(value))
        if key:
            self.selection = {obj.id: {key.id}}

    def _on_transform_field(self, field: str, value: Any) -> None:
        obj = self.obj()
        if obj and obj.id not in self.locked_ids:
            self._apply_pose_change(obj, field, value)
            self._commit()

    def flip_selected(self, axis: str) -> None:
        scene, obj = self.scene(), self.obj()
        if not scene or not obj or obj.id in self.locked_ids:
            return
        state = scene.evaluate_object_state(self.project, obj.id, ops.time_of(self.frame, scene.fps)) or {}
        field = "flip_x" if axis == "x" else "flip_y"
        self._apply_pose_change(obj, field, not bool(state.get(field, False)))
        self._commit()

    def rotate_selected(self, degrees: int) -> None:
        obj = self.obj()
        if obj and obj.id not in self.locked_ids:
            self._apply_pose_change(obj, "rotate", degrees)
            self._commit()

    def nudge_selected(self, dx: int, dy: int) -> None:
        scene, obj = self.scene(), self.obj()
        if not scene or not obj or obj.id in self.locked_ids:
            return
        state = scene.evaluate_object_state(self.project, obj.id, ops.time_of(self.frame, scene.fps)) or {}
        if dx:
            self._apply_pose_change(obj, "x", round(float(state.get("x", 0.0))) + dx)
        if dy:
            self._apply_pose_change(obj, "y", round(float(state.get("y", 0.0))) + dy)
        self.refresh()

    # ---- stage drags
    def _stage_drag_begin(self, object_id: str) -> None:
        scene = self.scene()
        obj = scene.get_object(object_id) if scene else None
        if not obj:
            self._drag = {}
            return
        time_value = ops.time_of(self.frame, scene.fps)
        parent = ops.parent_world_matrix(self.project, scene, obj, time_value)
        # Nothing changes until the mouse actually moves (a click only selects).
        self._drag = {"object_id": obj.id, "parent": parent, "bases": None, "moved": False}

    def _stage_drag(self, object_id: str, dx: float, dy: float) -> None:
        scene = self.scene()
        if not scene or self._drag.get("object_id") != object_id:
            return
        obj = scene.get_object(object_id)
        lx, ly = ops.world_to_parent_delta(self._drag["parent"], dx, dy)
        lx, ly = round(lx), round(ly)
        if self._drag["bases"] is None:
            if not (lx or ly):
                return
            key = self._key_here(obj)
            if key is None and self.auto_key:
                key = ops.ensure_key(self.project, scene, obj, self.frame)
            self._drag["bases"] = {k.id: (k.x, k.y) for k in ([key] if key else obj.keyframes)}
            if key:
                self.selection = {obj.id: {key.id}}
        for key in obj.keyframes:
            base = self._drag["bases"].get(key.id)
            if base:
                key.x, key.y = float(base[0] + lx), float(base[1] + ly)
        self._drag["moved"] = self._drag["moved"] or bool(lx or ly)
        self.refresh(inspector=False)

    def _stage_drag_end(self) -> None:
        moved = bool(self._drag.get("moved"))
        self._drag = {}
        if moved:
            self._commit()
        else:
            self.refresh()

    def _stage_key_drag_begin(self, object_id: str, key_id: str) -> None:
        scene = self.scene()
        obj = scene.get_object(object_id) if scene else None
        key = next((k for k in obj.keyframes if k.id == key_id), None) if obj else None
        if not key:
            self._drag = {}
            return
        self.frame = ops.frame_of(key.time, scene.fps)
        parent = ops.parent_world_matrix(self.project, scene, obj, key.time)
        self._drag = {"object_id": object_id, "key_id": key_id, "parent": parent, "base": (key.x, key.y)}
        self.selection = {object_id: {key_id}}
        self.refresh()

    def _stage_key_drag(self, object_id: str, key_id: str, dx: float, dy: float) -> None:
        scene = self.scene()
        if not scene or self._drag.get("key_id") != key_id:
            return
        obj = scene.get_object(object_id)
        key = next((k for k in obj.keyframes if k.id == key_id), None)
        if not key:
            return
        lx, ly = ops.world_to_parent_delta(self._drag["parent"], dx, dy)
        bx, by = self._drag["base"]
        key.x, key.y = float(round(bx + lx)), float(round(by + ly))
        self.refresh(inspector=False)

    def _stage_handle_drag_begin(self, object_id: str, key_id: str, kind: str) -> None:
        scene = self.scene()
        obj = scene.get_object(object_id) if scene else None
        keys = obj.sorted_keyframes() if obj else []
        index = next((i for i, k in enumerate(keys) if k.id == key_id), -1)
        if index < 0:
            self._drag = {}
            return
        key = keys[index]
        auto_in, auto_out = StageCanvas._auto_handles(keys, index)
        explicit = key.path_in if kind == "in" else key.path_out
        base = tuple(explicit) if explicit is not None else (auto_in if kind == "in" else auto_out)
        if base is None:
            self._drag = {}
            return
        parent = ops.parent_world_matrix(self.project, scene, obj, key.time)
        self._drag = {"object_id": object_id, "key_id": key_id, "kind": kind, "parent": parent, "base": base}

    def _stage_handle_drag(self, object_id: str, key_id: str, kind: str, dx: float, dy: float) -> None:
        scene = self.scene()
        if not scene or self._drag.get("key_id") != key_id or self._drag.get("kind") != kind:
            return
        obj = scene.get_object(object_id)
        key = next((k for k in obj.keyframes if k.id == key_id), None)
        if not key:
            return
        lx, ly = ops.world_to_parent_delta(self._drag["parent"], dx, dy)
        bx, by = self._drag["base"]
        point = (float(bx + lx), float(by + ly))
        if kind == "in":
            key.path_in = point
        else:
            key.path_out = point
        self.refresh(inspector=False)

    def _reset_handles(self) -> None:
        scene, obj = self.scene(), self.obj()
        key = self._key_here(obj) if scene and obj else None
        if key:
            key.path_in = None
            key.path_out = None
            self._commit()

    # ---- inspector edits
    def _on_object_field(self, field: str, value: Any) -> None:
        scene, obj = self.scene(), self.obj()
        if not scene or not obj:
            return
        if field == "name" and value:
            obj.name = str(value)
        elif field == "source":
            obj.source_type, obj.source_id = value
            if obj.source_type == "none":
                obj.source_id = None
        elif field == "parent":
            if not ops.move_layer(self.project, scene, obj.id, value, None):
                self.refresh()
                return
            if value:
                self.collapsed_ids.discard(value)
        elif field == "playback_mode":
            obj.playback_mode = str(value)
        elif field == "playback_speed":
            obj.playback_speed = max(0.05, float(value))
        elif field == "playback_offset_frames":
            obj.playback_offset = ops.time_of(int(value), scene.fps)
        elif field == "root_motion":
            obj.use_source_root_motion = bool(value)
        elif field == "mapping":
            obj.mapping_id = value or None
        elif field == "path_mode":
            obj.path_mode = str(value)
        self._commit()

    def _on_easing(self, easing: str) -> None:
        scene, obj = self.scene(), self.obj()
        if not scene:
            return
        changed = 0
        if self._selected_key_count() > 1:
            for obj_id, key_ids in self.selection.items():
                target = scene.get_object(obj_id)
                for key_id in key_ids:
                    changed += bool(target and ops.set_segment_easing(target, key_id, easing))
        elif obj:
            start = self._key_here(obj) or ops.key_before_or_at(obj, self.frame, scene.fps)
            changed += bool(start and ops.set_segment_easing(obj, start.id, easing))
        if changed:
            self._commit()

    def _on_swap_field(self, field: str, value: Any) -> None:
        scene, obj = self.scene(), self.obj()
        key = self._key_here(obj) if scene and obj else None
        if not key:
            return
        if field == "source":
            if value is None:
                key.source_type, key.source_id = None, None
            else:
                key.source_type, key.source_id = value
                if key.source_type == "none":
                    key.source_id = None
        elif field == "offset":
            key.source_offset = (float(value[0]), float(value[1]))
        self._commit()

    # ================================================================== context menus
    def _easing_menu(self, apply: Callable[[str], None]) -> wx.Menu:
        menu = wx.Menu()
        for label, easing in QUICK_EASINGS:
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda e, name=easing: apply(name), item)
        return menu

    def _menu_item(self, menu: wx.Menu, label: str, handler: Callable[[], None], enabled: bool = True) -> None:
        item = menu.Append(wx.ID_ANY, label)
        item.Enable(enabled)
        self.Bind(wx.EVT_MENU, lambda e: handler(), item)

    def _timeline_context_menu(self, kind: str, object_id: Optional[str], key_id: Optional[str], frame: int, pos: wx.Point) -> None:
        scene = self.scene()
        if not scene:
            return
        obj = scene.get_object(object_id) if object_id else None
        menu = wx.Menu()
        if kind == "key" and obj and key_id:
            def apply_easing(name: str) -> None:
                for oid, ids in self.selection.items():
                    target = scene.get_object(oid)
                    for kid in ids:
                        if target:
                            ops.set_segment_easing(target, kid, name)
                self._commit()

            menu.AppendSubMenu(self._easing_menu(apply_easing), "Motion to Next Key")
            menu.AppendSeparator()
            self._menu_item(menu, "Copy Keys", self.edit_copy)
            self._menu_item(menu, f"Paste Keys at Frame {self.frame}", self.edit_paste, bool(_KEY_CLIPBOARD))
            menu.AppendSeparator()
            self._menu_item(menu, "Delete Keys", self.delete_selection)
        elif kind == "segment" and obj and key_id:
            def apply_segment(name: str) -> None:
                ops.set_segment_easing(obj, key_id, name)
                self._commit()

            current = ops.segment_easing(obj, key_id) or "linear"
            menu.AppendSubMenu(self._easing_menu(apply_segment), f"Motion: {ops.easing_label(current)}")
            menu.AppendSeparator()
            self._menu_item(menu, f"Add Key at Frame {frame}", lambda: self._timeline_add_key(obj.id, frame))
        elif kind == "track" and obj:
            self.seek(frame)
            self._menu_item(menu, f"Add Key at Frame {frame}", lambda: self._timeline_add_key(obj.id, frame))
            self._menu_item(menu, f"Paste Keys at Frame {frame}", self.edit_paste, bool(_KEY_CLIPBOARD))
        elif kind == "layer" and obj:
            self._layer_menu(menu, obj)
        else:
            self._menu_item(menu, "Add Group", lambda: self.add_object("none", None))
        self.timeline.PopupMenu(menu, pos)
        menu.Destroy()

    def _layer_menu(self, menu: wx.Menu, obj: TimelineObject) -> None:
        scene = self.scene()
        self._menu_item(menu, "Duplicate", self.duplicate_selected_object)
        self._menu_item(menu, "Delete", lambda: (self.selection.clear(), self.delete_selection()))
        menu.AppendSeparator()
        self._menu_item(menu, "Bring Forward", lambda: self._step_layer(obj.id, +1))
        self._menu_item(menu, "Send Backward", lambda: self._step_layer(obj.id, -1))
        if obj.parent_id:
            self._menu_item(menu, "Unparent (keep position)", lambda: self._move_layer(obj.id, None, None))
        menu.AppendSeparator()
        self._menu_item(menu, "Show" if obj.id in self.hidden_ids else "Hide", lambda: self._toggle(self.hidden_ids, obj.id))
        self._menu_item(menu, "Unlock" if obj.id in self.locked_ids else "Lock", lambda: self._toggle(self.locked_ids, obj.id))
        if scene and obj.source_type == "frame" and obj.source_id:
            menu.AppendSeparator()
            self._menu_item(menu, "Edit Frame in Frames Tab", lambda: self._edit_frame(obj.source_id))

    def _edit_frame(self, frame_id: str) -> None:
        top = wx.GetTopLevelParent(self)
        switch = getattr(top, "switch_to_frame_editor", None)
        if switch:
            switch(frame_id)

    def _step_layer(self, object_id: str, direction: int) -> None:
        scene = self.scene()
        if scene and ops.step_layer(self.project, scene, object_id, direction):
            self._commit()

    def _stage_context_menu(self, object_id: Optional[str], pos: wx.Point) -> None:
        scene = self.scene()
        if not scene:
            return
        menu = wx.Menu()
        obj = scene.get_object(object_id) if object_id else None
        if obj:
            self._menu_item(menu, "Flip Horizontal\tH", lambda: self.flip_selected("x"))
            self._menu_item(menu, "Flip Vertical\tV", lambda: self.flip_selected("y"))
            self._menu_item(menu, "Rotate 90° CW\tR", lambda: self.rotate_selected(90))
            self._menu_item(menu, "Rotate 90° CCW\tShift+R", lambda: self.rotate_selected(-90))
            menu.AppendSeparator()
            self._menu_item(menu, f"Add Key at Frame {self.frame}\tK", self.add_key_at_playhead)
            menu.AppendSeparator()
            self._layer_menu(menu, obj)
        else:
            world = self.stage.screen_to_world(pos)
            self._menu_item(menu, "Add Group Here", lambda: self.add_object("none", None, (round(world[0]), round(world[1]))))
            self._menu_item(menu, "Scene Settings", lambda: self.select_object(None))
        self.stage.PopupMenu(menu, pos)
        menu.Destroy()

    # ================================================================== keyboard
    def _on_autokey(self, event: wx.CommandEvent) -> None:
        self.auto_key = event.IsChecked()
        self._update_autokey_button()
        self.refresh(stage=False, timeline=False)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if not self.IsShownOnScreen() or app_services.text_entry_has_focus():
            event.Skip()
            return
        if event.CmdDown() or event.ControlDown() or event.AltDown():
            event.Skip()
            return
        code = event.GetKeyCode()
        shift = event.ShiftDown()
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.toggle_play()
        elif code in (ord(","), ord("<")):
            self.jump_key(-1) if shift else self.step(-1)
        elif code in (ord("."), ord(">")):
            self.jump_key(1) if shift else self.step(1)
        elif code == wx.WXK_HOME:
            self.seek(0)
        elif code == wx.WXK_END:
            self.seek(self._length())
        elif code == ord("K"):
            self.toggle_key_at_playhead() if shift else self.add_key_at_playhead()
        elif code == ord("H"):
            self.flip_selected("x")
        elif code == ord("V"):
            self.flip_selected("y")
        elif code == ord("R"):
            self.rotate_selected(-90 if shift else 90)
        elif code in (wx.WXK_DELETE, wx.WXK_BACK):
            self.delete_selection()
        elif code == wx.WXK_ESCAPE:
            self.selection = {}
            self.refresh()
        elif code in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN) and wx.Window.FindFocus() is self.stage:
            step = 8 if shift else 1
            self.nudge_selected(
                {wx.WXK_LEFT: -step, wx.WXK_RIGHT: step}.get(code, 0),
                {wx.WXK_UP: -step, wx.WXK_DOWN: step}.get(code, 0),
            )
            app_services.request_checkpoint()
        elif code in (wx.WXK_LEFT, wx.WXK_RIGHT) and wx.Window.FindFocus() is self.timeline:
            self.step(-1 if code == wx.WXK_LEFT else 1)
        else:
            event.Skip()

    # ================================================================== edit menu
    def edit_copy(self) -> None:
        scene, obj = self.scene(), self.obj()
        if not scene:
            return
        if self.selection:
            _KEY_CLIPBOARD[:] = ops.copy_keys(scene, self.selection)
            app_services.show_status(f"Copied {len(_KEY_CLIPBOARD)} key(s)")
        elif obj:
            subtree: List[TimelineObject] = []

            def collect(o: TimelineObject) -> None:
                subtree.append(o)
                for child in ops.children_of(scene, o.id):
                    collect(child)

            collect(obj)
            _OBJECT_CLIPBOARD[:] = [o.to_dict() for o in subtree]
            app_services.show_status(f"Copied layer '{obj.name}'")

    def edit_cut(self) -> None:
        self.edit_copy()
        self.delete_selection()

    def edit_paste(self) -> None:
        scene = self.scene()
        if not scene:
            return
        if _KEY_CLIPBOARD and (self.selection or self.obj()):
            pasted = ops.paste_keys(scene, list(_KEY_CLIPBOARD), self.frame, self.selected_object_id)
            if pasted:
                self.selection = pasted
                self._commit()
            return
        if _OBJECT_CLIPBOARD:
            id_map = {data["id"]: generate_id("tlo") for data in _OBJECT_CLIPBOARD}
            new_root = None
            for data in _OBJECT_CLIPBOARD:
                clone = TimelineObject.from_dict(dict(data))
                clone.id = id_map[data["id"]]
                clone.parent_id = id_map.get(data.get("parent_id")) if data.get("parent_id") in id_map else None
                for key in clone.keyframes:
                    key.id = generate_id("tlk")
                if new_root is None:
                    new_root = clone
                    clone.name = f"{clone.name} copy"
                    clone.draw_order = 10**6
                scene.objects.append(clone)
            ops.normalize_draw_order(scene)
            self.selected_object_id = new_root.id if new_root else None
            self.selection = {}
            self._commit()

    def edit_duplicate(self) -> None:
        self.duplicate_selected_object()

    def edit_select_all(self) -> None:
        scene, obj = self.scene(), self.obj()
        if not scene:
            return
        targets = [obj] if obj else scene.objects
        self.selection = {o.id: {k.id for k in o.keyframes} for o in targets}
        self.refresh()
