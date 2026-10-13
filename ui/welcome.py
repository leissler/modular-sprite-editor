"""The welcome screen, shown before a project is open: new / open, recent projects, the examples and the guide."""

from __future__ import annotations

import os
import sys
from typing import Callable, List, Optional, Tuple

import wx
import wx.adv

from ui.components.inspector_kit import COL_DIM, COL_SECTION

GUIDE_URL = "https://modularsprites.bionic-productions.com/"
FIRST_SPRITE_URL = GUIDE_URL + "start/first-sprite/"
EXAMPLES_GUIDE_URL = GUIDE_URL + "examples/"
DOWNLOAD_URL = "https://github.com/leissler/modular-sprite-editor/releases/latest"
CONFIG_SHOW = "Welcome/ShowAtStart"
LINK_COLOUR = wx.Colour(120, 175, 255)

# (name, what it shows, path in the examples folder)
EXAMPLES: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("Prince of Persia", "small parts, animations, a scene, mappings, hitboxes", ("sgdk", "PoP_WW.json")),
    ("Sonic", "a hand-cut character with many animations", ("sonic", "sonic.json")),
    ("Adventurer", "a sheet of whole sprites to practise on", ("adventurer", "adventurer.json")),
]


def examples_folder() -> Optional[str]:
    """The example projects: the repository's examples/ when run from source, else an examples/ folder next to the
    program (the Windows kit has one; the examples download unpacks to one)."""
    if getattr(sys, "frozen", False):
        program = os.path.dirname(os.path.abspath(sys.executable))
        places = [os.path.join(program, "examples")]
        if program.endswith(os.path.join("Contents", "MacOS")):  # next to the .app on macOS
            places.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(program))), "examples"))
    else:
        places = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")]
    return next((place for place in places if os.path.isfile(os.path.join(place, *EXAMPLES[0][2]))), None)


def example_paths() -> List[Tuple[str, str, str]]:
    """(name, description, project path) of the examples found."""
    folder = examples_folder()
    if not folder:
        return []
    found = [(name, text, os.path.join(folder, *parts)) for name, text, parts in EXAMPLES]
    return [entry for entry in found if os.path.isfile(entry[2])]


def _heading(parent: wx.Window, text: str) -> wx.StaticText:
    label = wx.StaticText(parent, label=text.upper())
    font = label.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    font.SetPointSize(max(8, font.GetPointSize() - 1))
    label.SetFont(font)
    label.SetForegroundColour(COL_SECTION)
    return label


def _short_folder(path: str) -> str:
    folder = os.path.dirname(path)
    home = os.path.expanduser("~")
    return "~" + folder[len(home):] if folder == home or folder.startswith(home + os.sep) else folder


class WelcomePanel(wx.ScrolledWindow):
    """Calls ``on_new()``, ``on_open()``, ``on_open_path(path)``, ``on_shortcuts()`` and ``on_back()``."""

    def __init__(self, parent: wx.Window, version: str):
        super().__init__(parent, style=wx.VSCROLL)
        self.SetScrollRate(0, 12)
        self.on_new: Callable[[], None] = lambda: None
        self.on_open: Callable[[], None] = lambda: None
        self.on_open_path: Callable[[str], None] = lambda path: None
        self.on_shortcuts: Callable[[], None] = lambda: None
        self.on_back: Callable[[], None] = lambda: None
        self.on_show_at_start: Callable[[bool], None] = lambda value: None
        self._version = version

        page = wx.BoxSizer(wx.VERTICAL)
        self.column = wx.BoxSizer(wx.VERTICAL)
        page.AddStretchSpacer(1)
        page.Add(self.column, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 24)
        page.AddStretchSpacer(2)
        self.SetSizer(page)

    def _link(self, parent: wx.Window, label: str, action: Callable[[], None], tip: str = "") -> wx.adv.HyperlinkCtrl:
        link = wx.adv.HyperlinkCtrl(parent, label=label, url="", style=wx.adv.HL_ALIGN_LEFT | wx.BORDER_NONE)
        for colour in (link.SetNormalColour, link.SetHoverColour, link.SetVisitedColour):
            colour(LINK_COLOUR)
        if tip:
            link.SetToolTip(tip)
        link.Bind(wx.adv.EVT_HYPERLINK, lambda e: action())  # no Skip: nothing else opens
        return link

    def refresh(self, recent_files: List[str], can_go_back: bool, show_at_start: bool) -> None:
        """Rebuild the page (recent files and the examples change while the editor runs)."""
        self.Freeze()
        try:
            self.column.Clear(delete_windows=True)
            self._build(recent_files, can_go_back, show_at_start)
            self.Layout()
            self.FitInside()
        finally:
            self.Thaw()

    def _build(self, recent_files: List[str], can_go_back: bool, show_at_start: bool) -> None:
        head = wx.BoxSizer(wx.HORIZONTAL)
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base, "assets", "icon.png")
        if os.path.exists(icon_path):
            image = wx.Image(icon_path).Scale(72, 72, wx.IMAGE_QUALITY_NEAREST)
            head.Add(wx.StaticBitmap(self, bitmap=wx.Bitmap(image)), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 16)
        titles = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label="Modular Sprite Editor")
        font = title.GetFont()
        font.SetPointSize(font.GetPointSize() + 10)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(font)
        titles.Add(title, 0, wx.BOTTOM, 4)
        subtitle = wx.StaticText(self, label=f"Version {self._version}  ·  modular pixel-art sprites for retro consoles")
        subtitle.SetForegroundColour(COL_DIM)
        titles.Add(subtitle, 0)
        head.Add(titles, 0, wx.ALIGN_CENTER_VERTICAL)
        self.column.Add(head, 0, wx.BOTTOM, 28)

        columns = wx.BoxSizer(wx.HORIZONTAL)
        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(_heading(self, "Start"), 0, wx.BOTTOM, 8)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        new = wx.Button(self, label="New Project")
        new.Bind(wx.EVT_BUTTON, lambda e: self.on_new())
        open_ = wx.Button(self, label="Open...")
        open_.Bind(wx.EVT_BUTTON, lambda e: self.on_open())
        buttons.Add(new, 0, wx.RIGHT, 8)
        buttons.Add(open_, 0)
        if can_go_back:
            back = wx.Button(self, label="Back to the Project")
            back.Bind(wx.EVT_BUTTON, lambda e: self.on_back())
            buttons.Add(back, 0, wx.LEFT, 8)
        left.Add(buttons, 0, wx.BOTTOM, 22)
        left.Add(_heading(self, "Recent projects"), 0, wx.BOTTOM, 8)
        recent = [path for path in recent_files if path][:8]
        if not recent:
            none = wx.StaticText(self, label="Projects you open show up here.")
            none.SetForegroundColour(COL_DIM)
            left.Add(none, 0)
        for path in recent:
            entry = wx.BoxSizer(wx.HORIZONTAL)
            exists = os.path.isfile(path)
            if exists:
                link = self._link(self, os.path.basename(path), lambda p=path: self.on_open_path(p), path)
                entry.Add(link, 0, wx.RIGHT, 8)
            else:
                gone = wx.StaticText(self, label=os.path.basename(path))
                gone.SetForegroundColour(COL_DIM)
                gone.SetToolTip(f"Not found: {path}")
                entry.Add(gone, 0, wx.RIGHT, 8)
            where = wx.StaticText(self, label=_short_folder(path) if exists else "(not found)")
            where.SetForegroundColour(COL_DIM)
            entry.Add(where, 0)
            left.Add(entry, 0, wx.BOTTOM, 6)
        columns.Add(left, 1, wx.RIGHT, 48)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(_heading(self, "Example projects"), 0, wx.BOTTOM, 8)
        examples = example_paths()
        for name, text, path in examples:
            entry = wx.BoxSizer(wx.VERTICAL)
            entry.Add(self._link(self, name, lambda p=path: self.on_open_path(p), path), 0)
            about = wx.StaticText(self, label=text)
            about.SetForegroundColour(COL_DIM)
            entry.Add(about, 0)
            right.Add(entry, 0, wx.BOTTOM, 8)
        if not examples:
            right.Add(self._link(self, "Download the example projects", lambda: wx.LaunchDefaultBrowser(DOWNLOAD_URL),
                                 "ModularSpriteEditor-examples.zip on the release page; unpack it next to the editor"),
                      0, wx.BOTTOM, 4)
        right.Add(self._link(self, "What each example shows", lambda: wx.LaunchDefaultBrowser(EXAMPLES_GUIDE_URL)),
                  0, wx.BOTTOM, 22)
        right.Add(_heading(self, "Learn"), 0, wx.BOTTOM, 8)
        for label, action in (
            ("User guide", lambda: wx.LaunchDefaultBrowser(GUIDE_URL)),
            ("Your first animated sprite", lambda: wx.LaunchDefaultBrowser(FIRST_SPRITE_URL)),
            ("Keyboard and mouse shortcuts", lambda: self.on_shortcuts()),
        ):
            right.Add(self._link(self, label, action), 0, wx.BOTTOM, 6)
        columns.Add(right, 0)
        self.column.Add(columns, 0, wx.EXPAND | wx.BOTTOM, 28)

        self.show_at_start = wx.CheckBox(self, label="Show this when the editor starts")
        self.show_at_start.SetValue(show_at_start)
        self.show_at_start.Bind(wx.EVT_CHECKBOX, lambda e: self.on_show_at_start(e.IsChecked()))
        self.column.Add(self.show_at_start, 0)
