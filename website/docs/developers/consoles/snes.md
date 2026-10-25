# SNES (PVSnesLib)

The SNES export works with [PVSnesLib](https://github.com/alekmaul/pvsneslib) 4.x (tested with 4.6.0). The source code's `examples/snes` holds the exporter (`tools/export_snes.py`), the runtime, with its hot loops in 65816 assembly, and a demo (`snes_demo`) that starts on the project's first scene and browses everything else; its README is the most detailed reference. The release page has the demo as `ModularSpriteEditor-snes-demo.zip`: the ROM and its project.

## Set-up

1. Copy the runtime into your PVSnesLib project: `src/modsprite.c`, `src/modsprite_draw.asm` and `inc/modsprite.h`, from `examples/snes/snes_demo`.
2. Export the project into the same folder: in the editor **File ▸ Export ▸ SNES (PVSnesLib)...**, or `export_snes --project-json my.json --output-dir path/to/game` ([options](../exporting.md#options); `--setup` picks the two sprite sizes).
3. Build with PVSnesLib's `make` (on Windows without MSYS2, the demo's `build_windows.ps1` takes the same steps).

The export writes `res/ms_chunk_NN.bin` (the data, one ROM bank each, [documented here](snes-data.md)), `modsprite_chunks.asm` (places them), `inc/modsprite_data.h`, `src/modsprite_data.c` and `modsprite_rom.mk` (the ROM size the data needs). PVSnesLib's rules assemble every `.asm` in the project folder and in `src`; include the ROM size before them:

```make
export FASTROM := 1
-include modsprite_rom.mk
include $(PVSNESLIB_HOME)/devkitsnes/snes_rules
```

The runtime is built and tested as a LoROM FastROM program, like the demo.

## A complete program

```c
#include <snes.h>
#include "modsprite.h"

int main(void)
{
    MS_AnimPlayer hero;

    consoleInitDefaultText(0);
    setMode(BG_MODE1, 0);
    ms_init();                         /* while the screen is off: tiles, palettes, sprite sizes */
    ms_anim_player_init(&hero, 0);
    setScreenOn();
    while (1)
    {
        ms_begin_frame();
        ms_draw_anim_player(&hero, 128, 168);
        ms_end_frame();
        ms_anim_player_tick(&hero);
        WaitForVBlank();               /* PVSnesLib's interrupt sends the sprite table */
        ms_upload_tiles();             /* streamed exports: the slots' new tiles */
        ms_palette_tick();             /* palettes into CGRAM, colour cycles */
    }
    return 0;
}
```

PVSnesLib's start-up code clears no RAM: a global without an initial value starts with whatever the console's RAM held. The runtime gives everything it reads a value in `ms_init`; do the same with your own globals. The demo draws scenes at (128, 168), where the editor's Timeline screen outline puts a scene's origin.

## The SNES's own functions

| | |
|---|---|
| `void ms_init_ex(u16 vram_address, u16 first_palette)` | the sprite tables' VRAM word address (0x0000, 0x2000, 0x4000 or 0x6000: OBSEL's steps; `ms_init()`: 0x0000) and the first sprite palette; call it during forced blank |
| `u16 ms_tiles_end(void)` | the first tile after the runtime's (streamed: after the default slot), free for your own sprites and slots |
| `u8 ms_add_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large)` | `tile`: 9 bits; `attribute`: the OAM attribute byte without the tile's bit 8 (V flip 0x80, H flip 0x40, priority, palette); `large`: the large size |
| `ms_set_sprite_limit(limit)`, `u16 ms_sprite_base(void)` | 128 by default; a lower limit (a multiple of 4) leaves the entries from there to your engine, and `ms_sprite_base` gives the first |
| `void ms_upload_tiles(void)` | streamed exports: right after `WaitForVBlank()`, sends what this frame's draws queued |
| `void ms_set_upload_budget(u16 bytes)`, `u16 ms_upload_queued(void)` | the most one vertical blank uploads, and what this frame queued so far |
| `ms_load_palette(entry, palette)` | sprite palettes 0 to 7, written to CGRAM at the next `ms_palette_tick` |

`MS_FrameProfile` has one field more than elsewhere: `uploads_waiting`, the draws that showed what their slot held because the upload budget was used up.

## What the runtime touches

- **The sprite table.** It writes PVSnesLib's OAM buffer, `oamMemory`, from entry 0 up to the sprite limit, and its high table; PVSnesLib's vertical blank interrupt sends it. `ms_end_frame()` hides the entries the frame before used and this one does not (at y 240) and packs the high table (each sprite's X bit 8 and size).
- **Video memory.** `ms_init()` copies a resident export's sprite tables with `dmaCopyVram` and sets OBSEL with `oamInitGfxAttr` (the tables' address and the export's sprite sizes). In a streamed export `ms_upload_tiles()` sends the slots' new tiles on DMA channel 0, writing VMAIN, VMADD and DMA channel 0's registers directly and checking HVBJOY, so it stops when the vertical blank ends.
- **CGRAM.** The sprite palettes it uses (from CGRAM 128 + 16 × the first palette), with `dmaCopyCGram` in `ms_palette_tick()`.

Nothing else: backgrounds, modes, text, HDMA and sound stay your engine's. Sprites are drawn with priority 2, in front of every background.

## Video memory

**Resident.** The tiles go into the two sprite tables of 256 tiles each (16 KB of video memory) at the address `ms_init_ex` gives: put them where your backgrounds are not. The Prince of Persia example needs 300 tiles with 8×8 and 16×16 sprites, 284 with 8×8 and 32×32; the Adventurer 329; Sonic 600, more than 512, so its resident export stops and its streamed export works. The export dialog shows what each pair of sizes needs.

**Streamed.** The default slot starts at tile 0; slots are whole rows of the sprite tables (16 tiles) and start at a multiple of `MS_SLOT_ALIGN` (a row of large sprites), so `ms_slot_init` rounds the first tile up. Start your own slots at `ms_tiles_end()`. Video memory can only be written in the vertical blank: `ms_upload_tiles()` sends the queued lists right after `WaitForVBlank()` on DMA channel 0, within a budget of about 4.8 KB of tiles an NTSC vertical blank (`MS_UPLOAD_BUDGET`, what PVSnesLib's interrupt leaves, each run's set-up counted). A draw over the budget shows what its slot holds and uploads in a later frame; the first list of a frame goes whatever it costs. Lower the budget with `ms_set_upload_budget` when your game sends more in the vertical blank, or send your own data only when `ms_upload_queued()` leaves room. A list cut off by the end of the vertical blank is queued again when it is drawn next.

## Palettes

Eight sprite palettes of 15 colours and transparent; 5 bits a channel (BGR555). The runtime loads the palette entries into consecutive palettes from the first `ms_init_ex` gives; `ms_palettes_fit()` is `FALSE` when they run past palette 7. CGRAM can only be written in the vertical blank, which is why `ms_palette_tick()` belongs right after `WaitForVBlank()`: it writes the palettes that changed, then turns the colour cycles and prepares the next colours.

## Sprite limits

128 hardware sprites per screen, 32 per line and 34 tiles (272 pixels) per line, in two square sizes the game chooses for the whole screen (8×8 and 16×16 up to 32×32 and 64×64). Past a line's limit the PPU does not show the sprites last in the table on that line.

## What it costs

Measured in Mesen 2 with the PPU's V counter (a frame has 262 lines, NTSC): about 90 cycles per sprite in the fast loop, 100 mirrored. With the Prince of Persia example and 8×8 and 16×16 sprites:

| | Lines |
|---|---|
| one frame of the Prince, 18 sprites on average | 18 |
| the same frames mirrored | 20 |
| the *Swordfight* scene, 38 sprites | 31 |
| a frame across the screen's edge (each sprite tested) | up to 38 |

| The *Swordfight*, 600 frames | Drawing a frame | Uploads in the vertical blank |
|---|---|---|
| parts, resident | 31.4 lines on average, 39.4 at most | none |
| parts, streamed | 33.8 lines, 44.5 at most | 17.8 lines, one frame in nine |
| whole frames, streamed | 21.5 lines, 28.2 at most | 11.3 lines, one frame in nine |

| The Prince of Persia example | Video memory | Cartridge (tiles) | Hardware sprites a step | Busiest line |
|---|---|---|---|---|
| parts, resident | 300 tiles | 9.4 KB | 14.0, 30 at most | 21 of 32 |
| parts, streamed | 64 tiles a character and a scene | 9.4 KB | 14.0, 30 at most | 21 of 32 |
| whole frames, streamed | 32 a character, 64 a scene | 153.5 KB | 4.3, 11 at most | 6 of 32 |

## Without PVSnesLib

The runtime uses `oamMemory` (PVSnesLib's 544-byte OAM buffer: 128 entries of 4 bytes, then the 32-byte high table, sent in the vertical blank), `dmaCopyVram`, `dmaCopyCGram` and `oamInitGfxAttr`; `examples/snes/tools/snes_host.py` builds it for a PC against a stand-in. The assembly in `modsprite_draw.asm` follows 816-tcc's conventions: arguments on the stack as 16-bit words (a far pointer as its address then its bank, a `u8` as one byte), globals reached with long addressing (with FastROM, initialised ones live in bank $7F). The README's notes on 816-tcc list what the runtime works around in that compiler.

## How it is checked

- `tests/test_snes_runtime_draw.py` compiles the runtime's C for a PC and compares what it writes into the OAM, rasterised, with the editor's pictures pixel for pixel: every frame and module as it is and mirrored, and every animation step mirrored each way (with the Animations tab's Mirror preview, its hitboxes and points too); `test_snes_streaming.py` does the same with streamed exports, `test_snes_runtime_player.py` checks the player, hitboxes and points against the editor's.
- `tools/check_snes_rom.py` builds the runtime, its assembly included, into a ROM and plays it in Mesen 2: every sprite table must equal the PC build's byte for byte, video memory the export's tiles, in the three export modes. `tools/compare_snes_roms.py` plays two builds of the demo side by side. Every release runs both.
