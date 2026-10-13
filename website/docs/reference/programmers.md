# For your programmer

This page is for the moment your sprites go into a game. Share it with your programmer, or send them straight to the technical documentation in the [source code repository](https://github.com/leissler/modular-sprite-editor).

## What to hand over

The project file (`.json`) and its images. The project stores image paths relative to itself, so keep them in the same folder structure and send the folder. Projects are plain text, which also makes them easy to keep in version control together with the game.

## Check the project first

**Tools ▸ Check Project** lists everything an export would leave out or show differently from the editor:

- **Errors** lose something: a step whose frame was deleted, a part whose module is gone, a missing image.
- **Warnings** look or behave differently: more colours than the console shows at once, half-transparent pixels, names that become the same name in the game's code.
- **Notes** are worth knowing but harmless, such as an empty animation.

<figure class="ms-shot ms-shot--part" markdown="span">
  [![Check Project after a few slips in the Prince of Persia example: two errors about a deleted module and a deleted frame, a warning about a hitbox without size and two notes, with Go to, Remove those parts and Fix All below](../assets/images/screens/check-project.png){ width="820" height="360" loading="lazy" }](../assets/images/screens/check-project.png)
  <figcaption>Each issue says what an export would do with it. The second button is the fix for the selected issue.</figcaption>
</figure>

Select an issue and choose **Go to** to see the item, or **Fix** where the editor knows a fix, for example removing the steps whose frame is gone. **Fix All** repairs everything it can at once, and **Undo** takes any fix back.

## Mega Drive (SGDK)

The Mega Drive is the first console with an exporter and a runtime. More consoles will follow.

`export_sgdk`, on the [release page](https://github.com/leissler/modular-sprite-editor/releases/latest) next to the editor, turns a project into data for a Mega Drive game made with [SGDK](https://github.com/Stephane-D/SGDK). The source code includes a small runtime that draws it.

- Everything is baked into one data file: tiles and palettes, frames, animations, scenes, hitboxes and points with their types and roles, step events, and every mapping.
- Each palette chosen in the Modules tab gets a palette line of its own: Palette 1 goes into the first line the game gives the runtime, Palette 2 into the next, and so on.
- Animations play on the console exactly as in the editor's preview, tick for tick, including loop-from steps, repeat counts and follow-up animations.
- The game chooses a mapping when it draws a character, so several characters can share one set of animations.
- Scenes play as they look on the Timeline, including objects with their own mapping.
- The numbers of the budget overlay are the exporter's own, so a pose that fits in the editor fits on the console.

**File ▸ Export ▸ Mega Drive (SGDK)...** writes the data into the game's SGDK project folder. Choose the folder and which mappings to include; the editor remembers both for the project. The game's own resources stay as they are: the export adds one line for its data file. The report afterwards shows what the game gets: how much of the console's video memory the sprites take, colours that had to be merged, and anything **Check Project** finds.

<figure class="ms-shot ms-shot--part" markdown="span">
  [![The Mega Drive export report for the Prince of Persia example: 68 animations with 1044 steps, 207 frames, one scene and three mappings, 309 tiles of video memory, and a note that 1115 of about 1424 tiles are left](../assets/images/screens/export-report.png){ width="760" height="260" loading="lazy" }](../assets/images/screens/export-report.png)
  <figcaption>The report after exporting the Prince of Persia example.</figcaption>
</figure>

The game's folder needs the runtime from the source code. The demo project in `examples/sgdk/sgdk_demo` has it and shows every module, frame, animation and scene with live profiling. `export_sgdk` does the same from the command line, for build scripts; `--strict` makes it fail when the project has errors:

```text
export_sgdk --project-json my_project.json --output-demo-dir path/to/sgdk_demo
```

The [SGDK guide in the repository](https://github.com/leissler/modular-sprite-editor/blob/main/examples/sgdk/README.md) covers the runtime, its functions and its limits.

## Other exports

- **File ▸ Export ▸ RetroAnimator Project (\*.json)...** writes a RetroAnimator project with a picture for every part, drawn with the preview mapping.
- **Export GIF...** in the **Animations** tab writes one cycle of an animation, for sharing and reviews.

## Importing

**File ▸ Import** opens AuroraGT `.sprite` files and RetroAnimator projects, so you can bring existing modular sprites into the editor.

## The project format

The project file format is documented in the repository's [`docs/FILE_FORMAT.md`](https://github.com/leissler/modular-sprite-editor/blob/main/docs/FILE_FORMAT.md). The editor upgrades older projects when it opens them.
