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
#define MS_SPRITE_TILES 512u   /* both sprite tables */
#ifndef MS_CACHE_SLOTS
#define MS_CACHE_SLOTS 48      /* the slot cache's slots (ms_slot_cache_init); 0 leaves the cache out */
#endif
#ifndef MS_GIVE_WAY_DRAWS
#define MS_GIVE_WAY_DRAWS 32   /* give-way draws a frame writes that can still make room (ms_set_give_way) */
#endif
#ifndef MS_QUEUED_DRAWS
#define MS_QUEUED_DRAWS 32     /* draws a frame keeps waiting from its first that did not fit; 0 leaves the levels out */
#endif
#if MS_CACHE_SLOTS > 254 || MS_GIVE_WAY_DRAWS > 128
#error "MS_CACHE_SLOTS goes up to 254, MS_GIVE_WAY_DRAWS to 128"
#endif

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
/* The first tile of the slot drawn through, which modsprite_draw.asm adds to every sprite's tile (0 when every tile is
   in video memory). */
u16 ms_slot_base = 0;
/* Shared with modsprite_draw.asm (ms_send_uploads), which every build assembles: a streamed export's load lists queued
   for the next vertical blank and each one's slot's VRAM word address (an export that keeps every tile in video memory
   queues none). */
#define MS_MAX_UPLOADS 8u
u16 ms_upload_count = 0;
u16 ms_upload_lists[MS_MAX_UPLOADS];
u16 ms_upload_vram[MS_MAX_UPLOADS];
/* Shared with modsprite_draw.asm (ms_cache_hit), in every build (as small as can be where a resident export or no
   cache leaves them unused): the slot drawn through, the frame number (a slot shows one thing a frame) and the slot
   cache (ms_slot_cache_init): a slot per load list in one pool of whole sprite-table rows, each entry in the bucket of
   its list's low bits (found in a step or two) and in tile order (where first fit looks for room), or free; 16 bytes,
   so 816-tcc and the asm reach one with a shift. */
#define MS_CACHE_BUCKETS 64u
#define MS_NO_ENTRY 0xFFu
typedef struct
{
    MS_Slot slot;  /* its first tile, and what video memory holds there */
    u16 list;      /* the load list it is kept for; MS_NOTHING_LOADED: a free entry */
    u16 tiles;     /* the tiles its list's rows take from slot.tile_index */
    u16 drawn;     /* the frame it was drawn in last */
    u8 next;       /* the next entry in its bucket (a free entry: the next free one) */
    u8 after;      /* the entry after it in tile order */
} MS_CachedSlot;
#if defined(MS_STREAMED) && MS_CACHE_SLOTS > 0
#define MS_CACHE_ROOM MS_CACHE_SLOTS
#else
#define MS_CACHE_ROOM 1
#endif
MS_Slot *ms_slot;
u16 ms_frame_number = 0;
MS_CachedSlot ms_cache[MS_CACHE_ROOM];
u8 ms_cache_buckets[MS_CACHE_BUCKETS];
#ifdef MS_STREAMED
/* A streamed export: the slots (the default one unless the game sets its own), the queued lists' slots and what they
   cost of the vertical blank's budget. */
#define MS_DEFAULT_SLOT_TILES (MS_SLOT_TILES > MS_SCENE_SLOT_TILES ? MS_SLOT_TILES : MS_SCENE_SLOT_TILES)
#define MS_NOTHING_SHOWN 0xFFFFu
static MS_Slot g_default_slot;
static u16 g_upload_used;
static u16 g_upload_budget;
static MS_Slot *g_upload_slots[MS_MAX_UPLOADS];
#if MS_CACHE_SLOTS > 0
static u8 g_cache_first = MS_NO_ENTRY;  /* the first entry in tile order */
static u8 g_cache_free = MS_NO_ENTRY;   /* the first free entry */
static u16 g_cache_start = 0;           /* the pool: tiles g_cache_start .. g_cache_end - 1 */
static u16 g_cache_end = 0;
static u8 g_cache_on = FALSE;           /* draws take their slots from the cache */
#endif
#endif
/* Give-way levels (ms_set_give_way): once one was set, every draw is looked at against the limit. Give-way draws that
   fit are written and noted; from the first draw that does not fit, the rest of the frame waits for ms_end_frame.
   Shared with modsprite_draw.asm (ms_put_watched, ms_set_give_way): the level draws take now, whether a level was set
   (draws are looked at from then on; never without the queue), the give-way draws written this frame (their sprites
   first .. end - 1 in the OAM buffer, their levels; room for ms_give_way_room of them), the entries written this frame
   (a draw taken back or out leaves some behind, which ms_end_frame hides), whether the frame waits, and the waiting
   draws (room for ms_queue_room), 16 bytes each so 816-tcc and the asm reach one with shifts. */
#define MS_MAX_LEVEL 63u
#define MS_OWN_SPRITE 0xFFFFu  /* a waiting draw that is a game's own sprite (ms_add_hw_sprite) */
#define MS_GAVE_WAY 0xFFFEu    /* a waiting draw that gave way */
#define MS_GAVE_WAY_LEVEL 0xFFu  /* a written give-way draw's level once it gave way */
typedef struct
{
    u16 render;     /* its render frame; MS_OWN_SPRITE, MS_GAVE_WAY */
    s16 x;
    s16 y;
    u16 base;       /* ms_slot_base it was drawn with; an own sprite: its tile */
    u16 cost;       /* the sprites it puts on the screen */
    u8 flip;        /* its flips (bits 0-1; an own sprite: 1 large) and its level (bits 2-7) */
    u8 attribute;   /* an own sprite's attribute */
    u16 swap_at;    /* ms_swap_bits_at it was drawn with (its palette swap) */
    u16 reserved;
} MS_QueuedDraw;
#define MS_GIVE_WAY_ROOM (MS_GIVE_WAY_DRAWS > 0 && MS_QUEUED_DRAWS > 0 ? MS_GIVE_WAY_DRAWS : 0)
u8 ms_give_way = 0;
u8 ms_levels = FALSE;
u8 ms_levels_possible = MS_QUEUED_DRAWS > 0 ? TRUE : FALSE;
u16 ms_give_way_room = MS_GIVE_WAY_ROOM;
u16 ms_give_way_count = 0;
u8 ms_give_way_first[MS_GIVE_WAY_ROOM > 0 ? MS_GIVE_WAY_ROOM : 1];
u8 ms_give_way_end[MS_GIVE_WAY_ROOM > 0 ? MS_GIVE_WAY_ROOM : 1];
u8 ms_give_way_level[MS_GIVE_WAY_ROOM > 0 ? MS_GIVE_WAY_ROOM : 1];
u16 ms_written_end = 0;
u8 ms_waiting = FALSE;
u16 ms_queue_room = MS_QUEUED_DRAWS;
u16 ms_queued_count = 0;
MS_QueuedDraw ms_queued_draws[MS_QUEUED_DRAWS > 0 ? MS_QUEUED_DRAWS : 1];

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

/* A render frame's sprites (run_count runs: an MS_Run, then its sprites), in OAM order: the first in front, their tiles
   counted from ms_slot_base. The SNES build runs modsprite_draw.asm instead, which does exactly this, with no tests per
   sprite when the frame lies on the screen with X >= 0 and all its sprites fit (see ms_draw_render). Records are
   reached by offset: 816-tcc does not step far pointers reliably. */
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

            ms_push_sprite(ox + sprite->x, oy + sprite->y,
                           (u16)((sprite->tile | ((u16)(sprite->attribute & 1) << 8)) + ms_slot_base),
                           (u8)((sprite->attribute & 0xC0) | bits), sprite->size);
            at += sizeof(MS_Sprite);
        }
    }
    ms_frame_profile.hw_sprites = ms_hw_count;
    ms_frame_profile.sprites_dropped = ms_dropped;
}

/* ms_put_render_frame mirrored around (ox, oy) (flip: bit 0 left-right, bit 1 top-bottom; 0 as it is), as a mirrored
   animation step draws its frame: each sprite at its mirror image (on a mirrored axis -x - size), its flip bits
   toggled, in the same order. modsprite_draw.asm on the SNES, with the fast loop when the mirrored box lies on the
   screen. */
void ms_put_render_frame_flipped(u16 render_index, s16 ox, s16 oy, u16 flip)
{
    const MS_RenderFrame *frame = ms_render_frame(render_index);
    const u8 *runs;
    u8 flips = (u8)(((flip & 1) ? 0x40 : 0) | ((flip & 2) ? 0x80 : 0));
    u16 r, k, at = 0;

    if (!(flip & 3))
    {
        ms_put_render_frame(render_index, ox, oy);
        return;
    }
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
            s16 size = (s16)(sprite->size ? ms_large_size : ms_small_size);
            s16 x = (flip & 1) ? -sprite->x - size : sprite->x;
            s16 y = (flip & 2) ? -sprite->y - size : sprite->y;

            ms_push_sprite(ox + x, oy + y, (u16)((sprite->tile | ((u16)(sprite->attribute & 1) << 8)) + ms_slot_base),
                           (u8)(((sprite->attribute & 0xC0) ^ flips) | bits), sprite->size);
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

/* A game's own sprite (ms_add_hw_sprite, which looks at give-way levels first). modsprite_draw.asm on the SNES. */
u8 ms_push_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large)
{
    u8 added = ms_push_sprite(x, y, tile, attribute, large);
    ms_frame_profile.hw_sprites = ms_hw_count;
    ms_frame_profile.sprites_dropped = ms_dropped;
    return added;
}

/* A draw with give-way levels, as it is or mirrored (flip 0 or not). While the frame does not wait and it fitted, it
   stays (a give-way draw, ms_give_way not 0, noted among the written ones); else it is taken back (ms_hw_count and
   ms_dropped as they were, its entries remembered in ms_written_end), the frame waits from it on and it goes into the
   queue with the sprites it asked for (on the screen; past the queue's room it is left out, its sprites dropped).
   modsprite_draw.asm on the SNES. */
void ms_put_watched(u16 render_index, s16 ox, s16 oy, u16 flip)
{
    u16 first = ms_hw_count, dropped = ms_dropped, cost;

    ms_put_render_frame_flipped(render_index, ox, oy, flip);
    if (!ms_waiting && ms_dropped == dropped)
    {
        if (ms_give_way && ms_hw_count != first && ms_give_way_count < ms_give_way_room)
        {
            ms_give_way_first[ms_give_way_count] = (u8)first;
            ms_give_way_end[ms_give_way_count] = (u8)ms_hw_count;
            ms_give_way_level[ms_give_way_count] = ms_give_way;
            ms_give_way_count++;
        }
        return;
    }
    if (ms_hw_count > ms_written_end)
        ms_written_end = ms_hw_count;
    cost = ms_hw_count - first + ms_dropped - dropped;
    ms_hw_count = first;
    ms_dropped = dropped;
    ms_frame_profile.hw_sprites = first;
    ms_frame_profile.sprites_dropped = dropped;
    ms_waiting = TRUE;
    if (!cost)
        return;
    if (ms_queued_count < ms_queue_room)
    {
        MS_QueuedDraw *queued = &ms_queued_draws[ms_queued_count++];

        queued->render = render_index;
        queued->x = ox;
        queued->y = oy;
        queued->base = ms_slot_base;
        queued->cost = cost;
        queued->flip = (u8)((flip & 3) | (ms_give_way << 2));
        queued->attribute = 0;
        queued->swap_at = ms_swap_bits_at;
        return;
    }
    ms_frame_profile.draws_left_out++;
    ms_dropped += cost;
    ms_frame_profile.sprites_dropped = ms_dropped;
}

/* A render frame into the OAM buffer: as it is (or mirrored) without give-way levels, watched with them.
   modsprite_draw.asm on the SNES. */
void ms_draw_put(u16 render_index, s16 ox, s16 oy, u16 flip)
{
    if (ms_levels)
        ms_put_watched(render_index, ox, oy, flip);
    else
        ms_put_render_frame_flipped(render_index, ox, oy, flip);
}

/* A game's own sprite: pushed without give-way levels; with them a sprite on the screen waits for ms_end_frame when the
   frame waits or the buffer is full (past the queue's room it is left out, its sprite dropped), else it is pushed and,
   a give-way sprite, noted. modsprite_draw.asm on the SNES. */
u8 ms_add_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large)
{
    u16 first = ms_hw_count, size1 = (large ? ms_large_size : ms_small_size) - 1;
    u8 added;

    if (!ms_levels || (u16)(x + size1) >= (u16)(size1 + MS_SCREEN_W) || (u16)(y + size1) >= (u16)(size1 + MS_SCREEN_H))
        return ms_push_hw_sprite(x, y, tile, attribute, large);
    if (ms_waiting || ms_hw_count >= ms_sprite_limit)
    {
        ms_waiting = TRUE;
        if (ms_queued_count < ms_queue_room)
        {
            MS_QueuedDraw *queued = &ms_queued_draws[ms_queued_count++];

            queued->render = MS_OWN_SPRITE;
            queued->x = x;
            queued->y = y;
            queued->base = tile;
            queued->cost = 1;
            queued->flip = (u8)((large ? 1 : 0) | (ms_give_way << 2));
            queued->attribute = attribute;
        }
        else
        {
            ms_frame_profile.draws_left_out++;
            ms_dropped++;
            ms_frame_profile.sprites_dropped = ms_dropped;
        }
        return TRUE;
    }
    added = ms_push_hw_sprite(x, y, tile, attribute, large);
    if (ms_give_way && ms_hw_count != first && ms_give_way_count < ms_give_way_room)
    {
        ms_give_way_first[ms_give_way_count] = (u8)first;
        ms_give_way_end[ms_give_way_count] = (u8)ms_hw_count;
        ms_give_way_level[ms_give_way_count] = ms_give_way;
        ms_give_way_count++;
    }
    return added;
}

/* With the slot cache: when it holds the render frame's load list (loads: each render frame's), the slot drawn through
   from here (ms_slot; the entry drawn this frame, counted once) and TRUE; TRUE too when the render frame shows nothing
   (no slot needed); else FALSE: the C takes a new slot. modsprite_draw.asm on the SNES. */
u8 ms_cache_hit(u16 render_index, const u16 *loads)
{
    u16 list = loads[render_index];
    u8 n;

    if (list == 0xFFFFu)
        return TRUE;
    n = ms_cache_buckets[list & (MS_CACHE_BUCKETS - 1)];
    while (n != MS_NO_ENTRY && ms_cache[n].list != list)
        n = ms_cache[n].next;
    if (n == MS_NO_ENTRY)
        return FALSE;
    if (ms_cache[n].drawn != ms_frame_number)
    {
        ms_cache[n].drawn = ms_frame_number;
        ms_frame_profile.slots_used++;
    }
    ms_slot = &ms_cache[n].slot;
    return TRUE;
}

/* OAM entries from .. from + count - 1 to to .. (to < from): their four bytes and their high bits. modsprite_draw.asm
   (block moves) on the SNES. */
void ms_move_sprites(u16 to, u16 from, u16 count)
{
    memmove(&oamMemory[to << 2], &oamMemory[from << 2], (size_t)count << 2);
    memmove(&ms_high_bits[to << 2], &ms_high_bits[from << 2], (size_t)count << 2);
}

#ifdef MS_STREAMED
/* The host's vertical blank: FALSE once it ended (the harness decides; HVBJOY's bit 7 on the SNES). */
u8 ms_host_in_vblank(void);

/* The queued load lists (records in ``lists``) into their slots, a DMA run per entry, while the vertical blank lasts
   (looked at before and after each list); returns how many arrived whole. modsprite_draw.asm on the SNES. */
u16 ms_send_uploads(const MS_LoadList *lists)
{
    u16 n, g, e, at;

    for (n = 0; n < ms_upload_count; n++)
    {
        const MS_LoadList *load = &lists[ms_upload_lists[n]];
        const u8 *entries = MS_FAR(load->entries_chunk, load->entries_offset);

        if (!ms_host_in_vblank())
            return n;
        at = 0;
        for (g = 0; g < load->group_count; g++)
        {
            const MS_LoadGroup *group = (const MS_LoadGroup *)(entries + at);
            const u8 *chunk = ms_chunks[group->chunk];
            u16 count = group->count;

            at += sizeof(MS_LoadGroup);
            for (e = 0; e < count; e++)
            {
                const MS_LoadEntry *entry = (const MS_LoadEntry *)(entries + at);

                dmaCopyVram((u8 *)(chunk + entry->source), (u16)(ms_upload_vram[n] + entry->vram), entry->bytes);
                at += sizeof(MS_LoadEntry);
            }
        }
        if (!ms_host_in_vblank())
            return n;
    }
    return ms_upload_count;
}
#endif
#else
/* modsprite_draw.asm */
void ms_put_render_frame(u16 render_index, s16 ox, s16 oy);
void ms_put_render_frame_flipped(u16 render_index, s16 ox, s16 oy, u16 flip);
void ms_finish_oam(u8 *high_table, u16 count, u16 shown);
u8 ms_push_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large);
void ms_draw_put(u16 render_index, s16 ox, s16 oy, u16 flip);
u8 ms_cache_hit(u16 render_index, const u16 *loads);
void ms_move_sprites(u16 to, u16 from, u16 count);
#ifdef MS_STREAMED
u16 ms_send_uploads(const MS_LoadList *lists);
#endif
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

#ifdef MS_STREAMED
/* What the slot drawn through shows of a render frame this frame: the render frame itself when the slot holds its tiles
   or they can be queued for the next vertical blank; else what the slot showed before, while the upload waits for room
   in the budget (or nothing, when the slot holds nothing). A slot shows one thing a frame: a second list through it in
   the same frame is not drawn. */
static u16 ms_slot_render(u16 render_index)
{
    MS_Slot *slot = ms_slot;
    u16 list = ms_render_frame_loads[render_index];
    u16 cost;

    if (list == MS_NO_LIST)
        return render_index;  /* it shows nothing: the slot keeps what it holds */
    if (list == slot->load_list)
    {
        slot->render = render_index;
        slot->frame = ms_frame_number;
        return render_index;
    }
    if (slot->frame == ms_frame_number)
    {
        ms_frame_profile.uploads_waiting++;
        return MS_NOTHING_SHOWN;
    }
    slot->frame = ms_frame_number;
    cost = ms_load_lists[list].cost;
    /* the first list of a frame goes whatever it costs: a list above the budget would never go otherwise */
    if (ms_upload_count >= MS_MAX_UPLOADS
        || (ms_upload_count && (g_upload_used > g_upload_budget || cost > (u16)(g_upload_budget - g_upload_used))))
    {
        ms_frame_profile.uploads_waiting++;
        return slot->render;
    }
    g_upload_used += cost;
    g_upload_slots[ms_upload_count] = slot;
    ms_upload_lists[ms_upload_count] = list;
    ms_upload_vram[ms_upload_count] = g_vram + (slot->tile_index << 4);
    ms_upload_count++;
    slot->load_list = list;
    slot->render = render_index;
    ms_frame_profile.tiles_uploaded += ms_load_lists[list].tile_count;
    return render_index;
}
#endif

#if defined(MS_STREAMED) && MS_CACHE_SLOTS > 0
static void ms_cache_reset(void)
{
    u16 n;

    for (n = 0; n < MS_CACHE_BUCKETS; n++)
        ms_cache_buckets[n] = MS_NO_ENTRY;
    for (n = 0; n < MS_CACHE_SLOTS; n++)
    {
        ms_cache[n].list = MS_NOTHING_LOADED;
        ms_cache[n].next = (u8)(n + 1 < MS_CACHE_SLOTS ? n + 1 : MS_NO_ENTRY);
    }
    g_cache_first = MS_NO_ENTRY;
    g_cache_free = 0;
}

/* The first place of `tiles` tiles in the pool, from a multiple of MS_SLOT_ALIGN, in one walk along the entries in tile
   order (*before: the entry it follows, MS_NO_ENTRY at the pool's start); 0xFFFF when there is none. */
static u16 ms_cache_room(u16 tiles, u8 *before)
{
    u16 at = g_cache_start;
    u8 prev = MS_NO_ENTRY, n = g_cache_first;

    for (;;)
    {
        u16 end = n == MS_NO_ENTRY ? g_cache_end : ms_cache[n].slot.tile_index;

        at = (at + (MS_SLOT_ALIGN - 1)) & ~(MS_SLOT_ALIGN - 1);
        if (end >= at && end - at >= tiles)
        {
            *before = prev;
            return at;
        }
        if (n == MS_NO_ENTRY)
            return 0xFFFFu;
        at = ms_cache[n].slot.tile_index + ms_cache[n].tiles;
        prev = n;
        n = ms_cache[n].after;
    }
}

/* Room: the entry drawn longest ago goes (of equals the last in tile order), its tiles and its record free; FALSE when
   every entry was drawn this frame. One walk along the entries in tile order, which finds the one before it too. */
static u8 ms_cache_evict(void)
{
    u16 age = 0;
    u8 n, prev = MS_NO_ENTRY, oldest = MS_NO_ENTRY, before = MS_NO_ENTRY, *link;

    for (n = g_cache_first; n != MS_NO_ENTRY; prev = n, n = ms_cache[n].after)
        if (ms_cache[n].drawn != ms_frame_number && (u16)(ms_frame_number - ms_cache[n].drawn) >= age)
        {
            age = (u16)(ms_frame_number - ms_cache[n].drawn);
            oldest = n;
            before = prev;
        }
    if (oldest == MS_NO_ENTRY)
        return FALSE;
    for (link = &ms_cache_buckets[ms_cache[oldest].list & (MS_CACHE_BUCKETS - 1)]; *link != oldest;
         link = &ms_cache[*link].next)
        ;
    *link = ms_cache[oldest].next;
    if (before == MS_NO_ENTRY)
        g_cache_first = ms_cache[oldest].after;
    else
        ms_cache[before].after = ms_cache[oldest].after;
    ms_cache[oldest].list = MS_NOTHING_LOADED;
    ms_cache[oldest].next = g_cache_free;
    g_cache_free = oldest;
    return TRUE;
}

/* A new entry for a load list: room for its rows at the first place they fit (the entries drawn longest ago making
   room while there is none) and a record; MS_NO_ENTRY when what is in the way was all drawn this frame. */
static u8 ms_cache_take(u16 list)
{
    u16 tiles = (u16)ms_load_list_rows[list] << 4, at;
    u8 n, before;

    if (tiles > g_cache_end - g_cache_start)
        return MS_NO_ENTRY;
    if (g_cache_free == MS_NO_ENTRY && !ms_cache_evict())
        return MS_NO_ENTRY;
    while ((at = ms_cache_room(tiles, &before)) == 0xFFFFu)
        if (!ms_cache_evict())
            return MS_NO_ENTRY;
    n = g_cache_free;
    g_cache_free = ms_cache[n].next;
    ms_cache[n].list = list;
    ms_cache[n].tiles = tiles;
    ms_cache[n].drawn = MS_NOTHING_SHOWN;
    ms_slot_init(&ms_cache[n].slot, at);  /* holds nothing yet: the draw queues its tiles */
    ms_cache[n].next = ms_cache_buckets[list & (MS_CACHE_BUCKETS - 1)];
    ms_cache_buckets[list & (MS_CACHE_BUCKETS - 1)] = n;
    if (before == MS_NO_ENTRY)
    {
        ms_cache[n].after = g_cache_first;
        g_cache_first = n;
    }
    else
    {
        ms_cache[n].after = ms_cache[before].after;
        ms_cache[before].after = n;
    }
    return n;
}

/* With the slot cache: the slot kept for the render frame's load list, or a new one, drawn through from here; FALSE
   (the draw is left out) when the cache has no room for it. A render frame that shows nothing needs none. */
static u8 ms_cache_slot(u16 render_index)
{
    u8 n;

    if (ms_cache_hit(render_index, ms_render_frame_loads))
        return TRUE;  /* the cache holds it (ms_slot set), or it shows nothing */
    n = ms_cache_take(ms_render_frame_loads[render_index]);
    if (n == MS_NO_ENTRY)
    {
        ms_frame_profile.draws_left_out++;
        return FALSE;
    }
    ms_cache[n].drawn = ms_frame_number;
    ms_frame_profile.slots_used++;
    ms_slot = &ms_cache[n].slot;
    return TRUE;
}
#endif

#if MS_QUEUED_DRAWS > 0
/* The written draws that gave way leave the OAM buffer (the ones from `first` on): the sprites after them move up. */
static void ms_take_out_given_way(u16 first)
{
#if MS_GIVE_WAY_DRAWS > 0
    u16 n, read = first, write = first;

    for (n = 0; n < ms_give_way_count; n++)
    {
        if (ms_give_way_level[n] != MS_GAVE_WAY_LEVEL)
            continue;
        if (ms_give_way_first[n] > read)
        {
            ms_move_sprites(write, read, ms_give_way_first[n] - read);
            write += ms_give_way_first[n] - read;
        }
        read = ms_give_way_end[n];
    }
    if (ms_hw_count > read)
    {
        ms_move_sprites(write, read, ms_hw_count - read);
        write += ms_hw_count - read;
    }
    ms_hw_count = write;
#else
    (void)first;
#endif
}

/* The frame asked for more sprites than the limit and its draws wait from the first that did not fit: the draws with
   a level give way, level 1 first, within a level the last drawn first, as many as the frame asks too much; written
   ones leave the buffer, the waiting ones that stay are drawn behind what is left, as they would have been. */
static void ms_resolve_waiting(void)
{
    s16 excess = (s16)ms_hw_count - (s16)ms_sprite_limit;
    u16 n, level, top = 0, given = 0, first_out = 0xFFFFu, base = ms_slot_base, swap_at = ms_swap_bits_at;
    u16 calls = ms_frame_profile.render_calls, parts = ms_frame_profile.parts_submitted;

    for (n = 0; n < ms_queued_count; n++)
    {
        excess += (s16)ms_queued_draws[n].cost;
        if ((ms_queued_draws[n].flip >> 2) > top)
            top = ms_queued_draws[n].flip >> 2;
    }
#if MS_GIVE_WAY_DRAWS > 0
    for (n = 0; n < ms_give_way_count; n++)
        if (ms_give_way_level[n] > top)
            top = ms_give_way_level[n];
#endif
    for (level = 1; level <= top && excess > 0; level++)
    {
        for (n = ms_queued_count; n-- > 0 && excess > 0;)
        {
            MS_QueuedDraw *queued = &ms_queued_draws[n];

            if ((queued->flip >> 2) == level)
            {
                queued->render = MS_GAVE_WAY;
                excess -= (s16)queued->cost;
                given++;
            }
        }
#if MS_GIVE_WAY_DRAWS > 0
        for (n = ms_give_way_count; n-- > 0 && excess > 0;)
        {
            if (ms_give_way_level[n] == level)
            {
                ms_give_way_level[n] = MS_GAVE_WAY_LEVEL;
                excess -= (s16)(ms_give_way_end[n] - ms_give_way_first[n]);
                given++;
                if (ms_give_way_first[n] < first_out)
                    first_out = ms_give_way_first[n];
            }
        }
#endif
    }
    if (first_out != 0xFFFFu)
        ms_take_out_given_way(first_out);
    for (n = 0; n < ms_queued_count; n++)
    {
        const MS_QueuedDraw *queued = &ms_queued_draws[n];

        if (queued->render == MS_GAVE_WAY)
            continue;
        if (queued->render == MS_OWN_SPRITE)
        {
            ms_push_hw_sprite(queued->x, queued->y, queued->base, queued->attribute,
                              (u8)((queued->flip & 1) ? TRUE : FALSE));
            continue;
        }
        ms_slot_base = queued->base;
        ms_swap_bits_at = queued->swap_at;
        if (queued->flip & 3)
            ms_put_render_frame_flipped(queued->render, queued->x, queued->y, queued->flip & 3);
        else
            ms_put_render_frame(queued->render, queued->x, queued->y);
    }
    ms_slot_base = base;
    ms_swap_bits_at = swap_at;
    ms_frame_profile.render_calls = calls;
    ms_frame_profile.parts_submitted = parts;
    ms_frame_profile.hw_sprites = ms_hw_count;
    ms_frame_profile.sprites_dropped = ms_dropped;
    ms_frame_profile.draws_given_way = given;
}
#endif

/* Draw a render frame (flip: mirrored around the point drawn at, as a mirrored animation step or nested frame part is,
   bit 0 left-right, bit 1 top-bottom; 0 as it is) through its slot (streamed: the cache's when it is on; nothing when
   the slot shows nothing this frame), into the OAM buffer or, while give-way levels make it wait, the queue. The SNES
   build skips the tests per sprite when the frame's box lies on the screen with X >= 0 (ox + min_x >= 0,
   ox + max_x < 256 + small, oy + min_y > -small, oy + max_y < 224 + small: every sprite then has 0 <= x < 256 and
   -size < y < 224; mirrored, the box from -max to -min on a mirrored axis) and all its sprites fit under the limit;
   what it draws is the same. */
static void ms_draw_render(u16 render_index, s16 ox, s16 oy, u16 flip)
{
    if (render_index >= MS_RENDER_FRAME_COUNT)
        return;
#ifdef MS_STREAMED
#if MS_CACHE_SLOTS > 0
    if (g_cache_on && !ms_cache_slot(render_index))
        return;
#endif
    render_index = ms_slot_render(render_index);
    if (render_index == MS_NOTHING_SHOWN)
        return;
    ms_slot_base = ms_slot->tile_index;
#endif
    ms_draw_put(render_index, ox, oy, flip);  /* with give-way levels watched: modsprite_draw.asm */
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
    /* Both sprite tables, the second right after the first (OBSEL's name select 0); a streamed export loads nothing
       now: the default slot takes the tiles from tile 0 as things are drawn through it. */
    for (t = 0; t < MS_TILE_TABLES; t++)
        dmaCopyVram((u8 *)ms_tile_tables[t], g_vram + t * 0x1000, 0x2000);
    ms_slot_base = 0;
#ifdef MS_STREAMED
    ms_slot_init(&g_default_slot, 0);
    ms_slot = &g_default_slot;
    ms_frame_number = 0;
    g_upload_used = 0;
    g_upload_budget = MS_UPLOAD_BUDGET;
    ms_upload_count = 0;
#endif
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
    /* ms_put_render_frame reads an entry's bits as a word (the next entry's byte unused): every byte has a value. */
    memset(ms_swap_bits, 0, sizeof(ms_swap_bits));
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
#ifdef MS_STREAMED
    return (u16)MS_DEFAULT_SLOT_TILES;
#else
    return (u16)MS_TILE_COUNT;
#endif
}

u16 ms_tiles_end(void)
{
    return (u16)MS_TILE_END;
}

void ms_slot_init(MS_Slot *slot, u16 tile_index)
{
    if (!slot)
        return;
#ifdef MS_STREAMED
    tile_index = (tile_index + (MS_SLOT_ALIGN - 1)) & ~(MS_SLOT_ALIGN - 1);
#endif
    slot->tile_index = tile_index;
    slot->load_list = MS_NOTHING_LOADED;
    slot->render = MS_NOTHING_LOADED;
    slot->frame = 0xFFFFu;
}

void ms_set_slot(MS_Slot *slot)
{
#ifdef MS_STREAMED
    ms_slot = slot ? slot : &g_default_slot;
#if MS_CACHE_SLOTS > 0
    g_cache_on = FALSE;
#endif
#else
    (void)slot;
#endif
}

void ms_slot_cache_init(u16 tile_index, u16 tile_count)
{
#if defined(MS_STREAMED) && MS_CACHE_SLOTS > 0
    u16 end = tile_count < MS_SPRITE_TILES ? tile_index + tile_count : MS_SPRITE_TILES;

    g_cache_start = (tile_index + (MS_SLOT_ALIGN - 1)) & ~(MS_SLOT_ALIGN - 1);
    g_cache_end = end < MS_SPRITE_TILES ? end : MS_SPRITE_TILES;
    ms_cache_reset();
    g_cache_on = g_cache_end > g_cache_start;
#else
    (void)tile_index;
    (void)tile_count;
#endif
}

void ms_use_slot_cache(void)
{
#if defined(MS_STREAMED) && MS_CACHE_SLOTS > 0
    g_cache_on = g_cache_end > g_cache_start;
#endif
}

void ms_slot_cache_clear(void)
{
#if defined(MS_STREAMED) && MS_CACHE_SLOTS > 0
    ms_cache_reset();
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

void ms_set_upload_budget(u16 bytes)
{
#ifdef MS_STREAMED
    g_upload_budget = bytes;
#else
    (void)bytes;
#endif
}

u16 ms_upload_queued(void)
{
#ifdef MS_STREAMED
    return g_upload_used;
#else
    return 0;
#endif
}

void ms_upload_tiles(void)
{
#ifdef MS_STREAMED
    u16 sent;
#endif

    ms_upload_lines();  /* the sprite palettes ms_palette_tick prepared first: they are small, and need the blank too */
#ifdef MS_STREAMED
    if (!ms_upload_count)
        return;
    sent = ms_send_uploads(ms_load_lists);
    for (; sent < ms_upload_count; sent++)
    {
        /* past the vertical blank: the slot holds part of it at most; drawn again, it queues the list again */
        g_upload_slots[sent]->load_list = MS_NOTHING_LOADED;
        g_upload_slots[sent]->render = MS_NOTHING_LOADED;
    }
    ms_upload_count = 0;
    g_upload_used = 0;
#endif
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
    ms_frame_profile.tiles_uploaded = 0;
    ms_frame_profile.uploads_waiting = 0;
    ms_frame_profile.slots_used = 0;
    ms_frame_profile.draws_left_out = 0;
    ms_frame_profile.draws_given_way = 0;
    ms_hw_count = 0;
    ms_dropped = 0;
    ms_written_end = 0;
#ifdef MS_STREAMED
    if (++ms_frame_number == 0xFFFFu)
        ms_frame_number = 0;
#endif
#if MS_QUEUED_DRAWS > 0
    ms_waiting = FALSE;
    ms_give_way_count = 0;
    ms_queued_count = 0;
#endif
}

void ms_end_frame(void)
{
    /* The entries this frame did not use go below the screen (small, X below 256), the ones hidden before stay hidden
       (and the ones written before draws that gave way left the buffer); the entries from the limit on are the
       game's. */
    u16 shown = g_shown_last < ms_sprite_limit ? g_shown_last : ms_sprite_limit;

    if (ms_hw_count > shown)
        shown = ms_hw_count;
    if (ms_written_end > shown)
        shown = ms_written_end;
#if MS_QUEUED_DRAWS > 0
    if (ms_waiting)
        ms_resolve_waiting();
#endif
    ms_finish_oam(&oamMemory[512], ms_hw_count, shown > ms_hw_count ? shown : ms_hw_count);
    g_shown_last = ms_hw_count;
}

#ifdef MS_PUT_FRAME_C
/* modsprite_draw.asm on the SNES */
void ms_set_give_way(u8 level)
{
    ms_give_way = level < 63u ? level : 63u;
    if (level && ms_levels_possible)
        ms_levels = TRUE;
}
#endif

u8 ms_get_give_way(void)
{
    return ms_give_way;
}

void ms_draw_module(u16 module_index, s16 x, s16 y)
{
    if (module_index >= MS_MODULE_COUNT)
        return;
    ms_draw_render(ms_module_render_frames[ms_mapping_module_base() + module_index], x, y, 0);
}

void ms_draw_frame(u16 frame_index, s16 x, s16 y)
{
    if (frame_index >= MS_FRAME_COUNT)
        return;
    ms_draw_render(ms_frame_render_frames[ms_mapping_frame_base() + frame_index], x, y, 0);
}

static u16 ms_module_render_index(u16 module_index)
{
    if (module_index >= MS_MODULE_COUNT)
        return 0xFFFFu;
    return ms_module_render_frames[ms_mapping_module_base() + module_index];
}

static u16 ms_frame_render_index(u16 frame_index)
{
    if (frame_index >= MS_FRAME_COUNT)
        return 0xFFFFu;
    return ms_frame_render_frames[ms_mapping_frame_base() + frame_index];
}

/* Where a module mirrored in place is drawn mirrored around its pivot: moved by its width less twice its pivot's x (and
   the same for y) of the module the active mapping draws. */
static void ms_module_flip_offset(u16 module_index, u8 flip, s16 *x, s16 *y)
{
    u16 at = (ms_mapping_module_base() + module_index) << 1;

    if (flip & 1)
        *x += ms_module_flip_offsets[at];
    if (flip & 2)
        *y += ms_module_flip_offsets[at + 1];
}

void ms_draw_module_flipped(u16 module_index, s16 x, s16 y, u8 flip)
{
    u16 at;

    if (module_index >= MS_MODULE_COUNT)
        return;
    flip &= 3;
    at = ms_mapping_module_base() + module_index;
    /* (as ms_module_flip_offset, without taking x's and y's addresses: PVSnesLib 4.6.0's Linux build drops the frame
       size of a function without locals that takes a parameter's address, and the ROM does not link) */
    if (flip & 1)
        x += ms_module_flip_offsets[at << 1];
    if (flip & 2)
        y += ms_module_flip_offsets[(at << 1) + 1];
    ms_draw_render(ms_module_render_frames[at], x, y, flip);
}

void ms_draw_frame_flipped(u16 frame_index, s16 x, s16 y, u8 flip)
{
    if (frame_index >= MS_FRAME_COUNT)
        return;
    ms_draw_render(ms_frame_render_frames[ms_mapping_frame_base() + frame_index], x, y, flip);
}

/* The box of a render frame's hardware sprites drawn with flip, mirrored around (dx / 2, dy / 2). */
static u8 ms_render_bounds(u16 render_index, u8 flip, s16 dx, s16 dy, MS_Bounds *out)
{
    const MS_RenderFrame *frame;

    if (!out)
        return FALSE;
    out->min_x = 0;
    out->min_y = 0;
    out->max_x = 0;
    out->max_y = 0;
    if (render_index >= MS_RENDER_FRAME_COUNT)
        return FALSE;
    frame = ms_render_frame(render_index);
    if (!frame->sprite_count)
        return FALSE;
    out->min_x = (flip & 1) ? dx - frame->max_x : frame->min_x;
    out->max_x = (flip & 1) ? dx - frame->min_x : frame->max_x;
    out->min_y = (flip & 2) ? dy - frame->max_y : frame->min_y;
    out->max_y = (flip & 2) ? dy - frame->min_y : frame->max_y;
    return TRUE;
}

u16 ms_frame_sprites(u16 frame_index)
{
    u16 render = ms_frame_render_index(frame_index);

    return render < MS_RENDER_FRAME_COUNT ? ms_render_frame(render)->sprite_count : 0;
}

u16 ms_module_sprites(u16 module_index)
{
    u16 render = ms_module_render_index(module_index);

    return render < MS_RENDER_FRAME_COUNT ? ms_render_frame(render)->sprite_count : 0;
}

u8 ms_frame_bounds(u16 frame_index, u8 flip, MS_Bounds *out)
{
    return ms_render_bounds(ms_frame_render_index(frame_index), flip, 0, 0, out);
}

u8 ms_module_bounds(u16 module_index, u8 flip, MS_Bounds *out)
{
    s16 dx = 0, dy = 0;

    if (module_index < MS_MODULE_COUNT)
        ms_module_flip_offset(module_index, flip, &dx, &dy);
    return ms_render_bounds(ms_module_render_index(module_index), flip, dx, dy, out);
}

static u16 ms_render_load_list(u16 render_index)
{
#ifdef MS_STREAMED
    if (render_index < MS_RENDER_FRAME_COUNT)
        return ms_render_frame_loads[render_index];  /* MS_NO_LIST (MS_NOTHING_LOADED) when it shows nothing */
#else
    (void)render_index;
#endif
    return MS_NOTHING_LOADED;
}

u16 ms_frame_load_list(u16 frame_index)
{
    return ms_render_load_list(ms_frame_render_index(frame_index));
}

u16 ms_module_load_list(u16 module_index)
{
    return ms_render_load_list(ms_module_render_index(module_index));
}

u16 ms_load_list_tiles(u16 load_list)
{
#ifdef MS_STREAMED
    if (load_list < MS_LOAD_LIST_COUNT)
        return (u16)ms_load_list_rows[load_list] << 4;  /* its rows: the squares sit aligned to their size in them */
#else
    (void)load_list;
#endif
    return 0;
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
        ms_draw_render(step->frame_index, x, y, 0);
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
    ms_draw_render(ms_scene_samples[scene->first_sample + sample_index], x, y, 0);
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
