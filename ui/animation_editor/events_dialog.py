"""Event types of the project: rename, recolour, delete (with how often each is used)."""

from __future__ import annotations

from typing import Optional

import wx

from models import Project
from ui.animation_editor import ops


class EventTypesDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, title="Event Types", size=(440, 420), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.project = project
        self.changed = False
        sizer = wx.BoxSizer(wx.VERTICAL)
        info = wx.StaticText(
            self,
            label="Events mark animation steps for the game (hit windows, sounds, spawns…). "
            "The exporter numbers them in this order (MS_EVENT_<NAME>).",
        )
        info.Wrap(400)
        sizer.Add(info, 0, wx.ALL, 10)
        self.listing = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_EDIT_LABELS)
        self.listing.InsertColumn(0, "Name", width=220)
        self.listing.InsertColumn(1, "Used on", width=90)
        self.listing.InsertColumn(2, "Export id", width=80)
        sizer.Add(self.listing, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_rename = wx.Button(self, label="Rename")
        self.btn_colour = wx.Button(self, label="Colour…")
        self.btn_delete = wx.Button(self, label="Delete")
        for btn in (self.btn_rename, self.btn_colour, self.btn_delete):
            buttons.Add(btn, 0, wx.RIGHT, 6)
        buttons.AddStretchSpacer(1)
        close = wx.Button(self, wx.ID_OK, label="Close")
        buttons.Add(close, 0)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(sizer)

        self.btn_rename.Bind(wx.EVT_BUTTON, lambda e: self._rename())
        self.btn_colour.Bind(wx.EVT_BUTTON, lambda e: self._recolour())
        self.btn_delete.Bind(wx.EVT_BUTTON, lambda e: self._delete())
        self.listing.Bind(wx.EVT_LIST_END_LABEL_EDIT, self._on_rename_done)
        self.listing.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._rename())
        self.listing.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._update_buttons())
        self.listing.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda e: self._update_buttons())
        self._fill()
        self.CenterOnParent()

    def _fill(self, select: Optional[int] = None) -> None:
        self.listing.DeleteAllItems()
        for index, etype in enumerate(self.project.event_types):
            row = self.listing.InsertItem(index, etype.name)
            uses = ops.event_usage(self.project, etype.id)
            self.listing.SetItem(row, 1, f"{uses} step{'s' if uses != 1 else ''}")
            self.listing.SetItem(row, 2, str(index))
            self.listing.SetItemTextColour(row, wx.Colour(*etype.color))
        if select is not None and 0 <= select < self.listing.GetItemCount():
            self.listing.Select(select)
        self._update_buttons()

    def _selected(self) -> int:
        return self.listing.GetFirstSelected()

    def _update_buttons(self) -> None:
        has = self._selected() >= 0
        for btn in (self.btn_rename, self.btn_colour, self.btn_delete):
            btn.Enable(has)

    def _rename(self) -> None:
        index = self._selected()
        if index >= 0:
            self.listing.EditLabel(index)

    def _on_rename_done(self, event: wx.ListEvent) -> None:
        if event.IsEditCancelled():
            return
        index = event.GetIndex()
        name = event.GetLabel().strip()
        if not name or not (0 <= index < len(self.project.event_types)):
            event.Veto()
            return
        clash = ops.event_type_by_name(self.project, name)
        if clash is not None and clash is not self.project.event_types[index]:
            wx.MessageBox(f"An event called '{clash.name}' already exists.", "Rename Event", wx.OK | wx.ICON_INFORMATION, self)
            event.Veto()
            return
        self.project.event_types[index].name = name
        self.changed = True

    def _recolour(self) -> None:
        index = self._selected()
        if index < 0:
            return
        etype = self.project.event_types[index]
        data = wx.ColourData()
        data.SetColour(wx.Colour(*etype.color))
        with wx.ColourDialog(self, data) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                colour = dlg.GetColourData().GetColour()
                etype.color = (colour.Red(), colour.Green(), colour.Blue())
                self.changed = True
                self._fill(index)

    def _delete(self) -> None:
        index = self._selected()
        if index < 0:
            return
        etype = self.project.event_types[index]
        uses = ops.event_usage(self.project, etype.id)
        message = f"Delete the event '{etype.name}'?"
        if uses:
            message += f"\n\nIt is used on {uses} animation step(s); it will be removed from them."
        if wx.MessageBox(message, "Delete Event", wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
            return
        ops.delete_event_type(self.project, etype.id)
        self.changed = True
        self._fill(min(index, len(self.project.event_types) - 1))
