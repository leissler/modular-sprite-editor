# Video memory and limits

A retro console has little video memory and a fixed number of hardware sprites. This page explains how the exports and the runtime use both and what a game can choose; each console's page gives its numbers ([Consoles](consoles/index.md) compares them).

## Three ways to store the sprites

Two independent choices make an export:

- **What the cartridge stores.** *Parts*: each module's tiles once, a frame put together from its parts when it is drawn; the cartridge stays small and mappings cost nothing, but every part is at least one hardware sprite, overlaps included. *Whole frames*: each frame flattened into one picture per palette, cut into the fewest hardware sprites; overlaps cost nothing, but every frame is a picture of its own, and every mapping stores them all again.
- **Where the tiles live.** *Resident*: every tile sits in video memory, and drawing only writes the sprite table. *Streamed*: video memory holds a slot per thing drawn at the same time, and a frame's tiles are copied into its slot when it is drawn.

The exports offer three combinations: **Store as** in the editor's export dialog, `--mode` on the command line. Whole frames kept resident are not offered: they never fit.

| Mode | | Use it when |
|---|---|---|
| `parts` (the default) | parts, resident | the project's tiles fit video memory |
| `parts_streamed` | parts, streamed | they do not, or video memory is needed for other things |
| `frames_streamed` | whole frames, streamed | the fewest sprites matter most and the cartridge has room: few, large characters, few mappings |

What the choice means, for the Prince of Persia example on the Mega Drive (every console's page has its table):

| | Video memory | Cartridge | Hardware sprites a step | Busiest line |
|---|---|---|---|---|
| parts, resident | 305 tiles | 9.5 KB | 9.3 on average, 21 at most | 14 of 20 |
| parts, streamed | 39 tiles a character, 65 a scene | 9.5 KB | the same | the same |
| whole frames, streamed | 22 tiles a character, 38 a scene | 194 KB | 1.2, 3 at most | 2 of 20 |

The cartridge column counts tiles only; the records come on top. The editor's export dialog measures the modes on your project, for your console, before you export.

**Some frames whole.** Between parts and whole frames, an artist marks single frames **Store whole**: those are stored as pictures in every mode, the others stay parts. It suits props of many overlapping parts that show often. In the Prince of Persia port on the Mega Drive, platforms went from 7.5 hardware sprites on average to 3.7, crushers from 14 to 5, pressure plates from 15.5 to 5, for 27 KB more cartridge. Characters stay parts: their frames share parts and their mappings re-skin them for free; stored whole they would take 351 KB, 1.7 MB with the guards' eight mappings, against 26 KB as parts. Nothing changes for the game: a frame stored whole is drawn like any other.

## Resident exports

`ms_init()` loads every tile once, from the place `ms_init_ex` gives; drawing then writes only the sprite table. The tiles must fit the room the console leaves for sprite tiles beside the game's own graphics. The export reports how many tiles the sprites need, warns above three quarters of the room and reports an error when they do not fit; the editor's budget overlay and **Check Project** count video memory the same way, for the project's console.

## Streamed exports

The cartridge keeps every tile. Each render frame names a **load list**: the runs of tiles it needs, one after the other from a slot's first tile. Its sprites count their tiles from the slot. The exporter lays the tiles out in the order frames first use them, so a frame's tiles mostly lie together and a list has few runs: each run is a DMA transfer, which costs time to set up.

**Slots.** `ms_init` makes a **default slot**, as big as the largest module, frame, animation step or scene sample (`ms_slot_tiles()`, `ms_scene_slot_tiles()`). A slot holds one thing at a time: everything drawn in the same video frame needs a slot of its own, set with `ms_set_slot` before drawing it, like the mapping. Place your slots after the default slot (each console's page says where and how they align). Drawing what a slot already holds uploads nothing; drawing something else queues its load list, and the tiles arrive in the next vertical blank, together with the sprite table that uses them.

**The slot cache.** A game with many actors gives the runtime one pool: `ms_slot_cache_init(first_tile, tile_count)`. A load list (a frame or module under a mapping) gets a slot there the first time it is drawn, at the first place in tile order where it fits; every draw of it uses that slot, so actors showing the same frame share it and it is uploaded once. When the pool is full, the slots drawn longest ago make room, never one drawn this frame; a draw that still finds no room is left out and counted (`draws_left_out`).

**A cache of your own.** `ms_frame_load_list` and `ms_module_load_list` give the load list a draw would use, `ms_load_list_tiles` its size; a game places slots itself and sets them with `ms_set_slot`. The Prince of Persia port kept such a cache of 496 tiles for every gameplay bank before the runtime had one.

**Uploads.** What one vertical blank can carry is the console's limit for streaming: the export and **Check Project** warn when filling one slot costs more, and say how many characters can change steps in the same frame. When the uploads of a frame do not fit, the runtime keeps them correct rather than torn: on the Mega Drive a transfer the DMA queue refuses is queued again on the next draw; on the SNES a draw over the upload budget shows what its slot holds and uploads in a later frame.

## Palettes

The runtime loads the palette entries (the palettes, then the swaps' versions of the palettes they change) into consecutive palette lines from the first one `ms_init_ex` gives, as far as they fit; `ms_palettes_fit()` is `FALSE` when some did not. With more entries than lines, load the ones a screen needs with `ms_load_palette(entry, line)`. A swap's entry without a line draws in its palette's line with the colours unswapped. Colour cycles turn with `ms_palette_tick()`, once per video frame: after n calls they show what the editor's preview shows after n video frames. How many lines a console has, and whether its backgrounds share them, is on its page.

## Sprite limits

A console shows a fixed number of hardware sprites per screen and per line ([compared](consoles/index.md#compared)).

**Per screen**, the runtime keeps count: `ms_set_sprite_limit` sets the most it writes (lower it to leave room for your own sprites). Sprites over the limit are dropped, the ones drawn last first, and counted in the profile (`sprites_dropped`). Draws made while a **give-way level** is set ([API](api.md#give-way-levels)) are left out first instead: shadows, then decorations, then effects, as far as the picture asks too much, the farthest first, resolved in `ms_end_frame` without drawing the picture twice. On the Mega Drive, a picture that fits takes 94 lines with the Prince of Persia example's frames (99 with give-way levels); pictures over the limit take 227 to 398 lines with levels, where a game that measures them and draws them again without what gives way took 336 to 563.

**Per line**, the console's hardware decides: past a line's limit it does not show the sprites last in the table on that line. The runtime does not manage lines; plan for them with the editor's budget overlay, which marks lines over the limit, and with frames stored whole, which put far fewer sprites on a line (the Animations tab's budget says how many characters playing an animation fit side by side).

To plan a picture before drawing it, `ms_frame_sprites` and `ms_frame_bounds` give each draw's sprites and box from the records.

## Timing

The runtime counts video frames. Each animation step holds for its ticks at the animation's tick rate converted to whole video frames at 60 a second; rates that divide 60 are exact, others round some steps, which the editor's preview plays the same way and **Check Project** notes. A 50 Hz (PAL) console plays everything at 5/6 of the speed; the editor previews it with **View ▸ Play at 50 Hz**.
