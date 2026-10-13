"""Frames tab: Frames + Library | stage | inspector + contents.

Assemble a frame from modules and nested frames (drag from the library), mark hitboxes and points on
it; every selection shows its properties in the inspector, the contents list shows what the frame holds.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import wx

from models import FModule, Frame, Project
from optimization import optimize_nested_frame_combos
from ui import app_services
from ui.canvas import GHOST_NEXT, GHOST_PREVIOUS
from ui.components import confirm
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.components.module_palette import THUMBNAILS
from ui.components.thumb_list import Browser, Row
from ui.frame_editor import ops
from ui.frame_editor.inspector import FrameInspector
from ui.frame_editor.library import PartLibrary
from ui.frame_editor.stage import FrameStage
from ui.frame_render import SHARED, fit_bitmap, frame_signature, mapping_key

ONION_MODES: List[Tuple[str, str]] = [("Off", "off"), ("Previous", "previous"), ("Next", "next"), ("Both", "both")]
NUDGE_LARGE = 8  # one hardware tile
TILE_BG = (52, 53, 58)
UNKNOWN_TYPE_COLOUR = (150, 150, 150)
MODE_HINTS = {
    "parts": "Drag from the library onto the stage  •  Click: select (again: the part below)  •  Drag empty space: select several  •  Arrows: nudge (Shift = 8 px)  •  H/V flip  •  R rotate",
    "hitboxes": "Drag on empty space: new box of the chosen type  •  Drag a box: move  •  Drag a corner: resize  •  Arrows: nudge",
    "points": "Click: new point of the chosen type  •  Drag: move  •  Shift+click: add to selection  •  Arrows: nudge",
}

# Copied parts / hitboxes / points, shared between frames for the session.
_ITEM_CLIPBOARD: Dict[str, Any] = {"mode": None, "items": []}
# Hitboxes and points copied from a frame (frame list menu).
_MARKER_CLIPBOARD: Dict[str, List[Dict[str, Any]]] = {"hitboxes": [], "points": []}


class FrameEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_frame_id: Optional[str] = None
        self.mode = "parts"
        self._view: List[Frame] = []
        self._thumbs: Dict[Any, wx.Bitmap] = {}
        self._swatches: Dict[Tuple[int, int, int], wx.Bitmap] = {}
        self._active_type: Dict[str, Optional[str]] = {"hitboxes": None, "points": None}
        self._fitted_id: Optional[str] = None
        self.on_open_module: Optional[Callable[[str], None]] = None  # set by the main window

        self._build_ui()
        self._bind()
        self.set_project(project)

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        self.outer_split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.left_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.browser = Browser(self.left_split, "Frames", row_h=46, thumb=38, reorder=True)
        self.btn_new = self.browser.add_button("+ New", "New empty frame after the selected one", self.new_frame)
        self.btn_dup = self.browser.add_button("Duplicate", "Duplicate the selected frame", self.duplicate_frame)
        self.btn_del = self.browser.add_button("Delete", "Delete the selected frame", self.delete_frame)
        self.library = PartLibrary(self.left_split, self.project)
        self.left_split.SplitHorizontally(self.browser, self.library, 0)
        self.left_split.SetSashGravity(0.5)
        self.left_split.SetMinimumPaneSize(140)

        self.inner_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        stage_panel = wx.Panel(self.inner_split)
        stage_sizer = wx.BoxSizer(wx.VERTICAL)
        tools = wx.BoxSizer(wx.HORIZONTAL)
        self.mode_buttons: Dict[str, wx.ToggleButton] = {}
        for key, label, _canvas in ops.MODES:
            btn = wx.ToggleButton(stage_panel, label=label, size=(-1, -1))
            btn.SetToolTip({"parts": "Arrange modules and nested frames",
                            "hitboxes": "Draw collision boxes (hit, hurt, push…)",
                            "points": "Place control points (hands, feet, effect spawns…)"}[key])
            btn.Bind(wx.EVT_TOGGLEBUTTON, lambda e, k=key: self.set_mode(k))
            tools.Add(btn, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 2)
            self.mode_buttons[key] = btn
        tools.AddSpacer(10)
        self.type_label = wx.StaticText(stage_panel, label="New:")
        self.type_choice = wx.Choice(stage_panel)
        self.type_choice.SetToolTip("Type of the boxes / points you draw next (manage types in the inspector)")
        self.type_choice.SetMinSize((140, -1))
        tools.Add(self.type_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        tools.Add(self.type_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        tools.AddStretchSpacer(1)
        tools.Add(wx.StaticText(stage_panel, label="Onion"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.onion_choice = wx.Choice(stage_panel, choices=[label for label, _ in ONION_MODES])
        self.onion_choice.SetSelection(0)
        self.onion_choice.SetMinSize((stage_panel.GetTextExtent("Previous")[0] + 44, -1))
        self.onion_choice.SetToolTip("Ghost the previous (red) / next (blue) frame of the list")
        tools.Add(self.onion_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        stage_sizer.Add(tools, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

        self.stage = FrameStage(stage_panel, self.project)
        self.canvas = self.stage  # the shared canvas name other code expects
        self.canvas_controls = CanvasDisplayControls(stage_panel, self.stage, view_key="frames", part_bounds=True, budget=True)
        self.canvas_controls.add_separator()
        self.chk_hitboxes = self.canvas_controls.add_toggle("Hitboxes", False, self._on_show_hitboxes, "Show hitboxes while arranging parts")
        self.chk_points = self.canvas_controls.add_toggle("Points", True, self._on_show_points, "Show points while arranging parts")
        stage_sizer.Add(self.stage, 1, wx.EXPAND | wx.ALL, 2)
        stage_sizer.Add(self.canvas_controls, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        stage_panel.SetSizer(stage_sizer)

        self.right_split = wx.SplitterWindow(self.inner_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.inspector = FrameInspector(self.right_split)
        self.contents = Browser(self.right_split, "Contents", row_h=34, thumb=26, multiple=True, reorder=True)
        self.contents.search.Hide()
        self.btn_item_delete = self.contents.add_button("Delete", "Delete the selected items (Delete)", self.delete_selection)
        self.right_split.SplitHorizontally(self.inspector, self.contents, -230)
        self.right_split.SetSashGravity(1.0)
        self.right_split.SetMinimumPaneSize(120)

        self.inner_split.SplitVertically(stage_panel, self.right_split, -310)
        self.inner_split.SetSashGravity(1.0)
        self.inner_split.SetMinimumPaneSize(240)
        self.outer_split.SplitVertically(self.left_split, self.inner_split, 270)
        self.outer_split.SetMinimumPaneSize(200)
        root.Add(self.outer_split, 1, wx.EXPAND)
        self.SetSizer(root)
        wx.CallAfter(self._place_sashes)

    def _place_sashes(self) -> None:
        height = self.left_split.GetClientSize().height
        if height > 300:
            self.left_split.SetSashPosition(int(height * 0.48))

    def _bind(self) -> None:
        fl = self.browser.list
        fl.thumbnail = self._frame_thumbnail
        fl.Bind(wx.EVT_LISTBOX, lambda e: self._on_list_select())
        fl.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: fl.begin_rename())
        fl.Bind(wx.EVT_CONTEXT_MENU, lambda e: self._frame_menu())
        fl.on_rename = self._rename_frame
        fl.on_move = self._move_frame
        fl.drag_out_text = lambda frame_id: f"FRAME:{frame_id}"
        self.browser.search.Bind(wx.EVT_TEXT, lambda e: self.refresh_frames())
        self.library.on_add = lambda ref_type, ref_id: self.add_part(ref_type, ref_id, (0, 0))

        cl = self.contents.list
        cl.thumbnail = self._item_thumbnail
        cl.Bind(wx.EVT_LISTBOX, lambda e: self._on_contents_select())
        cl.Bind(wx.EVT_CONTEXT_MENU, lambda e: self._stage_menu(None))
        cl.on_move = self._move_item

        st = self.stage
        st.on_interaction = self._stage_interaction
        st.on_live = self._stage_live
        st.on_drop = lambda ref_type, ref_id, world: self.add_part(ref_type, ref_id, (int(world[0] // 1), int(world[1] // 1)))
        st.on_modify_started = None
        st.on_modify_ended = self._commit
        st.Bind(wx.EVT_RIGHT_DOWN, self._on_stage_right_down)

        self.type_choice.Bind(wx.EVT_CHOICE, lambda e: self._on_type_choice())
        self.onion_choice.Bind(wx.EVT_CHOICE, lambda e: self._update_ghosts())

        ins = self.inspector
        ins.on_frame_field = self._on_frame_field
        ins.on_frame_tool = self._on_frame_tool
        ins.on_part_field = self._on_part_field
        ins.on_part_tool = self._on_part_tool
        ins.on_marker_field = self._on_marker_field
        ins.on_type_action = self._on_type_action
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    # ================================================================== main-window interface
    def get_active_canvas(self):
        return self.stage

    def set_project(self, project: Project) -> None:
        self.project = project
        self.stage.project = project
        self.stage.clear_cache()
        project.ensure_default_collision_type()
        project.ensure_default_point_type()
        self.library.set_project(project)
        self.browser.search.ChangeValue("")
        self.inspector.hidden_types = {"hitboxes": set(), "points": set()}
        self._active_type = {"hitboxes": None, "points": None}
        self._thumbs = {}
        self._fitted_id = None
        self.selected_frame_id = project.frames[0].id if project.frames else None
        self._clear_selection()
        self.set_mode("parts")
        self.refresh_frames()
        self.show_frame(self.selected_frame_id, fit=True)

    def refresh_after_history(self) -> None:
        if self.selected_frame_id and not self.project.get_frame(self.selected_frame_id):
            self.selected_frame_id = None
        self.stage.clear_cache()
        self._thumbs = {}
        self.library.refresh()
        self.refresh_frames()
        self.show_frame(self.selected_frame_id, keep_selection=True)

    def on_tab_activated(self) -> None:
        """Modules and frames may have changed in other tabs."""
        self.stage.clear_cache()
        self.library.refresh()
        self.refresh_frames()
        self.show_frame(self.selected_frame_id, keep_selection=True)

    def on_active_mapping_changed(self) -> None:
        self.stage.clear_cache()
        self.library.frames.invalidate_scale()
        self.library.frames.Refresh()
        self.browser.list.Refresh()
        self.refresh()

    def stop_playback(self) -> None:
        pass

    # kept for the main window and tools
    def refresh_choices(self) -> None:
        self.on_tab_activated()

    def select_frame_by_id(self, frame_id: str) -> None:
        frame = self.project.get_frame(frame_id)
        if frame is None:
            return
        if self.browser.filter_text() and frame not in self._view:
            self.browser.search.ChangeValue("")
        self.selected_frame_id = frame_id
        self.refresh_frames()
        self.show_frame(frame_id, fit=True)

    def on_optimize_nested_combos(self, _event: Optional[wx.CommandEvent] = None) -> None:
        if not self.project.frames:
            wx.MessageBox("There are no frames.", "Optimize Nested Combos", wx.OK | wx.ICON_INFORMATION, self)
            return
        if wx.MessageBox(
            "Find module groups that repeat across all frames and replace them with nested helper frames?\n\n"
            "Frames look the same afterwards, but are built differently. (Undo with Cmd/Ctrl+Z.)",
            "Optimize Nested Combos", wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        with wx.BusyCursor():
            _success, message = optimize_nested_frame_combos(self.project)
        self.refresh_after_history()
        wx.MessageBox(message, "Optimize Nested Combos", wx.OK | wx.ICON_INFORMATION, self)

    # ================================================================== helpers
    def frame(self) -> Optional[Frame]:
        return self.project.get_frame(self.selected_frame_id) if self.selected_frame_id else None

    def selected_ids(self) -> List[str]:
        if self.mode == "hitboxes":
            return list(self.stage.selected_collision_rects)
        if self.mode == "points":
            return list(self.stage.selected_points)
        return list(self.stage.selected_fmodules)

    def selected_items(self) -> List[Any]:
        frame = self.frame()
        if frame is None:
            return []
        ids = set(self.selected_ids())
        return [item for item in ops.items(frame, self.mode) if item.id in ids]

    def set_selected(self, ids: List[str]) -> None:
        if self.mode == "hitboxes":
            self.stage.selected_collision_rects = list(ids)
        elif self.mode == "points":
            self.stage.selected_points = list(ids)
        else:
            self.stage.selected_fmodules = list(ids)
        self.refresh(frames=False)

    def _clear_selection(self) -> None:
        self.stage.selected_fmodules = []
        self.stage.selected_collision_rects = []
        self.stage.selected_points = []

    def _commit(self) -> None:
        self.refresh()
        app_services.request_checkpoint()

    # ================================================================== frames list
    def refresh_frames(self) -> None:
        query = self.browser.filter_text()
        self._view = [f for f in self.project.frames if not query or query in f.name.lower()]
        anims = ops.animation_counts(self.project)
        nested: Dict[str, int] = {}
        for f in self.project.frames:
            for fm in f.fmodules:
                if fm.ref_type == "frame":
                    nested[fm.ref_id] = nested.get(fm.ref_id, 0) + 1
        rows = []
        for f in self._view:
            bits = [f"{len(f.fmodules)} part{'s' if len(f.fmodules) != 1 else ''}"]
            if anims.get(f.id):
                bits.append(f"{anims[f.id]} anim{'s' if anims[f.id] != 1 else ''}")
            if nested.get(f.id):
                bits.append(f"nested ×{nested[f.id]}")
            used = bool(anims.get(f.id) or nested.get(f.id))
            rows.append(Row(f.id, f.name, " · ".join(bits) if used else bits[0] + " · unused", dim=not used))
        if self.selected_frame_id and not self.project.get_frame(self.selected_frame_id):
            self.selected_frame_id = None
        self.browser.list.set_rows(rows, [self.selected_frame_id] if self.selected_frame_id else [])
        self.browser.set_count(len(self._view), len(self.project.frames))
        self.btn_dup.Enable(self.frame() is not None)
        self.btn_del.Enable(self.frame() is not None)

    def _on_list_select(self) -> None:
        ids = self.browser.list.selected_ids()
        if ids and ids[0] != self.selected_frame_id:
            self.show_frame(ids[0])

    def show_frame(self, frame_id: Optional[str], fit: bool = False, keep_selection: bool = False) -> None:
        changed = frame_id != self.stage.frame.id if self.stage.frame is not None else frame_id is not None
        self.selected_frame_id = frame_id if frame_id and self.project.get_frame(frame_id) else None
        frame = self.frame()
        self.stage.set_frame(frame)
        if changed and not keep_selection:
            self._clear_selection()
        else:
            self._drop_stale_selection()
        self.browser.list.set_selected([self.selected_frame_id] if self.selected_frame_id else [])
        self.btn_dup.Enable(frame is not None)
        self.btn_del.Enable(frame is not None)
        self._update_ghosts()
        self.refresh(frames=False)
        if frame is not None and (fit or self._fitted_id is None):
            self._fitted_id = frame.id
            wx.CallAfter(self.stage.fit_to_content)

    def _drop_stale_selection(self) -> None:
        frame = self.frame()
        if frame is None:
            self._clear_selection()
            return
        self.stage.selected_fmodules = [i for i in self.stage.selected_fmodules if any(fm.id == i for fm in frame.fmodules)]
        self.stage.selected_collision_rects = [i for i in self.stage.selected_collision_rects if any(c.id == i for c in frame.collision_rects)]
        self.stage.selected_points = [i for i in self.stage.selected_points if any(c.id == i for c in frame.control_points)]

    def refresh(self, frames: bool = True) -> None:
        """Stage, contents list and inspector (and the frame list rows) from the data."""
        self._drop_stale_selection()
        self._sync_types()
        self.stage.Refresh(False)
        self._refresh_contents()
        self._refresh_inspector()
        if frames:
            self.refresh_frames()

    def _refresh_inspector(self) -> None:
        frame = self.frame()
        selected = self.selected_items()
        bitmap = None
        if frame is not None and self.mode == "parts" and len(selected) == 1:
            bitmap = self._part_thumbnail(selected[0], 40)
        size = ops.content_size(self.project, frame, self.project.active_mapping) if frame is not None else None
        self.inspector.show(self.project, frame, self.mode, selected, bitmap, size)

    def _refresh_contents(self) -> None:
        frame = self.frame()
        rows: List[Row] = []
        if frame is not None:
            if self.mode == "parts":
                for fm in reversed(frame.fmodules):
                    rows.append(Row(fm.id, ops.part_name(self.project, fm), ops.part_details(fm)))
            else:
                type_names = {t.id: t.name for t in ops.types(self.project, self.mode)}
                for item in ops.items(frame, self.mode):
                    title = item.role or type_names.get(item.type_id, "(unknown type)")
                    if self.mode == "hitboxes":
                        x, y, w, h = item.rect
                        where = f"{x}, {y} · {w}×{h}"
                    else:
                        where = f"{item.x}, {item.y}"
                    meta = f"{type_names.get(item.type_id, '?')} · {where}" if item.role else where
                    rows.append(Row(item.id, title, meta))
        title = {"parts": "Parts", "hitboxes": "Hitboxes", "points": "Points"}[self.mode]
        self.contents._title_text = title
        self.contents.set_count(len(rows), len(rows))
        self.contents.list.set_rows(rows, self.selected_ids())
        self.btn_item_delete.Enable(bool(self.selected_ids()))

    def _on_contents_select(self) -> None:
        ids = self.contents.list.selected_ids()
        if self.mode == "hitboxes":
            self.stage.selected_collision_rects = ids
        elif self.mode == "points":
            self.stage.selected_points = ids
        else:
            self.stage.selected_fmodules = ids
            self._sync_library_pick()
        self.stage.Refresh(False)
        self.btn_item_delete.Enable(bool(ids))
        self._refresh_inspector()

    def _sync_library_pick(self) -> None:
        parts = self.selected_items() if self.mode == "parts" else []
        if len(parts) == 1 and parts[0].ref_type == "module":
            self.library.modules.select_module(parts[0].ref_id)

    def _frame_thumbnail(self, frame_id: str, size: int) -> Optional[wx.Bitmap]:
        frame = self.project.get_frame(frame_id)
        if frame is None or not frame.fmodules:
            return None
        mapping = self.project.active_mapping
        key = (frame_signature(self.project, frame_id, mapping), mapping_key(mapping), size)
        bmp = self._thumbs.get(key)
        if bmp is None:
            image, _x, _y = SHARED.render(self.project, frame, mapping)
            bmp = fit_bitmap(image, size, size, TILE_BG, max_scale=4)
            if len(self._thumbs) > 2000:
                self._thumbs.clear()
            self._thumbs[key] = bmp
        return bmp

    def _part_thumbnail(self, fm: FModule, size: int) -> Optional[wx.Bitmap]:
        if fm.ref_type == "frame":
            return self._frame_thumbnail(fm.ref_id, size)
        mod = self.project.get_module(fm.ref_id)
        return THUMBNAILS.bitmap(self.project, mod, size, size) if mod else None

    def _item_thumbnail(self, item_id: str, size: int) -> Optional[wx.Bitmap]:
        frame = self.frame()
        if frame is None:
            return None
        item = next((i for i in ops.items(frame, self.mode) if i.id == item_id), None)
        if item is None:
            return None
        if self.mode == "parts":
            return self._part_thumbnail(item, size)
        kind = next((t for t in ops.types(self.project, self.mode) if t.id == item.type_id), None)
        colour = tuple(kind.color) if kind else UNKNOWN_TYPE_COLOUR
        bmp = self._swatches.get(colour)  # type: ignore[arg-type]
        if bmp is None:
            bmp = wx.Bitmap(size, size)
            dc = wx.MemoryDC(bmp)
            dc.SetBackground(wx.Brush(wx.Colour(*TILE_BG)))
            dc.Clear()
            dc.SetPen(wx.Pen(wx.Colour(*colour), 2))
            dc.SetBrush(wx.Brush(wx.Colour(colour[0], colour[1], colour[2], 90)))
            if self.mode == "hitboxes":
                dc.DrawRectangle(5, 5, size - 10, size - 10)
            else:
                c = size // 2
                dc.DrawLine(c - 7, c, c + 8, c)
                dc.DrawLine(c, c - 7, c, c + 8)
            dc.SelectObject(wx.NullBitmap)
            self._swatches[colour] = bmp  # type: ignore[index]
        return bmp

    # ================================================================== frame commands
    def new_frame(self) -> None:
        frame = ops.new_frame(self.project, self.selected_frame_id)
        if self.browser.filter_text():
            self.browser.search.ChangeValue("")
        self.selected_frame_id = frame.id
        self.refresh_frames()
        self.show_frame(frame.id)
        app_services.request_checkpoint()
        wx.CallAfter(self.browser.list.begin_rename, frame.id)

    def duplicate_frame(self) -> None:
        copy = ops.duplicate_frame(self.project, self.selected_frame_id or "")
        if copy is None:
            return
        if self.browser.filter_text():
            self.browser.search.ChangeValue("")
        self.selected_frame_id = copy.id
        self.refresh_frames()
        self.show_frame(copy.id)
        app_services.request_checkpoint()
        app_services.show_status(f"Duplicated as '{copy.name}'")

    # kept name for older callers
    duplicate_selected_frame = duplicate_frame

    def delete_frame(self) -> None:
        frame = self.frame()
        if frame is None:
            return
        refs = ops.frame_references(self.project, frame.id)
        clean_up = False
        if any(refs[k] for k in ("animations", "frames", "scene_objects")):
            message = (f"Delete '{frame.name}'? It is used by {ops.describe_references(refs)}.\n\nRemove its steps "
                       "and copies there too, or keep them as missing frames you can swap later?"
                       "\n\n(Undo with Cmd/Ctrl+Z.)")
            answer = confirm.ask_remove_uses(self, "Delete Frame", message, "Remove Uses Too")
            if answer is None:
                return
            clean_up = answer == confirm.REMOVE
        index = self._view.index(frame) if frame in self._view else -1
        if clean_up:
            ops.remove_frame_uses(self.project, frame.id)
        ops.delete_frame(self.project, frame.id)
        self._view = [f for f in self._view if f.id != frame.id]
        neighbour = self._view[min(index, len(self._view) - 1)] if self._view and index >= 0 else None
        self.selected_frame_id = neighbour.id if neighbour else None
        self.refresh_frames()
        self.show_frame(self.selected_frame_id)
        app_services.request_checkpoint()
        app_services.show_status(f"Deleted frame '{frame.name}'")

    def _rename_frame(self, frame_id: str, name: str) -> None:
        frame = self.project.get_frame(frame_id)
        if frame and name != frame.name:
            frame.name = name
            self._commit()

    def _move_frame(self, frame_id: str, before_id: Optional[str]) -> None:
        if self.browser.filter_text():
            app_services.show_status("Clear the filter to reorder frames")
            return
        ops.move_frame(self.project, frame_id, before_id)
        self.refresh_frames()
        self._update_ghosts()
        app_services.request_checkpoint()

    def _frame_menu(self) -> None:
        frame = self.frame()
        if frame is None:
            return
        menu = wx.Menu()

        def add(label: str, handler: Callable[[], None], enabled: bool = True) -> None:
            item = menu.Append(wx.ID_ANY, label)
            item.Enable(enabled)
            self.Bind(wx.EVT_MENU, lambda e: handler(), item)

        add("Rename", lambda: self.browser.list.begin_rename(frame.id))
        add("Duplicate", self.duplicate_frame)
        add("Delete", self.delete_frame)
        menu.AppendSeparator()
        add("Mirror Horizontally", lambda: self._on_frame_tool("mirror_x"))
        add("Mirror Vertically", lambda: self._on_frame_tool("mirror_y"))
        add("Rotate 90° Clockwise", lambda: self._on_frame_tool("rot_cw"))
        add("Rotate 90° Counter-clockwise", lambda: self._on_frame_tool("rot_ccw"))
        menu.AppendSeparator()
        has_markers = bool(frame.collision_rects or frame.control_points)
        add("Copy Hitboxes && Points", self._copy_markers, has_markers)
        add("Paste Hitboxes && Points", self._paste_markers, bool(_MARKER_CLIPBOARD["hitboxes"] or _MARKER_CLIPBOARD["points"]))
        add("Copy Hitboxes to All Frames…", lambda: self._markers_to_all("hitboxes"), bool(frame.collision_rects))
        add("Copy Points to All Frames…", lambda: self._markers_to_all("points"), bool(frame.control_points))
        self.browser.list.PopupMenu(menu)
        menu.Destroy()

    def _copy_markers(self) -> None:
        frame = self.frame()
        if frame is None:
            return
        _MARKER_CLIPBOARD["hitboxes"] = [c.to_dict() for c in frame.collision_rects]
        _MARKER_CLIPBOARD["points"] = [c.to_dict() for c in frame.control_points]
        app_services.show_status(f"Copied {len(frame.collision_rects)} hitbox(es) and {len(frame.control_points)} point(s)")

    def _paste_markers(self) -> None:
        frame = self.frame()
        if frame is None:
            return
        boxes = ops.insert_items(self.project, frame, "hitboxes", _MARKER_CLIPBOARD["hitboxes"])
        points = ops.insert_items(self.project, frame, "points", _MARKER_CLIPBOARD["points"])
        self._commit()
        app_services.show_status(f"Pasted {len(boxes)} hitbox(es) and {len(points)} point(s)")

    def _markers_to_all(self, mode: str) -> None:
        frame = self.frame()
        if frame is None:
            return
        noun = "hitboxes" if mode == "hitboxes" else "points"
        with wx.MessageDialog(self, f"Copy the {noun} of '{frame.name}' into every other frame ({len(self.project.frames) - 1})?",
                              f"Copy {noun.title()} to All Frames", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION) as dlg:
            dlg.SetYesNoCancelLabels("Add to theirs", "Replace theirs", "Cancel")
            answer = dlg.ShowModal()
        if answer == wx.ID_CANCEL:
            return
        count = ops.copy_markers_to(self.project, frame, mode, self.project.frames, replace=answer == wx.ID_NO)
        self._commit()
        app_services.show_status(f"Copied the {noun} into {count} frame(s)")

    def _on_frame_field(self, field: str, value: Any) -> None:
        frame = self.frame()
        if frame is not None and field == "name" and value and value != frame.name:
            frame.name = value
            self._commit()

    def _on_frame_tool(self, name: str) -> None:
        frame = self.frame()
        if frame is None:
            return
        mapping = self.project.active_mapping
        if name in ("mirror_x", "mirror_y"):
            ops.mirror_frame(self.project, frame, name[-1], mapping)
        elif name in ("rot_cw", "rot_ccw"):
            ops.rotate_frame(frame, 90 if name == "rot_cw" else -90)
        elif name in ("origin_feet", "origin_centre"):
            dx, dy = ops.origin_offset(self.project, frame, mapping, "feet" if name == "origin_feet" else "centre")
            if (dx, dy) == (0, 0):
                app_services.show_status("Already there")
                return
            ops.offset_frame(frame, dx, dy)
        else:
            return
        self._commit()
        self.stage.fit_to_content()

    # ================================================================== modes and types
    def set_mode(self, mode: str) -> None:
        if mode not in ops.CANVAS_MODE:
            return
        self.mode = mode
        for key, btn in self.mode_buttons.items():
            btn.SetValue(key == mode)
        self.stage.edit_mode = ops.CANVAS_MODE[mode]
        self._clear_selection()
        marker_mode = mode != "parts"
        self.type_label.Show(marker_mode)
        self.type_choice.Show(marker_mode)
        self.type_choice.GetContainingSizer().Layout()
        self.refresh(frames=False)
        app_services.show_status(MODE_HINTS[mode])

    def _sync_types(self) -> None:
        """Stage colours / visibility and the type choice from the project's types."""
        hidden = self.inspector.hidden_types
        boxes = {t.id: t.color for t in self.project.collision_types if t.id not in hidden["hitboxes"]}
        points = {t.id: t.color for t in self.project.point_types if t.id not in hidden["points"]}
        frame = self.frame()
        if frame is not None:
            # Items whose type was deleted (or never existed) show in grey, so they can be found and retyped.
            known_boxes = {t.id for t in self.project.collision_types}
            known_points = {t.id for t in self.project.point_types}
            boxes.update({c.type_id: UNKNOWN_TYPE_COLOUR for c in frame.collision_rects if c.type_id not in known_boxes})
            points.update({c.type_id: UNKNOWN_TYPE_COLOUR for c in frame.control_points if c.type_id not in known_points})
        self.stage.collision_type_colors = boxes
        self.stage.point_type_colors = points
        for mode in ("hitboxes", "points"):
            ids = [t.id for t in ops.types(self.project, mode)]
            if self._active_type[mode] not in ids:
                self._active_type[mode] = ids[0] if ids else None
        self.stage.active_collision_type_id = self._active_type["hitboxes"]
        self.stage.active_point_type_id = self._active_type["points"]
        if self.mode != "parts":
            type_list = ops.types(self.project, self.mode)
            names = [t.name for t in type_list]
            if self.type_choice.GetItems() != names:
                self.type_choice.SetItems(names)
            ids = [t.id for t in type_list]
            active = self._active_type[self.mode]
            self.type_choice.SetSelection(ids.index(active) if active in ids else wx.NOT_FOUND)

    def _on_type_choice(self) -> None:
        index = self.type_choice.GetSelection()
        type_list = ops.types(self.project, self.mode) if self.mode != "parts" else []
        if 0 <= index < len(type_list):
            self._active_type[self.mode] = type_list[index].id
            self._sync_types()

    def _on_type_action(self, action: str, type_id: str, value: Any) -> None:
        mode = self.mode
        type_list = ops.types(self.project, mode)
        kind = next((t for t in type_list if t.id == type_id), None)
        if action == "clean":
            removed = ops.remove_empty_hitboxes(self.project)
            self._commit()
            app_services.show_status(f"Removed {removed} empty hitbox(es) (undo with Cmd/Ctrl+Z)")
            return
        if action == "add":
            new = ops.add_type(self.project, mode)
            self._active_type[mode] = new.id
        elif action == "rename" and kind is not None and value and value != kind.name:
            kind.name = value
        elif action == "colour" and kind is not None:
            kind.color = tuple(value)
        elif action == "visible" and kind is not None:
            hidden = self.inspector.hidden_types[mode]
            hidden.discard(type_id) if value else hidden.add(type_id)
            self.refresh(frames=False)
            return
        elif action == "delete" and kind is not None:
            count, frames = ops.type_usage(self.project, mode, type_id)
            if count and wx.MessageBox(
                f"Delete '{kind.name}' and its {count} {'hitbox(es)' if mode == 'hitboxes' else 'point(s)'} in {frames} frame(s)?"
                "\n\n(Undo with Cmd/Ctrl+Z.)", "Delete Type", wx.YES_NO | wx.ICON_WARNING, self,
            ) != wx.YES:
                return
            ops.delete_type(self.project, mode, type_id)
        else:
            return
        self._commit()

    def _on_show_hitboxes(self, value: bool) -> None:
        self.stage.show_collision = value
        self.stage.Refresh(False)

    def _on_show_points(self, value: bool) -> None:
        self.stage.show_points = value
        self.stage.Refresh(False)

    # ================================================================== onion skin
    def _update_ghosts(self) -> None:
        mode = ONION_MODES[max(0, self.onion_choice.GetSelection())][1]
        frame = self.frame()
        layers: List[Dict[str, Any]] = []
        if frame is not None and mode != "off" and frame in self._view:
            index = self._view.index(frame)
            if mode in ("previous", "both") and index > 0:
                layers.append({"frame": self._view[index - 1], "style": GHOST_PREVIOUS})
            if mode in ("next", "both") and index + 1 < len(self._view):
                layers.append({"frame": self._view[index + 1], "style": GHOST_NEXT})
        self.stage.ghost_layers = layers
        self.stage.Refresh(False)

    # ================================================================== stage events
    def _stage_interaction(self) -> None:
        if self.mode == "parts":
            self._sync_library_pick()
        self.contents.list.set_selected(self.selected_ids(), ensure_visible=True)
        self.btn_item_delete.Enable(bool(self.selected_ids()))
        self._refresh_inspector()

    def _stage_live(self) -> None:
        self._refresh_inspector()

    def _on_stage_right_down(self, event: wx.MouseEvent) -> None:
        frame = self.frame()
        if frame is None:
            return
        world = self.stage.screen_to_world(event.GetPosition())
        if self.mode == "parts":
            hits = self.stage.hit_test_all(world)
            hit = next((fm for fm in hits if fm.id in self.stage.selected_fmodules), hits[0] if hits else None)
            if hit is not None and hit.id not in self.stage.selected_fmodules:
                self.stage.selected_fmodules = [hit.id]
        elif self.mode == "hitboxes":
            hit = self.stage.hit_test_collision_rect(world)
            if hit is not None and hit.id not in self.stage.selected_collision_rects:
                self.stage.selected_collision_rects = [hit.id]
        else:
            hit = self.stage.hit_test_control_point(world)
            if hit is not None and hit.id not in self.stage.selected_points:
                self.stage.selected_points = [hit.id]
        self._stage_interaction()
        self.stage.Refresh(False)
        self._stage_menu(event.GetPosition())

    def _stage_menu(self, pos: Optional[wx.Point]) -> None:
        selected = self.selected_items()
        menu = wx.Menu()

        def add(label: str, handler: Callable[[], None], enabled: bool = True) -> None:
            item = menu.Append(wx.ID_ANY, label)
            item.Enable(enabled)
            self.Bind(wx.EVT_MENU, lambda e: handler(), item)

        if self.mode == "parts" and selected:
            add("Flip Horizontally\tH", lambda: self._on_part_tool("flip_x"))
            add("Flip Vertically\tV", lambda: self._on_part_tool("flip_y"))
            add("Rotate 90° Clockwise\tR", lambda: self._on_part_tool("rot_cw"))
            add("Rotate 90° Counter-clockwise\tShift+R", lambda: self._on_part_tool("rot_ccw"))
            menu.AppendSeparator()
            add("Bring to Front", lambda: self._on_part_tool("top"))
            add("Bring Forward", lambda: self._on_part_tool("up"))
            add("Send Backward", lambda: self._on_part_tool("down"))
            add("Send to Back", lambda: self._on_part_tool("bottom"))
            menu.AppendSeparator()
            add("Use Library Pick", lambda: self._on_part_tool("swap"), self.library.picked() is not None)
            add("Open Module / Frame", lambda: self._on_part_tool("open"), len(selected) == 1)
            menu.AppendSeparator()
            add("Delete", self.delete_selection)
        elif selected:
            add("Delete", self.delete_selection)
        else:
            add("Select All\tCmd+A", self.edit_select_all, self.frame() is not None)
            add("Paste\tCmd+V", self.edit_paste, bool(_ITEM_CLIPBOARD["items"]))
        window = self.stage if pos is not None else self.contents.list
        if pos is not None:
            window.PopupMenu(menu, pos)
        else:
            window.PopupMenu(menu)
        menu.Destroy()

    # ================================================================== parts
    def add_part(self, ref_type: str, ref_id: str, position: Tuple[int, int]) -> None:
        frame = self.frame()
        if frame is None:
            self.new_frame()
            frame = self.frame()
            if frame is None:
                return
        if self.mode != "parts":
            self.set_mode("parts")
        part = ops.add_part(self.project, frame, ref_type, ref_id, position)
        if part is None:
            wx.MessageBox("A frame cannot contain itself (directly or through other frames).", "Add Frame",
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        self.stage.selected_fmodules = [part.id]
        self._commit()
        self.stage.SetFocus()

    def _on_part_field(self, field: str, value: Any) -> None:
        parts = self.selected_items() if self.mode == "parts" else []
        if len(parts) != 1:
            return
        part = parts[0]
        if field == "x":
            part.position = (int(value), part.position[1])
        elif field == "y":
            part.position = (part.position[0], int(value))
        elif field == "flip_x":
            part.flip_x = bool(value)
        elif field == "flip_y":
            part.flip_y = bool(value)
        else:
            return
        self._commit()

    def _on_part_tool(self, name: str) -> None:
        frame = self.frame()
        ids = self.selected_ids() if self.mode == "parts" else []
        if frame is None or not ids:
            return
        if name in ("flip_x", "flip_y"):
            ops.flip_parts(self.project, frame, ids, name[-1], self.project.active_mapping)
        elif name in ("rot_cw", "rot_ccw"):
            ops.rotate_parts(frame, ids, 90 if name == "rot_cw" else -90)
        elif name in ("up", "down", "top", "bottom"):
            if not ops.reorder_parts(frame, ids, name):
                return
        elif name == "swap":
            picked = self.library.picked()
            if picked is None:
                app_services.show_status("Select a module or frame in the library first")
                return
            if ops.swap_source(self.project, frame, ids, *picked) == 0:
                app_services.show_status("Nothing changed (a frame cannot contain itself)")
                return
        elif name == "open":
            part = next(fm for fm in frame.fmodules if fm.id == ids[0])
            if part.ref_type == "frame":
                self.select_frame_by_id(part.ref_id)
            elif self.on_open_module:
                self.on_open_module(part.ref_id)
            return
        else:
            return
        self._commit()

    def _on_marker_field(self, field: str, value: Any) -> None:
        markers = self.selected_items() if self.mode != "parts" else []
        if not markers:
            return
        if field == "type":
            for m in markers:
                m.type_id = value
        elif len(markers) == 1:
            m = markers[0]
            if field == "role":
                m.role = str(value)
            elif self.mode == "hitboxes" and field in ("x", "y", "w", "h"):
                x, y, w, h = m.rect
                values = {"x": x, "y": y, "w": w, "h": h}
                values[field] = max(0, int(value)) if field in ("w", "h") else int(value)
                m.rect = (values["x"], values["y"], values["w"], values["h"])
            elif self.mode == "points" and field in ("x", "y"):
                setattr(m, field, int(value))
            else:
                return
        else:
            return
        self._commit()

    def _move_item(self, item_id: str, before_id: Optional[str]) -> None:
        frame = self.frame()
        if frame is None:
            return
        if self.mode == "parts":
            # The list shows parts top-most first, the frame stores them back to front.
            order = [fm.id for fm in frame.fmodules if fm.id != item_id]
            if before_id is None:
                model_before = order[0] if order else None
            else:
                index = order.index(before_id) + 1
                model_before = order[index] if index < len(order) else None
            ops.move_item(frame, "parts", item_id, model_before)
        else:
            ops.move_item(frame, self.mode, item_id, before_id)
        self._commit()

    def delete_selection(self) -> None:
        frame = self.frame()
        ids = self.selected_ids()
        if frame is None or not ids:
            return
        count = ops.delete_items(frame, self.mode, ids)
        self.set_selected([])
        self._commit()
        app_services.show_status(f"Deleted {count} item(s)")

    def nudge(self, dx: int, dy: int) -> None:
        frame = self.frame()
        if frame is None or not self.selected_ids():
            return
        ops.nudge(frame, self.mode, self.selected_ids(), dx, dy)
        self.stage.Refresh(False)
        self._refresh_inspector()
        self._refresh_contents()
        app_services.request_checkpoint()

    def _flip(self, axis: str) -> None:
        """H / V: flip the selected parts as a group, or the whole frame's parts when nothing is selected."""
        frame = self.frame()
        if frame is None or self.mode != "parts":
            return
        ids = self.selected_ids()
        ops.flip_parts(self.project, frame, ids or None, axis, self.project.active_mapping)
        self._commit()

    # ================================================================== edit menu
    def edit_copy(self) -> None:
        items = self.selected_items()
        if not items:
            app_services.show_status("Nothing selected to copy")
            return
        _ITEM_CLIPBOARD["mode"] = self.mode
        _ITEM_CLIPBOARD["items"] = [item.to_dict() for item in items]
        app_services.show_status(f"Copied {len(items)} item(s)")

    def edit_cut(self) -> None:
        if self.selected_items():
            self.edit_copy()
            self.delete_selection()

    def edit_paste(self) -> None:
        mode, data = _ITEM_CLIPBOARD.get("mode"), _ITEM_CLIPBOARD.get("items") or []
        if not mode or not data:
            app_services.show_status("Clipboard is empty")
            return
        frame = self.frame()
        if frame is None:
            self.new_frame()
            frame = self.frame()
            if frame is None:
                return
        if mode != self.mode:
            self.set_mode(mode)
        new_ids = ops.insert_items(self.project, frame, mode, data)
        self.set_selected(new_ids)
        self._commit()
        app_services.show_status(f"Pasted {len(new_ids)} item(s)" + (f" ({len(data) - len(new_ids)} skipped: a frame cannot contain itself)" if len(new_ids) < len(data) else ""))

    def edit_duplicate(self) -> None:
        items = self.selected_items()
        if not items or wx.Window.FindFocus() is self.browser.list:
            self.duplicate_frame()
            return
        new_ids = ops.insert_items(self.project, self.frame(), self.mode, [item.to_dict() for item in items])
        self.set_selected(new_ids)
        self._commit()
        app_services.show_status(f"Duplicated {len(new_ids)} item(s) in place; move them with the arrow keys")

    def edit_select_all(self) -> None:
        frame = self.frame()
        if frame is not None:
            self.set_selected([item.id for item in ops.items(frame, self.mode)])

    # ================================================================== keyboard
    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if not self.IsShownOnScreen() or app_services.text_entry_has_focus() or self.browser.list.is_renaming():
            event.Skip()
            return
        key = event.GetKeyCode()
        focus = wx.Window.FindFocus()
        if focus is self.browser.list:
            if key in (wx.WXK_DELETE, wx.WXK_BACK) and not event.HasAnyModifiers():
                self.delete_frame()
                return
            if key == wx.WXK_F2:
                self.browser.list.begin_rename()
                return
            event.Skip()
            return
        if focus in (self.library.modules, self.library.frames):
            event.Skip()
            return
        cmd = event.CmdDown() or event.ControlDown()
        if cmd and key in (wx.WXK_UP, wx.WXK_DOWN) and self.mode == "parts":
            if key == wx.WXK_UP:
                self._on_part_tool("top" if event.ShiftDown() else "up")
            else:
                self._on_part_tool("bottom" if event.ShiftDown() else "down")
            return
        if cmd or event.AltDown():
            event.Skip()
            return
        if key == wx.WXK_ESCAPE:
            self.set_selected([])
            return
        if key in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN):
            if focus is self.contents.list and not self.selected_ids():
                event.Skip()
                return
            step = NUDGE_LARGE if event.ShiftDown() else 1
            self.nudge({wx.WXK_LEFT: -step, wx.WXK_RIGHT: step}.get(key, 0), {wx.WXK_UP: -step, wx.WXK_DOWN: step}.get(key, 0))
            return
        if key in (ord("H"), ord("X")):
            self._flip("x")
        elif key in (ord("V"), ord("Y")):
            self._flip("y")
        elif key == ord("R"):
            self._on_part_tool("rot_ccw" if event.ShiftDown() else "rot_cw")
        elif key in (wx.WXK_DELETE, wx.WXK_BACK):
            self.delete_selection()
        else:
            event.Skip()
