"""PaletteInspector: the selected palette (its slots, colours and cycles, as the project's console holds them) and,
with a palette swap selected, what the swap makes of it."""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

import wx

import consoles
import palettes
from models import Palette, PaletteSwap, Project
from ui.components.inspector_kit import dim_text, hbox, relayout, row, section, small_button, spin
from ui.components.palette_swatches import hex_colour
from ui.dpi import px
from ui.palette_editor import ops
from ui.palette_editor.swatches import SwatchGrid

MODELS = {"rgb333": "3 bits a channel (512 colours)", "bgr555": "5 bits a channel (32,768 colours)"}


def console_line(project: Project) -> str:
    """What a palette is on the project's console."""
    console = consoles.console_by_key(project.console)
    spec = console.palette
    model = (f"picked from the console's {len(spec.fixed_colours)}" if spec.colour_model == "fixed"
             else MODELS.get(spec.colour_model, ""))
    return (f"{console.name}: {spec.visible} colours and transparent, {model}; {spec.palettes} palettes on screen at "
            "once" + (", shared with the backgrounds" if spec.shared_with_backgrounds else ""))


class PaletteInspector(wx.ScrolledWindow):
    def __init__(self, parent: wx.Window):
        super().__init__(parent, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.SetScrollRate(0, px(12))
        self.SetMinSize((px(290), -1))
        self.project: Optional[Project] = None
        self.palette: Optional[Palette] = None
        self.swap: Optional[PaletteSwap] = None
        self.slots: List[int] = []
        self._updating = False
        # Callbacks (the panel sets them)
        self.on_command: Optional[Callable[[str], None]] = None
        self.on_rename_palette: Optional[Callable[[str], None]] = None
        self.on_rename_swap: Optional[Callable[[str], None]] = None
        self.on_cycle: Optional[Callable[[int, int, bool], None]] = None  # (cycle, frames, reverse)

        root = wx.BoxSizer(wx.VERTICAL)
        # ---------------------------------------------------------------- palette
        self.palette_section, grid, _ = section(self, root, "Palette", scope="PaletteInspector")
        p = self.palette_section.body
        self.name = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.name.Bind(wx.EVT_TEXT_ENTER, lambda e: self._rename_palette())
        self.name.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), self._rename_palette()))
        row(grid, p, "Name", self.name)
        self.console = dim_text(p)
        grid.Add((0, 0))
        grid.Add(self.console, 0, wx.EXPAND)
        self.images = dim_text(p)
        row(grid, p, "Images", self.images)
        self.grid = SwatchGrid(p)
        grid.Add((0, 0))
        grid.Add(self.grid, 0)
        self.slot_info = dim_text(p)
        row(grid, p, "Selected", self.slot_info)
        self.btn_add = small_button(p, "Add…", "Put a colour into the next free slot", lambda: self._command("add_colour"))
        self.btn_change = small_button(p, "Change…", "Pick another colour for the selected slot", lambda: self._command("change"))
        self.btn_original = small_button(p, "Original", "Show the palette's own colour in the selected slots under this swap",
                                         lambda: self._command("original"))
        self.btn_remove = small_button(p, "Remove", "Remove the selected slots (the colours after them move up)",
                                       lambda: self._command("remove_slots"))
        # The slot buttons get the section's whole width (beside the labels they would not fit).
        actions = p.GetSizer()
        actions.Add(hbox(self.btn_add, self.btn_change, self.btn_original, self.btn_remove), 0,
                    wx.EXPAND | wx.LEFT | wx.TOP, px(2))
        self.btn_missing = small_button(p, "Add missing", "Put the colours the images use that the palette lacks into free slots",
                                        lambda: self._command("add_missing"))
        self.btn_unused = small_button(p, "Remove unused", "Remove the slots no pixel uses", lambda: self._command("remove_unused"))
        self.btn_sort = small_button(p, "Sort ▾", "Order the slots: dark to light, by hue or most used first", self._sort_menu)
        tidy = hbox(self.btn_missing, self.btn_unused, self.btn_sort)
        tidy.GetItem(self.btn_sort).SetProportion(0)  # Sort keeps its width, the other two share the rest
        actions.Add(tidy, 0, wx.EXPAND | wx.LEFT | wx.TOP, px(2))

        # ---------------------------------------------------------------- cycles
        self.cycle_section, grid, _ = section(self, root, "Colour cycles", scope="PaletteInspector")
        p = self.cycle_section.body
        self.own_cycles = wx.CheckBox(p, label="Own cycles for this swap")
        self.own_cycles.SetToolTip("Off: the swap runs the palette's cycles. On: it runs cycles of its own for this palette.")
        self.own_cycles.Bind(wx.EVT_CHECKBOX, lambda e: self._command(f"own_cycles:{int(self.own_cycles.GetValue())}"))
        grid.Add((0, 0))
        grid.Add(self.own_cycles, 0)
        self.cycle_list = wx.ListBox(p, size=(-1, px(78)))
        self.cycle_list.Bind(wx.EVT_LISTBOX, lambda e: self._show_cycle())
        row(grid, p, "Cycles", self.cycle_list)
        self.frames = spin(p, 1, 600, 64, "Video frames each step lasts (60 a second, 50 on PAL)")
        self.frames.Bind(wx.EVT_SPINCTRL, lambda e: self._cycle_changed())
        self.frames.Bind(wx.EVT_TEXT_ENTER, lambda e: self._cycle_changed())
        self.reverse = wx.CheckBox(p, label="Down")
        self.reverse.SetToolTip("The colours move to the lower slots (off: to the higher ones)")
        self.reverse.Bind(wx.EVT_CHECKBOX, lambda e: self._cycle_changed())
        row(grid, p, "Every", hbox(self.frames, wx.StaticText(p, label="frames"), 8, self.reverse, "stretch"))
        self.btn_add_cycle = small_button(p, "+ From selection", "A cycle over the selected run of slots (select it with Shift+click)",
                                          lambda: self._command("add_cycle"))
        self.btn_remove_cycle = small_button(p, "Remove", "Remove the selected cycle", lambda: self._command("remove_cycle"))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_add_cycle, self.btn_remove_cycle), 0, wx.EXPAND)
        self.cycle_hint = dim_text(p, "Water, lava, a glowing super form: a cycle moves the colours of a run of slots "
                                      "along while animations and scenes play.")
        self.cycle_hint.Wrap(px(200))
        grid.Add((0, 0))
        grid.Add(self.cycle_hint, 0)

        # ---------------------------------------------------------------- swap
        self.swap_section, grid, _ = section(self, root, "Palette swap", scope="PaletteInspector")
        p = self.swap_section.body
        self.swap_name = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        self.swap_name.Bind(wx.EVT_TEXT_ENTER, lambda e: self._rename_swap())
        self.swap_name.Bind(wx.EVT_KILL_FOCUS, lambda e: (e.Skip(), self._rename_swap()))
        row(grid, p, "Name", self.swap_name)
        self.swap_info = dim_text(p)
        grid.Add((0, 0))
        grid.Add(self.swap_info, 0, wx.EXPAND)
        self.preview_everywhere = wx.CheckBox(p, label="Preview in every tab")
        self.preview_everywhere.SetToolTip("Draw every canvas and thumbnail with this swap (the Palette swap choice above the tabs)")
        self.preview_everywhere.Bind(wx.EVT_CHECKBOX,
                                     lambda e: self._command(f"preview:{int(self.preview_everywhere.GetValue())}"))
        grid.Add((0, 0))
        grid.Add(self.preview_everywhere, 0)
        self.btn_reset_swap = small_button(p, "Reset this palette", "This swap leaves the palette's colours as they are",
                                           lambda: self._command("reset_swap"))
        grid.Add((0, 0))
        grid.Add(hbox(self.btn_reset_swap), 0, wx.EXPAND)

        self.hint = dim_text(self, "")
        root.Add(self.hint, 0, wx.ALL, 10)
        self.SetSizer(root)

    # ------------------------------------------------------------------ showing
    def show(self, project: Project, palette: Optional[Palette], swap: Optional[PaletteSwap], slots: Sequence[int],
             cycle: int) -> None:
        self.project, self.palette, self.swap, self.slots = project, palette, swap, list(slots)
        self._updating = True
        self.Freeze()
        try:
            self.palette_section.Show(palette is not None)
            self.cycle_section.Show(palette is not None)
            self.swap_section.Show(palette is not None and swap is not None)
            self.hint.SetLabel("" if palette is not None else "Add a palette (+ New) or an image (Modules tab).")
            if palette is not None:
                self._fill_palette(project, palette, swap)
                self._fill_cycles(project, palette, swap, cycle)
                if swap is not None:
                    self._fill_swap(project, palette, swap)
        finally:
            self._updating = False
            self.Thaw()
        relayout(self)

    def _fill_palette(self, project: Project, palette: Palette, swap: Optional[PaletteSwap]) -> None:
        if self.name.GetValue() != palette.name and not self.name.HasFocus():
            self.name.ChangeValue(palette.name)
        self.console.SetLabel(console_line(project))
        self.console.Wrap(px(220))
        count, names = palettes.describe(project, palette)
        self.images.SetLabel((f"{len(names)}: " + ", ".join(names[:3]) + (" …" if len(names) > 3 else "")) if names else "none")
        self.images.SetToolTip("\n".join(names) if names else "No image uses this palette yet (Modules tab, the image's Palette)")
        colours = palettes.stored_colours(project, palette)  # with those waiting past the console's palette size
        replacements = None
        if swap is not None:
            change = swap.palettes.get(palette.id)
            replacements = list(change.colours) if change else []
        usage = palettes.slot_usage(project, palette)
        art = ops.art_slots(project, palette)
        self.grid.reorder = swap is None
        self.grid.set_palette(colours, palettes.capacity(project), replacements, palettes.cycles_of(palette, swap),
                              usage, art)
        self.grid.set_selected(self.slots)
        slots = [s for s in self.slots if s < len(colours)]
        if len(slots) == 1:
            slot = slots[0]
            text = f"slot {slot + 1}: {hex_colour(colours[slot])}"
            if swap is not None and ops.replacement(swap, palette, slot) is not None:
                text += f" → {hex_colour(ops.replacement(swap, palette, slot))}"
            text += f" · {usage[slot]} px" if slot < len(usage) else ""
        elif slots:
            text = f"slots {min(slots) + 1}–{max(slots) + 1}" if len(slots) > 1 else ""
        else:
            text = "click a slot, or a pixel of the image"
        self.slot_info.SetLabel(text)
        full = len(colours) >= palettes.capacity(project)
        lacking = len(palettes.missing_colours(project, palette)) if len(colours) <= palettes.capacity(project) else 0
        in_swap = swap is not None
        art_selected = bool(set(slots) & set(art))
        self.btn_add.Show(not in_swap)
        self.btn_add.Enable(not full)
        self.btn_change.Enable(len(slots) == 1 and (in_swap or not art_selected))
        self.btn_change.SetToolTip("Pick what the selected slot shows under this swap" if in_swap else
                                   ("The images have this colour: recolour it with a palette swap" if art_selected
                                    else "Pick another colour for the selected slot"))
        self.btn_original.Show(in_swap)
        self.btn_original.Enable(in_swap and any(ops.replacement(swap, palette, s) is not None for s in slots))
        self.btn_remove.Show(not in_swap)
        self.btn_remove.Enable(bool(slots) and not any(usage[s] for s in slots if s < len(usage)))
        self.btn_missing.SetLabel(f"Add missing ({lacking})" if lacking else "Add missing")
        self.btn_missing.Enable(bool(lacking) and not full)
        self.btn_unused.Enable(not in_swap and bool(palettes.unused_slots(project, palette)))
        self.btn_sort.Enable(not in_swap and len(colours) > 1)
        for btn in (self.btn_missing, self.btn_unused, self.btn_sort):
            btn.Show(not in_swap)

    def _fill_cycles(self, project: Project, palette: Palette, swap: Optional[PaletteSwap], cycle: int) -> None:
        own = ops.own_cycles(swap, palette)
        self.own_cycles.Show(swap is not None)
        self.own_cycles.SetValue(own)
        cycles = palettes.cycles_of(palette, swap)
        editable = swap is None or own
        self.cycle_list.Set([f"Slots {c.first}–{c.first + c.count - 1}, every {c.frames} frames"
                             + (", down" if c.reverse else "") for c in cycles])
        if cycles:
            self.cycle_list.SetSelection(cycle if 0 <= cycle < len(cycles) else 0)
        self._show_cycle()
        self.cycle_list.Enable(True)
        self.btn_add_cycle.Enable(editable and len(set(self.slots)) >= 2)
        self.btn_remove_cycle.Enable(editable and self.cycle_list.GetSelection() != wx.NOT_FOUND)
        for widget in (self.frames, self.reverse):
            widget.Enable(editable and self.cycle_list.GetSelection() != wx.NOT_FOUND)

    def _fill_swap(self, project: Project, palette: Palette, swap: PaletteSwap) -> None:
        if self.swap_name.GetValue() != swap.name and not self.swap_name.HasFocus():
            self.swap_name.ChangeValue(swap.name)
        changed = ops.changed_slots(swap, palette)
        others = [p.name for p in project.palettes if p.id in swap.palettes and p.id != palette.id]
        self.swap_info.SetLabel(
            (f"Changes {len(changed)} slot{'s' if len(changed) != 1 else ''} of this palette" if changed
             else "Leaves this palette as it is: select a slot and choose Change…")
            + (f"; also {', '.join(others)}" if others else "")
            + f". {ops.swap_uses(project, swap)} scene object(s) use it.")
        self.swap_info.Wrap(px(220))
        self.preview_everywhere.SetValue(project.active_palette_swap is swap)
        self.btn_reset_swap.Enable(palette.id in swap.palettes)

    def _show_cycle(self) -> None:
        index = self.cycle_list.GetSelection()
        cycles = palettes.cycles_of(self.palette, self.swap) if self.palette else []
        if 0 <= index < len(cycles):
            self.frames.SetValue(cycles[index].frames)
            self.reverse.SetValue(cycles[index].reverse)

    # ------------------------------------------------------------------ events
    def selected_cycle(self) -> int:
        index = self.cycle_list.GetSelection()
        return index if index != wx.NOT_FOUND else -1

    def _command(self, name: str) -> None:
        if not self._updating and self.on_command:
            self.on_command(name)

    def _rename_palette(self) -> None:
        if not self._updating and self.on_rename_palette and self.palette is not None:
            name = self.name.GetValue().strip()
            if name and name != self.palette.name:
                self.on_rename_palette(name)

    def _rename_swap(self) -> None:
        if not self._updating and self.on_rename_swap and self.swap is not None:
            name = self.swap_name.GetValue().strip()
            if name and name != self.swap.name:
                self.on_rename_swap(name)

    def _cycle_changed(self) -> None:
        index = self.selected_cycle()
        if not self._updating and self.on_cycle and index >= 0:
            self.on_cycle(index, int(self.frames.GetValue()), bool(self.reverse.GetValue()))

    def _sort_menu(self) -> None:
        menu = wx.Menu()
        for how, label in (("brightness", "Dark to light"), ("hue", "By hue (greys first)"), ("usage", "Most used first")):
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda e, h=how: self._command(f"sort:{h}"), item)
        self.btn_sort.PopupMenu(menu)
        menu.Destroy()
