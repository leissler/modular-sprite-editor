# SNES Example (PVSnesLib)

A complete SNES pipeline for modular sprites from your editor project, the counterpart of the Mega Drive's
(`examples/megadrive`):

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

`ms_draw_frame_flipped(frame, x, y, flip)` and `ms_draw_module_flipped(module, x, y, flip)` draw it mirrored about the
point it is drawn at (a frame's origin, a module's pivot; bit 0 of `flip` mirrors left to right, bit 1 top to bottom,
like a mirrored animation step): each sprite goes to its mirror image and gets its flip bits toggled, so a character
facing either way needs its frames stored once. The box is mirrored too, so a mirrored frame on the screen takes the
fast loop as well.

The hot loops (`ms_put_render_frame` and, mirrored, `ms_put_render_frame_flipped`, `ms_add_hw_sprite`,
`ms_finish_oam`, a streamed export's `ms_send_uploads`) are 65816 assembly in `src/modsprite_draw.asm`;
`src/modsprite.c` has their C versions, which the host tests run and `tools/check_snes_rom.py` compares with the
assembly in an emulator.

### Streamed exports

By default every tile stays in video memory. The export can instead keep there only what is on screen
(`--mode parts_streamed` or `--mode frames_streamed`; in the editor the export dialog's **Store as**, remembered per
project); [docs/EXPORT_MODES.md](../../docs/EXPORT_MODES.md) compares the three ways on the example projects:

- **`parts_streamed`**: the same parts and tiles in the cartridge as the default export. A project bigger than the 512
  sprite tiles exports this way: Sonic's 600 tiles stay in the cartridge, a player's slot takes 64.
- **`frames_streamed`**: each frame flattened into one picture per palette and cut into squares like a part, so
  overlapping parts cost nothing (PoP: 4.3 hardware sprites a step instead of 14.0, 6 on the busiest line instead of
  21), but the cartridge holds every frame's picture (PoP: 4912 tiles instead of 300) and each mapping is baked again.

The cartridge then holds the squares in strips: each frame's new squares, in the order frames first use them, side by
side in rows of at most 16 tiles. Every render frame names a load list (data version 3): its strips' pieces placed in a
slot of whole sprite-table rows, each square aligned to its size as the PPU finds its tiles 16 to a row, as DMA runs (a
row of a piece each, neighbours merged), with what uploading it costs in vertical blank; identical lists once. Its
sprites count their tiles from the slot. The generated header defines `MS_STREAMED`, `MS_SLOT_TILES` (a player's slot),
`MS_SCENE_SLOT_TILES` (a scene's), `MS_SLOT_ALIGN` (a slot's first tile is a multiple of it: a row of large sprites)
and `MS_UPLOAD_BUDGET`.

`ms_init()` then loads no tiles: it makes a default slot at tile 0, as big as the largest module, frame, step or scene
sample. Video memory can only be written in vertical blank, so drawing a render frame whose list the slot does not hold
queues it, and `ms_upload_tiles()`, called right after `WaitForVBlank()`, sends it: PVSnesLib's interrupt has sent the
sprite table just before, so the tiles and the sprites that use them change in the same vertical blank. It sends the
sprite palettes `ms_palette_tick` prepared first, then the lists, a DMA on channel 0 per run (`ms_send_uploads`);
before and after each list it looks whether the vertical blank still lasts, and a list cut off is queued again when it
is drawn next. Drawing what a slot holds already uploads nothing.

Everything drawn at the same time needs a slot of its own, set before drawing like the mapping:

```c
static MS_Slot guard_slot;
ms_slot_init(&guard_slot, ms_tiles_end());   /* after the default slot (rounded up to MS_SLOT_ALIGN) */

ms_draw_anim_player(&hero, hero_x, hero_y);  /* through the default slot */
ms_set_slot(&guard_slot);
ms_draw_anim_player_mapped(&guard, guard_mapping, guard_x, guard_y);
ms_set_slot(NULL);                           /* the default slot again */
...
WaitForVBlank();
ms_upload_tiles();                           /* the slots' new tiles */
ms_palette_tick();
```

A slot shows one thing a frame, and a scene streams through one slot, a sample's tiles at a time. What one vertical
blank uploads stays within a budget (`ms_set_upload_budget`, `MS_UPLOAD_BUDGET`: bytes of DMA, each list counted with
what setting up its runs costs; the default is what PVSnesLib's interrupt leaves of the blank). A draw over it shows
what its slot holds (the step before) and uploads in a later frame; the first list of a frame goes whatever it costs.
`ms_upload_queued()` says what this frame queued, for a game that sends more in the same blank (the demo writes its
text rows only when that leaves room). In a resident export the slot functions do nothing (`ms_slot_tiles()` is 0), so
the same game code builds with either.

A game with many actors can keep a cache of slots of its own instead of one per actor: `ms_frame_load_list(frame)` and
`ms_module_load_list(module)` name the load list a frame or module draws with (under the current mapping;
`MS_NOTHING_LOADED` when it shows nothing, and in a resident export), `ms_load_list_tiles(list)` the tiles it takes in a
slot. Actors showing the same frame then share one slot, loaded once: a slot that holds a list draws it as often as a
frame asks, mirrored or not.

### Performance

Measured in Mesen 2 with the PPU's V counter (`PoP_WW.json`, 8×8 and 16×16 sprites; one NTSC frame has 262 lines):

| | scanlines | of a frame |
|---|---|---|
| one frame of the Prince, 18 sprites on average | 18 | 7 % |
| the same frames mirrored (`ms_draw_frame_flipped`) | 20 | 8 % |
| the Swordfight scene, 38 sprites | 31 | 12 % |
| one animation drawn twice, the second through a mapping and a palette swap, 30 sprites | 37 | 14 % |
| a frame across the screen's edge (tested sprite by sprite) | up to 38 | 15 % |
| a mirrored frame across the edge | up to 41 | 16 % |

The Swordfight plays without a lag frame; the demo runs at 60 frames a second in every view, with the text panel
open. Each sprite costs about 90 cycles in the fast loop (mirrored about 100, and about 230 more a frame to set the
mirroring up); 816-tcc's C for the same loop took about 320 cycles a sprite and the C around it as long again (the
first ROM needed half a frame for the Swordfight).

Streamed exports, with the demo playing PoP's Swordfight (600 frames in Mesen 2):

| | drawing, average | at most | uploads, in vertical blank |
|---|---|---|---|
| parts, resident | 31.4 lines | 39.4 lines | none |
| `parts_streamed` | 33.8 lines | 44.5 lines | 17.8 lines in one frame in nine, 25.7 at most |
| `frames_streamed` | 21.5 lines | 28.2 lines | 11.3 lines in one frame in nine, 14.3 at most |

A draw through a slot costs about 3 lines more with parts (finding and queueing its list); whole frames have fewer
sprites to draw. The uploads use the vertical blank after PVSnesLib's interrupt: scanlines 230 to 261 (242 to 261 when
it sends the text map too). Each byte costs 8.5 master cycles, each run 533, each list 939 (1364 a scanline).

### Limits

- **Video memory**: all tiles stay resident, in the two sprite tables of 256 tiles. `PoP_WW` needs 300 tiles with
  8×8 and 16×16 sprites (284 with 8×8 and 32×32), the Adventurer 329, Sonic 600 (too many: the export stops, unless
  it streams). The File ▸ Export ▸ SNES dialog shows what each pair of sizes needs; the export reports the count,
  warns above three quarters and stops above 512; the editor shows the same count in the Budget readout (SNES setups)
  and in Check Project. `ms_init_ex(vram_address, first_palette)` puts the tables elsewhere (0x0000, 0x2000, 0x4000 or
  0x6000). A streamed export keeps only its slots there (PoP: 64 tiles a player and 64 a scene, whole frames 32 and
  64; Sonic 64): `ms_tiles_end()` is the default slot's end, the game places the others.
- **Uploads** (streamed exports): what PVSnesLib's interrupt leaves of an NTSC vertical blank carries about 4.8 KB of
  tiles (`MS_UPLOAD_BUDGET`, runs counted in); the export and Check Project warn when filling one slot costs more. A
  game that sends more in vertical blank lowers the budget (`ms_set_upload_budget`) or sends its own data only when
  `ms_upload_queued()` leaves room. The uploads use DMA channel 0, as PVSnesLib's own copies do.
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
  - `build_windows.ps1` - builds it on Windows with PVSnesLib's Windows tools, without make or MSYS2
  - `inc/modsprite.h` - runtime API
  - `src/modsprite.c` - players, palettes, hitboxes and points, the C versions of the assembly
  - `src/modsprite_draw.asm` - the runtime's hot loops in 65816 assembly
  - `src/main.c` - the demo
  - `Makefile` - PVSnesLib's rules, FastROM, the ROM size from `modsprite_rom.mk`
  - generated by the export: `res/ms_chunk_NN.bin`, `modsprite_chunks.asm`, `inc/modsprite_data.h` (record types,
    counts and `MS_EVENT_*` / `MS_HITBOX_*` / `MS_POINT_*` / `MS_ROLE_*` constants; a streamed export's also
    `MS_STREAMED` and the slot sizes), `src/modsprite_data.c`, `modsprite_rom.mk`

## Regenerate the data

In the editor: **File ▸ Export ▸ SNES (PVSnesLib)...**, choose the game's PVSnesLib project folder (one with
`src/modsprite.c`, `src/modsprite_draw.asm` and `inc/modsprite.h`, like `snes_demo/`), the mappings and the sprite
sizes. The editor remembers them per project and shows what the game gets.

From the command line (the same exporter; run from the repo root):

```bash
python3 examples/snes/tools/export_snes.py --project-json examples/pop/PoP_WW.json --output-dir examples/snes/snes_demo
```

The release page has it built for Windows, macOS and Linux, without Python: `export_snes` (`export_snes.exe`) takes the
same options (`build_snes_exporter.spec`; the release workflow checks that it writes exactly what the script writes). The
Windows kit has it with `export_to_snes.bat`, which exports a project dragged onto it into the demo and builds the ROM.

`--mapping all` (the default) bakes one data set per mapping plus index `0` (no mapping), `--setup snes_8_32` picks
other sprite sizes, `--mode parts_streamed` or `--mode frames_streamed` writes a streamed export
([Streamed exports](#streamed-exports); the default, `--mode parts`, keeps every tile in video memory), and `--strict`
makes the command fail (exit code 1) when Check Project finds errors.

## Build the demo

The demo needs [PVSnesLib](https://github.com/alekmaul/pvsneslib) 4.x (tested with 4.6.0): set `PVSNESLIB_HOME`, or
unpack a release into `snes_demo/third_party/pvsneslib` (the folder with `devkitsnes/` and `pvsneslib/`). Then:

```bash
cd examples/snes/snes_demo
make
```

This builds `modular_sprite_snes_demo.sfc` (FastROM, LoROM; 512 KB for the Prince of Persia example).

On Windows, PVSnesLib's rules need MSYS2 (`make`, `sh`, `sed`). Without it, unpack PVSnesLib's Windows release into
`snes_demo/third_party/pvsneslib` (or set `PVSNESLIB_HOME` to it) and run, in `snes_demo`:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File build_windows.ps1
```

`build_windows.ps1` takes the steps PVSnesLib's `snes_rules` takes for this project with its Windows tools: `hdr.asm`
from the Makefile's settings (and `modsprite_rom.mk`), every C file through `816-tcc`, `816-opt` and `wla-65816`, the
assembly files through `wla-65816`, `wlalink` with PVSnesLib's libraries (LoROM, like the demo). Its paths are relative,
so it builds in a folder whose path has spaces too. The Windows kit the release workflow assembles carries the demo
with PVSnesLib's Windows tools and `build_snes_demo.bat`, which runs it.

A ROM built on one system is not byte for byte one built on another: `wlalink` places sections of the same size (four
of the data chunks fill a bank each, and the compiler and PVSnesLib's libraries make many small code sections) in the
order the system's C library's `qsort` leaves them, as its comparison never says "equal"; a second `make` without
`make clean` also assembles the `hdr.asm` the first one left. What a build draws does not depend on it:
`tools/compare_snes_roms.py` (below) plays two builds and checks they draw the same.

The release page has the demo as `ModularSpriteEditor-snes-demo.zip`: the ROM built and checked by the release
workflow, with this README and the `snes_demo` project (without PVSnesLib), in the repository's `examples/` layout.

The demo starts on the project's first scene. **Up / Down** switch between scenes, animations, frames and modules,
**Left / Right** browse (held: faster), **A** plays and pauses, **B** shows hitboxes and points, **X** changes the
look (every mapping with every palette swap, then one animation drawn twice, the second re-skinned and recoloured),
**Start** shows the controls and what a frame costs (frames a second, the share of the frame the work takes, the
sprites, the tiles, sprites lost to the limits of a line). Built from a streamed export, it shows the most tiles one
frame uploaded instead of the tiles, and how many draws waited for their tiles; the side-by-side look draws its
second character through a slot of its own.

## Check it in an emulator

`tools/check_snes_rom.py` (repository root) builds the runtime with a probe program in place of the demo's `main.c`
and plays it in Mesen 2's headless test runner: every frame at three positions as it is and mirrored, every module,
frames drawn until the 128 sprites run out, the scenes with every mapping, an animation drawn through another mapping
and swap, a game's own sprites across the screen's edges, the colour cycles;
each sprite table must equal the host build's byte for byte (which `tests/test_snes_runtime_draw.py` checks against
the editor; `tests/test_snes_runtime_player.py` checks the host build's animation player, hitboxes and points against
the editor's), video memory the export's tiles. It prints the slowest draw in scanlines and the lag frames of the first
scene. It needs Mesen 2 (`--mesen`, `$MESEN`) and PVSnesLib (`--pvsneslib`, `$PVSNESLIB_HOME`). The release workflow
runs it on Linux with Mesen 2.1.1 after building the demo, whose committed data must be what the exporter writes:
export it again and commit it whenever the exporter changes. On a machine where Mesen has never run, put a
`settings.json` holding `{}` next to its executable first, or it opens its setup window instead of running the check.
On Linux the tool runs Mesen with `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`: Mesen 2.1's core dies with `std::bad_cast`
while loading when .NET has loaded the system's ICU first.

```bash
python3 tools/check_snes_rom.py [PROJECT.json ...]
```

With `--mode parts_streamed` or `--mode frames_streamed` it checks a streamed export: the probe uploads after each draw
(`ms_upload_tiles`, timed too), and the slots' video memory after every draw must equal the host build's
(`tests/test_snes_streaming.py` checks the host build against the editor: every frame of the testbeds, mirrored ones,
two characters in two slots, modules and the Swordfight as the resident export draws them, uploads waiting for the
budget or cut off by the end of the blank, the load lists a game's own slots ask for). `--timings FILE` writes each draw's scanlines and its upload's, with what it uploaded. The
release workflow checks PoP and Sonic both ways.

`tools/compare_snes_roms.py` carries that over to a demo ROM built elsewhere: it plays two builds in Mesen with the same
presses through every view (the first scene, animations with hitboxes and every look, frames, modules) and checks that
both show the same sprite table on every video frame, the same palettes whenever they change and the same video memory
at the end. Each build plays twice, with work RAM filled with zeros and with 0xFF at power-on, and all four runs must
be the same: a program that reads memory it never wrote is caught (Mesen's own random fill would catch it only now and
then; video memory, the sprite table and the palettes start as zeros). It lists the reads of unwritten memory Mesen
reports. The presses need a SNES controller on port 1 in Mesen's settings, which Mesen's defaults do not have: next to
the executable, a `settings.json` holding `{"Snes": {"Port1": {"Type": "SnesController"}}}` connects one (the check
fails when the sprite table moves while the demo should be paused). The release workflow compares the Windows kit's
build with the Linux one this way.

```bash
python3 tools/compare_snes_roms.py REFERENCE.sfc OTHER.sfc
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
- PVSnesLib's start-up code clears no RAM: a global without an initial value starts with whatever the console's RAM
  held at power-on, not zero (initialised globals are copied from the ROM). The runtime gives everything it reads a
  value in `ms_init_ex`; a game must do the same with its own (the demo's text rows once took their state from it).
