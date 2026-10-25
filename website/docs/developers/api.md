# Runtime API reference

The runtime's functions are declared in `inc/modsprite.h`; the export's `inc/modsprite_data.h` adds the record types, the counts and the constants generated from the project. `u8`, `u16`, `s16` and `u32` are the console SDK's types. Every function on this page exists on every console with the same meaning; where a parameter follows the console's hardware, a table gives each console's form, and the functions only some consoles have are listed [at the end](#console-specific-functions). Out-of-range indices are ignored: a draw draws nothing, a query returns 0 or an empty string.

## Start-up

```c
void ms_init(void);
void ms_init_ex(...);
```

Prepares the data and the console. In a resident export it loads every tile into video memory and the palette entries into consecutive palette lines; in a streamed export it loads no tiles and makes the default slot at the same place. `ms_init_ex` says where the runtime's tiles and palettes go:

| Console | `ms_init_ex` | `ms_init()` means |
|---|---|---|
| [Mega Drive](consoles/megadrive.md) | `(u16 tile_index, u16 palette)`: the first tile and the first palette line | `TILE_USER_INDEX`, `PAL1` |
| [SNES](consoles/snes.md) | `(u16 vram_address, u16 first_palette)`: the sprite tables' VRAM word address (OBSEL's steps) and the first sprite palette; call it in forced blank | 0x0000, palette 0 |

`ms_begin_frame()` calls `ms_init()` if nothing has.

```c
u8 ms_palettes_fit(void);
u16 ms_tile_base(void);
u16 ms_tiles_used(void);
```

`ms_palettes_fit` is `FALSE` when not every palette entry got a line; load the ones a screen needs with `ms_load_palette`. `ms_tile_base` and `ms_tiles_used` give the runtime's place in video memory: every tile, or in a streamed export the default slot's.

```c
void ms_set_sprite_limit(u16 limit);
```

The most hardware sprites the runtime writes in a frame: by default the console's sprites per screen. Lower it to leave room for sprites of your own.

## A frame of drawing

```c
void ms_begin_frame(void);
void ms_end_frame(void);
```

Every draw goes between the two, once per video frame. `ms_begin_frame` starts an empty sprite list and resets the profile. `ms_end_frame` finishes the list (resolving [give-way levels](#give-way-levels)) and leaves it for the console's vertical blank to send: SGDK's DMA queue on the Mega Drive, PVSnesLib's OAM buffer on the SNES.

```c
u8 ms_add_hw_sprite(s16 x, s16 y, ...);
```

A sprite of your own in this frame's list, at screen position (x, y), in front of what is drawn after it. Returns `FALSE` when the sprite did not fit under the limit; a sprite off the screen is skipped (`TRUE`). Its other parameters are the console's sprite format:

| Console | Parameters after `x, y` |
|---|---|
| Mega Drive | `u8 size, u16 attribute`: `SPRITE_SIZE(w, h)` in tiles, `TILE_ATTR_FULL(palette, priority, vflip, hflip, tile)` |
| SNES | `u16 tile, u8 attribute, u8 large`: a 9-bit tile, the OAM attribute byte without the tile's bit 8, the large size or not |

```c
void ms_get_frame_profile(MS_FrameProfile *out_profile);
```

What this frame cost so far:

| Field | |
|---|---|
| `render_calls` | draws of render frames |
| `parts_submitted` | parts drawn |
| `hw_sprites` | hardware sprites in the table |
| `sprites_dropped` | sprites that did not fit under the limit (the ones drawn last) |
| `tiles_uploaded` | tiles queued for the vertical blank (streamed exports) |
| `slots_used` | the slot cache's slots drawn this frame |
| `draws_left_out` | draws the slot cache had no room for, or the give-way queue |
| `draws_given_way` | draws left out to make room ([give-way levels](#give-way-levels)) |

A console may add fields of its own (the SNES's `uploads_waiting`); read the fields by name, not by position.

## Drawing

```c
void ms_draw_module(u16 module_index, s16 x, s16 y);
void ms_draw_frame(u16 frame_index, s16 x, s16 y);
void ms_draw_module_flipped(u16 module_index, s16 x, s16 y, u8 flip);
void ms_draw_frame_flipped(u16 frame_index, s16 x, s16 y, u8 flip);
```

Draws a module with its pivot at (x, y), or a frame with its origin at (x, y), under the active mapping and palette swap. `flip`: bit 0 mirrors left to right, bit 1 top to bottom, other bits are ignored; 0 draws as it is. A frame is mirrored about its origin, like a mirrored animation step (each hardware sprite moves to its mirror image and gets its flip bits); a module is mirrored in place, like a mirrored part in a frame (its pivot stays at (x, y), its picture where it was).

A render frame that lies entirely on the screen and fits under the sprite limit is copied without testing each sprite; otherwise each sprite is tested: sprites off the screen are skipped, sprites over the limit are dropped and counted.

## Planning a picture

```c
u16 ms_frame_sprites(u16 frame_index);
u16 ms_module_sprites(u16 module_index);
u8 ms_frame_bounds(u16 frame_index, u8 flip, MS_Bounds *out);
u8 ms_module_bounds(u16 module_index, u8 flip, MS_Bounds *out);

typedef struct { s16 min_x; s16 min_y; s16 max_x; s16 max_y; } MS_Bounds;
```

What a draw would ask for, without drawing it, read from the export's records: the hardware sprites a frame or module takes under the active mapping, and the box its sprites lie in, relative to the draw point (`min <= x < max`), drawn with `flip` as the flipped draws mirror it. The bounds are `FALSE`, and all zero, when it shows nothing. A draw puts only the sprites on the screen into the table, so the count is what it asks for at most.

## Mappings and palette swaps

```c
void ms_set_mapping(u16 mapping_index);
u16 ms_get_mapping(void);
void ms_set_palette_swap(u16 swap_index);
u16 ms_get_palette_swap(void);
```

The mapping re-skins, the palette swap recolours, everything drawn afterwards, until it is set again. Mapping 0 is no mapping (the exported mappings follow in their order); swap 0 is the palettes as they are. An index out of range sets 0. Scene objects with a mapping or swap of their own keep it.

```c
void ms_load_palette(u16 entry, u16 line);
s16 ms_palette_line(u16 entry);
void ms_palette_tick(void);
```

`ms_load_palette` puts a palette entry's colours into one of the console's palette lines, when there are more entries than lines. `ms_palette_line` gives the line an entry is in, or -1. A swap's entry without a line draws in its palette's line, with the colours unswapped. `ms_palette_tick` turns the colour cycles of the loaded entries one video frame on; call it once per video frame, where the console lets palettes be written (the console's page says when).

## Animation players

```c
typedef struct
{
    u16 animation_index;  /* changes when the animation ends and its follow-up takes over */
    u16 step_index;
    s16 ticks_left;       /* video frames the step still shows */
    s8 direction;
    u8 finished;          /* TRUE once playback stopped (no follow-up) */
    u8 step_started;      /* TRUE on the video frame a new step starts */
    u8 reserved0;
    u16 cycles;           /* completed passes, against the animation's repeat count */
} MS_AnimPlayer;

void ms_anim_player_init(MS_AnimPlayer *player, u16 animation_index);
void ms_anim_player_tick(MS_AnimPlayer *player);
void ms_draw_anim_player(const MS_AnimPlayer *player, s16 x, s16 y);
void ms_draw_anim_player_mapped(const MS_AnimPlayer *player, u16 mapping_index, s16 x, s16 y);
void ms_draw_anim_player_as(const MS_AnimPlayer *player, u16 mapping_index, u16 swap_index, s16 x, s16 y);
```

`ms_anim_player_init` starts an animation at its first step (playing backwards: its last). `ms_anim_player_tick` advances one video frame: the step holds for its duration in video frames, then playback moves on by the animation's rules ([animation playback](project-format.md#animation-playback)) and hands over to the follow-up when the animation ends. `ms_draw_anim_player` draws the shown step's render frame (the frame with the step's offset, flips and turn) with its origin at (x, y). `_mapped` and `_as` draw with another mapping, and palette swap, for this draw only; the active ones stay.

The playback modes are `MS_PLAY_LOOP` (0), `MS_PLAY_ONCE` (1), `MS_PLAY_PING_PONG` (2) and `MS_PLAY_BACKWARD` (3).

## Animation events

```c
u8 ms_anim_player_has_event(const MS_AnimPlayer *player, u16 event_type);
u8 ms_anim_player_event_started(const MS_AnimPlayer *player, u16 event_type);
s16 ms_anim_player_event_value(const MS_AnimPlayer *player, u16 event_type, s16 fallback);
u16 ms_anim_player_event_count(const MS_AnimPlayer *player);
const MS_StepEvent *ms_anim_player_event(const MS_AnimPlayer *player, u16 index);
const char *ms_event_name(u16 event_type);

typedef struct { u16 type; s16 value; } MS_StepEvent;
```

The events of the step being shown. `has_event` is true every video frame the step shows (hit windows, invulnerability, cancel windows), `event_started` only on the frame it starts (sounds, spawns, footsteps). `event_value` gives the step's value for that type, or `fallback`. `event_count` and `event` list them all. Event types are `MS_EVENT_<NAME>`, numbered in the order of the project's list.

## Hitboxes and points

```c
u16 ms_frame_hitboxes(u16 frame_index, const MS_Hitbox **out);
u16 ms_frame_points(u16 frame_index, const MS_Point **out);
u16 ms_anim_player_hitboxes(const MS_AnimPlayer *player, const MS_Hitbox **out);
u16 ms_anim_player_points(const MS_AnimPlayer *player, const MS_Point **out);
const MS_Hitbox *ms_find_hitbox(const MS_Hitbox *boxes, u16 count, u16 type, u16 role);
const MS_Point *ms_find_point(const MS_Point *points, u16 count, u16 type, u16 role);
const char *ms_hitbox_type_name(u16 type);
const char *ms_point_type_name(u16 type);
const char *ms_role_name(u16 role);
```

The functions return how many there are and point `*out` at the first. Coordinates are relative to the draw position; a player's are those of the shown step, already moved like it (offset, flips, turn). `ms_find_hitbox` and `ms_find_point` return the first of a type and role (`MS_NO_ROLE`: any role), or `NULL`.

| Field | `MS_Hitbox` | `MS_Point` |
|---|---|---|
| `type` | `MS_HITBOX_<NAME>`, or `MS_UNKNOWN_TYPE` | `MS_POINT_<NAME>` |
| `role` | `MS_ROLE_<NAME>`, or `MS_NO_ROLE` | the same |
| `x`, `y` | the box's top left | the pixel |
| `w`, `h` | its size | |

A frame drawn mirrored has its boxes and points unmirrored here: a mirrored box's `x` is `-x - w`, a mirrored point's `-x - 1` (and likewise `y` for bit 1).

## Scenes

```c
void ms_scene_player_init(MS_ScenePlayer *player, u16 scene_index);
void ms_scene_player_tick(MS_ScenePlayer *player);
void ms_draw_scene_player(const MS_ScenePlayer *player, s16 x, s16 y);
```

A scene plays back as staged in the Timeline, drawn with its origin at (x, y). `ms_scene_player_tick` counts one video frame; the sample shown is `tick × fps / 60`, wrapping when the scene loops and holding the last sample when it does not. Each scene is baked once per mapping: objects without a mapping of their own follow the active mapping, objects with one keep it (the same for palette swaps).

## Streaming: slots

These matter only in a streamed export (`MS_STREAMED` in `modsprite_data.h`). In a resident export they do nothing and the slot sizes are 0, so the same game code works with every export mode. [Video memory and limits](memory-and-limits.md#streamed-exports) explains how to use them.

```c
typedef struct
{
    u16 tile_index;  /* its first tile in video memory */
    u16 load_list;   /* what it holds, MS_NOTHING_LOADED until something is drawn through it */
    /* consoles may keep more here */
} MS_Slot;

void ms_slot_init(MS_Slot *slot, u16 tile_index);
void ms_set_slot(MS_Slot *slot);       /* NULL: the default slot */
u16 ms_slot_tiles(void);
u16 ms_scene_slot_tiles(void);
```

A slot is room in video memory for one thing drawn at a time. `ms_set_slot` makes every following draw go through it, like the mapping. Drawing a render frame whose tiles the slot does not hold queues their upload for the vertical blank; drawing what it holds uploads nothing. `ms_slot_tiles` is a character's slot size, the most tiles a module, frame or animation step needs; `ms_scene_slot_tiles` a scene's. A console may round a slot's first tile (the SNES's slots are whole rows of its sprite tables).

```c
void ms_slot_cache_init(u16 tile_index, u16 tile_count);
void ms_use_slot_cache(void);
void ms_slot_cache_clear(void);
```

One pool of tiles that every draw takes its slot from: a frame or module under a mapping gets a slot the first time it is drawn, at the first place in tile order where it fits, and every draw of it shares that slot until its room is needed (the slots drawn longest ago make room, never one drawn this frame). A draw that finds no room is left out (`draws_left_out`). `ms_set_slot` goes back to slots of your own, `ms_use_slot_cache` to the pool; `ms_slot_cache_clear` forgets what the pool holds after its video memory was used for something else.

```c
u16 ms_frame_load_list(u16 frame_index);
u16 ms_module_load_list(u16 module_index);
u16 ms_load_list_tiles(u16 load_list);
```

For a game that keeps its own cache of slots: the load list (the tiles) a frame or module draws with under the active mapping, and how many tiles it takes in a slot. Draws that share a load list can share a slot. `MS_NOTHING_LOADED` when it shows nothing, and in a resident export.

## Give-way levels

```c
void ms_set_give_way(u8 level);
u8 ms_get_give_way(void);
```

What gives way when a picture asks for more hardware sprites than the limit. What is drawn while a level from 1 to 63 is set (shadows, decorations, effects; 0, the default, means nothing) is left out to make room: level 1 first, then 2, and so on, within a level the farthest (drawn last) first, as much as the picture asks too much. Only then do the sprites drawn last drop, as without levels. The level stays set until it is set again.

Draws go into the table as they come while they fit; from the first that does not, the rest of the frame waits in a queue that `ms_end_frame` resolves, without drawing the picture twice. A frame that fits draws exactly as without levels. While a frame waits, the profile counts only the sprites drawn before it, and `ms_add_hw_sprite` returns `TRUE`. A game that never sets a level runs none of this.

## Names and ids

```c
const char *ms_module_name(u16 module_index);
const char *ms_frame_name(u16 frame_index);
const char *ms_animation_name(u16 animation_index);
const char *ms_scene_name(u16 scene_index);
const char *ms_mapping_name(u16 mapping_index);
const char *ms_palette_swap_name(u16 swap_index);
const char *ms_palette_entry_name(u16 entry);

s16 ms_find_module_index_by_id(const char *id);
s16 ms_find_frame_index_by_id(const char *id);
s16 ms_find_animation_index_by_id(const char *id);
s16 ms_find_scene_index_by_id(const char *id);
s16 ms_find_mapping_index_by_id(const char *id);
s16 ms_find_palette_swap_index_by_id(const char *id);
```

The names the artist gave, and lookups by the ids in the project file (-1 when there is none). A lookup compares strings, so look things up once at start, not every frame.

## Compile-time settings

Define these when compiling `modsprite.c` (for example in your makefile's `CFLAGS`):

| Setting | Default | |
|---|---|---|
| `MS_CACHE_SLOTS` | 48 | slots of the slot cache at most; 0 leaves the cache out |
| `MS_QUEUED_DRAWS` | 32 | draws a frame keeps waiting with give-way levels; 0 leaves the levels out |
| `MS_GIVE_WAY_DRAWS` | 32 | written give-way draws that can make room |
| `MS_PUT_FRAME_C` | off | draw with the runtime's C loops only, not the console's assembly (any compiler but the console's builds them alone) |

The slot cache and the give-way queues are static tables (about 1.2 KB of work RAM with the defaults on the Mega Drive): a game that uses neither sets the first two to 0. A console may have settings of its own (the Mega Drive's `MS_ASM_SPRITES`).

## Generated constants

`modsprite_data.h` defines what the project holds:

- **Counts**: `MS_MODULE_COUNT`, `MS_FRAME_COUNT`, `MS_ANIMATION_COUNT`, `MS_SCENE_COUNT`, `MS_MAPPING_COUNT`, `MS_PALETTE_SWAP_COUNT`, `MS_PALETTE_ENTRY_COUNT`, `MS_RENDER_FRAME_COUNT` and more. Depending on the console they are numbers or read the parsed data at run time; use them as values, not in `#if`.
- **Types and roles**: `MS_EVENT_<NAME>`, `MS_HITBOX_<NAME>`, `MS_POINT_<NAME>`, `MS_ROLE_<NAME>`, `MS_NO_ROLE`, `MS_UNKNOWN_TYPE`, `MS_NO_ANIMATION`. A name becomes upper case, anything but letters and digits an underscore (one at most in a row, none at the ends; `hit on` gives `MS_EVENT_HIT_ON`), a leading digit gets an `E` in front, and a name that clashes with an earlier one gets `_2`, `_3`; Check Project warns about such clashes.
- **Streamed exports**: `MS_STREAMED`, `MS_SLOT_TILES` (a character's slot), `MS_SCENE_SLOT_TILES` (a scene's).
- Each console's data page lists the constants of its own.

## Console-specific functions

| Console | Functions |
|---|---|
| [Mega Drive](consoles/megadrive.md#the-mega-drives-own-functions) | `ms_tiles_fit()`; `ms_data_is_ready()` (from the generated parser) |
| [SNES](consoles/snes.md#the-sness-own-functions) | `ms_tiles_end()`, `ms_sprite_base()`, `ms_upload_tiles()`, `ms_set_upload_budget()`, `ms_upload_queued()` |

Where the consoles differ in what the hardware allows, the functions do too: the SNES writes video memory only in the vertical blank, so its streamed uploads need a call of their own, where the Mega Drive's ride on SGDK's DMA queue.
