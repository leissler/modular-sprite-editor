# Project File Format

Native projects are UTF-8 JSON written by `Project.to_json()` (2-space indent). All cross references are
string ids, unique within their list (parts, hitboxes and points within their frame, objects within their scene, keys
within their object); Tools ▸ Check Project reports doubled ones and can give the others new ids. Unknown keys are
ignored on load (and dropped when the editor saves).

## Versioning

| `format_version` | Meaning |
|---|---|
| missing / `1` | Files written before versioning existed. |
| `2` | Legacy fields canonicalised (see below). Added 2026-10-09. |
| `3` | Animation step events + project event types, loop-from step, follow-up animation. Added 2026-10-11. |
| `4` | Timeline objects carry a module mapping (`mapping_id`); an animation swapped in at a later key plays from that key; root motion turns with the object. Added 2026-10-12. |
| `5` | Timeline objects play animations "as animated" (`playback_mode: "as_animated"`, the default for new objects; `"backward"` joins the overrides); flips and visibility switch at a key. Added 2026-10-13. |
| `6` | Every image belongs to one of four Mega Drive palettes (`images[].palette`, 0–3). Added 2026-10-13. |
| `7` | The target console (`console`); palettes are project data with their colours in slot order and colour cycles (`palettes`, `images[].palette_id`); palette swaps (`palette_swaps`, `objects[].palette_swap_id`); scene objects that follow a point of their parent's frames (`attach_point_role`, `attach_point_type`); groups for frames and animations (`group`). Added 2026-10-14. |
| `8` | The target console's setup (`console_setup`: the screen mode and, where games pick them, the sprite sizes). Added 2026-10-15. |
| `9` | Current. Frames the console exports store whole (`frames[].store_whole`: one picture per palette, cut into the fewest hardware sprites, instead of the frame's parts). Added 2026-10-19. |

`Project.from_dict()` runs `migrate_project_dict()` first. Migration works on a deep copy of the raw
dict and returns notes (shown once when a file is opened). Files with a newer version load with a
warning. v3, v4 and v6 are additive: older builds open them with a warning and drop the new keys on save. A v5 object
set to "as_animated" or "backward" plays as Loop in an older build; an older build exports every image with one
merged palette. A v7 file opened by a v6 build puts every image into the first palette (the `palette` key is gone)
and drops swaps, cycles, attachments and groups. v8 is additive: an older build drops `console_setup` and works with the
console's usual setup. v9 is additive: an older build drops `store_whole` and exports those frames as their parts.

v7 → v8 adds `console_setup`, the console's first setup (`md_h40`, `snes_8_16`, `nes_8x8`, `gba`, `gb_8x8`; see
`consoles.py`, one `BudgetSetup` each). The editor keeps the key as it is and reads it through `consoles.target`, which
takes the console's first setup for an unknown key or another console's.

v6 → v7 makes palettes project data. The format 6 palettes the images use (and the first, which vector shapes use)
become `{"id": "pal_N", "name": "Palette N", "colours": null}`; `images[].palette` becomes `palette_id`. A palette
whose `colours` is `null` is *automatic*: it takes its images' colours with format 6's rules (most used first, at
most 15, similar ones merged) until the editor stores them in the order of their slots, which it does when it opens
the project and when an image is added, so palettes and their slot order are fixed from then on (other consoles
have other palette sizes, and a stored order is what palette swaps and cycles refer to). Everything else is
additive: `console: "megadrive"`, `palette_swaps: []`, objects get `palette_swap_id: null` (inherit),
`attach_point_role: ""` and `attach_point_type: null`, frames and animations `group: ""`.

v5 → v6 adds `palette: 0` to every image: all images share the first palette, as every export did before. Images
in the same palette share its 15 colours; the Mega Drive export stores one palette per group and the runtime loads
them into consecutive palette lines (see `examples/megadrive/README.md`). Out-of-range values load as 0.

v4 → v5 writes `playback_mode: "loop"` where an object has none (the old default), so every existing object keeps
playing as before. New objects play their animation *as animated*: with the animation's own playback, repeat
count, loop-from step and follow-up, exactly like the Animations tab and the Mega Drive runtime (one player,
`playback.py`). Before, scenes sampled animations by time: a Play once animation looped, Loop backwards played
forwards, and Ping-pong showed its end steps twice; an object set to Ping-pong now turns like the runtime (the
migration notes how many objects that affects). Flips and visibility now hold until the next key's frame instead
of switching half-way to it (once the eased progress passed 0.5); the migration names the scenes where a key
changes them. No file on disk had either.

v3 → v4 adds `mapping_id: null` (inherit) to every timeline object. v4 also changes two timeline rules, so
scenes can be choreographed: an animation swapped in at a later key (`keyframes[].source_type/source_id`) plays
from that key instead of from the scene start, and root motion and the swap offset are mirrored and turned with
the object (before, they were added in the parent's space, so a mirrored fighter stepped backwards). No v3 file
on disk swapped animations at keys or mirrored / turned an object with root motion or a swap offset.

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
`~/Downloads/ModularSpriteEditor_format_v1_backup_2026-10-09.zip`): `examples/pop/PoP_WW.json` and, in
`~/Downloads`: `POP.json`, `PoP_SoT.json`, `PoP_Sonic.json`, `PoP_WW.json`, `PoP_WW_frameModules.json`,
`PoP_WW_opt4.json`, `Pop_WW_opt.json`, `Pop_WW_opt2.json`, `modules_POP_optimized_3.json`, `Shapes.json`,
`adventurer1.json`, `adventurer2.json`, `sonic.json`, `Hero_spritesheet/Hero_spritesheet.json`,
`Hero_spritesheet/Hero_optimize_auto-modules.json`, `Hero_spritesheet/Hero_optimize_auto-modules.fixed.json`.
Only `PoP_SoT.json` changed content (348 `duration_ms` → `duration_frames`); all migrations were verified to
load to identical projects before and after.

On 2026-10-11 the same 17 files were migrated to v3 (originals in
`~/Downloads/ModularSpriteEditor_format_v2_backup_2026-10-11.zip`); each was checked to equal its original
except for the added default keys.

On 2026-10-12 the same files (with `examples/sonic/sonic.json` and `examples/adventurer/adventurer.json`; 18 in
all) were migrated to v4 the same way (originals in `~/Downloads/ModularSpriteEditor_format_v3_backup_2026-10-12.zip`);
`examples/pop/PoP_WW.json` and `~/Downloads/PoP_WW.json` were saved as v4 with the new *Swordfight* scene, which
replaced their disposable test scene.

On 2026-10-13 all 19 project files (the three repo examples, the 13 in `~/Downloads` and the 3 in
`~/Downloads/Hero_spritesheet`) were migrated to v5
(originals in `~/Downloads/ModularSpriteEditor_format_v4_backup_2026-10-13.zip`). Only `format_version` changed: the
*Swordfight*'s two objects already had `playback_mode: "once"`, and its 222 object states were compared frame by
frame with the v4 evaluation: identical.

Later on 2026-10-13 the same 19 files were migrated to v6 (originals in
`~/Downloads/ModularSpriteEditor_format_v5_backup_2026-10-13.zip`); each was checked to equal its original except for
`format_version` and the added `palette: 0`, and to load to the same project.

On 2026-10-14 all 19 files went to v7: `examples/pop/PoP_WW.json` was saved by the editor (its palette stored in slot
order, and the *Swordfight* guard drawn with the new *Blue guard* palette swap), the other 18 were migrated (originals
in `~/Downloads/ModularSpriteEditor_format_v6_backup_2026-10-14.zip`); each was checked to equal its original
without the added keys (with `palette_id` read back as the old number) and to load to the same project.
`~/Downloads/PoP_WW.json` then got the example's palette and swap, so it equals the repo's copy again.

On 2026-10-19 the same 19 files were migrated to v9 (originals in
`~/Downloads/ModularSpriteEditor_format_v8_backup_2026-10-19.zip`); each was checked to equal its original except for
`format_version` and `store_whole: false` on every frame, and to load to the same project.

## Schema (v9)

```jsonc
{
  "format_version": 9,
  "name": "New Project",
  "console": "megadrive",                                // the target console (consoles.py): palette rules, limits
  "console_setup": "md_h40",                             // its setup: screen mode, sprite sizes (SNES "snes_16_32")
  "images": [
    {"id": "img_…", "file_path": "modules_POP.bmp",      // relative to the project file
     "width": 778, "height": 635,
     "transparent_color": [255, 0, 255],                 // or null
     "palette_id": "pal_1"}                              // the palette its pixels use
  ],
  "palettes": [
    {"id": "pal_1", "name": "Palette 1",
     "colours": [[r, g, b], …],                          // slot 1, 2, … (transparent is slot 0, not stored);
                                                         //    null = automatic: built from the images
     "cycles": [{"first": 3, "count": 4,                 // slots 3–6 rotate,
                 "frames": 8, "reverse": false}]}        //    one step every 8 video frames, towards slot 6
  ],
  "palette_swaps": [
    {"id": "swap_…", "name": "Blue guard",
     "palettes": {"pal_1": {"colours": [[36, 36, 218], null, …],   // per slot: what it shows, null = its own
                            "cycles": null}}}             // null = the palette's cycles, a list = its own
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
     "group": "",                                        // where it sits in long lists ("" = no group)
     "store_whole": false,                               // console exports store it as a picture per palette
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
     "group": "",                                        // where it sits in long lists ("" = no group)
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
        "mapping_id": null,                              // null = inherit, "original", or a mapping id
        "palette_swap_id": null,                         // null = inherit, "original", or a palette swap id
        "attach_point_role": "",                         // follow this point role of the parent's frames ("" = none)
        "attach_point_type": null,                       //    and this point type (null = any)
        "draw_order": 0, "playback_offset": 0.0, "playback_speed": 1.0,
        "playback_mode": "as_animated",                  // as_animated | loop | once | ping_pong | backward
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

An object's animation plays from the scene start (shifted by `playback_offset`, scaled by `playback_speed`); an
animation swapped in at a later key plays from that key with the same settings (a swap on the first key counts
from the scene start). `playback_mode: "as_animated"` plays the animation's own settings, follow-ups included (at
each animation's own tick rate); `loop`, `once` (the last step holds), `ping_pong` and `backward` override them and
never hand over to a follow-up (`loop` keeps the loop-from step). Before an animation starts (a negative offset)
its first step shows. Flips and visibility are stepped: a key's values hold until the next key's frame. With `use_source_root_motion` the current step's offset, flips and
rotation apply inside the object, like a nested frame inside a frame part: the object's flip and rotation also
mirror and turn the step (a mirrored fighter steps forward to the left). The key's swap `source_offset` is added
to the step offset the same way.

An object's `mapping_id` re-skins it and its children: `null` inherits the parent's mapping, and at the top level
the preview mapping in the editor or the mapping being exported (the SGDK exporter bakes every scene once per
mapping; objects with their own mapping keep it in all of them). `"original"` draws the original modules. An id
that no longer exists counts as `null`; deleting a mapping resets the objects that used it. `palette_swap_id`
works the same way for palette swaps.

An object with `attach_point_role` and a parent sits on that point of the parent's current frame (the frame its
source shows at the time): its key positions are offsets from the point, inside the parent's transform, so a
mirrored or turned parent carries it along. While the parent's frame has no such point the object does not show
(its keys' `visible` stays as it is). Reparenting an object ends the attachment and keeps its keys where the point
put them.

Palette notes: a palette swap changes slots per palette; a slot it leaves `null` shows the palette's colour.
Colour cycles count video frames (60 a second; a 50 Hz console runs them at 50). The SGDK export stores every
palette and every swap's version of the palettes it changes as palette entries (see `examples/megadrive/README.md`).

Not stored in the file: the active (preview) mapping and palette swap, view state (each tab's selection, zoom, pan
and grid are kept per project file in the editor's preferences, `ui/view_memory.py`).

## Other formats

- **Import:** AuroraGT `.sprite` text (`importers/aurora.py`), RetroAnimator JSON (`importers/retroanimator.py`,
  `ProjectType: "RetroAnimator"`; the playback type and repeat count this editor's export writes into an animation's
  `Properties` come back), Aseprite `.aseprite` / `.ase` files and sprite sheets with Aseprite / TexturePacker JSON
  (`importers/aseprite.py`: tags become animations; an Aseprite file's frames are packed into
  `<name>.sheet.png` next to it). What an importer leaves out or can't find goes into `Project.load_notes`, shown once;
  `Project.imported_from` names the format, and the editor opens an import as a new, unsaved project.
- **Export:** RetroAnimator JSON with baked part PNGs (`exporters/retroanimator.py`, bakes the active mapping; the
  report lists what the format can't hold; `Cropped parts/.modular-sprite-editor.json` records which parts each export
  file uses, so exporting again removes its own unused ones and nothing else);
  SGDK binary blob with tiles, palettes, frames, animations, scenes, hitboxes and points
  (`examples/megadrive/tools/export_megadrive.py`); sprite sheets for other engines (`exporters/sheet.py`: a packed
  PNG with JSON in the Aseprite / TexturePacker layout, a Godot 4 SpriteFrames `.tres` or a Unity `.png.meta`);
  PNG sequences and animated GIFs of an animation, animated GIFs of a scene.
