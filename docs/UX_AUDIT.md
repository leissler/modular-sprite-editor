# UI / UX / Workflow Audit

Audit of the editor as of commit `8af7238` (plus the dopesheet zoom/pan WIP), done against the
Prince of Persia (`examples/sgdk/PoP_WW.json`, 165 modules / 207 frames / 68 animations) and
Sonic (`~/Downloads/sonic.json`, 65 modules / 38 frames / 171 animations) testbeds.

Status legend: **done** = implemented on branch `ux-declutter-consistency`, **open** = recommended,
not implemented yet.

---

## 1. Cross-cutting findings

| # | Finding | Impact | Status |
|---|---------|--------|--------|
| X1 | **No unsaved-changes tracking.** Closing the window, opening another project or importing silently discards all edits. | Data loss | done: project fingerprint, `*` in title, Save/Discard/Cancel prompt on close/open/new/import |
| X2 | **Undo exists only in Frames and Animations**, each with its own stack. Modules, Timeline, Mappings, collision/point types and all list operations (delete frame, slice image, auto-detect...) cannot be undone. | Data loss, inconsistency | done: one project-wide history (Edit ▸ Undo/Redo, Cmd+Z / Cmd+Shift+Z / Cmd+Y) for every editor |
| X3 | Destructive operations without confirmation: delete frame (breaks animations that reference it), delete module, remove image (deletes its modules), **Slice Image / Auto Detect wipe every module of the image** (and with it every frame part that references them), delete scene, delete mapping. | Data loss | done: confirmation dialogs with reference counts (plus undo) |
| X4 | Empty toolbar band between title and tabs (created but never populated). | Clutter | done: removed; replaced by a slim context bar with the mapping selector |
| X5 | The **active mapping is hidden global state**: selecting a mapping in the Mappings tab silently changes rendering in all other tabs *and* what gets exported, with no indicator elsewhere. | Confusion, wrong exports | done: "Preview mapping" selector visible on every tab |
| X6 | "Saved to ..." modal after every Cmd+S; many "Success" modals after routine operations. | Flow interruption | done: status-bar messages for save, slice, auto detect, reference frames, deletes (multi-line reports such as export summaries stay dialogs) |
| X7 | No status bar; editors use ad-hoc labels ("Selection: -", "Pivot: -"). | Inconsistency | done: shared status bar (messages + zoom + hints) |
| X8 | `File ▸ New` handler exists but is not in the menu; no Edit / View / Help menus; About text shows a literal `\n`. | Missing affordances | done |
| X9 | **Pan gesture differs per canvas**: Modules = Alt/Middle, Frames = Alt/Middle, Animations = Alt/Ctrl/Middle, Timeline = Alt/Ctrl/Middle, Dopesheet = Space/Middle. | Inconsistency | done: Space+drag, Alt+drag or middle-drag on every canvas |
| X10 | **Non-integer zoom** (1.1× steps) produces uneven pixel sizes with nearest-neighbour scaling — wrong for pixel art. | Pixel-art fidelity | done: zoom glides during a wheel/trackpad gesture and snaps to an integer level (1×…32×) when it stops; trackpad gestures are locked to one axis |
| X11 | No "fit to content" / "reset view". | Navigation | done: View ▸ Fit (Cmd+0) and Actual size (Cmd+1) on every canvas |
| X12 | Transform shortcuts differ: Frames uses X/Y to flip, Timeline uses H/V and R. | Inconsistency | done: H / V / R / Shift+R everywhere (X/Y kept as aliases in Frames) |
| X13 | List management buttons differ per tab: `+`/`-`, `Add`/`Del`, `Add`/`Delete`; rename via double-click in some lists only; Delete key works in some lists only. | Inconsistency | done: Add / Duplicate / Delete everywhere, Delete key + double-click rename where lists support it |
| X14 | Big lists (165 modules, 207 frames, 171 animations) have no filter. | Navigation | done: search filter on module list, module palette, frame list, frame palette, animation list |
| X15 | Debug leftovers: frame flips append to `safe_debug.txt` in the CWD; `print("DEBUG: Save As triggered")`. | Hygiene | done |
| X16 | Every paint rescales every module bitmap (and frame canvases re-mirror/rotate images each paint). Dragging large frames is sluggish. | Performance | done: scaled-bitmap cache keyed by zoom/flip/rotation |
| X17 | Several renderers disagree: thumbnails and GIF export ignore nested frames and per-part rotation; GIF export ignores shape modules and mappings. | Correctness | partly done: the Animations tab (list icons, sequence thumbnails) and GIF export now render through the parity-checked RetroAnimator renderer; frame/module palettes still use `ThumbnailGenerator` (see §7) |
| X18 | One "Transparency" checkbox mixed two jobs (checkerboard *and* hiding the sheet's key colour); turning it off in a composition tab painted opaque pink boxes over the parts behind them, and the Timeline used it differently. | Inconsistency | done: **Backdrop** (Checker / Colour, a shared preview colour; Timeline: the scene colour) in every view bar; key colour always hidden except via **Show key colour** in Modules; **Part bounds** overlay in Frames, Animations and Timeline outlines each part's rectangle instead |
| X19 | Switching to the Timeline took ~0.5 s and typing in a module filter ~2 s per key: macOS builds a mask for every bitmap added to a masked `wx.ImageList`. | Performance | done: thumbnail image lists use `mask=False` |

## 2. Modules tab

| # | Finding | Status |
|---|---------|--------|
| M1 | The shape-type choice + colour swatch sit *above* the module list and look like a list filter; their meaning ("type for the next module you create") is unclear. | done: moved into a "Module" properties box below the list |
| M2 | Rect and pivot can only be changed by dragging; no numeric entry. For pixel-exact work this is the most common need. | done: X / Y / W / H and pivot X / Y spin controls |
| M3 | "Grid Slice" box (tile W/H, Slice, Auto Modularize) plus "Auto Detect / Merge Gap" are always visible although rarely used. | done: one "Slice ▾" menu button (Grid Slice…, Auto Detect…, Auto Modularize…) |
| M4 | Image list takes 1/3 of the sidebar even with a single image. | done: compact image list |
| M5 | Pivot drag is Shift+drag, pan is Alt+drag; undocumented. | done: hints in status bar + shortcut sheet |
| M6 | Duplicate methods (`refresh_images`, `show_optimization_dialog`), duplicate attribute inits. | done: removed |

## 3. Frames tab

| # | Finding | Status |
|---|---------|--------|
| F1 | Edit-mode selector (Modules / Collision / Points) lives in the frame-list button row, far from the canvas it controls. "Role Tools" button sits in the same row. | done: mode + overlay toggles in a canvas toolbar; Role tools moved to Tools menu |
| F2 | No keyboard nudge for parts, collision boxes or points (pixel-exact placement needs arrows). | done: arrows = 1 px, Shift+arrows = 8 px (one tile) |
| F3 | No copy/paste/duplicate of parts between frames (core modular workflow). | done: Cmd+C / Cmd+V / Cmd+D, Cmd+A select all |
| F4 | Paste / propagate collision & points and frame mirror/rotate are not undoable. | done (global history) |
| F5 | README promises onion skinning, which does not exist. | done: Animations ghost previous/next animation step (with their offsets); Frames ghost the previous/next frame of the (filtered) frame list |
| F6 | Two `on_frame_list_context_menu` definitions (the first is dead). | done |

## 4. Animations tab — redesigned (`animation-redesign` branch)

A first pass grouped the old controls (A1–A4: view bar, Enter/`,`/`.`, duration badges, onion skin). The redesign
then replaced `ui/animation_editor.py`, `ui/components/timeline_control.py` and `AnimationCanvas` with
`ui/animation_editor/`, laid out like the Timeline tab (list | stage | inspector, full-width sequence below). The file
format is unchanged.

| # | Finding in the old editor | Redesign |
|---|---------|--------|
| A1 | Animation list showed names only; nothing told you how long an animation is or how it plays. Adding a frame appended it at the end and needed a selected animation (otherwise a modal message). | List rows with a first-step thumbnail, *steps · ticks · seconds · mode*; rename in place, drag to reorder. Frames drop exactly where they should go in the sequence (or onto the stage / double-click: after the current step); with no animation one is created. |
| A2 | Equal-width strip cells, holds only as a `×N` badge, no time ruler; reorder via OS drag & drop or *Move Left/Right*; single selection; Edit ▸ Copy/Paste/Duplicate/Select All did nothing in this tab. | **Sequence on a tick ruler**: a step is as wide as its hold, longer holds show a hold bar; drag the right edge to retime, drag to reorder, Alt+drag copies; click / Shift / Cmd multi-select; copy/paste/duplicate/select all; `[` `]` change holds; a colour stripe marks repeated frames (cycles). |
| A3 | "Selected Frame" and "Animation" boxes in one dense row under the strip; Flip X/Y checkboxes (H/V elsewhere); step rotation only as a whole-animation menu entry (A5). | Contextual inspector: **Animation** (name, playback in plain words, repeat count only when it repeats, tick rate with ms / 60 Hz frames, length, timeline usage, whole-animation Mirror H/V, rotate, reverse, GIF) and **Step** / **N steps selected** (frame swap, hold, offset, ↺/↻ rotation, Flip H/V). H/V/R keys as in Frames. |
| A4 | Preview played "backward" once and stopped, while the SGDK runtime repeats it; a timer per step; no slow motion. | `ops.Player` advances tick by tick like the runtime's `ms_anim_player_tick`, plus the animation's repeat count (which the runtime ignores); the Repeat toggle restarts finished previews; playhead moves through holds; speed ¼× / ½× / 1× / 2×. |
| A5 | Mirror preview kept a step's rotation, which is wrong for 90°/270° steps (64 of 260 synthetic variants differed once checked). | Stage mirror reverses the rotation for an odd number of mirror axes; `tools/check_export_parity.py` now checks the mirror preview against the step renderer for every step. |
| A6 | GIF export ignored nested frames, part rotation, shape modules and the preview mapping, and confirmed with a modal dialog. Strip thumbnails ignored nested frames and part rotation. | GIF export and every thumbnail use the parity-checked renderer; the GIF plays one cycle in playback order (reversed / ping-pong); status bar instead of a dialog. |
| A7 | Steps with hold 0 (35 in PoP) showed `×0` but flashed for 10 ms in the preview; the exporters play them as one tick. | Timing treats them as one tick everywhere (`ops.hold`); the cell flags `×0` in red and the inspector explains it. |

Not done (needs a format change, see `docs/ANIMATION.md`): step events / markers, loop-from step and follow-up
animation, hardware budget overlay.

## 5. Timeline tab — redesigned (`timeline-redesign` branch)

The first pass only tidied the old editor (grouped boxes, global undo, play shortcuts); the redesign then replaced `ui/timeline_editor.py`
(3 400 lines) with `ui/scene_editor/` built around how animators already work (Flash/Animate, After Effects,
Spine, Aseprite). The file format is unchanged; every existing scene opens as before.

| # | Finding in the old editor | Redesign |
|---|---------|--------|
| T1 | One long inspector form mixing scene, object, key, segment, path and swap fields; many fields irrelevant to the selection; jargon ("source switch", "source offset", "root motion", spline handle numbers). | Contextual inspector: only the sections that apply (Scene when nothing is selected; Object; Animation playback only for animation sources; Transform *at frame N*; Motion to next key; Swap image at this key). Plain words, tooltips for the jargon. |
| T2 | Draw order was a number in the inspector and unrelated to the row order in the dopesheet; no per-layer hide / lock. | Row order = draw order (lower rows draw on top); drag a layer to reorder, onto another to parent it (world pose preserved). Eye / lock per layer. |
| T3 | Playhead edited in seconds, plus Ruler (time / frames) and Snap (free / frames / tenths / custom) modes. | Frames everywhere (ruler, playhead, inspector, length); keys always sit on whole frames; seconds only as secondary info. |
| T4 | Editing a pose required finding/selecting the right key first. | Auto-Key (on by default): move / flip / rotate at the playhead and a key appears. Off: edits move the whole layer. K / Shift+K set / toggle a key. |
| T5 | Easing picked per key from 32 technical names (`expo_in_out`, …) without a preview; it applied to the segment *ending* at that key, which was not obvious. | Tween bars between keys labelled with the easing ("Strong ease out", "Hold"); right-click a bar for quick presets; inspector picks shape × direction with a live curve preview. |
| T6 | Kept: motion path with draggable keys / spline handles on the canvas. | Added per-frame dots on the path (spacing shows the easing) and a plain "Straight / Curved" path choice for the layer. |
| T7 | No idea what fits on the console screen. | Screen guide (MD / SNES / NES / GBA / GB) with the scene origin at the screen's top-left; outside is dimmed. |
| T8 | Animation objects gave no hint where their frames change. | Green ticks on the layer row where the playing animation changes frame. |
| T9 | Scene settings, source palette and transport spread over three boxed panels. | Library (Animations / Frames / Modules, filtered) on the left, scene settings in the inspector when nothing is selected, one transport row above the timeline. |

Known limits: one selected object at a time (keys can be multi-selected across layers); rotation tweens in
90° steps; scale/opacity stay hidden (no hardware support on the main target).

## 6. Mappings tab

| # | Finding | Status |
|---|---------|--------|
| P1 | An unmapped slot is labelled "None" although it renders the *original* module; "Clear All" says "map all to None" but actually resets to original. Hidden modules (value `null`) cannot be created from the UI. | done: "= original" vs "Hidden" states, right-click slot ▸ Reset / Hide, "Reset All" |
| P2 | Duplicate `on_left_down` / `set_project` definitions. | done |

## 7. Recommended next steps (not done in this pass)

* ~~Decide the flip semantics.~~ **Resolved:** in-place part flips (editor behaviour) are canonical. The
  RetroAnimator exporter was fixed (it mirrored around the pivot since `a50b12f`, displacing 546 flipped parts
  in 189 PoP_WW frames). The parity check also exposed two canvas bugs, now fixed: rotated children of nested
  frames were drawn away from their hit-test bounds, and mirrored animation steps / mirror preview rotated
  parts the wrong way. `tools/check_export_parity.py` keeps export and canvas pixel-identical.

* **One shared compositor** (`Project`-level, PIL based) used by thumbnails, GIF export, onion skin and the
  RetroAnimator/SGDK exporters so nested frames, rotation, shapes and mappings render identically everywhere (X17).
* Frame list thumbnails (small icons in the list).
* Proportional-width (duration-scaled) cells in the animation strip, drag-to-change duration.
* AFrame rotation control in the Animations tab (A5).
* Per-project persisted view settings (grid size, zoom per tab) in `wx.Config`.
* Delete key for the scene list; drag-reorder for scenes and mappings.
* Remove the stale root-level `test_*.py` scripts or move them into `tests/` (one of them fails by design).
* See `docs/ANIMATION.md` for the animation feature roadmap.
