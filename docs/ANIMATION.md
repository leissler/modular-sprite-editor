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
- Collision boxes and control points live on frames; `compile_animation_role_tables()` turns their roles into
  dense per-step lookup tables (`type + role → index`), validated by Tools ▸ Validate Roles.
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
  points per frame and step. The runtime keeps all tiles in VRAM and only writes the sprite table each frame
  (about 7 % of a frame per character, measured in BlastEm); the demo HUD shows hardware sprites per frame.
- RetroAnimator JSON with baked part images (active mapping baked).

## Gaps that matter for retro work

1. **Hardware budget feedback (done for Mega Drive).** The view bar's *Budget* choice (MD H40 / H32) in Frames,
   Animations and Timeline outlines the VDP sprites, marks scanlines over the sprite / pixel limit in red and shows
   sprites, tiles and the busiest line; the Animations inspector names the worst step. Still missing: other
   consoles, and tile dedupe / DMA-per-step numbers.
2. **Animation events (done, format v3).** Steps carry events from a project-wide list (name, colour, export
   number) with an optional value; they fire when the step starts and are active while it shows. The SGDK runtime
   answers `ms_anim_player_has_event` / `_event_started` / `_event_value`.
3. **Loop-from step and follow-up animation (done, format v3).** "Loop from" plays an intro once and then loops
   the rest; an animation that ends (Play once, or after its repeat count) hands over to its "Then play"
   animation — in the editor preview and in the SGDK runtime, which are tested to step identically.
4. **Palette is invisible.** The SGDK exporter quantises to a master palette, but the editor never shows which
   palette/line a part uses, cannot preview palette swaps (Mega Drive: 4 lines × 16 colours) and has no palette
   cycling.
5. **Previews disagree (fixed).** All thumbnails and GIF export use the renderer that matches the canvas and the
   RetroAnimator export pixel-exactly (`ui/frame_render.py`, checked by `tests/test_thumbnails.py` and
   `tools/check_export_parity.py`).
6. **Timing UX (mostly done).** Duration-scaled cells, hold dragging, multi-select, step rotation and preview
   speed exist now; still missing: a 50/60 Hz (PAL/NTSC) preview switch and timing presets.
7. **No sprite-sheet / engine export** beyond RetroAnimator and SGDK (Aseprite JSON, Godot/Unity sheets), and no
   Aseprite import for animators who draw there.

## Recommended extensions (priority order)

### 1. Hardware budget overlay (Mega Drive done)
- Done: `hardware_budget.py` places parts exactly like the SGDK exporter (tested against it), cuts them into
  ≤32×32 VDP sprites on the 8 px grid (skipping empty blocks), and checks sprites per screen / per line and sprite
  pixels per line for MD H40 and H32. UI: *Budget* in the view bars (per tab, app preference), red scanlines,
  readout, worst step in the Animations inspector, whole-scene budget in the Timeline.
- Next: SNES / GBA / NES profiles (different sprite shapes and limits), unique-tile counting with flip dedupe,
  tiles to stream (DMA) per animation step, and a per-project target (would be **format v3**, additive).

### 2. Step events (done)
- Data (format v3): `Project.event_types` (id, name, colour; order = export number), `AFrame.events`
  (`type_id`, `value`). Typing a new name in the inspector creates the type; *Event types…* renames, recolours and
  deletes. Events travel with copied / duplicated steps and show as coloured chips above the steps.
- Export: blob v2 with a per-step event range and an event table; `MS_EVENT_<NAME>` defines in the generated
  header. Not yet: events in the RetroAnimator export and in the role tables.

### 3. Loop-from step and follow-up animation (done)
- Data (format v3): `Animation.loop_start`, `Animation.next_animation_id`; scenes honour them too (follow-ups since
  format v5, for objects that play *as animated*).
- Runtime: `MS_Animation.loop_start / next_animation / loop_count`; `ms_anim_player_tick` loops from
  `loop_start`, counts passes and hands over to the follow-up. `tests/test_runtime_player.py` compiles the C player
  and checks it against the editor preview tick by tick.

### 4. Timing tools (medium value, low effort)
- Done in the redesign: duration-scaled cells, edge-drag holds, multi-select edits, step rotation, preview speed.
- Still open: "spread" timing presets (1-1-2-2…), and a 60 Hz / 50 Hz display toggle to judge how ticks feel on
  NTSC vs. PAL.

### 5. One compositor for all previews and exports (correctness)
- Extract a `render_frame(project, frame, mapping, transform) -> PIL.Image + handle` from
  `RetroAnimatorExporter._render_frame_variant` (now verified against the canvas) and use it for thumbnails,
  the frame strip, GIF export, onion-skin bakes and both exporters.

### 6. Palette awareness (high value for MD/SNES, larger effort)
- Show the per-part palette line (derived from source colours or assigned), warn on parts that need >16 colours,
  preview palette swaps as a mapping-like "palette variant", and palette-cycling previews (water, fire, damage
  flashes) as an animation property.

### 7. Attachment & constraints (medium)
- Use control-point roles as sockets: in the Timeline, "attach object to point role X of parent" so weapons,
  effects and riders follow the parent's per-frame point automatically. Export as per-step socket offsets.

### 8. Interchange (medium)
- Export: sprite sheet PNG + JSON (Aseprite-compatible frames/tags, Godot SpriteFrames, Unity sprite atlas).
- Import: Aseprite `.ase/.json` tags as animations (frames become single-module frames or auto-modularised).

### Not recommended for the retro target
- Sub-pixel tweening or free rotation/scaling inside frame animations (no hardware support on MD/NES; bake
  instead). Keep the timeline's scale/opacity hidden unless a SNES Mode 7 / GBA affine profile is added.
