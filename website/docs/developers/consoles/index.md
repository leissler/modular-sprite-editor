# Consoles

The editor is made for retro consoles in general, and its data, export modes and runtime API are the same for every console. What differs from one console to the next is its hardware (sprite sizes, video memory, palettes), its SDK and the layout of the exported data. Each console with an exporter has its pages here; the rest of the developer pages hold for all of them.

## Support today

| Console | In the editor | Export and runtime | Pages |
|---|---|---|---|
| Mega Drive / Genesis | budget, palettes, Check Project | SGDK: `export_megadrive`, C runtime with 68000 draw loops | [Mega Drive (SGDK)](megadrive.md), [its data](megadrive-data.md) |
| SNES / Super Famicom | budget, palettes, Check Project | PVSnesLib: `export_snes`, C runtime with 65816 draw loops | [SNES (PVSnesLib)](snes.md), [its data](snes-data.md) |
| NES | budget, palettes | not yet | |
| Game Boy Advance | budget, palettes | not yet | |
| Game Boy | budget, palettes | not yet | |

A console **in the editor** can be a project's target: the palettes follow its colour model and sizes, the budget overlay counts its hardware sprites per screen and per line, and the Timeline shows its screen. A console is **fully supported** when a game on it can use the art, drawn, played and checked exactly as the editor shows it: an exporter, a runtime with the common API, video memory counted the way the export stores it, the console's checks in Check Project, tests that compare the runtime with the editor pixel for pixel, a demo, and a check in an emulator in every release. More consoles are on their way; [Adding a console](new.md) says what one takes.

## The same on every console

- **The data model**: modules, frames, animations, scenes, mappings, palettes, hitboxes, points and events ([How the data works](../concepts.md)), from one [project file](../project-format.md).
- **The runtime API**: the same `ms_*` functions with the same meaning ([API reference](../api.md)). A game that draws, plays and re-skins its characters on one console does the same on another; only the start-up and the end of a frame follow the console's SDK.
- **The export modes**: parts resident, parts streamed, whole frames streamed, and frames marked Store whole ([Video memory and limits](../memory-and-limits.md)).
- **The exporter's command line**: the same options, plus the console's own ([Export from your build](../exporting.md)).
- **Versions**: data, generated code and runtime come from the same editor version.

## What each console's pages cover

- **Set-up**: the runtime's files, what the export writes, the build, a complete program.
- **What the runtime touches** in the console's hardware and SDK, and how it shares them with an engine.
- **Video memory, palettes and sprite limits** in numbers, and how streaming works on that console.
- **The console's own functions** and the parameters that differ.
- **What it costs**: code, work RAM and drawing time, measured.
- **The data format**, record by record, for an engine that reads it itself.

## Compared

| | Mega Drive, H40 | SNES |
|---|---|---|
| Hardware sprites per screen / per line | 80 / 20 (320 pixels) | 128 / 32 (34 tiles, 272 pixels) |
| Sprite sizes | 8 to 32 pixels a side, in 8-pixel steps | two square sizes for the whole screen, from 8×8 and 16×16 up to 32×32 and 64×64 |
| Video memory for sprite tiles, resident | about 1424 tiles in SGDK's default layout | 512 tiles (two tables) |
| Palettes for sprites | 4 lines of 15 colours, shared with the backgrounds | 8 palettes of 15 colours |
| Colours | 3 bits a channel | 5 bits a channel |
| Streamed uploads a vertical blank (NTSC) | about 7.2 KB with the sprite table | about 4.8 KB of tiles (`MS_UPLOAD_BUDGET`) |
| The Prince of Persia example, resident | 305 tiles | 300 tiles (8×8 and 16×16) |
