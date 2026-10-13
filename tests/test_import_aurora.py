"""AuroraGT .sprite import: modules, frames, animations with flips, names, empty boxes, line shapes."""

import os
import tempfile
import unittest

from models import AuroraSpriteParser, Module, Project

PRINCE = r"""
// D:\Work\POPSOT2\POP2\res_data\game\sprites\prince.sprite
/*SPRITE*/ {

    VERSION 0001
    IMAGE 0x0001 "modules_POP.bmp" TRANSP 0x00FF00FF // 0

    MODULES
    {
        MD	0x1000	MD_IMAGE	0	1	1	6	7	"0cap01"
        MD	0x1001	MD_IMAGE	0	84	1	7	7	"0cap06"
        MD	0x1009	MD_IMAGE	0	0	1	1	1
    }

    FRAME "test_frame"
    {
        0x2000
        RC	0	0	0	0
        FM	0x1000	-7	-16
        FM	0x1001	-1	-16 +FLIP_X
    }

    ANIM "test_anim"
    {
        0x3000
        AF	0x2000	8	-2	0
        AF	0x2000	12	4	0 +FLIP_X
    }
}
"""


class TestAuroraProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "prince.sprite")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(PRINCE)

    def tearDown(self):
        self.tmp.cleanup()

    def test_modules_frames_and_animations(self):
        project = Project.from_json(self.path)  # opening a .sprite file imports it
        self.assertEqual(len(project.images), 1)
        image = project.images[0]
        self.assertEqual((os.path.basename(image.file_path), image.transparent_color), ("modules_POP.bmp", (255, 0, 255)))
        modules = {m.id: m for m in project.modules}
        self.assertEqual((modules["0x1000"].name, modules["0x1000"].rect), ("0cap01", (1, 1, 6, 7)))
        self.assertEqual(modules["0x1009"].name, "Module 0x1009", "a module without a name gets one")
        self.assertTrue(all(m.image_id == image.id for m in project.modules))

        frame = project.get_frame("0x2000")
        self.assertEqual(frame.name, "test_frame")
        self.assertEqual([(p.ref_id, p.position, p.flip_x) for p in frame.fmodules],
                         [("0x1000", (-7, -16), False), ("0x1001", (-1, -16), True)])

        anim = project.animations[0]
        self.assertEqual(anim.name, "test_anim")
        self.assertEqual([(s.frame_id, s.duration_frames, s.offset, s.flip_x) for s in anim.aframes],
                         [("0x2000", 8, (-2, 0), False), ("0x2000", 12, (4, 0), True)])

    def test_every_import_is_its_own_project(self):
        first, second = Project.from_json(self.path), Project.from_json(self.path)
        self.assertIsNot(first.modules, second.modules)
        first.modules.append(Module("new", "new", "img", (0, 0, 0, 0), (0, 0)))
        self.assertEqual((len(first.modules), len(second.modules)), (4, 3))

SPRITE = r"""
/*SPRITE*/ {
    VERSION 0001
    IMAGE 0x0001 "sheet.png"
    MODULES
    {
        MD	0x1000	MD_IMAGE	0	0	0	8	8	"head"
    }
    FRAME "empty"
    {
        0x2000
        RC	0	0	0	0
        FM	0x1000	0	0
    }
    FRAME "boxed"
    {
        0x2001
        RC	-4	-8	4	0
        RC	3	3	3	9
        FM	0x1000	0	0
    }
}
"""


class TestAuroraCollisionRects(unittest.TestCase):
    def test_empty_rects_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = AuroraSpriteParser.parse(SPRITE, tmp)
        frames = {f.name: f for f in project.frames}
        self.assertEqual(frames["empty"].collision_rects, [])
        self.assertEqual([cr.rect for cr in frames["boxed"].collision_rects], [(-4, -8, 8, 8)])
        self.assertEqual(len(project.collision_types), 1)


LINES = r"""
/*SPRITE*/ {
    VERSION 0001
    MODULES
    {
        MD	0x1000	MD_LINE	0xFF0000	8	4	"down right"
        MD	0x1001	MD_LINE	0x00FF00	-6	3	"left"
    }
}
"""


class TestAuroraLines(unittest.TestCase):
    def test_lines_become_percentages_of_their_rect(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = AuroraSpriteParser.parse(LINES, tmp)
        lines = {m.name: m for m in project.modules}
        self.assertEqual(sorted(lines), ["down right", "left"], "a name with a space no longer drops the module")
        self.assertEqual((lines["down right"].rect, lines["down right"].params), ((0, 0, 8, 4), [0.0, 0.0, 100.0, 100.0]))
        self.assertEqual((lines["left"].rect, lines["left"].params), ((-6, 0, 6, 3), [100.0, 0.0, 0.0, 100.0]))
        self.assertEqual(lines["left"].color, (0, 255, 0))


if __name__ == "__main__":
    unittest.main()
