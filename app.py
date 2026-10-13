"""Main entry point for the modular sprite editor built with wxPython."""

from __future__ import annotations

import ctypes
import ctypes.util
import functools
import json
import os
import sys
from typing import Callable, List, Optional

import wx
import wx.lib.agw.flatnotebook as fnb

from models import FModule, Project, generate_id
from ui import app_services
from ui.animation_editor.panel import AnimationEditorPanel
from ui.frame_editor.panel import FrameEditorPanel
from ui.mapping_editor.panel import MappingEditorPanel
from ui.module_editor.panel import ModuleEditorPanel
from ui.project_history import ProjectHistory
from ui.shortcuts_dialog import ShortcutsDialog
from ui.scene_editor.panel import SceneEditorPanel

APP_NAME = "Modular Sprite Editor"
# The release this is: the About box shows it, and the Build And Release workflow stops if it releases another.
APP_VERSION = "0.7.1"
TAB_NAMES = ["Modules", "Frames", "Animations", "Timeline", "Mappings"]

# Shown in the status bar when a tab is activated.
TAB_HINTS = {
    "Modules": "Drag on the image: new module  •  Drag a module: move  •  Shift+drag: pivot  •  Cmd+drag: select several  •  Arrows: nudge",
    "Frames": "Drag parts from the library  •  Drag empty space: select several  •  Arrows: nudge (Shift = 8 px)  •  H/V: flip  •  R: rotate",
    "Animations": "Drag frames into the sequence  •  Enter: play  •  , / .: step  •  [ / ]: hold  •  Drag a step's right edge: hold  •  Drag the stage: offset",
    "Timeline": "Drag from the Library onto the stage  •  Enter: play  •  , / .: step  •  K: key  •  Auto-Key edits set keys at the playhead",
    "Mappings": "Select modules, then click a replacement on the right (or drag it onto a row)  •  Delete: original  •  H: hide",
}

CHECKPOINT_INTERVAL_MS = 700


def _mac_force_app_menu_title(title: str) -> None:
    """macOS-only: override the application menu title when running under Python."""
    if sys.platform != "darwin":
        return

    try:
        objc_path = ctypes.util.find_library("objc")
        if not objc_path:
            return

        objc = ctypes.cdll.LoadLibrary(objc_path)
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def cls(name: str) -> ctypes.c_void_p:
            return objc.objc_getClass(name.encode("utf-8"))

        def sel(name: str) -> ctypes.c_void_p:
            return objc.sel_registerName(name.encode("utf-8"))

        # Create small helpers with concrete signatures to avoid ctypes restype errors.
        msg = objc.objc_msgSend
        msg.restype = ctypes.c_void_p
        msg.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        msg_ccharp = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)(("objc_msgSend", objc))
        msg_long = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(("objc_msgSend", objc))
        msg_void = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))

        ns_app = msg(cls("NSApplication"), sel("sharedApplication"))
        if not ns_app:
            return

        main_menu = msg(ns_app, sel("mainMenu"))
        if not main_menu:
            return

        first_item = msg_long(main_menu, sel("itemAtIndex:"), 0)
        if not first_item:
            return

        ns_title = msg_ccharp(cls("NSString"), sel("stringWithUTF8String:"), title.encode("utf-8"))
        if not ns_title:
            return

        msg_void(first_item, sel("setTitle:"), ns_title)
    except Exception:
        # If anything goes wrong, leave the default title to avoid crashing the app.
        pass


def _focus_is_text_entry() -> Optional[wx.Window]:
    """Return the focused text-entry widget (so Edit commands can go to it), else None."""
    return wx.Window.FindFocus() if app_services.text_entry_has_focus() else None


class ContextBar(wx.Panel):
    """Slim bar above the editor tabs showing state that affects every tab."""

    def __init__(self, parent: wx.Window, on_mapping_selected: Callable[[Optional[str]], None]):
        super().__init__(parent)
        self._on_mapping_selected = on_mapping_selected
        self._mapping_ids: List[Optional[str]] = [None]

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddStretchSpacer(1)
        label = wx.StaticText(self, label="Preview mapping:")
        label.SetToolTip("Module mapping applied to every preview and used by exports. Edit mappings in the Mappings tab.")
        self.mapping_choice = wx.Choice(self, choices=["<none>"])
        self.mapping_choice.SetSelection(0)
        self.mapping_choice.SetMinSize((180, -1))
        sizer.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        sizer.Add(self.mapping_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        self.SetSizer(sizer)
        self.mapping_choice.Bind(wx.EVT_CHOICE, self._on_choice)

    def set_mappings(self, project: Project) -> None:
        self._mapping_ids = [None] + [m.id for m in project.mappings]
        self.mapping_choice.SetItems(["<none>"] + [m.name for m in project.mappings])
        active_id = project.active_mapping.id if project.active_mapping else None
        self.mapping_choice.SetSelection(self._mapping_ids.index(active_id) if active_id in self._mapping_ids else 0)

    def _on_choice(self, _event: wx.CommandEvent) -> None:
        idx = self.mapping_choice.GetSelection()
        if 0 <= idx < len(self._mapping_ids):
            self._on_mapping_selected(self._mapping_ids[idx])


class MainFrame(wx.Frame):
    def __init__(self, parent=None, title=APP_NAME):
        super().__init__(parent, title=title, size=(1500, 980))

        self.project = Project()
        self.current_path: Optional[str] = None
        self.history = ProjectHistory()
        self._last_dirty_state: Optional[bool] = None

        # Config and Recent Files (Custom MRU); tests use their own preferences file (see SpriteEditorApp.OnInit)
        self.config = wx.Config.Get() if os.environ.get("MSE_PREFERENCES_FILE") else wx.Config(APP_NAME)
        self.recent_files: list[str] = []
        self._load_recent_files()

        self._build_menu()

        # Icon setup
        if os.path.exists(resource_path('assets/icon.png')):
            self.SetIcon(wx.Icon(resource_path('assets/icon.png')))

        self.status_bar = self.CreateStatusBar(2)
        self.status_bar.SetStatusWidths([-1, 120])

        root = wx.Panel(self)
        self.context_bar = ContextBar(root, self.on_preview_mapping_selected)

        if sys.platform == "win32":
            # Windows: Use FlatNotebook (VC8 style) but DEFAULT colors
            style = fnb.FNB_VC8 | fnb.FNB_NO_X_BUTTON | fnb.FNB_NO_NAV_BUTTONS | fnb.FNB_NO_TAB_FOCUS | fnb.FNB_TABS_BORDER_SIMPLE
            self.book = fnb.FlatNotebook(root, style=style)
        else:
            self.book = wx.Notebook(root)

        self.module_editor = ModuleEditorPanel(self.book, self.project)
        self.frame_editor = FrameEditorPanel(self.book, self.project)
        self.animation_editor = AnimationEditorPanel(self.book, self.project)
        self.timeline_editor = SceneEditorPanel(self.book, self.project)
        self.mapping_editor = MappingEditorPanel(self.book, self.project)
        self.panels = [
            self.module_editor,
            self.frame_editor,
            self.animation_editor,
            self.timeline_editor,
            self.mapping_editor,
        ]

        pad = "  " if sys.platform == "win32" else ""
        for idx, (panel, name) in enumerate(zip(self.panels, TAB_NAMES)):
            self.book.AddPage(panel, f"{pad}{name}{pad}", select=(idx == 0))

        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(self.context_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        root_sizer.Add(self.book, 1, wx.EXPAND)
        root.SetSizer(root_sizer)

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(root, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        if sys.platform == "win32":
            self.book.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CHANGED, self.on_page_changed)
            self.book.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CLOSING, self.on_page_closing)
        else:
            self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_page_changed)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.animation_editor.on_edit_frame = self.switch_to_frame_editor
        self.module_editor.on_open_frame = self.switch_to_frame_editor
        self.frame_editor.on_open_module = self.switch_to_module
        self.mapping_editor.on_open_module = self.switch_to_module

        app_services.install(
            checkpoint=self.history_checkpoint,
            status=self.set_status,
            zoom=self.set_zoom_status,
            mapping_changed=self.sync_mapping_controls,
        )

        self.history.reset(self.project)
        self.context_bar.set_mappings(self.project)
        self._checkpoint_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_checkpoint_timer, self._checkpoint_timer)
        self._checkpoint_timer.Start(CHECKPOINT_INTERVAL_MS)
        self._update_title()
        self._show_tab_hint()

    # ------------------------------------------------------------------ status / title
    def set_status(self, message: str) -> None:
        self.status_bar.SetStatusText(message, 0)

    def set_zoom_status(self, zoom: float) -> None:
        # Fractional values only show while a smooth zoom gesture is running.
        text = f"{zoom:.0f}" if abs(zoom - round(zoom)) < 1e-6 else f"{zoom:.2f}".rstrip("0").rstrip(".")
        self.status_bar.SetStatusText(f"Zoom {text}×", 1)

    def _current_tab_name(self) -> str:
        idx = self.book.GetSelection()
        return TAB_NAMES[idx] if 0 <= idx < len(TAB_NAMES) else "Unknown"

    def _show_tab_hint(self) -> None:
        self.set_status(TAB_HINTS.get(self._current_tab_name(), ""))

    def _update_title(self) -> None:
        fname = os.path.basename(self.current_path) if self.current_path else "New Project"
        dirty = self.history.is_dirty()
        marker = "*" if dirty else ""
        self.SetTitle(f"{APP_NAME} - {fname}{marker} - [{self._current_tab_name()}]")
        if sys.platform == "darwin":
            # Native "edited" dot in the macOS close button.
            try:
                self.OSXSetModified(dirty)
            except AttributeError:
                pass
        self._last_dirty_state = dirty

    # ------------------------------------------------------------------ history
    def history_checkpoint(self) -> None:
        self.history.checkpoint(self.project)
        if self.history.is_dirty() != self._last_dirty_state:
            self._update_title()

    def _on_checkpoint_timer(self, _event: wx.TimerEvent) -> None:
        mouse = wx.GetMouseState()
        if mouse.LeftIsDown() or mouse.MiddleIsDown() or mouse.RightIsDown():
            return  # never split a drag into several undo steps
        self.history_checkpoint()

    def _after_history_restore(self) -> None:
        for panel in self.panels:
            panel.refresh_after_history()
        self.context_bar.set_mappings(self.project)
        self._update_title()

    def on_undo(self, _event: wx.CommandEvent) -> None:
        text = _focus_is_text_entry()
        if text is not None and hasattr(text, "CanUndo") and text.CanUndo():
            text.Undo()
            return
        if self.history.undo(self.project):
            self._after_history_restore()
            self.set_status("Undo")
        else:
            self.set_status("Nothing to undo")

    def on_redo(self, _event: wx.CommandEvent) -> None:
        text = _focus_is_text_entry()
        if text is not None and hasattr(text, "CanRedo") and text.CanRedo():
            text.Redo()
            return
        if self.history.redo(self.project):
            self._after_history_restore()
            self.set_status("Redo")
        else:
            self.set_status("Nothing to redo")

    def on_update_undo_ui(self, event: wx.UpdateUIEvent) -> None:
        event.Enable(self.history.can_undo() or self.history.is_dirty() or _focus_is_text_entry() is not None)

    def on_update_redo_ui(self, event: wx.UpdateUIEvent) -> None:
        event.Enable(self.history.can_redo() or _focus_is_text_entry() is not None)

    # ------------------------------------------------------------------ edit commands
    def _dispatch_edit(self, method_name: str, text_method: str) -> None:
        text = _focus_is_text_entry()
        if text is not None:
            handler = getattr(text, text_method, None)
            if handler:
                handler()
            return
        panel = self.book.GetCurrentPage()
        handler = getattr(panel, method_name, None)
        if handler:
            handler()
            self.history_checkpoint()

    def on_copy(self, _event: wx.CommandEvent) -> None:
        self._dispatch_edit("edit_copy", "Copy")

    def on_cut(self, _event: wx.CommandEvent) -> None:
        self._dispatch_edit("edit_cut", "Cut")

    def on_paste(self, _event: wx.CommandEvent) -> None:
        self._dispatch_edit("edit_paste", "Paste")

    def on_select_all(self, _event: wx.CommandEvent) -> None:
        self._dispatch_edit("edit_select_all", "SelectAll")

    def on_duplicate(self, _event: wx.CommandEvent) -> None:
        panel = self.book.GetCurrentPage()
        handler = getattr(panel, "edit_duplicate", None)
        if handler:
            handler()
            self.history_checkpoint()

    # ------------------------------------------------------------------ view commands
    def _active_canvas(self):
        panel = self.book.GetCurrentPage()
        getter = getattr(panel, "get_active_canvas", None)
        return getter() if getter else None

    def _view_command(self, action: Callable) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            action(canvas)

    # ------------------------------------------------------------------ mapping
    def on_preview_mapping_selected(self, mapping_id: Optional[str]) -> None:
        self.project.active_mapping = next((m for m in self.project.mappings if m.id == mapping_id), None)
        self.sync_mapping_controls()

    def sync_mapping_controls(self) -> None:
        self.context_bar.set_mappings(self.project)
        for panel in self.panels:
            handler = getattr(panel, "on_active_mapping_changed", None)
            if handler:
                handler()

    # ------------------------------------------------------------------ tabs
    def on_page_closing(self, event):
        """Prevent tabs from being closed."""
        event.Veto()

    def on_page_changed(self, event) -> None:
        page_idx = event.GetSelection()
        if page_idx == 0:
            self.module_editor.on_tab_activated()
        elif page_idx == 1:
            self.frame_editor.on_tab_activated()
        elif page_idx == 2:
            self.animation_editor.on_tab_activated()
        elif page_idx == 3:
            self.timeline_editor.on_tab_activated()
        elif page_idx == 4:
            self.mapping_editor.on_tab_activated()

        self._update_title()
        self._show_tab_hint()
        canvas = self._active_canvas()
        if canvas is not None:
            self.set_zoom_status(canvas.zoom)
            # Editor hotkeys should work right away instead of typing into a filter field.
            wx.CallAfter(canvas.SetFocus)
        else:
            self.status_bar.SetStatusText("", 1)
        event.Skip()

    def select_tab(self, index: int) -> None:
        if 0 <= index < self.book.GetPageCount():
            self.book.SetSelection(index)

    def switch_to_frame_editor(self, frame_id: str) -> None:
        """Navigates to the Frame Editor and selects the given frame."""
        self.book.SetSelection(1)
        self.frame_editor.select_frame_by_id(frame_id)

    def switch_to_module(self, module_id: str) -> None:
        """Navigates to the Modules tab and shows the given module on its image."""
        self.book.SetSelection(0)
        self.module_editor.select_module(module_id)

    # ------------------------------------------------------------------ recent files
    def _load_recent_files(self) -> None:
        s = self.config.Read("RecentFiles", "")
        if s:
            try:
                self.recent_files = json.loads(s)
            except (ValueError, TypeError):
                self.recent_files = []

    def _save_recent_files(self) -> None:
        self.config.Write("RecentFiles", json.dumps(self.recent_files))
        self.config.Flush()

    def add_file_to_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:10]
        self._save_recent_files()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        for item in self.menu_recent.GetMenuItems():
            self.menu_recent.Delete(item)

        if not self.recent_files:
            self.menu_recent.Append(wx.ID_ANY, "No Recent Files").Enable(False)
            return
        for idx, path in enumerate(self.recent_files):
            item = self.menu_recent.Append(wx.ID_ANY, f"{idx + 1}. {os.path.basename(path)}")
            item.SetHelp(path)
            self.Bind(wx.EVT_MENU, functools.partial(self.on_open_recent_file, path=path), item)
        self.menu_recent.AppendSeparator()
        item_clear = self.menu_recent.Append(wx.ID_ANY, "Clear Recent")
        self.Bind(wx.EVT_MENU, self.on_clear_recent, item_clear)

    def on_open_recent_file(self, event, path):
        if not self.confirm_discard_changes():
            return
        if os.path.exists(path):
            self.load_project(path)
        else:
            wx.MessageBox(f"File not found: {path}", "Error", wx.OK | wx.ICON_ERROR)
            if path in self.recent_files:
                self.recent_files.remove(path)
                self._save_recent_files()
                self._rebuild_recent_menu()

    def on_clear_recent(self, event):
        self.recent_files = []
        self._save_recent_files()
        self._rebuild_recent_menu()

    # ------------------------------------------------------------------ menus
    def _build_menu(self) -> None:
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        m_new = file_menu.Append(wx.ID_NEW, "&New Project\tCtrl+N", "Start an empty project")
        m_open = file_menu.Append(wx.ID_OPEN, "&Open...\tCtrl+O", "Open an existing project")
        self.menu_recent = wx.Menu()
        file_menu.AppendSubMenu(self.menu_recent, "Open Recent")
        self._rebuild_recent_menu()
        file_menu.AppendSeparator()
        m_save = file_menu.Append(wx.ID_SAVE, "&Save\tCtrl+S", "Save the current project")
        m_save_as = file_menu.Append(wx.ID_SAVEAS, "Save &As...\tCtrl+Shift+S", "Save with a new name")
        file_menu.AppendSeparator()

        import_menu = wx.Menu()
        m_import_aurora = import_menu.Append(wx.ID_ANY, "AuroraGT Sprite (*.sprite)...")
        m_import_retro = import_menu.Append(wx.ID_ANY, "RetroAnimator Project (*.json)...")
        file_menu.AppendSubMenu(import_menu, "Import")
        export_menu = wx.Menu()
        m_export_retro = export_menu.Append(wx.ID_ANY, "RetroAnimator Project (*.json)...")
        m_export_gif = export_menu.Append(wx.ID_ANY, "Selected Animation as GIF...")
        file_menu.AppendSubMenu(export_menu, "Export")
        file_menu.AppendSeparator()
        m_exit = file_menu.Append(wx.ID_EXIT, "&Quit\tCtrl+Q")

        self.Bind(wx.EVT_MENU, self.on_new, m_new)
        self.Bind(wx.EVT_MENU, self.on_open, m_open)
        self.Bind(wx.EVT_MENU, self.on_save, m_save)
        self.Bind(wx.EVT_MENU, self.on_save_as, m_save_as)
        self.Bind(wx.EVT_MENU, self.on_import_aurora, m_import_aurora)
        self.Bind(wx.EVT_MENU, self.on_import_retro_animator, m_import_retro)
        self.Bind(wx.EVT_MENU, self.on_export_retro_animator, m_export_retro)
        self.Bind(wx.EVT_MENU, self.on_export_gif, m_export_gif)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), m_exit)
        menubar.Append(file_menu, "&File")

        edit_menu = wx.Menu()
        m_undo = edit_menu.Append(wx.ID_UNDO, "&Undo\tCtrl+Z")
        m_redo = edit_menu.Append(wx.ID_REDO, "&Redo\tCtrl+Shift+Z")
        edit_menu.AppendSeparator()
        m_cut = edit_menu.Append(wx.ID_CUT, "Cu&t\tCtrl+X")
        m_copy = edit_menu.Append(wx.ID_COPY, "&Copy\tCtrl+C")
        m_paste = edit_menu.Append(wx.ID_PASTE, "&Paste\tCtrl+V")
        m_dup = edit_menu.Append(wx.ID_DUPLICATE, "&Duplicate\tCtrl+D")
        edit_menu.AppendSeparator()
        m_select_all = edit_menu.Append(wx.ID_SELECTALL, "Select &All\tCtrl+A")
        self.Bind(wx.EVT_MENU, self.on_undo, m_undo)
        self.Bind(wx.EVT_MENU, self.on_redo, m_redo)
        self.Bind(wx.EVT_MENU, self.on_cut, m_cut)
        self.Bind(wx.EVT_MENU, self.on_copy, m_copy)
        self.Bind(wx.EVT_MENU, self.on_paste, m_paste)
        self.Bind(wx.EVT_MENU, self.on_duplicate, m_dup)
        self.Bind(wx.EVT_MENU, self.on_select_all, m_select_all)
        self.Bind(wx.EVT_UPDATE_UI, self.on_update_undo_ui, m_undo)
        self.Bind(wx.EVT_UPDATE_UI, self.on_update_redo_ui, m_redo)
        menubar.Append(edit_menu, "&Edit")

        view_menu = wx.Menu()
        m_zoom_in = view_menu.Append(wx.ID_ZOOM_IN, "Zoom &In\tCtrl+=")
        m_zoom_out = view_menu.Append(wx.ID_ZOOM_OUT, "Zoom &Out\tCtrl+-")
        m_zoom_fit = view_menu.Append(wx.ID_ZOOM_FIT, "&Fit to Content\tCtrl+0")
        m_zoom_1x = view_menu.Append(wx.ID_ZOOM_100, "Actual &Pixels (1×)\tCtrl+Shift+0")
        view_menu.AppendSeparator()
        m_grid = view_menu.Append(wx.ID_ANY, "Toggle &Grid\tCtrl+G")
        view_menu.AppendSeparator()
        for idx, name in enumerate(TAB_NAMES):
            item = view_menu.Append(wx.ID_ANY, f"{name}\tCtrl+{idx + 1}")
            self.Bind(wx.EVT_MENU, functools.partial(lambda e, i: self.select_tab(i), i=idx), item)
        self.Bind(wx.EVT_MENU, lambda e: self._view_command(lambda c: c.zoom_step(1)), m_zoom_in)
        self.Bind(wx.EVT_MENU, lambda e: self._view_command(lambda c: c.zoom_step(-1)), m_zoom_out)
        self.Bind(wx.EVT_MENU, lambda e: self._view_command(lambda c: c.fit_to_content()), m_zoom_fit)
        self.Bind(wx.EVT_MENU, lambda e: self._view_command(lambda c: c.set_zoom_level(1.0)), m_zoom_1x)
        self.Bind(wx.EVT_MENU, self.on_toggle_grid, m_grid)
        menubar.Append(view_menu, "&View")

        tools_menu = wx.Menu()
        m_automod = tools_menu.Append(wx.ID_ANY, "Auto Modularize Image…", "Cut the selected image's sprites into shared hardware-sized parts")
        m_opt_sprite = tools_menu.Append(wx.ID_ANY, "Optimize Sprite Sheet...")
        m_opt_nested = tools_menu.Append(wx.ID_ANY, "Optimize Nested Frame Combos (All Frames)...")
        tools_menu.AppendSeparator()
        m_ref_frames = tools_menu.Append(wx.ID_ANY, "Create Reference Frames From All Image Modules...")
        tools_menu.AppendSeparator()
        m_validate_roles = tools_menu.Append(wx.ID_ANY, "Validate Roles (All Frames)")
        m_inspect_roles = tools_menu.Append(wx.ID_ANY, "Inspect Compiled Role Tables...")
        self.Bind(wx.EVT_MENU, self.on_tool_auto_modularize, m_automod)
        self.Bind(wx.EVT_MENU, self.on_tool_optimize, m_opt_sprite)
        self.Bind(wx.EVT_MENU, self.on_tool_optimize_nested, m_opt_nested)
        self.Bind(wx.EVT_MENU, self.on_tool_create_reference_frames, m_ref_frames)
        self.Bind(wx.EVT_MENU, lambda e: self.frame_editor.validate_roles(), m_validate_roles)
        self.Bind(wx.EVT_MENU, lambda e: self.frame_editor.inspect_compiled_role_tables(), m_inspect_roles)
        menubar.Append(tools_menu, "&Tools")

        help_menu = wx.Menu()
        m_shortcuts = help_menu.Append(wx.ID_ANY, "Keyboard && Mouse Shortcuts\tCtrl+/")
        m_about = help_menu.Append(wx.ID_ABOUT, f"About {APP_NAME}")
        self.Bind(wx.EVT_MENU, self.on_shortcuts, m_shortcuts)
        self.Bind(wx.EVT_MENU, self.on_about, m_about)
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)
        _mac_force_app_menu_title(APP_NAME)

    # ------------------------------------------------------------------ project lifecycle
    def confirm_discard_changes(self) -> bool:
        """Ask to save unsaved changes. Returns False if the user cancelled."""
        self.history_checkpoint()
        if not self.history.is_dirty():
            return True
        name = os.path.basename(self.current_path) if self.current_path else "this project"
        dlg = wx.MessageDialog(
            self,
            f"Do you want to save the changes you made to {name}?",
            "Unsaved Changes",
            wx.YES_NO | wx.CANCEL | wx.ICON_WARNING,
        )
        dlg.SetYesNoCancelLabels("Save", "Don't Save", "Cancel")
        result = dlg.ShowModal()
        dlg.Destroy()
        if result == wx.ID_CANCEL:
            return False
        if result == wx.ID_YES:
            return self.save_project()
        return True

    def _set_project(self, project: Project, path: Optional[str], saved: bool) -> None:
        self.project = project
        self.current_path = path
        self._reload_project_into_panels()
        self.history.reset(self.project, saved=saved)
        self.context_bar.set_mappings(self.project)
        self._update_title()
        if project.load_notes:
            wx.MessageBox("\n".join(project.load_notes), "Project Upgraded", wx.OK | wx.ICON_INFORMATION)
            self.set_status("Project format upgraded; save to keep the upgrade")

    def on_new(self, _: wx.CommandEvent) -> None:
        if not self.confirm_discard_changes():
            return
        self._set_project(Project(), None, saved=True)

    def load_project(self, path: str) -> None:
        """Helper to load a project and update the UI."""
        path = os.path.abspath(path)  # before the chdir below, which would move a relative path
        try:
            os.chdir(os.path.dirname(path))  # Set CWD to project folder
            project = Project.from_json(path)
        except Exception as e:
            wx.MessageBox(f"Failed to load project: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return
        self._set_project(project, path, saved=True)
        self.add_file_to_recent(path)
        self.set_status(f"Opened {path}")

    def on_open(self, _: wx.CommandEvent) -> None:
        if not self.confirm_discard_changes():
            return
        with wx.FileDialog(
            self,
            "Open project",
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        self.load_project(path)

    def save_project(self, path: Optional[str] = None) -> bool:
        target = path or self.current_path
        if not target:
            return self._save_as_dialog()
        try:
            self.project.to_json(target)
        except Exception as exc:
            wx.MessageBox(f"Failed to save project: {exc}", "Save Error", wx.OK | wx.ICON_ERROR)
            return False
        self.current_path = target
        self.history_checkpoint()
        self.history.mark_saved(self.project)
        self.add_file_to_recent(target)
        self._update_title()
        self.set_status(f"Saved {target}")
        return True

    def _save_as_dialog(self) -> bool:
        default_name = os.path.basename(self.current_path) if self.current_path else "project.json"
        with wx.FileDialog(
            self,
            "Save project",
            defaultFile=default_name,
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return False
            path = dlg.GetPath()
        if not path.lower().endswith(".json"):
            path += ".json"
        return self.save_project(path)

    def on_save(self, _: wx.CommandEvent) -> None:
        self.save_project()

    def on_save_as(self, _: wx.CommandEvent) -> None:
        self._save_as_dialog()

    def on_import_aurora(self, _: wx.CommandEvent) -> None:
        if not self.confirm_discard_changes():
            return
        with wx.FileDialog(
            self,
            "Import AuroraGT Sprite",
            wildcard="AuroraGT Sprite (*.sprite)|*.sprite",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        os.chdir(os.path.dirname(path))
        # Not saved yet: Save prompts for a location (conversion).
        self._set_project(Project.from_json(path), None, saved=False)
        self.set_status("Imported AuroraGT sprite. Save it as a new project.")

    def on_import_retro_animator(self, _: wx.CommandEvent) -> None:
        if not self.confirm_discard_changes():
            return
        with wx.FileDialog(
            self,
            "Import RetroAnimator Project",
            wildcard="RetroAnimator JSON (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        os.chdir(os.path.dirname(path))
        try:
            project = Project.from_retro_animator_json(path)
        except Exception as exc:
            wx.MessageBox(f"Failed to import: {exc}", "Import Error", wx.OK | wx.ICON_ERROR)
            return
        self._set_project(project, None, saved=False)
        self.set_status("Imported RetroAnimator project. Save it as a new project.")

    def on_export_retro_animator(self, _: wx.CommandEvent) -> None:
        if not self.project.frames:
            wx.MessageBox("No frames available to export.", "Export RetroAnimator", wx.OK | wx.ICON_WARNING)
            return

        default_name = (self.project.name or "sprite").strip().replace(" ", "_") or "sprite"
        with wx.FileDialog(
            self,
            "Export RetroAnimator Project",
            defaultFile=f"{default_name}.json",
            wildcard="JSON files (*.json)|*.json|All files (*.*)|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            # wxPython 4.2.5 macOS can assert on ShowModal when filter index is out of bounds.
            # Explicitly select first filter and provide a fallback wildcard entry.
            dlg.SetFilterIndex(0)
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()

        try:
            with wx.BusyCursor():
                report = self.project.to_retro_animator_json(path, mapping=self.project.active_mapping)
        except Exception as exc:
            wx.MessageBox(f"Failed to export RetroAnimator project: {exc}", "Export Error", wx.OK | wx.ICON_ERROR)
            return

        losses = report.get("losses", [])
        mapping_name = self.project.active_mapping.name if self.project.active_mapping else "<none>"
        summary = [
            f"Exported RetroAnimator project to:\n{report.get('path', path)}",
            "",
            f"Frames: {report.get('frames_exported', 0)}",
            f"Animations: {report.get('animations_exported', 0)}",
            f"Generated parts: {report.get('parts_written', 0)}",
            f"Parts folder: {report.get('parts_dir', '')}",
            f"Preview mapping baked: {mapping_name if report.get('mapping_baked') else 'No'}",
        ]
        if losses:
            summary.append("")
            summary.append("Important compatibility notes:")
            summary.extend([f"- {line}" for line in losses])
        wx.MessageBox("\n".join(summary), "Export Complete", wx.OK | wx.ICON_INFORMATION)

    def on_export_gif(self, event: wx.CommandEvent) -> None:
        self.select_tab(2)
        self.animation_editor.export_gif()

    def on_shortcuts(self, _: wx.CommandEvent) -> None:
        with ShortcutsDialog(self) as dlg:
            dlg.ShowModal()

    def on_about(self, _: wx.CommandEvent) -> None:
        wx.MessageBox(
            f"{APP_NAME}\nVersion {APP_VERSION}\n\nAssemble, animate and map modular pixel-art sprites for retro consoles.",
            f"About {APP_NAME}",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def on_toggle_grid(self, _: wx.CommandEvent) -> None:
        panel = self.book.GetCurrentPage()
        controls = getattr(panel, "canvas_controls", None)
        if controls is not None:
            controls.toggle_grid()

    def on_tool_auto_modularize(self, _: wx.CommandEvent) -> None:
        self.book.SetSelection(0)
        self.module_editor.auto_modularize()

    def on_tool_optimize(self, _: wx.CommandEvent) -> None:
        self.book.SetSelection(0)
        output_dir = os.path.dirname(self.current_path) if self.current_path else None
        self.module_editor.show_optimization_dialog(output_dir)
        self.history_checkpoint()

    def on_tool_optimize_nested(self, event: wx.CommandEvent) -> None:
        # Global frame-level optimization entry point.
        self.book.SetSelection(1)
        self.frame_editor.on_optimize_nested_combos(event)
        self.history_checkpoint()

    def on_tool_create_reference_frames(self, _: wx.CommandEvent) -> None:
        if not self.project.images:
            wx.MessageBox("No images in project.", "Info")
            return

        image_ids = {img.id for img in self.project.images}
        modules = [m for m in self.project.modules if m.image_id in image_ids]
        if not modules:
            wx.MessageBox("No image-backed modules found to create reference frames.", "Info")
            return

        used_frame_names = {f.name for f in self.project.frames}

        def unique_frame_name(base_name: str) -> str:
            root = (base_name or "Reference").strip() or "Reference"
            candidate = root
            suffix = 2
            while candidate in used_frame_names:
                candidate = f"{root} ({suffix})"
                suffix += 1
            used_frame_names.add(candidate)
            return candidate

        created = 0
        last_frame_id: Optional[str] = None
        for mod in modules:
            img = self.project.get_image(mod.image_id)
            image_base = os.path.splitext(os.path.basename(img.file_path))[0] if img else "Image"
            frame = self.project.create_frame(unique_frame_name(f"Ref {image_base} - {mod.name}"))
            frame.fmodules.append(
                FModule(
                    id=generate_id("fmod"),
                    ref_type="module",
                    ref_id=mod.id,
                    position=(int(mod.pivot[0]), int(mod.pivot[1])),
                )
            )
            created += 1
            last_frame_id = frame.id

        self.frame_editor.refresh_choices()
        if last_frame_id:
            self.frame_editor.select_frame_by_id(last_frame_id)
        self.animation_editor.refresh_library()
        self.history_checkpoint()
        self.set_status(f"Created {created} reference frame(s).")

    def on_close(self, event: wx.CloseEvent) -> None:
        if event.CanVeto() and not self.confirm_discard_changes():
            event.Veto()
            return
        self._checkpoint_timer.Stop()
        for panel in self.panels:
            stop = getattr(panel, "stop_playback", None)
            if stop:
                stop()
        self._save_recent_files()
        app_services.install()
        event.Skip()

    def _reload_project_into_panels(self) -> None:
        for panel in self.panels:
            panel.set_project(self.project)
        self._update_title()


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


class SpriteEditorApp(wx.App):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Set names on the app instance so macOS uses them for the application menu.
        self.SetAppName(APP_NAME)
        self.SetAppDisplayName(APP_NAME)
        self.SetVendorName(APP_NAME)
        self.SetVendorDisplayName(APP_NAME)

    def OnInit(self) -> bool:  # type: ignore[N802]
        prefs = os.environ.get("MSE_PREFERENCES_FILE")
        if prefs:  # tests keep their preferences in a file of their own
            wx.Config.Set(wx.FileConfig(localFilename=prefs, style=wx.CONFIG_USE_LOCAL_FILE))
        frame = MainFrame()

        # Set Icon (Windows needs explicit setting for Taskbar/Window)
        if sys.platform == "win32":
            try:
                icon_path = resource_path(os.path.join("assets", "icon.ico"))
                if os.path.exists(icon_path):
                    frame.SetIcon(wx.Icon(icon_path, wx.BITMAP_TYPE_ICO))
            except Exception as e:
                print(f"Failed to load icon: {e}")

        frame.Show()
        self.SetTopWindow(frame)

        # Optional: open a project passed on the command line.
        paths = [arg for arg in sys.argv[1:] if arg.lower().endswith(".json") and os.path.exists(arg)]
        if paths:
            wx.CallAfter(frame.load_project, os.path.abspath(paths[0]))
        return True


def main() -> None:
    # redirect=False is CRITICAL to see console output if things go wrong
    app = SpriteEditorApp(False)
    app.MainLoop()


def run_smoke_test(args: List[str]) -> None:
    """`--smoke-test PROJECT.json [LOG]`: drive every tab against the project (tools/gui_smoke.py) and exit with
    0 (pass) or 1, so the built executables can be tested. A windowed exe has no console: LOG gets the output."""
    import atexit
    import shutil
    import tempfile

    if len(args) > 1:
        sys.stdout = sys.stderr = open(args[1], "w", encoding="utf-8", buffering=1)
    # Preferences go to a throwaway file: the test must not change the user's settings.
    prefs_dir = tempfile.mkdtemp(prefix="mse_smoke_")
    atexit.register(shutil.rmtree, prefs_dir, True)
    os.environ["MSE_PREFERENCES_FILE"] = os.path.join(prefs_dir, "preferences.ini")
    sys.argv = [sys.argv[0]] + args[:1]
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    import gui_smoke  # noqa: F401  (runs the test and exits)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--smoke-test"]:
        run_smoke_test(sys.argv[2:])
    else:
        main()
