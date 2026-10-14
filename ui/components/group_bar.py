"""The group filter and sort order above a long list (frames, animations); the rules are in ui/grouping.py."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence

import wx

from ui import grouping
from ui.dpi import px


class GroupBar(wx.Panel):
    """Two choices in a row: which group the list shows, and its order. ``on_change`` runs when either changes."""

    def __init__(self, parent: wx.Window, on_change: Callable[[], None], what: str = "items"):
        super().__init__(parent)
        self.on_change = on_change
        self._groups: List[Optional[str]] = [grouping.ALL]
        self.group_choice = wx.Choice(self, choices=["All groups"])
        self.group_choice.SetSelection(0)
        self.group_choice.SetToolTip(f"Show the {what} of one group. Give {what} a group in the inspector or the "
                                     "list's menu (right-click).")
        self.sort_choice = wx.Choice(self, choices=[label for label, _key in grouping.SORTS])
        self.sort_choice.SetSelection(0)
        self.sort_choice.SetToolTip("Order of the list: the project's (drag to reorder), by name, or by group")
        for choice in (self.group_choice, self.sort_choice):
            choice.SetMinSize((px(60), -1))  # both share the column's width
            choice.Bind(wx.EVT_CHOICE, lambda e: self.on_change())
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.group_choice, 3, wx.RIGHT, 4)
        sizer.Add(self.sort_choice, 2)
        self.SetSizer(sizer)

    def set_groups(self, items: Sequence[Any]) -> None:
        """The groups the items use (the filter stays on its group while that exists)."""
        current = self.group()
        groups = grouping.groups_of(items)
        ungrouped = sum(1 for item in items if not item.group)
        self._groups = [grouping.ALL] + [name for name, _count in groups] + ([""] if groups and ungrouped else [])
        labels = ["All groups"] + [f"{name} ({count})" for name, count in groups]
        if groups and ungrouped:
            labels.append(f"No group ({ungrouped})")
        if labels != list(self.group_choice.GetItems()):
            self.group_choice.SetItems(labels)
        self.group_choice.SetSelection(self._groups.index(current) if current in self._groups else 0)
        self.group_choice.Enable(bool(groups))

    def group(self) -> Optional[str]:
        index = self.group_choice.GetSelection()
        return self._groups[index] if 0 <= index < len(self._groups) else grouping.ALL

    def set_group(self, group: Optional[str]) -> None:
        if group in self._groups:
            self.group_choice.SetSelection(self._groups.index(group))

    def sort(self) -> str:
        return grouping.SORTS[max(0, self.sort_choice.GetSelection())][1]

    def set_sort(self, key: str) -> None:
        keys = [k for _label, k in grouping.SORTS]
        if key in keys:
            self.sort_choice.SetSelection(keys.index(key))

    def state(self) -> dict:
        """For the per-project view state (ui/view_memory.py)."""
        return {"group": self.group(), "sort": self.sort()}

    def restore(self, state: dict) -> None:
        group = state.get("group")
        if group is None or isinstance(group, str):
            self.set_group(group)
        if isinstance(state.get("sort"), str):
            self.set_sort(state["sort"])


def group_menu(parent: wx.Window, menu: wx.Menu, items: Sequence[Any], current: str,
               on_group: Callable[[str], None]) -> None:
    """A "Group" submenu: the groups in use, New Group… and No Group; ``on_group`` gets the chosen name."""
    sub = wx.Menu()
    for name, _count in grouping.groups_of(items):
        entry = sub.AppendRadioItem(wx.ID_ANY, name.replace("&", "&&"))
        entry.Check(name == current)
        parent.Bind(wx.EVT_MENU, lambda e, n=name: on_group(n), entry)
    if sub.GetMenuItemCount():
        sub.AppendSeparator()
    new = sub.Append(wx.ID_ANY, "New Group…")
    parent.Bind(wx.EVT_MENU, lambda e: _ask_new_group(parent, on_group), new)
    none = sub.Append(wx.ID_ANY, "No Group")
    none.Enable(bool(current))
    parent.Bind(wx.EVT_MENU, lambda e: on_group(""), none)
    menu.AppendSubMenu(sub, "Group")


def _ask_new_group(parent: wx.Window, on_group: Callable[[str], None]) -> None:
    with wx.TextEntryDialog(parent, "Name of the new group:", "New Group") as dialog:
        if dialog.ShowModal() == wx.ID_OK and grouping.clean_name(dialog.GetValue()):
            on_group(grouping.clean_name(dialog.GetValue()))
