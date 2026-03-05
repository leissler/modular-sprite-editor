![Modular Sprite Editor](assets/banner_project.png)

# Modular Sprite Editor

**A specialized tool for assembling, animating, and mapping modular pixel-art sprites.**

Construct complex character animations from individual body parts (modules). Define pivots, assemble frames, create smooth animations, and map internal hitboxes/points for game logic—all in one streamlined interface.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg) ![Library](https://img.shields.io/badge/GUI-wxPython-orange.svg) ![Platform](https://img.shields.io/badge/Platform-Win%20%7C%20Mac-lightgrey.svg)

---

## ✨ Key Features

### 🛠️ Module Editor
*   **Sprite Sheet Slicing**: Import sprite sheets and define individual "Modules" (head, sword, arm).
*   **Pivot Definition**: Set precise rotation pivots for every module.
*   **Dynamic Split**: Visualize split rectangles for advanced game engine integration.

### 🖼️ Frame Editor
*   **Visual Assembly**: Drag and drop modules onto a canvas to build keyframes.
*   **Layering**: Reorder Z-index (draw order) of each part.
*   **Transformations**: Rotate, flip (X/Y), and offset components relative to their parent pivot.
*   **Collision & Points**: Define hitboxes ("Hurtbox", "Hitbox") and utility points ("Spawn", "WeaponTip") directly on the frame.
*   **Ghosting/Onion Skinning**: Compare against other frames.

### 🎬 Animation Editor
*   **Timeline**: Sequence your constructed frames into animations.
*   **Playback**: Real-time previews with Loop, Ping-Pong, and FPS controls.
*   **Global Mirroring**: Instantly preview how animations look flipped horizontally/vertically.
*   **GIF Export**: Export your creations directly to animated GIFs.

### 🎯 Mapping Editor
*   **Module Variants**: Create alternate versions of your sprite by remapping specific modules (e.g., swap "Clean Armor" for "Damaged Armor").
*   **Visual States**: Define complex state changes like Invisibility (hiding body parts) or Shadow Forms (swapping palettes/modules) without modifying the original frames.

---

## 🚀 Getting Started

### Prerequisites
*   Python 3.10 or higher
*   pip (Python Package Manager)

### Installation (Development)

1.  **Clone the repository**
    ```bash
    git clone https://github.com/yourusername/ModularSpriteEditor.git
    cd ModularSpriteEditor
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

4.  **Run the App**
    ```bash
    python app.py
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

---

## ⌨️ Controls

| Context | Action | Shortcut |
| :--- | :--- | :--- |
| **General** | Save Project | `Ctrl+S` (Cmd+S) |
| | Open Project | `Ctrl+O` (Cmd+O) |
| **Canvas** | Pan | `Middle Mouse Drag` / `Space + Drag` |
| | Zoom | `Mouse Wheel` |
| **Timeline** | Play/Pause | `Space` |
| | Previous/Next Frame | `Left Arrow` / `Right Arrow` |

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
