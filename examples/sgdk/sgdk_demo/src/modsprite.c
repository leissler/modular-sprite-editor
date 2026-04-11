#include <genesis.h>
#include <string.h>
#include "modsprite.h"

static u8 g_initialized = FALSE;
static u16 g_active_mapping = 0;
static MS_FrameProfile g_frame_profile = { 0, 0, 0, 0 };

static u16 ms_sat_add_u16(u16 value, u16 add)
{
    u32 sum = (u32)value + (u32)add;
    if (sum > 0xFFFFu)
        return 0xFFFFu;
    return (u16)sum;
}

static u32 ms_mapping_module_base(void)
{
    return ((u32)g_active_mapping) * ((u32)MS_MODULE_COUNT);
}

static u32 ms_mapping_frame_base(void)
{
    return ((u32)g_active_mapping) * ((u32)MS_FRAME_COUNT);
}

static u32 ms_mapping_animation_base(void)
{
    return ((u32)g_active_mapping) * ((u32)MS_ANIMATION_COUNT);
}

static u32 ms_mapping_scene_base(void)
{
    return ((u32)g_active_mapping) * ((u32)MS_SCENE_COUNT);
}

static const MS_Animation *ms_current_animation(u16 animation_index)
{
    u32 table_index;

    if (animation_index >= MS_ANIMATION_COUNT)
        return NULL;
    table_index = ms_mapping_animation_base() + animation_index;
    if (table_index >= MS_ANIMATION_RECORD_COUNT)
        return NULL;
    return &ms_animations[table_index];
}

static const MS_Scene *ms_current_scene(u16 scene_index)
{
    u32 table_index;

    if (scene_index >= MS_SCENE_COUNT)
        return NULL;
    table_index = ms_mapping_scene_base() + scene_index;
    if (table_index >= MS_SCENE_RECORD_COUNT)
        return NULL;
    return &ms_scenes[table_index];
}

static void ms_draw_render_frame(u16 render_index, s16 ox, s16 oy)
{
    s32 i;
    u32 first;
    u32 end;

    if (render_index >= MS_RENDER_FRAME_COUNT)
        return;

    g_frame_profile.render_calls = ms_sat_add_u16(g_frame_profile.render_calls, 1u);

    first = ms_render_frames[render_index].first_part;
    end = first + ms_render_frames[render_index].part_count;

    for (i = (s32)end - 1; i >= (s32)first; i--)
    {
        const MS_Part *part;
        const SpriteDefinition *def;
        Sprite *sprite;

        part = &ms_parts[(u32)i];
        if (part->variant_index >= MS_VARIANT_COUNT)
            continue;

        def = ms_variant_defs[part->variant_index];
        if (!def)
            continue;

        g_frame_profile.parts_submitted = ms_sat_add_u16(g_frame_profile.parts_submitted, 1u);
        g_frame_profile.hw_sprites_estimated = ms_sat_add_u16(g_frame_profile.hw_sprites_estimated, def->maxNumSprite);

        sprite = SPR_addSprite(
            def,
            ox + part->x,
            oy + part->y,
            TILE_ATTR(PAL1, FALSE, part->vflip ? TRUE : FALSE, part->hflip ? TRUE : FALSE)
        );
        if (!sprite)
            g_frame_profile.add_failures = ms_sat_add_u16(g_frame_profile.add_failures, 1u);
    }
}

static void ms_anim_apply_step(MS_AnimPlayer *player, u16 step_index)
{
    const MS_Animation *anim;
    const MS_AnimStep *step;

    anim = ms_current_animation(player->animation_index);
    if (!anim)
    {
        player->step_index = 0;
        player->ticks_left = 1;
        return;
    }
    if (anim->step_count == 0)
    {
        player->step_index = 0;
        player->ticks_left = 1;
        return;
    }

    if (step_index >= anim->step_count)
        step_index = anim->step_count - 1;

    player->step_index = step_index;
    step = &ms_anim_steps[anim->first_step + player->step_index];
    player->ticks_left = (s16)((step->duration_ticks > 0) ? step->duration_ticks : 1);
}

void ms_init(void)
{
    if (g_initialized)
        return;

    SPR_init();

    if (MS_VARIANT_COUNT > 0 && ms_variant_defs[0] && ms_variant_defs[0]->palette)
        PAL_setPalette(PAL1, ms_variant_defs[0]->palette->data, DMA);

    ms_set_mapping(0);
    g_initialized = TRUE;
}

void ms_begin_frame(void)
{
    if (!g_initialized)
        ms_init();

    g_frame_profile.render_calls = 0;
    g_frame_profile.parts_submitted = 0;
    g_frame_profile.hw_sprites_estimated = 0;
    g_frame_profile.add_failures = 0;
    SPR_reset();
}

void ms_end_frame(void)
{
    SPR_update();
}

void ms_draw_module(u16 module_index, s16 x, s16 y)
{
    u32 table_index;
    u32 table_count;

    if (module_index >= MS_MODULE_COUNT)
        return;

    table_index = ms_mapping_module_base() + module_index;
    table_count = ((u32)MS_MAPPING_COUNT) * ((u32)MS_MODULE_COUNT);
    if (table_index >= table_count)
        return;
    ms_draw_render_frame(ms_module_render_frames[table_index], x, y);
}

void ms_draw_frame(u16 frame_index, s16 x, s16 y)
{
    u32 table_index;
    u32 table_count;

    if (frame_index >= MS_FRAME_COUNT)
        return;

    table_index = ms_mapping_frame_base() + frame_index;
    table_count = ((u32)MS_MAPPING_COUNT) * ((u32)MS_FRAME_COUNT);
    if (table_index >= table_count)
        return;
    ms_draw_render_frame(ms_frame_render_frames[table_index], x, y);
}

void ms_anim_player_init(MS_AnimPlayer *player, u16 animation_index)
{
    const MS_Animation *anim;

    if (!player)
        return;

    player->animation_index = 0;
    player->step_index = 0;
    player->ticks_left = 1;
    player->direction = 1;
    player->finished = FALSE;

    if (animation_index >= MS_ANIMATION_COUNT)
        return;

    player->animation_index = animation_index;
    anim = ms_current_animation(player->animation_index);
    if (!anim)
        return;

    if (anim->playback == MS_PLAY_BACKWARD)
    {
        player->direction = -1;
        ms_anim_apply_step(player, (anim->step_count > 0) ? (anim->step_count - 1) : 0);
    }
    else
    {
        player->direction = 1;
        ms_anim_apply_step(player, 0);
    }
}

void ms_anim_player_tick(MS_AnimPlayer *player)
{
    const MS_Animation *anim;
    u16 count;

    if (!player)
        return;

    anim = ms_current_animation(player->animation_index);
    if (!anim)
        return;
    count = anim->step_count;
    if (count == 0)
        return;

    if (player->ticks_left > 1)
    {
        player->ticks_left--;
        return;
    }

    if (anim->playback == MS_PLAY_ONCE)
    {
        if ((player->step_index + 1) >= count)
        {
            player->finished = TRUE;
            player->ticks_left = 1;
            return;
        }
        ms_anim_apply_step(player, player->step_index + 1);
        return;
    }

    if (anim->playback == MS_PLAY_BACKWARD)
    {
        if (player->step_index == 0)
            ms_anim_apply_step(player, count - 1);
        else
            ms_anim_apply_step(player, player->step_index - 1);
        return;
    }

    if (anim->playback == MS_PLAY_PING_PONG)
    {
        if (count <= 1)
        {
            ms_anim_apply_step(player, 0);
            return;
        }

        if (player->direction >= 0)
        {
            if ((player->step_index + 1) >= count)
            {
                player->direction = -1;
                ms_anim_apply_step(player, (player->step_index > 0) ? (player->step_index - 1) : 0);
            }
            else
            {
                ms_anim_apply_step(player, player->step_index + 1);
            }
        }
        else
        {
            if (player->step_index == 0)
            {
                player->direction = 1;
                ms_anim_apply_step(player, (count > 1) ? 1 : 0);
            }
            else
            {
                ms_anim_apply_step(player, player->step_index - 1);
            }
        }
        return;
    }

    ms_anim_apply_step(player, (u16)((player->step_index + 1) % count));
}

void ms_draw_anim_player(const MS_AnimPlayer *player, s16 x, s16 y)
{
    const MS_Animation *anim;
    const MS_AnimStep *step;

    if (!player)
        return;

    anim = ms_current_animation(player->animation_index);
    if (!anim)
        return;
    if (anim->step_count == 0)
        return;

    if (player->step_index >= anim->step_count)
        return;

    step = &ms_anim_steps[anim->first_step + player->step_index];
    ms_draw_render_frame(step->frame_index, x, y);
}

void ms_scene_player_init(MS_ScenePlayer *player, u16 scene_index)
{
    if (!player)
        return;

    player->scene_index = 0;
    player->tick = 0;

    if (scene_index < MS_SCENE_COUNT)
        player->scene_index = scene_index;
}

void ms_scene_player_tick(MS_ScenePlayer *player)
{
    if (!player)
        return;
    player->tick++;
}

void ms_draw_scene_player(const MS_ScenePlayer *player, s16 x, s16 y)
{
    const MS_Scene *scene;
    u32 sample_index;
    u32 scaled;

    if (!player)
        return;

    scene = ms_current_scene(player->scene_index);
    if (!scene)
        return;
    if (scene->sample_count == 0)
        return;

    scaled = (player->tick * scene->fps) / 60;
    sample_index = scaled;

    if (scene->loop)
    {
        sample_index %= scene->sample_count;
    }
    else
    {
        if (player->tick >= scene->duration_ticks)
            sample_index = scene->sample_count - 1;
        else if (sample_index >= scene->sample_count)
            sample_index = scene->sample_count - 1;
    }

    ms_draw_render_frame(ms_scene_samples[scene->first_sample + sample_index], x, y);
}

const char *ms_module_name(u16 module_index)
{
    if (module_index >= MS_MODULE_COUNT)
        return "";
    return ms_module_names[module_index];
}

const char *ms_frame_name(u16 frame_index)
{
    if (frame_index >= MS_FRAME_COUNT)
        return "";
    return ms_frame_names[frame_index];
}

const char *ms_animation_name(u16 animation_index)
{
    if (animation_index >= MS_ANIMATION_COUNT)
        return "";
    return ms_animation_names[animation_index];
}

const char *ms_scene_name(u16 scene_index)
{
    if (scene_index >= MS_SCENE_COUNT)
        return "";
    return ms_scene_names[scene_index];
}

const char *ms_mapping_name(u16 mapping_index)
{
    if (mapping_index >= MS_MAPPING_COUNT)
        return "";
    return ms_mapping_names[mapping_index];
}

void ms_set_mapping(u16 mapping_index)
{
    if (mapping_index >= MS_MAPPING_COUNT)
        mapping_index = 0;
    g_active_mapping = mapping_index;
}

u16 ms_get_mapping(void)
{
    return g_active_mapping;
}

s16 ms_find_module_index_by_id(const char *id)
{
    u16 i;

    if (!id || !id[0])
        return -1;

    for (i = 0; i < MS_MODULE_COUNT; i++)
    {
        if (strcmp(ms_module_ids[i], id) == 0)
            return (s16)i;
    }
    return -1;
}

s16 ms_find_frame_index_by_id(const char *id)
{
    u16 i;

    if (!id || !id[0])
        return -1;

    for (i = 0; i < MS_FRAME_COUNT; i++)
    {
        if (strcmp(ms_frame_ids[i], id) == 0)
            return (s16)i;
    }
    return -1;
}

s16 ms_find_animation_index_by_id(const char *id)
{
    u16 i;

    if (!id || !id[0])
        return -1;

    for (i = 0; i < MS_ANIMATION_COUNT; i++)
    {
        if (strcmp(ms_animation_ids[i], id) == 0)
            return (s16)i;
    }
    return -1;
}

s16 ms_find_scene_index_by_id(const char *id)
{
    u16 i;

    if (!id || !id[0])
        return -1;

    for (i = 0; i < MS_SCENE_COUNT; i++)
    {
        if (strcmp(ms_scene_ids[i], id) == 0)
            return (s16)i;
    }
    return -1;
}

s16 ms_find_mapping_index_by_id(const char *id)
{
    u16 i;

    if (!id || !id[0])
        return -1;

    for (i = 0; i < MS_MAPPING_COUNT; i++)
    {
        if (strcmp(ms_mapping_ids[i], id) == 0)
            return (s16)i;
    }
    return -1;
}

void ms_get_frame_profile(MS_FrameProfile *out_profile)
{
    if (!out_profile)
        return;

    *out_profile = g_frame_profile;
}
