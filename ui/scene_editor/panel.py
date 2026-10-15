"""Scene editor tab: Library | Stage | Inspector on top, layers + dopesheet timeline below."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import wx

from models import Project, TimelineKeyframe, TimelineObject, TimelineScene, generate_id
from ui import app_services, view_memory
from ui.base_canvas import BACKDROP_COLOUR
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.components.inspector_kit import fit_choice
from ui.components.thumb_list import Browser, Row
from ui.frame_render import fit_bitmap, mapping_key, swap_key
from ui.scene_editor import ops
from ui.scene_editor.inspector import SceneInspector
from ui.scene_editor.library import SceneLibrary
from ui.scene_editor.stage import SCREEN_GUIDES, StageCanvas, project_screen
from ui.scene_editor.thumbnails import scene_image
from ui.scene_editor.timeline import TimelineView
from ui.dpi import px
from ui.components.split_memory import split_bottom_remembered
from ui.refresh_rate import REFRESH

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
_PASTE_KIND = ["keys"]  # what Paste pastes: what was copied last ("keys" or "layers")
# Inspector fields that change every selected layer when several are selected.
GROUP_FIELDS = ("playback_mode", "playback_speed", "root_motion", "mapping", "palette_swap")

CONFIG_SCREEN_GUIDE = "SceneEditor/ScreenGuide"  # up to format 7: a position in SCREEN_GUIDES
CONFIG_SCREEN = "SceneEditor/Screen"  # "" (none), "project" (the project's console) or a screen's label to compare
PROJECT_SCREEN = "project"


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
        self.selected_object_id: Optional[str] = None  # the layer the inspector shows (the last one clicked)
        self.selected_object_ids: List[str] = []  # every selected layer, that one last
        self.selection: Selection = {}
        self.frame = 0
        self.auto_key = True
        self.is_playing = False
        self.hidden_ids: Set[str] = set()
        self.locked_ids: Set[str] = set()
        self.collapsed_ids: Set[str] = set()
        self._scene_thumbs: Dict[str, Tuple[Any, wx.Bitmap]] = {}
        self._tick_cache: Dict[str, Tuple[Any, List[int]]] = {}
        self._drag: Dict[str, Any] = {}
        self._play_start: Tuple[float, int] = (0.0, 0)
        self._fitted_scene_id: Optional[str] = None
        self._remembered_view: Optional[Tuple[str, view_memory.View]] = None  # shown instead of the first fit
        self.timer = wx.Timer(self)
        self._arm_timer_when_idle = False  # see _on_timer
        self._frame_time = 0.0  # when the last playback frame started

        self._build_ui()
        self._bind()
        self.refresh_scenes()

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)

        self.vsplit = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        top = wx.Panel(self.vsplit)
        self.outer_split = wx.SplitterWindow(top, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        # The left column: the scenes (a list like the other tabs') above the library of things to put in them.
        self.left_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.scene_browser = Browser(self.left_split, "Scenes", row_h=44, thumb=40, reorder=True, filter_hint="Filter scenes")
        self.btn_scene_add = self.scene_browser.add_button("+ New", "New scene", self.new_scene)
        self.btn_scene_dup = self.scene_browser.add_button("Duplicate", "Duplicate the selected scene", self.duplicate_scene)
        self.btn_scene_del = self.scene_browser.add_button("Delete", "Delete the selected scene", self.delete_scene)
        self.scene_browser.list.SetToolTip("Click a scene to show it and its settings (frame rate, length, background) in "
                                           "the inspector. Double-click or F2 renames, drag to reorder.")
        self.library = SceneLibrary(self.left_split, self.project)
        self.left_split.SplitHorizontally(self.scene_browser, self.library, px(200))
        self.left_split.SetMinimumPaneSize(px(110))
        self.inner_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)

        stage_panel = wx.Panel(self.inner_split)
        stage_sizer = wx.BoxSizer(wx.VERTICAL)
        self.stage = StageCanvas(stage_panel, self.project)
        self.stage.SetDropTarget(_StageDropTarget(self))
        self.canvas_controls = CanvasDisplayControls(
            stage_panel, self.stage, view_key="timeline", default_backdrop=BACKDROP_COLOUR,
            scene_backdrop=True, part_bounds=True, budget=True,
        )
        self.screen_choice = wx.Choice(self.canvas_controls, choices=[f"Compare: {label}" for label, _ in SCREEN_GUIDES])
        self.screen_choice.SetToolTip(
            "Outline of a console screen, placed like the SGDK demo shows scenes: the scene origin centred, three "
            "quarters down. The first is the project's console (Console, above the tabs); Compare shows another one."
        )
        fit_choice(self.screen_choice)  # macOS sizes a Choice for its current item: room for the longest label
        self.screen_value = ""
        self.canvas_controls.add_control(self.screen_choice, "Screen")
        stage_sizer.Add(self.stage, 1, wx.EXPAND | wx.ALL, 2)
        stage_sizer.Add(self.canvas_controls, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        stage_panel.SetSizer(stage_sizer)

        self.inspector = SceneInspector(self.inner_split)
        self.inner_split.SplitVertically(stage_panel, self.inspector, -px(320))
        self.inner_split.SetSashGravity(1.0)
        self.inner_split.SetMinimumPaneSize(px(240))
        self.outer_split.SplitVertically(self.left_split, self.inner_split, px(270))  # like the other tabs: room for the Animations tab label
        self.outer_split.SetMinimumPaneSize(px(180))
        top_sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer.Add(self.outer_split, 1, wx.EXPAND)
        top.SetSizer(top_sizer)

        bottom = wx.Panel(self.vsplit)
        bottom_sizer = wx.BoxSizer(wx.VERTICAL)
        transport = wx.BoxSizer(wx.HORIZONTAL)

        def tbutton(label: str, tip: str, width: int = 34) -> wx.Button:
            btn = wx.Button(bottom, label=label, size=(px(width), -1))
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
        self.frame_spin = wx.SpinCtrl(bottom, min=0, max=100000, initial=0, size=(px(70), -1), style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
        transport.Add(self.frame_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.frame_info = wx.StaticText(bottom, label="", size=(px(190), -1), style=wx.ST_NO_AUTORESIZE)
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

        split_bottom_remembered(self.vsplit, top, bottom, "Timeline/DopesheetHeight", 260)  # as the user dragged it last
        self.vsplit.SetSashGravity(1.0)
        self.vsplit.SetMinimumPaneSize(px(160))
        root.Add(self.vsplit, 1, wx.EXPAND)
        self.SetSizer(root)

        config = wx.Config.Get()
        if config.HasEntry(CONFIG_SCREEN):
            value = config.Read(CONFIG_SCREEN, "")
        else:  # an older editor kept the position in the list
            guide = config.ReadInt(CONFIG_SCREEN_GUIDE, 0)
            value = SCREEN_GUIDES[guide][0] if 0 < guide < len(SCREEN_GUIDES) else ""
        self._set_screen(value, persist=False)
        self._update_autokey_button()

    def _bind(self) -> None:
        scenes = self.scene_browser.list
        scenes.thumbnail = self._scene_thumbnail
        scenes.on_rename = self._rename_scene
        scenes.on_move = self._move_scene
        scenes.Bind(wx.EVT_LISTBOX, lambda e: self._on_scene_row())
        scenes.Bind(wx.EVT_LEFT_UP, self._on_scene_click)
        scenes.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: scenes.begin_rename())
        scenes.Bind(wx.EVT_KEY_DOWN, self._on_scene_key)
        self.scene_browser.search.Bind(wx.EVT_TEXT, lambda e: self.refresh_scenes())
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
        st.on_select_objects = self.select_objects
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
        tl.on_select_objects = self.select_objects
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
        self._remembered_view = None
        self.refresh_scenes()

    def view_state(self) -> Dict[str, Any]:
        """The scene shown, its playhead, the selected layer, the layers hidden, locked or folded and the stage's
        zoom and pan (kept per project)."""
        return {"scene": self.selected_scene_id, "frame": self.frame, "object": self.selected_object_id,
                "hidden": sorted(self.hidden_ids), "locked": sorted(self.locked_ids),
                "collapsed": sorted(self.collapsed_ids), "view": view_memory.canvas_view(self.stage),
                **self.canvas_controls.grid_state()}

    def restore_view_state(self, state: Dict[str, Any]) -> None:
        self.canvas_controls.restore_grid(state)
        objects = {o.id for scene in self.project.timeline_scenes for o in scene.objects}
        for name, kept in (("hidden", self.hidden_ids), ("locked", self.locked_ids), ("collapsed", self.collapsed_ids)):
            kept.clear()
            kept.update(i for i in view_memory.ids(state.get(name)) if i in objects)
        scene_id = view_memory.text(state.get("scene"))
        scene = self.project.get_timeline_scene(scene_id) if scene_id else None
        if scene is None:
            self.refresh()
            return
        view = view_memory.parse_view(state.get("view"))
        self._remembered_view = (scene.id, view) if view else None
        self.refresh_scenes(scene.id)
        if self._fitted_scene_id == scene.id and view:  # fitted already: show the remembered view now
            self._remembered_view = None
            self.stage.set_view_state(*view)
        if isinstance(state.get("frame"), int):
            self.frame = max(0, min(state["frame"], ops.scene_length_frames(scene)))
        object_id = view_memory.text(state.get("object"))
        self.select_object(object_id if object_id and scene.get_object(object_id) else None)

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
                scene.fps, scene.duration_seconds, ops.playback_signature(self.project, obj),
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
        text = self.scene_browser.filter_text()
        shown = [s for s in scenes if not text or text in s.name.lower()]
        self.scene_browser.list.set_rows(
            [Row(s.id, s.name, f"{len(s.objects)} layer{'s' if len(s.objects) != 1 else ''} · "
                               f"{s.duration_in_frames()} frames @ {s.fps} fps") for s in shown],
            [target] if target else [])
        self.scene_browser.set_count(len(shown), len(scenes))
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
        if self.timeline.GetClientSize().width < self.timeline.left_w + px(60) or not self.IsShownOnScreen():
            return  # retried from on_tab_activated / the next refresh_scenes
        self.refresh()
        self.timeline.fit_scene()
        remembered, self._remembered_view = self._remembered_view, None
        if remembered and remembered[0] == self.selected_scene_id:
            self.stage.set_view_state(*remembered[1])  # where the project was left
        else:
            self.stage.fit_to_content()
        self._fitted_scene_id = self.selected_scene_id

    def refresh(self, stage: bool = True, timeline: bool = True, inspector: bool = True) -> None:
        scene = self.scene()
        if scene:
            self.frame = max(0, min(self.frame, ops.scene_length_frames(scene)))
            valid = {o.id for o in scene.objects}
            if self.selected_object_id not in valid:
                self.selected_object_id = None
            ids = [i for i in self.selected_object_ids if i in valid]
            if self.selected_object_id is None:
                ids = []
            elif self.selected_object_id not in ids:  # set on its own (a new layer, a click): it alone
                ids = [self.selected_object_id]
            self.selected_object_ids = ids
            self.selection = {
                oid: {k.id for k in scene.get_object(oid).keyframes if k.id in ids}
                for oid, ids in self.selection.items()
                if oid in valid
            }
            self.selection = {k: v for k, v in self.selection.items() if v}
        else:
            self.frame = 0
            self.selected_object_id = None
            self.selected_object_ids = []
            self.selection = {}
        key_ids = set().union(*self.selection.values()) if self.selection else set()
        time_value = ops.time_of(self.frame, scene.fps) if scene else 0.0
        if stage:
            self.stage.set_view(scene, time_value, self.selected_object_id, key_ids, self.hidden_ids, self.locked_ids,
                                set(self.selected_object_ids))
        if timeline:
            rows = ops.tree_rows(scene, self.collapsed_ids)
            self.timeline.set_data(
                scene, rows, self.frame, self.selected_object_id, self.selection,
                self.hidden_ids, self.locked_ids, self.collapsed_ids,
                self._anim_ticks(scene) if scene else {}, self._source_labels(scene) if scene else {},
                set(self.selected_object_ids),
            )
            self.timeline_view.sync_scrollbars()
        if inspector:
            obj = self.obj()
            self.inspector.show_context(
                self.project, scene, obj, self.frame, self.auto_key, self._selected_key_count(),
                self.selection.get(obj.id) if obj else None, len(self.selected_object_ids),
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
    def _on_scene_row(self) -> None:
        ids = self.scene_browser.list.selected_ids()
        if ids and ids[0] != self.selected_scene_id:
            self.stop_playback()
            self.refresh_scenes(ids[0])
            self.select_object(None)  # the inspector shows the scene's settings

    def _on_scene_click(self, event: wx.MouseEvent) -> None:
        """A click on the scene shown already brings its settings into the inspector."""
        event.Skip()
        if self.scene_browser.list.selected_ids() == [self.selected_scene_id] and self.selected_object_id:
            wx.CallAfter(self.select_object, None)

    def _on_scene_key(self, event: wx.KeyEvent) -> None:
        if self.scene_browser.list.is_renaming():
            event.Skip()
            return
        key = event.GetKeyCode()
        if key in (wx.WXK_DELETE, wx.WXK_BACK):
            self.delete_scene()
        elif key == wx.WXK_F2:
            self.scene_browser.list.begin_rename()
        else:
            event.Skip()

    def _rename_scene(self, scene_id: str, name: str) -> None:
        scene = self.project.get_timeline_scene(scene_id)
        if scene is not None and name.strip() and name.strip() != scene.name:
            scene.name = name.strip()
            self.refresh_scenes(scene.id)
            app_services.request_checkpoint()

    def _move_scene(self, scene_id: str, before_id: Optional[str]) -> None:
        scenes = self.project.timeline_scenes
        scene = self.project.get_timeline_scene(scene_id)
        if scene is None or scene_id == before_id:
            return
        scenes.remove(scene)
        before = self.project.get_timeline_scene(before_id) if before_id else None
        scenes.insert(scenes.index(before) if before else len(scenes), scene)
        self.refresh_scenes(scene.id)
        app_services.request_checkpoint()

    def _scene_thumbnail(self, scene_id: str, size: int) -> Optional[wx.Bitmap]:
        """The scene's first frame, made again after every undo step (anything in it may have changed)."""
        scene = self.project.get_timeline_scene(scene_id)
        if scene is None:
            return None
        key = (app_services.project_revision(), size, swap_key(self.project, self.project.active_palette_swap),
               mapping_key(self.project.active_mapping))
        found = self._scene_thumbs.get(scene_id)
        if found is not None and found[0] == key and key[0] is not None:
            return found[1]
        image = scene_image(self.project, scene, 0.0)
        bg = tuple(scene.background_color) if scene.background_color else (40, 42, 46)
        if image is None:
            bmp = wx.Bitmap(size, size)
            dc = wx.MemoryDC(bmp)
            dc.SetBackground(wx.Brush(wx.Colour(*bg)))
            dc.Clear()
            dc.SelectObject(wx.NullBitmap)
        else:
            bmp = fit_bitmap(image, size, size, bg, max_scale=4)
        self._scene_thumbs[scene_id] = (key, bmp)
        return bmp

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

    def export_gif(self) -> None:
        """The scene as an animated GIF, drawn like the stage on its background colour (thumbnails.export_scene_gif)."""
        from ui.scene_editor.thumbnails import export_scene_gif

        scene = self.scene()
        if not scene:
            app_services.show_status("Make or pick a scene to export a GIF")
            return
        self.stop_playback()
        with wx.FileDialog(self, f"Export '{scene.name}' as GIF", defaultFile=f"{scene.name}.gif",
                           wildcard="GIF files (*.gif)|*.gif", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            with wx.BusyCursor():
                count = export_scene_gif(self.project, scene, path)
        except OSError as exc:
            wx.MessageBox(f"Could not write the GIF:\n{exc}", "Export GIF", wx.OK | wx.ICON_ERROR, self)
            return
        app_services.show_status(f"Exported {count} picture(s) of '{scene.name}' to {path}")

    def _on_scene_field(self, field: str, value: Any) -> None:
        if field == "export_gif":
            self.export_gif()
            return
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

    def _set_screen(self, value: str, persist: bool = True) -> None:
        """"" (none), PROJECT_SCREEN (the project's console, whichever it is) or a screen's label to compare with
        (the project's own counts as following the project)."""
        own_label, own_size = project_screen(self.project)
        if value == own_label:
            value = PROJECT_SCREEN
        guides = {label: size for label, size in SCREEN_GUIDES if size}
        if value not in guides and value != PROJECT_SCREEN:
            value = ""
        options = [("", "None"), (PROJECT_SCREEN, own_label)]
        options += [(label, f"Compare: {label}") for label in guides if label != own_label]
        self._screen_values = [v for v, _label in options]
        labels = [label for _v, label in options]
        if self.screen_choice.GetItems() != labels:
            self.screen_choice.SetItems(labels)
        self.screen_choice.SetSelection(self._screen_values.index(value))
        self.screen_value = value
        self.stage.screen_guide = own_size if value == PROJECT_SCREEN else guides.get(value)
        if persist:
            config = wx.Config.Get()
            config.Write(CONFIG_SCREEN, value)
            config.Flush()
        self.stage.Refresh(False)

    def on_console_changed(self) -> None:
        """The project's console changed: the first screen is its screen, and an outline that follows it moves."""
        self._set_screen(self.screen_value, persist=False)

    def _on_screen_choice(self, _event: wx.CommandEvent) -> None:
        idx = self.screen_choice.GetSelection()
        self._set_screen(self._screen_values[idx] if 0 <= idx < len(self._screen_values) else "")

    def _on_loop(self, event: wx.CommandEvent) -> None:
        scene = self.scene()
        if scene:
            scene.loop = event.IsChecked()
            self._commit()

    # ================================================================== selection & time
    def select_object(self, object_id: Optional[str]) -> None:
        self.selected_object_id = object_id
        self.selected_object_ids = [object_id] if object_id else []
        if object_id:
            self.selection = {k: v for k, v in self.selection.items() if k == object_id}
            self.timeline.ensure_row_visible(object_id)
        else:
            self.selection = {}
        self.refresh()

    def select_objects(self, ids: Sequence[str], primary: Optional[str] = None) -> None:
        """Several layers (Shift / Cmd+click, the stage's marquee); ``primary`` is the one the inspector shows."""
        scene = self.scene()
        chosen = [i for i in dict.fromkeys(ids) if scene is not None and scene.get_object(i) is not None]
        if primary not in chosen:
            primary = chosen[-1] if chosen else None
        if primary:
            chosen.remove(primary)
            chosen.append(primary)
        self.selected_object_ids = chosen
        self.selected_object_id = primary
        self.selection = {k: v for k, v in self.selection.items() if k in chosen}
        if primary:
            self.timeline.ensure_row_visible(primary)
        self.refresh()

    def _selected_objects(self, unlocked: bool = False) -> List[TimelineObject]:
        """The selected layers, the inspector's last; without those whose parent is selected too (they follow it)."""
        scene = self.scene()
        objs = ops.top_objects(scene, self.selected_object_ids) if scene else []
        return [o for o in objs if o.id not in self.locked_ids] if unlocked else objs

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
        # The game shows a scene sample per video frame: at 50 Hz (View menu) it plays at 5/6 of the speed.
        frame = start_frame + int((time.monotonic() - start_time) * scene.fps * REFRESH.speed(self.project))
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
        objs = [o for o in (scene.get_object(i) for i in self.selected_object_ids) if o is not None]
        if objs:
            for obj in objs:
                ops.delete_object(self.project, scene, obj.id)
            self.selected_object_id = None
            self._commit()
            app_services.show_status(f"Deleted layer '{objs[0].name}'" if len(objs) == 1 else f"Deleted {len(objs)} layers")

    def duplicate_selected_object(self) -> None:
        """Duplicate every selected layer (with the layers below it); the copies are selected."""
        scene, objs = self.scene(), self._selected_objects()
        if not scene or not objs:
            return
        copies = [c for c in (ops.duplicate_object(scene, o.id) for o in objs) if c is not None]
        if copies:
            self.select_objects([c.id for c in copies])
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
    def _apply_pose_change(self, obj: TimelineObject, field: str, value: Any, group: bool = False) -> None:
        """Auto-Key on (or a key at the playhead): edit that key. Off between keys: edit every key. ``group``: one of
        several layers edited together (the keys selected on the others stay selected)."""
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
            if group:
                self.selection[obj.id] = {key.id}
            else:
                self.selection = {obj.id: {key.id}}

    def _on_transform_field(self, field: str, value: Any) -> None:
        obj = self.obj()
        if obj and obj.id not in self.locked_ids:
            self._apply_pose_change(obj, field, value)
            self._commit()

    def flip_selected(self, axis: str) -> None:
        """H / V: every selected layer mirrors in place."""
        scene, objs = self.scene(), self._selected_objects(unlocked=True)
        if not scene or not objs:
            return
        field = "flip_x" if axis == "x" else "flip_y"
        for obj in objs:
            state = scene.evaluate_object_state(self.project, obj.id, ops.time_of(self.frame, scene.fps)) or {}
            self._apply_pose_change(obj, field, not bool(state.get(field, False)), group=len(objs) > 1)
        self._commit()

    def rotate_selected(self, degrees: int) -> None:
        objs = self._selected_objects(unlocked=True)
        for obj in objs:
            self._apply_pose_change(obj, "rotate", degrees, group=len(objs) > 1)
        if objs:
            self._commit()

    def nudge_selected(self, dx: int, dy: int) -> None:
        """Arrow keys: every selected layer moves (a child whose parent is selected moves with it)."""
        scene, objs = self.scene(), self._selected_objects(unlocked=True)
        if not scene or not objs:
            return
        for obj in objs:
            state = scene.evaluate_object_state(self.project, obj.id, ops.time_of(self.frame, scene.fps)) or {}
            if dx:
                self._apply_pose_change(obj, "x", round(float(state.get("x", 0.0))) + dx, group=len(objs) > 1)
            if dy:
                self._apply_pose_change(obj, "y", round(float(state.get("y", 0.0))) + dy, group=len(objs) > 1)
        self.refresh()

    # ---- stage drags
    def _stage_drag_begin(self, object_id: str) -> None:
        scene = self.scene()
        obj = scene.get_object(object_id) if scene else None
        if not obj:
            self._drag = {}
            return
        group = self._selected_objects(unlocked=True) if object_id in self.selected_object_ids else [obj]
        time_value = ops.time_of(self.frame, scene.fps)
        # Nothing changes until the mouse actually moves (a click only selects).
        self._drag = {"object_id": obj.id, "moved": False, "objects": {
            o.id: {"parent": ops.parent_world_matrix(self.project, scene, o, time_value), "bases": None} for o in group}}

    def _stage_drag(self, object_id: str, dx: float, dy: float) -> None:
        """Drag on the stage: the layers move together, each in its parent's space."""
        scene = self.scene()
        if not scene or self._drag.get("object_id") != object_id:
            return
        new_keys: Selection = {}
        for oid, entry in self._drag["objects"].items():
            obj = scene.get_object(oid)
            if obj is None:
                continue
            lx, ly = ops.world_to_parent_delta(entry["parent"], dx, dy)
            lx, ly = round(lx), round(ly)
            if entry["bases"] is None:
                if not (lx or ly):
                    continue
                key = self._key_here(obj)
                if key is None and self.auto_key:
                    key = ops.ensure_key(self.project, scene, obj, self.frame)
                entry["bases"] = {k.id: (k.x, k.y) for k in ([key] if key else obj.keyframes)}
                if key:
                    new_keys[obj.id] = {key.id}
            for key in obj.keyframes:
                base = entry["bases"].get(key.id)
                if base:
                    key.x, key.y = float(base[0] + lx), float(base[1] + ly)
            self._drag["moved"] = self._drag["moved"] or bool(lx or ly)
        if new_keys:
            self.selection = {**{k: v for k, v in self.selection.items() if k in self._drag["objects"]}, **new_keys}
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
            if not ops.move_layer(self.project, scene, obj.id, value, None):  # (it stops following a point)
                self.refresh()
                return
            if value:
                self.collapsed_ids.discard(value)
        elif field == "attach":
            role, type_id = value
            ops.set_attachment(self.project, scene, obj, role, type_id, ops.time_of(self.frame, scene.fps))
            if role:
                app_services.show_status(f"'{obj.name}' follows the point '{role}' of its parent's frames")
        elif field in GROUP_FIELDS:  # with several layers selected: all of them
            for target in [o for o in (scene.get_object(i) for i in self.selected_object_ids) if o] or [obj]:
                if field == "playback_mode":
                    target.playback_mode = str(value)
                elif field == "playback_speed":
                    target.playback_speed = max(0.05, float(value))
                elif field == "root_motion":
                    target.use_source_root_motion = bool(value)
                elif field == "mapping":
                    target.mapping_id = value or None
                elif field == "palette_swap":
                    target.palette_swap_id = value or None
        elif field == "playback_offset_frames":
            obj.playback_offset = ops.time_of(int(value), scene.fps)
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
        count = len(self.selected_object_ids)
        layers = f" {count} Layers" if count > 1 else ""
        self._menu_item(menu, f"Duplicate{layers}", self.duplicate_selected_object)
        self._menu_item(menu, f"Delete{layers}", lambda: (self.selection.clear(), self.delete_selection()))
        self._menu_item(menu, f"Copy{layers}", lambda: (self.selection.clear(), self.edit_copy()))
        self._menu_item(menu, "Paste Layers", self.paste_layers, bool(_OBJECT_CLIPBOARD))
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
            _PASTE_KIND[0] = "keys"
            app_services.show_status(f"Copied {len(_KEY_CLIPBOARD)} key(s)")
        elif obj:
            tops = self._selected_objects()
            _OBJECT_CLIPBOARD[:] = ops.copy_objects(scene, self.selected_object_ids)
            _PASTE_KIND[0] = "layers"
            app_services.show_status(f"Copied layer '{obj.name}'" if len(tops) == 1 else f"Copied {len(tops)} layers"
                                     + " (paste them into any scene)")

    def edit_cut(self) -> None:
        self.edit_copy()
        self.delete_selection()

    def edit_paste(self) -> None:
        """Paste what was copied last: keys (at the playhead, onto the selected layer) or layers (into this scene)."""
        scene = self.scene()
        if not scene:
            return
        if _KEY_CLIPBOARD and (self.selection or self.obj()) and (_PASTE_KIND[0] == "keys" or not _OBJECT_CLIPBOARD):
            pasted = ops.paste_keys(scene, list(_KEY_CLIPBOARD), self.frame, self.selected_object_id)
            if pasted:
                self.selection = pasted
                self._commit()
            return
        self.paste_layers()

    def paste_layers(self) -> None:
        """The copied layers (with the layers below them) into this scene, in front; also into another scene."""
        scene = self.scene()
        if scene and _OBJECT_CLIPBOARD:
            tops = ops.paste_objects(scene, list(_OBJECT_CLIPBOARD))
            self.selection = {}
            self.select_objects([o.id for o in tops])
            self._commit()
            app_services.show_status(f"Pasted {len(tops)} layer{'s' if len(tops) != 1 else ''} into '{scene.name}'")

    def edit_duplicate(self) -> None:
        self.duplicate_selected_object()

    def edit_select_all(self) -> None:
        scene, obj = self.scene(), self.obj()
        if not scene:
            return
        targets = [obj] if obj else scene.objects
        self.selection = {o.id: {k.id for k in o.keyframes} for o in targets}
        self.refresh()
