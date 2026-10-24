import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "examples", "megadrive", "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import compositor  # noqa: E402
import hardware_budget as hb  # noqa: E402
import sprite_cut  # noqa: E402
from models import FModule, ModuleMapping, Palette, Project, TimelineKeyframe, generate_id  # noqa: E402


def _transform(flip_x=False, flip_y=False, rotation=0.0, offset=(0.0, 0.0)):
    a = compositor.mat_mul(compositor.rotation_matrix(rotation), compositor.flip_matrix(flip_x, flip_y))
    return a, (float(offset[0]), float(offset[1]))


def _sheet(path, size=(64, 48), hole=None):
    img = Image.new("RGBA", size, (255, 0, 255, 255))
    for y in range(size[1]):
        for x in range(size[0]):
            if hole and hole[0] <= x < hole[2] and hole[1] <= y < hole[3]:
                continue
            img.putpixel((x, y), (10 + x * 3 % 200, 20 + y * 5 % 200, 90, 255))
    img.save(path)


class TestGridAndLines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sheet = os.path.join(self.tmp.name, "sheet.png")
        # A transparent (key colour) 8×8 hole that is exactly the last block of the "holey" module.
        _sheet(sheet, size=(96, 48), hole=(80, 32, 88, 40))
        self.project = Project()
        image = self.project.create_image(sheet, 96, 48)
        image.transparent_color = (255, 0, 255)
        self.big = self.project.create_module("big", image.id, (0, 0, 40, 40), (0, 0))
        self.holey = self.project.create_module("holey", image.id, (48, 0, 40, 40), (0, 0))
        self.calc = hb.BudgetCalculator()

    def tearDown(self):
        self.tmp.cleanup()

    def _frame(self, module, position=(0, 0), flip_x=False):
        frame = self.project.create_frame("f")
        frame.fmodules.append(FModule(id=generate_id("fm"), ref_type="module", ref_id=module.id, position=position, flip_x=flip_x))
        return frame

    def test_part_is_cut_into_32px_blocks(self):
        budget = self.calc.frame_budget(self.project, self._frame(self.big), None, hb.MEGA_DRIVE_H40)
        self.assertEqual(budget.sprite_count, 4)  # 40×40 -> 32+8 by 32+8
        self.assertEqual(budget.tile_count, 25)
        sizes = sorted((s.w, s.h) for s in budget.sprites)
        self.assertEqual(sizes, [(8, 8), (8, 32), (32, 8), (32, 32)])

    def test_fully_transparent_blocks_are_skipped(self):
        budget = self.calc.frame_budget(self.project, self._frame(self.holey), None, hb.MEGA_DRIVE_H40)
        self.assertEqual(budget.sprite_count, 3)  # the empty 8×8 corner block needs no sprite
        self.assertEqual(budget.tile_count, 24)

    def test_a_new_key_colour_counts_again(self):
        frame = self._frame(self.holey)
        self.assertEqual(self.calc.frame_budget(self.project, frame, None, hb.MEGA_DRIVE_H40).sprite_count, 3)
        self.project.images[0].transparent_color = None  # the hole shows its magenta pixels now
        budget = self.calc.frame_budget(self.project, frame, None, hb.MEGA_DRIVE_H40)
        self.assertEqual((budget.sprite_count, budget.tile_count), (4, 25))

    def test_hardware_flip_mirrors_the_block_layout(self):
        plain = self.calc.frame_budget(self.project, self._frame(self.big), None, hb.MEGA_DRIVE_H40)
        a, b = _transform(flip_x=True)
        mirrored = self.calc.frame_budget(self.project, self._frame(self.big), None, hb.MEGA_DRIVE_H40, a, b)
        self.assertTrue(all(p.hflip for p in mirrored.parts))
        self.assertEqual(sorted((-s.x - s.w, s.y, s.w, s.h) for s in mirrored.sprites),
                         sorted((s.x, s.y, s.w, s.h) for s in plain.sprites))

    def test_scanline_limits(self):
        profile = hb.MEGA_DRIVE_H40
        parts = [hb.HwPart(i * 8, 0, 8, 8, False, False, [hb.HwSprite(i * 8, 0, 8, 8)]) for i in range(21)]
        budget = hb.Budget(profile, parts)
        self.assertEqual(budget.worst_line(), (21, 168))
        self.assertEqual(budget.over_lines(), [(0, 7)])
        self.assertTrue(budget.over_budget())
        wide = hb.Budget(profile, [hb.HwPart(0, 4, 32, 8, False, False, [hb.HwSprite(i * 32, 4, 32, 8)]) for i in range(11)])
        self.assertEqual(wide.worst_line(), (11, 352))  # 352 px > 320: pixel limit
        self.assertEqual(wide.over_lines(), [(4, 11)])
        self.assertFalse(hb.Budget(profile, parts[:20]).over_budget())


class TestMatchesSgdkExporter(unittest.TestCase):
    """Part placement (position, padded size, flip bits) must equal what the SGDK exporter bakes."""

    def _check(self, project):
        import export_megadrive as sg

        calc = hb.BudgetCalculator()
        cases = [(f, (0.0, 0.0), 0.0, False, False) for f in project.frames]
        for anim in project.animations:
            for af in anim.aframes:
                frame = project.get_frame(af.frame_id)
                if frame:
                    cases.append((frame, tuple(map(float, af.offset)), float(af.rotation_degrees), bool(af.flip_x), bool(af.flip_y)))
        with tempfile.TemporaryDirectory() as out:
            (Path(out) / "res" / "gen").mkdir(parents=True)
            ctx = sg.MegaDriveBakeContext(project, [None], Path(out))
            for frame, offset, rotation, flip_x, flip_y in cases:
                expected = sorted(
                    (x, y, ctx.variants[v].tile_w * 8, ctx.variants[v].tile_h * 8, bool(h), bool(vf))
                    for v, x, y, h, vf in ctx._render_frame_parts(frame, offset, rotation, flip_x, flip_y)
                )
                a, b = _transform(flip_x, flip_y, rotation, offset)
                ours = sorted((p.x, p.y, p.w, p.h, p.hflip, p.vflip) for p in calc.frame_parts(project, frame, None, hb.MEGA_DRIVE_H40, a, b))
                self.assertEqual(expected, ours, f"{frame.name} {offset} {rotation} {flip_x} {flip_y}")
        return len(cases)

    def test_synthetic_nested_rotated_flipped(self):
        import test_export_canvas_parity as parity

        with tempfile.TemporaryDirectory() as tmp:
            sheet = os.path.join(tmp, "sheet.png")
            parity._asymmetric_sheet(sheet)
            path = os.path.join(tmp, "p.json")
            parity._build_project(sheet).to_json(path)
            self.assertGreater(self._check(Project.from_json(path)), 60)

    def test_pop_testbed(self):
        self.assertGreater(self._check(Project.from_json(os.path.join(REPO_ROOT, "examples", "pop", "PoP_WW.json"))), 500)

    def test_frames_stored_whole(self):
        """Frames stored whole are their pictures, placed and flipped like the export's: on their own, as steps that
        move, mirror and turn them, nested in frames of parts two levels deep, with two palettes."""
        import mixed_frames

        self.assertGreater(self._check(mixed_frames.pop_mixed()), 500)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._check(mixed_frames.nested_project(Path(tmp))), 12)


class TestVideoMemory(unittest.TestCase):
    """Tiles the Mega Drive export keeps in video memory: each stored block once, the project's total as exported."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_repeated_and_flipped_parts_need_their_tiles_once(self):
        sheet = self.folder / "sheet.png"
        _sheet(sheet, size=(48, 48))
        project = Project()
        image = project.create_image(str(sheet), 48, 48)
        big = project.create_module("big", image.id, (0, 0, 40, 40), (0, 0))
        frame = project.create_frame("twice")
        for position, flip in (((0, 0), False), ((48, 0), True)):
            frame.fmodules.append(FModule(id=generate_id("fm"), ref_type="module", ref_id=big.id, position=position, flip_x=flip))
        budget = hb.BudgetCalculator().frame_budget(project, frame, None, hb.MEGA_DRIVE_H40)
        self.assertEqual((budget.tile_count, budget.unique_tiles), (50, 25))

    def test_blocks_with_the_same_pixels_share_tiles(self):
        sheet = self.folder / "tiles.png"
        image = Image.new("RGBA", (32, 8), (0, 0, 0, 0))
        for x in range(8):
            for y in range(8):
                image.putpixel((x, y), (200, 40 + 20 * y, 30 * x, 255))
                image.putpixel((16 + x, y), (200, 40 + 20 * y, 30 * x, 255))  # the same 8×8 again
        image.save(sheet)
        project = Project()
        asset = project.create_image(str(sheet), 32, 8)
        first = project.create_module("first", asset.id, (0, 0, 8, 8), (0, 0))
        again = project.create_module("again", asset.id, (16, 0, 8, 8), (0, 0))
        calc = hb.BudgetCalculator()
        parts = calc.module_parts(project, first.id, None, hb.MEGA_DRIVE_H40) + calc.module_parts(project, again.id, None, hb.MEGA_DRIVE_H40)
        self.assertEqual((sum(p.tiles for p in parts), hb.vram_tiles(parts)), (2, 1))

    def _exported_tiles(self, project, mappings):
        import export_megadrive as sg

        ctx = sg.MegaDriveBakeContext(project, mappings, self.folder / "out")
        ctx.bake()
        return len(ctx.tile_data) // 32

    def test_project_total_matches_the_export(self):
        import test_export_canvas_parity as parity

        sheet = self.folder / "sheet.png"
        parity._asymmetric_sheet(str(sheet))
        project = parity._build_project(str(sheet))
        # A second image in the second palette, a mapping to it and a scene that turns, mirrors and swaps.
        other = self.folder / "other.png"
        _sheet(other, size=(24, 16))
        asset = project.create_image(str(other), 24, 16)
        asset.palette = 1
        green = project.create_module("green", asset.id, (0, 0, 20, 12), (3, 2))
        wide = project.modules[0]
        project.mappings.append(ModuleMapping(id="map_green", name="Green", map={wide.id: green.id}))
        scene = project.create_timeline_scene("Turn")
        scene.duration_seconds = 0.5
        obj = scene.create_object("spinner", "frame", project.frames[1].id)
        obj.keyframes = [TimelineKeyframe(id="k0", time=0.0, x=10.0), TimelineKeyframe(id="k1", time=0.4, x=40.0, rotation_degrees=50.0, flip_x=True)]
        loose = scene.create_object("module", "module", green.id)
        loose.keyframes = [TimelineKeyframe(id="k2", time=0.0, y=20.0, rotation_degrees=90.0)]
        for mappings in ([None], [None] + project.mappings):
            self.assertEqual(hb.BudgetCalculator().export_tiles(project, mappings), self._exported_tiles(project, mappings))

    def test_testbed_totals_match_the_export(self):
        for path in ("examples/pop/PoP_WW.json", "examples/adventurer/adventurer.json"):
            project = Project.from_json(os.path.join(REPO_ROOT, path))
            mappings = [None] + project.mappings
            self.assertEqual(hb.BudgetCalculator().export_tiles(project, mappings), self._exported_tiles(project, mappings), path)

    def test_frames_stored_whole_match_the_export(self):
        """Some frames stored whole (each mapping's pictures, the Swordfight's guard in his own mapping), and every
        frame whole as the frames_streamed mode stores them: the budget's total is the exporter's."""
        import export_megadrive as sg
        import mixed_frames

        project = mixed_frames.pop_mixed()
        mappings = [None] + project.mappings
        calc = hb.BudgetCalculator()
        tiles = calc.export_tiles(project, mappings)
        self.assertEqual(tiles, self._exported_tiles(project, mappings))
        self.assertGreater(tiles, calc.export_tiles(Project.from_json(str(mixed_frames.POP)), mappings),
                           "the pictures cost tiles")
        nested = mixed_frames.nested_project(self.folder)
        self.assertEqual(calc.export_tiles(nested, [None]), self._exported_tiles(nested, [None]))
        for project in (nested, Project.from_json(str(mixed_frames.POP))):
            ctx = sg.MegaDriveBakeContext(project, [None], self.folder / "streamed", mode="frames_streamed")
            ctx.bake()
            self.assertEqual(calc.export_tiles(project, [None], whole_frames=True), len(ctx.tile_data) // 32)

    def test_the_palette_decides_which_blocks_match(self):
        project = Project()
        modules = []
        for name, colour in (("red", (250, 10, 10, 255)), ("blue", (10, 10, 250, 255))):
            path = self.folder / f"{name}.png"
            Image.new("RGBA", (8, 8), colour).save(path)
            asset = project.create_image(str(path), 8, 8)
            modules.append(project.create_module(name, asset.id, (0, 0, 8, 8), (0, 0)))
        calc = hb.BudgetCalculator()

        def total():
            return hb.vram_tiles([part for mod in modules for part in calc.module_parts(project, mod.id, None, hb.MEGA_DRIVE_H40)])

        self.assertEqual(total(), 2, "two colours of one palette: different indices")
        project.palettes.append(Palette("pal_2", "Second"))
        project.images[1].palette_id = "pal_2"
        self.assertEqual(total(), 1, "each the first colour of its own palette: the same tile")


class TestSnes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sheet = os.path.join(self.tmp.name, "sheet.png")
        _sheet(sheet, size=(96, 48))
        self.project = Project()
        image = self.project.create_image(sheet, 96, 48)
        self.big = self.project.create_module("big", image.id, (0, 0, 40, 40), (0, 0))
        self.tile = self.project.create_module("tile", image.id, (48, 0, 8, 8), (0, 0))
        self.square = self.project.create_module("square", image.id, (64, 0, 16, 16), (0, 0))
        self.calc = hb.BudgetCalculator()

    def tearDown(self):
        self.tmp.cleanup()

    def _sprites(self, module, profile, flip_x=False):
        a, b = _transform(flip_x=flip_x)
        return sorted((s.x, s.y, s.w, s.h) for p in self.calc.module_parts(self.project, module.id, None, profile, a, b) for s in p.sprites)

    def test_small_and_large_square_sprites(self):
        self.assertEqual(self._sprites(self.tile, hb.SNES_8_16), [(0, 0, 8, 8)])
        self.assertEqual(self._sprites(self.square, hb.SNES_8_16), [(0, 0, 16, 16)])
        self.assertEqual(self._sprites(self.square, hb.SNES_16_32), [(0, 0, 16, 16)])
        # 40×40 with 16/32: one large sprite, small ones along the right and bottom edges.
        self.assertEqual(self._sprites(self.big, hb.SNES_16_32), [
            (0, 0, 32, 32), (0, 32, 16, 16), (16, 32, 16, 16), (32, 0, 16, 16), (32, 16, 16, 16), (32, 32, 16, 16)])

    def test_flips_mirror_the_cells(self):
        plain = self._sprites(self.big, hb.SNES_16_32)
        mirrored = self._sprites(self.big, hb.SNES_16_32, flip_x=True)
        self.assertEqual(sorted((-x - w, y, w, h) for x, y, w, h in mirrored), plain)

    def test_line_limits(self):
        parts = [hb.HwPart(i * 8, 0, 8, 8, False, False, [hb.HwSprite(i * 8, 0, 8, 8)]) for i in range(33)]
        self.assertTrue(hb.Budget(hb.SNES_8_16, parts).over_budget(), "33 sprites on a line")
        self.assertFalse(hb.Budget(hb.SNES_8_16, parts[:32]).over_budget())
        wide = [hb.HwPart(0, 0, 32, 32, False, False, [hb.HwSprite(i * 32, 0, 32, 32)]) for i in range(9)]
        self.assertEqual(hb.Budget(hb.SNES_16_32, wide).worst_line(), (9, 288))
        self.assertTrue(hb.Budget(hb.SNES_16_32, wide).over_budget(), "288 px > 34 tiles on a line")

    def test_video_memory_like_the_snes_export(self):
        """The SNES export keeps every sprite tile in video memory (two tables of 512): the budget counts the squares
        it stores, for any pair of sizes, and so the project's total is the exporter's."""
        sys.path.insert(0, os.path.join(REPO_ROOT, "examples", "snes", "tools"))
        import export_snes
        from console_bake import ConsoleBake

        self.assertEqual((hb.SNES_16_32.vram_tiles, hb.SNES_16_32.vram_model), (512, "snes"))
        for path in ("examples/pop/PoP_WW.json", "examples/adventurer/adventurer.json"):
            project = Project.from_json(os.path.join(REPO_ROOT, path))
            mappings = [None] + project.mappings
            for key in ("snes_8_16", "snes_8_32", "snes_16_32"):
                with self.subTest(project=path, setup=key):
                    bake = export_snes.SNESBakeContext(project, mappings, key)
                    ConsoleBake.bake(bake)  # the parts' squares, before they are packed (16x16 / 32x32 do not fit)
                    self.assertEqual(hb.BudgetCalculator().export_tiles(project, mappings, hb.profile_by_key(key)),
                                     bake.tiles_used())

    def test_frames_stored_whole_like_the_snes_export(self):
        """Frames stored whole: their pictures' squares, for any pair of sizes; every frame whole as the frames_streamed
        mode stores them."""
        sys.path.insert(0, os.path.join(REPO_ROOT, "examples", "snes", "tools"))
        import export_snes
        import mixed_frames
        from console_bake import ConsoleBake

        projects = [mixed_frames.pop_mixed(), mixed_frames.nested_project(Path(self.tmp.name))]
        for project in projects:
            mappings = [None] + project.mappings
            for key in ("snes_8_16", "snes_8_32", "snes_16_32"):
                with self.subTest(project=project.frames[0].name, setup=key):
                    profile = hb.profile_by_key(key)
                    bake = export_snes.SNESBakeContext(project, mappings, key)
                    ConsoleBake.bake(bake)
                    self.assertEqual(hb.BudgetCalculator().export_tiles(project, mappings, profile), bake.tiles_used())
                    whole = export_snes.SNESBakeContext(project, [None], key, mode="frames_streamed")
                    ConsoleBake.bake(whole)
                    self.assertEqual(hb.BudgetCalculator().export_tiles(project, [None], profile, whole_frames=True),
                                     whole.tiles_used())



class TestNesGameBoyAndGba(unittest.TestCase):
    """The consoles without an exporter: one sprite size per game (NES, Game Boy), shapes (GBA)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sheet = os.path.join(self.tmp.name, "sheet.png")
        # A transparent hole of 16×8 px at (8, 16)-(24, 24) inside the "holey" module (the second one).
        _sheet(sheet, size=(176, 48), hole=(56, 16, 72, 24))
        self.project = Project()
        image = self.project.create_image(sheet, 176, 48)
        image.transparent_color = (255, 0, 255)
        self.big = self.project.create_module("big", image.id, (0, 0, 40, 40), (0, 0))
        self.holey = self.project.create_module("holey", image.id, (48, 0, 40, 40), (0, 0))
        self.wide = self.project.create_module("wide", image.id, (88, 0, 88, 8), (0, 0))
        self.calc = hb.BudgetCalculator()

    def tearDown(self):
        self.tmp.cleanup()

    def _parts(self, module, profile, flip_x=False, flip_y=False):
        a, b = _transform(flip_x=flip_x, flip_y=flip_y)
        return self.calc.module_parts(self.project, module.id, None, profile, a, b)

    def _sprites(self, module, profile, flip_x=False, flip_y=False):
        return sorted((s.x, s.y, s.w, s.h) for p in self._parts(module, profile, flip_x, flip_y) for s in p.sprites)

    def _covered(self, sprites):
        return {(x + dx, y + dy) for x, y, w, h in sprites for dy in range(0, h, 8) for dx in range(0, w, 8)}

    def test_profiles_from_the_database(self):
        self.assertEqual((hb.NES_8X8.sprites_per_screen, hb.NES_8X8.sprites_per_line, hb.NES_8X8.pixels_per_line), (64, 8, 0))
        self.assertEqual((hb.GAME_BOY_8X16.sprites_per_screen, hb.GAME_BOY_8X16.sprites_per_line), (40, 10))
        self.assertEqual((hb.GBA.sprites_per_screen, hb.GBA.pixels_per_line, hb.GBA.max_sprite_tiles), (128, 1210, 8))
        self.assertEqual((hb.NES_8X16.cut, hb.NES_8X16.shapes), (hb.CELLS, ((8, 16),)))
        self.assertEqual(hb.GBA.cut, hb.SHAPES)
        self.assertEqual(len(hb.GBA.shapes), 12)
        for profile in (hb.NES_8X8, hb.NES_8X16, hb.GBA, hb.GAME_BOY_8X8, hb.GAME_BOY_8X16):
            self.assertEqual(profile.vram_tiles, 0, f"{profile.key}: no export, so video memory is not counted")

    def test_one_size_takes_every_cell_with_a_pixel(self):
        self.assertEqual(len(self._sprites(self.big, hb.NES_8X8)), 25)
        holey = self._sprites(self.holey, hb.NES_8X8)
        self.assertEqual(len(holey), 23, "the two empty tiles need no sprite")
        self.assertNotIn((8, 16, 8, 8), holey)
        # 8×16: the 40 px high part is padded to 48 and cut into 5 × 3 cells.
        tall = self._sprites(self.big, hb.NES_8X16)
        self.assertEqual(len(tall), 15)
        self.assertTrue(all((w, h) == (8, 16) for _x, _y, w, h in tall))
        part = self._parts(self.big, hb.NES_8X16)[0]
        self.assertEqual((part.w, part.h), (40, 48))
        self.assertEqual(self._sprites(self.big, hb.GAME_BOY_8X16), tall, "the Game Boy cuts like the NES")

    def test_one_size_mirrors_its_cells(self):
        plain = self._sprites(self.big, hb.NES_8X16)
        flipped = self._sprites(self.big, hb.NES_8X16, flip_y=True)
        self.assertEqual(sorted((x, -y - h, w, h) for x, y, w, h in flipped), plain)

    def test_lines_count_sprites_only(self):
        parts = [hb.HwPart(i * 8, 0, 8, 8, False, False, [hb.HwSprite(i * 8, 0, 8, 8)]) for i in range(9)]
        self.assertTrue(hb.Budget(hb.NES_8X8, parts).over_budget(), "9 sprites on a line")
        self.assertFalse(hb.Budget(hb.NES_8X8, parts[:8]).over_budget())
        self.assertFalse(hb.Budget(hb.GAME_BOY_8X8, parts).over_budget(), "the Game Boy shows 10 a line")
        self.assertNotIn("px", hb.Budget(hb.NES_8X8, parts).summary())
        self.assertEqual(hb.Budget(hb.NES_8X8, parts).summary(), "9/64 sprites · busiest line 9/8 sprites")

    def test_gba_shapes_cover_each_pixel_once(self):
        for module in (self.big, self.holey, self.wide):
            for flip_x in (False, True):
                with self.subTest(module=module.name, flip_x=flip_x):
                    sprites = self._sprites(module, hb.GBA, flip_x=flip_x)
                    self.assertTrue(all((w, h) in hb.GBA.shapes for _x, _y, w, h in sprites))
                    tiles = [(x + dx, y + dy) for x, y, w, h in sprites for dy in range(0, h, 8) for dx in range(0, w, 8)]
                    self.assertEqual(len(tiles), len(set(tiles)), "no tile drawn twice")
        # 40×40 (5×5 tiles): four sprites holding 25 tiles beat one 64×64 sprite (64 tiles).
        big = self._sprites(self.big, hb.GBA)
        self.assertEqual((len(big), sum(w * h for _x, _y, w, h in big) // 64), (4, 25))
        self.assertEqual(self._covered(big), {(x, y) for x in range(0, 40, 8) for y in range(0, 40, 8)})
        # 88×8: cut at 64 px; the first cell takes two 32×8 sprites, the last 24 px a 32×8 sticking out past the end.
        self.assertEqual(self._sprites(self.wide, hb.GBA), [(0, 0, 32, 8), (32, 0, 32, 8), (64, 0, 32, 8)])

    def test_gba_line_cycles(self):
        wide = [hb.HwPart(0, 0, 64, 8, False, False, [hb.HwSprite(i * 64, 0, 64, 8)]) for i in range(19)]
        self.assertEqual(hb.Budget(hb.GBA, wide).worst_line(), (19, 1216))
        self.assertTrue(hb.Budget(hb.GBA, wide).over_budget(), "1216 drawing cycles > 1210")
        self.assertFalse(hb.Budget(hb.GBA, wide[:18]).over_budget())

    def test_cover_prefers_a_shape_to_many_small_ones(self):
        shapes = [(w // 8, h // 8) for w, h in hb.GBA.shapes]
        full = lambda w, h: [[True] * w for _ in range(h)]  # noqa: E731
        self.assertEqual(sprite_cut.cover_with_shapes(full(3, 3), shapes), [(0, 0, 4, 4)])
        self.assertEqual(sprite_cut.cover_with_shapes(full(7, 2), shapes), [(0, 0, 4, 2), (4, 0, 4, 2)])
        # A closed edge (another cell beyond it): nothing may stick out there.
        closed = sprite_cut.cover_with_shapes(full(7, 2), shapes, open_edges=(False, True))
        self.assertTrue(all(x + w <= 7 for x, _y, w, _h in closed))
        self.assertEqual(sprite_cut.cover_with_shapes([[False, False], [False, False]], shapes), [])


if __name__ == "__main__":
    unittest.main()
