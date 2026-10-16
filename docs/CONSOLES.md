# Consoles: what supporting one means

The editor knows several consoles, and two of them fully. This page says what "fully" means, so that every console
that gets there gets the same, and none stands out.

## Two levels

**In the console database** (`consoles.py`): screen modes, sprite hardware and sizes, flips, palettes and colour models,
refresh rates and budget setups. A console here can be the project's console (Console, above the tabs): the palettes,
View ▸ Console Colours, the budget overlay (sprites per screen and per line), the Timeline's screen outline and Auto
Modularize follow it. Today: the Mega Drive, the SNES, the NES, the Game Boy Advance and the Game Boy.

**Fully supported**: a game on the console can use the art, drawn, played and checked exactly as the editor shows it.
Today: the Mega Drive (SGDK) and the SNES (PVSnesLib).

## The checklist

Every fully supported console has all of these. When one console gains something, the others get it too, or it is
listed under [Gaps](#gaps).

| | What it is | Mega Drive | SNES |
|---|---|---|---|
| Console database | `consoles.py` entry: screens, sprites, palettes, setups for the budget | `MEGA_DRIVE` | `SNES` |
| Export entry | `console_exports.py`: the one table the editor and the build follow ([below](#the-export-entry)) | `MEGA_DRIVE` | `SNES` |
| Budget with video memory | a `hardware_budget` profile with `vram_model`: tiles counted the way the export stores them, tested against the exporter (`tests/test_hardware_budget.py`) | H40, H32 | six pairs of sprite sizes |
| Check Project | the console's tile and palette checks in `project_check`, `<console>_tile_issue` and `<console>_palette_issue` | `megadrive_tile_issue`, `megadrive_palette_issue` | `snes_tile_issue`, `snes_palette_issue` |
| Exporter | a `console_bake.ConsoleBake` subclass (`_store_part`), `export_project()` (the one entry point for the command line and the editor) and `report_line()` (the editor's report) | `examples/megadrive/tools/export_megadrive.py` | `examples/snes/tools/export_snes.py` |
| Its warnings | `project_check.console_issue(project, console)` for a project made for another console, the tile and palette checks | yes | yes |
| Command line | `console_bake.export_arguments` (`--project-json`, `--output-dir`, `--mapping`, `--copy-assets`, `--strict`) plus the console's own options | `export_megadrive` | `export_snes` (`--setup`) |
| Command-line download | `build_<console>_exporter.spec`; the release workflow builds it on three platforms and checks it writes what the script writes | `export_megadrive-*` | `export_snes-*` |
| Editor | File ▸ Export ▸ *Console (SDK)*...: the dialog every console shares (`ui/console_export_dialog.py`), remembered choices, report; the editor's builds carry the exporter | from the entry | from the entry, with the sprite sizes |
| Runtime | the common C API (`ms_*`): players, mappings and palette swaps per draw, colour cycles, hitboxes, points and events, scenes | `megadrive_demo/src/modsprite.c` | `snes_demo/src/modsprite.c`, `modsprite_draw.asm` |
| Host tests | the runtime compiled for the host against the editor: drawing pixel for pixel, the player tick by tick, hitboxes and points | `tests/test_megadrive_runtime_draw.py`, `_runtime_player.py`, `_markers.py`, `_scenes.py` | `tests/test_snes_runtime_draw.py`, `_runtime_player.py` |
| Demo | `examples/<console>/<console>_demo`: starts on the first scene, one button per feature, scenes drawn where the Timeline's screen outline puts them (`tests/test_scene_ops.py`) | yes | yes |
| Emulator check in CI | the demo's runtime in a ROM, run in an emulator against the host build | no | `tools/check_snes_rom.py`, `tools/compare_snes_roms.py` (Mesen 2) |
| Demo download | `ModularSpriteEditor-<console>-demo.zip` on the release page: the ROM and its project | no | `ModularSpriteEditor-snes-demo.zip` |
| Windows kit | the demo with its SDK, `export_to_<console>.bat`, `build_<console>_demo.bat` | yes | yes |
| Docs | `examples/<console>/README.md`, a section of the guide's programmers page, README, AGENTS | yes | yes |

## Gaps

- The Mega Drive has no emulator check in CI and no demo download yet; the SNES has both. Its runtime is plain C, so the
  host tests cover more of it than of the SNES's, but nothing runs its ROM automatically.

## Names

Everything console-specific is named after the console's key in `consoles.py`: `megadrive`, `snes`, later `nes`,
`gba`, `gameboy`. That covers folders under `examples/`, exporter scripts and executables, specs, the kit's scripts,
release files, tests and checks (`project_check.<console>_tile_issue`). `console_exports.py` finds them by these
names, and `tests/test_console_exports.py` checks they are there. The SDK appears where people choose: menus, dialogs
and docs ("Mega Drive (SGDK)"). Example projects are console-neutral and live in their own folders (`examples/pop/`,
`examples/sonic/`, `examples/adventurer/`).

## The export entry

`console_exports.py` has one `ConsoleExport` per console with an export; the editor and the build keep no list of
exporters of their own. An entry holds what differs in substance:

| Field | What it is | Mega Drive | SNES |
|---|---|---|---|
| `console`, `sdk` | the `consoles.py` entry, the SDK the menus name (`Console.exporter` reads it) | `MEGA_DRIVE`, SGDK | `SNES`, PVSnesLib |
| `runtime` | the files a game folder needs (the demo has them) | `src/modsprite.c`, `inc/modsprite.h` | the same and `src/modsprite_draw.asm` |
| `intro` | the dialog's text: what the export writes where (`{runtime}` names the runtime's files) | the blob, the header and parser, a line in `res/resources.res` | the ROM bank chunks, `modsprite_chunks.asm`, the header and parser, `modsprite_rom.mk` |
| `preference` | where the editor remembers the folder, mappings and setup per project (keep it when renaming) | `MegaDriveExport` (earlier `SGDKExport`) | `SNESExport` |
| `setups` | the export bakes for one of the console's setups: the dialog's row for them | none | Sprite sizes |
| `tiles_about` | the tiles a game has depend on its video memory layout (readouts: "~1424") | yes | no |
| `sdk_folder`, `sdk_in_git`, `sdk_keep`, `sdk_needs` | where the demo finds its SDK, whether it is in git (else the kit is given it: `--sdk KEY=DIR`), what the Windows kit takes of it and what must be there | SGDK, in git | PVSnesLib's Windows release |

Everything else comes from the console's key: the exporter (`examples/<console>/tools/export_<console>.py`), its spec,
the demo (`examples/<console>/<console>_demo`), the README, the checks and the kit's scripts.

What follows the entry, with no code of its own:

- File ▸ Export ▸ *Console (SDK)*..., the dialog (title, text, folder, mappings, the setups row with the tiles each setup
  needs), the question when the folder has no runtime, the export and its report;
- the remembered choices;
- Check Project's video memory for the project's console (`check_dialog.memory_issues`: the entry's tile check) and the
  budget readout's "~";
- the editor's three specs (`pathex`, `hiddenimports`): every built editor carries every exporter;
- the Windows kit (`tools/make_windows_kit.py`): every exporter from `--exporters`, every demo with its README and the
  part of its SDK the entry names;
- the GUI smoke test: one step per entry, through the menu item (dialog, export into a game folder with the runtime,
  the tiles the budget counted, the report, the choices remembered);
- `tests/test_console_exports.py`: the exporter imports and has `export_project` (with `setup_key` exactly where the
  entry has setups), `report_line` and `main`; the spec builds it; the demo has the runtime; the README, the kit's
  scripts and the checks exist; a small project exports into a game folder with the tiles the budget counts; the
  editor specs bundle it.

## What is still per console

Code and files that are the console's own, by design or because hand-written is simpler than generated:

- `consoles.py`: the hardware entry (screens, sprites, palettes, setups).
- `console_exports.py`: the export entry.
- `examples/<console>/`: the exporter (`ConsoleBake` subclass, `export_project`, `report_line`, `main`), the runtime,
  the demo, the README.
- `hardware_budget.py`: how the export stores tiles (`_stored_blocks`, by the profile's `vram_model`), and its cut in
  `sprite_cut.py` where it is new; `project_check.py`: `<console>_tile_issue` and `<console>_palette_issue`.
- Tests: the runtime on the host (drawing, the player, hitboxes and points), the exporter's own tests.
- `build_<console>_exporter.spec`: another console's, with the three names changed.
- `packaging/windows_kit/`: `export_to_<console>.bat`, `build_<console>_demo.bat`, the README's section.
- The release workflow (hand-written YAML), in `.github/workflows/build-and-release.yml`:
  - the build job's *Build and test the ... exporter* step (the projects it compares, what must fail);
  - on Windows, for an SDK not in git: its download, cache and unpack steps and `--sdk <console>=DIR` on the kit's
    line; the kit test's ROM builds with the two scripts;
  - the console's own jobs: today `snes` (the demo's data exported again, the ROM, the emulator check, the demo zip)
    and `snes-kit` (the Windows kit's ROM against the Linux one), and the release job's `needs`;
  - the demo download: `tools/make_snes_demo_zip.py` and `packaging/snes_demo/` (the SNES only so far).
- Docs: README, AGENTS, the guide's programmers page, `examples/<console>/README.md`, this page's columns.

## Adding a console

1. **Database**: its `consoles.py` entry (screens, sprites, palettes, setups); the NES, the Game Boy Advance and the
   Game Boy have one. The palettes, the budget and the Timeline follow; `website/scripts/make_consoles_page.py`
   regenerates the guide's Consoles page.
2. **Exporter**: `examples/<console>/tools/export_<console>.py` with a `ConsoleBake` subclass that stores each part's
   picture as the hardware draws it, `export_project()`, `report_line()`, and `main()` through
   `console_bake.export_arguments` and `print_result`. Its checks go into `project_check` as `<console>_tile_issue`
   and `<console>_palette_issue`; `hardware_budget._stored_blocks` counts tiles as the export stores them, tested
   against the exporter.
3. **Export entry**: one `ConsoleExport` in `console_exports.py`. The editor (menu, dialog, remembered choices,
   report, Check Project), the smoke test, the editor specs and the Windows kit follow; `tests/test_console_exports.py`
   says what is still missing.
4. **Runtime and demo**: `examples/<console>/<console>_demo` with the common C API and the demo; host tests (drawing,
   player, hitboxes and points); an emulator check.
5. **Release**: `build_<console>_exporter.spec`, the kit's two scripts, the workflow's steps listed
   [above](#what-is-still-per-console), the demo ROM and its zip, and the docs: README, AGENTS, the guide's
   programmers page, `examples/<console>/README.md`, and this page.
