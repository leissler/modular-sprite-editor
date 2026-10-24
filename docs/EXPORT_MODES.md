# Export modes: parts or whole frames, resident or streamed

A console export can store the sprites three ways. Two separate choices make them: what the cartridge stores (parts or
whole frames) and where the tiles live (all of them in video memory, or only what is on screen). Between parts and whole
frames, chosen frames can be stored whole while every other frame stays parts ([Some frames whole](#some-frames-whole)).

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

## Some frames whole

A frame marked **Store whole** (the Frames tab's inspector, or every frame of a group from the frame list's right-click
menu; `Frame.store_whole`, project format 9) is stored as one picture per palette, cut into the fewest hardware sprites,
in the parts ways too, while every other frame stays parts. It suits the few frames of many overlapping parts that
show often: a platform or a crusher built from a dozen pieces, a pressure plate, a torch. Characters stay parts: their
frames share parts, and their mappings re-skin them for free (stored whole, PoP: Warrior Within's characters would take
351 KB of cartridge, 1.7 MB with the guards' eight mappings, against 26 KB as parts).

- A frame stored whole is drawn as its pictures wherever it shows: on its own, as an animation step, in a scene, and
  nested in a frame of parts (its pictures in its place, between the parts before and after it). Moved or mirrored, it
  shows its upright pictures with hardware flips; turned, pictures of its own.
- Each mapping that changes one of its modules stores its pictures again; the same pictures are stored once.
- Its modules keep their own tiles (a game can draw any module on its own, `ms_draw_module`), so the pictures' tiles
  come on top of theirs.
- The runtimes need nothing new: a frame stored whole is an ordinary render frame whose parts are its pictures.
- Whatever counts sprites and tiles counts it whole, as the exporters store it: the budget overlay and readouts,
  `hardware_budget.export_tiles`, Check Project's video memory (its too-many-tiles issue names the frames stored whole),
  `export_modes.measure` and the export dialog's table. The export report says how many frames it stored whole. The
  Frames inspector shows the frame's hardware sprites both ways on the project's console, and the tiles of its pictures.
- *Whole frames, streamed* stores every frame whole: there the mark changes nothing.

### Measured: Prince of Persia: Warrior Within's gameplay sprites

The native Mega Drive game (its `tools/make_sprites.py`) flattened 54 frames outside the editor: the platforms and
crushers its levels show, the pressure plates, the decorations of three parts or more, and two runs of chain links
(frames nesting the link frame). Its project rebuilt with those frames marked Store whole instead (664 frames, 399
modules, eight mappings), measured through the editors' exporters and budget, no mapping:

| Frames stored whole | Mega Drive H40: sprites, parts → whole | Busiest line | SNES 8×8 / 16×16 | Busiest line |
|---|---|---|---|---|
| Platforms (12) | 4–16, 7.5 on average → 2–7, 3.7 | 12 → 4 | 12–45, 22.7 → 8–23, 13.7 | 26 → 9 |
| Crushers (5) | 12–16, 14.0 → 5 | 4 → 3 | 28–40, 34.0 → 19–23, 20.2 | 8 → 5 |
| Pressure plates (6) | 11–20, 15.5 → 5 | 11 → 3 | 27–45, 36.0 → 16 | 18 → 5 |
| Decorations (29) | 3–20, 8.4 → 1–5, 2.6 | 12 → 3 | 3–20, 8.5 → 2–15, 6.1 | 12 → 5 |
| Chain runs (2) | 4–5 → 1–2 | 1 → 1 | 4–5 → 4–5 | 1 → 1 |

The cartridge, every mapping: on the Mega Drive 1391 tiles before, 2290 after (899 more, 28.1 KB); the blob of the
game's way (parts streamed) 853,356 bytes before, 880,958 after (27.0 KB more; resident 677,756 and 704,180). On the
SNES with 8×8 and 16×16 sprites 1320 tiles before, 1954 after (19.8 KB more); with 16×16 and 32×32, 2040 and 3264 (38.2
KB more). The SNES export of this project stops at its names (57 KB, more than a ROM bank) before and after alike; its
tiles come from the bake. A player's slot (streamed) stays 91 tiles on the Mega Drive, 96 on the SNES.

Every one of the 54 frames comes out exactly as the game flattened it: the same hardware sprites and the same pixels. The
game's two passes cost it 14 KB and 18.8 KB of cartridge; with the frames marked in the editor, the same frames cost 27.0
KB.

### Side by side

A game's limit is a few characters at once, not one frame. With the budget on, the Animations inspector says how many
copies of the animation fit side by side before sprites drop (`hardware_budget.side_by_side`): copies on the same lines
add up, so it is the busiest line of all its steps against a line's sprites and pixels, and every copy's sprites against
the screen's. PoP's 68 animations on the Mega Drive in H40: as parts, 10 of them fit once on a line, 49 twice and 9
three times; whole, 5 to 20 times (the attack, *C34 Attack*: once as parts, 8 times whole). On the SNES with 8×8 and
16×16 sprites: 1 to 5 as parts, 4 to 16 whole.

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

- **Data** (blob version 8; a resident export writes version 7: both versions 6 and 5 with each module's flip offset,
  for modules mirrored in place): every render frame names
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
  In a resident export the slot functions do nothing. A game with many actors can let the runtime keep the slots
  instead: [one slot cache](#one-slot-cache-for-every-actor) shares a slot per frame among everything that shows it.
- **Checks**: the export report and Check Project (for the way chosen last) give the slot sizes and how many players can
  change steps in one frame, and warn when a slot takes longer to fill than a vertical blank carries
  (`project_check.megadrive_stream_issues`). The budget readout shows a view's tiles as what it uploads.
- **Tests**: `tests/test_megadrive_streaming.py` compiles the runtime for the host with a streamed export: every frame
  of the three testbeds as the editor draws it (uploads only when the list changes), two players in two slots, every
  module and the Swordfight in every mapping as the resident export draws them, a run the DMA queue refuses queued
  again, the version 8 header as the generated parser reads it, and the slot cache (`TestSlotCache`).

## How the SNES streams

- **Data** (data version 5; a resident export writes version 4: both versions 3 and 2 with each module's flip offset,
  and a streamed one with the rows of a slot each load list takes, `ms_load_list_rows`): the cartridge holds the
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
  demo writes a text row only when the uploads leave room for its text map in the same blank). The slot cache works as
  on the Mega Drive, its slots whole rows from a multiple of `MS_SLOT_ALIGN` (`ms_load_list_tiles` gives a list's rows
  in tiles); a new slot whose upload has no room in the budget shows nothing until it is uploaded.
- **Checks**: the export report and Check Project give the slot sizes and warn when filling one costs more than the
  budget (`project_check.snes_stream_issues`, with the largest list's cost).
- **Tests**: `tests/test_snes_streaming.py` (the host build, `tools/snes_host.py`): every frame of the three testbeds in
  both ways as the editor draws it (uploads only when the list changes), two characters in two slots, every module and
  the Swordfight in every mapping as the resident export draws them, uploads that wait for the budget, a list cut off by
  the end of the blank queued again, the slot layout, the command line, the slot cache (`TestSlotCache`);
  `tools/check_snes_rom.py --mode` in Mesen 2.

Possible next steps: merging runs across gaps of a tile or two (fewer runs for a few more tiles in the slot: on PoP's
Swordfight 9.7 runs a sample instead of 12.8 on the Mega Drive, for a slot of 71 tiles instead of 65); a slot per scene
object, so a sample uploads only the objects whose step changed; the SNES's slot test in assembly (its 3 scanlines a
draw). The NES copies tiles into CHR-RAM in vertical blank, roughly a dozen a frame, or switches CHR-ROM banks (MMC3)
instead; the Game Boy copies about as many (the Game Boy Color's HDMA more); the Game Boy Advance's DMA copies far more
than a frame needs.

## One slot cache for every actor

A game drawing many actors from a streamed export needs a slot for everything on screen at once, and two actors that
show the same frame should share one: the native Prince of Persia: Warrior Within built that around the runtime (496
tiles of slots, 48 of them, for every gameplay bank). The runtimes keep it themselves now:

```c
ms_slot_cache_init(ms_tile_base(), 496);   /* the pool: from now on every draw takes its slot from it */
ms_set_mapping(guard_mapping);
ms_draw_frame_flipped(frame, x, y, flip);  /* the slot that holds the frame under that mapping, or a new one */
```

- **One slot per load list** (a frame or module under a mapping), shared by every draw of it this frame and later,
  whoever draws it: the tiles are uploaded once, when it is first drawn.
- **First fit in tile order, in one walk** along the slots in the pool (the game's first version looked at every slot
  again behind each one in the way: 5 % of its level 5's time; one walk made the level 6 % faster). On the SNES slots
  are whole rows of the sprite tables from a multiple of `MS_SLOT_ALIGN`, a list taking the rows its squares need.
- **The slots drawn longest ago make room**, never one drawn this frame; a draw for which the slots in the way were all
  drawn this frame is left out. A slot is found by its list in a bucket of the list's low bits.
- **What it does**: `MS_FrameProfile` counts the slots drawn this frame (`slots_used`), the tiles uploaded and the draws
  left out (`draws_left_out`). `MS_CACHE_SLOTS` (48) slots at most; `ms_slot_cache_clear()` forgets what the pool holds
  (its video memory was used for something else); `ms_set_slot()` goes back to slots of the game's own,
  `ms_use_slot_cache()` to the cache. The SNES's upload budget still holds: a new slot whose upload waits shows nothing.
- **Cost**: a draw through the cache finds its slot in about 1.3 scanlines on the Mega Drive (BlastEm: pictures of 7
  to 24 draws of PoP, everything cached, 131 to 411 scanlines against 122 to 383 drawn resident) and about 1.5 on the
  SNES (Mesen: one frame drawn eight times, 403 scanlines through the cache, 391 through the default slot that holds
  it; the lookup is 65816 assembly, `ms_cache_hit`, its misses C). Making room walks the slots in the pool once.
- **Checked**: `tests/test_megadrive_streaming.py` and `tests/test_snes_streaming.py` play five actors through a cache
  with room for two thirds of their busiest frame, and one with room for less than a frame: every frame against a
  reference cache (`tests/runtime_models.py`: what it uploads, the slots it uses, the draws it leaves out) and the
  editor (what shows, from the video memory the runtime uploaded into); `tools/check_snes_rom.py --mode` draws pictures
  through the cache in Mesen against the host build.

## When a picture asks for too many sprites

The hardware shows 80 sprites (the Mega Drive in H40) or 128 (the SNES). The runtimes are given the draws front to back,
so what drops when a picture asks for more are the pieces drawn last, whatever they are: spikes behind three fighters,
while their shadows stay. A game marks what may give way, like the mapping:

```c
ms_set_give_way(1);  /* shadows: the first to go */
draw_shadows();
ms_set_give_way(2);  /* decorations and effects: after the shadows */
draw_decorations();
ms_set_give_way(0);  /* everything else stays */
draw_characters();
```

When the picture asks for more than the limit, the draws with a level are left out, level 1 first, within a level the
farthest (drawn last) first, as many as the picture asks too much; only after that do pieces drop, from the back, as
they do without levels. A game's own sprites (`ms_add_hw_sprite`) take the level too. `MS_FrameProfile.draws_given_way`
counts them.

**No second submission.** The native PoP drew each picture, read every draw's cost from the profile, then drew the
picture again without the draws that gave way. The runtimes resolve it in one: draws go into the sprite table as they
come while they fit (a give-way draw is noted: where its sprites are); from the first draw that does not fit, it and the
rest of the frame wait in a queue (`MS_QUEUED_DRAWS`, 32), each with the sprites it puts on the screen (its record's
count when its box is on the screen, else counted). `ms_end_frame()` then chooses what gives way (the same greedy:
level by level, the farthest first, as many as the excess), takes the written ones out of the table (the sprites after
them move up) and draws the waiting ones that stay behind what is there, exactly as they would have been drawn. A
picture that fits never waits. Without a level ever set none of it runs, so existing games draw byte for byte as before.
`MS_GIVE_WAY_DRAWS` (32) written give-way draws a picture can make room with; past the queue's room a draw is left out,
its sprites counted as dropped.

Measured with the probes of `tools/check_snes_rom.py` (Mesen 2) and `tools/check_megadrive_rom.py` (BlastEm 0.6.2, the
runtime's 68000 draw loops), the V counter from the top of the screen, frames counted: crowds of PoP's frames, modules
and a few sprites of the game's own across the screen and its edges, mirrored and re-skinned, give-way levels at
random; a picture that fits and pictures over the limit, each drawn as it is (the back-most pieces drop), as a game
that measures and draws again would (as it is, then only the draws that stay), and with its levels. In scanlines:

| | Mega Drive (80 sprites), PoP resident | SNES (128 sprites), PoP resident |
|---|---|---|
| A picture that fits: as it is / with levels | 94 / 99 (96 with levels on, none set) | 140 / 160 (154 with levels on, none set) |
| Over the limit, with levels | 227–398 (5 pictures) | 371–554 (5 pictures) |
| Over the limit, measured and drawn again | 336–563: give-way levels take 29–41 % less | 456–783: 14–29 % less |
| Over the limit, as it is (pieces drop from the back) | 188–349 | 256–411 |

Streamed (parts) the SNES's pictures over the limit take 164–215 scanlines with levels against 275–352 measured and drawn
again (Sonic 219–268 against 351–439). On the SNES the watching is 65816 assembly (`ms_draw_put`, `ms_put_watched`: a
draw is drawn, and taken back only when it dropped sprites), which keeps a draw that fits to about two scanlines more.

**Not flicker.** The native PoP also built the other answer to too many sprites: a second version of the sprite table,
shown every other frame by the vertical interrupt, which leaves out the pieces in front of the ones lost on a line until
those fit. It did what it was built for (pieces cut off two frames in a row went from 171 / 97 / 142 / 27 to
6 / 2 / 1 / 0 over four plays), but it looked worse than the hole. With only the sprites shown (a cartridge with the
level's palettes magenta), the table as sent missed 5 to 37 visible pixels a picture on average, none in about half of
them, at most 164: the parts drawn over the lost ones cover them. The flickering version got 194 to 255 pixels wrong on
average, at most 574: what it leaves out are those parts drawn over the lost ones. At 30 Hz the eye sees both, so a
small steady gap becomes large parts of the guards flickering. It also took about 17 % of the 68000 in level 4's fight
and 2 KB of cartridge. So the runtimes keep the hardware's answer, the back-most pieces dropping, and give-way levels
choose what goes before that.

## How it is built

- `Frame.store_whole` (a frame marked so) and `console_bake.ConsoleBake.whole_frames` (every frame, and the modules
  drawn on their own: the whole frames mode): a frame stored whole is drawn as the editor draws it into one layer per
  palette (`compositor.palette_layers`, which `hardware_budget` counts with too), each pixel in the layer of the part on
  top, so layers never overlap; each layer goes to the console's `_store_part` like a part. A frame of parts that nests
  one stored whole gets its layers in the nested frame's place (`compositor.collect_leaf_instances(..., whole=True)`).
- Each console's exporter adds `_stored_part(stored)` (a stored part's padded size and its hardware sprites with their
  tile blocks) and `bake_context(project, mappings, setup_key)` (its bake, nothing written). From these,
  `ConsoleBake.render_frame_sprites` and `load_list` work for any console; `stream_slots` and `stream_upload_cost` are
  the slots and the largest upload as the console's export lays them out (the SNES's own: whole rows, runs counted).
- `export_modes.py` measures; `ui/console_export_dialog.py` shows the table and the choice; the registry entry
  (`console_exports.ConsoleExport.modes`) says which ways the console's runtime can do.
- `tests/test_export_modes.py`: whole frames rebuild every frame, step and module of PoP (every mapping) pixel for pixel
  as `FrameRenderer` draws them, with no two layers overlapping; layers split by palette; the parts measured equal
  `hardware_budget.export_tiles` on both consoles. Some frames stored whole (`tests/mixed_frames.py`: 50 of PoP's, and
  a project of two palettes whose whole frames nest and are nested, mirrored and turned): every frame, step and
  Swordfight sample of every mapping as the editor draws it.
- `tests/test_hardware_budget.py`: with frames stored whole, the budget places every part as the Mega Drive exporter
  does, and its tile totals are both exporters' (three SNES setups; every frame whole too).
- `tests/test_megadrive_runtime_draw.py`, `tests/test_snes_runtime_draw.py`: the host builds of both runtimes draw the
  mixed exports like the editor: every frame as it is and mirrored, the mirroring animations for the hero and the guard
  (whose mapping changes the pictures), and the nested project's frames and turned steps.
