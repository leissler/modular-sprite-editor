"""Mappings tab: Mappings | module map | replacement picker + preview.

A mapping swaps modules for others (or hides them) everywhere: palette or outfit variants without
duplicating frames. The selected mapping is the preview mapping of every tab (context bar).
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

import wx

from models import ModuleMapping, Project
from ui import app_services
from ui.components.frame_palette import FramePalette
from ui.components.module_palette import SHAPES_KEY, ModulePalette, sheet_of
from ui.components.inspector_kit import fit_choice
from ui.components.thumb_list import Browser, Row, title_label
from ui.mapping_editor import ops
from ui.mapping_editor.table import MapTable
from ui.module_editor import ops as module_ops


class UsagePreview(FramePalette):
    """Frames that show the selected modules, drawn with the mapping."""

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project)
        self.item_size = (80, 80)
        self.frame_ids: Optional[List[str]] = None

    def visible_frames(self):
        frames = list(self.project.frames) if self.frame_ids is None else [f for f in (self.project.get_frame(i) for i in self.frame_ids) if f]
        return [f for f in frames if not self.filter_text or self.filter_text in f.name.lower()]

    def _calculate_uniform_scale(self) -> float:
        if self._cached_scale > 0:
            return self._cached_scale
        mapping = self.project.active_mapping
        sizes = [self.generator.frame_size(self.project, f, mapping) for f in self.visible_frames()]
        width = max((w for w, _h in sizes), default=0)
        height = max((h for _w, h in sizes), default=0)
        scale = min(self.item_size[0] / width, self.item_size[1] / height, 4.0) if width and height else 1.0
        self._cached_scale = float(int(scale)) if scale >= 1 else scale
        return self._cached_scale


class MappingEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.current_mapping: Optional[ModuleMapping] = None
        self.selection: List[str] = []
        self._sheet_keys: List[Optional[str]] = [None]
        self._picker_keys: List[Optional[str]] = [None]
        self.on_open_module: Optional[Callable[[str], None]] = None  # set by the main window

        self._build_ui()
        self._bind()
        self.set_project(project)

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        self.outer_split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.browser = Browser(self.outer_split, "Mappings", row_h=44, thumb=0, reorder=True)
        self.browser.search.Hide()
        self.btn_new = self.browser.add_button("+ New", "New mapping (everything original)", self.new_mapping)
        self.btn_dup = self.browser.add_button("Duplicate", "Duplicate the selected mapping", self.duplicate_mapping)
        self.btn_del = self.browser.add_button("Delete", "Delete the selected mapping", self.delete_mapping)
        info = wx.StaticText(self.browser, label="The selected mapping previews in every tab and is used by the exports (see the bar above the tabs).")
        info.SetForegroundColour(wx.Colour(150, 156, 170))
        info.Wrap(230)
        self.browser.sizer.Add(info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.inner_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        centre = wx.Panel(self.inner_split)
        csizer = wx.BoxSizer(wx.VERTICAL)
        self.table_title = title_label(centre, "MODULES")
        csizer.Add(self.table_title, 0, wx.LEFT | wx.TOP, 8)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.SearchCtrl(centre, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Filter modules")
        self.search.ShowCancelButton(True)
        self.sheet_choice = wx.Choice(centre)
        self.chk_changed = wx.CheckBox(centre, label="Changed only")
        self.chk_changed.SetToolTip("Only modules this mapping replaces or hides")
        filters.Add(self.search, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        filters.Add(self.sheet_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        filters.Add(self.chk_changed, 0, wx.ALIGN_CENTER_VERTICAL)
        csizer.Add(filters, 0, wx.EXPAND | wx.ALL, 6)
        tools = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_original = wx.Button(centre, label="Original", style=wx.BU_EXACTFIT)
        self.btn_original.SetToolTip("Show the selected modules as themselves (Delete)")
        self.btn_hide = wx.Button(centre, label="Hide", style=wx.BU_EXACTFIT)
        self.btn_hide.SetToolTip("Do not draw the selected modules (H)")
        self.btn_match = wx.Button(centre, label="Match ▾", style=wx.BU_EXACTFIT)
        self.btn_match.SetToolTip("Map many modules at once: same layout on another image, or by name")
        self.btn_reset_all = wx.Button(centre, label="Reset all", style=wx.BU_EXACTFIT)
        self.btn_reset_all.SetToolTip("Every module original again")
        for btn in (self.btn_original, self.btn_hide):
            tools.Add(btn, 0, wx.RIGHT, 4)
        tools.AddSpacer(10)
        tools.Add(self.btn_match, 0, wx.RIGHT, 4)
        tools.AddStretchSpacer(1)
        tools.Add(self.btn_reset_all, 0)
        csizer.Add(tools, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.empty_hint = wx.StaticText(centre, label="")
        self.empty_hint.SetForegroundColour(wx.Colour(150, 156, 170))
        csizer.Add(self.empty_hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.table = MapTable(centre)
        csizer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        hint = wx.StaticText(centre, label="Select rows, then click a module on the right (or drag one onto a row). Delete = original, H = hide.")
        hint.SetForegroundColour(wx.Colour(150, 156, 170))
        csizer.Add(hint, 0, wx.ALL, 6)
        centre.SetSizer(csizer)

        self.right_split = wx.SplitterWindow(self.inner_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        picker = wx.Panel(self.right_split)
        psizer = wx.BoxSizer(wx.VERTICAL)
        psizer.Add(title_label(picker, "REPLACE WITH"), 0, wx.LEFT | wx.TOP, 8)
        prow = wx.BoxSizer(wx.HORIZONTAL)
        self.picker_search = wx.SearchCtrl(picker, style=wx.TE_PROCESS_ENTER)
        self.picker_search.SetDescriptiveText("Filter")
        self.picker_search.ShowCancelButton(True)
        self.picker_sheet = wx.Choice(picker)
        prow.Add(self.picker_search, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        prow.Add(self.picker_sheet, 0, wx.ALIGN_CENTER_VERTICAL)
        psizer.Add(prow, 0, wx.EXPAND | wx.ALL, 6)
        self.picker = ModulePalette(picker, self.project, item_size=56)
        psizer.Add(self.picker, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        picker.SetSizer(psizer)

        preview = wx.Panel(self.right_split)
        vsizer = wx.BoxSizer(wx.VERTICAL)
        self.preview_title = title_label(preview, "PREVIEW")
        vsizer.Add(self.preview_title, 0, wx.LEFT | wx.TOP, 8)
        self.preview_info = wx.StaticText(preview, label="")
        self.preview_info.SetForegroundColour(wx.Colour(150, 156, 170))
        vsizer.Add(self.preview_info, 0, wx.LEFT | wx.TOP, 8)
        self.preview = UsagePreview(preview, self.project)
        vsizer.Add(self.preview, 1, wx.EXPAND | wx.ALL, 6)
        preview.SetSizer(vsizer)
        self.right_split.SplitHorizontally(picker, preview, 0)
        self.right_split.SetSashGravity(0.5)
        self.right_split.SetMinimumPaneSize(140)

        self.inner_split.SplitVertically(centre, self.right_split, -330)
        self.inner_split.SetSashGravity(1.0)
        self.inner_split.SetMinimumPaneSize(260)
        self.outer_split.SplitVertically(self.browser, self.inner_split, 250)
        self.outer_split.SetMinimumPaneSize(180)
        root.Add(self.outer_split, 1, wx.EXPAND)
        self.SetSizer(root)
        wx.CallAfter(self._place_sashes)

    def _place_sashes(self) -> None:
        height = self.right_split.GetClientSize().height
        if height > 300:
            self.right_split.SetSashPosition(int(height * 0.55))

    def _bind(self) -> None:
        bl = self.browser.list
        bl.Bind(wx.EVT_LISTBOX, lambda e: self._on_list_select())
        bl.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: bl.begin_rename())
        bl.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        bl.on_rename = self._rename
        bl.on_move = self._move
        self.search.Bind(wx.EVT_TEXT, lambda e: self.refresh_table())
        self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.search.SetValue(""))
        self.sheet_choice.Bind(wx.EVT_CHOICE, lambda e: self.refresh_table())
        self.chk_changed.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_table())
        self.btn_original.Bind(wx.EVT_BUTTON, lambda e: self.apply(None, reset=True))
        self.btn_hide.Bind(wx.EVT_BUTTON, lambda e: self.apply(None))
        self.btn_match.Bind(wx.EVT_BUTTON, lambda e: self._match_menu())
        self.btn_reset_all.Bind(wx.EVT_BUTTON, lambda e: self.reset_all())
        self.table.Bind(wx.EVT_LISTBOX, lambda e: self._on_table_select())
        self.table.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._reveal_target())
        self.table.Bind(wx.EVT_CONTEXT_MENU, lambda e: self._table_menu())
        self.table.Bind(wx.EVT_KEY_DOWN, self._on_table_key)
        self.table.on_drop = self._on_drop
        self.picker.on_module_click = lambda module_id: self.apply(module_id)
        self.picker_search.Bind(wx.EVT_TEXT, lambda e: self.picker.set_filter(self.picker_search.GetValue()))
        self.picker_search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.picker_search.SetValue(""))
        self.picker_sheet.Bind(wx.EVT_CHOICE, lambda e: self.picker.set_sheet(self._picker_keys[max(0, self.picker_sheet.GetSelection())]))

    # ================================================================== main-window interface
    def get_active_canvas(self):
        return None

    def set_project(self, project: Project) -> None:
        self.project = project
        self.picker.project = project
        self.preview.project = project
        self.selection = []
        self.current_mapping = project.active_mapping
        self.search.ChangeValue("")
        self.picker_search.ChangeValue("")
        self.picker.filter_text = ""
        self._refresh_sheet_choices()
        self.refresh_list()
        self.refresh_table()

    def refresh_after_history(self) -> None:
        self.current_mapping = self.project.active_mapping
        self.selection = [i for i in self.selection if self.project.get_module(i)]
        self._refresh_sheet_choices()
        self.refresh_list()
        self.refresh_table()

    def on_tab_activated(self) -> None:
        self.current_mapping = self.project.active_mapping
        self._refresh_sheet_choices()
        self.refresh_list()
        self.refresh_table()

    def on_active_mapping_changed(self) -> None:
        """The context bar picked another preview mapping."""
        self.current_mapping = self.project.active_mapping
        self.refresh_list()
        self.refresh_table()

    def stop_playback(self) -> None:
        pass

    # kept for the main window
    def refresh_list_and_table(self) -> None:
        self.on_tab_activated()

    # ================================================================== lists
    def _refresh_sheet_choices(self) -> None:
        keys: List[Optional[str]] = [None] + [img.id for img in self.project.images]
        labels = ["All images"] + [module_ops.image_label(img) for img in self.project.images]
        if any(m.type != "MD_IMAGE" for m in self.project.modules):
            keys.append(SHAPES_KEY)
            labels.append("Shapes")
        for choice, attr in ((self.sheet_choice, "_sheet_keys"), (self.picker_sheet, "_picker_keys")):
            current = getattr(self, attr)[choice.GetSelection()] if choice.GetSelection() >= 0 else None
            setattr(self, attr, keys)
            choice.SetItems(labels)
            fit_choice(choice)
            choice.SetSelection(keys.index(current) if current in keys else 0)
        self.picker.sheet = self._picker_keys[self.picker_sheet.GetSelection()]
        self.picker.refresh_modules()

    def refresh_list(self) -> None:
        rows = [Row(m.id, m.name, ops.describe(self.project, m)) for m in self.project.mappings]
        if self.current_mapping not in self.project.mappings:
            self.current_mapping = None
        self.browser.list.set_rows(rows, [self.current_mapping.id] if self.current_mapping else [])
        self.browser.set_count(len(rows), len(rows))
        self.btn_dup.Enable(self.current_mapping is not None)
        self.btn_del.Enable(self.current_mapping is not None)

    def visible_module_ids(self) -> List[str]:
        query = self.search.GetValue().strip().lower()
        sheet = self._sheet_keys[self.sheet_choice.GetSelection()] if self.sheet_choice.GetSelection() >= 0 else None
        changed_only = self.chk_changed.GetValue()
        ids = []
        for m in self.project.modules:
            if sheet is not None and sheet_of(m) != sheet:
                continue
            if query and query not in m.name.lower():
                continue
            if changed_only and (self.current_mapping is None or m.id not in self.current_mapping.map):
                continue
            ids.append(m.id)
        return ids

    def refresh_table(self) -> None:
        mapping = self.current_mapping
        ids = self.visible_module_ids() if mapping is not None else []
        self.selection = [i for i in self.selection if i in ids]
        self.table.set_rows(self.project, mapping, ids, self.selection)
        total = len(self.project.modules)
        self.table_title.SetLabel(f"MODULES ({len(ids)} OF {total})" if mapping is not None and len(ids) != total else f"MODULES ({total})")
        if mapping is None:
            self.empty_hint.SetLabel("No mapping selected: pick one on the left, or click + New to make one.")
        else:
            self.empty_hint.SetLabel(f"{mapping.name}: {ops.describe(self.project, mapping)}")
        for ctrl in (self.btn_original, self.btn_hide):
            ctrl.Enable(mapping is not None and bool(self.selection))
        for ctrl in (self.btn_match, self.btn_reset_all, self.picker, self.search, self.sheet_choice, self.chk_changed):
            ctrl.Enable(mapping is not None)
        self.btn_reset_all.Enable(mapping is not None and bool(mapping.map))
        self._refresh_marks()
        self._refresh_preview()
        self.Layout()

    def _refresh_marks(self) -> None:
        mapping = self.current_mapping
        marked = set()
        if mapping is not None and len(self.selection) == 1:
            target = mapping.map.get(self.selection[0])
            if target:
                marked.add(target)
        self.picker.marked = marked
        self.picker.Refresh()

    def _refresh_preview(self) -> None:
        if self.current_mapping is None:
            self.preview.frame_ids = []
            self.preview_info.SetLabel("")
        elif self.selection:
            frames = ops.frames_using(self.project, self.selection)
            self.preview.frame_ids = [f.id for f in frames]
            self.preview_info.SetLabel(f"{len(frames)} frame{'s' if len(frames) != 1 else ''} with the selected module{'s' if len(self.selection) != 1 else ''}")
        else:
            changed = [k for k in self.current_mapping.map if self.project.get_module(k)]
            frames = ops.frames_using(self.project, changed)
            self.preview.frame_ids = [f.id for f in frames]
            self.preview_info.SetLabel(f"{len(frames)} frame{'s' if len(frames) != 1 else ''} this mapping changes")
        self.preview.invalidate_scale()
        self.preview.Scroll(0, 0)
        self.preview.layout_items()
        self.preview.Refresh()

    # ================================================================== mapping list
    def _set_active(self, mapping: Optional[ModuleMapping]) -> None:
        self.current_mapping = mapping
        self.project.active_mapping = mapping
        app_services.notify_active_mapping_changed()
        self.refresh_list()
        self.refresh_table()

    def _on_list_select(self) -> None:
        ids = self.browser.list.selected_ids()
        mapping = next((m for m in self.project.mappings if ids and m.id == ids[0]), None)
        if mapping is not self.current_mapping:
            self._set_active(mapping)

    def new_mapping(self) -> None:
        mapping = ops.new_mapping(self.project, self.current_mapping.id if self.current_mapping else None)
        self._set_active(mapping)
        app_services.request_checkpoint()
        wx.CallAfter(self.browser.list.begin_rename, mapping.id)

    def duplicate_mapping(self) -> None:
        if self.current_mapping is None:
            return
        copy = ops.duplicate_mapping(self.project, self.current_mapping.id)
        self._set_active(copy)
        app_services.request_checkpoint()

    def delete_mapping(self) -> None:
        mapping = self.current_mapping
        if mapping is None:
            return
        message = f"Delete the mapping '{mapping.name}' ({ops.describe(self.project, mapping)})?\n\n(Undo with Cmd/Ctrl+Z.)"
        if wx.MessageBox(message, "Delete Mapping", wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
            return
        index = self.project.mappings.index(mapping)
        ops.delete_mapping(self.project, mapping.id)
        remaining = self.project.mappings
        self._set_active(remaining[min(index, len(remaining) - 1)] if remaining else None)
        app_services.request_checkpoint()

    # old name (the main window's Delete key handling used it)
    def on_del(self, _event: Any = None) -> None:
        self.delete_mapping()

    def _rename(self, mapping_id: str, name: str) -> None:
        mapping = next((m for m in self.project.mappings if m.id == mapping_id), None)
        if mapping is not None and name != mapping.name:
            mapping.name = name
            self.refresh_list()
            self.refresh_table()
            app_services.notify_active_mapping_changed()
            app_services.request_checkpoint()

    def _move(self, mapping_id: str, before_id: Optional[str]) -> None:
        ops.move_mapping(self.project, mapping_id, before_id)
        self.refresh_list()
        app_services.notify_active_mapping_changed()
        app_services.request_checkpoint()

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_BACK) and not event.HasAnyModifiers():
            self.delete_mapping()
        elif event.GetKeyCode() == wx.WXK_F2:
            self.browser.list.begin_rename()
        else:
            event.Skip()

    # ================================================================== editing
    def _on_table_select(self) -> None:
        self.selection = self.table.selected_ids()
        for ctrl in (self.btn_original, self.btn_hide):
            ctrl.Enable(self.current_mapping is not None and bool(self.selection))
        self._refresh_marks()
        self._refresh_preview()

    def apply(self, target_id: Optional[str], reset: bool = False, ids: Optional[List[str]] = None) -> None:
        """Replace the selected modules with ``target_id`` (None = hide, reset = original)."""
        mapping = self.current_mapping
        ids = ids if ids is not None else self.selection
        if mapping is None:
            return
        if not ids:
            app_services.show_status("Select one or more modules in the list first")
            return
        changed = ops.reset(mapping, ids) if reset else ops.assign(mapping, ids, target_id)
        if not changed:
            return
        self._changed()
        if reset:
            what = "original"
        elif target_id is None:
            what = "hidden"
        else:
            target = self.project.get_module(target_id)
            what = f"→ {target.name}" if target else "replaced"
        app_services.show_status(f"{changed} module(s) {what}")

    def _on_drop(self, row_id: str, module_id: str) -> None:
        ids = self.selection if row_id in self.selection else [row_id]
        self.apply(module_id, ids=ids)

    def reset_all(self) -> None:
        mapping = self.current_mapping
        if mapping is None or not mapping.map:
            return
        if wx.MessageBox(f"Make every module original again in '{mapping.name}'?\n\n(Undo with Cmd/Ctrl+Z.)", "Reset All",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        mapping.map = {}
        self._changed()

    def _changed(self) -> None:
        self.table.Refresh()
        self.refresh_list()
        self.refresh_table()
        app_services.notify_active_mapping_changed()
        app_services.request_checkpoint()

    def _reveal_target(self) -> None:
        mapping = self.current_mapping
        if mapping is None or len(self.selection) != 1:
            return
        target = mapping.map.get(self.selection[0])
        if target and self.project.get_module(target):
            self.picker_search.ChangeValue("")
            self.picker.filter_text = ""
            self.picker_sheet.SetSelection(0)
            self.picker.sheet = None
            self.picker.refresh_modules()
            self.picker.select_module(target)

    def _table_menu(self) -> None:
        if self.current_mapping is None:
            return
        menu = wx.Menu()

        def add(label: str, handler: Callable[[], None], enabled: bool = True) -> None:
            item = menu.Append(wx.ID_ANY, label)
            item.Enable(enabled)
            self.Bind(wx.EVT_MENU, lambda e: handler(), item)

        has = bool(self.selection)
        add("Use Original", lambda: self.apply(None, reset=True), has)
        add("Hide", lambda: self.apply(None), has)
        add("Use Picked Module", lambda: self.apply(self.picker.selected_module_id), has and bool(self.picker.selected_module_id))
        menu.AppendSeparator()
        add("Match Names…", self.match_by_name)
        add("Show in Modules Tab", lambda: self.on_open_module and self.on_open_module(self.selection[0]), len(self.selection) == 1)
        self.table.PopupMenu(menu)
        menu.Destroy()

    def _on_table_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if event.HasAnyModifiers() and not event.ShiftDown():
            event.Skip()
            return
        if key in (wx.WXK_DELETE, wx.WXK_BACK):
            self.apply(None, reset=True)
        elif key == ord("H"):
            self.apply(None)
        else:
            event.Skip()

    # ================================================================== bulk matching
    def _match_menu(self) -> None:
        menu = wx.Menu()
        item_pos = menu.Append(wx.ID_ANY, "Same Layout on Another Image…")
        item_name = menu.Append(wx.ID_ANY, "Match Names…")
        item_pos.Enable(len(self.project.images) >= 2)
        self.Bind(wx.EVT_MENU, lambda e: self.match_by_position(), item_pos)
        self.Bind(wx.EVT_MENU, lambda e: self.match_by_name(), item_name)
        self.btn_match.PopupMenu(menu)
        menu.Destroy()

    def match_by_position(self) -> None:
        mapping = self.current_mapping
        if mapping is None or len(self.project.images) < 2:
            return
        labels = [module_ops.image_label(img) for img in self.project.images]
        with wx.Dialog(self, title="Same Layout on Another Image") as dlg:
            sizer = wx.BoxSizer(wx.VERTICAL)
            text = wx.StaticText(dlg, label="Every module of the first image shows the module at exactly the same place on the second "
                                            "image (e.g. a recoloured copy of the sheet).")
            text.Wrap(380)
            sizer.Add(text, 0, wx.ALL, 12)
            grid = wx.FlexGridSizer(0, 2, 8, 10)
            source = wx.Choice(dlg, choices=labels)
            target = wx.Choice(dlg, choices=labels)
            source.SetSelection(0)
            target.SetSelection(1)
            grid.Add(wx.StaticText(dlg, label="Modules of"), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(source, 0)
            grid.Add(wx.StaticText(dlg, label="show the ones on"), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(target, 0)
            sizer.Add(grid, 0, wx.LEFT | wx.RIGHT, 12)
            buttons = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
            if buttons:
                sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
            dlg.SetSizerAndFit(sizer)
            dlg.CenterOnParent()
            if dlg.ShowModal() != wx.ID_OK:
                return
            src, dst = self.project.images[source.GetSelection()].id, self.project.images[target.GetSelection()].id
        if src == dst:
            return
        count = ops.match_by_position(self.project, mapping, src, dst)
        self._changed()
        app_services.show_status(f"Mapped {count} module(s) by position" if count else "No module of the first image has a twin at the same place")

    def match_by_name(self) -> None:
        mapping = self.current_mapping
        if mapping is None:
            return
        scope = list(self.selection) if self.selection else None
        with wx.Dialog(self, title="Match Names") as dlg:
            sizer = wx.BoxSizer(wx.VERTICAL)
            text = wx.StaticText(dlg, label="Modules whose name contains the first text show the module named with the second "
                                            "text instead, e.g. “_red” → “_blue”." + (" Only the selected modules." if scope else ""))
            text.Wrap(380)
            sizer.Add(text, 0, wx.ALL, 12)
            grid = wx.FlexGridSizer(0, 2, 8, 10)
            find = wx.TextCtrl(dlg, size=(160, -1))
            replace = wx.TextCtrl(dlg, size=(160, -1))
            preview = wx.StaticText(dlg, label="")
            preview.SetForegroundColour(wx.Colour(150, 156, 170))
            grid.Add(wx.StaticText(dlg, label="Name part"), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(find, 0)
            grid.Add(wx.StaticText(dlg, label="replaced by"), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(replace, 0)
            sizer.Add(grid, 0, wx.LEFT | wx.RIGHT, 12)
            sizer.Add(preview, 0, wx.ALL, 12)

            def update(_event=None) -> None:
                trial = ModuleMapping("trial", "trial")
                pairs = ops.match_by_name(self.project, trial, find.GetValue(), replace.GetValue(), scope)
                preview.SetLabel(f"{len(pairs)} module(s) would be mapped")

            find.Bind(wx.EVT_TEXT, update)
            replace.Bind(wx.EVT_TEXT, update)
            update()
            buttons = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
            if buttons:
                sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            dlg.SetSizerAndFit(sizer)
            dlg.CenterOnParent()
            if dlg.ShowModal() != wx.ID_OK:
                return
            pattern, replacement = find.GetValue(), replace.GetValue()
        pairs = ops.match_by_name(self.project, mapping, pattern, replacement, scope)
        self._changed()
        app_services.show_status(f"Mapped {len(pairs)} module(s) by name")
