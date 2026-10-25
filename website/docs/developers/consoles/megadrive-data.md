# Mega Drive data

The Mega Drive export writes the whole project into one binary blob, `res/gen/modsprite_blob.bin`, which SGDK's resource compiler puts into the cartridge as `MS_BLOB` (`BIN MS_BLOB "gen/modsprite_blob.bin" 2 2 0 NONE FALSE` in `res/resources.res`). The generated `src/modsprite_data.c` parses it at start (`ms_data_init()`) and `inc/modsprite_data.h` declares its record types. This page documents version 7 (resident exports) and version 8 (streamed exports), for an engine that reads the blob itself.

## Layout

- Big-endian, like the 68000.
- Every section starts on an even offset (the strings may not), and every record is packed with its 16- and 32-bit fields on even offsets (`__attribute__((packed, aligned(2)))`), so the 68000 reads them with single moves.
- Offsets are bytes from the start of the blob.

## The header

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | magic: `MSB1` (0x4D534231) |
| 4 | 2 | version: 7, or 8 for a streamed export |
| 6 | 2 | palette entries |
| 8 | 46 | 23 counts, each `u16`, in this order: variants, modules, frames, animations, scenes, mappings, render frames, animation steps, scene samples, animation records, scene records, event types, step events, tiles, pieces, hitboxes, points, hitbox types, point types, roles, base palettes, palette swaps (counting 0, no swap), colour cycles |
| 54 | 4 | parts (`u32`) |
| 58 | 148 | the offsets of the 37 sections below, each `u32`, in the order of the table |
| 206 | 4 | the size of the strings section |
| 210 | 18 | *version 8 only*: load lists (`u16`), load entries (`u32`), then the offsets of `render_frame_loads`, `load_lists` and `load_entries` (`u32` each) |

The header is 210 bytes, 228 in version 8.

## The sections

| # | Section | Contents |
|---|---|---|
| 0 | `parts` | `MS_Part` records |
| 1 | `render_frames` | `MS_RenderFrame` records |
| 2 | `module_render_frames` | `u16` render frame per (mapping, module): index `mapping × modules + module` |
| 3 | `frame_render_frames` | `u16` render frame per (mapping, frame) |
| 4 | `anim_steps` | `MS_AnimStep` records |
| 5 | `animations` | `MS_Animation` records, one per (mapping, animation): index `mapping × animations + animation` |
| 6 | `scene_samples` | `u16` render frame per sample |
| 7 | `scenes` | `MS_Scene` records, one per (mapping, scene) |
| 8, 9 | `mapping_ids`, `mapping_names` | string tables, one entry per mapping (mapping 0: no mapping) |
| 10, 11 | `module_ids`, `module_names` | string tables |
| 12, 13 | `frame_ids`, `frame_names` | string tables |
| 14, 15 | `animation_ids`, `animation_names` | string tables |
| 16, 17 | `scene_ids`, `scene_names` | string tables |
| 18 | `strings` | the texts the string tables point to |
| 19 | `step_events` | `MS_StepEvent` records |
| 20 | `event_names` | string table, one per event type |
| 21 | `variants` | `MS_Variant` records |
| 22 | `pieces` | `MS_Piece` records |
| 23 | `tiles` | the tiles: 32 bytes each, 4 bits a pixel, in the VDP's order |
| 24 | `palette` | 16 colours per palette entry, VDP colour words (`0000 BBB0 GGG0 RRR0`) |
| 25 | `boxes` | `MS_Hitbox` records |
| 26 | `points` | `MS_Point` records |
| 27, 28, 29 | `box_type_names`, `point_type_names`, `role_names` | string tables |
| 30 | `palette_entries` | `MS_PaletteEntry` records |
| 31 | `colour_cycles` | `MS_ColourCycle` records |
| 32 | `swap_entries` | `u8` per (swap from 1, base palette): the entry swap `s` makes of palette `p` is at `(s - 1) × base palettes + p` |
| 33, 34 | `swap_ids`, `swap_names` | string tables, one per swap (swap 0: none) |
| 35 | `palette_names` | string table, one per palette entry |
| 36 | `module_flip_offsets` | two `s16` per (mapping, module): its width less twice its pivot's x, its height less twice its pivot's y |

A **string table** has a `u32` per item: the offset (from the start of the blob) of a zero-terminated UTF-8 text in the strings section.

Version 8 adds three sections, found through the header's last fields: `render_frame_loads` (a `u16` load list per render frame), `load_lists` and `load_entries`.

## The records

```c
typedef struct {            /* 8 bytes */
    u16 first_piece;        /* the part's pieces: first_piece .. + piece_count - 1, laid out for its flips */
    u8  piece_count;
    u8  flip;               /* bit 0 horizontal, bit 1 vertical: the hardware flips of its sprites */
    s16 x, y;               /* from the draw position */
} MS_Part;

typedef struct {            /* 28 bytes */
    u32 first_part;
    u16 part_count;         /* the parts, back to front: the last is in front */
    u16 hitbox_count;
    u32 first_hitbox;
    u32 first_point;
    u16 point_count;
    u16 sprite_count;       /* hardware sprites */
    s16 min_x, min_y, max_x, max_y;   /* the box around them, from the draw position */
} MS_RenderFrame;

typedef struct {            /* 6 bytes: one baked module picture; the runtime does not need it */
    u16 first_piece;
    u16 piece_count;
    u8  tile_w, tile_h;     /* its size padded to whole tiles: flips mirror the pieces inside it */
} MS_Variant;

typedef struct {            /* 8 bytes: one hardware sprite */
    s16 x, y;               /* from the part's position */
    u8  size;               /* the VDP's size code: (width in tiles - 1) << 2 | (height in tiles - 1) */
    u8  palette;            /* its palette entry; bit 7 (MS_FIXED_ENTRY): not recoloured by the active swap */
    u16 tile_offset;        /* its first tile, from the tile base (streamed: from the slot's first tile) */
} MS_Piece;

typedef struct {            /* 12 bytes */
    u8  type;               /* hitbox type, 0xFF: unknown */
    u8  reserved0;
    u16 role;               /* 0xFFFF: none */
    s16 x, y, w, h;         /* from the draw position, already moved like the picture */
} MS_Hitbox;

typedef struct {            /* 8 bytes */
    u8  type;
    u8  reserved0;
    u16 role;
    s16 x, y;
} MS_Point;

typedef struct {            /* 8 bytes */
    u16 frame_index;        /* the step's render frame (its frame with the step's offset, flips and turn) */
    u16 duration_ticks;     /* in video frames at 60 a second */
    u16 first_event;
    u8  event_count;
    u8  reserved0;
} MS_AnimStep;

typedef struct {            /* 16 bytes */
    u32 first_step;
    u16 step_count;
    u16 fps;                /* the editor's tick rate (the steps are already in video frames) */
    u8  playback;           /* 0 loop, 1 once, 2 ping-pong, 3 backward */
    u8  reserved0;
    u16 loop_start;         /* loop: later passes start at this step */
    u16 next_animation;     /* the follow-up, 0xFFFF: none */
    u16 loop_count;         /* passes before it ends, 0: never */
} MS_Animation;

typedef struct { u16 type; s16 value; } MS_StepEvent;   /* 4 bytes */

typedef struct {            /* 14 bytes */
    u32 first_sample;
    u16 sample_count;
    u16 fps;                /* samples a second */
    u16 duration_ticks;     /* in video frames */
    u8  loop;
    u8  reserved0, reserved1, reserved2;
} MS_Scene;

typedef struct {            /* 6 bytes */
    u8  palette;            /* the editor's palette it is, or recolours */
    u8  swap;               /* the swap that made it, 0: the palette itself */
    u16 first_cycle;
    u8  cycle_count;
    u8  reserved0;
} MS_PaletteEntry;

typedef struct {            /* 6 bytes */
    u8  first, count;       /* count slots from first rotate one slot */
    u16 frames;             /* every this many video frames */
    u8  reverse;            /* towards the first slot instead of the last */
    u8  reserved0;
} MS_ColourCycle;

/* version 8 */
typedef struct { u32 first_entry; u16 entry_count; u16 tile_count; } MS_LoadList;   /* 8 bytes */
typedef struct { u16 first_tile; u16 tile_count; } MS_LoadEntry;                  /* 4 bytes: tiles of the tiles section */
```

## How the pieces fit together

- **Mappings.** Every per-mapping table has one block per mapping, mapping 0 (no mapping) first, then the exported mappings in order. A module a mapping hides has an empty render frame.
- **Palette entries.** The first entries (as many as the base palettes) are the editor's palettes in their order; then, for each swap, its version of each palette it changes. Entry `e`'s colours are `palette[e × 16 .. e × 16 + 15]`, colour 0 transparent.
- **Tiles, resident.** A resident export's tiles go to video memory in the order of the section, from the tile base; a piece's tile offset counts from there.
- **Tiles, streamed.** A render frame's load list names runs of the tiles section (`first_tile`, `tile_count`); copied one after the other from a slot's first tile, they give the tiles its pieces count from. The tiles are laid out in the order frames first use them, so lists have few runs; identical lists are stored once. A list with no tiles draws nothing.

## Drawing a render frame

The runtime's loop, for an engine that draws the data itself:

```c
const MS_RenderFrame *rf = &render_frames[index];
for (p = rf->first_part + rf->part_count; p-- > rf->first_part; )   /* the last part first: it is in front */
{
    const MS_Part *part = &parts[p];
    for (k = 0; k < part->piece_count; k++)
    {
        const MS_Piece *piece = &pieces[part->first_piece + k];
        s16 x = part->x + piece->x, y = part->y + piece->y;
        if (flip & 1) x = -x - ((((piece->size >> 2) & 3) + 1) << 3);   /* mirrored draws only */
        if (flip & 2) y = -y - (((piece->size & 3) + 1) << 3);
        put_sprite(draw_x + x, draw_y + y, piece->size,
                   tile_base + piece->tile_offset            /* streamed: the slot's first tile */
                   + (line_of(piece->palette) << 13)          /* the palette line: bits 13 and 14 */
                   + ((part->flip ^ flip) << 11));            /* bit 11 H flip, bit 12 V flip */
    }
}
```

The first sprite put is the first in the VDP's list, in front. A part's pieces are already laid out for the part's flips; the part's flip bits only set the hardware flips. The runtime draws with priority off.

**The palette line** of a piece's entry: an entry below the base palette count is one of the editor's palettes; under palette swap `s` it is drawn from entry `swap_entries[(s - 1) × base palettes + entry]`. An entry with bit 7 (`MS_FIXED_ENTRY`) set is a scene object's own colours: drawn from entry `palette & 0x7F` whatever the swap. The line is the one that entry is loaded in, else the one its palette is loaded in, else the first line.

**Culling.** A render frame whose box (`min_x` ... `max_y`) lies on the screen and whose sprites fit under the limit is copied whole; otherwise each sprite is tested: one off the screen is skipped (a sprite at x = -128 would hide the sprites behind it on its lines), one over the limit is dropped.

## Versions

| Version | What changed |
|---|---|
| 8 (since 0.12) | streamed exports: version 6 with the module flip offsets of version 7 |
| 7 (since 0.12) | resident exports: version 5 with each module's flip offset under each mapping (`ms_draw_module_flipped` mirrors in place) |
| 6 | streamed exports only, never in a release: a load list per render frame; pieces count their tiles from the slot |
| 5 (0.9 to 0.11) | palette entries with their colour cycles, the swaps' entry table, each piece's palette entry |
| 4 (0.8) | several palettes |
| 3 | tiles, pieces and palette in the blob; hitboxes, points, type and role names; sprite count and box per render frame |
| 2 | step events, loop-from step, follow-up animation and repeat count |

The generated parser accepts only the version it was generated for: data, parser and runtime come from the same export and editor version.
