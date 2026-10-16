# Palettes, palette swaps and the console database

How palettes work since file format 7 and blob version 5 (2026-10-14). They replace the palettes of format 6, which were rebuilt
from the images every time (the 15 most used colours, in an order that changed with the pixel counts, the free slots
filled with copies of the last colour, always the Mega Drive's 16). Swaps need colours that stay where they are, and
other consoles have palettes of other sizes.

## The console database (`consoles.py`)

One wx-free module describes every console the editor knows: the screen modes (resolution, sprites per screen and per
line, sprite pixels per line), the refresh rates, the sprite hardware (tile size, bits per pixel, the sprite sizes,
hardware flips, rotation and scaling, the tiles sprites can use), the palette hardware (colours per palette, the
transparent index, palettes for sprites, whether backgrounds share them, the colour model: 3 bits per channel, 5 bits,
or a fixed set like the NES master palette) and what the editor supports for it (budget overlay, palettes, export).

It holds the Mega Drive, the SNES, the NES, the Game Boy Advance and the Game Boy, the consoles whose screens the
Timeline already shows. The budget overlay's profiles (Mega Drive H40 / H32, SNES 8/16 and 16/32, NES and Game Boy
8×8 and 8×16, GBA) and the Timeline's screen guides come from it, and so do the palette rules of a project's console.
Adding a console is adding an entry; supporting it in the budget, the palettes or an exporter is switching those on
with the code behind them.

## The project's console

A project has a target console (`Project.console`, `"megadrive"` by default) and a setup of it
(`Project.console_setup`: screen mode, sprite sizes), chosen with *Console* above the tabs (`MainFrame.set_project_console`
→ `ui/palette_editor/ops.set_console`, one undo step). Every console here has palettes; the Mega Drive and the
SNES have exporters (the SNES export writes BGR555 words, `palettes.snes_word`, into eight sprite palettes). The palette
code reads every limit from the console's entry, never a constant:

| Console | A palette holds | Colours | Palettes for sprites |
| --- | --- | --- | --- |
| Mega Drive | 15 + transparent | 3 bits a channel | 4, shared with the backgrounds |
| SNES | 15 + transparent | 5 bits a channel | 8 |
| Game Boy Advance | 15 + transparent | 5 bits a channel | 16 |
| NES | 3 + transparent | one of the PPU's 64 | 4 |
| Game Boy | 3 + transparent | one of its 4 shades | 2 |

On the NES and the Game Boy a slot takes one of the console's fixed colours: the Palettes tab picks them from a grid
(`fixed_colours.py`, the NES's numbered `$00`-`$3F`), and the console view shows every colour as the nearest of them.

Palettes keep the artist's colours when the console changes. A palette can then store more colours than the new
console shows: `palettes.colours_of` gives the first ones (what the console holds, what every draw, the budget and
the export use), `stored_colours` all of them. The Palettes tab crosses the others out, the palette list marks the
palette, and Check Project warns (`palette-too-long`) with the fix *Keep the most used*
(`palettes.keep_most_used`: the colours its images use most stay, in their slot order, the swaps' replacements and
the cycles move with them). Switching to a console with smaller palettes asks the same: keep the most used, or keep
every colour (they wait for a console with bigger palettes; dragging a crossed-out colour forward makes it shown).

The Mega Drive export of a project that targets another console still writes Mega Drive palette lines (16 colours,
the slots the console has no room for black) and reports `other-console` (`project_check.console_issue`).

## Palettes

A palette (`Project.palettes`) has an id, a name, its colours and its colour cycles. `colours` lists the visible
colours in hardware order: colour 1 is hardware index 1 (index 0 is the transparent one on every console here), so a
Mega Drive palette holds up to 15. The list may be shorter: the export fills the rest with black, the editor shows
them as empty slots. Every image belongs to one palette (`ImageAsset.palette_id`); vector shapes use the first.

The colours are the artist's, in the artist's order, and they stay where they are. The editor adds an image's colours
that are missing to free slots when the image joins the palette or is reloaded (one undo step), and Check Project
warns when there is no room left: those pixels show as the nearest colour, in the export as on the console view.
The Palettes tab reorders, edits (snapped to what the console can show), adds from the images, removes unused colours
and sorts.

A pixel's index is the first slot with exactly its colour, else the nearest one (by squared RGB distance), the same
in the editor's console view, the swaps, the budget's tile count and the export.

## Palette swaps

A palette swap (`Project.palette_swaps`) recolours without touching an image: for each palette it changes, a list of
replacement colours aligned with the palette's slots (`None` keeps the palette's colour) and optionally its own colour
cycles. A guard drawn from the hero's animations and modules can wear other clothes; a hit flash, poisoned skin or the
second player's colours are swaps too.

Swaps are chosen where mappings are chosen, and independently of them (AuroraGT games set a sprite's mapping and its
palette separately):

- the preview, next to the preview mapping above the tabs: every canvas, thumbnail and the GIF / RetroAnimator /
  sprite sheet exports draw with it;
- a Timeline object (`TimelineObject.palette_swap_id`): `None` takes the parent's (the preview's at the top),
  `"original"` the palettes as they are, or a swap's id, resolved like the object's mapping;
- the game, per draw.

Reordering a palette moves the swaps' replacements and the cycles with the slots.

## Colour cycles

A cycle (`ColourCycle`: first slot, count, video frames per step, direction) rotates a run of slots: water, lava,
conveyor belts, a glowing super form. Palettes have cycles, and a swap can give a palette cycles of its own. The
preview animates them while an animation or a scene plays (and all the time in the Palettes tab), counting video
frames at the preview's refresh rate (60 Hz, or 50 Hz for PAL).

## The Mega Drive export (blob version 5)

- Palette entries: every palette, then every swap's changed palette, 16 colour words each, with their cycles.
- A piece names its palette entry in its spare byte instead of carrying palette bits in its tile offset, so a project
  can have more palettes than the console has lines, and a swap shares the tiles of what it recolours (same indices,
  so no extra video memory).
- The runtime loads the entries into consecutive lines from the first one it is given, as many as fit
  (`ms_palettes_fit()` says whether all did), and keeps a table from entry to line. `ms_load_palette(entry, line)`
  lets a game manage the lines itself. `ms_set_palette_swap(swap)` recolours what is drawn afterwards, like
  `ms_set_mapping`; `ms_draw_anim_player_as(player, mapping, swap, x, y)` draws with both without changing them.
  A sprite's palette bits come from that table at draw time (one table read per hardware sprite).
- `ms_palette_tick()` advances the colour cycles of the loaded entries once per video frame.
- Scenes are baked once per mapping; an object with a swap of its own gets the swap's entries in its pieces, the
  rest follow the swap the scene is drawn with.

## Checks

Check Project reports image colours a palette has no room for, palettes that store more colours than the console
shows (with a fix), palettes with two slots of one colour (pixels use the first), swaps and objects that name a deleted
palette or swap (with fixes), and more palette entries than lines.
`ID_LISTS` covers palettes and swaps.

## File format 7

`console`, `palettes`, `palette_swaps`, `images[].palette_id` (replacing `palette`), `timeline_objects[].palette_swap_id`
(format 7 also brought scene objects that follow a point and groups for frames and animations; see
`docs/FILE_FORMAT.md`). The migration names the format 6 palettes Palette 1-4 and leaves their colours to be built from
the images once the project is open, with the format 6 rules, so a migrated project exports exactly as before.

## Where it is tested

`tests/test_palettes.py` (colours, slots, swaps, cycles, maintenance, other consoles), `tests/test_consoles.py` (the
database gives the budget profiles and screen guides), `tests/test_megadrive_runtime_draw.py` (the compiled
runtime draws a guard in a swap, scene objects with swaps of their own, and turns cycles like the preview),
`tests/test_project_check.py` (the palette checks), and the smoke test's palette steps.
