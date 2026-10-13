"""The editor's preferences store, and the one-time copy of the settings older versions kept elsewhere.

Up to 0.7 the main window kept its settings (recent files, export folders) in a store named after the editor, while
the view settings (backdrop, budget overlay, screen guide) went to wx's default store, named after the launched
program: "app" when run from source (shared with any other app.py), "ModularSpriteEditor" in the builds. Now every
setting is in the editor's store (``SpriteEditorApp.OnInit`` makes it wx's default), and the entries of the old
default store are copied over once.
"""

from __future__ import annotations

from typing import Optional

import wx

COPIED = "/Preferences/Copied"  # one flag per old store whose entries were copied


def config() -> Optional[wx.ConfigBase]:
    """The preferences store; None while there is no wx.App (widgets used without the editor, tests)."""
    try:
        return wx.Config.Get()
    except RuntimeError:  # wx.PyNoAppError
        return None


def _names(config: wx.ConfigBase, groups: bool) -> list:
    names = []
    more, name, index = config.GetFirstGroup() if groups else config.GetFirstEntry()
    while more:
        names.append(name)
        more, name, index = config.GetNextGroup(index) if groups else config.GetNextEntry(index)
    return names


def copy_missing(source: wx.ConfigBase, target: wx.ConfigBase, path: str = "") -> int:
    """Copy every entry of ``source`` that ``target`` does not have yet, in every group. Returns how many."""
    source.SetPath(path or "/")
    entries, groups = _names(source, groups=False), _names(source, groups=True)
    copied = 0
    for name in entries:
        key = f"{path}/{name}"
        if target.HasEntry(key):
            continue
        kind = source.GetEntryType(name)
        if kind == wx.ConfigBase.Type_Integer:
            target.WriteInt(key, source.ReadInt(name))
        elif kind == wx.ConfigBase.Type_Float:
            target.WriteFloat(key, source.ReadFloat(name))
        elif kind == wx.ConfigBase.Type_Boolean:
            target.WriteBool(key, source.ReadBool(name))
        else:
            target.Write(key, source.Read(name))
        copied += 1
    for group in groups:
        copied += copy_missing(source, target, f"{path}/{group}")
    source.SetPath("/")
    return copied


def adopt_old_store(config: wx.ConfigBase, old: wx.ConfigBase, old_name: str) -> int:
    """Copy the settings of the old default store ``old`` (named ``old_name``) into ``config``, once."""
    flag = f"{COPIED}/{old_name}"
    if config.ReadBool(flag, False):
        return 0
    copied = copy_missing(old, config)
    config.WriteBool(flag, True)
    config.Flush()
    return copied
