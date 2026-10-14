"""Display scaling (C13): crisp UI and pixel art on Windows at 125 %, 150 % and more.

Windows stretches the window of a program that doesn't say it handles the display's scaling as a bitmap, which blurs
the text and makes the pixels of the art uneven. Importing this module (app.py does it before any window exists) tells
Windows the editor scales itself for the system DPI, so wx draws in device pixels: canvases at whole-number zoom stay
pixel-exact. The editor's own fixed sizes (control widths, row heights, thumbnails, custom-drawn widgets) go through
``px``. macOS and GTK scale for the program (wx works in logical pixels there), so there ``px`` changes nothing.

``MSE_UI_SCALE`` (e.g. 1.5) sets the factor on any system, to try the scaled sizes without a scaled Windows display.
"""

from __future__ import annotations

import os
import sys


def _system_scale() -> float:
    if sys.platform != "win32":
        return 1.0
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE (Windows 8.1+), before any window
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            return 1.0
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()  # Windows 10 1607+; 96 while Windows still scales for us
    except (AttributeError, OSError):
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
    return max(1.0, dpi / 96.0) if dpi else 1.0


def _scale() -> float:
    system = _system_scale()  # always: the awareness must be set before the first window
    try:
        return max(0.5, float(os.environ["MSE_UI_SCALE"]))
    except (KeyError, ValueError):
        return system


SCALE = _scale()


def px(value: int) -> int:
    """A size in pixels at 100 % in device pixels of this display; -1 and 0 (wx's "default") stay as they are."""
    return int(round(value * SCALE)) if value > 0 else value


def pxf(value: float) -> float:
    """``px`` for sizes kept as floats (zoom-like widths)."""
    return value * SCALE
