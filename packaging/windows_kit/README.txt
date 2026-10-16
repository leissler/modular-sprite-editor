Modular Sprite Editor @VERSION@ - Windows kit
=============================================

The editor, three example projects, and demos that run them on a Mega Drive (SGDK) and a SNES
(PVSnesLib).
The user guide, with pictures of every editor: https://modularsprites.bionic-productions.com/

Unzip this folder to a path without spaces (for example C:\ModularSpriteEditor): SGDK's make
does not handle spaces in paths.


1. Try the editor
-----------------

- Start ModularSpriteEditor.exe. Windows may warn about an unknown publisher (the exe is not
  signed): click "More info", then "Run anyway".
- File > Open:
    examples\sgdk\PoP_WW.json    Prince of Persia: 165 modules, 207 frames, 68 animations,
                                 a timeline scene, 2 mappings (re-skins), hitboxes, points
                                 and events
    examples\sonic\sonic.json    Sonic: 65 modules, 38 frames, 171 animations, hitboxes
    examples\adventurer\adventurer.json
                                 Adventurer: 15 frames, each one whole sprite
- Tabs: Modules (cut the sprite sheet), Frames (assemble parts, hitboxes, points),
  Animations, Timeline (scenes), Mappings (re-skins), Palettes (colours, palette swaps).
  Help > Keyboard & Mouse Shortcuts lists the controls.
- Tools > Auto Modularize Image cuts whole sprites into hardware-sized parts they share, with a
  preview of the Mega Drive cost (try it on the Adventurer sheet in the Modules tab).


2. Run it on a Mega Drive (SGDK)
--------------------------------

Needs a Java runtime (SGDK's resource compiler is written in Java; any current version) and a
Mega Drive emulator, e.g. BlastEm (https://www.retrodev.com/blastem/). SGDK itself is included
(examples\sgdk\sgdk_demo\third_party\sgdk).

- build_sgdk_demo.bat builds the demo ROM from the data already exported from PoP_WW.json:
      examples\sgdk\sgdk_demo\out\debug\rom.bin
  Open it in the emulator.
- export_to_sgdk.bat exports a project into the demo and builds the ROM. Drag a project .json onto
  it, or run for example
      export_to_sgdk.bat examples\sonic\sonic.json
  Without a project it exports examples\sgdk\PoP_WW.json. Save your edits in the editor first.
- Or export from the editor: File > Export > Mega Drive (SGDK)..., choose the folder
  examples\sgdk\sgdk_demo, then run build_sgdk_demo.bat. The editor shows what the game gets
  (video memory, colours, anything Tools > Check Project finds).

The demo starts on the Swordfight scene. Demo controls (any pad):
  UP / DOWN        what to show: scenes, animations, frames, modules
  LEFT / RIGHT     previous / next (hold to run through them)
  A                play / pause
  B                hitboxes and points
  C                change the look: mappings and palette swaps, then side by side
  START            the controls, frame rate, CPU load, sprites and tiles


3. Run it on a SNES (PVSnesLib)
-------------------------------

Needs a SNES emulator, e.g. Mesen (https://www.mesen.ca/). PVSnesLib's Windows tools are included
(examples\snes\snes_demo\third_party\pvsneslib); no Java, make or MSYS2 needed, and this part
works from a path with spaces too.

- build_snes_demo.bat builds the demo ROM from the data already exported from PoP_WW.json:
      examples\snes\snes_demo\modular_sprite_snes_demo.sfc
  Open it in the emulator.
- export_to_snes.bat exports a project into the demo and builds the ROM. Drag a project .json onto
  it, or run for example
      export_to_snes.bat examples\adventurer\adventurer.json
  Without a project it exports examples\sgdk\PoP_WW.json. Save your edits in the editor first.
  All of a project's sprite tiles stay in the SNES's video memory, 512 at most: Sonic needs 600,
  so its export stops and says so.
- Or export from the editor: File > Export > SNES (PVSnesLib)..., choose the folder
  examples\snes\snes_demo and the sprite sizes (the list shows the tiles each pair needs), then
  run build_snes_demo.bat.

The demo starts on the Swordfight scene. Demo controls (pad 1):
  UP / DOWN        what to show: scenes, animations, frames, modules
  LEFT / RIGHT     previous / next (hold to run through them)
  A                play / pause
  B                hitboxes and points
  X                change the look: mappings and palette swaps, then side by side
  START            the controls, frame rate, CPU load, sprites and tiles


4. More
-------

The user guide, every editor explained with pictures:
    https://modularsprites.bionic-productions.com/
What to hand to a programmer, and how the Mega Drive export works:
    https://modularsprites.bionic-productions.com/reference/programmers/

examples\sgdk\README.md    how the export and the Mega Drive runtime work, the C API for your own
                           game (animation player, events, hitboxes, points), limits, performance
examples\snes\README.md    the same for the SNES: the export, the runtime (the same C API) and its
                           limits; examples\snes\snes_demo\build_windows.ps1 builds it on Windows
export_sgdk.exe --help     exporter options (for example --mapping to export a single mapping)
export_snes.exe --help     the same for the SNES (--setup picks other sprite sizes, e.g. snes_8_32)

Source code and issues: https://github.com/leissler/modular-sprite-editor
