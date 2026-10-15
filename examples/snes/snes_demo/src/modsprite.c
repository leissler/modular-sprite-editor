#include <snes.h>
#include <string.h>
#include "modsprite.h"

#define MS_MAX_SPRITES 128u
#define MS_NO_LINE 0xFFu
#define MS_MAX_ENTRIES 128u
#define MS_SCREEN_W 256
#define MS_SCREEN_H 224
/* Where unused entries wait: a small sprite there is on no line the PPU looks at (240 is below both the 224 and the
   239 line mode, so hidden sprites do not count against a line's 32; a 32-pixel one waits at 224, so it does not wrap
   round to the top). */
#define MS_HIDDEN_Y (MS_SMALL_SIZE <= 16 ? 240u : 224u)
#define MS_PRIORITY (2u << 4)  /* in front of every background (modsprite_draw.asm has it too) */
#define MS_CYCLE_SLOTS (MS_COLOUR_CYCLE_COUNT > 0 ? MS_COLOUR_CYCLE_COUNT : 1)

static u8 g_initialized = FALSE;
static u8 g_palettes_fit = FALSE;
static u16 g_active_mapping = 0;
/* Each mapping's first module, frame, animation and scene in the tables (one block per mapping), added up once by
   ms_init (a multiplication is a library call on the 65816). */
static u16 g_module_bases[MS_MAPPING_COUNT];
static u16 g_frame_bases[MS_MAPPING_COUNT];
static u16 g_animation_bases[MS_MAPPING_COUNT];
static u16 g_scene_bases[MS_MAPPING_COUNT];
static u16 g_vram = 0x0000;
static u16 g_first_palette = 0;
static u16 g_shown_last = MS_MAX_SPRITES;  /* entries the last frame used: the rest are already hidden */
/* Shared with modsprite_draw.asm (ms_put_render_frame, ms_finish_oam): the next OAM entry, the limit, the sprites that
   did not fit, the two sprite sizes, where unused entries wait, the attribute's palette bits of a run's palette byte under each palette swap (256
   a swap) and where the active swap's start, each sprite's two bits of the high table (X bit 8, size) at its OAM
   offset, which ms_end_frame packs into the table, and this frame's profile. */
u16 ms_hw_count = 0;
u16 ms_sprite_limit = MS_MAX_SPRITES;
u16 ms_dropped = 0;
u16 ms_small_size = MS_SMALL_SIZE;
u16 ms_large_size = MS_LARGE_SIZE;
u16 ms_hidden_y = MS_HIDDEN_Y;
u8 ms_swap_bits[MS_PALETTE_SWAP_COUNT * 256];
u16 ms_swap_bits_at = 0;
u8 ms_high_bits[MS_MAX_SPRITES * 4];
MS_FrameProfile ms_frame_profile;
/* Palette entries and sprite palettes: which palette each entry is in, which entry each palette shows, each entry's
   palette bits as the palettes are loaded, where each swap's entries start in ms_swap_entries. */
static u8 g_line_of[MS_MAX_ENTRIES];
static u8 g_line_entry[8];
static u8 g_line_bits[MS_MAX_ENTRIES];
static u16 g_swap_offsets[MS_PALETTE_SWAP_COUNT];
static u16 g_active_swap = 0;
/* What each sprite palette shows next, its colour cycles applied, and which ones ms_palette_tick has to put into CGRAM
   (prepared one tick ahead: CGRAM can only be written in vertical blank, and preparing takes a while). */
static u16 g_line_colours[8][16];
static u8 g_line_pending[8];
static u8 g_lines_pending = FALSE;
/* Colour cycles, one tick ahead of what CGRAM shows: video frames until each one's next step, its step ((frames since
   ms_init / its frames) % its count), and whether it stepped on the last tick. */
static u16 g_cycle_wait[MS_CYCLE_SLOTS];
static u8 g_cycle_step[MS_CYCLE_SLOTS];
static u8 g_cycle_moved[MS_CYCLE_SLOTS];

static u16 ms_mapping_module_base(void)
{
    return g_module_bases[g_active_mapping];
}

static u16 ms_mapping_frame_base(void)
{
    return g_frame_bases[g_active_mapping];
}

static u16 ms_mapping_animation_base(void)
{
    return g_animation_bases[g_active_mapping];
}

static u16 ms_mapping_scene_base(void)
{
    return g_scene_bases[g_active_mapping];
}

#ifdef MS_PUT_FRAME_C
/* The C versions of modsprite_draw.asm, which the host tests run (tools/check_snes_rom.py compares the two in an
   emulator). */

/* One hardware sprite into OAM entry ms_hw_count, unless it lies off the screen: the four bytes, and its X bit 8 and
   size bit for the high table. */
static u8 ms_push_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large)
{
    u16 size1 = (large ? ms_large_size : ms_small_size) - 1;
    u16 at;

    /* -size < x < 256 and -size < y < 224, one unsigned test each (as modsprite_draw.asm tests them) */
    if ((u16)(x + size1) >= (u16)(size1 + MS_SCREEN_W) || (u16)(y + size1) >= (u16)(size1 + MS_SCREEN_H))
        return TRUE;
    if (ms_hw_count >= ms_sprite_limit)
    {
        ms_dropped++;
        return FALSE;
    }
    at = ms_hw_count << 2;
    oamMemory[at] = (u8)x;
    oamMemory[at + 1] = (u8)y;  /* above the top: the sprite wraps from line 255, as the hardware draws it */
    oamMemory[at + 2] = (u8)tile;
    oamMemory[at + 3] = attribute | (u8)((tile >> 8) & 1);
    ms_high_bits[at] = (u8)(((x >> 8) & 1) | (large ? 2 : 0));
    ms_hw_count++;
    return TRUE;
}

/* A render frame's sprites (run_count runs: an MS_Run, then its sprites), in OAM order: the first in front. The SNES
   build runs modsprite_draw.asm instead, which does exactly this, with no tests per sprite when the frame lies on the
   screen with X >= 0 and all its sprites fit (see ms_draw_render_frame). Records are reached by offset: 816-tcc does
   not step far pointers reliably. */
void ms_put_render_frame(u16 render_index, s16 ox, s16 oy)
{
    const MS_RenderFrame *frame = ms_render_frame(render_index);
    const u8 *runs;
    u16 r, k, at = 0;

    ms_frame_profile.render_calls++;
    ms_frame_profile.parts_submitted += frame->part_count;
    if (!frame->run_count)
        return;
    runs = MS_FAR(frame->sprites_chunk, frame->sprites_offset);
    for (r = 0; r < frame->run_count; r++)
    {
        const MS_Run *run = (const MS_Run *)(runs + at);
        u8 bits = (u8)(MS_PRIORITY | ms_swap_bits[ms_swap_bits_at + run->palette]);
        u16 count = run->count;

        at += sizeof(MS_Run);
        for (k = 0; k < count; k++)
        {
            const MS_Sprite *sprite = (const MS_Sprite *)(runs + at);

            ms_push_sprite(ox + sprite->x, oy + sprite->y, sprite->tile | ((u16)(sprite->attribute & 1) << 8),
                           (u8)((sprite->attribute & 0xC0) | bits), sprite->size);
            at += sizeof(MS_Sprite);
        }
    }
    ms_frame_profile.hw_sprites = ms_hw_count;
    ms_frame_profile.sprites_dropped = ms_dropped;
}

/* The end of a frame: the entries count .. shown-1 (drawn last frame, not now) go below the screen, and the high
   table gets each drawn sprite's two bits, its bytes after the last group of four drawn sprites 0 up to the last
   frame's (the bytes after those are 0 already). modsprite_draw.asm on the SNES. */
void ms_finish_oam(u8 *high_table, u16 count, u16 shown)
{
    u16 n, end = (count + 3) & ~3u;

    for (n = count; n < shown; n++)
        oamMemory[(n << 2) + 1] = (u8)MS_HIDDEN_Y;
    for (n = count; n < end; n++)
        ms_high_bits[n << 2] = 0;
    for (n = 0; n < end; n += 4)
        high_table[n >> 2] = (u8)(ms_high_bits[n << 2] | (ms_high_bits[(n + 1) << 2] << 2)
                                  | (ms_high_bits[(n + 2) << 2] << 4) | (ms_high_bits[(n + 3) << 2] << 6));
    for (n = end >> 2; n < ((shown + 3) >> 2); n++)
        high_table[n] = 0;
}

u8 ms_add_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large)
{
    u8 added = ms_push_sprite(x, y, tile, attribute, large);
    ms_frame_profile.hw_sprites = ms_hw_count;
    ms_frame_profile.sprites_dropped = ms_dropped;
    return added;
}
#else
/* modsprite_draw.asm (ms_add_hw_sprite too) */
void ms_put_render_frame(u16 render_index, s16 ox, s16 oy);
void ms_finish_oam(u8 *high_table, u16 count, u16 shown);
#endif

static const MS_Animation *ms_current_animation(u16 animation_index)
{
    u16 table_index;

    if (animation_index >= MS_ANIMATION_COUNT)
        return NULL;
    table_index = ms_mapping_animation_base() + animation_index;
    if (table_index >= MS_ANIMATION_RECORD_COUNT)
        return NULL;
    return &ms_animations[table_index];
}

static const MS_Scene *ms_current_scene(u16 scene_index)
{
    u16 table_index;

    if (scene_index >= MS_SCENE_COUNT)
        return NULL;
    table_index = ms_mapping_scene_base() + scene_index;
    if (table_index >= MS_SCENE_RECORD_COUNT)
        return NULL;
    return &ms_scenes[table_index];
}

/* The SNES build skips the tests per sprite when the frame's box lies on the screen with X >= 0 (ox + min_x >= 0,
   ox + max_x < 256 + small, oy + min_y > -small, oy + max_y < 224 + small: every sprite then has 0 <= x < 256 and
   -size < y < 224) and all its sprites fit under the limit; what it draws is the same. */
static void ms_draw_render_frame(u16 render_index, s16 ox, s16 oy)
{
    if (render_index < MS_RENDER_FRAME_COUNT)
        ms_put_render_frame(render_index, ox, oy);
}

static void ms_anim_apply_step(MS_AnimPlayer *player, u16 step_index)
{
    const MS_Animation *anim;
    const MS_AnimStep *step;

    anim = ms_current_animation(player->animation_index);
    if (!anim || anim->step_count == 0)
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

/* The sprite palette an entry is drawn from: its own if it is loaded, else its palette's, else the first. */
static u16 ms_entry_line(u16 entry)
{
    if (entry >= MS_PALETTE_ENTRY_COUNT)
        return g_first_palette;
    if (g_line_of[entry] != MS_NO_LINE)
        return g_line_of[entry];
    entry = ms_palette_entries[entry].palette;
    if (entry < MS_PALETTE_ENTRY_COUNT && g_line_of[entry] != MS_NO_LINE)
        return g_line_of[entry];
    return g_first_palette;
}

/* After the palettes moved (ms_init, ms_load_palette): the attribute's palette bits of each run palette byte under
   every swap. A swap recolours the palettes themselves (their entries draw from the swap's entries), a swap's own
   entries and fixed pieces (MS_FIXED_ENTRY) keep theirs. Changing the swap then only picks a table. */
static void ms_refresh_palette_bits(void)
{
    u16 entry, swap, at;
    u16 count = MS_PALETTE_ENTRY_COUNT < MS_MAX_ENTRIES ? MS_PALETTE_ENTRY_COUNT : MS_MAX_ENTRIES - 1;

    for (entry = 0; entry < count; entry++)
        g_line_bits[entry] = (u8)(ms_entry_line(entry) << 1);
    for (swap = 0, at = 0; swap < MS_PALETTE_SWAP_COUNT; swap++, at += 256)
    {
        const u8 *swapped = ms_swap_entries + g_swap_offsets[swap];

        for (entry = 0; entry < count; entry++)
        {
            ms_swap_bits[at + entry] = g_line_bits[(swap && entry < MS_BASE_PALETTE_COUNT) ? swapped[entry] : entry];
            ms_swap_bits[at + (entry | MS_FIXED_ENTRY)] = g_line_bits[entry];
        }
    }
}

/* A sprite palette's colours with its entry's colour cycles at their steps, for ms_palette_tick to put into CGRAM: one
   cycle after the other, each moving its run's colours one slot up per step (down if reverse), as the editor's preview
   shows them (palettes.rotate). */
static void ms_prepare_line(u16 line)
{
    const MS_PaletteEntry *pe;
    const u16 *colours;
    u16 *out;
    u16 entry = g_line_entry[line];
    u16 c, k;
    u16 run[16];

    if (entry == MS_NO_LINE || entry >= MS_PALETTE_ENTRY_COUNT)
        return;
    pe = &ms_palette_entries[entry];
    colours = ms_palette + (entry << 4);
    out = g_line_colours[line];
    for (k = 0; k < 16; k++)
        out[k] = colours[k];
    for (c = 0; c < pe->cycle_count; c++)
    {
        const MS_ColourCycle *cycle = &ms_colour_cycles[pe->first_cycle + c];
        u16 count = cycle->count, first = cycle->first, steps = g_cycle_step[pe->first_cycle + c];
        u16 from;

        if (count < 2 || first < 1 || first + count > 16 || !steps)
            continue;
        for (k = 0; k < count; k++)
            run[k] = out[first + k];
        from = cycle->reverse ? steps : count - steps;  /* the run's slot its first slot shows: (0 - shift) mod count */
        for (k = 0; k < count; k++)
        {
            out[first + k] = run[from];
            if (++from >= count)
                from = 0;
        }
    }
    g_line_pending[line] = TRUE;
    g_lines_pending = TRUE;
}

/* The prepared sprite palettes into CGRAM (in vertical blank or forced blank). */
static void ms_upload_lines(void)
{
    u16 line;

    if (!g_lines_pending)
        return;
    for (line = 0; line < 8; line++)
    {
        if (g_line_pending[line])
        {
            dmaCopyCGram((u8 *)g_line_colours[line], 128 + (line << 4), 32);
            g_line_pending[line] = FALSE;
        }
    }
    g_lines_pending = FALSE;
}

/* The next step of every colour cycle, and the colours of the sprite palettes whose cycles moved. */
static void ms_step_cycles(void)
{
    u16 c, line;
    u8 moved = FALSE;

    for (c = 0; c < MS_COLOUR_CYCLE_COUNT; c++)
    {
        g_cycle_moved[c] = FALSE;
        if (--g_cycle_wait[c] == 0)
        {
            const MS_ColourCycle *cycle = &ms_colour_cycles[c];

            g_cycle_wait[c] = cycle->frames ? cycle->frames : 1;
            g_cycle_step[c] = (u8)((u16)(g_cycle_step[c] + 1) < cycle->count ? g_cycle_step[c] + 1 : 0);
            g_cycle_moved[c] = TRUE;
            moved = TRUE;
        }
    }
    if (!moved)
        return;
    for (line = 0; line < 8; line++)
    {
        u16 entry = g_line_entry[line];
        const MS_PaletteEntry *pe;

        if (entry == MS_NO_LINE || entry >= MS_PALETTE_ENTRY_COUNT)
            continue;
        pe = &ms_palette_entries[entry];
        for (c = 0; c < pe->cycle_count; c++)
        {
            if (g_cycle_moved[pe->first_cycle + c])
            {
                ms_prepare_line(line);
                break;
            }
        }
    }
}

void ms_init(void)
{
    ms_init_ex(0x0000, 0);
}

void ms_init_ex(u16 vram_address, u16 first_palette)
{
    u16 entry, t, n;

    if (g_initialized)
        return;
    ms_data_init();
    g_vram = vram_address & 0x6000;
    g_first_palette = first_palette & 7;
    g_active_swap = 0;
    ms_swap_bits_at = 0;
    for (n = 0; n < MS_COLOUR_CYCLE_COUNT; n++)
    {
        g_cycle_wait[n] = ms_colour_cycles[n].frames ? ms_colour_cycles[n].frames : 1;
        g_cycle_step[n] = 0;
        g_cycle_moved[n] = FALSE;
    }
    memset(g_line_of, MS_NO_LINE, sizeof(g_line_of));
    memset(g_line_entry, MS_NO_LINE, sizeof(g_line_entry));
    /* Both sprite tables, the second right after the first (OBSEL's name select 0). */
    for (t = 0; t < MS_TILE_TABLES; t++)
        dmaCopyVram((u8 *)ms_tile_tables[t], g_vram + t * 0x1000, 0x2000);
    oamInitGfxAttr(g_vram, MS_OBJ_SIZE);
    /* Every sprite hidden: below the screen, small, X below 256. */
    for (n = 0; n < MS_MAX_SPRITES; n++)
    {
        oamMemory[n << 2] = 0;
        oamMemory[(n << 2) + 1] = (u8)MS_HIDDEN_Y;
        oamMemory[(n << 2) + 2] = 0;
        oamMemory[(n << 2) + 3] = 0;
    }
    memset(&oamMemory[512], 0, 32);
    memset(ms_high_bits, 0, sizeof(ms_high_bits));
    /* The palette entries go into consecutive sprite palettes from the first one, as many as fit; a game with more
       entries than palettes loads the rest itself (ms_load_palette). */
    for (n = 0, t = 0; n < MS_MAPPING_COUNT; n++)
    {
        g_module_bases[n] = t;
        t += MS_MODULE_COUNT;
    }
    for (n = 0, t = 0; n < MS_MAPPING_COUNT; n++)
    {
        g_frame_bases[n] = t;
        t += MS_FRAME_COUNT;
    }
    for (n = 0, t = 0; n < MS_MAPPING_COUNT; n++)
    {
        g_animation_bases[n] = t;
        t += MS_ANIMATION_COUNT;
    }
    for (n = 0, t = 0; n < MS_MAPPING_COUNT; n++)
    {
        g_scene_bases[n] = t;
        t += MS_SCENE_COUNT;
    }
    g_swap_offsets[0] = 0;
    for (n = 1, t = 0; n < MS_PALETTE_SWAP_COUNT; n++)
    {
        g_swap_offsets[n] = t;
        t += MS_BASE_PALETTE_COUNT;
    }
    g_palettes_fit = (g_first_palette + MS_PALETTE_ENTRY_COUNT) <= 8;
    memset(g_line_pending, FALSE, sizeof(g_line_pending));
    g_lines_pending = FALSE;
    for (entry = 0; entry < MS_PALETTE_ENTRY_COUNT && g_first_palette + entry < 8; entry++)
    {
        g_line_of[entry] = (u8)(g_first_palette + entry);
        g_line_entry[g_first_palette + entry] = (u8)entry;
        ms_prepare_line(g_first_palette + entry);
    }
    ms_upload_lines();  /* the screen is off: now */
    ms_step_cycles();   /* the colours of the first tick, ready */
    ms_refresh_palette_bits();
    ms_set_mapping(0);
    g_shown_last = MS_MAX_SPRITES;  /* the first frame hides every entry it does not use */
    g_initialized = TRUE;
}

u8 ms_palettes_fit(void)
{
    return g_palettes_fit;
}

u16 ms_tile_base(void)
{
    return g_vram;
}

u16 ms_tiles_used(void)
{
    return (u16)MS_TILE_COUNT;
}

u16 ms_tiles_end(void)
{
    return (u16)MS_TILE_END;
}

void ms_set_sprite_limit(u16 limit)
{
    ms_sprite_limit = (limit > 0 && limit <= MS_MAX_SPRITES) ? limit : MS_MAX_SPRITES;
}

u16 ms_sprite_base(void)
{
    return ms_hw_count;
}

void ms_begin_frame(void)
{
    if (!g_initialized)
        ms_init();
    ms_frame_profile.render_calls = 0;
    ms_frame_profile.parts_submitted = 0;
    ms_frame_profile.hw_sprites = 0;
    ms_frame_profile.sprites_dropped = 0;
    ms_hw_count = 0;
    ms_dropped = 0;
}

void ms_end_frame(void)
{
    /* The entries this frame did not use go below the screen (small, X below 256), the ones hidden before stay hidden;
       the entries from the limit on are the game's. */
    u16 shown = g_shown_last < ms_sprite_limit ? g_shown_last : ms_sprite_limit;

    ms_finish_oam(&oamMemory[512], ms_hw_count, shown > ms_hw_count ? shown : ms_hw_count);
    g_shown_last = ms_hw_count;
}

void ms_draw_module(u16 module_index, s16 x, s16 y)
{
    if (module_index >= MS_MODULE_COUNT)
        return;
    ms_draw_render_frame(ms_module_render_frames[ms_mapping_module_base() + module_index], x, y);
}

void ms_draw_frame(u16 frame_index, s16 x, s16 y)
{
    if (frame_index >= MS_FRAME_COUNT)
        return;
    ms_draw_render_frame(ms_frame_render_frames[ms_mapping_frame_base() + frame_index], x, y);
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
                ms_anim_apply_step(player, player->step_index + 1);
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
                ms_anim_apply_step(player, player->step_index - 1);
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
    u16 at;

    if (!step || index >= step->event_count)
        return NULL;
    at = step->first_event + index;
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
    return ms_event_names(event_type);
}

void ms_draw_anim_player(const MS_AnimPlayer *player, s16 x, s16 y)
{
    const MS_AnimStep *step = ms_anim_current_step(player);

    if (step)
        ms_draw_render_frame(step->frame_index, x, y);
}

void ms_draw_anim_player_mapped(const MS_AnimPlayer *player, u16 mapping_index, s16 x, s16 y)
{
    u16 active = g_active_mapping;

    ms_set_mapping(mapping_index);
    ms_draw_anim_player(player, x, y);
    ms_set_mapping(active);
}

void ms_draw_anim_player_as(const MS_AnimPlayer *player, u16 mapping_index, u16 swap_index, s16 x, s16 y)
{
    u16 mapping = g_active_mapping;
    u16 swap = g_active_swap;

    ms_set_mapping(mapping_index);
    ms_set_palette_swap(swap_index);
    ms_draw_anim_player(player, x, y);
    ms_set_mapping(mapping);
    ms_set_palette_swap(swap);
}

void ms_load_palette(u16 entry, u16 line)
{
    if (entry >= MS_PALETTE_ENTRY_COUNT || entry >= MS_MAX_ENTRIES - 1 || line > 7)
        return;
    if (g_line_entry[line] != MS_NO_LINE)
        g_line_of[g_line_entry[line]] = MS_NO_LINE;  /* whatever was in that palette is not loaded any more */
    if (g_line_of[entry] != MS_NO_LINE)
        g_line_entry[g_line_of[entry]] = MS_NO_LINE;  /* the entry moves */
    g_line_of[entry] = (u8)line;
    g_line_entry[line] = (u8)entry;
    ms_prepare_line(line);  /* in CGRAM at the next ms_palette_tick */
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
    g_active_swap = swap_index;
    ms_swap_bits_at = swap_index << 8;
}

u16 ms_get_palette_swap(void)
{
    return g_active_swap;
}

void ms_palette_tick(void)
{
    ms_upload_lines();  /* first, while it is still vertical blank */
    ms_step_cycles();   /* then the next tick's colours, in RAM */
}

const char *ms_palette_swap_name(u16 swap_index)
{
    return ms_swap_names(swap_index);
}

const char *ms_palette_entry_name(u16 entry)
{
    return ms_palette_entry_names(entry);
}

static u16 ms_render_hitboxes(u16 render_index, const MS_Hitbox **out)
{
    const MS_RenderFrame *rf;

    if (out)
        *out = NULL;
    if (render_index >= MS_RENDER_FRAME_COUNT)
        return 0;
    rf = ms_render_frame(render_index);
    if (out && rf->box_count)
        *out = (const MS_Hitbox *)MS_FAR(rf->boxes_chunk, rf->boxes_offset);
    return rf->box_count;
}

static u16 ms_render_points(u16 render_index, const MS_Point **out)
{
    const MS_RenderFrame *rf;

    if (out)
        *out = NULL;
    if (render_index >= MS_RENDER_FRAME_COUNT)
        return 0;
    rf = ms_render_frame(render_index);
    if (out && rf->point_count)
        *out = (const MS_Point *)MS_FAR(rf->points_chunk, rf->points_offset);
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
    return ms_hitbox_type_names(type);
}

const char *ms_point_type_name(u16 type)
{
    return ms_point_type_names(type);
}

const char *ms_role_name(u16 role)
{
    return ms_role_names(role);
}

void ms_scene_player_init(MS_ScenePlayer *player, u16 scene_index)
{
    if (!player)
        return;
    player->scene_index = 0;
    player->tick = 0;
    player->sample = 0;
    player->phase = 0;
    if (scene_index < MS_SCENE_COUNT)
        player->scene_index = scene_index;
}

/* The sample shown is tick * fps / 60 (wrapped when the scene loops), kept up to date a tick at a time: dividing 32-bit
   numbers is slow on the 65816. */
void ms_scene_player_tick(MS_ScenePlayer *player)
{
    const MS_Scene *scene;

    if (!player)
        return;
    player->tick++;
    scene = ms_current_scene(player->scene_index);
    if (!scene || scene->sample_count == 0)
        return;
    player->phase += scene->fps;
    while (player->phase >= 60)
    {
        player->phase -= 60;
        if (player->sample < 0xFFFFu)
            player->sample++;
        if (scene->loop && player->sample >= scene->sample_count)
            player->sample = 0;
    }
}

void ms_draw_scene_player(const MS_ScenePlayer *player, s16 x, s16 y)
{
    const MS_Scene *scene;
    u16 sample_index;

    if (!player)
        return;
    scene = ms_current_scene(player->scene_index);
    if (!scene || scene->sample_count == 0)
        return;
    sample_index = player->sample;
    if (!scene->loop && (player->tick >= scene->duration_ticks || sample_index >= scene->sample_count))
        sample_index = scene->sample_count - 1;
    if (sample_index >= scene->sample_count)
        sample_index = 0;
    ms_draw_render_frame(ms_scene_samples[scene->first_sample + sample_index], x, y);
}

const char *ms_module_name(u16 module_index)
{
    return ms_module_names(module_index);
}

const char *ms_frame_name(u16 frame_index)
{
    return ms_frame_names(frame_index);
}

const char *ms_animation_name(u16 animation_index)
{
    return ms_animation_names(animation_index);
}

const char *ms_scene_name(u16 scene_index)
{
    return ms_scene_names(scene_index);
}

const char *ms_mapping_name(u16 mapping_index)
{
    return ms_mapping_names(mapping_index);
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

static s16 ms_find_id(const char *(*lookup)(u16), u16 first, u16 count, const char *id)
{
    u16 i;

    if (!id || !id[0])
        return -1;
    for (i = first; i < count; i++)
    {
        if (strcmp(lookup(i), id) == 0)
            return (s16)i;
    }
    return -1;
}

s16 ms_find_module_index_by_id(const char *id)
{
    return ms_find_id(ms_module_ids, 0, MS_MODULE_COUNT, id);
}

s16 ms_find_frame_index_by_id(const char *id)
{
    return ms_find_id(ms_frame_ids, 0, MS_FRAME_COUNT, id);
}

s16 ms_find_animation_index_by_id(const char *id)
{
    return ms_find_id(ms_animation_ids, 0, MS_ANIMATION_COUNT, id);
}

s16 ms_find_scene_index_by_id(const char *id)
{
    return ms_find_id(ms_scene_ids, 0, MS_SCENE_COUNT, id);
}

s16 ms_find_mapping_index_by_id(const char *id)
{
    return ms_find_id(ms_mapping_ids, 0, MS_MAPPING_COUNT, id);
}

s16 ms_find_palette_swap_index_by_id(const char *id)
{
    return ms_find_id(ms_swap_ids, 1, MS_PALETTE_SWAP_COUNT, id);
}

void ms_get_frame_profile(MS_FrameProfile *out_profile)
{
    if (out_profile)
        *out_profile = ms_frame_profile;
}
