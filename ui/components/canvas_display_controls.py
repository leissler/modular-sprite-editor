from __future__ import annotations

from typing import Callable, Optional

import wx

from ui.base_canvas import BaseCanvas


class CanvasDisplayControls(wx.Panel):
    """
    Shared view bar shown under every editor canvas.

    Always contains grid size, grid / transparency toggles and a Fit button. Editors append
    their own view toggles with ``add_toggle`` so view options live in one place everywhere.
    """

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

        self._sizer = wx.BoxSizer(wx.HORIZONTAL)
        controls = self._sizer
        controls.Add(wx.StaticText(self, label="Grid"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.grid_w = wx.SpinCtrl(self, min=4, max=512, initial=max(4, int(canvas.grid_spacing[0])), size=(64, -1))
        self.grid_w.SetToolTip("Grid width in pixels")
        controls.Add(self.grid_w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        controls.Add(wx.StaticText(self, label="×"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        self.grid_h = wx.SpinCtrl(self, min=4, max=512, initial=max(4, int(canvas.grid_spacing[1])), size=(64, -1))
        self.grid_h.SetToolTip("Grid height in pixels")
        controls.Add(self.grid_h, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.chk_grid = wx.CheckBox(self, label="Grid")
        self.chk_grid.SetValue(bool(canvas.show_grid))
        self.chk_grid.SetToolTip("Show grid (View ▸ Toggle Grid)")
        controls.Add(self.chk_grid, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.chk_transparency: Optional[wx.CheckBox] = None
        if show_transparency:
            self.chk_transparency = wx.CheckBox(self, label="Transparency")
            self.chk_transparency.SetValue(bool(canvas.show_transparency))
            self.chk_transparency.SetToolTip("Show the checkerboard and apply image transparent colours")
            controls.Add(self.chk_transparency, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            self.chk_transparency.Bind(wx.EVT_CHECKBOX, self._on_toggle_transparency)

        # Editor-specific toggles are inserted before the stretch spacer.
        self._extra_insert_index = controls.GetItemCount()
        controls.AddStretchSpacer(1)
        self.btn_fit = wx.Button(self, label="Fit", style=wx.BU_EXACTFIT)
        self.btn_fit.SetToolTip("Fit content in view (View ▸ Fit to Content, Ctrl+0)")
        controls.Add(self.btn_fit, 0, wx.ALIGN_CENTER_VERTICAL)

        self.SetSizer(controls)

        self.grid_w.Bind(wx.EVT_SPINCTRL, self._on_change_grid_spacing)
        self.grid_h.Bind(wx.EVT_SPINCTRL, self._on_change_grid_spacing)
        self.chk_grid.Bind(wx.EVT_CHECKBOX, self._on_toggle_grid)
        self.btn_fit.Bind(wx.EVT_BUTTON, lambda _e: self.canvas.fit_to_content())
        self._apply_grid_spacing()

    def add_separator(self) -> None:
        line = wx.StaticLine(self, style=wx.LI_VERTICAL, size=(1, 18))
        self._sizer.Insert(self._extra_insert_index, line, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        self._extra_insert_index += 1

    def add_toggle(self, label: str, value: bool, on_change: Callable[[bool], None], tooltip: str = "") -> wx.CheckBox:
        chk = wx.CheckBox(self, label=label)
        chk.SetValue(bool(value))
        if tooltip:
            chk.SetToolTip(tooltip)
        chk.Bind(wx.EVT_CHECKBOX, lambda e: on_change(e.IsChecked()))
        self._sizer.Insert(self._extra_insert_index, chk, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._extra_insert_index += 1
        self.Layout()
        return chk

    def add_control(self, window: wx.Window, label: str = "") -> wx.Window:
        if label:
            self._sizer.Insert(
                self._extra_insert_index,
                wx.StaticText(self, label=label),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                4,
            )
            self._extra_insert_index += 1
        self._sizer.Insert(self._extra_insert_index, window, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._extra_insert_index += 1
        self.Layout()
        return window

    def _apply_grid_spacing(self) -> None:
        spacing = (max(4, self.grid_w.GetValue()), max(4, self.grid_h.GetValue()))
        self.canvas.set_grid_spacing(spacing)

    def _on_change_grid_spacing(self, _: wx.CommandEvent) -> None:
        self._apply_grid_spacing()

    def _on_toggle_grid(self, event: wx.CommandEvent) -> None:
        self.canvas.set_show_grid(event.IsChecked())

    def toggle_grid(self) -> None:
        self.chk_grid.SetValue(not self.chk_grid.GetValue())
        self.canvas.set_show_grid(self.chk_grid.GetValue())

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
