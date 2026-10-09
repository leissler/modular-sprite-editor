# Animation Capabilities & Roadmap

Focus: pixel art for retro consoles (Mega Drive / SGDK first, SNES / GBA / NES-class targets second).

## What exists today

**Frame-based animation (Animations tab, production ready)**
- An animation is a list of steps `(frame, duration in ticks, offset, flip X/Y, rotation)` with `fps` = ticks
  per second, playback `forward / backward / loop / ping_pong` and `loop_count`.
- Per-step offsets give root motion; the canvas shows the offset trajectory and lets you drag/nudge offsets.
- Whole-animation flip / 90° rotate, duplicate, mirror preview (Mirror X/Y), GIF export.
- New in this pass: onion skin (previous = red, next = blue), duration badges in the strip, tick/length readout,
  Enter/`,`/`.` transport keys, arrow-key offset nudging, project-wide undo.
- Collision boxes and control points live on frames; `compile_animation_role_tables()` turns their roles into
  dense per-step lookup tables (`type + role → index`), validated by Tools ▸ Validate Roles.
- Mappings swap or hide modules for every frame of every animation (costume / damage / invisibility states),
  baked by the exporters.

**Timeline scenes (Timeline tab, experimental)**
- Objects with a source (module / frame / animation / none), parenting, draw order, playback speed/offset/mode.
- Keyframes: position, 90° rotation, flip, visibility, 31 easing curves, linear or spline motion paths with
  editable handles, per-key source switches with hold semantics, source offsets, root motion from the
  animation's step offsets. Dopesheet with zoom/pan, snapping, ruler in frames or seconds.
- Scale and opacity are in the data model but deliberately not exposed (no hardware support on the main target).

**Runtime / export**
- SGDK: modules, frames, animations (`frame_index + duration_ticks` steps) and scenes (pre-sampled per tick) in a
  binary blob; flips become hardware H/V flags, other transforms are baked; per-mapping data sets; runtime HUD
  estimates hardware sprites per frame.
- RetroAnimator JSON with baked part images (active mapping baked).

## Gaps that matter for retro work

1. **No hardware budget feedback while animating.** Sprite count, sprite-per-scanline overflow, unique 8×8 tiles
   and VRAM per frame are only visible later on hardware (SGDK HUD). This is the biggest risk for console work.
2. **No animation events / markers.** Hit-active windows, sound cues, spawn points, cancel windows, footsteps are
   per-step game data that today must be encoded in frame names or roles.
3. **No loop ranges or chaining.** Retro animations often play an intro once and then loop a sub-range, or hand
   over to another animation when done (`attack → idle`).
4. **Palette is invisible.** The SGDK exporter quantises to a master palette, but the editor never shows which
   palette/line a part uses, cannot preview palette swaps (Mega Drive: 4 lines × 16 colours) and has no palette
   cycling.
5. **Previews disagree.** Thumbnails, the frame strip and GIF export ignore nested frames and per-part rotation
   (GIF also ignores shapes and mappings), and the RetroAnimator exporter flips around the pivot while the
   editor and SGDK flip in place (see the failing export test).
6. **Timing UX.** All strip cells are equal width, so holds are only shown as a number; durations can't be dragged;
   no 50/60 Hz (PAL/NTSC) preview switch; per-step rotation has no direct control.
7. **No sprite-sheet / engine export** beyond RetroAnimator and SGDK (Aseprite JSON, Godot/Unity sheets), and no
   Aseprite import for animators who draw there.

## Recommended extensions (priority order)

### 1. Hardware budget overlay (high value, moderate effort)
- New `Project`-independent module `hardware_profiles.py` with per-target limits: sprite sizes (MD: 8–32 px in
  8 px steps, SNES: two global sizes, GBA: 12 shapes, NES: 8×8 / 8×16), sprites per frame, sprites per scanline,
  VRAM tiles.
- Per frame: greedy cover of each part with hardware sprites (reuse SGDK exporter logic), count sprites, mark
  scanlines over the limit in red on the canvas, show unique tiles; per animation: worst frame and tiles that must
  be streamed (DMA) per step.
- UI: a "Budget" toggle in the Frames/Animations view bar plus a numbers readout in the status bar; target
  chosen per project (store as `"target_profile"` → **format v3**, additive).

### 2. Step events / markers (high value, low effort)
- Data: `AFrame.events: List[str]` (free tags like `hit_on`, `sfx:slash`, `spawn:dust`) — additive, **format v3**.
- UI: a small tag row under the frame strip; events shown as markers on strip cells; copy events with steps.
- Export: SGDK blob gets an event table per step (string table indices); role tables gain an event column.

### 3. Loop range and follow-up animation (high value, low effort)
- Data: `Animation.loop_start: int = 0`, `Animation.next_animation_id: Optional[str]`.
- Playback: play steps once, then loop `[loop_start, end]`; when a `forward` animation ends, continue with
  `next_animation_id`. Preview in the editor and the SGDK player (`MS_PLAY_LOOP_FROM`, `next` index).

### 4. Duration-scaled strip and timing tools (medium value, low effort)
- Cell width proportional to `duration_frames` (with a minimum), drag a cell's right edge to change its hold,
  multi-select steps to set duration / offset / flip together, "spread" timing presets (1-1-2-2…).
- Playback rate toggle: animation fps vs. 60 Hz / 50 Hz display to judge how ticks feel on NTSC vs. PAL.
- Expose step rotation (90° buttons) in "Selected Frame".

### 5. One compositor for all previews and exports (correctness)
- Extract a `render_frame(project, frame, mapping, transform) -> PIL.Image + handle` from
  `RetroAnimatorExporter._render_frame_variant` once the flip semantics are decided (in place vs. around pivot),
  and use it for thumbnails, the frame strip, GIF export, onion-skin bakes and both exporters.

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
