"""The SNES runtime (snes_demo/src/modsprite.c) compiled for the host, and the SNES's sprite table decoded like the PPU
draws it: tests/test_snes_runtime_draw.py and tests/test_snes_runtime_player.py check the runtime against the editor
with it, tools/check_snes_rom.py the ROM against it.

PVSnesLib is replaced by a small stub (the OAM buffer, VRAM and CGRAM as arrays); the harness loads the export's real
data chunks and runs commands from stdin, printing the OAM buffer after each (as hex, 544 bytes); a draw ends with
ms_upload_tiles() as a game's frame does. A streamed export's harness draws the second character of "versus" through a
slot of its own (after the default one) and adds to each draw's line the tiles it uploaded, the draws that waited, the
load lists it queued and, when it uploaded, video memory from tile 0 to the second slot's end (``parse_draw``):

    frame INDEX MAPPING X Y                  ms_draw_frame with that mapping
    flipped INDEX MAPPING FLIP X Y           ms_draw_frame_flipped with that mapping
    module INDEX MAPPING FLIP X Y            ms_draw_module_flipped (FLIP 0: drawn as ms_draw_module draws it)
    crowd INDEX MAPPING COUNT X Y DX         a frame drawn COUNT times in one sprite table, DX apart, the flips 0 to 3
                                             in turn (past the 128 sprites: the limit, sprites dropped)
    lists MAPPING                            each frame's and each module's load list and its tiles
                                             ("list:tiles,..." for the frames, then for the modules, "-" for none),
                                             then the ones out of range ("frame:module:tiles") (no OAM)
    scene INDEX MAPPING TICKS X Y            a scene player ticked TICKS times
    versus ANIM MAPPING SWAP TICKS X Y X2 Y2 an animation drawn as it is, then with ms_draw_anim_player_as
    facing ANIM MAPPING SWAP FLIP TICKS X Y X2 Y2  the same mirrored: by FLIP (ms_draw_anim_player_flipped), then
                                             the other way left to right, FLIP ^ 1 (ms_draw_anim_player_as_flipped)
    step ANIM STEP FLIP X Y                  an animation's step (its player's step_index set) drawn mirrored with
                                             ms_draw_anim_player_flipped, after "marks" and the step's hitboxes and
                                             points through ms_flip_hitbox / ms_flip_point (each with 1 when it came
                                             back in *out and a copy mirrored in place came out the same)
    sprite X Y TILE ATTRIBUTE LARGE          a game's own sprite (ms_add_hw_sprite)
    cycle                                    the sprite palettes in CGRAM (128 words), then one ms_palette_tick
    budget BYTES                             ms_set_upload_budget (streamed)
    vblank CHECKS                            the next ms_upload_tiles finds the vertical blank over after CHECKS
                                             looks (one before and one after each list; streamed)
    player ANIM TICKS                        an animation player for TICKS video frames: per frame
                                             "animation:step:finished:event type 0 started:event type 1's value:
                                             hitboxes|points" (no OAM)
    markers FRAME                            a frame's "hitboxes|points" (no OAM)
    counts MAPPING                           each frame's and each module's hardware sprites and bounds under the
                                             mapping ("sprites:ok/min_x/min_y/max_x/max_y" for flips 0 to 3, ";"
                                             between the flips, "," between the items: the frames, then the modules)
                                             (no OAM)
    begin                                    ms_begin_frame: a picture drawn by the commands up to "end"
    put frame INDEX MAPPING FLIP LEVEL X Y   ms_draw_frame_flipped with that mapping and give-way level
    put module INDEX MAPPING FLIP LEVEL X Y  ms_draw_module_flipped
    put sprite X Y TILE ATTRIBUTE LARGE LEVEL  ms_add_hw_sprite with that give-way level
    end                                      ms_end_frame, then "given GAVE_WAY LEFT_OUT SLOTS_USED" before the draw
    cache TILE COUNT                         ms_slot_cache_init (streamed): draws take slots from the cache
    usecache                                 ms_use_slot_cache: the cache again (streamed)
    uncached                                 ms_set_slot(NULL): the default slot again
    checksum                                 a sum of every frame's and module's sprites and bounds under every
                                             mapping and flip and of every frame's hitboxes and points mirrored each
                                             way ("sum N"), then an empty frame drawn
    vramdump TILES                           a streamed draw's line shows video memory up to that tile (0: as above)

Hitboxes print as "type,role,x,y,w,h" and points as "type,role,x,y", separated by ";".
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

import console_bake
import export_snes
from models import Project

SCREEN_W, SCREEN_H = 256, 224
DEMO = Path(__file__).resolve().parents[1] / "snes_demo"

SNES_STUB = r"""
#ifndef SNES_STUB_H
#define SNES_STUB_H
#include <stdint.h>
#include <stddef.h>
typedef int8_t s8; typedef uint8_t u8; typedef int16_t s16; typedef uint16_t u16;
typedef int32_t s32; typedef uint32_t u32;
#define TRUE 0xff
#define FALSE 0
extern u8 oamMemory[128 * 4 + 8 * 4];
void dmaCopyVram(u8 *source, u16 address, u16 size);
void dmaCopyCGram(u8 *source, u16 address, u16 size);
void oamInitGfxAttr(u16 address, u8 oamsize);
#endif
"""

HARNESS = r"""
#include <stdio.h>
#include <string.h>
#include "modsprite.h"

u8 oamMemory[128 * 4 + 8 * 4];
static u16 g_vram[0x8000];
static u16 g_cgram[256];
static u16 g_obj_address = 0xFFFF;
static u8 g_obj_size = 0xFF;
void dmaCopyVram(u8 *source, u16 address, u16 size) { memcpy(&g_vram[address], source, size); }
void dmaCopyCGram(u8 *source, u16 address, u16 size) { memcpy(&g_cgram[address], source, size); }
void oamInitGfxAttr(u16 address, u8 oamsize) { g_obj_address = address; g_obj_size = oamsize; }

@CHUNKS@

static void load_chunks(const char *dir)
{
    char path[1024];
    unsigned i;
    for (i = 0; i < MS_CHUNK_COUNT; i++)
    {
        FILE *f;
        snprintf(path, sizeof(path), "%s/ms_chunk_%02u.bin", dir, i);
        f = fopen(path, "rb");
        if (!f) { printf("missing %s\n", path); return; }
        fread(g_chunk_data[i], 1, 0x8000, f);
        fclose(f);
    }
}

static void print_markers(const MS_Hitbox *boxes, u16 box_count, const MS_Point *points, u16 point_count)
{
    u16 i;
    for (i = 0; i < box_count; i++)
        printf("%s%u,%u,%d,%d,%d,%d", i ? ";" : "", boxes[i].type, boxes[i].role, boxes[i].x, boxes[i].y, boxes[i].w,
               boxes[i].h);
    printf("|");
    for (i = 0; i < point_count; i++)
        printf("%s%u,%u,%d,%d", i ? ";" : "", points[i].type, points[i].role, points[i].x, points[i].y);
}

/* The same through ms_flip_hitbox / ms_flip_point, each with 1 when it came back in *out and a copy mirrored in place
   came out the same. */
static void print_flipped_markers(const MS_Hitbox *boxes, u16 box_count, const MS_Point *points, u16 point_count,
                                  u8 flip)
{
    MS_Hitbox box, again;
    MS_Point point, same;
    u16 i;
    u8 out;
    for (i = 0; i < box_count; i++)
    {
        out = ms_flip_hitbox(&boxes[i], flip, &box) == &box;
        again = boxes[i];
        ms_flip_hitbox(&again, flip, &again);
        printf("%s%u,%u,%d,%d,%d,%d,%u", i ? ";" : "", box.type, box.role, box.x, box.y, box.w, box.h,
               out && again.type == box.type && again.role == box.role && again.x == box.x && again.y == box.y
               && again.w == box.w && again.h == box.h);
    }
    printf("|");
    for (i = 0; i < point_count; i++)
    {
        out = ms_flip_point(&points[i], flip, &point) == &point;
        same = points[i];
        ms_flip_point(&same, flip, &same);
        printf("%s%u,%u,%d,%d,%u", i ? ";" : "", point.type, point.role, point.x, point.y,
               out && same.type == point.type && same.role == point.role && same.x == point.x && same.y == point.y);
    }
}

#ifdef MS_STREAMED
static MS_Slot g_second_slot;
static u16 g_vblank_checks = 0xFFFF;
static u16 g_vram_dump_tiles = 0;
u8 ms_host_in_vblank(void)
{
    if (g_vblank_checks == 0xFFFF)
        return TRUE;
    if (!g_vblank_checks)
        return FALSE;
    g_vblank_checks--;
    return TRUE;
}
#endif

static void dump(const char *what)
{
    unsigned i;
    MS_FrameProfile profile;
#ifdef MS_STREAMED
    extern u16 ms_upload_count;
    extern u16 ms_upload_lists[];
    u16 queued[8], count = ms_upload_count;
    memcpy(queued, ms_upload_lists, sizeof(queued));
#endif
    ms_get_frame_profile(&profile);
    ms_upload_tiles();
#ifdef MS_STREAMED
    g_vblank_checks = 0xFFFF;
#endif
    printf("%s %u %u ", what, profile.hw_sprites, profile.sprites_dropped);
    for (i = 0; i < sizeof(oamMemory); i++)
        printf("%02x", oamMemory[i]);
#ifdef MS_STREAMED
    printf(" %u %u ", profile.tiles_uploaded, profile.uploads_waiting);
    for (i = 0; i < count; i++)
        printf("%s%u", i ? "," : "", queued[i]);
    printf("%s ", count ? "" : "-");
    if (profile.tiles_uploaded)
        for (i = 0; i < (unsigned)(g_vram_dump_tiles ? g_vram_dump_tiles : ms_tiles_end() + ms_slot_tiles()) * 16u; i++)
            printf("%04x", g_vram[i]);
    else
        printf("-");
#endif
    printf("\n");
}

/* What tools/check_snes_rom.py's probe sums too: every frame's and module's sprites and bounds, every mapping and flip,
   and every frame's hitboxes and points mirrored each way (the active mapping left at 0). */
static u16 query_sum(void)
{
    u16 m, n, k, flip, count, sum = 0;
    MS_Bounds box;
    const MS_Hitbox *boxes;
    const MS_Point *points;
    MS_Hitbox hitbox;
    MS_Point point;

    for (m = 0; m < MS_MAPPING_COUNT; m++)
    {
        ms_set_mapping(m);
        for (n = 0; n < MS_FRAME_COUNT + MS_MODULE_COUNT; n++)
            for (flip = 0; flip < 4; flip++)
            {
                u8 shows = n < MS_FRAME_COUNT ? ms_frame_bounds(n, (u8)flip, &box)
                                              : ms_module_bounds(n - MS_FRAME_COUNT, (u8)flip, &box);
                sum = (u16)(sum * 31u + (n < MS_FRAME_COUNT ? ms_frame_sprites(n) : ms_module_sprites(n - MS_FRAME_COUNT))
                            + shows + (u16)box.min_x * 3u + (u16)box.min_y * 5u + (u16)box.max_x * 7u
                            + (u16)box.max_y * 11u);
            }
        for (n = 0; n < MS_FRAME_COUNT; n++)
            for (flip = 0; flip < 4; flip++)
            {
                count = ms_frame_hitboxes(n, &boxes);
                for (k = 0; k < count; k++)
                {
                    ms_flip_hitbox(&boxes[k], (u8)flip, &hitbox);
                    sum = (u16)(sum * 31u + hitbox.type + hitbox.role * 3u + (u16)hitbox.x * 5u + (u16)hitbox.y * 7u
                                + (u16)hitbox.w * 11u + (u16)hitbox.h * 13u);
                }
                count = ms_frame_points(n, &points);
                for (k = 0; k < count; k++)
                {
                    ms_flip_point(&points[k], (u8)flip, &point);
                    sum = (u16)(sum * 31u + point.type + point.role * 3u + (u16)point.x * 5u + (u16)point.y * 7u);
                }
            }
    }
    ms_set_mapping(0);
    return sum;
}

static void print_bounds(u16 sprites, u8 (*bounds)(u16, u8, MS_Bounds *), u16 index)
{
    unsigned flip;
    printf("%u:", sprites);
    for (flip = 0; flip < 4; flip++)
    {
        MS_Bounds box;
        u8 ok = bounds(index, (u8)flip, &box);
        printf("%s%u/%d/%d/%d/%d", flip ? ";" : "", ok ? 1 : 0, box.min_x, box.min_y, box.max_x, box.max_y);
    }
}

int main(int argc, char **argv)
{
    unsigned i;
    char line[256];
    load_chunks(argv[1]);
    ms_init();
    printf("obsel %u %u\n", g_obj_address, g_obj_size);
    printf("sizes %u %u %u %u %u %u %u %u %u %u %u", (unsigned)sizeof(MS_RenderFrame), (unsigned)sizeof(MS_Run),
           (unsigned)sizeof(MS_Sprite), (unsigned)sizeof(MS_Hitbox), (unsigned)sizeof(MS_Point),
           (unsigned)sizeof(MS_AnimStep), (unsigned)sizeof(MS_Animation), (unsigned)sizeof(MS_StepEvent),
           (unsigned)sizeof(MS_Scene), (unsigned)sizeof(MS_PaletteEntry), (unsigned)sizeof(MS_ColourCycle));
#ifdef MS_STREAMED
    printf(" %u %u %u", (unsigned)sizeof(MS_LoadList), (unsigned)sizeof(MS_LoadGroup), (unsigned)sizeof(MS_LoadEntry));
    ms_slot_init(&g_second_slot, ms_tiles_end());
#endif
    printf("\n");
    printf("vram ");
    for (i = 0; i < 0x2000; i++)
        printf("%04x", g_vram[i]);
    printf("\ncgram ");
    for (i = 0; i < 256; i++)
        printf("%04x", g_cgram[i]);
    printf("\n");
    while (fgets(line, sizeof(line), stdin))
    {
        unsigned index, mapping, swap, flip, ticks, t;
        int x, y, x2, y2;
        if (sscanf(line, "frame %u %u %d %d", &index, &mapping, &x, &y) == 4)
        {
            ms_set_mapping(mapping);
            ms_begin_frame();
            ms_draw_frame(index, x, y);
            ms_end_frame();
            dump("frame");
        }
        else if (sscanf(line, "flipped %u %u %u %d %d", &index, &mapping, &swap, &x, &y) == 5)
        {
            ms_set_mapping(mapping);
            ms_begin_frame();
            ms_draw_frame_flipped(index, x, y, (u8)swap);
            ms_end_frame();
            dump("flipped");
        }
        else if (sscanf(line, "crowd %u %u %u %d %d %d", &index, &mapping, &ticks, &x, &y, &x2) == 6)
        {
            ms_set_mapping(mapping);
            ms_begin_frame();
            for (t = 0; t < ticks; t++)
                ms_draw_frame_flipped(index, x + (int)t * x2, y, (u8)(t & 3));
            ms_end_frame();
            dump("crowd");
        }
        else if (sscanf(line, "module %u %u %u %d %d", &index, &mapping, &swap, &x, &y) == 5)
        {
            ms_set_mapping(mapping);
            ms_begin_frame();
            ms_draw_module_flipped(index, x, y, (u8)swap);
            ms_end_frame();
            dump("module");
        }
        else if (sscanf(line, "lists %u", &mapping) == 1)
        {
            ms_set_mapping(mapping);
            printf("lists %s", MS_FRAME_COUNT ? "" : "-");
            for (t = 0; t < MS_FRAME_COUNT; t++)
                printf("%s%u:%u", t ? "," : "", ms_frame_load_list(t), ms_load_list_tiles(ms_frame_load_list(t)));
            printf(" %s", MS_MODULE_COUNT ? "" : "-");
            for (t = 0; t < MS_MODULE_COUNT; t++)
                printf("%s%u:%u", t ? "," : "", ms_module_load_list(t), ms_load_list_tiles(ms_module_load_list(t)));
            printf(" %u:%u:%u\n", ms_frame_load_list(MS_FRAME_COUNT), ms_module_load_list(MS_MODULE_COUNT),
                   ms_load_list_tiles(0xFFFF));
        }
        else if (sscanf(line, "scene %u %u %u %d %d", &index, &mapping, &ticks, &x, &y) == 5)
        {
            MS_ScenePlayer player;
            ms_set_mapping(mapping);
            ms_scene_player_init(&player, index);
            for (t = 0; t < ticks; t++)
                ms_scene_player_tick(&player);
            ms_begin_frame();
            ms_draw_scene_player(&player, x, y);
            ms_end_frame();
            dump("scene");
        }
        else if (sscanf(line, "versus %u %u %u %u %d %d %d %d", &index, &mapping, &swap, &ticks, &x, &y, &x2, &y2) == 8)
        {
            MS_AnimPlayer player;
            ms_set_mapping(0);
            ms_set_palette_swap(0);
            ms_anim_player_init(&player, index);
            for (t = 0; t < ticks; t++)
                ms_anim_player_tick(&player);
            ms_begin_frame();
            ms_draw_anim_player(&player, x, y);
#ifdef MS_STREAMED
            ms_set_slot(&g_second_slot);
#endif
            ms_draw_anim_player_as(&player, mapping, swap, x2, y2);
#ifdef MS_STREAMED
            ms_set_slot(NULL);
#endif
            ms_end_frame();
            printf("step %u %u %u ", player.step_index, ms_get_mapping(), ms_get_palette_swap());
            dump("versus");
        }
        else if (sscanf(line, "facing %u %u %u %u %u %d %d %d %d", &index, &mapping, &swap, &flip, &ticks, &x, &y, &x2,
                        &y2) == 9)
        {
            MS_AnimPlayer player;
            ms_set_mapping(0);
            ms_set_palette_swap(0);
            ms_anim_player_init(&player, index);
            for (t = 0; t < ticks; t++)
                ms_anim_player_tick(&player);
            ms_begin_frame();
            ms_draw_anim_player_flipped(&player, x, y, (u8)flip);
#ifdef MS_STREAMED
            ms_set_slot(&g_second_slot);
#endif
            ms_draw_anim_player_as_flipped(&player, mapping, swap, x2, y2, (u8)(flip ^ 1));
#ifdef MS_STREAMED
            ms_set_slot(NULL);
#endif
            ms_end_frame();
            printf("step %u %u %u ", player.step_index, ms_get_mapping(), ms_get_palette_swap());
            dump("facing");
        }
        else if (sscanf(line, "step %u %u %u %d %d", &index, &ticks, &flip, &x, &y) == 5)
        {
            MS_AnimPlayer player;
            const MS_Hitbox *boxes;
            const MS_Point *points;
            u16 box_count, point_count;
            ms_set_mapping(0);
            ms_set_palette_swap(0);
            ms_anim_player_init(&player, index);
            player.step_index = (u16)ticks;
            box_count = ms_anim_player_hitboxes(&player, &boxes);
            point_count = ms_anim_player_points(&player, &points);
            printf("marks ");
            print_flipped_markers(boxes, box_count, points, point_count, (u8)flip);
            printf(" ");
            ms_begin_frame();
            ms_draw_anim_player_flipped(&player, x, y, (u8)flip);
            ms_end_frame();
            dump("step");
        }
        else if (sscanf(line, "sprite %d %d %u %u %u", &x, &y, &index, &mapping, &swap) == 5)
        {
            u8 added;
            ms_begin_frame();
            added = ms_add_hw_sprite(x, y, index, (u8)mapping, (u8)swap);
            ms_end_frame();
            printf("added %u ", added);
            dump("sprite");
        }
        else if (sscanf(line, "player %u %u", &index, &ticks) == 2)
        {
            MS_AnimPlayer player;
            ms_set_mapping(0);
            ms_anim_player_init(&player, index);
            printf("player");
            for (t = 0; t < ticks; t++)
            {
                const MS_Hitbox *boxes;
                const MS_Point *points;
                u16 box_count, point_count;
                if (t > 0)
                    ms_anim_player_tick(&player);
                box_count = ms_anim_player_hitboxes(&player, &boxes);
                point_count = ms_anim_player_points(&player, &points);
                printf(" %u:%u:%u:%u:%d:", player.animation_index, player.step_index, player.finished ? 1 : 0,
                       ms_anim_player_event_started(&player, 0) ? 1 : 0, ms_anim_player_event_value(&player, 1, 0));
                print_markers(boxes, box_count, points, point_count);
            }
            printf("\n");
        }
        else if (sscanf(line, "counts %u", &mapping) == 1)
        {
            ms_set_mapping(mapping);
            printf("counts %s", MS_FRAME_COUNT ? "" : "-");
            for (t = 0; t < MS_FRAME_COUNT; t++)
            {
                printf("%s", t ? "," : "");
                print_bounds(ms_frame_sprites(t), ms_frame_bounds, t);
            }
            printf(" %s", MS_MODULE_COUNT ? "" : "-");
            for (t = 0; t < MS_MODULE_COUNT; t++)
            {
                printf("%s", t ? "," : "");
                print_bounds(ms_module_sprites(t), ms_module_bounds, t);
            }
            printf(" %u:%u\n", ms_frame_sprites(MS_FRAME_COUNT), ms_module_sprites(MS_MODULE_COUNT));
        }
        else if (strncmp(line, "begin", 5) == 0)
            ms_begin_frame();
        else if (strncmp(line, "checksum", 8) == 0)
        {
            printf("sum %u ", query_sum());
            ms_begin_frame();
            ms_end_frame();
            dump("checksum");
        }
        else if (sscanf(line, "put frame %u %u %u %u %d %d", &index, &mapping, &swap, &ticks, &x, &y) == 6)
        {
            ms_set_mapping(mapping);
            ms_set_give_way((u8)ticks);
            ms_draw_frame_flipped(index, x, y, (u8)swap);
        }
        else if (sscanf(line, "put module %u %u %u %u %d %d", &index, &mapping, &swap, &ticks, &x, &y) == 6)
        {
            ms_set_mapping(mapping);
            ms_set_give_way((u8)ticks);
            ms_draw_module_flipped(index, x, y, (u8)swap);
        }
        else if (sscanf(line, "put sprite %d %d %u %u %u %u", &x, &y, &index, &mapping, &swap, &ticks) == 6)
        {
            ms_set_give_way((u8)ticks);
            ms_add_hw_sprite(x, y, index, (u8)mapping, (u8)swap);
        }
        else if (strncmp(line, "end", 3) == 0)
        {
            MS_FrameProfile profile;
            ms_set_give_way(0);
            ms_end_frame();
            ms_get_frame_profile(&profile);
            printf("given %u %u %u ", profile.draws_given_way, profile.draws_left_out, profile.slots_used);
            dump("picture");
        }
        else if (sscanf(line, "markers %u", &index) == 1)
        {
            const MS_Hitbox *boxes;
            const MS_Point *points;
            u16 box_count, point_count;
            ms_set_mapping(0);
            box_count = ms_frame_hitboxes(index, &boxes);
            point_count = ms_frame_points(index, &points);
            printf("markers ");
            print_markers(boxes, box_count, points, point_count);
            printf("\n");
        }
#ifdef MS_STREAMED
        else if (sscanf(line, "cache %u %u", &index, &ticks) == 2)
            ms_slot_cache_init((u16)index, (u16)ticks);
        else if (strncmp(line, "uncached", 8) == 0)
            ms_set_slot(NULL);
        else if (strncmp(line, "usecache", 8) == 0)
            ms_use_slot_cache();
        else if (sscanf(line, "vramdump %u", &index) == 1)
            g_vram_dump_tiles = (u16)index;
        else if (sscanf(line, "budget %u", &index) == 1)
            ms_set_upload_budget((u16)index);
        else if (sscanf(line, "vblank %u", &index) == 1)
            g_vblank_checks = (u16)index;
#endif
        else if (strncmp(line, "cycle", 5) == 0)
        {
            printf("cgram");
            for (t = 0; t < 128; t++)
                printf(" %u", g_cgram[128 + t]);
            printf("\n");
            ms_palette_tick();
        }
    }
    return 0;
}
"""


def have_compiler() -> bool:
    return shutil.which("cc") is not None


_FLIP_OFFSETS: Dict[int, List[Tuple[int, int]]] = {}  # a bake's module flip offsets, worked out once


def draw_cost(ctx: export_snes.SNESBakeContext, kind: str, index: int, mapping: int, flip: int, x: int, y: int) -> int:
    """The hardware sprites a draw puts on the screen: a frame or module (ms_draw_frame_flipped,
    ms_draw_module_flipped: a module mirrored in place) or a game's own sprite (index its tile, flip 1 when large)."""
    if kind == "sprite":
        size = ctx.large if flip else ctx.small
        return int(-size < x < SCREEN_W and -size < y < SCREEN_H)
    count = len(ctx.project.frames if kind == "frame" else ctx.project.modules)
    render = (ctx.frame_render_frames if kind == "frame" else ctx.module_render_frames)[mapping * count + index]
    if kind == "module":
        offsets = _FLIP_OFFSETS.get(id(ctx))
        if offsets is None:
            offsets = _FLIP_OFFSETS[id(ctx)] = ctx.module_flip_offsets()
        dx, dy = offsets[mapping * count + index]
        x, y = x + (dx if flip & 1 else 0), y + (dy if flip & 2 else 0)
    data, runs = ctx.sprite_runs(ctx.render_frames[render], ctx.render_frame_slot_tiles[render] if ctx.streamed
                                 else None)
    cost = at = 0
    for _run in range(runs):
        sprites = data[at + 1]
        at += export_snes.RUN.size
        for _sprite in range(sprites):
            sx, sy, _tile, _attribute, large, _zero = export_snes.SPRITE.unpack_from(data, at)
            at += export_snes.SPRITE.size
            size = ctx.large if large else ctx.small
            sx, sy = x + (-sx - size if flip & 1 else sx), y + (-sy - size if flip & 2 else sy)
            cost += -size < sx < SCREEN_W and -size < sy < SCREEN_H
    return cost


def export(project: Project, folder: Path, mappings: str = "all", mode: str = "parts") -> export_snes.SNESBakeContext:
    """The project exported into ``folder`` (res/, inc/, src/ as in a PVSnesLib project); returns the bake."""
    ctx = export_snes.SNESBakeContext(project, console_bake.resolve_mappings(project, mappings), mode=mode)
    ctx.bake()
    ctx.write(folder)
    return ctx


def build(ctx: export_snes.SNESBakeContext, folder: Path) -> Path:
    """The harness compiled with the runtime and the export in ``folder``; raises RuntimeError with the compiler's
    output when that fails."""
    stub = folder / "stub"
    stub.mkdir(exist_ok=True)
    (stub / "snes.h").write_text(SNES_STUB)
    chunks = "\n".join(f"unsigned char ms_chunk_{i:02d}[0x8000];" for i in range(len(ctx.chunk_data)))
    chunks += "\nstatic unsigned char *const g_chunk_data[] = {" + ", ".join(
        f"ms_chunk_{i:02d}" for i in range(len(ctx.chunk_data))) + "};"
    (stub / "harness.c").write_text(HARNESS.replace("@CHUNKS@", chunks))
    exe = stub / "harness"
    # modsprite.h next to this export's modsprite_data.h: it includes it from its own folder (the demo's has its own).
    shutil.copy(DEMO / "inc" / "modsprite.h", folder / "inc" / "modsprite.h")
    result = subprocess.run(
        ["cc", "-std=c99", "-w", "-DMS_PUT_FRAME_C", f"-I{stub}", f"-I{folder / 'inc'}",
         str(DEMO / "src" / "modsprite.c"), str(folder / "src" / "modsprite_data.c"), str(stub / "harness.c"),
         "-o", str(exe)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-3000:])
    return exe


def run(exe: Path, folder: Path, commands: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """The harness's head (obsel, sizes, vram, cgram) and one output line per command."""
    result = subprocess.run([str(exe), str(folder / "res")], input="\n".join(commands) + "\n", capture_output=True,
                            text=True, check=True)
    lines = result.stdout.splitlines()
    head = {line.split(" ", 1)[0]: line.split(" ", 1)[1] for line in lines[:4]}
    return head, lines[4:]


def vram_bytes(head: Dict[str, str]) -> bytes:
    """VRAM as the harness printed it (16-bit words) back in byte order."""
    words = bytes.fromhex(head["vram"])
    return bytes(words[i ^ 1] for i in range(len(words)))


def parse_markers(text: str):
    """("type,role,x,y,w,h;...|type,role,x,y;...") -> ([(type, role, x, y, w, h)], [(type, role, x, y)])."""
    boxes, points = text.split("|")
    as_tuples = lambda part: [tuple(int(v) for v in item.split(",")) for item in part.split(";") if item]  # noqa: E731
    return as_tuples(boxes), as_tuples(points)


def oam_of(line: str) -> str:
    """The OAM hex of a draw's harness output line."""
    return parse_draw(line)["oam"]


def parse_draw(line: str) -> Dict[str, Any]:
    """A draw's harness output line: what, sprites, dropped, oam; a streamed export's also uploaded, waiting, queued
    (the load lists it queued) and vram (bytes from tile 0, b"" when the draw uploaded nothing)."""
    fields = line.split(" ")
    oam_at = next(i for i, field in enumerate(fields) if len(field) == 2 * 544)
    draw: Dict[str, Any] = {"what": fields[0], "sprites": int(fields[oam_at - 2]), "dropped": int(fields[oam_at - 1]),
                            "oam": fields[oam_at]}
    if len(fields) > oam_at + 1:
        draw["uploaded"], draw["waiting"] = int(fields[oam_at + 1]), int(fields[oam_at + 2])
        queued = fields[oam_at + 3]
        draw["queued"] = [] if queued == "-" else [int(n) for n in queued.split(",")]
        vram = fields[oam_at + 4]
        draw["vram"] = b"" if vram == "-" else vram_bytes({"vram": vram})
    return draw


def decode_oam(hexdata: str) -> List[Tuple[int, int, int, int, bool]]:
    """The 128 entries of an OAM dump: (x, y, tile, attribute, large)."""
    data = bytes.fromhex(hexdata)
    entries = []
    for n in range(128):
        low = data[n * 4:n * 4 + 4]
        high = (data[512 + n // 4] >> ((n % 4) * 2)) & 3
        x = low[0] | ((high & 1) << 8)
        x = x - 512 if x >= 256 else x
        entries.append((x, low[1], low[2] | ((low[3] & 1) << 8), low[3], bool(high & 2)))
    return entries


def rasterise(entries, vram: bytes, small: int, large: int, first_palette: int = 0) -> Dict[Tuple[int, int], Tuple[int, int]]:
    """{(x, y): (palette entry, colour slot)} of the OAM as the PPU shows it: lower entries in front, a sprite's tiles
    16 to a row in its table, lines wrap at 256."""
    out = {}
    for x, y, tile, attr, is_large in reversed(entries):
        size = large if is_large else small
        hflip, vflip = attr & 0x40, attr & 0x80
        palette = ((attr >> 1) & 7) - first_palette
        for sy in range(size):
            line = (y + sy) & 0xFF
            if line >= SCREEN_H:
                continue
            for sx in range(size):
                column = x + sx
                if not 0 <= column < SCREEN_W:
                    continue
                ux = size - 1 - sx if hflip else sx
                uy = size - 1 - sy if vflip else sy
                number = (tile & 0x100) | ((((tile >> 4) + uy // 8) & 0x0F) << 4) | (((tile & 0x0F) + ux // 8) & 0x0F)
                base = number * 32
                row, bit = uy % 8, 0x80 >> (ux % 8)
                index = sum(1 << plane for plane, at in ((0, base + 2 * row), (1, base + 2 * row + 1),
                                                          (2, base + 16 + 2 * row), (3, base + 17 + 2 * row))
                            if vram[at] & bit)
                if index:
                    out[(column, line)] = (palette, index)
    return out
