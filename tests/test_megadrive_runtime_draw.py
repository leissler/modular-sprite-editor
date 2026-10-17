"""The Mega Drive runtime must draw every frame exactly like the editor.

Bakes the testbed projects with the SGDK exporter, compiles examples/megadrive/megadrive_demo/src/modsprite.c for the
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
sys.path.insert(0, str(REPO_ROOT / "examples" / "megadrive" / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import Project  # noqa: E402
from test_megadrive_runtime_player import GENESIS_STUB, GENESIS_STUB_IMPL  # noqa: E402

SCREEN_W, SCREEN_H = 320, 224
POSITIONS = [(160, 112), (6, 10), (310, 216)]  # centre, across the top-left and the bottom-right edges
VERSUS = [(100, 150), (220, 150)]  # hero, guard
TILE_BASE = 16  # TILE_USER_INDEX in the stub
FIRST_LINE = 1  # ms_init() puts the first palette entry on PAL1, the next ones on the lines after it
PROJECTS = [REPO_ROOT / "examples" / "pop" / "PoP_WW.json", REPO_ROOT / "examples" / "sonic" / "sonic.json",
            REPO_ROOT / "examples" / "adventurer" / "adventurer.json"]  # the last two cut parts off the 32 px grid


def _tables(ctx, frame_count: int, mapping_count: int = 1, animation_count: int = 0, module_count: int = 0,
            scene_count: int = 0) -> str:
    """The exporter's tables as C arrays, with the counts and accessors modsprite.c expects (modules and scenes only
    when they are counted)."""
    def rows(items, fmt):
        return ",\n".join("    {" + fmt(item) + "}" for item in items) or "    {0}"

    variants = rows(ctx.variants, lambda v: f"{v.first_piece}, {v.piece_count}, {v.tile_w}, {v.tile_h}")
    pieces = rows(ctx.packed_pieces(), lambda p: f"{p[0]}, {p[1]}, {p[2]}, {p[4]}, {p[3]}")
    parts = rows(ctx.packed_parts(), lambda p: f"{p[0]}, {p[1]}, {p[2]}, {p[3]}, {p[4]}")
    frames = rows(ctx.render_frames, lambda r: f"{r.first_part}, {r.part_count}, 0, 0, 0, 0, "
                  + ", ".join(str(v) for v in ctx.render_frame_extent(r)))
    positions = ", ".join(f"{{{x}, {y}}}" for x, y in POSITIONS)
    frame_render = ", ".join(str(i) for i in ctx.frame_render_frames) or "0"
    module_render = ", ".join(str(i) for i in ctx.module_render_frames) or "0"
    samples = ", ".join(str(i) for i in ctx.scene_samples) or "0"
    scenes = rows(ctx.scene_records, lambda r: f"{r.first_sample}, {r.sample_count}, {r.fps}, {r.duration_ticks}, "
                  f"{r.loop}, 0, 0, 0")
    steps = rows(ctx.anim_steps, lambda s: f"{s[0]}, {s[1]}, {s[2]}, {s[3]}, 0")
    records = rows(ctx.anim_records, lambda r: f"{r.first_step}, {r.step_count}, {r.fps}, {r.playback}, 0, "
                   f"{r.loop_start}, {r.next_animation}, {r.loop_count}")
    events = rows(ctx.step_events, lambda e: f"{e[0]}, {e[1]}")
    words = ", ".join(str(w) for w in ctx.packed_palette_words()) or "0"
    entries = rows(ctx.packed_palette_entries(), lambda e: f"{e[0]}, {e[1]}, {e[2]}, {e[3]}, 0")
    cycles = rows(ctx.packed_colour_cycles(), lambda c: f"{c[0]}, {c[1]}, {c[2]}, {c[3]}, 0")
    swap_entries = ", ".join(str(e) for e in ctx.packed_swap_entries()) or "0"
    streamed, tiles_pointer = "", "NULL"
    if ctx.streamed:  # each render frame's load list, and the tiles to upload from
        streamed = f"""
static const u16 g_loads[] = {{ {", ".join(str(i) for i in ctx.render_frame_loads) or "0"} }};
static const MS_LoadList g_load_lists[] = {{
{rows(ctx.load_lists, lambda l: f"{l[0]}, {l[1]}, {l[2]}")}
}};
static const MS_LoadEntry g_load_entries[] = {{
{rows(ctx.load_entries, lambda e: f"{e[0]}, {e[1]}")}
}};
static const u8 g_tile_bytes[] __attribute__((aligned(4))) = {{ {", ".join(str(b) for b in ctx.tile_data) or "0"} }};
u16 ms_load_list_count = {len(ctx.load_lists)}; u32 ms_load_entry_count = {len(ctx.load_entries)};
const u16 *ms_render_frame_loads = g_loads; const MS_LoadList *ms_load_lists = g_load_lists;
const MS_LoadEntry *ms_load_entries = g_load_entries;
extern u8 g_stub_vram[0x10000];
"""
        tiles_pointer = "(const u32 *)g_tile_bytes"
    return f"""
#include <stdio.h>
#include "modsprite.h"
{streamed}
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
static const u16 g_module_render[] = {{ {module_render} }};
static const u16 g_samples[] = {{ {samples} }};
static const MS_Scene g_scenes[] = {{
{scenes}
}};
static const u16 g_palette[] = {{ {words} }};
static const MS_PaletteEntry g_entries[] = {{
{entries}
}};
static const MS_ColourCycle g_cycles[] = {{
{cycles}
}};
static const u8 g_swap_entries[] = {{ {swap_entries} }};
extern u16 g_stub_cram[64];
static const s16 g_positions[][2] = {{ {positions} }};
extern u16 g_stub_sprites_sent;

u16 ms_variant_count = {len(ctx.variants)}; u32 ms_part_count = {len(ctx.parts)}; u16 ms_render_frame_count = {len(ctx.render_frames)};
u16 ms_module_count = {module_count}; u16 ms_frame_count = {frame_count}; u16 ms_animation_count = {animation_count};
u16 ms_scene_count = {scene_count}; u16 ms_mapping_count = {mapping_count}; u16 ms_anim_step_count = {len(ctx.anim_steps)};
u16 ms_scene_sample_count = {len(ctx.scene_samples) if scene_count else 0}; u16 ms_animation_record_count = {len(ctx.anim_records) if animation_count else 0};
u16 ms_scene_record_count = {len(ctx.scene_records) if scene_count else 0};
u16 ms_event_type_count = 0; u16 ms_step_event_count = {len(ctx.step_events)};
u16 ms_tile_count = {len(ctx.tile_data) // 32}; u16 ms_piece_count = {len(ctx.packed_pieces())};
u16 ms_palette_entry_count = {len(ctx.palette_entries)}; u16 ms_base_palette_count = {len(ctx.palette_ids)};
u16 ms_palette_swap_count = {len(ctx.swaps) + 1}; u16 ms_colour_cycle_count = {len(ctx.packed_colour_cycles())};
const MS_PaletteEntry *ms_palette_entries = g_entries; const MS_ColourCycle *ms_colour_cycles = g_cycles;
const u8 *ms_swap_entries = g_swap_entries;
u16 ms_hitbox_count = 0; u16 ms_point_count = 0; u16 ms_hitbox_type_count = 0; u16 ms_point_type_count = 0; u16 ms_role_count = 0;
const MS_Variant *ms_variants = g_variants; const MS_Piece *ms_pieces = g_pieces; const u32 *ms_tiles = {tiles_pointer};
const u16 *ms_palette = g_palette; const MS_Hitbox *ms_hitboxes = NULL; const MS_Point *ms_points = NULL;
const MS_Part *ms_parts = g_parts; const MS_RenderFrame *ms_render_frames = g_frames;
const u16 *ms_module_render_frames = g_module_render; const u16 *ms_frame_render_frames = g_frame_render;
const MS_AnimStep *ms_anim_steps = g_steps; const MS_Animation *ms_animations = g_records;
const u16 *ms_scene_samples = g_samples; const MS_Scene *ms_scenes = g_scenes; const MS_StepEvent *ms_step_events = g_events;
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
const char *ms_palette_swap_id(u16 i) {{ return ""; }} const char *ms_palette_swap_name_data(u16 i) {{ return ""; }}
const char *ms_palette_entry_name_data(u16 i) {{ return ""; }}
"""


def _harness(ctx, frame_count: int) -> str:
    return _tables(ctx, frame_count) + f"""
int main(void)
{{
    u16 f, i, p;
    printf("sizes %u %u %u %u %u %u %u %u\\n", (unsigned)sizeof(MS_Part), (unsigned)sizeof(MS_RenderFrame),
           (unsigned)sizeof(MS_Variant), (unsigned)sizeof(MS_Piece), (unsigned)sizeof(MS_Hitbox), (unsigned)sizeof(MS_Point),
           (unsigned)sizeof(MS_PaletteEntry), (unsigned)sizeof(MS_ColourCycle));
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


def _mirrored_harness(ctx, frame_count: int) -> str:
    """Each frame mirrored three ways (left-right, top-bottom, both) through ms_draw_frame_flipped, in the middle of
    the screen and across the top-left edge."""
    return _tables(ctx, frame_count) + f"""
int main(void)
{{
    u16 f, i, p, flip;
    ms_init();
    for (f = 0; f < ms_frame_count; f++)
        for (flip = 1; flip <= 3; flip++)
            for (p = 0; p < 2; p++)
            {{
                MS_FrameProfile profile;
                ms_begin_frame();
                ms_draw_frame_flipped(f, g_positions[p][0], g_positions[p][1], (u8)flip);
                ms_get_frame_profile(&profile);
                ms_end_frame();
                printf("mirrored %u %u %u %u", f, flip, profile.hw_sprites, profile.sprites_dropped);
                for (i = 0; i < profile.hw_sprites; i++)
                    printf(" %d,%d,%u,%u", vdpSpriteCache[i].x - 0x80, vdpSpriteCache[i].y - 0x80, vdpSpriteCache[i].size,
                           vdpSpriteCache[i].attribut);
                printf("\\n");
            }}
    return 0;
}}
"""


def _rasterise(sprites, tiles: bytes, base: int = TILE_BASE):
    """{{(x, y): (palette entry, colour index)}} of the sprite list as the VDP shows it (earlier sprites in front); the
    runtime loads the palette entries into consecutive lines from FIRST_LINE. ``tiles`` start at tile ``base``."""
    out = {}
    for x, y, size, attr in reversed(sprites):
        tw, th = ((size >> 2) & 3) + 1, (size & 3) + 1
        hflip, vflip = bool(attr & 0x0800), bool(attr & 0x1000)
        palette = ((attr >> 13) & 3) - FIRST_LINE
        first = (attr & 0x07FF) - base
        for sy in range(th * 8):
            for sx in range(tw * 8):
                ux = tw * 8 - 1 - sx if hflip else sx
                uy = th * 8 - 1 - sy if vflip else sy
                tile = first + (ux // 8) * th + (uy // 8)
                byte = tiles[tile * 32 + (uy % 8) * 4 + (ux % 8) // 2]
                index = (byte >> 4) if (ux % 2) == 0 else (byte & 0x0F)
                if index and 0 <= x + sx < SCREEN_W and 0 <= y + sy < SCREEN_H:
                    out[(x + sx, y + sy)] = (palette, index)
    return out


def _versus_harness(ctx, frame_count: int, animation_count: int, animations, ticks: int,
                    guard_draw: str = "ms_draw_anim_player_mapped(&guard, 1, {x}, {y})") -> str:
    """Two players of the same animation in one sprite table: the hero with the active mapping (0), the guard
    with mapping 1 through ms_draw_anim_player_mapped (or ``guard_draw``). Prints both steps, the mapping (plus the
    palette swap) left active and the list."""
    anim_list = ", ".join(str(i) for i in animations)
    guard_call = guard_draw.format(x=VERSUS[1][0], y=VERSUS[1][1])
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
            {guard_call};
            ms_get_frame_profile(&profile);
            ms_end_frame();
            printf("versus %u %u %u %u %u %u", anims[a], hero.step_index, guard.step_index,
                   ms_get_mapping() + ms_get_palette_swap(), profile.hw_sprites, profile.sprites_dropped);
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
    shutil.copy(REPO_ROOT / "examples" / "megadrive" / "megadrive_demo" / "inc" / "modsprite.h", tmp_path / "modsprite.h")
    (tmp_path / "harness.c").write_text(source)
    exe = tmp_path / "harness"
    build = subprocess.run(
        ["cc", "-std=c99", "-w", f"-I{tmp_path}", str(REPO_ROOT / "examples" / "megadrive" / "megadrive_demo" / "src" / "modsprite.c"),
         str(tmp_path / "harness.c"), str(tmp_path / "genesis_stub.c"), "-o", str(exe)],
        capture_output=True, text=True,
    )
    test.assertEqual(build.returncode, 0, build.stderr[-2000:])
    return subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.splitlines()


def _palette_pixels(ctx, image, hx: int, hy: int, draw_x: int, draw_y: int, palette_at=lambda x, y: 0):
    """{(x, y): (palette entry, colour index)} of an editor render drawn at (draw_x, draw_y), clipped to the screen;
    ``palette_at(x, y)`` (render pixel) says which palette entry the image there is drawn from. The index is the slot
    of the entry's palette (a swap's entry has the same slots as its palette)."""
    rgba = image.convert("RGBA")
    pixels = {}
    for py in range(rgba.height):
        for px in range(rgba.width):
            r, g, b, a = rgba.getpixel((px, py))
            x, y = hx + px + draw_x, hy + py + draw_y
            if a and 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
                entry = palette_at(hx + px, hy + py)
                palette_id = ctx.palette_entries[entry].palette_id
                pixels[(x, y)] = (entry, ctx._nearest_palette_index((r, g, b), palette_id) + 1)
    return pixels


@unittest.skipIf(shutil.which("cc") is None, "no C compiler")
class TestRuntimeDrawsLikeTheEditor(unittest.TestCase):
    def test_every_frame(self):
        import export_megadrive as sg
        from ui.frame_render import FrameRenderer

        for project_path in PROJECTS:
            project = Project.from_json(str(project_path))
            with self.subTest(project=project_path.name), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                ctx = sg.MegaDriveBakeContext(project, [None], tmp_path)
                ctx.bake()
                lines = _build_and_run(self, ctx, tmp_path, _harness(ctx, len(project.frames)))

                # The blob packs records exactly as large as the C structs.
                sizes = [int(v) for v in lines[0].split()[1:]]
                self.assertEqual(sizes, [struct.calcsize(fmt) for fmt in (">HBBhh", ">IHHIIHHhhhh", ">HHBB", ">hhBBH", ">BBHhhhh",
                                                                          ">BBHhh", ">BBHBB", ">BBHBB")])

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

    def test_every_frame_mirrored(self):
        """ms_draw_frame_flipped draws each frame as the editor mirrors it around its origin (pixel x to -x - 1),
        on screen and across the edge."""
        import export_megadrive as sg
        from PIL import Image
        from ui.frame_render import FrameRenderer

        for project_path in PROJECTS[:2]:
            project = Project.from_json(str(project_path))
            with self.subTest(project=project_path.name), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                ctx = sg.MegaDriveBakeContext(project, [None], tmp_path)
                ctx.bake()
                lines = _build_and_run(self, ctx, tmp_path, _mirrored_harness(ctx, len(project.frames)))
                renderer = FrameRenderer()
                tiles = bytes(ctx.tile_data)
                results = iter(lines)
                for frame in project.frames:
                    image, hx, hy = renderer.render(project, frame, None)
                    for flip in (1, 2, 3):
                        mirrored, mx, my = image, hx, hy
                        if flip & 1:
                            mirrored = mirrored.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                            mx = -hx - image.width
                        if flip & 2:
                            mirrored = mirrored.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                            my = -hy - image.height
                        for draw_x, draw_y in POSITIONS[:2]:
                            fields = next(results).split()
                            self.assertEqual(fields[0], "mirrored")
                            self.assertEqual(int(fields[4]), 0, f"{frame.name}: sprites dropped")
                            sprites = [tuple(int(v) for v in item.split(",")[:4]) for item in fields[5:]]
                            self.assertEqual(len(sprites), int(fields[3]))
                            self.assertEqual(_rasterise(sprites, tiles),
                                             _palette_pixels(ctx, mirrored, mx, my, draw_x, draw_y),
                                             f"{project_path.name}: frame '{frame.name}' mirrored {flip} at "
                                             f"{draw_x},{draw_y} differs on the console")

    def test_images_in_two_palettes(self):
        """A frame with a part from an image in each palette: each sprite carries its palette line, the blob holds
        both palettes and the colours come from the right one."""
        import export_megadrive as sg
        from PIL import Image

        import palettes
        from models import FModule, ImageAsset, Module, Palette
        from ui.frame_render import FrameRenderer

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project = Project()
            project.palettes = [Palette("p0", "Warm"), Palette("p1", "Cool")]
            for index, (name, base) in enumerate((("warm.png", (200, 60, 40)), ("cool.png", (40, 80, 210)))):
                image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
                for x in range(8):
                    for y in range(8):
                        image.putpixel((x, y), (base[0] - 20 * (x % 3), base[1] + 10 * (y % 2), base[2], 255))
                image.save(tmp_path / name)
                project.images.append(ImageAsset(f"img{index}", str(tmp_path / name), 8, 8, palette_id=f"p{index}"))
                project.modules.append(Module(f"m{index}", name, f"img{index}", (0, 0, 8, 8), (0, 0)))
            for palette in project.palettes:
                palettes.add_missing_colours(project, palette)
            frame = project.create_frame("both")
            frame.fmodules += [FModule("a", "module", "m0", (0, 0)), FModule("b", "module", "m1", (16, 0))]
            ctx = sg.MegaDriveBakeContext(project, [None], tmp_path / "out")
            ctx.bake()
            self.assertEqual(len(ctx.palette_entries), 2)
            lines = _build_and_run(self, ctx, tmp_path, _harness(ctx, len(project.frames)))
            image, hx, hy = FrameRenderer().render(project, frame, None)
            fields = lines[1].split()
            sprites = [tuple(int(v) for v in item.split(",")[:4]) for item in fields[4:]]
            self.assertEqual(sorted((attr >> 13) & 3 for *_rest, attr in sprites), [FIRST_LINE, FIRST_LINE + 1])
            expected = _palette_pixels(ctx, image, hx, hy, *POSITIONS[0], palette_at=lambda x, y: 1 if x >= 16 else 0)
            self.assertEqual(_rasterise(sprites, bytes(ctx.tile_data)), expected)

    def test_two_players_with_their_own_mapping(self):
        """A guard re-skinned from the hero's animations: both in one sprite table, each with its own mapping."""
        import export_megadrive as sg
        from ui.frame_render import FrameRenderer, transform

        project = Project.from_json(str(PROJECTS[0]))
        guard_mapping = next(m for m in project.mappings if m.name == "Normal")
        names = ["C34 Attack", "C46 quick attack", "C21 multi stab throw enemy"]  # offsets, step flips
        animations = [next(i for i, a in enumerate(project.animations) if a.name == n) for n in names]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = sg.MegaDriveBakeContext(project, [None, guard_mapping], tmp_path)
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

    def test_a_guard_in_other_colours(self):
        """The guard drawn with a mapping and a palette swap: his sprites come from the swap's palette line, the
        hero's from the palette's, the tiles are the same slots, and the active swap stays as it was."""
        import export_megadrive as sg
        from ui.frame_render import FrameRenderer, transform

        project = Project.from_json(str(PROJECTS[0]))
        palette = project.palettes[0]
        swap = next(s for s in project.palette_swaps if s.name == "Blue guard")  # the Swordfight's guard wears it
        guard_mapping = next(m for m in project.mappings if m.name == "Normal")
        names = ["C34 Attack", "C21 multi stab throw enemy"]
        animations = [next(i for i, a in enumerate(project.animations) if a.name == n) for n in names]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = sg.MegaDriveBakeContext(project, [None, guard_mapping], tmp_path)
            ctx.bake()
            self.assertEqual([(e.palette_id, e.swap_id) for e in ctx.palette_entries],
                             [(palette.id, None), (palette.id, swap.id)])
            words = ctx.packed_palette_words()
            self.assertEqual(words[16 + 1], sg.palettes.md_word(swap.palettes[palette.id].colours[0]),
                             "the swap's entry holds its colour")
            self.assertEqual(words[16 + 2], words[2], "slots it leaves alone keep the palette's colour")
            lines = _build_and_run(self, ctx, tmp_path, _versus_harness(
                ctx, len(project.frames), len(project.animations), animations, ticks=60,
                guard_draw="ms_draw_anim_player_as(&guard, 1, 1, {x}, {y})"))
            renderer = FrameRenderer()
            tiles = bytes(ctx.tile_data)
            for line in lines:
                fields = line.split()
                anim = project.animations[int(fields[1])]
                hero_step, _guard_step, active, count, dropped = (int(v) for v in fields[2:7])
                self.assertEqual(active, 0, "the active mapping and swap stay as they were")
                sprites = [tuple(int(v) for v in item.split(",")) for item in fields[7:]]
                af = anim.aframes[hero_step]
                a, b = transform(af.flip_x, af.flip_y, af.rotation_degrees, af.offset)
                expected = {}
                for mapping, entry, (draw_x, draw_y) in reversed(list(zip((None, guard_mapping), (0, 1), VERSUS))):
                    image, hx, hy = renderer.render(project, project.get_frame(af.frame_id), mapping, a, b)
                    expected.update(_palette_pixels(ctx, image, hx, hy, draw_x, draw_y, palette_at=lambda x, y, e=entry: e))
                self.assertEqual(_rasterise(sprites, tiles), expected, f"'{anim.name}' step {hero_step}")

    def test_scene_objects_keep_their_own_swap(self):
        """A scene object with a palette swap of its own has the swap's entry fixed in its pieces; one that inherits
        follows the swap the game draws the scene with."""
        import console_bake
        import export_megadrive as sg
        from PIL import Image

        from models import ImageAsset, Module, PaletteChange, PaletteSwap, TimelineScene

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            Image.new("RGBA", (8, 8), (200, 40, 40, 255)).save(tmp_path / "red.png")
            project = Project()
            project.images.append(ImageAsset("img", str(tmp_path / "red.png"), 8, 8, palette_id=project.default_palette().id))
            project.modules.append(Module("m", "red", "img", (0, 0, 8, 8), (0, 0)))
            palette = project.palettes[0]
            swap = PaletteSwap("s", "Blue", {palette.id: PaletteChange(colours=[(40, 40, 200)])})
            project.palette_swaps.append(swap)
            scene = TimelineScene(id="scene", name="Duel")
            hero = scene.create_object("hero", "module", "m")
            guard = scene.create_object("guard", "module", "m")
            guard.keyframes[0].x = 20
            guard.palette_swap_id = swap.id
            project.timeline_scenes.append(scene)
            ctx = sg.MegaDriveBakeContext(project, [None], tmp_path / "out")
            ctx.bake()
            sample = ctx.render_frames[ctx.scene_samples[ctx.scene_records[0].first_sample]]
            entries = []
            for variant, *_rest in ctx.parts[sample.first_part:sample.first_part + sample.part_count]:
                first, count = ctx._piece_list(variant, False, False)
                entries.append(sorted({piece[4] for piece in ctx.pieces[first:first + count]}))
            self.assertEqual(sorted(entries), [[0], [1 | console_bake.FIXED_ENTRY]], "the hero follows, the guard keeps Blue")
            self.assertEqual(len(ctx.tile_data) // 32, 1, "both draw the same tile: a swap costs no video memory")
            self.assertEqual(hero.palette_swap_id, None)

    def test_colour_cycles_turn_like_the_preview(self):
        """ms_palette_tick() rotates a loaded entry's cycles in the colour RAM the way palettes.rotate shows them."""
        import export_megadrive as sg
        import palettes
        from models import ColourCycle

        project = Project.from_json(str(PROJECTS[0]))
        palette = project.palettes[0]
        palette.cycles = [ColourCycle(first=3, count=4, frames=3), ColourCycle(first=9, count=2, frames=5, reverse=True)]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = sg.MegaDriveBakeContext(project, [None], tmp_path)
            ctx.bake()
            source = _tables(ctx, len(project.frames)) + """
int main(void)
{
    u16 t, i;
    ms_init();
    for (t = 0; t < 40; t++)
    {
        printf("cram");
        for (i = 0; i < 16; i++)
            printf(" %u", g_stub_cram[16 * 1 + i]);
        printf("\\n");
        ms_palette_tick();
    }
    return 0;
}
"""
            lines = _build_and_run(self, ctx, tmp_path, source)
            colours = palettes.colours_of(project, palette)
            for frame, line in enumerate(lines):
                shown = palettes.rotate(colours, palette.cycles, frame)
                expected = [0] + [palettes.md_word(shown[s]) if s < len(shown) else 0 for s in range(15)]
                self.assertEqual([int(v) for v in line.split()[1:]], expected, f"frame {frame}")


if __name__ == "__main__":
    unittest.main()
