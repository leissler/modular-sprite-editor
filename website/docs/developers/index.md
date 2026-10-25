# Developer documentation

This part of the site is for programmers: engine developers who want to bring the editor's sprites into their engine, and game developers who draw them with the editor's runtime. The rest of the site is written for artists; [For your programmer](../reference/programmers.md) is the page they hand you.

## What the editor produces

An artist works in a **project**: a JSON file with the sprite sheets next to it. It holds the modules (pieces of the sheets), the frames built from them, animations, scenes, mappings (re-skins), palettes with their swaps and colour cycles, and the hitboxes, points and events a game's logic needs. Everything below comes from that file.

A **console export** bakes the project for one console, into the folder of a game made with that console's SDK: the data, laid out the way that console reads it best, and generated C code (record types, counts, the project's constants and the code that finds the data).

The **runtime** is a small C library, written for each console, with the same functions on every console (`ms_*`). Each video frame the game asks it to draw modules, frames, animations and scenes at positions on the screen, and it writes them into the console's sprite table. It also plays animations tick for tick as the editor previews them, and tells the game which hitboxes, points and events the shown step has.

```text
project.json + sheets ──export──▶ data + generated C ──┐
                                                       ├──▶ your game ──▶ sprite table
the console's runtime (C) ─────────────────────────────┘
```

| Console | SDK | Exporter | Pages |
|---|---|---|---|
| Mega Drive | SGDK | `export_megadrive` | [Mega Drive (SGDK)](consoles/megadrive.md) |
| SNES | PVSnesLib | `export_snes` | [SNES (PVSnesLib)](consoles/snes.md) |

More consoles are on their way, each with the same API and pages of its own: see [Consoles](consoles/index.md).

## Three ways in

1. **Use the runtime.** Copy its files and the export into your project, then call `ms_begin_frame()`, draw, and `ms_end_frame()` every video frame. The runtime writes the sprite table and, when the export streams, uploads tiles; your engine keeps the backgrounds, scrolling, sound and input. Start with [Use the runtime](runtime.md).
2. **Write your own runtime on the exported data.** Each console's data is documented record by record on its pages; your engine reads it and puts the hardware sprites into its own sprite list.
3. **Write your own exporter.** Read [the project file](project-format.md) and bake what your engine uses, or reuse the editor's bake (Python) and write your own output. See [Integrate with your engine](engine.md#path-3-your-own-exporter), and [Adding a console](consoles/new.md) for a platform the editor does not export for yet.

Most engines start with the first: the runtime is written to live next to an engine, and every release checks it in emulators against the editor.

## Where to read

| You want to | Read |
|---|---|
| know what modules, frames, mappings and render frames are | [How the data works](concepts.md) |
| draw the artist's sprites in a game | [Use the runtime](runtime.md), then the [API reference](api.md) |
| plan video memory, stream tiles, stay under the sprite limits | [Video memory and limits](memory-and-limits.md) |
| put the runtime into your engine, or replace it | [Integrate with your engine](engine.md) |
| export from a build script or CI | [Export from your build](exporting.md) |
| read the project format | [The project file](project-format.md) |
| set up a console, its numbers, its data format | its page under [Consoles](consoles/index.md) |
| bring the editor to another platform | [Adding a console](consoles/new.md) |

## Versions

These pages describe version 0.12, project file format 9. Each console's data has a version of its own, given on its data page. The data, the generated code and the runtime belong together: after exporting with a newer editor, copy that version's runtime files into the game; an older runtime does not compile against newer data. Every release lists what changed for programmers in its [release notes](https://github.com/leissler/modular-sprite-editor/releases).

The [source repository](https://github.com/leissler/modular-sprite-editor) is the reference behind these pages: the runtimes' headers (`inc/modsprite.h`), each console's guide (`examples/<console>/README.md`) and the documents in `docs/`.
