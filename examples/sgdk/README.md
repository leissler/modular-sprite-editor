# SGDK Example (Mega Drive)

This folder contains a complete SGDK pipeline for modular sprite rendering from your editor JSON:

- **Input assets**: `PoP_WW.json` + `modules_POP.bmp` (any project works, e.g. `examples/sonic/sonic.json`)
- **Bake step**: a Python exporter turns the JSON into one compact binary blob
- **Runtime**: a small SGDK/C library that draws a **module**, **frame**, **animation** or **timeline scene**, plays
  animations exactly like the editor, and gives the game the hitboxes and points of what it shows

## How it works

Mega Drive code should not parse JSON or transform images per frame, so the exporter bakes everything into
`res/gen/modsprite_blob.bin` (included by `res/resources.res` as `BIN MS_BLOB ...`, parsed by the generated
`src/modsprite_data.c`):

- **Tiles and palette**: every module image as it is used (flipped parts reuse the same tiles through the
  sprite's flip bits; rotations are baked), cut into hardware sprites of at most 32×32 on the same grid as the
  editor's Budget overlay (`hardware_budget.py`), as 4 bpp tiles in VDP order, deduplicated; one 15-colour
  palette.
- **Pieces**: the hardware sprites of each image, laid out once for every flip combination a part uses.
- **Render frames**: the parts of each frame, animation step and scene sample, with their hitboxes and points,
  sprite count and bounds; animations, scenes, mappings, step events and all names.

At start `ms_init()` loads all tiles into VRAM (at `TILE_USER_INDEX`) and the palette (into `PAL1`). Drawing
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

- **VRAM**: all tiles stay resident. `PoP_WW` needs 309 tiles, `sonic` 658; they must fit between the tile
  base and SGDK's font (`TILE_FONT_INDEX`). `ms_tiles_fit()` reports whether they did; use
  `ms_init_ex(tile_index, palette)` to put them after a game's own tiles or into another palette.
- **One palette**: 15 colours plus transparent. The exporter warns when the images use more and merges
  similar colours.
- **80 hardware sprites** per screen (H40); `ms_set_sprite_limit(64)` in H32 or to leave room for other sprites.
  Pieces that do not fit are counted in `MS_FrameProfile.sprites_dropped`.
- **Scenes** are baked as one render frame per tick: they play back exactly, but objects cannot be moved
  individually at runtime. Each scene is baked once per mapping; objects with a mapping of their own (Timeline
  inspector ▸ Mapping) keep it in all of them, the others follow the mapping chosen at runtime.

## Files

- `tools/export_sgdk_example.py` - bake exporter
- `sgdk_demo/` - self-contained SGDK project
  - `inc/modsprite.h` - runtime API
  - `inc/modsprite_data.h` - generated record types, counts and `MS_EVENT_*` / `MS_HITBOX_*` / `MS_POINT_*` /
    `MS_ROLE_*` constants
  - `src/modsprite.c` - renderer and players
  - `src/modsprite_data.c` - generated blob parser and accessors
  - `src/main.c` - demo browser for modules, frames, animations and scenes with live profiling
  - `res/resources.res` + `res/gen/modsprite_blob.bin` - generated data

## Regenerate SGDK data

Run from the repo root:

```bash
python3 examples/sgdk/tools/export_sgdk_example.py \
  --project-json examples/sgdk/PoP_WW.json \
  --output-demo-dir examples/sgdk/sgdk_demo \
  --mapping all
```

`--mapping all` bakes one data set per mapping plus index `0` as `<none>` (no mapping).

Blob version 3 (2026-10-11): tiles, pieces and palette in the blob (no SGDK sprite resources), hitboxes and
points, type and role names, sprite count and bounds per render frame. Version 2 added step events, loop-from,
follow-up animation and repeat count. Regenerate the data with the exporter after updating.

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

- `ms_init()` / `ms_init_ex(tile_index, palette)`, `ms_tiles_fit()`, `ms_tiles_used()`
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
  position and moved like the animation step (flip, rotation, offset):
  ```c
  const MS_Hitbox *boxes;
  u16 count = ms_anim_player_hitboxes(&player, &boxes);
  const MS_Hitbox *hurt = ms_find_hitbox(boxes, count, MS_HITBOX_HURT, MS_NO_ROLE);  /* type "Hurt" */
  if (hurt) check_overlap(x + hurt->x, y + hurt->y, hurt->w, hurt->h);
  ```
  `ms_frame_hitboxes()` / `ms_frame_points()` / `ms_anim_player_points()` / `ms_find_point()` work the same way.
  Types are numbered in the editor's list order (`MS_HITBOX_<NAME>`, `MS_POINT_<NAME>`), roles alphabetically
  (`MS_ROLE_<NAME>`, `MS_NO_ROLE` for none); a box whose type was deleted has type `MS_UNKNOWN_TYPE`.
- `ms_scene_player_*()` for scene playback
- `ms_set_mapping(index)` re-skins everything drawn afterwards
- `ms_get_frame_profile()`: render calls, parts, hardware sprites used and dropped this frame

## Demo controls

- `UP / DOWN`: switch unit type (`Module`, `Frame`, `Animation`, `Scene`)
- `LEFT / RIGHT`: previous / next entry; `X / Y`: jump `-10 / +10`
- `A`: pause/resume playback; `B`: reset the player
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
  sizes against the blob.
- `tests/test_sgdk_scenes.py` checks that scene objects are placed like on the Timeline stage (root motion
  mirrored and turned with the object) and keep a mapping of their own in every baked mapping.
- `tests/test_runtime_player.py` compiles the C animation player and compares it with the editor's preview
  tick by tick.
- `tests/test_sgdk_markers.py` checks hitbox / point export (types, roles, step transforms, defines).
- `tests/test_hardware_budget.py` keeps the editor's Budget overlay in step with the exporter.

## Troubleshooting

- `Error: blob load failed` in the demo: regenerate the data with the exporter, rebuild
  (`make debug CONVSYM=true`) and run the fresh `out/debug/rom.bin`.
- `Error: tiles do not fit in VRAM`: the project needs more tiles than there is room for between the tile base
  and SGDK's font. Reduce the images: every module, every rotation of a module and every mapping target is
  baked as its own image (the exporter prints the tile count).
