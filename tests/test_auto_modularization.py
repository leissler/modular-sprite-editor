import unittest
import os
import shutil
import math
from PIL import Image, ImageDraw, ImageOps, ImageChops
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

    def _render_frame_canvas_like(
        self,
        project: Project,
        frame_id: str,
        canvas_size=(256, 256),
        origin=(128, 128),
    ) -> Image.Image:
        frame = project.get_frame(frame_id)
        self.assertIsNotNone(frame)
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

        image_cache = {}
        for fm in frame.fmodules:  # type: ignore[union-attr]
            if fm.ref_type != "module":
                continue
            mod = project.get_module(fm.ref_id)
            if not mod:
                continue
            asset = project.get_image(mod.image_id)
            if not asset or not os.path.exists(asset.file_path):
                continue

            if asset.id not in image_cache:
                image_cache[asset.id] = Image.open(asset.file_path).convert("RGBA")
            src_sheet = image_cache[asset.id]

            rx, ry, rw, rh = mod.rect
            patch = src_sheet.crop((rx, ry, rx + rw, ry + rh))

            if fm.flip_x:
                patch = ImageOps.mirror(patch)
            if fm.flip_y:
                patch = ImageOps.flip(patch)

            rot = int(round(float(fm.rotation_degrees))) % 360
            if rot == 90:
                patch = patch.transpose(Image.Transpose.ROTATE_270)  # clockwise
            elif rot == 180:
                patch = patch.transpose(Image.Transpose.ROTATE_180)
            elif rot == 270:
                patch = patch.transpose(Image.Transpose.ROTATE_90)

            piv_x, piv_y = mod.pivot
            w, h = mod.rect[2], mod.rect[3]
            corners = [
                (0 - piv_x, 0 - piv_y),
                (w - piv_x, 0 - piv_y),
                (0 - piv_x, h - piv_y),
                (w - piv_x, h - piv_y),
            ]
            rad = math.radians(float(fm.rotation_degrees))
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            points = []
            for cx, cy in corners:
                px = cx * cos_a - cy * sin_a + fm.position[0]
                py = cx * sin_a + cy * cos_a + fm.position[1]
                points.append((px, py))

            x0 = min(p[0] for p in points)
            y0 = min(p[1] for p in points)
            x1 = max(p[0] for p in points)
            y1 = max(p[1] for p in points)
            target_w = max(1, int(round(abs(x1 - x0))))
            target_h = max(1, int(round(abs(y1 - y0))))
            if patch.size != (target_w, target_h):
                patch = patch.resize((target_w, target_h), Image.Resampling.NEAREST)

            dst_x = int(round(origin[0] + x0))
            dst_y = int(round(origin[1] + y0))
            canvas.alpha_composite(patch, (dst_x, dst_y))

        return canvas

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

    def test_tile_mode_snaps_parts_to_tile_grid(self):
        img_path = os.path.join(self.test_dir, "tile_snap.png")
        img = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, 7, 7), fill=(255, 255, 255, 255))
        draw.rectangle((8, 0, 15, 7), fill=(255, 0, 0, 255))
        draw.rectangle((0, 8, 7, 15), fill=(0, 255, 0, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 32, 16)
        self.project.create_module("TileAligned", asset.id, (0, 0, 16, 16), (8, 8))

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "modularization_mode": "tile_constrained",
                "platform_profile": "generic_8x8",
                "tile_width": 8,
                "tile_height": 8,
                "meta_tile_mode": "off",
                "replace_in_frames": False,
                "delete_original_modules": False,
            },
        )
        self.assertTrue(success, msg)

        auto_parts = [m for m in self.project.modules if m.name.startswith("AutoPart ")]
        self.assertGreater(len(auto_parts), 0)
        for mod in auto_parts:
            self.assertEqual(mod.rect[0] % 8, 0)
            self.assertEqual(mod.rect[1] % 8, 0)
            self.assertEqual(mod.rect[2] % 8, 0)
            self.assertEqual(mod.rect[3] % 8, 0)

    def test_tile_mode_force_meta_tile_reports_meta_usage(self):
        img_path = os.path.join(self.test_dir, "meta_force.png")
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, 7, 7), fill=(255, 255, 255, 255))
        draw.rectangle((8, 0, 15, 7), fill=(255, 255, 255, 255))
        draw.rectangle((0, 8, 7, 15), fill=(255, 255, 255, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 16, 16)
        self.project.create_module("MetaCandidate", asset.id, (0, 0, 16, 16), (8, 8))

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "modularization_mode": "tile_constrained",
                "platform_profile": "generic_8x8",
                "meta_tile_mode": "force",
                "meta_tile_sizes": [(16, 16)],
                "replace_in_frames": False,
                "delete_original_modules": False,
            },
        )
        self.assertTrue(success, msg)
        self.assertIn("Selected meta-tiles", msg)

        auto_parts = [m for m in self.project.modules if m.name.startswith("AutoPart ")]
        self.assertTrue(any(m.rect[2] == 16 and m.rect[3] == 16 for m in auto_parts))

    def test_tile_profile_reports_palette_constraint_violations(self):
        img_path = os.path.join(self.test_dir, "palette_limits.png")
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        pix = img.load()
        c = 0
        for y in range(8):
            for x in range(8):
                pix[x, y] = ((c * 17) % 256, (c * 31) % 256, (c * 47) % 256, 255)
                c += 1
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 8, 8)
        self.project.create_module("TooManyColors", asset.id, (0, 0, 8, 8), (4, 4))

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "modularization_mode": "tile_constrained",
                "platform_profile": "mega_drive",
                "tile_enforce_palette_constraints": True,
                "replace_in_frames": False,
                "delete_original_modules": False,
                "deduplicate": False,
            },
        )
        self.assertTrue(success, msg)
        self.assertIn("per-tile palette limits", msg)

    def test_mega_drive_tile_mode_handles_unaligned_source_module(self):
        img_path = os.path.join(self.test_dir, "unaligned_source.png")
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((5, 6, 18, 19), fill=(255, 220, 60, 255))
        draw.rectangle((10, 10, 11, 11), fill=(0, 0, 0, 0))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 32, 32)
        self.project.create_module("Unaligned", asset.id, (5, 6, 14, 14), (7, 7))

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "modularization_mode": "tile_constrained",
                "platform_profile": "mega_drive",
                "replace_in_frames": False,
                "delete_original_modules": False,
                "deduplicate": True,
            },
        )
        self.assertTrue(success, msg)

        auto_parts = [m for m in self.project.modules if m.name.startswith("AutoPart ")]
        self.assertGreater(len(auto_parts), 0)
        self.assertTrue(all(m.rect[2] % 8 == 0 and m.rect[3] % 8 == 0 for m in auto_parts))
        self.assertIn("padded tile snapping", msg)

    def test_tile_mode_transparency_threshold_changes_grouping(self):
        img_path = os.path.join(self.test_dir, "tile_threshold_effect.png")
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Four sparse islands: one inside each 8x8 tile.
        draw.rectangle((2, 2, 5, 5), fill=(255, 255, 255, 255))
        draw.rectangle((10, 2, 13, 5), fill=(255, 255, 255, 255))
        draw.rectangle((2, 10, 5, 13), fill=(255, 255, 255, 255))
        draw.rectangle((10, 10, 13, 13), fill=(255, 255, 255, 255))
        img.save(img_path)

        low_proj = Project()
        low_asset = low_proj.create_image(os.path.abspath(img_path), 16, 16)
        low_proj.create_module("SparseCell", low_asset.id, (0, 0, 16, 16), (8, 8))
        low_ok, low_msg = run_auto_modularization(
            low_proj,
            low_asset.id,
            {
                "modularization_mode": "tile_constrained",
                "platform_profile": "generic_8x8",
                "meta_tile_mode": "off",
                "max_transparent_ratio": 0.5,
                "deduplicate": False,
                "replace_in_frames": False,
                "delete_original_modules": False,
            },
        )
        self.assertTrue(low_ok, low_msg)
        low_parts = [m for m in low_proj.modules if m.name.startswith("AutoPart ")]
        self.assertGreater(len(low_parts), 0)

        high_proj = Project()
        high_asset = high_proj.create_image(os.path.abspath(img_path), 16, 16)
        high_proj.create_module("SparseCell", high_asset.id, (0, 0, 16, 16), (8, 8))
        high_ok, high_msg = run_auto_modularization(
            high_proj,
            high_asset.id,
            {
                "modularization_mode": "tile_constrained",
                "platform_profile": "generic_8x8",
                "meta_tile_mode": "off",
                "max_transparent_ratio": 0.9,
                "deduplicate": False,
                "replace_in_frames": False,
                "delete_original_modules": False,
            },
        )
        self.assertTrue(high_ok, high_msg)
        high_parts = [m for m in high_proj.modules if m.name.startswith("AutoPart ")]
        self.assertGreater(len(high_parts), 0)

        self.assertGreater(len(low_parts), len(high_parts))

    def test_freeform_rewrite_preserves_canvas_pixels_for_flipped_offcenter_pivot(self):
        img_path = os.path.join(self.test_dir, "flip_offcenter_freeform.png")
        img = Image.new("RGBA", (16, 8), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, 3, 7), fill=(255, 255, 255, 255))
        draw.rectangle((12, 0, 15, 7), fill=(255, 0, 0, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 16, 8)
        mod = self.project.create_module("Base", asset.id, (0, 0, 16, 8), (1, 4))
        self.project.frames.append(
            Frame(
                id="frm_flip_free",
                name="FlipFree",
                fmodules=[
                    FModule(
                        id="fm_src_free",
                        ref_type="module",
                        ref_id=mod.id,
                        position=(20, 12),
                        flip_x=True,
                        flip_y=False,
                        rotation_degrees=0.0,
                    )
                ],
            )
        )
        before = self._render_frame_canvas_like(self.project, "frm_flip_free")

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "replace_in_frames": True,
                "delete_original_modules": False,
                "pattern_mining": False,
                "deduplicate": False,
                "max_transparent_ratio": 0.2,
                "merge_gap": 0,
                "min_split_side": 2,
                "max_split_depth": 8,
            },
        )
        self.assertTrue(success, msg)

        after = self._render_frame_canvas_like(self.project, "frm_flip_free")
        self.assertIsNone(ImageChops.difference(before, after).getbbox())

    def test_tile_rewrite_preserves_canvas_pixels_for_flipped_offcenter_pivot(self):
        img_path = os.path.join(self.test_dir, "flip_offcenter_tile.png")
        img = Image.new("RGBA", (16, 8), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, 3, 7), fill=(255, 255, 255, 255))
        draw.rectangle((12, 0, 15, 7), fill=(255, 0, 0, 255))
        img.save(img_path)

        asset = self.project.create_image(os.path.abspath(img_path), 16, 8)
        mod = self.project.create_module("Base", asset.id, (0, 0, 16, 8), (1, 4))
        self.project.frames.append(
            Frame(
                id="frm_flip_tile",
                name="FlipTile",
                fmodules=[
                    FModule(
                        id="fm_src_tile",
                        ref_type="module",
                        ref_id=mod.id,
                        position=(20, 12),
                        flip_x=True,
                        flip_y=False,
                        rotation_degrees=0.0,
                    )
                ],
            )
        )
        before = self._render_frame_canvas_like(self.project, "frm_flip_tile")

        success, msg = run_auto_modularization(
            self.project,
            asset.id,
            {
                "modularization_mode": "tile_constrained",
                "platform_profile": "mega_drive",
                "replace_in_frames": True,
                "delete_original_modules": False,
                "deduplicate": False,
                "meta_tile_mode": "off",
                "max_transparent_ratio": 0.2,
            },
        )
        self.assertTrue(success, msg)

        after = self._render_frame_canvas_like(self.project, "frm_flip_tile")
        self.assertIsNone(ImageChops.difference(before, after).getbbox())

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
