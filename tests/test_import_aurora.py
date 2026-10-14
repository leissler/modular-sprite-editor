"""AuroraGT .sprite import: modules, frames, animations with flips, names, empty boxes, line shapes, and notes on
whatever it leaves out or can't find."""

import os
import tempfile
import unittest

from PIL import Image

from importers import aurora
from models import Module, Project

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
            project = aurora.parse(SPRITE, tmp)
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
            project = aurora.parse(LINES, tmp)
        lines = {m.name: m for m in project.modules}
        self.assertEqual(sorted(lines), ["down right", "left"], "a name with a space no longer drops the module")
        self.assertEqual((lines["down right"].rect, lines["down right"].params), ((0, 0, 8, 4), [0.0, 0.0, 100.0, 100.0]))
        self.assertEqual((lines["left"].rect, lines["left"].params), ((-6, 0, 6, 3), [100.0, 0.0, 0.0, 100.0]))
        self.assertEqual(lines["left"].color, (0, 255, 0))


BROKEN = r"""
/*SPRITE*/ {
    VERSION 0001
    IMAGE 0x0001 "sheet.png"
    IMAGE 0x0002 "gone.png"
    MODULES
    {
        MD	0x1000	MD_IMAGE	0	0	0	8	8	"head"
        MD	0x1001	MD_IMAGE	0	0	x	8	8	"bad number"
        MD	0x1002	MD_SPLINE	0xFF0000	3	3	"unknown kind"
        MD	0x1000	MD_IMAGE	0	8	0	8	8	"same id"
        MD	0x1003	MD_IMAGE	7	0	0	8	8	"no such image"
        WHATEVER	1	2
    }
    FRAME "pose"
    {
        0x2000
        FM	0x1000	0	0
        FM	0x9999	0	0
        FM	0x1000	zero	0
        RC	1	2	three	4
    }
    ANIM "walk"
    {
        0x3000
        AF	0x2000	4	0	0
        AF	0x2999	4	0	0
        AF	0x2000	soon	0	0
    }
    MAPPING "skin"
    {
        0x4000
        MD_MAP	0x1000	0x7777
        MD_MAP	0x1000
    }
}
"""


def line_of(text: str, exact: bool = False) -> int:
    """The number of the first line of BROKEN that contains ``text`` (or, ``exact``, reads just that)."""
    return next(n for n, line in enumerate(BROKEN.splitlines(), 1) if (line.strip() == text if exact else text in line))


class TestAuroraNotes(unittest.TestCase):
    def test_a_clean_file_imports_without_notes_and_with_image_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            Image.new("RGB", (90, 20), (255, 0, 255)).save(os.path.join(tmp, "modules_POP.bmp"))
            project = aurora.parse(PRINCE, tmp)
        self.assertEqual(project.load_notes, [])
        self.assertEqual((project.images[0].width, project.images[0].height), (90, 20), "the real size, not 0 x 0")

    def test_what_it_leaves_out_is_named_once_per_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            Image.new("RGB", (16, 8)).save(os.path.join(tmp, "sheet.png"))
            project = aurora.parse(BROKEN, tmp)
        notes = "\n".join(project.load_notes)
        lone_map = line_of("MD_MAP\t0x1000", exact=True)
        expected = {
            "Images not found next to the file": "gone.png",
            "Module lines that couldn't be read, left out": f"line {line_of('bad number')} (MD",
            "Modules of a kind the editor doesn't know, left out": "0x1002 (MD_SPLINE)",
            "Modules defined twice, the second one left out": "0x1000",
            "Modules on an image the file doesn't list (they use the first image)": "0x1003",
            "Lines the importer doesn't know, ignored": f"line {line_of('WHATEVER')} (WHATEVER",
            "Frame parts that couldn't be read, left out": f"line {line_of('zero')} (FM",
            "Hitboxes that couldn't be read, left out": f"line {line_of('three')} (RC",
            "Animation steps that couldn't be read, left out": f"line {line_of('soon')} (AF",
            "Mapping lines that couldn't be read, left out": f"line {lone_map} (MD_MAP",
            "Frame parts using a module the file doesn't define": "0x9999 in pose",
            "Animation steps using a frame the file doesn't define": "0x2999 in walk step 2",
            "Mapping entries naming a module the file doesn't define": "0x7777 in skin",
        }
        for message, example in expected.items():
            line = next((l for l in project.load_notes if l.startswith(message)), None)
            self.assertIsNotNone(line, f"{message!r} missing in:\n{notes}")
            self.assertIn(example, line)
        self.assertEqual(len(project.load_notes), len(expected), notes)
        # What could be read is imported as before; what couldn't is not.
        self.assertEqual(sorted(m.id for m in project.modules), ["0x1000", "0x1003"])
        self.assertEqual(project.get_module("0x1000").name, "head", "the first definition wins")
        self.assertEqual([fm.ref_id for fm in project.frames[0].fmodules], ["0x1000", "0x9999"])
        self.assertEqual([af.frame_id for af in project.animations[0].aframes], ["0x2000", "0x2999"])

    def test_opening_a_sprite_marks_the_project_imported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prince.sprite")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(PRINCE)
            self.assertEqual(Project.from_json(path).imported_from, "AuroraGT sprite")


if __name__ == "__main__":
    unittest.main()
