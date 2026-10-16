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
} MS_FrameProfile;

/* ms_init() loads every sprite tile into VRAM (word address 0x0000, both sprite tables) and the palette entries into
   sprite palettes 0, 1, ... (CGRAM 128 on), and sets OBSEL to the export's two sprite sizes; call it while the screen
   is off (forced blank). ms_init_ex() picks the VRAM address (0x0000, 0x2000, 0x4000 or 0x6000: OBSEL's 8K-word steps)
   and the first sprite palette. Drawing then only writes the OAM buffer. */
void ms_init(void);
void ms_init_ex(u16 vram_address, u16 first_palette);
u8 ms_palettes_fit(void);       /* FALSE when not every palette entry got a sprite palette (ms_load_palette) */
u16 ms_tile_base(void);
u16 ms_tiles_used(void);
/* The first tile number after the runtime's tiles: tiles from there to 511 are free for the game's own sprites (a
   sprite of N pixels uses a block of N/8 x N/8 tiles in a table 16 tiles wide, its first tile a multiple of N/8 in
   both directions). */
u16 ms_tiles_end(void);
/* 128 (default); fewer leaves the entries from the limit on to the game (a multiple of 4: the high table's bytes
   from there are the game's too) */
void ms_set_sprite_limit(u16 limit);
u16 ms_sprite_base(void);             /* the first OAM entry the runtime does not use: ms_add_hw_sprite writes there */
void ms_begin_frame(void);
void ms_end_frame(void);
/* A sprite of your own in this frame's list, in front of what is drawn later (tile: 9 bits, attribute: the OAM
   attribute byte without the tile's ninth bit). */
u8 ms_add_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large);

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

void ms_anim_player_init(MS_AnimPlayer *player, u16 animation_index);
void ms_anim_player_tick(MS_AnimPlayer *player);
void ms_draw_anim_player(const MS_AnimPlayer *player, s16 x, s16 y);
/* Draw with another mapping (and palette swap); the active ones are left as they were. */
void ms_draw_anim_player_mapped(const MS_AnimPlayer *player, u16 mapping_index, s16 x, s16 y);
void ms_draw_anim_player_as(const MS_AnimPlayer *player, u16 mapping_index, u16 swap_index, s16 x, s16 y);

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
