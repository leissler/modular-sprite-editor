#include <genesis.h>
#include <string.h>
#include "modsprite_data.h"
#include "resources.h"

#define MS_BLOB_MAGIC 0x4D534231u
#define MS_BLOB_VERSION 1u
#define MS_BLOB_HEADER_SIZE 114u
#define MS_VARIANT_DEF_COUNT 164u

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
    MS_SEC_COUNT = 19
};

const SpriteDefinition *const ms_variant_defs[] = {
    &MS_VAR_0000,
    &MS_VAR_0001,
    &MS_VAR_0002,
    &MS_VAR_0003,
    &MS_VAR_0004,
    &MS_VAR_0005,
    &MS_VAR_0006,
    &MS_VAR_0007,
    &MS_VAR_0008,
    &MS_VAR_0009,
    &MS_VAR_0010,
    &MS_VAR_0011,
    &MS_VAR_0012,
    &MS_VAR_0013,
    &MS_VAR_0014,
    &MS_VAR_0015,
    &MS_VAR_0016,
    &MS_VAR_0017,
    &MS_VAR_0018,
    &MS_VAR_0019,
    &MS_VAR_0020,
    &MS_VAR_0021,
    &MS_VAR_0022,
    &MS_VAR_0023,
    &MS_VAR_0024,
    &MS_VAR_0025,
    &MS_VAR_0026,
    &MS_VAR_0027,
    &MS_VAR_0028,
    &MS_VAR_0029,
    &MS_VAR_0030,
    &MS_VAR_0031,
    &MS_VAR_0032,
    &MS_VAR_0033,
    &MS_VAR_0034,
    &MS_VAR_0035,
    &MS_VAR_0036,
    &MS_VAR_0037,
    &MS_VAR_0038,
    &MS_VAR_0039,
    &MS_VAR_0040,
    &MS_VAR_0041,
    &MS_VAR_0042,
    &MS_VAR_0043,
    &MS_VAR_0044,
    &MS_VAR_0045,
    &MS_VAR_0046,
    &MS_VAR_0047,
    &MS_VAR_0048,
    &MS_VAR_0049,
    &MS_VAR_0050,
    &MS_VAR_0051,
    &MS_VAR_0052,
    &MS_VAR_0053,
    &MS_VAR_0054,
    &MS_VAR_0055,
    &MS_VAR_0056,
    &MS_VAR_0057,
    &MS_VAR_0058,
    &MS_VAR_0059,
    &MS_VAR_0060,
    &MS_VAR_0061,
    &MS_VAR_0062,
    &MS_VAR_0063,
    &MS_VAR_0064,
    &MS_VAR_0065,
    &MS_VAR_0066,
    &MS_VAR_0067,
    &MS_VAR_0068,
    &MS_VAR_0069,
    &MS_VAR_0070,
    &MS_VAR_0071,
    &MS_VAR_0072,
    &MS_VAR_0073,
    &MS_VAR_0074,
    &MS_VAR_0075,
    &MS_VAR_0076,
    &MS_VAR_0077,
    &MS_VAR_0078,
    &MS_VAR_0079,
    &MS_VAR_0080,
    &MS_VAR_0081,
    &MS_VAR_0082,
    &MS_VAR_0083,
    &MS_VAR_0084,
    &MS_VAR_0085,
    &MS_VAR_0086,
    &MS_VAR_0087,
    &MS_VAR_0088,
    &MS_VAR_0089,
    &MS_VAR_0090,
    &MS_VAR_0091,
    &MS_VAR_0092,
    &MS_VAR_0093,
    &MS_VAR_0094,
    &MS_VAR_0095,
    &MS_VAR_0096,
    &MS_VAR_0097,
    &MS_VAR_0098,
    &MS_VAR_0099,
    &MS_VAR_0100,
    &MS_VAR_0101,
    &MS_VAR_0102,
    &MS_VAR_0103,
    &MS_VAR_0104,
    &MS_VAR_0105,
    &MS_VAR_0106,
    &MS_VAR_0107,
    &MS_VAR_0108,
    &MS_VAR_0109,
    &MS_VAR_0110,
    &MS_VAR_0111,
    &MS_VAR_0112,
    &MS_VAR_0113,
    &MS_VAR_0114,
    &MS_VAR_0115,
    &MS_VAR_0116,
    &MS_VAR_0117,
    &MS_VAR_0118,
    &MS_VAR_0119,
    &MS_VAR_0120,
    &MS_VAR_0121,
    &MS_VAR_0122,
    &MS_VAR_0123,
    &MS_VAR_0124,
    &MS_VAR_0125,
    &MS_VAR_0126,
    &MS_VAR_0127,
    &MS_VAR_0128,
    &MS_VAR_0129,
    &MS_VAR_0130,
    &MS_VAR_0131,
    &MS_VAR_0132,
    &MS_VAR_0133,
    &MS_VAR_0134,
    &MS_VAR_0135,
    &MS_VAR_0136,
    &MS_VAR_0137,
    &MS_VAR_0138,
    &MS_VAR_0139,
    &MS_VAR_0140,
    &MS_VAR_0141,
    &MS_VAR_0142,
    &MS_VAR_0143,
    &MS_VAR_0144,
    &MS_VAR_0145,
    &MS_VAR_0146,
    &MS_VAR_0147,
    &MS_VAR_0148,
    &MS_VAR_0149,
    &MS_VAR_0150,
    &MS_VAR_0151,
    &MS_VAR_0152,
    &MS_VAR_0153,
    &MS_VAR_0154,
    &MS_VAR_0155,
    &MS_VAR_0156,
    &MS_VAR_0157,
    &MS_VAR_0158,
    &MS_VAR_0159,
    &MS_VAR_0160,
    &MS_VAR_0161,
    &MS_VAR_0162,
    &MS_VAR_0163,
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

const MS_Part *ms_parts = NULL;
const MS_RenderFrame *ms_render_frames = NULL;
const u16 *ms_module_render_frames = NULL;
const u16 *ms_frame_render_frames = NULL;
const MS_AnimStep *ms_anim_steps = NULL;
const MS_Animation *ms_animations = NULL;
const u16 *ms_scene_samples = NULL;
const MS_Scene *ms_scenes = NULL;

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

    ms_parts = NULL;
    ms_render_frames = NULL;
    ms_module_render_frames = NULL;
    ms_frame_render_frames = NULL;
    ms_anim_steps = NULL;
    ms_animations = NULL;
    ms_scene_samples = NULL;
    ms_scenes = NULL;

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
    g_strings_base = 0;
    g_strings_size = 0;
    g_data_ready = FALSE;
}

static u8 ms_safe_mul_u32(u32 a, u32 b, u32 *out)
{
    if (!out)
        return FALSE;
    if (a == 0 || b == 0)
    {
        *out = 0;
        return TRUE;
    }
    if (a > (0xFFFFFFFFu / b))
        return FALSE;
    *out = a * b;
    return TRUE;
}

static u8 ms_blob_range_ok(u32 offset, u32 size)
{
    if (offset > g_blob_size)
        return FALSE;
    if (size > (g_blob_size - offset))
        return FALSE;
    return TRUE;
}

static u8 ms_validate_string_offsets(const u8 *offsets, u16 count)
{
    u16 i;
    u32 end;

    if (count == 0)
        return TRUE;
    if (!offsets)
        return FALSE;
    if (g_strings_size == 0)
        return FALSE;

    end = g_strings_base + g_strings_size;
    for (i = 0; i < count; i++)
    {
        u32 off = ms_read_be32(offsets + ((u32)i * 4u));
        if (off < g_strings_base || off >= end)
            return FALSE;
    }
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
    ptr += 2; /* reserved */

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
    ms_part_count = ms_read_be32(ptr); ptr += 4;

    for (i = 0; i < MS_SEC_COUNT; i++)
    {
        g_section_offsets[i] = ms_read_be32(ptr);
        ptr += 4;
    }
    g_strings_size = ms_read_be32(ptr);

    if (ms_variant_count > MS_VARIANT_DEF_COUNT)
        ms_variant_count = MS_VARIANT_DEF_COUNT;

    ms_parts = (const MS_Part *)(g_blob + g_section_offsets[MS_SEC_PARTS]);
    ms_render_frames = (const MS_RenderFrame *)(g_blob + g_section_offsets[MS_SEC_RENDER_FRAMES]);
    ms_module_render_frames = (const u16 *)(g_blob + g_section_offsets[MS_SEC_MODULE_RENDER_FRAMES]);
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
