# SNES data

The SNES export writes the project into chunks of at most 32 KB, one LoROM bank each, with the C that finds them. This page documents data version 4 (resident exports) and 5 (streamed exports), for an engine that reads the data itself. The generated `inc/modsprite_data.h` declares every record and table named here.

## The files

| File | |
|---|---|
| `res/ms_chunk_NN.bin` | the data, in chunks of at most 32 KB |
| `modsprite_chunks.asm` | one `superfree` section per chunk, labelled `ms_chunk_NN`, so the linker places each in a bank |
| `inc/modsprite_data.h` | the counts and constants (as numbers), the record types, the tables' declarations |
| `src/modsprite_data.c` | `ms_chunks[]` and the tables' addresses in the chunks; `ms_data_init()` sets them up |
| `modsprite_rom.mk` | `ROMBANKS` and `ROMSIZE`: the ROM size the chunks need |

## Layout

- Little-endian, like the 65816. Every 16-bit field sits on an even offset, so the records read the same packed or aligned.
- The records the runtime indexes are padded to 8 or 16 bytes (816-tcc multiplies by other sizes with a library call); a render frame's 22 bytes are multiplied in shifts.
- A table the runtime indexes sits whole in one chunk. Render frames come in pages of 1024 (`MS_RF_PAGE_SHIFT`, `ms_rf_pages[]`); `ms_render_frame(index)` finds one.
- Lists a render frame points to are **far references**: an offset into a chunk and the chunk's number, `MS_FAR(chunk, offset)`.

## Constants

`MS_DATA_VERSION`, the counts (`MS_MODULE_COUNT`, `MS_FRAME_COUNT`, `MS_ANIMATION_COUNT`, `MS_SCENE_COUNT`, `MS_MAPPING_COUNT`, `MS_RENDER_FRAME_COUNT`, `MS_ANIM_STEP_COUNT`, `MS_TILE_COUNT`, `MS_PALETTE_ENTRY_COUNT`, `MS_BASE_PALETTE_COUNT`, `MS_PALETTE_SWAP_COUNT`, ...), the sprite sizes (`MS_SMALL_SIZE`, `MS_LARGE_SIZE`, and `MS_OBJ_SIZE`, OBSEL's size select in bits 5 to 7), `MS_TILE_TABLES`, `MS_FIXED_ENTRY` (0x80), `MS_NO_ANIMATION` and `MS_NO_ROLE` (0xFFFF), `MS_UNKNOWN_TYPE` (0xFF), and the project's `MS_EVENT_*`, `MS_HITBOX_*`, `MS_POINT_*` and `MS_ROLE_*`. A streamed export adds `MS_STREAMED`, `MS_SLOT_TILES`, `MS_SCENE_SLOT_TILES`, `MS_SLOT_ALIGN` and `MS_UPLOAD_BUDGET`.

## The records

```c
typedef struct {                 /* 22 bytes */
    u16 sprites_offset; u8 sprites_chunk; u8 run_count;   /* its sprites: run_count runs */
    u16 boxes_offset;   u8 boxes_chunk;   u8 box_count;
    u16 points_offset;  u8 points_chunk;  u8 point_count;
    u8  sprite_count;   u8 part_count;
    s16 min_x, min_y, max_x, max_y;      /* the box around its sprites, from the draw position */
} MS_RenderFrame;

typedef struct { u8 palette; u8 count; } MS_Run;   /* 2 bytes, then count MS_Sprite */
/* palette: the run's palette entry; MS_FIXED_ENTRY set: a scene object's own colours, not recoloured */

typedef struct {                 /* 8 bytes: one hardware sprite, ready for the OAM */
    s16 x, y;                    /* from the draw position */
    u8  tile;                    /* the tile's low 8 bits */
    u8  attribute;               /* V flip 0x80, H flip 0x40, the tile's bit 8 0x01 */
    u8  size;                    /* 2: large (its bit in the high table), 0: small */
    u8  reserved;
} MS_Sprite;

typedef struct { u8 type; u8 reserved; u16 role; s16 x, y, w, h; u16 reserved2[2]; } MS_Hitbox;   /* 16 bytes */
typedef struct { u8 type; u8 reserved; u16 role; s16 x, y; } MS_Point;                           /* 8 bytes */

typedef struct {                 /* 8 bytes */
    u16 frame_index;             /* the step's render frame */
    u16 duration_ticks;          /* in video frames at 60 a second */
    u16 first_event; u8 event_count; u8 reserved;
} MS_AnimStep;

typedef struct {                 /* 16 bytes */
    u16 first_step; u16 step_count; u16 fps;
    u8  playback;                /* 0 loop, 1 once, 2 ping-pong, 3 backward */
    u8  reserved;
    u16 loop_start; u16 next_animation; u16 loop_count; u16 reserved2;
} MS_Animation;

typedef struct { u16 type; s16 value; } MS_StepEvent;   /* 4 bytes */

typedef struct {                 /* 16 bytes */
    u16 first_sample; u16 sample_count; u16 fps;
    u16 duration_ticks;          /* in video frames */
    u8  loop; u8 reserved; u16 reserved2[3];
} MS_Scene;

typedef struct { u8 palette; u8 swap; u16 first_cycle; u8 cycle_count; u8 reserved; u16 reserved2; } MS_PaletteEntry;  /* 8 */
typedef struct { u8 first; u8 count; u16 frames; u8 reverse; u8 reserved; u16 reserved2; } MS_ColourCycle;            /* 8 */
```

Hitboxes and points are already moved like the picture, relative to the draw position. Field meanings are those of the [Mega Drive's records](megadrive-data.md#the-records).

## The tables

| Table | |
|---|---|
| `ms_tile_tables[2]` | resident exports: the two sprite tables, 256 tiles each (8 KB, 4 bits a pixel in the SNES's planar format), as they go into video memory |
| `ms_module_render_frames`, `ms_frame_render_frames` | `u16` render frame per (mapping, module or frame): index `mapping × count + index` |
| `ms_anim_steps`, `ms_animations` | the steps; one animation record per (mapping, animation) |
| `ms_step_events` | the events the steps name |
| `ms_scene_samples`, `ms_scenes` | `u16` render frame per sample; one scene record per (mapping, scene) |
| `ms_palette` | 16 BGR555 colours (`0bbbbbgg gggrrrrr`) per palette entry |
| `ms_palette_entries`, `ms_colour_cycles` | as on the Mega Drive |
| `ms_swap_entries` | `u8` per (swap from 1, base palette): the entry swap `s` makes of palette `p` is at `(s - 1) × base palettes + p` |
| `ms_module_flip_offsets` | two `s16` per (mapping, module): its width less twice its pivot's x, its height less twice its pivot's y |
| names and ids | `ms_module_names(i)`, `ms_module_ids(i)`, and the same for mappings, frames, animations, scenes, events, types, roles, swaps and palette entries |

Mapping 0 is no mapping, then the exported mappings in order.

## Tiles

A resident export packs the squares of the two sizes into the two tables, largest first, each at the first free place aligned to its size: a square of N pixels takes N/8 × N/8 tiles in a table 16 tiles wide, its first tile a multiple of N/8 in both directions, as the PPU finds them. Squares with the same pixels are stored once; a sprite's tile number (9 bits) counts from the first table.

## Streamed exports (version 5)

The cartridge keeps the squares in strips: each frame's new squares, in the order frames first use them, side by side in rows of at most 16 tiles. Every render frame names a load list:

```c
/* ms_render_frame_loads: a u16 load list per render frame (MS_NO_LIST: it shows nothing) */
typedef struct { u16 entries_offset; u8 entries_chunk; u8 group_count; u16 tile_count; u16 cost; } MS_LoadList;  /* 8 */
typedef struct { u8 chunk; u8 count; } MS_LoadGroup;          /* 2: the chunk its runs read, then count entries */
typedef struct { u16 vram; u16 source; u16 bytes; } MS_LoadEntry;   /* 6: one DMA run */
/* ms_load_list_rows: a u8 per list, the sprite-table rows it takes in a slot */
```

A list is `group_count` groups; each group names a chunk and holds `count` entries, each a DMA run copying `bytes` from `source` in that chunk to the slot's VRAM word address plus `vram`. Laid out in a slot of whole rows, each square aligned to its size, the runs give the tiles the render frame's sprites count from: a sprite's tile number is the slot's first tile plus the sprite's (an addition, not an or). `cost` is what the list takes of the upload budget: its bytes plus the set-up of its runs, groups and the list, measured in Mesen 2. Identical lists are stored once.

## Drawing a render frame

```c
const MS_RenderFrame *rf = ms_render_frame(index);
const u8 *at = MS_FAR(rf->sprites_chunk, rf->sprites_offset);
for (r = 0; r < rf->run_count; r++)
{
    const MS_Run *run = (const MS_Run *)at;
    u8 bits = priority | palette_bits(run->palette);     /* the OAM byte's priority and palette (bits 1-3) */
    at += sizeof(MS_Run);
    for (k = 0; k < run->count; k++, at += sizeof(MS_Sprite))
    {
        const MS_Sprite *s = (const MS_Sprite *)at;
        s16 size = s->size ? MS_LARGE_SIZE : MS_SMALL_SIZE;
        s16 x = (flip & 1) ? -s->x - size : s->x;         /* mirrored draws only */
        s16 y = (flip & 2) ? -s->y - size : s->y;
        u16 tile = (s->tile | ((s->attribute & 1) << 8)) + tile_base;   /* streamed: the slot's first tile */
        oam_put(draw_x + x, draw_y + y, tile,
                ((s->attribute & 0xC0) ^ flip_bits) | bits,  /* flip_bits: H 0x40, V 0x80 of the mirrored draw */
                s->size);
    }
}
```

The sprites are stored in OAM order, the first in front. The palette bits come from the run's entry as on the Mega Drive: under palette swap `s` an entry below the base palette count is drawn from `ms_swap_entries[(s - 1) × base palettes + entry]`, an entry with `MS_FIXED_ENTRY` set from its own, each from the sprite palette it is loaded in. The runtime draws with priority 2.

## Versions

| Version | What changed |
|---|---|
| 5 (0.12) | streamed exports: version 3 with the module flip offsets of version 4, and each load list's rows (`ms_load_list_rows`) |
| 4 (0.12) | resident exports: version 2 with each module's flip offset under each mapping |
| 3 | streamed exports only, never in a release: load lists, sprites counted from a slot |
| 2 (0.10 to 0.11) | the first released version |

The generated files carry the version (`MS_DATA_VERSION`); data, generated code and runtime come from the same export and editor version.
