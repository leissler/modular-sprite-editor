# AGENTS.md — Modular Sprite Editor

Guidance for coding agents (and humans) working on this repository. Read this before changing code.

## What this is

A wxPython desktop tool for **modular pixel-art sprites for retro consoles** (Mega Drive / SGDK is the
main target). Artwork is cut into reusable **modules** (sprite-sheet rectangles or vector shapes), assembled
into **frames** (positioned, flipped, 90°-rotated parts, optionally nested frames), sequenced into
**animations** (per-frame duration in ticks, offset, flip), composed in **timeline scenes**
(keyframed objects), re-skinned with **mappings** (module → module / hidden substitutions) and recoloured with
**palette swaps** (per palette slot, chosen per draw like a mapping; colour cycles turn slots). Frames also carry
**collision boxes** and **control points** with semantic *roles* for game logic. `consoles.py` describes the target
consoles (screens, sprite hardware, palettes, limits): each has setups (budget profiles), a project targets one console
and setup (`Project.console`, `Project.console_setup`, chosen with Console above the tabs) that its palettes, the budget
overlay, the Timeline's screen, Auto Modularize and Check Project follow; the Mega Drive (SGDK) and the SNES
(PVSnesLib) have exporters.

Primary testbeds (keep them working):

| Project | Location | Size |
|---|---|---|
| Prince of Persia (WW) | `examples/sgdk/PoP_WW.json` (+ `modules_POP.bmp`), copy in `~/Downloads/PoP_WW.json` | 165 modules, 207 frames, 68 animations, 1 scene (*Swordfight*: the Prince vs. a mirrored guard with his own mapping and the *Blue guard* palette swap), 2 mappings, 1 palette, 1 palette swap; hitboxes (Hurt `head`/`body` on every frame, Attack `blade` on striking frames), points (Weapon `blade_tip` in combat, Ground `feet`), `hit`/`footstep` events |
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
python3 tools/check_engine_exports.py             # Godot / Unity exports played inside Godot 4 and Unity 6 (installed)
python3 tools/check_snes_rom.py [PROJECT...]      # the SNES runtime built into a ROM vs. its host build, in Mesen 2
python3 tools/migrate_projects.py --dry-run DIR_OR_FILES   # upgrade project files to the current format
./build_macos.sh | ./build_linux.sh | build_windows.bat     # PyInstaller builds
<built executable> --smoke-test PROJECT.json [LOG]          # gui_smoke inside a build (own preferences file)
```

Releases: `.github/workflows/build-and-release.yml` (manual, with a version; *publish* off = build and test only)
builds and tests the editor and the SGDK exporter (`build_sgdk_exporter.spec`) on all three platforms; the release
gets both, plus `ModularSpriteEditor-examples.zip` (`tools/make_examples_zip.py`: the example projects in the repo's
`examples/` layout, so the user guide's paths apply, with `packaging/examples/README.txt`). It also assembles the Windows kit, a run artifact that is not released (`tools/make_windows_kit.py`:
editor, `export_sgdk.exe`, examples, SGDK demo + vendored SGDK, `packaging/windows_kit/`), and builds its ROMs on
Windows with the vendored SGDK. Its SNES job builds the SNES demo ROM on Linux with PVSnesLib 4.6.0 (run artifact
`snes-demo`, not released): the demo's data exported again must be the committed data (re-export and commit it after
changing the exporter), and `tools/check_snes_rom.py` runs in Mesen 2's test runner (a `settings.json` next to the
executable: without one Mesen opens its first-run window instead; on Linux the tool sets
`DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`, without which Mesen 2.1 dies with std::bad_cast); publishing waits for it. Pin wxPython there and in `requirements.txt` (the build scripts) to the version you test
with; `tests/test_requirements.py` checks they agree, and `requirements.txt` says what moving to 4.3 needs. Set
`APP_VERSION` in `app.py` to the release first: the About box and the macOS Info.plist show it, and the workflow stops if
it releases another version.

All tests live in `tests/`; `python3 -m pytest -q` from the repository root runs them.

## Layout

```
app.py                     MainFrame: menus, tabs, context bar (project console, preview mapping and palette swap),
                           status bar,
                           project lifecycle (new/open/save/import/export), unsaved-change prompt,
                           project-wide undo/redo dispatch, autosave timer + crash recovery prompt,
                           images changed on disk (checked when the window becomes active), Preferences,
                           per-project view memory (remembered when a project closes, restored when it opens)
models/                    The data model (wx-free); import from `models` (the package re-exports it all):
  core.py                  ImageAsset, Module, FModule, Frame (hitboxes, points), Animation, mappings, palettes
                           (Palette, ColourCycle, PaletteSwap, PaletteChange), types, ids, JSON (to_dict/from_dict)
  timeline.py              Timeline scenes: keys, easing, spline paths, source switching, evaluate_object_state
                           (attachments: attach_offset / attach_missing, state_shows, find_point)
  migration.py             PROJECT_FORMAT_VERSION, migrate_project_dict (raw dicts, one step per version)
  project.py               Project: the lists, lookups by id, native JSON (from_json also imports the formats below)
importers/                 aurora.py (AuroraGT .sprite), retroanimator.py (RetroAnimator JSON), aseprite.py (.aseprite /
                           .ase files read and flattened like Aseprite exports them, sheets with Aseprite / TexturePacker
                           JSON): parse() -> Project; notes.py groups what an import leaves out (Project.load_notes)
exporters/                 retroanimator.py: export() (RetroAnimator JSON + baked part PNGs, the active mapping baked);
                           sheet.py: sprite sheets for other engines (packed PNG + Aseprite / TexturePacker JSON) and PNG
                           sequences, drawn through compositor; each step's hitboxes / points / events (step_markers) and
                           the clips the engines play (clips: playback.Player's rules); godot.py: SpriteFrames .tres +
                           scene .tscn (AnimationPlayer, Area2D hitboxes, Marker2D points, sprite_event signal);
                           unity.py: texture .meta (layout v13), .anim clips, .controller, .prefab
consoles.py                The console database (wx-free): screen modes, sprite hardware, tile flips, palettes,
                           refresh rates, budget setups; hardware_budget's profiles and the Timeline's screen guides
                           come from it
compositor.py              The reference compositor (Pillow, wx-free): 2×2 matrices, module images (key colour,
                           shapes), leaf instances of nested frames, render_frame — previews, budget, Optimize Sprite
                           Sheet and both exporters build on it
hardware_budget.py         Hardware sprite budget (Mega Drive H40/H32, SNES 8/16 and 16/32, NES and Game Boy 8×8 /
                           8×16, GBA): SGDK-exact part placement, the cuts of sprite_cut.py (Mega Drive: the export's),
                           per-screen / per-line limits, video memory (tiles stored like the console's export, the
                           project's total; Mega Drive and SNES) — wx-free, tested against both exporters
console_bake.py            The console-independent half of a console export (wx-free): ConsoleBake walks the project
                           like the editor draws it (parts through nested frames with flips and turns, palette entries
                           and swaps, hitboxes / points, animation steps with the game's timing and events, scene
                           samples with each object's mapping and swap, one pass per mapping) and hands each part's
                           picture to the console's exporter (_store_part); SGDKBakeContext subclasses it
sprite_cut.py              How hardware sprites cover a part (wx-free, Pillow only), one implementation for the SGDK
                           exporter, the budget and Auto Modularize: export_cut (Mega Drive: fewest sprites, then fewest
                           tiles, at any pixel; the 32 px grid where that is as good), cut per console (cells, squares,
                           GBA shapes via cover_with_shapes), tight_cut (band DP over a console's sizes)
modularize.py              Auto-modularisation (wx-free): shared parts at any offset / mirrored / under parts drawn later,
                           cut in a console's sprite sizes (Settings.hardware), cost = its tiles + weight x hardware
                           sprites (sprite_cut); plan(own=...), apply_plan() (mapping stand-ins), mapping_roles
optimization.py            Sheet repacking (Optimize Sprite Sheet), nested-frame combo optimisation
palettes.py                Palettes (wx-free, shared with the SGDK exporter): a palette's colours (stored in slot order, or
                           automatic: built from its images; colours_of = as many as the console shows, stored_colours =
                           all), console colours (consoles.PaletteHardware: 3 or 5 bits a channel, or the NES / Game Boy
                           fixed colours), palette swaps and colour cycles (swapped_colours, rotate, shown_colours),
                           recolouring images, the export's palette entries, maintenance (add missing colours, sort,
                           remove slots, keep_most_used)
playback.py                Animation playback exactly like the SGDK runtime (wx-free): Player (tick by tick, or video frame by
                           video frame with hold_of=console_hold: the Animations tab's preview), console_frames (a step's
                           hold in the game's frames, the exporter's conversion) and animation_at (Timeline objects and so
                           the scene bakes)
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
  console_colours.py       CONSOLE: the colours a draw shows (View ▸ Console Colours, palette swaps, turning colour
                           cycles); recoloured whole images for the canvases (keyed out first: no key colour mask after)
  view_memory.py           Per-project view state in the preferences (each tab's view_state / restore_view_state)
  refresh_rate.py          REFRESH: View ▸ Play at 50 Hz (PAL), the video frame rate every preview plays at
  grouping.py              Groups and sort orders for long lists (wx-free): natural name sort, shown()
  preferences_dialog.py    Edit ▸ Preferences (Cmd+,): the editor-wide settings in one window
  theme.py                 T: the editor's colours (View ▸ Theme: like the system, dark or light), a dark and a light
                           version of each named colour; T.style for controls, on_change for redraws
  sheet_export_dialog.py   File ▸ Export ▸ Sprite Sheet: format, animations, padding, scale
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
    panel.py               FrameEditorPanel: Frames list (group filter and sort) + library, mode bar, stage, inspector +
                           contents list
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
    inspector.py           AnimationInspector: animation settings/tools (Group, the game's timing) + selected step(s)
                           (Spread presets)
    browser.py             AnimationBrowser (thumbnail list, group filter and sort, rename, drag reorder), FrameLibrary
    batch_dialog.py        Change Animations: one tick rate, playback, repeat count or group for many animations
  scene_editor/            Timeline tab (scene editor), redesigned from scratch:
    ops.py                 wx-free scene operations (frame<->time, keys, easing names, layer tree, draw
                           order, world-preserving reparent, add/duplicate/delete) — unit-tested
    panel.py               SceneEditorPanel: Scenes list (thumbnails), transport, Auto-Key, commands (several selected
                           layers, copy and paste between scenes), keyboard, playback, scene GIF export
    thumbnails.py          scene_picture / scene_image (what a scene shows at a moment) and export_scene_gif
    stage.py               StageCanvas (FrameCanvas): objects, screen guides, motion path + handles
    timeline.py            TimelineWidget: layer tree + frame-based dopesheet in one custom-drawn widget
    inspector.py           SceneInspector: contextual sections (scene / object (Follows, Mapping, Colours) / playback /
                           transform / motion / swap), EasingPreview, SourcePickerDialog
    library.py             SceneLibrary: Animations / Frames / Modules palettes (drag or double-click)
  palette_editor/          Palettes tab: palettes and palette swaps (lists), preview (an image, pick a slot by its pixel,
                           cycles turning), inspector (the project's console, slot grid, change / original / remove,
                           add image colours, sort, colour cycles, swap settings), fixed_colours.py (the NES / Game Boy
                           colour picker); ops.py wx-free (set_console, new / duplicate / delete, replacements, slot
                           edits that keep swaps and cycles pointing at the same colours)
  mapping_editor/          Mappings tab, redesigned from scratch:
    ops.py                 wx-free: states (original/replaced/hidden/missing), assign/reset, match by position
                           between two images or by name, frames using modules (through nesting) — unit-tested
    table.py               MapTable: module → replacement rows (drop target)
    panel.py               MappingEditorPanel: mappings list, module map, Replace with picker, usage preview
  components/              CanvasDisplayControls (shared view bar), split_memory (splitters that keep their height),
                           FramePalette, ModulePalette (module grid, THUMBNAILS cache), ThumbList / Browser
                           (thumbnail rows: rename, reorder, drag out; add_group_bar), GroupBar + group_menu (group
                           filter, sort order, the lists' Group submenu), PaletteStrip (a palette's colours),
                           inspector_kit (foldable Section: rows on section.body; relayout; row / spin helpers),
                           confirm (remove uses / keep as missing)
  shortcuts_dialog.py      Help ▸ Keyboard & Mouse Shortcuts (single source for the shortcut table)
  preferences.py           The one-time copy of settings older versions kept in a second preferences store
  welcome.py               The welcome screen (recent projects, the examples, the guide) shown before a project is open
  first_steps.py           Empty-state hints: what a tab needs first (frames need modules, animations need frames...)
  check_dialog.py          Tools ▸ Check Project: the issue list, Go to, Fix / Fix All
  sgdk_export_dialog.py    File ▸ Export ▸ Mega Drive (SGDK): folder + mappings, the report (runs the SGDK exporter)
  snes_export_dialog.py    File ▸ Export ▸ SNES (PVSnesLib): folder + mappings + sprite sizes (with each pair's tiles),
                           the report (the SGDK dialog's, its own lines)
  utils.py                 image loading via Pillow, pixel shape rasteriser, ThumbnailGenerator (frames delegate
                           to frame_render)
  frame_render.py          FrameRenderer: pixel-exact frame images via the parity-checked RetroAnimator renderer,
                           cached by content (frame_signature); SHARED instance, to_bitmap / fit_bitmap
tools/                     migrate_projects.py, gui_smoke.py, automod_bench.py (auto-modularize benchmark),
                           check_engine_exports.py (+ engine_checks/: the Godot / Unity exports checked in the engines),
                           check_snes_rom.py (the SNES runtime in a ROM: a probe program played in Mesen 2's test
                           runner, every OAM against the host build),
                           make_windows_kit.py, make_examples_zip.py (the examples download of a release),
                           make_readme_banner.py (README banner from the PoP example),
                           make_app_icon.py (the pixel-art app icon, a wooden mannequin: every size, nearest-neighbour only),
                           make_logo.py (the product logo: the icon's mannequin over a pixel wordmark, no example art)
website/                   Product site + user guide for artists (MkDocs Material, deployed to
                           modularsprites.bionic-productions.com): see website/README.md
examples/sgdk/             SGDK exporter (tools/export_sgdk_example.py: one binary blob) + Mega Drive runtime
                           (sgdk_demo/src/modsprite.c: VRAM-resident tiles, writes the sprite table) + demo
examples/snes/             SNES exporter (tools/export_snes.py: chunks of a ROM bank + the C that finds them;
                           tools/snes_host.py: the runtime compiled for the host) + runtime (snes_demo/src/modsprite.c,
                           the hot loops in src/modsprite_draw.asm, 65816 assembly) + demo; see examples/snes/README.md
tests/                     unittest/pytest suites (import/export, auto-modularisation, roles, timeline,
                           scene / animation / module / frame / mapping ops, export/canvas parity, migration,
                           SGDK and SNES runtimes: player, drawing, hitboxes / points)
docs/                      AUDIT_0.7.md (the audit of 0.7.1 and how each finding was done), UX_AUDIT.md,
                           FILE_FORMAT.md, ANIMATION.md, PALETTES.md (palettes, swaps, cycles, the console database,
                           blob v5)
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
  resolved by `TimelineScene.object_mapping(project, id, default)`. `Project.active_palette_swap`,
  `TimelineObject.palette_swap_id` and `TimelineScene.object_palette_swap` work the same way for palette swaps.
- Palettes: `Project.palettes` (each `Palette` has its colours in slot order, `None` = automatic until the editor
  stores them, and `cycles`), `ImageAsset.palette_id`, `Project.palette_swaps` (`PaletteSwap.palettes`: palette id →
  `PaletteChange`, per slot a colour or `None` = its own, and optionally cycles of its own). `Project.console` keys
  the console and `Project.console_setup` its setup (a `consoles.BudgetSetup` key: screen mode, sprite sizes); read
  them through `consoles.target(project.console, project.console_setup)` (`hardware_budget.project_profile` for the
  profile), which falls back to the console's first setup: the setup is stored as it is, never corrected on load,
  so undo restores exactly. They decide palette size and colour model, and every tool's default console. A palette may store more colours than the
  console shows (kept from a console with bigger palettes; crossed out in the Palettes tab, `palette-too-long` in Check
  Project). Read a palette's colours with `palettes.colours_of(project, palette)` (what the console shows), never
  `palette.colours` directly; `palettes.stored_colours` for editing every stored slot.
- `Frame.group` / `Animation.group` place items in the long lists ("" = no group); nothing exports them.
- A timeline object with `attach_point_role` (and a parent) sits on that point of its parent's current frame: the
  evaluated state carries `attach_offset` (and `attach_missing` while the frame has no such point); `local_matrix`
  adds the offset, and drawing code asks `models.state_shows(state)` instead of `state["visible"]`.
- Timeline: `TimelineScene.evaluate_object_state()` evaluates keyframes (easing,
  linear/spline paths, per-key source switches, root motion from animation offsets). An animation swapped in at a
  later key plays from that key. Scale/opacity exist in the model but are not exposed or rendered.

## File format

Native projects are JSON (`Project.to_json`). Top-level `"format_version"` (currently **8**, constant
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
  `get_active_canvas()` (a `BaseCanvas` or `None`), optional `on_active_mapping_changed()` (also for the preview's
  palette swap), `edit_copy/edit_cut/edit_paste/edit_duplicate/edit_select_all`, `stop_playback()`,
  `view_state()` / `restore_view_state(state)` (what the tab shows: selected ids, the canvas' zoom and pan, the grid,
  list group and order; `ui/view_memory.py` keeps it per project file, the restore checks every id); tabs that fit
  lazily also get `on_tab_activated()`. A restored zoom and pan replaces the tab's first fit (its
  `_remembered_view`), it is not set and then fitted over.
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
- **The project's console:** Console above the tabs (`ContextBar.console_choice`, every setup of every console) calls
  `MainFrame.set_project_console`: it asks how to fit longer palettes (`palette_editor.panel.ask_fit_palettes`),
  applies `palette_editor.ops.set_console(project, console, keep_most_used, setup)`, checkpoints, and
  `show_project_console()` updates the menu, every view bar's budget menu
  (`canvas_display_controls.project_console_changed`) and the panels' `on_console_changed()` (the Timeline's screen);
  loading and undo call it too. Menus that show a console offer the project's first and others to compare: the budget
  menu keeps "" / "project" / a profile key per tab, the Timeline's Screen "" / "project" / a screen label
  (`SceneEditor/Screen`; up to 0.9 one screen for every project, `ScreenGuide`, which `stored_screen` reads as "project"
  when it showed one); a stored key that is the project's own counts as "project". Auto Modularize starts at
  `hardware_budget.project_profile` (another one is for that run only).
- **Budget overlay:** `FrameCanvas.budget_profile` + `compute_budget()` (the Timeline stage overrides it for the
  whole scene); the canvas draws the overlay with the content and the readout last (`_draw_budget_hud`). Keep
  `hardware_budget.py` in step with `console_bake.ConsoleBake._render_leaf_part`; both cut parts with
  `sprite_cut.export_cut` (`SGDKBakeContext._store_part`) on the Mega Drive and `sprite_cut.cut` with the setup's two
  sizes (`SNESBakeContext._store_part`) on the SNES, never with a cut of their own. `tests/test_hardware_budget.py`
  compares them, `tests/test_sgdk_runtime_draw.py` draws the pieces with the compiled runtime. Video memory (profiles
  of a console with an exporter, `HardwareProfile.vram_model`): each part carries the ids of the tile blocks the
  console's export stores for it (`HwPart.vram`, compared in palette indices, flips free: the Mega Drive's hardware
  sprites, the SNES's squares), so `Budget.unique_tiles` / `vram_tiles` count what a view, an animation or
  `export_tiles(project, mappings, profile)` (the whole export: every module, frame, step and scene sample per mapping)
  needs; the tests compare `export_tiles` with the exporters' totals. The readouts take the project's total from
  `canvas.EXPORT_TILES` (worked out again per undo checkpoint, `app_services.project_revision`); Check Project counts
  for the project's console (`check_dialog.memory_issues`: `tile_issue`, `snes_tile_issue`).
- **Palettes:** a palette's slot order is fixed once stored (swaps and cycles refer to slots); `palettes.py` maps a
  colour to its slot (exact, else nearest) the way the exporter does; the exporter, Check Project (per palette:
  `too-many-colours`, `colours-not-in-palette`, `palette-too-long`, `duplicate-palette-colour`; dead swap entries), the
  Palettes tab (on the NES and the Game Boy a slot takes one of the console's fixed colours, `fixed_colours.py`), the
  Modules inspector and every canvas (`ui/console_colours.py` `CONSOLE`: View ▸ Console Colours, the draw's palette
  swap, turning cycles; canvases put `CONSOLE.image_key(...)` in their cache keys) all use it. A recoloured image
  comes with the key colour cut out as alpha: never also set the key colour as a wx mask (on macOS the mask wins and
  shows the cut-out pixels). Palette swaps cost no tiles: the SGDK export stores the palettes and each swap's version
  of the palettes it changes as palette entries (blob v5); a piece stores its entry, the runtime maps entries to
  lines at draw time (`ms_set_palette_swap`, `ms_draw_anim_player_as`; bit 7 of a piece's entry = a scene object's
  own swap, not remapped), loads the entries into consecutive lines from `ms_init_ex`'s first line
  (`ms_palettes_fit`; `ms_load_palette` for more entries than lines) and turns cycles with `ms_palette_tick`. The
  export always writes Mega Drive palette lines (16 colours); a project whose palettes follow another console gets the
  `other-console` warning (`project_check.console_issue`).
  `tests/test_sgdk_runtime_draw.py` draws a swapped guard and turning cycles against the editor.
- **SGDK runtime:** the exporter writes everything into `modsprite_blob.bin` (`_emit_blob`) and generates the C
  record types and parser (`_emit_header`, `_emit_data_c`). Records are packed structs (`MS_RECORD`): when one
  changes, update the struct, the `struct.pack` format and the size list in `tests/test_sgdk_runtime_draw.py`, and
  bump `BLOB_VERSION` (now 5). Animation holds are exported with `playback.console_frames`, the preview's timing.
  Tiles stay in VRAM; drawing only writes `vdpSpriteCache` (no SGDK `SPR_*` engine).
  `tests/test_sgdk_runtime_draw.py` compiles `modsprite.c` for the host and compares its sprite table, rasterised
  like the VDP, with `FrameRenderer`. The active mapping is runtime state read at draw time (players keep none), so
  characters with different mappings share one set of animations (`ms_draw_anim_player_mapped`, as AuroraGT games
  set the mapping per draw); scenes are baked once per mapping, objects with their own mapping keep it. Measure performance in an emulator (BlastEm is cycle-accurate) with the V
  counter, not `getSubTick()` (it only advances per scanline and jumps around vblank).
- **Console exports:** `console_bake.ConsoleBake` is what every console's exporter shares: it bakes the project
  (render frames of parts, hitboxes and points; module and frame render frames; animation steps and records; scene
  samples and records; once per mapping) and calls `_store_part(image, palette, entry)` for each part's picture, which
  the console's exporter implements (the Mega Drive's `SGDKBakeContext`: VDP tiles, the sprite cut, pieces per flip).
  Put nothing console-specific into it (tile formats, sprite sizes, palette words, blob layout); a console's exporter
  subclasses it. `tests/test_console_bake.py` checks that a minimal exporter gets exactly the Mega Drive exporter's
  parts, frames, steps and samples.
- **SGDK export:** `export_project()` in the exporter is the one entry point for the command line and File ▸ Export ▸
  Mega Drive (the editor builds carry both console exporters: `pathex` + `hiddenimports` in the three editor specs). It writes
  the blob, the header and the parser and merges its `BIN MS_BLOB` line into the game's `res/resources.res`
  (`merged_resources`; never overwrite the game's file, and delete nothing in its folder but older exporters'
  `var_NNNN.png` sheets). Its issues are `project_check`'s plus the tile count (`tile_issue`) and the palette lines
  (`palette_issue`): whatever the exporter leaves out or changes must show up as an issue there, not
  disappear silently. Name C symbols through `project_check.c_symbols` so Check Project's clash warning stays true.
- **SNES export and runtime** (`examples/snes`, see its README): `export_snes.export_project()` is the entry point for
  the command line and File ▸ Export ▸ SNES; it bakes for one pair of sprite sizes (the project's SNES setup, else
  `--setup` / snes_8_16) and stops (`ExportError`) when the tiles do not fit the 512 or a table its bank; its issues
  are `project_check`'s plus `snes_tile_issue` and the palette count. A render frame's sprites are written in OAM order,
  in runs of one palette entry, ready for the sprite table. Records (`RECORDS`) are little-endian with every 16-bit
  field even; the ones the runtime indexes are padded to 8 or 16 bytes (816-tcc multiplies by other sizes with a
  library call), the render frame's 22 are multiplied in shifts (asserted); when a record changes, update the struct
  in `header_text`, the C reference and `modsprite_draw.asm` (the size list in the host test follows `RECORDS`), and
  bump `DATA_VERSION` (now 2). The hot loops are 65816 assembly (`modsprite_draw.asm`: `ms_put_render_frame`,
  `ms_add_hw_sprite`, `ms_finish_oam`) with C versions under `MS_PUT_FRAME_C`, which `tests/test_snes_runtime_draw.py`
  compiles for the host (`tools/snes_host.py`) and compares with the editor; `tests/test_snes_runtime_player.py` plays
  the Mega Drive player test's cases and every PoP animation against `playback.Player` video frame by video frame and
  checks every frame's and step's hitboxes and points (the SNES player is the Mega Drive's C: keep both in step);
  `tools/check_snes_rom.py` builds the
  assembly into a ROM and compares every OAM with the host build in Mesen 2 (run it after touching the runtime). 816-tcc:
  never step a far pointer in a loop (reach records by index), assembly reaches globals with long addressing
  (initialised ones live in bank $7F), a `u8` argument is pushed as one byte. CGRAM can only be written in vertical
  blank: `ms_palette_tick()` uploads what it prepared one call earlier, then prepares the next. Measure in Mesen 2 with
  the PPU's V counter (and Lua `exec` callbacks on single addresses for a breakdown), not by eye.
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
  Update `ui/shortcuts_dialog.py` and the README controls table when adding shortcuts, then regenerate the guide's
  page with `python3 website/scripts/make_shortcuts_page.py` (`website/docs/reference/shortcuts.md` is generated from
  the dialog's list: never edit it by hand). The same holds for `website/docs/reference/consoles.md`, made from
  `consoles.py` by `website/scripts/make_consoles_page.py`; `tests/test_generated_pages.py` fails while either is stale.
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
  Several layers can be selected (`selected_object_ids`, the inspector's one last as `selected_object_id`; setting
  `selected_object_id` alone makes it the only one): drags, arrows, flips, Delete, Duplicate and Copy act on
  `ops.top_objects` (a child whose parent is selected follows it), Paste pastes what was copied last (keys or
  layers, `ops.copy_objects` / `paste_objects`, also into another scene). Following a point: `ops.set_attachment`
  keeps the object in place at the playhead, reparenting ends it (`set_parent_keep_world`), key positions of an
  attached object live in `ops.key_space_matrix`; Check Project warns when no frame of the parent has the point.
- **Animations:** holds are ticks at `Animation.fps`; anything below 1 plays as 1 (`ops.hold`), like the exporters.
  The preview plays the game's timing: `Player(anim, hold_of=playback.console_hold(anim))` advances one video frame
  per call (each step held for its `console_frames`), at `REFRESH.hz(project)` frames a second (View ▸ Play at 50 Hz;
  the Timeline and colour cycles follow it too). Rates that do not divide 60 round steps; Check Project notes it
  (`rounded-holds`). Spread presets (`ops.SPREADS`) and Change Animations (`ops.change_animations`, tick rate with or
  without keeping the timing) are wx-free. Playback preview goes through `playback.Player` (also `ops.Player`),
  which mirrors `ms_anim_player_tick` in the SGDK runtime (Loop backwards repeats; ping-pong does not repeat its end steps; `loop_start`, repeat counts,
  follow-up animation); `tests/test_runtime_player.py` compiles the C player and compares both tick by tick (the SNES
  runtime's copy: `tests/test_snes_runtime_player.py`), and `tests/test_playback.py` checks `playback.step_after` /
  `animation_at` (what scenes use) against the Player — keep them all in sync.
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
  all its pixels equal the sprite's, or (``Settings.underdraw``) where the pixels that differ are opaque in the sprite
  and still to be covered by parts drawn later (the leftovers at the latest), so placements are in draw order and
  `apply_plan` keeps that order; every opaque pixel is covered. Its cost model is the chosen console's
  (`Settings.hardware`, `part_tiles` = `sprite_cut`, what the budget and the export count). Mappings: modules that
  mappings replace are planned with `own` (parts of their own) and get an empty stand-in in their frames, which the
  mappings replace instead (their parts hidden); modules mappings show stay (`mapping_roles`, `mapping_only`: the
  Modules tab leaves those out). Measure changes with `tools/automod_bench.py` (flattened testbeds, exactness, tiles,
  hardware sprites; `--console`; every row the frames alone) — `tests/test_modularize.py` covers the rewrite of
  flipped / rotated references, underdraw and mappings. Hand-made modular art such as PoP draws parts over each other
  (a quarter of its pixels are hidden): flattened frames lack those pixels, so no plan gets near its tile count.
- **Imports** list whatever they leave out or can't find in `Project.load_notes` (`importers.notes.Notes`: one line per
  kind, with examples), never silently; `Project.imported_from` marks an import, which the editor opens as a new,
  unsaved project (File ▸ Open of another editor's file too), so Save never writes over the file it came from. The
  Aseprite reader is checked pixel for pixel against Aseprite's own export; an import that writes a file (the
  packed `<name>.sheet.png`) never writes over an existing one.
- **Exports for other engines** (`exporters/sheet.py`) draw through `compositor` with the preview's mapping and palette
  swap, steps with their offsets, flips and turns; hitboxes and points move like the SGDK export's (`step_markers`),
  and `clips` turns each animation into engine clips that play like `playback.Player` (an intro clip and a loop clip
  for "loop from"). `tests/test_sheet_export.py` imports the JSON back and compares every frame with its step, checks
  the clips against `playback.step_after` in every mode and the markers against the SGDK exporter.
  `exporters/godot.py` and `exporters/unity.py` write the engines' text assets in the layout the engines write
  themselves (Godot 4.6, Unity 6000.6; Unity's clip binding table is CRC32 of path and property, its texture meta
  must be serializedVersion 13 with `nameFileIdTable` or Unity gives the sprites new ids). After changing them run
  `tools/check_engine_exports.py` (`tools/engine_checks`: a Godot script and Unity editor scripts that sample every
  clip, play events and follow-ups); in Godot test after the scene is ready (autoplay, deferred method calls) and
  stop the player between clips (it queues follow-ups when an animation starts).
- **Destructive actions** confirm when they break references (count the references) and stay undoable. Deleting
  modules, an image or a frame that is still used asks through `confirm.ask_remove_uses` (call it module-qualified,
  the smoke test patches it): remove the uses too (`module_editor.ops.remove_module_uses`,
  `frame_editor.ops.remove_frame_uses`, `scene_editor.ops.clear_sources`) or keep them as missing, which Check
  Project lists with a fix. A new kind of reference needs a check and, where possible, a fix in `project_check.py`.
- **Lists** use + New / Duplicate / Delete buttons (images: + Add), Delete key, double-click/F2 rename, drag to
  reorder and a filter (`wx.SearchCtrl`); new lists use `components.thumb_list.Browser` / `ThumbList`. Lists show a
  filtered view: map rows to objects by id, never index `project.frames[...]` with a list index. Long lists (frames,
  animations) add a group filter and sort order (`Browser.add_group_bar`, `ui/grouping.py`: the filter text finds
  groups too; drag to reorder only in list order).
- **Preferences:** editor-wide settings belong in the Preferences window (`ui/preferences_dialog.py`,
  `MainFrame.preference_values` / `apply_preferences`) and, when they are views, in the View menu too.
- **Theme** (`ui/theme.py`, View ▸ Theme and Preferences: like the system, dark or light): whatever the editor draws
  itself takes its colours from `T` (`T.row`, `T.hint`, ... read when painting, never kept), labels and backgrounds
  set once go through `T.style(window, fg=, bg=)`; add a colour to `theme.COLOURS` (a dark and a light version)
  rather than writing `wx.Colour(...)` into a panel. Lines over the art (outlines, selections, drafts, the grid) use
  `BaseCanvas.overlay_colour`, which follows the backdrop actually behind them (a solid backdrop colour can be light
  in the dark theme); handles, hitbox / point colours and readouts in their dark boxes keep fixed colours. Pictures
  drawn on a theme colour (thumbnails) put `T.dark` or the colour in their cache key. A change calls
  `MainFrame.theme_changed`: the picture caches are cleared (`images_changed`) and every window redrawn. On macOS a
  chosen Dark or Light also sets the application's appearance; wx 3.2 cannot darken Windows' or GTK's own controls.
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
| Sprite sheets, PNG sequences | `exporters/sheet.py` (on `compositor`) | yes | yes | yes | yes |
| Scene pictures and GIF | `ui/scene_editor/thumbnails.py` (`FrameRenderer`, each object's mapping and swap) | yes | yes | yes | yes |
| SGDK export | `examples/sgdk/tools/export_sgdk_example.py` (on `console_bake.py`) | yes | baked | yes | yes |
| SNES export | `examples/snes/tools/export_snes.py` (on `console_bake.py`) | yes | baked | yes | yes |

Previews share one compositor (`compositor.py`, cached by `ui/frame_render.py`); `tests/test_thumbnails.py` checks
thumbnails against the canvas. The console exporters bake on their own (they need per-part hardware sprites, not a flat
image); `tests/test_sgdk_runtime_draw.py` and `tests/test_snes_runtime_draw.py` check what the Mega Drive and SNES
runtimes draw against `FrameRenderer`.
