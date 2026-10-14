"""Splitters that remember where the user dragged them (the preferences keep the bottom pane's height)."""

from __future__ import annotations

import wx

from ui import dpi
from ui.preferences import config


def split_bottom_remembered(splitter: wx.SplitterWindow, top: wx.Window, bottom: wx.Window, key: str,
                            default: int) -> None:
    """Split with ``bottom`` as tall as the user dragged it last time (``default`` at first, pixels at 100 %), and keep
    the preferences up to date when they drag the sash again."""
    store = config()
    height = store.ReadInt(key, default) if store is not None else default
    height = max(1, height)
    splitter.SplitHorizontally(top, bottom, -dpi.px(height))

    def dragged(event: wx.SplitterEvent) -> None:
        event.Skip()
        if event.GetEventObject() is not splitter:  # the splitters inside it report their sashes here too
            return
        target = config()
        shown = splitter.GetWindow2()
        if target is not None and shown is not None:
            target.WriteInt(key, max(1, round(shown.GetSize().height / dpi.SCALE)))

    splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, dragged)
