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
| Console database | `consoles.py` entry naming its exporter, setups for the budget | `MEGA_DRIVE` | `SNES` |
| Budget with video memory | a `hardware_budget` profile with `vram_model`: tiles counted the way the export stores them, tested against the exporter (`tests/test_hardware_budget.py`) | H40, H32 | six pairs of sprite sizes |
| Check Project | the console's tile and palette checks in `project_check` | `megadrive_tile_issue`, `megadrive_palette_issue` | `snes_tile_issue`, `snes_palette_issue` |
| Exporter | a `console_bake.ConsoleBake` subclass (`_store_part`) and `export_project()`, the one entry point for the command line and the editor | `examples/megadrive/tools/export_megadrive.py` | `examples/snes/tools/export_snes.py` |
| Its warnings | `project_check.console_issue(project, console)` for a project made for another console, the tile and palette checks | yes | yes |
| Command line | `console_bake.export_arguments` (`--project-json`, `--output-dir`, `--mapping`, `--copy-assets`, `--strict`) plus the console's own options | `export_megadrive` | `export_snes` (`--setup`) |
| Command-line download | `build_<console>_exporter.spec`; the release workflow builds it on three platforms and checks it writes what the script writes | `export_megadrive-*` | `export_snes-*` |
| Editor | File ▸ Export ▸ *Console (SDK)*...: dialog, remembered choices, report | `ui/megadrive_export_dialog.py` | `ui/snes_export_dialog.py` |
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
release files, tests, and modules such as `ui/<console>_export_dialog.py`. The SDK appears where people choose:
menus, dialogs and docs ("Mega Drive (SGDK)"). Example projects are console-neutral and live in their own folders
(`examples/pop/`, `examples/sonic/`, `examples/adventurer/`).

## Adding a console

1. **Database**: its `consoles.py` entry (screens, sprites, palettes, setups). The palettes, the budget and the
   Timeline follow; `website/scripts/make_consoles_page.py` regenerates the guide's Consoles page.
2. **Exporter**: `examples/<console>/tools/export_<console>.py` with a `ConsoleBake` subclass that stores each part's
   picture as the hardware draws it, `export_project()`, and `main()` through `console_bake.export_arguments` and
   `print_result`. Its checks go into `project_check`; the budget profile gets a `vram_model` that counts tiles as the
   export stores them (`hardware_budget._stored_blocks`), tested against the exporter.
3. **Editor**: File ▸ Export entry and `ui/<console>_export_dialog.py`, and the exporter in the three editor specs'
   `pathex` and `hiddenimports`; the smoke test exports into a game folder.
4. **Runtime and demo**: `examples/<console>/<console>_demo` with the common C API and the demo; host tests (drawing,
   player, hitboxes and points); an emulator check.
5. **Release**: `build_<console>_exporter.spec` and its build-and-check step in the release workflow, the demo ROM and
   its zip, the Windows kit (the SDK if it runs there, the two scripts), and the docs: README, AGENTS, the guide's
   programmers page, `examples/<console>/README.md`, and this page.
