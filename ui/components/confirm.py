"""Confirming a delete that other things still use: remove those uses too, keep them as missing, or cancel."""

from __future__ import annotations

from typing import Optional

import wx

REMOVE, KEEP = "remove", "keep"


def ask_remove_uses(parent: Optional[wx.Window], title: str, message: str, remove_label: str,
                    keep_label: str = "Keep as Missing") -> Optional[str]:
    """REMOVE, KEEP or None when cancelled. Tests replace this function to answer without a dialog."""
    dlg = wx.MessageDialog(parent, message, title, wx.YES_NO | wx.CANCEL | wx.ICON_WARNING)
    dlg.SetYesNoCancelLabels(remove_label, keep_label, "Cancel")
    result = dlg.ShowModal()
    dlg.Destroy()
    return {wx.ID_YES: REMOVE, wx.ID_NO: KEEP}.get(result)
