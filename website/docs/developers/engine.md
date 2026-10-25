# Integrate with your engine

There are three ways to bring the editor's sprites into an engine: use the runtime as it is, write your own runtime on the exported data, or write your own exporter. This page covers what each takes; the details that depend on the console are on its page under [Consoles](consoles/index.md).

## Path 1: the runtime inside your engine

The runtime is written to live next to an engine: it draws sprites into the sprite table and stays out of everything else.

### What the runtime touches

On every console it uses three things, and nothing more:

- **The sprite table.** Between `ms_begin_frame()` and `ms_end_frame()` it fills the SDK's copy of the console's sprite table from its first entry; the SDK sends it in the vertical blank. Do not run another sprite engine on the same table at the same time.
- **Video memory** for its tiles: all of them once at start (resident exports), or the slots' uploads in the vertical blank (streamed exports).
- **Palette memory** for the palette lines it was given.

It leaves backgrounds, scrolling, interrupts, sound and input to your engine, and keeps its data in the cartridge. Each console's page lists exactly which SDK calls and registers it uses, and what an engine on another base must provide in their place ([Mega Drive](consoles/megadrive.md#what-the-runtime-touches), [SNES](consoles/snes.md#what-the-runtime-touches)).

### Sharing the sprite table

The runtime fills the table in draw order, the first draw in front. Add your engine's own sprites in the same frame with `ms_add_hw_sprite()`, before the draws that should be behind them, and lower `ms_set_sprite_limit()` to keep room for them. Some consoles also let your engine own the end of the table outright (the SNES's `ms_sprite_base()`); the console's page says how.

### Video memory and palettes next to your engine

Load your own graphics first and pass the first free place to `ms_init_ex()`: the runtime's tiles (resident) or its default slot (streamed) start there. Place further slots, or the slot cache, after `ms_tile_base() + ms_tiles_used()`. Leave the palette lines your backgrounds need, or manage the runtime's lines yourself with `ms_load_palette()`. Each console's page gives its layout.

### When to call what

```text
start:        your video set-up, then ms_init() / ms_init_ex()
every frame:  your game logic
              ms_begin_frame()
              draws: ms_draw_*(), ms_add_hw_sprite()
              ms_end_frame()
              ms_anim_player_tick() for each player
              the console's vertical blank, with ms_palette_tick() (and on the SNES ms_upload_tiles())
```

Your engine does not have to use the runtime's animation players. A game with timing of its own (the Prince of Persia port plays the original game's step lengths at 15 updates a second) draws frames with `ms_draw_frame_flipped` and keeps its own state; the hitboxes and points of a frame come from `ms_frame_hitboxes` and `ms_frame_points`.

### What it costs

Code, work RAM and drawing time differ per console and are measured on each console's page. On the Mega Drive, for example, the runtime takes about 11.7 KB of code and 0.8 KB of work RAM without the slot cache and give-way levels, and the demo's two-character *Swordfight* takes 30.7 of the 262 lines of a frame to draw. The slot cache and give-way levels are static tables you can compile out ([settings](api.md#compile-time-settings)).

## Path 2: your own runtime on the exported data

For an engine with a sprite system of its own: read the data the export writes and put its hardware sprites into your table. Each console's data page documents its records field by field, and how the runtime draws them ([Mega Drive data](consoles/megadrive-data.md), [SNES data](consoles/snes-data.md)). What holds on every console:

- **Render frames.** Every frame, animation step, scene sample and module becomes a render frame, once per mapping: the hardware sprites relative to the draw position, with the frame's hitboxes and points already moved like the picture, the sprite count and the box around the sprites. Modules, frames, animations and scenes are tables per mapping: the render frame of module `m` under mapping `k` is entry `k × module count + m`, likewise for the others. A module the mapping hides has an empty render frame.
- **Drawing order.** A render frame's sprites go into the table in the stored order, the first in front.
- **Palette entries.** Every palette, then each swap's version of the palettes it changes. Under palette swap `s`, a sprite of palette entry `e` (one of the editor's palettes) is drawn from the entry the swap table gives for `(s, e)`; an entry marked fixed (a scene object's own colours) keeps its own.
- **Animations.** A step's duration is already in video frames (the export converted it at 60 a second). Play the steps by the [playback rules](project-format.md#animation-playback): loop from, repeat count, ping-pong without repeating its end steps, backward, and the follow-up when an animation ends.
- **Scenes.** A scene's samples are render frames, one per tick of its frame rate: show sample `tick × fps / 60` (video frames since the start), modulo the sample count when the scene loops, else the last one once the scene is over.
- **Mirrored draws.** A frame mirrored about its origin moves each sprite to its mirror image (`x` becomes `-x - width`) and toggles its flip bit; mirror hitboxes the same way (`-x - w`) and points as pixels (`-x - 1`).

**Checking your runtime.** The editor's tests compile the real runtime for a PC and compare what it draws with the editor's own pictures, pixel for pixel. Compare your engine's sprite tables with that PC build, frame by frame, and you match the editor.

## Path 3: your own exporter

For an engine that wants its own data format, or a platform the editor does not export for yet.

**From the project file.** [The project file](project-format.md) documents every field and the rules for drawing, timing and palettes. The editor's own renderer, `compositor.py` in the source code, draws frames exactly as the editor shows them; compare your pictures with it (`render_frame`). The editor's sprite sheet export writes every animation step as a picture, a quick reference too.

**From the editor's bake.** In Python, `console_bake.ConsoleBake` does the console-independent half of an export: it walks the modules and frames (nested frames flattened into module parts with their flips and quarter turns, a part a hardware flip cannot show drawn into a picture of its own), the animation steps with the game's timing, events, loop-from steps, follow-ups and repeat counts, the scene samples with each object's mapping and palette swap, once per mapping, with the palette entries and the frames stored whole. Subclass it and implement one method:

```python
class MyEngineBake(ConsoleBake):
    def _store_part(self, image, palette, entry):
        """A part's picture (pixels as slot numbers of `palette`, drawn from palette entry `entry`):
        store it as your hardware draws it and return its number (the same for the same picture and entry)."""
```

After `bake()`, the render frames, parts, hitboxes, points, animation steps and records, and scene samples and records are lists on the object, ready to write in your format. Every console's exporter is built this way; [Adding a console](consoles/new.md) describes the whole of it.

**Exports that engines read as they are.** The editor also exports sprite sheets with JSON in the Aseprite and TexturePacker layout (every step a picture, with its hitboxes, points and events, and the animations as clips), Godot 4 scenes and Unity 6 prefabs: see [Work with other tools](../guide/other-tools.md).
