"""File ▸ Export ▸ Sprite Sheet: which animations, which format (JSON / Godot / Unity), padding and scale; the
exporter is exporters/sheet.py."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import wx

from models import Animation, Project
from ui import grouping
from ui.components.inspector_kit import dim_text
from ui.dpi import px
from ui.preferences import config

FORMAT_CHOICES: List[Tuple[str, str]] = [
    ("JSON (Aseprite / TexturePacker layout)", "json"),
    ("Godot 4 SpriteFrames (.tres)", "godot"),
    ("Unity sprites (.png.meta)", "unity"),
]
CONFIG_KEY = "SheetExport/{}"


class SheetExportDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, project: Project, selected_animation: Optional[str], drawn_with: str):
        super().__init__(parent, title="Export Sprite Sheet")
        self.project = project
        self.selected_animation = selected_animation
        cfg = config()
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label="Every step of the animations, drawn as in the Animations tab, packed into "
                                          "one PNG with the data an engine reads.")
        intro.Wrap(px(440))
        root.Add(intro, 0, wx.ALL, 12)
        grid = wx.FlexGridSizer(0, 2, 8, 10)

        self.format = wx.Choice(self, choices=[label for label, _key in FORMAT_CHOICES])
        keys = [key for _label, key in FORMAT_CHOICES]
        stored = cfg.Read(CONFIG_KEY.format("Format"), "json") if cfg else "json"
        self.format.SetSelection(keys.index(stored) if stored in keys else 0)
        self.format.SetToolTip(
            "JSON: frames, durations and tags in the layout Aseprite and TexturePacker write, which Phaser, LÖVE, "
            "Defold, GameMaker and many engines' importers read (this editor's Import too).\n"
            "Godot 4: a SpriteFrames resource for AnimatedSprite2D (keep it next to the PNG in the Godot project).\n"
            "Unity: the PNG's import settings, the sheet cut into sprites with their pivots on the origin.")
        grid.Add(wx.StaticText(self, label="Format"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.format, 0, wx.EXPAND)

        self._scopes: List[Tuple[str, Optional[str]]] = [("All animations", None)]
        if selected_animation and project.get_animation(selected_animation):
            self._scopes.append((f"The selected animation ({project.get_animation(selected_animation).name})", "@selected"))
        for name, count in grouping.groups_of(project.animations):
            self._scopes.append((f"The group {name} ({count})", name))
        self.scope = wx.Choice(self, choices=[label for label, _key in self._scopes])
        self.scope.SetSelection(0)
        grid.Add(wx.StaticText(self, label="Animations"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.scope, 0, wx.EXPAND)

        self.loose = wx.CheckBox(self, label="Also the frames no animation shows")
        grid.Add((0, 0))
        grid.Add(self.loose, 0)

        sizes = wx.BoxSizer(wx.HORIZONTAL)
        self.padding = wx.SpinCtrl(self, min=0, max=16, initial=cfg.ReadInt(CONFIG_KEY.format("Padding"), 1) if cfg else 1,
                                   size=(px(56), -1))
        self.padding.SetToolTip("Clear pixels between the pictures (1 keeps engines from bleeding neighbours in)")
        self.scale = wx.SpinCtrl(self, min=1, max=8, initial=cfg.ReadInt(CONFIG_KEY.format("Scale"), 1) if cfg else 1,
                                 size=(px(56), -1))
        self.scale.SetToolTip("Every pixel this many times as wide and high (nearest neighbour)")
        sizes.Add(self.padding, 0, wx.ALIGN_CENTER_VERTICAL)
        sizes.Add(wx.StaticText(self, label="px padding"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        sizes.Add(self.scale, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        sizes.Add(wx.StaticText(self, label="× scale"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        grid.Add(wx.StaticText(self, label="Pixels"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(sizes, 0)
        root.Add(grid, 0, wx.LEFT | wx.RIGHT, 12)

        note = dim_text(self, f"Drawn with {drawn_with}, as chosen above the tabs. The data file goes next to "
                              "the PNG; identical pictures are stored once.")
        note.Wrap(px(440))
        root.Add(note, 0, wx.ALL, 12)
        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            root.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        ok = self.FindWindowById(wx.ID_OK)
        if ok:
            ok.SetLabel("Export…")
        self.SetSizerAndFit(root)
        self.CenterOnParent()

    def fmt(self) -> str:
        return FORMAT_CHOICES[max(0, self.format.GetSelection())][1]

    def animations(self) -> List[Animation]:
        _label, key = self._scopes[max(0, self.scope.GetSelection())]
        if key is None:
            return list(self.project.animations)
        if key == "@selected":
            anim = self.project.get_animation(self.selected_animation or "")
            return [anim] if anim else []
        return [a for a in self.project.animations if a.group == key]

    def options(self) -> Dict[str, Any]:
        """Keyword arguments for exporters.sheet.export_sheet (remembered for next time)."""
        cfg = config()
        if cfg:
            cfg.Write(CONFIG_KEY.format("Format"), self.fmt())
            cfg.WriteInt(CONFIG_KEY.format("Padding"), self.padding.GetValue())
            cfg.WriteInt(CONFIG_KEY.format("Scale"), self.scale.GetValue())
            cfg.Flush()
        return {"fmt": self.fmt(), "animations": self.animations(), "loose_frames": self.loose.GetValue(),
                "padding": self.padding.GetValue(), "scale": self.scale.GetValue()}
