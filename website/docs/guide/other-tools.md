# Work with other tools

Your sprites can leave the editor for other engines and tools, and art drawn elsewhere can come in. Exports draw with the preview mapping and palette swap chosen above the tabs.

## Sprite sheets for game engines

**File ▸ Export ▸ Sprite Sheet (JSON, Godot, Unity)...** draws every step of your animations the way the Animations tab shows it (with its offset, flips and turns) and packs the pictures into one PNG. Identical pictures are stored once. Next to the PNG goes the data file the engine reads.

<figure class="ms-shot ms-shot--part" markdown="span">
  [![The Export Sprite Sheet window: the format, which animations, also the frames no animation shows, padding and scale](../assets/images/screens/sheet-export.png){ width="462" height="334" loading="lazy" }](../assets/images/screens/sheet-export.png)
  <figcaption>Choose the format, the animations and the pixels; then where to save the PNG.</figcaption>
</figure>

- **JSON (Aseprite / TexturePacker layout)** describes every step as a frame: where it is on the sheet, where it sits on a canvas shared by all of them, how long it shows, and the editor's origin as its pivot. Every animation becomes a tag with its direction and repeats. Phaser, LÖVE, Defold, GameMaker and many other engines read this layout, and so does this editor's import.
- **Godot 4 SpriteFrames (.tres)** is a resource for an **AnimatedSprite2D**: one animation per animation, with its speed and each step's duration. Copy the PNG and the `.tres` together into the Godot project. Every texture has the size of the shared canvas, so the character stays in place; a note at the top of the file says which offset puts the editor's origin on the node.
- **Unity sprites (.png.meta)** are the import settings Unity reads next to the PNG: copy both into the project's Assets folder and Unity cuts the sheet into sprites, with point filtering for crisp pixels and each sprite's pivot on the editor's origin.

**Animations** exports all of them, the selected one or one [group](../start/tour.md#lists). **Also the frames no animation shows** adds those too. **Padding** keeps clear pixels between the pictures, so an engine never bleeds a neighbour in, and **Scale** makes every pixel larger.

## PNG sequences and GIFs

- **File ▸ Export ▸ Selected Animation as PNG Sequence...** writes one picture per step, or one per tick for a steady frame rate in video tools. All pictures share one canvas, so the origin stays put.
- **Export GIF...** in the [Animations](animations.md) inspector writes one cycle of an animation, and **Export GIF...** in the scene settings of the [Timeline](scenes.md) writes a scene, on its background colour. Both are in **File ▸ Export** too.

## Bring in art from Aseprite

**File ▸ Import ▸ Aseprite File...** opens an `.aseprite` or `.ase` file the way Aseprite exports it: the visible layers flattened with their opacity. The editor packs the frames into one PNG next to the file, named after it with `.sheet.png` (it never writes over a file that is there), and makes:

- a module for each distinct picture and a frame for each Aseprite frame,
- an animation for each **tag**, with its direction (forward, reverse, ping-pong) and repeats, and the durations as holds at the tick rate that fits them best.

The origin of each frame is the bottom centre of the Aseprite canvas, where a character's feet usually are. Then cut the pictures into parts the frames share: **Tools ▸ Auto Modularize Image...** finds them, see [Find shared parts automatically](auto-modularize.md).

**File ▸ Import ▸ Sprite Sheet with JSON...** opens a sheet that Aseprite or TexturePacker exported with its JSON (hash or array): the PNG stays as it is and its rectangles become the modules. A pivot in the JSON becomes the origin.

The import opens as a new project, so **Save** asks for a new file. Anything it leaves out, such as a layer blend mode it draws as Normal or a tilemap layer, is listed once the import is done.

## Other formats

**File ▸ Import** also opens AuroraGT `.sprite` files and RetroAnimator projects, and **File ▸ Export ▸ RetroAnimator Project (\*.json)...** writes one. The Mega Drive export is described in [For your programmer](../reference/programmers.md).
