"""Main entry point for the modular sprite editor built with wxPython."""

from __future__ import annotations

from typing import Optional

import wx

from models import Project
from ui.animation_editor import AnimationEditorPanel
from ui.frame_editor import FrameEditorPanel
from ui.module_editor import ModuleEditorPanel


class MainFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title="Modular Sprite Editor", size=(1200, 800))
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

        self.Bind(wx.EVT_TOOL, self.on_switch_tool)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    # UI construction
    def _build_menu(self) -> None:
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        self.m_new = file_menu.Append(wx.ID_NEW, "&New\tCtrl+N")
        self.m_open = file_menu.Append(wx.ID_OPEN, "&Open...\tCtrl+O")
        self.m_save = file_menu.Append(wx.ID_SAVE, "&Save\tCtrl+S")
        self.m_save_as = file_menu.Append(wx.ID_SAVEAS, "Save &As...")
        file_menu.AppendSeparator()
        self.m_quit = file_menu.Append(wx.ID_EXIT, "Quit")
        menubar.Append(file_menu, "&File")
        menubar.Append(wx.Menu(), "&Edit")
        menubar.Append(wx.Menu(), "&View")
        menubar.Append(wx.Menu(), "&Help")
        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self.on_new, self.m_new)
        self.Bind(wx.EVT_MENU, self.on_open, self.m_open)
        self.Bind(wx.EVT_MENU, self.on_save, self.m_save)
        self.Bind(wx.EVT_MENU, self.on_save_as, self.m_save_as)
        self.Bind(wx.EVT_MENU, lambda _: self.Close(), self.m_quit)

    def _add_toolbar_tools(self) -> None:
        size = (16, 16)
        self.t_modules = self.toolbar.AddRadioTool(
            wx.ID_ANY, "Modules", self._make_tool_bitmap(wx.Colour(70, 130, 180), size)
        )
        self.t_frames = self.toolbar.AddRadioTool(
            wx.ID_ANY, "Frames", self._make_tool_bitmap(wx.Colour(40, 180, 90), size)
        )
        self.t_anims = self.toolbar.AddRadioTool(
            wx.ID_ANY, "Animations", self._make_tool_bitmap(wx.Colour(200, 150, 60), size)
        )
        self.toolbar.ToggleTool(self.t_modules.GetId(), True)

    def _make_tool_bitmap(self, color: wx.Colour, size: tuple[int, int]) -> wx.Bitmap:
        bmp = wx.Bitmap(*size)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(color))
        dc.Clear()
        pen = wx.Pen(wx.Colour(255, 255, 255))
        dc.SetPen(pen)
        dc.DrawLine(2, size[1] // 2, size[0] - 2, size[1] // 2)
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
            wildcard="JSON files (*.json)|*.json",
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

    def on_close(self, event: wx.CloseEvent) -> None:
        event.Skip()

    # Toolbar switching
    def on_switch_tool(self, event: wx.CommandEvent) -> None:
        tool_id = event.GetId()
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


def main() -> None:
    app = wx.App()
    frame = MainFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
