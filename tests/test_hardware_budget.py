import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "examples", "sgdk", "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hardware_budget as hb  # noqa: E402
from models import AFrame, FModule, Project, RetroAnimatorExporter, generate_id  # noqa: E402


def _transform(flip_x=False, flip_y=False, rotation=0.0, offset=(0.0, 0.0)):
    a = RetroAnimatorExporter._mat_mul(RetroAnimatorExporter._rotation_matrix(rotation), RetroAnimatorExporter._flip_matrix(flip_x, flip_y))
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
        import export_sgdk_example as sg

        calc = hb.BudgetCalculator()
        cases = [(f, (0.0, 0.0), 0.0, False, False) for f in project.frames]
        for anim in project.animations:
            for af in anim.aframes:
                frame = project.get_frame(af.frame_id)
                if frame:
                    cases.append((frame, tuple(map(float, af.offset)), float(af.rotation_degrees), bool(af.flip_x), bool(af.flip_y)))
        with tempfile.TemporaryDirectory() as out:
            (Path(out) / "res" / "gen").mkdir(parents=True)
            ctx = sg.SGDKBakeContext(project, [None], Path(out))
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
        self.assertGreater(self._check(Project.from_json(os.path.join(REPO_ROOT, "examples", "sgdk", "PoP_WW.json"))), 500)


if __name__ == "__main__":
    unittest.main()
