"""Streamed SNES exports (docs/EXPORT_MODES.md): the runtime uploads each render frame's tiles into the slot it is drawn
through and draws from there exactly what the editor draws, and what the default export draws.

Exports the testbeds streamed, compiles examples/snes/snes_demo/src/modsprite.c for the host with the export
(examples/snes/tools/snes_host.py: the generated header defines MS_STREAMED; each draw ends with ms_upload_tiles()), lets
it draw, then decodes the OAM buffer like the PPU from the video memory the runtime uploaded into. Skipped without a C
compiler.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "examples" / "snes" / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import console_exports  # noqa: E402
import export_modes  # noqa: E402
import export_snes  # noqa: E402
import snes_host  # noqa: E402
from models import Project  # noqa: E402
from test_snes_runtime_draw import POSITIONS, _editor_pixels  # noqa: E402

PROJECTS = [REPO_ROOT / "examples" / "pop" / "PoP_WW.json", REPO_ROOT / "examples" / "sonic" / "sonic.json",
            REPO_ROOT / "examples" / "adventurer" / "adventurer.json"]
STREAMED = ("parts_streamed", "frames_streamed")


def _export_and_build(project: Project, folder: Path, mode: str, mappings: str = "all"):
    ctx = snes_host.export(project, folder, mappings, mode)
    return ctx, snes_host.build(ctx, folder)


def _draws(lines):
    """Each draw's fields (snes_host.parse_draw), its "vram" kept from the last draw that uploaded."""
    vram = b""
    for line in lines:
        draw = snes_host.parse_draw(line)
        if draw["vram"]:
            vram = draw["vram"]
        draw["vram"] = vram
        yield draw


def _shown(ctx, draw, count=None):
    entries = snes_host.decode_oam(draw["oam"])
    return snes_host.rasterise(entries if count is None else entries[:count], draw["vram"] + bytes(0x4000), ctx.small,
                               ctx.large)


@unittest.skipUnless(snes_host.have_compiler(), "no C compiler")
class TestStreamedRuntime(unittest.TestCase):
    def test_every_frame_through_the_default_slot(self):
        """Each frame, drawn at the centre and across the edges: the first draw uploads its load list (unless the slot
        holds it already), the others nothing, and the screen shows what the editor shows."""
        from ui.frame_render import FrameRenderer

        renderer = FrameRenderer()
        for path in PROJECTS:
            project = Project.from_json(str(path))
            for mode in STREAMED:
                with self.subTest(project=path.name, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    folder = Path(tmp)
                    ctx, exe = _export_and_build(project, folder, mode, "none")
                    commands = [f"frame {f} 0 {x} {y}" for f in range(len(project.frames)) for x, y in POSITIONS]
                    head, lines = snes_host.run(exe, folder, commands)
                    records = list(export_snes.RECORDS.values()) + list(export_snes.STREAM_RECORDS.values())
                    self.assertEqual(head["sizes"], " ".join(str(record.size) for record in records),
                                     "the C records are the exporter's")
                    self.assertEqual(set(snes_host.vram_bytes(head)), {0}, "a streamed export loads no tiles at start")
                    draws = iter(_draws(lines))
                    loaded = None
                    for index, frame in enumerate(project.frames):
                        image, hx, hy = renderer.render(project, frame, None)
                        listed = ctx.render_frame_loads[ctx.frame_render_frames[index]]
                        for p, (x, y) in enumerate(POSITIONS):
                            draw = next(draws)
                            self.assertEqual((draw["dropped"], draw["waiting"]), (0, 0))
                            fresh = p == 0 and listed != export_snes.NO_LIST and listed != loaded
                            self.assertEqual(draw["uploaded"], ctx.load_lists[listed][1] if fresh else 0,
                                             f"{frame.name}: tiles uploaded at {x},{y}")
                            self.assertEqual(_shown(ctx, draw), _editor_pixels(ctx, image, int(hx), int(hy), x, y),
                                             f"{path.name} ({mode}): '{frame.name}' at {x},{y}")
                        if listed != export_snes.NO_LIST:
                            loaded = listed

    def test_mirrored_frames_through_the_default_slot(self):
        """ms_draw_frame_flipped through a slot: each frame mirrored each way shows what the editor's mirrored frame
        shows (Sonic: more tiles than video memory keeps)."""
        from test_snes_runtime_draw import _mirrored
        from ui.frame_render import FrameRenderer

        renderer = FrameRenderer()
        project = Project.from_json(str(PROJECTS[1]))
        for mode in STREAMED:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                ctx, exe = _export_and_build(project, folder, mode, "none")
                draws = [(f, flip, x, y) for f in range(len(project.frames)) for flip in (1, 2, 3)
                         for x, y in POSITIONS[:2]]
                _head, lines = snes_host.run(exe, folder, [f"flipped {f} 0 {flip} {x} {y}" for f, flip, x, y in draws])
                self.assertEqual(len(lines), len(draws))
                for (f, flip, x, y), draw in zip(draws, _draws(lines)):
                    self.assertEqual((draw["dropped"], draw["waiting"]), (0, 0))
                    image, hx, hy = renderer.render(project, project.frames[f], None)
                    image, hx, hy = _mirrored(image, int(hx), int(hy), flip)
                    self.assertEqual(_shown(ctx, draw), _editor_pixels(ctx, image, hx, hy, x, y),
                                     f"{mode}: '{project.frames[f].name}' mirrored {flip} at {x},{y}")

    def test_load_lists_for_a_game_of_its_own_slots(self):
        """A game that keeps its own slots asks each frame's and module's load list and its tiles (a list drawn by
        several actors is loaded once): ms_frame_load_list, ms_module_load_list and ms_load_list_tiles name the
        export's lists under the active mapping; out of range, and in an export that keeps every tile in video memory,
        they name none."""
        project = Project.from_json(str(PROJECTS[0]))
        mappings = 1 + len(project.mappings)
        for mode in ("parts",) + STREAMED:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                ctx, exe = _export_and_build(project, folder, mode)
                _head, lines = snes_host.run(exe, folder, [f"lists {m}" for m in range(mappings)])
                self.assertEqual(len(lines), mappings)
                for m, line in enumerate(lines):
                    _what, frames, modules, beyond = line.split(" ")
                    for kind, field, renders in (("frame", frames, ctx.frame_render_frames),
                                                 ("module", modules, ctx.module_render_frames)):
                        count = len(renders) // mappings
                        got = [tuple(int(v) for v in item.split(":")) for item in field.split(",")]
                        if ctx.streamed:
                            listed = [ctx.render_frame_loads[render] for render in renders[m * count:(m + 1) * count]]
                            expected = [(n, 0 if n == export_snes.NO_LIST else ctx.load_lists[n][1]) for n in listed]
                        else:
                            expected = [(0xFFFF, 0)] * count
                        self.assertEqual(got, expected, f"{mode}, mapping {m}: the {kind}s' load lists")
                    self.assertEqual(beyond, "65535:65535:0", "out of range: none")
                if ctx.streamed:
                    self.assertGreater(len({n for n in ctx.render_frame_loads if n != export_snes.NO_LIST}), 1)

    def test_two_characters_in_two_slots(self):
        """One animation drawn as it is through the default slot and re-skinned and recoloured through a slot of its
        own (ms_draw_anim_player_as): both upload when their step's tiles change and show what the editor shows."""
        from ui.frame_render import FrameRenderer, transform

        project = Project.from_json(str(PROJECTS[0]))
        guard_mapping = project.mappings[0]
        swap = project.palette_swaps[0]
        names = ["C34 Attack", "C46 quick attack", "C21 multi stab throw enemy"]  # offsets, step flips
        animations = [next(i for i, a in enumerate(project.animations) if a.name == n) for n in names]
        left, right = (60, 150), (190, 150)
        for mode in STREAMED:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                ctx, exe = _export_and_build(project, folder, mode)
                commands = ["budget 65535"] + [f"versus {a} 1 1 {t} {left[0]} {left[1]} {right[0]} {right[1]}"
                                               for a in animations for t in range(0, 150, 3)]
                _head, lines = snes_host.run(exe, folder, commands)
                renderer, shown, uploads = FrameRenderer(), set(), 0
                for command, line, draw in zip(commands[1:], lines, _draws(lines)):
                    anim = project.animations[int(command.split()[1])]
                    step = int(line.split()[1])
                    self.assertEqual((draw["dropped"], draw["waiting"]), (0, 0))
                    uploads += draw["uploaded"] > 0
                    af = anim.aframes[step]
                    a, b = transform(af.flip_x, af.flip_y, af.rotation_degrees, af.offset)
                    frame = project.get_frame(af.frame_id)
                    expected = {}
                    for mapping, entry, (x, y) in ((guard_mapping, ctx.entry_of[(project.palettes[0].id, swap.id)],
                                                    right), (None, 0, left)):
                        image, hx, hy = renderer.render(project, frame, mapping, a, b)
                        expected.update(_editor_pixels(ctx, image, int(hx), int(hy), x, y, lambda px, py: entry))
                    self.assertEqual(_shown(ctx, draw), expected, f"{mode}: '{anim.name}' step {step}")
                    shown.add((anim.name, step))
                self.assertEqual(len(shown), sum(len(project.animations[i].aframes) for i in animations))
                self.assertLess(uploads, len(lines), "a step that shows the same tiles uploads nothing")

    def test_modules_and_scenes_like_the_default_export(self):
        """Every module and the Swordfight in every mapping (a scene streams through one slot, a sample's tiles at a
        time): the streamed export shows the same pixels as the export that keeps every tile in video memory."""
        project = Project.from_json(str(PROJECTS[0]))
        mappings = 1 + len(project.mappings)
        commands = []
        for m in range(mappings):
            commands += [f"frame 0 {m} 128 112"]  # (the frames' own test covers them)
            commands += [f"scene 0 {m} {t} 128 168" for t in range(0, 400, 2)]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "resident"
            ctx, exe = _export_and_build(project, folder, "parts")
            head, lines = snes_host.run(exe, folder, commands)
            vram = snes_host.vram_bytes(head)
            expected = [snes_host.rasterise(snes_host.decode_oam(snes_host.oam_of(line)), vram, ctx.small, ctx.large)
                        for line in lines]
        for mode in STREAMED:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                ctx, exe = _export_and_build(project, folder, mode)
                _head, lines = snes_host.run(exe, folder, commands)
                got = [_shown(ctx, draw) for draw in _draws(lines)]
                self.assertEqual(len(got), len(expected))
                for command, want, have in zip(commands, expected, got):
                    self.assertEqual(have, want, f"{mode}: {command}")

    def test_uploads_wait_for_room_in_the_budget(self):
        """Over the vertical blank's budget a draw shows what its slot holds (the step it showed before, or nothing)
        and uploads once there is room; the first list of a frame goes whatever it costs."""
        project = Project.from_json(str(PROJECTS[0]))
        anim = next(i for i, a in enumerate(project.animations) if a.name == "C34 Attack")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ctx, exe = _export_and_build(project, folder, "parts_streamed")
            player = [f"versus {anim} 0 0 {t} 60 150 190 150" for t in range(0, 60)]
            _head, lines = snes_host.run(exe, folder, player)
            steps = [int(line.split()[1]) for line in lines]
            later = steps.index(next(s for s in steps if s != steps[0]))  # the first tick of the next step
            commands = ["budget 10", player[0], "budget 65535", player[0], "budget 10", player[later]]
            _head, lines = snes_host.run(exe, folder, commands)
            draws = list(_draws(lines))
        alone, both, late = draws
        right = lambda draw: {xy: v for xy, v in _shown(ctx, draw).items() if xy[0] >= 128}  # noqa: E731
        left = lambda draw: {xy: v for xy, v in _shown(ctx, draw).items() if xy[0] < 128}  # noqa: E731
        self.assertEqual(alone["waiting"], 1)
        self.assertGreater(alone["uploaded"], 0, "the first list goes, over the budget too")
        self.assertTrue(left(alone))
        self.assertEqual(right(alone), {}, "a slot that holds nothing shows nothing while its upload waits")
        self.assertEqual(both["waiting"], 0)
        self.assertTrue(right(both))
        self.assertEqual(late["waiting"], 1)
        self.assertNotEqual(left(late), left(both), "the first character shows the next step")
        self.assertEqual(right(late), right(both), "the second shows the step its slot holds")

    def test_a_list_past_the_vertical_blank_is_queued_again(self):
        """When the vertical blank ends during a list, the slot holds nothing known: the next draw queues the list
        again and shows the frame right."""
        project = Project.from_json(str(PROJECTS[0]))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ctx, exe = _export_and_build(project, folder, "parts_streamed", "none")
            frame = next(i for i, r in enumerate(ctx.frame_render_frames)
                         if ctx.render_frame_loads[r] != export_snes.NO_LIST)
            commands = ["vblank 1", f"frame {frame} 0 128 112", f"frame {frame} 0 128 112", f"frame {frame} 0 128 112"]
            _head, lines = snes_host.run(exe, folder, commands)
            draws = list(_draws(lines))
        tiles = ctx.load_lists[ctx.render_frame_loads[ctx.frame_render_frames[frame]]][1]
        self.assertEqual([draw["uploaded"] for draw in draws], [tiles, tiles, 0],
                         "cut off after the list, queued again, then held")
        self.assertEqual(_shown(ctx, draws[1]), _shown(ctx, draws[2]))


class TestStreamedExport(unittest.TestCase):
    def test_the_default_export_keeps_every_tile(self):
        project = Project.from_json(str(PROJECTS[2]))
        with tempfile.TemporaryDirectory() as tmp:
            result = export_snes.export_project(project, Path(tmp) / "game")
            header = (Path(tmp) / "game" / export_snes.HEADER_FILE).read_text()
        self.assertNotIn("MS_STREAMED", header)
        self.assertIn(f"#define MS_DATA_VERSION {export_snes.DATA_VERSION}", header)
        self.assertNotIn("slot_tiles", result.summary)
        self.assertIn("tiles", [issue.code for issue in result.issues])

    def test_a_streamed_export_reports_its_slots(self):
        project = Project.from_json(str(PROJECTS[1]))  # Sonic: 600 tiles, more than the 512 kept in video memory
        with tempfile.TemporaryDirectory() as tmp:
            result = export_snes.export_project(project, Path(tmp) / "game", mode="parts_streamed")
            header = (Path(tmp) / "game" / export_snes.HEADER_FILE).read_text()
        self.assertIn("#define MS_STREAMED 1", header)
        self.assertIn(f"#define MS_DATA_VERSION {export_snes.STREAMED_DATA_VERSION}", header)
        self.assertIn(f"#define MS_SLOT_TILES {result.summary['slot_tiles']}", header)
        self.assertEqual(result.summary["slot_tiles"] % 16, 0, "whole rows of a sprite table")
        codes = [issue.code for issue in result.issues]
        self.assertIn("slots", codes)
        self.assertNotIn("tiles", codes, "no resident tile count")
        self.assertIn("Streamed", export_snes.report_line(result.summary))
        with self.assertRaises(export_snes.ExportError):
            with tempfile.TemporaryDirectory() as tmp:
                export_snes.export_project(project, Path(tmp) / "game")

    def test_the_slots_are_what_export_modes_measures(self):
        project = Project.from_json(str(PROJECTS[0]))
        mappings = [None] + list(project.mappings)
        for mode in STREAMED:
            with self.subTest(mode=mode):
                ctx = export_snes.SNESBakeContext(project, mappings, mode=mode)
                ctx.bake()
                costs = export_modes.measure_mode(project, console_exports.SNES, export_modes.mode_by_key(mode))
                self.assertEqual((ctx.slot_tiles, ctx.scene_slot_tiles), (costs.video_tiles, costs.scene_video_tiles))
                self.assertEqual(ctx.tiles_used(), costs.cartridge_tiles)

    def test_the_slot_layout(self):
        """Every square of a render frame sits in its slot aligned to its size, inside the slot's rows, none over
        another; its runs copy each square's rows from the cartridge to where the square sits."""
        project = Project.from_json(str(PROJECTS[0]))
        ctx = export_snes.SNESBakeContext(project, [None] + list(project.mappings), mode="parts_streamed")
        ctx.bake()
        store = {}  # (chunk, offset of a tile) -> the tile's 32 bytes
        for chunk, piece in enumerate(ctx.store_pieces):
            for at in range(0, len(piece), 32):
                store[(chunk, at)] = piece[at:at + 32]
        for render, in_slot in enumerate(ctx.render_frame_slot_tiles):
            listed = ctx.render_frame_loads[render]
            if listed == export_snes.NO_LIST:
                continue
            runs, tiles, _cost = ctx.load_lists[listed]
            slot = {}
            for chunk, source, tile, count in runs:
                for k in range(count):
                    self.assertNotIn(tile + k, slot, "runs never overlap in the slot")
                    slot[tile + k] = store[(chunk, source + k * 32)]
            limit = ctx.slot_tiles if render not in set(ctx.scene_samples) else max(ctx.slot_tiles, ctx.scene_slot_tiles)
            for block, first in in_slot.items():
                side, pixels = ctx.blocks[block]
                self.assertEqual((first // 16 % side, first % 16 % side), (0, 0), "aligned to its size")
                for ty in range(side):
                    for tx in range(side):
                        tile = first + ty * 16 + tx
                        self.assertLess(tile, limit)
                        self.assertEqual(slot.get(tile), export_snes._snes_tile(pixels, side * 8, tx * 8, ty * 8))
            self.assertEqual(tiles, len(slot))

    def test_the_command_line_takes_a_mode(self):
        self.assertEqual(console_exports.SNES.modes, export_snes.MODES)
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run([sys.executable, str(REPO_ROOT / "examples" / "snes" / "tools" / "export_snes.py"),
                                  "--project-json", str(PROJECTS[1]), "--output-dir", str(Path(tmp) / "game"),
                                  "--mode", "frames_streamed"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout[-1000:] + run.stderr[-1000:])
            self.assertIn("mode: frames_streamed", run.stdout)


if __name__ == "__main__":
    unittest.main()
