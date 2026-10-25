# SGDK Example (Mega Drive)

This folder contains a complete SGDK pipeline for modular sprite rendering from your editor JSON:

- **Input assets**: `PoP_WW.json` + `modules_POP.bmp` (any project works, e.g. `examples/sonic/sonic.json`)
- **Bake step**: a Python exporter turns the JSON into one compact binary blob
- **Runtime**: a small SGDK/C library that draws a **module**, **frame**, **animation** or **timeline scene**, plays
  animations exactly like the editor, and gives the game the hitboxes and points of what it shows

The editor's online documentation is at [modularsprites.bionic-productions.com](https://modularsprites.bionic-productions.com/);
[For your programmer](https://modularsprites.bionic-productions.com/reference/programmers/) explains what the artist
hands over and how this export fits in.

## How it works

Mega Drive code should not parse JSON or transform images per frame, so the exporter bakes everything into
`res/gen/modsprite_blob.bin` (included by `res/resources.res` as `BIN MS_BLOB ...`, parsed by the generated
`src/modsprite_data.c`):

- **Tiles and palettes**: every module image as it is used (flipped parts reuse the same tiles through the
  sprite's flip bits; rotations are baked), cut into hardware sprites of at most 32×32 (the fewest, then the fewest
  tiles, at any pixel of the part: `sprite_cut.export_cut`, which the editor's Budget overlay counts too), as 4 bpp
  tiles in VDP order, deduplicated; the editor's palettes
  (Palettes tab; Modules tab ▸ image ▸ **Palette**, `ImageAsset.palette_id`) in their slot order, each palette
  swap's version of the palettes it changes, and the colour cycles (`palettes.py`, shared with the editor's
  View ▸ Console Colours). A piece stores which palette entry its pixels index; a swap recolours by changing the
  entry, so swaps cost no tiles.
- **Pieces**: the hardware sprites of each image, laid out once for every flip combination a part uses.
- **Render frames**: the parts of each frame, animation step and scene sample, with their hitboxes and points,
  sprite count and bounds; animations, scenes, mappings, step events and all names.

Only the first two are the Mega Drive's: what parts, render frames, animations and scenes hold is worked out by
`console_bake.py` (repository root), the bake every console's exporter shares; `MegaDriveBakeContext` subclasses it and
stores each part's picture as VDP tiles and hardware sprites (`_store_part`).

At start `ms_init()` loads all tiles into VRAM (at `TILE_USER_INDEX`) and the palette entries into consecutive
palette lines from `PAL1` (the palettes first, then the swaps' versions); a table maps every entry to its line, and
drawing puts the line into each sprite's palette bits (entries a scene object fixed with a swap of its own keep it).
Drawing
then only writes SGDK's sprite table cache: a part becomes its pieces plus the part's position and flip bits;
frames that lie fully on screen are copied without per-sprite tests, others are culled sprite by sprite (a
sprite at x = -128 would hide the sprites behind it). `ms_end_frame()` queues one sprite-table DMA, which
`SYS_doVBlankProcess()` sends. The runtime does not use SGDK's `SPR_*` sprite engine; add sprites of your own
to the same list with `ms_add_hw_sprite()`.

### Streamed exports

By default every tile stays in video memory. The export can instead keep there only what is on screen
(`--mode parts_streamed` or `--mode frames_streamed`; in the editor the export dialog's **Store as**, remembered per
project); [docs/EXPORT_MODES.md](../../docs/EXPORT_MODES.md) compares the three ways on the example projects:

- **`parts_streamed`**: the same parts and tiles in the cartridge as the default export. PoP needs a slot of 39 tiles
  a player instead of 305 resident.
- **`frames_streamed`**: each frame flattened into one picture per palette and cut into hardware sprites like a part,
  so overlapping parts cost nothing (PoP: 1.2 hardware sprites a step instead of 9.3, 2 on the busiest line instead of
  14), but the cartridge holds every frame's picture (PoP: 6209 tiles instead of 305) and each mapping is baked again.

The blob (version 8) then gives every render frame a load list: the runs of tiles it needs, one after the other from a
slot's first tile (identical lists stored once); its pieces count their tiles from the slot. The tiles are laid out in
the order frames first use them, so a frame's tiles mostly lie together, in few runs. The generated header defines
`MS_STREAMED`, `MS_SLOT_TILES` (a player's slot) and `MS_SCENE_SLOT_TILES` (a scene's).

`ms_init()` then loads no tiles: it makes a default slot at its tile index, as big as the largest module, frame, step
or scene sample. Drawing a render frame whose list the slot does not hold queues one DMA per run
(`DMA_queueDmaFast`), which `SYS_doVBlankProcess()` sends with the sprite table, so the tiles and the sprites that use
them arrive in the same vertical blank; drawing what the slot holds already uploads nothing. A run SGDK refuses (its
DMA queue is full) leaves the slot holding nothing, and the next draw through it queues the list again.

Everything drawn at the same time needs a slot of its own, set before drawing like the mapping:

```c
static MS_Slot guard_slot;
ms_slot_init(&guard_slot, ms_tile_base() + ms_tiles_used());  /* after the default slot, ms_slot_tiles() tiles */

ms_draw_anim_player(&hero, hero_x, hero_y);                   /* through the default slot */
ms_set_slot(&guard_slot);
ms_draw_anim_player_mapped(&guard, guard_mapping, guard_x, guard_y);
ms_set_slot(NULL);                                            /* the default slot again */
```

A scene streams through one slot, a sample's tiles at a time, so a sample that only moves its objects uploads nothing.
In a resident export the slot functions do nothing (`ms_slot_tiles()` is 0), so the same game code builds with either.

A game with many actors lets the runtime keep the slots: `ms_slot_cache_init(tile_index, tile_count)` makes one pool
of tiles that every draw takes its slot from. A load list (a frame or module under a mapping) gets a slot there the first
time it is drawn, at the first place in tile order where it fits (one walk along the slots), and every draw of it uses
that slot, so actors showing the same frame share it and it is uploaded once. When there is no room, the slots drawn
longest ago make room (never one drawn this frame); a draw that still finds none is left out. `MS_FrameProfile` counts
`slots_used`, `tiles_uploaded` and `draws_left_out`; `ms_slot_cache_clear()` forgets what the pool holds,
`ms_set_slot()` / `ms_use_slot_cache()` switch between slots of the game's own and the cache. `MS_CACHE_SLOTS` (48; define
another number when compiling `modsprite.c`, 0 leaves the cache out) caps the slots. The native Prince of Persia:
Warrior Within kept such a cache of its own, 496 tiles for every gameplay bank, which this replaces:

```c
ms_slot_cache_init(ms_tile_base(), 496);
ms_set_mapping(guard_mapping);
ms_draw_frame_flipped(frame, x, y, flip);   /* through the slot that holds that frame under that mapping */
```

A game that keeps its own slots after all asks `ms_frame_load_list(frame)` and `ms_module_load_list(module)` for the
load list a frame or module draws with (under the current mapping; `MS_NOTHING_LOADED` in a resident export) and
`ms_load_list_tiles(list)` for the tiles it takes.

### Performance

Measured in BlastEm 0.6.2 (`PoP_WW.json`, every animation for one cycle and every frame, scanline-accurate
timing with the VDP V counter; one NTSC frame has 262 lines):

| | old runtime (one SGDK `Sprite` per part) | current runtime |
|---|---|---|
| draw + upload, average | 56 + 47 lines (39 % of a frame) | 14.5 + 4 lines (7 %) |
| worst frame | 98 % of a frame | 11 % |
| dropped frames | 20 | 0 |
| DMA per frame | up to 1400 bytes of tiles | 168 bytes (sprite table) |

Streamed exports, with the demo playing PoP's Swordfight (600 frames in BlastEm, drawing only, with the C draw loops
the runtime had before [the 68000 ones](#the-draw-loops-in-68000-assembly)):

| | drawing, average | frames that upload | at most |
|---|---|---|---|
| parts, resident | 32.2 lines | none | 42 lines |
| `parts_streamed` | 36.9 lines | 67.8 lines (one frame in nine) | 88 lines |
| `frames_streamed` | 11.2 lines | 16.5 lines | 21 lines |

The uploads themselves go in the vertical blank (up to 2 KB here; a vertical blank carries about 7 KB, NTSC). The
68000 spends its time queueing them: about 2.3 lines for each run of tiles, and a Swordfight sample of two characters in
parts has 12.8 runs on average (21 at most), whole frames one to four.

Crowds of PoP's frames, modules and sprites of the game's own across the screen and its edges
([`tools/check_megadrive_rom.py`](#check-the-runtime-in-a-rom) in BlastEm, resident,
[docs/EXPORT_MODES.md](../../docs/EXPORT_MODES.md#when-a-picture-asks-for-too-many-sprites)): a picture that fits the
80 sprites draws in 94 lines (99 with give-way levels, 96 with levels on and none set), pictures over the limit in 227
to 398 lines with give-way levels where measuring and drawing them again takes 336 to 563. Streamed, through the slot
cache with everything cached, a draw takes about one line more.

#### The draw loops in 68000 assembly

Most of a frame's drawing is the loop that copies its pieces into the sprite table. A frame of four hardware sprites or
more goes through the 68000 loops of `src/modsprite_draw.s`: on the screen and under the limit they copy a piece in 116
cycles (gcc's loop: about 200) and start a part in about 190 (250), mirrored a piece in 152 cycles one way and 188 both
ways; across an edge of the screen, every piece tested, about 285 cycles a piece drawn (gcc's: about 540). A smaller
frame keeps the C loops, which draw it faster: the call costs about what the assembly saves on three sprites
(`MS_ASM_SPRITES`, 4; a game can define another number when it compiles `modsprite.c`). The C loops stay in
`modsprite.c`: any compiler but a 68000 one builds them alone (the host tests), and so does `MS_PUT_FRAME_C`
(`make debug EXTRA_FLAGS=-DMS_PUT_FRAME_C`).
[`tools/check_megadrive_rom.py`](#check-the-runtime-in-a-rom) keeps the two equal. In BlastEm, the check's draws and
pictures with the C loops alone (`--c`) and with the 68000 ones, in lines (a frame has 262):

| PoP, resident | C loops | 68000 loops |
|---|---|---|
| a frame of 7 sprites in 7 parts: as it is / mirrored / across the left edge | 12.0 / 15.7 / 14.0 | 10.5 / 12.0 / 12.4 |
| a frame of 21 sprites in 21 parts | 25.7 / 36.0 / 34.3 | 19.7 / 22.7 / 26.0 |
| a frame of one sprite (Sonic) | 6.1 / 7.1 / 6.3 | the C loops |
| the Swordfight, 600 frames: a frame on average / at most | 38.2 / 48 | 30.7 / 37 |
| the same `parts_streamed` | 43.0 / 96 | 35.2 / 86 |
| pictures over the 80 sprites: as they are / with give-way levels | 230–417 / 270–455 | 188–349 / 227–398 |

A frame of parts draws in 11 to 37 % less time (the more sprites, the more; mirrored ones the most), the Swordfight in a
fifth less; whole frames (`frames_streamed`: 1.2 sprites a step) as before (17.1 lines a frame). Besides its pieces a
draw takes about five lines whatever its size (its record found, the profile, the tests), most of a small frame's time.

`make release` against `make debug` ([Build the SGDK demo](#build-the-sgdk-demo)), the demo on PoP's Swordfight (600
frames, resident export, the frame from the start of the vertical blank to the end of the frame's work, read from the V
counter; with the C draw loops, before the 68000 ones took about a fifth off its drawing):

| | `make debug` | `make release` |
|---|---|---|
| frame, average (BlastEm) | 63.8 lines (4.1 ms, 24 % of a frame) | 51.8 lines (3.3 ms, 20 %) |
| worst frame (BlastEm) | 77 lines | 65 lines |
| drawing (BlastEm) | 32.6 lines | 30.7 lines |
| ROM, code and data (both files pad to 384 KB) | 287,906 bytes | 284,328 bytes |

Most of the difference is SGDK's own time (MAME, which counts about 2 lines a frame fewer than BlastEm in both builds):
the vertical blank's work (the DMA queue, the sprite table) 11.7 lines against 7.5, reading the pad 8.5 against 5.5,
queueing the sprite table in `ms_end_frame` 5.8 against 3.8, the demo's text 3.1 against 1.9. The runtime draws 6 %
faster (link-time optimisation across it and SGDK). Neither build drops a frame; with START's panel open both now and
then do when its numbers change (the demo's text takes 124 to 260 lines then; 7 frames in 600 in debug, 4 in release).

### Limits

- **VRAM**: all tiles stay resident. `PoP_WW` needs 305 tiles, `sonic` 620; they must fit between the tile
  base and SGDK's font (`TILE_FONT_INDEX`). With SGDK's default layout that is about 1424 tiles (1536 below the
  plane maps at `0xC000`, minus 16 system and 96 font tiles); the export reports how many the sprites need,
  warns above three quarters of that and reports an error above it; the editor shows the same count in the
  Budget readout (MD modes) and in Check Project. `ms_tiles_fit()` reports at runtime whether they fit; use
  `ms_init_ex(tile_index, palette)` to put them after a game's own tiles or to start at another palette line.
  A streamed export keeps only its slots there (PoP: 39 tiles a player, 65 a scene): `ms_tiles_fit()` checks the
  default slot, the game places the others.
- **Uploads** (streamed exports): SGDK sends the whole DMA queue at the next vertical blank, which carries about
  7200 bytes, the sprite table included (NTSC); more runs into the picture and can show broken sprites for a frame. The
  export and Check Project say how many players can change steps in one frame (PoP: five) and warn when one slot's
  tiles alone take more. SGDK's queue holds 80 transfers, one per run of tiles (`DMA_setMaxQueueSize` for more).
- **Palettes**: 15 colours plus transparent each, in the order of the editor's slots. The runtime loads the palette
  entries (palettes, then palette swaps' versions) into consecutive lines; `ms_palettes_fit()` is false when they
  would run past `PAL3` (start at `PAL0` with `ms_init_ex(tile_index, PAL0)` for one more). With more entries than
  lines, load the ones a screen needs with `ms_load_palette(entry, line)`; a swap's entry without a line draws in
  its palette's line (the colours unswapped), anything else without one in the first line. Check Project and the export warn when a palette's images use more than 15 visible colours
  (similar colours merge) or colours its slots lack.
- **80 hardware sprites** per screen (H40); `ms_set_sprite_limit(64)` in H32 or to leave room for other sprites.
  Pieces that do not fit are counted in `MS_FrameProfile.sprites_dropped`: the pieces drawn last drop. Draws a game
  marks with `ms_set_give_way(level)` (shadows, decorations, effects) give way first, level 1 first and the farthest
  first, as many as the picture asks too much (`draws_given_way`); `ms_end_frame()` resolves it without drawing the
  picture twice ([docs/EXPORT_MODES.md](../../docs/EXPORT_MODES.md#when-a-picture-asks-for-too-many-sprites)).
  `MS_QUEUED_DRAWS` (32) draws can wait from the first that does not fit, `MS_GIVE_WAY_DRAWS` (32) written give-way
  draws make room (define others when compiling `modsprite.c`).
- **Scenes** are baked as one render frame per tick: they play back exactly, but objects cannot be moved
  individually at runtime. Each scene is baked once per mapping; objects with a mapping of their own (Timeline
  inspector ▸ Mapping) keep it in all of them, the others follow the mapping chosen at runtime. The same holds for
  palette swaps (Timeline inspector ▸ Colours), and objects that follow a point of their parent's frames (Follows)
  are baked where the point puts them.
- **Timing**: the runtime counts video frames. Each animation step is exported as its hold at the animation's
  tick rate in whole frames at 60 a second (`playback.console_frames`); rates that do not divide 60 round each
  step, which the editor's preview plays and Check Project notes. A 50 Hz (PAL) console plays everything at 5/6 of
  the speed, which the editor previews with View ▸ Play at 50 Hz.

## Files

- `tools/export_megadrive.py` - bake exporter
- `megadrive_demo/` - self-contained SGDK project
  - `Makefile` - SGDK's `makefile.gen`, plus SGDK's library built with your GCC for release outside Windows
  - `inc/modsprite.h` - runtime API
  - `inc/modsprite_data.h` - generated record types, counts and `MS_EVENT_*` / `MS_HITBOX_*` / `MS_POINT_*` /
    `MS_ROLE_*` constants (a streamed export's also `MS_STREAMED` and the slot sizes)
  - `src/modsprite.c` - renderer and players
  - `src/modsprite_draw.s` - its draw loops in 68000 assembly (for frames of four sprites or more; the C ones in
    `modsprite.c` draw the same, [checked in a ROM](#check-the-runtime-in-a-rom))
  - `src/modsprite_data.c` - generated blob parser and accessors
  - `src/main.c` - demo browser for modules, frames, animations and scenes with live profiling
  - `res/gen/modsprite_blob.bin` - generated data, included by its line in `res/resources.res`

## Regenerate SGDK data

In the editor: **File ▸ Export ▸ Mega Drive (SGDK)...**, choose the game's SGDK project folder (one with the runtime,
`src/modsprite.c`, `src/modsprite_draw.s` and `inc/modsprite.h`, like `megadrive_demo/`) and the mappings. The editor
remembers the folder per project and shows what the game gets.

From the command line (the same exporter; run from the repo root):

```bash
python3 examples/megadrive/tools/export_megadrive.py \
  --project-json examples/pop/PoP_WW.json \
  --output-dir examples/megadrive/megadrive_demo \
  --mapping all
```

`--mapping all` bakes one data set per mapping plus index `0` as `<none>` (no mapping). `--mode parts_streamed` or
`--mode frames_streamed` writes a streamed export ([Streamed exports](#streamed-exports)); the default, `--mode parts`,
keeps every tile in video memory.

Both write `res/gen/modsprite_blob.bin`, `inc/modsprite_data.h` and `src/modsprite_data.c`, and put one line,
`BIN MS_BLOB ...`, into `res/resources.res`. The game's other resources, in that file and in `res/gen`, stay
(earlier exporters replaced the whole file and deleted every image and binary in `res/gen`); only the sprite
sheets of exporters before blob version 3 (`res/gen/var_0000.png` ... and their `SPRITE MS_VAR_...` lines) are
removed.

Both then list what the game would get differently from the editor, the same issues as the editor's
**Tools ▸ Check Project**: errors (something is lost, e.g. a step whose frame was deleted is left out), warnings
(it looks or behaves differently, e.g. more than 15 colours) and a note on video memory. `--strict` makes the
command fail (exit code 1) when there are errors, for build scripts.

Blob version 7 (2026-10-19; a streamed export writes version 8, version 6 with the same): each module's flip offset under
each mapping (`ms_module_flip_offsets`: its width less twice its pivot's x, its height less twice its pivot's y), with
which `ms_draw_module_flipped` mirrors a module in place. Version 6 (2026-10-17), streamed exports only (a resident
export wrote version 5): each render frame's load list, the lists and their runs of tiles; pieces count their tiles
from the slot. Version 5 (2026-10-14): palette
entries (the palettes in slot order, then each palette swap's version of the palettes it changes) with their colour
cycles, the palette entry of every piece (bit 7 set: a scene object's own swap, not remapped at draw time) and the
swaps' entry tables. Version 4 (2026-10-13): several palettes (the
header's spare field counts them, 16 colours each follow in the palette section) and the palette bits in the
pieces' tile offsets. Version 3 (2026-10-11): tiles, pieces and
palette in the blob (no SGDK sprite resources), hitboxes and points, type and role names, sprite count and bounds
per render frame. Version 2 added step events, loop-from, follow-up animation and repeat count. Regenerate the
data with the exporter after updating.

## Build the SGDK demo

The demo expects SGDK in one of these places:

1. `SGDK` environment variable
2. `examples/megadrive/megadrive_demo/third_party/sgdk`

Then build, with `m68k-elf-gcc` (on macOS Homebrew's `m68k-elf-gcc` and `m68k-elf-binutils`), Java (SGDK's resource
compiler) and the host's `cc` and `c++` on the PATH:

```bash
cd examples/megadrive/megadrive_demo
make release
```

This produces `out/release/rom.bin`. Outside Windows the first release build also builds SGDK's library with your
GCC, into `out/sgdk-gcc<version>/libmd.a`, which takes under a minute and happens once: the `lib/libmd.a` SGDK ships
was built by SGDK's GCC 13 with link-time optimisation, and other GCC versions refuse to link it ("bytecode stream ...
generated with LTO version 13.0 instead of the expected 15.1"). The demo's `Makefile` runs SGDK's own library makefile
(`makelib.gen`, its release flags) on the vendored sources, builds SGDK's Z80 assembler and converter (`sjasm`,
`bintos`) from its `tools` folder, and compiles SGDK as C17, GCC 13's default (GCC 15's C23 makes `bool` a keyword, and
one of SGDK's sources no longer matches its header). The library is built again when SGDK changes; `make clean`
removes it with the rest of `out/`, `make sgdk-lib` builds only the library, and `SGDK_LIB_DIR=...` keeps it elsewhere,
for a game whose build deletes `out/` each time. A game with a `Makefile` of its own copies the block after
`include $(SGDK)/makefile.gen`. The vendored SGDK sources are a little newer than its prebuilt libraries (2.12, for
example MegaWiFi's `ssf_ed_pro` and `ssf_ed_x7`); the library built here matches the headers. On Windows SGDK's own
GCC 13 links `lib/libmd.a` as it is.

`make debug CONVSYM=true` builds `out/debug/rom.bin` with SGDK's debug library (`lib/libmd_debug.a`, which has no
link-time code, so any GCC links it) and debug symbols; `CONVSYM=true` is only needed when `convsym` is not on the PATH
(common outside Windows). The demo's own code is compiled with `-O3` in both builds; SGDK's library and link-time
optimisation make release faster: in the Swordfight a frame keeps the 68000 busy for 52 lines instead of 64
([Performance](#performance)).

With link-time optimisation GCC sees inside SGDK: memory that only a DMA reads looks unused to it, so it can drop the
stores that fill a local array passed to, for example, `VDP_loadTileData(tiles, index, count, DMA)`, and the DMA copies
whatever the stack held (the demo's hitbox marks came out as garbage until they were copied with `CPU`). Keep data that
a DMA copies at once in a static or global buffer, as the runtime does, or copy it with `CPU`; `DMA_QUEUE` needs a
buffer that lasts until the vertical blank anyway.

## Check the runtime in a ROM

`tools/check_megadrive_rom.py` (from the repository root) builds the runtime into a ROM and checks what it draws on the
console against the host build that the tests compare with the editor. For each project it exports the project into a
copy of the demo with a probe program as its `main.c`, builds it (`make debug`) and plays it in BlastEm through its GDB
stub (`blastem ROM -D`), stopped after every draw: every frame at three places, as it is and mirrored, every module,
crowds of one frame past the 80 sprites, each scene at a few moments with every mapping, an animation drawn twice
(the second time with another mapping and palette swap) and twice facing itself, mirrored each way, a game's own
sprites across the edges, the planning queries' answers and every frame's hitboxes and points mirrored, copies of a
few frames, and pictures of many draws as they are, as a game that measures them would draw them
again and with give-way levels (streamed also through the slot cache). The same probe compiled for the host makes the
same calls. Every sprite table (all 80 entries) and profile must be the host build's, the VDP's sprite table (read
back from video memory) the sprite table cache, video memory the export's tiles (streamed: the slots and the slot
cache's pool after each draw, the host build's), colour RAM the host build's after the colour cycles turned, and the
first scene's 600 frames the host build's. Each draw is timed with the V counter (`--timings FILE` writes them all):

```bash
python3 tools/check_megadrive_rom.py --mode parts_streamed
```

Without projects it checks PoP, Sonic and the Adventurer (about a minute and a half a mode); `--mode` takes the three
modes, `--c` builds the C loops alone (to compare the two in time), `--release` builds with `make release` (as games
ship; SGDK's library is built once for the run), `--keep DIR` keeps the builds. It needs SGDK's
toolchain (`m68k-elf-gcc`, `make`, Java; the SGDK in `third_party`), the host's `cc` and BlastEm (`--blastem`,
`$BLASTEM`, the PATH or `/Applications/blastem*`). Run it in the three modes after changing `modsprite.c` or
`modsprite_draw.s`; the release workflow runs it so too (its `megadrive` job, on macOS, before anything is published).

## Runtime API summary (`inc/modsprite.h`)

- `ms_init()` / `ms_init_ex(tile_index, palette)`, `ms_tiles_fit()`, `ms_tiles_used()`, `ms_palettes_fit()`
- Streamed exports: `ms_slot_init(&slot, tile_index)`, `ms_set_slot(&slot)` (`NULL`: the default slot) before drawing
  through it, `ms_slot_tiles()` / `ms_scene_slot_tiles()` (a player's and a scene's slot; 0 in a resident export)
- Palettes: `ms_set_palette_swap(index)` recolours everything drawn afterwards (0 = the palettes as they are),
  like the mapping; `ms_load_palette(entry, line)` / `ms_palette_line(entry)` when there are more entries than
  lines; `ms_palette_tick()` once per video frame turns the colour cycles of the loaded entries
  (`MS_PALETTE_SWAP_COUNT`, `ms_palette_swap_name()`, `ms_find_palette_swap_index_by_id()`)
- Per video frame: `ms_begin_frame()`, any number of draw calls, `ms_end_frame()`, then `SYS_doVBlankProcess()`
- `ms_draw_module(index, x, y)`, `ms_draw_frame(index, x, y)`; `ms_draw_module_flipped(index, x, y, flip)`,
  `ms_draw_frame_flipped(index, x, y, flip)` (bit 0 mirrors left to right, bit 1 top to bottom: a frame about its
  origin, like a mirrored step, a module in place, like a part mirrored in a frame (its pivot at x, y); each hardware
  sprite is mirrored and gets the flip bits, so the export stores a frame once for both directions)
- Before drawing: `ms_frame_sprites(index)` / `ms_module_sprites(index)` (the hardware sprites it takes under the
  current mapping) and `ms_frame_bounds(index, flip, &box)` / `ms_module_bounds(index, flip, &box)` (where they lie,
  `MS_Bounds`; FALSE when it shows nothing), from the export's records: a game can plan a picture without drawing it
- `ms_set_give_way(level)` / `ms_get_give_way()`: what gives way past the sprite limit ([Limits](#limits))
- Streamed exports: the slot cache, `ms_slot_cache_init(tile_index, tile_count)`, `ms_use_slot_cache()`,
  `ms_slot_cache_clear()`; a game's own slots: `ms_frame_load_list(index)`, `ms_module_load_list(index)`,
  `ms_load_list_tiles(list)`
- `ms_anim_player_*()` for animation playback. The player follows the editor exactly
  (`tests/test_megadrive_runtime_player.py`): *Loop* plays the steps before `loop_start` once and then loops the rest,
  repeat counts end an animation, and an animation that ends continues with its follow-up
  (`player.animation_index` changes; `player.finished` is set only when there is none).
- `ms_draw_anim_player_flipped(&player, x, y, flip)` draws the step mirrored about the draw point (`flip` as for
  frames), as the Animations tab's **Mirror** preview shows it (H 1, V 2, H + V 3): the step's offset, flips and turn
  are in its render frame and mirror with it, so a character that turns around needs each animation once.
  `ms_draw_anim_player_as_flipped(&player, mapping, swap, x, y, flip)` does the same with another mapping and palette
  swap for that draw (another mapping alone: pass `ms_get_palette_swap()`).
- Animation events (editor: Animations ▸ step ▸ Events; `MS_EVENT_<NAME>` in `inc/modsprite_data.h`):
  - `ms_anim_player_has_event(&player, MS_EVENT_HIT_ON)` — active while the step shows (hit windows,
    invulnerability, cancel windows)
  - `ms_anim_player_event_started(&player, MS_EVENT_SFX)` — only on the tick the step starts (sounds, spawns,
    footsteps); `ms_anim_player_event_value(&player, MS_EVENT_SFX, 0)` gives the step's value
- Hitboxes and points (editor: Frames ▸ Hitboxes / Points, with types and roles), relative to the draw
  position and moved like the animation step (flip, rotation, offset). A point marks a pixel, so a mirrored step
  puts it on the mirrored pixel (`x` becomes `-x - 1`), where the art is:
  ```c
  const MS_Hitbox *boxes;
  u16 count = ms_anim_player_hitboxes(&player, &boxes);
  const MS_Hitbox *hurt = ms_find_hitbox(boxes, count, MS_HITBOX_HURT, MS_NO_ROLE);  /* type "Hurt" */
  if (hurt) check_overlap(x + hurt->x, y + hurt->y, hurt->w, hurt->h);
  ```
  `ms_frame_hitboxes()` / `ms_frame_points()` / `ms_anim_player_points()` / `ms_find_point()` work the same way.
  A step or frame drawn mirrored (`ms_draw_anim_player_flipped`, `ms_draw_frame_flipped`) has its boxes and points
  mirrored with `ms_flip_hitbox(box, flip, &out)` / `ms_flip_point(point, flip, &out)`, as the draw mirrors the art (a
  box's `x` becomes `-x - w`, a point's `-x - 1`); they return `out`, and NULL for NULL, so they take what
  `ms_find_hitbox()` gives:
  ```c
  MS_Hitbox box;
  const MS_Hitbox *blade = ms_flip_hitbox(ms_find_hitbox(boxes, count, MS_HITBOX_ATTACK, MS_ROLE_BLADE), flip, &box);
  ```
  Types are numbered in the editor's list order (`MS_HITBOX_<NAME>`, `MS_POINT_<NAME>`), roles alphabetically
  (`MS_ROLE_<NAME>`, `MS_NO_ROLE` for none); a box whose type was deleted has type `MS_UNKNOWN_TYPE`.
  The Prince of Persia example has them: `MS_HITBOX_HURT` boxes `head` and `body` on every frame, an
  `MS_HITBOX_ATTACK` box `blade` on the striking frames, points `blade_tip` (`MS_POINT_WEAPON`, in combat) and
  `feet` (`MS_POINT_GROUND`), and the events `hit` (the step a blade strikes) and `footstep` (a run's landing).
- `ms_scene_player_*()` for scene playback
- `ms_set_mapping(index)` re-skins everything drawn afterwards. The players keep no mapping of their own, so
  several characters share one set of animations and differ only in the mapping they are drawn with, the way
  AuroraGT games call the sprite's mapping setter before drawing each character:
  ```c
  ms_draw_anim_player(&hero, hero_x, hero_y);                              /* active mapping */
  ms_draw_anim_player_mapped(&guard, guard_mapping, guard_x, guard_y);    /* active one stays */
  ms_draw_anim_player_as(&guard, guard_mapping, blue_swap, guard_x, guard_y);  /* re-skinned and recoloured */
  ms_draw_anim_player_as_flipped(&guard, guard_mapping, blue_swap, guard_x, guard_y, 1);  /* facing the hero */
  ```
- `ms_get_frame_profile()`: render calls, parts, hardware sprites used and dropped this frame, tiles uploaded
  (streamed exports), the slot cache's slots used and draws left out, the draws that gave way

## Demo controls

The demo starts on the project's first scene, playing: in the Prince of Persia example the *Swordfight*, where the
Prince fights a guard drawn from the same animations with his own mapping and the *Blue guard* palette swap. Each
button does one thing:

| Button | |
|---|---|
| `UP / DOWN` | what to show: scenes, animations, frames, modules |
| `LEFT / RIGHT` | previous / next; held, it repeats and then runs |
| `A` | play / pause |
| `B` | hitboxes (red corner marks) and points (green crosses), in animations and frames |
| `C` | change the look: every mapping with every palette swap (`ms_set_mapping`, `ms_set_palette_swap`); with animations last *side by side*: the animation as it is and, on the right, re-skinned and recoloured for that draw only (`ms_draw_anim_player_as`: the guard in blue) |
| `START` | the controls and what the frame costs |

The screen shows what plays and its look; a step's events appear under it as they fire (`hit`, `footstep`).
`START` adds the frame rate, the CPU load, the time drawing and queueing the sprite table take (measured with the
V counter, so in steps of one scanline, about 64 µs), parts, hardware sprites (and dropped ones), tiles and, with
`B`, the hitboxes and points shown. Text is redrawn one line per frame at most, because drawing many lines in one
frame drops it; with the panel closed only the title, the look and the events are drawn. Built from a streamed
export, the panel also shows the most tiles one frame uploaded, and the side-by-side look draws its second character
through a slot of its own.

## Tests

- `tests/test_megadrive_runtime_draw.py` compiles `src/modsprite.c` for the host, lets it draw every frame of the
  testbeds in the middle of the screen and across its edges, rasterises the sprite table from the exported
  tiles like the VDP and compares it with the editor's renderer pixel by pixel; it also checks the C record
  sizes against the blob. It also draws two players of one animation with different mappings into one sprite
  table (`ms_draw_anim_player_mapped`), and once with a palette swap (`ms_draw_anim_player_as`: the guard's sprites
  take the swap's palette line, the tiles are the same), scene objects with a swap of their own, and colour cycles
  turned by `ms_palette_tick()` against the editor's preview. Every step of the testbeds' animations mirrored each
  way (`ms_draw_anim_player_flipped`) against the editor's Mirror preview, with its hitboxes and points
  (`ms_flip_hitbox`, `ms_flip_point`), and a guard facing the hero (`ms_draw_anim_player_as_flipped`). Every module of
  the testbeds under every mapping mirrored in place, the sprite counts and bounds the queries give against the drawn
  sprite table, and crowds with
  give-way levels: the draws that give way as the reference choice in `tests/runtime_models.py` says, and the sprite
  table exactly the one the runtime draws without levels from the draws that stay.
- `tests/test_megadrive_streaming.py` does the same with streamed exports, rasterising from the video memory the
  runtime uploaded into: every frame of the testbeds through the default slot (uploads only when the list changes),
  two players in two slots, every module and the Swordfight in every mapping as the resident export draws them, a run
  the DMA queue refuses queued again, the version 8 header as the generated parser reads it, and the slot cache: five
  actors against the reference cache (uploads, slots used, draws left out) and the editor, a cache too small for a
  frame, and crowds with give-way levels drawn through it.
- `tests/test_megadrive_scenes.py` checks that scene objects are placed like on the Timeline stage (root motion
  mirrored and turned with the object, objects that follow a point of their parent's frames) and keep a mapping of
  their own in every baked mapping.
- `tests/test_megadrive_runtime_player.py` compiles the C animation player and compares it with the editor's preview
  tick by tick.
- `tests/test_megadrive_markers.py` checks hitbox / point export (types, roles, step transforms, defines).
- `tests/test_megadrive_export_project.py` checks the export into a game folder (its own resources stay) and the
  issues it reports.
- `tests/test_hardware_budget.py` keeps the editor's Budget overlay in step with the exporter.
- The host builds draw with the runtime's C loops; `tools/check_megadrive_rom.py` (SGDK and BlastEm, not a unit test)
  runs the 68000 ones in a ROM against that host build ([Check the runtime in a ROM](#check-the-runtime-in-a-rom)).

## Troubleshooting

- `Error: blob load failed` in the demo: regenerate the data with the exporter, rebuild (`make release`) and run
  the fresh `out/release/rom.bin`.
- `make release` fails while it builds SGDK's library: it needs the host's `cc` and `c++` (Xcode's command line tools
  on macOS, `build-essential` on Linux) for SGDK's Z80 tools and Java for its resource compiler. After updating
  `m68k-elf-gcc` the next release build makes a library for the new version (`out/sgdk-gcc<version>`).
- `Error: tiles do not fit in VRAM`: the project needs more tiles than there is room for between the tile base
  and SGDK's font. Reduce the images: every module, every rotation of a module and every mapping target is
  baked as its own image (the export reports the tile count; exporting fewer mappings also helps). Or export
  streamed (`--mode parts_streamed`): video memory then holds only the slots.
