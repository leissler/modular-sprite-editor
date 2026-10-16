Modular Sprite Editor @VERSION@ - SNES demo
===========================================

modular_sprite_snes_demo.sfc is a SNES ROM made with the editor's SNES export from the Prince of
Persia example. Open it in a SNES emulator, for example Mesen (https://www.mesen.ca/), bsnes or
ares. It starts on the Swordfight scene: the Prince against a guard drawn from the same
animations with another set of parts and other colours.

Controls (pad 1):
  UP / DOWN        what to show: scenes, animations, frames, modules
  LEFT / RIGHT     previous / next (hold to run through them)
  A                play / pause
  B                hitboxes and points
  X                change the look: mappings and palette swaps, then side by side
  START            the controls, frame rate, CPU load, sprites and tiles

examples/snes/snes_demo is the ROM's PVSnesLib project: the runtime, the demo and the exported
data. To build it again, or with your own project:

1. Export from the editor: File > Export > SNES (PVSnesLib)..., choose the folder
   examples/snes/snes_demo and the sprite sizes (the list shows the tiles each pair needs).
2. Put PVSnesLib 4.x (https://github.com/alekmaul/pvsneslib, tested with 4.6.0) into
   examples/snes/snes_demo/third_party/pvsneslib, or set PVSNESLIB_HOME.
3. Build, in examples/snes/snes_demo:
     macOS, Linux:  make
     Windows:       powershell -NoProfile -ExecutionPolicy Bypass -File build_windows.ps1
                    (no make or MSYS2 needed)

examples/snes/README.md explains the export, the runtime's C API for your own game (the Mega
Drive runtime's: animation players, mappings and palette swaps per draw, hitboxes, points and
events) and its limits.

The user guide: https://modularsprites.bionic-productions.com/
Source code: https://github.com/leissler/modular-sprite-editor

The sprite art belongs to its owners, is not covered by the editor's license and is included only
to show the editor's export. Prince of Persia is a trademark of Ubisoft Entertainment. Credits:
  https://modularsprites.bionic-productions.com/reference/credits/
