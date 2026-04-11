#ifndef MODSPRITE_DATA_H
#define MODSPRITE_DATA_H

#include <genesis.h>

typedef struct
{
    u16 variant_index;
    s16 x;
    s16 y;
    u8 hflip;
    u8 vflip;
} MS_Part;

typedef struct
{
    u32 first_part;
    u16 part_count;
} MS_RenderFrame;

typedef struct
{
    u16 frame_index;
    u16 duration_ticks;
} MS_AnimStep;

typedef struct
{
    u32 first_step;
    u16 step_count;
    u16 fps;
    u8 playback;
} MS_Animation;

typedef struct
{
    u32 first_sample;
    u16 sample_count;
    u16 fps;
    u16 duration_ticks;
    u8 loop;
} MS_Scene;

#define MS_VARIANT_COUNT 164U
#define MS_PART_COUNT 10220U
#define MS_RENDER_FRAME_COUNT 1226U

#define MS_MODULE_COUNT 165U
#define MS_FRAME_COUNT 207U
#define MS_ANIMATION_COUNT 68U
#define MS_SCENE_COUNT 1U
#define MS_MAPPING_COUNT 3U

#define MS_ANIM_STEP_COUNT 1044U
#define MS_SCENE_SAMPLE_COUNT 360U
#define MS_ANIMATION_RECORD_COUNT 204U
#define MS_SCENE_RECORD_COUNT 3U

extern const SpriteDefinition *const ms_variant_defs[];
extern const MS_Part ms_parts[];
extern const MS_RenderFrame ms_render_frames[];

extern const u16 ms_module_render_frames[];
extern const char *const ms_mapping_ids[];
extern const char *const ms_mapping_names[];
extern const char *const ms_module_ids[];
extern const char *const ms_module_names[];

extern const u16 ms_frame_render_frames[];
extern const char *const ms_frame_ids[];
extern const char *const ms_frame_names[];

extern const MS_AnimStep ms_anim_steps[];
extern const MS_Animation ms_animations[];
extern const char *const ms_animation_ids[];
extern const char *const ms_animation_names[];

extern const u16 ms_scene_samples[];
extern const MS_Scene ms_scenes[];
extern const char *const ms_scene_ids[];
extern const char *const ms_scene_names[];

#endif
