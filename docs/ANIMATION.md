# Animation Capabilities & Roadmap

Focus: pixel art for retro consoles (Mega Drive / SGDK first, SNES / GBA / NES-class targets second).

## What exists today

**Frame-based animation (Animations tab, production ready)**
- An animation is a list of steps `(frame, duration in ticks, offset, flip X/Y, rotation)` with `fps` = ticks
  per second, playback `forward / backward / loop / ping_pong` and `loop_count`.
- Per-step offsets give root motion; the stage shows the motion path and moves the selected steps' offsets by
  drag or arrow keys.
- Editor (`ui/animation_editor/`, redesigned): animations list with thumbnails and length; a sequence on a tick
  ruler where each step is as wide as its hold (drag the edge to retime, drag to reorder, Alt copies, multi-select,
  copy/paste); contextual inspector (animation settings and whole-animation mirror / rotate / reverse, step
  frame / hold / offset / rotation / flips); onion skin, mirror preview, part bounds; playback that follows the
  SGDK runtime tick by tick with ¼×–2× preview speed; GIF export of one cycle through the parity-checked renderer.
- Collision boxes and control points live on frames, each with a type and a role; the Mega Drive runtime finds them
  per frame (`ms_find_hitbox` / `ms_find_point`), and Check Project warns when a frame repeats a type and role.
- Mappings swap or hide modules for every frame of every animation (costume / damage / invisibility states),
  baked by the exporters.

**Timeline scenes (Timeline tab)**
- Objects with a source (module / frame / animation / group), parenting, draw order, playback speed/offset/mode.
  An animation plays *as animated* by default (format v5): its own playback, repeat count, loop-from step and
  follow-up, through the same rules as the Animations tab and the runtime (`playback.py`); Loop / Play once /
  Ping-pong / Loop backwards override them.
- Keyframes: position, 90° rotation, flip and visibility (stepped: they change at the key), easing per segment
  (shape × direction, plus Hold),
  straight or curved motion paths with handles edited on the stage, per-key image swaps with hold semantics,
  swap offsets, root motion from the animation's step offsets.
- Editor (`ui/scene_editor/`): Library | Stage | contextual Inspector, one frame-based timeline with the layer
  tree and dopesheet side by side, Auto-Key, tween bars labelled with their easing, animation frame-change
  ticks, console screen guides.
- Scale and opacity are in the data model but deliberately not exposed (no hardware support on the main target).

**Runtime / export**
- SGDK: modules, frames, animations (`frame_index + duration_ticks` steps) and scenes (pre-sampled per tick) in a
  binary blob; flips become hardware H/V flags, other transforms are baked; per-mapping data sets; hitboxes and
  points per frame and step; every palette in a palette line of its own. The runtime keeps all tiles in VRAM and only
  writes the sprite table each frame (about 7 % of a frame per character, measured in BlastEm); the demo HUD shows
  hardware sprites per frame.
- RetroAnimator JSON with baked part images (active mapping baked); its report lists what the format has no place
  for (step events, loop-from steps, follow-ups, hitbox roles, scenes).

## Gaps that matter for retro work

1. **Hardware budget feedback (done for every console in the database).** The view bar's *Budget* choice (MD H40 /
   H32, SNES 8/16 and 16/32, NES and GB 8×8 / 8×16, GBA) in Frames, Animations and Timeline outlines the hardware
   sprites, marks scanlines over the sprite / pixel limit in red and shows sprites, tiles and the busiest line; the
   Animations inspector names the worst step. For the Mega Drive it also counts video memory as the export stores it
   (flips free): the view's tiles, the animation's and the whole project's against the ~1424 SGDK leaves free.
2. **Animation events (done, format v3).** Steps carry events from a project-wide list (name, colour, export
   number) with an optional value; they fire when the step starts and are active while it shows. The SGDK runtime
   answers `ms_anim_player_has_event` / `_event_started` / `_event_value`.
3. **Loop-from step and follow-up animation (done, format v3).** "Loop from" plays an intro once and then loops
   the rest; an animation that ends (Play once, or after its repeat count) hands over to its "Then play"
   animation — in the editor preview and in the SGDK runtime, which are tested to step identically.
4. **Palettes (done, formats v6 and v7).** Palettes are project data with a fixed slot order (the Palettes tab);
   every image belongs to one. Palette swaps recolour per slot and are chosen per draw like mappings (the preview,
   a Timeline object's Colours, `ms_set_palette_swap` / `ms_draw_anim_player_as` in the game), colour cycles turn
   runs of slots (`ms_palette_tick`); View ▸ Console Colours shows every canvas as the console does. See
   `docs/PALETTES.md`.
5. **Previews disagree (fixed).** All thumbnails and GIF export use the renderer that matches the canvas and the
   RetroAnimator export pixel-exactly (`ui/frame_render.py`, checked by `tests/test_thumbnails.py` and
   `tools/check_export_parity.py`).
6. **Timing UX (done).** Duration-scaled cells, hold dragging, multi-select, step rotation, preview speed, the
   game's own timing in the preview (steps in whole video frames, View ▸ Play at 50 Hz), spread presets for holds
   and Change Animations (one tick rate, playback or group for many).
7. **Interchange (done).** Sprite sheets with JSON (Aseprite / TexturePacker layout), Godot 4 SpriteFrames and
   Unity sprites, PNG sequences, scene GIFs; Aseprite files and sheets with JSON import, tags as animations.

## Recommended extensions (priority order)

### 1. Hardware budget overlay (done)
- Done: `hardware_budget.py` places parts exactly like the SGDK exporter (tested against it), cuts them into
  ≤32×32 VDP sprites on the 8 px grid (skipping empty blocks), and checks sprites per screen / per line and sprite
  pixels per line for MD H40 and H32; the SNES profiles cover parts with square small and large sprites, the NES and
  Game Boy ones with sprites of one size (8×8 or 8×16), the GBA one with the cheapest cover of its twelve shapes (a
  sprite weighing 8 tiles; 1210 drawing cycles a line). UI: *Budget*
  in the view bars (per tab, app preference), red scanlines, readout, worst step in the Animations inspector,
  whole-scene budget in the Timeline. Video memory: each part carries the tile blocks the export stores for it
  (`Budget.unique_tiles`, `export_tiles` equals the exporter's count).
- The project's target console (`Project.console`, format 7) sets its palettes; the budget menu offers every
  console's profiles whatever the target. Tiles streamed per step (DMA) do not apply: the runtime keeps every tile in
  VRAM. Next: exporters (and video memory counts) for the other consoles.

### 2. Step events (done)
- Data (format v3): `Project.event_types` (id, name, colour; order = export number), `AFrame.events`
  (`type_id`, `value`). Typing a new name in the inspector creates the type; *Event types…* renames, recolours and
  deletes. Events travel with copied / duplicated steps and show as coloured chips above the steps.
- Export: blob v2 with a per-step event range and an event table; `MS_EVENT_<NAME>` defines in the generated
  header. The RetroAnimator format has no place for events; its export says so in its report.

### 3. Loop-from step and follow-up animation (done)
- Data (format v3): `Animation.loop_start`, `Animation.next_animation_id`; scenes honour them too (follow-ups since
  format v5, for objects that play *as animated*).
- Runtime: `MS_Animation.loop_start / next_animation / loop_count`; `ms_anim_player_tick` loops from
  `loop_start`, counts passes and hands over to the follow-up. `tests/test_megadrive_runtime_player.py` compiles the C player
  and checks it against the editor preview tick by tick.

### 4. Timing tools (medium value, low effort)
- Done in the redesign: duration-scaled cells, edge-drag holds, multi-select edits, step rotation, preview speed.
- Still open: "spread" timing presets (1-1-2-2…), and a 60 Hz / 50 Hz display toggle to judge how ticks feel on
  NTSC vs. PAL.

### 5. One compositor for all previews and exports (correctness)
- Done: `compositor.render_frame(project, frame, mapping, transform, ...) -> image + handle` (`compositor.py`, verified
  against the canvas) draws every thumbnail, the frame strip, GIF export and the RetroAnimator export. The SGDK
  exporter shares its matrices and module images but cuts its own hardware-sprite pieces.

### 6. Palette awareness (done)
- Done (format v6): a palette per image, its colours in the Modules inspector, warnings over 15 colours, console
  colours on every canvas, one palette line per palette in the SGDK export.
- Done (format v7): palettes as project data in slot order (the Palettes tab), palette swaps chosen per draw like
  mappings (no tiles of their own in the export), colour cycles, the console database (`consoles.py`) that sizes
  palettes per console.
- Done: palettes for every console in the database (the Palettes tab's Console: SNES and GBA 15 colours in 5 bits a
  channel, NES and Game Boy 3 from their fixed colours, picked from a grid). Next: their exporters.

### 7. Attachment & constraints (done)
- Done (format v7): a Timeline object follows a point role of its parent's frames (Inspector ▸ Follows): weapons,
  effects and riders sit on the parent's per-frame point, mirror and turn with it, and hide on frames without the
  point; the SGDK export bakes them into the scene samples.
- Next: export the points as per-step socket offsets for objects the game moves itself.

### 8. Interchange (done)
- Done: File ▸ Export ▸ Sprite Sheet (packed PNG + JSON in the Aseprite / TexturePacker layout, Godot 4
  SpriteFrames `.tres`, Unity `.png.meta` with pivots), PNG sequences, scene GIFs; File ▸ Import ▸ Aseprite File
  (read like Aseprite flattens it, tags as animations) and Sprite Sheet with JSON.
- Next: Unity animation clips, Godot scenes with the hitboxes as areas.

### Not recommended for the retro target
- Sub-pixel tweening or free rotation/scaling inside frame animations (no hardware support on MD/NES; bake
  instead). Keep the timeline's scale/opacity hidden unless a SNES Mode 7 / GBA affine profile is added.
