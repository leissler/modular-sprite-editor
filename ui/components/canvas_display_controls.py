from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import wx

from ui.base_canvas import BACKDROP_CHECKER, BACKDROP_COLOUR, DEFAULT_BACKDROP_COLOUR, BaseCanvas

CONFIG_BACKDROP = "View/Backdrop/{}"  # per tab: "checker" | "colour"
CONFIG_BACKDROP_COLOUR = "View/BackdropColour"  # "r,g,b", one preview colour shared by all tabs

# Live view bars, so a new backdrop colour shows in every tab at once. Destroyed wx windows are falsy.
_LIVE_BARS: List["CanvasDisplayControls"] = []
_shared_colour: Optional[Tuple[int, int, int]] = None


def _config() -> Optional[wx.ConfigBase]:
    try:
        return wx.Config.Get()
    except Exception:
        return None


def shared_backdrop_colour() -> Tuple[int, int, int]:
    global _shared_colour
    if _shared_colour is None:
        _shared_colour = DEFAULT_BACKDROP_COLOUR
        cfg = _config()
        raw = cfg.Read(CONFIG_BACKDROP_COLOUR, "") if cfg else ""
        try:
            r, g, b = (max(0, min(255, int(v))) for v in raw.split(","))
            _shared_colour = (r, g, b)
        except ValueError:
            pass
    return _shared_colour


def set_shared_backdrop_colour(colour: Tuple[int, int, int]) -> None:
    global _shared_colour
    _shared_colour = (int(colour[0]), int(colour[1]), int(colour[2]))
    cfg = _config()
    if cfg:
        cfg.Write(CONFIG_BACKDROP_COLOUR, ",".join(str(v) for v in _shared_colour))
        cfg.Flush()
    _LIVE_BARS[:] = [bar for bar in _LIVE_BARS if bar]
    for bar in _LIVE_BARS:
        bar._on_shared_colour(_shared_colour)


class CanvasDisplayControls(wx.Panel):
    """
    Shared view bar shown under every editor canvas.

    Contains grid size, Grid toggle, Backdrop (checkerboard or a solid preview colour) and a Fit
    button. Optional: "Part bounds" (outline every module part) for composition canvases and
    "Show key colour" (raw sheet pixels) for the Modules tab, the only place where seeing the
    transparent key colour helps. Editors append their own view toggles with ``add_toggle``.
    """

    def __init__(
        self,
        parent: wx.Window,
        canvas: BaseCanvas,
        *,
        view_key: str,
        default_backdrop: str = BACKDROP_CHECKER,
        scene_backdrop: bool = False,
        part_bounds: bool = False,
        key_colour_toggle: bool = False,
        on_key_colour_changed: Optional[Callable[[bool], None]] = None,
    ):
        super().__init__(parent)
        self.canvas = canvas
        self.view_key = view_key
        self.scene_backdrop = scene_backdrop
        self.on_key_colour_changed = on_key_colour_changed

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

        # Backdrop: what shows where the artwork is transparent.
        controls.Add(wx.StaticText(self, label="Backdrop"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.backdrop_choice = wx.Choice(self, choices=["Checker", "Scene colour" if scene_backdrop else "Colour"])
        self.backdrop_choice.SetToolTip(
            "Checker shows exactly what is transparent. "
            + ("Scene colour previews the scene's background (Scene settings)."
               if scene_backdrop else "Colour previews the artwork on a solid backdrop, e.g. your game's background.")
        )
        # macOS sizes a Choice for its current item; leave room for the longest one plus the arrows.
        longest = max(self.GetTextExtent(self.backdrop_choice.GetString(i))[0] for i in range(self.backdrop_choice.GetCount()))
        self.backdrop_choice.SetMinSize((longest + 44, -1))
        controls.Add(self.backdrop_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.backdrop_picker: Optional[wx.ColourPickerCtrl] = None
        if not scene_backdrop:
            self.backdrop_picker = wx.ColourPickerCtrl(self, colour=wx.Colour(*shared_backdrop_colour()))
            self.backdrop_picker.SetToolTip("Backdrop colour (shared by all tabs)")
            controls.Add(self.backdrop_picker, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        else:
            controls.AddSpacer(4)

        self.chk_part_bounds: Optional[wx.CheckBox] = None
        if part_bounds:
            self.chk_part_bounds = wx.CheckBox(self, label="Part bounds")
            self.chk_part_bounds.SetToolTip("Outline every module part: the area each hardware sprite covers")
            controls.Add(self.chk_part_bounds, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            self.chk_part_bounds.Bind(wx.EVT_CHECKBOX, self._on_toggle_part_bounds)

        self.chk_key_colour: Optional[wx.CheckBox] = None
        if key_colour_toggle:
            self.chk_key_colour = wx.CheckBox(self, label="Show key colour")
            self.chk_key_colour.SetToolTip("Show the sheet's transparent (key) colour instead of hiding it")
            controls.Add(self.chk_key_colour, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            self.chk_key_colour.Bind(wx.EVT_CHECKBOX, self._on_toggle_key_colour)

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
        self.backdrop_choice.Bind(wx.EVT_CHOICE, self._on_backdrop_choice)
        if self.backdrop_picker:
            self.backdrop_picker.Bind(wx.EVT_COLOURPICKER_CHANGED, self._on_backdrop_colour)
        self._apply_grid_spacing()

        cfg = _config()
        mode = cfg.Read(CONFIG_BACKDROP.format(view_key), default_backdrop) if cfg else default_backdrop
        self._set_backdrop_mode(mode, persist=False)
        _LIVE_BARS.append(self)

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

    # --- grid
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

    # --- backdrop
    def _set_backdrop_mode(self, mode: str, persist: bool = True) -> None:
        mode = BACKDROP_COLOUR if mode == BACKDROP_COLOUR else BACKDROP_CHECKER
        self.backdrop_choice.SetSelection(1 if mode == BACKDROP_COLOUR else 0)
        self.canvas.set_backdrop(mode, None if self.scene_backdrop else shared_backdrop_colour())
        if persist:
            cfg = _config()
            if cfg:
                cfg.Write(CONFIG_BACKDROP.format(self.view_key), mode)
                cfg.Flush()

    def _on_backdrop_choice(self, _event: wx.CommandEvent) -> None:
        self._set_backdrop_mode(BACKDROP_COLOUR if self.backdrop_choice.GetSelection() == 1 else BACKDROP_CHECKER)

    def _on_backdrop_colour(self, event: wx.ColourPickerEvent) -> None:
        colour = event.GetColour()
        # Picking a colour means "show it": switch this tab to the colour backdrop.
        self._set_backdrop_mode(BACKDROP_COLOUR)
        set_shared_backdrop_colour((colour.Red(), colour.Green(), colour.Blue()))

    def _on_shared_colour(self, colour: Tuple[int, int, int]) -> None:
        if self.scene_backdrop:
            return
        if self.backdrop_picker:
            self.backdrop_picker.SetColour(wx.Colour(*colour))
        self.canvas.set_backdrop(self.canvas.backdrop, colour)

    # --- part bounds (FrameCanvas and subclasses)
    def _on_toggle_part_bounds(self, event: wx.CommandEvent) -> None:
        self.canvas.set_show_part_bounds(event.IsChecked())  # type: ignore[attr-defined]

    # --- key colour (Modules tab)
    def _on_toggle_key_colour(self, event: wx.CommandEvent) -> None:
        if self.on_key_colour_changed:
            self.on_key_colour_changed(event.IsChecked())

    def set_key_colour_shown(self, shown: bool) -> None:
        if self.chk_key_colour:
            self.chk_key_colour.SetValue(bool(shown))
