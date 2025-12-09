
import os
import unittest
from models import Project, Module, Frame, Animation

SAMPLE_SPRITE = r"""
// D:\Work\POPSOT2\POP2\res_data\game\sprites\prince.sprite
/////////////////////////////////////////////////////////////////////////////////
/*SPRITE*/ {

    VERSION 0001
    IMAGE 0x0001 "modules_POP.bmp" TRANSP 0x00FF00FF // 0

    MODULES
    {
        MD	0x1000	MD_IMAGE	0	1	1	6	7	"0cap01"
        MD	0x1001	MD_IMAGE	0	84	1	7	7	"0cap06"
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
        AF	0x2000	8	0	0
        AF	0x2000	12	0	0 +FLIP_X
    }
}
"""

class TestAuroraImport(unittest.TestCase):
    def test_import(self):
        filename = "test.sprite"
        with open(filename, "w") as f:
            f.write(SAMPLE_SPRITE)

        try:
            project = Project.from_json(filename)

            # verify modules
            self.assertEqual(len(project.modules), 2)
            m0 = project.get_module("0x1000")
            self.assertIsNotNone(m0)
            self.assertEqual(m0.name, "0cap01")
            self.assertEqual(m0.rect, (1, 1, 6, 7))
            self.assertEqual(m0.image_id, "modules_POP.bmp")

            # verify frame
            self.assertEqual(len(project.frames), 1)
            f0 = project.frames[0]
            self.assertEqual(f0.name, "test_frame")
            self.assertEqual(len(f0.fmodules), 2)
            
            fm0 = f0.fmodules[0]
            self.assertEqual(fm0.ref_id, "0x1000")
            self.assertEqual(fm0.position, (-7, -16))
            self.assertFalse(fm0.flip_x)

            fm1 = f0.fmodules[1]
            self.assertEqual(fm1.ref_id, "0x1001")
            self.assertTrue(fm1.flip_x)

            # verify anim
            self.assertEqual(len(project.animations), 1)
            a0 = project.animations[0]
            self.assertEqual(a0.name, "test_anim")
            self.assertEqual(len(a0.aframes), 2)
            
            af0 = a0.aframes[0]
            self.assertEqual(af0.frame_id, "0x2000")
            self.assertEqual(af0.duration_ms, 8)
            
            af1 = a0.aframes[1]
            self.assertTrue(af1.flip_x)

        finally:
            if os.path.exists(filename):
                os.remove(filename)

if __name__ == "__main__":
    unittest.main()
