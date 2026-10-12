Modular Sprite Editor @VERSION@ - Windows kit
=============================================

The editor, two example projects and an SGDK demo that runs them on a Mega Drive.
Unzip this folder to a path without spaces (for example C:\ModularSpriteEditor): SGDK's make
does not handle spaces in paths.


1. Try the editor
-----------------

- Start ModularSpriteEditor.exe. Windows may warn about an unknown publisher (the exe is not
  signed): click "More info", then "Run anyway".
- File > Open:
    examples\sgdk\PoP_WW.json    Prince of Persia: 165 modules, 207 frames, 68 animations,
                                 a timeline scene and 2 mappings (re-skins)
    examples\sonic\sonic.json    Sonic: 65 modules, 38 frames, 171 animations, hitboxes
    examples\adventurer\adventurer.json
                                 Adventurer: 15 frames, each one whole sprite
- Tabs: Modules (cut the sprite sheet), Frames (assemble parts, hitboxes, points),
  Animations, Timeline (scenes), Mappings. Help > Keyboard & Mouse Shortcuts lists the controls.
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

Demo controls (3- or 6-button pad):
  UP / DOWN        unit: Module, Frame, Animation, Scene
  LEFT / RIGHT     previous / next entry      X / Y   -10 / +10
  A                pause / resume             B       restart
  START            next mapping (re-skin)
  START + A        show hitboxes and points
  START + UP/DOWN  background brightness
  C                jump to an id              MODE / Z   minimal HUD (FPS / CPU only)
The HUD shows the time spent drawing, hardware sprites per frame and the CPU load.


3. More
-------

examples\sgdk\README.md    how the export and the Mega Drive runtime work, the C API for your own
                           game (animation player, events, hitboxes, points), limits, performance
export_sgdk.exe --help     exporter options (for example --mapping to export a single mapping)

Source code and issues: https://github.com/leissler/modular-sprite-editor
