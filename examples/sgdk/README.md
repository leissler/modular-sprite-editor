# SGDK Example (Mega Drive)

This folder contains a complete SGDK-oriented example pipeline for modular sprite rendering from your editor JSON:

- **Input assets**: `PoP_WW.json` + `modules_POP.bmp`
- **Bake step**: Python exporter converts JSON data into SGDK-friendly resources and a compact binary blob
- **Runtime**: SGDK/C library that can render a **module**, **frame**, **animation**, and **timeline scene**

## Current State

- The SGDK example uses a **binary data blob** (`modsprite_blob.bin`) instead of giant generated C data tables.
- The blob is included in the ROM via `res/resources.res` as:
  - `BIN MS_BLOB "gen/modsprite_blob.bin" ...`
- Runtime data access is loaded from `MS_BLOB` in `src/modsprite_data.c`.
- Selector UI includes unit selection (module/frame/animation/scene), mapping selection, ID jump, and live profiling.

## Why this is baked (not runtime JSON)

Mega Drive runtime code should avoid JSON parsing and expensive per-frame transform work. The exporter bakes data into:

- `res/gen/*.png` sprite resources (including baked transforms for unsupported hardware rotation cases)
- `res/resources.res` resource declarations
- `res/gen/modsprite_blob.bin` data blob loaded by `inc/modsprite_data.h` and `src/modsprite_data.c`

This keeps the SGDK runtime simple and deterministic.

Note: pure X/Y flips are now emitted as per-part hardware H/V flip flags; rotations and other unsupported transforms are still baked.

## Files

- `tools/export_sgdk_example.py` - bake exporter
- `sgdk_demo/` - self-contained SGDK project scaffold
  - `inc/modsprite.h` - reusable runtime API
  - `inc/modsprite_data.h` - generated data declarations + loader API
  - `src/modsprite.c` - renderer/player implementation
  - `src/modsprite_data.c` - generated blob parser + accessors
  - `src/main.c` - demo app cycling module/frame/animation/scene rendering
  - `res/resources.res` + `res/gen/*.png` + `res/gen/modsprite_blob.bin` - generated SGDK resources

## Regenerate SGDK data

Run from repo root:

```bash
python3 examples/sgdk/tools/export_sgdk_example.py \
  --project-json examples/sgdk/PoP_WW.json \
  --output-demo-dir examples/sgdk/sgdk_demo \
  --mapping all
```

`--mapping all` bakes one data set per mapping plus index `0` as `<none>` (no mapping).

## Build the SGDK demo

The demo expects SGDK in one of these places:

1. `SGDK` environment variable
2. `examples/sgdk/sgdk_demo/third_party/sgdk`

Then build:

```bash
cd examples/sgdk/sgdk_demo
make
```

On some macOS/Linux toolchains, `make release` can fail with an SGDK `libmd.a` LTO-version mismatch.
In that case use `make debug` (works with the bundled `libmd_debug.a`).
The demo `Makefile` forces `-O3` for `debug` builds so runtime profiling remains representative.

If your local SGDK toolchain has no `convsym` on PATH (common on non-Windows setups), use:

```bash
cd examples/sgdk/sgdk_demo
make debug CONVSYM=true
```

This produces `out/debug/rom.bin`.

For convenience you can also run `out/rom.bin` if present.

## Runtime API summary (`inc/modsprite.h`)

- `ms_draw_module(index, x, y)`
- `ms_draw_frame(index, x, y)`
- `ms_anim_player_*()` for animation playback/render
- `ms_scene_player_*()` for scene playback/render

The generated blob includes all modules/frames/animations/scenes from the input JSON for each baked mapping.

## Selector UI controls

In `sgdk_demo/src/main.c` the demo now uses an interactive selector UI:

- `UP / DOWN`: switch unit type (`Module`, `Frame`, `Animation`, `Scene`)
- `LEFT / RIGHT`: previous / next entry (by ID)
- `X / Y`: jump `-10 / +10`
- `START`: cycle active mapping (`<none>` / mapped variants)
- `START + UP / DOWN`: increase / decrease background brightness
- `A`: pause/resume playback for animation/scene
- `B`: reset animation/scene player
- `C`: open ID jump editor
- `MODE` / `Z` / `START + C`: toggle minimal HUD (CPU/FPS only) for performance measurement

Live profiling overlay (shown in the selector UI):

- `CPU%` + `FPS` from SGDK runtime
- per-frame modular render cost in `subticks` and `microseconds`
- render stats: render calls, submitted parts, estimated hardware sprites, and sprite add failures

ID jump editor:

- `UP / DOWN`: change character at cursor
- `LEFT / RIGHT`: move cursor
- `A`: apply jump to exact ID
- `B`: cancel
- `X`: clear input
- `Y`: backspace

## Troubleshooting

- If you see `Error: blob load failed` in the demo UI:
  1. Regenerate data with the exporter command above.
  2. Rebuild the ROM (`make debug CONVSYM=true`).
  3. Make sure you run the freshly rebuilt ROM from `out/debug/rom.bin` (or a copied fresh `out/rom.bin`).
- If `make release` fails with LTO mismatch, use `make debug` as described above.
