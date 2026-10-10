"""Inspector: the animation's settings and tools, plus the selected step(s)."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

import wx

from models import AFrame, Animation, Project
from ui.animation_editor import ops


def _section(parent: wx.Window, sizer: wx.BoxSizer, title: str) -> Tuple[wx.Panel, wx.FlexGridSizer, wx.StaticText]:
    panel = wx.Panel(parent)
    outer = wx.BoxSizer(wx.VERTICAL)
    label = wx.StaticText(panel, label=title.upper())
    font = label.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    font.SetPointSize(max(8, font.GetPointSize() - 1))
    label.SetFont(font)
    label.SetForegroundColour(wx.Colour(150, 156, 170))
    outer.Add(label, 0, wx.LEFT | wx.TOP, 2)
    outer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 4)
    grid = wx.FlexGridSizer(0, 2, 6, 8)
    grid.AddGrowableCol(1, 1)
    outer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)
    panel.SetSizer(outer)
    sizer.Add(panel, 0, wx.EXPAND | wx.ALL, 6)
    return panel, grid, label


def _row(grid: wx.FlexGridSizer, parent: wx.Window, label: str, item: Any) -> wx.StaticText:
    text = wx.StaticText(parent, label=label)
    grid.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(item, 1, wx.EXPAND)
    return text


def _hbox(*items: Any, gap: int = 4) -> wx.BoxSizer:
    box = wx.BoxSizer(wx.HORIZONTAL)
    for item in items:
        if isinstance(item, int):
            box.AddSpacer(item)
        elif isinstance(item, str):
            box.AddStretchSpacer(1)
        else:
            box.Add(item, 1 if isinstance(item, (wx.Button, wx.ToggleButton)) else 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, gap)
    return box


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

        root = wx.BoxSizer(wx.VERTICAL)
        self.hint = wx.StaticText(self, label="")
        self.hint.SetForegroundColour(wx.Colour(150, 156, 170))
        root.Add(self.hint, 0, wx.ALL, 8)

        # --- Animation
        self.anim_panel, grid, _ = _section(self, root, "Animation")
        p = self.anim_panel
        self.name = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        _row(grid, p, "Name", self.name)
        self.playback = wx.Choice(p, choices=[label for label, _ in ops.PLAYBACK_MODES])
        self.playback.SetToolTip(
            "Loop: start → end, again.  Play once: stops on the last step.\n"
            "Ping-pong: forward, then back.  Loop backwards: end → start, again."
        )
        _row(grid, p, "Playback", self.playback)
        self.loops = wx.SpinCtrl(p, min=0, max=999, initial=0, size=(64, -1))
        self.loops.SetToolTip("How many times a looping animation repeats before it stops. 0 = forever.")
        self.loops_info = wx.StaticText(p, label="times (0 = forever)")
        self.loops_label = _row(grid, p, "Repeat", _hbox(self.loops, self.loops_info))
        self.fps = wx.SpinCtrl(p, min=1, max=60, initial=10, size=(64, -1))
        self.fps.SetToolTip(
            "Ticks per second: one tick of hold lasts 1/rate seconds.\n"
            "The SGDK export converts holds to 60 Hz frames (10 ticks/s = 6 frames per tick)."
        )
        self.fps_info = wx.StaticText(p, label="ticks / s")
        self.tick_ms = wx.StaticText(p, label="")
        self.tick_ms.SetForegroundColour(wx.Colour(150, 156, 170))
        _row(grid, p, "Tick rate", _hbox(self.fps, self.fps_info))
        grid.Add((0, 0))
        grid.Add(self.tick_ms, 0)
        self.length = wx.StaticText(p, label="")
        _row(grid, p, "Length", self.length)
        self.usage = wx.StaticText(p, label="")
        self.usage.SetForegroundColour(wx.Colour(150, 156, 170))
        _row(grid, p, "Used in", self.usage)
        self.budget_info = wx.StaticText(p, label="")
        self.budget_info.SetToolTip("The step that needs the most hardware sprites (view bar ▸ Budget)")
        self.budget_label = _row(grid, p, "Budget", self.budget_info)
        self.btn_mirror_h = wx.Button(p, label="Mirror H", style=wx.BU_EXACTFIT)
        self.btn_mirror_v = wx.Button(p, label="Mirror V", style=wx.BU_EXACTFIT)
        self.btn_mirror_h.SetToolTip("Mirror every step and its motion horizontally (e.g. turn a walk to face left)")
        self.btn_mirror_v.SetToolTip("Mirror every step and its motion vertically")
        _row(grid, p, "Whole", _hbox(self.btn_mirror_h, self.btn_mirror_v, gap=2))
        self.btn_rot_ccw = wx.Button(p, label="↺ 90°", style=wx.BU_EXACTFIT)
        self.btn_rot_cw = wx.Button(p, label="↻ 90°", style=wx.BU_EXACTFIT)
        self.btn_reverse = wx.Button(p, label="Reverse", style=wx.BU_EXACTFIT)
        self.btn_rot_ccw.SetToolTip("Rotate every step and its motion 90° counter-clockwise")
        self.btn_rot_cw.SetToolTip("Rotate every step and its motion 90° clockwise")
        self.btn_reverse.SetToolTip("Play the steps in reverse order (the selected steps, or all)")
        grid.Add((0, 0))
        grid.Add(_hbox(self.btn_rot_ccw, self.btn_rot_cw, self.btn_reverse, gap=2), 1, wx.EXPAND)
        self.btn_gif = wx.Button(p, label="Export GIF…", style=wx.BU_EXACTFIT)
        self.btn_gif.SetToolTip("Save one cycle as an animated GIF (uses the mirror preview and the preview mapping)")
        grid.Add((0, 0))
        grid.Add(self.btn_gif, 0)

        # --- Step(s)
        self.step_panel, grid, self.step_title = _section(self, root, "Step")
        p = self.step_panel
        self.frame_btn = wx.Button(p, label="", style=wx.BU_EXACTFIT)
        self.frame_btn.SetToolTip("Show a different frame in this step")
        self.btn_edit_frame = wx.Button(p, label="Edit…", style=wx.BU_EXACTFIT)
        self.btn_edit_frame.SetToolTip("Open this frame in the Frames tab (or double-click the step)")
        self.frame_label = _row(grid, p, "Frame", _hbox(self.frame_btn, self.btn_edit_frame, gap=2))
        self.hold = wx.SpinCtrl(p, min=1, max=999, initial=1, size=(64, -1))
        self.hold.SetToolTip("How many ticks this step stays on screen. Drag a step's right edge in the sequence, or press [ / ].")
        self.hold_info = wx.StaticText(p, label="")
        _row(grid, p, "Hold", _hbox(self.hold, self.hold_info))
        self.off_x = wx.SpinCtrl(p, min=-4096, max=4096, initial=0, size=(64, -1))
        self.off_y = wx.SpinCtrl(p, min=-4096, max=4096, initial=0, size=(64, -1))
        self.offset_label = _row(grid, p, "Offset", _hbox(wx.StaticText(p, label="X"), self.off_x, 6, wx.StaticText(p, label="Y"), self.off_y))
        self.offset_label.SetToolTip("Where this step's frame origin sits (root motion). Drag on the stage or use the arrow keys.")
        self.rot_ccw = wx.Button(p, label="↺ 90°", style=wx.BU_EXACTFIT)
        self.rot_cw = wx.Button(p, label="↻ 90°", style=wx.BU_EXACTFIT)
        self.rot_value = wx.StaticText(p, label="0°")
        _row(grid, p, "Rotation", _hbox(self.rot_ccw, self.rot_cw, self.rot_value, gap=2))
        self.flip_h = wx.ToggleButton(p, label="Flip H")
        self.flip_v = wx.ToggleButton(p, label="Flip V")
        self.flip_h.SetToolTip("Mirror this step's frame horizontally in place (H)")
        self.flip_v.SetToolTip("Mirror this step's frame vertically in place (V)")
        _row(grid, p, "Mirror", _hbox(self.flip_h, self.flip_v, gap=2))
        self.step_hint = wx.StaticText(p, label="")
        self.step_hint.SetForegroundColour(wx.Colour(150, 156, 170))
        grid.Add((0, 0))
        grid.Add(self.step_hint, 0)

        self.SetSizer(root)
        # Let everything shrink with the pane (macOS truncates button text natively).
        for ctrl in (self.playback, self.frame_btn, self.flip_h, self.flip_v, self.btn_mirror_h, self.btn_mirror_v,
                     self.btn_rot_ccw, self.btn_rot_cw, self.btn_reverse, self.rot_ccw, self.rot_cw, self.btn_edit_frame):
            ctrl.SetMinSize((40, -1))
        for spin in (self.loops, self.fps, self.hold, self.off_x, self.off_y):
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
            self.hint.SetLabel("" if animation else "Select an animation in the list, or click + New.")
            self.hint.Show(animation is None)
            self.anim_panel.Show(animation is not None)
            self.step_panel.Show(bool(self.indices))
            if animation is not None:
                self._fill_animation(animation)
            if self.indices:
                self._fill_steps(animation, self.indices)
            self.Layout()
            self.FitInside()
        finally:
            self.Thaw()
            self._updating = False

    def _fill_animation(self, anim: Animation) -> None:
        if not self.name.HasFocus():
            self.name.ChangeValue(anim.name)
        self.playback.SetSelection(next((i for i, (_l, k) in enumerate(ops.PLAYBACK_MODES) if k == anim.playback_type), 0))
        repeating = anim.playback_type in ops.REPEATING_MODES
        self.loops.SetValue(int(anim.loop_count or 0))
        for ctrl in (self.loops, self.loops_info, self.loops_label):
            ctrl.Show(repeating)
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


def _short(text: str, limit: int = 26) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
