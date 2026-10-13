"""Modules tab: Images + Modules | sheet canvas | inspector.

Cut modules straight on the sheet (drag on empty space), select / move / resize them there, set pivots
with Shift+drag or a preset; slicing tools live with the sheet in the inspector.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

import wx

from models import FModule, ImageAsset, Module, Project, generate_id
from ui import app_services
from ui.components import confirm
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.components.module_palette import THUMBNAILS
from ui.components.thumb_list import Browser, Row
from ui.frame_render import SHARED, fit_bitmap, to_wx_image
from ui.module_editor import ops
from ui.module_editor.canvas import SheetCanvas
from ui.module_editor.dialogs import DetectDialog, FolderImportDialog, GridSliceDialog
from ui.module_editor.inspector import ModuleInspector

IMAGE_WILDCARD = "Images (*.png;*.bmp;*.gif;*.jpg;*.jpeg)|*.png;*.bmp;*.gif;*.jpg;*.jpeg|All files|*.*"
TILE_BG = (52, 53, 58)

# Copied modules (as dicts), shared between sheets for the session: paste repeats the same cuts elsewhere.
_MODULE_CLIPBOARD: List[Dict[str, Any]] = []


class ModuleEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.sheet_key: Optional[str] = None
        self.selection: List[str] = []
        self.show_key_colour = False
        self._view_states: Dict[str, Tuple[Tuple[float, float], float]] = {}
        self._sheet_thumbs: Dict[Any, wx.Bitmap] = {}
        self._grid_values: Dict[str, int] = {"tile_w": 16, "tile_h": 16, "skip_empty": 1}
        self._merge_gap = 1
        self._counts: Dict[str, int] = {}
        self.on_open_frame: Optional[Callable[[str], None]] = None  # set by the main window

        self._build_ui()
        self._bind()
        self.set_project(project)

    # ================================================================== layout
    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        self.outer_split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.left_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)

        self.sheets = Browser(self.left_split, "Images", row_h=46, thumb=38, reorder=True)
        self.sheets.search.Hide()
        self.btn_add_image = self.sheets.add_button("+ Add ▾", "Add an image file or a whole folder", self._add_menu)
        self.btn_remove_image = self.sheets.add_button("Remove", "Remove the image and its modules from the project", self.remove_image)

        self.modules = Browser(self.left_split, "Modules", row_h=40, thumb=32, multiple=True, reorder=True)
        self.btn_slice = self.modules.add_button("Slice ▾", "Grid slice, detect sprites or auto modularize this image", self._slice_menu)
        self.btn_dup = self.modules.add_button("Duplicate", "Duplicate the selected modules (Cmd+D)", self.duplicate_modules)
        self.btn_del = self.modules.add_button("Delete", "Delete the selected modules (Delete)", self.delete_modules)

        self.left_split.SplitHorizontally(self.sheets, self.modules, 200)
        self.left_split.SetMinimumPaneSize(110)

        self.inner_split = wx.SplitterWindow(self.outer_split, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        canvas_panel = wx.Panel(self.inner_split)
        canvas_sizer = wx.BoxSizer(wx.VERTICAL)
        self.canvas = SheetCanvas(canvas_panel, self.project)
        self.canvas_controls = CanvasDisplayControls(
            canvas_panel, self.canvas, view_key="modules", key_colour_toggle=True,
            on_key_colour_changed=self._on_show_key_colour,
        )
        self.canvas_controls.add_separator()
        self.chk_snap = self.canvas_controls.add_toggle("Snap", False, self._on_snap, "Snap drawing, moving and resizing to the grid")
        self.chk_names = self.canvas_controls.add_toggle("Names", False, self._on_names, "Show module names on the sheet")
        self.chk_pivots = self.canvas_controls.add_toggle("Pivots", False, self._on_pivots, "Show the pivot of every module")
        canvas_sizer.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 2)
        canvas_sizer.Add(self.canvas_controls, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        canvas_panel.SetSizer(canvas_sizer)

        self.inspector = ModuleInspector(self.inner_split)
        self.inner_split.SplitVertically(canvas_panel, self.inspector, -300)
        self.inner_split.SetSashGravity(1.0)
        self.inner_split.SetMinimumPaneSize(240)
        self.outer_split.SplitVertically(self.left_split, self.inner_split, 270)
        self.outer_split.SetMinimumPaneSize(200)
        root.Add(self.outer_split, 1, wx.EXPAND)
        self.SetSizer(root)
        self.canvas_controls.set_key_colour_shown(False)

    def _bind(self) -> None:
        sl = self.sheets.list
        sl.thumbnail = self._sheet_thumbnail
        sl.Bind(wx.EVT_LISTBOX, lambda e: self.select_sheet(next(iter(sl.selected_ids()), None)))
        sl.on_move = self._move_image
        ml = self.modules.list
        ml.thumbnail = self._module_thumbnail
        ml.Bind(wx.EVT_LISTBOX, lambda e: self._list_selection_changed())
        ml.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: ml.begin_rename())
        ml.Bind(wx.EVT_CONTEXT_MENU, lambda e: self._module_menu(None))
        ml.on_rename = self._rename_module
        ml.on_move = self._move_module
        self.modules.search.Bind(wx.EVT_TEXT, lambda e: self.refresh_modules())

        cv = self.canvas
        cv.on_select = self._canvas_selection
        cv.on_create = self._create_from_canvas
        cv.on_changed = self._live_changed
        cv.on_edit_end = self._commit
        cv.on_pick = self._picked_key
        cv.on_activate = lambda module_id: self._focus_name()
        cv.on_context_menu = self._module_menu

        ins = self.inspector
        ins.on_field = self._on_field
        ins.on_preset = self._on_preset
        ins.on_tool = self._on_tool
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    # ================================================================== main-window interface
    def get_active_canvas(self):
        return self.canvas

    def set_project(self, project: Project) -> None:
        self.project = project
        self.canvas.project = project
        self._view_states = {}
        self._sheet_thumbs = {}
        self.selection = []
        SHARED.clear()
        THUMBNAILS.clear()
        first = project.images[0].id if project.images else (ops.SHAPES_KEY if any(m.type != "MD_IMAGE" for m in project.modules) else None)
        self.sheet_key = None
        self.refresh_sheets()
        self.select_sheet(first, fit=True)

    def refresh_after_history(self) -> None:
        keys = self._sheet_keys()
        if self.sheet_key not in keys:
            self.sheet_key = None
        self.selection = [i for i in self.selection if self.project.get_module(i)]
        self._sheet_thumbs = {}
        self.refresh_sheets()
        self._load_sheet_image()
        self.refresh_modules()

    def on_tab_activated(self) -> None:
        """Frames may have started or stopped using modules (the usage counts)."""
        self.refresh_sheets()
        self.refresh_modules()

    def on_active_mapping_changed(self) -> None:
        pass  # the sheet shows the modules themselves, not their replacements

    def stop_playback(self) -> None:
        pass

    # ================================================================== helpers
    def asset(self) -> Optional[ImageAsset]:
        if self.sheet_key and not self.sheet_key.startswith("@"):
            return self.project.get_image(self.sheet_key)
        return None

    def sheet_modules(self) -> List[Module]:
        return ops.modules_of_sheet(self.project, self.sheet_key)

    def selected_modules(self) -> List[Module]:
        return [m for m in (self.project.get_module(i) for i in self.selection) if m is not None]

    def _sheet_keys(self) -> List[str]:
        keys = [img.id for img in self.project.images] + [ops.SHAPES_KEY]
        if ops.has_orphans(self.project):
            keys.append(ops.ORPHANS_KEY)
        return keys

    def _commit(self) -> None:
        self.refresh_modules()
        self.refresh_sheets()
        app_services.request_checkpoint()

    def _keyed_sheet(self) -> Any:
        asset = self.asset()
        return SHARED.sheet(self.project, asset, keyed=True) if asset else None

    # ================================================================== lists
    def refresh_sheets(self) -> None:
        rows = []
        for key in self._sheet_keys():
            if key == ops.SHAPES_KEY:
                count = len(ops.modules_of_sheet(self.project, key))
                rows.append(Row(key, "Shapes", f"{count} vector shape{'s' if count != 1 else ''}"))
            elif key == ops.ORPHANS_KEY:
                count = len(ops.modules_of_sheet(self.project, key))
                rows.append(Row(key, "Missing image", f"{count} module{'s' if count != 1 else ''} without an image", warn=True))
            else:
                asset = self.project.get_image(key)
                count = sum(1 for m in self.project.modules if m.type == "MD_IMAGE" and m.image_id == key)
                missing = ops.image_missing(asset)
                meta = "file not found" if missing else f"{asset.width}×{asset.height} · {count} module{'s' if count != 1 else ''}"
                rows.append(Row(key, ops.image_label(asset), meta, warn=missing))
        self.sheets.list.set_rows(rows, [self.sheet_key] if self.sheet_key else [])
        self.sheets.set_count(len(self.project.images), len(self.project.images))
        self.btn_remove_image.Enable(self.asset() is not None)

    def refresh_modules(self) -> None:
        counts = ops.part_counts(self.project)
        self._counts = counts
        mods = self.sheet_modules()
        query = self.modules.filter_text()
        view = [m for m in mods if not query or query in m.name.lower()]
        rows = []
        for m in view:
            uses = counts.get(m.id, 0)
            size = f"{m.rect[2]}×{m.rect[3]}"
            meta = f"{size} · {uses} use{'s' if uses != 1 else ''}" if uses else f"{size} · unused"
            rows.append(Row(m.id, m.name, meta, dim=not uses))
        self.selection = [i for i in self.selection if any(m.id == i for m in mods)]
        self.modules.list.set_rows(rows, self.selection)
        self.modules.set_count(len(view), len(mods))
        is_image = self.asset() is not None
        self.btn_slice.Enable(is_image and not ops.image_missing(self.asset()))
        self.btn_dup.Enable(bool(self.selection))
        self.btn_del.Enable(bool(self.selection))
        self.canvas.set_modules(mods, self.selection)
        self._refresh_inspector()

    def _refresh_inspector(self) -> None:
        self.inspector.show(self.project, self.sheet_key, self.selected_modules(), self.asset())

    def _sheet_thumbnail(self, key: str, size: int) -> Optional[wx.Bitmap]:
        if key.startswith("@"):
            return None
        asset = self.project.get_image(key)
        if asset is None:
            return None
        cache_key = (asset.file_path, tuple(asset.transparent_color or ()), size)
        bmp = self._sheet_thumbs.get(cache_key)
        if bmp is None:
            image = SHARED.sheet(self.project, asset, keyed=True)
            if image is None:
                return None
            bmp = fit_bitmap(image, size, size, TILE_BG, max_scale=4)
            self._sheet_thumbs[cache_key] = bmp
        return bmp

    def _module_thumbnail(self, module_id: str, size: int) -> Optional[wx.Bitmap]:
        mod = self.project.get_module(module_id)
        return THUMBNAILS.bitmap(self.project, mod, size, size) if mod else None

    # ================================================================== sheets
    def select_sheet(self, key: Optional[str], fit: bool = False) -> None:
        if self.sheet_key and self.sheet_key != key:
            self._view_states[self.sheet_key] = self.canvas.get_view_state()
        changed = key != self.sheet_key
        self.sheet_key = key
        if changed:
            self.selection = []
        self.sheets.list.set_selected([key] if key else [])
        self.btn_remove_image.Enable(self.asset() is not None)
        self.canvas.pick_mode = False
        self._load_sheet_image()
        self.refresh_modules()
        if key in self._view_states:
            pan, zoom = self._view_states[key]
            self.canvas.set_view_state(pan, zoom)
        elif changed or fit:
            self.canvas.fit_to_content()

    def _load_sheet_image(self) -> None:
        asset = self.asset()
        if asset is None:
            self.canvas.set_sheet(self.sheet_key, None, (0, 0))
            return
        image = SHARED.sheet(self.project, asset, keyed=not self.show_key_colour)
        if image is None:
            self.canvas.set_sheet(self.sheet_key, None, (asset.width, asset.height), missing_file=asset.file_path)
            return
        if (asset.width, asset.height) != image.size:
            asset.width, asset.height = image.size
        self.canvas.set_sheet(self.sheet_key, to_wx_image(image), image.size)

    def _add_menu(self) -> None:
        menu = wx.Menu()
        item_image = menu.Append(wx.ID_ANY, "Image…")
        item_folder = menu.Append(wx.ID_ANY, "Folder…")
        self.Bind(wx.EVT_MENU, lambda e: self.add_images(), item_image)
        self.Bind(wx.EVT_MENU, lambda e: self.add_folder(), item_folder)
        self.btn_add_image.PopupMenu(menu)
        menu.Destroy()

    def _import(self, path: str) -> Optional[ImageAsset]:
        from PIL import Image as PILImage

        try:
            with PILImage.open(path) as img:
                width, height = img.size
        except OSError:
            return None
        return self.project.create_image(path, width, height)

    def add_images(self) -> None:
        with wx.FileDialog(self, "Add Images", wildcard=IMAGE_WILDCARD, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            paths = dlg.GetPaths()
        added = [a for a in (self._import(p) for p in paths) if a is not None]
        failed = len(paths) - len(added)
        if not added:
            wx.MessageBox("The file could not be read as an image.", "Add Image", wx.OK | wx.ICON_WARNING, self)
            return
        self.refresh_sheets()
        self.select_sheet(added[-1].id, fit=True)
        app_services.request_checkpoint()
        app_services.show_status(f"Added {len(added)} image(s)" + (f"; {failed} could not be read" if failed else ""))

    def add_folder(self) -> None:
        with wx.DirDialog(self, "Add Folder", style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            folder = dlg.GetPath()
        with FolderImportDialog(self, folder, lambda recursive: len(ops.scan_image_files(folder, recursive))) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            recursive, full_modules = dlg.values()
        paths = ops.scan_image_files(folder, recursive)
        added: List[ImageAsset] = []
        with wx.BusyCursor():
            for path in paths:
                asset = self._import(path)
                if asset is None:
                    continue
                added.append(asset)
                if full_modules:
                    name = os.path.splitext(os.path.basename(path))[0]
                    ops.create_image_module(self.project, asset.id, (0, 0, asset.width, asset.height), name=name)
        if not added:
            wx.MessageBox("No image could be read from this folder.", "Add Folder", wx.OK | wx.ICON_WARNING, self)
            return
        self.refresh_sheets()
        self.select_sheet(added[-1].id, fit=True)
        app_services.request_checkpoint()
        skipped = len(paths) - len(added)
        app_services.show_status(
            f"Added {len(added)} image(s)" + (", one module each" if full_modules else "") + (f"; {skipped} skipped" if skipped else "")
        )

    def remove_image(self) -> None:
        asset = self.asset()
        if asset is None:
            return
        mods = ops.modules_of_sheet(self.project, asset.id)
        parts, frames, entries = ops.usage(self.project, [m.id for m in mods])
        objects = ops.scene_uses(self.project, [m.id for m in mods])
        message = f"Remove {ops.image_label(asset)} from the project?"
        if mods:
            message += f"\n\nIts {len(mods)} module(s) go with it."
        clean_up = False
        if parts or entries or objects:
            message += (f" They are used by {ops.describe_usage(parts, frames, entries, objects)}.\n\nRemove those "
                        "uses too, or keep them as missing, to swap for other modules later?"
                        "\n\n(Undo with Cmd/Ctrl+Z.)")
            answer = confirm.ask_remove_uses(self, "Remove Image", message, "Remove Uses Too")
            if answer is None:
                return
            clean_up = answer == confirm.REMOVE
        elif wx.MessageBox(message + "\n\n(Undo with Cmd/Ctrl+Z.)", "Remove Image", wx.YES_NO | wx.ICON_WARNING,
                           self) != wx.YES:
            return
        keys = self._sheet_keys()
        index = keys.index(asset.id)
        if clean_up:
            ops.remove_module_uses(self.project, [m.id for m in mods])
        ops.remove_image(self.project, asset.id)
        self._view_states.pop(asset.id, None)
        remaining = self._sheet_keys()
        self.refresh_sheets()
        self.select_sheet(remaining[min(index, len(remaining) - 1)] if remaining else None)
        app_services.request_checkpoint()
        app_services.show_status(f"Removed {ops.image_label(asset)}")

    def _move_image(self, image_id: str, before_id: Optional[str]) -> None:
        asset = self.project.get_image(image_id)
        if asset is None or image_id.startswith("@"):
            return
        self.project.images.remove(asset)
        anchor = self.project.get_image(before_id) if before_id else None
        index = self.project.images.index(anchor) if anchor else len(self.project.images)
        self.project.images.insert(index, asset)
        self.refresh_sheets()
        app_services.request_checkpoint()

    def locate_image(self) -> None:
        asset = self.asset()
        if asset is None:
            return
        with wx.FileDialog(self, f"Locate {ops.image_label(asset)}", wildcard=IMAGE_WILDCARD,
                           defaultFile=os.path.basename(asset.file_path), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        from PIL import Image as PILImage

        try:
            with PILImage.open(path) as img:
                size = img.size
        except OSError:
            wx.MessageBox("The file could not be read as an image.", "Locate Image", wx.OK | wx.ICON_WARNING, self)
            return
        asset.file_path = path
        asset.width, asset.height = size
        self.reload_image()
        app_services.request_checkpoint()
        app_services.show_status(f"{ops.image_label(asset)} now points to {path}")

    def reload_image(self) -> None:
        """Read the images again (after editing them elsewhere). The main window drops every cached picture in every
        tab, the budget overlay's too."""
        if app_services.notify_images_changed():
            return
        SHARED.clear()
        THUMBNAILS.clear()
        self._sheet_thumbs = {}
        self._load_sheet_image()
        self.refresh_sheets()
        self.refresh_modules()

    # ================================================================== key colour
    def begin_pick_key(self) -> None:
        if self.asset() is None:
            return
        self.canvas.pick_mode = True
        self.canvas.SetFocus()
        self.canvas.Refresh(False)
        app_services.show_status("Click a pixel of the image: its colour becomes transparent  •  Esc cancels")

    def _picked_key(self, x: int, y: int) -> None:
        asset = self.asset()
        self.canvas.pick_mode = False
        raw = SHARED.sheet(self.project, asset, keyed=False) if asset else None
        if raw is None or not (0 <= x < raw.width and 0 <= y < raw.height):
            self.canvas.Refresh(False)
            app_services.show_status("No pixel there; key colour unchanged")
            return
        r, g, b, _a = raw.getpixel((x, y))
        self._set_key((r, g, b))

    def _set_key(self, colour: Optional[Tuple[int, int, int]]) -> None:
        asset = self.asset()
        if asset is None:
            return
        asset.transparent_color = colour
        self._sheet_thumbs = {}
        self._load_sheet_image()
        self._commit()
        app_services.show_status(f"Key colour #{colour[0]:02X}{colour[1]:02X}{colour[2]:02X}" if colour else "No key colour")

    def _on_show_key_colour(self, shown: bool) -> None:
        self.show_key_colour = shown
        self._load_sheet_image()

    # ================================================================== view toggles
    def _on_snap(self, value: bool) -> None:
        self.canvas.snap = value

    def _on_names(self, value: bool) -> None:
        self.canvas.show_names = value
        self.canvas.Refresh(False)

    def _on_pivots(self, value: bool) -> None:
        self.canvas.show_pivots = value
        self.canvas.Refresh(False)

    # ================================================================== selection
    def select_modules(self, ids: List[str], reveal: bool = False) -> None:
        self.selection = [i for i in ids if self.project.get_module(i)]
        self.modules.list.set_selected(self.selection)
        self.canvas.set_modules(self.sheet_modules(), self.selection)
        self.btn_dup.Enable(bool(self.selection))
        self.btn_del.Enable(bool(self.selection))
        self._refresh_inspector()
        if reveal and self.selection:
            mod = self.project.get_module(self.selection[0])
            if mod:
                self.canvas.reveal(tuple(mod.rect))  # type: ignore[arg-type]

    def select_module(self, module_id: str) -> None:
        """Show a module from elsewhere (e.g. the Frames tab): its sheet, selected and in view."""
        mod = self.project.get_module(module_id)
        if mod is None:
            return
        key = ops.sheet_key(mod, self.project)
        if key != self.sheet_key:
            self.select_sheet(key)
        if self.modules.filter_text():
            self.modules.search.ChangeValue("")
            self.refresh_modules()
        self.select_modules([module_id], reveal=True)

    def _list_selection_changed(self) -> None:
        self.select_modules(self.modules.list.selected_ids(), reveal=True)

    def _canvas_selection(self, ids: List[str]) -> None:
        self.selection = list(ids)
        self.modules.list.set_selected(self.selection)
        self.btn_dup.Enable(bool(self.selection))
        self.btn_del.Enable(bool(self.selection))
        self._refresh_inspector()

    def _focus_name(self) -> None:
        if len(self.selection) == 1:
            self.inspector.name.SetFocus()
            self.inspector.name.SelectAll()

    def _live_changed(self) -> None:
        self._refresh_inspector()

    # ================================================================== create / edit
    def _create_from_canvas(self, rect: Tuple[int, int, int, int]) -> None:
        if self.sheet_key == ops.SHAPES_KEY:
            shape_type, colour = self.inspector.draw_shape()
            mod = ops.create_shape_module(self.project, shape_type, rect, colour)
        elif self.asset() is not None:
            mod = ops.create_image_module(self.project, self.sheet_key, rect, name=self._next_name())
        else:
            return
        self.selection = [mod.id]
        self._commit()
        app_services.show_status(f"New module '{mod.name}' {rect[2]}×{rect[3]}  •  Shift+drag sets the pivot")

    def _next_name(self) -> str:
        prefix = ops.sheet_prefix(self.asset())
        return ops.numbered_names(prefix, 1, {m.name for m in self.project.modules})[0]

    def _rename_module(self, module_id: str, name: str) -> None:
        mod = self.project.get_module(module_id)
        if mod and name != mod.name:
            mod.name = name
            self._commit()

    def _move_module(self, module_id: str, before_id: Optional[str]) -> None:
        mod = self.project.get_module(module_id)
        if mod is None:
            return
        self.project.modules.remove(mod)
        anchor = self.project.get_module(before_id) if before_id else None
        if anchor is not None:
            index = self.project.modules.index(anchor)
        else:
            sheet = self.sheet_modules()
            index = self.project.modules.index(sheet[-1]) + 1 if sheet else len(self.project.modules)
        self.project.modules.insert(index, mod)
        self._commit()

    def _on_field(self, field: str, value: Any) -> None:
        mods = self.selected_modules()
        if len(mods) != 1:
            return
        mod = mods[0]
        x, y, w, h = mod.rect
        if field == "name":
            name = str(value).strip()
            if not name or name == mod.name:
                return
            mod.name = name
        elif field in ("x", "y", "w", "h"):
            values = {"x": x, "y": y, "w": w, "h": h}
            values[field] = max(1, int(value)) if field in ("w", "h") else int(value)
            mod.rect = (values["x"], values["y"], values["w"], values["h"])
        elif field == "px":
            mod.pivot = (int(value), mod.pivot[1])
        elif field == "py":
            mod.pivot = (mod.pivot[0], int(value))
        elif field == "shape":
            if value == mod.type:
                return
            if len(ops.default_shape_params(value)) != len(ops.default_shape_params(mod.type)):
                mod.params = ops.default_shape_params(value)
            mod.type = value
        elif field == "color":
            mod.color = tuple(value)  # type: ignore[assignment]
        elif field == "params":
            mod.params = [float(v) for v in value]
        else:
            return
        self._commit()

    def _on_preset(self, fractions: Tuple[float, float]) -> None:
        mods = self.selected_modules()
        if not mods:
            return
        for mod in mods:
            ops.apply_pivot_preset(mod, fractions)
        self._commit()
        label = next(name for name, f in ops.PIVOT_PRESETS if f == fractions)
        app_services.show_status(f"Pivot: {label.lower()} on {len(mods)} module(s)")

    def _on_tool(self, name: str) -> None:
        handlers: Dict[str, Callable[[], None]] = {
            "locate": self.locate_image, "reload": self.reload_image,
            "pick_key": self.begin_pick_key, "clear_key": lambda: self._set_key(None),
            "grid": self.grid_slice, "detect": self.detect_sprites, "automod": self.auto_modularize,
            "optimize": lambda: self.show_optimization_dialog(),
            "trim": self.trim_modules, "duplicate": self.duplicate_modules, "delete": self.delete_modules,
            "new_frame": self.new_frame_from_module, "show_usage": self.show_usage,
        }
        handler = handlers.get(name)
        if handler:
            handler()

    def trim_modules(self) -> None:
        sheet = self._keyed_sheet()
        mods = [m for m in self.selected_modules() if m.type == "MD_IMAGE" and not getattr(m, "rotated", False)]
        if sheet is None or not mods:
            return
        trimmed = 0
        for mod in mods:
            box = ops.opaque_bbox(sheet, tuple(mod.rect))  # type: ignore[arg-type]
            if box and box != tuple(mod.rect):
                ops.resize_keeping_pivot(mod, box, ops.pivot_on_sheet(mod))
                trimmed += 1
        self._commit()
        app_services.show_status(f"Trimmed {trimmed} of {len(mods)} module(s) to their opaque pixels")

    def duplicate_modules(self) -> None:
        copies = ops.duplicate_modules(self.project, self.selection)
        if not copies:
            return
        self.selection = [m.id for m in copies]
        self._commit()
        app_services.show_status(f"Duplicated {len(copies)} module(s) in place; move them with the arrow keys")

    def delete_modules(self) -> None:
        mods = self.selected_modules()
        if not mods:
            return
        parts, frames, entries = ops.usage(self.project, [m.id for m in mods])
        objects = ops.scene_uses(self.project, [m.id for m in mods])
        clean_up = False
        if parts or entries or objects:
            what = f"'{mods[0].name}'" if len(mods) == 1 else f"{len(mods)} modules"
            message = (f"Delete {what}? {'It is' if len(mods) == 1 else 'They are'} used by "
                       f"{ops.describe_usage(parts, frames, entries, objects)}.\n\nRemove those uses too, or keep "
                       "them as missing, to swap for other modules later?\n\n(Undo with Cmd/Ctrl+Z.)")
            answer = confirm.ask_remove_uses(self, "Delete Modules", message, "Remove Uses Too")
            if answer is None:
                return
            clean_up = answer == confirm.REMOVE
        view = [m.id for m in self.sheet_modules()]
        first = view.index(mods[0].id) if mods[0].id in view else 0
        if clean_up:
            ops.remove_module_uses(self.project, self.selection)
        ops.delete_modules(self.project, self.selection)
        remaining = [m.id for m in self.sheet_modules()]
        self.selection = [remaining[min(first, len(remaining) - 1)]] if remaining else []
        self._commit()
        app_services.show_status(f"Deleted {len(mods)} module(s)")

    def nudge(self, dx: int, dy: int) -> None:
        if not self.selection:
            return
        ops.move_modules(self.project, self.selection, dx, dy)
        self.canvas.Refresh(False)
        self._refresh_inspector()
        app_services.request_checkpoint()

    def new_frame_from_module(self) -> None:
        mods = self.selected_modules()
        if len(mods) != 1:
            return
        mod = mods[0]
        used = {f.name for f in self.project.frames}
        frame = self.project.create_frame(ops.unique_name(mod.name, used))
        frame.fmodules.append(FModule(id=generate_id("fmod"), ref_type="module", ref_id=mod.id, position=(0, 0)))
        self._commit()
        app_services.show_status(f"New frame '{frame.name}' with {mod.name} on its origin")
        if self.on_open_frame:
            self.on_open_frame(frame.id)

    def show_usage(self) -> None:
        mods = self.selected_modules()
        frames = ops.frames_using(self.project, mods[0].id) if mods else []
        if frames and self.on_open_frame:
            self.on_open_frame(frames[0])

    # ================================================================== slicing
    def _existing_count(self) -> int:
        asset = self.asset()
        return len(ops.modules_of_sheet(self.project, asset.id)) if asset else 0

    def grid_slice(self) -> None:
        asset = self.asset()
        sheet = self._keyed_sheet()
        if asset is None or sheet is None:
            return

        def rects_for(values: Dict[str, int], skip_empty: bool) -> List[Tuple[int, int, int, int]]:
            rects = ops.grid_rects(sheet.width, sheet.height, values["tile_w"], values["tile_h"],
                                   values.get("offset_x", 0), values.get("offset_y", 0), values.get("gap_x", 0), values.get("gap_y", 0))
            if skip_empty:
                rects = [r for r in rects if ops.opaque_bbox(sheet, r) is not None]
            return rects

        def count(values: Dict[str, int], skip_empty: bool) -> Tuple[int, int]:
            total = len(rects_for(values, False))
            return total, (len(rects_for(values, True)) if skip_empty else total)

        with GridSliceDialog(self, self._grid_values, self._existing_count(), count) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            self._grid_values = dlg.values()
            replace = dlg.replace()
        rects = rects_for(self._grid_values, bool(self._grid_values.get("skip_empty", 1)))
        self._add_cut_modules(rects, replace, "Grid slice")

    def detect_sprites(self) -> None:
        asset = self.asset()
        sheet = self._keyed_sheet()
        if asset is None or sheet is None:
            return
        with wx.BusyCursor():
            regions = ops.detect_regions(sheet.getchannel("A").tobytes(), sheet.width, sheet.height)
        cache: Dict[int, List[Tuple[int, int, int, int]]] = {}

        def merged(gap: int) -> List[Tuple[int, int, int, int]]:
            if gap not in cache:
                cache[gap] = ops.merge_regions(regions, gap) if gap > 0 else regions
            return cache[gap]

        with DetectDialog(self, self._merge_gap, self._existing_count(), lambda gap: len(merged(gap))) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            self._merge_gap = dlg.merge_gap()
            replace = dlg.replace()
        self._add_cut_modules(merged(self._merge_gap), replace, "Detect sprites")

    def _add_cut_modules(self, rects: List[Tuple[int, int, int, int]], replace: bool, action: str) -> None:
        asset = self.asset()
        if asset is None:
            return
        if replace:
            parts, frames, entries = ops.usage(self.project, [m.id for m in ops.modules_of_sheet(self.project, asset.id)])
            if parts and wx.MessageBox(
                f"Replacing the modules breaks {ops.describe_usage(parts, frames, entries)}.\n\nContinue? (Undo with Cmd/Ctrl+Z.)",
                action, wx.YES_NO | wx.ICON_WARNING, self,
            ) != wx.YES:
                return
        created = ops.add_sheet_modules(self.project, asset.id, rects, replace=replace)
        self.selection = [m.id for m in created]
        self._commit()
        skipped = len(rects) - len(created)
        app_services.show_status(
            f"{action}: {len(created)} new module(s)" + (f", {skipped} skipped (already cut)" if skipped else "")
        )

    def auto_modularize(self) -> None:
        """Cut this image's sprites into shared hardware-sized parts (preview first), on a new image."""
        from ui.module_editor.modularize_dialog import ModularizeDialog

        asset = self.asset()
        if asset is None:
            app_services.show_status("Select an image to modularize.")
            return
        modules = [m for m in ops.modules_of_sheet(self.project, asset.id) if m.type == "MD_IMAGE"]
        if not modules:
            app_services.show_status("This image has no modules yet: slice it or detect its sprites first, then modularize.")
            return
        with ModularizeDialog(self, self.project, asset, modules) as dlg:
            if dlg.ShowModal() != wx.ID_OK or dlg.plan is None:
                return
            plan, sheet_path = dlg.plan, dlg.sheet_path()
        try:
            self.apply_modularize(asset, modules, plan, sheet_path)
        except OSError as exc:
            wx.MessageBox(f"Could not save {sheet_path}:\n{exc}", "Auto Modularize", wx.OK | wx.ICON_ERROR, self)

    def apply_modularize(self, asset: ImageAsset, modules: List[Module], plan: Any, sheet_path: str) -> Any:
        """Put a modularize plan into the project (one undo step) and show the new image."""
        import modularize

        with wx.BusyCursor():
            applied = modularize.apply_plan(self.project, asset.id, [m.id for m in modules], plan, sheet_path)
        SHARED.clear()
        self.refresh_sheets()
        self.select_sheet(applied.image_id, fit=True)
        app_services.request_checkpoint()
        text = (f"Modularized: {applied.parts} parts on {os.path.basename(applied.sheet_path)}, "
                f"{applied.rewritten_refs} frame parts rebuilt")
        if applied.new_frames:
            text += f", {applied.new_frames} new frames"
        if applied.kept_modules:
            text += f", {applied.kept_modules} sprites kept whole (freely rotated in a frame)"
        if applied.mapping_entries_removed:
            text += f", {applied.mapping_entries_removed} mapping entries removed"
        app_services.show_status(text + ".")
        return applied

    def show_optimization_dialog(self, output_dir: Optional[str] = None, name_hint: Optional[str] = None) -> None:
        """Repack modules into a new sheet (Tools ▸ Optimize Sprite Sheet)."""
        from optimization import optimize_modules
        from ui.optimize_dialog import OptimizeDialog

        if not self.project.modules:
            wx.MessageBox("There are no modules to optimize.", "Optimize Sprite Sheet", wx.OK | wx.ICON_INFORMATION, self)
            return
        with OptimizeDialog(self) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            config = dlg.GetValues()
        asset = self.asset()
        if config.get("scope", "local") == "local":
            if asset is None:
                wx.MessageBox("Select an image for a local optimization.", "Optimize Sprite Sheet", wx.OK | wx.ICON_INFORMATION, self)
                return
            scope = ops.modules_of_sheet(self.project, asset.id)
            hint = name_hint or f"{os.path.splitext(os.path.basename(asset.file_path))[0]}_optimized"
        else:
            scope = list(self.project.modules)
            hint = name_hint or (f"{self.project.name.replace(' ', '_')}_optimized" if self.project.name else "Global_Optimized")
        if not scope:
            wx.MessageBox("No modules in this scope.", "Optimize Sprite Sheet", wx.OK | wx.ICON_INFORMATION, self)
            return
        targets = scope
        if config.get("delete_unused", False):
            used = set(ops.part_counts(self.project)) | {t for mp in self.project.mappings for t in mp.map.values() if t}
            unused = [m for m in scope if m.id not in used]
            targets = [m for m in scope if m.id in used]
            if unused and wx.MessageBox(f"Delete the {len(unused)} unused module(s) of this scope?", "Optimize Sprite Sheet",
                                        wx.YES_NO | wx.ICON_WARNING, self) == wx.YES:
                ops.delete_modules(self.project, [m.id for m in unused])
            if not targets:
                wx.MessageBox("No used modules in this scope.", "Optimize Sprite Sheet", wx.OK | wx.ICON_INFORMATION, self)
                return
        with wx.BusyCursor():
            success, message = optimize_modules(self.project, [m.id for m in targets], config, output_dir, hint)
        if not success:
            wx.MessageBox(f"Optimization failed: {message}", "Optimize Sprite Sheet", wx.OK | wx.ICON_ERROR, self)
            return
        SHARED.clear()
        THUMBNAILS.clear()
        self.refresh_sheets()
        if self.project.images:
            self.select_sheet(self.project.images[-1].id, fit=True)
        app_services.request_checkpoint()
        wx.MessageBox(message, "Optimize Sprite Sheet", wx.OK | wx.ICON_INFORMATION, self)

    def _slice_menu(self) -> None:
        menu = wx.Menu()
        items = [("Grid slice…", self.grid_slice), ("Detect sprites…", self.detect_sprites), (None, None),
                 ("Auto modularize…", self.auto_modularize)]
        for label, handler in items:
            if label is None:
                menu.AppendSeparator()
                continue
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda e, h=handler: h(), item)
        self.btn_slice.PopupMenu(menu)
        menu.Destroy()

    def _module_menu(self, pos: Optional[wx.Point]) -> None:
        mods = self.selected_modules()
        menu = wx.Menu()

        def add(label: str, handler: Callable[[], None], enabled: bool = True, target: Optional[wx.Menu] = None) -> None:
            item = (target or menu).Append(wx.ID_ANY, label)
            item.Enable(enabled)
            self.Bind(wx.EVT_MENU, lambda e: handler(), item)

        if mods:
            add("Rename…" if len(mods) == 1 else "Rename", self._focus_name, len(mods) == 1)
            add("Duplicate\tCmd+D", self.duplicate_modules)
            add("Trim to Content", self.trim_modules, any(m.type == "MD_IMAGE" for m in mods))
            pivots = wx.Menu()
            for label, fractions in ops.PIVOT_PRESETS:
                add(label, lambda f=fractions: self._on_preset(f), True, pivots)
            menu.AppendSubMenu(pivots, "Pivot")
            menu.AppendSeparator()
            add("New Frame from Module", self.new_frame_from_module, len(mods) == 1)
            add("Show in Frames", self.show_usage, len(mods) == 1 and bool(ops.frames_using(self.project, mods[0].id)))
            menu.AppendSeparator()
            add("Delete", self.delete_modules)
        else:
            add("Select All\tCmd+A", self.edit_select_all, bool(self.sheet_modules()))
            add("Paste\tCmd+V", self.edit_paste, bool(_MODULE_CLIPBOARD))
        window = self.canvas if pos is not None else self.modules.list
        window.PopupMenu(menu, pos) if pos is not None else window.PopupMenu(menu)
        menu.Destroy()

    # ================================================================== edit menu
    def edit_copy(self) -> None:
        mods = self.selected_modules()
        if not mods:
            app_services.show_status("Nothing selected to copy")
            return
        _MODULE_CLIPBOARD[:] = [m.to_dict() for m in mods]
        app_services.show_status(f"Copied {len(mods)} module(s); paste them onto any image to cut the same areas")

    def edit_cut(self) -> None:
        if self.selected_modules():
            self.edit_copy()
            self.delete_modules()

    def edit_paste(self) -> None:
        if not _MODULE_CLIPBOARD or self.sheet_key is None or self.sheet_key == ops.ORPHANS_KEY:
            app_services.show_status("Clipboard is empty" if not _MODULE_CLIPBOARD else "Select an image to paste onto")
            return
        used = {m.name for m in self.project.modules}
        created: List[Module] = []
        for data in _MODULE_CLIPBOARD:
            data = dict(data)
            is_shape = data.get("type", "MD_IMAGE") != "MD_IMAGE"
            if is_shape != (self.sheet_key == ops.SHAPES_KEY):
                continue
            data["id"] = generate_id("mod")
            data["name"] = ops.unique_name(data.get("name", "Module"), used)
            if not is_shape:
                data["image_id"] = self.sheet_key
            mod = Module.from_dict(data)
            self.project.modules.append(mod)
            created.append(mod)
        if not created:
            app_services.show_status("Shapes paste onto Shapes, image modules onto an image")
            return
        self.selection = [m.id for m in created]
        self._commit()
        app_services.show_status(f"Pasted {len(created)} module(s)")

    def edit_duplicate(self) -> None:
        self.duplicate_modules()

    def edit_select_all(self) -> None:
        self.select_modules([m.id for m in self.sheet_modules()])

    # ================================================================== keyboard
    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if not self.IsShownOnScreen() or app_services.text_entry_has_focus() or self.modules.list.is_renaming():
            event.Skip()
            return
        key = event.GetKeyCode()
        focus = wx.Window.FindFocus()
        in_list = focus in (self.modules.list, self.sheets.list)
        if key == wx.WXK_ESCAPE:
            if self.canvas.pick_mode:
                self.canvas.pick_mode = False
                self.canvas.Refresh(False)
                app_services.show_status("Key colour unchanged")
            elif self.selection:
                self.select_modules([])
            return
        if event.CmdDown() or event.ControlDown() or event.AltDown():
            event.Skip()
            return
        if key in (wx.WXK_DELETE, wx.WXK_BACK):
            if focus is self.sheets.list:
                self.remove_image()
            else:
                self.delete_modules()
            return
        if key == wx.WXK_F2 and in_list:
            (self.sheets.list if focus is self.sheets.list else self.modules.list).begin_rename()
            return
        if key in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN) and not in_list:
            step = 8 if event.ShiftDown() else 1
            dx = {wx.WXK_LEFT: -step, wx.WXK_RIGHT: step}.get(key, 0)
            dy = {wx.WXK_UP: -step, wx.WXK_DOWN: step}.get(key, 0)
            self.nudge(dx, dy)
            return
        event.Skip()
