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

At start `ms_init()` loads all tiles into VRAM (at `TILE_USER_INDEX`) and the palette entries into consecutive
palette lines from `PAL1` (the palettes first, then the swaps' versions); a table maps every entry to its line, and
drawing puts the line into each sprite's palette bits (entries a scene object fixed with a swap of its own keep it).
Drawing
then only writes SGDK's sprite table cache: a part becomes its pieces plus the part's position and flip bits;
frames that lie fully on screen are copied without per-sprite tests, others are culled sprite by sprite (a
sprite at x = -128 would hide the sprites behind it). `ms_end_frame()` queues one sprite-table DMA, which
`SYS_doVBlankProcess()` sends. The runtime does not use SGDK's `SPR_*` sprite engine; add sprites of your own
to the same list with `ms_add_hw_sprite()`.

### Performance

Measured in BlastEm 0.6.2 (`PoP_WW.json`, every animation for one cycle and every frame, scanline-accurate
timing with the VDP V counter; one NTSC frame has 262 lines):

| | old runtime (one SGDK `Sprite` per part) | current runtime |
|---|---|---|
| draw + upload, average | 56 + 47 lines (39 % of a frame) | 14.5 + 4 lines (7 %) |
| worst frame | 98 % of a frame | 11 % |
| dropped frames | 20 | 0 |
| DMA per frame | up to 1400 bytes of tiles | 168 bytes (sprite table) |

### Limits

- **VRAM**: all tiles stay resident. `PoP_WW` needs 305 tiles, `sonic` 620; they must fit between the tile
  base and SGDK's font (`TILE_FONT_INDEX`). With SGDK's default layout that is about 1424 tiles (1536 below the
  plane maps at `0xC000`, minus 16 system and 96 font tiles); the export reports how many the sprites need,
  warns above three quarters of that and reports an error above it; the editor shows the same count in the
  Budget readout (MD modes) and in Check Project. `ms_tiles_fit()` reports at runtime whether they fit; use
  `ms_init_ex(tile_index, palette)` to put them after a game's own tiles or to start at another palette line.
- **Palettes**: 15 colours plus transparent each, in the order of the editor's slots. The runtime loads the palette
  entries (palettes, then palette swaps' versions) into consecutive lines; `ms_palettes_fit()` is false when they
  would run past `PAL3` (start at `PAL0` with `ms_init_ex(tile_index, PAL0)` for one more). With more entries than
  lines, load the ones a screen needs with `ms_load_palette(entry, line)`; a swap's entry without a line draws in
  its palette's line (the colours unswapped), anything else without one in the first line. Check Project and the export warn when a palette's images use more than 15 visible colours
  (similar colours merge) or colours its slots lack.
- **80 hardware sprites** per screen (H40); `ms_set_sprite_limit(64)` in H32 or to leave room for other sprites.
  Pieces that do not fit are counted in `MS_FrameProfile.sprites_dropped`.
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

- `tools/export_sgdk_example.py` - bake exporter
- `sgdk_demo/` - self-contained SGDK project
  - `inc/modsprite.h` - runtime API
  - `inc/modsprite_data.h` - generated record types, counts and `MS_EVENT_*` / `MS_HITBOX_*` / `MS_POINT_*` /
    `MS_ROLE_*` constants
  - `src/modsprite.c` - renderer and players
  - `src/modsprite_data.c` - generated blob parser and accessors
  - `src/main.c` - demo browser for modules, frames, animations and scenes with live profiling
  - `res/gen/modsprite_blob.bin` - generated data, included by its line in `res/resources.res`

## Regenerate SGDK data

In the editor: **File ▸ Export ▸ Mega Drive (SGDK)...**, choose the game's SGDK project folder (one with
`src/modsprite.c` and `inc/modsprite.h`, like `sgdk_demo/`) and the mappings. The editor remembers the folder
per project and shows what the game gets.

From the command line (the same exporter; run from the repo root):

```bash
python3 examples/sgdk/tools/export_sgdk_example.py \
  --project-json examples/sgdk/PoP_WW.json \
  --output-demo-dir examples/sgdk/sgdk_demo \
  --mapping all
```

`--mapping all` bakes one data set per mapping plus index `0` as `<none>` (no mapping).

Both write `res/gen/modsprite_blob.bin`, `inc/modsprite_data.h` and `src/modsprite_data.c`, and put one line,
`BIN MS_BLOB ...`, into `res/resources.res`. The game's other resources, in that file and in `res/gen`, stay
(earlier exporters replaced the whole file and deleted every image and binary in `res/gen`); only the sprite
sheets of exporters before blob version 3 (`res/gen/var_0000.png` ... and their `SPRITE MS_VAR_...` lines) are
removed.

Both then list what the game would get differently from the editor, the same issues as the editor's
**Tools ▸ Check Project**: errors (something is lost, e.g. a step whose frame was deleted is left out), warnings
(it looks or behaves differently, e.g. more than 15 colours) and a note on video memory. `--strict` makes the
command fail (exit code 1) when there are errors, for build scripts.

Blob version 5 (2026-10-14): palette entries (the palettes in slot order, then each palette swap's version of the
palettes it changes) with their colour cycles, the palette entry of every piece (bit 7 set: a scene object's own
swap, not remapped at draw time) and the swaps' entry tables. Version 4 (2026-10-13): several palettes (the
header's spare field counts them, 16 colours each follow in the palette section) and the palette bits in the
pieces' tile offsets. Version 3 (2026-10-11): tiles, pieces and
palette in the blob (no SGDK sprite resources), hitboxes and points, type and role names, sprite count and bounds
per render frame. Version 2 added step events, loop-from, follow-up animation and repeat count. Regenerate the
data with the exporter after updating.

## Build the SGDK demo

The demo expects SGDK in one of these places:

1. `SGDK` environment variable
2. `examples/sgdk/sgdk_demo/third_party/sgdk`

Then build:

```bash
cd examples/sgdk/sgdk_demo
make debug CONVSYM=true
```

This produces `out/debug/rom.bin`. `CONVSYM=true` is only needed when `convsym` is not on the PATH (common
outside Windows). `make release` can fail with an SGDK `libmd.a` LTO-version mismatch on newer GCCs; the demo
`Makefile` builds `debug` with `-O3`, so its timings are representative.

## Runtime API summary (`inc/modsprite.h`)

- `ms_init()` / `ms_init_ex(tile_index, palette)`, `ms_tiles_fit()`, `ms_tiles_used()`, `ms_palettes_fit()`
- Palettes: `ms_set_palette_swap(index)` recolours everything drawn afterwards (0 = the palettes as they are),
  like the mapping; `ms_load_palette(entry, line)` / `ms_palette_line(entry)` when there are more entries than
  lines; `ms_palette_tick()` once per video frame turns the colour cycles of the loaded entries
  (`MS_PALETTE_SWAP_COUNT`, `ms_palette_swap_name()`, `ms_find_palette_swap_index_by_id()`)
- Per video frame: `ms_begin_frame()`, any number of draw calls, `ms_end_frame()`, then `SYS_doVBlankProcess()`
- `ms_draw_module(index, x, y)`, `ms_draw_frame(index, x, y)`
- `ms_anim_player_*()` for animation playback. The player follows the editor exactly
  (`tests/test_runtime_player.py`): *Loop* plays the steps before `loop_start` once and then loops the rest,
  repeat counts end an animation, and an animation that ends continues with its follow-up
  (`player.animation_index` changes; `player.finished` is set only when there is none).
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
  ```
- `ms_get_frame_profile()`: render calls, parts, hardware sprites used and dropped this frame

## Demo controls

- `UP / DOWN`: switch unit type (`Module`, `Frame`, `Animation`, `Scene`)
- `LEFT / RIGHT`: previous / next entry; `X / Y`: jump `-10 / +10`
- `A`: pause/resume playback; `B`: reset the player
- `START + B`: versus view (animations): the animation again on the right, drawn with the next mapping and the
  first palette swap through `ms_draw_anim_player_as` (in the Prince of Persia example: the guard in blue)
- `START` (press and release): cycle the active mapping (`<none>` / mapped variants)
- `START + A`: show hitboxes (red corner marks) and points (green crosses)
- `START + UP / DOWN`: background brightness
- `C`: ID jump editor (`UP / DOWN` character, `LEFT / RIGHT` cursor, `A` apply, `B` cancel, `X` clear,
  `Y` backspace)
- `MODE` / `Z` / `START + C`: minimal HUD (FPS / CPU only) for performance measurement

The HUD shows FPS and CPU load, the time spent drawing and queueing the sprite table (measured with the V
counter, so in steps of one scanline, about 64 µs), parts, hardware sprites and dropped sprites, and the hitbox, point and tile
counts. It redraws one text line per frame at most, because drawing many lines in one frame drops it.

## Tests

- `tests/test_sgdk_runtime_draw.py` compiles `src/modsprite.c` for the host, lets it draw every frame of the
  testbeds in the middle of the screen and across its edges, rasterises the sprite table from the exported
  tiles like the VDP and compares it with the editor's renderer pixel by pixel; it also checks the C record
  sizes against the blob. It also draws two players of one animation with different mappings into one sprite
  table (`ms_draw_anim_player_mapped`), and once with a palette swap (`ms_draw_anim_player_as`: the guard's sprites
  take the swap's palette line, the tiles are the same), scene objects with a swap of their own, and colour cycles
  turned by `ms_palette_tick()` against the editor's preview.
- `tests/test_sgdk_scenes.py` checks that scene objects are placed like on the Timeline stage (root motion
  mirrored and turned with the object, objects that follow a point of their parent's frames) and keep a mapping of
  their own in every baked mapping.
- `tests/test_runtime_player.py` compiles the C animation player and compares it with the editor's preview
  tick by tick.
- `tests/test_sgdk_markers.py` checks hitbox / point export (types, roles, step transforms, defines).
- `tests/test_sgdk_export_project.py` checks the export into a game folder (its own resources stay) and the
  issues it reports.
- `tests/test_hardware_budget.py` keeps the editor's Budget overlay in step with the exporter.

## Troubleshooting

- `Error: blob load failed` in the demo: regenerate the data with the exporter, rebuild
  (`make debug CONVSYM=true`) and run the fresh `out/debug/rom.bin`.
- `Error: tiles do not fit in VRAM`: the project needs more tiles than there is room for between the tile base
  and SGDK's font. Reduce the images: every module, every rotation of a module and every mapping target is
  baked as its own image (the export reports the tile count; exporting fewer mappings also helps).
