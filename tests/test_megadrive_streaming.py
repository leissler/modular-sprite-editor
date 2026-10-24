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

    def test_load_lists_for_a_game_of_its_own_slots(self):
        """A game that keeps its own slots asks each frame's and module's load list and its tiles (a list drawn by
        several actors is loaded once): ms_frame_load_list, ms_module_load_list and ms_load_list_tiles name the
        export's lists; out of range they name none."""
        body = """
    for (f = 0; f < ms_frame_count; f++)
        printf("frame %u %u %u\\n", f, ms_frame_load_list(f), ms_load_list_tiles(ms_frame_load_list(f)));
    for (m = 0; m < ms_module_count; m++)
        printf("module %u %u %u\\n", m, ms_module_load_list(m), ms_load_list_tiles(ms_module_load_list(m)));
    printf("beyond %u %u %u\\n", ms_frame_load_list(ms_frame_count), ms_module_load_list(ms_module_count),
           ms_load_list_tiles(0xFFFF));"""
        project = Project.from_json(str(PROJECTS[0]))
        for mode in STREAMED:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                ctx = _bake(project, [None], mode, Path(tmp))
                source = _harness(ctx, body, "0", frame_count=len(project.frames), module_count=len(project.modules))
                lines = [line.split() for line in _build_and_run(self, ctx, Path(tmp), source)]
                frames = [line for line in lines if line[0] == "frame"]
                modules = [line for line in lines if line[0] == "module"]
                self.assertEqual(len(frames), len(project.frames))
                self.assertEqual(len(modules), len(project.modules))
                for kind, rows, renders in (("frame", frames, ctx.frame_render_frames),
                                            ("module", modules, ctx.module_render_frames)):
                    for index, listed, tiles in ((int(r[1]), int(r[2]), int(r[3])) for r in rows):
                        expected = ctx.render_frame_loads[renders[index]]
                        self.assertEqual(listed, expected, f"{kind} {index}")
                        self.assertEqual(tiles, ctx.load_lists[expected][2], f"{kind} {index}: tiles")
                beyond = next(line for line in lines if line[0] == "beyond")
                self.assertEqual([int(v) for v in beyond[1:]], [0xFFFF, 0xFFFF, 0])

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


# Prints a frame drawn through the slot cache: the profile, each actor's animation and step, the sprites and, when the
# frame uploaded tiles, video memory from TILE_BASE (`tiles` tiles).
PRINT_CACHED = r"""
extern u8 g_stub_vram[0x10000];
static void print_cached(u16 t, const MS_AnimPlayer *players, u16 count, u16 tiles)
{
    MS_FrameProfile profile;
    u16 i;
    ms_end_frame();
    ms_get_frame_profile(&profile);
    printf("cache %u %u %u %u %u %u", t, profile.hw_sprites, profile.sprites_dropped, profile.tiles_uploaded,
           profile.slots_used, profile.draws_left_out);
    for (i = 0; i < count; i++)
        printf(" a%u", players[i].animation_index * 1000u + players[i].step_index);
    for (i = 0; i < profile.hw_sprites; i++)
        printf(" %d,%d,%u,%u", vdpSpriteCache[i].x - 0x80, vdpSpriteCache[i].y - 0x80, vdpSpriteCache[i].size,
               vdpSpriteCache[i].attribut);
    printf(" |");
    if (profile.tiles_uploaded)
        for (i = 0; i < tiles * 32u; i++)
            printf("%02x", g_stub_vram[TILE_BASE * 32u + i]);
    printf("\n");
}
"""

# Actors for the cache: (animation, mapping, x, y); the last one shows the same as the third, elsewhere.
CACHE_ACTORS = [("C34 Attack", 0, 60, 150), ("C46 quick attack", 1, 140, 150), ("C21 multi stab throw enemy", 1, 220, 150),
                ("C34 Attack", 1, 290, 100), ("C21 multi stab throw enemy", 1, 100, 60)]


def _cache_harness(ctx, actors, frames: int, pool: int, clear_at: int, counts) -> str:
    table = ", ".join(f"{a}, {m}, {x}, {y}" for a, m, x, y in actors)
    return (_tables(ctx, **counts) + f"\n#define TILE_BASE {TILE_BASE}u\n" + PRINT_CACHED + f"""
static const s16 g_actors[] = {{ {table} }};

int main(void)
{{
    static MS_AnimPlayer players[{len(actors)}];
    static MS_Slot own;
    u16 k, t;
    ms_init();
    ms_slot_init(&own, TILE_BASE + {pool});
    ms_slot_cache_init(TILE_BASE, {pool});
    for (k = 0; k < {len(actors)}; k++)
        ms_anim_player_init(&players[k], (u16)g_actors[4 * k]);
    for (t = 0; t < {frames}; t++)
    {{
        if (t == {clear_at})
            ms_slot_cache_clear();  /* the cache's video memory used for something else */
        ms_begin_frame();
        for (k = 0; k < {len(actors)}; k++)
        {{
            ms_set_mapping((u16)g_actors[4 * k + 1]);
            ms_draw_anim_player(&players[k], g_actors[4 * k + 2], g_actors[4 * k + 3]);
        }}
        ms_set_slot(&own);  /* a slot of the game's own in between: the cache stays as it is */
        ms_use_slot_cache();
        print_cached(t, players, {len(actors)}, {pool});
        for (k = 0; k < {len(actors)}; k++)
            ms_anim_player_tick(&players[k]);
    }}
    return 0;
}}
""")


@unittest.skipIf(shutil.which("cc") is None, "no C compiler")
class TestSlotCache(unittest.TestCase):
    def _play(self, mode: str, pool_share: float, frames: int = 240):
        """Five actors (two of them showing the same steps elsewhere) drawn through one slot cache; returns the
        project, the bake, the actors (animation index, mapping, x, y), the printed frames and the pool's tiles."""
        project = Project.from_json(str(PROJECTS[0]))
        mappings = [None, next(m for m in project.mappings if m.name == "Normal")]
        names = {a.name: i for i, a in enumerate(project.animations)}
        actors = [(names[a], m, x, y) for a, m, x, y in CACHE_ACTORS]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = _bake(project, mappings, mode, Path(tmp.name))
        need = max(sum(ctx.load_lists[ctx.render_frame_loads[s[0]]][2] for s in ctx.anim_steps[
            ctx.anim_records[m * len(project.animations) + a].first_step:][:1]) for a, m, _x, _y in actors)
        busiest = sum(max(ctx.load_lists[ctx.render_frame_loads[s[0]]][2] for s in ctx.anim_steps[
            r.first_step:r.first_step + r.step_count]) for r in (ctx.anim_records[m * len(project.animations) + a]
                                                                 for a, m, _x, _y in actors))
        pool = max(need, int(busiest * pool_share))
        counts = dict(frame_count=len(project.frames), mapping_count=len(mappings),
                      animation_count=len(project.animations))
        lines = _build_and_run(self, ctx, Path(tmp.name), _cache_harness(ctx, actors, frames, pool, frames // 2, counts))
        return project, mappings, ctx, actors, lines, pool

    def _check(self, mode: str, pool_share: float):
        from runtime_models import SlotCache
        from ui.frame_render import FrameRenderer, transform

        project, mappings, ctx, actors, lines, pool = self._play(mode, pool_share)
        model = SlotCache(TILE_BASE, pool, 48)
        renderer, vram = FrameRenderer(), b""
        uploads = left_out = 0
        self.assertEqual(len(lines), 240)
        for t, line in enumerate(lines):
            head, _bar, dump = line.partition(" |")
            fields = head.split()
            hw, dropped, uploaded, used, left = (int(v) for v in fields[2:7])
            steps = [int(f[1:]) for f in fields[7:7 + len(actors)]]
            sprites = [tuple(int(v) for v in item.split(",")) for item in fields[7 + len(actors):]]
            if dump:
                vram = bytes.fromhex(dump)
            if t == len(lines) // 2:
                model.clear()
            model.begin()
            drawn = []
            for (anim, mapping, x, y), code in zip(actors, steps):
                self.assertEqual(code // 1000, anim)
                record = ctx.anim_records[mapping * len(project.animations) + anim]
                render = ctx.anim_steps[record.first_step + code % 1000][0]
                listed = ctx.render_frame_loads[render]
                tiles = ctx.load_lists[listed][2]
                if tiles and model.draw(listed, tiles) is not None:
                    drawn.append((anim, mapping, x, y, code % 1000))
            self.assertEqual((uploaded, used, left), (model.uploaded, model.slots_used, model.left_out),
                             f"{mode}, frame {t}: tiles uploaded, slots used, draws left out")
            self.assertEqual((len(sprites), dropped), (hw, 0))
            expected = {}
            for anim, mapping, x, y, step in reversed(drawn):  # the first actor in front
                af = project.animations[anim].aframes[step]
                a, b = transform(af.flip_x, af.flip_y, af.rotation_degrees, af.offset)
                image, hx, hy = renderer.render(project, project.get_frame(af.frame_id), mappings[mapping], a, b)
                expected.update(_palette_pixels(ctx, image, hx, hy, x, y))
            self.assertEqual(_rasterise(sprites, vram), expected, f"{mode}, frame {t}")
            uploads += uploaded > 0
            left_out += left
        self.assertGreater(model.evicted, 0, "slots made room")
        return uploads, left_out

    def test_one_cache_for_every_actor(self):
        """Five actors through one slot cache with room for about two thirds of what they show at their busiest: a step
        is uploaded once and every actor that shows it draws from that slot (two show the same), the slots drawn
        longest ago make room (first fit in tile order), the cache cleared halfway uploads again; a slot of the
        game's own in between leaves it alone. Each frame shows what the editor shows, with what the reference cache
        uploads, uses and leaves out."""
        for mode in STREAMED:
            with self.subTest(mode=mode):
                uploads, left_out = self._check(mode, 0.75)
                self.assertGreater(uploads, 20)
                self.assertLess(uploads, 200, "steps that stay cached upload nothing")

    def test_a_full_cache_leaves_draws_out(self):
        """With room for less than a frame's slots, the draws that find none (everything in the way drawn this frame)
        are left out and the others still show right."""
        _uploads, left_out = self._check("parts_streamed", 0.3)
        self.assertGreater(left_out, 0)

    def test_draws_give_way_through_the_cache(self):
        """Crowds drawn through the slot cache with give-way levels: the draws that stay show what the editor shows,
        their tiles from the slots the cache gave them (a waiting draw keeps its slot until it is drawn)."""
        import compositor
        from PIL import Image
        from runtime_models import crowd_draws, given_way
        from test_megadrive_runtime_draw import CROWD_C, KINDS, _md_draw_costs
        from ui.frame_render import FrameRenderer

        project = Project.from_json(str(PROJECTS[0]))
        mappings = [None, next(m for m in project.mappings if m.name == "Normal")]
        frames, modules = len(project.frames), len(project.modules)
        pool = 1200
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _bake(project, mappings, "parts_streamed", Path(tmp))
            pictures, given = [], []
            for seed in range(200):
                draws = crowd_draws(seed, 6 + seed % 20, frames, modules, len(mappings), 320, 224)
                costs = _md_draw_costs(ctx, draws, frames, modules)
                gone = given_way(costs, [d[4] for d in draws], 80)
                if sum(costs) - sum(costs[n] for n in gone) <= 80:  # what stays fits: no piece drops
                    pictures.append(draws)
                    given.append(gone)
                if len(pictures) == 30:
                    break
            values = ",\n".join("    " + ", ".join(str(v) for v in (KINDS[k], i, m, f, lv, x, y))
                                for draws in pictures for k, i, m, f, lv, x, y in draws)
            starts = ", ".join(f"{sum(len(d) for d in pictures[:p])}, {len(pictures[p])}" for p in range(len(pictures)))
            body = CROWD_C + f"""
extern u8 g_stub_vram[0x10000];
static const s16 g_draws[] = {{
{values}
}};
static const u16 g_pictures[] = {{ {starts} }};

int main(void)
{{
    u16 p, n, i;
    ms_init();
    ms_slot_cache_init({TILE_BASE}, {pool});
    for (p = 0; p < {len(pictures)}; p++)
    {{
        ms_begin_frame();
        for (n = g_pictures[2 * p]; n < g_pictures[2 * p] + g_pictures[2 * p + 1]; n++)
            draw_one(&g_draws[7 * n], 1);
        print_picture("levels", p);
        printf("vram ");
        for (i = 0; i < {pool} * 32u; i++)
            printf("%02x", g_stub_vram[{TILE_BASE} * 32u + i]);
        printf("\\n");
    }}
    return 0;
}}
"""
            lines = _build_and_run(self, ctx, Path(tmp), _tables(
                ctx, frame_count=frames, mapping_count=len(mappings), module_count=modules) + body)
        self.assertGreater(sum(1 for g in given if g), 10)
        renderer = FrameRenderer()
        offsets = ctx.module_flip_offsets()
        for p, draws in enumerate(pictures):
            fields, vram = lines[2 * p].split(), bytes.fromhex(lines[2 * p + 1].split()[1])
            self.assertEqual((int(fields[3]), int(fields[4]), int(fields[5])), (0, len(given[p]), 0))
            sprites = [tuple(int(v) for v in item.split(",")[:4]) for item in fields[6:]]
            expected = {}
            for n in reversed(range(len(draws))):
                kind, index, mapping, flip, _level, x, y = draws[n]
                if n in given[p]:
                    continue
                if kind == "frame":
                    image, hx, hy = renderer.render(project, project.frames[index], mappings[mapping])
                    if flip & 1:
                        image, hx = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT), -hx - image.width
                    if flip & 2:
                        image, hy = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM), -hy - image.height
                else:
                    drawn = compositor.resolve_module(project, project.modules[index].id, mappings[mapping])
                    if drawn is None or drawn.rect[2] <= 0 or drawn.rect[3] <= 0:
                        continue
                    image, hx, hy = renderer.module(project, drawn), -int(drawn.pivot[0]), -int(drawn.pivot[1])
                    if flip & 1:
                        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    if flip & 2:
                        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                entry = 1 if mapping and ctx.palette_entries[1:] else 0  # the guard in the Blue guard's colours
                expected.update(_palette_pixels(ctx, image, int(hx), int(hy), x, y,
                                                palette_at=lambda px, py, e=entry: e))
            self.assertEqual(_rasterise(sprites, vram), expected, f"picture {p}")


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
