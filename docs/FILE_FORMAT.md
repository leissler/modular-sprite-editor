# Project File Format

Native projects are UTF-8 JSON written by `Project.to_json()` (2-space indent). All cross references are
string ids. Unknown keys are ignored on load (and dropped when the editor saves).

## Versioning

| `format_version` | Meaning |
|---|---|
| missing / `1` | Files written before versioning existed. |
| `2` | Legacy fields canonicalised (see below). Added 2026-10-09. |
| `3` | Current. Animation step events + project event types, loop-from step, follow-up animation. Added 2026-10-11. |

`Project.from_dict()` runs `migrate_project_dict()` first. Migration works on a deep copy of the raw
dict and returns notes (shown once when a file is opened). Files with a newer version load with a
warning. v3 is additive: builds that only know v2 open v3 files with a warning and drop the new keys on save.

v2 → v3 adds, with their defaults: top-level `event_types: []`, per animation `loop_start: 0` and
`next_animation_id: null`, per step `events: []`. Nothing else changes.

v1 → v2 canonicalises:

- `aframes[].duration_ms` → `duration_frames` (values ≥ 10 are treated as milliseconds at 10 FPS, as the
  loader always did).
- `control_points[].name` → `role`; every control point and collision rect gets a `role` key.
- Timeline scenes without `duration_seconds` (frame time base) are converted to seconds
  (`duration_frames / fps`, keyframe `time` and object `playback_offset` likewise).
- `MD_LINE` with 2 pixel params → 4 percentage params; `MD_TRIANGLE`/`MD_FILL_TRIANGLE` with 4 pixel params
  → 6 percentage params.

Upgrade files in place (raw JSON edit, key order and unknown keys preserved):

```bash
python3 tools/migrate_projects.py --backup-zip ~/project_backup.zip path/to/projects/
```

On 2026-10-09 the following were migrated (originals in
`~/Downloads/ModularSpriteEditor_format_v1_backup_2026-10-09.zip`): `examples/sgdk/PoP_WW.json` and, in
`~/Downloads`: `POP.json`, `PoP_SoT.json`, `PoP_Sonic.json`, `PoP_WW.json`, `PoP_WW_frameModules.json`,
`PoP_WW_opt4.json`, `Pop_WW_opt.json`, `Pop_WW_opt2.json`, `modules_POP_optimized_3.json`, `Shapes.json`,
`adventurer1.json`, `adventurer2.json`, `sonic.json`, `Hero_spritesheet/Hero_spritesheet.json`,
`Hero_spritesheet/Hero_optimize_auto-modules.json`, `Hero_spritesheet/Hero_optimize_auto-modules.fixed.json`.
Only `PoP_SoT.json` changed content (348 `duration_ms` → `duration_frames`); all migrations were verified to
load to identical projects before and after.

On 2026-10-11 the same 17 files were migrated to v3 (originals in
`~/Downloads/ModularSpriteEditor_format_v2_backup_2026-10-11.zip`); each was checked to equal its original
except for the added default keys.

## Schema (v3)

```jsonc
{
  "format_version": 3,
  "name": "New Project",
  "images": [
    {"id": "img_…", "file_path": "modules_POP.bmp",      // relative to the project file
     "width": 778, "height": 635,
     "transparent_color": [255, 0, 255]}                 // or null
  ],
  "modules": [
    {"id": "mod_…", "name": "0cap01", "image_id": "img_…",
     "rect": [x, y, w, h],                               // sheet pixels
     "pivot": [px, py],                                  // relative to rect top-left
     "type": "MD_IMAGE",                                 // or MD_RECT, MD_FILL_RECT, MD_ARC, MD_FILL_ARC,
                                                         //    MD_MARKER, MD_TRIANGLE, MD_FILL_TRIANGLE, MD_LINE
     "color": [r, g, b],                                 // shapes only
     "rotated": false,                                   // region stored rotated 90° CCW by the packer
     "params": []}                                       // arc: [start°, sweep°]; triangle: 6 %; line: 4 %
  ],
  "frames": [
    {"id": "frm_…", "name": "stand01",
     "fmodules": [
       {"id": "fmod_…", "ref_type": "module",            // or "frame" (nested frame)
        "ref_id": "mod_…", "position": [x, y],           // where the pivot lands, frame space
        "flip_x": false, "flip_y": false,                // module: mirror in place; frame: mirror about position
        "rotation_degrees": 0.0}                          // about the pivot / position, 90° steps
     ],
     "collision_rects": [{"id": "crect_…", "type_id": "ctype_…", "rect": [x, y, w, h], "role": "hurt"}],
     "control_points":  [{"id": "pt_…", "type_id": "ptype_…", "x": 0, "y": 0, "role": "hand"}]}
  ],
  "animations": [
    {"id": "anim_…", "name": "run",
     "playback_type": "loop",                            // forward | backward | loop | ping_pong
     "loop_count": 0,                                    // 0 = infinite
     "fps": 10,                                          // ticks per second
     "loop_start": 0,                                    // loop playback: later passes start at this step
     "next_animation_id": null,                          // continue with this animation when it ends
     "aframes": [
       {"frame_id": "frm_…", "duration_frames": 1,       // ticks
        "offset": [x, y], "flip_x": false, "flip_y": false, "rotation_degrees": 0.0,
        "events": [{"type_id": "evt_…", "value": 0}]}   // fire when the step starts, active while it shows
     ]}
  ],
  "timeline_scenes": [
    {"id": "scene_…", "name": "Scene", "fps": 12, "duration_seconds": 10.0,
     "duration_frames": 120,                             // derived, written for convenience
     "loop": true, "background_color": [32, 32, 32],
     "objects": [
       {"id": "tlo_…", "name": "Hero", "parent_id": null,
        "source_type": "animation", "source_id": "anim_…",   // none | module | frame | animation
        "draw_order": 0, "playback_offset": 0.0, "playback_speed": 1.0,
        "playback_mode": "loop",                         // loop | once | ping_pong
        "path_mode": "linear",                           // linear | spline
        "use_source_root_motion": false,
        "keyframes": [
          {"id": "tlk_…", "time": 0.0, "x": 0.0, "y": 0.0, "rotation_degrees": 0.0,
           "scale_x": 1.0, "scale_y": 1.0,               // reserved, not rendered
           "flip_x": false, "flip_y": false, "visible": true,
           "opacity": 1.0,                               // reserved, not rendered
           "easing": "linear",                           // see TIMELINE_EASINGS
           "path_in": null, "path_out": null,            // spline handles (parent space) or null = auto
           "source_type": null, "source_id": null,       // per-key source switch (null = no change)
           "source_offset": [0.0, 0.0]}
        ]}
     ]}
  ],
  "mappings": [
    {"id": "map_…", "name": "Invisible",
     "map": {"mod_a": "mod_b",                           // replace
             "mod_c": null}}                             // hide; missing key = original
  ],
  "collision_types": [{"id": "ctype_…", "name": "Hurt", "color": [255, 0, 0]}],
  "point_types":     [{"id": "ptype_…", "name": "Hand", "color": [0, 255, 0]}],
  "event_types":     [{"id": "evt_…", "name": "hit_on", "color": [255, 110, 100]}]   // order = export number
}
```

Animation playback notes: an animation *ends* when it is `forward` (Play once) and reaches its last step, or
after `loop_count` passes in the repeating modes (`loop`, `ping_pong`, `backward`); then `next_animation_id`
takes over. `loop_start` only applies to `loop`: the first pass plays every step, later passes start at that
step. A step's events fire when the step starts and stay active while it shows; `value` is a free number for the
game (which sound, which object). The SGDK exporter numbers event types in list order (`MS_EVENT_<NAME>`).

Timeline evaluation notes: a segment's easing is the `easing` of its *end* key. With `path_mode: "spline"`,
a segment with an explicit handle (`path_out` of its start key or `path_in` of its end key) is a cubic Bézier;
otherwise it follows an automatic Catmull-Rom curve through the neighbouring keys, except that two
consecutive keys at the same position hold still (no drift out and back).

Not stored in the file: the active (preview) mapping, view state, grid size, zoom.

## Other formats

- **Import:** AuroraGT `.sprite` text (`AuroraSpriteParser`), RetroAnimator JSON (`RetroAnimatorParser`,
  `ProjectType: "RetroAnimator"`).
- **Export:** RetroAnimator JSON with baked part PNGs (`RetroAnimatorExporter`, bakes the active mapping);
  SGDK binary blob with tiles, palette, frames, animations, scenes, hitboxes and points
  (`examples/sgdk/tools/export_sgdk_example.py`); animated GIF (Animations tab).
