# Mega Drive (SGDK)

The Mega Drive export works with [SGDK](https://github.com/Stephane-D/SGDK). The source code's `examples/megadrive` holds the exporter (`tools/export_megadrive.py`), the runtime and a demo (`megadrive_demo`) that browses every module, frame, animation and scene of a project with live profiling; its README is the most detailed reference.

## Set-up

1. Copy the runtime into your SGDK project: `src/modsprite.c`, `src/modsprite_draw.s` and `inc/modsprite.h`, from `examples/megadrive/megadrive_demo`.
2. Export the project into the same folder: in the editor **File ▸ Export ▸ Mega Drive (SGDK)...**, or `export_megadrive --project-json my.json --output-dir path/to/game` ([options](../exporting.md#options)).
3. Build with SGDK. Its makefile compiles every `.c` and assembles every `.s` under `src` by itself.

The export writes `res/gen/modsprite_blob.bin` (the data, [documented here](megadrive-data.md)), `inc/modsprite_data.h` and `src/modsprite_data.c` (record types, counts, constants and the parser), and adds one line to `res/resources.res`, keeping the game's other resources:

```text
BIN MS_BLOB "gen/modsprite_blob.bin" 2 2 0 NONE FALSE
```

## A complete program

```c
#include <genesis.h>
#include "modsprite.h"

int main(bool hardReset)
{
    MS_AnimPlayer hero;

    ms_init();                         /* tiles into VRAM, palettes from line PAL1 on */
    if (!ms_data_is_ready() || !ms_tiles_fit())
        SYS_die("sprite data");
    ms_anim_player_init(&hero, 0);     /* the first animation of the Animations list */
    for (;;)
    {
        ms_begin_frame();
        ms_draw_anim_player(&hero, 160, 168);
        ms_end_frame();                /* queues the sprite table for the vertical blank */
        ms_anim_player_tick(&hero);    /* one video frame of playback */
        ms_palette_tick();             /* colour cycles */
        SYS_doVBlankProcess();         /* waits for the vertical blank and sends the queue */
    }
    return 0;
}
```

`ms_data_is_ready()` says whether the blob was found and is of the version the generated parser expects. The demo draws scenes at (160, 168), where the editor's Timeline screen outline puts a scene's origin.

## The Mega Drive's own functions

| | |
|---|---|
| `void ms_init_ex(u16 tile_index, u16 palette)` | the first tile (`TILE_USER_INDEX` for `ms_init()`) and the first palette line (`PAL1` for `ms_init()`; `PAL0` gives one line more) |
| `u8 ms_tiles_fit(void)` | `FALSE` when the tiles (streamed: the default slot) do not fit between the first tile and SGDK's font |
| `u8 ms_add_hw_sprite(s16 x, s16 y, u8 size, u16 attribute)` | `size`: `SPRITE_SIZE(w, h)` in tiles; `attribute`: `TILE_ATTR_FULL(palette, priority, vflip, hflip, tile)` |
| `ms_set_sprite_limit(limit)` | 80 in H40 (the default), 64 in H32 |
| `ms_load_palette(entry, line)` | lines 0 to 3 |

Compile-time settings of its own: `MS_ASM_SPRITES` (4): render frames of this many sprites or more go through the 68000 loops of `src/modsprite_draw.s`, smaller ones through the C loops, whose call costs less; `MS_PUT_FRAME_C`: the C loops only, which any compiler but a 68000 one builds anyway (the host tests). Both loops write the same sprite table.

## What the runtime touches

- **The sprite table.** Between `ms_begin_frame()` and `ms_end_frame()` it writes SGDK's sprite table cache, `vdpSpriteCache`, from entry 0. `ms_end_frame()` ends the link chain and queues the table with `VDP_updateSprites(count, DMA_QUEUE)`; `SYS_doVBlankProcess()` sends it. An empty frame parks one sprite off the screen. Do not use SGDK's sprite engine (`SPR_*`) at the same time: both write the table. Add your own sprites with `ms_add_hw_sprite()`: `ms_end_frame()` sends only the entries the frame filled.
- **Video memory.** A resident export's tiles are loaded once by `ms_init()` with `VDP_loadTileData`. A streamed export's draws queue uploads into slots with `DMA_queueDmaFast` (`DMA_queueDma` for a run across a 128 KB bank of the cartridge).
- **Colour RAM.** `PAL_setColors` into the palette lines it was given, at start and when `ms_load_palette` or `ms_palette_tick` changes them.
- **Reads** the screen size (`VDP_getScreenWidth`, `VDP_getScreenHeight`) at each `ms_begin_frame()`, to cull sprites.

Nothing else: no planes, scrolling, window, interrupts, sound or input. Its data stays in the cartridge.

## Video memory

**Resident.** The tiles go from the first tile on and must end before SGDK's font: in SGDK's default layout about 1424 tiles (the 1536 below the plane maps at 0xC000, less 16 system and 96 font tiles). The Prince of Persia example needs 305, Sonic 620. Load your own tiles first and pass the first free one to `ms_init_ex`. The export reports the count, warns above three quarters of the room and reports an error above it.

**Streamed.** `ms_init()` makes the default slot at the first tile; place more slots, or the slot cache, after `ms_tile_base() + ms_tiles_used()`, below the font and the plane maps. `SYS_doVBlankProcess()` sends SGDK's DMA queue in the vertical blank, which carries about 7.2 KB on an NTSC console, the sprite table included; more runs into the picture. SGDK's queue holds 80 transfers, one per run of tiles (`DMA_setMaxQueueSize` for more), and queueing costs the 68000 about 2.3 scanlines a run. A run the queue refuses leaves the slot holding nothing known, and the next draw queues the list again. The export and Check Project say how many characters can change steps in the same frame (the Prince of Persia example: five).

## Palettes

Four palette lines of 15 colours and transparent, shared with the backgrounds; 3 bits a channel. The runtime loads the palette entries into consecutive lines from `PAL1` (or the line `ms_init_ex` gives) as far as they fit; `ms_palettes_fit()` is `FALSE` when they run past `PAL3`. Keep a line for your backgrounds, or manage the lines yourself with `ms_load_palette`.

## Sprite limits

80 hardware sprites per screen and 20 per line (320 sprite pixels) in H40, 64 and 16 (256 pixels) in H32. Past a line's limit the VDP does not show the sprites last in the table on that line.

## SGDK release builds

SGDK's `make release` links its prebuilt library, `lib/libmd.a`, which holds GCC 13's link-time code: other GCC versions refuse to link it. The demo's `Makefile` builds SGDK's library from its sources with your GCC instead, once, into `out/sgdk-gcc<version>` (outside Windows; on Windows SGDK's own GCC links the prebuilt one). A game with a makefile of its own copies the demo's block after `include $(SGDK)/makefile.gen`. `make debug` links SGDK's debug library, which any GCC links.

With link-time optimisation GCC sees into SGDK: memory that only a DMA reads looks unused to it, so it may drop the stores that fill a local array passed to `VDP_loadTileData(..., DMA)`. Keep data a DMA copies in a static buffer, as the runtime does, or copy it with `CPU`.

## What it costs

Measured in the Prince of Persia port (a streamed export): about 11.7 KB of code, 1.4 KB of it 68000 assembly, and 0.8 KB of work RAM with the slot cache and give-way levels compiled out (`MS_CACHE_SLOTS=0 MS_QUEUED_DRAWS=0`); about 16.4 KB and 2 KB with them.

Drawing, measured in BlastEm with the VDP's V counter (a frame has 262 lines, NTSC): a piece copied in about 116 cycles on the screen (about 285 across the screen's edge, where each sprite is tested), plus about five lines per draw whatever its size. The demo playing the Prince of Persia example's *Swordfight* (two characters, 600 frames):

| Export mode | Drawing a frame |
|---|---|
| parts, resident | 30.7 lines on average, 37 at most |
| parts, streamed | 35.2 lines, 86 at most (frames that upload) |
| whole frames, streamed | 17.1 lines |

| The Prince of Persia example | Video memory | Cartridge (tiles) | Hardware sprites a step | Busiest line |
|---|---|---|---|---|
| parts, resident | 305 tiles | 9.5 KB | 9.3, 21 at most | 14 of 20 |
| parts, streamed | 39 tiles a character, 65 a scene | 9.5 KB | 9.3, 21 at most | 14 of 20 |
| whole frames, streamed | 22 tiles a character, 38 a scene | 194 KB | 1.2, 3 at most | 2 of 20 |

## Without SGDK

The runtime needs only a small part of SGDK. The tests compile `modsprite.c` for a PC against a stand-in (`GENESIS_STUB` in `tests/test_megadrive_runtime_player.py`), which shows exactly what an engine on another base must provide:

- the types (`u8`, `s8`, `u16`, `s16`, `u32`, `bool`, `TRUE`, `FALSE`) and `PAL0` to `PAL3`, `DMA`, `DMA_QUEUE`, `DMA_VRAM`, `TILE_USER_INDEX`, `TILE_FONT_INDEX`, `TILE_ATTR_FULL`, `SPRITE_SIZE`;
- the sprite cache `VDPSprite vdpSpriteCache[80]` (`s16 y; u8 size; u8 link; u16 attribut; s16 x;`, positions with the VDP's 128 added);
- `VDP_updateSprites`, `VDP_loadTileData`, `DMA_queueDma`, `DMA_queueDmaFast`, `PAL_setColors`, `VDP_getScreenWidth`, `VDP_getScreenHeight`, `memcpy` and `memset`.

The 68000 loops in `modsprite_draw.s` follow GCC's calling convention (every argument a 4-byte stack slot, `d2-d7` and `a2-a6` saved). With another compiler, build the C loops alone (`MS_PUT_FRAME_C`).

## How it is checked

- `tests/test_megadrive_runtime_draw.py` compiles the runtime for a PC, lets it draw every frame and module of the example projects as they are and mirrored, and every animation step mirrored each way, in the middle of the screen and across its edges, rasterises the sprite table like the VDP and compares it with the editor's pictures pixel for pixel (a mirrored step with the Animations tab's Mirror preview, its hitboxes and points too); `test_megadrive_streaming.py` does the same with streamed exports, `test_megadrive_runtime_player.py` compares the animation player with the editor's tick by tick.
- `tools/check_megadrive_rom.py` builds the runtime into ROMs and plays them in BlastEm: every sprite table, the VDP's own sprite table, video memory and colour RAM must equal the PC build's, in the three export modes. Every release runs it.
