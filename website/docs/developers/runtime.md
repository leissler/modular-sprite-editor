# Use the runtime

The runtime is a small C library that draws the exported sprites. It is written for each console, in that console's SDK, with the same functions everywhere: a game draws, plays and re-skins its characters the same way on every console. This page shows how to use it; the [API reference](api.md) lists every function, and each console's page has the set-up and a complete program.

## Add it to your game

1. **Copy the runtime** of your console into your game's project: `src/modsprite.c`, its draw loops (`src/modsprite_draw.s` on the Mega Drive, `src/modsprite_draw.asm` on the SNES) and `inc/modsprite.h`, from the console's demo in the source code.
2. **Export** the artist's project into the same folder: in the editor **File ▸ Export ▸** *Console (SDK)*..., or from a build script with the console's exporter ([Export from your build](exporting.md)).
3. **Build** with the console's SDK.

The set-up of each console, what its export writes and a complete program are on its page: [Mega Drive (SGDK)](consoles/megadrive.md), [SNES (PVSnesLib)](consoles/snes.md).

## The frame loop

```c
ms_init();                          /* once: data, tiles, palettes (the console's page has its options) */

/* every video frame: */
ms_begin_frame();
ms_draw_anim_player(&hero, hero_x, hero_y);   /* draws, front to back */
ms_draw_anim_player(&guard, guard_x, guard_y);
ms_end_frame();                     /* the sprite list, ready for the vertical blank */
ms_anim_player_tick(&hero);         /* one video frame of playback */
ms_anim_player_tick(&guard);
/* then the console's vertical blank: SGDK's SYS_doVBlankProcess(), or PVSnesLib's WaitForVBlank()
   followed by ms_upload_tiles() and ms_palette_tick() */
```

Draw calls go between `ms_begin_frame()` and `ms_end_frame()`. The first thing drawn is in front: draw the player's character before the enemies behind it, and effects in front before both. `ms_palette_tick()` turns the colour cycles once per video frame.

## Draw what the artist made

Everything is numbered in the order of the editor's lists: module 0 is the first module in the Modules list, animation 3 the fourth animation. `MS_MODULE_COUNT`, `MS_FRAME_COUNT`, `MS_ANIMATION_COUNT` and `MS_SCENE_COUNT` say how many there are; `ms_find_animation_index_by_id("anim_...")` finds one by the id the project file gives it (look it up once, at start), and `ms_animation_name(index)` gives its name.

```c
ms_draw_module(module, x, y);   /* the module's pivot at (x, y) */
ms_draw_frame(frame, x, y);     /* the frame's origin at (x, y) */

MS_AnimPlayer guard;            /* animation playback, one per character */
ms_anim_player_init(&guard, walk);
ms_anim_player_tick(&guard);    /* once per video frame */
ms_draw_anim_player(&guard, x, y);

MS_ScenePlayer intro;           /* a Timeline scene as staged */
ms_scene_player_init(&intro, 0);
ms_scene_player_tick(&intro);   /* once per video frame */
ms_draw_scene_player(&intro, x, y);
```

A player plays its animation exactly as the editor's Animations tab does: loop from, repeat count, ping-pong, and the follow-up animation, which takes over when the animation ends (`guard.animation_index` changes; `guard.finished` is set only when there is no follow-up). `guard.step_started` is true on the video frame a new step starts.

A scene is drawn at its origin. Each demo draws it where the editor's Timeline screen outline puts the scene's origin on that console, so it shows as staged.

## Characters: mappings and palette swaps

The players keep no mapping: the mapping is chosen per draw, so one set of animations draws every character.

```c
ms_draw_anim_player(&hero, hero_x, hero_y);                          /* the active mapping */
ms_draw_anim_player_mapped(&guard, guard_mapping, guard_x, guard_y); /* another one, this draw only */
ms_draw_anim_player_as(&guard, guard_mapping, blue_swap, guard_x, guard_y); /* re-skinned and recoloured */

ms_set_mapping(guard_mapping);  /* or set it, like a pen colour, for everything drawn afterwards */
ms_set_palette_swap(blue_swap); /* 0: the palettes as they are */
```

Mapping 0 is no mapping, then the exported mappings in their order; look mappings up by id to be safe (`ms_find_mapping_index_by_id`). A palette swap costs no video memory; its colours must be in a palette line to show ([palettes](memory-and-limits.md#palettes)).

## Facing either way

```c
ms_draw_anim_player_flipped(&hero, hero_x, hero_y, 1);   /* bit 0 mirrors left to right, bit 1 top to bottom */
ms_draw_anim_player_as_flipped(&guard, guard_mapping, blue_swap, guard_x, guard_y, 1);  /* facing the hero */
ms_draw_frame_flipped(frame, x, y, 1);
ms_draw_module_flipped(module, x, y, 1);
```

A player is drawn mirrored as the Animations tab's **Mirror** preview shows the animation (H is 1, V 2, H + V 3): the step's offset, flips and turn are in its render frame and mirror with it, so a character that turns around needs each animation once. `_as_flipped` draws with another mapping and palette swap for that draw (another mapping alone: pass `ms_get_palette_swap()`). A frame is mirrored about its origin the same way: each hardware sprite moves to its mirror image and gets its flip bits, so the export stores it once for both directions. A module is mirrored in place, like a mirrored part in a frame: its pivot at (x, y), its picture where it was.

## Hitboxes, points and events

The hitboxes and points of what a player shows are relative to its draw position, already moved like the step (offset, flips, turn):

```c
const MS_Hitbox *boxes;
u16 count = ms_anim_player_hitboxes(&guard, &boxes);
const MS_Hitbox *hurt = ms_find_hitbox(boxes, count, MS_HITBOX_HURT, MS_ROLE_BODY);
if (hurt && overlaps(guard_x + hurt->x, guard_y + hurt->y, hurt->w, hurt->h))
    take_hit();

const MS_Point *points;
u16 n = ms_anim_player_points(&guard, &points);
const MS_Point *tip = ms_find_point(points, n, MS_POINT_WEAPON, MS_ROLE_BLADE_TIP);

if (ms_anim_player_event_started(&guard, MS_EVENT_FOOTSTEP))   /* the video frame the step starts */
    play_sound(ms_anim_player_event_value(&guard, MS_EVENT_FOOTSTEP, 0));
if (ms_anim_player_has_event(&guard, MS_EVENT_HIT))             /* every video frame it shows */
    check_hits();
```

`MS_HITBOX_*`, `MS_POINT_*`, `MS_ROLE_*` and `MS_EVENT_*` are generated from the project's lists into `modsprite_data.h`; `MS_NO_ROLE` finds a box or point of any role.

A step or frame drawn mirrored has its boxes and points as the functions above give them, unmirrored: `ms_flip_hitbox` and `ms_flip_point` mirror one with the draw's `flip` (a box's `x` becomes `-x - w`, a point's `-x - 1`) and pass `NULL` on, so they take what the find functions give:

```c
MS_Hitbox box;
const MS_Hitbox *blade = ms_flip_hitbox(ms_find_hitbox(boxes, count, MS_HITBOX_ATTACK, MS_ROLE_BLADE), facing, &box);
```

## Several characters in a streamed export

A streamed export keeps only what is on screen in video memory, in slots ([streaming](memory-and-limits.md#streamed-exports)). Everything drawn in the same video frame needs a slot of its own, or the slot cache:

```c
static MS_Slot guard_slot;
ms_slot_init(&guard_slot, first_free_tile);   /* after the default slot: the console's page says where */

ms_draw_anim_player(&hero, hero_x, hero_y);   /* through the default slot */
ms_set_slot(&guard_slot);
ms_draw_anim_player_mapped(&guard, guard_mapping, guard_x, guard_y);
ms_set_slot(NULL);                            /* the default slot again */

/* or one pool that every draw takes its slot from: */
ms_slot_cache_init(first_free_tile, tile_count);
```

In a resident export the slot functions do nothing, so the same game code works with every export mode.

## Your own sprites in the same table

The runtime fills the console's sprite table from its first entry. Add sprites of your own (a cursor, bullets, text) in the same frame with `ms_add_hw_sprite(x, y, ...)`; like draws, the first added is in front. Its other parameters are the console's sprite format (size, tile, attribute): see your console's page. It returns `FALSE` when the sprite did not fit under the sprite limit; sprites off the screen are skipped.

## Is it working?

- `ms_palettes_fit()`: every palette entry got a palette line.
- `ms_get_frame_profile(&profile)`: this frame's draw calls, parts, hardware sprites used and dropped, tiles uploaded, slots used, draws left out and draws that gave way.
- Each console's page names its own checks (on the Mega Drive `ms_data_is_ready()` and `ms_tiles_fit()`).

Each console's demo uses every function on this page and shows the profile on screen (START).
