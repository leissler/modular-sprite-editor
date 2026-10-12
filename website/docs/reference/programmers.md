# For your programmer

This page is for the moment your sprites go into a game. Share it with your programmer, or send them straight to the technical documentation in the [source code repository](https://github.com/leissler/modular-sprite-editor).

## What to hand over

The project file (`.json`) and its images. The project stores image paths relative to itself, so keep them in the same folder structure and send the folder. Projects are plain text, which also makes them easy to keep in version control together with the game.

## Mega Drive (SGDK)

The Mega Drive is the first console with an exporter and a runtime. More consoles will follow.

`export_sgdk`, on the [release page](https://github.com/leissler/modular-sprite-editor/releases/latest) next to the editor, turns a project into data for a Mega Drive game made with [SGDK](https://github.com/Stephane-D/SGDK). The source code includes a small runtime that draws it.

- Everything is baked into one data file: tiles and palette, frames, animations, scenes, hitboxes and points with their types and roles, step events, and every mapping.
- Animations play on the console exactly as in the editor's preview, tick for tick, including loop-from steps, repeat counts and follow-up animations.
- The game chooses a mapping when it draws a character, so several characters can share one set of animations.
- Scenes play as they look on the Timeline, including objects with their own mapping.
- The numbers of the budget overlay are the exporter's own, so a pose that fits in the editor fits on the console.

The exporter writes into the demo project in `examples/sgdk/sgdk_demo`, which shows every module, frame, animation and scene with live profiling:

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
