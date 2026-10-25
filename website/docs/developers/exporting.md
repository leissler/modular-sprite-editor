# Export from your build

Every console export runs in the editor (**File ▸ Export ▸** *Console (SDK)*...) and from the command line, with the same code and the same results. The command line suits a game's build: export the artist's project every time the game is built, and the data can never be out of date.

## The exporters

| Console | Download (no Python needed) | From the source code |
|---|---|---|
| Mega Drive | `export_megadrive` | `python3 examples/megadrive/tools/export_megadrive.py` |
| SNES | `export_snes` | `python3 examples/snes/tools/export_snes.py` |

The downloads, for Windows, macOS and Linux, are on the [releases page](https://github.com/leissler/modular-sprite-editor/releases): the scripts built into programs, each checked in every release to write exactly what its script writes. The scripts run from the repository's root with Python 3.10 or newer and Pillow; exporting needs nothing else.

```bash
export_megadrive --project-json art/hero.json --output-dir game
export_snes --project-json art/hero.json --output-dir snes_game --mode parts_streamed
```

## Options

Every exporter takes the same options:

| Option | |
|---|---|
| `--project-json FILE` | the artist's project file; its images are found as the file names them, relative to it |
| `--output-dir DIR` | the game's project folder, with the console's runtime in it |
| `--mapping WHICH` | `all` (the default): every mapping; `none`: no mapping; or one mapping's name or id |
| `--mode MODE` | `parts` (the default, every tile resident), `parts_streamed` or `frames_streamed` ([the three ways](memory-and-limits.md#three-ways-to-store-the-sprites)), where the console's runtime streams |
| `--copy-assets` | also copy the project file and its images into the folder's `source/`, for reference |
| `--strict` | exit with code 1 when the project has errors (see below) |

A console adds options for what only it has:

| Console | Option |
|---|---|
| SNES | `--setup SIZES`: the two sprite sizes, `snes_8_16`, `snes_8_32`, `snes_8_64`, `snes_16_32`, `snes_16_64` or `snes_32_64`; the default is the project's own setup when it is made for the SNES, else `snes_8_16` |

**Mappings.** The export bakes the data once per mapping. Mapping 0 is always no mapping; with `--mapping all` mappings 1 and up are the project's in their order, with one named mapping it is mapping 1. Find a mapping by its id at run time (`ms_find_mapping_index_by_id`) and the game does not depend on the choice. Every mapping adds its render frames, and its tiles where it shows other modules, so export the ones the game uses.

**What gets written** is the data and the generated code, never the runtime: see each console's page ([Mega Drive](consoles/megadrive.md#set-up), [SNES](consoles/snes.md#set-up)). The runtime files come with the editor's source code and are copied into the game once per editor version. An exporter leaves the game's other files alone.

## Issues and exit codes

After exporting, the exporter lists what the game gets differently from what the editor shows: the same issues as the editor's **Tools ▸ Check Project**.

- **Errors**: something is lost, for example a step whose frame was deleted is left out, or the tiles do not fit video memory.
- **Warnings**: it looks or behaves differently, for example a palette with more colours than the console shows, or a project made for another console.
- **Notes**: information, for example how much video memory the sprites take.

The exit code is 0 unless the export failed. With `--strict` it is 1 when there are errors, so a build stops instead of shipping a broken export. Some problems stop the export itself (exit code 1 in any case): a project file that cannot be read, a mapping that does not exist, or data the console's format cannot hold (on the SNES, tiles that do not fit the 512 resident, or a table bigger than a ROM bank).

## In a build script

Export before `make` runs, as a step of its own: the SDKs' makefiles look for the sources and the data when they start, so files written during the same `make` run would be missed on a fresh checkout.

```bash
#!/bin/sh
set -e
export_megadrive --project-json art/hero.json --output-dir . --strict
make release
```

The export takes a few seconds for a project like the Prince of Persia example, so running it on every build is cheap; the files it writes are the same for the same project.

## After an editor update

Export again with the new version, and copy the new version's runtime files into the game: data, generated code and runtime belong together ([versions](index.md#versions)). The release notes say when a console's data changed. In 0.12 both did: the Mega Drive's data is version 7 (it was 5), the SNES's version 4 (it was 2), and the Mega Drive's runtime gained a file, `src/modsprite_draw.s`. 0.12.1 changed only the runtimes (new calls): its data is 0.12's, so a game keeps its export and copies the new runtime files for the new calls.
