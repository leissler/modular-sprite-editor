import unittest
import os
import shutil
from PIL import Image, ImageDraw
from models import Project, Frame, FModule
from optimization import run_auto_modularization

class TestAutoModularization(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_output"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        self.project = Project()

    def tearDown(self):
        # clean up
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_sheet_level_dedupe_and_reference_replacement(self):
        img_path = os.path.join(self.test_dir, "grid_sheet.png")
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Shared part (head) appears in both cells at different positions.
        draw.rectangle((2, 2, 7, 7), fill=(255, 255, 255, 255))
        draw.rectangle((38, 4, 43, 9), fill=(255, 255, 255, 255))

        # Unique parts for each cell.
        draw.rectangle((20, 10, 22, 23), fill=(255, 0, 0, 255))
        draw.rectangle((50, 12, 59, 14), fill=(0, 255, 0, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 64, 32)
        mod_a = self.project.create_module("CellA", asset.id, (0, 0, 32, 32), (16, 16))
        mod_b = self.project.create_module("CellB", asset.id, (32, 0, 32, 32), (16, 16))

        frame = Frame(
            id="frm_base",
            name="Base",
            fmodules=[
                FModule(id="fm_a", ref_type="module", ref_id=mod_a.id, position=(10, 10)),
                FModule(id="fm_b", ref_type="module", ref_id=mod_b.id, position=(50, 10)),
            ],
        )
        self.project.frames.append(frame)

        config = {
            "alpha_threshold": 0,
            "max_transparent_ratio": 0.5,
            "min_part_area": 1,
            "merge_gap": 1,
            "min_split_side": 2,
            "max_split_depth": 8,
            "deduplicate": True,
            "replace_in_frames": True,
            "delete_original_modules": True,
        }

        success, msg = run_auto_modularization(self.project, asset.id, config)
        self.assertTrue(success, msg)

        remaining_ids = {m.id for m in self.project.modules}
        self.assertNotIn(mod_a.id, remaining_ids)
        self.assertNotIn(mod_b.id, remaining_ids)

        auto_frames = [f for f in self.project.frames if f.name.startswith("AutoMod ")]
        self.assertEqual(len(auto_frames), 0)

        updated_base = self.project.get_frame("frm_base")
        self.assertIsNotNone(updated_base)
        self.assertTrue(all(fm.ref_type == "module" for fm in updated_base.fmodules))

        placement_count = len(updated_base.fmodules)
        unique_part_refs = {fm.ref_id for fm in updated_base.fmodules}
        self.assertLess(len(unique_part_refs), placement_count)
        self.assertGreater(placement_count, 2)

    def test_sparse_l_shape_splits_into_multiple_parts(self):
        img_path = os.path.join(self.test_dir, "l_shape.png")
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((1, 1, 12, 2), fill=(255, 255, 255, 255))
        draw.rectangle((1, 1, 2, 12), fill=(255, 255, 255, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 16, 16)
        self.project.create_module("LShape", asset.id, (0, 0, 16, 16), (8, 8))

        config = {
            "alpha_threshold": 0,
            "max_transparent_ratio": 0.35,
            "min_part_area": 1,
            "merge_gap": 0,
            "min_split_side": 2,
            "max_split_depth": 10,
            "deduplicate": False,
            "replace_in_frames": False,
            "delete_original_modules": False,
        }

        success, msg = run_auto_modularization(self.project, asset.id, config)
        self.assertTrue(success, msg)

        auto_parts = [m for m in self.project.modules if m.name.startswith("AutoPart ")]
        self.assertGreaterEqual(len(auto_parts), 2)

    def test_sparse_diagonal_does_not_leave_large_sparse_chunk(self):
        img_path = os.path.join(self.test_dir, "diag_sparse.png")
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for i in range(24):
            x = 2 + i
            y = 4 + (i // 2)
            if 0 <= x < 32 and 0 <= y < 32:
                draw.point((x, y), fill=(255, 255, 255, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 32, 32)
        self.project.create_module("Diag", asset.id, (0, 0, 32, 32), (16, 16))

        max_transparent_ratio = 0.1
        min_split_side = 2
        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "alpha_threshold": 0,
                "max_transparent_ratio": max_transparent_ratio,
                "min_part_area": 1,
                "merge_gap": 1,
                "min_split_side": min_split_side,
                "max_split_depth": 8,
                "pattern_mining": False,
                "deduplicate": False,
                "replace_in_frames": False,
                "delete_original_modules": False,
            },
        )
        self.assertTrue(success, msg)

        sheet = Image.open(os.path.abspath(img_path)).convert("RGBA")
        auto_parts = [m for m in self.project.modules if m.name.startswith("AutoPart ")]
        self.assertGreater(len(auto_parts), 0)

        # No large part should violate the threshold. Tiny strips may still do so
        # because min_split_side stops further recursion.
        for mod in auto_parts:
            x, y, w, h = mod.rect
            crop = sheet.crop((x, y, x + w, y + h))
            raw = crop.tobytes()
            opaque = sum(1 for idx in range(3, len(raw), 4) if raw[idx] > 0)
            transparent_ratio = 1.0 - (opaque / float(max(1, w * h)))
            if w > min_split_side and h > min_split_side:
                self.assertLessEqual(
                    transparent_ratio,
                    max_transparent_ratio + 1e-9,
                    f"{mod.name} remains a large sparse chunk: rect={mod.rect}",
                )

    def test_pattern_mining_reuses_large_patch_across_modules(self):
        img_path = os.path.join(self.test_dir, "pattern_sheet.png")
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Shared 10x10 patch appears in two cells at different offsets.
        draw.rectangle((2, 2, 11, 11), fill=(255, 200, 120, 255))
        draw.rectangle((38, 6, 47, 15), fill=(255, 200, 120, 255))

        # Unique details to avoid whole-cell equality.
        draw.rectangle((14, 10, 16, 12), fill=(255, 0, 0, 255))
        draw.rectangle((50, 18, 52, 20), fill=(0, 255, 0, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 64, 32)
        mod_a = self.project.create_module("A", asset.id, (0, 0, 32, 32), (16, 16))
        mod_b = self.project.create_module("B", asset.id, (32, 0, 32, 32), (16, 16))

        self.project.frames.append(
            Frame(
                id="frm_a",
                name="A",
                fmodules=[FModule(id="fm_a", ref_type="module", ref_id=mod_a.id, position=(0, 0))],
            )
        )
        self.project.frames.append(
            Frame(
                id="frm_b",
                name="B",
                fmodules=[FModule(id="fm_b", ref_type="module", ref_id=mod_b.id, position=(0, 0))],
            )
        )

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "replace_in_frames": True,
                "delete_original_modules": False,
                "pattern_mining": True,
                "min_pattern_occurrences": 2,
                "pattern_min_size": 10,
                "pattern_max_size": 10,
                "pattern_size_step": 1,
                "pattern_stride": 1,
                "min_pattern_area": 80,
                "min_pattern_opaque": 60,
            },
        )
        self.assertTrue(success, msg)

        frame_a = self.project.get_frame("frm_a")
        frame_b = self.project.get_frame("frm_b")
        self.assertIsNotNone(frame_a)
        self.assertIsNotNone(frame_b)

        ids_a = {fm.ref_id for fm in frame_a.fmodules if fm.ref_type == "module"}
        ids_b = {fm.ref_id for fm in frame_b.fmodules if fm.ref_type == "module"}
        shared_ids = ids_a.intersection(ids_b)
        self.assertTrue(shared_ids)

        shared_areas = [self.project.get_module(mid).rect[2] * self.project.get_module(mid).rect[3] for mid in shared_ids if self.project.get_module(mid)]
        self.assertTrue(shared_areas)
        self.assertGreaterEqual(max(shared_areas), 80)

    def test_pattern_mining_avoids_redundant_overlap_duplicates(self):
        img_path = os.path.join(self.test_dir, "pattern_overlap.png")
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((4, 4, 13, 13), fill=(200, 200, 255, 255))
        draw.rectangle((36, 4, 45, 13), fill=(200, 200, 255, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 64, 32)
        mod_a = self.project.create_module("A", asset.id, (0, 0, 32, 32), (16, 16))
        mod_b = self.project.create_module("B", asset.id, (32, 0, 32, 32), (16, 16))

        self.project.frames.append(
            Frame(
                id="frm_a2",
                name="A2",
                fmodules=[FModule(id="fm_a2", ref_type="module", ref_id=mod_a.id, position=(0, 0))],
            )
        )
        self.project.frames.append(
            Frame(
                id="frm_b2",
                name="B2",
                fmodules=[FModule(id="fm_b2", ref_type="module", ref_id=mod_b.id, position=(0, 0))],
            )
        )

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "replace_in_frames": True,
                "delete_original_modules": False,
                "pattern_mining": True,
                "min_pattern_occurrences": 2,
                "pattern_min_size": 6,
                "pattern_max_size": 12,
                "pattern_size_step": 1,
                "pattern_stride": 1,
                "min_pattern_area": 16,
                "min_pattern_opaque": 8,
                "min_pattern_new_coverage": 0.6,
                "placement_min_unique_ratio": 0.4,
            },
        )
        self.assertTrue(success, msg)

        fa = self.project.get_frame("frm_a2")
        fb = self.project.get_frame("frm_b2")
        self.assertIsNotNone(fa)
        self.assertIsNotNone(fb)
        self.assertLessEqual(len(fa.fmodules), 3)
        self.assertLessEqual(len(fb.fmodules), 3)

    def test_single_pixel_parts_are_kept_in_frames(self):
        img_path = os.path.join(self.test_dir, "single_pixel_parts.png")
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.point((8, 8), fill=(255, 255, 0, 255))
        draw.point((40, 12), fill=(255, 255, 0, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 64, 32)
        mod_a = self.project.create_module("A", asset.id, (0, 0, 32, 32), (16, 16))
        mod_b = self.project.create_module("B", asset.id, (32, 0, 32, 32), (16, 16))

        self.project.frames.append(
            Frame(
                id="frm_px_a",
                name="PxA",
                fmodules=[FModule(id="fm_px_a", ref_type="module", ref_id=mod_a.id, position=(0, 0))],
            )
        )
        self.project.frames.append(
            Frame(
                id="frm_px_b",
                name="PxB",
                fmodules=[FModule(id="fm_px_b", ref_type="module", ref_id=mod_b.id, position=(0, 0))],
            )
        )

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "replace_in_frames": True,
                "delete_original_modules": False,
                "pattern_mining": True,
                "min_pattern_occurrences": 2,
                "pattern_min_size": 1,
                "pattern_max_size": 2,
                "pattern_size_step": 1,
                "pattern_stride": 1,
                "min_pattern_area": 1,
                "min_pattern_opaque": 1,
            },
        )
        self.assertTrue(success, msg)

        frame_a = self.project.get_frame("frm_px_a")
        frame_b = self.project.get_frame("frm_px_b")
        self.assertIsNotNone(frame_a)
        self.assertIsNotNone(frame_b)

        self.assertGreaterEqual(len(frame_a.fmodules), 1)
        self.assertGreaterEqual(len(frame_b.fmodules), 1)

        def has_one_pixel_part(frame):
            for fm in frame.fmodules:
                if fm.ref_type != "module":
                    continue
                mod = self.project.get_module(fm.ref_id)
                if mod and mod.rect[2] == 1 and mod.rect[3] == 1:
                    return True
            return False

        self.assertTrue(has_one_pixel_part(frame_a))
        self.assertTrue(has_one_pixel_part(frame_b))

    def test_only_referenced_modules_are_rewritten(self):
        img_path = os.path.join(self.test_dir, "refs.png")
        img = Image.new("RGBA", (96, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((2, 2, 10, 10), fill=(255, 255, 255, 255))
        draw.rectangle((34, 2, 42, 10), fill=(255, 0, 0, 255))
        draw.rectangle((66, 2, 74, 10), fill=(0, 255, 0, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 96, 32)
        mod_a = self.project.create_module("A", asset.id, (0, 0, 32, 32), (16, 16))
        mod_b = self.project.create_module("B", asset.id, (32, 0, 32, 32), (16, 16))
        self.project.create_module("C_unused", asset.id, (64, 0, 32, 32), (16, 16))

        self.project.frames.append(
            Frame(
                id="frm_refs",
                name="Refs",
                fmodules=[
                    FModule(id="fm_a", ref_type="module", ref_id=mod_a.id, position=(0, 0)),
                    FModule(id="fm_b", ref_type="module", ref_id=mod_b.id, position=(40, 0)),
                ],
            )
        )

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "replace_in_frames": True,
                "delete_original_modules": False,
            },
        )
        self.assertTrue(success, msg)

        auto_frames = [f for f in self.project.frames if f.name.startswith("AutoMod ")]
        self.assertEqual(len(auto_frames), 0)

        frm = self.project.get_frame("frm_refs")
        self.assertIsNotNone(frm)
        self.assertGreaterEqual(len(frm.fmodules), 2)
        # Both original references should have been expanded to module-part references.
        self.assertTrue(all(fm.ref_type == "module" for fm in frm.fmodules))

    def test_pattern_mining_respects_max_transparent_ratio(self):
        img_path = os.path.join(self.test_dir, "diag_pattern.png")
        img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Same sparse diagonal appears in both cells to trigger pattern mining.
        for off in (0, 32):
            for i in range(20):
                x = off + 5 + i
                y = 5 + (i // 2)
                if x < off + 32 and y < 32:
                    draw.point((x, y), fill=(255, 255, 255, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 64, 32)
        mod_a = self.project.create_module("A", asset.id, (0, 0, 32, 32), (16, 16))
        mod_b = self.project.create_module("B", asset.id, (32, 0, 32, 32), (16, 16))

        self.project.frames.append(
            Frame(
                id="frm_diag_a",
                name="DiagA",
                fmodules=[FModule(id="fm_diag_a", ref_type="module", ref_id=mod_a.id, position=(0, 0))],
            )
        )
        self.project.frames.append(
            Frame(
                id="frm_diag_b",
                name="DiagB",
                fmodules=[FModule(id="fm_diag_b", ref_type="module", ref_id=mod_b.id, position=(0, 0))],
            )
        )

        max_transparent_ratio = 0.1
        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "max_transparent_ratio": max_transparent_ratio,
                "min_part_area": 1,
                "merge_gap": 1,
                "min_split_side": 2,
                "max_split_depth": 8,
                "deduplicate": True,
                "replace_in_frames": True,
                "delete_original_modules": False,
                "pattern_mining": True,
                "min_pattern_occurrences": 2,
                "min_pattern_active_occurrences": 2,
                "pattern_min_size": 6,
                "pattern_max_size": 20,
                "pattern_size_step": 2,
                "pattern_stride": 1,
                "min_pattern_area": 16,
                "min_pattern_opaque": 8,
            },
        )
        self.assertTrue(success, msg)

        sheet = Image.open(os.path.abspath(img_path)).convert("RGBA")
        auto_parts = [m for m in self.project.modules if m.name.startswith("AutoPart ")]
        self.assertGreater(len(auto_parts), 0)

        for mod in auto_parts:
            x, y, w, h = mod.rect
            crop = sheet.crop((x, y, x + w, y + h))
            raw = crop.tobytes()
            opaque = sum(1 for idx in range(3, len(raw), 4) if raw[idx] > 0)
            transparent_ratio = 1.0 - (opaque / float(max(1, w * h)))
            # Small terminal fragments can still be sparse when min_split_side prevents
            # further recursion; ensure larger parts still obey the threshold.
            if w > 2 and h > 2:
                self.assertLessEqual(
                    transparent_ratio,
                    max_transparent_ratio + 1e-9,
                    f"{mod.name} exceeds max transparent ratio with rect={mod.rect}",
                )

    def test_delete_without_replacement_is_blocked_when_frames_reference_modules(self):
        img_path = os.path.join(self.test_dir, "single.png")
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((2, 2, 6, 6), fill=(255, 255, 255, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 16, 16)
        mod = self.project.create_module("One", asset.id, (0, 0, 16, 16), (8, 8))
        self.project.frames.append(
            Frame(
                id="frm_ref",
                name="Ref",
                fmodules=[FModule(id="fm_ref", ref_type="module", ref_id=mod.id, position=(0, 0))],
            )
        )

        config = {
            "deduplicate": True,
            "replace_in_frames": False,
            "delete_original_modules": True,
        }
        success, msg = run_auto_modularization(self.project, asset.id, config)
        self.assertFalse(success)
        self.assertIn("Cannot delete originals", msg)

if __name__ == '__main__':
    unittest.main()
