"""Hooks the main window installs so editor panels can reach it without importing app.py.

All functions are safe no-ops when no main window is installed (tests, standalone widgets).
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

import wx

_checkpoint: Optional[Callable[[], None]] = None
_status: Optional[Callable[[str], None]] = None
_zoom: Optional[Callable[[float], None]] = None
_mapping_changed: Optional[Callable[[], None]] = None
_images_changed: Optional[Callable[[], None]] = None
_revision: Optional[Callable[[], Optional[str]]] = None
_swap_changed: Optional[Callable[[], None]] = None
_go_to: Optional[Callable[[Tuple[str, str]], None]] = None


def install(
    checkpoint: Optional[Callable[[], None]] = None,
    status: Optional[Callable[[str], None]] = None,
    zoom: Optional[Callable[[float], None]] = None,
    mapping_changed: Optional[Callable[[], None]] = None,
    images_changed: Optional[Callable[[], None]] = None,
    revision: Optional[Callable[[], Optional[str]]] = None,
    swap_changed: Optional[Callable[[], None]] = None,
    go_to: Optional[Callable[[Tuple[str, str]], None]] = None,
) -> None:
    global _checkpoint, _status, _zoom, _mapping_changed, _images_changed, _revision, _swap_changed, _go_to
    _checkpoint = checkpoint
    _status = status
    _zoom = zoom
    _mapping_changed = mapping_changed
    _images_changed = images_changed
    _revision = revision
    _swap_changed = swap_changed
    _go_to = go_to


def text_entry_has_focus() -> bool:
    """True while the user types into a text field (so editor hotkeys must stay quiet)."""
    focus = wx.Window.FindFocus()
    if focus is None:
        return False
    # wx.SearchCtrl is not a wx.TextCtrl on macOS; spin controls host a child TextCtrl.
    if isinstance(focus, (wx.TextCtrl, wx.SearchCtrl, wx.ComboBox)):
        return True
    parent = focus.GetParent()
    return isinstance(parent, (wx.SpinCtrl, wx.SpinCtrlDouble, wx.SearchCtrl))


def request_checkpoint() -> None:
    """Mark an undo step boundary now (call after a completed edit)."""
    if _checkpoint:
        _checkpoint()


def project_revision() -> Optional[str]:
    """Changes whenever the project does (the fingerprint of the last undo checkpoint); None without a main window,
    so callers then work out again what they would cache."""
    return _revision() if _revision else None


def show_status(text: str) -> None:
    """Show a transient message in the main window status bar."""
    if _status:
        _status(text)


def show_zoom(zoom: float) -> None:
    if _zoom:
        _zoom(zoom)


def notify_active_mapping_changed() -> None:
    if _mapping_changed:
        _mapping_changed()


def notify_active_palette_swap_changed() -> None:
    """The preview's palette swap (Project.active_palette_swap) changed: every preview draws with it."""
    if _swap_changed:
        _swap_changed()


def go_to(target: Tuple[str, str]) -> None:
    """Show an item in its tab, as Check Project's Go to does: (kind, id), e.g. ("palette", id)."""
    if _go_to:
        _go_to(target)


def notify_images_changed() -> bool:
    """Image files were reloaded, relinked or edited elsewhere: every cached picture of them is stale. Returns False
    without a main window (the caller then refreshes what it shows itself)."""
    if _images_changed:
        _images_changed()
        return True
    return False
