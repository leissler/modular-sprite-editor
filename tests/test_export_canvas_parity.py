"""RetroAnimator export must place every pixel where the editor canvas draws it.

Uses tools/check_export_parity.py, which renders frames with the editor's own canvas code.
Skipped when wxPython cannot start (e.g. headless CI without a display).
"""

import os
import sys
import tempfile
import unittest

from PIL import Image

from models import AFrame, FModule, Project, generate_id

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

try:
    import wx

    _APP = wx.App(False)
    _PARENT = wx.Frame(None)
    import check_export_parity
except Exception:  # pragma: no cover - environment without a usable wx
    wx = None


def _asymmetric_sheet(path: str) -> None:
    # Every pixel has a unique colour, so any mirror/rotation/placement error changes the result.
    img = Image.new("RGBA", (24, 12), (0, 0, 0, 0))
    for y in range(12):
        for x in range(24):
            if (x * 7 + y * 3) % 5 != 0:  # holes make the alpha shape asymmetric too
                img.putpixel((x, y), (10 + x * 9, 10 + y * 19, (x * y) % 255, 255))
    img.save(path)


def _part(ref_type: str, ref_id: str, pos, flip_x=False, flip_y=False, rot=0.0) -> FModule:
    return FModule(
        id=generate_id("fmod"), ref_type=ref_type, ref_id=ref_id, position=pos,
        flip_x=flip_x, flip_y=flip_y, rotation_degrees=rot,
    )


def _build_project(sheet_path: str) -> Project:
    project = Project(name="Parity")
    asset = project.create_image(sheet_path, 24, 12)
    wide = project.create_module("wide", asset.id, (0, 0, 7, 4), (1, 3))        # off-centre pivot
    tall = project.create_module("tall", asset.id, (8, 0, 3, 9), (2, 1))
    packed = project.create_module("packed", asset.id, (12, 0, 5, 8), (1, 2))   # stored rotated by the packer
    packed.rotated = True

    combos = project.create_frame("combos")
    x = 0
    for mod in (wide, tall, packed):
        for rot in (0.0, 90.0, 180.0, 270.0):
            for flip_x, flip_y in ((False, False), (True, False), (False, True), (True, True)):
                combos.fmodules.append(_part("module", mod.id, (x, (x * 3) % 17 - 8), flip_x, flip_y, rot))
                x += 11

    simple = project.create_frame("simple")
    simple.fmodules.append(_part("module", wide.id, (3, -2), flip_x=True))
    simple.fmodules.append(_part("module", tall.id, (-5, 4), flip_y=True, rot=90.0))

    nested = project.create_frame("nested")
    nested.fmodules.append(_part("frame", simple.id, (20, 5), flip_x=True, rot=90.0))
    nested.fmodules.append(_part("module", packed.id, (-7, 1), flip_x=True, flip_y=True))
    nested.fmodules.append(_part("frame", simple.id, (-30, -12), flip_y=True))

    deep = project.create_frame("deep")
    deep.fmodules.append(_part("frame", nested.id, (4, 9), flip_y=True, rot=270.0))
    deep.fmodules.append(_part("frame", nested.id, (-40, 2), flip_x=True, flip_y=True, rot=180.0))

    anim = project.create_animation("steps")
    for frame in (simple, nested, deep, combos):
        for rot in (0.0, 90.0, 180.0, 270.0):
            for flip_x, flip_y in ((False, False), (True, False), (False, True), (True, True)):
                anim.aframes.append(
                    AFrame(frame_id=frame.id, duration_frames=1, offset=(int(rot) // 30 - 4, 3),
                           flip_x=flip_x, flip_y=flip_y, rotation_degrees=rot)
                )
    return project


@unittest.skipIf(wx is None, "wxPython display not available")
class TestExportCanvasParity(unittest.TestCase):
    def test_synthetic_transform_combinations_match_canvas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet = os.path.join(tmpdir, "sheet.png")
            _asymmetric_sheet(sheet)
            project_path = os.path.join(tmpdir, "parity.json")
            _build_project(sheet).to_json(project_path)

            checked, bad, problems = check_export_parity.check_project(project_path, _PARENT)

        self.assertGreater(checked, 60)
        self.assertEqual(bad, 0, "\n".join(problems[:20]))

    def test_pop_testbed_matches_canvas(self):
        path = os.path.join(REPO_ROOT, "examples", "pop", "PoP_WW.json")
        checked, bad, problems = check_export_parity.check_project(path, _PARENT)
        self.assertGreater(checked, 500)
        self.assertEqual(bad, 0, "\n".join(problems[:20]))


if __name__ == "__main__":
    unittest.main()
