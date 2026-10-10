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
| Prince of Persia (WW) | `examples/sgdk/PoP_WW.json` (+ `modules_POP.bmp`), copy in `~/Downloads/PoP_WW.json` | 165 modules, 207 frames, 68 animations, 1 scene, 2 mappings |
| Prince of Persia (SoT) | `~/Downloads/PoP_SoT.json` | 165 modules, 208 frames, 68 animations |
| Sonic | `~/Downloads/sonic.json` | 65 modules, 38 frames, 171 animations |

## Run, test, build

```bash
pip install -r requirements.txt          # wxPython, Pillow, pyinstaller (Python 3.10+)
python3 app.py [project.json]            # optional project path opens it on start
python3 -m pytest -q                     # unit tests (no display needed)
python3 tools/gui_smoke.py [project]     # drives the real window (needs a display); default PoP_WW
python3 tools/check_export_parity.py PROJECT...   # RetroAnimator export vs editor canvas, pixel-exact
python3 tools/migrate_projects.py --dry-run DIR_OR_FILES   # upgrade project files to the current format
./build_macos.sh | ./build_linux.sh | build_windows.bat     # PyInstaller builds
```

Known pre-existing test failure: `test_import_aurora.py` (repo root, stale) expects Aurora image ids to be
file names; ids are generated on purpose.

## Layout

```
app.py                     MainFrame: menus, tabs, context bar (preview mapping), status bar,
                           project lifecycle (new/open/save/import/export), unsaved-change prompt,
                           project-wide undo/redo dispatch
models.py                  Dataclasses + JSON (to_dict/from_dict), format migration, timeline evaluation
                           (easing, spline paths, source switching), AuroraGT + RetroAnimator import,
                           RetroAnimator export (baked parts), role tables
optimization.py            Sheet optimisation/packing, auto-modularisation (freeform + tile-constrained
                           with console profiles), nested-frame combo optimisation
rect_packer.py             MaxRects bin packer
algorithms/decomposition.py  Rectangle decomposition helpers for auto-modularisation
ui/
  app_services.py          Hooks panels use to reach the main window (checkpoint, status, zoom,
                           mapping changed, text-focus test). No-ops without a main window.
  project_history.py       ProjectHistory: compressed Project.to_dict() snapshots, undo/redo, dirty flag
  base_canvas.py           BaseCanvas: pan/zoom model, integer zoom levels, fit, grid, checkerboard
  canvas.py                FrameCanvas (frame editing, collision/point modes, ghost layers, bitmap
                           caches, part bounds)
  module_editor.py         Modules tab (ModuleCanvas + panel)
  frame_editor.py          Frames tab (ModulePalette + panel)
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
  mapping_editor.py        Mappings tab
  components/              CanvasDisplayControls (shared view bar), FramePalette
  collision_manager.py / point_manager.py   type lists (colour, visibility, active type)
  shortcuts_dialog.py      Help ▸ Keyboard & Mouse Shortcuts (single source for the shortcut table)
  utils.py                 image loading via Pillow, pixel shape rasteriser, ThumbnailGenerator
tools/                     migrate_projects.py, gui_smoke.py
examples/sgdk/             SGDK exporter (tools/export_sgdk_example.py) + Mega Drive runtime demo
tests/                     unittest/pytest suites (import/export, auto-modularisation, roles, timeline,
                           scene ops, animation ops, export/canvas parity, migration)
docs/                      UX_AUDIT.md, FILE_FORMAT.md, ANIMATION.md
```

## Data model essentials (`models.py`)

- `Project` holds lists of `ImageAsset`, `Module`, `Frame`, `Animation`, `TimelineScene`, `ModuleMapping`,
  `CollisionType`, `PointType`. Lookups are linear `get_*` by id. Everything is referenced **by id**.
- `Module.rect` is in sheet pixels, `Module.pivot` is relative to the rect's top-left. `rotated=True` means the
  packer stored the region rotated 90° CCW (pivot is logical, canvas converts).
- `FModule` (a frame part): `ref_type` `"module"` or `"frame"` (nesting; cycles are rejected via
  `Project.frame_has_cycle`), `position` = where the module pivot lands, `flip_x/flip_y`, `rotation_degrees`
  (90° steps are pixel-exact).
- `AFrame.duration_frames` is in animation ticks (`Animation.fps` ticks per second). Playback types:
  `forward`, `backward`, `loop`, `ping_pong`; `loop_count` 0 = infinite.
- `ModuleMapping.map`: `{source_module_id: target_module_id | None}`. Missing key = original module,
  `None` = hidden. `Project.active_mapping` is **runtime only** (not saved) and drives every preview and the
  RetroAnimator export; it is shown/selected in the context bar.
- Timeline: `TimelineScene.evaluate_object_state()` / `sample_draw_list()` evaluate keyframes (easing,
  linear/spline paths, per-key source switches, root motion from animation offsets). Scale/opacity exist in
  the model but are not exposed or rendered.

## File format

Native projects are JSON (`Project.to_json`). Top-level `"format_version"` (currently **2**, constant
`PROJECT_FORMAT_VERSION`). `Project.from_dict` always runs `migrate_project_dict()` first, which upgrades
older dicts and reports notes in `Project.load_notes` (shown to the user once). Image paths are written
relative to the project file. Details: `docs/FILE_FORMAT.md`.

**When you change the format:** bump `PROJECT_FORMAT_VERSION`, add a `_migrate_vN_to_vN+1` step that works
on raw dicts, add a test in `tests/test_format_migration.py`, keep changes additive where possible, then run
`tools/migrate_projects.py --backup-zip …` over every project file you can find (repo examples and the user's
copies, e.g. `~/Downloads`) after verifying the migration is lossless.

## UI architecture & conventions

- **Panel interface** (every tab panel implements): `set_project(project)`, `refresh_after_history()`
  (re-resolve selections by id after undo/redo replaced the project contents in place),
  `get_active_canvas()` (a `BaseCanvas` or `None`), optional `on_active_mapping_changed()`,
  `edit_copy/edit_cut/edit_paste/edit_duplicate/edit_select_all`, `stop_playback()`; the Timeline panel
  also gets `on_tab_activated()` (fits the stage/timeline the first time a scene is shown).
- **Undo:** do not add per-editor undo stacks. After a completed edit call
  `app_services.request_checkpoint()`. The main window also checkpoints every 700 ms while no mouse button is
  held, so a drag becomes one step. Undo/redo replace the *contents* of the same `Project` object
  (`replace_project_contents`), so object references held by panels go stale — always re-fetch by id.
- **Canvases** subclass `BaseCanvas`. In mouse handlers start with
  `if self.begin_pan_if_requested(event): return` and `if self.handle_pan_motion(event): return`.
  Implement `get_content_bounds()` for Fit. Wheel/pinch zoom is continuous during a gesture and snaps to
  an integer level (`ZOOM_LEVELS`) ~180 ms after it stops (`snap_zoom_level`); `WheelGestureFilter` locks
  each trackpad gesture to one axis. Programmatic zoom uses `zoom_step` / `set_zoom_level`.
- **Backdrop vs. key colour** are separate: `BaseCanvas.backdrop` (checker / solid colour, chosen in the view
  bar, remembered per tab in `wx.Config`; the colour is shared by all tabs, the Timeline uses the scene's) and
  `apply_key_colour` (hide the sheet's transparent colour). Composition canvases always key; only the Modules
  tab offers "Show key colour". `FrameCanvas.show_part_bounds` outlines every module part. Create thumbnail
  `wx.ImageList`s with `mask=False` (a masked list costs ~6 ms per `Add` on macOS).
- **View options** belong in the canvas's `CanvasDisplayControls` (`add_toggle`, `add_control`), not in side
  panels. **Status/hints** go through `app_services.show_status`, not modal dialogs.
- **Keyboard:** panels use `EVT_CHAR_HOOK`; always bail out with `app_services.text_entry_has_focus()`
  (on macOS `wx.SearchCtrl` is *not* a `wx.TextCtrl`) and leave Cmd/Ctrl combos to the menus. Shared keys:
  H/V flip, R / Shift+R rotate, arrows nudge (Shift = 8 px), Enter play/pause, `,`/`.` step, Delete.
  Update `ui/shortcuts_dialog.py` and the README controls table when adding shortcuts.
- **Timeline (scene editor):** the UI counts in *frames* at the scene fps; the model stores seconds — convert
  with `ops.time_of` / `ops.frame_of` only. A segment's easing lives on its *end* key (`ops.segment_end_key`).
  Layer rows are listed in draw order (lower rows draw on top) and `ops.normalize_draw_order` keeps
  `draw_order` depth-first so the SGDK exporter's global sort matches. Auto-Key on: pose edits create/update a
  key at the playhead (created lazily on the first real drag movement); off: edits between keys shift every
  key of the layer. Put scene logic in `ops.py` (testable without a display), not in the widgets.
- **Animations:** holds are ticks at `Animation.fps`; anything below 1 plays as 1 (`ops.hold`), like the exporters.
  Playback preview goes through `ops.Player`, which mirrors `ms_anim_player_tick` in the SGDK runtime (Loop
  backwards repeats; ping-pong does not repeat its end steps); keep them in sync. Thumbnails and GIF export
  render through `render.StepRenderer` (the parity-checked renderer), not `ThumbnailGenerator`. The stage's
  mirror preview reverses a step's rotation for an odd number of mirror axes (`AnimationStage.step_transform`).
- **Destructive actions** confirm when they break references (count the references) and stay undoable.
- **Lists** use Add / Duplicate / Delete buttons, Delete key, double-click/F2 rename, and a filter
  (`wx.SearchCtrl`). Filtered lists keep a view list (`_frame_view`, `_anim_view`, `_modules_view`); never
  index `project.frames[...]` with a list-control index.
- wx label gotcha: `&` in `StaticBox`/menu labels is a mnemonic — write `&&` for a literal ampersand.
- Pixel art: scale images with `wx.IMAGE_QUALITY_NEAREST` on the image (GraphicsContext would smooth),
  keep zoom integral, and draw bitmaps at exactly their size.
- Code style follows the surrounding code: type hints, `Optional[...]`, small helpers, comments only where
  they explain intent. No new dependencies without discussion.

## Transform semantics (canonical — the editor canvas is the reference)

- **Part flip** (`FModule.flip_x/y` on a module): mirrors the module image *in place* — the part's bounds do
  not move, regardless of where the pivot is.
- **Part rotation**: about the pivot, 90° steps (use exact cos/sin at 90° multiples, never raw `math.cos`).
- **Nested frame part, animation step, mirror preview, timeline object**: geometric transform about the
  anchor/origin — flip first, then rotate. A mirrored parent (odd number of flips) reverses the direction of
  its children's rotation (`final_rot = parent_rot - child_rot`).
- `tools/check_export_parity.py` and `tests/test_export_canvas_parity.py` render with the real canvas code and
  compare against the RetroAnimator export pixel by pixel (and the Animations stage's mirror preview against
  `StepRenderer`); run them after touching any transform code.

## Rendering paths (keep consistent)

| Path | Where | Nested frames | Rotation | Shapes | Mapping |
|---|---|---|---|---|---|
| Frame/animation/timeline canvas | `ui/canvas.py` | yes | 90° steps | yes | yes |
| Animations tab thumbnails, GIF export | `ui/animation_editor/render.py` (RetroAnimator renderer) | yes | yes | yes | yes |
| Thumbnails (frame/module palettes, mappings) | `ui/utils.py` `ThumbnailGenerator` | **no** | frame-level only | yes | yes |
| RetroAnimator export | `RetroAnimatorExporter` | yes | any (affine) | yes | yes |
| SGDK export | `examples/sgdk/tools/export_sgdk_example.py` | yes | baked | yes | yes |

Unifying these on one compositor is the top technical-debt item (`docs/UX_AUDIT.md` X17).
