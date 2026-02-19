import json
import os
import tempfile
import unittest

from PIL import Image

from models import AFrame, CollisionRect, CollisionType, FModule, Frame, ModuleMapping, Project, generate_id


class TestRetroAnimatorExport(unittest.TestCase):
    def _create_sheet(self, path: str) -> None:
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        for y in range(8):
            for x in range(8):
                img.putpixel((x, y), (x * 20 % 255, y * 20 % 255, 200, 255))
        img.save(path)

    def test_export_converts_timing_and_bakes_aframe_offset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet_path = os.path.join(tmpdir, "sheet.png")
            self._create_sheet(sheet_path)

            project = Project(name="Hero")
            asset = project.create_image(sheet_path, 8, 8)
            mod = project.create_module("Body", asset.id, (1, 2, 2, 3), (0, 0))

            frame = Frame(id=generate_id("frm"), name="IdleBase")
            frame.fmodules.append(
                FModule(
                    id=generate_id("fmod"),
                    ref_type="module",
                    ref_id=mod.id,
                    position=(5, -2),
                )
            )
            ctype = CollisionType(id=generate_id("ctype"), name="hurt", color=(12, 34, 56))
            project.collision_types.append(ctype)
            frame.collision_rects.append(
                CollisionRect(
                    id=generate_id("crect"),
                    type_id=ctype.id,
                    rect=(-1, -2, 3, 4),
                )
            )
            project.frames.append(frame)

            anim = project.create_animation("idle")
            anim.fps = 10
            anim.aframes.append(
                AFrame(
                    frame_id=frame.id,
                    duration_frames=2,
                    offset=(2, 1),
                    flip_x=False,
                    flip_y=False,
                    rotation_degrees=0.0,
                )
            )

            out_json = os.path.join(tmpdir, "retro_export.json")
            report = project.to_retro_animator_json(out_json)
            self.assertTrue(os.path.exists(out_json))
            self.assertGreaterEqual(report["frames_exported"], 1)

            with open(out_json, "r", encoding="utf-8") as f:
                exported = json.load(f)

            self.assertEqual(exported["ProjectType"], "RetroAnimator")
            self.assertIn("idle", exported["Animations"])
            self.assertEqual(len(exported["Animations"]["idle"]["FrameData"]), 1)

            # 2 frames at 10 FPS => 0.2s => 10 retro ticks (50 ticks/sec).
            af = exported["Animations"]["idle"]["FrameData"][0]
            self.assertEqual(af["Duration"], 10)
            exported_frame_name = af["FrameID"]
            self.assertIn(exported_frame_name, exported["Frames"])

            exported_frame = exported["Frames"][exported_frame_name]
            self.assertEqual(len(exported_frame["Sprites"]), 1)
            sprite = exported_frame["Sprites"][0]
            self.assertEqual(sprite["HandleX"], 7)  # original 5 + aframe offset x=2
            self.assertEqual(sprite["HandleY"], -1)  # original -2 + aframe offset y=1

            self.assertIn("hurt", exported_frame["ColRects"])
            col = exported_frame["ColRects"]["hurt"]
            self.assertEqual((col["ColorR"], col["ColorG"], col["ColorB"]), (12, 34, 56))

            rel_part = sprite["FramePath"].replace("\\", os.sep)
            abs_part = os.path.join(os.path.dirname(out_json), rel_part)
            self.assertTrue(os.path.exists(abs_part))
            with Image.open(abs_part) as part_img:
                self.assertEqual(part_img.size, (2, 3))

    def test_export_bakes_selected_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet_path = os.path.join(tmpdir, "sheet.png")
            self._create_sheet(sheet_path)

            project = Project(name="Mapped")
            asset = project.create_image(sheet_path, 8, 8)
            mod_a = project.create_module("A", asset.id, (0, 0, 2, 3), (0, 0))
            mod_b = project.create_module("B", asset.id, (0, 0, 4, 1), (0, 0))

            frame = Frame(id=generate_id("frm"), name="Pose")
            frame.fmodules.append(
                FModule(
                    id=generate_id("fmod"),
                    ref_type="module",
                    ref_id=mod_a.id,
                    position=(0, 0),
                )
            )
            project.frames.append(frame)

            anim = project.create_animation("idle")
            anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=1))

            mapping = ModuleMapping(id=generate_id("map"), name="UseB", map={mod_a.id: mod_b.id})
            project.mappings.append(mapping)
            project.active_mapping = mapping

            out_json = os.path.join(tmpdir, "retro_export.json")
            report = project.to_retro_animator_json(out_json, mapping=project.active_mapping)
            self.assertTrue(report["mapping_baked"])

            with open(out_json, "r", encoding="utf-8") as f:
                exported = json.load(f)

            af = exported["Animations"]["idle"]["FrameData"][0]
            frame_payload = exported["Frames"][af["FrameID"]]
            rel_part = frame_payload["Sprites"][0]["FramePath"].replace("\\", os.sep)
            abs_part = os.path.join(os.path.dirname(out_json), rel_part)
            with Image.open(abs_part) as part_img:
                # Must match mapped module B dimensions, not source module A.
                self.assertEqual(part_img.size, (4, 1))

    def test_export_keeps_frame_as_multiple_parts_not_single_baked_sprite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet_path = os.path.join(tmpdir, "sheet.png")
            self._create_sheet(sheet_path)

            project = Project(name="Multipart")
            asset = project.create_image(sheet_path, 8, 8)
            mod_head = project.create_module("Head", asset.id, (0, 0, 2, 2), (0, 0))
            mod_body = project.create_module("Body", asset.id, (2, 0, 2, 3), (0, 0))

            frame = Frame(id=generate_id("frm"), name="Pose")
            frame.fmodules.append(FModule(id=generate_id("fmod"), ref_type="module", ref_id=mod_head.id, position=(1, 1)))
            frame.fmodules.append(FModule(id=generate_id("fmod"), ref_type="module", ref_id=mod_body.id, position=(1, 3)))
            project.frames.append(frame)

            anim = project.create_animation("idle")
            anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=1))

            out_json = os.path.join(tmpdir, "retro_export.json")
            report = project.to_retro_animator_json(out_json)

            with open(out_json, "r", encoding="utf-8") as f:
                exported = json.load(f)

            af = exported["Animations"]["idle"]["FrameData"][0]
            frame_payload = exported["Frames"][af["FrameID"]]
            sprites = frame_payload["Sprites"]

            # Critical behavior: keep separate parts, do NOT collapse into one frame-wide sprite.
            self.assertEqual(len(sprites), 2)
            self.assertEqual(report["parts_written"], 2)


if __name__ == "__main__":
    unittest.main()
