#include <genesis.h>
#include <string.h>
#include "modsprite_data.h"
#include "resources.h"

#define MS_BLOB_MAGIC 0x4D534231u
#define MS_BLOB_VERSION 7u
#define MS_BLOB_HEADER_SIZE 210u

enum
{
    MS_SEC_PARTS = 0,
    MS_SEC_RENDER_FRAMES = 1,
    MS_SEC_MODULE_RENDER_FRAMES = 2,
    MS_SEC_FRAME_RENDER_FRAMES = 3,
    MS_SEC_ANIM_STEPS = 4,
    MS_SEC_ANIMATIONS = 5,
    MS_SEC_SCENE_SAMPLES = 6,
    MS_SEC_SCENES = 7,
    MS_SEC_MAPPING_IDS = 8,
    MS_SEC_MAPPING_NAMES = 9,
    MS_SEC_MODULE_IDS = 10,
    MS_SEC_MODULE_NAMES = 11,
    MS_SEC_FRAME_IDS = 12,
    MS_SEC_FRAME_NAMES = 13,
    MS_SEC_ANIMATION_IDS = 14,
    MS_SEC_ANIMATION_NAMES = 15,
    MS_SEC_SCENE_IDS = 16,
    MS_SEC_SCENE_NAMES = 17,
    MS_SEC_STRINGS = 18,
    MS_SEC_STEP_EVENTS = 19,
    MS_SEC_EVENT_NAMES = 20,
    MS_SEC_VARIANTS = 21,
    MS_SEC_PIECES = 22,
    MS_SEC_TILES = 23,
    MS_SEC_PALETTE = 24,
    MS_SEC_HITBOXES = 25,
    MS_SEC_POINTS = 26,
    MS_SEC_HITBOX_TYPE_NAMES = 27,
    MS_SEC_POINT_TYPE_NAMES = 28,
    MS_SEC_ROLE_NAMES = 29,
    MS_SEC_PALETTE_ENTRIES = 30,
    MS_SEC_COLOUR_CYCLES = 31,
    MS_SEC_SWAP_ENTRIES = 32,
    MS_SEC_SWAP_IDS = 33,
    MS_SEC_SWAP_NAMES = 34,
    MS_SEC_PALETTE_NAMES = 35,
    MS_SEC_MODULE_FLIP_OFFSETS = 36,
    MS_SEC_COUNT = 37
};

u16 ms_variant_count = 0;
u32 ms_part_count = 0;
u16 ms_render_frame_count = 0;
u16 ms_module_count = 0;
u16 ms_frame_count = 0;
u16 ms_animation_count = 0;
u16 ms_scene_count = 0;
u16 ms_mapping_count = 0;
u16 ms_anim_step_count = 0;
u16 ms_scene_sample_count = 0;
u16 ms_animation_record_count = 0;
u16 ms_scene_record_count = 0;
u16 ms_event_type_count = 0;
u16 ms_step_event_count = 0;
u16 ms_tile_count = 0;
u16 ms_palette_entry_count = 0;
u16 ms_base_palette_count = 0;
u16 ms_palette_swap_count = 0;
u16 ms_colour_cycle_count = 0;
u16 ms_piece_count = 0;
u16 ms_hitbox_count = 0;
u16 ms_point_count = 0;
u16 ms_hitbox_type_count = 0;
u16 ms_point_type_count = 0;
u16 ms_role_count = 0;

const MS_Variant *ms_variants = NULL;
const MS_Piece *ms_pieces = NULL;
const u32 *ms_tiles = NULL;
const u16 *ms_palette = NULL;
const MS_PaletteEntry *ms_palette_entries = NULL;
const MS_ColourCycle *ms_colour_cycles = NULL;
const u8 *ms_swap_entries = NULL;
const MS_Hitbox *ms_hitboxes = NULL;
const MS_Point *ms_points = NULL;
const MS_Part *ms_parts = NULL;
const MS_RenderFrame *ms_render_frames = NULL;
const u16 *ms_module_render_frames = NULL;
const s16 *ms_module_flip_offsets = NULL;
const u16 *ms_frame_render_frames = NULL;
const MS_AnimStep *ms_anim_steps = NULL;
const MS_Animation *ms_animations = NULL;
const u16 *ms_scene_samples = NULL;
const MS_Scene *ms_scenes = NULL;
const MS_StepEvent *ms_step_events = NULL;

static const u8 *g_blob = NULL;
static u32 g_blob_size = 0;
static u8 g_data_ready = FALSE;
static u8 g_data_attempted = FALSE;
static u32 g_section_offsets[MS_SEC_COUNT];
static u32 g_strings_base = 0;
static u32 g_strings_size = 0;
static const u8 *g_mapping_id_offsets = NULL;
static const u8 *g_mapping_name_offsets = NULL;
static const u8 *g_module_id_offsets = NULL;
static const u8 *g_module_name_offsets = NULL;
static const u8 *g_frame_id_offsets = NULL;
static const u8 *g_frame_name_offsets = NULL;
static const u8 *g_animation_id_offsets = NULL;
static const u8 *g_animation_name_offsets = NULL;
static const u8 *g_scene_id_offsets = NULL;
static const u8 *g_scene_name_offsets = NULL;
static const u8 *g_event_name_offsets = NULL;
static const u8 *g_hitbox_type_name_offsets = NULL;
static const u8 *g_point_type_name_offsets = NULL;
static const u8 *g_role_name_offsets = NULL;
static const u8 *g_swap_id_offsets = NULL;
static const u8 *g_swap_name_offsets = NULL;
static const u8 *g_palette_name_offsets = NULL;

static u16 ms_read_be16(const u8 *ptr)
{
    return (u16)(((u16)ptr[0] << 8) | (u16)ptr[1]);
}

static u32 ms_read_be32(const u8 *ptr)
{
    return ((u32)ptr[0] << 24) | ((u32)ptr[1] << 16) | ((u32)ptr[2] << 8) | (u32)ptr[3];
}

static void ms_reset_data(void)
{
    ms_variant_count = 0;
    ms_part_count = 0;
    ms_render_frame_count = 0;
    ms_module_count = 0;
    ms_frame_count = 0;
    ms_animation_count = 0;
    ms_scene_count = 0;
    ms_mapping_count = 0;
    ms_anim_step_count = 0;
    ms_scene_sample_count = 0;
    ms_animation_record_count = 0;
    ms_scene_record_count = 0;
    ms_event_type_count = 0;
    ms_step_event_count = 0;
    ms_tile_count = 0;
    ms_palette_entry_count = 0;
    ms_base_palette_count = 0;
    ms_palette_swap_count = 0;
    ms_colour_cycle_count = 0;
    ms_piece_count = 0;
    ms_hitbox_count = 0;
    ms_point_count = 0;
    ms_hitbox_type_count = 0;
    ms_point_type_count = 0;
    ms_role_count = 0;

    ms_variants = NULL;
    ms_pieces = NULL;
    ms_tiles = NULL;
    ms_palette = NULL;
    ms_palette_entries = NULL;
    ms_colour_cycles = NULL;
    ms_swap_entries = NULL;
    ms_hitboxes = NULL;
    ms_points = NULL;
    ms_parts = NULL;
    ms_render_frames = NULL;
    ms_module_render_frames = NULL;
    ms_module_flip_offsets = NULL;
    ms_frame_render_frames = NULL;
    ms_anim_steps = NULL;
    ms_animations = NULL;
    ms_scene_samples = NULL;
    ms_scenes = NULL;
    ms_step_events = NULL;

    g_mapping_id_offsets = NULL;
    g_mapping_name_offsets = NULL;
    g_module_id_offsets = NULL;
    g_module_name_offsets = NULL;
    g_frame_id_offsets = NULL;
    g_frame_name_offsets = NULL;
    g_animation_id_offsets = NULL;
    g_animation_name_offsets = NULL;
    g_scene_id_offsets = NULL;
    g_scene_name_offsets = NULL;
    g_event_name_offsets = NULL;
    g_hitbox_type_name_offsets = NULL;
    g_point_type_name_offsets = NULL;
    g_role_name_offsets = NULL;
    g_swap_id_offsets = NULL;
    g_swap_name_offsets = NULL;
    g_palette_name_offsets = NULL;
    g_strings_base = 0;
    g_strings_size = 0;
    g_data_ready = FALSE;
}

static u8 ms_blob_range_ok(u32 offset, u32 size)
{
    if (offset > g_blob_size)
        return FALSE;
    if (size > (g_blob_size - offset))
        return FALSE;
    return TRUE;
}

u8 ms_data_is_ready(void)
{
    return g_data_ready;
}

void ms_data_init(void)
{
    const u8 *ptr;
    u16 i;

    if (g_data_attempted)
        return;

    g_data_attempted = TRUE;
    ms_reset_data();

    g_blob = MS_BLOB;
    g_blob_size = (u32)sizeof(MS_BLOB);
    if (g_blob_size < MS_BLOB_HEADER_SIZE)
        return;

    ptr = g_blob;
    if (ms_read_be32(ptr) != MS_BLOB_MAGIC)
        return;
    ptr += 4;
    if (ms_read_be16(ptr) != MS_BLOB_VERSION)
        return;
    ptr += 2;
    ms_palette_entry_count = ms_read_be16(ptr); ptr += 2;

    ms_variant_count = ms_read_be16(ptr); ptr += 2;
    ms_module_count = ms_read_be16(ptr); ptr += 2;
    ms_frame_count = ms_read_be16(ptr); ptr += 2;
    ms_animation_count = ms_read_be16(ptr); ptr += 2;
    ms_scene_count = ms_read_be16(ptr); ptr += 2;
    ms_mapping_count = ms_read_be16(ptr); ptr += 2;
    ms_render_frame_count = ms_read_be16(ptr); ptr += 2;
    ms_anim_step_count = ms_read_be16(ptr); ptr += 2;
    ms_scene_sample_count = ms_read_be16(ptr); ptr += 2;
    ms_animation_record_count = ms_read_be16(ptr); ptr += 2;
    ms_scene_record_count = ms_read_be16(ptr); ptr += 2;
    ms_event_type_count = ms_read_be16(ptr); ptr += 2;
    ms_step_event_count = ms_read_be16(ptr); ptr += 2;
    ms_tile_count = ms_read_be16(ptr); ptr += 2;
    ms_piece_count = ms_read_be16(ptr); ptr += 2;
    ms_hitbox_count = ms_read_be16(ptr); ptr += 2;
    ms_point_count = ms_read_be16(ptr); ptr += 2;
    ms_hitbox_type_count = ms_read_be16(ptr); ptr += 2;
    ms_point_type_count = ms_read_be16(ptr); ptr += 2;
    ms_role_count = ms_read_be16(ptr); ptr += 2;
    ms_base_palette_count = ms_read_be16(ptr); ptr += 2;
    ms_palette_swap_count = ms_read_be16(ptr); ptr += 2;
    ms_colour_cycle_count = ms_read_be16(ptr); ptr += 2;
    ms_part_count = ms_read_be32(ptr); ptr += 4;

    for (i = 0; i < MS_SEC_COUNT; i++)
    {
        g_section_offsets[i] = ms_read_be32(ptr);
        ptr += 4;
    }
    g_strings_size = ms_read_be32(ptr);

    ms_parts = (const MS_Part *)(g_blob + g_section_offsets[MS_SEC_PARTS]);
    ms_render_frames = (const MS_RenderFrame *)(g_blob + g_section_offsets[MS_SEC_RENDER_FRAMES]);
    ms_module_render_frames = (const u16 *)(g_blob + g_section_offsets[MS_SEC_MODULE_RENDER_FRAMES]);
    ms_module_flip_offsets = (const s16 *)(g_blob + g_section_offsets[MS_SEC_MODULE_FLIP_OFFSETS]);
    ms_frame_render_frames = (const u16 *)(g_blob + g_section_offsets[MS_SEC_FRAME_RENDER_FRAMES]);
    ms_anim_steps = (const MS_AnimStep *)(g_blob + g_section_offsets[MS_SEC_ANIM_STEPS]);
    ms_animations = (const MS_Animation *)(g_blob + g_section_offsets[MS_SEC_ANIMATIONS]);
    ms_scene_samples = (const u16 *)(g_blob + g_section_offsets[MS_SEC_SCENE_SAMPLES]);
    ms_scenes = (const MS_Scene *)(g_blob + g_section_offsets[MS_SEC_SCENES]);
    g_mapping_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_MAPPING_IDS]);
    g_mapping_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_MAPPING_NAMES]);
    g_module_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_MODULE_IDS]);
    g_module_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_MODULE_NAMES]);
    g_frame_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_FRAME_IDS]);
    g_frame_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_FRAME_NAMES]);
    g_animation_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_ANIMATION_IDS]);
    g_animation_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_ANIMATION_NAMES]);
    g_scene_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SCENE_IDS]);
    g_scene_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SCENE_NAMES]);
    ms_step_events = (const MS_StepEvent *)(g_blob + g_section_offsets[MS_SEC_STEP_EVENTS]);
    g_event_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_EVENT_NAMES]);
    ms_variants = (const MS_Variant *)(g_blob + g_section_offsets[MS_SEC_VARIANTS]);
    ms_pieces = (const MS_Piece *)(g_blob + g_section_offsets[MS_SEC_PIECES]);
    ms_tiles = (const u32 *)(g_blob + g_section_offsets[MS_SEC_TILES]);
    ms_palette = (const u16 *)(g_blob + g_section_offsets[MS_SEC_PALETTE]);
    ms_palette_entries = (const MS_PaletteEntry *)(g_blob + g_section_offsets[MS_SEC_PALETTE_ENTRIES]);
    ms_colour_cycles = (const MS_ColourCycle *)(g_blob + g_section_offsets[MS_SEC_COLOUR_CYCLES]);
    ms_swap_entries = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SWAP_ENTRIES]);
    ms_hitboxes = (const MS_Hitbox *)(g_blob + g_section_offsets[MS_SEC_HITBOXES]);
    ms_points = (const MS_Point *)(g_blob + g_section_offsets[MS_SEC_POINTS]);
    g_hitbox_type_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_HITBOX_TYPE_NAMES]);
    g_point_type_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_POINT_TYPE_NAMES]);
    g_role_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_ROLE_NAMES]);
    g_swap_id_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SWAP_IDS]);
    g_swap_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_SWAP_NAMES]);
    g_palette_name_offsets = (const u8 *)(g_blob + g_section_offsets[MS_SEC_PALETTE_NAMES]);

    g_strings_base = g_section_offsets[MS_SEC_STRINGS];

    g_data_ready = TRUE;
}

static const char *ms_lookup_string(const u8 *offsets, u16 count, u16 index)
{
    u32 off;

    if (!g_data_ready || !offsets || index >= count)
        return "";
    off = ms_read_be32(offsets + ((u32)index * 4u));
    if (!ms_blob_range_ok(off, 1u))
        return "";
    return (const char *)(g_blob + off);
}

const char *ms_mapping_id(u16 index) { return ms_lookup_string(g_mapping_id_offsets, ms_mapping_count, index); }
const char *ms_mapping_name_data(u16 index) { return ms_lookup_string(g_mapping_name_offsets, ms_mapping_count, index); }
const char *ms_module_id(u16 index) { return ms_lookup_string(g_module_id_offsets, ms_module_count, index); }
const char *ms_module_name_data(u16 index) { return ms_lookup_string(g_module_name_offsets, ms_module_count, index); }
const char *ms_frame_id(u16 index) { return ms_lookup_string(g_frame_id_offsets, ms_frame_count, index); }
const char *ms_frame_name_data(u16 index) { return ms_lookup_string(g_frame_name_offsets, ms_frame_count, index); }
const char *ms_animation_id(u16 index) { return ms_lookup_string(g_animation_id_offsets, ms_animation_count, index); }
const char *ms_animation_name_data(u16 index) { return ms_lookup_string(g_animation_name_offsets, ms_animation_count, index); }
const char *ms_scene_id(u16 index) { return ms_lookup_string(g_scene_id_offsets, ms_scene_count, index); }
const char *ms_scene_name_data(u16 index) { return ms_lookup_string(g_scene_name_offsets, ms_scene_count, index); }
const char *ms_event_name_data(u16 index) { return ms_lookup_string(g_event_name_offsets, ms_event_type_count, index); }
const char *ms_hitbox_type_name_data(u16 index) { return ms_lookup_string(g_hitbox_type_name_offsets, ms_hitbox_type_count, index); }
const char *ms_point_type_name_data(u16 index) { return ms_lookup_string(g_point_type_name_offsets, ms_point_type_count, index); }
const char *ms_role_name_data(u16 index) { return ms_lookup_string(g_role_name_offsets, ms_role_count, index); }
const char *ms_palette_swap_id(u16 index) { return ms_lookup_string(g_swap_id_offsets, ms_palette_swap_count, index); }
const char *ms_palette_swap_name_data(u16 index) { return ms_lookup_string(g_swap_name_offsets, ms_palette_swap_count, index); }
const char *ms_palette_entry_name_data(u16 index) { return ms_lookup_string(g_palette_name_offsets, ms_palette_entry_count, index); }
