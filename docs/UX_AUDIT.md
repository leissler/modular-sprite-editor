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
| X6 | "Saved to ..." modal after every Cmd+S; many "Success" modals after routine operations. | Flow interruption | done: status-bar messages instead of modals for routine results |
| X7 | No status bar; editors use ad-hoc labels ("Selection: -", "Pivot: -"). | Inconsistency | done: shared status bar (messages + zoom + hints) |
| X8 | `File ▸ New` handler exists but is not in the menu; no Edit / View / Help menus; About text shows a literal `\n`. | Missing affordances | done |
| X9 | **Pan gesture differs per canvas**: Modules = Alt/Middle, Frames = Alt/Middle, Animations = Alt/Ctrl/Middle, Timeline = Alt/Ctrl/Middle, Dopesheet = Space/Middle. | Inconsistency | done: Space+drag, Alt+drag or middle-drag on every canvas |
| X10 | **Non-integer zoom** (1.1× steps) produces uneven pixel sizes with nearest-neighbour scaling — wrong for pixel art. | Pixel-art fidelity | done: zoom snaps through integer levels (1×…32×) |
| X11 | No "fit to content" / "reset view". | Navigation | done: View ▸ Fit (Cmd+0) and Actual size (Cmd+1) on every canvas |
| X12 | Transform shortcuts differ: Frames uses X/Y to flip, Timeline uses H/V and R. | Inconsistency | done: H / V / R / Shift+R everywhere (X/Y kept as aliases in Frames) |
| X13 | List management buttons differ per tab: `+`/`-`, `Add`/`Del`, `Add`/`Delete`; rename via double-click in some lists only; Delete key works in some lists only. | Inconsistency | done: Add / Duplicate / Delete everywhere, Delete key + double-click rename where lists support it |
| X14 | Big lists (165 modules, 207 frames, 171 animations) have no filter. | Navigation | done: search filter on module list, module palette, frame list, frame palette, animation list |
| X15 | Debug leftovers: frame flips append to `safe_debug.txt` in the CWD; `print("DEBUG: Save As triggered")`. | Hygiene | done |
| X16 | Every paint rescales every module bitmap (and frame canvases re-mirror/rotate images each paint). Dragging large frames is sluggish. | Performance | done: scaled-bitmap cache keyed by zoom/flip/rotation |
| X17 | Several renderers disagree: thumbnails and GIF export ignore nested frames and per-part rotation; GIF export ignores shape modules and mappings. | Correctness | open (see §7) |

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
| F5 | README promises onion skinning, which does not exist. | done in Animations (prev/next ghosts); "reference frame" ghost in Frames |
| F6 | Two `on_frame_list_context_menu` definitions (the first is dead). | done |

## 4. Animations tab

| # | Finding | Status |
|---|---------|--------|
| A1 | Two centred rows mix per-frame properties, animation properties and view toggles ("Trajectory", "Mirror X/Y", "Col", "Pts"). | done: grouped into *Frame*, *Animation* and a canvas view bar |
| A2 | No play/pause or step shortcut (README claims Space / ←→). | done: Enter = play/pause, `,` / `.` = step, ←→ in the strip |
| A3 | Frame strip shows no duration; holds are invisible. | done: duration badge per cell + total length (ticks / seconds) |
| A4 | No onion skin. | done: previous/next ghosts |
| A5 | AFrame rotation is only reachable from the context menu. | open |

## 5. Timeline tab (experimental)

| # | Finding | Status |
|---|---------|--------|
| T1 | One long "Object & Key" form (the `&` is swallowed as a mnemonic and renders as "Object Key"); disabled Scale X/Y rows; spline handle rows shown for linear paths. | done: separate *Object* and *Keyframe* boxes, hidden scale rows, handle rows only for spline paths |
| T2 | Scene settings (name, FPS, length, loop) are in the transport bar, object Add-Null/Delete are mixed with transport buttons. | done: scene settings next to the scene list, object buttons above the tracks |
| T3 | No undo. | done (global history) |
| T4 | No play/step shortcuts. | done (same keys as Animations) |

## 6. Mappings tab

| # | Finding | Status |
|---|---------|--------|
| P1 | An unmapped slot is labelled "None" although it renders the *original* module; "Clear All" says "map all to None" but actually resets to original. Hidden modules (value `null`) cannot be created from the UI. | done: "= original" vs "Hidden" states, right-click slot ▸ Reset / Hide, "Reset All" |
| P2 | Duplicate `on_left_down` / `set_project` definitions. | done |

## 7. Recommended next steps (not done in this pass)

* **One shared compositor** (`Project`-level, PIL based) used by thumbnails, GIF export, onion skin and the
  RetroAnimator/SGDK exporters so nested frames, rotation, shapes and mappings render identically everywhere (X17).
* Frame list thumbnails (small icons in the list).
* Proportional-width (duration-scaled) cells in the animation strip, drag-to-change duration.
* AFrame rotation control in the Animations tab (A5).
* Per-project persisted view settings (grid size, zoom per tab) in `wx.Config`.
* See `docs/ANIMATION.md` for the animation feature roadmap.
