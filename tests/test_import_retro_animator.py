import json
import os
import tempfile
import unittest

from PIL import Image

from models import Project


class TestRetroAnimatorImport(unittest.TestCase):
    def test_import_retro_animator_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            parts_dir = os.path.join(tmpdir, "Cropped parts")
            os.makedirs(parts_dir, exist_ok=True)

            sword_path = os.path.join(parts_dir, "Sword.png")
            torso_path = os.path.join(parts_dir, "Torso.png")
            Image.new("RGBA", (3, 4), (255, 0, 0, 255)).save(sword_path)
            Image.new("RGBA", (5, 6), (0, 255, 0, 255)).save(torso_path)

            data = {
                "ProjectType": "RetroAnimator",
                "Frames": {
                    "pose-1": {
                        "Sprites": [
                            {
                                "FramePath": "Cropped Parts\\Sword.PNG",
                                "HandleX": -10,
                                "HandleY": -20,
                                "XFlip": True,
                            },
                            {
                                "FramePath": "cropped parts/torso.png",
                                "HandleX": 2,
                                "HandleY": -8,
                                "XFlip": False,
                            },
                        ],
                        "ColRects": {
                            "hurt": {
                                "X": -3,
                                "Y": -9,
                                "Width": 8,
                                "Height": 10,
                                "ColorR": 10,
                                "ColorG": 20,
                                "ColorB": 30,
                            }
                        },
                    },
                    "pose-2": {
                        "Sprites": [
                            {
                                "FramePath": "cropped parts/sword.png",
                                "HandleX": -11,
                                "HandleY": -20,
                                "XFlip": False,
                            }
                        ],
                        "ColRects": {
                            "block": {
                                "X": 4,
                                "Y": -7,
                                "Width": 2,
                                "Height": 6,
                                "ColorR": 40,
                                "ColorG": 50,
                                "ColorB": 60,
                            },
                            # RetroAnimator's "no box": a box of no size. Not imported (and no type for it).
                            "Default": {"X": 0, "Y": 0, "Width": 0, "Height": 0, "ColorR": 255, "ColorG": 0, "ColorB": 0},
                        },
                    },
                },
                "Animations": {
                    "idle": {
                        "FrameData": [
                            {"FrameID": "pose-1", "Duration": 5},
                            {"FrameID": "pose-2", "Duration": 7},
                        ]
                    }
                },
            }

            json_path = os.path.join(tmpdir, "hero.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f)

            project = Project.from_json(json_path)

            self.assertEqual(project.name, "hero")
            self.assertEqual(len(project.images), 2)
            self.assertEqual(len(project.modules), 2)
            self.assertEqual(len(project.frames), 2)
            self.assertEqual(len(project.animations), 1)

            module_dims = {(m.name.lower(), m.rect[2], m.rect[3]) for m in project.modules}
            self.assertIn(("sword", 3, 4), module_dims)
            self.assertIn(("torso", 5, 6), module_dims)

            pose1 = project.get_frame("pose-1")
            self.assertIsNotNone(pose1)
            self.assertEqual(len(pose1.fmodules), 2)
            self.assertEqual(pose1.fmodules[0].position, (-10, -20))
            self.assertTrue(pose1.fmodules[0].flip_x)
            self.assertEqual(pose1.fmodules[1].position, (2, -8))

            pose2 = project.get_frame("pose-2")
            self.assertIsNotNone(pose2)
            self.assertEqual(len(pose2.fmodules), 1)

            col_types = {ct.name for ct in project.collision_types}
            self.assertEqual(col_types, {"hurt", "block"})
            self.assertEqual(len(pose1.collision_rects), 1)
            self.assertEqual(pose1.collision_rects[0].rect, (-3, -9, 8, 10))
            self.assertEqual([cr.rect for cr in pose2.collision_rects], [(4, -7, 2, 6)])

            anim = project.animations[0]
            self.assertEqual(anim.name, "idle")
            self.assertEqual(anim.fps, 50)
            self.assertEqual([af.frame_id for af in anim.aframes], ["pose-1", "pose-2"])
            self.assertEqual([af.duration_frames for af in anim.aframes], [5, 7])

    def test_retro_animator_explicit_loader_rejects_non_retro_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "native.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"name": "native", "images": [], "modules": [], "frames": [], "animations": []}, f)

            with self.assertRaises(ValueError):
                Project.from_retro_animator_json(json_path)


if __name__ == "__main__":
    unittest.main()
