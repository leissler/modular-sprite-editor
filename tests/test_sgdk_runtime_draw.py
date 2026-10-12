"""The Mega Drive runtime must draw every frame exactly like the editor.

Bakes the testbed projects with the SGDK exporter, compiles examples/sgdk/sgdk_demo/src/modsprite.c for the
host (with the exporter's tables as C arrays), lets the runtime draw each frame into the sprite table (in the
middle of the screen, where it copies whole frames, and across the edges, where it culls sprite by sprite),
then rasterises that sprite table from the exported tiles like the VDP does (column-major tiles, flips, list
order = priority) and compares the visible pixels with the editor's renderer, quantised to the exported
palette. Also checks that the blob's records have the size the C structs have. Skipped without a C compiler.
"""

import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "examples" / "sgdk" / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import Project  # noqa: E402
from test_runtime_player import GENESIS_STUB, GENESIS_STUB_IMPL  # noqa: E402

SCREEN_W, SCREEN_H = 320, 224
POSITIONS = [(160, 112), (6, 10), (310, 216)]  # centre, across the top-left and the bottom-right edges
VERSUS = [(100, 150), (220, 150)]  # hero, guard
TILE_BASE = 16  # TILE_USER_INDEX in the stub
PROJECTS = [REPO_ROOT / "examples" / "sgdk" / "PoP_WW.json", REPO_ROOT / "examples" / "sonic" / "sonic.json"]


def _tables(ctx, frame_count: int, mapping_count: int = 1, animation_count: int = 0) -> str:
    """The exporter's tables as C arrays, with the counts and accessors modsprite.c expects."""
    def rows(items, fmt):
        return ",\n".join("    {" + fmt(item) + "}" for item in items) or "    {0}"

    variants = rows(ctx.variants, lambda v: f"{v.first_piece}, {v.piece_count}, {v.tile_w}, {v.tile_h}")
    pieces = rows(ctx.pieces, lambda p: f"{p[0]}, {p[1]}, {p[2]}, 0, {p[3]}")
    parts = rows(ctx.packed_parts(), lambda p: f"{p[0]}, {p[1]}, {p[2]}, {p[3]}, {p[4]}")
    frames = rows(ctx.render_frames, lambda r: f"{r.first_part}, {r.part_count}, 0, 0, 0, 0, "
                  + ", ".join(str(v) for v in ctx.render_frame_extent(r)))
    positions = ", ".join(f"{{{x}, {y}}}" for x, y in POSITIONS)
    frame_render = ", ".join(str(i) for i in ctx.frame_render_frames) or "0"
    steps = rows(ctx.anim_steps, lambda s: f"{s[0]}, {s[1]}, {s[2]}, {s[3]}, 0")
    records = rows(ctx.anim_records, lambda r: f"{r.first_step}, {r.step_count}, {r.fps}, {r.playback}, 0, "
                   f"{r.loop_start}, {r.next_animation}, {r.loop_count}")
    events = rows(ctx.step_events, lambda e: f"{e[0]}, {e[1]}")
    return f"""
#include <stdio.h>
#include "modsprite.h"

static const MS_Variant g_variants[] = {{
{variants}
}};
static const MS_Piece g_pieces[] = {{
{pieces}
}};
static const MS_Part g_parts[] = {{
{parts}
}};
static const MS_RenderFrame g_frames[] = {{
{frames}
}};
static const MS_AnimStep g_steps[] = {{
{steps}
}};
static const MS_Animation g_records[] = {{
{records}
}};
static const MS_StepEvent g_events[] = {{
{events}
}};
static const u16 g_frame_render[] = {{ {frame_render} }};
static const s16 g_positions[][2] = {{ {positions} }};
extern u16 g_stub_sprites_sent;

u16 ms_variant_count = {len(ctx.variants)}; u32 ms_part_count = {len(ctx.parts)}; u16 ms_render_frame_count = {len(ctx.render_frames)};
u16 ms_module_count = 0; u16 ms_frame_count = {frame_count}; u16 ms_animation_count = {animation_count};
u16 ms_scene_count = 0; u16 ms_mapping_count = {mapping_count}; u16 ms_anim_step_count = {len(ctx.anim_steps)};
u16 ms_scene_sample_count = 0; u16 ms_animation_record_count = {len(ctx.anim_records) if animation_count else 0}; u16 ms_scene_record_count = 0;
u16 ms_event_type_count = 0; u16 ms_step_event_count = {len(ctx.step_events)};
u16 ms_tile_count = {len(ctx.tile_data) // 32}; u16 ms_piece_count = {len(ctx.pieces)};
u16 ms_hitbox_count = 0; u16 ms_point_count = 0; u16 ms_hitbox_type_count = 0; u16 ms_point_type_count = 0; u16 ms_role_count = 0;
const MS_Variant *ms_variants = g_variants; const MS_Piece *ms_pieces = g_pieces; const u32 *ms_tiles = NULL;
const u16 *ms_palette = NULL; const MS_Hitbox *ms_hitboxes = NULL; const MS_Point *ms_points = NULL;
const MS_Part *ms_parts = g_parts; const MS_RenderFrame *ms_render_frames = g_frames;
const u16 *ms_module_render_frames = NULL; const u16 *ms_frame_render_frames = g_frame_render;
const MS_AnimStep *ms_anim_steps = g_steps; const MS_Animation *ms_animations = g_records;
const u16 *ms_scene_samples = NULL; const MS_Scene *ms_scenes = NULL; const MS_StepEvent *ms_step_events = g_events;
void ms_data_init(void) {{}}
u8 ms_data_is_ready(void) {{ return TRUE; }}
const char *ms_mapping_id(u16 i) {{ return ""; }} const char *ms_mapping_name_data(u16 i) {{ return ""; }}
const char *ms_module_id(u16 i) {{ return ""; }} const char *ms_module_name_data(u16 i) {{ return ""; }}
const char *ms_frame_id(u16 i) {{ return ""; }} const char *ms_frame_name_data(u16 i) {{ return ""; }}
const char *ms_animation_id(u16 i) {{ return ""; }} const char *ms_animation_name_data(u16 i) {{ return ""; }}
const char *ms_scene_id(u16 i) {{ return ""; }} const char *ms_scene_name_data(u16 i) {{ return ""; }}
const char *ms_event_name_data(u16 i) {{ return ""; }}
const char *ms_hitbox_type_name_data(u16 i) {{ return ""; }} const char *ms_point_type_name_data(u16 i) {{ return ""; }}
const char *ms_role_name_data(u16 i) {{ return ""; }}
"""


def _harness(ctx, frame_count: int) -> str:
    return _tables(ctx, frame_count) + f"""
int main(void)
{{
    u16 f, i, p;
    printf("sizes %u %u %u %u %u %u\\n", (unsigned)sizeof(MS_Part), (unsigned)sizeof(MS_RenderFrame),
           (unsigned)sizeof(MS_Variant), (unsigned)sizeof(MS_Piece), (unsigned)sizeof(MS_Hitbox), (unsigned)sizeof(MS_Point));
    ms_init();
    for (f = 0; f < ms_frame_count; f++)
        for (p = 0; p < {len(POSITIONS)}; p++)
        {{
            MS_FrameProfile profile;
            ms_begin_frame();
            ms_draw_frame(f, g_positions[p][0], g_positions[p][1]);
            ms_get_frame_profile(&profile);
            ms_end_frame();
            printf("frame %u %u %u", f, profile.hw_sprites, profile.sprites_dropped);
            for (i = 0; i < profile.hw_sprites; i++)
                printf(" %d,%d,%u,%u,%u", vdpSpriteCache[i].x - 0x80, vdpSpriteCache[i].y - 0x80, vdpSpriteCache[i].size,
                       vdpSpriteCache[i].attribut, vdpSpriteCache[i].link);
            printf("\\n");
        }}
    return 0;
}}
"""


def _rasterise(sprites, tiles: bytes):
    """{{(x, y): palette index}} of the sprite list as the VDP shows it (earlier sprites in front)."""
    out = {}
    for x, y, size, attr in reversed(sprites):
        tw, th = ((size >> 2) & 3) + 1, (size & 3) + 1
        hflip, vflip = bool(attr & 0x0800), bool(attr & 0x1000)
        first = (attr & 0x07FF) - TILE_BASE
        for sy in range(th * 8):
            for sx in range(tw * 8):
                ux = tw * 8 - 1 - sx if hflip else sx
                uy = th * 8 - 1 - sy if vflip else sy
                tile = first + (ux // 8) * th + (uy // 8)
                byte = tiles[tile * 32 + (uy % 8) * 4 + (ux % 8) // 2]
                index = (byte >> 4) if (ux % 2) == 0 else (byte & 0x0F)
                if index and 0 <= x + sx < SCREEN_W and 0 <= y + sy < SCREEN_H:
                    out[(x + sx, y + sy)] = index
    return out


def _versus_harness(ctx, frame_count: int, animation_count: int, animations, ticks: int) -> str:
    """Two players of the same animation in one sprite table: the hero with the active mapping (0), the guard
    with mapping 1 through ms_draw_anim_player_mapped. Prints both steps, the mapping left active and the list."""
    anim_list = ", ".join(str(i) for i in animations)
    return _tables(ctx, frame_count, mapping_count=2, animation_count=animation_count) + f"""
int main(void)
{{
    static const u16 anims[] = {{ {anim_list} }};
    u16 a, t, i;
    ms_init();
    for (a = 0; a < {len(animations)}; a++)
    {{
        MS_AnimPlayer hero, guard;
        ms_anim_player_init(&hero, anims[a]);
        ms_anim_player_init(&guard, anims[a]);
        for (t = 0; t < {ticks}; t++)
        {{
            MS_FrameProfile profile;
            ms_begin_frame();
            ms_draw_anim_player(&hero, {VERSUS[0][0]}, {VERSUS[0][1]});
            ms_draw_anim_player_mapped(&guard, 1, {VERSUS[1][0]}, {VERSUS[1][1]});
            ms_get_frame_profile(&profile);
            ms_end_frame();
            printf("versus %u %u %u %u %u %u", anims[a], hero.step_index, guard.step_index, ms_get_mapping(),
                   profile.hw_sprites, profile.sprites_dropped);
            for (i = 0; i < profile.hw_sprites; i++)
                printf(" %d,%d,%u,%u", vdpSpriteCache[i].x - 0x80, vdpSpriteCache[i].y - 0x80, vdpSpriteCache[i].size,
                       vdpSpriteCache[i].attribut);
            printf("\\n");
            ms_anim_player_tick(&hero);
            ms_anim_player_tick(&guard);
        }}
    }}
    return 0;
}}
"""


def _build_and_run(test: unittest.TestCase, ctx, tmp_path: Path, source: str):
    (tmp_path / "genesis.h").write_text(GENESIS_STUB)
    (tmp_path / "genesis_stub.c").write_text(GENESIS_STUB_IMPL)
    ctx._emit_header(tmp_path / "modsprite_data.h")
    shutil.copy(REPO_ROOT / "examples" / "sgdk" / "sgdk_demo" / "inc" / "modsprite.h", tmp_path / "modsprite.h")
    (tmp_path / "harness.c").write_text(source)
    exe = tmp_path / "harness"
    build = subprocess.run(
        ["cc", "-std=c99", "-w", f"-I{tmp_path}", str(REPO_ROOT / "examples" / "sgdk" / "sgdk_demo" / "src" / "modsprite.c"),
         str(tmp_path / "harness.c"), str(tmp_path / "genesis_stub.c"), "-o", str(exe)],
        capture_output=True, text=True,
    )
    test.assertEqual(build.returncode, 0, build.stderr[-2000:])
    return subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.splitlines()


def _palette_pixels(ctx, image, hx: int, hy: int, draw_x: int, draw_y: int):
    """{(x, y): palette index} of an editor render drawn at (draw_x, draw_y), clipped to the screen."""
    rgba = image.convert("RGBA")
    pixels = {}
    for py in range(rgba.height):
        for px in range(rgba.width):
            r, g, b, a = rgba.getpixel((px, py))
            x, y = hx + px + draw_x, hy + py + draw_y
            if a and 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
                pixels[(x, y)] = ctx._nearest_master_palette_index((r, g, b)) + 1
    return pixels


@unittest.skipIf(shutil.which("cc") is None, "no C compiler")
class TestRuntimeDrawsLikeTheEditor(unittest.TestCase):
    def test_every_frame(self):
        import export_sgdk_example as sg
        from ui.frame_render import FrameRenderer

        for project_path in PROJECTS:
            project = Project.from_json(str(project_path))
            with self.subTest(project=project_path.name), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                ctx = sg.SGDKBakeContext(project, [None], tmp_path)
                ctx.bake()
                lines = _build_and_run(self, ctx, tmp_path, _harness(ctx, len(project.frames)))

                # The blob packs records exactly as large as the C structs.
                sizes = [int(v) for v in lines[0].split()[1:]]
                self.assertEqual(sizes, [struct.calcsize(fmt) for fmt in (">HBBhh", ">IHHIIHHhhhh", ">HHBB", ">hhBBH", ">BBHhhhh", ">BBHhh")])

                renderer = FrameRenderer()
                tiles = bytes(ctx.tile_data)
                checked = 0
                results = iter(lines[1:])
                for frame in project.frames:
                    image, hx, hy = renderer.render(project, frame, None)
                    for draw_x, draw_y in POSITIONS:
                        fields = next(results).split()
                        count, dropped = int(fields[2]), int(fields[3])
                        sprites = [tuple(int(v) for v in item.split(",")[:4]) for item in fields[4:]]
                        self.assertEqual(len(sprites), count)
                        self.assertEqual(dropped, 0, f"{frame.name}: sprites dropped")
                        for x, y, size, _attr in sprites:
                            # Off-screen sprites are culled (one at x = -128 would mask the sprites behind it).
                            w, h = (((size >> 2) & 3) + 1) * 8, ((size & 3) + 1) * 8
                            self.assertTrue(x < SCREEN_W and y < SCREEN_H and x + w > 0 and y + h > 0,
                                            f"{frame.name}: off-screen sprite at {x},{y}")
                        self.assertEqual(_rasterise(sprites, tiles), _palette_pixels(ctx, image, hx, hy, draw_x, draw_y),
                                         f"{project_path.name}: frame '{frame.name}' at {draw_x},{draw_y} differs on the console")
                    checked += 1
                self.assertEqual(checked, len(project.frames))

    def test_two_players_with_their_own_mapping(self):
        """A guard re-skinned from the hero's animations: both in one sprite table, each with its own mapping."""
        import export_sgdk_example as sg
        from ui.frame_render import FrameRenderer, transform

        project = Project.from_json(str(PROJECTS[0]))
        guard_mapping = next(m for m in project.mappings if m.name == "Normal")
        names = ["C34 Attack", "C46 quick attack", "C21 multi stab throw enemy"]  # offsets, step flips
        animations = [next(i for i, a in enumerate(project.animations) if a.name == n) for n in names]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = sg.SGDKBakeContext(project, [None, guard_mapping], tmp_path)
            ctx.bake()
            lines = _build_and_run(self, ctx, tmp_path, _versus_harness(
                ctx, len(project.frames), len(project.animations), animations, ticks=150))

            renderer = FrameRenderer()
            tiles = bytes(ctx.tile_data)
            shown = set()
            for line in lines:
                fields = line.split()
                anim = project.animations[int(fields[1])]
                hero_step, guard_step, active, count, dropped = (int(v) for v in fields[2:7])
                self.assertEqual(active, 0, "ms_draw_anim_player_mapped must leave the active mapping alone")
                self.assertEqual(hero_step, guard_step)
                self.assertEqual(dropped, 0)
                sprites = [tuple(int(v) for v in item.split(",")) for item in fields[7:]]
                self.assertEqual(len(sprites), count)
                af = anim.aframes[hero_step]
                a, b = transform(af.flip_x, af.flip_y, af.rotation_degrees, af.offset)
                expected = {}
                for mapping, (draw_x, draw_y) in reversed(list(zip((None, guard_mapping), VERSUS))):
                    image, hx, hy = renderer.render(project, project.get_frame(af.frame_id), mapping, a, b)
                    expected.update(_palette_pixels(ctx, image, hx, hy, draw_x, draw_y))  # the hero is drawn in front
                self.assertEqual(_rasterise(sprites, tiles), expected,
                                 f"'{anim.name}' step {hero_step}: hero and guard differ on the console")
                shown.add((anim.name, hero_step))
            self.assertEqual(len(shown), sum(len(project.animations[i].aframes) for i in animations))


if __name__ == "__main__":
    unittest.main()
