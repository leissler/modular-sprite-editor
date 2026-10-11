"""Tools ▸ Validate Roles and Inspect Compiled Role Tables (hitbox / point roles across frames)."""

from __future__ import annotations

import json

import wx

from models import Project


def validate_roles(parent: wx.Window, project: Project) -> None:
    issues = project.validate_role_uniqueness()
    if not issues:
        wx.MessageBox("No duplicate role keys found.\nEach frame has unique (type, role) pairs.", "Role Validation",
                      wx.OK | wx.ICON_INFORMATION, parent)
        return
    lines = [f"{len(issues)} duplicate role key(s) found:", ""]
    for i, issue in enumerate(issues[:20], start=1):
        lines.append(
            f"{i}. [{issue.get('kind')}] frame='{issue.get('frame_name')}' type='{issue.get('type_id')}' "
            f"role='{issue.get('role')}' count={len(issue.get('item_ids', []))}"
        )
    if len(issues) > 20:
        lines.append(f"... and {len(issues) - 20} more.")
    lines += ["", "Tip: keep each (type, role) unique per frame for O(1) runtime lookup tables."]
    wx.MessageBox("\n".join(lines), "Role Validation", wx.OK | wx.ICON_WARNING, parent)


def inspect_role_tables(parent: wx.Window, project: Project) -> None:
    if not project.animations:
        wx.MessageBox("No animations available.", "Role Table Inspection", wx.OK | wx.ICON_INFORMATION, parent)
        return
    if len(project.animations) == 1:
        anim = project.animations[0]
    else:
        choices = [f"{a.name} [{a.id}] ({len(a.aframes)} steps)" for a in project.animations]
        with wx.SingleChoiceDialog(parent, "Choose an animation to compile role tables for.", "Inspect Role Tables", choices) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            anim = project.animations[dlg.GetSelection()]
    tables = project.compile_animation_role_tables(anim.id)
    if tables is None:
        wx.MessageBox("Could not compile role tables for this animation.", "Role Table Inspection", wx.OK | wx.ICON_WARNING, parent)
        return
    text = json.dumps({"animation_name": anim.name, "animation_id": anim.id, "tables": tables}, indent=2)
    with wx.Dialog(parent, title=f"Role Tables: {anim.name}", size=(920, 640), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER) as dlg:
        sizer = wx.BoxSizer(wx.VERTICAL)
        view = wx.TextCtrl(dlg, value=text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        view.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
        sizer.Add(view, 1, wx.EXPAND | wx.ALL, 8)
        buttons = dlg.CreateSeparatedButtonSizer(wx.OK)
        if buttons:
            sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        dlg.SetSizer(sizer)
        dlg.ShowModal()
