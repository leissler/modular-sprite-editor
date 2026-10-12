# The example projects

Three example projects come with the editor's source code. Download **Source code (zip)** from the [latest release](https://github.com/leissler/modular-sprite-editor/releases/latest), unpack it and open a project with **File ▸ Open...**. Keep each project next to its image.

The sprite art in the examples belongs to its owners and is included only to show and test the editor. See [Credits](../reference/credits.md).

## Prince of Persia

`examples/sgdk/PoP_WW.json` is the most complete example: the Prince from a mobile Prince of Persia game, cut into 165 small parts on one sheet, with 207 poses, 68 animations, two mappings and a scene.

<div class="ms-art" markdown="span">![The Prince slashes while the hooded guard blocks with sparks](../assets/images/art/step-scene.png){ .ms-pixel width="408" height="216" }</div>

Things to look at:

- **Modules**: the parts are tiny, often just a forearm or a boot, and **Used by** shows that many are used in more than 50 frames.
- **Frames**: turn on **Part bounds** to see how many parts a pose has, and **Budget** to see what it costs on a Mega Drive.
- **Animations**: play **C34 Attack**, **C06 slash** or **A05 run**. Turn on **Path** to see how a run moves forward.
- **Mappings**: **Normal** turns the Prince into a hooded guard. **Invizibil** swaps 89 body parts for an empty module, so only his swords remain visible. Try both with **Preview mapping** at the top of the window.
- **Timeline**: the **Swordfight** scene, explained in [Inside the Swordfight](swordfight.md).

## Sonic

`examples/sonic/sonic.json` is a hand-cut Sonic with 65 modules, 38 frames and 171 animations. Open the **Animations** tab and play through them: it is a good example of how many animations a small set of poses can drive, with holds, offsets and flips doing the rest.

The [Auto Modularize guide](../guide/auto-modularize.md) shows the same Sonic poses as whole sprites, cut into shared parts automatically.

## Adventurer

`examples/adventurer/adventurer.json` is a sheet of whole sprites in 32 by 32 pixel cells, sliced into 68 modules with 15 frames. It has no animations yet, which makes it a good sheet to practise on:

- follow [Your first animated sprite](../start/first-sprite.md) to animate its run;
- run [Auto Modularize](../guide/auto-modularize.md) on it and compare the memory before and after.
