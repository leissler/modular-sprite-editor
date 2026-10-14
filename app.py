"""Main entry point for the modular sprite editor built with wxPython."""

from __future__ import annotations

import ctypes
import ctypes.util
import functools
import hashlib
import importlib
import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import wx
import wx.lib.agw.flatnotebook as fnb

import consoles
import palettes
from models import FModule, Project, generate_id
from ui import app_services, autosave, preferences, view_memory
from ui.animation_editor import ops as anim_ops
from ui.animation_editor.panel import AnimationEditorPanel
from ui.base_canvas import SCROLL
from ui.components.canvas_display_controls import set_shared_backdrop_colour, shared_backdrop_colour
from ui.canvas import BUDGET
import project_check
from ui.check_dialog import CheckProjectDialog
from ui.console_colours import CONSOLE
from ui.components.module_palette import THUMBNAILS
from ui.frame_render import SHARED
from ui.image_watch import Stamp, changed_images, image_stamp, image_stamps, update_image_sizes
from ui.frame_editor.panel import FrameEditorPanel
from ui.mapping_editor.panel import MappingEditorPanel
from ui.palette_editor.panel import PaletteEditorPanel
from ui.module_editor.panel import ModuleEditorPanel
from ui.preferences_dialog import PreferencesDialog
from ui.project_history import ProjectHistory
from ui.refresh_rate import REFRESH
from ui.sheet_export_dialog import SheetExportDialog
from ui.shortcuts_dialog import MOD, ShortcutsDialog
from ui.scene_editor.panel import SceneEditorPanel
from ui.sgdk_export_dialog import ID_CHECK_PROJECT, ExportReportDialog, MegaDriveExportDialog, has_runtime, load_exporter
from ui.welcome import CONFIG_SHOW, DOWNLOAD_URL, EXAMPLES_GUIDE_URL, GUIDE_URL, WelcomePanel, example_paths
from ui.dpi import px

APP_NAME = "Modular Sprite Editor"
# The release this is: the About box shows it, and the Build And Release workflow stops if it releases another.
APP_VERSION = "0.9"
TAB_NAMES = ["Modules", "Frames", "Animations", "Timeline", "Mappings", "Palettes"]
CONFIG_WINDOW = "Window/Geometry"  # "x,y,width,height" when the editor last closed
CONFIG_WINDOW_MAXIMIZED = "Window/Maximized"
CONFIG_NEW_TICK_RATE = "Animations/NewTickRate"  # Preferences ▸ New animations
CONFIG_AUTOSAVE_SECONDS = "Autosave/Seconds"  # Preferences ▸ Safety
DEFAULT_WINDOW = (1500, 980)

# Shown in the status bar when a tab is activated.
TAB_HINTS = {
    "Modules": "Drag on the image: new module  •  Drag a module: move  •  Shift+drag: pivot  •  Cmd+drag: select several  •  Arrows: nudge",
    "Frames": "Drag parts from the library  •  Drag empty space: select several  •  Arrows: nudge (Shift = 8 px)  •  H/V: flip  •  R: rotate",
    "Animations": "Drag frames into the sequence  •  Enter: play  •  , / .: step  •  [ / ]: hold  •  Drag a step's right edge: hold  •  Drag the stage: offset",
    "Timeline": "Drag from the Library onto the stage  •  Enter: play  •  , / .: step  •  K: key  •  Auto-Key edits set keys at the playhead",
    "Mappings": "Select modules, then click a replacement on the right (or drag it onto a row)  •  Delete: original  •  H: hide",
}

CHECKPOINT_INTERVAL_MS = 700
CHECKPOINT_FALLBACK_TICKS = 15  # without input, look for changes about every 10 s anyway (never while playing)
# Events from the user that can change the project: the next undo checkpoint looks for changes after them.
INPUT_EVENTS = frozenset((
    wx.wxEVT_LEFT_UP, wx.wxEVT_RIGHT_UP, wx.wxEVT_MIDDLE_UP, wx.wxEVT_KEY_UP, wx.wxEVT_KILL_FOCUS,
    wx.wxEVT_MENU, wx.wxEVT_BUTTON, wx.wxEVT_CHECKBOX, wx.wxEVT_CHOICE, wx.wxEVT_COMBOBOX, wx.wxEVT_RADIOBUTTON,
    wx.wxEVT_SLIDER, wx.wxEVT_SPINCTRL, wx.wxEVT_SPINCTRLDOUBLE, wx.wxEVT_TEXT_ENTER, wx.wxEVT_COLOURPICKER_CHANGED,
    wx.wxEVT_LIST_END_LABEL_EDIT, wx.wxEVT_DROP_FILES,
))


def _mac_force_app_menu_title(title: str) -> None:
    """macOS-only: override the application menu title when running under Python."""
    if sys.platform != "darwin":
        return

    try:
        objc_path = ctypes.util.find_library("objc")
        if not objc_path:
            return

        objc = ctypes.cdll.LoadLibrary(objc_path)
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def cls(name: str) -> ctypes.c_void_p:
            return objc.objc_getClass(name.encode("utf-8"))

        def sel(name: str) -> ctypes.c_void_p:
            return objc.sel_registerName(name.encode("utf-8"))

        # Create small helpers with concrete signatures to avoid ctypes restype errors.
        msg = objc.objc_msgSend
        msg.restype = ctypes.c_void_p
        msg.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        msg_ccharp = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)(("objc_msgSend", objc))
        msg_long = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(("objc_msgSend", objc))
        msg_void = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))

        ns_app = msg(cls("NSApplication"), sel("sharedApplication"))
        if not ns_app:
            return

        main_menu = msg(ns_app, sel("mainMenu"))
        if not main_menu:
            return

        first_item = msg_long(main_menu, sel("itemAtIndex:"), 0)
        if not first_item:
            return

        ns_title = msg_ccharp(cls("NSString"), sel("stringWithUTF8String:"), title.encode("utf-8"))
        if not ns_title:
            return

        msg_void(first_item, sel("setTitle:"), ns_title)
    except (OSError, AttributeError, ctypes.ArgumentError):
        pass  # the menu keeps the default title


def _focus_is_text_entry() -> Optional[wx.Window]:
    """Return the focused text-entry widget (so Edit commands can go to it), else None."""
    return wx.Window.FindFocus() if app_services.text_entry_has_focus() else None


def tab_height(page_container: wx.Window) -> int:
    """The height of the main tabs (FlatNotebook, Windows): the bold label in the tab row's own DC plus the spacer."""
    dc = wx.ClientDC(page_container)
    font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    dc.SetFont(font)
    return dc.GetCharHeight() + px(fnb.FNB_HEIGHT_SPACER)


def measure_tabs_on_screen() -> None:
    """FlatNotebook measures its labels in a memory DC, which Windows gives 96 dpi while the tabs are drawn at the
    display's: with display scaling the labels came out wider and taller than their tabs. Measure them where they are
    drawn."""

    def calc_tab_height(renderer, page_container):  # FNBRenderer.CalcTabHeight
        if not renderer._tabHeight:
            renderer._tabHeight = tab_height(page_container)
        return renderer._tabHeight

    def calc_tab_width(renderer, page_container, index, height):  # FNBRendererVC8.CalcTabWidth (no images, no 'x')
        dc = wx.ClientDC(page_container)
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font.SetWeight(wx.FONTWEIGHT_BOLD)  # the selected tab's label is bold: no tab grows when selected
        dc.SetFont(font)
        width = max(px(20), dc.GetTextExtent(page_container.GetPageText(index))[0])
        padding = page_container._pParent.GetPadding()
        # VC8 starts a label after the tab's slanted edge, which grows with the tab's height, while the next tab starts
        # only a fixed gap further on: make room for the part of the edge that the padding and that gap don't cover.
        edge = height - fnb.VERTICAL_BORDER_PADDING - 2
        return 2 * padding + width + max(0, edge - padding - fnb.FNB_HEIGHT_SPACER)

    fnb.FNBRenderer.CalcTabHeight = calc_tab_height
    fnb.FNBRendererVC8.CalcTabWidth = calc_tab_width


class ContextBar(wx.Panel):
    """Slim bar above the editor tabs showing state that affects every tab."""

    def __init__(self, parent: wx.Window, on_mapping_selected: Callable[[Optional[str]], None],
                 on_swap_selected: Callable[[Optional[str]], None]):
        super().__init__(parent)
        self._on_mapping_selected = on_mapping_selected
        self._on_swap_selected = on_swap_selected
        self._mapping_ids: List[Optional[str]] = [None]
        self._swap_ids: List[Optional[str]] = [None]

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddStretchSpacer(1)
        label = wx.StaticText(self, label="Preview mapping:")
        label.SetToolTip("Module mapping applied to every preview and used by exports. Edit mappings in the Mappings tab.")
        self.mapping_choice = wx.Choice(self, choices=["<none>"])
        self.mapping_choice.SetSelection(0)
        self.mapping_choice.SetMinSize((px(180), -1))
        sizer.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        sizer.Add(self.mapping_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        swap_label = wx.StaticText(self, label="Palette swap:")
        swap_label.SetToolTip("Palette swap every preview draws with, and the GIF, sprite sheet and RetroAnimator exports. "
                              "Edit swaps in the Palettes tab.")
        self.swap_choice = wx.Choice(self, choices=["Original"])
        self.swap_choice.SetSelection(0)
        self.swap_choice.SetMinSize((px(150), -1))
        sizer.Add(swap_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        sizer.Add(self.swap_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        self.SetSizer(sizer)
        self.mapping_choice.Bind(wx.EVT_CHOICE, self._on_choice)
        self.swap_choice.Bind(wx.EVT_CHOICE, self._on_swap_choice)

    def set_mappings(self, project: Project) -> None:
        self._mapping_ids = [None] + [m.id for m in project.mappings]
        self.mapping_choice.SetItems(["<none>"] + [m.name for m in project.mappings])
        active_id = project.active_mapping.id if project.active_mapping else None
        self.mapping_choice.SetSelection(self._mapping_ids.index(active_id) if active_id in self._mapping_ids else 0)

    def _on_choice(self, _event: wx.CommandEvent) -> None:
        idx = self.mapping_choice.GetSelection()
        if 0 <= idx < len(self._mapping_ids):
            self._on_mapping_selected(self._mapping_ids[idx])

    def set_swaps(self, project: Project) -> None:
        self._swap_ids = [None] + [s.id for s in project.palette_swaps]
        self.swap_choice.SetItems(["Original"] + [s.name for s in project.palette_swaps])
        active_id = project.active_palette_swap.id if project.active_palette_swap else None
        self.swap_choice.SetSelection(self._swap_ids.index(active_id) if active_id in self._swap_ids else 0)

    def _on_swap_choice(self, _event: wx.CommandEvent) -> None:
        idx = self.swap_choice.GetSelection()
        if 0 <= idx < len(self._swap_ids):
            self._on_swap_selected(self._swap_ids[idx])


class MainFrame(wx.Frame):
    def __init__(self, parent=None, title=APP_NAME):
        super().__init__(parent, title=title, size=(px(DEFAULT_WINDOW[0]), px(DEFAULT_WINDOW[1])))

        self.project = Project()
        self.current_path: Optional[str] = None
        self.history = ProjectHistory()
        self._last_dirty_state: Optional[bool] = None

        # Preferences and Recent Files (Custom MRU): the one store SpriteEditorApp.OnInit sets up (tests use a file)
        self.config = wx.Config.Get()
        anim_ops.set_new_tick_rate(self.config.ReadInt(CONFIG_NEW_TICK_RATE, anim_ops.DEFAULT_TICK_RATE))
        self.recent_files: list[str] = []
        self._load_recent_files()

        self._build_menu()

        # Icon setup
        if os.path.exists(resource_path('assets/icon.png')):
            self.SetIcon(wx.Icon(resource_path('assets/icon.png')))

        self.status_bar = self.CreateStatusBar(2)
        self.status_bar.SetStatusWidths([-1, 120])

        root = wx.Panel(self)
        self.context_bar = ContextBar(root, self.on_preview_mapping_selected, self.on_preview_swap_selected)

        if sys.platform == "win32":
            # Windows: Use FlatNotebook (VC8 style) but DEFAULT colors
            style = fnb.FNB_VC8 | fnb.FNB_NO_X_BUTTON | fnb.FNB_NO_NAV_BUTTONS | fnb.FNB_NO_TAB_FOCUS | fnb.FNB_TABS_BORDER_SIMPLE
            measure_tabs_on_screen()
            self.book = fnb.FlatNotebook(root, agwStyle=style)  # the FNB_ flags are agwStyle (style= is the panel's)
            self.book.SetPadding(wx.Size(px(6), 0))
            tabs = self.book.GetTabArea()
            tabs.SetSizeHints(-1, tab_height(tabs))
        else:
            self.book = wx.Notebook(root)

        self.module_editor = ModuleEditorPanel(self.book, self.project)
        self.frame_editor = FrameEditorPanel(self.book, self.project)
        self.animation_editor = AnimationEditorPanel(self.book, self.project)
        self.timeline_editor = SceneEditorPanel(self.book, self.project)
        self.mapping_editor = MappingEditorPanel(self.book, self.project)
        self.palette_editor = PaletteEditorPanel(self.book, self.project)
        self.panels = [
            self.module_editor,
            self.frame_editor,
            self.animation_editor,
            self.timeline_editor,
            self.mapping_editor,
            self.palette_editor,
        ]

        pad = "  " if sys.platform == "win32" else ""
        for idx, (panel, name) in enumerate(zip(self.panels, TAB_NAMES)):
            self.book.AddPage(panel, f"{pad}{name}{pad}", select=(idx == 0))

        # Before a project is open the welcome screen takes the tabs' place.
        self.welcome = WelcomePanel(root, APP_VERSION)
        self.welcome.on_new = lambda: self.on_new(None)
        self.welcome.on_open = lambda: self.on_open(None)
        self.welcome.on_open_path = self.open_path
        self.welcome.on_shortcuts = lambda: self.on_shortcuts(None)
        self.welcome.on_back = lambda: self.show_welcome(False)
        self.welcome.on_show_at_start = self._set_welcome_at_start
        self.welcome.Hide()

        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(self.context_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        root_sizer.Add(self.book, 1, wx.EXPAND)
        root_sizer.Add(self.welcome, 1, wx.EXPAND)
        root.SetSizer(root_sizer)

        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(root, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        if sys.platform == "win32":
            self.book.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CHANGED, self.on_page_changed)
            self.book.Bind(fnb.EVT_FLATNOTEBOOK_PAGE_CLOSING, self.on_page_closing)
        else:
            self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_page_changed)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.animation_editor.on_edit_frame = self.switch_to_frame_editor
        self.module_editor.on_open_frame = self.switch_to_frame_editor
        self.module_editor.on_open_animation = self.switch_to_animation
        self.frame_editor.on_open_module = self.switch_to_module
        self.mapping_editor.on_open_module = self.switch_to_module

        app_services.install(
            checkpoint=self.history_checkpoint,
            status=self.set_status,
            zoom=self.set_zoom_status,
            mapping_changed=self.sync_mapping_controls,
            images_changed=self.images_changed,
            revision=lambda: self.history.fingerprint,
            swap_changed=self.sync_palette_swap_controls,
            go_to=self.go_to,
        )

        self.history.reset(self.project)
        self.context_bar.set_mappings(self.project)
        self.context_bar.set_swaps(self.project)
        # Serialising the project for a checkpoint costs milliseconds (tens in big projects), so the timer only
        # looks after user input (note_input), and now and then in case something else changed it.
        self._input_seen = False
        self._quiet_ticks = 0
        self._checkpoint_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_checkpoint_timer, self._checkpoint_timer)
        self._checkpoint_timer.Start(CHECKPOINT_INTERVAL_MS)

        # Images edited in another program reload when the window becomes active again.
        self._image_stamps: Dict[str, Stamp] = image_stamps(self.project)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

        # Unsaved changes are copied to the recovery folder, so a crash does not lose them (ui/autosave.py).
        self._session_key = f"{os.getpid()}-{int(time.time())}"
        self._recovery_file: Optional[str] = None
        self._autosaved_fingerprint: Optional[str] = None
        self._autosave_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_autosave_timer, self._autosave_timer)
        self._autosave_timer.Start(self._autosave_ms())
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

        self._update_title()
        self._show_tab_hint()
        self._restore_geometry()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        """A wx.Timer outlives the window it reports to and crashes the process when it fires after the window is
        gone. Closing the window stops them (on_close); this stops them however the window goes (scripts and tests
        that destroy it directly)."""
        event.Skip()
        if event.GetEventObject() is not self:
            return
        self._checkpoint_timer.Stop()
        self._autosave_timer.Stop()
        for panel in self.panels:
            timer = getattr(panel, "timer", None)  # the Animations and Timeline playback timers
            if isinstance(timer, wx.Timer):
                timer.Stop()

    # ------------------------------------------------------------------ window geometry
    def _restore_geometry(self) -> None:
        """Where and how large the window was last time, if its title bar is still on a screen; else a size that
        fits the screen it opens on (laptops have less room than the default)."""
        try:
            x, y, w, h = (int(v) for v in self.config.Read(CONFIG_WINDOW, "").split(","))
        except ValueError:
            x = y = w = h = None
        screen = wx.Display.GetFromPoint(wx.Point(x + 60, y + 12)) if x is not None else wx.NOT_FOUND
        if screen != wx.NOT_FOUND:
            area = wx.Display(screen).GetClientArea()
            w, h = min(max(w, px(800)), area.width), min(max(h, px(560)), area.height)
            self.SetSize(max(area.x, min(x, area.Right - w + 1)), max(area.y, min(y, area.Bottom - h + 1)), w, h)
            if self.config.ReadBool(CONFIG_WINDOW_MAXIMIZED, False):
                self.Maximize()
            return
        screen = wx.Display.GetFromWindow(self)
        area = wx.Display(screen if screen != wx.NOT_FOUND else 0).GetClientArea()
        self.SetSize(min(px(DEFAULT_WINDOW[0]), area.width - px(40)), min(px(DEFAULT_WINDOW[1]), area.height - px(40)))
        self.CentreOnScreen()

    def _save_geometry(self) -> None:
        if self.IsIconized() or self.IsFullScreen():
            return
        self.config.WriteBool(CONFIG_WINDOW_MAXIMIZED, self.IsMaximized())
        if not self.IsMaximized():
            rect = self.GetRect()
            self.config.Write(CONFIG_WINDOW, f"{rect.x},{rect.y},{rect.width},{rect.height}")
        self.config.Flush()

    # ------------------------------------------------------------------ status / title
    def set_status(self, message: str) -> None:
        self.status_bar.SetStatusText(message, 0)

    def set_zoom_status(self, zoom: float) -> None:
        # Fractional values only show while a smooth zoom gesture is running.
        text = f"{zoom:.0f}" if abs(zoom - round(zoom)) < 1e-6 else f"{zoom:.2f}".rstrip("0").rstrip(".")
        self.status_bar.SetStatusText(f"Zoom {text}×", 1)

    def _current_tab_name(self) -> str:
        idx = self.book.GetSelection()
        return TAB_NAMES[idx] if 0 <= idx < len(TAB_NAMES) else "Unknown"

    def _show_tab_hint(self) -> None:
        self.set_status(TAB_HINTS.get(self._current_tab_name(), ""))

    def _update_title(self) -> None:
        fname = os.path.basename(self.current_path) if self.current_path else "New Project"
        dirty = self.history.is_dirty()
        marker = "*" if dirty else ""
        welcome = hasattr(self, "welcome") and self.welcome.IsShown()
        self.SetTitle(APP_NAME if welcome else f"{APP_NAME} - {fname}{marker} - [{self._current_tab_name()}]")
        if sys.platform == "darwin":
            # Native "edited" dot in the macOS close button.
            try:
                self.OSXSetModified(dirty)
            except AttributeError:
                pass
        self._last_dirty_state = dirty

    # ------------------------------------------------------------------ history
    def history_checkpoint(self) -> None:
        before = self.history.fingerprint
        self.history.checkpoint(self.project)
        if self.history.is_dirty() != self._last_dirty_state:
            self._update_title()
        if self.history.fingerprint != before:
            canvas = self._active_budget_canvas()
            if canvas is not None:
                canvas.Refresh(False)  # its readout shows the whole project's tiles, worked out per checkpoint

    def _active_budget_canvas(self) -> Optional[wx.Window]:
        canvas = self._active_canvas()
        return canvas if getattr(canvas, "budget_profile", None) is not None else None

    def note_input(self) -> None:
        """The user did something that can change the project (SpriteEditorApp.FilterEvent sees every event)."""
        self._input_seen = True

    def is_playing(self) -> bool:
        return any(getattr(panel, "is_playing", False) for panel in self.panels)

    def _on_checkpoint_timer(self, _event: wx.TimerEvent) -> None:
        mouse = wx.GetMouseState()
        if mouse.LeftIsDown() or mouse.MiddleIsDown() or mouse.RightIsDown():
            return  # never split a drag into several undo steps
        if self.is_playing():
            return  # playback changes nothing: anything the user did meanwhile is looked at once it stops
        self._quiet_ticks += 1
        if not self._input_seen and self._quiet_ticks < CHECKPOINT_FALLBACK_TICKS:
            return  # nothing the user did: idle time changes nothing
        self._input_seen = False
        self._quiet_ticks = 0
        self.history_checkpoint()
        self._remember_new_images()

    # ------------------------------------------------------------------ images changed on disk
    def _remember_new_images(self) -> None:
        """Note the file state of images added since the last look, so a later edit elsewhere counts as a change."""
        for asset in self.project.images:
            if asset.id not in self._image_stamps:
                self._image_stamps[asset.id] = image_stamp(asset.file_path)

    def set_scroll_moves(self, moves: bool) -> None:
        """View ▸ Scroll Moves the View (kept in the preferences)."""
        SCROLL.set(moves)
        self.m_scroll_moves.Check(moves)
        self.set_status(f"Scrolling moves the view; pinch or {MOD}+scroll zooms" if moves
                        else "Scrolling zooms; Shift / Alt + scroll moves the view")

    # ------------------------------------------------------------------ preferences
    def _autosave_ms(self) -> int:
        seconds = self.config.ReadInt(CONFIG_AUTOSAVE_SECONDS, autosave.AUTOSAVE_INTERVAL_MS // 1000)
        return max(5, seconds) * 1000

    def preference_values(self) -> Dict[str, Any]:
        """What the Preferences window shows, read from where each setting lives."""
        return {
            "scroll_moves": SCROLL.moves,
            "play_50hz": REFRESH.pal,
            "backdrop_colour": shared_backdrop_colour(),
            "tick_rate": anim_ops.new_tick_rate(),
            "autosave_seconds": self._autosave_ms() // 1000,
            "welcome": self.config.ReadBool(CONFIG_SHOW, True),
            "recent_count": len(self.recent_files),
        }

    def apply_preferences(self, values: Dict[str, Any]) -> None:
        if bool(values["scroll_moves"]) != SCROLL.moves:
            self.set_scroll_moves(bool(values["scroll_moves"]))
        if bool(values["play_50hz"]) != REFRESH.pal:
            self.set_play_at_50hz(bool(values["play_50hz"]))
        if tuple(values["backdrop_colour"]) != shared_backdrop_colour():
            set_shared_backdrop_colour(values["backdrop_colour"])
        anim_ops.set_new_tick_rate(int(values["tick_rate"]))
        self.config.WriteInt(CONFIG_NEW_TICK_RATE, anim_ops.new_tick_rate())
        if int(values["autosave_seconds"]) * 1000 != self._autosave_ms():
            self.config.WriteInt(CONFIG_AUTOSAVE_SECONDS, int(values["autosave_seconds"]))
            self._autosave_timer.Start(self._autosave_ms())
        self.config.WriteBool(CONFIG_SHOW, bool(values["welcome"]))
        self.config.Flush()

    def on_preferences(self, _event: Optional[wx.CommandEvent] = None) -> None:
        with PreferencesDialog(self, self.preference_values(), self.clear_recent_files) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.apply_preferences(dialog.values())
                self.set_status("Preferences saved")

    def clear_recent_files(self) -> None:
        self.recent_files = []
        self._save_recent_files()
        self._rebuild_recent_menu()

    def set_play_at_50hz(self, pal: bool) -> None:
        """View ▸ Play at 50 Hz (PAL): every preview plays at a 50 Hz console's speed (kept in the preferences)."""
        for panel in self.panels:
            stop = getattr(panel, "stop_playback", None)
            if stop:
                stop()
        REFRESH.set(pal)
        self.m_play_50hz.Check(REFRESH.pal)
        self.animation_editor.refresh()  # its inspector shows the timing at this rate
        hz = REFRESH.hz(self.project)
        self.set_status(f"Previews play at {hz} Hz" + (" (PAL): 5/6 of the speed, as a 50 Hz console shows the game"
                                                      if hz == 50 else ""))

    def set_console_colours(self, shown: bool) -> None:
        """View ▸ Console Colours: every canvas shows the art through the export's palettes, as the console shows it."""
        CONSOLE.enabled = bool(shown)
        self.m_console.Check(CONSOLE.enabled)
        self.images_changed()
        console = consoles.console_by_key(self.project.console)
        self.set_status(f"{console.name} colours: each image through its palette, as the console shows it" if shown
                        else "The art's own colours")

    def images_changed(self) -> None:
        """Image pixels changed (reloaded, relinked, edited elsewhere): drop every cached picture and redraw."""
        CONSOLE.touch()
        SHARED.clear()
        THUMBNAILS.clear()
        BUDGET.clear()
        for panel in self.panels:
            panel.refresh_after_history()  # each tab rebuilds its own pictures from the data
        self._image_stamps = image_stamps(self.project)

    def _on_activate(self, event: wx.ActivateEvent) -> None:
        event.Skip()
        if event.GetActive():
            wx.CallAfter(self.check_images_on_disk)

    def check_images_on_disk(self) -> List[str]:
        """Reload images another program changed while the editor was in the background. Returns their ids."""
        if not self:
            return []
        now = image_stamps(self.project)
        changed = changed_images(self._image_stamps, now)
        self._image_stamps.update(now)
        if not changed:
            return []
        update_image_sizes(self.project, changed)
        for palette in {self.project.image_palette(self.project.get_image(i)).id: None for i in changed
                        if self.project.get_image(i)}:
            palettes.add_missing_colours(self.project, self.project.get_palette(palette))  # new colours join
        self.images_changed()
        self.history_checkpoint()  # a sheet that grew is project data (its size), new colours too
        names = [os.path.basename(self.project.get_image(i).file_path) for i in changed if self.project.get_image(i)]
        shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        self.set_status(f"Reloaded {shown}: changed on disk")
        return changed

    # ------------------------------------------------------------------ autosave and crash recovery
    def _on_autosave_timer(self, _event: wx.TimerEvent) -> None:
        mouse = wx.GetMouseState()
        if mouse.LeftIsDown() or mouse.MiddleIsDown() or mouse.RightIsDown():
            return  # a drag is still going on
        self.autosave_now()

    def autosave_now(self) -> None:
        """Keep a recovery copy of unsaved changes; none while everything is saved."""
        self.history_checkpoint()
        target = autosave.recovery_file_for(self.current_path, self._session_key)
        if self._recovery_file and self._recovery_file != target:
            self._drop_recovery()  # saved under another name since the last copy
        if not self.history.is_dirty():
            self._drop_recovery()
            return
        if self._recovery_file and self._autosaved_fingerprint == self.history.fingerprint:
            return  # nothing new since the last copy
        try:
            autosave.write_recovery(target, self.project, self.current_path)
        except (OSError, TypeError, ValueError) as exc:
            self.set_status(f"Autosave failed: {exc}")
            return
        self._recovery_file = target
        self._autosaved_fingerprint = self.history.fingerprint

    def _drop_recovery(self) -> None:
        """The changes were saved or discarded: their recovery copy is not needed any more."""
        autosave.remove_recovery(self._recovery_file)
        self._recovery_file = None
        self._autosaved_fingerprint = None

    def _ask_recovery(self, recovery: autosave.Recovery) -> str:
        """"restore", "discard" or "later" for a copy left by an editor that quit unexpectedly."""
        name = os.path.basename(recovery.project_path) if recovery.project_path else "a new project"
        when = time.strftime("%d %b %Y, %H:%M", time.localtime(recovery.saved_at))
        dlg = wx.MessageDialog(
            self,
            f"Modular Sprite Editor quit before the changes to {name} were saved.\n\n"
            f"Restore the changes it kept (autosaved {when})?",
            "Restore Unsaved Changes",
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
        )
        dlg.SetYesNoCancelLabels("Restore", "Discard", "Later")
        result = dlg.ShowModal()
        dlg.Destroy()
        return {wx.ID_YES: "restore", wx.ID_NO: "discard"}.get(result, "later")

    def offer_recovery(self) -> bool:
        """Offer the changes an editor that quit unexpectedly kept. Returns True if a project was restored."""
        for recovery in autosave.stale_recoveries():
            answer = self._ask_recovery(recovery)
            if answer == "discard":
                autosave.remove_recovery(recovery.path)
            if answer != "restore":
                continue
            try:
                project = autosave.load_recovery(recovery)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                wx.MessageBox(f"The autosaved copy could not be read: {exc}", "Restore Unsaved Changes",
                              wx.OK | wx.ICON_WARNING, self)
                continue
            self._set_project(project, recovery.project_path, saved=False)
            self._recovery_file = recovery.path  # updated by the next autosave until the project is saved
            when = time.strftime("%H:%M", time.localtime(recovery.saved_at))
            self.set_status(f"Restored the changes autosaved at {when}. Save to keep them.")
            return True
        return False

    def startup(self, path: Optional[str]) -> None:
        """First thing after the window opens: offer crash recovery, then open the project from the command line,
        else show the welcome screen."""
        if self.offer_recovery():
            return
        if path:
            self.load_project(path)
        elif self.config.ReadBool(CONFIG_SHOW, True):
            self.show_welcome()

    # ------------------------------------------------------------------ welcome screen
    def show_welcome(self, show: bool = True) -> None:
        """The welcome screen in place of the tabs (at the start, Help ▸ Welcome Screen), or the tabs again."""
        if show:
            has_project = bool(self.current_path or self.history.is_dirty() or self.project.images or self.project.frames)
            self.welcome.refresh(self.recent_files, has_project, self.config.ReadBool(CONFIG_SHOW, True))
        if show == self.welcome.IsShown():
            return
        self.welcome.Show(show)
        self.context_bar.Show(not show)
        self.book.Show(not show)
        self.welcome.GetParent().Layout()
        self._update_title()
        if show:
            self.set_status("")
            self.status_bar.SetStatusText("", 1)
        else:
            self._show_tab_hint()

    def _set_welcome_at_start(self, show: bool) -> None:
        self.config.WriteBool(CONFIG_SHOW, show)
        self.config.Flush()

    def open_path(self, path: str) -> None:
        """Open a project (a recent one, an example), after asking about unsaved changes."""
        if not os.path.isfile(path):
            wx.MessageBox(f"File not found: {path}", "Open Project", wx.OK | wx.ICON_ERROR, self)
            return
        if self.confirm_discard_changes():
            self.load_project(path)

    def _after_history_restore(self) -> None:
        for panel in self.panels:
            panel.refresh_after_history()
        self.context_bar.set_mappings(self.project)
        self.context_bar.set_swaps(self.project)
        self._update_title()

    def on_undo(self, _event: wx.CommandEvent) -> None:
        text = _focus_is_text_entry()
        if text is not None and hasattr(text, "CanUndo") and text.CanUndo():
            text.Undo()
            return
        if self.history.undo(self.project):
            self._after_history_restore()
            self.set_status("Undo")
        else:
            self.set_status("Nothing to undo")

    def on_redo(self, _event: wx.CommandEvent) -> None:
        text = _focus_is_text_entry()
        if text is not None and hasattr(text, "CanRedo") and text.CanRedo():
            text.Redo()
            return
        if self.history.redo(self.project):
            self._after_history_restore()
            self.set_status("Redo")
        else:
            self.set_status("Nothing to redo")

    def on_update_undo_ui(self, event: wx.UpdateUIEvent) -> None:
        event.Enable(self.history.can_undo() or self.history.is_dirty() or _focus_is_text_entry() is not None)

    def on_update_redo_ui(self, event: wx.UpdateUIEvent) -> None:
        event.Enable(self.history.can_redo() or _focus_is_text_entry() is not None)

    # ------------------------------------------------------------------ edit commands
    def _dispatch_edit(self, method_name: str, text_method: str) -> None:
        text = _focus_is_text_entry()
        if text is not None:
            handler = getattr(text, text_method, None)
            if handler:
                handler()
            return
        panel = self.book.GetCurrentPage()
        handler = getattr(panel, method_name, None)
        if handler:
            handler()
            self.history_checkpoint()

    def on_copy(self, _event: wx.CommandEvent) -> None:
        self._dispatch_edit("edit_copy", "Copy")

    def on_cut(self, _event: wx.CommandEvent) -> None:
        self._dispatch_edit("edit_cut", "Cut")

    def on_paste(self, _event: wx.CommandEvent) -> None:
        self._dispatch_edit("edit_paste", "Paste")

    def on_select_all(self, _event: wx.CommandEvent) -> None:
        self._dispatch_edit("edit_select_all", "SelectAll")

    def on_duplicate(self, _event: wx.CommandEvent) -> None:
        panel = self.book.GetCurrentPage()
        handler = getattr(panel, "edit_duplicate", None)
        if handler:
            handler()
            self.history_checkpoint()

    # ------------------------------------------------------------------ view commands
    def _active_canvas(self):
        panel = self.book.GetCurrentPage()
        getter = getattr(panel, "get_active_canvas", None)
        return getter() if getter else None

    def _view_command(self, action: Callable) -> None:
        canvas = self._active_canvas()
        if canvas is not None:
            action(canvas)

    # ------------------------------------------------------------------ mapping
    def on_preview_mapping_selected(self, mapping_id: Optional[str]) -> None:
        self.project.active_mapping = next((m for m in self.project.mappings if m.id == mapping_id), None)
        self.sync_mapping_controls()

    def on_preview_swap_selected(self, swap_id: Optional[str]) -> None:
        self.project.active_palette_swap = self.project.get_palette_swap(swap_id) if swap_id else None
        self.sync_palette_swap_controls()
        name = self.project.active_palette_swap.name if self.project.active_palette_swap else "the original colours"
        self.set_status(f"Every preview shows {name}")

    def sync_palette_swap_controls(self) -> None:
        """The preview's palette swap (or a swap it draws) changed: the choice above the tabs and every preview."""
        self.context_bar.set_swaps(self.project)
        for panel in self.panels:
            handler = getattr(panel, "on_active_mapping_changed", None)
            if handler:
                handler()

    def sync_mapping_controls(self) -> None:
        self.context_bar.set_mappings(self.project)
        self.context_bar.set_swaps(self.project)
        for panel in self.panels:
            handler = getattr(panel, "on_active_mapping_changed", None)
            if handler:
                handler()

    # ------------------------------------------------------------------ tabs
    def on_page_closing(self, event):
        """Prevent tabs from being closed."""
        event.Veto()

    def on_page_changed(self, event) -> None:
        self._page_shown(event.GetSelection())
        event.Skip()

    def _page_shown(self, page_idx: int) -> None:
        if page_idx == 0:
            self.module_editor.on_tab_activated()
        elif page_idx == 1:
            self.frame_editor.on_tab_activated()
        elif page_idx == 2:
            self.animation_editor.on_tab_activated()
        elif page_idx == 3:
            self.timeline_editor.on_tab_activated()
        elif page_idx == 4:
            self.mapping_editor.on_tab_activated()
        elif page_idx == 5:
            self.palette_editor.on_tab_activated()

        self._update_title()
        self._show_tab_hint()
        canvas = self._active_canvas()
        if canvas is not None:
            self.set_zoom_status(canvas.zoom)
            # Editor hotkeys should work right away instead of typing into a filter field.
            wx.CallAfter(canvas.SetFocus)
        else:
            self.status_bar.SetStatusText("", 1)

    def select_tab(self, index: int) -> None:
        self.show_welcome(False)
        if 0 <= index < self.book.GetPageCount():
            changed = index != self.book.GetSelection()
            self.book.SetSelection(index)
            if changed and isinstance(self.book, fnb.FlatNotebook):
                self._page_shown(index)  # FlatNotebook.SetSelection sends no page events (wx.Notebook's does)

    def switch_to_frame_editor(self, frame_id: str) -> None:
        """Navigates to the Frame Editor and selects the given frame."""
        self.select_tab(1)
        self.frame_editor.select_frame_by_id(frame_id)

    def switch_to_animation(self, anim_id: str) -> None:
        """The Animations tab with this animation selected."""
        self.select_tab(2)
        self.animation_editor.select_animation(anim_id)

    def switch_to_module(self, module_id: str) -> None:
        """Navigates to the Modules tab and shows the given module on its image."""
        self.select_tab(0)
        self.module_editor.select_module(module_id)

    # ------------------------------------------------------------------ recent files
    def _load_recent_files(self) -> None:
        s = self.config.Read("RecentFiles", "")
        if s:
            try:
                self.recent_files = json.loads(s)
            except (ValueError, TypeError):
                self.recent_files = []

    def _save_recent_files(self) -> None:
        self.config.Write("RecentFiles", json.dumps(self.recent_files))
        self.config.Flush()

    def add_file_to_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:10]
        self._save_recent_files()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        for item in self.menu_recent.GetMenuItems():
            self.menu_recent.Delete(item)

        if not self.recent_files:
            self.menu_recent.Append(wx.ID_ANY, "No Recent Files").Enable(False)
            return
        for idx, path in enumerate(self.recent_files):
            item = self.menu_recent.Append(wx.ID_ANY, f"{idx + 1}. {os.path.basename(path)}")
            item.SetHelp(path)
            self.Bind(wx.EVT_MENU, functools.partial(self.on_open_recent_file, path=path), item)
        self.menu_recent.AppendSeparator()
        item_clear = self.menu_recent.Append(wx.ID_ANY, "Clear Recent")
        self.Bind(wx.EVT_MENU, self.on_clear_recent, item_clear)

    def on_open_recent_file(self, event, path):
        if not self.confirm_discard_changes():
            return
        if os.path.exists(path):
            self.load_project(path)
        else:
            wx.MessageBox(f"File not found: {path}", "Error", wx.OK | wx.ICON_ERROR)
            if path in self.recent_files:
                self.recent_files.remove(path)
                self._save_recent_files()
                self._rebuild_recent_menu()

    def on_clear_recent(self, event):
        self.recent_files = []
        self._save_recent_files()
        self._rebuild_recent_menu()

    # ------------------------------------------------------------------ menus
    def _build_menu(self) -> None:
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        m_new = file_menu.Append(wx.ID_NEW, "&New Project\tCtrl+N", "Start an empty project")
        m_open = file_menu.Append(wx.ID_OPEN, "&Open...\tCtrl+O", "Open an existing project")
        self.menu_recent = wx.Menu()
        file_menu.AppendSubMenu(self.menu_recent, "Open Recent")
        self._rebuild_recent_menu()
        file_menu.AppendSeparator()
        m_save = file_menu.Append(wx.ID_SAVE, "&Save\tCtrl+S", "Save the current project")
        m_save_as = file_menu.Append(wx.ID_SAVEAS, "Save &As...\tCtrl+Shift+S", "Save with a new name")
        file_menu.AppendSeparator()

        import_menu = wx.Menu()
        m_import_aurora = import_menu.Append(wx.ID_ANY, "AuroraGT Sprite (*.sprite)...")
        m_import_retro = import_menu.Append(wx.ID_ANY, "RetroAnimator Project (*.json)...")
        m_import_aseprite = import_menu.Append(wx.ID_ANY, "Aseprite File (*.aseprite, *.ase)...",
                                               "Frames and tags of an Aseprite file as frames and animations")
        m_import_sheet = import_menu.Append(wx.ID_ANY, "Sprite Sheet with JSON (Aseprite, TexturePacker)...",
                                            "A sprite sheet PNG and its JSON as modules, frames and animations")
        file_menu.AppendSubMenu(import_menu, "Import")
        export_menu = wx.Menu()
        m_export_sgdk = export_menu.Append(wx.ID_ANY, "Mega Drive (SGDK)...", "Bake the project into a Mega Drive game's SGDK folder")
        m_export_retro = export_menu.Append(wx.ID_ANY, "RetroAnimator Project (*.json)...")
        m_export_sheet = export_menu.Append(wx.ID_ANY, "Sprite Sheet (JSON, Godot, Unity)...",
                                            "The animations' steps packed into one PNG with the data an engine reads")
        export_menu.AppendSeparator()
        m_export_gif = export_menu.Append(wx.ID_ANY, "Selected Animation as GIF...")
        m_export_sequence = export_menu.Append(wx.ID_ANY, "Selected Animation as PNG Sequence...")
        m_export_scene_gif = export_menu.Append(wx.ID_ANY, "Selected Scene as GIF...")
        file_menu.AppendSubMenu(export_menu, "Export")
        file_menu.AppendSeparator()
        m_exit = file_menu.Append(wx.ID_EXIT, "&Quit\tCtrl+Q")

        self.Bind(wx.EVT_MENU, self.on_new, m_new)
        self.Bind(wx.EVT_MENU, self.on_open, m_open)
        self.Bind(wx.EVT_MENU, self.on_save, m_save)
        self.Bind(wx.EVT_MENU, self.on_save_as, m_save_as)
        self.Bind(wx.EVT_MENU, self.on_import_aurora, m_import_aurora)
        self.Bind(wx.EVT_MENU, self.on_import_retro_animator, m_import_retro)
        self.Bind(wx.EVT_MENU, lambda e: self.import_aseprite(sheet_json=False), m_import_aseprite)
        self.Bind(wx.EVT_MENU, lambda e: self.import_aseprite(sheet_json=True), m_import_sheet)
        self.Bind(wx.EVT_MENU, self.on_export_sgdk, m_export_sgdk)
        self.Bind(wx.EVT_MENU, self.on_export_retro_animator, m_export_retro)
        self.Bind(wx.EVT_MENU, self.on_export_gif, m_export_gif)
        self.Bind(wx.EVT_MENU, self.on_export_sheet, m_export_sheet)
        self.Bind(wx.EVT_MENU, lambda e: (self.select_tab(2), self.animation_editor.export_png_sequence()), m_export_sequence)
        self.Bind(wx.EVT_MENU, lambda e: (self.select_tab(3), self.timeline_editor.export_gif()), m_export_scene_gif)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), m_exit)
        menubar.Append(file_menu, "&File")

        edit_menu = wx.Menu()
        m_undo = edit_menu.Append(wx.ID_UNDO, "&Undo\tCtrl+Z")
        m_redo = edit_menu.Append(wx.ID_REDO, "&Redo\tCtrl+Shift+Z")
        edit_menu.AppendSeparator()
        m_cut = edit_menu.Append(wx.ID_CUT, "Cu&t\tCtrl+X")
        m_copy = edit_menu.Append(wx.ID_COPY, "&Copy\tCtrl+C")
        m_paste = edit_menu.Append(wx.ID_PASTE, "&Paste\tCtrl+V")
        m_dup = edit_menu.Append(wx.ID_DUPLICATE, "&Duplicate\tCtrl+D")
        edit_menu.AppendSeparator()
        m_select_all = edit_menu.Append(wx.ID_SELECTALL, "Select &All\tCtrl+A")
        edit_menu.AppendSeparator()
        m_prefs = edit_menu.Append(wx.ID_PREFERENCES, "Preferences...\tCtrl+,")  # macOS: the application menu
        self.Bind(wx.EVT_MENU, self.on_undo, m_undo)
        self.Bind(wx.EVT_MENU, self.on_redo, m_redo)
        self.Bind(wx.EVT_MENU, self.on_cut, m_cut)
        self.Bind(wx.EVT_MENU, self.on_copy, m_copy)
        self.Bind(wx.EVT_MENU, self.on_paste, m_paste)
        self.Bind(wx.EVT_MENU, self.on_duplicate, m_dup)
        self.Bind(wx.EVT_MENU, self.on_select_all, m_select_all)
        self.Bind(wx.EVT_MENU, self.on_preferences, m_prefs)
        self.Bind(wx.EVT_UPDATE_UI, self.on_update_undo_ui, m_undo)
        self.Bind(wx.EVT_UPDATE_UI, self.on_update_redo_ui, m_redo)
        menubar.Append(edit_menu, "&Edit")

        view_menu = wx.Menu()
        m_zoom_in = view_menu.Append(wx.ID_ZOOM_IN, "Zoom &In\tCtrl+=")
        m_zoom_out = view_menu.Append(wx.ID_ZOOM_OUT, "Zoom &Out\tCtrl+-")
        m_zoom_fit = view_menu.Append(wx.ID_ZOOM_FIT, "&Fit to Content\tCtrl+0")
        m_zoom_1x = view_menu.Append(wx.ID_ZOOM_100, "Actual &Pixels (1×)\tCtrl+Shift+0")
        view_menu.AppendSeparator()
        m_grid = view_menu.Append(wx.ID_ANY, "Toggle &Grid\tCtrl+G")
        self.m_console = view_menu.AppendCheckItem(
            wx.ID_ANY, "Console Colours\tCtrl+Shift+P",
            "Show the art as the console will: each image through its palette, in the colours the console can show")
        self.m_scroll_moves = view_menu.AppendCheckItem(
            wx.ID_ANY, "Scroll Moves the View",
            f"Mouse wheel and two-finger scroll move the view; pinch or {MOD}+scroll zooms (off: scrolling zooms)")
        self.m_scroll_moves.Check(SCROLL.moves)
        self.m_play_50hz = view_menu.AppendCheckItem(
            wx.ID_ANY, "Play at 50 Hz (PAL)",
            "Previews play as a 50 Hz console shows the game: animations, scenes and colour cycles at 5/6 of the speed")
        self.m_play_50hz.Check(REFRESH.pal)
        view_menu.AppendSeparator()
        for idx, name in enumerate(TAB_NAMES):
            item = view_menu.Append(wx.ID_ANY, f"{name}\tCtrl+{idx + 1}")
            self.Bind(wx.EVT_MENU, functools.partial(lambda e, i: self.select_tab(i), i=idx), item)
        self.Bind(wx.EVT_MENU, lambda e: self._view_command(lambda c: c.zoom_step(1)), m_zoom_in)
        self.Bind(wx.EVT_MENU, lambda e: self._view_command(lambda c: c.zoom_step(-1)), m_zoom_out)
        self.Bind(wx.EVT_MENU, lambda e: self._view_command(lambda c: c.fit_to_content()), m_zoom_fit)
        self.Bind(wx.EVT_MENU, lambda e: self._view_command(lambda c: c.set_zoom_level(1.0)), m_zoom_1x)
        self.Bind(wx.EVT_MENU, self.on_toggle_grid, m_grid)
        self.Bind(wx.EVT_MENU, lambda e: self.set_console_colours(e.IsChecked()), self.m_console)
        self.Bind(wx.EVT_MENU, lambda e: self.set_scroll_moves(e.IsChecked()), self.m_scroll_moves)
        self.Bind(wx.EVT_MENU, lambda e: self.set_play_at_50hz(e.IsChecked()), self.m_play_50hz)
        menubar.Append(view_menu, "&View")

        tools_menu = wx.Menu()
        m_check = tools_menu.Append(wx.ID_ANY, "Check Project...", "What exports would drop or show differently, with fixes")
        tools_menu.AppendSeparator()
        m_automod = tools_menu.Append(wx.ID_ANY, "Auto Modularize Image...", "Cut the selected image's sprites into shared hardware-sized parts")
        m_opt_sprite = tools_menu.Append(wx.ID_ANY, "Optimize Sprite Sheet...")
        m_opt_nested = tools_menu.Append(wx.ID_ANY, "Optimize Nested Frame Combos (All Frames)...")
        tools_menu.AppendSeparator()
        m_ref_frames = tools_menu.Append(wx.ID_ANY, "Create Reference Frames From All Image Modules...")
        m_change_anims = tools_menu.Append(wx.ID_ANY, "Change Animations...",
                                           "One tick rate, playback, repeat count or group for many animations")
        self.Bind(wx.EVT_MENU, self.on_check_project, m_check)
        self.Bind(wx.EVT_MENU, self.on_tool_auto_modularize, m_automod)
        self.Bind(wx.EVT_MENU, self.on_tool_optimize, m_opt_sprite)
        self.Bind(wx.EVT_MENU, self.on_tool_optimize_nested, m_opt_nested)
        self.Bind(wx.EVT_MENU, self.on_tool_create_reference_frames, m_ref_frames)
        self.Bind(wx.EVT_MENU, lambda e: (self.select_tab(2), self.animation_editor.change_animations()), m_change_anims)
        menubar.Append(tools_menu, "&Tools")

        help_menu = wx.Menu()
        m_guide = help_menu.Append(wx.ID_ANY, "User Guide\tF1", "The user guide on the web")
        examples_menu = wx.Menu()
        for name, _text, path in example_paths():
            item = examples_menu.Append(wx.ID_ANY, name, path)
            self.Bind(wx.EVT_MENU, lambda e, p=path: self.open_path(p), item)
        if not examples_menu.GetMenuItemCount():
            item = examples_menu.Append(wx.ID_ANY, "Download the Example Projects...", DOWNLOAD_URL)
            self.Bind(wx.EVT_MENU, lambda e: wx.LaunchDefaultBrowser(DOWNLOAD_URL), item)
        examples_menu.AppendSeparator()
        item = examples_menu.Append(wx.ID_ANY, "What Each Example Shows...", EXAMPLES_GUIDE_URL)
        self.Bind(wx.EVT_MENU, lambda e: wx.LaunchDefaultBrowser(EXAMPLES_GUIDE_URL), item)
        help_menu.AppendSubMenu(examples_menu, "Example Projects")
        m_welcome = help_menu.Append(wx.ID_ANY, "Welcome Screen", "Recent projects, the examples and the guide")
        help_menu.AppendSeparator()
        m_shortcuts = help_menu.Append(wx.ID_ANY, "Keyboard && Mouse Shortcuts\tCtrl+/")
        m_about = help_menu.Append(wx.ID_ABOUT, f"About {APP_NAME}")
        self.Bind(wx.EVT_MENU, lambda e: wx.LaunchDefaultBrowser(GUIDE_URL), m_guide)
        self.Bind(wx.EVT_MENU, lambda e: self.show_welcome(), m_welcome)
        self.Bind(wx.EVT_MENU, self.on_shortcuts, m_shortcuts)
        self.Bind(wx.EVT_MENU, self.on_about, m_about)
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)
        _mac_force_app_menu_title(APP_NAME)

    # ------------------------------------------------------------------ project lifecycle
    def confirm_discard_changes(self) -> bool:
        """Ask to save unsaved changes. Returns False if the user cancelled."""
        self.history_checkpoint()
        if not self.history.is_dirty():
            return True
        name = os.path.basename(self.current_path) if self.current_path else "this project"
        dlg = wx.MessageDialog(
            self,
            f"Do you want to save the changes you made to {name}?",
            "Unsaved Changes",
            wx.YES_NO | wx.CANCEL | wx.ICON_WARNING,
        )
        dlg.SetYesNoCancelLabels("Save", "Don't Save", "Cancel")
        result = dlg.ShowModal()
        dlg.Destroy()
        if result == wx.ID_CANCEL:
            return False
        if result == wx.ID_YES:
            return self.save_project()
        self._drop_recovery()  # the changes were discarded on purpose
        return True

    def _set_project(self, project: Project, path: Optional[str], saved: bool, notes_title: str = "Project Upgraded",
                     notes_status: str = "Project format upgraded; save to keep the upgrade") -> None:
        self._remember_view()  # where the project being closed was left
        self._drop_recovery()  # the previous project's changes were saved or discarded by now
        self.show_welcome(False)
        self.project = project
        self.current_path = path
        self._reload_project_into_panels()
        self.history.reset(self.project, saved=saved)
        self._image_stamps = image_stamps(self.project)
        self._restore_view()
        self.context_bar.set_mappings(self.project)
        self.context_bar.set_swaps(self.project)
        self._update_title()
        if project.load_notes:
            wx.MessageBox("\n".join(project.load_notes), notes_title, wx.OK | wx.ICON_INFORMATION)
            self.set_status(notes_status)

    def on_new(self, _: wx.CommandEvent) -> None:
        if not self.confirm_discard_changes():
            return
        self._set_project(Project(), None, saved=True)

    def load_project(self, path: str) -> None:
        """Helper to load a project and update the UI."""
        path = os.path.abspath(path)  # before the chdir below, which would move a relative path
        try:
            os.chdir(os.path.dirname(path))  # Set CWD to project folder
            project = Project.from_json(path)
        except Exception as e:
            wx.MessageBox(f"Failed to load project: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return
        if project.imported_from:
            # Another editor's file: an import, saved as a new project (never over the file it came from).
            self._set_imported(project, path)
            return
        self._set_project(project, path, saved=True)
        self.add_file_to_recent(path)
        self.set_status(f"Opened {path}")

    def _set_imported(self, project: Project, path: str) -> None:
        kind = project.imported_from
        self._set_project(project, None, saved=False, notes_title=f"Imported {kind}",
                          notes_status=f"Imported {kind} with notes. Save it as a new project.")
        if not project.load_notes:
            self.set_status(f"Imported {kind} {os.path.basename(path)}. Save it as a new project.")

    def on_open(self, _: wx.CommandEvent) -> None:
        if not self.confirm_discard_changes():
            return
        with wx.FileDialog(
            self,
            "Open project",
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        self.load_project(path)

    def save_project(self, path: Optional[str] = None) -> bool:
        target = path or self.current_path
        if not target:
            return self._save_as_dialog()
        try:
            self.project.to_json(target)
        except Exception as exc:
            wx.MessageBox(f"Failed to save project: {exc}", "Save Error", wx.OK | wx.ICON_ERROR)
            return False
        self.current_path = target
        self.history_checkpoint()
        self.history.mark_saved(self.project)
        self._drop_recovery()
        self.add_file_to_recent(target)
        self._update_title()
        self.set_status(f"Saved {target}")
        return True

    def _save_as_dialog(self) -> bool:
        default_name = os.path.basename(self.current_path) if self.current_path else "project.json"
        with wx.FileDialog(
            self,
            "Save project",
            defaultFile=default_name,
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return False
            path = dlg.GetPath()
        if not path.lower().endswith(".json"):
            path += ".json"
        return self.save_project(path)

    def on_save(self, _: wx.CommandEvent) -> None:
        self.save_project()

    def on_save_as(self, _: wx.CommandEvent) -> None:
        self._save_as_dialog()

    def on_import_aurora(self, _: wx.CommandEvent) -> None:
        if not self.confirm_discard_changes():
            return
        with wx.FileDialog(
            self,
            "Import AuroraGT Sprite",
            wildcard="AuroraGT Sprite (*.sprite)|*.sprite",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        os.chdir(os.path.dirname(path))
        try:
            project = Project.from_json(path)
        except Exception as exc:
            wx.MessageBox(f"Failed to import: {exc}", "Import Error", wx.OK | wx.ICON_ERROR)
            return
        self._set_imported(project, path)  # not saved yet: Save asks for a location

    def on_import_retro_animator(self, _: wx.CommandEvent) -> None:
        if not self.confirm_discard_changes():
            return
        with wx.FileDialog(
            self,
            "Import RetroAnimator Project",
            wildcard="RetroAnimator JSON (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        os.chdir(os.path.dirname(path))
        try:
            project = Project.from_retro_animator_json(path)
        except Exception as exc:
            wx.MessageBox(f"Failed to import: {exc}", "Import Error", wx.OK | wx.ICON_ERROR)
            return
        self._set_imported(project, path)

    def import_aseprite(self, sheet_json: bool) -> None:
        """File ▸ Import ▸ Aseprite File / Sprite Sheet with JSON (importers/aseprite.py): a new, unsaved project."""
        from importers import aseprite

        if not self.confirm_discard_changes():
            return
        wildcard = ("Sprite sheet JSON (*.json)|*.json" if sheet_json
                    else "Aseprite files (*.aseprite;*.ase)|*.aseprite;*.ase")
        with wx.FileDialog(self, "Import Sprite Sheet with JSON" if sheet_json else "Import Aseprite File",
                           wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            with wx.BusyCursor():
                project = aseprite.parse_sheet_json(path) if sheet_json else aseprite.parse_aseprite(path)
        except (OSError, ValueError, KeyError, TypeError, struct.error, zlib.error) as exc:
            wx.MessageBox(f"Could not import {os.path.basename(path)}:\n{exc}", "Import", wx.OK | wx.ICON_ERROR, self)
            return
        project.imported_from = "sprite sheet" if sheet_json else "Aseprite file"
        os.chdir(os.path.dirname(os.path.abspath(path)))
        self._set_imported(project, path)

    def on_export_retro_animator(self, _: wx.CommandEvent) -> None:
        if not self.project.frames:
            wx.MessageBox("No frames available to export.", "Export RetroAnimator", wx.OK | wx.ICON_WARNING)
            return

        default_name = (self.project.name or "sprite").strip().replace(" ", "_") or "sprite"
        mapping = self.project.active_mapping  # the preview mapping and palette swap are baked into the pictures
        swap = self.project.active_palette_swap
        drawn = self._drawn_with()
        with wx.FileDialog(
            self,
            f"Export RetroAnimator Project, drawn with {drawn}",
            defaultFile=f"{default_name}.json",
            wildcard="JSON files (*.json)|*.json|All files (*.*)|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            # wxPython 4.2.5 macOS can assert on ShowModal when filter index is out of bounds.
            # Explicitly select first filter and provide a fallback wildcard entry.
            dlg.SetFilterIndex(0)
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()

        try:
            with wx.BusyCursor():
                report = self.project.to_retro_animator_json(path, mapping=mapping, swap=swap)
        except Exception as exc:
            wx.MessageBox(f"Failed to export RetroAnimator project: {exc}", "Export Error", wx.OK | wx.ICON_ERROR)
            return

        losses = report.get("losses", [])
        mapping_name = self.project.active_mapping.name if self.project.active_mapping else "<none>"
        summary = [
            f"Exported RetroAnimator project to:\n{report.get('path', path)}",
            "",
            f"Frames: {report.get('frames_exported', 0)}",
            f"Animations: {report.get('animations_exported', 0)}",
            f"Generated parts: {report.get('parts_written', 0)}",
            f"Parts folder: {report.get('parts_dir', '')}",
            f"Preview mapping baked: {mapping_name if report.get('mapping_baked') else 'No'}",
        ]
        if report.get("parts_removed"):
            summary.insert(5, f"Old parts removed: {report['parts_removed']} (written by this export before, no longer used)")
        if losses:
            summary.append("")
            summary.append("Important compatibility notes:")
            summary.extend([f"- {line}" for line in losses])
        errors = project_check.counts(project_check.check_project(self.project, pixels=False))[project_check.ERROR]
        if errors:
            summary += ["", f"Tools ▸ Check Project finds {errors} error{'s' if errors != 1 else ''}: things the export "
                        "leaves out or gets wrong, such as missing parts, steps or images."]
        wx.MessageBox("\n".join(summary), "Export Complete", wx.OK | wx.ICON_INFORMATION)

    # ------------------------------------------------------------------ check and export
    def go_to(self, target: Tuple[str, str]) -> None:
        """Show the item an issue is about in its tab."""
        kind, ident = target
        if kind == "image":
            self.select_tab(0)
            self.module_editor.select_sheet(ident, fit=True)
        elif kind == "module":
            self.switch_to_module(ident)
        elif kind == "frame":
            self.switch_to_frame_editor(ident)
        elif kind == "animation":
            self.select_tab(2)
            self.animation_editor.select_animation(ident)
        elif kind == "mapping":
            self.select_tab(4)
            self.mapping_editor.select_mapping(ident)
        elif kind == "scene":
            self.select_tab(3)
            self.timeline_editor.refresh_scenes(select_id=ident)
        elif kind == "palette":
            self.select_tab(5)
            self.palette_editor.select_palette(ident)
        elif kind == "palette_swap":
            self.select_tab(5)
            self.palette_editor.select_swap(ident)

    def _after_fix(self, message: str) -> None:
        """Check Project changed the project: one undo step, every tab shows the result."""
        self.history_checkpoint()
        for panel in self.panels:
            panel.refresh_after_history()
        self.set_status(message)

    def on_check_project(self, _event: Optional[wx.CommandEvent] = None) -> None:
        with CheckProjectDialog(self, self.project, self._after_fix) as dlg:
            dlg.ShowModal()
            target = dlg.target
        if target:
            self.go_to(target)

    # ------------------------------------------------------------------ view memory
    def _remember_view(self) -> None:
        """Keep where the project was left (tab, preview mapping and swap, each tab's selection and view) in the
        preferences, under the project file's path."""
        if not self.current_path:
            return
        project = self.project
        state = {
            "tab": self.book.GetSelection(),
            "mapping": project.active_mapping.id if project.active_mapping else None,
            "palette_swap": project.active_palette_swap.id if project.active_palette_swap else None,
            "tabs": {name: panel.view_state() for panel, name in zip(self.panels, TAB_NAMES)},
        }
        view_memory.save(self.config, self.current_path, state)

    def _restore_view(self) -> None:
        """Back to where the project was left the last time it was open (whatever of it still exists)."""
        state = view_memory.load(self.config, self.current_path)
        if not state:
            return
        project = self.project
        mapping_id = view_memory.text(state.get("mapping"))
        project.active_mapping = next((m for m in project.mappings if m.id == mapping_id), None)
        swap_id = view_memory.text(state.get("palette_swap"))
        project.active_palette_swap = project.get_palette_swap(swap_id) if swap_id else None
        tabs = state.get("tabs") if isinstance(state.get("tabs"), dict) else {}
        for panel, name in zip(self.panels, TAB_NAMES):
            panel_state = tabs.get(name)
            if isinstance(panel_state, dict):
                panel.restore_view_state(panel_state)
        if project.active_mapping is not None or project.active_palette_swap is not None:
            for panel in self.panels:
                handler = getattr(panel, "on_active_mapping_changed", None)
                if handler:
                    handler()
        tab = state.get("tab")
        if isinstance(tab, int) and 0 <= tab < self.book.GetPageCount():
            self.select_tab(tab)

    def _export_preference(self) -> str:
        """Preferences key for this project's Mega Drive export folder."""
        path = os.path.abspath(self.current_path) if self.current_path else "untitled"
        return "SGDKExport/" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]

    def export_sgdk(self, folder: str, selector: str):
        """Bake the project into an SGDK project folder; the exporter's result, or None when it failed."""
        try:
            exporter = load_exporter()
            with wx.BusyCursor():
                result = exporter.export_project(self.project, Path(folder), selector,
                                                 Path(self.current_path) if self.current_path else None)
        except Exception as exc:  # the exporter reports bad data as exceptions; keep the editor running
            wx.MessageBox(f"The export failed: {exc}", "Export for the Mega Drive", wx.OK | wx.ICON_ERROR, self)
            return None
        self.set_status(f"Exported for the Mega Drive to {folder}")
        return result

    def on_export_sgdk(self, _event: Optional[wx.CommandEvent] = None) -> None:
        key = self._export_preference()
        default = os.path.dirname(os.path.abspath(self.current_path)) if self.current_path else os.path.expanduser("~")
        folder, selector = self.config.Read(key, default), self.config.Read(key + "Mapping", "all")
        with MegaDriveExportDialog(self, self.project, folder, selector) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            folder, selector = dlg.values()
        if not folder or not os.path.isdir(folder):
            wx.MessageBox("Choose a folder that exists.", "Export for the Mega Drive", wx.OK | wx.ICON_WARNING, self)
            return
        if not has_runtime(folder) and wx.MessageBox(
            "This folder has no Mega Drive runtime (src/modsprite.c and inc/modsprite.h), so it does not look like "
            "the game's SGDK project. Export into it anyway?",
            "Export for the Mega Drive", wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        self.config.Write(key, folder)
        self.config.Write(key + "Mapping", selector)
        self.config.Flush()
        result = self.export_sgdk(folder, selector)
        if result is None:
            return
        with ExportReportDialog(self, folder, result) as report:
            answer = report.ShowModal()
        if answer == ID_CHECK_PROJECT:
            self.on_check_project()

    def _drawn_with(self) -> str:
        """What exports draw with: the preview mapping and palette swap (the bar above the tabs)."""
        mapping, swap = self.project.active_mapping, self.project.active_palette_swap
        return (f"the mapping {mapping.name}" if mapping else "the original modules (no preview mapping)") + (
            f" and the palette swap {swap.name}" if swap else "")

    def on_export_sheet(self, _event: Optional[wx.CommandEvent] = None) -> None:
        """File ▸ Export ▸ Sprite Sheet: the steps packed into a PNG with JSON, a Godot .tres or a Unity .meta."""
        from exporters import sheet

        if not self.project.animations and not self.project.frames:
            wx.MessageBox("There are no animations or frames to export.", "Export Sprite Sheet",
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        with SheetExportDialog(self, self.project, self.animation_editor.selected_animation_id,
                               self._drawn_with()) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            options = dlg.options()
        default = sheet.safe_name(os.path.splitext(os.path.basename(self.current_path or "sprites"))[0]) + ".png"
        with wx.FileDialog(self, "Save the sprite sheet (its data file goes next to it)", defaultFile=default,
                           wildcard="PNG images (*.png)|*.png", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            path = fd.GetPath()
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            with wx.BusyCursor():
                report = sheet.export_sheet(self.project, path, mapping=self.project.active_mapping,
                                            swap=self.project.active_palette_swap, **options)
        except (OSError, ValueError) as exc:
            wx.MessageBox(f"Could not export the sprite sheet:\n{exc}", "Export Sprite Sheet", wx.OK | wx.ICON_ERROR, self)
            return
        width, height = report["size"]
        notes = "" if not report["notes"] else "\n\n" + "\n".join(report["notes"])
        wx.MessageBox(
            f"{report['entries']} steps of {report['animations']} animation(s) as {report['cells']} pictures on a "
            f"{width} × {height} sheet:\n\n{report['image']}\n{report['data']}{notes}",
            "Export Sprite Sheet", wx.OK | wx.ICON_INFORMATION, self)
        self.set_status(f"Exported the sprite sheet to {os.path.basename(report['image'])}")

    def on_export_gif(self, event: wx.CommandEvent) -> None:
        self.select_tab(2)
        self.animation_editor.export_gif()

    def on_shortcuts(self, _: wx.CommandEvent) -> None:
        with ShortcutsDialog(self) as dlg:
            dlg.ShowModal()

    def on_about(self, _: wx.CommandEvent) -> None:
        wx.MessageBox(
            f"{APP_NAME}\nVersion {APP_VERSION}\n\nAssemble, animate and map modular pixel-art sprites for retro consoles.",
            f"About {APP_NAME}",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def on_toggle_grid(self, _: wx.CommandEvent) -> None:
        panel = self.book.GetCurrentPage()
        controls = getattr(panel, "canvas_controls", None)
        if controls is not None:
            controls.toggle_grid()

    def on_tool_auto_modularize(self, _: wx.CommandEvent) -> None:
        self.select_tab(0)
        self.module_editor.auto_modularize()

    def on_tool_optimize(self, _: wx.CommandEvent) -> None:
        self.select_tab(0)
        output_dir = os.path.dirname(self.current_path) if self.current_path else None
        self.module_editor.show_optimization_dialog(output_dir)
        self.history_checkpoint()

    def on_tool_optimize_nested(self, event: wx.CommandEvent) -> None:
        # Global frame-level optimization entry point.
        self.select_tab(1)
        self.frame_editor.on_optimize_nested_combos(event)
        self.history_checkpoint()

    def on_tool_create_reference_frames(self, _: wx.CommandEvent) -> None:
        if not self.project.images:
            wx.MessageBox("No images in project.", "Info")
            return

        image_ids = {img.id for img in self.project.images}
        modules = [m for m in self.project.modules if m.image_id in image_ids]
        if not modules:
            wx.MessageBox("No image-backed modules found to create reference frames.", "Info")
            return

        used_frame_names = {f.name for f in self.project.frames}

        def unique_frame_name(base_name: str) -> str:
            root = (base_name or "Reference").strip() or "Reference"
            candidate = root
            suffix = 2
            while candidate in used_frame_names:
                candidate = f"{root} ({suffix})"
                suffix += 1
            used_frame_names.add(candidate)
            return candidate

        created = 0
        last_frame_id: Optional[str] = None
        for mod in modules:
            img = self.project.get_image(mod.image_id)
            image_base = os.path.splitext(os.path.basename(img.file_path))[0] if img else "Image"
            frame = self.project.create_frame(unique_frame_name(f"Ref {image_base} - {mod.name}"))
            frame.fmodules.append(
                FModule(
                    id=generate_id("fmod"),
                    ref_type="module",
                    ref_id=mod.id,
                    position=(int(mod.pivot[0]), int(mod.pivot[1])),
                )
            )
            created += 1
            last_frame_id = frame.id

        self.frame_editor.refresh_choices()
        if last_frame_id:
            self.frame_editor.select_frame_by_id(last_frame_id)
        self.animation_editor.refresh_library()
        self.history_checkpoint()
        self.set_status(f"Created {created} reference frame(s).")

    def on_close(self, event: wx.CloseEvent) -> None:
        if event.CanVeto() and not self.confirm_discard_changes():
            event.Veto()
            return
        self._checkpoint_timer.Stop()
        self._autosave_timer.Stop()
        if not event.CanVeto() and self.history.is_dirty(self.project):
            self.autosave_now()  # the system is shutting down: keep the changes for the next start
        else:
            self._drop_recovery()
        for panel in self.panels:
            stop = getattr(panel, "stop_playback", None)
            if stop:
                stop()
        self._remember_view()
        self._save_recent_files()
        self._save_geometry()
        app_services.install()
        event.Skip()

    def _reload_project_into_panels(self) -> None:
        for panel in self.panels:
            panel.set_project(self.project)
        self._update_title()


def resource_path(relative_path):
    """A bundled file (assets/...): next to app.py, or in PyInstaller's folder in the builds."""
    base_path = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class SpriteEditorApp(wx.App):
    _main: Optional["MainFrame"] = None

    def FilterEvent(self, event: wx.Event) -> int:  # type: ignore[N802]
        """Every event passes here first: user input tells the main window to look for changes to checkpoint."""
        if event.GetEventType() in INPUT_EVENTS and self._main:
            self._main.note_input()
        return wx.EventFilter.Event_Skip  # then handled as usual

    def OnInit(self) -> bool:  # type: ignore[N802]
        # wx's default name, the launched program's: older versions kept the view settings in a store named so.
        old_name = self.GetAppName()
        # The names before any window or preference exists: macOS uses them for the application menu.
        self.SetAppName(APP_NAME)
        self.SetAppDisplayName(APP_NAME)
        prefs = os.environ.get("MSE_PREFERENCES_FILE")
        if prefs:  # tests keep their preferences in a file of their own
            wx.Config.Set(wx.FileConfig(localFilename=prefs, style=wx.CONFIG_USE_LOCAL_FILE))
        else:
            # Before the vendor name is set: on Windows it would become part of the registry path.
            config = wx.Config(APP_NAME)
            if old_name and old_name != APP_NAME:
                preferences.adopt_old_store(config, wx.Config(old_name), old_name)
            wx.Config.Set(config)
        self.SetVendorName(APP_NAME)
        self.SetVendorDisplayName(APP_NAME)
        frame = self._main = MainFrame()

        # Set Icon (Windows needs explicit setting for Taskbar/Window)
        if sys.platform == "win32":
            try:
                icon_path = resource_path(os.path.join("assets", "icon.ico"))
                if os.path.exists(icon_path):
                    frame.SetIcon(wx.Icon(icon_path, wx.BITMAP_TYPE_ICO))
            except (OSError, wx.wxAssertionError):
                pass  # the window keeps wx's default icon

        frame.Show()
        self.SetTopWindow(frame)

        # Offer changes a crashed session kept, then open a project passed on the command line.
        paths = [arg for arg in sys.argv[1:] if arg.lower().endswith(".json") and os.path.exists(arg)]
        wx.CallAfter(frame.startup, os.path.abspath(paths[0]) if paths else None)
        return True


def main() -> None:
    # redirect=False is CRITICAL to see console output if things go wrong
    app = SpriteEditorApp(False)
    app.MainLoop()


def run_smoke_test(args: List[str]) -> None:
    """`--smoke-test PROJECT.json [LOG]`: drive every tab against the project (tools/gui_smoke.py) and exit with
    0 (pass) or 1, so the built executables can be tested. A windowed exe has no console: LOG gets the output."""
    import atexit
    import shutil
    import tempfile

    if len(args) > 1:
        sys.stdout = sys.stderr = open(args[1], "w", encoding="utf-8", buffering=1)
    # Preferences go to a throwaway file: the test must not change the user's settings.
    prefs_dir = tempfile.mkdtemp(prefix="mse_smoke_")
    atexit.register(shutil.rmtree, prefs_dir, True)
    os.environ["MSE_PREFERENCES_FILE"] = os.path.join(prefs_dir, "preferences.ini")
    sys.argv = [sys.argv[0]] + args[:1]
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    importlib.import_module("gui_smoke")  # importing it runs the test and exits


if __name__ == "__main__":
    if sys.argv[1:2] == ["--smoke-test"]:
        run_smoke_test(sys.argv[2:])
    else:
        main()
