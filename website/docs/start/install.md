# Get the editor

Modular Sprite Editor is free and open source. It runs on Windows, macOS and Linux.

## Download

Open the [latest release](https://github.com/leissler/modular-sprite-editor/releases/latest) and download the file for your computer:

| Your computer | Download |
| --- | --- |
| Windows 10 or 11 (64-bit) | `ModularSpriteEditor-windows.zip` |
| Mac with Apple silicon | `ModularSpriteEditor-macos.zip` |
| Linux (64-bit, for example Ubuntu 22.04 or newer) | `ModularSpriteEditor-linux.tar.gz` |

The `export_sgdk` and `export_snes` downloads are for programmers who build Mega Drive or SNES games: they export from the command line, for example in a game's build. You do not need them to make sprites, the editor exports for both consoles itself.

`ModularSpriteEditor-snes-demo.zip` holds a SNES ROM made from the Prince of Persia example: open `modular_sprite_snes_demo.sfc` in a SNES emulator such as [Mesen](https://www.mesen.ca/) to see the export running on the console. It starts on the *Swordfight*. See [SNES (PVSnesLib)](../reference/programmers.md#snes-pvsneslib).

## Start it

=== "Windows"

    Unpack the zip file into a folder of your choice and start `ModularSpriteEditor.exe`.

    The editor is not signed, so Windows may show "Windows protected your PC" the first time. Choose **More info**, then **Run anyway**.

=== "macOS"

    Unpack the zip file and move **ModularSpriteEditor** to your Applications folder.

    The app is not signed, so macOS refuses to open it with a double-click the first time. Right-click it, choose **Open**, then confirm with **Open**. If macOS still refuses, open **System Settings ▸ Privacy & Security** and choose **Open Anyway**. After the first time it opens normally.

=== "Linux"

    Unpack the archive and start `ModularSpriteEditor` in the unpacked folder. Your system needs glibc 2.35 or newer, which Ubuntu 22.04 and later have.

## Get the example projects

On the release page, download `ModularSpriteEditor-examples.zip` and unpack it. The examples are in its `examples` folder:

- `examples/sgdk/PoP_WW.json`: Prince of Persia, with the Swordfight scene
- `examples/sonic/sonic.json`: Sonic
- `examples/adventurer/adventurer.json`: a sheet of whole sprites

Open one with **File ▸ Open...** and keep the project file next to its image, where it already is. [The example projects](../examples/index.md) describes what to look at in each one.

## Updating

**Help ▸ About** shows which version you have, from 0.7 on. On a Mac, choose **About Modular Sprite Editor** in the first menu after the Apple menu. The [release notes](../reference/releases.md) list what each version brings.

Newer versions of the editor open projects made with older versions and upgrade them when you save. An older version opening a newer project shows a warning and can lose newer details when it saves, so keep everyone on a team on the same version.
