"""AuroraGT import: "RC 0 0 0 0" means a frame has no box and must not become a 0×0 hitbox."""

import os
import tempfile
import unittest

from models import AuroraSpriteParser

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


if __name__ == "__main__":
    unittest.main()
