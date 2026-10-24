"""The SNES runtime must draw every frame exactly like the editor.

Exports the testbeds with the SNES exporter (examples/snes/tools/export_snes.py), compiles
examples/snes/snes_demo/src/modsprite.c with the generated data file for the host (examples/snes/tools/snes_host.py:
PVSnesLib replaced by a small stub, the OAM buffer, VRAM and CGRAM as arrays), loads the real data chunks, lets the runtime draw each frame into the OAM
buffer (in the middle of the screen and across its edges; as it is and mirrored each way, and each module), then
decodes that buffer like the PPU does (the high table's
X bit and size bit, the setup's two sprite sizes, 4 bpp planar tiles from the 16-tile-wide sprite tables, flips, lower
entries in front) and compares the visible pixels with the editor's renderer as (palette entry, colour slot). Also
draws the Swordfight scene (the guard keeps his own palette swap) and one animation twice with
ms_draw_anim_player_as. Skipped without a C compiler.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "examples" / "snes" / "tools"))

from models import Project  # noqa: E402

import snes_host  # noqa: E402

SCREEN_W, SCREEN_H = snes_host.SCREEN_W, snes_host.SCREEN_H
POSITIONS = [(128, 112), (6, 10), (250, 216)]  # centre, across the top-left and the bottom-right edges
PROJECTS = [REPO_ROOT / "examples" / "pop" / "PoP_WW.json", REPO_ROOT / "examples" / "adventurer" / "adventurer.json"]


def _editor_pixels(ctx, image, hx: int, hy: int, draw_x: int, draw_y: int, palette_at=lambda x, y: 0):
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


def _mirrored(image, hx: int, hy: int, flip: int):
    """A picture whose top left is at (hx, hy) mirrored around the origin (flip: bit 0 left-right, bit 1 top-bottom; a
    pixel's x goes to -x - 1), and its new top left."""
    from PIL import Image

    if flip & 1:
        image, hx = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT), -hx - image.width
    if flip & 2:
        image, hy = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM), -hy - image.height
    return image, hx, hy


def _export_and_build(project: Project, folder: Path, mappings: str = "all"):
    ctx = snes_host.export(project, folder, mappings)
    return ctx, snes_host.build(ctx, folder)


@unittest.skipUnless(snes_host.have_compiler(), "no C compiler")
class SNESRuntimeTest(unittest.TestCase):
    def test_every_frame_like_the_editor(self):
        from ui.frame_render import FrameRenderer

        renderer = FrameRenderer()
        for path in PROJECTS:
            project = Project.from_json(str(path))
            with self.subTest(project=path.name), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                ctx, exe = _export_and_build(project, folder, "none")
                commands = [f"frame {f} 0 {x} {y}" for f in range(len(project.frames)) for x, y in POSITIONS]
                head, lines = snes_host.run(exe, folder, commands)
                import export_snes

                self.assertEqual(head["sizes"], " ".join(str(record.size) for record in export_snes.RECORDS.values()),
                                 "the C records are the exporter's")
                vram = snes_host.vram_bytes(head)
                self.assertEqual(vram[:len(ctx.tables)], bytes(ctx.tables), "every sprite tile in VRAM, both tables")
                self.assertEqual(head["obsel"], f"0 {export_snes.OBSEL_SIZES[tuple(ctx.setup.sizes)] << 5}",
                                 "OBSEL: the tiles at 0x0000, the setup's sizes")
                checked = 0
                for (frame_index, (x, y)), line in zip([(f, p) for f in range(len(project.frames)) for p in POSITIONS],
                                                        lines):
                    _what, sprites, dropped, oam = line.split(" ")
                    self.assertEqual(dropped, "0")
                    shown = snes_host.rasterise(snes_host.decode_oam(oam), vram, ctx.small, ctx.large)
                    image, hx, hy = renderer.render(project, project.frames[frame_index], None)
                    expected = _editor_pixels(ctx, image, int(hx), int(hy), x, y)
                    self.assertEqual(shown, expected, f"{project.frames[frame_index].name} at {x},{y}")
                    checked += 1
                self.assertEqual(checked, len(project.frames) * len(POSITIONS))

    def test_every_frame_mirrored(self):
        """ms_draw_frame_flipped draws each frame as the editor mirrors it around its origin, each way, in the middle
        of the screen and across the edges."""
        from ui.frame_render import FrameRenderer

        renderer = FrameRenderer()
        for path in PROJECTS:
            project = Project.from_json(str(path))
            with self.subTest(project=path.name), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                ctx, exe = _export_and_build(project, folder, "none")
                draws = [(f, flip, x, y) for f in range(len(project.frames)) for flip in (1, 2, 3) for x, y in POSITIONS]
                head, lines = snes_host.run(exe, folder, [f"flipped {f} 0 {flip} {x} {y}" for f, flip, x, y in draws])
                vram = snes_host.vram_bytes(head)
                self.assertEqual(len(lines), len(draws))
                pictures = {}
                for (f, flip, x, y), line in zip(draws, lines):
                    draw = snes_host.parse_draw(line)
                    self.assertEqual((draw["what"], draw["dropped"]), ("flipped", 0))
                    if f not in pictures:
                        image, hx, hy = renderer.render(project, project.frames[f], None)
                        pictures[f] = (image, int(hx), int(hy))
                    image, hx, hy = _mirrored(*pictures[f], flip)
                    shown = snes_host.rasterise(snes_host.decode_oam(draw["oam"]), vram, ctx.small, ctx.large)
                    self.assertEqual(shown, _editor_pixels(ctx, image, hx, hy, x, y),
                                     f"{path.name}: '{project.frames[f].name}' mirrored {flip} at {x},{y}")

    def test_every_module_as_it_is_and_mirrored(self):
        """ms_draw_module_flipped draws each module with its pivot where it is drawn, as it is (flip 0: ms_draw_module)
        and mirrored in place each way, as the editor mirrors a part (its picture stays where it is), in the middle of
        the screen and across the top-left edge; with every mapping, the module each one draws in its place."""
        import compositor
        from ui.frame_render import FrameRenderer

        renderer = FrameRenderer()
        for path in PROJECTS:
            project = Project.from_json(str(path))
            with self.subTest(project=path.name), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                ctx, exe = _export_and_build(project, folder)
                draws = [(mapping, m, flip, x, y) for mapping in range(len(ctx.mappings))
                         for m in range(len(project.modules)) for flip in range(4) for x, y in POSITIONS[:2]]
                head, lines = snes_host.run(exe, folder, [f"module {m} {mapping} {flip} {x} {y}"
                                                          for mapping, m, flip, x, y in draws])
                vram = snes_host.vram_bytes(head)
                self.assertEqual(len(lines), len(draws))
                for (mapping, m, flip, x, y), line in zip(draws, lines):
                    module = compositor.resolve_module(project, project.modules[m].id, ctx.mappings[mapping])
                    draw = snes_host.parse_draw(line)
                    self.assertEqual((draw["what"], draw["dropped"]), ("module", 0))
                    shown = snes_host.rasterise(snes_host.decode_oam(draw["oam"]), vram, ctx.small, ctx.large)
                    if module is None or module.rect[2] <= 0 or module.rect[3] <= 0:
                        self.assertEqual(shown, {}, f"{path.name}: module {m} hidden by mapping {mapping}")
                        continue
                    image, _hx, _hy = _mirrored(renderer.module(project, module), 0, 0, flip)
                    self.assertEqual(shown, _editor_pixels(ctx, image, -int(module.pivot[0]), -int(module.pivot[1]),
                                                           x, y),
                                     f"{path.name}: module '{module.name}' (mapping {mapping}) mirrored {flip} at {x},{y}")

    def test_frames_stored_whole(self):
        """Frames stored whole are drawn as their pictures, the others as parts: PoP with its turns stored whole, every
        frame as it is and mirrored and the turns for the hero and the guard (whose mapping changes the pictures);
        frames of two palettes stored whole, nested in parts, mirrored and turned, and an animation that turns them."""
        import mixed_frames
        from ui.frame_render import FrameRenderer, transform

        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from test_megadrive_runtime_draw import _palette_of_pixels

        renderer = FrameRenderer()
        project = mixed_frames.pop_mixed(mixed_frames.TURNS, every=0)
        guard = next(m for m in project.mappings if m.name == "Normal")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ctx, exe = _export_and_build(project, folder)
            self.assertEqual(ctx.mapping_ids[1], guard.id)
            frames = range(len(project.frames))
            draws = [(f, 0, x, y) for f in frames for x, y in POSITIONS] + \
                    [(f, flip, x, y) for f in frames for flip in (1, 2, 3) for x, y in POSITIONS[:2]]
            turns = [i for i, a in enumerate(project.animations) if a.name in mixed_frames.TURNS]
            plays = [(anim, tick) for anim in turns for tick in range(0, 90, 3)]
            commands = [f"flipped {f} 0 {flip} {x} {y}" if flip else f"frame {f} 0 {x} {y}" for f, flip, x, y in draws]
            commands += [f"versus {anim} 1 0 {tick} 80 160 176 160" for anim, tick in plays]
            head, lines = snes_host.run(exe, folder, commands)
            vram = snes_host.vram_bytes(head)
            for (f, flip, x, y), line in zip(draws, lines):
                draw = snes_host.parse_draw(line)
                self.assertEqual(draw["dropped"], 0)
                image, hx, hy = _mirrored(*renderer.render(project, project.frames[f], None)[:3], flip)
                shown = snes_host.rasterise(snes_host.decode_oam(draw["oam"]), vram, ctx.small, ctx.large)
                self.assertEqual(shown, _editor_pixels(ctx, image, int(hx), int(hy), x, y),
                                 f"'{project.frames[f].name}' mirrored {flip} at {x},{y}")
            steps = set()
            for (anim, _tick), line in zip(plays, lines[len(draws):]):
                _label, step, mapping, swap, _what, sprites, dropped, oam = line.split(" ")
                self.assertEqual((mapping, swap, dropped), ("0", "0", "0"))
                af = project.animations[anim].aframes[int(step)]
                a, b = transform(af.flip_x, af.flip_y, af.rotation_degrees, af.offset)
                expected = {}
                for mapping, (x, y) in ((guard, (176, 160)), (None, (80, 160))):  # the hero is drawn first: in front
                    image, hx, hy = renderer.render(project, project.get_frame(af.frame_id), mapping, a, b)
                    expected.update(_editor_pixels(ctx, image, int(hx), int(hy), x, y))
                shown = snes_host.rasterise(snes_host.decode_oam(oam)[:int(sprites)], vram, ctx.small, ctx.large)
                self.assertEqual(shown, expected, f"{project.animations[anim].name} step {step}")
                steps.add((anim, int(step)))
            self.assertEqual(len(steps), sum(len(project.animations[a].aframes) for a in turns))

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            project = mixed_frames.nested_project(folder)
            project.console, project.console_setup = "snes", "snes_16_32"  # twice in one sprite table: under 128
            ctx, exe = _export_and_build(project, folder / "out", "none")
            self.assertEqual((ctx.small, ctx.large), (16, 32))
            anim = project.animations[0]
            draws = [(f, x, y) for f in range(len(project.frames)) for x, y in POSITIONS]
            commands = [f"frame {f} 0 {x} {y}" for f, x, y in draws] + \
                       [f"versus 0 0 0 {tick} 60 120 180 100" for tick in range(0, 84, 4)]
            head, lines = snes_host.run(exe, folder / "out", commands)
            vram = snes_host.vram_bytes(head)
            identity = ((1.0, 0.0), (0.0, 1.0)), (0.0, 0.0)
            for (f, x, y), line in zip(draws, lines):
                frame = project.frames[f]
                image, hx, hy = renderer.render(project, frame, None)
                draw = snes_host.parse_draw(line)
                self.assertEqual(draw["dropped"], 0)
                shown = snes_host.rasterise(snes_host.decode_oam(draw["oam"]), vram, ctx.small, ctx.large)
                self.assertEqual(shown, _editor_pixels(ctx, image, int(hx), int(hy), x, y,
                                                       _palette_of_pixels(project, frame, None, identity)),
                                 f"'{frame.name}' at {x},{y}")
            steps = set()
            for line in lines[len(draws):]:
                _label, step, _mapping, _swap, _what, sprites, dropped, oam = line.split(" ")
                self.assertEqual(dropped, "0")
                af = anim.aframes[int(step)]
                a, b = transform(af.flip_x, af.flip_y, af.rotation_degrees, af.offset)
                frame = project.get_frame(af.frame_id)
                image, hx, hy = renderer.render(project, frame, None, a, b)
                palette_at = _palette_of_pixels(project, frame, None, (a, b))
                expected = {}
                for x, y in ((180, 100), (60, 120)):
                    expected.update(_editor_pixels(ctx, image, int(hx), int(hy), x, y, palette_at))
                shown = snes_host.rasterise(snes_host.decode_oam(oam)[:int(sprites)], vram, ctx.small, ctx.large)
                self.assertEqual(shown, expected, f"step {step}")
                steps.add(int(step))
            self.assertEqual(steps, set(range(len(anim.aframes))))

    def test_the_swordfight_and_a_recoloured_guard(self):
        """The scene draws its objects with their own mapping and swap; ms_draw_anim_player_as recolours one draw and
        leaves the active mapping and swap as they were."""
        project = Project.from_json(str(PROJECTS[0]))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ctx, exe = _export_and_build(project, folder)
            scene = project.timeline_scenes[0]
            commands = [f"scene 0 0 {t} 128 168" for t in (0, 60, 300)]
            anim = next(i for i, a in enumerate(project.animations) if len(a.aframes) > 1)
            commands.append(f"versus {anim} 1 1 0 80 160 176 160")
            head, lines = snes_host.run(exe, folder, commands)
            vram = snes_host.vram_bytes(head)
            for line in lines[:3]:
                _what, sprites, dropped, oam = line.split(" ")
                self.assertEqual(dropped, "0", scene.name)
                entries = snes_host.decode_oam(oam)[:int(sprites)]
                self.assertTrue(entries, "the scene draws sprites")
                palettes = {(attr >> 1) & 7 for _x, _y, _t, attr, _l in entries}
                self.assertEqual(palettes, {0, 1}, "the Prince in his palette, the guard in the Blue guard's")
                self.assertTrue(snes_host.rasterise(entries, vram, ctx.small, ctx.large))
            _label, _step, mapping, swap, _what, sprites, dropped, oam = lines[3].split(" ")
            self.assertEqual((mapping, swap), ("0", "0"), "ms_draw_anim_player_as leaves the active ones as they were")
            entries = snes_host.decode_oam(oam)[:int(sprites)]
            left = [e for e in entries if e[0] < 128]
            right = [e for e in entries if e[0] >= 128]
            self.assertTrue(left and right)
            self.assertEqual({(e[3] >> 1) & 7 for e in left}, {0})
            self.assertEqual({(e[3] >> 1) & 7 for e in right}, {1}, "the second draw in the swap's palette")

    def test_colour_cycles_turn_like_the_preview(self):
        """ms_palette_tick() turns a loaded entry's colour cycles in CGRAM the way palettes.rotate shows them, a step per
        video frame."""
        import palettes
        from models import ColourCycle

        project = Project.from_json(str(PROJECTS[0]))
        palette = project.palettes[0]
        palette.cycles = [ColourCycle(first=3, count=4, frames=3), ColourCycle(first=9, count=2, frames=5, reverse=True)]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _ctx, exe = _export_and_build(project, folder, "none")
            _head, lines = snes_host.run(exe, folder, ["cycle"] * 40)
            colours = palettes.colours_of(project, palette)
            for frame, line in enumerate(lines):
                shown = palettes.rotate(colours, palette.cycles, frame)
                expected = [0] + [palettes.snes_word(shown[s]) if s < len(shown) else 0 for s in range(15)]
                self.assertEqual([int(v) for v in line.split()[1:17]], expected, f"frame {frame}")


def _snes_sprites(ctx, render: int):
    """A render frame's sprites as the runtime reads them: (x, y, size in pixels)."""
    import export_snes

    data, runs = ctx.sprite_runs(ctx.render_frames[render], ctx.render_frame_slot_tiles[render] if ctx.streamed
                                 else None)
    out, at = [], 0
    for _run in range(runs):
        count = data[at + 1]
        at += export_snes.RUN.size
        for _sprite in range(count):
            x, y, _tile, _attribute, size, _zero = export_snes.SPRITE.unpack_from(data, at)
            out.append((x, y, ctx.large if size else ctx.small))
            at += export_snes.SPRITE.size
    return out


def _snes_cost(ctx, render: int, ox: int, oy: int, flip: int) -> int:
    """The hardware sprites a render frame puts on the screen drawn at (ox, oy) with flip."""
    cost = 0
    for x, y, size in _snes_sprites(ctx, render):
        x, y = ox + (-x - size if flip & 1 else x), oy + (-y - size if flip & 2 else y)
        cost += -size < x < SCREEN_W and -size < y < SCREEN_H
    return cost


def _snes_draw_costs(ctx, draws):
    """Each crowd draw's sprites on the screen (runtime_models.crowd_draws: modules mirrored in place, a sprite's index
    odd for a large one)."""
    frames, modules = len(ctx.project.frames), len(ctx.project.modules)
    offsets = ctx.module_flip_offsets()
    costs = []
    for kind, index, mapping, flip, _level, x, y in draws:
        if kind == "sprite":
            size = ctx.large if index & 1 else ctx.small
            costs.append(int(-size < x < SCREEN_W and -size < y < SCREEN_H))
        elif kind == "frame":
            costs.append(_snes_cost(ctx, ctx.frame_render_frames[mapping * frames + index], x, y, flip))
        else:
            dx, dy = offsets[mapping * modules + index]
            costs.append(_snes_cost(ctx, ctx.module_render_frames[mapping * modules + index],
                                    x + (dx if flip & 1 else 0), y + (dy if flip & 2 else 0), flip))
    return costs


def _put(draw, level: int) -> str:
    """A crowd draw as snes_host's put command."""
    kind, index, mapping, flip, _level, x, y = draw
    if kind == "sprite":
        return f"put sprite {x} {y} {0x100 + index} {0x20 | ((index & 3) << 1)} {index & 1} {level}"
    return f"put {kind} {index} {mapping} {flip} {level} {x} {y}"


@unittest.skipUnless(snes_host.have_compiler(), "no C compiler")
class SNESRuntimePlansAndGivesWay(unittest.TestCase):
    def test_sprites_and_bounds_before_drawing(self):
        """ms_frame_sprites / ms_module_sprites and ms_frame_bounds / ms_module_bounds tell, under each mapping and for
        each flip, what a draw asks for: the render frame's sprites and box (mirrored around the origin, a module in
        place); drawn in the middle of the screen it puts exactly that many sprites into the OAM buffer, all inside the
        box. Out of range: nothing."""
        project = Project.from_json(str(PROJECTS[0]))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ctx, exe = _export_and_build(project, folder)
            mappings = len(ctx.mappings)
            frames, modules = len(project.frames), len(project.modules)
            commands = [f"counts {m}" for m in range(mappings)]
            draws = [(m, kind, index, flip) for m in range(mappings) for kind, count in (("frame", frames),
                                                                                    ("module", modules))
                     for index in range(count) for flip in range(4)]
            commands += [f"flipped {i} {m} {flip} 128 112" if kind == "frame" else f"module {i} {m} {flip} 128 112"
                         for m, kind, i, flip in draws]
            _head, lines = snes_host.run(exe, folder, commands)
        offsets = ctx.module_flip_offsets()
        bounds = {}
        for m, line in enumerate(lines[:mappings]):
            _what, frame_items, module_items, beyond = line.split(" ")
            self.assertEqual(beyond, "0:0")
            for kind, items, renders, count in (("frame", frame_items, ctx.frame_render_frames, frames),
                                                ("module", module_items, ctx.module_render_frames, modules)):
                for index, item in enumerate(items.split(",")):
                    sprites, boxes = item.split(":")
                    count_, min_x, min_y, max_x, max_y = ctx.render_frame_extent(ctx.render_frames[renders[m * count + index]])
                    self.assertEqual(int(sprites), count_, f"{kind} {index}: its sprites")
                    dx, dy = offsets[m * count + index] if kind == "module" else (0, 0)
                    for flip, box in enumerate(boxes.split(";")):
                        shows, *got = (int(v) for v in box.split("/"))
                        want = [dx - max_x if flip & 1 else min_x, dy - max_y if flip & 2 else min_y,
                                dx - min_x if flip & 1 else max_x, dy - min_y if flip & 2 else max_y]
                        self.assertEqual((shows, got), (1, want) if count_ else (0, [0, 0, 0, 0]),
                                         f"{kind} {index} flip {flip}: its bounds")
                        bounds[(m, kind, index, flip)] = (count_, got)
        for (m, kind, index, flip), line in zip(draws, lines[mappings:]):
            draw = snes_host.parse_draw(line)
            count_, (min_x, min_y, max_x, max_y) = bounds[(m, kind, index, flip)]
            self.assertEqual((draw["sprites"], draw["dropped"]), (count_, 0), f"{kind} {index} flip {flip}: drawn")
            for x, y, _tile, _attribute, large in snes_host.decode_oam(draw["oam"])[:count_]:
                size = ctx.large if large else ctx.small
                y = y - 256 if y >= 224 else y  # above the top it wraps from line 255
                self.assertTrue(min_x <= x - 128 and x - 128 + size <= max_x and min_y <= y - 112
                                and y - 112 + size <= max_y, f"{kind} {index} flip {flip}: a sprite outside its bounds")

    def test_draws_give_way_farthest_first(self):
        """Crowds of frames, modules and the game's own sprites, some with give-way levels, across the screen and its
        edges, mirrored and re-skinned: a picture that asks for more than 128 sprites leaves out the draws with a
        level, level 1 first and within it the farthest first, as many as the excess, and then holds exactly the
        sprites the runtime draws without levels from the draws that stay (their entries, high bits, what still
        drops), every entry after them hidden; a picture that fits is as it would be without levels."""
        from runtime_models import crowd_draws, given_way

        project = Project.from_json(str(PROJECTS[0]))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ctx, exe = _export_and_build(project, folder)
            frames, modules = len(project.frames), len(project.modules)
            pictures = [crowd_draws(seed, 8 + seed % 24, frames, modules, len(ctx.mappings), SCREEN_W, SCREEN_H,
                                    own_sprites=seed % 5 * 4) for seed in range(60)]
            costs = [_snes_draw_costs(ctx, draws) for draws in pictures]
            given = [given_way(c, [d[4] for d in draws], 128) for c, draws in zip(costs, pictures)]
            commands = []  # every picture first with only the draws that stay, before any level is set
            for draws, gone in zip(pictures, given):
                commands += ["begin"] + [_put(d, 0) for n, d in enumerate(draws) if n not in gone] + ["end"]
            for draws in pictures:
                commands += ["begin"] + [_put(d, d[4]) for d in draws] + ["end"]
            _head, lines = snes_host.run(exe, folder, commands)
        self.assertEqual(len(lines), 2 * len(pictures))
        hidden = 240 if ctx.small <= 16 else 224
        for p, (plain_line, levels_line) in enumerate(zip(lines[:len(pictures)], lines[len(pictures):])):
            plain, levels = plain_line.split(" "), levels_line.split(" ")
            self.assertEqual(int(levels[1]), len(given[p]), f"picture {p}: draws that gave way")
            self.assertEqual((plain[1], levels[2]), ("0", "0"), f"picture {p}: nothing left out")
            a, b = snes_host.parse_draw(" ".join(plain[4:])), snes_host.parse_draw(" ".join(levels[4:]))
            self.assertEqual((b["sprites"], b["dropped"]), (a["sprites"], a["dropped"]), f"picture {p}")
            count = b["sprites"]
            self.assertEqual(snes_host.decode_oam(b["oam"])[:count], snes_host.decode_oam(a["oam"])[:count],
                             f"picture {p} ({sum(costs[p])} asked): the sprites")
            self.assertTrue(all(y == hidden for _x, y, *_rest in snes_host.decode_oam(b["oam"])[count:]),
                            f"picture {p}: every entry after them hidden")
        firsts = [next((n for n in range(len(c)) if sum(c[:n + 1]) > 128), len(c)) for c in costs]
        self.assertGreater(sum(1 for c in costs if sum(c) > 128), 10, "enough pictures ask for too much")
        self.assertTrue(any(n < first for g, first in zip(given, firsts) for n in g), "written ones gave way")
        self.assertTrue(any(n >= first for g, first in zip(given, firsts) for n in g), "waiting ones gave way")
        self.assertTrue(any(pictures[p][n][0] == "sprite" for p, g in enumerate(given) for n in g), "own sprites too")
        self.assertTrue(any(snes_host.parse_draw(" ".join(line.split(" ")[4:]))["dropped"] for line in lines),
                        "some still drop the farthest sprites")


if __name__ == "__main__":
    unittest.main()
