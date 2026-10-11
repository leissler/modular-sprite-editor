![Modular Sprite Editor](assets/banner_project.png)

# Modular Sprite Editor

**A specialized tool for assembling, animating, and mapping modular pixel-art sprites for retro consoles.**

Construct complex character animations from individual body parts (modules). Define pivots, assemble frames, create animations, and map internal hitboxes/points for game logic — then export to SGDK (Mega Drive) or RetroAnimator.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg) ![Library](https://img.shields.io/badge/GUI-wxPython-orange.svg) ![Platform](https://img.shields.io/badge/Platform-Win%20%7C%20Mac%20%7C%20Linux-lightgrey.svg)

---

## ⚠️ Project Status

- The **Modules / Frames / Animations / Mappings** workflow is actively used and is the most complete part of the tool.
- The **Timeline** (scene editor) was redesigned on the `timeline-redesign` branch and is still young: the file format is unchanged, but the UX may still evolve.
- SGDK export and demo content lives in [`examples/sgdk`](examples/sgdk/README.md), including a blob-based runtime data path for Mega Drive tests.
- Project files carry a `format_version` (currently 3); older files are upgraded on load. See [`docs/FILE_FORMAT.md`](docs/FILE_FORMAT.md).

---

## ✨ Key Features

### Everywhere
*   **Project-wide Undo/Redo** for every editor, unsaved-change tracking and a save prompt on close.
*   **One canvas model**: wheel/trackpad zoom glides and settles on whole pixel sizes (1×, 2×, 3×…), Space/Alt/middle-drag pans, `Ctrl+0` fits.
*   **Preview mapping selector** above the tabs — the mapping applied to every preview and to exports.
*   **Filters** on all long lists (modules, frames, animations, palettes).

### 🛠️ Module Editor
*   **Cut directly on the sheet**: drag over a sprite to make a module; move, resize (8 handles, optional grid snap) and nudge it right there; Cmd+drag selects several.
*   **Slicing tools**: grid slice (tile size, offset, gap, skip empty tiles), sprite detection (touching pixels, merge gap; milliseconds on a full sheet), auto modularize — each can keep the existing modules and add only new areas. Copy modules and paste them onto another image to cut the same areas there.
*   **Pivots**: Shift+drag, type them, or a 3×3 preset (bottom centre = feet on the origin); **Trim** shrinks modules to their pixels.
*   **Images list** with thumbnails, missing files flagged (**Locate…** relinks), key colour picked from the image; **modules list** with thumbnails, size and how often each is used.
*   **Vector shape modules** (rects, arcs, triangles, lines, markers) on their own *Shapes* sheet, rendered pixel-exact.

### 🖼️ Frame Editor
*   **Frames list with thumbnails** and usage; a **library** of modules (per image) and frames to drag onto the stage or double-click.
*   **Parts / Hitboxes / Points** modes above the stage; the inspector edits the selection (position, flips, rotation, draw order, swap the source; hitbox type, role, rect) and the frame (mirror, rotate, put the feet on the origin).
*   **Contents list** of the frame's parts (top-most first; drag to reorder), hitboxes or points; marquee selection on the stage.
*   **Pixel-exact editing**: arrow-key nudging (Shift = 8 px tile), flip (H/V), 90° rotation (R), draw order, copy/paste/duplicate of parts between frames.
*   **Hitboxes & points** with semantic roles (compiled into per-animation lookup tables); types managed inline (colour, visibility, usage).
*   **Onion Skinning**: ghost the previous/next frame of the list.

### 🎮 Hardware Budget (Mega Drive)
*   **Budget** in the Frames, Animations and Timeline view bars (MD H40 / H32): outlines the hardware sprites each part becomes, marks scanlines where sprites would drop out in red, and shows sprites, tiles and the busiest line. The Animations inspector names the worst step; the Timeline counts the whole scene. Numbers follow the SGDK exporter.

### 🎬 Animation Editor
*   **Sequence on a tick ruler**: every step is as wide as its hold; drag a step's right edge to change the hold, drag steps to reorder (Alt copies), drop frames from the library where they should go. A coloured stripe marks repeated frames.
*   **Playback like the game**: Loop, Play once, Ping-pong and Loop backwards follow the SGDK runtime tick by tick; preview speed ½× / ¼× / 2×.
*   **Stage**: drag to move the selected steps' offsets, motion path, onion skin, mirror preview, part bounds, collision boxes and points.
*   **Animations list** with thumbnails, length and playback mode; contextual inspector for the animation and the selected step(s); whole-animation mirror / rotate / reverse.
*   **Game data on animations**: step **events** (hit windows, sounds, spawns… from a project-wide list, with a value), **Loop from** a step (an intro plays once), and **Then play** a follow-up animation when one ends (`attack → idle`). The SGDK runtime plays them exactly like the editor preview.
*   **GIF Export** of one playback cycle, pixel-identical to the editor (nested frames, rotation, shapes, preview mapping).

### 🎬 Timeline (Scenes)
*   **Library → Stage**: drag animations, frames or modules onto the stage; a console screen guide (MD / SNES / NES / GBA / GB) shows what fits on screen.
*   **Layers + dopesheet** in one timeline, counted in frames: lower rows draw on top, drag a layer onto another to parent it, eye / lock per layer.
*   **Auto-Key** like in animation tools: moving, flipping or rotating an object sets a key at the playhead. With Auto-Key off, edits move the whole layer.
*   **Readable tweens**: bars between keys show the easing by name (right-click a bar to change it), curved paths are edited on the stage, animation frame changes show as ticks.
*   **Contextual inspector**: only what applies to the selection — scene, object, animation playback, transform at the playhead, motion to the next key, swap image at a key.

### 🎯 Mapping Editor
*   **Module Variants**: Replace modules (e.g. "Clean Armor" → "Damaged Armor") or hide them (invisibility) without touching frames.
*   **Module map**: every module with what it shows under the mapping; select rows and click a replacement (or drag it onto a row); filter by image or "changed only".
*   **Bulk matching**: map a whole sheet onto a recoloured copy with the same layout, or by names (`_red` → `_blue`).
*   **Preview** of the frames the selected modules appear in, drawn with the mapping.

---

## 🚀 Getting Started

### Prerequisites
*   Python 3.10 or higher
*   pip (Python Package Manager)

### Installation (Development)

1.  **Clone the repository**
    ```bash
    git clone https://github.com/leissler/modular-sprite-editor.git
    cd modular-sprite-editor
    ```

2.  **Create a Virtual Environment**
    ```bash
    # Mac/Linux
    python3 -m venv .venv
    source .venv/bin/activate

    # Windows
    python -m venv .venv
    .venv\Scripts\activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the App** (optionally with a project to open)
    ```bash
    python app.py examples/sgdk/PoP_WW.json
    ```

### Build Executables
```bash
# macOS
./build_macos.sh

# Linux
./build_linux.sh
```

```bat
REM Windows
build_windows.bat
```

Releases come from the **Build And Release** GitHub workflow (Actions ▸ Run workflow, with a version). It builds
the editor and the SGDK exporter (`export_sgdk`, the exporter as one executable) for all three platforms, tests
every build (unit tests; the built editor drives every tab against both example projects with
`--smoke-test PROJECT.json [LOG]`; the built exporter must write exactly what the Python one writes) and publishes
`ModularSpriteEditor-{macos,windows}.zip`, `ModularSpriteEditor-linux.tar.gz` and `export_sgdk-*`. With *publish*
off the run only builds and tests.

The run also leaves a **Windows kit** (artifact `windows-kit`, not released) to hand to a developer: the editor,
`export_sgdk.exe`, the example projects and the SGDK demo with the SGDK it builds with, plus `export_to_sgdk.bat` /
`build_sgdk_demo.bat` and a README (`tools/make_windows_kit.py`, `packaging/windows_kit/`). CI unpacks it and builds
the PoP_WW and Sonic ROMs with those scripts.

### Tests & Tools
```bash
python3 -m pytest -q                          # unit tests
python3 tools/gui_smoke.py [project.json]     # drives the real UI against a project (needs a display)
python3 tools/migrate_projects.py --dry-run DIR   # upgrade project files to the current format
```

---

## ⌨️ Controls

`Cmd` on macOS, `Ctrl` elsewhere. The full table is in **Help ▸ Keyboard & Mouse Shortcuts** (`Cmd+/`).

| Context | Action | Shortcut |
| :--- | :--- | :--- |
| **General** | New / Open / Save / Save As | `Cmd+N` / `Cmd+O` / `Cmd+S` / `Cmd+Shift+S` |
| | Undo / Redo (all editors) | `Cmd+Z` / `Cmd+Shift+Z` |
| | Switch tab | `Cmd+1` … `Cmd+5` |
| **Canvas** | Zoom at cursor (settles on whole pixel sizes) | `Mouse Wheel` / two-finger scroll / pinch |
| | Pan | `Space + Drag`, `Alt + Drag`, `Middle Mouse Drag`, `Shift+Wheel` |
| | Fit / Actual pixels / Grid | `Cmd+0` / `Cmd+Shift+0` / `Cmd+G` |
| **Modules** | New module / move / resize | Drag on the image / drag a module / drag a handle |
| | Move pivot / select several | `Shift + Drag` / `Cmd + Drag` |
| | Nudge 1 px / 8 px | `Arrows` / `Shift+Arrows` |
| **Frames** | Nudge 1 px / 8 px | `Arrows` / `Shift+Arrows` |
| | Flip / Rotate 90° | `H` `V` / `R` (`Shift+R` = CCW) |
| | Draw order | `Cmd+↑/↓` (`Shift` = to front/back) |
| | Copy / Paste / Duplicate / Select all | `Cmd+C` / `Cmd+V` / `Cmd+D` / `Cmd+A` |
| | Select several parts | Drag on empty space |
| **Mappings** | Original / hide the selected modules | `Delete` / `H` |
| **Animations / Timeline** | Play/Pause | `Enter` |
| | Previous/Next step (Animations) or frame (Timeline) | `,` / `.` (`←` / `→` in the sequence / timeline) |
| **Animations** | Previous/Next tick, first/last step | `Shift+,` / `Shift+.`, `Home` / `End` |
| | Shorter / longer hold | `[` / `]` or drag a step's right edge |
| | Flip / Rotate selected steps | `H` `V` / `R` (`Shift+R` = CCW) |
| **Timeline** | Previous/Next key, first/last frame | `Shift+,` / `Shift+.`, `Home` / `End` |
| | Set key / add-or-remove key at playhead | `K` / `Shift+K` |
| | Flip / Rotate selected object | `H` `V` / `R` (`Shift+R` = CCW) |

---

## 📚 Documentation

*   [`AGENTS.md`](AGENTS.md) — architecture, conventions and workflows for contributors and coding agents
*   [`docs/FILE_FORMAT.md`](docs/FILE_FORMAT.md) — project JSON schema and versioning
*   [`docs/UX_AUDIT.md`](docs/UX_AUDIT.md) — UI/UX audit, what changed, open items
*   [`docs/ANIMATION.md`](docs/ANIMATION.md) — animation capabilities and roadmap
*   [`examples/sgdk/README.md`](examples/sgdk/README.md) — SGDK export and Mega Drive runtime

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
