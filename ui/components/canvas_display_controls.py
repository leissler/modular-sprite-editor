from __future__ import annotations

from typing import Callable, Optional

import wx

from ui.base_canvas import BaseCanvas


class CanvasDisplayControls(wx.Panel):
    """Shared grid/transparency controls for canvas panels."""

    def __init__(
        self,
        parent: wx.Window,
        canvas: BaseCanvas,
        *,
        show_transparency: bool = True,
        on_transparency_changed: Optional[Callable[[bool], None]] = None,
    ):
        super().__init__(parent)
        self.canvas = canvas
        self.on_transparency_changed = on_transparency_changed

        controls = wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(wx.StaticText(self, label="Grid X"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.grid_w = wx.SpinCtrl(self, min=4, max=512, initial=max(4, int(canvas.grid_spacing[0])))
        controls.Add(self.grid_w, 0, wx.RIGHT, 8)
        controls.Add(wx.StaticText(self, label="Grid Y"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.grid_h = wx.SpinCtrl(self, min=4, max=512, initial=max(4, int(canvas.grid_spacing[1])))
        controls.Add(self.grid_h, 0, wx.RIGHT, 12)

        self.chk_grid = wx.CheckBox(self, label="Show Grid")
        self.chk_grid.SetValue(bool(canvas.show_grid))
        controls.Add(self.chk_grid, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.chk_transparency: Optional[wx.CheckBox] = None
        if show_transparency:
            self.chk_transparency = wx.CheckBox(self, label="Transparency")
            self.chk_transparency.SetValue(bool(canvas.show_transparency))
            controls.Add(self.chk_transparency, 0, wx.ALIGN_CENTER_VERTICAL)
            self.chk_transparency.Bind(wx.EVT_CHECKBOX, self._on_toggle_transparency)

        self.SetSizer(controls)

        self.grid_w.Bind(wx.EVT_SPINCTRL, self._on_change_grid_spacing)
        self.grid_h.Bind(wx.EVT_SPINCTRL, self._on_change_grid_spacing)
        self.chk_grid.Bind(wx.EVT_CHECKBOX, self._on_toggle_grid)
        self._apply_grid_spacing()

    def _apply_grid_spacing(self) -> None:
        spacing = (max(4, self.grid_w.GetValue()), max(4, self.grid_h.GetValue()))
        self.canvas.set_grid_spacing(spacing)

    def _on_change_grid_spacing(self, _: wx.CommandEvent) -> None:
        self._apply_grid_spacing()

    def _on_toggle_grid(self, event: wx.CommandEvent) -> None:
        self.canvas.set_show_grid(event.IsChecked())

    def _on_toggle_transparency(self, event: wx.CommandEvent) -> None:
        enabled = event.IsChecked()
        self.canvas.set_show_transparency(enabled)
        if self.on_transparency_changed:
            self.on_transparency_changed(enabled)

    def set_transparency_value(self, enabled: bool) -> None:
        if not self.chk_transparency:
            return
        self.chk_transparency.SetValue(bool(enabled))
        self.canvas.set_show_transparency(bool(enabled))

