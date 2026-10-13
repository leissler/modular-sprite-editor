"""Inspector: the animation's settings and tools, plus the selected step(s)."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

import wx

from models import AFrame, Animation, Project
from ui import first_steps
from ui.animation_editor import ops
from ui.components.inspector_kit import hbox, relayout, row, section


class AnimationInspector(wx.ScrolledWindow):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.SetScrollRate(0, 12)
        self.SetMinSize((280, -1))
        self.project: Optional[Project] = None
        self.animation: Optional[Animation] = None
        self.indices: List[int] = []
        self.budget: Optional[Tuple[str, bool]] = None
        self._updating = False

        # Callbacks (set by the panel)
        self.on_animation_change: Optional[Callable[[str, Any], None]] = None  # name / playback / loops / fps
        self.on_animation_tool: Optional[Callable[[str], None]] = None  # mirror_x / mirror_y / rot_cw / rot_ccw / reverse / gif
        self.on_step_change: Optional[Callable[[str, Any], None]] = None  # hold / x / y / flip_x / flip_y / rotate
        self.on_pick_frame: Optional[Callable[[], None]] = None
        self.on_open_frame: Optional[Callable[[], None]] = None
        self.on_event_change: Optional[Callable[[str, str, Any], None]] = None  # (add|remove|value, name or type id, value)
        self.on_manage_events: Optional[Callable[[], None]] = None
        self._event_rows_key: Any = None
        self._event_names_key: Any = None
        self._event_spins: dict = {}
        self._next_ids: List[Optional[str]] = [None]
        self._next_key: Any = None

        root = wx.BoxSizer(wx.VERTICAL)
        self.hint = wx.StaticText(self, label="")
        self.hint.SetForegroundColour(wx.Colour(150, 156, 170))
        root.Add(self.hint, 0, wx.ALL, 8)

        # --- Animation
        self.anim_panel, grid, _ = section(self, root, "Animation", "Animations")
        p = self.anim_panel.body
        self.name = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        row(grid, p, "Name", self.name)
        self.playback = wx.Choice(p, choices=[label for label, _ in ops.PLAYBACK_MODES])
        self.playback.SetToolTip(
            "Loop: start → end, again.  Play once: stops on the last step.\n"
            "Ping-pong: forward, then back.  Loop backwards: end → start, again."
        )
        row(grid, p, "Playback", self.playback)
        self.loops = wx.SpinCtrl(p, min=0, max=999, initial=0, size=(64, -1))
        self.loops.SetToolTip("How many times a looping animation repeats before it stops. 0 = forever.")
        self.loops_info = wx.StaticText(p, label="times (0 = forever)")
        self.loops_label = row(grid, p, "Repeat", hbox(self.loops, self.loops_info))
        self.loop_from = wx.SpinCtrl(p, min=1, max=999, initial=1, size=(64, -1))
        self.loop_from.SetToolTip("Later passes start at this step; the steps before it play once (an intro).")
        self.loop_from_info = wx.StaticText(p, label="step")
        self.loop_from_info.SetToolTip("Steps before it play once (an intro), then the loop repeats from here")
        self.loop_from_label = row(grid, p, "Loop from", hbox(self.loop_from, self.loop_from_info))
        self.next_anim = wx.Choice(p, choices=["— nothing —"])
        self.next_anim.SetToolTip(
            "When this animation ends, continue with another one (e.g. attack → idle).\n"
            "Only animations that end can continue: Play once, or a repeat count above 0."
        )
        self.next_info = wx.StaticText(p, label="")
        self.next_info.SetForegroundColour(wx.Colour(150, 156, 170))
        row(grid, p, "Then play", self.next_anim)
        grid.Add((0, 0))
        grid.Add(self.next_info, 0)
        self.fps = wx.SpinCtrl(p, min=1, max=60, initial=10, size=(64, -1))
        self.fps.SetToolTip(
            "Ticks per second: one tick of hold lasts 1/rate seconds.\n"
            "The SGDK export converts holds to 60 Hz frames (10 ticks/s = 6 frames per tick)."
        )
        self.fps_info = wx.StaticText(p, label="ticks / s")
        self.tick_ms = wx.StaticText(p, label="")
        self.tick_ms.SetForegroundColour(wx.Colour(150, 156, 170))
        row(grid, p, "Tick rate", hbox(self.fps, self.fps_info))
        grid.Add((0, 0))
        grid.Add(self.tick_ms, 0)
        self.length = wx.StaticText(p, label="")
        row(grid, p, "Length", self.length)
        self.usage = wx.StaticText(p, label="")
        self.usage.SetForegroundColour(wx.Colour(150, 156, 170))
        row(grid, p, "Used in", self.usage)
        self.budget_info = wx.StaticText(p, label="")
        self.budget_info.SetToolTip(
            "The step that needs the most hardware sprites, and the tiles of video memory all steps need together "
            "(each part image once, also when it is flipped or used again) (view bar ▸ Budget)"
        )
        self.budget_label = row(grid, p, "Budget", self.budget_info)
        self.btn_mirror_h = wx.Button(p, label="Mirror H", style=wx.BU_EXACTFIT)
        self.btn_mirror_v = wx.Button(p, label="Mirror V", style=wx.BU_EXACTFIT)
        self.btn_mirror_h.SetToolTip("Mirror every step and its motion horizontally (e.g. turn a walk to face left)")
        self.btn_mirror_v.SetToolTip("Mirror every step and its motion vertically")
        row(grid, p, "Whole", hbox(self.btn_mirror_h, self.btn_mirror_v, gap=2))
        self.btn_rot_ccw = wx.Button(p, label="↺ 90°", style=wx.BU_EXACTFIT)
        self.btn_rot_cw = wx.Button(p, label="↻ 90°", style=wx.BU_EXACTFIT)
        self.btn_reverse = wx.Button(p, label="Reverse", style=wx.BU_EXACTFIT)
        self.btn_rot_ccw.SetToolTip("Rotate every step and its motion 90° counter-clockwise")
        self.btn_rot_cw.SetToolTip("Rotate every step and its motion 90° clockwise")
        self.btn_reverse.SetToolTip("Play the steps in reverse order (the selected steps, or all)")
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_rot_ccw, self.btn_rot_cw, self.btn_reverse, gap=2), 1, wx.EXPAND)
        self.btn_gif = wx.Button(p, label="Export GIF…", style=wx.BU_EXACTFIT)
        self.btn_gif.SetToolTip("Save one cycle as an animated GIF (uses the mirror preview and the preview mapping)")
        grid.Add((0, 0))
        grid.Add(self.btn_gif, 0)

        # --- Step(s)
        self.step_panel, grid, self.step_title = section(self, root, "Step", "Animations")
        p = self.step_panel.body
        self.frame_btn = wx.Button(p, label="", style=wx.BU_EXACTFIT)
        self.frame_btn.SetToolTip("Show a different frame in this step")
        self.btn_edit_frame = wx.Button(p, label="Edit…", style=wx.BU_EXACTFIT)
        self.btn_edit_frame.SetToolTip("Open this frame in the Frames tab (or double-click the step)")
        self.frame_label = row(grid, p, "Frame", hbox(self.frame_btn, self.btn_edit_frame, gap=2))
        self.hold = wx.SpinCtrl(p, min=1, max=999, initial=1, size=(64, -1))
        self.hold.SetToolTip("How many ticks this step stays on screen. Drag a step's right edge in the sequence, or press [ / ].")
        self.hold_info = wx.StaticText(p, label="")
        row(grid, p, "Hold", hbox(self.hold, self.hold_info))
        self.off_x = wx.SpinCtrl(p, min=-4096, max=4096, initial=0, size=(64, -1))
        self.off_y = wx.SpinCtrl(p, min=-4096, max=4096, initial=0, size=(64, -1))
        self.offset_label = row(grid, p, "Offset", hbox(wx.StaticText(p, label="X"), self.off_x, 6, wx.StaticText(p, label="Y"), self.off_y))
        self.offset_label.SetToolTip("Where this step's frame origin sits (root motion). Drag on the stage or use the arrow keys.")
        self.rot_ccw = wx.Button(p, label="↺ 90°", style=wx.BU_EXACTFIT)
        self.rot_cw = wx.Button(p, label="↻ 90°", style=wx.BU_EXACTFIT)
        self.rot_value = wx.StaticText(p, label="0°")
        row(grid, p, "Rotation", hbox(self.rot_ccw, self.rot_cw, self.rot_value, gap=2))
        self.flip_h = wx.ToggleButton(p, label="Flip H")
        self.flip_v = wx.ToggleButton(p, label="Flip V")
        self.flip_h.SetToolTip("Mirror this step's frame horizontally in place (H)")
        self.flip_v.SetToolTip("Mirror this step's frame vertically in place (V)")
        row(grid, p, "Mirror", hbox(self.flip_h, self.flip_v, gap=2))
        self.events_box = wx.BoxSizer(wx.VERTICAL)
        self.events_empty = wx.StaticText(p, label="none")
        self.events_empty.SetForegroundColour(wx.Colour(150, 156, 170))
        self.events_box.Add(self.events_empty, 0, wx.BOTTOM, 2)
        self.events_rows = wx.BoxSizer(wx.VERTICAL)
        self.events_box.Add(self.events_rows, 0, wx.EXPAND)
        self.event_name = wx.ComboBox(p, choices=[], style=wx.TE_PROCESS_ENTER)
        self.event_name.SetHint("event name")
        self.event_name.SetToolTip("Pick an event or type a new name (it is added to the project's event list)")
        self.btn_add_event = wx.Button(p, label="Add", style=wx.BU_EXACTFIT)
        add_row = wx.BoxSizer(wx.HORIZONTAL)
        add_row.Add(self.event_name, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        add_row.Add(self.btn_add_event, 0, wx.ALIGN_CENTER_VERTICAL)
        self.events_box.Add(add_row, 0, wx.EXPAND | wx.TOP, 2)
        self.btn_manage_events = wx.Button(p, label="Event types…", style=wx.BU_EXACTFIT)
        self.btn_manage_events.SetToolTip("Rename, recolour or delete the project's event types")
        self.events_box.Add(self.btn_manage_events, 0, wx.TOP, 2)
        events_label = row(grid, p, "Events", self.events_box)
        events_label.SetToolTip(
            "Game events on this step: they fire when the step starts and are active while it shows "
            "(hit windows, sounds, spawns, footsteps). The value is up to the game (e.g. which sound)."
        )
        self.step_hint = wx.StaticText(p, label="")
        self.step_hint.SetForegroundColour(wx.Colour(150, 156, 170))
        grid.Add((0, 0))
        grid.Add(self.step_hint, 0)

        self.SetSizer(root)
        # Let everything shrink with the pane (macOS truncates button text natively).
        for ctrl in (self.playback, self.frame_btn, self.flip_h, self.flip_v, self.btn_mirror_h, self.btn_mirror_v,
                     self.btn_rot_ccw, self.btn_rot_cw, self.btn_reverse, self.rot_ccw, self.rot_cw, self.btn_edit_frame):
            ctrl.SetMinSize((40, -1))
        self.next_anim.SetMinSize((60, -1))
        self.event_name.SetMinSize((60, -1))
        for spin in (self.loops, self.fps, self.hold, self.off_x, self.off_y, self.loop_from):
            spin.SetMinSize((56, -1))
        self._bind()
        self.show(None, None, [])

    def _bind(self) -> None:
        def anim(field: str, value: Any) -> None:
            if not self._updating and self.on_animation_change:
                self.on_animation_change(field, value)

        def step(field: str, value: Any) -> None:
            if not self._updating and self.on_step_change:
                self.on_step_change(field, value)

        def tool(name: str) -> None:
            if self.on_animation_tool:
                self.on_animation_tool(name)

        self.name.Bind(wx.EVT_TEXT_ENTER, lambda e: anim("name", self.name.GetValue().strip()))
        self.name.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), anim("name", self.name.GetValue().strip())))
        self.playback.Bind(wx.EVT_CHOICE, lambda e: anim("playback", ops.PLAYBACK_MODES[self.playback.GetSelection()][1]))
        self.loops.Bind(wx.EVT_SPINCTRL, lambda e: anim("loops", self.loops.GetValue()))
        self.fps.Bind(wx.EVT_SPINCTRL, lambda e: anim("fps", self.fps.GetValue()))
        self.btn_mirror_h.Bind(wx.EVT_BUTTON, lambda e: tool("mirror_x"))
        self.btn_mirror_v.Bind(wx.EVT_BUTTON, lambda e: tool("mirror_y"))
        self.btn_rot_ccw.Bind(wx.EVT_BUTTON, lambda e: tool("rot_ccw"))
        self.btn_rot_cw.Bind(wx.EVT_BUTTON, lambda e: tool("rot_cw"))
        self.btn_reverse.Bind(wx.EVT_BUTTON, lambda e: tool("reverse"))
        self.btn_gif.Bind(wx.EVT_BUTTON, lambda e: tool("gif"))

        self.frame_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_pick_frame and self.on_pick_frame())
        self.btn_edit_frame.Bind(wx.EVT_BUTTON, lambda e: self.on_open_frame and self.on_open_frame())
        self.loop_from.Bind(wx.EVT_SPINCTRL, lambda e: anim("loop_start", self.loop_from.GetValue() - 1))
        self.next_anim.Bind(wx.EVT_CHOICE, lambda e: anim("next", self._next_ids[max(0, self.next_anim.GetSelection())]))

        def add_event(_event=None) -> None:
            name = self.event_name.GetValue().strip()
            if name and self.on_event_change:
                self.on_event_change("add", name, 0)
                self.event_name.SetValue("")

        self.btn_add_event.Bind(wx.EVT_BUTTON, add_event)
        self.event_name.Bind(wx.EVT_TEXT_ENTER, add_event)
        self.event_name.Bind(wx.EVT_COMBOBOX, add_event)
        self.btn_manage_events.Bind(wx.EVT_BUTTON, lambda e: self.on_manage_events and self.on_manage_events())
        self.hold.Bind(wx.EVT_SPINCTRL, lambda e: step("hold", self.hold.GetValue()))
        self.hold.Bind(wx.EVT_TEXT_ENTER, lambda e: step("hold", self.hold.GetValue()))
        for spin, field in ((self.off_x, "x"), (self.off_y, "y")):
            spin.Bind(wx.EVT_SPINCTRL, lambda e, f=field, s=spin: step(f, s.GetValue()))
            spin.Bind(wx.EVT_TEXT_ENTER, lambda e, f=field, s=spin: step(f, s.GetValue()))
        self.rot_ccw.Bind(wx.EVT_BUTTON, lambda e: step("rotate", -90))
        self.rot_cw.Bind(wx.EVT_BUTTON, lambda e: step("rotate", 90))
        self.flip_h.Bind(wx.EVT_TOGGLEBUTTON, lambda e: step("flip_x", self.flip_h.GetValue()))
        self.flip_v.Bind(wx.EVT_TOGGLEBUTTON, lambda e: step("flip_y", self.flip_v.GetValue()))

    # ------------------------------------------------------------------ context
    def show(
        self,
        project: Optional[Project],
        animation: Optional[Animation],
        indices: List[int],
        budget: Optional[Tuple[str, bool]] = None,
    ) -> None:
        """``budget``: (text about the worst step, over the limit?) when the Budget view is on."""
        self.budget = budget
        self.project = project
        self.animation = animation
        self.indices = [i for i in indices if animation and 0 <= i < len(animation.aframes)]
        self._updating = True
        try:
            self.Freeze()
            self.hint.SetLabel("" if animation else
                               first_steps.animations(project) or "Select an animation in the list, or click + New.")
            self.hint.Wrap(260)
            self.hint.Show(animation is None)
            self.anim_panel.Show(animation is not None)
            self.step_panel.Show(bool(self.indices))
            if animation is not None:
                self._fill_animation(animation)
            if self.indices:
                self._fill_steps(animation, self.indices)
            self._order_sections(step_first=bool(self.indices))
            relayout(self)
        finally:
            self.Thaw()
            self._updating = False

    def _order_sections(self, step_first: bool) -> None:
        """While steps are selected their section comes first: the controls used most while timing stay in view."""
        root = self.GetSizer()
        items = [item.GetWindow() for item in root.GetChildren()]
        if (items.index(self.step_panel) < items.index(self.anim_panel)) == step_first:
            return
        root.Detach(self.step_panel)
        anim_at = [item.GetWindow() for item in root.GetChildren()].index(self.anim_panel)
        root.Insert(anim_at if step_first else anim_at + 1, self.step_panel, 0, wx.EXPAND | wx.ALL, 6)

    def _fill_animation(self, anim: Animation) -> None:
        if not self.name.HasFocus():
            self.name.ChangeValue(anim.name)
        self.playback.SetSelection(next((i for i, (_l, k) in enumerate(ops.PLAYBACK_MODES) if k == anim.playback_type), 0))
        repeating = anim.playback_type in ops.REPEATING_MODES
        self.loops.SetValue(int(anim.loop_count or 0))
        for ctrl in (self.loops, self.loops_info, self.loops_label):
            ctrl.Show(repeating)
        looping = anim.playback_type == "loop" and len(anim.aframes) > 1
        self.loop_from.SetRange(1, max(1, len(anim.aframes)))
        self.loop_from.SetValue(ops.loop_start(anim) + 1)
        for ctrl in (self.loop_from, self.loop_from_info, self.loop_from_label):
            ctrl.Show(looping)
        self._fill_next(anim)
        rate = ops.tick_rate(anim)
        self.fps.SetValue(rate)
        self.tick_ms.SetLabel(f"1 tick = {1000.0 / rate:.0f} ms  ·  {60.0 / rate:g} frames at 60 Hz")
        self.length.SetLabel(ops.describe_length(anim))
        uses = ops.scene_usage(self.project, anim.id) if self.project else 0
        self.usage.SetLabel(f"{uses} timeline object{'s' if uses != 1 else ''}" if uses else "no timeline scenes")
        text, over = self.budget if self.budget else ("", False)
        self.budget_info.SetLabel(text)
        self.budget_info.SetForegroundColour(wx.Colour(255, 120, 110) if over else self.length.GetForegroundColour())
        self.budget_info.Wrap(200)
        self.budget_info.Show(bool(text))
        self.budget_label.Show(bool(text))
        has_steps = bool(anim.aframes)
        for btn in (self.btn_mirror_h, self.btn_mirror_v, self.btn_rot_ccw, self.btn_rot_cw, self.btn_reverse, self.btn_gif):
            btn.Enable(has_steps)

    def _fill_steps(self, anim: Animation, indices: List[int]) -> None:
        first: AFrame = anim.aframes[indices[0]]
        single = len(indices) == 1
        if single:
            start = ops.step_starts(anim)[indices[0]]
            title = f"Step {indices[0] + 1} of {len(anim.aframes)}  ·  ticks {start}–{start + ops.hold(first) - 1}"
        else:
            title = f"{len(indices)} steps selected"
        self.step_title.SetLabel(title.upper())
        frame = self.project.get_frame(first.frame_id) if self.project else None
        same_frame = all(anim.aframes[i].frame_id == first.frame_id for i in indices)
        label = (frame.name.strip() or frame.id) if frame and same_frame else ("(different frames)" if not same_frame else "(missing frame)")
        self.frame_btn.SetLabel(_short(label))
        self.btn_edit_frame.Enable(single and frame is not None)
        holds = {ops.hold(anim.aframes[i]) for i in indices}
        self.hold.SetValue(min(holds))
        rate = ops.tick_rate(anim)
        self.hold_info.SetLabel(
            f"ticks = {ops.hold(first) / rate:.2f} s" if len(holds) == 1 else "ticks (mixed: sets all)"
        )
        self.off_x.SetValue(int(first.offset[0]))
        self.off_y.SetValue(int(first.offset[1]))
        for ctrl in (self.off_x, self.off_y):
            ctrl.Enable(single)
        rotations = {int(round(anim.aframes[i].rotation_degrees)) % 360 for i in indices}
        self.rot_value.SetLabel(f"{rotations.pop()}°" if len(rotations) == 1 else "mixed")
        self.flip_h.SetValue(bool(first.flip_x))
        self.flip_v.SetValue(bool(first.flip_y))
        self.step_hint.SetLabel(
            "Drag on the stage or use the arrow keys to move it." if single
            else "Hold, flips and rotation apply to all of them. Drag on the stage or use the arrow keys to move them together."
        )
        self.step_hint.Wrap(190)
        if first.duration_frames < 1 and single:
            self.hold_info.SetLabel("ticks (stored as 0: plays as 1)")
        self._fill_events(anim, indices)


    def _fill_next(self, anim: Animation) -> None:
        others = [a for a in self.project.animations if a.id != anim.id] if self.project else []
        key = tuple((a.id, a.name) for a in others)
        if key != self._next_key:
            self._next_key = key
            self._next_ids = [None] + [a.id for a in others]
            self.next_anim.SetItems(["— nothing —"] + [_short(a.name, 34) for a in others])
        target = anim.next_animation_id if anim.next_animation_id in self._next_ids else None
        self.next_anim.SetSelection(self._next_ids.index(target))
        can_end = ops.can_finish(anim)
        self.next_anim.Enable(can_end or target is not None)
        if not can_end:
            self.next_info.SetLabel("This animation never ends: choose Play once or a repeat count.")
        elif target is not None:
            self.next_info.SetLabel("Starts when this one ends.")
        else:
            self.next_info.SetLabel("")
        self.next_info.Wrap(200)
        self.next_info.Show(bool(self.next_info.GetLabel()))

    def _fill_events(self, anim: Animation, indices: List[int]) -> None:
        project = self.project
        names = tuple(t.name for t in project.event_types) if project else ()
        if names != self._event_names_key:
            self._event_names_key = names
            typed = self.event_name.GetValue()
            self.event_name.SetItems(list(names))
            self.event_name.SetValue(typed)
        events = ops.events_on(anim, indices)
        rows_key = tuple((type_id, count, len(indices)) for type_id, _value, count in events) + (
            tuple((t.id, t.name, tuple(t.color)) for t in project.event_types) if project else (),
        )
        if rows_key != self._event_rows_key:
            self._event_rows_key = rows_key
            self._rebuild_event_rows(events, len(indices))
        for type_id, value, _count in events:
            spin = self._event_spins.get(type_id)
            if spin is not None and not spin.HasFocus():
                spin.SetValue(int(value))
        self.events_empty.Show(not events)

    def _rebuild_event_rows(self, events: List[Tuple[str, int, int]], selected: int) -> None:
        parent = self.step_panel.body
        self.events_rows.Clear(delete_windows=True)
        self._event_spins = {}
        for type_id, value, count in events:
            etype = self.project.get_event_type(type_id) if self.project else None
            swatch = wx.Panel(parent, size=(10, 10))
            swatch.SetBackgroundColour(wx.Colour(*(etype.color if etype else (160, 160, 160))))
            label = (etype.name if etype else "(deleted type)") + (f"  ({count}/{selected})" if count < selected else "")
            name = wx.StaticText(parent, label=_short(label, 18))
            spin = wx.SpinCtrl(parent, min=-32768, max=32767, initial=int(value), size=(56, -1), style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
            spin.SetMinSize((50, -1))
            spin.SetToolTip("Value for the game (e.g. sound or object number); applies to all selected steps that have this event")
            remove = wx.Button(parent, label="×", size=(26, -1), style=wx.BU_EXACTFIT)
            remove.SetToolTip("Remove this event from the selected steps")
            for evt in (wx.EVT_SPINCTRL, wx.EVT_TEXT_ENTER):
                spin.Bind(evt, lambda e, t=type_id, s=spin: self.on_event_change and self.on_event_change("value", t, s.GetValue()))
            remove.Bind(wx.EVT_BUTTON, lambda e, t=type_id: self.on_event_change and self.on_event_change("remove", t, None))
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(swatch, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            row.Add(name, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            row.Add(spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
            row.Add(remove, 0, wx.ALIGN_CENTER_VERTICAL)
            self.events_rows.Add(row, 0, wx.EXPAND | wx.BOTTOM, 2)
            self._event_spins[type_id] = spin


def _short(text: str, limit: int = 26) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
