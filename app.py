"""Main entry point for the modular sprite editor built with wxPython."""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Optional

import wx

from models import Project
from ui.animation_editor import AnimationEditorPanel
from ui.frame_editor import FrameEditorPanel
from ui.module_editor import ModuleEditorPanel

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


class MainFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title=APP_NAME, size=(1200, 800))
        self.project: Project = Project()
        self.current_path: Optional[str] = None

        self._build_menu()
        self.toolbar = self.CreateToolBar(style=wx.TB_HORIZONTAL | wx.TB_TEXT)
        self._add_toolbar_tools()
        self.toolbar.Realize()

        self.book = wx.Simplebook(self)
        self.module_editor = ModuleEditorPanel(self.book, self.project)
        self.frame_editor = FrameEditorPanel(self.book, self.project)
        self.animation_editor = AnimationEditorPanel(self.book, self.project)
        self.book.AddPage(self.module_editor, "Modules", select=True)
        self.book.AddPage(self.frame_editor, "Frames", select=False)
        self.book.AddPage(self.animation_editor, "Animations", select=False)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.book, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.toolbar.Bind(wx.EVT_TOOL, self.on_switch_tool)

    # UI construction
    def _build_menu(self) -> None:
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        
        # Standard items, simplified accelerators to avoid parsing issues
        self.m_open = file_menu.Append(wx.ID_OPEN, "&Open...\tCtrl+O", "Open an existing project")
        self.m_save = file_menu.Append(wx.ID_SAVE, "&Save\tCtrl+S", "Save the current project")
        self.m_save_as = file_menu.Append(wx.ID_ANY, "Save &As...\tCtrl+Shift+S", "Save with a new name")
        #file_menu.AppendSeparator()
        
        file_menu.Bind(wx.EVT_MENU, self.on_save_as, self.m_save_as)
        file_menu.Bind(wx.EVT_MENU, self.on_open, self.m_open)
        file_menu.Bind(wx.EVT_MENU, self.on_save, self.m_save)
        
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
        
        # File Tools
        #self.toolbar.AddTool(wx.ID_OPEN, "Open", wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN, wx.ART_TOOLBAR, size))
        #self.toolbar.AddTool(wx.ID_SAVE, "Save", wx.ArtProvider.GetBitmap(wx.ART_FILE_SAVE, wx.ART_TOOLBAR, size))
        #self.toolbar.AddSeparator()
        
        self.t_modules = self.toolbar.AddRadioTool(
            wx.ID_ANY, "Modules", self._make_icon("modules", size)
        )
        self.t_frames = self.toolbar.AddRadioTool(
            wx.ID_ANY, "Frames", self._make_icon("frames", size)
        )
        self.t_anims = self.toolbar.AddRadioTool(
            wx.ID_ANY, "Animations", self._make_icon("animations", size)
        )
        self.toolbar.ToggleTool(self.t_modules.GetId(), True)

    def _make_icon(self, kind: str, size: tuple[int, int]) -> wx.Bitmap:
        w, h = size
        bmp = wx.Bitmap(w, h, 32)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 0)))
        dc.Clear()

        if kind == "modules":
            dc.SetPen(wx.Pen(wx.Colour(70, 130, 180), width=2))
            dc.DrawRectangle(4, 4, w - 8, h - 8)
            dc.SetPen(wx.Pen(wx.Colour(70, 130, 180), width=1))
            for x in range(6, w - 6, 6):
                dc.DrawLine(x, 6, x, h - 6)
            for y in range(6, h - 6, 6):
                dc.DrawLine(6, y, w - 6, y)
            dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), width=1))
            dc.DrawLine(6, 6, w - 6, h - 6)
        elif kind == "frames":
            dc.SetPen(wx.Pen(wx.Colour(40, 180, 90), width=2))
            dc.SetBrush(wx.Brush(wx.Colour(40, 180, 90, 40)))
            dc.DrawRectangle(6, 6, w - 12, h - 12)
            dc.SetPen(wx.Pen(wx.Colour(30, 140, 70), width=2))
            dc.SetBrush(wx.Brush(wx.Colour(30, 140, 70, 50)))
            dc.DrawRectangle(10, 10, w - 14, h - 14)
        elif kind == "animations":
            dc.SetBrush(wx.Brush(wx.Colour(200, 150, 60)))
            dc.SetPen(wx.Pen(wx.Colour(200, 150, 60)))
            points = [(8, 6), (18, 12), (8, 18)]
            dc.DrawPolygon(points)
            dc.SetPen(wx.Pen(wx.Colour(120, 120, 120), width=2))
            dc.DrawLine(4, 6, 4, 18)
            dc.DrawLine(4, 18, 6, 18)
            dc.SetPen(wx.Pen(wx.Colour(220, 200, 120), width=2, style=wx.PENSTYLE_DOT))
            dc.DrawLine(12, 6, 20, 6)
            dc.DrawLine(12, 18, 20, 18)
        dc.SelectObject(wx.NullBitmap)
        return bmp

    # Menu handlers
    def on_new(self, _: wx.CommandEvent) -> None:
        self.project = Project()
        self.current_path = None
        self._reload_project_into_panels()

    def on_open(self, _: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self,
            "Open project",
            wildcard="JSON files (*.json)|*.json|AuroraGT Sprite (*.sprite)|*.sprite",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
            self.project = Project.from_json(path)
            self.current_path = path
            self._reload_project_into_panels()

    def on_save(self, _: wx.CommandEvent) -> None:
        if not self.current_path:
            self.on_save_as(wx.CommandEvent())
            return
        self.project.to_json(self.current_path)
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
                wx.MessageBox(f"Saved to {path}", "Saved")
        except Exception as exc:
            wx.LogError(f"Save As failed: {exc}")


    def on_about(self, _: wx.CommandEvent) -> None:
        wx.MessageBox(
            "Modular Sprite Editor\nA simple modular sprite editing tool built with wxPython.",
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

        # Handle View Tools
        if tool_id == self.t_modules.GetId():
            self.book.ChangeSelection(0)
        elif tool_id == self.t_frames.GetId():
            self.book.ChangeSelection(1)
            self.frame_editor.refresh_choices()
            self.frame_editor.refresh_frames(self.frame_editor.selected_frame_id)
        elif tool_id == self.t_anims.GetId():
            self.book.ChangeSelection(2)
            self.animation_editor.refresh_choices()
            self.animation_editor.refresh_animations(self.animation_editor.selected_animation_id)

    # Helpers
    def _reload_project_into_panels(self) -> None:
        self.module_editor.set_project(self.project)
        self.frame_editor.set_project(self.project)
        self.animation_editor.set_project(self.project)


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
        frame.Show()
        self.SetTopWindow(frame)
        return True

def main() -> None:
    # redirect=False is CRITICAL to see console output if things go wrong
    app = SpriteEditorApp(False)
    app.MainLoop()


if __name__ == "__main__":
    main()
