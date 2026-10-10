#include <genesis.h>
#include <string.h>
#include "modsprite.h"

#define MS_RUNTIME_SPRITE_LIMIT 80u

static u8 g_initialized = FALSE;
static u16 g_active_mapping = 0;
static MS_FrameProfile g_frame_profile = { 0, 0, 0, 0 };
static Sprite *g_runtime_sprites[MS_RUNTIME_SPRITE_LIMIT];
static u16 g_runtime_capacity = 0;
static u16 g_runtime_used = 0;
static u16 g_runtime_prev_used = 0;
static u16 g_runtime_attr = TILE_ATTR(PAL1, FALSE, FALSE, FALSE);
static u16 g_runtime_flags = SPR_FLAG_AUTO_VRAM_ALLOC | SPR_FLAG_AUTO_TILE_UPLOAD;

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

static u16 ms_max_render_part_count(void)
{
    u16 i;
    u16 max_parts = 0;

    for (i = 0; i < MS_RENDER_FRAME_COUNT; i++)
    {
        if (ms_render_frames[i].part_count > max_parts)
            max_parts = ms_render_frames[i].part_count;
    }

    if (max_parts > MS_RUNTIME_SPRITE_LIMIT)
        max_parts = MS_RUNTIME_SPRITE_LIMIT;
    return max_parts;
}

static const SpriteDefinition *ms_seed_definition(void)
{
    const SpriteDefinition *best = NULL;
    u16 i;

    for (i = 0; i < MS_VARIANT_COUNT; i++)
    {
        const SpriteDefinition *def = ms_variant_defs[i];
        if (!def)
            continue;
        if (!best)
        {
            best = def;
            continue;
        }
        if (def->maxNumTile > best->maxNumTile)
        {
            best = def;
            continue;
        }
        if ((def->maxNumTile == best->maxNumTile) && (def->maxNumSprite > best->maxNumSprite))
            best = def;
    }

    return best;
}

static void ms_init_runtime_sprites(void)
{
    const SpriteDefinition *seed_def;
    u16 target;
    u16 i;

    seed_def = ms_seed_definition();
    if (!seed_def)
        return;

    target = ms_max_render_part_count();
    for (i = 0; i < target; i++)
    {
        Sprite *sprite = SPR_addSpriteExSafe(
            seed_def,
            -128,
            -128,
            g_runtime_attr,
            g_runtime_flags
        );
        if (!sprite)
            break;
        SPR_setVisibility(sprite, HIDDEN);
        g_runtime_sprites[g_runtime_capacity++] = sprite;
    }
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

        if (g_runtime_used >= g_runtime_capacity)
        {
            if (g_runtime_capacity >= MS_RUNTIME_SPRITE_LIMIT)
            {
                g_frame_profile.add_failures = ms_sat_add_u16(g_frame_profile.add_failures, 1u);
                continue;
            }
            sprite = SPR_addSpriteExSafe(def, -128, -128, g_runtime_attr, g_runtime_flags);
            if (!sprite)
            {
                g_frame_profile.add_failures = ms_sat_add_u16(g_frame_profile.add_failures, 1u);
                continue;
            }
            SPR_setVisibility(sprite, HIDDEN);
            g_runtime_sprites[g_runtime_capacity++] = sprite;
        }

        sprite = g_runtime_sprites[g_runtime_used++];
        if (!sprite)
        {
            sprite = SPR_addSpriteExSafe(def, -128, -128, g_runtime_attr, g_runtime_flags);
            if (!sprite)
            {
                g_frame_profile.add_failures = ms_sat_add_u16(g_frame_profile.add_failures, 1u);
                continue;
            }
            SPR_setVisibility(sprite, HIDDEN);
            g_runtime_sprites[g_runtime_used - 1] = sprite;
        }
        if (sprite->definition != def)
        {
            if (!SPR_setDefinition(sprite, def))
            {
                SPR_releaseSprite(sprite);
                sprite = SPR_addSpriteExSafe(def, -128, -128, g_runtime_attr, g_runtime_flags);
                if (!sprite)
                {
                    g_runtime_sprites[g_runtime_used - 1] = NULL;
                    g_frame_profile.add_failures = ms_sat_add_u16(g_frame_profile.add_failures, 1u);
                    continue;
                }
                g_runtime_sprites[g_runtime_used - 1] = sprite;
            }
        }

        SPR_setPosition(sprite, ox + part->x, oy + part->y);
        SPR_setHFlip(sprite, part->hflip ? TRUE : FALSE);
        SPR_setVFlip(sprite, part->vflip ? TRUE : FALSE);
        SPR_setVisibility(sprite, VISIBLE);
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
    player->step_started = TRUE;
}

/* A pass is complete; TRUE when the animation's repeat count is used up. */
static u8 ms_anim_cycle_done(MS_AnimPlayer *player, const MS_Animation *anim)
{
    if (player->cycles < 0xFFFFu)
        player->cycles++;
    return (anim->loop_count > 0 && player->cycles >= anim->loop_count) ? TRUE : FALSE;
}

/* The animation ended: its follow-up takes over, otherwise playback stops on the current step. */
static void ms_anim_finish(MS_AnimPlayer *player, const MS_Animation *anim)
{
    if (anim->next_animation != MS_NO_ANIMATION && anim->next_animation < MS_ANIMATION_COUNT)
    {
        ms_anim_player_init(player, anim->next_animation);
        return;
    }
    player->finished = TRUE;
    player->ticks_left = 1;
}

void ms_init(void)
{
    if (g_initialized)
        return;

    ms_data_init();
    SPR_init();

    if (MS_VARIANT_COUNT > 0 && ms_variant_defs[0] && ms_variant_defs[0]->palette)
        PAL_setPalette(PAL1, ms_variant_defs[0]->palette->data, DMA);

    ms_set_mapping(0);
    ms_init_runtime_sprites();
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
    g_runtime_used = 0;
}

void ms_end_frame(void)
{
    u16 i;

    if (g_runtime_used < g_runtime_prev_used)
    {
        for (i = g_runtime_used; i < g_runtime_prev_used; i++)
        {
            if (g_runtime_sprites[i])
                SPR_setVisibility(g_runtime_sprites[i], HIDDEN);
        }
    }
    g_runtime_prev_used = g_runtime_used;
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
    player->step_started = FALSE;
    player->reserved0 = 0;
    player->cycles = 0;

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
    player->step_started = FALSE;
    if (count == 0 || player->finished)
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
            ms_anim_finish(player, anim);
            return;
        }
        ms_anim_apply_step(player, player->step_index + 1);
        return;
    }

    if (anim->playback == MS_PLAY_BACKWARD)
    {
        if (player->step_index == 0)
        {
            if (ms_anim_cycle_done(player, anim))
            {
                ms_anim_finish(player, anim);
                return;
            }
            ms_anim_apply_step(player, count - 1);
        }
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
                if (ms_anim_cycle_done(player, anim))
                {
                    ms_anim_finish(player, anim);
                    return;
                }
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

    /* MS_PLAY_LOOP: later passes start at loop_start, the steps before it play once. */
    if ((player->step_index + 1) >= count)
    {
        if (ms_anim_cycle_done(player, anim))
        {
            ms_anim_finish(player, anim);
            return;
        }
        ms_anim_apply_step(player, (anim->loop_start < count) ? anim->loop_start : 0);
        return;
    }
    ms_anim_apply_step(player, (u16)(player->step_index + 1));
}

static const MS_AnimStep *ms_anim_current_step(const MS_AnimPlayer *player)
{
    const MS_Animation *anim;

    if (!player)
        return NULL;
    anim = ms_current_animation(player->animation_index);
    if (!anim || player->step_index >= anim->step_count)
        return NULL;
    return &ms_anim_steps[anim->first_step + player->step_index];
}

u16 ms_anim_player_event_count(const MS_AnimPlayer *player)
{
    const MS_AnimStep *step = ms_anim_current_step(player);
    return step ? step->event_count : 0;
}

const MS_StepEvent *ms_anim_player_event(const MS_AnimPlayer *player, u16 index)
{
    const MS_AnimStep *step = ms_anim_current_step(player);
    u32 at;

    if (!step || index >= step->event_count)
        return NULL;
    at = (u32)step->first_event + (u32)index;
    if (at >= MS_STEP_EVENT_COUNT)
        return NULL;
    return &ms_step_events[at];
}

s16 ms_anim_player_event_value(const MS_AnimPlayer *player, u16 event_type, s16 fallback)
{
    u16 i;
    u16 count = ms_anim_player_event_count(player);

    for (i = 0; i < count; i++)
    {
        const MS_StepEvent *event = ms_anim_player_event(player, i);
        if (event && event->type == event_type)
            return event->value;
    }
    return fallback;
}

u8 ms_anim_player_has_event(const MS_AnimPlayer *player, u16 event_type)
{
    u16 i;
    u16 count = ms_anim_player_event_count(player);

    for (i = 0; i < count; i++)
    {
        const MS_StepEvent *event = ms_anim_player_event(player, i);
        if (event && event->type == event_type)
            return TRUE;
    }
    return FALSE;
}

u8 ms_anim_player_event_started(const MS_AnimPlayer *player, u16 event_type)
{
    return (player && player->step_started && ms_anim_player_has_event(player, event_type)) ? TRUE : FALSE;
}

const char *ms_event_name(u16 event_type)
{
    return ms_event_name_data(event_type);
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
    return ms_module_name_data(module_index);
}

const char *ms_frame_name(u16 frame_index)
{
    return ms_frame_name_data(frame_index);
}

const char *ms_animation_name(u16 animation_index)
{
    return ms_animation_name_data(animation_index);
}

const char *ms_scene_name(u16 scene_index)
{
    return ms_scene_name_data(scene_index);
}

const char *ms_mapping_name(u16 mapping_index)
{
    return ms_mapping_name_data(mapping_index);
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
        if (strcmp(ms_module_id(i), id) == 0)
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
        if (strcmp(ms_frame_id(i), id) == 0)
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
        if (strcmp(ms_animation_id(i), id) == 0)
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
        if (strcmp(ms_scene_id(i), id) == 0)
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
        if (strcmp(ms_mapping_id(i), id) == 0)
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
