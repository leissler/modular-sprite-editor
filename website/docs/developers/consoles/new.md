# Adding a console

The editor is built for more consoles than it exports for today, and every console that gets an exporter gets the same as the others: the same runtime API, the same export modes, the same checks. This page is for developers who want their platform supported, or who write an exporter for their own engine: what a console takes, and where each part lives in the source code. The repository's `docs/CONSOLES.md` is the full checklist, with each item for the Mega Drive and the SNES.

## The principle

- **Every console gets the same.** When one console gains a feature, the others get it too, or it is listed as a gap. A game written against the runtime API on one console moves to another without relearning anything.
- **Console code stays apart.** Everything specific to a console is named after its key in the console database (`megadrive`, `snes`): its folder `examples/<key>`, its exporter `export_<key>`, its demo `<key>_demo`, its tests `tests/test_<key>_*`. What is common lives in shared modules, never copied.
- **Exact by construction.** A console's runtime draws what the editor shows, and tests prove it pixel for pixel.

## What a console takes

### 1. An entry in the console database

`consoles.py` describes a console's hardware: screen modes (size, sprites per screen and per line, sprite pixels per line), the sprite hardware (tile size, bits per pixel, sprite sizes, flips), the palette hardware (colours per palette, the transparent index, palettes for sprites, the colour model: bits per channel or a fixed set of colours), refresh rates and the budget setups. This alone makes the console a project target in the editor: the palettes follow it, the budget overlay counts its sprites per screen and per line, the Timeline shows its screen. The NES, the Game Boy Advance and the Game Boy are at this stage.

### 2. An exporter

A Python module, `examples/<key>/tools/export_<key>.py`, that subclasses `console_bake.ConsoleBake`. The shared bake walks the project as the editor draws it, once per mapping: modules, frames with nested frames flattened into module parts (flips, quarter turns, parts a hardware flip cannot show drawn as pictures of their own), frames stored whole, animation steps with the game's timing, events, loop-from steps, follow-ups and repeat counts, scene samples with each object's mapping and palette swap, palette entries, hitboxes and points. The console's exporter adds what is its own:

- `_store_part(image, palette, entry)`: a part's picture, in the palette's slots and drawn from a palette entry, stored as the hardware draws it (tiles, hardware sprites); it returns a number for it, the same for the same picture and entry.
- `_stored_part(number)`: that part's padded size and hardware sprites, so the export modes can be measured.
- The data and the generated code the console's runtime reads, in the layout that suits the console.
- `export_project()` (the one entry point for the command line and the editor), `report_line()` (the editor's report), `bake_context()` (the bake without writing anything, for measuring) and `main()`, whose command line comes from `console_bake.export_arguments` so every exporter takes the same options.

### 3. An entry in the export table

`console_exports.py` is the one table of the consoles the editor exports for, and nothing else names an exporter: File ▸ Export, its dialog, Check Project, the smoke test, the editor's builds and the Windows kit loop over it. An entry names the console, its SDK, the runtime's files, the dialog's text, where the editor remembers the choices, the setups the export bakes for, and the export modes the runtime plays.

### 4. A runtime with the common API

A C library in the console's SDK with the same `ms_*` functions and the same meaning ([API reference](../api.md)): render frames drawn into the console's sprite table, the animation player tick for tick, mappings and palette swaps per draw, colour cycles, hitboxes, points and events, scenes, the planning queries, give-way levels, and, where the console streams, slots, the slot cache and load lists. Start-up and the end of a frame follow the SDK; the hot loops may be in the console's assembly, with C versions the tests run.

### 5. Video memory and checks in the editor

A budget profile with a video memory model (`hardware_budget.py`) that counts tiles exactly the way the exporter stores them, tested against the exporter, so the overlay, the readouts and Check Project tell the truth. Check Project gets the console's tile and palette checks (`project_check.<key>_tile_issue`, `<key>_palette_issue`, and stream checks where it streams): whatever the export leaves out or changes shows up there.

### 6. Tests and a demo

- The runtime compiled for a PC against a stand-in for the SDK, drawing every frame and module of the example projects as they are and mirrored, and every animation step mirrored each way, compared with the editor's pictures pixel for pixel; the animation player compared tick by tick; hitboxes and points, as they are and mirrored.
- A demo, `examples/<key>/<key>_demo`, that starts on the first scene with one button per feature, and a README.
- The runtime in a ROM, played in an emulator against the PC build in the release workflow.
- A command-line exporter built for Windows, macOS and Linux, checked to write exactly what the script writes.

## The documentation

Each console gets two pages here, with the same sections as the [Mega Drive's](megadrive.md) and the [SNES's](snes.md): set-up, a complete program, the console's own functions, what the runtime touches, video memory, palettes, sprite limits, what it costs, and its data format record by record. It gets a row in the tables of the [Consoles](index.md) page. The general pages do not change.

## Talk to us

A console is a larger piece of work, best planned together: see [Get help](../../reference/support.md) for how to reach the maintainers, or open an issue in the [source repository](https://github.com/leissler/modular-sprite-editor).
