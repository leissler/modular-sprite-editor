"""The editor's theme: Like the system, Dark or Light (Edit ▸ Preferences, View ▸ Theme).

One palette of named colours for everything the editor draws itself (lists, the step strip, the timeline, swatches,
inspector texts, the canvas checkerboard), in a dark and a light version; ``T.<name>`` is the current one, so paint
code reads it when it paints. Colours set on a control once (a label's grey, a list's background) go through
``style``, which sets them again when the theme changes. What is drawn over the art (outlines, handles, hitboxes,
readouts in their dark boxes) keeps its own colours: it has to show on any backdrop.

Native controls follow the system's appearance. On macOS a chosen Dark or Light sets the application's appearance
too; wx 3.2 cannot darken native controls on Windows or GTK, so there the theme changes the editor's own drawing
(Like the system is light on Windows, as its controls are). Kept in the preferences under ``View/Theme``.
"""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Optional, Tuple

import wx

from ui.preferences import config

SYSTEM, DARK, LIGHT = "system", "dark", "light"
MODES = (SYSTEM, DARK, LIGHT)
LABELS = {SYSTEM: "Like the system", DARK: "Dark", LIGHT: "Light"}
CONFIG_KEY = "View/Theme"

RGB = Tuple[int, int, int]

# name: (dark, light). Groups: lists and text, the step strip and the timeline, swatches, the canvas.
COLOURS: Dict[str, Tuple[RGB, RGB]] = {
    # lists, rows and text
    "row": ((40, 41, 45), (255, 255, 255)),
    "row_alt": ((44, 45, 49), (246, 247, 249)),
    "selected": ((56, 74, 104), (204, 223, 250)),
    "also_selected": ((50, 63, 84), (226, 236, 251)),
    "text": ((226, 226, 230), (30, 32, 36)),
    "text_dim": ((140, 142, 150), (112, 116, 126)),
    "hint": ((150, 156, 170), (104, 108, 120)),  # explanations, captions, section titles
    "warn": ((255, 140, 120), (196, 64, 40)),
    "error": ((255, 120, 110), (200, 48, 40)),
    "accent": ((255, 176, 64), (214, 124, 16)),  # marked, chosen, keys being dragged
    "drop": ((140, 210, 255), (32, 120, 220)),  # where a dragged item goes
    "focus": ((100, 200, 255), (24, 120, 216)),  # the selected tile's outline
    "link": ((120, 175, 255), (24, 100, 210)),
    "replaced": ((120, 210, 255), (24, 116, 196)),  # a mapping's replacement
    "border": ((70, 72, 80), (196, 198, 204)),
    "thumb": ((36, 37, 40), (234, 235, 238)),  # behind a list's thumbnails
    "tile": ((52, 53, 58), (238, 239, 242)),  # a palette's module tiles
    "hover": ((120, 124, 136), (150, 154, 164)),
    "well": ((30, 31, 34), (244, 245, 247)),  # small drawings inside an inspector (the easing curve)
    "well_line": ((64, 66, 74), (200, 202, 208)),
    # the step strip and the timeline
    "track": ((34, 35, 38), (250, 250, 252)),
    "ruler": ((30, 31, 34), (236, 237, 240)),
    "grid": ((52, 53, 58), (224, 225, 230)),
    "grid_strong": ((78, 80, 88), (190, 192, 200)),
    "outside": ((28, 28, 30), (230, 230, 234)),  # after the end of a scene
    "tick": ((70, 72, 80), (200, 202, 208)),
    "second": ((120, 124, 136), (140, 144, 154)),
    "cell": ((46, 47, 52), (238, 239, 243)),
    "cell_border": ((80, 82, 90), (176, 178, 186)),
    "hold": ((96, 100, 112), (176, 180, 190)),
    "playhead": ((255, 92, 92), (222, 52, 52)),
    "key": ((196, 204, 220), (92, 100, 118)),
    "key_stack": ((255, 120, 90), (222, 90, 56)),
    "tween": ((88, 120, 186), (126, 156, 218)),
    "tween_eased": ((132, 96, 186), (164, 130, 218)),
    "tween_text": ((230, 230, 240), (24, 28, 40)),  # the easing's name on a tween
    "ok": ((120, 210, 140), (36, 150, 70)),  # loop marks, a pose change on the timeline
    "outline": ((20, 20, 24), (90, 92, 100)),  # around small marks on the strip and the timeline
    # swatches
    "swatch_border": ((30, 30, 34), (110, 112, 120)),
    "empty_slot": ((96, 100, 112), (184, 188, 196)),
    "swatch_selected": ((255, 255, 255), (20, 22, 26)),
    # the canvas: the checkerboard follows the theme; lines over the art follow the backdrop behind it
    # (BaseCanvas.overlay_colour: a solid backdrop colour can be light in the dark theme and the other way round)
    "checker_a": ((60, 60, 60), (204, 204, 204)),
    "checker_b": ((80, 80, 80), (232, 232, 232)),
    "canvas_grid": ((100, 100, 100), (160, 160, 160)),
    "axis": ((200, 200, 200), (70, 70, 70)),  # the origin's cross (drawn see-through)
    "canvas_line": ((255, 255, 255), (20, 22, 28)),  # selections and drafts
    "canvas_faint": ((205, 208, 218), (70, 74, 86)),  # outlines and edges (drawn see-through)
}


def on(name: str, dark: bool) -> RGB:
    """A colour of the dark or the light theme, whichever is current (lines over a canvas' backdrop)."""
    on_dark, on_light = COLOURS[name]
    return on_dark if dark else on_light


class Palette:
    """The colours of one theme, as attributes (``palette.row``) holding wx.Colour."""

    def __init__(self, dark: bool):
        self.dark = dark
        for name, (on_dark, on_light) in COLOURS.items():
            setattr(self, name, wx.Colour(*(on_dark if dark else on_light)))

    def rgb(self, name: str) -> RGB:
        return on(name, self.dark)


def _set_macos_appearance(mode: str) -> None:
    """The application's appearance on macOS: dark, light, or the system's (nil)."""
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = objc.objc_msgSend

        def call(target, selector: bytes, *args, types=()):
            send.restype = ctypes.c_void_p
            send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *types]
            return send(target, objc.sel_registerName(selector), *args)

        app = call(objc.objc_getClass(b"NSApplication"), b"sharedApplication")
        appearance = None
        if mode in (DARK, LIGHT):
            name = call(objc.objc_getClass(b"NSString"), b"stringWithUTF8String:",
                        b"NSAppearanceNameDarkAqua" if mode == DARK else b"NSAppearanceNameAqua", types=(ctypes.c_char_p,))
            appearance = call(objc.objc_getClass(b"NSAppearance"), b"appearanceNamed:", name, types=(ctypes.c_void_p,))
        call(app, b"setAppearance:", appearance, types=(ctypes.c_void_p,))
    except (OSError, AttributeError, TypeError):
        pass  # the native controls keep the system's appearance


class Theme:
    def __init__(self) -> None:
        self.mode = SYSTEM
        self.palette = Palette(dark=True)
        self._styled: List[Tuple[wx.Window, Optional[str], Optional[str]]] = []
        self._listeners: List[Callable[[], None]] = []

    def __getattr__(self, name: str) -> wx.Colour:
        """``T.row``: the current theme's colour of that name."""
        palette = self.__dict__.get("palette")
        if palette is not None and name in COLOURS:
            return getattr(palette, name)
        raise AttributeError(name)

    @property
    def dark(self) -> bool:
        return self.palette.dark

    # ---------------------------------------------------------------- the setting
    def load(self) -> None:
        """Read the setting (call once a wx.App exists, before the windows are made)."""
        store = config()
        mode = store.Read(CONFIG_KEY, SYSTEM) if store else SYSTEM
        self.mode = mode if mode in MODES else SYSTEM
        _set_macos_appearance(self.mode)
        self.palette = Palette(self._resolved_dark())

    def _resolved_dark(self) -> bool:
        if self.mode == DARK:
            return True
        if self.mode == LIGHT:
            return False
        try:
            return bool(wx.SystemSettings.GetAppearance().IsDark())
        except (AttributeError, wx.wxAssertionError):
            return True

    def set_mode(self, mode: str) -> None:
        """Choose Like the system, Dark or Light: kept in the preferences, shown at once."""
        mode = mode if mode in MODES else SYSTEM
        store = config()
        if store:
            store.Write(CONFIG_KEY, mode)
            store.Flush()
        self.mode = mode
        _set_macos_appearance(mode)
        self._changed(self._resolved_dark())

    def system_changed(self) -> None:
        """The system's appearance changed (wx.EVT_SYS_COLOUR_CHANGED): follow it in Like the system."""
        if self.mode == SYSTEM:
            self._changed(self._resolved_dark())

    def _changed(self, dark: bool) -> None:
        if dark == self.palette.dark:
            return
        self.palette = Palette(dark)
        self._restyle()
        for listener in list(self._listeners):
            listener()

    # ---------------------------------------------------------------- controls
    def style(self, window: wx.Window, fg: Optional[str] = None, bg: Optional[str] = None) -> wx.Window:
        """Give a control a foreground and / or background colour of the theme, now and whenever it changes."""
        self._styled.append((window, fg, bg))
        self._apply(window, fg, bg)
        return window

    def _apply(self, window: wx.Window, fg: Optional[str], bg: Optional[str]) -> None:
        if fg:
            window.SetForegroundColour(getattr(self.palette, fg))
        if bg:
            window.SetBackgroundColour(getattr(self.palette, bg))
        window.Refresh()

    def _restyle(self) -> None:
        self._styled = [(w, fg, bg) for w, fg, bg in self._styled if w]  # destroyed windows are falsy
        for window, fg, bg in self._styled:
            self._apply(window, fg, bg)

    def on_change(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` after the theme changed (the main window redraws everything)."""
        self._listeners.append(listener)


T = Theme()
