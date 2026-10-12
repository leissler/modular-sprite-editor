# Stay within the console's limits

A Mega Drive does not draw your character as one picture. It shows it as **hardware sprites**: rectangles of up to 32 by 32 pixels, made from 8 by 8 pixel **tiles** stored in video memory. There are limits on how many fit, and when a pose asks for too much, parts of it flicker or disappear. The budget overlay shows you this while you draw.

<figure class="ms-shot" markdown="span">
  [![The Frames tab with the budget overlay: the slash pose outlined in yellow hardware sprites, with a readout of sprites, tiles and the busiest line](../assets/images/screens/budget.png)](../assets/images/screens/budget.png)
  <figcaption>The slash pose needs 16 hardware sprites and 41 tiles. Its busiest line uses 10 of the 20 sprites a line can show.</figcaption>
</figure>

## Turn it on

Choose **Budget** in the view bar of the **Frames**, **Animations** or **Timeline** tab:

- **MD H40** is the Mega Drive's wide mode, 320 pixels across, used by most games.
- **MD H32** is the narrower mode, 256 pixels across.

The editor remembers the choice for each tab.

## Read it

Every hardware sprite the pose needs is outlined. A part bigger than 32 by 32 pixels is split into several. Lines where too many sprites meet are marked in red: on the console, sprites would drop out there.

The readout in the corner counts:

| | Mega Drive H40 | Mega Drive H32 |
| --- | --- | --- |
| Hardware sprites on the screen | 80 | 64 |
| Hardware sprites on one line | 20 | 16 |
| Sprite pixels on one line | 320 | 256 |

It also counts the **tiles** the pose uses. Tiles are video memory, shared with the backgrounds and everything else on screen. The same tile used twice, or a part flipped, costs nothing extra.

These limits are for everything on screen together, not for one character. Leave room for enemies, effects and the player's shots.

In the **Animations** tab, the inspector names the animation's worst step. In the **Timeline** tab, the readout counts everything in the scene at the playhead.

## Tips for artists

- **Fewer, bigger parts** use fewer hardware sprites. **More, smaller shared parts** use less memory. [Auto Modularize](auto-modularize.md) finds a balance with one slider.
- A part 33 pixels wide becomes two sprites. Trimming one column can halve its cost.
- Wide poses are expensive on a single line: a sword swing stretched across the screen can use many sprites on the same lines.
- Reuse parts flipped instead of drawing mirrored copies. The console flips hardware sprites for free, so they share tiles.
- The numbers follow the Mega Drive exporter exactly, so they are what the game will use.
