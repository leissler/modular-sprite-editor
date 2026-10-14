"""Animations tab: Animations + Frames | Stage | Inspector on top, transport and sequence below."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import wx

import playback
from models import AFrame, Animation, Project
from ui import app_services, grouping, view_memory
from ui.animation_editor import ops
from ui.animation_editor.batch_dialog import ChangeAnimationsDialog
from ui.animation_editor.browser import AnimationBrowser, FrameLibrary
from ui.animation_editor.inspector import AnimationInspector
from ui.animation_editor.render import StepRenderer, export_gif
from ui.animation_editor.sequence import SequenceView
from ui.animation_editor.stage import ONION_MODES, AnimationStage
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.components.group_bar import group_menu
from ui.dpi import px
from ui.refresh_rate import REFRESH
from ui.components.split_memory import split_bottom_remembered

MIRROR_MODES: List[Tuple[str, Tuple[bool, bool]]] = [
    ("Off", (False, False)),
    ("H", (True, False)),
    ("V", (False, True)),
    ("H + V", (True, True)),
]
SPEEDS: List[Tuple[str, float]] = [("1×", 1.0), ("½×", 0.5), ("¼×", 0.25), ("2×", 2.0)]
HOLD_PRESETS = (1, 2, 3, 4, 6, 8)
EVENT_FLASH_SECONDS = 0.6  # how long the events of a step that just started light up in the preview
# Playback shows a frame this often, but never before the last one has been drawn: the one-shot timer is armed on
# the next idle event, with what is left of the interval. Armed before the drawing (or periodic), a frame that took
# longer to draw than this (a slow machine) always left a timer message waiting on Windows, so wx.Yield never
# returned.
PLAY_INTERVAL_MS = 10

# Copied steps, shared between animations for the session.
_STEP_CLIPBOARD: List[Dict[str, Any]] = []


class AnimationEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_animation_id: Optional[str] = None
        self.tick = 0
        self.selection: Set[int] = set()
        self.is_playing = False
        self.repeat = True
        self.speed = 1.0
        self.renderer = StepRenderer()
        self.player: Optional[ops.Player] = None
        self._play_clock: Tuple[float, int] = (0.0, 0)
        self._fired: Optional[Tuple[str, int, float]] = None  # (animation id, step, when) whose events last fired
        self._drag_bases: Dict[int, Tuple[int, int]] = {}
        self._hold_bases: Dict[int, int] = {}
        self._fitted_id: Optional[str] = None
        self._remembered_view: Optional[Tuple[str, view_memory.View]] = None  # shown instead of the first fit
        self._view: List[Animation] = []
        self.on_edit_frame: Optional[Callable[[str], None]] = None  # set by the main window
        self.timer = wx.Timer(self)
        self._arm_timer_when_idle = False  # see PLAY_INTERVAL_MS
        self._frame_time = 0.0  # when the last playback frame started

        self._build_ui()
        self._bind()
        self.refresh_animations()

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        self.vsplit = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        top = wx.Panel(self.vsplit)
        self.outer_split = wx.SplitterWindow(top, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)

        self.left_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.browser = AnimationBrowser(self.left_split)
        self.library = FrameLibrary(self.left_split, self.project)
        self.left_split.SplitHorizontally(self.browser, self.library, 0)
        self.left_split.SetSashGravity(0.5)
        self.left_split.SetMinimumPaneSize(px(140))

        self.inner_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        stage_panel = wx.Panel(self.inner_split)
        stage_sizer = wx.BoxSizer(wx.VERTICAL)
        self.stage = AnimationStage(stage_panel, self.project)
        self.canvas_controls = CanvasDisplayControls(stage_panel, self.stage, view_key="animations", part_bounds=True, budget=True)
        self.canvas_controls.add_separator()
        self.chk_path = self.canvas_controls.add_toggle("Path", True, lambda v: self._refresh_stage(), "Show the motion path of the step offsets")
        self.chk_collision = self.canvas_controls.add_toggle(
            "Hitboxes", False, self._on_toggle_collision, "Show the step's hitboxes, moved like the step")
        self.chk_points = self.canvas_controls.add_toggle(
            "Points", False, self._on_toggle_points, "Show the step's points, moved like the step")
        self.canvas_controls.on_budget_changed = lambda: self.refresh(stage=False, sequence=False)
        stage_sizer.Add(self.stage, 1, wx.EXPAND | wx.ALL, 2)
        stage_sizer.Add(self.canvas_controls, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        stage_panel.SetSizer(stage_sizer)

        self.inspector = AnimationInspector(self.inner_split)
        self.inner_split.SplitVertically(stage_panel, self.inspector, -px(320))
        self.inner_split.SetSashGravity(1.0)
        self.inner_split.SetMinimumPaneSize(px(240))
        self.outer_split.SplitVertically(self.left_split, self.inner_split, px(260))
        self.outer_split.SetMinimumPaneSize(px(200))
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

        self.btn_first = tbutton("|◀", "First step (Home)")
        self.btn_prev_step = tbutton("◆◀", "Previous step (,)")
        self.btn_prev_tick = tbutton("◀", "Previous tick (Shift+,)")
        self.btn_play = tbutton("▶", "Play / pause (Enter)", 44)
        self.btn_next_tick = tbutton("▶", "Next tick (Shift+.)")
        self.btn_next_step = tbutton("▶◆", "Next step (.)")
        self.btn_last = tbutton("▶|", "Last step (End)")
        transport.AddSpacer(10)
        transport.Add(wx.StaticText(bottom, label="Tick"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.tick_spin = wx.SpinCtrl(bottom, min=0, max=100000, initial=0, size=(px(64), -1), style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
        transport.Add(self.tick_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.tick_info = wx.StaticText(bottom, label="", size=(px(230), -1), style=wx.ST_NO_AUTORESIZE)
        transport.Add(self.tick_info, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.chk_repeat = wx.CheckBox(bottom, label="Repeat")
        self.chk_repeat.SetValue(True)
        self.chk_repeat.SetToolTip("Keep the preview going: restart when the animation stops (Play once, or after its repeats)")
        transport.Add(self.chk_repeat, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        transport.Add(wx.StaticText(bottom, label="Speed"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.speed_choice = wx.Choice(bottom, choices=[label for label, _ in SPEEDS])
        self.speed_choice.SetSelection(0)
        self.speed_choice.SetToolTip("Preview speed (slow motion helps to check single ticks)")
        transport.Add(self.speed_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        # Preview settings live with playback (like onion skin in a timeline), not in the view bar.
        transport.Add(wx.StaticText(bottom, label="Onion"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.onion_choice = wx.Choice(bottom, choices=[label for label, _ in ONION_MODES])
        self.onion_choice.SetSelection(0)
        self.onion_choice.SetMinSize((bottom.GetTextExtent("Previous")[0] + px(44), -1))
        self.onion_choice.SetToolTip("Ghost the previous (red) / next (blue) step on the stage")
        transport.Add(self.onion_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        transport.Add(wx.StaticText(bottom, label="Mirror"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.mirror_choice = wx.Choice(bottom, choices=[label for label, _ in MIRROR_MODES])
        self.mirror_choice.SetSelection(0)
        self.mirror_choice.SetToolTip("Preview the animation mirrored (e.g. facing the other way); the data is not changed")
        transport.Add(self.mirror_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        self.btn_delete = tbutton("Delete", "Delete the selected steps (Delete)", 64)
        transport.AddStretchSpacer(1)
        self.btn_fit_seq = tbutton("Fit", "Show the whole animation in the sequence", 44)
        bottom_sizer.Add(transport, 0, wx.EXPAND | wx.ALL, 4)
        self.sequence_view = SequenceView(bottom)
        self.sequence = self.sequence_view.widget
        bottom_sizer.Add(self.sequence_view, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        bottom.SetSizer(bottom_sizer)

        split_bottom_remembered(self.vsplit, top, bottom, "Animations/SequenceHeight", 194)  # as the user dragged it last
        self.vsplit.SetSashGravity(1.0)
        self.vsplit.SetMinimumPaneSize(px(140))
        root.Add(self.vsplit, 1, wx.EXPAND)
        self.SetSizer(root)
        wx.CallAfter(self._place_left_sash)

    def _place_left_sash(self) -> None:
        if self.left_split:
            height = self.left_split.GetClientSize().height
            if height > 300:
                self.left_split.SetSashPosition(int(height * 0.52))

    def _bind(self) -> None:
        b = self.browser
        b.search.Bind(wx.EVT_TEXT, lambda e: self.refresh_animations())
        b.on_view_changed = self.refresh_animations
        b.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: b.search.SetValue(""))
        b.list.Bind(wx.EVT_LISTBOX, self._on_list_select)
        b.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: b.list.begin_rename())
        b.list.Bind(wx.EVT_CONTEXT_MENU, self._on_list_menu)
        b.list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        b.list.on_move = self._move_animation
        b.list.on_rename = self._rename_animation
        b.btn_new.Bind(wx.EVT_BUTTON, lambda e: self.new_animation())
        b.btn_dup.Bind(wx.EVT_BUTTON, lambda e: self.duplicate_animation())
        b.btn_del.Bind(wx.EVT_BUTTON, lambda e: self.delete_animation())
        self.library.palette.on_frame_double_click = self.insert_frame_after_current
        self.library.palette.on_context_menu = self._library_menu

        self.onion_choice.Bind(wx.EVT_CHOICE, lambda e: self._refresh_stage())
        self.mirror_choice.Bind(wx.EVT_CHOICE, lambda e: self._refresh_stage())

        self.btn_first.Bind(wx.EVT_BUTTON, lambda e: self.seek_step(0))
        self.btn_last.Bind(wx.EVT_BUTTON, lambda e: self.seek_step(len(self._steps()) - 1))
        self.btn_prev_step.Bind(wx.EVT_BUTTON, lambda e: self.step(-1))
        self.btn_next_step.Bind(wx.EVT_BUTTON, lambda e: self.step(1))
        self.btn_prev_tick.Bind(wx.EVT_BUTTON, lambda e: self.step_tick(-1))
        self.btn_next_tick.Bind(wx.EVT_BUTTON, lambda e: self.step_tick(1))
        self.btn_play.Bind(wx.EVT_BUTTON, lambda e: self.toggle_play())
        self.tick_spin.Bind(wx.EVT_SPINCTRL, lambda e: self.seek_tick(self.tick_spin.GetValue()))
        self.tick_spin.Bind(wx.EVT_TEXT_ENTER, lambda e: self.seek_tick(self.tick_spin.GetValue()))
        self.chk_repeat.Bind(wx.EVT_CHECKBOX, self._on_repeat)
        self.speed_choice.Bind(wx.EVT_CHOICE, self._on_speed)
        self.btn_delete.Bind(wx.EVT_BUTTON, lambda e: self.delete_steps())
        self.btn_fit_seq.Bind(wx.EVT_BUTTON, lambda e: self.sequence.fit())
        self.Bind(wx.EVT_TIMER, self._on_timer, self.timer)
        self.Bind(wx.EVT_IDLE, self._on_idle)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        st = self.stage
        st.on_pick_step = self._pick_step_on_stage
        st.on_drag_begin = self._stage_drag_begin
        st.on_drag = self._stage_drag
        st.on_drag_end = self._stage_drag_end
        st.on_drop_frames = self.insert_frames_after_current

        sq = self.sequence
        sq.on_seek_tick = self.seek_tick
        sq.on_select_steps = self._sequence_select
        sq.on_hold_drag_begin = self._hold_drag_begin
        sq.on_hold_drag = self._hold_drag
        sq.on_hold_drag_end = self._commit
        sq.on_move_steps = self.move_steps
        sq.on_insert_frames = self.insert_frames
        sq.on_open_frame = self._open_frame_of_step
        sq.on_context_menu = self._sequence_menu

        ins = self.inspector
        ins.on_animation_change = self._on_animation_field
        ins.on_animation_tool = self._on_animation_tool
        ins.on_step_change = self._on_step_field
        ins.on_pick_frame = self._pick_frame_for_selection
        ins.on_open_frame = lambda: self._open_frame_of_step(self.current_step())
        ins.on_event_change = self._on_event_field
        ins.on_manage_events = self.manage_event_types

    # ================================================================== main-window interface
    def get_active_canvas(self):
        return self.stage

    def set_project(self, project: Project) -> None:
        self.stop_playback()
        self.project = project
        self.renderer.clear()
        self.stage.set_project(project)
        self.stage.collision_type_colors = {ct.id: ct.color for ct in project.collision_types}
        self.stage.point_type_colors = {pt.id: pt.color for pt in project.point_types}
        self.library.set_project(project)
        self.browser.search.ChangeValue("")
        self.browser.groups.set_group(grouping.ALL)
        self.browser.groups.set_sort("order")
        self.selected_animation_id = project.animations[0].id if project.animations else None
        self.selection = set()
        self.tick = 0
        self._fitted_id = None
        self._remembered_view = None
        self.refresh_animations()

    def refresh_after_history(self) -> None:
        self.renderer.clear()
        self.stage.clear_cache()
        self.library.refresh()
        if self.selected_animation_id and not self.project.get_animation(self.selected_animation_id):
            self.selected_animation_id = None
        self.refresh_animations()

    def on_tab_activated(self) -> None:
        """Frames or modules may have changed in other tabs."""
        self.renderer.clear()
        self.stage.clear_cache()
        self.stage.collision_type_colors = {ct.id: ct.color for ct in self.project.collision_types}
        self.stage.point_type_colors = {pt.id: pt.color for pt in self.project.point_types}
        self.library.refresh()
        self.refresh_animations()
        wx.CallAfter(self._fit_views)

    def view_state(self) -> Dict[str, Any]:
        """The animation shown, the list's group and order and the stage's zoom and pan (kept per project)."""
        return {"animation": self.selected_animation_id, "view": view_memory.canvas_view(self.stage),
                "list": self.browser.groups.state(), **self.canvas_controls.grid_state()}

    def restore_view_state(self, state: Dict[str, Any]) -> None:
        self.canvas_controls.restore_grid(state)
        if isinstance(state.get("list"), dict):
            self.browser.groups.restore(state["list"])
            self.refresh_animations()
        anim_id = view_memory.text(state.get("animation"))
        if anim_id and self.project.get_animation(anim_id):  # the list's filter is empty: a project was just opened
            view = view_memory.parse_view(state.get("view"))
            self._remembered_view = (anim_id, view) if view else None
            self.select_animation(anim_id)

    def refresh_library(self) -> None:
        self.library.refresh()

    def on_active_mapping_changed(self) -> None:
        self.library.refresh()
        self.stage.clear_cache()
        self.refresh()

    def stop_playback(self) -> None:
        if self.is_playing:
            self.toggle_play()

    # ================================================================== helpers
    def animation(self) -> Optional[Animation]:
        return self.project.get_animation(self.selected_animation_id) if self.selected_animation_id else None

    def _steps(self) -> List[AFrame]:
        anim = self.animation()
        return anim.aframes if anim else []

    def current_step(self) -> int:
        anim = self.animation()
        return ops.step_at_tick(anim, self.tick) if anim else -1

    def _targets(self) -> List[int]:
        """Steps an edit applies to: the selection, else the step at the playhead."""
        if self.selection:
            return sorted(self.selection)
        current = self.current_step()
        return [current] if current >= 0 else []

    def _commit(self) -> None:
        self.refresh()
        app_services.request_checkpoint()

    def _mirror(self) -> Tuple[bool, bool]:
        return MIRROR_MODES[max(0, self.mirror_choice.GetSelection())][1]

    def _clamp(self) -> None:
        anim = self.animation()
        total = ops.total_ticks(anim) if anim else 0
        self.tick = max(0, min(self.tick, total - 1)) if total else 0
        count = len(anim.aframes) if anim else 0
        self.selection = {i for i in self.selection if i < count}

    # ================================================================== refresh
    def refresh_animations(self) -> None:
        groups = self.browser.groups
        groups.set_groups(self.project.animations)
        self._view = grouping.shown(self.project.animations, self.browser.filter_text(), groups.group(), groups.sort())
        self.browser.list.can_reorder = groups.sort() == "order"
        self.browser.list.show_group = groups.group() is grouping.ALL
        total = len(self.project.animations)
        self.browser.title.SetLabel(
            f"ANIMATIONS ({len(self._view)} OF {total})" if len(self._view) != total else f"ANIMATIONS ({total})"
        )
        if self.selected_animation_id and not self.project.get_animation(self.selected_animation_id):
            self.selected_animation_id = None
        if self.selected_animation_id is None and self.project.animations:
            self.selected_animation_id = self.project.animations[0].id
        self.browser.list.set_items(self.project, self.renderer, self._view, self.selected_animation_id)
        self.browser.btn_dup.Enable(self.animation() is not None)
        self.browser.btn_del.Enable(self.animation() is not None)
        self.refresh()

    def refresh(self, stage: bool = True, sequence: bool = True, inspector: bool = True) -> None:
        self._clamp()
        anim = self.animation()
        step = self.current_step()
        if stage:
            self._refresh_stage()
        if sequence:
            self.sequence.set_data(self.project, anim, self.renderer, self.tick, step, self.selection)
        if inspector:
            self.inspector.show(self.project, anim, sorted(self.selection), self._worst_step_budget(anim))
        if not self.is_playing:
            self.browser.list.Refresh()  # rows show length and mode
        self._update_transport()

    def _worst_step_budget(self, anim: Optional[Animation]) -> Optional[Tuple[str, bool]]:
        profile = self.stage.budget_profile
        if profile is None or not anim or not anim.aframes:
            return None
        from hardware_budget import vram_tiles
        from ui.animation_editor.render import step_affine
        from ui.canvas import BUDGET

        worst = None
        parts = []
        for index, af in enumerate(anim.aframes):
            frame = self.project.get_frame(af.frame_id)
            if frame is None:
                continue
            a, b = step_affine(af)
            budget = BUDGET.frame_budget(self.project, frame, self.project.active_mapping, profile, a, b)
            parts += budget.parts
            rank = (budget.over_budget(), budget.sprite_count, budget.tile_count)
            if worst is None or rank > worst[0]:
                worst = (rank, index, budget)
        if worst is None:
            return None
        _rank, index, budget = worst
        count, pixels = budget.worst_line()
        text = (
            f"worst step {index + 1}: {budget.sprite_count} sprites; "
            f"busiest line {count}/{profile.sprites_per_line} sprites, {pixels}/{profile.pixels_per_line} px"
        )
        if profile.vram_tiles:
            text += f"\nvideo memory: {vram_tiles(parts)} tiles for the animation"
        return text, budget.over_budget()

    def _refresh_stage(self) -> None:
        anim = self.animation()
        # Colour cycles turn while it plays: video frames since playback started (none while it stands).
        self.stage.colour_frame = ((time.monotonic() - self._play_clock[0]) * REFRESH.hz(self.project) * self.speed
                                   if self.is_playing else None)
        self.stage.set_view(
            anim,
            self.current_step(),
            self.selection,
            self._mirror(),
            ONION_MODES[max(0, self.onion_choice.GetSelection())][1],
            self.chk_path.GetValue(),
        )
        self._refresh_events()

    # ------------------------------------------------------------------ events in the preview
    def _note_fired(self, anim: Animation, step: int) -> None:
        """A step started while playing (the runtime's step_started): its events fire."""
        if 0 <= step < len(anim.aframes) and anim.aframes[step].events:
            self._fired = (anim.id, step, time.monotonic())

    def _flash(self, anim: Optional[Animation], step: int) -> float:
        fired = self._fired
        if not self.is_playing or fired is None or anim is None or fired[0] != anim.id or fired[1] != step:
            return 0.0
        return max(0.0, 1.0 - (time.monotonic() - fired[2]) / EVENT_FLASH_SECONDS)

    def _refresh_events(self) -> None:
        """Event chips of the shown step on the stage (active while it shows), lit up while they have just fired;
        the sequence lights up the chips of the step that fired."""
        anim = self.animation()
        step = self.current_step()
        chips: List[Tuple[str, Tuple[int, int, int]]] = []
        if anim and 0 <= step < len(anim.aframes):
            for event in anim.aframes[step].events:
                etype = self.project.get_event_type(event.type_id)
                label = (etype.name if etype else "?") + (f"={event.value}" if event.value else "")
                chips.append((label, tuple(etype.color) if etype else (150, 150, 150)))
        self.stage.set_events(chips, self._flash(anim, step))
        fired_step = self._fired[1] if self._fired and anim and self._fired[0] == anim.id else -1
        glow = self._flash(anim, fired_step)
        lit = fired_step if glow > 0 else -1
        if lit != self.sequence.flash_step or abs(glow - self.sequence.flash) > 1e-3:
            self.sequence.flash_step = lit
            self.sequence.flash = glow
            self.sequence.Refresh(False)

    def _update_transport(self) -> None:
        anim = self.animation()
        has_steps = bool(anim and anim.aframes)
        self.btn_play.SetLabel("❚❚" if self.is_playing else "▶")
        for btn in (self.btn_first, self.btn_prev_step, self.btn_prev_tick, self.btn_play,
                    self.btn_next_tick, self.btn_next_step, self.btn_last, self.btn_fit_seq):
            btn.Enable(has_steps)
        self.btn_delete.Enable(has_steps)
        if not has_steps:
            self.tick_info.SetLabel("")
            self.tick_spin.SetValue(0)
            return
        total = ops.total_ticks(anim)
        if not self.tick_spin.HasFocus():
            self.tick_spin.SetRange(0, max(0, total - 1))
            self.tick_spin.SetValue(self.tick)
        self.tick_info.SetLabel(
            f"/ {total - 1}   {ops.seconds(anim, self.tick):.2f} s   step {self.current_step() + 1} of {len(anim.aframes)}"
        )

    def _fit_views(self) -> None:
        anim = self.animation()
        if anim and self._fitted_id != anim.id and self.stage.IsShownOnScreen():
            self._fitted_id = anim.id
            remembered, self._remembered_view = self._remembered_view, None
            if remembered and remembered[0] == anim.id:
                self.stage.set_view_state(*remembered[1])  # where the project was left
            else:
                self.stage.fit_to_content()
            self.sequence.fit()

    # ================================================================== animations
    def select_animation(self, anim_id: Optional[str]) -> None:
        self.stop_playback()
        self.selected_animation_id = anim_id
        self.tick = 0
        self.selection = set()
        self.browser.list.set_items(self.project, self.renderer, self._view, anim_id)
        self.browser.btn_dup.Enable(anim_id is not None)
        self.browser.btn_del.Enable(anim_id is not None)
        self.refresh()
        self._fitted_id = None
        self._fit_views()

    def _on_list_select(self, _event: wx.CommandEvent) -> None:
        anim = self.browser.list.selected_animation()
        if anim and anim.id != self.selected_animation_id:
            self.select_animation(anim.id)

    def new_animation(self) -> None:
        anim = ops.new_animation(self.project, self.selected_animation_id)
        self.browser.search.ChangeValue("")
        self.selected_animation_id = anim.id
        self.refresh_animations()
        self.select_animation(anim.id)
        app_services.request_checkpoint()
        wx.CallAfter(self.browser.list.begin_rename)

    def duplicate_animation(self) -> None:
        anim = self.animation()
        if not anim:
            return
        copy = ops.duplicate_animation(self.project, anim)
        self.browser.search.ChangeValue("")
        self.selected_animation_id = copy.id
        self.refresh_animations()
        self.select_animation(copy.id)
        app_services.request_checkpoint()
        app_services.show_status(f"Duplicated '{anim.name}'")

    def delete_animation(self) -> None:
        anim = self.animation()
        if not anim:
            return
        uses = ops.scene_usage(self.project, anim.id)
        followers = ops.follow_up_references(self.project, anim.id)
        message = f"Delete animation '{anim.name}'?"
        if uses:
            message += f"\n\nIt is shown by {uses} timeline object(s); they will show nothing."
        if followers:
            names = ", ".join(f"'{a.name}'" for a in followers[:3]) + (" …" if len(followers) > 3 else "")
            message += f"\n\n{len(followers)} animation(s) continue with it ({names}); they will simply end."
        if wx.MessageBox(message, "Delete Animation", wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
            return
        position = self._view.index(anim) if anim in self._view else 0
        self.stop_playback()
        self.project.animations.remove(anim)
        for follower in followers:
            follower.next_animation_id = None
        remaining = [a for a in self._view if a is not anim]
        neighbour = remaining[min(position, len(remaining) - 1)] if remaining else None
        self.selected_animation_id = neighbour.id if neighbour else None
        self.refresh_animations()
        self.select_animation(self.selected_animation_id)
        app_services.request_checkpoint()
        app_services.show_status(f"Deleted '{anim.name}'")

    def _rename_animation(self, anim_id: str, name: str) -> None:
        anim = self.project.get_animation(anim_id)
        if anim and name and name != anim.name:
            anim.name = name
            self.refresh_animations()
            app_services.request_checkpoint()

    def _move_animation(self, anim_id: str, index: int) -> None:
        if self.browser.filter_text():
            app_services.show_status("Clear the filter to reorder animations")
            return
        ops.move_animation(self.project, anim_id, index)
        self.refresh_animations()
        app_services.request_checkpoint()

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_DELETE, wx.WXK_BACK):
            self.delete_animation()
        elif code == wx.WXK_F2:
            self.browser.list.begin_rename()
        else:
            event.Skip()

    def _on_list_menu(self, _event: wx.ContextMenuEvent) -> None:
        if not self.animation():
            return
        menu = wx.Menu()
        entries = [
            ("Rename", self.browser.list.begin_rename),
            ("Duplicate", self.duplicate_animation),
            ("Delete", self.delete_animation),
            None,
            ("Change Animations…", self.change_animations),
            ("Export GIF…", self.export_gif),
        ]
        for entry in entries:
            if entry is None:
                menu.AppendSeparator()
                continue
            label, handler = entry
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda e, h=handler: h(), item)
        menu.AppendSeparator()
        anim = self.animation()
        group_menu(self, menu, self.project.animations, anim.group if anim else "",
                   lambda name: self._on_animation_field("group", name))
        self.browser.list.PopupMenu(menu)
        menu.Destroy()

    def change_animations(self) -> None:
        """Change Animations…: one setting (tick rate, playback, repeats, group) for many animations, one undo step."""
        if not self.project.animations:
            return
        chosen = [self.selected_animation_id] if self.selected_animation_id else []
        with ChangeAnimationsDialog(self, self.project, chosen) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            ids, settings = dlg.chosen_ids(), dlg.settings()
        self.stop_playback()
        count, rounded = ops.change_animations(self.project, ids, **settings)
        self.refresh_animations()
        app_services.request_checkpoint()
        message = f"Changed {count} animation{'s' if count != 1 else ''}"
        if rounded:
            names = ", ".join(f"'{n}'" for n in rounded[:3]) + (" …" if len(rounded) > 3 else "")
            message += f"; the holds of {len(rounded)} ({names}) are rounded to whole ticks"
        app_services.show_status(message)

    def _on_animation_field(self, field: str, value: Any) -> None:
        anim = self.animation()
        if not anim:
            return
        if field == "name":
            if not value or value == anim.name:
                return
            anim.name = str(value)
        elif field == "playback":
            anim.playback_type = str(value)
        elif field == "loops":
            anim.loop_count = max(0, int(value))
        elif field == "loop_start":
            anim.loop_start = max(0, min(int(value), max(0, len(anim.aframes) - 1)))
        elif field == "next":
            anim.next_animation_id = str(value) if value else None
        elif field == "fps":
            anim.fps = max(1, int(value))
        elif field == "group":
            group = grouping.clean_name(str(value or ""))
            if group == anim.group:
                return
            anim.group = group
            app_services.show_status(f"'{anim.name}' is in the group '{group}'" if group else f"'{anim.name}' has no group")
        if self.is_playing:
            self.player = ops.Player(anim, self.repeat, playback.console_hold(anim))
            self.player.start(self.current_step())
            self._play_clock = (time.monotonic(), 0)
        self.refresh_animations()
        app_services.request_checkpoint()

    def _on_animation_tool(self, name: str) -> None:
        anim = self.animation()
        if not anim or not anim.aframes:
            return
        if name == "gif":
            self.export_gif()
            return
        if name == "mirror_x":
            ops.mirror_animation(anim, "x")
        elif name == "mirror_y":
            ops.mirror_animation(anim, "y")
        elif name == "rot_cw":
            ops.rotate_animation(anim, 90)
        elif name == "rot_ccw":
            ops.rotate_animation(anim, -90)
        elif name == "reverse":
            self.reverse_steps()
            return
        self.renderer.clear()
        self._commit()
        self._fitted_id = None
        self._fit_views()

    # ================================================================== playhead
    def seek_tick(self, tick: int) -> None:
        anim = self.animation()
        if not anim or not anim.aframes:
            return
        self.tick = max(0, min(int(tick), ops.total_ticks(anim) - 1))
        if self.is_playing and self.player:
            self.player.start(self.current_step())
            self._note_fired(anim, self.player.step)
            self._play_clock = (time.monotonic(), 0)
        self.sequence.ensure_tick_visible(self.tick)
        self.refresh()

    def seek_step(self, index: int) -> None:
        anim = self.animation()
        if not anim or not anim.aframes:
            return
        index = max(0, min(index, len(anim.aframes) - 1))
        self.seek_tick(ops.step_starts(anim)[index])

    def step(self, delta: int) -> None:
        anim = self.animation()
        if not anim or not anim.aframes:
            return
        self.stop_playback()
        count = len(anim.aframes)
        current = self.current_step()
        target = (current + delta) % count if anim.playback_type in ops.REPEATING_MODES else max(0, min(current + delta, count - 1))
        self.seek_step(target)

    def step_tick(self, delta: int) -> None:
        anim = self.animation()
        if not anim or not anim.aframes:
            return
        self.stop_playback()
        total = ops.total_ticks(anim)
        self.seek_tick((self.tick + delta) % total)

    def toggle_play(self) -> None:
        anim = self.animation()
        if self.is_playing or not anim or not anim.aframes:
            self.is_playing = False
            self.timer.Stop()
            self._fired = None
        else:
            self.is_playing = True
            # The game's timing: one advance per video frame, each step held for the frames the export gives it.
            self.player = ops.Player(anim, self.repeat, playback.console_hold(anim))
            start = self.current_step()
            last = len(anim.aframes) - 1
            if anim.playback_type == "forward" and start >= last:
                start = 0
            self.player.start(start)
            self._note_fired(anim, self.player.step)
            self.tick = self.player.position()
            self._play_clock = (time.monotonic(), 0)
            self._frame_time = time.monotonic()
            self._arm_timer_when_idle = True
        self.refresh(inspector=not self.is_playing)

    def _on_timer(self, _event: wx.TimerEvent) -> None:
        self._frame_time = time.monotonic()
        self._play_frame()
        self._arm_timer_when_idle = self.is_playing

    def _on_idle(self, event: wx.IdleEvent) -> None:
        event.Skip()
        if self._arm_timer_when_idle:
            self._arm_timer_when_idle = False
            if self.is_playing:
                spent = int((time.monotonic() - self._frame_time) * 1000)
                self.timer.StartOnce(max(1, PLAY_INTERVAL_MS - spent))

    def _play_frame(self) -> None:
        anim = self.animation()
        if not anim or not self.player or not anim.aframes:
            self.stop_playback()
            return
        started, done = self._play_clock
        due = int((time.monotonic() - started) * REFRESH.hz(self.project) * self.speed)  # video frames
        running = True
        fired = -1
        while done < due and running:
            running = self.player.advance()
            if self.player.step_started:
                fired = self.player.step
            done += 1
        self._play_clock = (started, done)
        if fired >= 0:
            self._note_fired(anim, fired)
        tick = self.player.position()
        if tick != self.tick or not running:
            self.tick = tick
            self.sequence.ensure_tick_visible(tick)
            if not running:
                self.is_playing = False
                self.timer.Stop()
                follow = self.project.get_animation(anim.next_animation_id) if anim.next_animation_id else None
                if follow is not None and follow.aframes:
                    # Like the game: when this one ends, its follow-up animation takes over.
                    self.select_animation(follow.id)
                    self.toggle_play()
                    app_services.show_status(f"'{anim.name}' ended → '{follow.name}'")
                    return
            self.refresh(inspector=not self.is_playing)
        elif self._fired is not None:
            self._refresh_events()  # let a flash fade while the step holds

    def _on_repeat(self, event: wx.CommandEvent) -> None:
        self.repeat = event.IsChecked()
        if self.player:
            self.player.repeat = self.repeat

    def _on_speed(self, _event: wx.CommandEvent) -> None:
        self.speed = SPEEDS[max(0, self.speed_choice.GetSelection())][1]
        if self.is_playing:
            self._play_clock = (time.monotonic(), 0)

    # ================================================================== selection
    def _sequence_select(self, selection: Set[int], current: int) -> None:
        self.selection = set(selection)
        anim = self.animation()
        if anim and 0 <= current < len(anim.aframes):
            start = ops.step_starts(anim)[current]
            if not (start <= self.tick < start + ops.hold(anim.aframes[current])):
                self.tick = start
            if self.is_playing and self.player:
                self.player.start(current)  # keep playing from the clicked step
                self._play_clock = (time.monotonic(), 0)
        self.refresh()

    def select_steps(self, indices: List[int]) -> None:
        self.selection = set(indices)
        if indices:
            self.seek_step(indices[0])
        else:
            self.refresh()

    def _pick_step_on_stage(self, index: int, additive: bool) -> None:
        if additive:
            self.selection.symmetric_difference_update({index})
            self.refresh()
        else:
            self.selection = {index}
            self.seek_step(index)

    # ================================================================== step edits
    def insert_frames(self, frame_ids: List[str], index: int) -> None:
        frame_ids = [fid for fid in frame_ids if self.project.get_frame(fid)]
        if not frame_ids:
            return
        anim = self.animation()
        if not anim:
            anim = ops.new_animation(self.project)
            self.selected_animation_id = anim.id
            self.refresh_animations()
        with ops.keep_loop_start(anim):
            new = ops.insert_steps(anim, index, [ops.new_step(fid) for fid in frame_ids])
        self.selection = set(new)
        self.tick = ops.step_starts(anim)[new[0]]
        self.sequence.ensure_tick_visible(self.tick)
        self._commit()

    def insert_frame(self, frame_id: str, index: int) -> None:
        self.insert_frames([frame_id], index)

    def insert_frames_after_current(self, frame_ids: List[str]) -> None:
        current = self.current_step()
        self.insert_frames(frame_ids, current + 1 if current >= 0 else 0)

    def insert_frame_after_current(self, frame_id: str) -> None:
        self.insert_frames_after_current([frame_id])

    def new_animation_from_frames(self, frame_ids: List[str]) -> None:
        """A new animation through these frames (in the library's order), one tick each."""
        anim = ops.animation_from_frames(self.project, frame_ids, after_id=self.selected_animation_id)
        if not anim.aframes:
            return
        self._commit()
        self.select_animation(anim.id)
        app_services.show_status(f"New animation '{anim.name}' with {len(anim.aframes)} step(s): Enter plays it")

    def _library_menu(self, frame_ids: List[str], pos: wx.Point) -> None:
        count = len(frame_ids)
        menu = wx.Menu()
        insert = menu.Append(wx.ID_ANY, "Insert After the Current Step" if count == 1
                             else f"Insert {count} Frames After the Current Step")
        new = menu.Append(wx.ID_ANY, "New Animation from Frame" if count == 1 else f"New Animation from {count} Frames")
        menu.Bind(wx.EVT_MENU, lambda e: self.insert_frames_after_current(frame_ids), insert)
        menu.Bind(wx.EVT_MENU, lambda e: self.new_animation_from_frames(frame_ids), new)
        self.library.palette.PopupMenu(menu, pos)
        menu.Destroy()

    def delete_steps(self) -> None:
        anim = self.animation()
        targets = self._targets()
        if not anim or not targets:
            return
        with ops.keep_loop_start(anim):
            removed = ops.delete_steps(anim, targets)
        self.selection = set()
        if anim.aframes:
            index = min(targets[0], len(anim.aframes) - 1)
            self.tick = ops.step_starts(anim)[index]
        self._commit()
        app_services.show_status(f"Deleted {removed} step(s)")

    def move_steps(self, indices: List[int], insert_at: int, copy: bool) -> None:
        anim = self.animation()
        if not anim or not indices:
            return
        with ops.keep_loop_start(anim):
            if copy:
                new = ops.paste_steps(anim, insert_at, ops.copy_steps(anim, indices))
            else:
                new = ops.move_steps(anim, indices, insert_at)
        if not new:
            return
        self.selection = set(new)
        self.tick = ops.step_starts(anim)[new[0]]
        self._commit()

    def reverse_steps(self) -> None:
        anim = self.animation()
        if not anim:
            return
        with ops.keep_loop_start(anim):
            ops.reverse_steps(anim, sorted(self.selection))
        self._commit()

    def change_hold(self, delta: int) -> None:
        anim = self.animation()
        targets = self._targets()
        if anim and targets:
            ops.change_hold(anim, targets, delta)
            self._commit()

    def set_hold(self, ticks: int) -> None:
        anim = self.animation()
        targets = self._targets()
        if anim and targets:
            ops.set_hold(anim, targets, ticks)
            self._commit()

    def spread_selected(self, kind: str) -> None:
        """Hold ▸ Spread: a hold pattern over the selected steps."""
        anim = self.animation()
        targets = self._targets()
        if anim and len(targets) > 1:
            steps = ops.spread(anim, targets, kind)
            self.selection = set(steps)
            self._commit()
            app_services.show_status("Holds " + "-".join(str(ops.hold(anim.aframes[i])) for i in steps))

    def flip_selected(self, axis: str) -> None:
        anim = self.animation()
        targets = self._targets()
        if anim and targets:
            ops.toggle_flip(anim, targets, axis)
            self._commit()

    def rotate_selected(self, degrees: int) -> None:
        anim = self.animation()
        targets = self._targets()
        if anim and targets:
            ops.rotate_steps(anim, targets, degrees)
            self._commit()

    def nudge_selected(self, dx: int, dy: int) -> None:
        anim = self.animation()
        targets = self._targets()
        if anim and targets:
            mx, my = self._mirror()
            ops.nudge(anim, targets, -dx if mx else dx, -dy if my else dy)
            self.refresh()

    def _on_step_field(self, field: str, value: Any) -> None:
        anim = self.animation()
        targets = sorted(self.selection)
        if not anim or not targets:
            return
        if field == "hold":
            ops.set_hold(anim, targets, int(value))
        elif field == "spread":
            self.spread_selected(str(value))
            return
        elif field in ("x", "y"):
            af = anim.aframes[targets[0]]
            x, y = af.offset
            af.offset = (int(value), int(y)) if field == "x" else (int(x), int(value))
        elif field in ("flip_x", "flip_y"):
            ops.set_flip(anim, targets, field[-1], bool(value))
        elif field == "rotate":
            ops.rotate_steps(anim, targets, int(value))
        self._commit()

    def _pick_frame_for_selection(self) -> None:
        from ui.scene_editor.inspector import SourcePickerDialog

        anim = self.animation()
        targets = sorted(self.selection)
        if not anim or not targets:
            return
        current = ("frame", anim.aframes[targets[0]].frame_id)
        with SourcePickerDialog(self, self.project, current, allow_none=False, kinds=("frame",), title="Choose Frame") as dlg:
            if dlg.ShowModal() != wx.ID_OK or not dlg.result:
                return
            frame_id = dlg.result[1]
        for i in targets:
            anim.aframes[i].frame_id = str(frame_id)
        self._commit()

    def _open_frame_of_step(self, index: int) -> None:
        steps = self._steps()
        if 0 <= index < len(steps) and self.on_edit_frame and self.project.get_frame(steps[index].frame_id):
            self.stop_playback()
            self.on_edit_frame(steps[index].frame_id)

    # ---- drags
    def _stage_drag_begin(self) -> None:
        anim = self.animation()
        if not anim or not anim.aframes:
            return
        if not self.selection:
            self.selection = {self.current_step()}
        self._drag_bases = {i: tuple(anim.aframes[i].offset) for i in self.selection if i < len(anim.aframes)}

    def _stage_drag(self, dx: int, dy: int) -> None:
        anim = self.animation()
        if not anim:
            return
        for i, (x, y) in self._drag_bases.items():
            if i < len(anim.aframes):
                anim.aframes[i].offset = (int(x) + dx, int(y) + dy)
        self.refresh(sequence=False)
        app_services.show_status(f"Offset moved by {dx:+d}, {dy:+d}")

    def _stage_drag_end(self, moved: bool) -> None:
        self._drag_bases = {}
        if moved:
            self._commit()
        else:
            self.refresh()

    def _hold_drag_begin(self, index: int) -> None:
        anim = self.animation()
        if not anim:
            return
        targets = sorted(self.selection) or [index]
        self._hold_bases = {i: ops.hold(anim.aframes[i]) for i in targets if i < len(anim.aframes)}

    def _hold_drag(self, delta: int) -> None:
        anim = self.animation()
        if not anim:
            return
        for i, base in self._hold_bases.items():
            anim.aframes[i].duration_frames = max(1, base + delta)
        self.refresh(stage=False)
        first = next(iter(self._hold_bases), None)
        if first is not None:
            app_services.show_status(f"Hold: {ops.hold(anim.aframes[first])} tick(s)")

    # ================================================================== context menu
    def _sequence_menu(self, index: int, pos: wx.Point) -> None:
        anim = self.animation()
        if not anim:
            return
        menu = wx.Menu()

        def add(label: str, handler: Callable[[], None], enabled: bool = True, target: Optional[wx.Menu] = None) -> None:
            item = (target or menu).Append(wx.ID_ANY, label)
            item.Enable(enabled)
            self.Bind(wx.EVT_MENU, lambda e: handler(), item)

        has = index >= 0
        if has:
            holds = wx.Menu()
            for ticks in HOLD_PRESETS:
                add(f"{ticks} tick{'s' if ticks != 1 else ''}", lambda t=ticks: self.set_hold(t), target=holds)
            holds.AppendSeparator()
            for label, kind in ops.SPREADS:
                add(f"Spread {label}", lambda k=kind: self.spread_selected(k), len(self._targets()) > 1, target=holds)
            menu.AppendSubMenu(holds, "Hold")
            add("Flip H\tH", lambda: self.flip_selected("x"))
            add("Flip V\tV", lambda: self.flip_selected("y"))
            add("Rotate 90° CW\tR", lambda: self.rotate_selected(90))
            add("Rotate 90° CCW\tShift+R", lambda: self.rotate_selected(-90))
            add("Reset offset", self._reset_offsets)
            menu.AppendSeparator()
            add("Swap frame…", self._pick_frame_for_selection)
            add("Edit frame in Frames tab", lambda: self._open_frame_of_step(index), len(self.selection) <= 1)
            menu.AppendSeparator()
            if anim.playback_type == "loop" and len(anim.aframes) > 1:
                add("Loop from this step", lambda: self._on_animation_field("loop_start", index),
                    index != ops.loop_start(anim))
            events = wx.Menu()
            for etype in self.project.event_types:
                add(etype.name, lambda t=etype.id: self._on_event_field("add_id", t, 0), target=events)
            if self.project.event_types:
                events.AppendSeparator()
            add("New event…", self._new_event_for_selection, target=events)
            menu.AppendSubMenu(events, "Add event")
            if any(af.events for af in (anim.aframes[i] for i in self._targets())):
                add("Remove events", self._remove_all_events)
            menu.AppendSeparator()
            add("Duplicate", self.edit_duplicate)
            add("Copy", self.edit_copy)
        add("Paste", self.edit_paste, bool(_STEP_CLIPBOARD))
        if has:
            add("Reverse order", self.reverse_steps, len(self.selection) > 1)
            menu.AppendSeparator()
            add("Delete", self.delete_steps)
        self.sequence.PopupMenu(menu, pos)
        menu.Destroy()

    def _reset_offsets(self) -> None:
        anim = self.animation()
        for i in self._targets():
            if anim and i < len(anim.aframes):
                anim.aframes[i].offset = (0, 0)
        self._commit()

    # ================================================================== events
    def _on_event_field(self, action: str, key: str, value: Any) -> None:
        """Inspector / menu: add (by name, or by type id), remove or set the value of an event on the steps."""
        anim = self.animation()
        targets = self._targets()
        if not anim or not targets:
            return
        if action == "add":
            etype = ops.ensure_event_type(self.project, str(key))
            if etype is None:
                return
            added = ops.add_event(anim, targets, etype.id, int(value or 0))
            app_services.show_status(f"Event '{etype.name}' on {added} step(s)")
        elif action == "add_id":
            ops.add_event(anim, targets, str(key), int(value or 0))
        elif action == "remove":
            ops.remove_event(anim, targets, str(key))
        elif action == "value":
            ops.set_event_value(anim, targets, str(key), int(value))
        self.selection = set(targets)
        self._commit()

    def _new_event_for_selection(self) -> None:
        with wx.TextEntryDialog(self, "Name of the new event (e.g. hit_on, sfx, footstep):", "New Event") as dlg:
            if dlg.ShowModal() == wx.ID_OK and dlg.GetValue().strip():
                self._on_event_field("add", dlg.GetValue().strip(), 0)

    def _remove_all_events(self) -> None:
        anim = self.animation()
        if not anim:
            return
        for i in self._targets():
            anim.aframes[i].events = []
        self._commit()

    def manage_event_types(self) -> None:
        from ui.animation_editor.events_dialog import EventTypesDialog

        with EventTypesDialog(self, self.project) as dlg:
            dlg.ShowModal()
            changed = dlg.changed
        if changed:
            self._commit()

    # ================================================================== edit menu
    def edit_copy(self) -> None:
        anim = self.animation()
        if anim and self._targets():
            _STEP_CLIPBOARD[:] = ops.copy_steps(anim, self._targets())
            app_services.show_status(f"Copied {len(_STEP_CLIPBOARD)} step(s)")

    def edit_cut(self) -> None:
        self.edit_copy()
        self.delete_steps()

    def edit_paste(self) -> None:
        anim = self.animation()
        if not anim or not _STEP_CLIPBOARD:
            return
        targets = self._targets()
        index = targets[-1] + 1 if targets else len(anim.aframes)
        with ops.keep_loop_start(anim):
            new = ops.paste_steps(anim, index, _STEP_CLIPBOARD)
        self.selection = set(new)
        self.tick = ops.step_starts(anim)[new[0]]
        self.refresh()

    def edit_duplicate(self) -> None:
        anim = self.animation()
        if not anim or not self._targets():
            return
        with ops.keep_loop_start(anim):
            new = ops.duplicate_steps(anim, self._targets())
        self.selection = set(new)
        self.tick = ops.step_starts(anim)[new[0]]
        self.refresh()

    def edit_select_all(self) -> None:
        anim = self.animation()
        if anim:
            self.selection = set(range(len(anim.aframes)))
            self.refresh()

    # ================================================================== GIF
    def export_gif(self) -> None:
        anim = self.animation()
        if not anim or not anim.aframes:
            app_services.show_status("Select an animation with steps to export a GIF")
            return
        mapping, swap = self.project.active_mapping, self.project.active_palette_swap
        drawn = (f"the mapping {mapping.name}" if mapping else "the original modules") + (
            f" and the palette swap {swap.name}" if swap else "")
        with wx.FileDialog(self, f"Export GIF, drawn with {drawn}", defaultFile=f"{anim.name}.gif",
                           wildcard="GIF files (*.gif)|*.gif",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            count = export_gif(self.project, anim, path, mapping, self._mirror(), swap=swap)
        except Exception as exc:  # disk full, permissions, Pillow missing …
            wx.MessageBox(f"Could not write the GIF:\n{exc}", "Export GIF", wx.OK | wx.ICON_ERROR, self)
            return
        app_services.show_status(f"Exported {count} frame(s) to {path}")

    # ================================================================== keyboard
    def _on_toggle_collision(self, checked: bool) -> None:
        self.stage.show_collision = checked
        self.stage.Refresh(False)

    def _on_toggle_points(self, checked: bool) -> None:
        self.stage.show_points = checked
        self.stage.Refresh(False)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if not self.IsShownOnScreen() or app_services.text_entry_has_focus():
            event.Skip()
            return
        if event.CmdDown() or event.ControlDown() or event.AltDown():
            event.Skip()
            return
        code = event.GetKeyCode()
        shift = event.ShiftDown()
        focus = wx.Window.FindFocus()
        if focus is self.browser.list and code in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_DELETE, wx.WXK_BACK, wx.WXK_F2):
            event.Skip()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.toggle_play()
        elif code in (ord(","), ord("<")):
            self.step_tick(-1) if shift else self.step(-1)
        elif code in (ord("."), ord(">")):
            self.step_tick(1) if shift else self.step(1)
        elif code == wx.WXK_HOME:
            self.seek_step(0)
        elif code == wx.WXK_END:
            self.seek_step(len(self._steps()) - 1)
        elif code == ord("["):
            self.change_hold(-1)
        elif code == ord("]"):
            self.change_hold(1)
        elif code == ord("H"):
            self.flip_selected("x")
        elif code == ord("V"):
            self.flip_selected("y")
        elif code == ord("R"):
            self.rotate_selected(-90 if shift else 90)
        elif code in (wx.WXK_DELETE, wx.WXK_BACK):
            self.delete_steps()
        elif code == wx.WXK_ESCAPE:
            self.selection = set()
            self.refresh()
        elif code in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN) and focus is self.stage:
            step = 8 if shift else 1
            self.nudge_selected({wx.WXK_LEFT: -step, wx.WXK_RIGHT: step}.get(code, 0),
                                {wx.WXK_UP: -step, wx.WXK_DOWN: step}.get(code, 0))
            app_services.request_checkpoint()
        elif code in (wx.WXK_LEFT, wx.WXK_RIGHT) and focus is self.sequence:
            if shift:
                self._extend_selection(-1 if code == wx.WXK_LEFT else 1)
            else:
                self.step(-1 if code == wx.WXK_LEFT else 1)
                current = self.current_step()
                self.selection = {current} if current >= 0 else set()
                self.refresh()
        else:
            event.Skip()

    def _extend_selection(self, delta: int) -> None:
        anim = self.animation()
        if not anim or not anim.aframes:
            return
        current = self.current_step()
        target = max(0, min(current + delta, len(anim.aframes) - 1))
        self.selection |= {current, target}
        self.seek_step(target)
