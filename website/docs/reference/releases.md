# Release notes

Downloads for every version are on the [releases page](https://github.com/leissler/modular-sprite-editor/releases).

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
