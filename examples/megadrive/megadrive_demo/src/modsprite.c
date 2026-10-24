#include <genesis.h>
#include <string.h>
#include "modsprite.h"

#define MS_DEFAULT_SPRITE_LIMIT 80u
#define MS_NO_LINE 0xFFu
#define MS_MAX_ENTRIES 128u
#ifndef MS_CACHE_SLOTS
#define MS_CACHE_SLOTS 48  /* the slot cache's slots (ms_slot_cache_init); 0 leaves the cache out */
#endif
#ifndef MS_GIVE_WAY_DRAWS
#define MS_GIVE_WAY_DRAWS 32  /* give-way draws a frame writes that can still make room (ms_set_give_way) */
#endif
#ifndef MS_QUEUED_DRAWS
#define MS_QUEUED_DRAWS 32  /* draws a frame keeps waiting from its first that did not fit; 0 leaves the levels out */
#endif
#if MS_CACHE_SLOTS > 254 || MS_GIVE_WAY_DRAWS > 80
#error "MS_CACHE_SLOTS goes up to 254, MS_GIVE_WAY_DRAWS to 80"
#endif

static u8 g_initialized = FALSE;
static u8 g_tiles_fit = FALSE;
static u8 g_palettes_fit = FALSE;
static u16 g_active_mapping = 0;
static MS_FrameProfile g_frame_profile = { 0, 0, 0, 0, 0, 0, 0, 0 };
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
/* A streamed export: what is drawn takes its tiles from a slot (the default one unless the game sets its own), and
   the frame number (never 0xFFFF: a slot cache entry not drawn yet). */
#define MS_DEFAULT_SLOT_TILES (MS_SLOT_TILES > MS_SCENE_SLOT_TILES ? MS_SLOT_TILES : MS_SCENE_SLOT_TILES)
#define MS_NOT_DRAWN 0xFFFFu
static MS_Slot g_default_slot = { TILE_USER_INDEX, MS_NOTHING_LOADED };
static MS_Slot *g_slot = &g_default_slot;
static u16 g_frame_number = 0;
#if MS_CACHE_SLOTS > 0
/* The slot cache (ms_slot_cache_init): a slot per load list in one pool of tiles. Each entry is in the bucket of its
   list's low bits (found in a step or two) and in tile order (where first fit looks for room), or free. */
#define MS_CACHE_BUCKETS 64u
#define MS_NO_ENTRY 0xFFu
typedef struct
{
    MS_Slot slot;  /* its first tile, and what video memory holds there */
    u16 list;      /* the load list it is kept for; MS_NOTHING_LOADED: a free entry */
    u16 tiles;     /* the tiles it takes from slot.tile_index */
    u16 drawn;     /* the frame it was drawn in last */
    u8 next;       /* the next entry in its bucket (a free entry: the next free one) */
    u8 after;      /* the entry after it in tile order */
} MS_CachedSlot;
static MS_CachedSlot g_cache[MS_CACHE_SLOTS];
static u8 g_cache_buckets[MS_CACHE_BUCKETS];
static u8 g_cache_first = MS_NO_ENTRY;  /* the first entry in tile order */
static u8 g_cache_free = MS_NO_ENTRY;   /* the first free entry */
static u16 g_cache_start = 0;           /* the pool: tiles g_cache_start .. g_cache_end - 1 */
static u16 g_cache_end = 0;
static u8 g_cache_on = FALSE;           /* draws take their slots from the cache */
static MS_Slot g_cache_nothing;         /* the slot of render frames that show no tiles */
#endif
#endif
#if MS_QUEUED_DRAWS > 0
/* Give-way levels (ms_set_give_way): once one was set, every draw is looked at against the limit. Give-way draws that
   fit are written and noted; from the first draw that does not fit, the rest of the frame waits for ms_end_frame. */
#define MS_MAX_LEVEL 63u
#define MS_OWN_SPRITE 0xFFFFu  /* a waiting draw that is a game's own sprite (ms_add_hw_sprite) */
#define MS_GAVE_WAY 0xFFFEu    /* a waiting draw that gave way */
typedef struct
{
    u8 first;     /* its first sprite in the table */
    u8 count;     /* its sprites */
    u8 level;
    u8 gave_way;  /* TRUE: ms_end_frame takes it out of the table */
} MS_GiveWayDraw;
typedef struct
{
    u16 render;   /* its render frame; MS_OWN_SPRITE, MS_GAVE_WAY */
    s16 x;
    s16 y;
    u16 base;     /* the attribute base it was drawn with (its slot's first tile); an own sprite: its attribute */
    u16 cost;     /* the sprites it puts on the screen */
    u8 flip;      /* its flips (bits 0-1) and its level (bits 2-7) */
    u8 swap;      /* the palette swap it was drawn with; an own sprite: its size */
} MS_QueuedDraw;
static u8 g_levels = FALSE;  /* a level was set: draws are looked at */
static u8 g_waiting = FALSE; /* this frame: a draw did not fit, it and the ones after it wait */
static u8 g_top_level = 0;   /* the highest level drawn this frame */
static u16 g_give_way_count = 0;
static u16 g_queued_count = 0;
#if MS_GIVE_WAY_DRAWS > 0
static MS_GiveWayDraw g_give_way_draws[MS_GIVE_WAY_DRAWS];
#endif
static MS_QueuedDraw g_queued_draws[MS_QUEUED_DRAWS];
#endif
static u8 g_give_way = 0;    /* the level draws take now */

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

/* Whether a hardware sprite at (x, y) shows: off-screen ones are skipped (a sprite at x = -128 would also mask the
   sprites behind it on its lines). */
static inline u8 ms_on_screen(s16 x, s16 y, u8 size)
{
    return !(x >= g_screen_w || y >= g_screen_h || x + (s16)((((size >> 2) & 3) + 1) << 3) <= 0
             || y + (s16)(((size & 3) + 1) << 3) <= 0);
}

/* One hardware sprite into the sprite table cache, unless it is off the screen. */
static inline u8 ms_push_sprite(s16 x, s16 y, u8 size, u16 attribute)
{
    VDPSprite *sprite;

    if (!ms_on_screen(x, y, size))
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

/* A render frame's pieces into the sprite table from g_hw_count on, their tiles from g_attr_base. The last part is on
   top: it goes first into the sprite list. */
static void ms_put_render_frame(const MS_RenderFrame *frame, s16 ox, s16 oy)
{
    const MS_Part *part = &ms_parts[frame->first_part + frame->part_count];
    u16 n;

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

/* ms_put_render_frame mirrored around the point it is drawn at (flip: bit 0 left-right, bit 1 top-bottom, not 0), as a
   mirrored animation step or nested frame part is: each hardware sprite at its mirror image, its flip bits toggled. */
static void ms_put_render_frame_flipped(const MS_RenderFrame *frame, s16 ox, s16 oy, u8 flip)
{
    const MS_Part *part = &ms_parts[frame->first_part + frame->part_count];
    s16 min_x, min_y, max_x, max_y;
    u16 n;

    min_x = (flip & 1) ? -frame->max_x : frame->min_x;
    max_x = (flip & 1) ? -frame->min_x : frame->max_x;
    min_y = (flip & 2) ? -frame->max_y : frame->min_y;
    max_y = (flip & 2) ? -frame->min_y : frame->max_y;
    if (ox + min_x >= 0 && oy + min_y >= 0 && ox + max_x <= g_screen_w && oy + max_y <= g_screen_h
        && g_hw_count + frame->sprite_count <= g_sprite_limit)
    {
        VDPSprite *sprite = &vdpSpriteCache[g_hw_count];
        u16 link = g_hw_count;

        for (n = frame->part_count; n > 0; n--)
        {
            const MS_Piece *piece;
            u16 attribute, k;

            part--;
            piece = &ms_pieces[part->first_piece];
            attribute = g_attr_base | ((u16)(part->flip ^ flip) << 11);
            for (k = part->piece_count; k > 0; k--, piece++, sprite++)
            {
                s16 x = part->x + piece->x;
                s16 y = part->y + piece->y;

                if (flip & 1)
                    x = -x - (s16)((((piece->size >> 2) & 3) + 1) << 3);
                if (flip & 2)
                    y = -y - (s16)(((piece->size & 3) + 1) << 3);
                sprite->y = oy + y + 0x80;
                sprite->size = piece->size;
                sprite->link = (u8)++link;
                sprite->attribut = attribute + piece->tile_offset + g_entry_bits[piece->palette];
                sprite->x = ox + x + 0x80;
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

        part--;
        piece = &ms_pieces[part->first_piece];
        attribute = g_attr_base | ((u16)(part->flip ^ flip) << 11);
        for (k = part->piece_count; k > 0; k--, piece++)
        {
            s16 x = part->x + piece->x;
            s16 y = part->y + piece->y;

            if (flip & 1)
                x = -x - (s16)((((piece->size >> 2) & 3) + 1) << 3);
            if (flip & 2)
                y = -y - (s16)(((piece->size & 3) + 1) << 3);
            ms_push_sprite(ox + x, oy + y, piece->size, attribute + piece->tile_offset + g_entry_bits[piece->palette]);
        }
    }
    g_frame_profile.hw_sprites = g_hw_count;
}

#if defined(MS_STREAMED) && MS_CACHE_SLOTS > 0
static void ms_cache_reset(void)
{
    u16 n;

    for (n = 0; n < MS_CACHE_BUCKETS; n++)
        g_cache_buckets[n] = MS_NO_ENTRY;
    for (n = 0; n < MS_CACHE_SLOTS; n++)
    {
        g_cache[n].list = MS_NOTHING_LOADED;
        g_cache[n].next = (u8)(n + 1 < MS_CACHE_SLOTS ? n + 1 : MS_NO_ENTRY);
    }
    g_cache_first = MS_NO_ENTRY;
    g_cache_free = 0;
}

/* The entry kept for a load list, or MS_NO_ENTRY. */
static u8 ms_cache_find(u16 list)
{
    u8 n = g_cache_buckets[list & (MS_CACHE_BUCKETS - 1)];

    while (n != MS_NO_ENTRY && g_cache[n].list != list)
        n = g_cache[n].next;
    return n;
}

/* The first place of `tiles` tiles in the pool, in one walk along the entries in tile order (*before: the entry it
   follows, MS_NO_ENTRY at the pool's start); 0xFFFF when there is none. */
static u16 ms_cache_room(u16 tiles, u8 *before)
{
    u16 at = g_cache_start;
    u8 prev = MS_NO_ENTRY, n = g_cache_first;

    for (;;)
    {
        u16 end = n == MS_NO_ENTRY ? g_cache_end : g_cache[n].slot.tile_index;

        if (end >= at && end - at >= tiles)
        {
            *before = prev;
            return at;
        }
        if (n == MS_NO_ENTRY)
            return 0xFFFFu;
        at = g_cache[n].slot.tile_index + g_cache[n].tiles;
        prev = n;
        n = g_cache[n].after;
    }
}

/* Room: the entry drawn longest ago goes (of equals the last in tile order), its tiles and its record free; FALSE when
   every entry was drawn this frame. One walk along the entries in tile order, which finds the one before it too. */
static u8 ms_cache_evict(void)
{
    u16 age = 0;
    u8 n, prev = MS_NO_ENTRY, oldest = MS_NO_ENTRY, before = MS_NO_ENTRY, *link;

    for (n = g_cache_first; n != MS_NO_ENTRY; prev = n, n = g_cache[n].after)
        if (g_cache[n].drawn != g_frame_number && (u16)(g_frame_number - g_cache[n].drawn) >= age)
        {
            age = (u16)(g_frame_number - g_cache[n].drawn);
            oldest = n;
            before = prev;
        }
    if (oldest == MS_NO_ENTRY)
        return FALSE;
    for (link = &g_cache_buckets[g_cache[oldest].list & (MS_CACHE_BUCKETS - 1)]; *link != oldest;
         link = &g_cache[*link].next)
        ;
    *link = g_cache[oldest].next;
    if (before == MS_NO_ENTRY)
        g_cache_first = g_cache[oldest].after;
    else
        g_cache[before].after = g_cache[oldest].after;
    g_cache[oldest].list = MS_NOTHING_LOADED;
    g_cache[oldest].next = g_cache_free;
    g_cache_free = oldest;
    return TRUE;
}

/* A new entry for a load list: room for its tiles at the first place they fit (the entries drawn longest ago making
   room while there is none) and a record; MS_NO_ENTRY when what is in the way was all drawn this frame. */
static u8 ms_cache_take(u16 list)
{
    u16 tiles = ms_load_lists[list].tile_count, at;
    u8 n, before;

    if (tiles > g_cache_end - g_cache_start)
        return MS_NO_ENTRY;
    if (g_cache_free == MS_NO_ENTRY && !ms_cache_evict())
        return MS_NO_ENTRY;
    while ((at = ms_cache_room(tiles, &before)) == 0xFFFFu)
        if (!ms_cache_evict())
            return MS_NO_ENTRY;
    n = g_cache_free;
    g_cache_free = g_cache[n].next;
    g_cache[n].list = list;
    g_cache[n].tiles = tiles;
    g_cache[n].drawn = MS_NOT_DRAWN;
    ms_slot_init(&g_cache[n].slot, at);  /* holds nothing yet: the draw uploads its tiles */
    g_cache[n].next = g_cache_buckets[list & (MS_CACHE_BUCKETS - 1)];
    g_cache_buckets[list & (MS_CACHE_BUCKETS - 1)] = n;
    if (before == MS_NO_ENTRY)
    {
        g_cache[n].after = g_cache_first;
        g_cache_first = n;
    }
    else
    {
        g_cache[n].after = g_cache[before].after;
        g_cache[before].after = n;
    }
    return n;
}

/* With the slot cache: the slot kept for the render frame's load list, or a new one, drawn through from here; FALSE
   (the draw is left out) when the cache has no room for it. */
static u8 ms_cache_slot(u16 render_index)
{
    u16 list = ms_render_frame_loads[render_index];
    u8 n;

    if (list >= ms_load_list_count || !ms_load_lists[list].tile_count)
    {
        g_slot = &g_cache_nothing;  /* no tiles, no pieces: nothing to draw, nothing to keep */
        return TRUE;
    }
    n = ms_cache_find(list);
    if (n == MS_NO_ENTRY && (n = ms_cache_take(list)) == MS_NO_ENTRY)
    {
        g_frame_profile.draws_left_out++;
        return FALSE;
    }
    if (g_cache[n].drawn != g_frame_number)
    {
        g_cache[n].drawn = g_frame_number;
        g_frame_profile.slots_used++;
    }
    g_slot = &g_cache[n].slot;
    return TRUE;
}
#endif

#if MS_QUEUED_DRAWS > 0
/* The hardware sprites a render frame puts on the screen drawn at (ox, oy) with flip, as ms_put_render_frame*() put
   them: all of them when its box lies on the screen, else those ms_push_sprite does not skip. */
static u16 ms_render_cost(const MS_RenderFrame *frame, s16 ox, s16 oy, u8 flip)
{
    const MS_Part *part;
    s16 min_x = (flip & 1) ? -frame->max_x : frame->min_x;
    s16 max_x = (flip & 1) ? -frame->min_x : frame->max_x;
    s16 min_y = (flip & 2) ? -frame->max_y : frame->min_y;
    s16 max_y = (flip & 2) ? -frame->min_y : frame->max_y;
    u16 n, k, cost = 0;

    if (ox + min_x >= 0 && oy + min_y >= 0 && ox + max_x <= g_screen_w && oy + max_y <= g_screen_h)
        return frame->sprite_count;
    part = &ms_parts[frame->first_part];
    for (n = frame->part_count; n > 0; n--, part++)
    {
        const MS_Piece *piece = &ms_pieces[part->first_piece];

        for (k = part->piece_count; k > 0; k--, piece++)
        {
            s16 x = part->x + piece->x;
            s16 y = part->y + piece->y;

            if (flip & 1)
                x = -x - (s16)((((piece->size >> 2) & 3) + 1) << 3);
            if (flip & 2)
                y = -y - (s16)(((piece->size & 3) + 1) << 3);
            cost += ms_on_screen(ox + x, oy + y, piece->size);
        }
    }
    return cost;
}

/* A draw that waits for ms_end_frame (one past the queue's room is left out: its sprites count as dropped). */
static void ms_queue_draw(u16 render, s16 x, s16 y, u16 base, u16 cost, u8 flip, u8 swap)
{
    MS_QueuedDraw *queued;

    if (g_queued_count >= MS_QUEUED_DRAWS)
    {
        g_frame_profile.draws_left_out++;
        g_frame_profile.sprites_dropped += cost;
        return;
    }
    queued = &g_queued_draws[g_queued_count++];
    queued->render = render;
    queued->x = x;
    queued->y = y;
    queued->base = base;
    queued->cost = cost;
    queued->flip = flip;
    queued->swap = swap;
    if ((flip >> 2) > g_top_level)
        g_top_level = flip >> 2;
}

/* With give-way levels: TRUE when the draw waits for ms_end_frame, because it does not fit or one before it did not. */
static u8 ms_draw_waits(u16 render_index, const MS_RenderFrame *frame, s16 ox, s16 oy, u8 flip)
{
    u16 cost;

    if (!g_waiting)
    {
        u16 room = g_hw_count < g_sprite_limit ? g_sprite_limit - g_hw_count : 0;

        if (frame->sprite_count <= room)
            return FALSE;
        cost = ms_render_cost(frame, ox, oy, flip);
        if (cost <= room)
            return FALSE;
        g_waiting = TRUE;
    }
    else
        cost = ms_render_cost(frame, ox, oy, flip);
    if (cost)
        ms_queue_draw(render_index, ox, oy, g_attr_base, cost, (u8)(flip | (g_give_way << 2)), (u8)g_active_swap);
    return TRUE;
}

/* A give-way draw that was written: it can still make room until the frame ends. */
static void ms_note_give_way(u16 first)
{
#if MS_GIVE_WAY_DRAWS > 0
    if (g_give_way_count < MS_GIVE_WAY_DRAWS)
    {
        MS_GiveWayDraw *draw = &g_give_way_draws[g_give_way_count++];

        draw->first = (u8)first;
        draw->count = (u8)(g_hw_count - first);
        draw->level = g_give_way;
        draw->gave_way = FALSE;
        if (g_give_way > g_top_level)
            g_top_level = g_give_way;
    }
#else
    (void)first;
#endif
}

/* The written draws that gave way leave the sprite table (the ones from `first` on): the sprites after them move up,
   their links follow. */
static void ms_take_out_given_way(u16 first)
{
#if MS_GIVE_WAY_DRAWS > 0
    u16 n, read = first, write = first;

    for (n = 0; n < g_give_way_count; n++)
    {
        const MS_GiveWayDraw *draw = &g_give_way_draws[n];

        if (!draw->gave_way)
            continue;
        while (read < draw->first)
            vdpSpriteCache[write++] = vdpSpriteCache[read++];
        read = draw->first + draw->count;
    }
    while (read < g_hw_count)
        vdpSpriteCache[write++] = vdpSpriteCache[read++];
    for (n = first; n < write; n++)
        vdpSpriteCache[n].link = (u8)(n + 1);
    g_hw_count = write;
#else
    (void)first;
#endif
}

/* The frame asked for more sprites than the limit and its draws wait from the first that did not fit: the draws with
   a level give way, level 1 first, within a level the last drawn first, as many as the frame asks too much; written
   ones leave the table, the waiting ones that stay are drawn behind what is left, as they would have been. */
static void ms_resolve_waiting(void)
{
    s32 excess = (s32)g_hw_count - (s32)g_sprite_limit;
    u16 n, level, given = 0, first_out = 0xFFFFu, swap = g_active_swap, base = g_attr_base;

    for (n = 0; n < g_queued_count; n++)
        excess += g_queued_draws[n].cost;
    for (level = 1; level <= g_top_level && excess > 0; level++)
    {
        for (n = g_queued_count; n-- > 0 && excess > 0;)
        {
            MS_QueuedDraw *queued = &g_queued_draws[n];

            if ((queued->flip >> 2) == level)
            {
                queued->render = MS_GAVE_WAY;
                excess -= queued->cost;
                given++;
            }
        }
#if MS_GIVE_WAY_DRAWS > 0
        for (n = g_give_way_count; n-- > 0 && excess > 0;)
        {
            MS_GiveWayDraw *draw = &g_give_way_draws[n];

            if (draw->level == level)
            {
                draw->gave_way = TRUE;
                excess -= draw->count;
                given++;
                if (draw->first < first_out)
                    first_out = draw->first;
            }
        }
#endif
    }
    if (first_out != 0xFFFFu)
        ms_take_out_given_way(first_out);
    for (n = 0; n < g_queued_count; n++)
    {
        const MS_QueuedDraw *queued = &g_queued_draws[n];

        if (queued->render == MS_GAVE_WAY)
            continue;
        if (queued->render == MS_OWN_SPRITE)
        {
            ms_push_sprite(queued->x, queued->y, queued->swap, queued->base);
            continue;
        }
        if (queued->swap != g_active_swap)
            ms_set_palette_swap(queued->swap);
        g_attr_base = queued->base;
        if (queued->flip & 3)
            ms_put_render_frame_flipped(&ms_render_frames[queued->render], queued->x, queued->y, queued->flip & 3);
        else
            ms_put_render_frame(&ms_render_frames[queued->render], queued->x, queued->y);
    }
    ms_set_palette_swap(swap);
    g_attr_base = base;
    g_frame_profile.hw_sprites = g_hw_count;
    g_frame_profile.draws_given_way = given;
}
#endif

/* Draw a render frame (flip: mirrored around the point drawn at, 0 as it is): through its slot (streamed: the cache's
   when it is on), then into the sprite table, or into the queue while give-way levels make it wait. */
static void ms_draw_render(u16 render_index, s16 ox, s16 oy, u8 flip)
{
    const MS_RenderFrame *frame;
    u16 first;

    if (render_index >= MS_RENDER_FRAME_COUNT)
        return;
#ifdef MS_STREAMED
#if MS_CACHE_SLOTS > 0
    if (g_cache_on && !ms_cache_slot(render_index))
        return;
#endif
    ms_fill_slot(render_index);
#endif
    frame = &ms_render_frames[render_index];
    g_frame_profile.render_calls++;
    g_frame_profile.parts_submitted += frame->part_count;
    flip &= 3;
    first = g_hw_count;
#if MS_QUEUED_DRAWS > 0
    if (g_levels && ms_draw_waits(render_index, frame, ox, oy, flip))
        return;
#endif
    if (flip)
        ms_put_render_frame_flipped(frame, ox, oy, flip);
    else
        ms_put_render_frame(frame, ox, oy);
#if MS_QUEUED_DRAWS > 0
    if (g_give_way && g_hw_count > first)
        ms_note_give_way(first);
#else
    (void)first;
#endif
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
    g_cache_start = tile_index;
    g_cache_end = (u32)tile_index + tile_count < 0xFFFFu ? (u16)(tile_index + tile_count) : 0xFFFFu;
    ms_slot_init(&g_cache_nothing, tile_index);
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
    g_frame_profile.slots_used = 0;
    g_frame_profile.draws_left_out = 0;
    g_frame_profile.draws_given_way = 0;
    g_hw_count = 0;
#ifdef MS_STREAMED
    if (++g_frame_number == MS_NOT_DRAWN)
        g_frame_number = 0;
#endif
#if MS_QUEUED_DRAWS > 0
    g_waiting = FALSE;
    g_top_level = 0;
    g_give_way_count = 0;
    g_queued_count = 0;
#endif
    g_screen_w = (s16)VDP_getScreenWidth();
    g_screen_h = (s16)VDP_getScreenHeight();
}

u8 ms_add_hw_sprite(s16 x, s16 y, u8 size, u16 attribute)
{
    u8 added;
#if MS_QUEUED_DRAWS > 0
    u16 first = g_hw_count;

    /* With give-way levels a sprite on the screen waits like a draw: past the limit, or behind a draw that waits. */
    if (g_levels && ms_on_screen(x, y, size) && (g_waiting || g_hw_count >= g_sprite_limit))
    {
        g_waiting = TRUE;
        ms_queue_draw(MS_OWN_SPRITE, x, y, attribute, 1, (u8)(g_give_way << 2), size);
        return TRUE;
    }
    added = ms_push_sprite(x, y, size, attribute);
    if (g_give_way && g_hw_count > first)
        ms_note_give_way(first);
#else
    added = ms_push_sprite(x, y, size, attribute);
#endif
    g_frame_profile.hw_sprites = g_hw_count;
    return added;
}

void ms_set_give_way(u8 level)
{
#if MS_QUEUED_DRAWS > 0
    g_give_way = level < MS_MAX_LEVEL ? level : MS_MAX_LEVEL;
    if (level)
        g_levels = TRUE;
#else
    g_give_way = level;
#endif
}

u8 ms_get_give_way(void)
{
    return g_give_way;
}

void ms_end_frame(void)
{
    u16 count;

#if MS_QUEUED_DRAWS > 0
    if (g_waiting)
        ms_resolve_waiting();
#endif
    count = g_hw_count;
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
    ms_draw_render(ms_module_render_frames[table_index], x, y, 0);
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
    ms_draw_render(ms_frame_render_frames[table_index], x, y, 0);
}

static u16 ms_module_render_index(u16 module_index)
{
    u32 table_index;

    if (module_index >= MS_MODULE_COUNT)
        return 0xFFFFu;
    table_index = ms_mapping_module_base() + module_index;
    if (table_index >= ((u32)MS_MAPPING_COUNT) * ((u32)MS_MODULE_COUNT))
        return 0xFFFFu;
    return ms_module_render_frames[table_index];
}

static u16 ms_frame_render(u16 frame_index)
{
    u32 table_index;

    if (frame_index >= MS_FRAME_COUNT)
        return 0xFFFFu;
    table_index = ms_mapping_frame_base() + frame_index;
    if (table_index >= ((u32)MS_MAPPING_COUNT) * ((u32)MS_FRAME_COUNT))
        return 0xFFFFu;
    return ms_frame_render_frames[table_index];
}

/* Where a module mirrored in place is drawn mirrored around its pivot: moved by its width less twice its pivot's x (and
   the same for y) of the module the active mapping draws. */
static void ms_module_flip_offset(u16 module_index, u8 flip, s16 *x, s16 *y)
{
    const s16 *offset = &ms_module_flip_offsets[(ms_mapping_module_base() + module_index) << 1];

    if (flip & 1)
        *x += offset[0];
    if (flip & 2)
        *y += offset[1];
}

void ms_draw_module_flipped(u16 module_index, s16 x, s16 y, u8 flip)
{
    u16 render = ms_module_render_index(module_index);

    if (render == 0xFFFFu)
        return;
    flip &= 3;
    if (flip)
        ms_module_flip_offset(module_index, flip, &x, &y);
    ms_draw_render(render, x, y, flip);
}

void ms_draw_frame_flipped(u16 frame_index, s16 x, s16 y, u8 flip)
{
    u16 render = ms_frame_render(frame_index);

    if (render != 0xFFFFu)
        ms_draw_render(render, x, y, flip);
}

/* The box of a render frame's hardware sprites drawn with flip, mirrored around (dx / 2, dy / 2). */
static u8 ms_render_bounds(u16 render_index, u8 flip, s16 dx, s16 dy, MS_Bounds *out)
{
    const MS_RenderFrame *frame;

    if (!out)
        return FALSE;
    out->min_x = out->min_y = out->max_x = out->max_y = 0;
    if (render_index >= MS_RENDER_FRAME_COUNT || !ms_render_frames[render_index].sprite_count)
        return FALSE;
    frame = &ms_render_frames[render_index];
    out->min_x = (flip & 1) ? dx - frame->max_x : frame->min_x;
    out->max_x = (flip & 1) ? dx - frame->min_x : frame->max_x;
    out->min_y = (flip & 2) ? dy - frame->max_y : frame->min_y;
    out->max_y = (flip & 2) ? dy - frame->min_y : frame->max_y;
    return TRUE;
}

u16 ms_frame_sprites(u16 frame_index)
{
    u16 render = ms_frame_render(frame_index);

    return render < MS_RENDER_FRAME_COUNT ? ms_render_frames[render].sprite_count : 0;
}

u16 ms_module_sprites(u16 module_index)
{
    u16 render = ms_module_render_index(module_index);

    return render < MS_RENDER_FRAME_COUNT ? ms_render_frames[render].sprite_count : 0;
}

u8 ms_frame_bounds(u16 frame_index, u8 flip, MS_Bounds *out)
{
    return ms_render_bounds(ms_frame_render(frame_index), flip, 0, 0, out);
}

u8 ms_module_bounds(u16 module_index, u8 flip, MS_Bounds *out)
{
    u16 render = ms_module_render_index(module_index);
    s16 dx = 0, dy = 0;

    if (render != 0xFFFFu)
        ms_module_flip_offset(module_index, flip, &dx, &dy);
    return ms_render_bounds(render, flip, dx, dy, out);
}

static u16 ms_render_load_list(u16 render_index)
{
#ifdef MS_STREAMED
    if (render_index < MS_RENDER_FRAME_COUNT)
        return ms_render_frame_loads[render_index];
#else
    (void)render_index;
#endif
    return MS_NOTHING_LOADED;
}

u16 ms_frame_load_list(u16 frame_index)
{
    return ms_render_load_list(ms_frame_render(frame_index));
}

u16 ms_module_load_list(u16 module_index)
{
    return ms_render_load_list(ms_module_render_index(module_index));
}

u16 ms_load_list_tiles(u16 load_list)
{
#ifdef MS_STREAMED
    if (load_list < ms_load_list_count)
        return ms_load_lists[load_list].tile_count;
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
    ms_draw_render(step->frame_index, x, y, 0);
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

    ms_draw_render(ms_scene_samples[scene->first_sample + sample_index], x, y, 0);
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
