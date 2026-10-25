#ifndef MODSPRITE_H
#define MODSPRITE_H

/* The Modular Sprite Editor's SNES runtime (PVSnesLib): draws the exported modules, frames, animations and scenes
   into PVSnesLib's OAM buffer (oamMemory, sent by its VBlank interrupt), plays animations exactly like the editor and
   gives the game the hitboxes and points of what it shows. The API is the Mega Drive runtime's
   (examples/megadrive/megadrive_demo/inc/modsprite.h), so a game uses the same calls on both. */

#include <snes.h>
#include "modsprite_data.h"

enum
{
    MS_PLAY_LOOP = 0,
    MS_PLAY_ONCE = 1,
    MS_PLAY_PING_PONG = 2,
    MS_PLAY_BACKWARD = 3,
};

typedef struct
{
    u16 animation_index;  /* changes when an animation ends and its follow-up takes over */
    u16 step_index;
    s16 ticks_left;
    s8 direction;
    u8 finished;          /* TRUE once playback stopped (no follow-up animation) */
    u8 step_started;      /* TRUE on the tick a new step starts: its events fire */
    u8 reserved0;
    u16 cycles;           /* completed passes, compared with the animation's loop_count */
} MS_AnimPlayer;

typedef struct
{
    u16 scene_index;
    u32 tick;             /* video frames since the scene started */
    u16 sample;           /* the sample shown: tick * fps / 60, wrapped when the scene loops */
    u16 phase;            /* (tick * fps) % 60 */
} MS_ScenePlayer;

typedef struct
{
    u16 render_calls;
    u16 parts_submitted;
    u16 hw_sprites;       /* hardware sprites used this frame */
    u16 sprites_dropped;  /* pieces that did not fit into the 128 sprites */
    u16 tiles_uploaded;   /* streamed exports: tiles queued for the next vertical blank */
    u16 uploads_waiting;  /* streamed exports: draws that showed what their slot held, their upload waiting */
    u16 slots_used;       /* the slot cache's slots drawn this frame (streamed exports, ms_slot_cache_init) */
    u16 draws_left_out;   /* draws the slot cache had no room for, or the draw queue (MS_QUEUED_DRAWS) */
    u16 draws_given_way;  /* draws left out to make room for the others (ms_set_give_way) */
} MS_FrameProfile;

/* Where a frame or module draws, relative to the point it is drawn at: its hardware sprites lie in
   min_x <= x < max_x, min_y <= y < max_y. */
typedef struct
{
    s16 min_x;
    s16 min_y;
    s16 max_x;
    s16 max_y;
} MS_Bounds;

/* Streamed exports (MS_STREAMED in modsprite_data.h, docs/EXPORT_MODES.md) keep only what is on screen in video memory,
   in slots of whole rows of the sprite tables (16 tiles): ms_slot_tiles() tiles for a player, ms_scene_slot_tiles() for
   a scene. Whatever is drawn takes its tiles from the slot set with ms_set_slot(), like the mapping; drawing something
   the slot does not hold queues its tiles, and ms_upload_tiles(), called right after WaitForVBlank() (PVSnesLib has sent
   the sprite table then), puts them into video memory, which can only be written in vertical blank. ms_init() makes a
   default slot at tile 0, as big as either; give everything else drawn at the same time a slot of its own (one thing a
   frame through each). When this vertical blank's uploads would exceed the budget (ms_set_upload_budget), a draw shows
   what its slot holds (what it showed before) and uploads in a later frame. Exports that keep every tile in video memory
   ignore slots (their sizes are 0). */
typedef struct
{
    u16 tile_index;  /* its first tile, a multiple of MS_SLOT_ALIGN */
    u16 load_list;   /* the tiles it holds, MS_NOTHING_LOADED until something is drawn through it */
    u16 render;      /* the render frame it showed last, which those tiles are for */
    u16 frame;       /* the frame it was drawn through last */
} MS_Slot;

#define MS_NOTHING_LOADED 0xFFFFu

/* ms_init() loads every sprite tile into VRAM (word address 0x0000, both sprite tables) and the palette entries into
   sprite palettes 0, 1, ... (CGRAM 128 on), and sets OBSEL to the export's two sprite sizes; call it while the screen
   is off (forced blank). ms_init_ex() picks the VRAM address (0x0000, 0x2000, 0x4000 or 0x6000: OBSEL's 8K-word steps)
   and the first sprite palette. Drawing then only writes the OAM buffer. A streamed export loads no tiles there: the
   tables are the slots'. */
void ms_init(void);
void ms_init_ex(u16 vram_address, u16 first_palette);
u8 ms_palettes_fit(void);       /* FALSE when not every palette entry got a sprite palette (ms_load_palette) */
u16 ms_tile_base(void);
u16 ms_tiles_used(void);        /* the tiles from tile 0 it takes: every one, or the default slot's */
/* The first tile number after the runtime's tiles (streamed: the default slot): tiles from there to 511 are free for
   the game's own sprites and slots (a sprite of N pixels uses a block of N/8 x N/8 tiles in a table 16 tiles wide, its
   first tile a multiple of N/8 in both directions). */
u16 ms_tiles_end(void);
void ms_slot_init(MS_Slot *slot, u16 tile_index);  /* tile_index rounded up to a multiple of MS_SLOT_ALIGN */
void ms_set_slot(MS_Slot *slot);      /* draw through this slot from now on; NULL: the default slot */
u16 ms_slot_tiles(void);              /* a player's slot: the rows the largest module, frame or animation step needs */
u16 ms_scene_slot_tiles(void);        /* a scene's slot: the rows its largest sample needs */
/* A slot cache instead: tile_count tiles from tile_index (rounded up to a multiple of MS_SLOT_ALIGN) shared by everything
   drawn from now on. A load list gets a slot there the first time it is drawn, at the first place in tile order where
   its rows fit, and every draw of the same frame or module under the same mapping uses it, whoever draws it, until its
   room is needed: the slots drawn longest ago make room (never one drawn this frame). A draw finds no room only when
   the slots in the way were all drawn this frame; it is left out (MS_FrameProfile's draws_left_out, slots_used and
   tiles_uploaded tell how the cache does), and one whose upload waits for room in the budget shows nothing until it is
   uploaded (uploads_waiting). MS_CACHE_SLOTS slots at most (48 unless the game defines another number when it compiles
   modsprite.c; 0 leaves the cache out). ms_set_slot() goes back to slots of the game's own, ms_use_slot_cache() to the
   cache; ms_slot_cache_clear() forgets what it holds when its video memory was used for something else. */
void ms_slot_cache_init(u16 tile_index, u16 tile_count);
void ms_use_slot_cache(void);
void ms_slot_cache_clear(void);
/* What one vertical blank uploads at most, in bytes of DMA (about 170 a scanline, each list counted with what setting up
   its runs costs; MS_UPLOAD_BUDGET: what is left after PVSnesLib's interrupt sent the sprite table). Lower it when the
   game sends more in vertical blank; the first list of a frame goes whatever it costs. ms_upload_queued(): what this
   frame's draws queued so far, to send other things in the same vertical blank only when they leave room. */
void ms_set_upload_budget(u16 bytes);
u16 ms_upload_queued(void);
/* Right after WaitForVBlank(), before ms_palette_tick(): puts the sprite palettes ms_palette_tick prepared and the tiles
   this frame's draws queued into video memory (DMA channel 0). What does not arrive before the vertical blank ends is
   queued again when it is drawn next. */
void ms_upload_tiles(void);
/* 128 (default); fewer leaves the entries from the limit on to the game (a multiple of 4: the high table's bytes
   from there are the game's too) */
void ms_set_sprite_limit(u16 limit);
u16 ms_sprite_base(void);             /* the first OAM entry the runtime does not use: ms_add_hw_sprite writes there */
void ms_begin_frame(void);
void ms_end_frame(void);
/* A sprite of your own in this frame's list, in front of what is drawn later (tile: 9 bits, attribute: the OAM
   attribute byte without the tile's ninth bit). */
u8 ms_add_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large);

/* What gives way when a frame asks for more hardware sprites than the limit: what is drawn while a level from 1 to 63
   is set (shadows, decorations, effects; 0, the default: nothing) is left out to make room, level 1 first, then 2 and
   so on, within a level what was drawn last (the farthest) first, as much as the frame asks too much; the sprites drawn
   last drop only after that, as they do without levels. The level stays set until it is set again, like the mapping.
   Draws go into the OAM buffer as they come while they fit; from the first one that does not, the rest of the frame
   waits in a queue (MS_QUEUED_DRAWS draws, 32 unless the game defines another number) that ms_end_frame() resolves:
   a frame that fits is drawn as without levels, each draw only looked at. MS_GIVE_WAY_DRAWS give-way draws (32) can make room from before that draw, the later
   ones stay. While a frame waits, the profile counts the sprites drawn before it, and ms_add_hw_sprite() returns TRUE. */
void ms_set_give_way(u8 level);
u8 ms_get_give_way(void);

/* The mapping re-skins everything drawn afterwards; set it per character before drawing it. */
void ms_set_mapping(u16 mapping_index);
u16 ms_get_mapping(void);

/* A palette swap recolours everything drawn afterwards (0 = the palettes as they are); scene objects with a swap of
   their own keep it. */
void ms_set_palette_swap(u16 swap_index);
u16 ms_get_palette_swap(void);
/* Put an entry's colours into a sprite palette (0-7): CGRAM gets them at the next ms_palette_tick. */
void ms_load_palette(u16 entry, u16 palette);
s16 ms_palette_line(u16 entry);                /* the sprite palette an entry is in, -1 if none */
/* Call once per video frame right after WaitForVBlank: it puts the sprite palettes that changed into CGRAM (which can
   only be written in vertical blank), then turns the colour cycles a step and prepares the next colours in RAM. After
   n calls the cycles show what the editor's preview shows after n video frames. */
void ms_palette_tick(void);

void ms_draw_module(u16 module_index, s16 x, s16 y);
void ms_draw_frame(u16 frame_index, s16 x, s16 y);

/* Mirrored (flip: bit 0 left-right, bit 1 top-bottom): a frame around the point drawn at (its origin), like a mirrored
   animation step, so a character facing either way needs its frames stored once; a module in place, like a part
   mirrored in a frame (its pivot drawn at x, y, its picture mirrored where it is). */
void ms_draw_module_flipped(u16 module_index, s16 x, s16 y, u8 flip);
void ms_draw_frame_flipped(u16 frame_index, s16 x, s16 y, u8 flip);
/* What a draw would ask for, without drawing it: the hardware sprites a frame or module takes under the active
   mapping (a draw puts only those on screen into the OAM buffer), and where they lie drawn with flip (0 as it is;
   mirrored as ms_draw_frame_flipped / ms_draw_module_flipped mirror it). The bounds are FALSE, and all 0, when it shows
   nothing. All read from the export's records: a game can plan a picture before it draws it. */
u16 ms_frame_sprites(u16 frame_index);
u16 ms_module_sprites(u16 module_index);
u8 ms_frame_bounds(u16 frame_index, u8 flip, MS_Bounds *out);
u8 ms_module_bounds(u16 module_index, u8 flip, MS_Bounds *out);
/* For a game that keeps its own slots (streamed exports): the load list a frame or module draws with under the active
   mapping (MS_NOTHING_LOADED if none, and in resident exports), and the tiles a load list takes in a slot (its rows of
   the sprite tables: a slot of that many tiles from a multiple of MS_SLOT_ALIGN holds it). Actors that show the same
   frame can share one slot that holds it. */
u16 ms_frame_load_list(u16 frame_index);
u16 ms_module_load_list(u16 module_index);
u16 ms_load_list_tiles(u16 load_list);

void ms_anim_player_init(MS_AnimPlayer *player, u16 animation_index);
void ms_anim_player_tick(MS_AnimPlayer *player);
void ms_draw_anim_player(const MS_AnimPlayer *player, s16 x, s16 y);
/* Mirrored (flip as ms_draw_frame_flipped's) around the point drawn at: the step as the editor's mirror preview shows
   it, its offset, flips and turn mirrored with it, so a character facing either way needs its animations once. */
void ms_draw_anim_player_flipped(const MS_AnimPlayer *player, s16 x, s16 y, u8 flip);
/* Draw with another mapping (and palette swap); the active ones are left as they were. _as_flipped mirrors the draw
   (with another mapping alone: the swap ms_get_palette_swap() gives), a guard drawn from the hero's animations who
   faces him. */
void ms_draw_anim_player_mapped(const MS_AnimPlayer *player, u16 mapping_index, s16 x, s16 y);
void ms_draw_anim_player_as(const MS_AnimPlayer *player, u16 mapping_index, u16 swap_index, s16 x, s16 y);
void ms_draw_anim_player_as_flipped(const MS_AnimPlayer *player, u16 mapping_index, u16 swap_index, s16 x, s16 y,
                                    u8 flip);

/* Animation events (MS_EVENT_* from modsprite_data.h) on the step being shown. */
u8 ms_anim_player_has_event(const MS_AnimPlayer *player, u16 event_type);
u8 ms_anim_player_event_started(const MS_AnimPlayer *player, u16 event_type);
s16 ms_anim_player_event_value(const MS_AnimPlayer *player, u16 event_type, s16 fallback);
u16 ms_anim_player_event_count(const MS_AnimPlayer *player);
const MS_StepEvent *ms_anim_player_event(const MS_AnimPlayer *player, u16 index);
const char *ms_event_name(u16 event_type);

/* Hitboxes and points, relative to the position the frame is drawn at. */
u16 ms_frame_hitboxes(u16 frame_index, const MS_Hitbox **out);
u16 ms_frame_points(u16 frame_index, const MS_Point **out);
u16 ms_anim_player_hitboxes(const MS_AnimPlayer *player, const MS_Hitbox **out);
u16 ms_anim_player_points(const MS_AnimPlayer *player, const MS_Point **out);
const MS_Hitbox *ms_find_hitbox(const MS_Hitbox *boxes, u16 count, u16 type, u16 role);
const MS_Point *ms_find_point(const MS_Point *points, u16 count, u16 type, u16 role);
/* One of a frame or step drawn mirrored (flip as the draw's), mirrored with it into *out: a box's x becomes -x - w (its
   y -y - h), a point's x -x - 1 (its y -y - 1: it marks a pixel, which goes to its mirror image). Returns out, NULL
   for NULL (what ms_find_hitbox / ms_find_point give when there is none). */
MS_Hitbox *ms_flip_hitbox(const MS_Hitbox *box, u8 flip, MS_Hitbox *out);
MS_Point *ms_flip_point(const MS_Point *point, u8 flip, MS_Point *out);
const char *ms_hitbox_type_name(u16 type);
const char *ms_point_type_name(u16 type);
const char *ms_role_name(u16 role);

void ms_scene_player_init(MS_ScenePlayer *player, u16 scene_index);
void ms_scene_player_tick(MS_ScenePlayer *player);
void ms_draw_scene_player(const MS_ScenePlayer *player, s16 x, s16 y);

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

void ms_get_frame_profile(MS_FrameProfile *out_profile);

#endif
