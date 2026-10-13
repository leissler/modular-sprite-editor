from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import wx

from hardware_budget import PROFILES, profile_by_key
from ui.base_canvas import BACKDROP_CHECKER, BACKDROP_COLOUR, DEFAULT_BACKDROP_COLOUR, BaseCanvas

CONFIG_BACKDROP = "View/Backdrop/{}"  # per tab: "checker" | "colour"
CONFIG_BACKDROP_COLOUR = "View/BackdropColour"  # "r,g,b", one preview colour shared by all tabs
CONFIG_BUDGET = "View/Budget/{}"  # per tab: "" (off) or a hardware profile key
BUDGET_LABELS = {"md_h40": "MD H40", "md_h32": "MD H32"}
GAP = 8  # between the bar's groups

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

    Contains the Grid toggle and size, Backdrop (checkerboard or a solid preview colour) and a Fit
    button. Optional: "Bounds" (outline every module part) for composition canvases and "Key colour"
    (raw sheet pixels) for the Modules tab, the only place where seeing the transparent key colour
    helps. Editors append their own view toggles with ``add_toggle``. The controls wrap into more
    rows when the canvas is narrow (laptop screens), so none of them gets cut off.
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
        budget: bool = False,
        key_colour_toggle: bool = False,
        on_key_colour_changed: Optional[Callable[[bool], None]] = None,
    ):
        super().__init__(parent)
        self.canvas = canvas
        self.view_key = view_key
        self.scene_backdrop = scene_backdrop
        self.on_key_colour_changed = on_key_colour_changed
        self.on_budget_changed: Optional[Callable[[], None]] = None

        # The controls wrap into more rows when the canvas is narrow; Fit stays at the right of the first row.
        self._sizer = wx.WrapSizer(wx.HORIZONTAL, wx.REMOVE_LEADING_SPACES)
        controls = self._sizer
        self.chk_grid = wx.CheckBox(self, label="Grid")
        self.chk_grid.SetValue(bool(canvas.show_grid))
        self.chk_grid.SetToolTip("Show grid (View ▸ Toggle Grid). The numbers are its width and height in pixels.")
        self.grid_w = wx.SpinCtrl(self, min=4, max=512, initial=max(4, int(canvas.grid_spacing[0])), size=(52, -1))
        self.grid_w.SetToolTip("Grid width in pixels")
        self.grid_h = wx.SpinCtrl(self, min=4, max=512, initial=max(4, int(canvas.grid_spacing[1])), size=(52, -1))
        self.grid_h.SetToolTip("Grid height in pixels")
        grid_box = wx.BoxSizer(wx.HORIZONTAL)
        grid_box.Add(self.chk_grid, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        grid_box.Add(self.grid_w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        grid_box.Add(wx.StaticText(self, label="×"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        grid_box.Add(self.grid_h, 0, wx.ALIGN_CENTER_VERTICAL)
        controls.Add(grid_box, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, GAP)

        # Backdrop: what shows where the artwork is transparent.
        backdrop_box = wx.BoxSizer(wx.HORIZONTAL)
        self.backdrop_choice = wx.Choice(self, choices=["Checker", "Scene colour" if scene_backdrop else "Colour"])
        self.backdrop_choice.SetToolTip(
            "Backdrop: what shows where the artwork is transparent. Checker shows exactly what is transparent. "
            + ("Scene colour previews the scene's background (Scene settings)."
               if scene_backdrop else "Colour previews the artwork on a solid backdrop, e.g. your game's background.")
        )
        # macOS sizes a Choice for its current item; leave room for the longest one plus the arrows.
        longest = max(self.GetTextExtent(self.backdrop_choice.GetString(i))[0] for i in range(self.backdrop_choice.GetCount()))
        self.backdrop_choice.SetMinSize((longest + 44, -1))
        backdrop_box.Add(self.backdrop_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        self.backdrop_picker: Optional[wx.ColourPickerCtrl] = None
        if not scene_backdrop:
            self.backdrop_picker = wx.ColourPickerCtrl(self, colour=wx.Colour(*shared_backdrop_colour()))
            self.backdrop_picker.SetToolTip("Backdrop colour (shared by all tabs)")
            backdrop_box.Add(self.backdrop_picker, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        controls.Add(backdrop_box, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, GAP)

        self.chk_part_bounds: Optional[wx.CheckBox] = None
        if part_bounds:
            self.chk_part_bounds = wx.CheckBox(self, label="Bounds")
            self.chk_part_bounds.SetToolTip("Outline every module part: the area each hardware sprite covers")
            controls.Add(self.chk_part_bounds, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, GAP)
            self.chk_part_bounds.Bind(wx.EVT_CHECKBOX, self._on_toggle_part_bounds)

        self.budget_choice: Optional[wx.Choice] = None
        if budget:
            labels = ["No budget"] + [BUDGET_LABELS.get(p.key, p.name) for p in PROFILES]
            self.budget_choice = wx.Choice(self, choices=labels)
            longest = max(self.GetTextExtent(label)[0] for label in labels)
            self.budget_choice.SetMinSize((longest + 44, -1))
            self.budget_choice.SetToolTip(
                "Hardware budget: outline the console's hardware sprites, mark scanlines where sprites would "
                "drop out (red) and show sprite / tile counts. MD H40 = 320 px wide mode, H32 = 256 px."
            )
            controls.Add(self.budget_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, GAP)
            self.budget_choice.Bind(wx.EVT_CHOICE, self._on_budget_choice)

        self.chk_key_colour: Optional[wx.CheckBox] = None
        if key_colour_toggle:
            self.chk_key_colour = wx.CheckBox(self, label="Key colour")
            self.chk_key_colour.SetToolTip("Show the sheet's transparent (key) colour instead of hiding it")
            controls.Add(self.chk_key_colour, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, GAP)
            self.chk_key_colour.Bind(wx.EVT_CHECKBOX, self._on_toggle_key_colour)

        # Editor-specific toggles go after these.
        self._extra_insert_index = controls.GetItemCount()
        self.btn_fit = wx.Button(self, label="Fit", style=wx.BU_EXACTFIT)
        self.btn_fit.SetToolTip("Fit content in view (View ▸ Fit to Content, Ctrl+0)")
        outer = wx.BoxSizer(wx.HORIZONTAL)
        outer.Add(controls, 1, wx.EXPAND)
        outer.Add(self.btn_fit, 0, wx.ALIGN_TOP)
        self.SetSizer(outer)
        self._rows_height: Optional[int] = None
        self.Bind(wx.EVT_SIZE, self._on_size)

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
        if self.budget_choice is not None:
            self._set_budget(cfg.Read(CONFIG_BUDGET.format(view_key), "") if cfg else "", persist=False)
        _LIVE_BARS.append(self)

    def _on_size(self, event: wx.SizeEvent) -> None:
        """Wrap the controls for the width there is; the bar grows by a row instead of cutting controls off."""
        event.Skip()
        width = self.GetClientSize().width - self.btn_fit.GetBestSize().width
        if width <= 0:
            return
        self._sizer.InformFirstDirection(wx.HORIZONTAL, width, -1)
        height = max(self._sizer.CalcMin().height, self.btn_fit.GetBestSize().height)
        if height != self._rows_height:
            self._rows_height = height
            self.SetMinSize((self.btn_fit.GetBestSize().width + 160, height))
            parent = self.GetParent()
            wx.CallAfter(lambda: parent and parent.Layout())

    def add_separator(self) -> None:
        """Extra room before an editor's own toggles (a spacer: dropped where the bar wraps)."""
        self._sizer.InsertSpacer(self._extra_insert_index, GAP)
        self._extra_insert_index += 1

    def add_toggle(self, label: str, value: bool, on_change: Callable[[bool], None], tooltip: str = "") -> wx.CheckBox:
        chk = wx.CheckBox(self, label=label)
        chk.SetValue(bool(value))
        if tooltip:
            chk.SetToolTip(tooltip)
        chk.Bind(wx.EVT_CHECKBOX, lambda e: on_change(e.IsChecked()))
        self._sizer.Insert(self._extra_insert_index, chk, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, GAP)
        self._extra_insert_index += 1
        self.Layout()
        return chk

    def add_control(self, window: wx.Window, label: str = "") -> wx.Window:
        box = wx.BoxSizer(wx.HORIZONTAL)  # a label stays with its control when the bar wraps
        if label:
            box.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        box.Add(window, 0, wx.ALIGN_CENTER_VERTICAL)
        self._sizer.Insert(self._extra_insert_index, box, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, GAP)
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

    # --- hardware budget (FrameCanvas and subclasses)
    def _set_budget(self, key: str, persist: bool = True) -> None:
        profile = profile_by_key(key)
        if self.budget_choice is not None:
            self.budget_choice.SetSelection(PROFILES.index(profile) + 1 if profile else 0)
        self.canvas.set_budget_profile(profile)  # type: ignore[attr-defined]
        if persist:
            cfg = _config()
            if cfg:
                cfg.Write(CONFIG_BUDGET.format(self.view_key), profile.key if profile else "")
                cfg.Flush()

    def _on_budget_choice(self, _event: wx.CommandEvent) -> None:
        index = self.budget_choice.GetSelection() if self.budget_choice else 0
        self._set_budget(PROFILES[index - 1].key if index > 0 else "")
        if self.on_budget_changed:
            self.on_budget_changed()

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
