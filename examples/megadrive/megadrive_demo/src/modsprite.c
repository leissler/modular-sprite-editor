#include <genesis.h>
#include <string.h>
#include "modsprite.h"

#define MS_DEFAULT_SPRITE_LIMIT 80u
#define MS_NO_LINE 0xFFu
#define MS_MAX_ENTRIES 128u

static u8 g_initialized = FALSE;
static u8 g_tiles_fit = FALSE;
static u8 g_palettes_fit = FALSE;
static u16 g_active_mapping = 0;
static MS_FrameProfile g_frame_profile = { 0, 0, 0, 0, 0 };
static u16 g_tile_base = TILE_USER_INDEX;
static u16 g_palette = PAL1;
static u16 g_sprite_limit = MS_DEFAULT_SPRITE_LIMIT;
static u16 g_hw_count = 0;
static u16 g_attr_base = TILE_ATTR_FULL(PAL0, FALSE, FALSE, FALSE, TILE_USER_INDEX);  /* palette bits per piece */
/* Palette entries and lines: which line each entry is in, which entry each line shows, and the attribute palette
   bits for a piece's entry byte (indexed with MS_FIXED_ENTRY too), refreshed when a swap or a line changes. */
static u8 g_line_of[MS_MAX_ENTRIES];
static u8 g_line_entry[4];
static u16 g_entry_bits[256];
static u16 g_active_swap = 0;
static u32 g_palette_frame = 0;
static u16 g_line_colours[4][16];  /* what each line shows, its colour cycles applied */
static u16 g_line_phase[4];        /* a mark of the cycle steps each line last showed */
static s16 g_screen_w = 320;
static s16 g_screen_h = 224;
#ifdef MS_STREAMED
/* A streamed export: what is drawn takes its tiles from a slot (the default one unless the game sets its own). */
#define MS_DEFAULT_SLOT_TILES (MS_SLOT_TILES > MS_SCENE_SLOT_TILES ? MS_SLOT_TILES : MS_SCENE_SLOT_TILES)
static MS_Slot g_default_slot = { TILE_USER_INDEX, MS_NOTHING_LOADED };
static MS_Slot *g_slot = &g_default_slot;
#endif

static u32 ms_mapping_module_base(void)
{
    return (u32)g_active_mapping * (u32)MS_MODULE_COUNT;
}

static u32 ms_mapping_frame_base(void)
{
    return (u32)g_active_mapping * (u32)MS_FRAME_COUNT;
}

static u32 ms_mapping_animation_base(void)
{
    return (u32)g_active_mapping * (u32)MS_ANIMATION_COUNT;
}

static u32 ms_mapping_scene_base(void)
{
    return (u32)g_active_mapping * (u32)MS_SCENE_COUNT;
}

/* One hardware sprite into the sprite table cache; off-screen ones are skipped (a sprite at
   x = -128 would also mask the sprites behind it on its lines). */
static inline u8 ms_push_sprite(s16 x, s16 y, u8 size, u16 attribute)
{
    VDPSprite *sprite;

    if (x >= g_screen_w || y >= g_screen_h || x + (s16)((((size >> 2) & 3) + 1) << 3) <= 0 || y + (s16)(((size & 3) + 1) << 3) <= 0)
        return TRUE;
    if (g_hw_count >= g_sprite_limit)
    {
        g_frame_profile.sprites_dropped++;
        return FALSE;
    }
    sprite = &vdpSpriteCache[g_hw_count++];
    sprite->y = y + 0x80;
    sprite->size = size;
    sprite->link = (u8)g_hw_count;
    sprite->attribut = attribute;
    sprite->x = x + 0x80;
    return TRUE;
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

#ifdef MS_STREAMED
/* The slot drawn through gets the render frame's tiles unless it holds them already: a DMA per run of tiles, queued to
   reach video memory with the sprite table at the next vertical blank. The pieces count their tiles from the slot.
   Queueing costs the 68000 time per run (the transfer itself happens in the vertical blank), so the runs go straight
   to DMA_queueDmaFast; only a run that crosses a 128 KB bank of the cartridge (DMA cannot) takes SGDK's splitting
   DMA_queueDma. A run SGDK refuses (its queue is full: 80 transfers unless DMA_setMaxQueueSize sets another size; or
   the frame is over the DMA capacity and the game set DMA_setIgnoreOverCapacity) leaves the slot holding nothing known,
   and the next draw through it queues the list again. */
static void ms_fill_slot(u16 render_index)
{
    u16 list = ms_render_frame_loads[render_index];

    if (g_slot->load_list != list && list < ms_load_list_count)
    {
        const MS_LoadList *load = &ms_load_lists[list];
        const MS_LoadEntry *entry = &ms_load_entries[load->first_entry];
        u16 tile = g_slot->tile_index;
        u8 queued = TRUE;
        u16 n;

        for (n = load->entry_count; n > 0; n--, entry++)
        {
            const u32 *from = ms_tiles + ((u32)entry->first_tile << 3);
            u16 words = (u16)(entry->tile_count << 4);

            if ((((u32)from & 0x1FFFFu) + ((u32)words << 1)) <= 0x20000u)
                queued &= DMA_queueDmaFast(DMA_VRAM, (void *)from, (u16)(tile << 5), words, 2);
            else
                queued &= DMA_queueDma(DMA_VRAM, (void *)from, (u16)(tile << 5), words, 2);
            tile += entry->tile_count;
        }
        g_slot->load_list = queued ? list : MS_NOTHING_LOADED;
        g_frame_profile.tiles_uploaded += load->tile_count;
    }
    g_attr_base = TILE_ATTR_FULL(PAL0, FALSE, FALSE, FALSE, g_slot->tile_index);
}
#endif

static void ms_draw_render_frame(u16 render_index, s16 ox, s16 oy)
{
    const MS_RenderFrame *frame;
    const MS_Part *part;
    u16 n;

    if (render_index >= MS_RENDER_FRAME_COUNT)
        return;
#ifdef MS_STREAMED
    ms_fill_slot(render_index);
#endif
    frame = &ms_render_frames[render_index];
    g_frame_profile.render_calls++;
    g_frame_profile.parts_submitted += frame->part_count;

    /* The last part is on top: it goes first into the sprite list. */
    part = &ms_parts[frame->first_part + frame->part_count];
    if (ox + frame->min_x >= 0 && oy + frame->min_y >= 0 && ox + frame->max_x <= g_screen_w
        && oy + frame->max_y <= g_screen_h && g_hw_count + frame->sprite_count <= g_sprite_limit)
    {
        /* All on screen and under the limit: copy the pieces without per-sprite tests. */
        VDPSprite *sprite = &vdpSpriteCache[g_hw_count];
        u16 link = g_hw_count;

        for (n = frame->part_count; n > 0; n--)
        {
            const MS_Piece *piece;
            u16 attribute, k;
            s16 x, y;

            part--;
            piece = &ms_pieces[part->first_piece];
            attribute = g_attr_base | ((u16)part->flip << 11);
            x = ox + part->x + 0x80;
            y = oy + part->y + 0x80;
            for (k = part->piece_count; k > 0; k--, piece++, sprite++)
            {
                sprite->y = y + piece->y;
                sprite->size = piece->size;
                sprite->link = (u8)++link;
                sprite->attribut = attribute + piece->tile_offset + g_entry_bits[piece->palette];
                sprite->x = x + piece->x;
            }
        }
        g_hw_count = link;
        g_frame_profile.hw_sprites = g_hw_count;
        return;
    }
    for (n = frame->part_count; n > 0; n--)
    {
        const MS_Piece *piece;
        u16 attribute, k;
        s16 x, y;

        part--;
        piece = &ms_pieces[part->first_piece];
        attribute = g_attr_base | ((u16)part->flip << 11);  /* bit 11 = H flip, bit 12 = V flip */
        x = ox + part->x;
        y = oy + part->y;
        for (k = part->piece_count; k > 0; k--, piece++)
            ms_push_sprite(x + piece->x, y + piece->y, piece->size,
                           attribute + piece->tile_offset + g_entry_bits[piece->palette]);
    }
    g_frame_profile.hw_sprites = g_hw_count;
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

/* The line an entry is drawn from: its own if it is loaded, else its palette's, else the first line. */
static u16 ms_entry_line(u16 entry)
{
    if (entry >= MS_PALETTE_ENTRY_COUNT)
        return g_palette;
    if (g_line_of[entry] != MS_NO_LINE)
        return g_line_of[entry];
    entry = ms_palette_entries[entry].palette;
    if (entry < MS_PALETTE_ENTRY_COUNT && g_line_of[entry] != MS_NO_LINE)
        return g_line_of[entry];
    return g_palette;
}

static void ms_refresh_palette_bits(void)
{
    u16 entry;
    u16 count = MS_PALETTE_ENTRY_COUNT < MS_MAX_ENTRIES ? MS_PALETTE_ENTRY_COUNT : MS_MAX_ENTRIES - 1;

    for (entry = 0; entry < count; entry++)
    {
        u16 shown = entry;

        /* The active swap recolours the palettes themselves; a swap's entries and fixed pieces keep theirs. */
        if (g_active_swap && entry < MS_BASE_PALETTE_COUNT)
            shown = ms_swap_entries[(u32)(g_active_swap - 1) * MS_BASE_PALETTE_COUNT + entry];
        g_entry_bits[entry] = ms_entry_line(shown) << 13;
        g_entry_bits[entry | MS_FIXED_ENTRY] = ms_entry_line(entry) << 13;
    }
}

/* Each colour cycle's step at the current frame, as one number (it changes when any step does). */
static u16 ms_line_phase(u16 line)
{
    const MS_PaletteEntry *pe = &ms_palette_entries[g_line_entry[line]];
    u16 c, phase = 0;

    for (c = 0; c < pe->cycle_count; c++)
    {
        const MS_ColourCycle *cycle = &ms_colour_cycles[pe->first_cycle + c];
        u16 frames = cycle->frames ? cycle->frames : 1;

        phase = (u16)(phase * 31u + (u16)((g_palette_frame / frames) % (cycle->count ? cycle->count : 1)) + 1u);
    }
    return phase;
}

/* Put a line's entry into CRAM, its colour cycles at the current frame: a cycle moves its colours one slot up per
   step (down if reverse), as the editor's preview shows it. */
static void ms_show_line(u16 line)
{
    const MS_PaletteEntry *pe;
    u16 entry = g_line_entry[line];
    u16 c, k;

    if (entry == MS_NO_LINE || entry >= MS_PALETTE_ENTRY_COUNT)
        return;
    pe = &ms_palette_entries[entry];
    memcpy(g_line_colours[line], ms_palette + (u32)entry * 16u, 32);
    for (c = 0; c < pe->cycle_count; c++)
    {
        const MS_ColourCycle *cycle = &ms_colour_cycles[pe->first_cycle + c];
        u16 count = cycle->count, first = cycle->first, frames = cycle->frames ? cycle->frames : 1;
        u16 steps, shift;
        u16 run[16];

        if (count < 2 || first < 1 || first + count > 16)
            continue;
        steps = (u16)((g_palette_frame / frames) % count);
        if (!steps)
            continue;
        shift = cycle->reverse ? (u16)(count - steps) : steps;
        memcpy(run, &g_line_colours[line][first], (u32)count * 2u);
        for (k = 0; k < count; k++)
            g_line_colours[line][first + k] = run[(k + count - shift) % count];
    }
    g_line_phase[line] = ms_line_phase(line);
    PAL_setColors(line * 16, g_line_colours[line], 16, DMA);
}

void ms_init(void)
{
    ms_init_ex(TILE_USER_INDEX, PAL1);
}

void ms_init_ex(u16 tile_index, u16 palette)
{
    if (g_initialized)
        return;

    ms_data_init();
    g_tile_base = tile_index;
    g_palette = palette & 3;
    g_attr_base = TILE_ATTR_FULL(PAL0, FALSE, FALSE, FALSE, g_tile_base);
    g_tiles_fit = FALSE;
    g_palettes_fit = FALSE;
    g_active_swap = 0;
    g_palette_frame = 0;
    memset(g_line_of, MS_NO_LINE, sizeof(g_line_of));
    memset(g_line_entry, MS_NO_LINE, sizeof(g_line_entry));
    if (ms_data_is_ready())
    {
        u16 entry;

#ifdef MS_STREAMED
        /* Nothing to load now: the default slot takes the tiles from here as things are drawn through it. */
        g_tiles_fit = ((u32)g_tile_base + (u32)MS_DEFAULT_SLOT_TILES) <= (u32)TILE_FONT_INDEX;
        ms_slot_init(&g_default_slot, g_tile_base);
        g_slot = &g_default_slot;
#else
        g_tiles_fit = ((u32)g_tile_base + (u32)MS_TILE_COUNT) <= (u32)TILE_FONT_INDEX;
        if (g_tiles_fit && MS_TILE_COUNT > 0)
            VDP_loadTileData(ms_tiles, g_tile_base, MS_TILE_COUNT, DMA);
#endif
        /* The palette entries go into consecutive lines from the first one, as many as fit; a game with more
           entries than lines loads the rest itself (ms_load_palette). */
        g_palettes_fit = (g_palette + MS_PALETTE_ENTRY_COUNT) <= 4;
        for (entry = 0; entry < MS_PALETTE_ENTRY_COUNT && g_palette + entry < 4; entry++)
        {
            g_line_of[entry] = (u8)(g_palette + entry);
            g_line_entry[g_palette + entry] = (u8)entry;
            ms_show_line(g_palette + entry);
        }
    }
    ms_refresh_palette_bits();
    ms_set_mapping(0);
    g_initialized = TRUE;
}

u8 ms_tiles_fit(void)
{
    return g_tiles_fit;
}

u8 ms_palettes_fit(void)
{
    return g_palettes_fit;
}

u16 ms_tile_base(void)
{
    return g_tile_base;
}

u16 ms_tiles_used(void)
{
#ifdef MS_STREAMED
    return (u16)MS_DEFAULT_SLOT_TILES;
#else
    return (u16)MS_TILE_COUNT;
#endif
}

void ms_slot_init(MS_Slot *slot, u16 tile_index)
{
    if (!slot)
        return;
    slot->tile_index = tile_index;
    slot->load_list = MS_NOTHING_LOADED;
}

void ms_set_slot(MS_Slot *slot)
{
#ifdef MS_STREAMED
    g_slot = slot ? slot : &g_default_slot;
#else
    (void)slot;
#endif
}

u16 ms_slot_tiles(void)
{
#ifdef MS_STREAMED
    return (u16)MS_SLOT_TILES;
#else
    return 0;
#endif
}

u16 ms_scene_slot_tiles(void)
{
#ifdef MS_STREAMED
    return (u16)MS_SCENE_SLOT_TILES;
#else
    return 0;
#endif
}

void ms_set_sprite_limit(u16 limit)
{
    g_sprite_limit = (limit > 0 && limit <= MS_DEFAULT_SPRITE_LIMIT) ? limit : MS_DEFAULT_SPRITE_LIMIT;
}

void ms_begin_frame(void)
{
    if (!g_initialized)
        ms_init();

    g_frame_profile.render_calls = 0;
    g_frame_profile.parts_submitted = 0;
    g_frame_profile.hw_sprites = 0;
    g_frame_profile.sprites_dropped = 0;
    g_frame_profile.tiles_uploaded = 0;
    g_hw_count = 0;
    g_screen_w = (s16)VDP_getScreenWidth();
    g_screen_h = (s16)VDP_getScreenHeight();
}

u8 ms_add_hw_sprite(s16 x, s16 y, u8 size, u16 attribute)
{
    u8 added = ms_push_sprite(x, y, size, attribute);
    g_frame_profile.hw_sprites = g_hw_count;
    return added;
}

void ms_end_frame(void)
{
    u16 count = g_hw_count;

    if (count == 0)
    {
        /* An empty list: one sprite parked above the screen. */
        vdpSpriteCache[0].y = 0;
        vdpSpriteCache[0].size = 0;
        vdpSpriteCache[0].link = 0;
        vdpSpriteCache[0].attribut = 0;
        vdpSpriteCache[0].x = 1;
        count = 1;
    }
    else
        vdpSpriteCache[count - 1].link = 0;
    VDP_updateSprites(count, DMA_QUEUE);
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

void ms_draw_anim_player_mapped(const MS_AnimPlayer *player, u16 mapping_index, s16 x, s16 y)
{
    u16 active = g_active_mapping;

    ms_set_mapping(mapping_index);
    ms_draw_anim_player(player, x, y);
    g_active_mapping = active;
}

void ms_draw_anim_player_as(const MS_AnimPlayer *player, u16 mapping_index, u16 swap_index, s16 x, s16 y)
{
    u16 mapping = g_active_mapping;
    u16 swap = g_active_swap;

    ms_set_mapping(mapping_index);
    ms_set_palette_swap(swap_index);
    ms_draw_anim_player(player, x, y);
    g_active_mapping = mapping;
    ms_set_palette_swap(swap);
}

void ms_load_palette(u16 entry, u16 line)
{
    if (entry >= MS_PALETTE_ENTRY_COUNT || entry >= MS_MAX_ENTRIES - 1 || line > 3)
        return;
    if (g_line_entry[line] != MS_NO_LINE)
        g_line_of[g_line_entry[line]] = MS_NO_LINE;  /* whatever was in that line is not loaded any more */
    if (g_line_of[entry] != MS_NO_LINE)
        g_line_entry[g_line_of[entry]] = MS_NO_LINE;  /* the entry moves */
    g_line_of[entry] = (u8)line;
    g_line_entry[line] = (u8)entry;
    ms_show_line(line);
    ms_refresh_palette_bits();
}

s16 ms_palette_line(u16 entry)
{
    if (entry >= MS_PALETTE_ENTRY_COUNT || g_line_of[entry] == MS_NO_LINE)
        return -1;
    return g_line_of[entry];
}

void ms_set_palette_swap(u16 swap_index)
{
    if (swap_index >= MS_PALETTE_SWAP_COUNT)
        swap_index = 0;
    if (swap_index != g_active_swap)
    {
        g_active_swap = swap_index;
        ms_refresh_palette_bits();
    }
}

u16 ms_get_palette_swap(void)
{
    return g_active_swap;
}

void ms_palette_tick(void)
{
    u16 line;

    g_palette_frame++;
    for (line = 0; line < 4; line++)
    {
        u16 entry = g_line_entry[line];

        if (entry == MS_NO_LINE || entry >= MS_PALETTE_ENTRY_COUNT || !ms_palette_entries[entry].cycle_count)
            continue;
        if (ms_line_phase(line) != g_line_phase[line])
            ms_show_line(line);
    }
}

const char *ms_palette_swap_name(u16 swap_index)
{
    return ms_palette_swap_name_data(swap_index);
}

const char *ms_palette_entry_name(u16 entry)
{
    return ms_palette_entry_name_data(entry);
}

static u16 ms_render_hitboxes(u16 render_index, const MS_Hitbox **out)
{
    const MS_RenderFrame *rf;

    if (out)
        *out = NULL;
    if (render_index >= MS_RENDER_FRAME_COUNT)
        return 0;
    rf = &ms_render_frames[render_index];
    if (out && rf->hitbox_count)
        *out = &ms_hitboxes[rf->first_hitbox];
    return rf->hitbox_count;
}

static u16 ms_render_points(u16 render_index, const MS_Point **out)
{
    const MS_RenderFrame *rf;

    if (out)
        *out = NULL;
    if (render_index >= MS_RENDER_FRAME_COUNT)
        return 0;
    rf = &ms_render_frames[render_index];
    if (out && rf->point_count)
        *out = &ms_points[rf->first_point];
    return rf->point_count;
}

static u16 ms_frame_render_index(u16 frame_index)
{
    if (frame_index >= MS_FRAME_COUNT)
        return 0xFFFFu;
    return ms_frame_render_frames[ms_mapping_frame_base() + frame_index];
}

u16 ms_frame_hitboxes(u16 frame_index, const MS_Hitbox **out)
{
    return ms_render_hitboxes(ms_frame_render_index(frame_index), out);
}

u16 ms_frame_points(u16 frame_index, const MS_Point **out)
{
    return ms_render_points(ms_frame_render_index(frame_index), out);
}

u16 ms_anim_player_hitboxes(const MS_AnimPlayer *player, const MS_Hitbox **out)
{
    const MS_AnimStep *step = ms_anim_current_step(player);
    return ms_render_hitboxes(step ? step->frame_index : 0xFFFFu, out);
}

u16 ms_anim_player_points(const MS_AnimPlayer *player, const MS_Point **out)
{
    const MS_AnimStep *step = ms_anim_current_step(player);
    return ms_render_points(step ? step->frame_index : 0xFFFFu, out);
}

const MS_Hitbox *ms_find_hitbox(const MS_Hitbox *boxes, u16 count, u16 type, u16 role)
{
    u16 i;

    for (i = 0; boxes && i < count; i++)
    {
        if (boxes[i].type == type && (role == MS_NO_ROLE || boxes[i].role == role))
            return &boxes[i];
    }
    return NULL;
}

const MS_Point *ms_find_point(const MS_Point *points, u16 count, u16 type, u16 role)
{
    u16 i;

    for (i = 0; points && i < count; i++)
    {
        if (points[i].type == type && (role == MS_NO_ROLE || points[i].role == role))
            return &points[i];
    }
    return NULL;
}

const char *ms_hitbox_type_name(u16 type)
{
    return ms_hitbox_type_name_data(type);
}

const char *ms_point_type_name(u16 type)
{
    return ms_point_type_name_data(type);
}

const char *ms_role_name(u16 role)
{
    return ms_role_name_data(role);
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

s16 ms_find_palette_swap_index_by_id(const char *id)
{
    u16 i;

    if (!id || !id[0])
        return -1;
    for (i = 1; i < MS_PALETTE_SWAP_COUNT; i++)
    {
        if (strcmp(ms_palette_swap_id(i), id) == 0)
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
