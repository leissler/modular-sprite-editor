# Stay within the console's limits

A retro console does not draw your character as one picture. It shows it as **hardware sprites**: small rectangles made from 8 by 8 pixel **tiles** stored in video memory. There are limits on how many fit on the screen and on one line, and when a pose asks for too much, parts of it flicker or disappear. The budget overlay shows you this while you draw.

The editor knows the limits of the Sega Mega Drive and the Super Nintendo (SNES). More consoles will follow, each with its own entry in **Budget**.

<figure class="ms-shot" markdown="span">
  [![The Frames tab with the budget overlay: the slash pose outlined in yellow hardware sprites, with a readout of sprites, the busiest line and video memory](../assets/images/screens/budget.png)](../assets/images/screens/budget.png)
  <figcaption>The slash pose needs 16 hardware sprites and 35 tiles of video memory. Its busiest line uses 10 of the 20 sprites a line can show.</figcaption>
</figure>

## Turn it on

In the view bar of the **Frames**, **Animations** or **Timeline** tab, change **No budget** to a console mode:

- **MD H40** is the Mega Drive's wide mode, 320 pixels across, used by most games.
- **MD H32** is the narrower mode, 256 pixels across.
- **SNES 8/16** and **SNES 16/32** are the Super Nintendo. Its sprites are squares in two sizes, and a game picks one pair for all of them: 8 and 16 pixels, or 16 and 32.

On the Mega Drive, a hardware sprite is 8 to 32 pixels wide and high, in steps of 8. On the SNES, the editor covers each part with the large squares, and uses small ones where the part's pixels only fill an edge or a corner of a large square.

The editor remembers the choice for each tab.

## Read it

Every hardware sprite the pose needs is outlined. A part bigger than the largest hardware sprite is split into several. Lines where too many sprites meet are marked in red: on the console, sprites would drop out there.

<figure class="ms-shot ms-shot--part" markdown="span">
  [![The two fighters of the Swordfight at the clash, outlined in hardware sprites, with red bands across the lines where they have more sprites than one line can show](../assets/images/screens/budget-lines.png){ width="661" height="277" loading="lazy" }](../assets/images/screens/budget-lines.png)
  <figcaption>Both fighters at the clash in the narrower <strong>MD H32</strong> mode: the red bands are lines with more sprites than the console can show.</figcaption>
</figure>

The readout in the corner counts:

<figure class="ms-shot ms-shot--part" markdown="span">
  [![The budget readout: Mega Drive H40, 16 of 80 sprites, busiest line 10 of 20 sprites and 136 of 320 pixels, video memory 35 tiles here and 309 of about 1424 for the whole project](../assets/images/screens/budget-readout.png){ width="400" height="60" loading="lazy" }](../assets/images/screens/budget-readout.png)
  <figcaption>The readout for the slash pose.</figcaption>
</figure>

| | Mega Drive H40 | Mega Drive H32 | SNES |
| --- | --- | --- | --- |
| Hardware sprites on the screen | 80 | 64 | 128 |
| Hardware sprites on one line | 20 | 16 | 32 |
| Sprite pixels on one line | 320 | 256 | 272 |

These limits are for everything on screen together, not for one character. Leave room for enemies, effects and the player's shots.

In the **Animations** tab, the inspector names the animation's worst step. In the **Timeline** tab, the readout counts everything in the scene at the playhead.

## Video memory

Every tile a sprite shows is stored in the console's video memory, which the sprites share with the backgrounds. On the Mega Drive, the last line of the readout counts the tiles of what you see and of the whole project, against the about 1424 tiles a game made with SGDK has free:

- The same part used twice, or flipped, needs its tiles only once: the console flips sprites for free.
- A part turned by 90° needs tiles of its own, because the console cannot turn sprites. So does every turned position of an object that rotates in a scene.
- Parts with the same pixels share their tiles, even when they come from different modules.

In the **Animations** tab, the inspector also counts the tiles of all the animation's steps together.

<figure class="ms-shot ms-shot--part" markdown="span">
  [![Budget in the Animations tab's inspector: worst step 8 with 16 sprites, busiest line 11 of 20 sprites and 144 of 320 pixels, video memory 88 tiles for the animation](../assets/images/screens/budget-animation.png){ width="311" height="64" loading="lazy" }](../assets/images/screens/budget-animation.png)
  <figcaption><strong>Budget</strong> in the inspector of the <strong>Animations</strong> tab, for a whole attack.</figcaption>
</figure>

**Tools ▸ Check Project** warns when the project needs more than three quarters of the free tiles, and reports an error when they do not fit: the game could not load the sprites. The SNES has no exporter yet, so its readout counts sprites only.

## Tips for artists

- **Fewer, bigger parts** use fewer hardware sprites. **More, smaller shared parts** use less memory. [Auto Modularize](auto-modularize.md) finds a balance with one slider.
- On the Mega Drive, a part 33 pixels wide becomes two sprites. Trimming one column can halve its cost.
- Wide poses are expensive on a single line: a sword swing stretched across the screen can use many sprites on the same lines.
- Reuse parts flipped instead of drawing mirrored copies. The console flips hardware sprites for free, so they share tiles.
- A part turned by 90° costs its tiles a second time. Turned by 180° it is only flipped both ways, which is free.
- The Mega Drive numbers follow its exporter exactly, so they are what the game will use.
