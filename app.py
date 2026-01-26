"""Main entry point for the modular sprite editor built with wxPython."""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
import os
from typing import Optional

import wx

from models import Project
from ui.animation_editor import AnimationEditorPanel
from ui.frame_editor import FrameEditorPanel
from ui.module_editor import ModuleEditorPanel
from ui.mapping_editor import MappingEditorPanel
import wx.lib.agw.flatnotebook as fnb

APP_NAME = "Modular Sprite Editor"

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


import json
import functools

# ... imports ...

class MainFrame(wx.Frame):
    def __init__(self, parent=None, title="Modular Sprite Editor"):
        super(MainFrame, self).__init__(parent, title=title, size=(1200, 800))
        
        self.project = Project()
        self.current_path = None
        
        # Config and Recent Files (Custom MRU)
        self.config = wx.Config(APP_NAME)
        self.recent_files: list[str] = []
        self._load_recent_files()

        self._build_menu()
        
        # Icon setup
        if os.path.exists(resource_path('assets/icon.png')):
             icon = wx.Icon(resource_path('assets/icon.png'))
             self.SetIcon(icon)
        self.toolbar = self.CreateToolBar(style=wx.TB_HORIZONTAL | wx.TB_TEXT)
        self._add_toolbar_tools()
        self.toolbar.Realize()

        if sys.platform == "win32":
            # Windows: Use FlatNotebook (VC8 style) but DEFAULT colors
            style = fnb.FNB_VC8 | fnb.FNB_NO_X_BUTTON | fnb.FNB_NO_NAV_BUTTONS | fnb.FNB_NO_TAB_FOCUS | fnb.FNB_TABS_BORDER_SIMPLE
            self.book = fnb.FlatNotebook(self, style=style)
        else:
            self.book = wx.Notebook(self)
        
        self.module_editor = ModuleEditorPanel(self.book, self.project)
        self.frame_editor = FrameEditorPanel(self.book, self.project)
        self.animation_editor = AnimationEditorPanel(self.book, self.project)
        self.mapping_editor = MappingEditorPanel(self.book, self.project)
        
        if sys.platform == "win32": 
            pad = "  "
        else:
            pad = ""
            
        self.book.AddPage(self.module_editor, f"{pad}Modules{pad}", select=True)
        self.book.AddPage(self.frame_editor, f"{pad}Frames{pad}", select=False)
        self.book.AddPage(self.animation_editor, f"{pad}Animations{pad}", select=False)
        self.book.AddPage(self.mapping_editor, f"{pad}Mappings{pad}", select=False)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.book, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.toolbar.Bind(wx.EVT_TOOL, self.on_switch_tool)
        
        if sys.platform == "win32":
            self.book.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CHANGED, self.on_page_changed)
            self.book.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CLOSING, self.on_page_closing)
        else:
            self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_page_changed)
            
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        
        self.animation_editor.timeline.on_edit_frame = self.switch_to_frame_editor

    def on_page_closing(self, event):
        """Prevent tabs from being closed."""
        event.Veto()

    def on_page_changed(self, event) -> None:
        page_idx = event.GetSelection()
        if page_idx == 0:
            mode_name = "Modules"
        elif page_idx == 1:
            self.frame_editor.refresh_choices()
            self.frame_editor.refresh_frames(self.frame_editor.selected_frame_id)
            mode_name = "Frames"
        elif page_idx == 2:
            self.animation_editor.refresh_choices()
            self.animation_editor.refresh_animations(self.animation_editor.selected_animation_id)
            mode_name = "Animations"
        elif page_idx == 3:
            self.mapping_editor.refresh_list()
            self.mapping_editor.visualizer.update_virtual_size()
            mode_name = "Mappings"
        else:
            mode_name = "Unknown"

        self._update_title()
        event.Skip()

    def update_status(self, message):
        pass
        
    def _update_title(self) -> None:
        fname = "New Project"
        if self.current_path:
            fname = os.path.basename(self.current_path)
        
        page_idx = self.book.GetSelection()
        mode_name = "Unknown"
        if page_idx == 0: mode_name = "Modules"
        elif page_idx == 1: mode_name = "Frames"
        elif page_idx == 2: mode_name = "Animations"
        elif page_idx == 3: mode_name = "Mappings"
            
        self.SetTitle(f"{APP_NAME} - {fname} - [{mode_name}]")
        
    def on_size(self, event: wx.SizeEvent) -> None:
        self.Layout()
        self.Refresh()
        event.Skip()

    def switch_to_frame_editor(self, frame_id: str) -> None:
        """Navigates to the Frame Editor and selects the given frame."""
        self.book.SetSelection(1) # Index 1 is Frame Editor
        self.frame_editor.selected_frame_id = frame_id
        self.frame_editor.refresh_frames(select_id=frame_id)
        # Force canvas update
        frame = self.project.get_frame(frame_id)
        if frame:
            self.frame_editor.canvas.set_frame(frame)

    def _load_recent_files(self) -> None:
        """Load recent files from config."""
        s = self.config.Read("RecentFiles", "")
        if s:
            try:
                self.recent_files = json.loads(s)
            except:
                self.recent_files = [] 
                
    def _save_recent_files(self) -> None:
        """Save recent files to config."""
        s = json.dumps(self.recent_files)
        self.config.Write("RecentFiles", s)
        self.config.Flush()

    def add_file_to_recent(self, path: str) -> None:
        """Add a file to the recent list and update menu."""
        # Normalize path
        path = os.path.abspath(path)
        
        # Remove if exists (to move to top)
        if path in self.recent_files:
            self.recent_files.remove(path)
            
        self.recent_files.insert(0, path)
        
        # Keep max 10
        if len(self.recent_files) > 10:
            self.recent_files = self.recent_files[:10]
            
        self._save_recent_files()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        """Rebuild the Open Recent submenu."""
        # Clear existing items
        for item in self.menu_recent.GetMenuItems():
            self.menu_recent.Delete(item)
            
        if not self.recent_files:
            self.menu_recent.Append(wx.ID_ANY, "No Recent Files").Enable(False)
        else:
             for idx, path in enumerate(self.recent_files):
                 # Show only filename
                 label = f"{idx+1}. {os.path.basename(path)}"
                 item = self.menu_recent.Append(wx.ID_ANY, label)
                 # Tooltip / Status hint with full path? 
                 item.SetHelp(path)
                 
                 # Bind using partial to capture path
                 self.Bind(wx.EVT_MENU, functools.partial(self.on_open_recent_file, path=path), item)
                 
             self.menu_recent.AppendSeparator()
             item_clear = self.menu_recent.Append(wx.ID_ANY, "Clear Recent")
             self.Bind(wx.EVT_MENU, self.on_clear_recent, item_clear)

    def on_open_recent_file(self, event, path):
        # Triggered by closure
        if os.path.exists(path):
            self.load_project(path)
        else:
            wx.MessageBox(f"File not found: {path}", "Error", wx.OK | wx.ICON_ERROR)
            # Remove directly if not found?
            if path in self.recent_files:
                self.recent_files.remove(path)
                self._save_recent_files()
                self._rebuild_recent_menu()

    def on_clear_recent(self, event):
        self.recent_files = []
        self._save_recent_files()
        self._rebuild_recent_menu()

    # UI construction
    def _build_menu(self) -> None:
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        
        self.m_open = file_menu.Append(wx.ID_OPEN, "\u0026Open...\tCtrl+O", "Open an existing project")
        self.m_save = file_menu.Append(wx.ID_SAVE, "\u0026Save\tCtrl+S", "Save the current project")
        self.m_save_as = file_menu.Append(wx.ID_ANY, "Save \u0026As...\tCtrl+Shift+S", "Save with a new name")
        
        # Open Recent Submenu (Custom)
        file_menu.AppendSeparator()
        self.menu_recent = wx.Menu()
        file_menu.AppendSubMenu(self.menu_recent, "Open Recent")
        self._rebuild_recent_menu()
        file_menu.AppendSeparator()
        
        file_menu.Bind(wx.EVT_MENU, self.on_save_as, self.m_save_as)
        file_menu.Bind(wx.EVT_MENU, self.on_open, self.m_open)
        file_menu.Bind(wx.EVT_MENU, self.on_save, self.m_save)
        
        # Import Submenu
        import_menu = wx.Menu()
        self.m_import_aurora = import_menu.Append(wx.ID_ANY, "AuroraGT Sprite (*.sprite)...")
        file_menu.AppendSubMenu(import_menu, "Import")
        
        
        self.Bind(wx.EVT_MENU, self.on_import_aurora, self.m_import_aurora)
        
        menubar.Append(file_menu, "&File")

        # Tools Menu
        tools_menu = wx.Menu()
        self.m_opt_sprite = tools_menu.Append(wx.ID_ANY, "Optimize Sprite Sheet...")
        menubar.Append(tools_menu, "&Tools")
        
        self.Bind(wx.EVT_MENU, self.on_tool_optimize, self.m_opt_sprite)

        self.SetMenuBar(menubar)
        _mac_force_app_menu_title(APP_NAME)

    def _add_toolbar_tools(self) -> None:
        size = (24, 24)
        pass # No extra tools for now, can add Open/Save here later

    # Menu handlers
    def on_new(self, _: wx.CommandEvent) -> None:
        self.project = Project()
        self.current_path = None
        self._reload_project_into_panels()

    def load_project(self, path: str) -> None:
        """Helper to load a project and update the UI."""
        try:
            os.chdir(os.path.dirname(path)) # Set CWD to project folder
            self.project = Project.from_json(path)
            self.current_path = path
            self._reload_project_into_panels()
            self.add_file_to_recent(path)
        except Exception as e:
            wx.MessageBox(f"Failed to load project: {e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_open(self, _: wx.CommandEvent) -> None:
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

    # Note: on_file_history REMOVED as redundant

    def on_save(self, _: wx.CommandEvent) -> None:
        if not self.current_path:
            self.on_save_as(wx.CommandEvent())
            return
        self.project.to_json(self.current_path)
        self.add_file_to_recent(self.current_path)
        self._update_title()
        wx.MessageBox(f"Saved to {self.current_path}", "Saved")

    def on_save_as(self, _: wx.CommandEvent) -> None:
        print("DEBUG: Save As triggered")
        try:
            with wx.FileDialog(
                self,
                "Save project",
                wildcard="JSON files (*.json)|*.json",
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            ) as dlg:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                path = dlg.GetPath()
                if not path.lower().endswith(".json"):
                    path += ".json"
                self.project.to_json(path)
                self.current_path = path
                self.add_file_to_recent(path)
                self._update_title()
                wx.MessageBox(f"Saved to {path}", "Saved")
        except Exception as exc:
            wx.LogError(f"Save As failed: {exc}")

    def on_import_aurora(self, _: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self,
            "Import AuroraGT Sprite",
            wildcard="AuroraGT Sprite (*.sprite)|*.sprite",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
            os.chdir(os.path.dirname(path)) # Set CWD to imported file folder
            # Project.from_json handles parsing based on extension
            self.project = Project.from_json(path)
            # Do NOT set current_path, so Save prompts for a new location (conversion)
            self.current_path = None 
            self._reload_project_into_panels()
            self._update_title()
            wx.MessageBox("Imported successfully. Please save as a new project.", "Import Complete", wx.OK | wx.ICON_INFORMATION)

    def on_about(self, _: wx.CommandEvent) -> None:
        wx.MessageBox(
            "Modular Sprite Editor\\nA simple modular sprite editing tool built with wxPython.",
            f"About {APP_NAME}",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def on_preferences(self, _: wx.CommandEvent) -> None:
        wx.MessageBox("Preferences are not implemented yet.", "Preferences", wx.OK, self)

    def _on_menu_debug(self, event: wx.CommandEvent) -> None:
        print(f"MENU DEBUG: id={event.GetId()} source={event.GetEventObject()}")
        event.Skip()
    
    def on_tool_optimize(self, _: wx.CommandEvent) -> None:
        # Delegate to module editor
        # We might need to ensure the Module tab is selected? 
        # Or just let the dialog appear.
        # The user's request said "simple menu option... opens a dialog".
        # It doesn't strictly require switching tabs, but contextual actions usually imply focus.
        # Let's switch to Module Editor tab for clarity if not active.
        self.book.SetSelection(0)
        self.module_editor.show_optimization_dialog()

    def on_close(self, event: wx.CloseEvent) -> None:
        self._save_recent_files()
        event.Skip()

    # Toolbar switching
    def on_switch_tool(self, event: wx.CommandEvent) -> None:
        tool_id = event.GetId()
        # Handle File Tools from Toolbar
        if tool_id == wx.ID_OPEN:
            self.on_open(event)
            return
        elif tool_id == wx.ID_SAVE:
            self.on_save(event)
            return

    # Helpers
    def _reload_project_into_panels(self) -> None:
        self.module_editor.set_project(self.project)
        self.frame_editor.set_project(self.project)
        self.animation_editor.set_project(self.project)
        self.mapping_editor.set_project(self.project)
        self._update_title()

    def switch_to_frame_editor(self, frame_id: str) -> None:
        """Navigates to the Frame Editor and selects the given frame."""
        self.book.SetSelection(1) # Index 1 is Frame Editor
        self.frame_editor.selected_frame_id = frame_id
        self.frame_editor.refresh_frames(select_id=frame_id)
        # Force canvas update
        frame = self.project.get_frame(frame_id)
        if frame:
            self.frame_editor.canvas.set_frame(frame)


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
        frame = MainFrame()
        
        # Set Icon (Windows needs explicit setting for Taskbar/Window)
        if sys.platform == "win32":
            try:
                icon_path = resource_path(os.path.join("assets", "icon.ico"))
                if os.path.exists(icon_path):
                    icon = wx.Icon(icon_path, wx.BITMAP_TYPE_ICO)
                    frame.SetIcon(icon)
            except Exception as e:
                print(f"Failed to load icon: {e}")
        
        frame.Show()
        self.SetTopWindow(frame)
        return True

def main() -> None:
    # redirect=False is CRITICAL to see console output if things go wrong
    app = SpriteEditorApp(False)
    app.MainLoop()


if __name__ == "__main__":
    main()
