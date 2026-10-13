# Audit of Modular Sprite Editor 0.7.1

Audit of release 0.7.1 (commit `bf9e6d7`, 2026-10-13) as the starting point for the next version. It covers the editor
(all five tabs and the Tools menu), the data model and file format, the importers and exporters (AuroraGT, RetroAnimator,
GIF, the SGDK exporter and the Mega Drive runtime), the build tooling and the user guide.

How it was checked:

- the full test suite, pyflakes and vulture (static analysis), `tools/check_export_parity.py`, `tools/automod_bench.py`,
  the GUI smoke test, and the SGDK exporter on all three examples;
- small reproduction scripts for every bug below (each one says what was run and what came out);
- timings of the core operations on Prince of Persia (PoP) and on synthetic projects 5× and 10× its size;
- screenshots of every tab at 1440×900 (the guide's pictures) and 1280×800, with an empty project and with PoP;
- reading every module of the editor, the exporter and the runtime.

Severity: **High** = data loss or wrong results without warning; **Medium** = wrong or surprising behaviour with a
workaround, or friction in a main workflow; **Low** = polish, hygiene, rare cases.

---

## 1. Summary

The core is in good shape. The renderers agree pixel for pixel (parity on 3,348 frames, thumbnails, mirror preview),
the Mega Drive runtime is tested against the editor tick by tick and pixel by pixel, Auto Modularize is exact on every
testbed, the 153 tests in `tests/` and the smoke test pass on three platforms, and the code has no TODOs.
Performance is fine at PoP's size and degrades gracefully at 10×.

The weak spots are elsewhere:

1. **Data safety.** A failed save leaves a truncated, unloadable project file (C1). Undo does not restore event types
   and then loses the redo steps (C2). Deleting modules or frames leaves dangling references that exports drop silently
   (C5).
2. **Scenes behave differently from animations.** An animation placed in a scene ignores its own playback settings:
   Play once loops, Loop backwards plays forwards, ping-pong repeats its end steps (C3). Flips and visibility switch
   half-way between keys, and the moment depends on the easing (C4).
3. **The UI at laptop sizes.** At 1280–1440 px wide, every view bar loses controls (the Timeline's Screen guide, the
   Animations tab's Path / Hitboxes / Points toggles), and the per-step settings sit below the inspector's fold (U1, U2).
4. **The retro promise.** The SGDK export squeezes every image into one 15-colour palette and never checks video memory
   (C7); there is no palette view, no console other than the Mega Drive and no in-app export (F1–F3, F7).

### Top recommendations for the next version

Done since the audit, for the next version: C1–C8, C12, K1, K2, K4, K7, U1–U4, U6, F2, F5, F6, F7, H1, H2 and H4,
most of F1, the SNES part of F3, the warning of C9 and parts of U8 (each entry says how).

| # | What | Why | Size |
|---|------|-----|------|
| 1 | Atomic saves with a backup, plus autosave / crash recovery (C1, F6) | A crash or error during save destroys the project | S / M |
| 2 | Copy every project field on undo; test it field by field (C2) | Undo silently mixes states | S |
| 3 | Scene objects play animations "as animated" by default; one tick-based player for both (C3) | The Timeline contradicts the Animations tab and the runtime | M |
| 4 | Discrete properties (flip, visibility) switch at the key (C4, format v5) | Animators expect it; the current switch point moves with the easing | S + migration |
| 5 | Tools ▸ Check Project and export warnings; clean or fix references on delete (C5, F5) | Silent data loss in exports | M |
| 6 | View bars that wrap or fold into a menu; collapsible inspector sections (U1, U2) | Controls are unreachable on laptops | M |
| 7 | Welcome screen with examples and the guide; Help ▸ User Guide; sheet-to-animation shortcuts (U3, U4) | First steps for artists | M |
| 8 | SGDK export: VRAM check, palette per image/module, warnings in-app (C7, F1) | Real games need several palettes and must fit VRAM | M / L |
| 9 | Clear every image cache on reload; reload images changed on disk (C6) | Artists edit sheets in Aseprite while the editor is open | S |
| 10 | Windows: declare DPI awareness and zoom in device pixels (C14) | Blurry pixel art on scaled Windows displays (to verify) | M |

---

## 2. Correctness and data safety

### C1 (High) A failed save destroys the project file

`Project.to_json` ([models.py:3344](../models.py)) opens the file with `"w"`, which empties it, and only then
serialises. Any exception, crash, full disk or power loss during a save leaves a truncated file;
`MainFrame.save_project` ([app.py:615](../app.py)) only shows the error.

Reproduced on a copy of PoP_WW.json: one value json cannot write (a set) made the save fail half-way. The file
shrank from 1,041,675 to 945,134 bytes and no longer loads (`JSONDecodeError`).

**Fix:** serialise to a string first, write `name.json.tmp` in the same folder, flush and `fsync`, then `os.replace`;
keep the previous version as `name.json.bak`. Add a test that a failing save leaves the old file intact.

**Done:** `safe_files.write_text_atomically` (temporary file, fsync, `os.replace`, permissions and symlinks kept),
used by `Project.to_json` (with `name.json.bak`) and the RetroAnimator export; `tests/test_safe_files.py`.

### C2 (High) Undo and redo ignore event types, then lose the redo steps

`replace_project_contents` ([ui/project_history.py:24](../ui/project_history.py)) copies nine lists back into the
project but not `event_types` (added in format 3). The undo snapshot includes them, but restoring does not.

Reproduced on PoP: rename the `hit` event type, add a new one, then undo. Afterwards the types still read
`renamed, footstep, new_event`, the project no longer matches its history entry, and the next 700 ms checkpoint
records it as a new state, which deletes the redo branch.

**Fix:** copy every dataclass field of `Project` except the `init=False` ones (`dataclasses.fields`), so a new field
can never be forgotten again; test that undo restores the exact fingerprint after changing each field.

**Done:** `SAVED_FIELDS` in `ui/project_history.py`; `tests/test_project_history.py` changes every field, undoes and
redoes it, and fails if a new field has no change of its own (it fails three ways against the old code).

### C3 (Medium-high) Scenes ignore an animation's own playback settings

`ops.add_object` ([ui/scene_editor/ops.py:579](../ui/scene_editor/ops.py)) never sets `playback_mode`, so every
animation object starts as "Loop". The Timeline inspector only offers Loop / Play once / Ping-pong
([ui/scene_editor/inspector.py:227](../ui/scene_editor/inspector.py)). The scene sampler
(`TimelineScene._sample_source`, `Project.sample_animation_frame`,
[models.py:1031](../models.py) and [:3067](../models.py)) is time-based, while the Animations tab and the runtime use
the tick-based `ops.Player`.

Reproduced with a four-step animation (steps 0–3), sampled for 12 frames:

| Animation set to | Scene shows | Animations tab and runtime |
|---|---|---|
| Play once | `012301230123` (loops) | `0123` then stops |
| Loop backwards | `012301230123` (forwards) | `321032103210` |
| Ping-pong (object set to Ping-pong) | `01233210012332` (ends doubled) | `01232101232101` |

Repeat counts and "Then play" follow-ups are ignored in scenes too. The SGDK exporter bakes scenes from the same
sampler, so the game shows the scene's version, not the animation's.

**Fix:** a default object mode "As animated" that steps the animation with `ops.Player` (direction, loop-from, repeat
count, follow-up), keeping Loop / Play once / Ping-pong / Backwards as overrides. Same semantics in the exporter (it
already uses the editor's evaluation). This changes scene output: format v5 with a migration that keeps existing
objects on their current mode.

**Done:** `playback.py` holds the runtime's rules once: the Player (Animations tab) and `animation_at` (what shows
some time after an animation started, follow-ups at their own tick rate, repeating chains skipped in whole rounds),
which `TimelineScene._sample_source` and so the SGDK scene bake use. Format v5: new objects play *As animated*,
existing ones keep their mode ("loop" where unset), Loop backwards joins the overrides, Ping-pong no longer doubles
its end steps. `tests/test_playback.py` checks the shortcut against the Player (every playback, repeat count and
loop-from, all testbed animations, follow-up chains against a runtime-style simulation); `test_timeline_scenes.py`
has the table above; `test_sgdk_scenes.py` a baked follow-up. The Swordfight is unchanged (222 states compared).

### C4 (Medium) Flips and visibility switch half-way between keys

`evaluate_object_state` ([models.py:1237](../models.py)) switches `flip_x`, `flip_y` and `visible` when the *eased*
progress passes 0.5. Two keys 10 frames apart, the second one flipped and hidden: with linear motion the object flips
and disappears at frame 5; with Ease in at frame 8. Animation tools switch such properties at the key (stepped keys),
and the guide says a key stores how the object is flipped "at one frame".

**Fix:** stepped semantics: the value of the previous key holds until the next key's frame. Format v5, with a note in
the migration for scenes whose result changes.

**Done** as proposed (`evaluate_object_state`, any easing); no file on disk had a key that changes them.

### C5 (Medium) Deleting things leaves dangling references, and exports drop them silently

`module ops.delete_modules` / `remove_image` and `frame ops.delete_frame`
([ui/module_editor/ops.py:119, :330](../ui/module_editor/ops.py), [ui/frame_editor/ops.py:98](../ui/frame_editor/ops.py))
remove only the item itself. Frame parts, animation steps, nested frames, mapping entries and scene objects keep
pointing at the missing id. The confirm dialog counts the references, but nothing fixes them later.
`mapping ops.drop_dead_entries` exists but the app never calls it.

Reproduced: deleting five of PoP's modules (the three most used and two mapping targets) and one frame, then
exporting. Renderers and both exporters survive,
but the SGDK export silently loses the steps that showed the frame (1044 → 1041 steps) and prints no warning.

**Fix:** a **Check Project** report (missing images, references to deleted modules / frames / animations / mappings,
empty frames, zero-size boxes, steps whose frame is gone, C name collisions, colours over the palette, tiles over
VRAM) shown in-app and printed by `export_sgdk`. On delete, offer "remove the parts / steps that use it" next to
"leave them missing".

**Done:** `project_check.py` (wx-free, shared with the exporter): errors, warnings and notes with a target and, for
most reference problems, a fix; Tools ▸ Check Project (`ui/check_dialog.py`: Go to, Fix, Fix All, one undo step each).
`export_project` reports the same issues (the command line prints them, `--strict` fails on errors). Deleting used
modules, an image or a frame asks "remove the uses too" or "keep as missing" (`remove_module_uses`,
`remove_frame_uses`, `scene ops.clear_sources`). Tests: `tests/test_project_check.py`, `tests/test_delete_cleanup.py`,
smoke test step "check project".

### C6 (Medium) Reloaded images: the budget overlay keeps the old pixels

**Reload** in the Modules tab ([ui/module_editor/panel.py:408](../ui/module_editor/panel.py)) clears the shared
renderer and the thumbnails. It doesn't clear `canvas.BUDGET` ([ui/canvas.py:58](../ui/canvas.py)), which caches
sheet images by path and block masks by module geometry. After a sheet is edited in another program and reloaded, the
budget overlay keeps counting the old pixels until the editor restarts. Nothing notices when an image changes on disk
either: artists who draw in Aseprite must remember to press Reload.

**Fix:** one "images changed" notification that clears every cache (renderer, thumbnails, budget, every canvas, the
step renderers); check image modification times when the window is activated and reload changed sheets.

**Done:** `app_services.notify_images_changed()` → `MainFrame.images_changed`; `ui/image_watch.py` stamps;
`MainFrame.check_images_on_disk` on activation (sizes re-read, status message). Smoke test step "images"; checked by
hand: a sheet repainted on disk shows up on the stage, the lists and the library.

### C7 (Medium) SGDK export: one palette for everything, no VRAM check

- `_build_master_palette` ([examples/sgdk/tools/export_sgdk_example.py:332](../examples/sgdk/tools/export_sgdk_example.py))
  merges the colours of *all* images into one 15-colour palette. The Mega Drive has four 16-colour lines; a game with a
  hero and an enemy in different colours cannot be exported faithfully. The Adventurer (22 colours) is merged with only
  a console warning. The editor never shows the colour count or the console's 9-bit colours.
- No VRAM budget: the runtime refuses to load tiles that don't fit (`g_tiles_fit`,
  [modsprite.c:212](../examples/sgdk/sgdk_demo/src/modsprite.c)), but the exporter never warns. A large project
  builds a ROM that draws nothing.

**Fix:** see F1 (palettes); warn at export and in the budget overlay when unique tiles exceed the space
`TILE_USER_INDEX`..`TILE_FONT_INDEX` leaves.

**Done:** the export reports the tiles against about 1424 (SGDK's default layout: 1536 below the plane maps,
minus 16 system and 96 font tiles; `project_check.tile_issue`), a warning above three quarters and an error above
all of it. Colours are counted on visible pixels only (the Adventurer has 21, not 22). Each image has a palette (F1),
and the budget readout and Check Project show the tiles (F2).

### C8 (Low-medium) Mirrored points land one pixel off the art

A point is drawn as the pixel cell `[x, x+1)` ([ui/canvas.py:630](../ui/canvas.py)), but mirroring treats it as a grid
position: `mirror_frame` sets `cp.x = -cp.x` ([ui/frame_editor/ops.py:273](../ui/frame_editor/ops.py)), and the
exporter's `_frame_markers` does the same. Hitboxes mirror pixel-exactly (`-x - w`). On a mirrored frame, step or
scene object, a `blade_tip` point sits one pixel beside the mirrored blade, in the editor and in the game.

**Fix:** decide that a point marks a pixel and mirror it to `-x - 1` in the editor, the mirror preview and the
exporter together, so the runtime test still matches.

**Done:** a transform moves the pixel's centre and floors: mirror `x → -x - 1`, quarter turn `(x, y) → (-y - 1, x)`
in `frame ops` (`turn_pixel`), the canvas (`_draw_control_point`, so also the mirror preview) and the exporter's
`_frame_markers`. The SGDK demo data is regenerated (only point records changed).

### C9 (Low) Semi-transparent pixels look different in the export

The editor blends partly transparent pixels, while `_to_indexed_4bpp` makes every pixel with alpha > 0 opaque
([export_sgdk_example.py:398](../examples/sgdk/tools/export_sgdk_example.py)). Anti-aliased PNG edges look soft in the
editor and hard in the game. Check Project (C5) should flag them; the Modules tab could offer "show what the console
shows".

**Done (the warning):** Check Project warns about half-transparent pixels per image; a console preview is part of F1.

### C10 (Low) Editing glitches on the canvas

- Dragging parts, hitboxes and points converts with `int()`, which rounds toward zero
  ([ui/canvas.py:931, :1294, :1474](../ui/canvas.py)), so drags across the origin step unevenly.
- Dragging a hitbox corner past the opposite edge makes the box jump (`nw = 1`) and allows zero-size boxes
  ([ui/canvas.py:1314](../ui/canvas.py)).
- Hitbox and point editing ignores the frame's flip and rotation. That's fine in the Frames tab, but it's a trap if
  editing ever moves to the stages.

### C11 (Low) Importers fail quietly

- AuroraGT: modules that don't parse are dropped by `except: pass` with no load note
  ([models.py:1544](../models.py)). `MD_LINE` with four numbers is read as the legacy two-number form, under an
  80-line block of thinking-aloud comments ([models.py:1452–1532](../models.py)). `on_import_aurora` has no error
  handling ([app.py:654](../app.py)), unlike the RetroAnimator import.
- RetroAnimator export: the loss report omits step events, loop-from, follow-ups, scenes and point types
  ([models.py:2913](../models.py)). Exporting again into the same folder leaves stale part images behind.

### C12 (Low) Small robustness items

- Running from source, preferences are stored as **"app"** (`~/Library/Preferences/app Preferences`).
  `SetAppName` runs after `OnInit` has built the window ([app.py:851](../app.py)), so any other `app.py` shares the
  file. Set the name at the start of `OnInit`.
- `generate_id` uses 32 random bits ([models.py:15](../models.py)): about a 0.1 % chance of a clash among 3,000 frame
  parts, which would make selection by id ambiguous. Use 64 bits or check for collisions.
- `frame_has_cycle` revisits shared nested frames without memoising ([models.py:2994](../models.py)). That's fine for
  PoP but exponential for deep shared nesting.
- `resource_path` falls back to the current folder when run from source ([app.py:840](../app.py)); the app icon goes
  missing when started from another folder.

**Done:** `OnInit` names the app first and makes the editor's store wx's default, so every setting is in one store;
the old store's entries are copied over once (`ui/preferences.py`, `tests/test_preferences.py`). Ids have 64 random
bits, `frame_has_cycle` walks each nested frame once, `resource_path` is relative to `app.py`.

### C13 (Windows, to verify) Blurry UI and uneven pixels on scaled displays

Neither the app nor the PyInstaller manifest (`build_windows.spec`, PyInstaller 6 default) declares DPI awareness.
At 125 % or 150 % display scaling, Windows stretches the whole window as a bitmap, which softens the UI and the pixel
art. Even when DPI-aware, whole-number zoom levels in logical pixels become 1.25 or 1.5 device pixels, so pixel sizes
are uneven.

**Fix:** declare per-monitor DPI awareness (manifest or `SetProcessDpiAwareness` before the first window) and let
canvases zoom in device pixels (`GetContentScaleFactor`). Check it in the Windows VM at 150 %.

---

## 3. Consistency

| # | Finding | Suggestion |
|---|---------|------------|
| K1 | **Adding to a selection** is Cmd+click in Modules, Shift+click in Frames and the Timeline, Shift (range) / Cmd (toggle) in Animations and Mappings ([ui/shortcuts_dialog.py](../ui/shortcuts_dialog.py)). The marquee is Cmd+drag in Modules and a plain drag elsewhere. | One rule everywhere: Shift = range / add, Cmd = toggle. Modules keeps Cmd+drag for the marquee because a plain drag draws a module. **Done:** parts, points, Timeline keys and the Animations frame library follow it; Modules keeps Shift for pivots. |
| K2 | **Creating markers:** a hitbox is a drag on empty space; a point is a **Shift+click**, and a plain click on empty space only deselects ([ui/canvas.py:1386](../ui/canvas.py)). | A plain click on empty space creates a point, like a drag creates a box. **Done.** |
| K3 | **List buttons:** images have "+ Add ▾ / Remove", frames, animations and mappings "+ New / Duplicate / Delete", scenes "New / Duplicate / Delete" next to a dropdown. Scenes are the only collection without thumbnails, rename in place, reordering or the Delete key (an open item since the UX audit). | Same labels everywhere; scenes in a thumbnail list like the rest. |
| K4 | **Ping-pong, Play once and backwards differ between tabs** (C3). | One player. **Done** with C3. |
| K5 | **Menus:** "Auto Modularize Image…" uses an ellipsis character, every other item three dots ([app.py:524](../app.py)). The Tools menu mixes current tools with older ones (Optimize Sprite Sheet, Optimize Nested Frame Combos, role tables) that the guide never mentions. | Consistent labels; group the older tools under "More tools" or document them. |
| K6 | **Two time units:** animations count ticks at the animation's rate, scenes count frames at the scene's rate. It is documented, and the inspector shows seconds too. | Keep; show the other unit in tooltips where the two meet (a scene object's Start offset, Speed). |
| K7 | **The preview mapping in exports:** the RetroAnimator export bakes the preview mapping, while `export_sgdk` takes `--mapping`. | Spell out the mapping choice in every export dialog. **Done:** the Mega Drive export has a Mappings choice; the RetroAnimator and GIF file dialogs name the mapping they draw with. |

---

## 4. UI/UX and workflow

### U1 (Medium) View bars overflow and lose controls

The view bar under each canvas ([ui/components/canvas_display_controls.py](../ui/components/canvas_display_controls.py))
is a single row. On a 1440 px wide window the Frames bar ends in "Hitboxes ☐ P…" and the Animations bar in
"Path ☑ Collis…". At 1280 px the Timeline's **Screen** guide and the Animations tab's Path, Hitboxes and Points
toggles disappear entirely, and the Modules bar loses Names and Pivots. The controls can't be reached on most laptops.

**Fix:** let the bar wrap, or move the less used toggles into a "View ▾" menu; shorten labels ("Bounds", "Budget").

**Done:** the bar wraps (a `WrapSizer` that grows a row), labels are shorter ("Bounds", "Key colour", the budget menu
reads "No budget", the Grid checkbox leads its size). Every bar fits one row at 1440 px and two at 1280; the smoke test
checks that nothing is cut off at 1100 px.

### U2 (Medium) Inspectors at laptop heights

At 800 px high, the Animations inspector is filled by the animation settings: the selected step's frame, hold,
offset, rotation, flips and events are mostly below the fold. Those are the controls used most while timing. The Timeline inspector
behaves the same way.

**Fix:** collapsible sections that remember their state; put the step section first while steps are selected.

**Done:** one `inspector_kit.Section` for every inspector (the three copies merged); the Animations, Timeline and Frames
inspectors' sections fold at a click on their title and stay folded; the step section comes first while steps are
selected.

### U3 (Medium) First run and getting help

A new project opens on an empty Modules tab with a one-line hint. Nothing leads to the example projects or the user
guide, and the Help menu has only the shortcuts and About. The empty states don't explain the order of work: an empty
Animations tab says "Select an animation in the list, or click + New", but nothing works there until frames exist.

**Fix:** a welcome screen (recent projects, open an example, read the guide); Help ▸ User Guide and Help ▸ Example
Projects; empty-state hints that point to the previous step ("No frames yet: make them in the Frames tab").

**Done** as proposed (`ui/welcome.py`, `ui/first_steps.py`); the examples are found next to the program in builds (the
Windows kit, or the examples download unpacked there), else the menu offers the download.

### U4 (Medium) The "sheet of whole sprites" workflow takes many clicks

This is the most common start for artists:
- **Tools ▸ Create Reference Frames From All Image Modules** makes a frame for every module of every image, including
  part sheets.
- **New frame** in the inspector works for one module only.
- An animation is built by double-clicking each frame in order (eight double-clicks for the lesson's run).

**Fix:** "New frames from selected modules" (scoped to the selection); "New animation from selected frames" (in list
order); "Grid slice → one animation per row" as an option in the slice dialog. Multi-select drag from the frame
palette into the sequence.

**Done:** Modules: **New frames** / **New animation** for the selected modules (inspector and menu); Grid slice:
"Make a frame for every tile and an animation for every row"; Animations: the frame library selects several
(Shift / Cmd), drags them in together and offers **New Animation from N Frames**. The first lesson uses it.

### U5 (Low-medium) Trackpad scrolling zooms

On every canvas a two-finger scroll zooms; panning needs Shift / Alt + scroll, Space+drag or a sideways swipe. That
suits a mouse wheel, but on a MacBook most people expect scroll to pan and pinch to zoom.

**Fix:** a preference ("Scroll: zoom / pan").

### U6 (Low) Window and view memory

The window always opens at 1500×980 ([app.py:134](../app.py)), larger than many laptop screens, and its size and
position are not remembered. Zoom, pan, grid size and the selected items are not kept per project. Remember the window
geometry; store view state in a sidecar next to the project or in the preferences.

**Done** for the window (size, position, maximized; a first start fits the screen). Per-project view state is still
open.

### U7 (Low) Example data

In PoP, the guard's replacement modules (used by the Normal mapping) are named `ZZZZ_… UNUSED`, which shows in the
Mappings tab and on the guide's pictures. Rename them (`guard_…`) and regenerate the affected screenshots.

### U8 (Low) Smaller observations

- The Timeline library's first tab reads "Animatio…" at the default width. **Done:** the column is as wide as in the
  other tabs.
- With only a couple of layers, the dopesheet takes half the window and leaves the stage small. Let the user drag the
  splitter and remember its position.
- The Modules view bar has "Grid 8 × 8" next to a checkbox also called "Grid". **Done** with U1.

---

## 5. Performance

Measured on an M-series Mac. "10×" is PoP copied ten times (1,650 modules, 2,070 frames).

| Operation | PoP | 10× PoP |
|---|---|---|
| Load project data | 12 ms | — |
| Undo checkpoint (serialise + hash), runs every 700 ms | 4–5 ms | 51 ms |
| Restore an undo step (data only) | 14 ms | — |
| Render every frame (cold / cached) | 88 ms / 3 ms | 0.77 s |
| Frame signatures for every frame | < 5 ms | 0.23 s |
| SGDK export (all mappings) | 0.3 s | — |
| Auto Modularize, whole PoP | 0.8–1.0 s | — |

### P1 (Medium for large projects) The undo checkpoint runs constantly

`_on_checkpoint_timer` ([app.py:254](../app.py)) serialises and hashes the whole project every 700 ms, even when
nothing changed and while playback runs. That's 0.6 % of a core at PoP's size, 7 % at 10×, and it happens on the UI
thread, so playback stutters at that rhythm in big projects.

**Fix:** checkpoint after user input (mouse up, key up, text commit) or when an editor calls `request_checkpoint`;
skip the timer while playing.

### P2 (Low) Linear lookups by id

`get_module`, `get_frame` and the rest scan lists ([models.py:2973](../models.py)), so signatures and part bounds
grow with project size × parts (0.23 s for all signatures at 10×). Add id dictionaries kept in step with the lists, or
build a lookup once per paint or export.

### P3 (Low) Grid lines at low zoom

`_draw_grid` ([ui/base_canvas.py:322](../ui/base_canvas.py)) draws every line however close together: an 8 px grid at
0.25× is a line every 2 screen pixels, which is slow with GDI and looks like a grey fill. Skip lines closer than about
4 px.

Fixed in 0.7.1: the step sequence worked out its layout once per cell (25×25 signatures per repaint, now once per
repaint), and playback timers no longer starve the event queue on slow machines.

---

## 6. Feature completeness

Measured against the editor's purpose (modular sprites for retro consoles, made by artists, used in games) and its own
roadmap ([ANIMATION.md](ANIMATION.md)).

| # | Feature | Value | Notes |
|---|---------|-------|-------|
| F1 | **Palettes**: colours per image / module, the four Mega Drive palette lines, warnings over 15 colours, a preview in console colours (9-bit), palette swaps as variants (like mappings), palette cycling | High | Today one merged palette at export (C7). Needed for any real Mega Drive / SNES game. **Done** except swaps and cycling: format v6 gives every image a palette (`ImageAsset.palette`, Modules inspector with its colours as the console shows them); `palettes.py` builds them for the exporter and the preview; blob v4 stores one per palette, the runtime loads them into consecutive lines (`ms_palettes_fit`), and the pieces carry their palette bits; Check Project warns per palette over 15 colours; View ▸ Mega Drive Colours shows every canvas through them. Tests: `tests/test_palettes.py`, two palettes drawn by the compiled runtime (`test_sgdk_runtime_draw`). |
| F2 | **Memory budget**: unique tiles per animation and per project (with flip dedupe), DMA per step, VRAM left | Medium | The overlay counts sprites and tiles per frame only. **Done:** `hardware_budget` stores each part's tile blocks like the exporter (palette indices, flips free); the readout shows the tiles of the view and the project's total against the free space, the Animations inspector the animation's, Check Project warns when it gets tight. `export_tiles` equals the exporter's count on all 19 project files and a synthetic project with turning scene objects, two palettes and a mapping. DMA per step does not apply: the runtime keeps every tile in VRAM. |
| F3 | **More consoles**: SNES, GBA and NES sprite shapes and limits as budget profiles, then exporters | Medium (promised on the site) | The screen guide already knows five consoles; the budget knows the Mega Drive only. **Partly done:** SNES 8/16 and 16/32 budget profiles (square small / large sprites, 128 per screen, 32 and 272 px per line). Open: GBA and NES, and exporters. |
| F4 | **Interchange**: sprite sheet PNG + JSON export (generic, Godot, Unity), Aseprite import (tags → animations), PNG sequence export, scene export as GIF | Medium | Today: RetroAnimator JSON, animation GIF, AuroraGT import. |
| F5 | **Check Project** (C5) | Medium | **Done**, see C5. |
| F6 | **Autosave and crash recovery** | Medium | **Done:** `ui/autosave.py`, a recovery copy every 30 s while unsaved, offered after a crash (Restore / Discard / Later); `tests/test_autosave.py`, smoke test step "autosave", checked with a real SIGKILL. |
| F7 | **In-app Mega Drive export** (choose mappings and folder, show the report; optionally build and start an emulator) | Medium | **Done** without build / emulator: File ▸ Export ▸ Mega Drive (SGDK), folder and mappings remembered per project, a report with Check Project. Found on the way: the exporter overwrote the game's `res/resources.res` and deleted every `.png` / `.bin` in its `res/gen`; it now merges its line (`merged_resources`) and removes only older exporters' `var_NNNN.png` sheets. |
| F8 | **Attachment points**: a scene object follows a parent's point role frame by frame (weapons, effects, riders) | Medium | Listed in ANIMATION.md. |
| F9 | **Timing tools**: 50 / 60 Hz preview, spread presets (1-1-2-2…), batch edits across animations (tick rate, playback) | Low-medium | |
| F10 | **Organising large projects**: folders or tags for animations and frames (Sonic has 171 animations), sort options | Low-medium | |
| F11 | **Preferences window** (scroll behaviour, default tick rate, autosave, theme) | Low | Settings are spread over view bars. |
| F12 | **Timeline**: several selected objects at once, copying objects between scenes | Low | Known limit since the redesign. |

---

## 7. Code health and tests

- **H1 Dead code (no callers):**
  - `ui/canvas.py`: `hit_test`, `_get_pivot_offset`, `_get_width`, `set_frame_offset`, `_color_from_id`, unused
    attributes `show_control_points` and `grid_size`.
  - `ui/frame_editor/panel.py`: `on_delete_frame`, `set_edit_mode`, `_nudge_selection`, `_toggle_flip`,
    `_rotate_selected`.
  - `ui/mapping_editor/panel.py`: `refresh_list_and_table`, `on_del`.
  - `ui/scene_editor/ops.py`: `shift_all_keys`.
  - `models.py`: `TimelineScene.sample_draw_list`, `RetroAnimatorExporter._module_handle_for_rotation`.
    AGENTS.md still names `sample_draw_list` as part of the timeline API.
  - `rect_packer.py`: `insert_batch`, `occupancy`, `_score_rect` (and the unused `score1` / `score2`).
  - `ui/utils.py`: `load_wx_bitmap_safely`, `get_derivative`.
  - Exporter: `_c_string`, `_effective_hw_flip`.
  - `ops.TICK_RATE_PRESETS`, `inspector_kit.full_row`.

  **Done:** all removed (and what only they used: `MODE_OF_CANVAS`, the canvas' `_hit_test`).
- **H2** The root-level `test_*.py` files are stale (open since the UX audit). `test_import_aurora.py` fails by design;
  `test_flip_parser.py` and `test_parser_fix.py` are scripts, not tests. Move the useful ones into `tests/`, delete
  the rest.

  **Done:** their checks (ids, rects, flips on parts and steps, default names, separate imports) are in
  `tests/test_import_aurora.py`; the four files are gone, `python3 -m pytest -q` passes from the root.
- **H3 Untested and undocumented tools:** Optimize Sprite Sheet (`optimization.py`, needs wx), Optimize Nested Frame
  Combos, Validate Roles and Inspect Compiled Role Tables. Optimize Sprite Sheet works: PoP repacked in 0.1 s, all
  207 frames render identically. Add that as a test, make it wx-free, and document or retire the others.
- **H4 Hygiene:** 40 pyflakes notes (unused imports and variables, a duplicated `import math`, string annotations
  without a `TYPE_CHECKING` import in `ui/utils.py`), two `print` calls in app code, nine broad `except Exception`.

  **Done:** pyflakes is clean over the repository; the prints are gone; the silent broad handlers name what they
  expect (the nine left show the error to the user and keep the editor running). Found on the way: AuroraGT line
  shapes with a space in their name were dropped on import.
- **H5 Size:** `models.py` (3,400 lines) mixes the data model, timeline evaluation, two importers and the RetroAnimator
  exporter; `ui/canvas.py` (1,500 lines) still carries pre-redesign interaction code. Split into `model/`,
  `timeline.py`, `importers/` and `exporters/`, and move hitbox / point editing into the Frames stage.

---

## 8. Suggested plan for the next version

1. **Safety first (0.8.0):** C1 atomic saves + backup, C2 undo of every field, C6 cache clearing + reload on change,
   F6 autosave, C12 preferences name. Small changes, large effect.
2. **Trustworthy exports:** C5 / F5 Check Project with export warnings and delete cleanup, C7 VRAM check, C8 point
   mirroring, C9 alpha warning, K7 export dialogs, F7 in-app SGDK export.
3. **Scenes that match animations (format v5):** C3 "As animated" playback through one player, C4 stepped flips and
   visibility, with a migration and the SGDK scene tests extended.
4. **Laptop-friendly UI and first steps:** U1 view bars, U2 inspector sections, U3 welcome screen and help links, U4
   sheet-to-animation shortcuts, K1 / K2 one selection rule and click-to-add points, U6 window memory.
5. **Retro depth:** F1 palettes, F2 memory budget, F3 a second console profile (SNES or GBA).
6. **Housekeeping, alongside the rest:** H1–H5, P1 checkpoint on input, C13 Windows DPI (verify first).
