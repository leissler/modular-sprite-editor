# Your first animated sprite

In this lesson you take a sprite sheet, cut it into modules, make frames from them and turn eight of them into a running animation. At the end you export it as an animated GIF.

Use any sheet you like. The steps use Elthen's Adventurer sheet from the [example projects](../examples/index.md), `examples/adventurer/adventurer_sprite_sheet_v1.1.png`: a character drawn in 32 by 32 pixel cells, one animation per row, on a transparent background. Its second row is an eight-step run.

## 1. Start a project

Choose **File ▸ New Project**, then **File ▸ Save As...** and save the project in the same folder as your sprite sheet. The project remembers where its images are relative to the project file, so keep them together.

## 2. Add the sheet

Open the **Modules** tab. Under the **Images** list, choose **+ Add ▾ ▸ Image...** and pick your sheet. It appears on the canvas.

<figure class="ms-shot" markdown="span">
  [![The Modules tab with the Adventurer sheet on the canvas, not cut yet](../assets/images/screens/lesson-sheet.png){ width="1440" height="900" loading="lazy" }](../assets/images/screens/lesson-sheet.png)
  <figcaption>The Adventurer sheet in the <strong>Modules</strong> tab, before it is cut.</figcaption>
</figure>

If your sheet has a solid background colour instead of transparency, select the image, choose **Pick** next to **Key colour** in the inspector and click the background. That colour becomes transparent everywhere. The Adventurer sheet is already transparent, so skip this.

## 3. Cut it into modules

Choose **Slice ▾ ▸ Grid slice...** under the **Modules** list. Set **Tile size** to 32 by 32 and leave **Skip empty tiles** on, so empty cells do not become modules. The window counts the modules it will make. Choose **OK**.

<figure class="ms-shot ms-shot--part" markdown="span">
  [![The Grid Slice window: tile size 32 by 32, offset and gap 0, Skip empty tiles on, 68 tiles with 36 empty ones skipped](../assets/images/screens/lesson-grid.png){ width="383" height="286" loading="lazy" }](../assets/images/screens/lesson-grid.png)
  <figcaption>32 by 32 pixel tiles: 68 modules, and 36 empty cells skipped.</figcaption>
</figure>

Every sprite now has an outline: each one is a module. Click one to select it. The inspector shows its name, position, size and **Used by**, which counts the frames that use it.

<figure class="ms-shot" markdown="span">
  [![The sheet with an outline around every sprite, the first sprite of the second row selected, and its settings in the inspector](../assets/images/screens/lesson-sliced.png){ width="1440" height="900" loading="lazy" }](../assets/images/screens/lesson-sliced.png)
  <figcaption>Every sprite is a module now. The selected one is the first step of the run.</figcaption>
</figure>

!!! tip "Whole sprites or parts?"
    Here each module is a whole sprite, which is the quickest way to start. The editor is at its best when modules are parts, such as a head or an arm, that many frames share. [Build frames from parts](../guide/frames.md) shows how. If you have whole sprites and want parts, [Auto Modularize](../guide/auto-modularize.md) can find them for you.

## 4. Make frames

An animation is made of frames, so each sprite needs one. Choose **Tools ▸ Create Reference Frames From All Image Modules...**. It makes one frame per module, with the module placed on the frame's origin. Their names start with "Ref".

<figure class="ms-shot" markdown="span">
  [![The Frames tab with the new reference frames in the list and the first step of the run on the stage](../assets/images/screens/lesson-frames.png){ width="1440" height="900" loading="lazy" }](../assets/images/screens/lesson-frames.png)
  <figcaption>One reference frame for every module, in the <strong>Frames</strong> tab.</figcaption>
</figure>

For a single module, select it and choose **New frame** in the inspector instead.

## 5. Make the animation

Open the **Animations** tab and choose **+ New** under the animation list. Double-click its name and call it "run".

The **Frames** palette below the list shows your frames. Find the eight frames of the second row and double-click them in order: each double-click adds a step after the current one. You can also drag frames into the sequence at the bottom, exactly where they should go.

<figure class="ms-shot" markdown="span">
  [![The Animations tab with the animation run: its eight steps in the sequence at the bottom and the fourth step large on the stage](../assets/images/screens/lesson-animation.png){ width="1440" height="900" loading="lazy" }](../assets/images/screens/lesson-animation.png)
  <figcaption>The run with its eight steps in the sequence, the fourth step on the stage.</figcaption>
</figure>

If a step ends up in the wrong place, drag it along the sequence. ++delete++ removes the selected steps.

## 6. Set the timing

Timing is counted in ticks. In the inspector, **Tick rate** says how many ticks make a second. Set it to 12.

<figure class="ms-shot ms-shot--part" markdown="span">
  [![The animation settings in the inspector: name run, playback Loop, tick rate 12, one tick is 83 milliseconds](../assets/images/screens/lesson-timing.png){ width="311" height="279" loading="lazy" }](../assets/images/screens/lesson-timing.png)
  <figcaption><strong>Tick rate</strong> 12: one tick lasts 83 milliseconds.</figcaption>
</figure>

Each step holds for a number of ticks, shown by its width in the sequence. New steps hold for one tick, which gives this run twelve steps a second. To slow a step down, drag its right edge, or select it and press ++bracket-right++. ++bracket-left++ makes it shorter.

## 7. Play it

Press ++enter++ to play and again to stop. Use ++comma++ and ++period++ to step through it one pose at a time.

While it plays, try **Speed** ½× to look at the motion closely, and set **Onion** to **Previous** to see the step before as a faint red ghost. Onion skin is the quickest way to check that a run does not jump.

<figure class="ms-shot ms-shot--part" markdown="span">
  [![The run step on the stage with the step before it as a faint red ghost behind it](../assets/images/screens/lesson-onion.png){ width="385" height="361" loading="lazy" }](../assets/images/screens/lesson-onion.png)
  <figcaption><strong>Onion</strong> set to <strong>Previous</strong>: the step before shows as a faint ghost.</figcaption>
</figure>

## 8. Export a GIF

Choose **Export GIF...** in the inspector. The GIF shows one cycle of the animation exactly as the editor does, pixel for pixel. It is a good way to share the run with someone who does not have the editor.

<div class="ms-art" markdown="span">![The Adventurer running: the GIF the editor exports, four times larger](../assets/images/art/lesson-run.gif){ .ms-pixel width="128" height="128" loading="lazy" }</div>

Save your project with ++cmd+s++.

## Where to go next

You have a running character made of whole sprites. To build characters from parts, read [Build frames from parts](../guide/frames.md). To see how a finished project is put together, open the [Prince of Persia example](../examples/swordfight.md).
