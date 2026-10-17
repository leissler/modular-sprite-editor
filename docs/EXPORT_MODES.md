# Export modes: parts or whole frames, resident or streamed

A console export can store the sprites three ways. Two separate choices make them: what the cartridge stores (parts or
whole frames) and where the tiles live (all of them in video memory, or only what is on screen).

| Way | Mega Drive (SGDK) | SNES (PVSnesLib) |
|---|---|---|
| Parts, resident | yes (the default) | yes (the default) |
| Parts, streamed | yes | yes |
| Whole frames, streamed | yes | yes |

File ▸ Export ▸ *Console (SDK)* shows what each way would cost on the project, measured for the chosen mappings and
setup, and where the console's runtime streams, offers the choice (**Store as**, remembered per project). The command
line takes `--mode parts | parts_streamed | frames_streamed` (`export_megadrive`, `export_snes`). Check Project and the
budget readout follow the way chosen last for the project.

## Three ways

**Parts, resident** (the default). Each module's tiles are stored once, a frame is its parts put together when it is
drawn, and video memory holds every tile the export stores, so the runtime only writes the sprite table: no uploads
while the game runs. The cartridge stays small and mappings are free (a re-skin swaps modules at draw time), but video
memory must hold every tile of the project, and a frame takes as many hardware sprites as its parts, overlaps included.

**Parts, streamed.** The cartridge holds the same parts and tiles. Video memory holds a slot for each thing drawn at the
same time, as big as the largest frame it shows; when it shows a frame whose tiles the slot does not hold, they are
uploaded into it. Mappings stay free. Sonic's games do this with their "pattern load cues": art in the cartridge, a list
per frame of the tiles to copy.

**Whole frames, streamed.** Each frame is flattened into one picture per palette and cut into the console's hardware
sprites like a part, so overlapping parts cost nothing: the fewest hardware sprites, the fewest on a line. The cartridge
holds every frame's picture (identical tiles once), and each mapping is baked again. Mirrored steps reuse the upright
pictures with hardware flips; turned ones are pictures of their own, as turned parts are.

Whole frames kept resident are not offered: their tiles are what no console's video memory holds (PoP needs 6209 tiles
on the Mega Drive, which has about 1424 free).

## What is measured

`export_modes.measure(project, export, setup_key, mappings)` bakes the project with the console's own exporter (its
`bake_context`: the same cut and the same tiles as its export, nothing written), once with parts and once with whole
frames, and reports for each way:

| Number | What it is |
|---|---|
| Video memory | Resident: every tile stored. Streamed: a player's slot, the most tiles a module, frame or animation step shows; and a scene's slot, the most one of its samples shows. The SNES's slots are whole rows of its sprite tables (16 tiles, aligned to the large sprites), as its export lays them out: `ConsoleBake.stream_slots`. |
| Cartridge | Every tile stored, once (identical tiles shared), at 32 bytes a tile (4 bits a pixel). Only the tiles: the records come on top. |
| Hardware sprites | Per animation step (per frame in a project without animations), on average and at most. |
| Busiest line | The most hardware sprites a line of pixels crosses in one step, against the setup's limit. |
| Upload a step | Streamed: the bytes of a step's tiles, uploaded when it starts. |
| Busiest scene line | The same for a scene sample, every object (on screen or not). |

Every mapping is baked, as the export does by default. Modules drawn on their own (`ms_draw_module`) are part of the
export in every way: flattened too in whole frames, so a frame of one module shares its picture.

## Measured

Mega Drive in H40 (20 sprites on a line), SNES with 8×8 and 16×16 sprites (32 on a line); every mapping.

### Prince of Persia (two mappings, the Swordfight scene)

Mega Drive:

| | Video memory | Cartridge: tiles | Hardware sprites | Busiest line | Upload a step | Busiest scene line |
|---|---|---|---|---|---|---|
| Parts, resident | 305 tiles | 305 (9.5 KB) | 9.3 a step, 21 at most | 14 of 20 | nothing | 20 of 20 |
| Parts, streamed | 39 tiles a player, 65 a scene | 305 (9.5 KB) | 9.3 a step, 21 at most | 14 of 20 | 500 B, 1248 B at most | 20 of 20 |
| Whole frames, streamed | 22 tiles a player, 38 a scene | 6209 (194.0 KB) | 1.2 a step, 3 at most | 2 of 20 | 341 B, 704 B at most | 3 of 20 |

SNES:

| | Video memory | Cartridge: tiles | Hardware sprites | Busiest line | Upload a step | Busiest scene line |
|---|---|---|---|---|---|---|
| Parts, resident | 300 tiles | 300 (9.4 KB) | 14.0 a step, 30 at most | 21 of 32 | nothing | 25 of 32 |
| Parts, streamed | 64 tiles a player, 64 a scene | 300 (9.4 KB) | 14.0 a step, 30 at most | 21 of 32 | 505 B, 1184 B at most | 25 of 32 |
| Whole frames, streamed | 32 tiles a player, 64 a scene | 4912 (153.5 KB) | 4.3 a step, 11 at most | 6 of 32 | 314 B, 736 B at most | 8 of 32 |

The SNES's slots are rows of 16 tiles, two at a time for 16×16 sprites: a step's 37 tiles at most take four rows,
the Swordfight's 63 four as well (with whole frames 23 and 38: two and four).

Without the mappings, whole frames on the Mega Drive take 3374 tiles (105.4 KB); everything else stays about the same.

### Sonic (no mappings, no scenes)

Mega Drive:

| | Video memory | Cartridge: tiles | Hardware sprites | Busiest line | Upload a step |
|---|---|---|---|---|---|
| Parts, resident | 620 tiles | 620 (19.4 KB) | 2.0 a step, 6 at most | 4 of 20 | nothing |
| Parts, streamed | 34 tiles a player | 620 (19.4 KB) | 2.0 a step, 6 at most | 4 of 20 | 598 B, 1088 B at most |
| Whole frames, streamed | 27 tiles a player | 1225 (38.3 KB) | 1.8 a step, 3 at most | 3 of 20 | 586 B, 864 B at most |

SNES:

| | Video memory | Cartridge: tiles | Hardware sprites | Busiest line | Upload a step |
|---|---|---|---|---|---|
| Parts, resident | 600 tiles | 600 (18.8 KB) | 7.5 a step, 15 at most | 10 of 32 | nothing |
| Parts, streamed | 64 tiles a player | 600 (18.8 KB) | 7.5 a step, 15 at most | 10 of 32 | 589 B, 960 B at most |
| Whole frames, streamed | 32 tiles a player | 1104 (34.5 KB) | 6.4 a step, 12 at most | 5 of 32 | 593 B, 800 B at most |

### Adventurer (frames of one whole sprite each, no animations)

Mega Drive:

| | Video memory | Cartridge: tiles | Hardware sprites | Busiest line | Upload a frame |
|---|---|---|---|---|---|
| Parts, resident | 381 tiles | 381 (11.9 KB) | 1.0 a frame, 1 at most | 1 of 20 | nothing |
| Parts, streamed | 12 tiles a player | 381 (11.9 KB) | 1.0 a frame, 1 at most | 1 of 20 | 250 B, 384 B at most |
| Whole frames, streamed | 12 tiles a player | 369 (11.5 KB) | 1.0 a frame, 1 at most | 1 of 20 | 250 B, 384 B at most |

SNES:

| | Video memory | Cartridge: tiles | Hardware sprites | Busiest line | Upload a frame |
|---|---|---|---|---|---|
| Parts, resident | 329 tiles | 329 (10.3 KB) | 4.8 a frame, 7 at most | 4 of 32 | nothing |
| Parts, streamed | 32 tiles a player | 329 (10.3 KB) | 4.8 a frame, 7 at most | 4 of 32 | 269 B, 352 B at most |
| Whole frames, streamed | 32 tiles a player | 256 (8.0 KB) | 3.7 a frame, 6 at most | 3 of 32 | 228 B, 352 B at most |

### On the Mega Drive itself

The SGDK demo built three ways from PoP, measured in BlastEm while it plays the Swordfight (600 frames): the 68000's
time to draw a frame, in scanlines (the demo's own V counter span around drawing; a frame has 262).

| | Drawing, on average | Frames that upload | At most |
|---|---|---|---|
| Parts, resident | 32.2 lines | none | 42 |
| Parts, streamed | 36.9 lines | 67.8 lines (one in nine frames) | 88 |
| Whole frames, streamed | 11.2 lines | 16.5 lines | 21 |

The uploads themselves happen in the vertical blank (up to 2 KB here; SGDK's DMA queue sends about 7 KB in one, NTSC).
What costs the 68000 time is queueing them: about 2.3 scanlines for each run of tiles (SGDK's `DMA_queueDmaFast`), and a
Swordfight sample of two characters in parts has 12.8 runs on average, 21 at most (a step 6.5). Whole frames have one to
four runs a list, so they upload almost for free and draw in a third of the resident time. In MAME, the three ROMs show
the same pictures on every one of 50 snapshots (the Swordfight as it plays, 25 frames, 13 modules).

### On the SNES itself

The SNES demo built three ways from PoP, measured in Mesen 2 while it plays the Swordfight (600 frames): the 65816's
time from `ms_begin_frame` to `ms_end_frame`, and what `ms_upload_tiles` takes in vertical blank, in scanlines.

| | Drawing, on average | At most | Uploads (vertical blank) |
|---|---|---|---|
| Parts, resident | 31.4 lines | 39.4 | none |
| Parts, streamed | 33.8 lines | 44.5 | 17.8 lines in one frame in nine, 25.7 at most |
| Whole frames, streamed | 21.5 lines | 28.2 | 11.3 lines in one frame in nine, 14.3 at most |

A draw through a slot costs about 3 scanlines more with parts (816-tcc's C finds the list and queues it); whole frames,
fewer sprites, draw in two thirds of the resident time. The uploads happen in vertical blank, which the 65816 has from
scanline 230 to 261 once PVSnesLib's interrupt has sent the sprite table (from 242 when it sends the text map too):
`ms_send_uploads` (65816 assembly) costs 8.5 master cycles a byte, 533 a run, 611 a group of runs from one chunk and 939
a list (1364 a scanline; tools/check_snes_rom.py --timings, fitted to within a quarter scanline), which the export
counts into each list's cost. `tools/check_snes_rom.py --mode` checks every draw of PoP, Sonic and the Adventurer in
both streamed ways (sprite tables, the slots' video memory, palettes) against the host build: alike, and the Swordfight
plays without a lag frame in every way.

## What the numbers say

- **Streaming makes video memory small.** One player's slot is 12 to 39 tiles with parts on the Mega Drive (32 to 64 on
  the SNES, whole rows), against 300 to 620 resident. A streamed export is how a project bigger than video memory gets
  onto a console at all: Sonic needs 600 tiles on the SNES, more than its 512, but a slot of 64 streamed.
- **Uploads are small; queueing them is what costs.** At most 2 KB when a frame or a scene sample changes, well inside
  a vertical blank, but each run of tiles costs the Mega Drive's 68000 about 2.3 scanlines to queue. Art in many small
  shared parts (PoP) has many runs a frame. The SNES sends its own DMA in vertical blank, about 0.4 scanlines a run,
  but the rows of a square's tiles lie 16 tiles apart in video memory, so it has more runs (8.5 a step and 15.6 a
  Swordfight sample with parts, against 6.5 and 12.8 on the Mega Drive).
- **Whole frames pay off for art drawn in overlapping parts.** PoP's frames are many parts over each other (a quarter
  of its pixels are hidden): flattened, a step takes 1.2 hardware sprites instead of 9.3 on the Mega Drive, 2 on a line
  instead of 14, and the Swordfight 3 instead of 20 (the H40 limit, so sprites would vanish); drawing takes a third of
  the time. The cartridge pays: 20 times the tiles, about 194 KB with the two mappings. The SNES gains less (4.3 instead
  of 14.0 a step): its two square sizes fit a whole frame less closely than the Mega Drive's sixteen.
- **Art sliced into whole sprites gains nothing from whole frames.** Sonic's frames are mostly one part each: 1.8
  sprites a step instead of 2.0, for twice the cartridge. The Adventurer's frames are one sprite each: on the Mega
  Drive the three ways differ only in where the tiles live; on the SNES whole frames come out a little smaller (3.7
  sprites a frame instead of 4.8, 256 tiles instead of 329), because a flattened frame is cut from where its pixels
  start and a module from the corner of its 32×32 cell.

So no one way wins: resident parts are the simplest when everything fits, parts streamed suit big projects and consoles
with little video memory, and whole frames suit characters drawn in many overlapping parts where the sprites per line
run out.

## How the Mega Drive streams

- **Data** (blob version 6; a resident export still writes version 5, byte for byte as before): every render frame names
  a load list, the runs of tiles a slot takes for it, one after the other from the slot's first tile; identical lists
  are stored once. Its pieces count their tiles from the slot. The tiles are laid out in the order frames first use
  them, so a frame's tiles mostly lie together (fewer runs). The generated header defines `MS_STREAMED`,
  `MS_SLOT_TILES` (a player's slot) and `MS_SCENE_SLOT_TILES` (a scene's).
- **Runtime** (`modsprite.c`): whatever is drawn goes through a slot (`MS_Slot`). Drawing a render frame whose list the
  slot does not hold queues its runs (`DMA_queueDmaFast`), which reach video memory with the sprite table at the next
  vertical blank; the pieces are then drawn from the slot. `ms_init()` makes a default slot at its tile index, as big
  as either kind; a game gives everything else drawn at the same time a slot of its own (`ms_slot_init`) and sets it
  before drawing (`ms_set_slot`), like the mapping. A scene streams through one slot, a sample's tiles at a time, so a
  sample that only moves its objects uploads nothing. A run SGDK refuses (its DMA queue is full) leaves the slot
  holding nothing, so the next draw queues the list again. `MS_FrameProfile.tiles_uploaded` counts a frame's uploads.
  In a resident export the slot functions do nothing.
- **Checks**: the export report and Check Project (for the way chosen last) give the slot sizes and how many players can
  change steps in one frame, and warn when a slot takes longer to fill than a vertical blank carries
  (`project_check.megadrive_stream_issues`). The budget readout shows a view's tiles as what it uploads.
- **Tests**: `tests/test_megadrive_streaming.py` compiles the runtime for the host with a streamed export: every frame
  of the three testbeds as the editor draws it (uploads only when the list changes), two players in two slots, every
  module and the Swordfight in every mapping as the resident export draws them, a run the DMA queue refuses queued
  again, and the version 6 header as the generated parser reads it.

## How the SNES streams

- **Data** (data version 3; a resident export still writes version 2, byte for byte as before): the cartridge holds the
  squares in strips: each render frame's new squares, in the order frames first use them, side by side in rows of at
  most 16 tiles, one row of tiles after the other, so a frame's squares mostly lie together. Every render frame names a
  load list: its strips' pieces placed in a slot (largest squares first, each aligned to its size, as the PPU finds a
  square's tiles 16 to a row), as DMA runs (a row of a piece each; runs that follow each other in the cartridge and in
  the slot are merged, so a strip as wide as the slot is one run), in groups of one chunk, with what uploading it costs.
  Its sprites count their tiles from the slot. The generated header defines `MS_STREAMED`, `MS_SLOT_TILES`,
  `MS_SCENE_SLOT_TILES`, `MS_SLOT_ALIGN` (a slot's first tile is a multiple of it) and `MS_UPLOAD_BUDGET`.
- **Runtime** (`modsprite.c`, `modsprite_draw.asm`): slots as on the Mega Drive (`MS_Slot`, `ms_slot_init`,
  `ms_set_slot`, the default one from `ms_init` at tile 0). Video memory can only be written in vertical blank, so a
  draw whose slot does not hold its list queues it, and `ms_upload_tiles()`, called right after `WaitForVBlank()`
  (PVSnesLib has sent the sprite table then, in the same blank), sends the queued lists (`ms_send_uploads`: DMA channel
  0, a run each) and the sprite palettes `ms_palette_tick` prepared. A frame's uploads stay within a budget
  (`ms_set_upload_budget`, `MS_UPLOAD_BUDGET`: what PVSnesLib's interrupt leaves of the blank); a draw over it shows
  what its slot holds (the step before) and uploads in a later frame; the first list of a frame goes whatever it costs.
  Before and after each list HVBJOY says whether the blank still lasts; a list cut off is queued again when it is drawn
  next. A slot shows one thing a frame; a scene streams through one slot, a sample's tiles at a time.
  `MS_FrameProfile.tiles_uploaded` and `uploads_waiting` count them; `ms_upload_queued()` says what a frame queued (the
  demo writes a text row only when the uploads leave room for its text map in the same blank).
- **Checks**: the export report and Check Project give the slot sizes and warn when filling one costs more than the
  budget (`project_check.snes_stream_issues`, with the largest list's cost).
- **Tests**: `tests/test_snes_streaming.py` (the host build, `tools/snes_host.py`): every frame of the three testbeds in
  both ways as the editor draws it (uploads only when the list changes), two characters in two slots, every module and
  the Swordfight in every mapping as the resident export draws them, uploads that wait for the budget, a list cut off by
  the end of the blank queued again, the slot layout, the command line; `tools/check_snes_rom.py --mode` in Mesen 2.

Possible next steps: merging runs across gaps of a tile or two (fewer runs for a few more tiles in the slot: on PoP's
Swordfight 9.7 runs a sample instead of 12.8 on the Mega Drive, for a slot of 71 tiles instead of 65); a slot per scene
object, so a sample uploads only the objects whose step changed; the SNES's slot test in assembly (its 3 scanlines a
draw). The NES copies tiles into CHR-RAM in vertical blank, roughly a dozen a frame, or switches CHR-ROM banks (MMC3)
instead; the Game Boy copies about as many (the Game Boy Color's HDMA more); the Game Boy Advance's DMA copies far more
than a frame needs.

## How it is built

- `console_bake.ConsoleBake.whole_frames`: frames (and modules drawn on their own) are drawn as the editor draws them
  (`compositor.render_instance`) into one layer per palette, each pixel in the layer of the part on top, so layers never
  overlap; each layer goes to the console's `_store_part` like a part.
- Each console's exporter adds `_stored_part(stored)` (a stored part's padded size and its hardware sprites with their
  tile blocks) and `bake_context(project, mappings, setup_key)` (its bake, nothing written). From these,
  `ConsoleBake.render_frame_sprites` and `load_list` work for any console; `stream_slots` and `stream_upload_cost` are
  the slots and the largest upload as the console's export lays them out (the SNES's own: whole rows, runs counted).
- `export_modes.py` measures; `ui/console_export_dialog.py` shows the table and the choice; the registry entry
  (`console_exports.ConsoleExport.modes`) says which ways the console's runtime can do.
- `tests/test_export_modes.py`: whole frames rebuild every frame, step and module of PoP (every mapping) pixel for pixel
  as `FrameRenderer` draws them, with no two layers overlapping; layers split by palette; the parts measured equal
  `hardware_budget.export_tiles` on both consoles.
