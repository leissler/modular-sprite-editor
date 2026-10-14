"""Frames inspector: the frame (tools, usage), or the selected parts / hitboxes / points, and the types."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import wx

from models import Frame, Project
from ui import first_steps, grouping
from ui.components.inspector_kit import (
    bind_spin, common, dim_text, hbox, relayout, row, section, set_spin, small_button, spin,
)
from ui.frame_editor import ops
from ui.dpi import px


class FrameInspector(wx.ScrolledWindow):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.SetScrollRate(0, px(12))
        self.SetMinSize((px(280), -1))
        self.project: Optional[Project] = None
        self.frame: Optional[Frame] = None
        self.mode = "parts"
        self.selected: List[Any] = []
        self._updating = False
        self._type_rows_key: Any = None
        self.hidden_types: Dict[str, set] = {"hitboxes": set(), "points": set()}

        # Callbacks (set by the panel)
        self.on_frame_field: Optional[Callable[[str, Any], None]] = None
        self.on_frame_tool: Optional[Callable[[str], None]] = None
        self.on_part_field: Optional[Callable[[str, Any], None]] = None
        self.on_part_tool: Optional[Callable[[str], None]] = None
        self.on_marker_field: Optional[Callable[[str, Any], None]] = None
        self.on_type_action: Optional[Callable[[str, str, Any], None]] = None  # (add|rename|colour|visible|delete, type id, value)

        root = wx.BoxSizer(wx.VERTICAL)
        self.hint = dim_text(self)
        root.Add(self.hint, 0, wx.ALL, 8)

        # --- Frame
        self.frame_panel, grid, _ = section(self, root, "Frame", "Frames")
        p = self.frame_panel.body
        self.name = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        row(grid, p, "Name", self.name)
        self.group = wx.ComboBox(p, style=wx.TE_PROCESS_ENTER)
        self.group.SetHint("no group")
        self.group.SetToolTip("Where the frame sits in the list: pick a group or type a new one (the list's group "
                              "choice shows one group at a time)")
        self._group_names: List[str] = []
        row(grid, p, "Group", self.group)
        self.contents = wx.StaticText(p, label="")
        row(grid, p, "Contents", self.contents)
        self.size = wx.StaticText(p, label="")
        row(grid, p, "Size", self.size)
        self.used_by = dim_text(p)
        row(grid, p, "Used by", self.used_by)
        self.btn_mirror_h = small_button(p, "Mirror H", "Mirror the whole frame left ↔ right about its origin (parts, hitboxes, points)", lambda: self._frame_tool("mirror_x"))
        self.btn_mirror_v = small_button(p, "Mirror V", "Mirror the whole frame top ↕ bottom about its origin", lambda: self._frame_tool("mirror_y"))
        row(grid, p, "Whole frame", hbox(self.btn_mirror_h, self.btn_mirror_v))
        self.btn_rot_ccw = small_button(p, "↺ 90°", "Turn the whole frame 90° counter-clockwise about its origin", lambda: self._frame_tool("rot_ccw"))
        self.btn_rot_cw = small_button(p, "↻ 90°", "Turn the whole frame 90° clockwise about its origin", lambda: self._frame_tool("rot_cw"))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_rot_ccw, self.btn_rot_cw), 0, wx.EXPAND)
        self.btn_feet = small_button(p, "Feet on origin", "Move everything so the parts' bottom centre sits on the origin", lambda: self._frame_tool("origin_feet"))
        self.btn_centre = small_button(p, "Centre", "Move everything so the parts' centre sits on the origin", lambda: self._frame_tool("origin_centre"))
        row(grid, p, "Origin", hbox(self.btn_feet, self.btn_centre))

        # --- Part(s)
        self.part_panel, grid, self.part_title = section(self, root, "Part", "Frames")
        p = self.part_panel.body
        self.source_bitmap = wx.StaticBitmap(p, size=(px(40), px(40)))
        self.source_name = wx.StaticText(p, label="")
        self.source_info = dim_text(p)
        names = wx.BoxSizer(wx.VERTICAL)
        names.Add(self.source_name, 0)
        names.Add(self.source_info, 0, wx.TOP, 2)
        source_row = wx.BoxSizer(wx.HORIZONTAL)
        source_row.Add(self.source_bitmap, 0, wx.RIGHT, 8)
        source_row.Add(names, 1, wx.ALIGN_CENTER_VERTICAL)
        self.source_label = row(grid, p, "Shows", source_row)
        self.btn_swap = small_button(p, "Use library pick", "Show the module or frame selected in the library instead (keeps position, flips, rotation)", lambda: self._part_tool("swap"))
        self.btn_open = small_button(p, "Open", "Show this module in the Modules tab, or select this nested frame", lambda: self._part_tool("open"))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_swap, self.btn_open), 0, wx.EXPAND)
        self.px = spin(p, tip="Where the module's pivot (or the nested frame's origin) sits in this frame")
        self.py = spin(p)
        self.pos_label = row(grid, p, "Position", hbox(self.px, self.py))
        self.flip_h = wx.ToggleButton(p, label="Flip H", style=wx.BU_EXACTFIT)
        self.flip_v = wx.ToggleButton(p, label="Flip V", style=wx.BU_EXACTFIT)
        self.flip_h.SetToolTip("Mirror left ↔ right in place (H)")
        self.flip_v.SetToolTip("Mirror top ↕ bottom in place (V)")
        self.btn_group_h = small_button(p, "Flip H", "Mirror the selection left ↔ right as a group (H)", lambda: self._part_tool("flip_x"))
        self.btn_group_v = small_button(p, "Flip V", "Mirror the selection top ↕ bottom as a group (V)", lambda: self._part_tool("flip_y"))
        row(grid, p, "Flip", hbox(self.flip_h, self.flip_v, self.btn_group_h, self.btn_group_v))
        self.btn_ccw = small_button(p, "↺", "Turn 90° counter-clockwise about the pivot (Shift+R)", lambda: self._part_tool("rot_ccw"))
        self.btn_cw = small_button(p, "↻", "Turn 90° clockwise about the pivot (R)", lambda: self._part_tool("rot_cw"))
        self.rotation = wx.StaticText(p, label="0°")
        row(grid, p, "Rotation", hbox(self.btn_ccw, self.btn_cw, 6, self.rotation, "stretch"))
        self.btn_bottom = small_button(p, "⤓", "To the back (Shift+Cmd+↓)", lambda: self._part_tool("bottom"))
        self.btn_down = small_button(p, "↓", "One step back (Cmd+↓)", lambda: self._part_tool("down"))
        self.btn_up = small_button(p, "↑", "One step forward (Cmd+↑)", lambda: self._part_tool("up"))
        self.btn_top = small_button(p, "⤒", "To the front (Shift+Cmd+↑)", lambda: self._part_tool("top"))
        row(grid, p, "Order", hbox(self.btn_bottom, self.btn_down, self.btn_up, self.btn_top))

        # --- Hitbox / point
        self.marker_panel, grid, self.marker_title = section(self, root, "Hitbox", "Frames")
        p = self.marker_panel.body
        self.marker_type = wx.Choice(p)
        row(grid, p, "Type", self.marker_type)
        self.role = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.role.SetToolTip("A stable name the game looks up (e.g. left_foot, weapon_tip). Unique per type within a frame.")
        self.role_label = row(grid, p, "Role", self.role)
        self.mx = spin(p)
        self.my = spin(p)
        self.mpos_label = row(grid, p, "Position", hbox(self.mx, self.my))
        self.mw = spin(p, 0, 9999)
        self.mh = spin(p, 0, 9999)
        self.msize_label = row(grid, p, "Size", hbox(self.mw, self.mh))

        # --- Types
        self.types_panel, grid, self.types_title = section(self, root, "Hitbox types", "Frames")
        p = self.types_panel.body
        self.types_box = wx.BoxSizer(wx.VERTICAL)
        outer = p.GetSizer()
        outer.Add(self.types_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 2)
        self.btn_add_type = small_button(p, "+ Add type", "A new type with its own colour", lambda: self._type("add", "", None))
        types_info = dim_text(p, "Click a swatch to recolour. Unticked types are not drawn on the stage.")
        types_info.Wrap(px(240))
        outer.Add(self.btn_add_type, 0, wx.LEFT | wx.TOP, 2)
        self.btn_clean = small_button(p, "Remove empty boxes", "Delete hitboxes without an area (0 wide or high) in every frame", lambda: self._type("clean", "", None))
        outer.Add(self.btn_clean, 0, wx.LEFT | wx.TOP, 2)
        outer.Add(types_info, 0, wx.LEFT | wx.TOP, 4)

        self.SetSizer(root)
        self._bind()

    # ------------------------------------------------------------------ events
    def _frame_tool(self, name: str) -> None:
        if self.on_frame_tool:
            self.on_frame_tool(name)

    def _part_tool(self, name: str) -> None:
        if self.on_part_tool:
            self.on_part_tool(name)

    def _type(self, action: str, type_id: str, value: Any) -> None:
        if self.on_type_action:
            self.on_type_action(action, type_id, value)

    def _bind(self) -> None:
        def frame_name(_event=None) -> None:
            if not self._updating and self.frame and self.name.GetValue().strip() and self.name.GetValue() != self.frame.name and self.on_frame_field:
                self.on_frame_field("name", self.name.GetValue().strip())

        self.name.Bind(wx.EVT_TEXT_ENTER, frame_name)
        self.name.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), frame_name()))

        def frame_group(_event=None) -> None:
            if not self._updating and self.frame and self.on_frame_field:
                self.on_frame_field("group", self.group.GetValue())

        self.group.Bind(wx.EVT_COMBOBOX, frame_group)
        self.group.Bind(wx.EVT_TEXT_ENTER, frame_group)
        self.group.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), frame_group()))

        def part(field: str, value: Any) -> None:
            if not self._updating and self.on_part_field:
                self.on_part_field(field, value)

        bind_spin(self.px, lambda v: part("x", v))
        bind_spin(self.py, lambda v: part("y", v))
        self.flip_h.Bind(wx.EVT_TOGGLEBUTTON, lambda e: part("flip_x", self.flip_h.GetValue()))
        self.flip_v.Bind(wx.EVT_TOGGLEBUTTON, lambda e: part("flip_y", self.flip_v.GetValue()))

        def marker(field: str, value: Any) -> None:
            if not self._updating and self.on_marker_field:
                self.on_marker_field(field, value)

        self.marker_type.Bind(wx.EVT_CHOICE, lambda e: marker("type", self._type_ids[self.marker_type.GetSelection()]))
        self.role.Bind(wx.EVT_TEXT_ENTER, lambda e: marker("role", self.role.GetValue().strip()))
        self.role.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), self._commit_role()))
        for key, ctrl in (("x", self.mx), ("y", self.my), ("w", self.mw), ("h", self.mh)):
            bind_spin(ctrl, lambda v, k=key: marker(k, v))
        self._type_ids: List[str] = []

    def _commit_role(self) -> None:
        if len(self.selected) == 1 and self.mode != "parts" and self.role.GetValue().strip() != (self.selected[0].role or ""):
            if not self._updating and self.on_marker_field:
                self.on_marker_field("role", self.role.GetValue().strip())

    # ------------------------------------------------------------------ fill
    def show(self, project: Project, frame: Optional[Frame], mode: str, selected: List[Any],
             source_bitmap: Optional[wx.Bitmap] = None, size: Optional[Tuple[int, int]] = None) -> None:
        self.project, self.frame, self.mode, self.selected = project, frame, mode, selected
        self._updating = True
        self.Freeze()
        try:
            self.frame_panel.Show(frame is not None and not selected)
            self.part_panel.Show(frame is not None and mode == "parts" and bool(selected))
            self.marker_panel.Show(frame is not None and mode != "parts" and bool(selected))
            self.types_panel.Show(mode != "parts" and not selected)
            if frame is None:
                self.hint.SetLabel(first_steps.frames(project) or "Select a frame in the list, or click + New.")
            elif not selected:
                self.hint.SetLabel({
                    "parts": "Drag modules or frames from the library onto the stage. Click a part to edit it; drag on empty space to select several.",
                    "hitboxes": "Drag on empty space to draw a box of the type chosen above the stage. Drag a box to move it, a corner to resize.",
                    "points": "Click to place a point of the chosen type. Drag points to move them; Shift+click adds one to the selection.",
                }[mode])
            else:
                self.hint.SetLabel("")
            self.hint.Wrap(px(260))
            if frame is not None and not selected:
                self._fill_frame(project, frame, size)
            if frame is not None and mode == "parts" and selected:
                self._fill_parts(project, selected, source_bitmap)
            if frame is not None and mode != "parts" and selected:
                self._fill_markers(project, mode, selected)
            if mode != "parts" and not selected:
                self._fill_types(project, mode)
        finally:
            self._updating = False
            self.Thaw()
        relayout(self)

    def _fill_frame(self, project: Project, frame: Frame, size: Optional[Tuple[int, int]]) -> None:
        if not self.name.HasFocus():
            self.name.ChangeValue(frame.name)
        if not self.group.HasFocus():
            names = [name for name, _count in grouping.groups_of(project.frames)]
            if names != self._group_names:
                self._group_names = names
                self.group.SetItems(names)
            self.group.ChangeValue(frame.group)
        self.contents.SetLabel(ops.summary(frame))
        self.size.SetLabel(f"{size[0]} × {size[1]} px" if size else "—")
        self.used_by.SetLabel(ops.describe_references(ops.frame_references(project, frame.id)))
        self.used_by.Wrap(px(190))
        has_parts = bool(frame.fmodules)
        self.btn_feet.Enable(has_parts)
        self.btn_centre.Enable(has_parts)

    def _fill_parts(self, project: Project, parts: List[Any], bitmap: Optional[wx.Bitmap]) -> None:
        single = parts[0] if len(parts) == 1 else None
        self.part_title.SetLabel("PART" if single else f"{len(parts)} PARTS")
        for widget in (self.source_label, self.source_bitmap, self.source_name, self.source_info, self.btn_open,
                       self.pos_label, self.px, self.py, self.flip_h, self.flip_v):
            widget.Show(single is not None)
        self.btn_group_h.Show(single is None)
        self.btn_group_v.Show(single is None)
        if single is not None:
            self.source_bitmap.SetBitmap(bitmap if bitmap is not None else wx.Bitmap(px(40), px(40)))
            self.source_name.SetLabel(_short(ops.part_name(project, single), 26))
            if single.ref_type == "frame":
                self.source_info.SetLabel("nested frame")
            else:
                mod = project.get_module(single.ref_id)
                self.source_info.SetLabel(f"module {mod.rect[2]}×{mod.rect[3]}" if mod else "missing module")
            set_spin(self.px, single.position[0])
            set_spin(self.py, single.position[1])
            self.flip_h.SetValue(bool(single.flip_x))
            self.flip_v.SetValue(bool(single.flip_y))
        rotation = common([int(round(fm.rotation_degrees)) % 360 for fm in parts])
        self.rotation.SetLabel(f"{rotation}°" if rotation is not None else "mixed")

    def _fill_markers(self, project: Project, mode: str, markers: List[Any]) -> None:
        single = markers[0] if len(markers) == 1 else None
        noun = "Hitbox" if mode == "hitboxes" else "Point"
        self.marker_title.SetLabel(noun.upper() if single else f"{len(markers)} {'HITBOXES' if mode == 'hitboxes' else 'POINTS'}")
        type_list = ops.types(project, mode)
        self._type_ids = [t.id for t in type_list]
        self.marker_type.SetItems([t.name for t in type_list])
        shared = common([m.type_id for m in markers])
        self.marker_type.SetSelection(self._type_ids.index(shared) if shared in self._type_ids else wx.NOT_FOUND)
        for widget in (self.role_label, self.role, self.mpos_label, self.mx, self.my):
            widget.Show(single is not None)
        is_box = mode == "hitboxes"
        for widget in (self.msize_label, self.mw, self.mh):
            widget.Show(single is not None and is_box)
        if single is not None:
            if not self.role.HasFocus():
                self.role.ChangeValue(single.role or "")
            if is_box:
                x, y, w, h = single.rect
                set_spin(self.mx, x)
                set_spin(self.my, y)
                set_spin(self.mw, w)
                set_spin(self.mh, h)
            else:
                set_spin(self.mx, single.x)
                set_spin(self.my, single.y)

    def _fill_types(self, project: Project, mode: str) -> None:
        self.types_title.SetLabel("HITBOX TYPES" if mode == "hitboxes" else "POINT TYPES")
        type_list = ops.types(project, mode)
        empty = ops.empty_hitboxes(project) if mode == "hitboxes" else 0
        self.btn_clean.Show(empty > 0)
        self.btn_clean.SetLabel(f"Remove {empty} empty box{'es' if empty != 1 else ''}")
        hidden = self.hidden_types[mode]
        key = (mode, tuple((t.id, t.name, tuple(t.color), t.id in hidden, ops.type_usage(project, mode, t.id)) for t in type_list))
        if key == self._type_rows_key:
            return
        self._type_rows_key = key
        self.types_box.Clear(True)
        p = self.types_panel.body
        for t in type_list:
            line = wx.BoxSizer(wx.HORIZONTAL)
            swatch = wx.Button(p, label="", size=(px(22), px(20)), style=wx.BORDER_NONE)
            swatch.SetBackgroundColour(wx.Colour(*t.color))
            swatch.SetToolTip("Change the colour")
            swatch.Bind(wx.EVT_BUTTON, lambda e, tid=t.id, col=t.color: self._pick_colour(tid, col))
            name = wx.TextCtrl(p, value=t.name, style=wx.TE_PROCESS_ENTER, size=(px(110), -1))
            name.Bind(wx.EVT_TEXT_ENTER, lambda e, tid=t.id, ctrl=name: self._type("rename", tid, ctrl.GetValue().strip()))
            name.Bind(wx.EVT_KILL_FOCUS, lambda e, tid=t.id, ctrl=name, old=t.name: (e.Skip(), ctrl.GetValue().strip() != old and self._type("rename", tid, ctrl.GetValue().strip())))
            show = wx.CheckBox(p, label="")
            show.SetValue(t.id not in hidden)
            show.SetToolTip("Show this type on the stage")
            show.Bind(wx.EVT_CHECKBOX, lambda e, tid=t.id: self._type("visible", tid, e.IsChecked()))
            count, frames = ops.type_usage(project, mode, t.id)
            uses = dim_text(p, f"{count}×")
            uses.SetToolTip(f"Used {count} time(s) in {frames} frame(s)")
            delete = wx.Button(p, label="✕", style=wx.BU_EXACTFIT)
            delete.SetToolTip("Delete this type and every hitbox / point of it")
            delete.Bind(wx.EVT_BUTTON, lambda e, tid=t.id: self._type("delete", tid, None))
            line.Add(swatch, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            line.Add(name, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            line.Add(show, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            line.Add(uses, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            line.Add(delete, 0, wx.ALIGN_CENTER_VERTICAL)
            self.types_box.Add(line, 0, wx.EXPAND | wx.BOTTOM, 4)

    def _pick_colour(self, type_id: str, colour: Tuple[int, int, int]) -> None:
        data = wx.ColourData()
        data.SetColour(wx.Colour(*colour))
        with wx.ColourDialog(self, data) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                c = dlg.GetColourData().GetColour()
                self._type("colour", type_id, (c.Red(), c.Green(), c.Blue()))


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
