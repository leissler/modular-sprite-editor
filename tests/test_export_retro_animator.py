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

    def test_export_bakes_flip_without_displacing_handle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet_path = os.path.join(tmpdir, "sheet_flip.png")
            img = Image.new("RGBA", (4, 1), (0, 0, 0, 0))
            img.putpixel((0, 0), (255, 0, 0, 255))
            img.putpixel((1, 0), (0, 255, 0, 255))
            img.putpixel((2, 0), (0, 0, 255, 255))
            img.save(sheet_path)

            project = Project(name="FlipBake")
            asset = project.create_image(sheet_path, 4, 1)
            mod = project.create_module("Asym", asset.id, (0, 0, 3, 1), (1, 0))

            frame = Frame(id=generate_id("frm"), name="Pose")
            frame.fmodules.append(
                FModule(
                    id=generate_id("fmod"),
                    ref_type="module",
                    ref_id=mod.id,
                    position=(10, 0),
                    flip_x=True,
                    flip_y=False,
                    rotation_degrees=0.0,
                )
            )
            project.frames.append(frame)

            anim = project.create_animation("idle")
            anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=1))

            out_json = os.path.join(tmpdir, "retro_export.json")
            project.to_retro_animator_json(out_json)

            with open(out_json, "r", encoding="utf-8") as f:
                exported = json.load(f)

            af = exported["Animations"]["idle"]["FrameData"][0]
            frame_payload = exported["Frames"][af["FrameID"]]
            sprite = frame_payload["Sprites"][0]

            # In-editor semantics: flipping does not shift top-left placement.
            self.assertEqual(sprite["HandleX"], 9)  # position.x - pivot.x
            self.assertEqual(sprite["HandleY"], 0)
            self.assertFalse(sprite["XFlip"])  # flip baked into part image

            rel_part = sprite["FramePath"].replace("\\", os.sep)
            abs_part = os.path.join(os.path.dirname(out_json), rel_part)
            with Image.open(abs_part).convert("RGBA") as part_img:
                self.assertEqual(part_img.size, (3, 1))
                self.assertEqual(part_img.getpixel((0, 0))[:3], (0, 0, 255))
                self.assertEqual(part_img.getpixel((1, 0))[:3], (0, 255, 0))
                self.assertEqual(part_img.getpixel((2, 0))[:3], (255, 0, 0))

    def test_export_aframe_flip_and_offset_reuses_base_parts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet_path = os.path.join(tmpdir, "sheet_aframe.png")
            img = Image.new("RGBA", (4, 1), (0, 0, 0, 0))
            img.putpixel((0, 0), (255, 0, 0, 255))
            img.putpixel((1, 0), (0, 255, 0, 255))
            img.putpixel((2, 0), (0, 0, 255, 255))
            img.save(sheet_path)

            project = Project(name="AFrameFlip")
            asset = project.create_image(sheet_path, 4, 1)
            mod = project.create_module("Asym", asset.id, (0, 0, 3, 1), (1, 0))

            frame = Frame(id=generate_id("frm"), name="Pose")
            frame.fmodules.append(
                FModule(
                    id=generate_id("fmod"),
                    ref_type="module",
                    ref_id=mod.id,
                    position=(10, 0),
                    flip_x=False,
                    flip_y=False,
                    rotation_degrees=0.0,
                )
            )
            project.frames.append(frame)

            anim = project.create_animation("idle")
            anim.fps = 10
            anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=1, offset=(0, 0), flip_x=False))
            anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=1, offset=(2, 0), flip_x=True))

            out_json = os.path.join(tmpdir, "retro_export.json")
            report = project.to_retro_animator_json(out_json)
            self.assertEqual(report["parts_written"], 1)

            with open(out_json, "r", encoding="utf-8") as f:
                exported = json.load(f)

            frame_data = exported["Animations"]["idle"]["FrameData"]
            self.assertEqual(len(frame_data), 2)
            self.assertNotEqual(frame_data[0]["FrameID"], frame_data[1]["FrameID"])

            base_frame = exported["Frames"][frame_data[0]["FrameID"]]
            var_frame = exported["Frames"][frame_data[1]["FrameID"]]
            self.assertEqual(len(base_frame["Sprites"]), 1)
            self.assertEqual(len(var_frame["Sprites"]), 1)

            base_sprite = base_frame["Sprites"][0]
            var_sprite = var_frame["Sprites"][0]

            # Simple variant should reuse same part file and only alter handle/flip metadata.
            self.assertEqual(base_sprite["FramePath"], var_sprite["FramePath"])
            self.assertEqual(base_sprite["HandleX"], 9)  # position.x - pivot.x
            self.assertEqual(base_sprite["HandleY"], 0)

            # RetroAnimator XFlip toggle rule: x = -x - width; then apply aframe offset (+2).
            self.assertEqual(var_sprite["HandleX"], -10)
            self.assertEqual(var_sprite["HandleY"], 0)
            self.assertTrue(var_sprite["XFlip"])

    def test_export_aframe_flip_xy_bakes_and_shifts_handle_by_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet_path = os.path.join(tmpdir, "sheet_aframe_xy.png")
            img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
            img.putpixel((0, 0), (255, 0, 0, 255))
            img.putpixel((1, 0), (0, 255, 0, 255))
            img.putpixel((0, 1), (0, 0, 255, 255))
            img.putpixel((1, 1), (255, 255, 0, 255))
            img.save(sheet_path)

            project = Project(name="AFrameFlipXY")
            asset = project.create_image(sheet_path, 2, 2)
            mod = project.create_module("Asym2x2", asset.id, (0, 0, 2, 2), (0, 0))

            frame = Frame(id=generate_id("frm"), name="Pose")
            frame.fmodules.append(
                FModule(
                    id=generate_id("fmod"),
                    ref_type="module",
                    ref_id=mod.id,
                    position=(1, 2),
                    flip_x=False,
                    flip_y=False,
                    rotation_degrees=0.0,
                )
            )
            project.frames.append(frame)

            anim = project.create_animation("idle")
            anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=1, offset=(0, 0), flip_x=False, flip_y=False))
            anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=1, offset=(0, 0), flip_x=True, flip_y=True))

            out_json = os.path.join(tmpdir, "retro_export.json")
            project.to_retro_animator_json(out_json)

            with open(out_json, "r", encoding="utf-8") as f:
                exported = json.load(f)

            frame_data = exported["Animations"]["idle"]["FrameData"]
            base_payload = exported["Frames"][frame_data[0]["FrameID"]]
            var_payload = exported["Frames"][frame_data[1]["FrameID"]]
            base_sprite = base_payload["Sprites"][0]
            var_sprite = var_payload["Sprites"][0]

            # Bounding-box transform under global X/Y flip around origin.
            self.assertEqual(var_sprite["HandleX"], -3)  # -1 - width(2)
            self.assertEqual(var_sprite["HandleY"], -4)  # -2 - height(2)
            self.assertFalse(var_sprite["XFlip"])  # transform baked into the part image
            self.assertNotEqual(base_sprite["FramePath"], var_sprite["FramePath"])

            rel_part = var_sprite["FramePath"].replace("\\", os.sep)
            abs_part = os.path.join(os.path.dirname(out_json), rel_part)
            with Image.open(abs_part).convert("RGBA") as part_img:
                self.assertEqual(part_img.size, (2, 2))
                self.assertEqual(part_img.getpixel((0, 0))[:3], (255, 255, 0))
                self.assertEqual(part_img.getpixel((1, 0))[:3], (0, 0, 255))
                self.assertEqual(part_img.getpixel((0, 1))[:3], (0, 255, 0))
                self.assertEqual(part_img.getpixel((1, 1))[:3], (255, 0, 0))

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

    def test_export_applies_transparent_color_key_to_parts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sheet_path = os.path.join(tmpdir, "sheet_keyed.png")
            img = Image.new("RGB", (4, 4), (255, 0, 255))  # keyed pink background
            img.putpixel((1, 1), (10, 20, 30))
            img.save(sheet_path)

            project = Project(name="Keyed")
            asset = project.create_image(sheet_path, 4, 4, transparent_color=(255, 0, 255))
            mod = project.create_module("Part", asset.id, (0, 0, 4, 4), (0, 0))

            frame = Frame(id=generate_id("frm"), name="Pose")
            frame.fmodules.append(
                FModule(
                    id=generate_id("fmod"),
                    ref_type="module",
                    ref_id=mod.id,
                    position=(0, 0),
                )
            )
            project.frames.append(frame)

            anim = project.create_animation("idle")
            anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=1))

            out_json = os.path.join(tmpdir, "retro_export.json")
            project.to_retro_animator_json(out_json)

            with open(out_json, "r", encoding="utf-8") as f:
                exported = json.load(f)

            af = exported["Animations"]["idle"]["FrameData"][0]
            frame_payload = exported["Frames"][af["FrameID"]]
            rel_part = frame_payload["Sprites"][0]["FramePath"].replace("\\", os.sep)
            abs_part = os.path.join(os.path.dirname(out_json), rel_part)
            with Image.open(abs_part).convert("RGBA") as part_img:
                self.assertEqual(part_img.getpixel((0, 0))[3], 0)  # keyed background is transparent
                self.assertEqual(part_img.getpixel((1, 1))[3], 255)  # actual painted pixel is opaque


if __name__ == "__main__":
    unittest.main()
