#ifndef MODSPRITE_DATA_H
#define MODSPRITE_DATA_H

#include <genesis.h>

/* Blob records: no padding, but every record starts on an even address (the blob keeps them aligned),
   so the 68000 can read 16 / 32-bit fields with single word / long moves. */
#define MS_RECORD __attribute__((packed, aligned(2)))

/* A part shows the pieces first_piece .. first_piece + piece_count - 1 (already laid out for its flips)
   at (x, y) from the position it is drawn at; flip: bit 0 = horizontal, bit 1 = vertical. */
typedef struct MS_RECORD
{
    u16 first_piece;
    u8 piece_count;
    u8 flip;
    s16 x;
    s16 y;
} MS_Part;

typedef struct MS_RECORD
{
    u32 first_part;
    u16 part_count;
    u16 hitbox_count;
    u32 first_hitbox;
    u32 first_point;
    u16 point_count;
    u16 sprite_count;  /* hardware sprites, inside min..max (relative to the draw position) */
    s16 min_x;
    s16 min_y;
    s16 max_x;
    s16 max_y;
} MS_RenderFrame;

/* A variant is one baked module image; it shows as one or more hardware sprites (pieces).
   The runtime does not need it (parts point at their pieces); tools can use it. */
typedef struct MS_RECORD
{
    u16 first_piece;
    u16 piece_count;
    u8 tile_w;  /* padded size in tiles: flips mirror the pieces inside it */
    u8 tile_h;
} MS_Variant;

typedef struct MS_RECORD
{
    s16 x;            /* offset from the part's position */
    s16 y;
    u8 size;          /* VDP sprite size: SPRITE_SIZE(w, h) */
    u8 reserved0;
    u16 tile_offset;  /* first tile, from the runtime's tile base */
} MS_Piece;

/* Hitboxes and points of a frame, already moved like the frame (step offset, flips, rotation).
   Coordinates are relative to the position the frame is drawn at. */
typedef struct MS_RECORD
{
    u8 type;      /* MS_HITBOX_*, MS_UNKNOWN_TYPE if its type was deleted */
    u8 reserved0;
    u16 role;     /* MS_ROLE_*, MS_NO_ROLE */
    s16 x;
    s16 y;
    s16 w;
    s16 h;
} MS_Hitbox;

typedef struct MS_RECORD
{
    u8 type;      /* MS_POINT_* */
    u8 reserved0;
    u16 role;     /* MS_ROLE_*, MS_NO_ROLE */
    s16 x;
    s16 y;
} MS_Point;

#define MS_NO_ROLE 0xFFFFu
#define MS_UNKNOWN_TYPE 0xFFu

typedef struct MS_RECORD
{
    u16 frame_index;
    u16 duration_ticks;
    u16 first_event;
    u8 event_count;
    u8 reserved0;
} MS_AnimStep;

typedef struct MS_RECORD
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

typedef struct MS_RECORD
{
    u16 type;   /* MS_EVENT_* */
    s16 value;  /* free parameter, e.g. which sound */
} MS_StepEvent;

#define MS_NO_ANIMATION 0xFFFFu

typedef struct MS_RECORD
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
extern u16 ms_tile_count;
extern u16 ms_palette_count;
extern u16 ms_piece_count;
extern u16 ms_hitbox_count;
extern u16 ms_point_count;
extern u16 ms_hitbox_type_count;
extern u16 ms_point_type_count;
extern u16 ms_role_count;

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
#define MS_TILE_COUNT (ms_tile_count)
#define MS_PALETTE_COUNT (ms_palette_count) /* palette lines (16 colours each) in ms_palette, loaded from the first */

extern const MS_Variant *ms_variants;
extern const MS_Piece *ms_pieces;
extern const u32 *ms_tiles;
extern const u16 *ms_palette;
extern const MS_Hitbox *ms_hitboxes;
extern const MS_Point *ms_points;
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
const char *ms_hitbox_type_name_data(u16 index);
const char *ms_point_type_name_data(u16 index);
const char *ms_role_name_data(u16 index);

/* Animation events (project event types, in the editor's order). */
#define MS_EVENT_HIT 0u
#define MS_EVENT_FOOTSTEP 1u

/* Hitbox types and point types (the editor's lists, in order). */
#define MS_HITBOX_HURT 0u
#define MS_HITBOX_ATTACK 1u
#define MS_POINT_WEAPON 0u
#define MS_POINT_GROUND 1u

/* Roles of hitboxes and points (sorted by name). */
#define MS_ROLE_BLADE 0u
#define MS_ROLE_BLADE_TIP 1u
#define MS_ROLE_BODY 2u
#define MS_ROLE_FEET 3u
#define MS_ROLE_HEAD 4u

#endif
