# Project File Format

Native projects are UTF-8 JSON written by `Project.to_json()` (2-space indent). All cross references are
string ids. Unknown keys are ignored on load (and dropped when the editor saves).

## Versioning

| `format_version` | Meaning |
|---|---|
| missing / `1` | Files written before versioning existed. |
| `2` | Current. Legacy fields canonicalised (see below). Added 2026-10-09. |

`Project.from_dict()` runs `migrate_project_dict()` first. Migration works on a deep copy of the raw
dict and returns notes (shown once when a file is opened). Files with a newer version load with a
warning. Older builds of the editor can read v2 files (the only new key is `format_version`).

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

## Schema (v2)

```jsonc
{
  "format_version": 2,
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
     "aframes": [
       {"frame_id": "frm_…", "duration_frames": 1,       // ticks
        "offset": [x, y], "flip_x": false, "flip_y": false, "rotation_degrees": 0.0}
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
  "point_types":     [{"id": "ptype_…", "name": "Hand", "color": [0, 255, 0]}]
}
```

Not stored in the file: the active (preview) mapping, view state, grid size, zoom.

## Other formats

- **Import:** AuroraGT `.sprite` text (`AuroraSpriteParser`), RetroAnimator JSON (`RetroAnimatorParser`,
  `ProjectType: "RetroAnimator"`).
- **Export:** RetroAnimator JSON with baked part PNGs (`RetroAnimatorExporter`, bakes the active mapping);
  SGDK resources + binary blob (`examples/sgdk/tools/export_sgdk_example.py`); animated GIF (Animations tab).
