# Release notes

Downloads for every version are on the [releases page](https://github.com/leissler/modular-sprite-editor/releases).

## Next version (not released yet)

**Palettes, palette swaps and colour cycles.** A new **Palettes** tab holds the project's palettes with their colours in fixed slots, palette swaps that recolour them without touching an image, and colour cycles that make colours move. Choose a swap for the preview, per scene object or, in the game, per character: the guard of the *Swordfight* example now fights in blue. A swap costs no video memory on the console. See [Colours, palettes and swaps](../guide/palettes.md).

**Timing like the game.** The Animations tab plays every step for the video frames the game shows it, **View ▸ Play at 50 Hz** shows how a PAL console plays it, **Spread** gives selected steps a rhythm (1-1-2-2, slow start, slow end), and **Tools ▸ Change Animations...** sets one tick rate, playback, repeat count or group for many animations at once. See [Timing](../guide/animations.md#timing).

**Bigger scenes.** Scenes have a list with pictures, several layers can be selected and moved, flipped, deleted or copied together, layers paste into other scenes, and a layer can follow a point of its parent's frames, such as a sword in a hand. Scenes export as GIFs. See [Stage a scene](../guide/scenes.md).

**Work with other tools.** Export sprite sheets with JSON for engines that read Aseprite's layout, Godot 4 SpriteFrames or Unity sprites, and PNG sequences; import Aseprite files and sprite sheets with JSON, tags as animations. See [Work with other tools](../guide/other-tools.md).

**Long lists and your own settings.** Frames and animations can be put into groups and sorted by name, each project opens where you left it, and **Edit ▸ Preferences** gathers the settings that apply everywhere.

**Consoles.** The editor keeps what it knows about the Mega Drive, the SNES, the NES, the Game Boy Advance and the Game Boy in one place, the start for more consoles. See [Consoles](consoles.md).

Projects are saved in file format 7. Older projects are upgraded when you open them; version 0.8 cannot keep the new palettes, swaps, attachments and groups. For programmers: the Mega Drive data changed (blob version 5), so take the runtime from this version together with the new export.

## 0.8, October 2026

**Safer work.** Saving replaces the project file in one go and keeps the previous version next to it as `name.json.bak`. While you have unsaved changes, the editor keeps a recovery copy every 30 seconds and offers it after a crash. Undo covers everything in a project now, and sheets you change in another program reload when you come back to the editor. See [Undo, save and hints](../start/tour.md#undo-save-and-hints).

**Check Project.** **Tools ▸ Check Project** lists everything an export would leave out or show differently, such as steps whose frame was deleted, missing images or more colours than the console shows, with **Go to** and a fix for most. Deleting something that is still in use asks whether to remove its uses too. See [Check the project first](programmers.md#check-the-project-first).

**Mega Drive export in the editor.** **File ▸ Export ▸ Mega Drive (SGDK)...** writes the data into the game's folder and shows a report with the video memory the sprites need. See [Mega Drive (SGDK)](programmers.md#mega-drive-sgdk).

**Palettes.** Every image belongs to one of the Mega Drive's four palettes. The Modules inspector shows its colours the way the console shows them, and **View ▸ Mega Drive Colours** shows every canvas like that. See [Palettes](../guide/modules.md#palettes).

**More in the budget.** The budget overlay knows the Super Nintendo too, and for the Mega Drive it counts the video memory of what you see, of an animation and of the whole project. See [Video memory](../guide/hardware-budget.md#video-memory).

**Scenes play animations as animated.** An object on the Timeline plays its animation the way the Animations tab and the game do: Play once ends, and repeat counts, loop-from steps and follow-up animations work. Flips and visibility change exactly at a key. See [Scenes](../guide/scenes.md).

**Easier on a laptop and on the first start.** View bars wrap into a second row instead of hiding controls, inspector sections fold away, and the window opens where you left it. A welcome screen offers recent projects, the examples and this guide, and an empty tab says what to make first. **New animation** turns a row of whole sprites into an animation in one step. One selection rule everywhere: Shift+click adds, Cmd+click adds or removes, and a click on empty space places a point.

**Scroll to move around.** With **View ▸ Scroll Moves the View**, the mouse wheel and two fingers on a trackpad move the view, and a pinch or Cmd+scroll zooms. The Timeline's dopesheet and the Animations step sequence keep the height you drag them to. See [Moving around the canvas](../start/tour.md#moving-around-the-canvas).

**Sharp on Windows.** At 125 or 150 % display scaling the editor is no longer stretched: text is crisp and pixels stay square.

**Imports say what they leave out.** An AuroraGT or RetroAnimator file opens as a new project, so **Save** never writes over it, and the editor lists anything it could not bring over. The RetroAnimator export lists what that format has no place for, such as step events and scenes.

**Smaller things.** Parts, hitboxes and points move in whole pixels, a hitbox corner dragged past the opposite one turns the box around, mirrored points stay on their pixel, the grid thins out when you zoom far out, **Optimize Sprite Sheet** keeps every frame exactly as it was, and the guard's parts in the Prince of Persia example have proper names.

Projects are saved in file format 6. Older projects are upgraded when you open them. Version 0.7.1 opens format 6 projects with a warning, but plays objects that play as animated as a loop, exports all images with one merged palette, and forgets both when it saves.

For programmers: the Mega Drive data changed (blob version 4), so take the runtime (`modsprite.c` and `modsprite.h`) from this version together with the new export.

## 0.7.1, October 2026

**Smoother playback on slow computers.** Playing an animation or a scene no longer keeps a slow computer busy with drawing alone, especially on Windows, so the editor stays quick to respond while it plays. The sequence of a long animation also draws about ten times faster.

## 0.7, October 2026

**A user guide with pictures.** This site is new: how to install the editor, a first lesson that turns a sprite sheet into a running animation, and a page with pictures for every editor.

**A new icon**: an artist's wooden mannequin, drawn as pixel art.

**The About box shows the version**, so you can tell which one you have.

**Richer examples.** Every pose of the Prince of Persia example has hitboxes and points now, and its attacks and runs have events. The Adventurer example names its artist, Elthen. The examples are a small download of their own on the release page, `ModularSpriteEditor-examples.zip`.

**Long frame names** are shortened to fit in the Frames, Animations and Timeline libraries instead of running into the next frame.

Projects are still saved in file format 4, so 0.6 and 0.7 open each other's projects without losing anything.

## 0.6, October 2026

**A mapping per object in scenes.** Each object on the Timeline can have its own mapping, so a hero and an enemy made from the same animations appear in one scene. The Prince of Persia example has a new scene, the Swordfight.

**Easier choreography.** An animation swapped in at a key now plays from that key. Root motion follows an object's mirror, so a character facing left steps forward to the left. The screen guide shows the screen the way the Mega Drive demo shows scenes, and labels on the timeline no longer run into each other.

**Smoother on slow computers.** The checkerboard backdrop is drawn in one go instead of tile by tile, and playback no longer floods Windows with work when a frame takes long to draw.

**Animations** show the current step's events on the stage and light them up when they fire.

Projects are saved in file format 4. Older projects are upgraded when you open them. Version 0.5 can open format 4 projects, but drops the objects' mappings when it saves.

## 0.5, October 2026

**Auto Modularize, redesigned.** It cuts a sheet of whole sprites into the parts they share, also mirrored, and rebuilds every frame from them, pixel for pixel. A preview shows each sprite's parts and the Mega Drive memory and sprite cost before and after, and a slider trades fewer tiles against fewer hardware sprites.

**New example**: the Adventurer sheet, a set of whole sprites to try Auto Modularize on.

## 0.4, October 2026

**All editors redesigned**: Modules, Frames, Animations, Timeline and Mappings share one layout and one undo history, with drag and drop between them.

**Animations** play exactly like the Mega Drive runtime, with step events, loop-from steps, follow-up animations, onion skin and GIF export.

**Timeline** with layers, Auto-Key, easing, curved paths and image swaps per key.

**The budget overlay** shows hardware sprites, per-line limits and tiles as the Mega Drive exporter makes them.
