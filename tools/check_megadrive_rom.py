"""Build the Mega Drive runtime into a ROM with SGDK and check what it draws on the console against the host build of
the same runtime, which tests/test_megadrive_runtime_draw.py checks against the editor (needs SGDK's toolchain,
m68k-elf-gcc, and BlastEm; neither is needed by the editor or its tests).

For each project: exports it (examples/megadrive/tools/export_megadrive.py) into a copy of the Mega Drive demo with a
probe program in place of the demo's main.c and builds the ROM (make debug; --release: make release, as games ship
it). BlastEm plays it through its GDB stub
(``blastem ROM -D`` speaks the GDB remote protocol on its standard input and output): a breakpoint in the probe stops
it after every draw, and the script reads the sprite table cache (vdpSpriteCache), the frame's profile, the VDP's sprite
table read back from video memory and the draw's time. The probe draws every frame at three positions, as it is and
mirrored (ms_draw_frame_flipped, the three ways in turn), every module (ms_draw_module_flipped: as it is or mirrored,
in turn), crowds of one frame past the 80 sprites, each scene at a few moments with every mapping, one animation twice
with ms_draw_anim_player_as (the second time with another mapping and palette swap) and twice facing itself
(ms_draw_anim_player_flipped each way, then ms_draw_anim_player_as_flipped the other way left to right), a game's own
sprites (ms_add_hw_sprite) across the screen's edges, the sum of every frame's and module's sprites and bounds
(ms_frame_sprites, ms_frame_bounds, ...) and of every frame's hitboxes and points mirrored each way (ms_flip_hitbox,
ms_flip_point), copies of a few frames in one picture each (what one draw takes, as it is,
mirrored and across an edge) and pictures of many draws, one that fits and some past the 80 sprites: as they are, only
the draws that would stay, and with give-way levels, timing each draw with the VDP's V counter; then it turns
the colour cycles (two added to the first palette when it has none) for 47 video frames and plays the first scene for
ten seconds, each frame drawn from the top of the screen and timed. The same probe compiled for the host, with the
tests' stand-in for SGDK, makes the same calls: every sprite table (all 80 entries) and profile must equal the host
build's, the VDP's sprite table the sprite table cache, video memory the export's tiles, the palette lines the host
build's after as many palette ticks and the scene's frames (a sum of their sprite tables) the host build's.

With --mode parts_streamed or frames_streamed the export is streamed: after each draw the vertical blank sends the
tiles it queued, and the probe sums the slots' video memory (the default slot and a second one, or for the pictures
drawn through it the slot cache's pool after them) for the script to compare with the host build's.

The ROM draws frames of MS_ASM_SPRITES hardware sprites or more with the runtime's 68000 loops (src/modsprite_draw.s),
smaller ones with its C loops; --c builds it with the C loops alone (MS_PUT_FRAME_C, as the host build always draws), to
compare their times.

Usage (from the repository root):
    python3 tools/check_megadrive_rom.py [PROJECT.json ...] [--mode MODE] [--c] [--release] [--blastem PATH]
        [--keep DIR] [--timings FILE]
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "examples" / "megadrive" / "megadrive_demo"
SGDK = DEMO / "third_party" / "sgdk"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "examples" / "megadrive" / "tools"))
sys.path.insert(0, str(REPO / "tests"))

import console_bake  # noqa: E402
import console_exports  # noqa: E402
import export_megadrive  # noqa: E402
from models import Project  # noqa: E402
from runtime_models import crowd_draws, given_way  # noqa: E402
from test_megadrive_runtime_draw import _md_draw_costs, _tables  # noqa: E402  (the host build the tests use)
from test_megadrive_runtime_player import GENESIS_STUB, GENESIS_STUB_IMPL  # noqa: E402

DEFAULT_PROJECTS = [REPO / "examples" / "pop" / "PoP_WW.json", REPO / "examples" / "sonic" / "sonic.json",
                    REPO / "examples" / "adventurer" / "adventurer.json"]
SCREEN_W, SCREEN_H = 320, 224
POSITIONS = [(160, 112), (6, 10), (310, 216)]  # the middle of the screen, across the top-left and bottom-right edges
SCENE_X, SCENE_Y = 160, 168  # where the demo draws scenes (SPRITE_DRAW_X / Y, ui/scene_editor/ops.screen_origin)
SCENE_TICKS = (0, 60, 300)
PALETTE_TICKS = 47  # with the cycles below: every cycle in a step other than its first
PLAY_FRAMES = 600
SPRITE_LIMIT = 80
TILE_USER_INDEX = 16  # SGDK's, and the host stand-in's
TILE_FONT_INDEX = 1440  # the host stand-in's; the probe reports the ROM's
LINES_PER_FRAME = 262  # NTSC
LINE_US = 3420 / 53.693175  # a scanline: 3420 master cycles
KINDS = {"frame": 0, "module": 1, "sprite": 2}

# The probe's drawing, the same in the ROM and in the host build: setup, each item between probe_start() and
# probe_stop() (the ROM times it there), the region of video memory its draws went to, and the queries' sum.
PROBE_SHARED = r"""
#define PROBE_COUNT @COUNT@
#define PROBE_TICKS @TICKS@
#define PROBE_PLAY @PLAY@
#define PROBE_SLOTS_FIRST @SLOTS_FIRST@  /* streamed: the default slot and the second one, tiles from here */
#define PROBE_SLOTS_TILES @SLOTS_TILES@  /* 0: a resident export */
#define PROBE_CACHE_FIRST @CACHE_FIRST@  /* the slot cache's pool (streamed) */
#define PROBE_CACHE_TILES @CACHE_TILES@  /* 0: no slot cache */

/* kind (0 frame, 1 scene, 2 versus, 3 a sprite of the game's own: index = size, mapping = attribute, 4 a frame mirrored
   and 5 a module as it is or mirrored: swap = flip, 6 a crowd: a frame swap times, x2 apart, the flips 0 to 3 in turn,
   7 a picture: the draws index .. index + mapping - 1 of probe_draws, swap bit 0 with their give-way levels, bit 1
   through the slot cache, 8 the sum of every frame's and module's sprites, bounds and load lists and of every frame's
   hitboxes and points mirrored each way, 9 versus facing: mirrored by y2, the second at (x2, y) the other way left to
   right), index, mapping, swap, ticks, x, y, x2, y2 */
static const s16 probe_items[PROBE_COUNT * 9] = {
@ITEMS@
};
/* A picture's draws: kind (0 frame, 1 module, 2 a sprite of the game's own: index = its size), index, mapping (and
   the palette swap of that number, where there is one), flip, give-way level, x, y */
static const s16 probe_draws[@DRAW_COUNT@ * 7 + 1] = {
@DRAWS@
};

static MS_Slot probe_second;  /* the second draw of "versus" (streamed) */
static u16 probe_query;       /* kind 8: the queries' sum */

static void probe_start(void);
static void probe_stop(void);

static u16 probe_query_sum(void)
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
        {
            u16 frame = n < MS_FRAME_COUNT;
            u16 list = frame ? ms_frame_load_list(n) : ms_module_load_list(n - MS_FRAME_COUNT);

            sum = (u16)(sum * 31u + list + ms_load_list_tiles(list) * 3u);
            for (flip = 0; flip < 4; flip++)
            {
                u8 shows = frame ? ms_frame_bounds(n, (u8)flip, &box)
                                 : ms_module_bounds(n - MS_FRAME_COUNT, (u8)flip, &box);

                sum = (u16)(sum * 31u + (frame ? ms_frame_sprites(n) : ms_module_sprites(n - MS_FRAME_COUNT)) + shows
                            + (u16)box.min_x * 3u + (u16)box.min_y * 5u + (u16)box.max_x * 7u + (u16)box.max_y * 11u);
            }
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

static void probe_setup(void)
{
    memset(vdpSpriteCache, 0, sizeof(VDPSprite) * 80);
    ms_init();
    ms_slot_init(&probe_second, ms_tile_base() + ms_tiles_used());
    if (PROBE_CACHE_TILES)
    {
        ms_slot_cache_init(PROBE_CACHE_FIRST, PROBE_CACHE_TILES);
        ms_set_slot(NULL);
    }
}

/* Item i, from ms_begin_frame to ms_end_frame. */
static void probe_draw(u16 i)
{
    const s16 *item = &probe_items[i * 9];
    MS_ScenePlayer scene;
    MS_AnimPlayer player;
    u16 t;
    u8 level = 0;

    probe_query = 0;
    ms_set_mapping(0);
    ms_set_palette_swap(0);
    if (item[0] == 1)
    {
        ms_set_mapping((u16)item[2]);
        ms_scene_player_init(&scene, (u16)item[1]);
        for (t = 0; t < (u16)item[4]; t++)
            ms_scene_player_tick(&scene);
    }
    else if (item[0] == 2 || item[0] == 9)
    {
        ms_anim_player_init(&player, (u16)item[1]);
        for (t = 0; t < (u16)item[4]; t++)
            ms_anim_player_tick(&player);
    }
    else if (item[0] != 7 && item[0] != 8)
        ms_set_mapping((u16)item[2]);
    if (item[0] == 7 && (item[3] & 2))
        ms_use_slot_cache();
    probe_start();
    if (item[0] == 8)
        probe_query = probe_query_sum();
    ms_begin_frame();
    switch (item[0])
    {
    case 0:
        ms_draw_frame((u16)item[1], item[5], item[6]);
        break;
    case 1:
        ms_draw_scene_player(&scene, item[5], item[6]);
        break;
    case 2:
        ms_draw_anim_player(&player, item[5], item[6]);
        ms_set_slot(&probe_second);
        ms_draw_anim_player_as(&player, (u16)item[2], (u16)item[3], item[7], item[8]);
        ms_set_slot(NULL);
        break;
    case 3:
        ms_add_hw_sprite(item[5], item[6], (u8)item[1], (u16)item[2]);
        break;
    case 4:
        ms_draw_frame_flipped((u16)item[1], item[5], item[6], (u8)item[3]);
        break;
    case 5:
        ms_draw_module_flipped((u16)item[1], item[5], item[6], (u8)item[3]);
        break;
    case 6:
        for (t = 0; t < (u16)item[3]; t++)
            ms_draw_frame_flipped((u16)item[1], item[5] + (s16)t * item[7], item[6], (u8)(t & 3));
        break;
    case 7:
        for (t = 0; t < (u16)item[2]; t++)
        {
            const s16 *draw = &probe_draws[(item[1] + t) * 7];

            ms_set_mapping((u16)draw[2]);
            ms_set_palette_swap((u16)draw[2] < MS_PALETTE_SWAP_COUNT ? (u16)draw[2] : 0);
            if ((item[3] & 1) && (u8)draw[4] != level)
            {
                level = (u8)draw[4];
                ms_set_give_way(level);  /* when it changes, as a game sets it */
            }
            if (draw[0] == 0)
                ms_draw_frame_flipped((u16)draw[1], draw[5], draw[6], (u8)draw[3]);
            else if (draw[0] == 1)
                ms_draw_module_flipped((u16)draw[1], draw[5], draw[6], (u8)draw[3]);
            else
                ms_add_hw_sprite(draw[5], draw[6], (u8)draw[1],
                                 TILE_ATTR_FULL(PAL1, FALSE, FALSE, FALSE, 20 + draw[1]));
        }
        if (level)
            ms_set_give_way(0);
        break;
    case 9:
        ms_draw_anim_player_flipped(&player, item[5], item[6], (u8)item[8]);
        ms_set_slot(&probe_second);
        ms_draw_anim_player_as_flipped(&player, (u16)item[2], (u16)item[3], item[7], item[6], (u8)(item[8] ^ 1));
        ms_set_slot(NULL);
        break;
    default:
        break;
    }
    ms_end_frame();
    probe_stop();
    if (item[0] == 7 && (item[3] & 2))
        ms_set_slot(NULL);
}

/* A sum of the sprite table ms_end_frame sent, going on from sum. */
static u32 probe_table_sum(u32 sum)
{
    MS_FrameProfile profile;
    u16 n, count;

    ms_get_frame_profile(&profile);
    count = profile.hw_sprites ? profile.hw_sprites : 1;
    for (n = 0; n < count; n++)
        sum = sum * 31u + (u16)vdpSpriteCache[n].y + ((u32)vdpSpriteCache[n].size << 16)
              + ((u32)vdpSpriteCache[n].link << 8) + (u32)vdpSpriteCache[n].attribut * 7u
              + (u32)(u16)vdpSpriteCache[n].x * 3u;
    return sum;
}

/* A video frame of the first scene played (the mapping and palette swap 0): ticked, then drawn. */
static void probe_play(MS_ScenePlayer *scene)
{
    probe_start();
    ms_begin_frame();
    ms_scene_player_tick(scene);
    ms_draw_scene_player(scene, @SCENE_X@, @SCENE_Y@);
    ms_end_frame();
    probe_stop();
}

/* The video memory item i drew into (streamed): the slot cache's pool, or the default slot and the second one. */
static void probe_region(u16 i, u16 *first, u16 *count)
{
    const s16 *item = &probe_items[i * 9];

    if (item[0] == 7 && (item[3] & 2))
    {
        *first = PROBE_CACHE_FIRST;
        *count = PROBE_CACHE_TILES;
    }
    else
    {
        *first = PROBE_SLOTS_FIRST;
        *count = PROBE_SLOTS_TILES;
    }
}

/* All of it: the slots and the pool (streamed), else the tiles ms_init loaded. */
static void probe_all(u16 *first, u16 *count)
{
    if (PROBE_SLOTS_TILES)
    {
        *first = PROBE_SLOTS_FIRST;
        *count = PROBE_CACHE_TILES ? PROBE_CACHE_FIRST + PROBE_CACHE_TILES - PROBE_SLOTS_FIRST : PROBE_SLOTS_TILES;
    }
    else
    {
        *first = ms_tile_base();
        *count = ms_tiles_used();
    }
}
"""

PROBE_ROM = r"""/* Generated by tools/check_megadrive_rom.py: draws each item as the host build does and stops at
   probe_check() for the script (BlastEm's GDB stub) to read probe and vdpSpriteCache; each draw timed with the V
   counter from line 0. */
#include <genesis.h>
#include <string.h>
#include "modsprite.h"
@SHARED@

typedef struct
{
    u16 state;       /* 1: item `item` was drawn, 2: the palette ticks, 3: the scene played */
    u16 item;
    u16 lines;       /* scanlines from probe_start() to probe_stop() */
    u16 frames;      /* vertical blanks meanwhile */
    u16 query;       /* kind 8: the queries' sum */
    u16 sent;        /* the sprites ms_end_frame sent, read back into table */
    u16 profile[8];  /* MS_FrameProfile after ms_end_frame */
    u32 vram;        /* the sum of the video memory the item drew into (streamed); state 2: all of it */
    u16 font;        /* TILE_FONT_INDEX */
    u16 played;      /* state 3: the frames of the first scene played, each drawn from line 0 */
    u16 most;        /* the most scanlines one took */
    u16 late;        /* the ones that took 224 scanlines or more (they would miss the vertical blank) */
    u16 average;     /* the scanlines they took on average, in tenths */
    u32 play;        /* a sum of their sprite tables */
    u16 cram[64];    /* state 2: colour RAM */
    u16 table[320];  /* the VDP's sprite table */
} Probe;

volatile Probe probe;
static u32 probe_t0;
static u16 probe_v0;

void __attribute__((noinline)) probe_check(void)
{
    asm volatile ("nop");
}

static void probe_start(void)
{
    while (GET_VCOUNTER != 0)
        ;
    probe_t0 = vtimer;
    probe_v0 = GET_VCOUNTER;
}

/* Scanlines since line 0 of the frame vtimer was probe_t0 in (NTSC, 262 lines; the vertical interrupt counts vtimer
   at line 224; the V counter goes 0x00-0xEA, then 0xE5-0xFF): an ambiguous value is told apart by the counter's
   seventh change after it (one more: before the jump; seven more: after it). */
static void probe_stop(void)
{
    u16 v = GET_VCOUNTER, n, last, k = (u16)(vtimer - probe_t0), lines;

    if (!k)
        lines = v;
    else if (v <= 0xDF)
        lines = k * 262 + v;
    else if (v >= 0xE5 && v <= 0xEA)
    {
        last = v;
        for (n = 0; n < 7; n++)
        {
            while (GET_VCOUNTER == last)
                ;
            last = GET_VCOUNTER;
        }
        lines = (k - 1) * 262 + v + (((u16)(last - v) & 0xFF) == 7 ? 6 : 0);
    }
    else
        lines = (k - 1) * 262 + (v <= 0xEA ? v : v + 6);
    probe.lines = lines - probe_v0;
    probe.frames = (u16)(vtimer - probe_t0);
}

/* Words of video memory or colour RAM through the VDP's data port, the interrupts off. */
static void probe_read(u32 command, volatile u16 *to, u16 words)
{
    vu32 *ctrl = (vu32 *)VDP_CTRL_PORT;
    vu16 *data = (vu16 *)VDP_DATA_PORT;

    SYS_disableInts();
    VDP_setAutoInc(2);
    *ctrl = command;
    while (words--)
        *to++ = *data;
    SYS_enableInts();
}

/* A sum of `count` tiles of video memory from `first`, word by word, as the host build sums them. */
static u32 probe_vram_sum(u16 first, u16 count)
{
    vu32 *ctrl = (vu32 *)VDP_CTRL_PORT;
    vu16 *data = (vu16 *)VDP_DATA_PORT;
    u32 n = (u32)count * 16u;
    u16 a = 0, b = 0;

    SYS_disableInts();
    VDP_setAutoInc(2);
    *ctrl = VDP_READ_VRAM_ADDR((u32)first * 32u);
    while (n--)
    {
        a += *data;
        b += a;
    }
    SYS_enableInts();
    return ((u32)b << 16) | a;
}

int main(bool hardReset)
{
    MS_FrameProfile profile;
    u16 i, t, first, count;

    (void)hardReset;
    VDP_setScreenWidth320();
    DMA_setMaxQueueSize(@DMA_QUEUE@);  /* every run a frame queues fits, as in the host build */
    probe_all(&first, &count);
    if (PROBE_SLOTS_TILES)
        VDP_fillTileData(0, first, count, TRUE);  /* the slots start empty, as the host build's */
    probe.font = TILE_FONT_INDEX;
    probe_setup();
    for (i = 0; i < PROBE_COUNT; i++)
    {
        probe_draw(i);
        ms_get_frame_profile(&profile);
        SYS_doVBlankProcess();  /* the sprite table and the queued tiles go to video memory */
        memcpy((void *)probe.profile, &profile, sizeof(profile));
        probe.sent = profile.hw_sprites ? profile.hw_sprites : 1;
        probe_read(VDP_READ_VRAM_ADDR((u32)VDP_getSpriteListAddress()), probe.table, probe.sent * 4);
        probe_region(i, &first, &count);
        probe.vram = count ? probe_vram_sum(first, count) : 0;
        probe.query = probe_query;
        probe.item = i;
        probe.state = 1;
        probe_check();
    }
    for (t = 0; t < PROBE_TICKS; t++)
    {
        SYS_doVBlankProcess();
        ms_palette_tick();  /* in the vertical blank, as colour RAM takes it */
    }
    probe_read(VDP_READ_CRAM_ADDR(0), probe.cram, 64);
    probe_all(&first, &count);
    probe.vram = probe_vram_sum(first, count);
    probe.state = 2;
    probe_check();
    if (MS_SCENE_COUNT)
    {
        MS_ScenePlayer scene;
        u32 lines = 0;

        ms_set_mapping(0);
        ms_set_palette_swap(0);
        ms_scene_player_init(&scene, 0);
        for (t = 0; t < PROBE_PLAY; t++)
        {
            SYS_doVBlankProcess();
            probe_play(&scene);
            lines += probe.lines;
            if (probe.lines > probe.most)
                probe.most = probe.lines;
            if (probe.lines >= 224)
                probe.late++;
            probe.play = probe_table_sum(probe.play);
        }
        probe.played = PROBE_PLAY;
        probe.average = (u16)(lines * 10u / PROBE_PLAY);
    }
    probe.state = 3;
    probe_check();
    while (1)
        SYS_doVBlankProcess();
    return 0;
}
"""

PROBE_HOST = r"""/* Generated by tools/check_megadrive_rom.py: the probe's drawing on the host, one line per item: the
   queries' sum, the profile, the sum of the video memory it drew into, the runs of tiles it queued and the 80 sprite
   table entries; then colour RAM after the palette ticks, the sum of all video memory and of the scene's frames. */
#include <stdio.h>
#include <string.h>
#include "modsprite.h"
@SHARED@

extern u8 g_stub_vram[0x10000];
extern u16 g_stub_cram[64];
extern u16 g_stub_dma_calls;

static void probe_start(void)
{
}

static void probe_stop(void)
{
}

static u32 probe_vram_sum(u16 first, u16 count)
{
    const u8 *at = &g_stub_vram[(u32)first * 32u];
    u32 n;
    u16 a = 0, b = 0;

    for (n = 0; n < (u32)count * 16u; n++, at += 2)
    {
        a += (u16)((at[0] << 8) | at[1]);
        b += a;
    }
    return ((u32)b << 16) | a;
}

int main(void)
{
    MS_FrameProfile profile;
    u16 i, k, first, count, runs;

    probe_setup();
    for (i = 0; i < PROBE_COUNT; i++)
    {
        runs = g_stub_dma_calls;
        probe_draw(i);
        runs = (u16)(g_stub_dma_calls - runs);
        ms_get_frame_profile(&profile);
        probe_region(i, &first, &count);
        printf("item %u %u %u %u %u %u %u %u %u %u %lu %u", i, probe_query, profile.render_calls,
               profile.parts_submitted, profile.hw_sprites, profile.sprites_dropped, profile.tiles_uploaded,
               profile.slots_used, profile.draws_left_out, profile.draws_given_way,
               (unsigned long)(count ? probe_vram_sum(first, count) : 0), runs);
        for (k = 0; k < 80; k++)
            printf(" %d,%u,%u,%u,%d", vdpSpriteCache[k].y, vdpSpriteCache[k].size, vdpSpriteCache[k].link,
                   vdpSpriteCache[k].attribut, vdpSpriteCache[k].x);
        printf("\n");
    }
    for (k = 0; k < PROBE_TICKS; k++)
        ms_palette_tick();
    printf("cram");
    for (k = 0; k < 64; k++)
        printf(" %u", g_stub_cram[k]);
    printf("\n");
    probe_all(&first, &count);
    printf("vram %lu\n", (unsigned long)probe_vram_sum(first, count));
    if (MS_SCENE_COUNT)
    {
        MS_ScenePlayer scene;
        u32 sum = 0;

        ms_set_mapping(0);
        ms_set_palette_swap(0);
        ms_scene_player_init(&scene, 0);
        for (k = 0; k < PROBE_PLAY; k++)
        {
            probe_play(&scene);
            sum = probe_table_sum(sum);
        }
        printf("play %lu\n", (unsigned long)sum);
    }
    return 0;
}
"""


def find_blastem(given: Optional[str]) -> Optional[str]:
    candidates = [given, os.environ.get("BLASTEM"), shutil.which("blastem")]
    candidates += sorted(glob.glob("/Applications/blastem*/blastem"), reverse=True)
    candidates += sorted(glob.glob(os.path.expanduser("~/Applications/blastem*/blastem")), reverse=True)
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def have_tools() -> List[str]:
    """What building the ROM and the host build needs and is missing."""
    missing = [tool for tool in ("m68k-elf-gcc", "m68k-elf-nm", "make", "java", "cc") if not shutil.which(tool)]
    if not (SGDK / "makefile.gen").exists():
        missing.append(f"SGDK ({SGDK.relative_to(REPO)})")
    return missing


def word(value: int) -> int:
    """A u16 as the C tables' s16."""
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def probe_items(project: Project, mapping_count: int, bake: export_megadrive.MegaDriveBakeContext,
                cache_tiles: int = 0) -> Tuple[List[Tuple[List[int], str]], List[List[int]]]:
    """(the C table's nine values, a description) of everything the probe draws, and the pictures' draws (seven
    values each)."""
    items: List[Tuple[List[int], str]] = []
    for f, frame in enumerate(project.frames):
        for x, y in POSITIONS:
            items.append(([0, f, 0, 0, 0, x, y, 0, 0], f"frame {frame.name} at {x},{y}"))
    for f, frame in enumerate(project.frames):
        for p, (x, y) in enumerate(POSITIONS):
            flip = 1 + (f + p) % 3  # each frame mirrored each way, each way at another position
            items.append(([4, f, 0, flip, 0, x, y, 0, 0], f"frame {frame.name} mirrored {flip} at {x},{y}"))
    for m, module in enumerate(project.modules):
        flip, (x, y) = m % 4, POSITIONS[m % len(POSITIONS)]
        items.append(([5, m, 0, flip, 0, x, y, 0, 0],
                      f"module {module.name} {'mirrored ' + str(flip) if flip else 'as it is'} at {x},{y}"))
    if project.frames:  # past the 80 sprites: the fast loops' room test fails part way, the careful ones drop sprites
        busiest = max(range(len(project.frames)), key=lambda f: len(project.frames[f].fmodules))
        for f, count, (x, y), dx in ((busiest, 12, (20, 112), 26), (busiest, 16, (-30, 216), 25), (0, 24, (4, 10), 13)):
            items.append(([6, f, 0, count, 0, x, y, dx, 0],
                          f"frame {project.frames[f].name} {count} times from {x},{y}, {dx} apart, the flips in turn"))
    for s, scene in enumerate(project.timeline_scenes):
        for m in range(mapping_count):
            for ticks in SCENE_TICKS:
                items.append(([1, s, m, 0, ticks, SCENE_X, SCENE_Y, 0, 0],
                              f"scene {scene.name}, mapping {m}, tick {ticks}"))
    anim = next((i for i, a in enumerate(project.animations) if len(a.aframes) > 1), None)
    if anim is not None:
        mapping = 1 if mapping_count > 1 else 0
        swap = 1 if project.palette_swaps else 0
        for ticks in (0, 30):
            items.append(([2, anim, mapping, swap, ticks, SCENE_X - 40, SCENE_Y, SCENE_X + 40, SCENE_Y],
                          f"animation {project.animations[anim].name} twice, tick {ticks}"))
        for flip in range(4):  # the second the other way left to right: they face each other
            for ticks in (0, 30):
                items.append(([9, anim, mapping, swap, ticks, SCENE_X - 40, SCENE_Y, SCENE_X + 40, flip],
                              f"animation {project.animations[anim].name} twice facing, the first mirrored {flip}, "
                              f"tick {ticks}"))
    for size in (0, 15):  # 8 x 8 and 32 x 32
        for x, y in ((0, 0), (-3, 5), (310, 220), (-20, 100), (100, -10), (330, 50), (319, 223), (-15, -15)):
            attribute = 0x2000 | 0x8000 * (size == 15) | 0x0800 | 0x123
            items.append(([3, size, word(attribute), 0, 0, x, y, 0, 0],
                          f"a game's {'32x32' if size else '8x8'} sprite at {x},{y}"))
    items.append(([8, 0, 0, 0, 0, 0, 0, 0, 0], "every frame's and module's sprites, bounds and load lists, every "
                  "frame's hitboxes and points mirrored"))
    draws: List[List[int]] = []
    items.append(([7, 0, 0, 0, 0, 0, 0, 0, 0], "picture empty"))  # what drawing nothing takes
    if not project.frames:
        return items, draws
    # Pictures (last: the first give-way level stays on): each drawn as it is, then only the draws that stay (what a
    # game that measured the picture first submits a second time), then with its levels; streamed also through the
    # slot cache, three times (the first ones upload). The first fits.
    frames, modules = len(project.frames), len(project.modules)
    pictures = []
    for seed in range(400):
        picture = crowd_draws(seed, 6 + seed % 18, frames, modules, mapping_count, SCREEN_W, SCREEN_H,
                              own_sprites=(6 + seed % 18) // 4)
        costs = _md_draw_costs(bake, picture, frames, modules)
        gone = given_way(costs, [d[4] for d in picture], SPRITE_LIMIT)
        fits = sum(costs) <= SPRITE_LIMIT
        if (not pictures and fits) or (pictures and not fits and gone):
            pictures.append((picture, gone, sum(costs)))
        if len(pictures) == 6:
            break
    plain, kept, levels, watched, cached = [], [], [], [], []
    for p, (picture, gone, asked) in enumerate(pictures):
        first = len(draws)
        draws += [[KINDS[k], i, m, f, lv, x, y] for k, i, m, f, lv, x, y in picture]
        stays = [d for n, d in enumerate(picture) if n not in gone]
        plain.append(([7, first, len(picture), 0, 0, 0, 0, 0, 0], f"picture {p} ({asked} sprites asked) as it is"))
        first_kept = len(draws)
        draws += [[KINDS[k], i, m, f, lv, x, y] for k, i, m, f, lv, x, y in stays]
        kept.append(([7, first_kept, len(stays), 0, 0, 0, 0, 0, 0], f"picture {p}: the draws that stay"))
        levels.append(([7, first, len(picture), 1, 0, 0, 0, 0, 0],
                       f"picture {p} with its give-way levels ({len(gone)} give way)"))
        watched.append(([7, first, len(picture), 0, 0, 0, 0, 0, 0], f"picture {p} watched (levels on, none set)"))
        if cache_tiles:
            cached += [([7, first, len(picture), 3, 0, 0, 0, 0, 0],
                        f"picture {p} through the slot cache with its levels, time {n}") for n in range(3)]
    bench = []  # copies of a few frames (by their sprites) in one picture each: what one draw takes, to a fraction
    sizes = {}
    for f in range(frames):
        extent = bake.render_frame_extent(bake.render_frames[bake.frame_render_frames[f]])
        sprites, width, height = extent[0], extent[3] - extent[1], extent[4] - extent[2]
        if sprites and width < SCREEN_W - 64 and height < SCREEN_H:
            sizes.setdefault(sprites, (f, extent))
    counts = sorted(sizes)
    for sprites in sorted({counts[round(q * (len(counts) - 1))] for q in (0, 0.25, 0.5, 0.75, 1)} if counts else ()):
        f, (_n, min_x, min_y, max_x, max_y) = sizes[sprites]
        copies = max(1, min(16, SPRITE_LIMIT // sprites))
        x, y = SCREEN_W // 2 - (min_x + max_x) // 2, SCREEN_H // 2 - (min_y + max_y) // 2
        for how, flip, at_x in (("as it is", 0, x), ("mirrored", 1, SCREEN_W // 2 + (min_x + max_x) // 2),
                                ("across the left edge", 0, -(min_x + max_x) // 2)):
            first = len(draws)
            draws += [[0, f, 0, flip, 0, at_x, y] for _k in range(copies)]
            bench.append(([7, first, copies, 0, 0, 0, 0, 0, 0],
                          f"bench: frame {project.frames[f].name} ({sprites} sprites, "
                          f"{bake.render_frames[bake.frame_render_frames[f]].part_count} parts) {how}, {copies} times"))
    hits = []
    if cache_tiles:  # eight draws of one frame: through the default slot (it holds it), and through the cache
        frame = max(range(frames), key=lambda f: _md_draw_costs(bake, [("frame", f, 0, 0, 0, 160, 112)], frames,
                                                                modules)[0])
        first = len(draws)
        draws += [[0, frame, 0, 0, 0, 20 + 36 * k, 112] for k in range(8)]
        for through_cache in (False, True):
            hits += [([7, first, 8, 2 if through_cache else 0, 0, 0, 0, 0, 0],
                      f"hits: frame {project.frames[frame].name} 8 times through "
                      f"{'the slot cache' if through_cache else 'the default slot'}, time {n}") for n in range(3)]
    return items + bench + plain + kept + levels + watched + cached + hits, draws


def export(project: Project, folder: Path, mode: str) -> export_megadrive.MegaDriveBakeContext:
    """The project exported into ``folder`` as export_megadrive.export_project writes it (every mapping), from one bake
    that the host build gets too; returns the bake."""
    mappings = console_bake.resolve_mappings(project, "all")
    bake = export_megadrive.MegaDriveBakeContext(project=project, mappings=mappings, output_dir=folder, mode=mode)
    bake.bake()
    bake._emit_blob(folder / export_megadrive.BLOB_FILE)
    bake._emit_header(folder / export_megadrive.HEADER_FILE)
    bake._emit_data_c(folder / export_megadrive.DATA_C_FILE)
    bake._emit_resources(folder / export_megadrive.RESOURCE_FILE)
    return bake


def probe_source(template: str, items, draws, layout: Dict[str, int], extra: Dict[str, str]) -> str:
    table = ",\n".join("    " + ", ".join(str(v) for v in values) for values, _what in items)
    shared = (PROBE_SHARED.replace("@COUNT@", str(len(items))).replace("@ITEMS@", table)
              .replace("@DRAW_COUNT@", str(len(draws)))
              .replace("@DRAWS@", ",\n".join("    " + ", ".join(str(v) for v in d) for d in draws) or "    0")
              .replace("@TICKS@", str(PALETTE_TICKS)).replace("@PLAY@", str(PLAY_FRAMES))
              .replace("@SCENE_X@", str(SCENE_X)).replace("@SCENE_Y@", str(SCENE_Y)))
    for key, value in layout.items():
        shared = shared.replace(f"@{key}@", str(value))
    text = template.replace("@SHARED@", shared)
    for key, value in extra.items():
        text = text.replace(f"@{key}@", value)
    return text


def build_host(bake, project: Project, folder: Path, source: str) -> Path:
    """The probe compiled for the host with the runtime's C, the tests' SGDK stand-in and the bake's tables."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "genesis.h").write_text(GENESIS_STUB)
    (folder / "genesis_stub.c").write_text(GENESIS_STUB_IMPL)
    bake._emit_header(folder / "modsprite_data.h")
    shutil.copy(DEMO / "inc" / "modsprite.h", folder / "modsprite.h")
    tables = _tables(bake, len(project.frames), mapping_count=len(bake.mappings),
                     animation_count=len(project.animations), module_count=len(project.modules),
                     scene_count=len(project.timeline_scenes))
    (folder / "probe.c").write_text(tables + source.replace('#include "modsprite.h"', "", 1))
    exe = folder / "probe"
    result = subprocess.run(["cc", "-std=c99", "-w", f"-I{folder}", str(DEMO / "src" / "modsprite.c"),
                             str(folder / "probe.c"), str(folder / "genesis_stub.c"), "-o", str(exe)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("the host build failed:\n" + result.stderr[-3000:])
    return exe


def build_rom(work: Path, source: str, c_loops: bool, release: bool = False) -> Path:
    """The demo's runtime, the export in ``work`` and the probe as its main.c, built (make debug, or release with
    link-time optimisation: SGDK's library built once next to ``work``, as the demo's Makefile does); returns the ELF
    file (the ROM next to it)."""
    for name in console_exports.MEGA_DRIVE.runtime + ("src/rom_header.c", "Makefile"):
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DEMO / name, work / name)
    (work / "src" / "main.c").write_text(source)
    build = "release" if release else "debug"
    command = ["make", build, f"SGDK={SGDK}"] + (["EXTRA_FLAGS=-DMS_PUT_FRAME_C"] if c_loops else [])
    if release:
        command.append(f"SGDK_LIB_DIR={work.parent / 'sgdk-lib'}")
    result = subprocess.run(command, cwd=work, capture_output=True, text=True)
    elf, rom = work / "out" / build / "rom.out", work / "out" / build / "rom.bin"
    if result.returncode != 0 or not rom.exists():
        raise RuntimeError("the ROM did not build:\n" + (result.stdout + result.stderr)[-3000:])
    return elf


def symbols(elf: Path) -> Dict[str, int]:
    out = subprocess.run(["m68k-elf-nm", str(elf)], capture_output=True, text=True, check=True).stdout
    found = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            found[parts[2]] = int(parts[0], 16)
    return found


class Gdb:
    """BlastEm's GDB stub (blastem ROM -D) on its standard input and output."""

    def __init__(self, blastem: str, rom: Path, timeout: float):
        env = dict(os.environ)
        self.proc = subprocess.Popen([blastem, str(rom), "-D"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, env=env)
        self.deadline = time.monotonic() + timeout
        self.buffer = b""

    def _read(self, deadline: float) -> bytes:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([self.proc.stdout], [], [], left)[0]:
            raise TimeoutError("BlastEm did not answer in time")
        data = os.read(self.proc.stdout.fileno(), 65536)
        if not data:
            raise RuntimeError("BlastEm ended")
        return data

    def send(self, command: str) -> None:
        data = command.encode()
        self.proc.stdin.write(b"$" + data + b"#" + f"{sum(data) & 0xFF:02x}".encode())
        self.proc.stdin.flush()

    def receive(self, timeout: Optional[float] = None) -> str:
        deadline = self.deadline if timeout is None else min(self.deadline, time.monotonic() + timeout)
        while True:
            start = self.buffer.find(b"$")
            end = self.buffer.find(b"#", start + 1) if start >= 0 else -1
            if start >= 0 and end >= 0 and len(self.buffer) >= end + 3:
                packet = self.buffer[start + 1:end]
                self.buffer = self.buffer[end + 3:]
                self.proc.stdin.write(b"+")
                self.proc.stdin.flush()
                return packet.decode()
            self.buffer += self._read(deadline)

    def ask(self, command: str, timeout: Optional[float] = None) -> str:
        self.send(command)
        return self.receive(timeout)

    def memory(self, address: int, size: int) -> bytes:
        """``size`` bytes from ``address`` (the stub answers a read with at most what its buffer holds)."""
        out = b""
        while len(out) < size:
            reply = self.ask(f"m{address + len(out):x},{size - len(out):x}")
            if not reply or (len(reply) == 3 and reply[0] == "E") or len(reply) % 2:
                raise RuntimeError(f"BlastEm could not read memory at {address + len(out):#x}: {reply[:20]!r}")
            out += bytes.fromhex(reply)
        return out[:size]

    def close(self) -> None:
        try:
            self.send("k")
        except OSError:
            pass
        self.proc.kill()
        self.proc.wait()


# The probe's record in the 68000's memory (big-endian, no padding: every field on an even address).
PROBE = struct.Struct(">6H8HI5HI64H640s")


def parse_probe(data: bytes) -> Dict[str, object]:
    values = PROBE.unpack(data[:PROBE.size])
    names = ("state", "item", "lines", "frames", "query", "sent")
    record: Dict[str, object] = dict(zip(names, values[:6]))
    record["profile"] = list(values[6:14])
    record.update(zip(("vram", "font", "played", "most", "late", "average", "play"), values[14:21]))
    record["cram"] = list(values[21:85])
    record["table"] = values[85]
    return record


def sprite_entries(data: bytes, count: int = 80) -> List[Tuple[int, int, int, int, int]]:
    """(y, size, link, attribute, x) of the sprite table entries in the 68000's memory (big-endian VDPSprite)."""
    out = []
    for n in range(count):
        y, size, link, attr, x = (int.from_bytes(data[8 * n:8 * n + 2], "big", signed=True), data[8 * n + 2],
                                  data[8 * n + 3], int.from_bytes(data[8 * n + 4:8 * n + 6], "big"),
                                  int.from_bytes(data[8 * n + 6:8 * n + 8], "big", signed=True))
        out.append((y, size, link, attr, x))
    return out


def run_rom(blastem: str, elf: Path, item_count: int, has_scene: bool) -> Tuple[List[Dict[str, object]], List[Dict]]:
    """Every item's record from the ROM (BlastEm through its GDB stub), then the palette ticks' and the scene's."""
    found = symbols(elf)
    missing = [n for n in ("probe", "probe_check", "vdpSpriteCache") if n not in found]
    if missing:
        raise RuntimeError(f"symbols not found in {elf.name}: {', '.join(missing)}")
    timeout = 120 + item_count * 0.25 + (PLAY_FRAMES / 30 if has_scene else 0)
    gdb = Gdb(blastem, elf.with_suffix(".bin"), timeout)
    records, ends = [], []
    try:
        try:
            gdb.ask("?", timeout=60)
        except TimeoutError:
            raise RuntimeError("BlastEm did not start its GDB stub within a minute (it needs a window: a desktop "
                               "session)") from None
        if gdb.ask(f"Z0,{found['probe_check']:x},2") != "OK":
            raise RuntimeError("BlastEm took no breakpoint")
        while True:
            stop = gdb.ask("c")
            if not stop.startswith(("S", "T")):
                raise RuntimeError(f"BlastEm stopped with {stop!r}")
            record = parse_probe(gdb.memory(found["probe"], PROBE.size))
            if record["state"] == 1:
                record["sprites"] = gdb.memory(found["vdpSpriteCache"], 640)
                records.append(record)
            else:
                ends.append(record)
                if record["state"] == 3:
                    break
    finally:
        gdb.close()
    return records, ends


def vram_sum(data: bytes) -> int:
    """The probe's sum of video memory over these bytes."""
    a = b = 0
    for n in range(0, len(data) - 1, 2):
        a = (a + (data[n] << 8 | data[n + 1])) & 0xFFFF
        b = (b + a) & 0xFFFF
    return b << 16 | a


def check_project(path: Path, blastem: str, work: Path, mode: str = "parts", c_loops: bool = False,
                  timings: Optional[Path] = None, release: bool = False) -> bool:
    from models import ColourCycle

    project = Project.from_json(str(path))
    name = ((path.name if mode == "parts" else f"{path.name} ({mode})") + (" (C loops)" if c_loops else "")
            + (" (release)" if release else ""))
    if project.palettes and not any(p.cycles for p in project.palettes):  # something for ms_palette_tick to turn
        project.palettes[0].cycles = [ColourCycle(first=3, count=4, frames=3),
                                      ColourCycle(first=9, count=2, frames=5, reverse=True)]
    if work.exists():
        shutil.rmtree(work)
    for folder in ("src", "inc", "res"):
        (work / folder).mkdir(parents=True)
    bake = export(project, work, mode)
    layout = {"SLOTS_FIRST": TILE_USER_INDEX, "SLOTS_TILES": 0, "CACHE_FIRST": 0, "CACHE_TILES": 0}
    if bake.streamed:  # the default slot and the second one, then the slot cache's pool up to the font
        default = max(bake.slot_tiles, bake.scene_slot_tiles)
        layout["SLOTS_TILES"] = default + bake.slot_tiles
        first = TILE_USER_INDEX + layout["SLOTS_TILES"]
        if TILE_FONT_INDEX - first >= 2 * bake.slot_tiles:
            layout["CACHE_FIRST"], layout["CACHE_TILES"] = first, TILE_FONT_INDEX - first
    items, draws = probe_items(project, len(bake.mappings), bake, layout["CACHE_TILES"])
    host = build_host(bake, project, work / "host", probe_source(PROBE_HOST, items, draws, layout, {}))
    host_lines = subprocess.run([str(host)], capture_output=True, text=True, check=True).stdout.splitlines()
    host_items = [line.split(" ") for line in host_lines if line.startswith("item ")]
    host_cram = [int(v) for v in next(line for line in host_lines if line.startswith("cram ")).split()[1:]]
    host_vram = int(next(line for line in host_lines if line.startswith("vram ")).split()[1])
    host_play = next((int(line.split()[1]) for line in host_lines if line.startswith("play ")), None)
    runs = max((int(fields[12]) for fields in host_items), default=0)
    elf = build_rom(work, probe_source(PROBE_ROM, items, draws, layout, {
        "DMA_QUEUE": str(max(80, runs + 8))}), c_loops, release)
    records, ends = run_rom(blastem, elf, len(items), bool(project.timeline_scenes))

    problems = []
    shown = {int(record["item"]): record for record in records}
    for index, (values, what) in enumerate(items):
        fields = host_items[index]
        if index not in shown:
            problems.append(f"{what}: the ROM did not draw it")
            continue
        record = shown[index]
        profile = [int(v) for v in fields[3:11]]
        sprites = [tuple(int(v) for v in item.split(",")) for item in fields[13:]]
        if record["profile"] != profile:
            problems.append(f"{what}: the profile differs from the host build's ({record['profile']} against "
                            f"{profile})")
        rom_sprites = sprite_entries(record["sprites"])
        if rom_sprites != sprites:
            at = next(n for n in range(80) if rom_sprites[n] != sprites[n])
            problems.append(f"{what}: the sprite table differs from the host build's from entry {at} "
                            f"({rom_sprites[at]} against {sprites[at]})")
        if record["table"][:8 * record["sent"]] != record["sprites"][:8 * record["sent"]]:
            problems.append(f"{what}: the VDP's sprite table differs from the sprite table cache")
        if values[0] == 8 and record["query"] != int(fields[2]):
            problems.append(f"{what}: the queries' sum differs from the host build's")
        if record["vram"] != int(fields[11]):
            problems.append(f"{what}: the video memory it drew into differs from the host build's")
    palettes = next((end for end in ends if end["state"] == 2), None)
    played = next((end for end in ends if end["state"] == 3), None)
    if palettes is None:
        problems.append("the ROM did not reach the palette ticks")
    else:
        if layout["CACHE_TILES"] and palettes["font"] < layout["CACHE_FIRST"] + layout["CACHE_TILES"]:
            problems.append(f"the slot cache's pool runs into SGDK's font (tile {palettes['font']})")
        if bake.streamed and palettes["vram"] != host_vram:
            problems.append("the slots' video memory differs from the host build's at the end")
        elif not bake.streamed and palettes["vram"] != vram_sum(bytes(bake.tile_data)):
            problems.append("video memory does not hold the export's sprite tiles")
        for line in range(1, min(4, 1 + len(bake.palette_entries))):  # the lines ms_init loads, from PAL1
            if [c & 0x0EEE for c in palettes["cram"][16 * line + 1:16 * line + 16]] != \
                    [c & 0x0EEE for c in host_cram[16 * line + 1:16 * line + 16]]:
                problems.append(f"palette line {line} differs from the host build's after {PALETTE_TICKS} palette "
                                "ticks")
    if host_play is not None and (played is None or played["play"] != host_play):
        problems.append(f"the frames of {project.timeline_scenes[0].name} played differ from the host build's")
    for problem in problems[:20]:
        print(f"{name}: {problem}")
    if len(problems) > 20:
        print(f"{name}: ... and {len(problems) - 20} more")
    if timings is not None:
        rows = ["item\tlines\tframes\tsprites\tparts\tdraws\twhat"]
        for index, (_values, what) in enumerate(items):
            if index in shown:
                record = shown[index]
                rows.append("\t".join(str(v) for v in (index, record["lines"], record["frames"], record["profile"][2],
                                                       record["profile"][1], record["profile"][0], what)))
        with open(timings, "a", encoding="utf-8") as out:
            out.write(f"# {name}\n" + "\n".join(rows) + "\n")

    summary = f"{name}: {len(shown)} of {len(items)} draws checked"
    if not problems:
        summary += (", every sprite table and profile like the host build's, the VDP's sprite tables like the cache, "
                    f"video memory like the {'host build' if bake.streamed else 'export'}'s, palettes like the host "
                    f"build's after {PALETTE_TICKS} palette ticks"
                    + (f", every frame of {project.timeline_scenes[0].name} played like the host build's"
                       if host_play is not None else ""))
    single = {index: record for index, record in shown.items() if items[index][0][0] not in (6, 7, 8)}
    if single:
        index, record = max(single.items(), key=lambda kv: kv[1]["lines"])
        lines = record["lines"]
        summary += (f"; slowest draw {lines} scanlines ({lines * LINE_US / 1000:.1f} ms of a "
                    f"{LINES_PER_FRAME * LINE_US / 1000:.1f} ms frame): {items[index][1]}")
    if bake.streamed:
        summary += f"; at most {runs} runs of tiles queued for a frame"
    if played is not None and played["played"]:
        summary += (f"; {project.timeline_scenes[0].name} played {played['played']} frames, each drawn in "
                    f"{played['average'] / 10:.1f} scanlines on average, {played['most']} at most"
                    + (f", {played['late']} too late for the vertical blank" if played["late"] else ""))
    print(summary)
    for line in draw_timings(items, shown):
        print(f"{name}: {line}")
    return not problems


def draw_timings(items, shown) -> List[str]:
    """What the draws took: per hardware sprite in the middle of the screen (as it is and mirrored) and across the
    edges, beyond an empty picture, and the pictures (as SNES's check_snes_rom.py reports them)."""
    empty = next((shown[i]["lines"] for i, (_values, what) in enumerate(items)
                  if what == "picture empty" and i in shown), None)
    out = []
    if empty is None:
        return out
    groups = {"as it is in the middle": [], "mirrored in the middle": [], "across the edges": []}
    for index, (values, _what) in enumerate(items):
        if index not in shown or values[0] not in (0, 4):
            continue
        middle = (values[5], values[6]) == POSITIONS[0]
        key = "across the edges" if not middle else "as it is in the middle" if values[0] == 0 else \
            "mirrored in the middle"
        groups[key].append(shown[index])
    parts = []
    for key, records in groups.items():
        sprites = sum(r["profile"][2] for r in records)
        lines = sum(r["lines"] - empty for r in records)
        if sprites:
            parts.append(f"{key} {lines * 488.6 / sprites:.0f} cycles a sprite ({lines} lines for {sprites} sprites"
                         f" in {len(records)} draws)")
    if parts:
        out.append(f"drawing frames beyond an empty picture ({empty} lines): " + "; ".join(parts))
    bench: Dict[str, List[str]] = {}
    for index, (values, what) in enumerate(items):
        match = re.match(r"bench: frame .* \((\d+) sprites, (\d+) parts\) (.*), (\d+) times", what)
        if match and index in shown:
            per_draw = (shown[index]["lines"] - empty) / int(match.group(4))
            bench.setdefault(f"{match.group(1)} sprites in {match.group(2)} parts", []).append(
                f"{per_draw:.2f} {match.group(3)}")
    if bench:
        out.append("lines a draw: " + "; ".join(f"{key}: {', '.join(rows)}" for key, rows in bench.items()))
    by_kind: Dict[str, Dict[int, int]] = {}
    for index, (_values, what) in enumerate(items):
        match = re.match(r"picture (\d+)(.*)", what)
        if match and index in shown:
            kind = ("cached" if "cache" in match.group(2) else "watched" if "watched" in match.group(2)
                    else "levels" if "levels" in match.group(2) else "kept" if "stay" in match.group(2) else "plain")
            by_kind.setdefault(kind, {})[int(match.group(1))] = shown[index]["lines"]
    plain, kept, levels = by_kind.get("plain", {}), by_kind.get("kept", {}), by_kind.get("levels", {})
    watched = by_kind.get("watched", {})
    if plain and 0 in levels:
        over = [p for p in plain if p and p in levels and p in kept]
        text = (f"a picture that fits: {plain[0]} scanlines as it is, {levels[0]} with give-way levels"
                + (f" ({watched[0]} watched, none set)" if 0 in watched else ""))
        if over:
            text += ("; pictures over the limit: {} scanlines with give-way levels, {} drawing them and again without "
                     "what gives way (as it is {}, watched with none set {})").format(
                         "/".join(str(levels[p]) for p in over), "/".join(str(plain[p] + kept[p]) for p in over),
                         "/".join(str(plain[p]) for p in over), "/".join(str(watched.get(p, "-")) for p in over))
        cached = by_kind.get("cached", {})
        if cached:
            text += "; through the slot cache, the third time: " + "/".join(str(cached[p]) for p in sorted(cached))
        hits = {what.split(" through ")[1].split(",")[0]: shown[index]["lines"]
                for index, (_v, what) in enumerate(items) if what.startswith("hits:") and what.endswith("time 2")
                and index in shown}
        if hits:
            text += "; one frame 8 times, held: " + ", ".join(f"{lines} scanlines through {slot}"
                                                             for slot, lines in sorted(hits.items()))
        out.append(text)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Mega Drive runtime in a ROM against its host build "
                                     "(BlastEm).")
    parser.add_argument("projects", nargs="*", help="Project files (default: the Prince of Persia, Sonic and "
                        "Adventurer examples).")
    parser.add_argument("--blastem", help="The BlastEm executable (default: $BLASTEM, PATH, /Applications/blastem*).")
    parser.add_argument("--keep", help="Build in this folder and keep it (default: a temporary folder).")
    parser.add_argument("--mode", choices=export_megadrive.MODES, default="parts",
                        help="How the export stores the sprites (docs/EXPORT_MODES.md); default: parts.")
    parser.add_argument("--c", action="store_true", dest="c_loops",
                        help="Build the runtime with its C draw loops alone (MS_PUT_FRAME_C), to compare times.")
    parser.add_argument("--release", action="store_true",
                        help="Build the ROMs with make release (link-time optimisation) instead of make debug.")
    parser.add_argument("--timings", help="Add each draw's scanlines to this file, tab-separated.")
    args = parser.parse_args()
    blastem = find_blastem(args.blastem)
    missing = have_tools()
    if not blastem or missing:
        print("needs BlastEm (--blastem), " + (", ".join(missing) if missing else "SGDK's toolchain"))
        return 2
    paths = [Path(p).resolve() for p in args.projects] or DEFAULT_PROJECTS
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(args.keep).resolve() if args.keep else Path(tmp)
        for path in paths:
            ok = check_project(path, blastem, base / path.stem, args.mode, args.c_loops,
                               Path(args.timings) if args.timings else None, args.release) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
