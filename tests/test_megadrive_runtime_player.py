"""The Mega Drive runtime's animation player must step exactly like the editor's preview.

Compiles examples/megadrive/megadrive_demo/src/modsprite.c for the host (with a tiny stand-in for the SGDK
headers and the exporter's generated data header), plays the same animations in C and in
ui.animation_editor.ops.Player, and compares which step of which animation shows on every tick.
Skipped when no C compiler is available.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "examples" / "megadrive" / "tools"))

from models import AFrame, Animation, EventType, Project, StepEvent  # noqa: E402
from ui.animation_editor import ops  # noqa: E402

TICKS = 48
PLAYBACK_CODE = {"loop": 0, "forward": 1, "ping_pong": 2, "backward": 3}

# (name, playback, holds, loop_start, next case index or None, loop_count, events per step)
CASES = [
    ("loop", "loop", [1, 2, 1], 0, None, 0, {}),
    ("loop_from", "loop", [1, 1, 2, 1], 2, None, 0, {}),
    ("loop_twice_then_next", "loop", [1, 1], 0, 0, 2, {}),
    ("once_then_next", "forward", [2, 1, 1], 0, 1, 0, {1: [(0, 5)]}),
    ("once_stops", "forward", [1, 3], 0, None, 0, {}),
    ("ping_pong", "ping_pong", [1, 1, 1, 1], 0, None, 0, {}),
    ("ping_pong_once_then_next", "ping_pong", [1, 2, 1], 0, 5, 1, {2: [(1, -3)]}),
    ("backward", "backward", [1, 1, 2], 0, None, 0, {}),
    ("backward_twice_then_next", "backward", [2, 1], 0, 4, 2, {0: [(0, 1), (1, 2)]}),
    ("single_step", "loop", [3], 0, None, 0, {}),
]

# The palette tables of a blob without palette entries (the player draws nothing).
NO_PALETTES = """u16 ms_palette_entry_count = 0; u16 ms_base_palette_count = 0; u16 ms_palette_swap_count = 1;
u16 ms_colour_cycle_count = 0; const MS_PaletteEntry *ms_palette_entries = NULL;
const MS_ColourCycle *ms_colour_cycles = NULL; const u8 *ms_swap_entries = NULL;
const char *ms_palette_swap_id(u16 i) { return ""; } const char *ms_palette_swap_name_data(u16 i) { return ""; }
const char *ms_palette_entry_name_data(u16 i) { return ""; }
"""

GENESIS_STUB = r"""
#ifndef GENESIS_STUB_H
#define GENESIS_STUB_H
#include <stddef.h>
#include <stdint.h>
typedef uint8_t u8; typedef int8_t s8; typedef uint16_t u16; typedef int16_t s16;
typedef uint32_t u32; typedef int32_t s32; typedef u8 bool;
#define TRUE 1
#define FALSE 0
#define PAL0 0
#define PAL1 1
#define PAL2 2
#define PAL3 3
#define DMA 1
#define DMA_QUEUE 2
#define TILE_USER_INDEX 16
#define TILE_FONT_INDEX 1440
#define TILE_ATTR_FULL(pal, prio, flipV, flipH, index) \
    ((u16)(((flipH) << 11) + ((flipV) << 12) + ((pal) << 13) + ((prio) << 15) + (index)))
#define SPRITE_SIZE(w, h) ((((w) - 1) << 2) | ((h) - 1))
typedef struct { s16 y; u8 size; u8 link; u16 attribut; s16 x; } VDPSprite;
extern VDPSprite vdpSpriteCache[80];
void VDP_updateSprites(u16 num, u16 tm);
void VDP_loadTileData(const u32 *data, u16 index, u16 num, u16 tm);
void PAL_setPalette(u16 num, const u16 *pal, u16 tm);
void PAL_setColors(u16 index, const u16 *pal, u16 count, u16 tm);
u16 VDP_getScreenWidth(void);
u16 VDP_getScreenHeight(void);
#endif
"""

# The SGDK functions the runtime calls, for host builds (sprite table and colour RAM in RAM, VRAM loads ignored).
GENESIS_STUB_IMPL = r"""
#include "genesis.h"
VDPSprite vdpSpriteCache[80];
u16 g_stub_sprites_sent = 0;
void VDP_updateSprites(u16 num, u16 tm) { g_stub_sprites_sent = num; }
void VDP_loadTileData(const u32 *data, u16 index, u16 num, u16 tm) {}
void PAL_setPalette(u16 num, const u16 *pal, u16 tm) {}
u16 g_stub_cram[64];  /* what the runtime put into the colour RAM */
void PAL_setColors(u16 index, const u16 *pal, u16 count, u16 tm)
{
    u16 i;
    for (i = 0; i < count && index + i < 64; i++)
        g_stub_cram[index + i] = pal[i];
}
u16 VDP_getScreenWidth(void) { return 320; }
u16 VDP_getScreenHeight(void) { return 224; }
"""


def _c_harness(project: Project, anims) -> str:
    steps, records, events = [], [], []
    for anim in anims:
        first = len(steps)
        for af in anim.aframes:
            first_event = len(events)
            for e in af.events:
                events.append((int(e.type_id.split("_")[1]), e.value))
            steps.append((len(steps), ops.hold(af), first_event, len(events) - first_event))
        next_index = next((i for i, a in enumerate(anims) if a.id == anim.next_animation_id), 0xFFFF)
        records.append((first, len(anim.aframes), PLAYBACK_CODE[anim.playback_type], anim.loop_start, next_index, anim.loop_count))
    step_rows = ",\n".join(f"    {{{s[0]}, {s[1]}, {s[2]}, {s[3]}, 0}}" for s in steps)
    record_rows = ",\n".join(f"    {{{r[0]}, {r[1]}, 10, {r[2]}, 0, {r[3]}, {r[4]}, {r[5]}}}" for r in records)
    event_rows = ",\n".join(f"    {{{t}, {v}}}" for t, v in events) or "    {0, 0}"
    return f"""
#include <stdio.h>
#include "modsprite.h"

static const MS_AnimStep g_steps[] = {{
{step_rows}
}};
static const MS_Animation g_records[] = {{
{record_rows}
}};
static const MS_StepEvent g_events[] = {{
{event_rows}
}};
u16 ms_variant_count = 0; u32 ms_part_count = 0; u16 ms_render_frame_count = 0;
u16 ms_module_count = 0; u16 ms_frame_count = 0; u16 ms_animation_count = {len(anims)};
u16 ms_scene_count = 0; u16 ms_mapping_count = 1; u16 ms_anim_step_count = {len(steps)};
u16 ms_scene_sample_count = 0; u16 ms_animation_record_count = {len(anims)}; u16 ms_scene_record_count = 0;
u16 ms_event_type_count = 2; u16 ms_step_event_count = {max(1, len(events))};
u16 ms_tile_count = 0; u16 ms_piece_count = 0; u16 ms_hitbox_count = 0; u16 ms_point_count = 0;
u16 ms_hitbox_type_count = 0; u16 ms_point_type_count = 0; u16 ms_role_count = 0;
{NO_PALETTES}
const MS_Variant *ms_variants = NULL; const MS_Piece *ms_pieces = NULL; const u32 *ms_tiles = NULL;
const u16 *ms_palette = NULL; const MS_Hitbox *ms_hitboxes = NULL; const MS_Point *ms_points = NULL;
const MS_Part *ms_parts = NULL; const MS_RenderFrame *ms_render_frames = NULL;
const u16 *ms_module_render_frames = NULL; const u16 *ms_frame_render_frames = NULL;
const MS_AnimStep *ms_anim_steps = g_steps; const MS_Animation *ms_animations = g_records;
const u16 *ms_scene_samples = NULL; const MS_Scene *ms_scenes = NULL; const MS_StepEvent *ms_step_events = g_events;
void ms_data_init(void) {{}}
u8 ms_data_is_ready(void) {{ return TRUE; }}
const char *ms_mapping_id(u16 i) {{ return ""; }} const char *ms_mapping_name_data(u16 i) {{ return ""; }}
const char *ms_module_id(u16 i) {{ return ""; }} const char *ms_module_name_data(u16 i) {{ return ""; }}
const char *ms_frame_id(u16 i) {{ return ""; }} const char *ms_frame_name_data(u16 i) {{ return ""; }}
const char *ms_animation_id(u16 i) {{ return ""; }} const char *ms_animation_name_data(u16 i) {{ return ""; }}
const char *ms_scene_id(u16 i) {{ return ""; }} const char *ms_scene_name_data(u16 i) {{ return ""; }}
const char *ms_event_name_data(u16 i) {{ return i == 0 ? "a" : "b"; }}
const char *ms_hitbox_type_name_data(u16 i) {{ return ""; }} const char *ms_point_type_name_data(u16 i) {{ return ""; }}
const char *ms_role_name_data(u16 i) {{ return ""; }}

int main(void)
{{
    u16 c;
    for (c = 0; c < {len(anims)}; c++)
    {{
        MS_AnimPlayer p;
        int t;
        ms_anim_player_init(&p, c);
        for (t = 0; t < {TICKS}; t++)
        {{
            if (t > 0)
                ms_anim_player_tick(&p);
            printf("%u:%u:%u:%d:%d ", p.animation_index, (unsigned)(p.step_index), p.finished,
                   ms_anim_player_event_started(&p, 0), ms_anim_player_event_value(&p, 1, 0));
        }}
        printf("\\n");
    }}
    return 0;
}}
"""


def _python_trace(project: Project, anims, start: int) -> str:
    """The editor's preview, including the hand-over to follow-up animations (Repeat off)."""
    out = []
    index = start
    player = ops.Player(anims[index], repeat=False)
    player.start()
    for t in range(TICKS):
        if t > 0:
            running = player.advance()
            if not running and anims[index].next_animation_id:
                index = next(i for i, a in enumerate(anims) if a.id == anims[index].next_animation_id)
                player = ops.Player(anims[index], repeat=False)
                player.start()
        started = player.step_started
        af = anims[index].aframes[player.step]
        has_a = any(e.type_id == "evt_0" for e in af.events)
        value_b = next((e.value for e in af.events if e.type_id == "evt_1"), 0)
        out.append(f"{index}:{player.step}:{int(player.finished)}:{int(started and has_a)}:{value_b}")
    return " ".join(out)


@unittest.skipIf(shutil.which("cc") is None, "no C compiler")
class TestRuntimePlayerMatchesEditor(unittest.TestCase):
    def test_runtime_steps_like_the_editor(self):
        import export_megadrive as sg

        project = Project()
        project.event_types = [EventType("evt_0", "a", (255, 0, 0)), EventType("evt_1", "b", (0, 255, 0))]
        anims = []
        for i, (name, playback, holds, loop_start, _next, loop_count, step_events) in enumerate(CASES):
            anim = Animation(id=f"a{i}", name=name, playback_type=playback, loop_count=loop_count, loop_start=loop_start)
            anim.aframes = [
                AFrame(frame_id="f", duration_frames=h, events=[StepEvent(f"evt_{t}", v) for t, v in step_events.get(s, [])])
                for s, h in enumerate(holds)
            ]
            anims.append(anim)
        for anim, case in zip(anims, CASES):
            anim.next_animation_id = anims[case[4]].id if case[4] is not None else None
        project.animations = anims

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "genesis.h").write_text(GENESIS_STUB)
            ctx = sg.MegaDriveBakeContext(project, [None], tmp_path)
            ctx._emit_header(tmp_path / "modsprite_data.h")
            (tmp_path / "harness.c").write_text(_c_harness(project, anims))
            (tmp_path / "genesis_stub.c").write_text(GENESIS_STUB_IMPL)
            exe = tmp_path / "harness"
            demo = REPO_ROOT / "examples" / "megadrive" / "megadrive_demo"
            # modsprite.h includes "modsprite_data.h" from its own folder: keep it next to the fresh header.
            shutil.copy(demo / "inc" / "modsprite.h", tmp_path / "modsprite.h")
            build = subprocess.run(
                ["cc", "-std=c99", "-w", f"-I{tmp_path}",
                 str(demo / "src" / "modsprite.c"), str(tmp_path / "harness.c"), str(tmp_path / "genesis_stub.c"),
                 "-o", str(exe)],
                capture_output=True, text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr[-2000:])
            lines = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.strip().splitlines()

        self.assertEqual(len(lines), len(anims))
        for index, (line, case) in enumerate(zip(lines, CASES)):
            self.assertEqual(line.strip(), _python_trace(project, anims, index), f"case '{case[0]}'")


if __name__ == "__main__":
    unittest.main()
