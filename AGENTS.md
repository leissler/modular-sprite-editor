# AGENTS.md — Modular Sprite Editor

Guidance for coding agents (and humans) working on this repository. Read this before changing code.

## What this is

A wxPython desktop tool for **modular pixel-art sprites for retro consoles** (Mega Drive / SGDK is the
main target). Artwork is cut into reusable **modules** (sprite-sheet rectangles or vector shapes), assembled
into **frames** (positioned, flipped, 90°-rotated parts, optionally nested frames), sequenced into
**animations** (per-frame duration in ticks, offset, flip), composed in **timeline scenes**
(keyframed objects), and re-skinned with **mappings** (module → module / hidden substitutions).
Frames also carry **collision boxes** and **control points** with semantic *roles* for game logic.

Primary testbeds (keep them working):

| Project | Location | Size |
|---|---|---|
| Prince of Persia (WW) | `examples/sgdk/PoP_WW.json` (+ `modules_POP.bmp`), copy in `~/Downloads/PoP_WW.json` | 165 modules, 207 frames, 68 animations, 1 scene (*Swordfight*: the Prince vs. a mirrored guard with his own mapping), 2 mappings; hitboxes (Hurt `head`/`body` on every frame, Attack `blade` on striking frames), points (Weapon `blade_tip` in combat, Ground `feet`), `hit`/`footstep` events |
| Prince of Persia (SoT) | `~/Downloads/PoP_SoT.json` (not in the repo; mostly a duplicate of PoP_WW) | 165 modules, 208 frames, 68 animations |
| Sonic | `examples/sonic/sonic.json` (+ `sonic.png`), copy in `~/Downloads/sonic.json` | 65 modules, 38 frames, 171 animations |
| Adventurer | `examples/adventurer/adventurer.json` (+ `adventurer_sprite_sheet_v1.1.png`), copy in `~/Downloads/adventurer2.json` | 68 modules (32×32 grid slice), 15 frames of one whole sprite each: the Auto Modularize testbed |

## Run, test, build

```bash
pip install -r requirements.txt          # wxPython, Pillow, pyinstaller (Python 3.10+)
python3 app.py [project.json]            # optional project path opens it on start
python3 -m pytest -q                     # unit tests (no display needed)
python3 tools/gui_smoke.py [project]     # drives the real window (needs a display); default PoP_WW
python3 tools/check_export_parity.py PROJECT...   # RetroAnimator export vs editor canvas, pixel-exact
python3 tools/migrate_projects.py --dry-run DIR_OR_FILES   # upgrade project files to the current format
./build_macos.sh | ./build_linux.sh | build_windows.bat     # PyInstaller builds
<built executable> --smoke-test PROJECT.json [LOG]          # gui_smoke inside a build (own preferences file)
```

Releases: `.github/workflows/build-and-release.yml` (manual, with a version; *publish* off = build and test only)
builds and tests the editor and the SGDK exporter (`build_sgdk_exporter.spec`) on all three platforms; the release
gets both, plus `ModularSpriteEditor-examples.zip` (`tools/make_examples_zip.py`: the example projects in the repo's
`examples/` layout, so the user guide's paths apply, with `packaging/examples/README.txt`). It also assembles the Windows kit, a run artifact that is not released (`tools/make_windows_kit.py`:
editor, `export_sgdk.exe`, examples, SGDK demo + vendored SGDK, `packaging/windows_kit/`), and builds its ROMs on
Windows with the vendored SGDK. Pin wxPython there and in `requirements.txt` (the build scripts) to the version you test
with; `tests/test_requirements.py` checks they agree, and `requirements.txt` says what moving to 4.3 needs. Set
`APP_VERSION` in `app.py` to the release first: the About box and the macOS Info.plist show it, and the workflow stops if
it releases another version.

All tests live in `tests/`; `python3 -m pytest -q` from the repository root runs them.

## Layout

```
app.py                     MainFrame: menus, tabs, context bar (preview mapping), status bar,
                           project lifecycle (new/open/save/import/export), unsaved-change prompt,
                           project-wide undo/redo dispatch, autosave timer + crash recovery prompt,
                           images changed on disk (checked when the window becomes active)
models/                    The data model (wx-free); import from `models` (the package re-exports it all):
  core.py                  ImageAsset, Module, FModule, Frame (hitboxes, points), Animation, mappings, types, ids,
                           JSON (to_dict/from_dict)
  timeline.py              Timeline scenes: keys, easing, spline paths, source switching, evaluate_object_state
  migration.py             PROJECT_FORMAT_VERSION, migrate_project_dict (raw dicts, one step per version)
  project.py               Project: the lists, lookups by id, native JSON (from_json also imports the formats below)
importers/                 aurora.py (AuroraGT .sprite), retroanimator.py (RetroAnimator JSON): parse() -> Project;
                           notes.py groups what an import leaves out (Project.load_notes)
exporters/                 retroanimator.py: export() (RetroAnimator JSON + baked part PNGs, the active mapping baked)
compositor.py              The reference compositor (Pillow, wx-free): 2×2 matrices, module images (key colour,
                           shapes), leaf instances of nested frames, render_frame — previews, budget, Optimize Sprite
                           Sheet and both exporters build on it
hardware_budget.py         Hardware sprite budget (Mega Drive H40/H32, SNES 8/16 and 16/32): SGDK-exact part placement,
                           ≤32×32 VDP sprite cut (SNES: square small / large sprites), per-screen / per-line limits,
                           video memory (tiles stored like the export, the project's total) — wx-free, tested against
                           the SGDK exporter
modularize.py              Auto-modularisation (wx-free): shared parts at any offset / mirrored, tight hardware-sprite
                           cut, cost = SGDK exporter's tiles + weight x hardware sprites; plan(), apply_plan()
optimization.py            Sheet repacking (Optimize Sprite Sheet), nested-frame combo optimisation
palettes.py                Mega Drive colours (3 bits per channel, CRAM words) and palettes: one per image group
                           (ImageAsset.palette 0–3), the console preview image — wx-free, shared with the SGDK exporter
playback.py                Animation playback exactly like the SGDK runtime (wx-free): Player (tick by tick, the
                           Animations tab's preview) and animation_at (Timeline objects and so the scene bakes)
project_check.py           Check Project (wx-free, shared with the SGDK exporter): issues (error / warning / note) with
                           a target to go to and a fix, C symbol names, the Mega Drive tile capacity
rect_packer.py             MaxRects bin packer
safe_files.py              write_text_atomically: temp file + fsync + os.replace (+ name.json.bak), wx-free
ui/
  dpi.py                   Display scaling: tells Windows the editor scales itself (imported before any window
                           exists), px() / pxf() turn sizes at 100 % into device pixels (1:1 on macOS and GTK)
  app_services.py          Hooks panels use to reach the main window (checkpoint, status, zoom,
                           mapping changed, images changed, project revision, text-focus test). No-ops without a main
                           window.
  console_colours.py       View ▸ Mega Drive Colours: CONSOLE (on/off, console images per palette) for the canvases
  project_history.py       ProjectHistory: compressed Project.to_dict() snapshots, undo/redo, dirty flag
  autosave.py              Crash recovery copies (wx-free): recovery folder, write / find stale / load / remove
  image_watch.py           Image file stamps (mtime, size) to notice sheets edited elsewhere (wx-free)
  base_canvas.py           BaseCanvas: pan/zoom model, integer zoom levels, fit, grid, checkerboard
  canvas.py                FrameCanvas: draws a frame (parts, mapping, hitboxes / points when shown, ghost layers,
                           part bounds, budget overlay, bitmap caches); no editing — the stages add theirs
  frame_geometry.py        wx-free part bounds (module pivot/rotation, nested frames, mapping) — the one
                           implementation FrameCanvas, the Frames ops and hit-testing share
  module_editor/           Modules tab, redesigned from scratch:
    ops.py                 wx-free: sheets (+ Shapes / missing-image pseudo sheets), usage counts, naming,
                           pivots (packed-rotation aware, presets), grid slice, sprite detection (run-based
                           connected components), trim, add/replace cut modules — unit-tested
    canvas.py              SheetCanvas: the image with its modules; draw / move / resize / Shift+drag pivot /
                           Cmd+drag marquee, snap, names, pivots, key-colour pick
    inspector.py           ModuleInspector: sheet (file, key colour, slicing tools) or module(s)
    dialogs.py             Grid slice / detect sprites (live counts, keep-or-replace) / folder import
    modularize_dialog.py   Auto Modularize: background planning, sprite list, cut / parts-sheet preview, cost table
    panel.py               ModuleEditorPanel: Images + Modules lists, canvas, inspector, commands, keyboard
  frame_editor/            Frames tab, redesigned from scratch:
    ops.py                 wx-free: frames (new/duplicate/delete/move/references), items (paste with cycle
                           check, nudge, delete, reorder), group flip, mirror/rotate frame, origin, hitbox /
                           point copy to frames, types — unit-tested
    stage.py               FrameStage (FrameCanvas): all mouse editing — parts (select, click-cycle, drag),
                           hitboxes (draw, move, corner handles), points (click places, drag) — pixel hit-testing,
                           marquee, origin marker, drops, selection look (handles, roles, dimming)
    inspector.py           FrameInspector: frame tools, part(s), hitbox/point, types (inline)
    library.py             PartLibrary: modules (per image) and frames to drag or double-click
    panel.py               FrameEditorPanel: Frames list + library, mode bar, stage, inspector + contents list
  animation_editor/        Animations tab, redesigned from scratch:
    ops.py                 wx-free: tick timing, Player (playback exactly like the SGDK runtime),
                           step edits (insert/move/copy/hold/flip/rotate/nudge/reverse), whole-animation
                           mirror/rotate, animation list ops — unit-tested
    render.py              StepRenderer: pixel-exact step images via the RetroAnimator renderer
                           (thumbnails, list icons, GIF export)
    panel.py               AnimationEditorPanel: layout, playhead/playback, commands, keyboard, edit menu
    stage.py               AnimationStage (FrameCanvas): current step, onion skin, motion path, offset drag,
                           mirror preview (step_transform)
    sequence.py            SequenceWidget: steps as hold-wide cells on a tick ruler (hold drag, reorder,
                           drops from the library)
    inspector.py           AnimationInspector: animation settings/tools + selected step(s)
    browser.py             AnimationBrowser (thumbnail list, rename, drag reorder), FrameLibrary
  scene_editor/            Timeline tab (scene editor), redesigned from scratch:
    ops.py                 wx-free scene operations (frame<->time, keys, easing names, layer tree, draw
                           order, world-preserving reparent, add/duplicate/delete) — unit-tested
    panel.py               SceneEditorPanel: scene bar, transport, Auto-Key, commands, keyboard, playback
    stage.py               StageCanvas (FrameCanvas): objects, screen guides, motion path + handles
    timeline.py            TimelineWidget: layer tree + frame-based dopesheet in one custom-drawn widget
    inspector.py           SceneInspector: contextual sections (scene / object / playback / transform /
                           motion / swap), EasingPreview, SourcePickerDialog
    library.py             SceneLibrary: Animations / Frames / Modules palettes (drag or double-click)
  mapping_editor/          Mappings tab, redesigned from scratch:
    ops.py                 wx-free: states (original/replaced/hidden/missing), assign/reset, match by position
                           between two images or by name, frames using modules (through nesting) — unit-tested
    table.py               MapTable: module → replacement rows (drop target)
    panel.py               MappingEditorPanel: mappings list, module map, Replace with picker, usage preview
  components/              CanvasDisplayControls (shared view bar), split_memory (splitters that keep their height),
                           FramePalette, ModulePalette (module grid, THUMBNAILS cache), ThumbList / Browser
                           (thumbnail rows: rename, reorder, drag out),
                           inspector_kit (foldable Section: rows on section.body; relayout; row / spin helpers),
                           confirm (remove uses / keep as missing)
  shortcuts_dialog.py      Help ▸ Keyboard & Mouse Shortcuts (single source for the shortcut table)
  preferences.py           The one-time copy of settings older versions kept in a second preferences store
  welcome.py               The welcome screen (recent projects, the examples, the guide) shown before a project is open
  first_steps.py           Empty-state hints: what a tab needs first (frames need modules, animations need frames...)
  check_dialog.py          Tools ▸ Check Project: the issue list, Go to, Fix / Fix All
  sgdk_export_dialog.py    File ▸ Export ▸ Mega Drive (SGDK): folder + mappings, the report (runs the SGDK exporter)
  utils.py                 image loading via Pillow, pixel shape rasteriser, ThumbnailGenerator (frames delegate
                           to frame_render)
  frame_render.py          FrameRenderer: pixel-exact frame images via the parity-checked RetroAnimator renderer,
                           cached by content (frame_signature); SHARED instance, to_bitmap / fit_bitmap
tools/                     migrate_projects.py, gui_smoke.py, automod_bench.py (auto-modularize benchmark),
                           make_windows_kit.py, make_examples_zip.py (the examples download of a release),
                           make_readme_banner.py (README banner from the PoP example),
                           make_app_icon.py (the pixel-art app icon, a wooden mannequin: every size, nearest-neighbour only),
                           make_logo.py (the product logo: the icon's mannequin over a pixel wordmark, no example art)
website/                   Product site + user guide for artists (MkDocs Material, deployed to
                           modularsprites.bionic-productions.com): see website/README.md
examples/sgdk/             SGDK exporter (tools/export_sgdk_example.py: one binary blob) + Mega Drive runtime
                           (sgdk_demo/src/modsprite.c: VRAM-resident tiles, writes the sprite table) + demo
tests/                     unittest/pytest suites (import/export, auto-modularisation, roles, timeline,
                           scene / animation / module / frame / mapping ops, export/canvas parity, migration,
                           SGDK runtime: player, drawing, hitboxes / points)
docs/                      AUDIT_0.7.md (open findings and the plan for the next version), UX_AUDIT.md,
                           FILE_FORMAT.md, ANIMATION.md
```

## Data model essentials (`models/`)

- `Project` holds lists of `ImageAsset`, `Module`, `Frame`, `Animation`, `TimelineScene`, `ModuleMapping`,
  `CollisionType`, `PointType`. Look things up with `get_*` by id: O(1) through positions checked on every use, so the
  lists can be edited in place. Everything is referenced **by id**, unique in its list (parts, hitboxes and points in
  their frame, objects in their scene, keys in their object): new ones come from `generate_id`, and Check Project
  reports doubled ones (`duplicate-id`; the fix gives the others new ids, the first keeps its references).
- `Module.rect` is in sheet pixels, `Module.pivot` is relative to the rect's top-left. `rotated=True` means the
  packer stored the region rotated 90° CCW (pivot is logical, canvas converts).
- `FModule` (a frame part): `ref_type` `"module"` or `"frame"` (nesting; cycles are rejected via
  `Project.frame_has_cycle`), `position` = where the module pivot lands, `flip_x/flip_y`, `rotation_degrees`
  (90° steps are pixel-exact).
- `AFrame.duration_frames` is in animation ticks (`Animation.fps` ticks per second). Playback types:
  `forward`, `backward`, `loop`, `ping_pong`; `loop_count` 0 = infinite.
- `ModuleMapping.map`: `{source_module_id: target_module_id | None}`. Missing key = original module,
  `None` = hidden. `Project.active_mapping` is **runtime only** (not saved) and drives every preview and the
  RetroAnimator export; it is shown/selected in the context bar. Timeline objects can carry their own
  (`TimelineObject.mapping_id`: `None` inherits from the parent, `TIMELINE_MAPPING_ORIGINAL`, or a mapping id),
  resolved by `TimelineScene.object_mapping(project, id, default)`.
- Timeline: `TimelineScene.evaluate_object_state()` evaluates keyframes (easing,
  linear/spline paths, per-key source switches, root motion from animation offsets). An animation swapped in at a
  later key plays from that key. Scale/opacity exist in the model but are not exposed or rendered.

## File format

Native projects are JSON (`Project.to_json`). Top-level `"format_version"` (currently **6**, constant
`PROJECT_FORMAT_VERSION` in `models/migration.py`). `Project.from_dict` always runs `migrate_project_dict()` first, which upgrades
older dicts and reports notes in `Project.load_notes` (shown to the user once). Image paths are written
relative to the project file. Details: `docs/FILE_FORMAT.md`.

**When you change the format:** bump `PROJECT_FORMAT_VERSION`, add a `_migrate_vN_to_vN+1` step to `models/migration.py`
that works on raw dicts, add a test in `tests/test_format_migration.py`, keep changes additive where possible, then run
`tools/migrate_projects.py --backup-zip …` over every project file you can find (repo examples and the user's
copies, e.g. `~/Downloads`) after verifying the migration is lossless.

## UI architecture & conventions

- **Panel interface** (every tab panel implements): `set_project(project)`, `refresh_after_history()`
  (re-resolve selections by id after undo/redo replaced the project contents in place),
  `get_active_canvas()` (a `BaseCanvas` or `None`), optional `on_active_mapping_changed()`,
  `edit_copy/edit_cut/edit_paste/edit_duplicate/edit_select_all`, `stop_playback()`; the Timeline panel
  also gets `on_tab_activated()` (fits the stage/timeline the first time a scene is shown).
- **Undo:** do not add per-editor undo stacks. After a completed edit call
  `app_services.request_checkpoint()`. The main window also checkpoints on a 700 ms timer while no mouse button is
  held, so a drag becomes one step, but only after user input (`SpriteEditorApp.FilterEvent` → `MainFrame.note_input`:
  mouse buttons and keys released, menu and control commands); without input it looks about every 10 s. During
  playback it never looks (playback changes nothing): what happened meanwhile is looked at once playback stops. An
  edit that follows no user input (a callback, a drop, a timer) calls `request_checkpoint()` itself.
  Undo/redo replace the *contents* of the same `Project` object
  (`replace_project_contents` copies every saved field, `SAVED_FIELDS`), so object references held by panels go
  stale — always re-fetch by id. `tests/test_project_history.py` needs one change per saved field: add one when a
  field is added to `Project`.
- **Saving:** `Project.to_json` writes through `safe_files.write_text_atomically` (the old file stays intact if
  anything fails) and keeps the previous version as `name.json.bak`. Anything else that writes user files uses the
  same helper. While a project has unsaved changes, the main window writes a recovery copy every 30 s
  (`ui/autosave.py`, in the user's data folder; next to `MSE_PREFERENCES_FILE` in tests); saving or discarding the
  changes removes it, and a copy whose editor is no longer running is offered at the next start.
- **Images changed:** after reloading, relinking or regenerating image files call
  `app_services.notify_images_changed()`. The main window then clears every picture cache (`frame_render.SHARED`,
  `module_palette.THUMBNAILS`, `canvas.BUDGET`, `console_colours.CONSOLE`) and calls each panel's
  `refresh_after_history()`, which must rebuild
  that tab's own pictures. When the window becomes active it also reloads images whose file changed on disk
  (`MainFrame.check_images_on_disk`). A new cache of image pixels must be cleared there too.
- **Pixel sizes** in the UI go through `ui.dpi.px` (written at 100 %): control widths and min sizes, splitter
  positions, row heights, thumbnails, offsets next to text in custom drawing, hit tolerances in screen pixels. On
  Windows the editor is DPI-aware (`ui/dpi.py`): wx works in device pixels there and fonts grow with the display's
  scaling, so a literal size stays small and cuts text off at 150 %; on macOS and GTK `px` is 1:1. Canvas content
  (art pixels at whole-number zoom) is never scaled. Never name a local variable `px`. After UI changes, run the smoke
  test with `MSE_UI_SCALE=1.5` (it scales `px` on any system) as well. FlatNotebook measures its tab labels in a memory
  DC, which Windows gives 96 dpi: `measure_tabs_on_screen` measures them where they are drawn.
- **Canvases** subclass `BaseCanvas`. In mouse handlers start with
  `if self.begin_pan_if_requested(event): return` and `if self.handle_pan_motion(event): return`.
  Implement `get_content_bounds()` for Fit. The wheel follows `base_canvas.SCROLL` (View ▸ Scroll Moves the View:
  scrolling moves, pinch / Cmd+scroll zooms); widgets with wheel handling of their own (the step sequence, the
  timeline) read it too. Wheel/pinch zoom is continuous during a gesture and snaps to
  an integer level (`ZOOM_LEVELS`) ~180 ms after it stops (`snap_zoom_level`); `WheelGestureFilter` locks
  each trackpad gesture to one axis. Programmatic zoom uses `zoom_step` / `set_zoom_level`.
- **Backdrop vs. key colour** are separate: `BaseCanvas.backdrop` (checker / solid colour, chosen in the view
  bar, remembered per tab in `wx.Config`; the colour is shared by all tabs, the Timeline uses the scene's) and
  `apply_key_colour` (hide the sheet's transparent colour). Composition canvases always key; only the Modules
  tab offers "Show key colour". `FrameCanvas.show_part_bounds` outlines every module part. Create thumbnail
  `wx.ImageList`s with `mask=False` (a masked list costs ~6 ms per `Add` on macOS).
- **Budget overlay:** `FrameCanvas.budget_profile` + `compute_budget()` (the Timeline stage overrides it for the
  whole scene); the canvas draws the overlay with the content and the readout last (`_draw_budget_hud`). Keep
  `hardware_budget.py` in step with `SGDKBakeContext._render_leaf_part` and its 32 px piece cut (`_ensure_variant`);
  `tests/test_hardware_budget.py` compares them. Video memory (Mega Drive profiles): each part carries the ids of
  the tile blocks the export stores for it (`HwPart.vram`, compared in palette indices, flips free), so
  `Budget.unique_tiles` / `vram_tiles` count what a view, an animation or `export_tiles` (the whole export: every
  module, frame, step and scene sample per mapping) needs; the test compares `export_tiles` with the exporter's
  `tile_data`. The readouts take the project's total from `canvas.EXPORT_TILES` (worked out again per undo checkpoint,
  `app_services.project_revision`).
- **Palettes:** `palettes.py` builds each palette from its images' visible colours (≤15 kept, else merged by the
  quantizer) and maps a colour to its nearest entry the way the exporter does; the exporter, Check Project
  (`too-many-colours` per palette), the Modules inspector and View ▸ Mega Drive Colours (`ui/console_colours.py`,
  canvases put `CONSOLE.state()` in their cache keys) all use it. The runtime loads Palette 1 up to the last one used
  into consecutive lines from `ms_init_ex`'s first line; a piece's palette rides in bits 13–14 of its tile offset
  (`attribute + tile_offset` adds both), so the first line plus the count must stay ≤ 4 (`ms_palettes_fit`).
- **SGDK runtime:** the exporter writes everything into `modsprite_blob.bin` (`_emit_blob`) and generates the C
  record types and parser (`_emit_header`, `_emit_data_c`). Records are packed structs (`MS_RECORD`): when one
  changes, update the struct, the `struct.pack` format and the size list in `tests/test_sgdk_runtime_draw.py`, and
  bump `BLOB_VERSION`. Tiles stay in VRAM; drawing only writes `vdpSpriteCache` (no SGDK `SPR_*` engine).
  `tests/test_sgdk_runtime_draw.py` compiles `modsprite.c` for the host and compares its sprite table, rasterised
  like the VDP, with `FrameRenderer`. The active mapping is runtime state read at draw time (players keep none), so
  characters with different mappings share one set of animations (`ms_draw_anim_player_mapped`, as AuroraGT games
  set the mapping per draw); scenes are baked once per mapping, objects with their own mapping keep it. Measure performance in an emulator (BlastEm is cycle-accurate) with the V
  counter, not `getSubTick()` (it only advances per scanline and jumps around vblank).
- **SGDK export:** `export_project()` in the exporter is the one entry point for the command line and File ▸ Export ▸
  Mega Drive (the editor builds carry the exporter: `pathex` + `hiddenimports` in the three editor specs). It writes
  the blob, the header and the parser and merges its `BIN MS_BLOB` line into the game's `res/resources.res`
  (`merged_resources`; never overwrite the game's file, and delete nothing in its folder but older exporters'
  `var_NNNN.png` sheets). Its issues are `project_check`'s plus the tile count (`tile_issue`) and the palette lines
  (`palette_issue`): whatever the exporter leaves out or changes must show up as an issue there, not
  disappear silently. Name C symbols through `project_check.c_symbols` so Check Project's clash warning stays true.
- **Preferences** go through `wx.Config.Get()`. `SpriteEditorApp.OnInit` names the app and makes the editor's store
  (`wx.Config(APP_NAME)`, created before the vendor name is set, which on Windows would change the registry path)
  wx's default before any window exists. Up to 0.7 the view settings went to a second store named after the launched
  program ("app" from source); `ui/preferences.adopt_old_store` copies them over once. Tests set
  `MSE_PREFERENCES_FILE` to a throwaway file (`--smoke-test` and `tools/gui_smoke.py` do), which also keeps their
  recovery copies out of the user's folder. On macOS wx ignores `$HOME`: never start the editor to try preference
  handling, it writes the user's real store; test with `wx.FileConfig` files.
- **View options** belong in the canvas's `CanvasDisplayControls` (`add_toggle`, `add_control`), not in side
  panels. The bar is a `WrapSizer` that grows a row instead of cutting controls off on narrow windows (its EVT_SIZE
  handler sets the height); keep labels short, one item per control and its label, and check new controls at
  1280 px wide (the smoke test's "laptop UI" step checks every bar at 1100 px). **Status/hints** go through
  `app_services.show_status`, not modal dialogs; an empty tab's hint names the step before it (`ui/first_steps.py`).
- **Inspector sections** come from `inspector_kit.section(parent, sizer, title, scope)`: create the rows' widgets on
  `section.body` (wx asserts if a row's parent is the section itself), show / hide whole sections on the section,
  and finish a refresh with `relayout(inspector)`. With a `scope` (the inspector's name) the title folds the section
  away and the preferences remember it. The Animations inspector puts the step section first while steps are selected.
- **Selection**: one rule everywhere: Shift+click adds (a range in lists), Cmd+click adds or removes; a drag on empty
  space is a marquee (Shift or Cmd keeps the selection). The Modules sheet keeps Shift for pivots and Cmd+drag for
  its marquee (a plain drag draws a module). In Points mode a click on empty space places a point.
- **Timers** (`wx.Timer(self)`) outlive their window and crash the process (SIGSEGV in `wxTimerImpl::SendEvent`) if
  they fire after it is gone: stop them on close and on destroy (`MainFrame._on_destroy` stops the main window's and
  the playback timers). Scripts end the editor with `frame.Close(True)`, not `frame.Destroy()`.
- **Welcome screen and window**: without a project to open (and no crash recovery) the editor starts on
  `ui/welcome.py` in place of the tabs (`MainFrame.show_welcome`; `select_tab` and opening a project leave it). The
  window remembers its size, position and maximized state (`Window/Geometry`, only if its title bar is still on a
  screen), else it opens at a size that fits the screen.
- **Main tabs:** a FlatNotebook on Windows (`wx.Notebook` elsewhere). Its flags go in `agwStyle` (`style=` is the
  panel's), and its `SetSelection` sends no page events: switch tabs with `MainFrame.select_tab`, which activates them
  like a click on every platform.
- **Keyboard:** panels use `EVT_CHAR_HOOK`; always bail out with `app_services.text_entry_has_focus()`
  (on macOS `wx.SearchCtrl` is *not* a `wx.TextCtrl`) and leave Cmd/Ctrl combos to the menus. Shared keys:
  H/V flip, R / Shift+R rotate, arrows nudge (Shift = 8 px), Enter play/pause, `,`/`.` step, Delete.
  Update `ui/shortcuts_dialog.py` and the README controls table when adding shortcuts.
- **Timeline (scene editor):** the UI counts in *frames* at the scene fps; the model stores seconds — convert
  with `ops.time_of` / `ops.frame_of` only. A segment's easing lives on its *end* key (`ops.segment_end_key`).
  Layer rows are listed in draw order (lower rows draw on top) and `ops.normalize_draw_order` keeps
  `draw_order` depth-first so the SGDK exporter's global sort matches. Auto-Key on: pose edits create/update a
  key at the playhead (created lazily on the first real drag movement); off: edits between keys shift every
  key of the layer. Put scene logic in `ops.py` (testable without a display), not in the widgets. The stage draws,
  measures and budgets each object with its mapping (`StageCanvas.object_mapping`); canvases resolve parts through
  `FrameCanvas.mapping` (the preview mapping unless `drawing_mapping()` overrides it), never
  `project.active_mapping` directly. The screen guide puts the scene origin where the SGDK demo draws scenes
  (`ops.screen_origin`, tested against `SPRITE_DRAW_X/Y` in `sgdk_demo/src/main.c`). Objects play animations
  *as animated* through `playback.animation_at` (own playback, repeat count, loop-from, follow-ups at their own tick
  rate); the other modes (`ops.PLAYBACK_MODES`) override them. Flips and visibility are stepped (they change at the
  key). Caches of what an object shows must compare `ops.playback_signature`, which covers its animations' timing.
- **Animations:** holds are ticks at `Animation.fps`; anything below 1 plays as 1 (`ops.hold`), like the exporters.
  Playback preview goes through `playback.Player` (also `ops.Player`), which mirrors `ms_anim_player_tick` in the
  SGDK runtime (Loop backwards repeats; ping-pong does not repeat its end steps; `loop_start`, repeat counts,
  follow-up animation); `tests/test_runtime_player.py` compiles the C player and compares both tick by tick, and
  `tests/test_playback.py` checks `playback.step_after` / `animation_at` (what scenes use) against the Player — keep
  all three in sync.
  Step events reference `Project.event_types` by id (order = `MS_EVENT_*` number); `ops.Player.step_started` is the
  runtime's `step_started` (compared in the same test) and drives the preview's event chips on the stage; wrap structural step edits in
  `ops.keep_loop_start(anim)` so "loop from" stays on its step. Thumbnails and GIF export
  render through `render.StepRenderer` (the parity-checked renderer), not `ThumbnailGenerator`. The stage's
  mirror preview reverses a step's rotation for an odd number of mirror axes (`AnimationStage.step_transform`).
  Playback timers (here and in the Timeline) are one-shot and armed on the next idle event, once the frame has been
  drawn: armed any earlier, frames slower than the interval kept wx.Yield from returning on Windows (the smoke
  test's "playback with slow drawing" step checks it). Keep per-frame drawing cheap: the step strip works out its
  layout once per repaint (`strip_layout`), not per cell.
- **Modules / Frames / Mappings:** laid out like the animation editors (browser list with thumbnails | canvas
  with view bar | contextual inspector). Panels keep selections by id (`ModuleEditorPanel.selection`,
  the stage's `selected_*` lists, `MappingEditorPanel.selection`) and rebuild their lists from the data after
  every edit; logic lives in each package's `ops.py`. Module pivots are stored for the module *as used*:
  packed (`rotated`) modules convert with `ops.visual_pivot` / `ops.logical_pivot`. Part bounds come from
  `ui/frame_geometry.py` only. Module thumbnails go through `components.module_palette.THUMBNAILS`.
- **Auto modularize:** the engine (`modularize.py`) stays wx-free and exact by construction: a part is placed only where
  all its pixels equal the sprite's, every opaque pixel is covered. Its cost model is the SGDK exporter's
  (`part_tiles`); keep them in step. Measure changes with `tools/automod_bench.py` (flattened testbeds, exactness,
  tiles, hardware sprites) — `tests/test_modularize.py` covers the rewrite of flipped / rotated references.
- **Imports** list whatever they leave out or can't find in `Project.load_notes` (`importers.notes.Notes`: one line per
  kind, with examples), never silently; `Project.imported_from` marks an import, which the editor opens as a new,
  unsaved project (File ▸ Open of another editor's file too), so Save never writes over the file it came from.
- **Destructive actions** confirm when they break references (count the references) and stay undoable. Deleting
  modules, an image or a frame that is still used asks through `confirm.ask_remove_uses` (call it module-qualified,
  the smoke test patches it): remove the uses too (`module_editor.ops.remove_module_uses`,
  `frame_editor.ops.remove_frame_uses`, `scene_editor.ops.clear_sources`) or keep them as missing, which Check
  Project lists with a fix. A new kind of reference needs a check and, where possible, a fix in `project_check.py`.
- **Lists** use Add / Duplicate / Delete buttons, Delete key, double-click/F2 rename, drag to reorder and a filter
  (`wx.SearchCtrl`); new lists use `components.thumb_list.Browser` / `ThumbList`. Lists show a filtered view:
  map rows to objects by id, never index `project.frames[...]` with a list index.
- wx label gotcha: `&` in `StaticBox`/menu labels is a mnemonic — write `&&` for a literal ampersand.
- Pixel art: scale images with `wx.IMAGE_QUALITY_NEAREST` on the image (GraphicsContext would smooth),
  keep zoom integral, and draw bitmaps at exactly their size.
- Code style follows the surrounding code: type hints, `Optional[...]`, small helpers, comments only where
  they explain intent. No new dependencies without discussion.

## Transform semantics (canonical — the editor canvas is the reference)

- **Part flip** (`FModule.flip_x/y` on a module): mirrors the module image *in place* — the part's bounds do
  not move, regardless of where the pivot is.
- **Part rotation**: about the pivot, 90° steps (use exact cos/sin at 90° multiples, never raw `math.cos`).
- **Points** mark a pixel: a transform moves the pixel's centre (`x + 0.5`, `y + 0.5`) and floors, so a mirror maps
  `x` to `-x - 1` and a clockwise quarter turn `(x, y)` to `(-y - 1, x)` (`frame_editor.ops.turn_pixel`, the canvas'
  `_draw_control_point`, the exporter's `_frame_markers`). Hitboxes are areas: their corners transform as they are.
- **Nested frame part, animation step, mirror preview, timeline object**: geometric transform about the
  anchor/origin — flip first, then rotate. A mirrored parent (odd number of flips) reverses the direction of
  its children's rotation (`final_rot = parent_rot - child_rot`). A timeline object's root motion (the step's
  offset, flips, rotation) and swap offset sit inside the object's transform (`ops.local_matrix` = pose ·
  `ops.source_matrix`, the same in the SGDK exporter's `_build_local_matrix`; `tests/test_sgdk_scenes.py` compares).
- `tools/check_export_parity.py` and `tests/test_export_canvas_parity.py` render with the real canvas code and
  compare against the RetroAnimator export pixel by pixel (and the Animations stage's mirror preview against
  `StepRenderer`); run them after touching any transform code.

## Rendering paths (keep consistent)

| Path | Where | Nested frames | Rotation | Shapes | Mapping |
|---|---|---|---|---|---|
| Frame/animation/timeline canvas | `ui/canvas.py` | yes | 90° steps | yes | yes |
| All frame thumbnails, Animations tab, GIF export | `ui/frame_render.py` (`compositor.render_frame`, content-cached) | yes | yes | yes | yes |
| Module thumbnails (lists, palettes, mapping table) | `ui/frame_render.py` `FrameRenderer.module` via `ModuleThumbnails` | n/a | n/a | yes | n/a |
| Modules tab sheet | `FrameRenderer.sheet` (key colour cut in C, like the exporter) | n/a | n/a | n/a | n/a |
| RetroAnimator export | `exporters/retroanimator.py` (on `compositor`) | yes | any (affine) | yes | yes |
| SGDK export | `examples/sgdk/tools/export_sgdk_example.py` | yes | baked | yes | yes |

Previews share one compositor (`compositor.py`, cached by `ui/frame_render.py`); `tests/test_thumbnails.py` checks
thumbnails against the canvas. The SGDK exporter still bakes on its own (it needs per-part hardware sprites, not a flat image);
`tests/test_sgdk_runtime_draw.py` checks what the Mega Drive runtime draws against `FrameRenderer`.
