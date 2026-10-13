"""Tools ▸ Optimize Sprite Sheet (optimization.optimize_modules): the repacked sheet draws every frame the same."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import compositor  # noqa: E402
from models import FModule, Project, generate_id  # noqa: E402
from optimization import optimize_modules  # noqa: E402

IDENTITY = ((1.0, 0.0), (0.0, 1.0))
CONFIG = {"padding": 2, "border_padding": 2, "max_w": 2048, "max_h": 2048}


def rendered(project):
    """Every frame with every mapping, as the renderers draw it: {(frame, mapping): (size, pixels, handle)}."""
    shown = {}
    for mapping in [None] + list(project.mappings):
        images, modules = {}, {}
        for frame in project.frames:
            image, hx, hy, _boxes = compositor.render_frame(project, frame, mapping, IDENTITY, (0.0, 0.0), images, modules)
            shown[(frame.id, mapping.id if mapping else None)] = (image.size, image.tobytes(), hx, hy) if image else None
    return shown


class TestOptimizeSheet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pop_repacks_and_draws_every_frame_the_same(self):
        project = Project.from_json(str(ROOT / "examples" / "sgdk" / "PoP_WW.json"))
        before = rendered(project)
        old = project.images[0]
        for rotate in (False, True, True):  # the last run repacks modules that are stored turned
            ok, message = optimize_modules(project, [m.id for m in project.modules], dict(CONFIG, allow_rotation=rotate),
                                           str(self.folder), "pop")
            self.assertTrue(ok, message)
            self.assertEqual(rendered(project), before, f"rotation {rotate}")
        self.assertEqual(len(project.images), 1, "the old sheets left the project")
        sheet = project.images[0]
        self.assertLess(sheet.width * sheet.height, old.width * old.height)
        self.assertTrue(any(m.rotated for m in project.modules))
        self.assertTrue(os.path.exists(str(ROOT / "examples" / "sgdk" / "modules_POP.bmp")), "source files stay")

    def _sheet(self, name, colour, palette=0):
        path = self.folder / name
        Image.new("RGBA", (16, 8), colour).save(path)
        asset = self.project.create_image(str(path), 16, 8)
        asset.palette = palette
        return asset

    def test_only_what_was_repacked_moves(self):
        self.project = project = Project()
        red, blue = self._sheet("red.png", (250, 20, 20, 255)), self._sheet("blue.png", (20, 20, 250, 255))
        loose = self._sheet("reference.png", (90, 90, 90, 255))  # an image without modules
        a = project.create_module("a", red.id, (0, 0, 8, 8), (4, 8))
        b = project.create_module("b", blue.id, (8, 0, 8, 8), (0, 0))
        hidden = project.create_module("hidden", red.id, (0, 0, 0, 0), (0, 0))
        gone = project.create_module("gone", "img_missing", (0, 0, 8, 8), (0, 0))
        frame = project.create_frame("pose")
        for mod, x in ((a, 0), (b, 10)):
            frame.fmodules.append(FModule(id=generate_id("fm"), ref_type="module", ref_id=mod.id, position=(x, 0)))
        before = rendered(project)

        blue.palette = 1
        ok, message = optimize_modules(project, [m.id for m in project.modules], CONFIG, str(self.folder), "both")
        self.assertFalse(ok)
        self.assertIn("different palettes", message)
        blue.palette = 0
        red.palette = blue.palette = 2

        ok, message = optimize_modules(project, [m.id for m in project.modules], CONFIG, str(self.folder), "both")
        self.assertTrue(ok, message)
        self.assertEqual(rendered(project), before)
        sheet = project.get_image(a.image_id)
        self.assertEqual((b.image_id, hidden.image_id, sheet.palette), (sheet.id, sheet.id, 2))
        self.assertEqual((gone.image_id, gone.rect), ("img_missing", (0, 0, 8, 8)), "a module of a missing image stays")
        self.assertEqual({i.id for i in project.images}, {sheet.id, loose.id}, "only the emptied sheets leave")


if __name__ == "__main__":
    unittest.main()
