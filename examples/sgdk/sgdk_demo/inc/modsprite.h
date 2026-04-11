#ifndef MODSPRITE_H
#define MODSPRITE_H

#include <genesis.h>
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
    u16 animation_index;
    u16 step_index;
    s16 ticks_left;
    s8 direction;
    u8 finished;
} MS_AnimPlayer;

typedef struct
{
    u16 scene_index;
    u32 tick;
} MS_ScenePlayer;

typedef struct
{
    u16 render_calls;
    u16 parts_submitted;
    u16 hw_sprites_estimated;
    u16 add_failures;
} MS_FrameProfile;

void ms_init(void);
void ms_begin_frame(void);
void ms_end_frame(void);

void ms_set_mapping(u16 mapping_index);
u16 ms_get_mapping(void);

void ms_draw_module(u16 module_index, s16 x, s16 y);
void ms_draw_frame(u16 frame_index, s16 x, s16 y);

void ms_anim_player_init(MS_AnimPlayer *player, u16 animation_index);
void ms_anim_player_tick(MS_AnimPlayer *player);
void ms_draw_anim_player(const MS_AnimPlayer *player, s16 x, s16 y);

void ms_scene_player_init(MS_ScenePlayer *player, u16 scene_index);
void ms_scene_player_tick(MS_ScenePlayer *player);
void ms_draw_scene_player(const MS_ScenePlayer *player, s16 x, s16 y);

const char *ms_module_name(u16 module_index);
const char *ms_frame_name(u16 frame_index);
const char *ms_animation_name(u16 animation_index);
const char *ms_scene_name(u16 scene_index);
const char *ms_mapping_name(u16 mapping_index);

s16 ms_find_module_index_by_id(const char *id);
s16 ms_find_frame_index_by_id(const char *id);
s16 ms_find_animation_index_by_id(const char *id);
s16 ms_find_scene_index_by_id(const char *id);
s16 ms_find_mapping_index_by_id(const char *id);

void ms_get_frame_profile(MS_FrameProfile *out_profile);

#endif
