# SNES Example (PVSnesLib)

A complete SNES pipeline for modular sprites from your editor project, the counterpart of the Mega Drive's
(`examples/sgdk`):

- **Bake step**: a Python exporter turns the project into binary chunks, one per ROM bank, and the C files that find
  them
- **Runtime**: a small PVSnesLib C library with its hot loops in 65816 assembly that draws a **module**, **frame**,
  **animation** or **timeline scene**, plays animations exactly like the editor, and gives the game the hitboxes and
  points of what it shows; the API is the Mega Drive runtime's, so a game uses the same calls on both
- **Demo**: `snes_demo/`, a ROM that starts on the project's first scene (the Prince of Persia example's Swordfight)
  and browses everything else

The editor's online documentation is at [modularsprites.bionic-productions.com](https://modularsprites.bionic-productions.com/).

## How it works

The SNES draws sprites from two tables of 256 tiles (16 KB of video memory) in two square sizes a game chooses for
the whole screen (OBSEL: 8×8 and 16×16, 8×8 and 32×32, ... 32×32 and 64×64). The exporter
(`tools/export_snes.py`) bakes for one of those pairs, the project's when it is made for the SNES (Console, above the
tabs), else 8×8 and 16×16:

- **Tiles and palettes**: every module image as it is used (flipped parts reuse the same tiles through the sprite's
  flip bits; rotations are baked), cut into squares of the two sizes (`sprite_cut.cut`: a cell of the large size whose
  pixels sit in at most half of its small squares takes small sprites, otherwise one large sprite), as 4 bpp planar
  tiles, squares with the same pixels stored once, packed into the two tables (largest first, each at the first free
  place aligned to its size: squares of powers of two leave no gaps). The palettes in slot order as SNES colours
  (BGR555), each palette swap's version of the palettes it changes, and the colour cycles, as for the Mega Drive.
  Every tile stays in video memory; the editor's Budget overlay and Check Project count them the same way.
- **Render frames**: each frame, animation step and scene sample as the sprites the runtime writes into the sprite
  table: in OAM order (the last part first: it is on top), relative to where the frame is drawn, in runs of one palette
  entry; with the frame's hitboxes and points, its sprite count and the box around its sprites.
- **Animations, scenes, mappings, step events and names**, as for the Mega Drive.

What parts, render frames, animations and scenes hold is worked out by `console_bake.py` (repository root), the bake
every console's exporter shares; `SNESBakeContext` subclasses it and stores each part's picture as SNES squares
(`_store_part`).

The data is in chunks of at most 32 KB (a LoROM bank, `res/ms_chunk_NN.bin`), placed by `modsprite_chunks.asm`; a
table the runtime indexes sits whole in one chunk, render frames come in pages of 1024, and the lists a render frame
points to are far references (offset, chunk). `modsprite_rom.mk` gives the Makefile the ROM size the chunks need.

At start `ms_init()` loads both sprite tables into video memory (word address 0x0000), sets OBSEL to the export's
sizes and loads the palette entries into sprite palettes 0, 1, ... (the palettes first, then the swaps' versions).
Drawing then only writes PVSnesLib's OAM buffer (`oamMemory`), which its vertical blank interrupt sends to the PPU: a
render frame's runs become sprites at the draw position with their run's palette bits. A frame whose box lies on the
screen with X >= 0, and whose sprites all fit under the limit, is copied without per-sprite tests; others are culled
sprite by sprite. `ms_end_frame()` hides the entries the last frame used and this one does not (at y 240, below the
lines the PPU looks at) and packs the sprite table's high table (X bit 8 and size of every sprite). Add sprites of
your own to the same list with `ms_add_hw_sprite()`; `ms_tiles_end()` says where free tiles start.

The hot loops (`ms_put_render_frame`, `ms_add_hw_sprite`, `ms_finish_oam`) are 65816 assembly in
`src/modsprite_draw.asm`; `src/modsprite.c` has their C versions, which the host tests run and
`tools/check_snes_rom.py` compares with the assembly in an emulator.

### Performance

Measured in Mesen 2 with the PPU's V counter (`PoP_WW.json`, 8×8 and 16×16 sprites; one NTSC frame has 262 lines):

| | scanlines | of a frame |
|---|---|---|
| one frame of the Prince, 18 sprites on average | 18 | 7 % |
| the Swordfight scene, 38 sprites | 31 | 12 % |
| one animation drawn twice, the second through a mapping and a palette swap, 30 sprites | 37 | 14 % |
| a frame across the screen's edge (tested sprite by sprite) | up to 38 | 15 % |

The Swordfight plays without a lag frame; the demo runs at 60 frames a second in every view, with the text panel
open. Each sprite costs about 90 cycles in the fast loop; 816-tcc's C for the same loop took about 320 cycles a
sprite and the C around it as long again (the first ROM needed half a frame for the Swordfight).

### Limits

- **Video memory**: all tiles stay resident, in the two sprite tables of 256 tiles. `PoP_WW` needs 300 tiles with
  8×8 and 16×16 sprites (284 with 8×8 and 32×32), the Adventurer 329, Sonic 600 (too many: the export stops). The
  File ▸ Export ▸ SNES dialog shows what each pair of sizes needs; the export reports the count, warns above three
  quarters and stops above 512; the editor shows the same count in the Budget readout (SNES setups) and in Check
  Project. `ms_init_ex(vram_address, first_palette)` puts the tables elsewhere (0x0000, 0x2000, 0x4000 or 0x6000).
- **Palettes**: 15 colours plus transparent each, in the order of the editor's slots, eight sprite palettes. The
  runtime loads the palette entries into consecutive palettes from the first; `ms_palettes_fit()` is false when they
  would run past palette 7, and `ms_load_palette(entry, palette)` loads others when they are needed. Colour cycles
  turn with `ms_palette_tick()`, called once a frame right after `WaitForVBlank()`: it puts the palettes that changed
  into CGRAM first (CGRAM can only be written in vertical blank), then prepares the next ones in RAM.
- **128 hardware sprites** per screen, 32 and 34 tiles (272 px) a line; `ms_set_sprite_limit()` leaves the entries
  from the limit on to the game (a multiple of 4: the high table's bytes from there are the game's too). Sprites that
  do not fit are counted in `MS_FrameProfile.sprites_dropped`.
- **Scenes** are baked as one render frame per tick, once per mapping, as for the Mega Drive.
- **Timing**: as for the Mega Drive, the runtime counts video frames (60 a second; a PAL console plays at 5/6 of the
  speed, which the editor previews with View ▸ Play at 50 Hz).
- **Data**: a frame, step or sample has at most 255 parts and 255 sprites; a table the runtime indexes must fit a
  32 KB bank (the export says which one does not).

## Files

- `tools/export_snes.py` - bake exporter
- `tools/snes_host.py` - the runtime compiled for the host (the tests' and the ROM check's reference)
- `snes_demo/` - a PVSnesLib project
  - `inc/modsprite.h` - runtime API
  - `src/modsprite.c` - players, palettes, hitboxes and points, the C versions of the assembly
  - `src/modsprite_draw.asm` - the runtime's hot loops in 65816 assembly
  - `src/main.c` - the demo
  - `Makefile` - PVSnesLib's rules, FastROM, the ROM size from `modsprite_rom.mk`
  - generated by the export: `res/ms_chunk_NN.bin`, `modsprite_chunks.asm`, `inc/modsprite_data.h` (record types,
    counts and `MS_EVENT_*` / `MS_HITBOX_*` / `MS_POINT_*` / `MS_ROLE_*` constants), `src/modsprite_data.c`,
    `modsprite_rom.mk`

## Regenerate the data

In the editor: **File ▸ Export ▸ SNES (PVSnesLib)...**, choose the game's PVSnesLib project folder (one with
`src/modsprite.c`, `src/modsprite_draw.asm` and `inc/modsprite.h`, like `snes_demo/`), the mappings and the sprite
sizes. The editor remembers them per project and shows what the game gets.

From the command line (the same exporter; run from the repo root):

```bash
python3 examples/snes/tools/export_snes.py --project-json examples/sgdk/PoP_WW.json --output-dir examples/snes/snes_demo
```

`--mapping all` (the default) bakes one data set per mapping plus index `0` (no mapping), `--setup snes_8_32` picks
other sprite sizes, and `--strict` makes the command fail (exit code 1) when Check Project finds errors.

## Build the demo

The demo needs [PVSnesLib](https://github.com/alekmaul/pvsneslib) 4.x (tested with 4.6.0): set `PVSNESLIB_HOME`, or
unpack a release into `snes_demo/third_party/pvsneslib` (the folder with `devkitsnes/` and `pvsneslib/`). Then:

```bash
cd examples/snes/snes_demo
make
```

This builds `modular_sprite_snes_demo.sfc` (FastROM, LoROM; 512 KB for the Prince of Persia example).

The demo starts on the project's first scene. **Up / Down** switch between scenes, animations, frames and modules,
**Left / Right** browse (held: faster), **A** plays and pauses, **B** shows hitboxes and points, **X** changes the
look (every mapping with every palette swap, then one animation drawn twice, the second re-skinned and recoloured),
**Start** shows the controls and what a frame costs (frames a second, the share of the frame the work takes, the
sprites, the tiles, sprites lost to the limits of a line).

## Check it in an emulator

`tools/check_snes_rom.py` (repository root) builds the runtime with a probe program in place of the demo's `main.c`
and plays it in Mesen 2's headless test runner: every frame at three positions, the scenes with every mapping, an
animation drawn through another mapping and swap, a game's own sprites across the screen's edges, the colour cycles;
each sprite table must equal the host build's byte for byte (which `tests/test_snes_runtime_draw.py` checks against
the editor), video memory the export's tiles. It prints the slowest draw in scanlines and the lag frames of the first
scene. It needs Mesen 2 (`--mesen`, `$MESEN`) and PVSnesLib (`--pvsneslib`, `$PVSNESLIB_HOME`). The release workflow
runs it on Linux with Mesen 2.1.1 after building the demo, whose committed data must be what the exporter writes:
export it again and commit it whenever the exporter changes. On a machine where Mesen has never run, put a
`settings.json` holding `{}` next to its executable first, or it opens its setup window instead of running the check.
On Linux the tool runs Mesen with `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`: Mesen 2.1's core dies with `std::bad_cast`
while loading when .NET has loaded the system's ICU first.

```bash
python3 tools/check_snes_rom.py [PROJECT.json ...]
```

## Notes on 816-tcc

PVSnesLib's C compiler makes slow code (a couple of hundred cycles for a short C statement on far data) and has
quirks the runtime works around:

- Stepping a pointer (`p++` in a loop) is unreliable: records are reached by index or offset.
- With FastROM (`-F`), initialised globals live in bank $7F and the others in $7E: assembly reaches them with long
  addressing (`lda.l`), never `.w` (which hits bank $7E's first page, tcc's own registers).
- Arguments are 16-bit words on the stack, a pointer as its address then its bank, but a `u8` argument is one byte
  (`sep #$20 / pha`).
- A multiplication by anything but a power of two is a library call: records the runtime indexes are padded to 8 or
  16 bytes, and a render frame's 22 are multiplied in shifts.
- A ternary choosing between an array and a pointer argument crashed the compiler (`ICE 2`).
