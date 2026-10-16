"""File ▸ Export ▸ SNES (PVSnesLib): bake the project into a PVSnesLib project folder and report what the game gets.

The exporter is examples/snes/tools/export_snes.py, the same code as its command line; the built editor carries it
inside (see the build specs). The dialog offers the SNES's six pairs of sprite sizes with the tiles each needs (the
budget model counts them as the export stores them): every tile stays in video memory, and the two sprite tables hold
512.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import wx

import consoles
from models import Project
from ui.dpi import px
from ui.megadrive_export_dialog import mapping_choices, short_path

RUNTIME_FILES = (os.path.join("src", "modsprite.c"), os.path.join("src", "modsprite_draw.asm"),
                 os.path.join("inc", "modsprite.h"))
SPRITE_TILES = consoles.SNES.sprites.tiles


def load_exporter() -> Any:
    """The SNES exporter module (bundled in builds; from the source tree otherwise)."""
    tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "snes", "tools")
    if os.path.isdir(tools) and tools not in sys.path:
        sys.path.insert(0, tools)
    return importlib.import_module("export_snes")


def has_runtime(folder: str) -> bool:
    """Whether the folder holds the SNES runtime the exported data is for."""
    return all(os.path.exists(os.path.join(folder, path)) for path in RUNTIME_FILES)


def default_setup(project: Project, remembered: str) -> str:
    """The sprite sizes to offer first: the project's when it is made for the SNES, else the last export's, else
    8×8 and 16×16."""
    console, setup = consoles.target(project.console, project.console_setup)
    if console is consoles.SNES:
        return setup.key
    keys = [s.key for s in consoles.SNES.budgets]
    return remembered if remembered in keys else keys[0]


def setup_label(setup: consoles.BudgetSetup, tiles: Optional[int]) -> str:
    """"8×8 and 16×16 (300 of 512 tiles)": the pair of sizes and what the project needs with it."""
    name = setup.name.split(", ", 1)[-1].replace(" sprites", "")
    if tiles is None:
        return name
    if tiles > SPRITE_TILES:
        return f"{name} ({tiles} tiles: too many)"
    return f"{name} ({tiles} of {SPRITE_TILES} tiles)"


class SnesExportDialog(wx.Dialog):
    """Where the data goes (the game's PVSnesLib project folder), which mappings it holds and the two sprite sizes."""

    def __init__(self, parent: Optional[wx.Window], project: Project, folder: str, selector: str, setup_key: str,
                 tiles: Optional[Dict[str, int]] = None):
        super().__init__(parent, title="Export for the SNES (PVSnesLib)", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._choices = mapping_choices(project)
        self._setups = list(consoles.SNES.budgets)
        intro = wx.StaticText(self, label=(
            "The data goes into the game's PVSnesLib project folder: res/ms_chunk_NN.bin (a ROM bank each), "
            "modsprite_chunks.asm, inc/modsprite_data.h, src/modsprite_data.c and modsprite_rom.mk (the ROM size, for "
            "the Makefile). The folder needs the runtime, src/modsprite.c, src/modsprite_draw.asm and "
            "inc/modsprite.h; the SNES demo in the source code has it. Every sprite tile stays in video memory: the "
            "sizes show what each pair needs with every mapping."
        ))
        intro.Wrap(px(560))
        self.folder = wx.DirPickerCtrl(self, path=folder, message="Choose the game's PVSnesLib project folder",
                                       style=wx.DIRP_USE_TEXTCTRL | wx.DIRP_DIR_MUST_EXIST)
        self.folder.SetMinSize((px(560), -1))
        self.mapping = wx.Choice(self, choices=[label for label, _value in self._choices])
        values = [value for _label, value in self._choices]
        self.mapping.SetSelection(values.index(selector) if selector in values else 0)
        self.sizes = wx.Choice(self, choices=[setup_label(s, (tiles or {}).get(s.key)) for s in self._setups])
        keys = [s.key for s in self._setups]
        self.sizes.SetSelection(keys.index(setup_key) if setup_key in keys else 0)
        grid = wx.FlexGridSizer(3, 2, 8, 10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="Folder"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.folder, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Mappings"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.mapping, 0)
        grid.Add(wx.StaticText(self, label="Sprite sizes"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.sizes, 0)
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindowById(wx.ID_OK).SetLabel("Export")
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(intro, 0, wx.EXPAND | wx.ALL, 12)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(sizer)

    def values(self) -> Tuple[str, str, str]:
        """(folder, the exporter's --mapping value, the sprite sizes' setup key)."""
        return (self.folder.GetPath(), self._choices[max(0, self.mapping.GetSelection())][1],
                self._setups[max(0, self.sizes.GetSelection())].key)


def summary_lines(folder: str, summary: dict) -> List[str]:
    steps = summary.get("anim_steps", 0)
    return [
        f"Written to {short_path(folder)}",
        f"{summary.get('animations', 0)} animations ({steps} steps), {summary.get('frames', 0)} frames, "
        f"{summary.get('scenes', 0)} scenes; mappings: {summary.get('mappings', '')}",
        f"{summary.get('setup', '')}: {summary.get('tiles', 0)} of {SPRITE_TILES} sprite tiles, "
        f"{summary.get('data_bytes', 0) / 1024:.0f} KB of data in {summary.get('chunks', 0)} ROM banks "
        f"(a {summary.get('rom_kb', 0)} KB ROM)",
    ]
