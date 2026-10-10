#ifndef MODSPRITE_DATA_H
#define MODSPRITE_DATA_H

#include <genesis.h>

typedef struct __attribute__((packed))
{
    u16 variant_index;
    s16 x;
    s16 y;
    u8 hflip;
    u8 vflip;
} MS_Part;

typedef struct __attribute__((packed))
{
    u32 first_part;
    u16 part_count;
} MS_RenderFrame;

typedef struct __attribute__((packed))
{
    u16 frame_index;
    u16 duration_ticks;
    u16 first_event;
    u8 event_count;
    u8 reserved0;
} MS_AnimStep;

typedef struct __attribute__((packed))
{
    u32 first_step;
    u16 step_count;
    u16 fps;
    u8 playback;
    u8 reserved0;
    u16 loop_start;      /* MS_PLAY_LOOP: later passes start at this step */
    u16 next_animation;  /* continue with this animation when it ends, MS_NO_ANIMATION = none */
    u16 loop_count;      /* repeats before it ends, 0 = forever */
} MS_Animation;

typedef struct __attribute__((packed))
{
    u16 type;   /* MS_EVENT_* */
    s16 value;  /* free parameter, e.g. which sound */
} MS_StepEvent;

#define MS_NO_ANIMATION 0xFFFFu

typedef struct __attribute__((packed))
{
    u32 first_sample;
    u16 sample_count;
    u16 fps;
    u16 duration_ticks;
    u8 loop;
    u8 reserved0;
    u8 reserved1;
    u8 reserved2;
} MS_Scene;

extern u16 ms_variant_count;
extern u32 ms_part_count;
extern u16 ms_render_frame_count;

extern u16 ms_module_count;
extern u16 ms_frame_count;
extern u16 ms_animation_count;
extern u16 ms_scene_count;
extern u16 ms_mapping_count;

extern u16 ms_anim_step_count;
extern u16 ms_scene_sample_count;
extern u16 ms_animation_record_count;
extern u16 ms_scene_record_count;
extern u16 ms_event_type_count;
extern u16 ms_step_event_count;

#define MS_VARIANT_COUNT (ms_variant_count)
#define MS_PART_COUNT (ms_part_count)
#define MS_RENDER_FRAME_COUNT (ms_render_frame_count)
#define MS_MODULE_COUNT (ms_module_count)
#define MS_FRAME_COUNT (ms_frame_count)
#define MS_ANIMATION_COUNT (ms_animation_count)
#define MS_SCENE_COUNT (ms_scene_count)
#define MS_MAPPING_COUNT (ms_mapping_count)
#define MS_ANIM_STEP_COUNT (ms_anim_step_count)
#define MS_SCENE_SAMPLE_COUNT (ms_scene_sample_count)
#define MS_ANIMATION_RECORD_COUNT (ms_animation_record_count)
#define MS_SCENE_RECORD_COUNT (ms_scene_record_count)
#define MS_EVENT_TYPE_COUNT (ms_event_type_count)
#define MS_STEP_EVENT_COUNT (ms_step_event_count)

extern const SpriteDefinition *const ms_variant_defs[];
extern const MS_Part *ms_parts;
extern const MS_RenderFrame *ms_render_frames;
extern const u16 *ms_module_render_frames;
extern const u16 *ms_frame_render_frames;
extern const MS_AnimStep *ms_anim_steps;
extern const MS_Animation *ms_animations;
extern const u16 *ms_scene_samples;
extern const MS_Scene *ms_scenes;
extern const MS_StepEvent *ms_step_events;

void ms_data_init(void);
u8 ms_data_is_ready(void);

const char *ms_mapping_id(u16 index);
const char *ms_mapping_name_data(u16 index);
const char *ms_module_id(u16 index);
const char *ms_module_name_data(u16 index);
const char *ms_frame_id(u16 index);
const char *ms_frame_name_data(u16 index);
const char *ms_animation_id(u16 index);
const char *ms_animation_name_data(u16 index);
const char *ms_scene_id(u16 index);
const char *ms_scene_name_data(u16 index);
const char *ms_event_name_data(u16 index);

/* Animation events (project event types, in the editor's order). */
/* none */

#endif
