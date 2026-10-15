"""The SNES runtime (snes_demo/src/modsprite.c) compiled for the host, and the SNES's sprite table decoded like the PPU
draws it: tests/test_snes_runtime_draw.py and tests/test_snes_runtime_player.py check the runtime against the editor
with it, tools/check_snes_rom.py the ROM against it.

PVSnesLib is replaced by a small stub (the OAM buffer, VRAM and CGRAM as arrays); the harness loads the export's real
data chunks and runs commands from stdin, printing the OAM buffer after each (as hex, 544 bytes):

    frame INDEX MAPPING X Y                  ms_draw_frame with that mapping
    scene INDEX MAPPING TICKS X Y            a scene player ticked TICKS times
    versus ANIM MAPPING SWAP TICKS X Y X2 Y2 an animation drawn as it is, then with ms_draw_anim_player_as
    sprite X Y TILE ATTRIBUTE LARGE          a game's own sprite (ms_add_hw_sprite)
    cycle                                    the sprite palettes in CGRAM (128 words), then one ms_palette_tick
    player ANIM TICKS                        an animation player for TICKS video frames: per frame
                                             "animation:step:finished:event type 0 started:event type 1's value:
                                             hitboxes|points" (no OAM)
    markers FRAME                            a frame's "hitboxes|points" (no OAM)

Hitboxes print as "type,role,x,y,w,h" and points as "type,role,x,y", separated by ";".
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

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

static void dump(const char *what)
{
    unsigned i;
    MS_FrameProfile profile;
    ms_get_frame_profile(&profile);
    printf("%s %u %u ", what, profile.hw_sprites, profile.sprites_dropped);
    for (i = 0; i < sizeof(oamMemory); i++)
        printf("%02x", oamMemory[i]);
    printf("\n");
}

int main(int argc, char **argv)
{
    unsigned i;
    char line[256];
    load_chunks(argv[1]);
    ms_init();
    printf("obsel %u %u\n", g_obj_address, g_obj_size);
    printf("sizes %u %u %u %u %u %u %u %u %u %u %u\n", (unsigned)sizeof(MS_RenderFrame), (unsigned)sizeof(MS_Run),
           (unsigned)sizeof(MS_Sprite), (unsigned)sizeof(MS_Hitbox), (unsigned)sizeof(MS_Point),
           (unsigned)sizeof(MS_AnimStep), (unsigned)sizeof(MS_Animation), (unsigned)sizeof(MS_StepEvent),
           (unsigned)sizeof(MS_Scene), (unsigned)sizeof(MS_PaletteEntry), (unsigned)sizeof(MS_ColourCycle));
    printf("vram ");
    for (i = 0; i < 0x2000; i++)
        printf("%04x", g_vram[i]);
    printf("\ncgram ");
    for (i = 0; i < 256; i++)
        printf("%04x", g_cgram[i]);
    printf("\n");
    while (fgets(line, sizeof(line), stdin))
    {
        unsigned index, mapping, swap, ticks, t;
        int x, y, x2, y2;
        if (sscanf(line, "frame %u %u %d %d", &index, &mapping, &x, &y) == 4)
        {
            ms_set_mapping(mapping);
            ms_begin_frame();
            ms_draw_frame(index, x, y);
            ms_end_frame();
            dump("frame");
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
            ms_draw_anim_player_as(&player, mapping, swap, x2, y2);
            ms_end_frame();
            printf("step %u %u %u ", player.step_index, ms_get_mapping(), ms_get_palette_swap());
            dump("versus");
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


def export(project: Project, folder: Path, mappings: str = "all") -> export_snes.SNESBakeContext:
    """The project exported into ``folder`` (res/, inc/, src/ as in a PVSnesLib project); returns the bake."""
    ctx = export_snes.SNESBakeContext(project, export_snes._resolve_mappings(project, mappings))
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
    """The OAM hex of a harness output line (its last field)."""
    return line.rsplit(" ", 1)[1]


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
