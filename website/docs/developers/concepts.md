# How the data works

The editor's data model is small: pictures (modules), poses built from them (frames), and timing and staging on top (animations, scenes). Re-skins (mappings) and recolours (palette swaps) are applied when something is drawn, not stored as copies. This page explains each piece, then what a console export makes of it.

## Modules

A **module** is a rectangle of a sprite sheet with a **pivot**: the point that lands where the module is placed, given relative to the rectangle's top left. Modules are the smallest pictures the editor reuses; a sheet's transparent colour (or its alpha) marks what is not drawn. A module can also be a simple vector shape (rectangle, arc, triangle, line), which the exports rasterise like an image.

On the console a module's picture becomes tiles and hardware sprites. Its tiles are stored once, however many frames use it.

## Frames

A **frame** is a pose: a list of **parts**. A part places a module, or another frame (a nested frame), with:

- **position**: where its pivot lands, in the frame's coordinates. x grows to the right, y downward, in whole pixels; (0, 0) is the frame's origin, the point a game draws the frame at.
- **flip_x / flip_y**: a module is mirrored in place, its picture staying where it is whatever its pivot; a nested frame is mirrored about its position.
- **rotation** in steps of 90°, about the pivot (a nested frame: about its position).

Parts are listed back to front: the last part is drawn on top.

A frame also carries **hitboxes** (rectangles, each with a type and a role) and **points** (single pixels with a type and a role: a hand, the feet, a blade's tip) for the game's logic. And it can be marked **Store whole**: the console exports then keep it as one flattened picture per palette instead of its parts ([below](#what-an-export-makes-of-it)).

## Animations

An **animation** is a list of **steps**. A step shows a frame for a **hold** of some ticks, with an **offset** (root motion), flips, a turn by 90° steps, and **events**. `fps` is ticks per second.

- **Playback**: forward (play once), backward (looping backwards), loop, ping-pong. `loop_count` ends the repeating modes after that many passes (0: never).
- **Loop from** (`loop_start`): in loop playback, the first pass plays every step and later passes start at this step, so an intro plays once.
- **Follow-up** (`next_animation`): when an animation ends, this one takes over.
- **Events** fire on the tick their step starts and stay active while it shows. Each has a type from the project's list and a free number (which sound, which effect).

The console runtimes count video frames, not ticks: the exports turn each hold into `round(hold × 60 / fps)` video frames, at least one, so tick rates that divide 60 play exactly. The exact playback rules are in [the project file](project-format.md#animation-playback).

## Scenes

A **scene** (the Timeline) stages objects (modules, frames, animations) over time: keys for position, 90° turns, flips and visibility, easing, curved paths, parents, a mapping and a palette swap per object, objects that follow a point of their parent's frames. The console exports bake a scene into one picture per tick of its frame rate (a **sample**): a game plays a scene back as it was staged, it does not move the objects one by one.

## Mappings

A **mapping** replaces modules by other modules, or hides them, for everything drawn with it: costumes, damage states, a guard drawn from the hero's animations with other clothes and another sword. A game chooses the mapping per draw, the way AuroraGT games set a sprite's mapping before drawing each character, so one set of animations serves every character. The exports bake each mapping's pictures; mapping 0 is no mapping.

## Palettes, swaps and colour cycles

A **palette** holds colours in fixed slots (slot 0 is transparent); every sheet belongs to one palette, and its pixels are stored as slot numbers. A **palette swap** replaces colours per palette and slot without new pictures: on the console a swap is another set of colours for the same tiles, so it costs no video memory. **Colour cycles** rotate a run of slots every few video frames (water, lava, a glowing sword).

The exports store **palette entries**: every palette, then each swap's version of the palettes it changes. A hardware sprite names its entry, and the runtime turns entries into the console's palette lines at draw time. How many lines a console has, and whether the backgrounds share them, is on its page.

## Types, roles and their numbers

Hitbox types, point types and event types are lists in the project; the exports number them in list order (`MS_HITBOX_HURT` is 0 when *Hurt* is the first hitbox type). Roles are free names (`head`, `blade_tip`); the exports sort them alphabetically (`MS_ROLE_BLADE`, `MS_ROLE_HEAD`). `MS_NO_ROLE` is a box or point without a role, `MS_UNKNOWN_TYPE` one whose type was deleted.

Modules, frames, animations, scenes, mappings and palette swaps are numbered in the order of their lists in the editor: frame 0 is the first frame in the Frames list. The runtime finds them by the editor's ids too (`ms_find_frame_index_by_id`).

## What an export makes of it

- **Render frames.** Every frame, every animation step (its frame with the step's offset, flips and turn applied), every scene sample and every module becomes a render frame, once per mapping: the hardware sprites relative to the draw position, with the frame's hitboxes and points already moved like the picture, the sprite count and the box around the sprites. The runtime draws render frames; animations and scenes are tables of render frame numbers. Identical render frames are stored once.
- **Hardware sprites and tiles.** Each module picture is cut into the console's hardware sprites, as few as its sprite sizes allow (on the Mega Drive rectangles up to 32×32 pixels at any pixel, on the SNES squares of the game's two sizes; each console's page says how). Tiles with the same pixels are stored once. A flipped part shares its tiles through the hardware's flip bits; a part turned by 90° is a picture of its own.
- **Parts or whole frames.** By default a render frame is its parts, so frames that share modules share tiles. A frame marked Store whole is one picture per palette, cut into the fewest hardware sprites: fewer sprites on screen for tiles of its own.
- **Where the tiles live.** Resident (the default): every tile sits in video memory. Streamed: video memory holds a slot per thing drawn at the same time, and a frame's tiles are copied in when it is drawn. The [export modes](memory-and-limits.md#three-ways-to-store-the-sprites) combine both choices.

## The editor's transform rules

Every export, the runtimes and the editor's own pictures follow these rules, and an engine that draws from the project file must follow them too to match the editor pixel for pixel:

- A **module part's flip** mirrors the module's picture in place: its bounds do not move.
- A **module part's rotation** turns it about its pivot, in 90° steps (exact: no rounding).
- A **nested frame part, an animation step and a scene object** are transformed about their anchor (the position, the frame's origin): flip first, then turn. A mirrored parent (an odd number of flips) reverses the direction of its children's turns.
- **Points mark pixels**: a transform moves the pixel's centre, so mirroring maps `x` to `-x - 1` and a clockwise quarter turn maps `(x, y)` to `(-y - 1, x)`. **Hitboxes are areas**: their corners transform as they are.
