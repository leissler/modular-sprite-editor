# The project file

A project is one UTF-8 JSON file (`.json`, 2-space indent) with the sprite sheets it names. This page documents format 9, the format since version 0.12, and the rules that turn it into pictures and motion. The editor is the reference: what it shows is what these rules give.

## Basics

- **Images** are named by paths relative to the project file.
- **References** are string ids, unique within their list: module ids among the modules, part ids within their frame, keyframe ids within their object, and so on. New ids are random (`mod_3f9a...`); treat them as opaque strings.
- **Unknown keys** are ignored when the editor loads a file and dropped when it saves.
- **Versions**: `format_version` says which format a file has. The editor upgrades older files when it opens them; a file of a newer format opens with a warning, and what the older editor does not know is lost when it saves. Most changes since format 3 only added keys; the repository's `docs/FILE_FORMAT.md` lists every version and what an older editor makes of a newer file.
- **Order** matters in several lists: parts are drawn back to front, the export numbers types in list order, and modules, frames, animations, scenes and mappings keep the numbers their position gives them.

## Top level

```jsonc
{
  "format_version": 9,
  "name": "Prince of Persia",
  "console": "megadrive",          // the target console: megadrive, snes, nes, gba, gb
  "console_setup": "md_h40",       // its setup: md_h40, md_h32, snes_8_16 ... snes_32_64, nes_8x8, gba, gb_8x8 ...
  "images": [],
  "palettes": [],
  "palette_swaps": [],
  "modules": [],
  "frames": [],
  "animations": [],
  "timeline_scenes": [],
  "mappings": [],
  "collision_types": [],           // hitbox types
  "point_types": [],
  "event_types": []                // animation event types
}
```

An unknown `console_setup` stands for the console's first setup.

## Images and palettes

```jsonc
"images": [
  {"id": "img_1", "file_path": "modules_POP.bmp", "width": 778, "height": 635,
   "transparent_color": [255, 0, 255],     // the key colour, or null (then the image's alpha)
   "palette_id": "pal_1"}
],
"palettes": [
  {"id": "pal_1", "name": "Palette 1",
   "colours": [[r, g, b], ...],            // slots 1, 2, ...; slot 0 is transparent and not stored
   "cycles": [{"first": 3, "count": 4, "frames": 8, "reverse": false}]}
],
"palette_swaps": [
  {"id": "swap_1", "name": "Blue guard",
   "palettes": {"pal_1": {"colours": [[36, 36, 218], null, ...],   // per slot: its colour, or null = the palette's
                          "cycles": null}}}                        // null: the palette's cycles; a list: its own
]
```

- Every image belongs to one palette; vector shapes use the first.
- A pixel's slot is the first slot with exactly its colour, else the nearest colour by squared RGB distance. Pixels equal to the key colour are transparent.
- `colours: null` is an automatic palette: the editor builds it from its images (the most used colours first, at most as many as the console shows) and stores them in slot order once the project is open. Slots are fixed from then on: swaps and cycles refer to them.
- A palette may store more colours than the console shows (kept from a console with bigger palettes); only the first are used.
- A **colour cycle** rotates `count` slots from `first` by one slot every `frames` video frames, towards the last slot (the first, when `reverse`).

## Modules

```jsonc
{"id": "mod_1", "name": "0cap01", "image_id": "img_1",
 "rect": [x, y, w, h],                 // in sheet pixels
 "pivot": [px, py],                    // relative to the rectangle's top left
 "type": "MD_IMAGE",
 "rotated": false,
 "color": [r, g, b],                   // shapes only
 "params": []}                         // shapes only
```

- **The picture** of an image module is its rectangle of the sheet, with the key colour made transparent. With `rotated` (set by sheet packers) the picture is that rectangle turned 90° anticlockwise; the pivot is given for the picture as used.
- **Shapes** are drawn in a `w` × `h` picture in `color`, one pixel wide: `MD_RECT` and `MD_FILL_RECT` the rectangle; `MD_MARKER` its two diagonals; `MD_ARC` and `MD_FILL_ARC` an ellipse's pie slice from `params[0]` degrees, `params[1]` degrees long (0 and 360 by default); `MD_TRIANGLE` and `MD_FILL_TRIANGLE` the triangle through three points given as percentages of the size (`params`: six numbers); `MD_LINE` the line between two points given the same way (four numbers).

## Frames

```jsonc
{"id": "frm_1", "name": "stand01", "group": "", "store_whole": false,
 "fmodules": [
   {"id": "fmod_1", "ref_type": "module", "ref_id": "mod_1",   // or "frame": a nested frame
    "position": [x, y], "flip_x": false, "flip_y": false, "rotation_degrees": 0.0}
 ],
 "collision_rects": [{"id": "crect_1", "type_id": "ctype_1", "rect": [x, y, w, h], "role": "body"}],
 "control_points": [{"id": "pt_1", "type_id": "ptype_1", "x": 0, "y": 0, "role": "feet"}]}
```

- `fmodules` are the parts, back to front: the last is drawn on top.
- `group` only sorts the editor's lists. `store_whole` asks the console exports to store the frame as one picture per palette.
- Hitbox and point roles are free names (`""`: none); their types are ids from `collision_types` and `point_types` (a missing type is an unknown type).
- Nested frames never form a cycle; the editor refuses one.

### Drawing a frame

Draw the parts in order, each with its transform, about the frame's origin (0, 0), with y downward:

1. **A module part**: the module's picture (under the mapping being drawn, [below](#mappings)) is mirrored in place by its flips: its bounds stay where they are, whatever the pivot. Then it is turned by `rotation_degrees` about its pivot, in steps of 90° (use exact values, never a computed cosine). The pivot lands on `position`.
2. **A nested frame part**: the nested frame is drawn whole and transformed about `position`: flipped first, then turned. Inside a mirrored frame (an odd number of flips on the way down) its children's turns go the other way.
3. **Hitboxes** are areas: their corners transform with the frame. **Points** mark pixels: a transform moves the pixel's centre (`x + 0.5`, `y + 0.5`) and floors, so mirroring maps `x` to `-x - 1` and a clockwise quarter turn maps `(x, y)` to `(-y - 1, x)`.

The editor turns parts in 90° steps only. A part at another angle (from an imported file) is drawn by the console exports as a picture of its own, turned about its pivot.

## Animations

```jsonc
{"id": "anim_1", "name": "run", "group": "",
 "playback_type": "loop",         // forward | backward | loop | ping_pong
 "loop_count": 0,                 // passes before a repeating playback ends; 0 = never
 "fps": 10,                       // ticks per second
 "loop_start": 0,                 // loop: later passes start at this step
 "next_animation_id": null,       // continues with this animation when it ends
 "aframes": [
   {"frame_id": "frm_1", "duration_frames": 1,     // the hold, in ticks
    "offset": [x, y], "flip_x": false, "flip_y": false, "rotation_degrees": 0.0,
    "events": [{"type_id": "evt_1", "value": 0}]}
 ]}
```

A step shows its frame flipped, then turned, about the frame's origin, then moved by `offset` (root motion). An `fps` of 0 counts as 10.

### Animation playback

These are the rules the editor's preview and both runtimes follow, tick for tick (the editor's `playback.py` and the runtimes' `ms_anim_player_tick` are tested against each other):

- A step holds for `duration_frames` ticks; anything below 1 counts as 1.
- **Start**: at step 0, or at the last step for `backward`.
- **forward** (play once): after the last step the animation ends.
- **loop**: after the last step, a pass is complete; it continues at `loop_start` (clamped to the steps), so the steps before it play only in the first pass.
- **backward**: plays from the last step down; after step 0 a pass is complete and it continues at the last step.
- **ping_pong**: plays up, then down, without repeating the end steps (0 1 2 1 0 1 2 ...); a pass is complete when it comes back down to step 0. An animation of one step stays on it.
- **Ending**: a repeating playback ends when its completed passes reach `loop_count` (when that is above 0). An animation that ends continues with `next_animation_id` from its start; without one, playback stops on its last shown step.
- **Events** fire on the tick their step starts and are active while it shows; `value` is a free number for the game.

**On the consoles** the runtimes count video frames: the exports convert each step's hold to `max(1, round(duration_frames × 60 / fps))` video frames. Rates that divide 60 (10, 12, 15, 20, 30, 60) are exact; others round some steps, which the editor's preview plays the same way.

## Scenes

```jsonc
{"id": "scene_1", "name": "Swordfight", "fps": 12, "duration_seconds": 10.0,
 "duration_frames": 120,            // derived, written for convenience
 "loop": true, "background_color": [32, 32, 32],
 "objects": [
   {"id": "tlo_1", "name": "Prince", "parent_id": null,
    "source_type": "animation", "source_id": "anim_1",   // none | module | frame | animation
    "mapping_id": null,             // null: the parent's (at the top: the one being drawn); "original"; or a mapping id
    "palette_swap_id": null,        // the same, for palette swaps
    "attach_point_role": "",        // follow this point role of the parent's frames ("" = none)
    "attach_point_type": null,      //   and this point type (null = any)
    "draw_order": 0, "playback_offset": 0.0, "playback_speed": 1.0,
    "playback_mode": "as_animated", // as_animated | loop | once | ping_pong | backward
    "path_mode": "linear",          // linear | spline
    "use_source_root_motion": false,
    "keyframes": [
      {"id": "tlk_1", "time": 0.0, "x": 0.0, "y": 0.0, "rotation_degrees": 0.0,
       "flip_x": false, "flip_y": false, "visible": true,
       "easing": "linear",
       "path_in": null, "path_out": null,       // spline handles in the parent's space, or null = automatic
       "source_type": null, "source_id": null,  // switch the source at this key (null = no change)
       "source_offset": [0.0, 0.0],
       "scale_x": 1.0, "scale_y": 1.0, "opacity": 1.0}   // reserved: not drawn
    ]}
 ]}
```

Times are seconds. The console exports bake every scene into one picture per tick of its `fps`, so a game usually never evaluates scenes; an engine that wants to stage them itself follows these rules (the reference is `models/timeline.py` in the source code):

- A segment between two keys eases by the **end key's** `easing`: `step`, `linear`, or a shape (`quad`, `cubic`, `quart`, `quint`, `sine`, `expo`, `circ`, `back`, `elastic`, `bounce`) with `_in`, `_out` or `_in_out`.
- With `path_mode: "spline"` a segment with a handle (`path_out` of its start key, `path_in` of its end key) is a cubic Bézier; otherwise it follows a Catmull-Rom curve through the neighbouring keys, except that two keys at the same position hold still.
- Flips and visibility change at a key and hold until the next.
- An object's animation plays from the scene start, shifted by `playback_offset` and scaled by `playback_speed`; a source switched in at a later key plays from that key. `as_animated` plays the animation's own playback, repeat count, loop-from step and follow-ups; the other modes override them and never hand over to a follow-up.
- With `use_source_root_motion` the current step's offset, flips and turn apply inside the object, like a nested frame in a frame, and the key's `source_offset` is added to the step's offset the same way.
- A parent's transform carries its children. Objects are drawn by ascending `draw_order` (ties by name, then id), back to front; the editor keeps it the depth-first order of the layer tree, a parent before its children.
- An object with `attach_point_role` sits on that point of its parent's current frame: its key positions are offsets from the point, inside the parent's transform; while the parent's frame has no such point the object does not show.

## Mappings

```jsonc
{"id": "map_1", "name": "Guard",
 "map": {"mod_a": "mod_b",     // draw mod_b wherever mod_a is used
         "mod_c": null}}       // hide mod_c; a module not listed stays as it is
```

A mapping replaces modules wherever they are drawn, in nested frames too: the replacement is drawn at the original's part, with the part's position, flips and turn, its own pivot landing on the position. Mapping a module to a module that is itself mapped does not chain.

## Types

```jsonc
"collision_types": [{"id": "ctype_1", "name": "Hurt", "color": [255, 0, 0]}],
"point_types":     [{"id": "ptype_1", "name": "Weapon", "color": [0, 255, 0]}],
"event_types":     [{"id": "evt_1", "name": "hit", "color": [255, 110, 100]}]
```

The colours are the editor's. The console exports number each list in its order (`MS_HITBOX_HURT`, `MS_POINT_WEAPON`, `MS_EVENT_HIT`) and the roles alphabetically.

## Not in the file

The editor keeps the preview's mapping and palette swap, and each tab's view (selection, zoom, grid), in its own preferences, per project file. Nothing in a project depends on them.
