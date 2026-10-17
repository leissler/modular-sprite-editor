"""Streamed Mega Drive exports (docs/EXPORT_MODES.md): the runtime uploads each render frame's tiles into the slot it is
drawn through and draws from there exactly what the editor draws, and what the default export draws.

Compiles examples/megadrive/megadrive_demo/src/modsprite.c for the host with a streamed export's tables (the generated
header defines MS_STREAMED), lets it draw, then rasterises the sprite table from the video memory the runtime uploaded
into (the SGDK stand-in keeps it). Skipped without a C compiler.
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

import console_exports  # noqa: E402
import export_modes  # noqa: E402
from models import Project  # noqa: E402
from test_megadrive_runtime_draw import (  # noqa: E402
    POSITIONS, PROJECTS, TILE_BASE, VERSUS, _build_and_run, _palette_pixels, _rasterise, _tables,
)
from test_megadrive_runtime_player import GENESIS_STUB  # noqa: E402

STREAMED = ("parts_streamed", "frames_streamed")

# Prints a drawn frame: its sprites and, when the frame uploaded tiles, video memory from TILE_BASE (`tiles` tiles).
PRINT_FRAME = r"""
extern u8 g_stub_vram[0x10000];
extern u16 g_stub_dma_room;
static void print_frame(const char *what, u32 index, u16 tiles)
{
    MS_FrameProfile profile;
    u16 i;
    ms_get_frame_profile(&profile);
    ms_end_frame();
    printf("%s %u %u %u %u", what, (unsigned)index, profile.hw_sprites, profile.sprites_dropped, profile.tiles_uploaded);
    for (i = 0; i < profile.hw_sprites; i++)
        printf(" %d,%d,%u,%u", vdpSpriteCache[i].x - 0x80, vdpSpriteCache[i].y - 0x80, vdpSpriteCache[i].size,
               vdpSpriteCache[i].attribut);
    printf(" |");
    if (profile.tiles_uploaded)
        for (i = 0; i < tiles * 32u; i++)
            printf("%02x", g_stub_vram[TILE_BASE_BYTES + i]);
    printf("\n");
}
"""


def _bake(project: Project, mappings, mode: str, folder: Path):
    import export_megadrive as sg

    ctx = sg.MegaDriveBakeContext(project, mappings, folder, mode)
    ctx.bake()
    return ctx


def _draws(lines):
    """(name, index, sprites, dropped, uploaded, video memory) of each printed frame; video memory is kept from the
    last frame that uploaded."""
    vram = b""
    for line in lines:
        head, _bar, dump = line.partition(" |")
        fields = head.split()
        if dump:
            vram = bytes.fromhex(dump)
        sprites = [tuple(int(v) for v in item.split(",")) for item in fields[5:]]
        yield fields[0], int(fields[1]), sprites, int(fields[3]), int(fields[4]), vram


def _harness(ctx, body: str, tiles: str, **counts) -> str:
    return (_tables(ctx, **counts) + f"\n#define TILE_BASE_BYTES ({TILE_BASE}u * 32u)\n" + PRINT_FRAME
            + f"\nint main(void)\n{{\n    u16 f, p, t, m;\n    ms_init();\n{body}\n    return 0;\n}}\n").replace(
        "@TILES@", tiles)


@unittest.skipIf(shutil.which("cc") is None, "no C compiler")
class TestStreamedRuntime(unittest.TestCase):
    def test_every_frame_through_the_default_slot(self):
        """Each frame, drawn at the centre and across the edges: the first draw uploads its load list, the others
        nothing, and the screen shows what the editor shows."""
        from ui.frame_render import FrameRenderer

        body = f"""
    for (f = 0; f < ms_frame_count; f++)
        for (p = 0; p < {len(POSITIONS)}; p++)
        {{
            ms_begin_frame();
            ms_draw_frame(f, g_positions[p][0], g_positions[p][1]);
            print_frame("frame", f, @TILES@);
        }}"""
        for project_path in PROJECTS:
            project = Project.from_json(str(project_path))
            for mode in STREAMED:
                with self.subTest(project=project_path.name, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    ctx = _bake(project, [None], mode, Path(tmp))
                    source = _harness(ctx, body, "ms_tiles_used()", frame_count=len(project.frames))
                    lines = _build_and_run(self, ctx, Path(tmp), source)
                    renderer = FrameRenderer()
                    draws = iter(_draws(lines))
                    loaded = None
                    for index, frame in enumerate(project.frames):
                        image, hx, hy = renderer.render(project, frame, None)
                        render = ctx.frame_render_frames[index]
                        listed = ctx.render_frame_loads[render]
                        for p, (draw_x, draw_y) in enumerate(POSITIONS):
                            _what, _f, sprites, dropped, uploaded, vram = next(draws)
                            self.assertEqual(dropped, 0)
                            expected = ctx.load_lists[listed][2] if (p == 0 and listed != loaded) else 0
                            self.assertEqual(uploaded, expected, f"{frame.name}: tiles uploaded at {draw_x},{draw_y}")
                            self.assertEqual(_rasterise(sprites, vram), _palette_pixels(ctx, image, hx, hy, draw_x, draw_y),
                                             f"{project_path.name} ({mode}): '{frame.name}' at {draw_x},{draw_y}")
                        loaded = listed

    def test_two_players_in_two_slots(self):
        """The hero through the default slot, the guard (his own mapping) through a slot of his own: both upload
        when their step's tiles change and show what the editor shows."""
        from ui.frame_render import FrameRenderer, transform

        project = Project.from_json(str(PROJECTS[0]))
        guard_mapping = next(m for m in project.mappings if m.name == "Normal")
        names = ["C34 Attack", "C46 quick attack", "C21 multi stab throw enemy"]  # offsets, step flips
        animations = [next(i for i, a in enumerate(project.animations) if a.name == n) for n in names]
        body = f"""
    static MS_Slot guard_slot;
    static const u16 anims[] = {{ {", ".join(str(a) for a in animations)} }};
    ms_slot_init(&guard_slot, ms_tile_base() + ms_tiles_used());
    for (m = 0; m < {len(animations)}; m++)
    {{
        MS_AnimPlayer hero, guard;
        ms_anim_player_init(&hero, anims[m]);
        ms_anim_player_init(&guard, anims[m]);
        for (t = 0; t < 150; t++)
        {{
            ms_begin_frame();
            ms_draw_anim_player(&hero, {VERSUS[0][0]}, {VERSUS[0][1]});
            ms_set_slot(&guard_slot);
            ms_draw_anim_player_mapped(&guard, 1, {VERSUS[1][0]}, {VERSUS[1][1]});
            ms_set_slot(NULL);
            print_frame("versus", anims[m] * 1000u + hero.step_index, @TILES@);
            ms_anim_player_tick(&hero);
            ms_anim_player_tick(&guard);
        }}
    }}"""
        for mode in STREAMED:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                ctx = _bake(project, [None, guard_mapping], mode, Path(tmp))
                source = _harness(ctx, body, "(u16)(ms_tiles_used() + ms_slot_tiles())", frame_count=len(project.frames),
                                  mapping_count=2, animation_count=len(project.animations))
                lines = _build_and_run(self, ctx, Path(tmp), source)
                renderer, shown, uploads = FrameRenderer(), set(), 0
                for _what, code, sprites, dropped, uploaded, vram in _draws(lines):
                    anim, step = project.animations[code // 1000], code % 1000
                    self.assertEqual(dropped, 0)
                    uploads += uploaded > 0
                    af = anim.aframes[step]
                    a, b = transform(af.flip_x, af.flip_y, af.rotation_degrees, af.offset)
                    expected = {}
                    for mapping, (draw_x, draw_y) in reversed(list(zip((None, guard_mapping), VERSUS))):
                        image, hx, hy = renderer.render(project, project.get_frame(af.frame_id), mapping, a, b)
                        expected.update(_palette_pixels(ctx, image, hx, hy, draw_x, draw_y))
                    self.assertEqual(_rasterise(sprites, vram), expected, f"{mode}: '{anim.name}' step {step}")
                    shown.add((anim.name, step))
                self.assertEqual(len(shown), sum(len(project.animations[i].aframes) for i in animations))
                self.assertLess(uploads, len(lines), "a step that shows the same tiles uploads nothing")

    def test_a_full_dma_queue_is_queued_again(self):
        """SGDK's DMA queue refuses transfers once it is full: the slot then holds nothing, so the next draw queues the
        frame's tiles again and shows it right."""
        from ui.frame_render import FrameRenderer

        project = Project.from_json(str(PROJECTS[0]))
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _bake(project, [None], "parts_streamed", Path(tmp))

            def later_runs_show(render: int) -> bool:  # more than one run, and the others hold more than blank tiles
                first, count, _tiles = ctx.load_lists[ctx.render_frame_loads[render]]
                return any(bytes(ctx.tile_data[tile * 32:(tile + n) * 32]).strip(b"\0")
                           for tile, n in ctx.load_entries[first + 1:first + count])

            index = next(i for i, render in enumerate(ctx.frame_render_frames) if later_runs_show(render))
            body = f"""
    for (t = 0; t < 3; t++)
    {{
        g_stub_dma_room = t ? 0xFFFFu : 1u;  /* the first draw finds room for one run */
        ms_begin_frame();
        ms_draw_frame({index}, {POSITIONS[0][0]}, {POSITIONS[0][1]});
        print_frame("frame", {index}, @TILES@);
    }}"""
            lines = _build_and_run(self, ctx, Path(tmp), _harness(ctx, body, "ms_tiles_used()",
                                                                   frame_count=len(project.frames)))
        draws = list(_draws(lines))
        tiles = ctx.load_lists[ctx.render_frame_loads[ctx.frame_render_frames[index]]][2]
        self.assertEqual([uploaded for _what, _f, _sprites, _dropped, uploaded, _vram in draws], [tiles, tiles, 0],
                         "refused in part, queued again, then held")
        image, hx, hy = FrameRenderer().render(project, project.frames[index], None)
        expected = _palette_pixels(ctx, image, hx, hy, *POSITIONS[0])
        self.assertNotEqual(_rasterise(draws[0][2], draws[0][5]), expected, "only the first run arrived")
        for _what, _f, sprites, _dropped, _uploaded, vram in draws[1:]:
            self.assertEqual(_rasterise(sprites, vram), expected)

    def test_modules_and_scenes_like_the_default_export(self):
        """Every module and the Swordfight in every mapping (a scene streams through one slot, a sample's tiles at a
        time): the streamed export shows the same pixels as the export that keeps every tile in video memory."""
        project = Project.from_json(str(PROJECTS[0]))
        mappings = [None] + list(project.mappings)
        body = f"""
    MS_ScenePlayer scene;
    for (m = 0; m < ms_mapping_count; m++)
    {{
        ms_set_mapping(m);
        for (f = 0; f < ms_module_count; f++)
        {{
            ms_begin_frame();
            ms_draw_module(f, 160, 112);
            print_frame("module", f, @TILES@);
        }}
        ms_scene_player_init(&scene, 0);
        for (t = 0; t < 400; t++)
        {{
            ms_begin_frame();
            ms_draw_scene_player(&scene, 160, 168);
            print_frame("scene", t, @TILES@);
            ms_scene_player_tick(&scene);
        }}
    }}"""
        counts = dict(frame_count=len(project.frames), mapping_count=len(mappings), module_count=len(project.modules),
                      scene_count=len(project.timeline_scenes))
        with tempfile.TemporaryDirectory() as tmp:
            resident = _bake(project, mappings, "parts", Path(tmp) / "resident")
            expected = [(what, index, _rasterise(sprites, bytes(resident.tile_data)))
                        for what, index, sprites, *_rest in _draws(_build_and_run(
                            self, resident, Path(tmp), _harness(resident, body, "0", **counts)))]
        self.assertGreater(len(expected), 400 * len(mappings))
        for mode in STREAMED:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                ctx = _bake(project, mappings, mode, Path(tmp))
                lines = _build_and_run(self, ctx, Path(tmp), _harness(ctx, body, "ms_tiles_used()", **counts))
                got = [(what, index, _rasterise(sprites, vram)) for what, index, sprites, _d, _u, vram in _draws(lines)]
                self.assertEqual(len(got), len(expected))
                for want, have in zip(expected, got):
                    self.assertEqual(have, want, f"{mode}: {want[0]} {want[1]}")

    def test_the_streamed_blob_parses(self):
        """The generated parser reads a streamed blob's header (version 6): the counts and where its load lists are."""
        import export_megadrive as sg

        project = Project.from_json(str(PROJECTS[2]))
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = sg.export_project(project, tmp_path / "game", mode="parts_streamed")
            blob = (tmp_path / "game" / sg.BLOB_FILE).read_bytes()
            self.assertEqual(struct.unpack(">H", blob[4:6])[0], sg.STREAMED_BLOB_VERSION)
            (tmp_path / "genesis.h").write_text(GENESIS_STUB)
            (tmp_path / "resources.h").write_text(f"extern const unsigned char MS_BLOB[{len(blob)}];\n")
            (tmp_path / "blob.c").write_text("const unsigned char MS_BLOB[] __attribute__((aligned(4))) = {"
                                             + ", ".join(str(b) for b in blob) + "};\n")
            (tmp_path / "main.c").write_text(r"""
#include <stdio.h>
#include "modsprite_data.h"
extern const unsigned char MS_BLOB[];
int main(void)
{
    ms_data_init();
    printf("%u %u %u %u %u %u %u %ld %ld %ld\n", ms_data_is_ready(), (unsigned)sizeof(MS_LoadList),
           (unsigned)sizeof(MS_LoadEntry), ms_tile_count, ms_render_frame_count, ms_load_list_count,
           (unsigned)ms_load_entry_count, (long)((const unsigned char *)ms_render_frame_loads - MS_BLOB),
           (long)((const unsigned char *)ms_load_lists - MS_BLOB), (long)((const unsigned char *)ms_load_entries - MS_BLOB));
    return 0;
}
""")
            shutil.copy(tmp_path / "game" / sg.HEADER_FILE, tmp_path / "modsprite_data.h")
            exe = tmp_path / "parse"
            build = subprocess.run(["cc", "-std=c99", "-w", f"-I{tmp_path}", str(tmp_path / "game" / sg.DATA_C_FILE),
                                    str(tmp_path / "blob.c"), str(tmp_path / "main.c"), "-o", str(exe)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr[-2000:])
            ready, list_size, entry_size, tiles, frames, lists, entries, *offsets = (int(v) for v in subprocess.run(
                [str(exe)], capture_output=True, text=True, check=True).stdout.split())
            ctx = _bake(project, [None], "parts_streamed", tmp_path / "again")
        self.assertEqual((list_size, entry_size), (struct.calcsize(">IHH"), struct.calcsize(">HH")),
                         "MS_LoadList and MS_LoadEntry as the blob packs them")
        self.assertEqual((ready, tiles, frames, lists, entries),
                         (1, len(ctx.tile_data) // 32, len(ctx.render_frames), len(ctx.load_lists), len(ctx.load_entries)))
        header = sg.BLOB_HEADER_SIZE
        self.assertEqual(offsets, list(struct.unpack(">III", blob[header + 6:header + 18])))
        loads = offsets[0]
        self.assertEqual(list(struct.unpack(f">{len(ctx.render_frames)}H", blob[loads:loads + 2 * len(ctx.render_frames)])),
                         ctx.render_frame_loads)
        self.assertEqual(result.summary["slot_tiles"], ctx.slot_tiles)


class TestStreamedExport(unittest.TestCase):
    def test_the_default_export_is_resident(self):
        import export_megadrive as sg

        project = Project.from_json(str(PROJECTS[2]))
        with tempfile.TemporaryDirectory() as tmp:
            result = sg.export_project(project, Path(tmp) / "game")
            header = (Path(tmp) / "game" / sg.HEADER_FILE).read_text()
            blob = (Path(tmp) / "game" / sg.BLOB_FILE).read_bytes()
        self.assertNotIn("MS_STREAMED", header)
        self.assertEqual(struct.unpack(">H", blob[4:6])[0], sg.BLOB_VERSION)
        self.assertNotIn("slot_tiles", result.summary)
        self.assertIn("tiles", [issue.code for issue in result.issues])

    def test_a_streamed_export_reports_its_slots(self):
        import export_megadrive as sg

        project = Project.from_json(str(PROJECTS[0]))
        with tempfile.TemporaryDirectory() as tmp:
            result = sg.export_project(project, Path(tmp) / "game", mode="parts_streamed")
            header = (Path(tmp) / "game" / sg.HEADER_FILE).read_text()
        self.assertIn("#define MS_STREAMED 1", header)
        self.assertIn(f"#define MS_SLOT_TILES {result.summary['slot_tiles']}u", header)
        codes = [issue.code for issue in result.issues]
        self.assertIn("slots", codes)
        self.assertNotIn("tiles", codes, "no resident tile count")
        self.assertIn("Streamed", sg.report_line(result.summary))

    def test_the_slots_are_what_export_modes_measures(self):
        project = Project.from_json(str(PROJECTS[0]))
        mappings = [None] + list(project.mappings)
        for mode in STREAMED:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                ctx = _bake(project, mappings, mode, Path(tmp))
                costs = export_modes.measure_mode(project, console_exports.MEGA_DRIVE, export_modes.mode_by_key(mode))
                self.assertEqual((ctx.slot_tiles, ctx.scene_slot_tiles), (costs.video_tiles, costs.scene_video_tiles))
                self.assertEqual(len(ctx.tile_data) // 32, costs.cartridge_tiles)
                for first, count, tiles in ctx.load_lists:
                    self.assertEqual(sum(n for _tile, n in ctx.load_entries[first:first + count]), tiles)

    def test_the_command_line_takes_a_mode(self):
        import export_megadrive as sg

        self.assertEqual(console_exports.MEGA_DRIVE.modes, sg.MODES)
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run([sys.executable, str(REPO_ROOT / "examples" / "megadrive" / "tools" / "export_megadrive.py"),
                                  "--project-json", str(PROJECTS[2]), "--output-dir", str(Path(tmp) / "game"),
                                  "--mode", "frames_streamed"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr[-1000:])
            self.assertIn("mode: frames_streamed", run.stdout)


if __name__ == "__main__":
    unittest.main()
