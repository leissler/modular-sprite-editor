"""Change Animations: one setting for many animations at once (tick rate, playback, repeats, group)."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import wx

from models import Animation, Project
from ui.animation_editor import ops
from ui.components.inspector_kit import dim_text
from ui.dpi import px

ALL_GROUPS = "All groups"
NO_GROUP = "(no group)"


class ChangeAnimationsDialog(wx.Dialog):
    """Pick animations (filter, group, all / none), tick what to change, then Change: the editor applies it as one
    undoable step (``ops.change_animations`` with ``settings()``)."""

    def __init__(self, parent: wx.Window, project: Project, chosen: Sequence[str]):
        super().__init__(parent, title="Change Animations", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.project = project
        self.chosen = {i for i in chosen if project.get_animation(i)}
        self._shown: List[Animation] = []
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label="Tick the animations to change, then the settings they all get.")
        root.Add(intro, 0, wx.ALL, 12)

        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.SearchCtrl(self, size=(px(170), -1))
        self.search.SetDescriptiveText("Filter")
        self.search.ShowCancelButton(True)
        self.group_choice = wx.Choice(self, choices=[ALL_GROUPS] + self._groups() + [NO_GROUP])
        self.group_choice.SetSelection(0)
        bar.Add(self.search, 1, wx.RIGHT, 6)
        bar.Add(self.group_choice, 0)
        root.Add(bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.list = wx.CheckListBox(self, size=(px(440), px(240)))
        root.Add(self.list, 1, wx.EXPAND | wx.ALL, 12)
        picks = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_all = wx.Button(self, label="Tick Shown", style=wx.BU_EXACTFIT)
        self.btn_none = wx.Button(self, label="Untick Shown", style=wx.BU_EXACTFIT)
        self.count = dim_text(self)
        picks.Add(self.btn_all, 0, wx.RIGHT, 4)
        picks.Add(self.btn_none, 0, wx.RIGHT, 10)
        picks.Add(self.count, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(picks, 0, wx.LEFT | wx.RIGHT, 12)

        grid = wx.FlexGridSizer(0, 2, 8, 10)
        self.use_rate = wx.CheckBox(self, label="Tick rate")
        self.rate = wx.SpinCtrl(self, min=1, max=60, initial=10, size=(px(64), -1))
        self.keep_timing = wx.CheckBox(self, label="Keep their timing (scale the holds)")
        self.keep_timing.SetValue(True)
        self.keep_timing.SetToolTip("Each step lasts as long as before, in ticks of the new rate (rounded to whole "
                                    "ticks). Off: the holds stay, so the animations play faster or slower.")
        rate_box = wx.BoxSizer(wx.HORIZONTAL)
        rate_box.Add(self.rate, 0, wx.RIGHT, 6)
        rate_box.Add(wx.StaticText(self, label="ticks / s"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.use_rate, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(rate_box, 0)
        grid.Add((0, 0))
        grid.Add(self.keep_timing, 0)
        self.use_playback = wx.CheckBox(self, label="Playback")
        self.playback = wx.Choice(self, choices=[label for label, _key in ops.PLAYBACK_MODES])
        self.playback.SetSelection(0)
        grid.Add(self.use_playback, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.playback, 0)
        self.use_loops = wx.CheckBox(self, label="Repeat")
        self.loops = wx.SpinCtrl(self, min=0, max=255, initial=0, size=(px(64), -1))
        self.loops.SetToolTip("How often a repeating playback runs before it ends (0 = forever)")
        loops_box = wx.BoxSizer(wx.HORIZONTAL)
        loops_box.Add(self.loops, 0, wx.RIGHT, 6)
        loops_box.Add(wx.StaticText(self, label="times (0 = forever)"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.use_loops, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(loops_box, 0)
        self.use_group = wx.CheckBox(self, label="Group")
        self.group = wx.ComboBox(self, choices=self._groups(), size=(px(170), -1))
        self.group.SetHint("no group")
        self.group.SetToolTip("Where they sit in the Animations list (empty: no group)")
        grid.Add(self.use_group, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.group, 0)
        root.Add(grid, 0, wx.ALL, 12)

        buttons = wx.StdDialogButtonSizer()
        self.btn_ok = wx.Button(self, wx.ID_OK, "Change")
        self.btn_ok.SetDefault()
        buttons.AddButton(self.btn_ok)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL))
        buttons.Realize()
        root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizerAndFit(root)
        self.CenterOnParent()

        first = project.get_animation(next(iter(chosen), "")) if chosen else None
        if first is not None:  # start from the current animation's settings
            self.rate.SetValue(ops.tick_rate(first))
            self.playback.SetSelection(next((i for i, (_l, k) in enumerate(ops.PLAYBACK_MODES)
                                             if k == first.playback_type), 0))
            self.loops.SetValue(int(first.loop_count or 0))
            self.group.SetValue(first.group)
        self.search.Bind(wx.EVT_TEXT, lambda e: self._fill())
        self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.search.SetValue(""))
        self.group_choice.Bind(wx.EVT_CHOICE, lambda e: self._fill())
        self.list.Bind(wx.EVT_CHECKLISTBOX, self._on_tick)
        self.btn_all.Bind(wx.EVT_BUTTON, lambda e: self._tick_shown(True))
        self.btn_none.Bind(wx.EVT_BUTTON, lambda e: self._tick_shown(False))
        # Changing a value ticks its setting.
        for ctrl, use, events in ((self.rate, self.use_rate, (wx.EVT_SPINCTRL, wx.EVT_TEXT)),
                                  (self.loops, self.use_loops, (wx.EVT_SPINCTRL, wx.EVT_TEXT)),
                                  (self.playback, self.use_playback, (wx.EVT_CHOICE,)),
                                  (self.group, self.use_group, (wx.EVT_TEXT, wx.EVT_COMBOBOX))):
            for event in events:
                ctrl.Bind(event, lambda e, u=use: self._use(u))
        for use in (self.use_rate, self.use_playback, self.use_loops, self.use_group, self.keep_timing):
            use.Bind(wx.EVT_CHECKBOX, lambda e: self._update())
        self._fill()

    def _use(self, setting: wx.CheckBox) -> None:
        setting.SetValue(True)
        self._update()

    def _groups(self) -> List[str]:
        return sorted({a.group for a in self.project.animations if a.group}, key=str.lower)

    def _fill(self) -> None:
        text = self.search.GetValue().strip().lower()
        group = self.group_choice.GetStringSelection()
        self._shown = [
            a for a in self.project.animations
            if (not text or text in a.name.lower())
            and (group == ALL_GROUPS or (a.group == "" if group == NO_GROUP else a.group == group))
        ]
        self.list.Set([f"{a.name}   ·   {ops.tick_rate(a)} ticks/s, {ops.playback_label(a.playback_type)}"
                       + (f"   ·   {a.group}" if a.group else "") for a in self._shown])
        for index, anim in enumerate(self._shown):
            self.list.Check(index, anim.id in self.chosen)
        self._update()

    def _on_tick(self, event: wx.CommandEvent) -> None:
        index = event.GetInt()
        if 0 <= index < len(self._shown):
            ident = self._shown[index].id
            (self.chosen.add if self.list.IsChecked(index) else self.chosen.discard)(ident)
        self._update()

    def _tick_shown(self, tick: bool) -> None:
        for index, anim in enumerate(self._shown):
            self.list.Check(index, tick)
            (self.chosen.add if tick else self.chosen.discard)(anim.id)
        self._update()

    def _update(self) -> None:
        total = len(self.project.animations)
        self.count.SetLabel(f"{len(self.chosen)} of {total} ticked")
        self.keep_timing.Enable(self.use_rate.GetValue())
        self.btn_ok.Enable(bool(self.chosen) and any(c.GetValue() for c in (
            self.use_rate, self.use_playback, self.use_loops, self.use_group)))

    def chosen_ids(self) -> List[str]:
        """The ticked animations, in the project's order."""
        return [a.id for a in self.project.animations if a.id in self.chosen]

    def settings(self) -> Dict[str, Optional[object]]:
        """Keyword arguments for ``ops.change_animations``: only what was ticked."""
        return {
            "rate": self.rate.GetValue() if self.use_rate.GetValue() else None,
            "keep_timing": self.keep_timing.GetValue(),
            "playback_type": ops.PLAYBACK_MODES[max(0, self.playback.GetSelection())][1]
            if self.use_playback.GetValue() else None,
            "loop_count": self.loops.GetValue() if self.use_loops.GetValue() else None,
            "group": self.group.GetValue() if self.use_group.GetValue() else None,
        }
