"""Contextual inspector for the scene editor.

Shows only what applies to the current selection:
- nothing selected: scene settings
- an object: name, source, parent, (animation playback), transform at the playhead,
  motion to the next key, and the optional image swap at this key
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import wx

from models import Project, TimelineKeyframe, TimelineObject, TimelineScene, apply_timeline_easing
from ui.scene_editor import ops

SOURCE_TYPE_LABELS = {"none": "Group", "module": "Module", "frame": "Frame", "animation": "Animation"}


class EasingPreview(wx.Panel):
    """Small graph of an easing curve (time → progress)."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, size=(96, 64))
        self.SetMinSize((96, 64))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.easing: Optional[str] = "linear"
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def set_easing(self, easing: Optional[str]) -> None:
        self.easing = easing
        self.Refresh(False)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour(30, 31, 34)))
        dc.Clear()
        w, h = self.GetClientSize()
        pad_x, pad_y = 6, 12
        gw, gh = w - 2 * pad_x, h - 2 * pad_y
        dc.SetPen(wx.Pen(wx.Colour(64, 66, 74)))
        dc.DrawLine(pad_x, pad_y + gh, pad_x + gw, pad_y + gh)
        dc.DrawLine(pad_x, pad_y, pad_x + gw, pad_y)
        if not self.easing:
            return
        points = []
        for i in range(41):
            t = i / 40.0
            v = apply_timeline_easing(self.easing, t)
            points.append(wx.Point(int(pad_x + t * gw), int(pad_y + gh - v * gh)))
        dc.SetPen(wx.Pen(wx.Colour(255, 176, 64), 2))
        dc.DrawLines(points)


class SourcePickerDialog(wx.Dialog):
    """Searchable list of everything an object can show."""

    def __init__(self, parent: wx.Window, project: Project, current: Tuple[str, Optional[str]], allow_none: bool = True):
        super().__init__(parent, title="Choose Source", size=(420, 520), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.project = project
        self.items: List[Tuple[str, Optional[str], str]] = []
        if allow_none:
            self.items.append(("none", None, "Group (no image)"))
        self.items += [("animation", a.id, a.name) for a in project.animations]
        self.items += [("frame", f.id, f.name) for f in project.frames]
        self.items += [("module", m.id, m.name) for m in project.modules]
        self.visible: List[int] = []
        self.result: Optional[Tuple[str, Optional[str]]] = None

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Search animations, frames, modules")
        self.search.ShowCancelButton(True)
        self.listing = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.listing.InsertColumn(0, "Name", width=270)
        self.listing.InsertColumn(1, "Type", width=100)
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self.listing, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(sizer)

        self.search.Bind(wx.EVT_TEXT, lambda e: self._fill())
        self.search.Bind(wx.EVT_TEXT_ENTER, lambda e: self._accept())
        self.listing.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._accept())
        self.Bind(wx.EVT_BUTTON, lambda e: self._accept(), id=wx.ID_OK)
        self._fill(select=current)
        self.CenterOnParent()
        wx.CallAfter(self.search.SetFocus)

    def _fill(self, select: Optional[Tuple[str, Optional[str]]] = None) -> None:
        query = self.search.GetValue().strip().lower()
        self.listing.DeleteAllItems()
        self.visible = []
        for idx, (source_type, source_id, name) in enumerate(self.items):
            if query and query not in name.lower() and query not in source_type:
                continue
            row = self.listing.InsertItem(self.listing.GetItemCount(), name)
            self.listing.SetItem(row, 1, SOURCE_TYPE_LABELS[source_type])
            self.visible.append(idx)
            if select and (source_type, source_id) == select:
                self.listing.Select(row)
                self.listing.EnsureVisible(row)
        if self.listing.GetFirstSelected() == -1 and self.visible:
            self.listing.Select(0)

    def _accept(self) -> None:
        row = self.listing.GetFirstSelected()
        if 0 <= row < len(self.visible):
            source_type, source_id, _name = self.items[self.visible[row]]
            self.result = (source_type, source_id)
            self.EndModal(wx.ID_OK)


def _short(text: str, limit: int = 30) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _section(parent: wx.Window, sizer: wx.BoxSizer, title: str) -> Tuple[wx.Panel, wx.FlexGridSizer]:
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
    return panel, grid


def _row(grid: wx.FlexGridSizer, parent: wx.Window, label: str, item) -> wx.StaticText:
    text = wx.StaticText(parent, label=label)
    grid.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(item, 1, wx.EXPAND)
    return text


class SceneInspector(wx.ScrolledWindow):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.SetScrollRate(0, 12)
        self.SetMinSize((280, -1))
        self.project: Optional[Project] = None
        self.scene: Optional[TimelineScene] = None
        self.obj: Optional[TimelineObject] = None
        self.frame = 0
        self.auto_key = True
        self.selected_key_count = 0
        self.selected_key_ids: Set[str] = set()
        self._updating = False
        self._parent_ids: List[Optional[str]] = []

        # Callbacks: field name -> value
        self.on_scene_change: Optional[Callable[[str, object], None]] = None
        self.on_object_change: Optional[Callable[[str, object], None]] = None
        self.on_transform_change: Optional[Callable[[str, object], None]] = None
        self.on_toggle_key: Optional[Callable[[], None]] = None
        self.on_easing_change: Optional[Callable[[str], None]] = None
        self.on_swap_change: Optional[Callable[[str, object], None]] = None
        self.on_reset_handles: Optional[Callable[[], None]] = None

        root = wx.BoxSizer(wx.VERTICAL)
        self._root = root
        self.hint = wx.StaticText(self, label="")
        self.hint.SetForegroundColour(wx.Colour(150, 156, 170))
        root.Add(self.hint, 0, wx.ALL, 8)

        # --- Scene
        self.scene_panel, g = _section(self, root, "Scene")
        p = self.scene_panel
        self.scene_name = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.scene_fps = wx.SpinCtrl(p, min=1, max=120, initial=12)
        self.scene_length = wx.SpinCtrl(p, min=1, max=100000, initial=120)
        self.scene_length_info = wx.StaticText(p, label="")
        self.scene_loop = wx.CheckBox(p, label="Loop playback")
        self.scene_bg = wx.ColourPickerCtrl(p)
        _row(g, p, "Name", self.scene_name)
        _row(g, p, "Frame rate", self._with_suffix(p, self.scene_fps, "fps"))
        length_row = wx.BoxSizer(wx.HORIZONTAL)
        length_row.Add(self.scene_length, 1, wx.RIGHT, 6)
        length_row.Add(self.scene_length_info, 0, wx.ALIGN_CENTER_VERTICAL)
        _row(g, p, "Length", length_row)
        _row(g, p, "", self.scene_loop)
        _row(g, p, "Background", self.scene_bg)

        # --- Object
        self.object_panel, g = _section(self, root, "Object")
        p = self.object_panel
        self.obj_name = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.obj_source = wx.Button(p, label="", style=wx.BU_LEFT)
        self.obj_source.SetToolTip("What this object shows. Click to choose another source.")
        self.obj_parent = wx.Choice(p)
        self.obj_parent.SetToolTip("Children follow their parent's position, rotation and flips")
        _row(g, p, "Name", self.obj_name)
        _row(g, p, "Shows", self.obj_source)
        _row(g, p, "Parent", self.obj_parent)

        # --- Playback (animation sources)
        self.playback_panel, g = _section(self, root, "Animation playback")
        p = self.playback_panel
        self.pb_mode = wx.Choice(p, choices=["Loop", "Play once", "Ping-pong"])
        self.pb_speed = wx.SpinCtrlDouble(p, min=0.05, max=16.0, initial=1.0, inc=0.25)
        self.pb_speed.SetDigits(2)
        self.pb_offset = wx.SpinCtrl(p, min=-100000, max=100000, initial=0)
        self.pb_offset.SetToolTip("Start the animation this many scene frames in")
        self.pb_root = wx.CheckBox(p, label="Root motion")
        self.pb_root.SetToolTip("Move with the animation's per-frame offsets (as set in the Animations tab)")
        _row(g, p, "Mode", self.pb_mode)
        _row(g, p, "Speed", self._with_suffix(p, self.pb_speed, "×"))
        _row(g, p, "Start offset", self._with_suffix(p, self.pb_offset, "frames"))
        _row(g, p, "", self.pb_root)

        # --- Transform at the playhead
        self.transform_panel, g = _section(self, root, "Transform")
        p = self.transform_panel
        key_row = wx.BoxSizer(wx.HORIZONTAL)
        self.key_button = wx.ToggleButton(p, label="◆", size=(32, -1))
        self.key_button.SetToolTip("Key at this frame (K). Toggle to add or remove it.")
        self.key_state = wx.StaticText(p, label="")
        key_row.Add(self.key_button, 0, wx.RIGHT, 6)
        key_row.Add(self.key_state, 1, wx.ALIGN_CENTER_VERTICAL)
        self.tr_x = wx.SpinCtrl(p, min=-100000, max=100000, initial=0, size=(70, -1))
        self.tr_y = wx.SpinCtrl(p, min=-100000, max=100000, initial=0, size=(70, -1))
        pos_row = wx.BoxSizer(wx.HORIZONTAL)
        pos_row.Add(wx.StaticText(p, label="X"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
        pos_row.Add(self.tr_x, 1, wx.RIGHT, 8)
        pos_row.Add(wx.StaticText(p, label="Y"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
        pos_row.Add(self.tr_y, 1)
        rot_row = wx.BoxSizer(wx.HORIZONTAL)
        self.rot_ccw = wx.Button(p, label="↺ 90°", style=wx.BU_EXACTFIT)
        self.rot_cw = wx.Button(p, label="↻ 90°", style=wx.BU_EXACTFIT)
        self.rot_value = wx.StaticText(p, label="0°")
        self.rot_ccw.SetToolTip("Rotate 90° counter-clockwise (Shift+R)")
        self.rot_cw.SetToolTip("Rotate 90° clockwise (R)")
        rot_row.Add(self.rot_ccw, 0, wx.RIGHT, 4)
        rot_row.Add(self.rot_cw, 0, wx.RIGHT, 8)
        rot_row.Add(self.rot_value, 0, wx.ALIGN_CENTER_VERTICAL)
        flip_row = wx.BoxSizer(wx.HORIZONTAL)
        self.flip_h = wx.ToggleButton(p, label="Flip H")
        self.flip_v = wx.ToggleButton(p, label="Flip V")
        self.flip_h.SetToolTip("Mirror horizontally (H)")
        self.flip_v.SetToolTip("Mirror vertically (V)")
        flip_row.Add(self.flip_h, 1, wx.RIGHT, 4)
        flip_row.Add(self.flip_v, 1)
        self.tr_visible = wx.CheckBox(p, label="Visible")
        _row(g, p, "Key", key_row)
        _row(g, p, "Position", pos_row)
        _row(g, p, "Rotation", rot_row)
        _row(g, p, "Mirror", flip_row)
        _row(g, p, "", self.tr_visible)

        # --- Motion to next key
        self.motion_panel, g = _section(self, root, "Motion to next key")
        p = self.motion_panel
        self.motion_info = wx.StaticText(p, label="")
        self.ease_shape = wx.Choice(p, choices=[label for label, _ in ops.EASING_SHAPES])
        self.ease_shape.SetToolTip("How strongly the motion speeds up / slows down. Hold jumps at the next key.")
        self.ease_dir = wx.Choice(p, choices=[label for label, _ in ops.EASING_DIRECTIONS])
        self.ease_dir.SetToolTip("Ease in: starts slow.  Ease out: ends slow.  In & out: slow at both ends.")
        self.ease_preview = EasingPreview(p)
        ease_box = wx.BoxSizer(wx.VERTICAL)
        ease_box.Add(self.ease_shape, 0, wx.EXPAND | wx.BOTTOM, 4)
        ease_box.Add(self.ease_dir, 0, wx.EXPAND)
        ease_row = wx.BoxSizer(wx.HORIZONTAL)
        ease_row.Add(ease_box, 1, wx.RIGHT, 6)
        ease_row.Add(self.ease_preview, 0)
        self.path_choice = wx.Choice(p, choices=["Straight", "Curved"])
        self.path_choice.SetToolTip("Path shape for this layer's whole motion. Curved paths are shaped with the handles shown on the stage.")
        self.reset_handles = wx.Button(p, label="Reset curve handles", style=wx.BU_EXACTFIT)
        _row(g, p, "", self.motion_info)
        _row(g, p, "Easing", ease_row)
        _row(g, p, "Path", self.path_choice)
        _row(g, p, "", self.reset_handles)

        # --- Image swap at this key
        self.swap_panel, g = _section(self, root, "Swap image at this key")
        p = self.swap_panel
        self.swap_enable = wx.CheckBox(p, label="Swap the image here")
        self.swap_enable.SetToolTip("From this key on, show another animation, frame or module")
        self.swap_source = wx.Button(p, label="", style=wx.BU_LEFT)
        self.swap_off_x = wx.SpinCtrl(p, min=-100000, max=100000, initial=0, size=(70, -1))
        self.swap_off_y = wx.SpinCtrl(p, min=-100000, max=100000, initial=0, size=(70, -1))
        off_row = wx.BoxSizer(wx.HORIZONTAL)
        off_row.Add(wx.StaticText(p, label="X"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
        off_row.Add(self.swap_off_x, 1, wx.RIGHT, 8)
        off_row.Add(wx.StaticText(p, label="Y"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
        off_row.Add(self.swap_off_y, 1)
        _row(g, p, "", self.swap_enable)
        self.swap_source_label = _row(g, p, "Shows", self.swap_source)
        self.swap_offset_label = _row(g, p, "Offset", off_row)

        self.SetSizer(root)
        # Let popups/buttons shrink with the panel (macOS truncates their text natively).
        for ctrl in (self.obj_source, self.obj_parent, self.pb_mode, self.ease_shape, self.ease_dir,
                     self.path_choice, self.swap_source, self.flip_h, self.flip_v):
            ctrl.SetMinSize((60, -1))
        for spin in (self.tr_x, self.tr_y, self.swap_off_x, self.swap_off_y):
            spin.SetMinSize((56, -1))
        self.key_state.SetMinSize((60, -1))
        self._bind()
        self.show_context(None, None, None, 0)

    @staticmethod
    def _with_suffix(parent: wx.Window, ctrl: wx.Window, suffix: str) -> wx.BoxSizer:
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(ctrl, 1, wx.RIGHT, 4)
        row.Add(wx.StaticText(parent, label=suffix), 0, wx.ALIGN_CENTER_VERTICAL)
        return row

    # ------------------------------------------------------------------ binding
    def _emit(self, callback: Optional[Callable], *args) -> None:
        if not self._updating and callback:
            callback(*args)

    def _bind(self) -> None:
        def text_commit(ctrl: wx.TextCtrl, cb_getter, field: str) -> None:
            def commit(event):
                event.Skip()
                self._emit(cb_getter(), field, ctrl.GetValue().strip())
            ctrl.Bind(wx.EVT_TEXT_ENTER, commit)
            ctrl.Bind(wx.EVT_KILL_FOCUS, commit)

        def spin(ctrl, cb_getter, field: str, getter=None) -> None:
            def fire(event):
                event.Skip()
                self._emit(cb_getter(), field, getter() if getter else ctrl.GetValue())
            evt = wx.EVT_SPINCTRLDOUBLE if isinstance(ctrl, wx.SpinCtrlDouble) else wx.EVT_SPINCTRL
            ctrl.Bind(evt, fire)
            ctrl.Bind(wx.EVT_TEXT_ENTER, fire)

        text_commit(self.scene_name, lambda: self.on_scene_change, "name")
        spin(self.scene_fps, lambda: self.on_scene_change, "fps")
        spin(self.scene_length, lambda: self.on_scene_change, "length")
        self.scene_loop.Bind(wx.EVT_CHECKBOX, lambda e: self._emit(self.on_scene_change, "loop", e.IsChecked()))
        self.scene_bg.Bind(
            wx.EVT_COLOURPICKER_CHANGED,
            lambda e: self._emit(self.on_scene_change, "background", tuple(e.GetColour().Get(includeAlpha=False))),
        )

        text_commit(self.obj_name, lambda: self.on_object_change, "name")
        self.obj_source.Bind(wx.EVT_BUTTON, lambda e: self._pick_source("source"))
        self.obj_parent.Bind(wx.EVT_CHOICE, self._on_parent_choice)
        self.pb_mode.Bind(
            wx.EVT_CHOICE,
            lambda e: self._emit(self.on_object_change, "playback_mode", ("loop", "once", "ping_pong")[self.pb_mode.GetSelection()]),
        )
        spin(self.pb_speed, lambda: self.on_object_change, "playback_speed")
        spin(self.pb_offset, lambda: self.on_object_change, "playback_offset_frames")
        self.pb_root.Bind(wx.EVT_CHECKBOX, lambda e: self._emit(self.on_object_change, "root_motion", e.IsChecked()))

        self.key_button.Bind(wx.EVT_TOGGLEBUTTON, lambda e: self._emit(self.on_toggle_key))
        spin(self.tr_x, lambda: self.on_transform_change, "x")
        spin(self.tr_y, lambda: self.on_transform_change, "y")
        self.rot_cw.Bind(wx.EVT_BUTTON, lambda e: self._emit(self.on_transform_change, "rotate", 90))
        self.rot_ccw.Bind(wx.EVT_BUTTON, lambda e: self._emit(self.on_transform_change, "rotate", -90))
        self.flip_h.Bind(wx.EVT_TOGGLEBUTTON, lambda e: self._emit(self.on_transform_change, "flip_x", e.IsChecked()))
        self.flip_v.Bind(wx.EVT_TOGGLEBUTTON, lambda e: self._emit(self.on_transform_change, "flip_y", e.IsChecked()))
        self.tr_visible.Bind(wx.EVT_CHECKBOX, lambda e: self._emit(self.on_transform_change, "visible", e.IsChecked()))

        self.ease_shape.Bind(wx.EVT_CHOICE, self._on_easing_choice)
        self.ease_dir.Bind(wx.EVT_CHOICE, self._on_easing_choice)
        self.path_choice.Bind(
            wx.EVT_CHOICE,
            lambda e: self._emit(self.on_object_change, "path_mode", ("linear", "spline")[self.path_choice.GetSelection()]),
        )
        self.reset_handles.Bind(wx.EVT_BUTTON, lambda e: self._emit(self.on_reset_handles))

        self.swap_enable.Bind(wx.EVT_CHECKBOX, self._on_swap_toggle)
        self.swap_source.Bind(wx.EVT_BUTTON, lambda e: self._pick_source("swap"))
        spin(self.swap_off_x, lambda: self.on_swap_change, "offset",
             lambda: (self.swap_off_x.GetValue(), self.swap_off_y.GetValue()))
        spin(self.swap_off_y, lambda: self.on_swap_change, "offset",
             lambda: (self.swap_off_x.GetValue(), self.swap_off_y.GetValue()))

    def _on_parent_choice(self, _event: wx.CommandEvent) -> None:
        idx = self.obj_parent.GetSelection()
        if 0 <= idx < len(self._parent_ids):
            self._emit(self.on_object_change, "parent", self._parent_ids[idx])

    def _on_easing_choice(self, _event: wx.CommandEvent) -> None:
        shape = ops.EASING_SHAPES[max(0, self.ease_shape.GetSelection())][1]
        direction = ops.EASING_DIRECTIONS[max(0, self.ease_dir.GetSelection())][1]
        easing = ops.join_easing(shape, direction)
        self.ease_dir.Enable(shape not in ("linear", "step"))
        self.ease_preview.set_easing(easing)
        self._emit(self.on_easing_change, easing)

    def _on_swap_toggle(self, event: wx.CommandEvent) -> None:
        if event.IsChecked():
            picked = self._ask_source(("animation", None), allow_none=True)
            if picked is None:
                self._updating = True
                self.swap_enable.SetValue(False)
                self._updating = False
                return
            self._emit(self.on_swap_change, "source", picked)
        else:
            self._emit(self.on_swap_change, "source", None)

    def _ask_source(self, current: Tuple[str, Optional[str]], allow_none: bool = True) -> Optional[Tuple[str, Optional[str]]]:
        if not self.project:
            return None
        with SourcePickerDialog(self, self.project, current, allow_none) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                return dlg.result
        return None

    def _pick_source(self, which: str) -> None:
        if not self.obj:
            return
        if which == "source":
            picked = self._ask_source((self.obj.source_type, self.obj.source_id))
            if picked is not None:
                self._emit(self.on_object_change, "source", picked)
        else:
            key = self._key_here()
            current = (key.source_type or "none", key.source_id) if key else ("none", None)
            picked = self._ask_source(current)
            if picked is not None:
                self._emit(self.on_swap_change, "source", picked)

    # ------------------------------------------------------------------ context
    def _key_here(self) -> Optional[TimelineKeyframe]:
        if not self.obj or not self.scene:
            return None
        return ops.key_at_frame(self.obj, self.frame, self.scene.fps, self.selected_key_ids)

    def show_context(
        self,
        project: Optional[Project],
        scene: Optional[TimelineScene],
        obj: Optional[TimelineObject],
        frame: int,
        auto_key: bool = True,
        selected_key_count: int = 0,
        selected_key_ids: Optional[Iterable[str]] = None,
    ) -> None:
        self.project = project
        self.scene = scene
        self.obj = obj
        self.frame = frame
        self.auto_key = auto_key
        self.selected_key_count = selected_key_count
        self.selected_key_ids = set(selected_key_ids or ())
        self._updating = True
        try:
            self.Freeze()
            self._update_visibility()
            if scene and not obj:
                self._fill_scene()
            if scene and obj:
                self._fill_object()
            self.Layout()
            self.FitInside()
        finally:
            self.Thaw()
            self._updating = False

    def _update_visibility(self) -> None:
        has_scene = self.scene is not None
        has_obj = self.obj is not None
        anim = has_obj and (self.obj.source_type == "animation" or any(k.source_type == "animation" for k in self.obj.keyframes))
        self.hint.SetLabel(
            "Create a scene with + in the scene bar." if not has_scene else
            ("Nothing selected — scene settings. Click an object on the stage or a layer to edit it." if not has_obj else "")
        )
        self.hint.Show(bool(self.hint.GetLabel()))
        self.hint.Wrap(260)
        self.scene_panel.Show(has_scene and not has_obj)
        self.object_panel.Show(has_obj)
        self.playback_panel.Show(bool(anim))
        self.transform_panel.Show(has_obj)
        self.motion_panel.Show(has_obj)
        self.swap_panel.Show(has_obj)

    def _fill_scene(self) -> None:
        scene = self.scene
        if not self.scene_name.HasFocus():
            self.scene_name.ChangeValue(scene.name)
        self.scene_fps.SetValue(scene.fps)
        length = ops.scene_length_frames(scene)
        self.scene_length.SetValue(length)
        self.scene_length_info.SetLabel(f"frames ({scene.duration_seconds:.2f} s)")
        self.scene_loop.SetValue(scene.loop)
        self.scene_bg.SetColour(wx.Colour(*scene.background_color))

    def _fill_object(self) -> None:
        obj, scene, project = self.obj, self.scene, self.project
        fps = scene.fps
        if not self.obj_name.HasFocus():
            self.obj_name.ChangeValue(obj.name)
        self.obj_source.SetLabel(_short(f"{SOURCE_TYPE_LABELS.get(obj.source_type, '?')}: {ops.source_name(project, obj.source_type, obj.source_id)}"))

        # Parent choices: anything that is not this object or below it.
        self._parent_ids = [None]
        labels = ["— none (top level) —"]
        for row_obj, depth, _kids in ops.tree_rows(scene, set()):
            if ops.is_descendant(scene, obj.id, row_obj.id):
                continue
            self._parent_ids.append(row_obj.id)
            labels.append("   " * depth + row_obj.name)
        self.obj_parent.SetItems(labels)
        self.obj_parent.SetSelection(self._parent_ids.index(obj.parent_id) if obj.parent_id in self._parent_ids else 0)

        self.pb_mode.SetSelection({"loop": 0, "once": 1, "ping_pong": 2}.get(obj.playback_mode, 0))
        self.pb_speed.SetValue(obj.playback_speed)
        self.pb_offset.SetValue(int(round(obj.playback_offset * fps)))
        self.pb_root.SetValue(obj.use_source_root_motion)

        # Transform at the playhead
        key = self._key_here()
        state = scene.evaluate_object_state(project, obj.id, ops.time_of(self.frame, fps)) or {}
        self.transform_panel.GetChildren()[0].SetLabel(f"TRANSFORM AT FRAME {self.frame}")
        self.key_button.SetValue(key is not None)
        stack = ops.keys_at_frame(obj, self.frame, fps)
        if key and len(stack) > 1:
            # Old files can hold several keys on one frame: show the one that edits will change.
            state = dict(state, x=key.x, y=key.y, rotation_degrees=key.rotation_degrees,
                         flip_x=key.flip_x, flip_y=key.flip_y, visible=key.visible)
            self.key_state.SetLabel(
                f"{len(stack)} keys on this frame (this is #{stack.index(key) + 1}). "
                "Click the key again for the next one; delete the one you don't need."
            )
        elif key:
            self.key_state.SetLabel("Key at this frame")
        elif self.auto_key:
            self.key_state.SetLabel("Between keys — edits add a key (Auto-Key)")
        else:
            self.key_state.SetLabel("Between keys — edits move the whole animation")
        self.key_state.Wrap(170)
        self.tr_x.SetValue(int(round(float(state.get("x", 0.0)))))
        self.tr_y.SetValue(int(round(float(state.get("y", 0.0)))))
        rotation = int(round(float(state.get("rotation_degrees", 0.0)))) % 360
        self.rot_value.SetLabel(f"{rotation}°")
        self.flip_h.SetValue(bool(state.get("flip_x", False)))
        self.flip_v.SetValue(bool(state.get("flip_y", False)))
        self.tr_visible.SetValue(bool(state.get("visible", True)))

        # Motion from the key at/before the playhead to the next one
        start = key or ops.key_before_or_at(obj, self.frame, fps)
        end = ops.segment_end_key(obj, start.id) if start else None
        enabled = start is not None and end is not None
        if self.selected_key_count > 1:
            self.motion_info.SetLabel(f"Applies to the {self.selected_key_count} selected keys")
            enabled = True
            easing = end.easing if end else "linear"
        elif enabled:
            a, b = ops.frame_of(start.time, fps), ops.frame_of(end.time, fps)
            self.motion_info.SetLabel(f"Frames {a} → {b} ({b - a} frames)")
            easing = end.easing
        else:
            self.motion_info.SetLabel("Add a later key to create motion")
            easing = None
        shape, direction = ops.split_easing(easing or "linear")
        self.ease_shape.SetSelection(next((i for i, (_l, k) in enumerate(ops.EASING_SHAPES) if k == shape), 0))
        self.ease_dir.SetSelection(next((i for i, (_l, k) in enumerate(ops.EASING_DIRECTIONS) if k == direction), 2))
        self.ease_shape.Enable(enabled)
        self.ease_dir.Enable(enabled and shape not in ("linear", "step"))
        self.ease_preview.set_easing(easing if enabled else None)
        self.path_choice.SetSelection(1 if obj.path_mode == "spline" else 0)
        has_handles = key is not None and (key.path_in is not None or key.path_out is not None)
        self.reset_handles.Show(obj.path_mode == "spline" and has_handles)

        # Image swap
        swap = key is not None and key.source_type is not None
        self.swap_enable.Enable(key is not None)
        self.swap_enable.SetValue(swap)
        self.swap_enable.SetLabel("Swap the image here" if key else "Needs a key at this frame")
        show_offset = key is not None and (swap or tuple(key.source_offset) != (0.0, 0.0))
        for widget in (self.swap_source, self.swap_source_label):
            widget.Show(swap)
        for widget in (self.swap_offset_label,):
            widget.Show(show_offset)
        self.swap_off_x.GetContainingSizer().ShowItems(show_offset)
        if swap:
            self.swap_source.SetLabel(
                _short(f"{SOURCE_TYPE_LABELS.get(key.source_type, '?')}: {ops.source_name(project, key.source_type, key.source_id)}")
            )
        if key:
            self.swap_off_x.SetValue(int(round(key.source_offset[0])))
            self.swap_off_y.SetValue(int(round(key.source_offset[1])))
