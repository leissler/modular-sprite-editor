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

APP_NAME = "RetroSpine"

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


class MainFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title=APP_NAME, size=(1200, 800))
        self.project: Project = Project()
        self.current_path: Optional[str] = None

        self._build_menu()
        self.toolbar = self.CreateToolBar(style=wx.TB_HORIZONTAL | wx.TB_TEXT)
        self._add_toolbar_tools()
        self.toolbar.Realize()

        self.status_bar = self.CreateStatusBar()
        self.status_bar.SetStatusText("Ready")

        if sys.platform == "win32":
            # Windows: Use FlatNotebook (VC8 style) but DEFAULT colors
            # Style: VC8 (Angled), No X button, No Nav buttons, No Dropdown
            # Removing SMART_TABS as it might override VC8 look or cause extra icons.
            # Adding NO_TAB_FOCUS just in case. FNB_TABS_BORDER_SIMPLE for clean look.
            style = fnb.FNB_VC8 | fnb.FNB_NO_X_BUTTON | fnb.FNB_NO_NAV_BUTTONS | fnb.FNB_NO_TAB_FOCUS | fnb.FNB_TABS_BORDER_SIMPLE
            self.book = fnb.FlatNotebook(self, style=style)
            
            
        else:
            # Mac / Others: Standard Native Notebook
            self.book = wx.Notebook(self)
        
        self.module_editor = ModuleEditorPanel(self.book, self.project)
        self.frame_editor = FrameEditorPanel(self.book, self.project)
        self.animation_editor = AnimationEditorPanel(self.book, self.project)
        self.mapping_editor = MappingEditorPanel(self.book, self.project)
        
        # Add Pages (API is compatible)
        # We keep the spaces for Windows readability (FlatNotebook), 
        # but on Mac native control spaces might look weird? 
        # User said "Mac I want the default look", usually means native labels too.
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
            # Prevent closing tabs
            self.book.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CLOSING, self.on_page_closing)
        else:
            self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_page_changed)
            
        self.Bind(wx.EVT_SIZE, self.on_size)
        
        # Initial Title/Status
        self.status_bar.SetStatusText("Active Mode: Modules")
        
        # Wire Cross-Panel Events
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
        self.status_bar.SetStatusText(f"Active Mode: {mode_name}")
        
    def on_size(self, event: wx.SizeEvent) -> None:
        self.Layout()
        self.Refresh()
        event.Skip()

    # UI construction
    def _build_menu(self) -> None:
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        
        # Standard items, simplified accelerators to avoid parsing issues
        self.m_open = file_menu.Append(wx.ID_OPEN, "\u0026Open...\tCtrl+O", "Open an existing project")
        self.m_save = file_menu.Append(wx.ID_SAVE, "\u0026Save\tCtrl+S", "Save the current project")
        self.m_save_as = file_menu.Append(wx.ID_ANY, "Save \u0026As...\tCtrl+Shift+S", "Save with a new name")
        #file_menu.AppendSeparator()
        
        file_menu.Bind(wx.EVT_MENU, self.on_save_as, self.m_save_as)
        file_menu.Bind(wx.EVT_MENU, self.on_open, self.m_open)
        file_menu.Bind(wx.EVT_MENU, self.on_save, self.m_save)
        
        # Import Submenu
        import_menu = wx.Menu()
        self.m_import_aurora = import_menu.Append(wx.ID_ANY, "AuroraGT Sprite (*.sprite)...")
        file_menu.AppendSubMenu(import_menu, "Import")
        
        self.Bind(wx.EVT_MENU, self.on_import_aurora, self.m_import_aurora)
        
        menubar.Append(file_menu, "&File")

        self.SetMenuBar(menubar)

        # Explicit accelerator table for reliability (Cmd on macOS, Ctrl elsewhere)
        """
        accel = wx.AcceleratorTable(
            [
                (wx.ACCEL_CMD, ord("N"), wx.ID_NEW),
                (wx.ACCEL_CMD, ord("O"), wx.ID_OPEN),
                (wx.ACCEL_CMD, ord("S"), wx.ID_SAVE),
                (wx.ACCEL_CMD | wx.ACCEL_SHIFT, ord("S"), ID_SAVE_AS),
                #(wx.ACCEL_CMD, ord("Q"), ID_QUIT_APP),
            ]
        )
        self.SetAcceleratorTable(accel)
        """

        _mac_force_app_menu_title(APP_NAME)



    def _add_toolbar_tools(self) -> None:
        size = (24, 24)
        pass # No extra tools for now, can add Open/Save here later



    # Menu handlers
    def on_new(self, _: wx.CommandEvent) -> None:
        self.project = Project()
        self.current_path = None
        self._reload_project_into_panels()

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
            os.chdir(os.path.dirname(path)) # Set CWD to project folder
            self.project = Project.from_json(path)
            self.current_path = path
            self._reload_project_into_panels()

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
            self.current_path = None 
            self._reload_project_into_panels()
            self._update_title()
            wx.MessageBox("Imported successfully. Please save as a new project.", "Import Complete", wx.OK | wx.ICON_INFORMATION)

    def on_save(self, _: wx.CommandEvent) -> None:
        if not self.current_path:
            self.on_save_as(wx.CommandEvent())
            return
        self.project.to_json(self.current_path)
        self.project.to_json(self.current_path)
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
                self.project.to_json(path)
                self.current_path = path
                self._update_title()
                wx.MessageBox(f"Saved to {path}", "Saved")
        except Exception as exc:
            wx.LogError(f"Save As failed: {exc}")


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

    def on_close(self, event: wx.CloseEvent) -> None:
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
