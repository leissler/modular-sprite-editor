"""Modules tab operations (ui/module_editor/ops.py): detection, slicing, trimming, pivots, naming."""

import random
import unittest
from collections import deque

from PIL import Image

from models import FModule, Frame, ImageAsset, Module, ModuleMapping, Project
from ui.module_editor import ops


def _flood_fill_regions(alpha, w, h, threshold=10):
    """The previous editor's pixel flood fill, as the reference for detect_regions."""
    visited = bytearray(w * h)
    rects = []
    for y in range(h):
        for x in range(w):
            idx = y * w + x
            if alpha[idx] > threshold and not visited[idx]:
                min_x = max_x = x
                min_y = max_y = y
                q = deque([(x, y)])
                visited[idx] = 1
                while q:
                    cx, cy = q.popleft()
                    min_x, max_x, min_y, max_y = min(min_x, cx), max(max_x, cx), min(min_y, cy), max(max_y, cy)
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            n = ny * w + nx
                            if not visited[n] and alpha[n] > threshold:
                                visited[n] = 1
                                q.append((nx, ny))
                rects.append((min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))
    return rects


class TestDetection(unittest.TestCase):
    def test_matches_flood_fill_on_random_sheets(self):
        rng = random.Random(7)
        for _ in range(30):
            w, h = rng.randint(1, 40), rng.randint(1, 30)
            density = rng.random() * 0.5
            alpha = bytes(rng.choice((0, 5, 11, 200, 255)) if rng.random() < density else 0 for _ in range(w * h))
            expected = sorted(_flood_fill_regions(alpha, w, h))
            self.assertEqual(sorted(ops.detect_regions(alpha, w, h)), expected)

    def test_diagonal_pixels_connect(self):
        alpha = bytes([255, 0, 0,
                       0, 255, 0,
                       0, 0, 255])
        self.assertEqual(ops.detect_regions(alpha, 3, 3), [(0, 0, 3, 3)])

    def test_reading_order_and_merge_gap(self):
        img = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
        for box in ((30, 2, 4, 4), (2, 2, 4, 4), (8, 2, 3, 4), (2, 12, 4, 4)):
            for x in range(box[0], box[0] + box[2]):
                for y in range(box[1], box[1] + box[3]):
                    img.putpixel((x, y), (255, 255, 255, 255))
        alpha = img.getchannel("A").tobytes()
        regions = ops.detect_regions(alpha, 40, 20)
        self.assertEqual(regions, [(2, 2, 4, 4), (8, 2, 3, 4), (30, 2, 4, 4), (2, 12, 4, 4)])
        self.assertEqual(ops.merge_regions(regions, 0), regions)  # 2 px apart, gap 0: separate
        merged = ops.merge_regions(regions, 3)
        self.assertEqual(merged, [(2, 2, 9, 4), (30, 2, 4, 4), (2, 12, 4, 4)])


class TestSlicing(unittest.TestCase):
    def test_grid_rects(self):
        self.assertEqual(ops.grid_rects(10, 5, 4, 4), [(0, 0, 4, 4), (4, 0, 4, 4)])
        self.assertEqual(ops.grid_rects(20, 10, 4, 4, offset_x=1, offset_y=1, gap_x=2, gap_y=1),
                         [(1, 1, 4, 4), (7, 1, 4, 4), (13, 1, 4, 4), (1, 6, 4, 4), (7, 6, 4, 4), (13, 6, 4, 4)])

    def test_opaque_bbox_trims(self):
        sheet = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        sheet.putpixel((5, 6), (1, 1, 1, 255))
        sheet.putpixel((9, 8), (1, 1, 1, 255))
        self.assertEqual(ops.opaque_bbox(sheet, (0, 0, 16, 16)), (5, 6, 5, 3))
        self.assertIsNone(ops.opaque_bbox(sheet, (0, 0, 4, 4)))
        self.assertEqual(ops.opaque_bbox(sheet, (-4, -4, 12, 12)), (5, 6, 1, 1))  # clipped to the sheet

    def test_add_sheet_modules_replace_and_keep(self):
        project = Project()
        project.images.append(ImageAsset("img_a", "/tmp/hero sheet.png", 64, 64))
        old = ops.create_image_module(project, "img_a", (0, 0, 8, 8))
        created = ops.add_sheet_modules(project, "img_a", [(0, 0, 8, 8), (16, 0, 8, 8)], replace=False)
        self.assertEqual([m.rect for m in created], [(16, 0, 8, 8)])  # the overlapping rect is kept as it was
        self.assertIn(old, project.modules)
        self.assertEqual(created[0].name, "hero_sheet_01")
        created = ops.add_sheet_modules(project, "img_a", [(0, 0, 4, 4)], replace=True)
        self.assertEqual(project.modules, created)


class TestPivots(unittest.TestCase):
    def test_presets(self):
        self.assertEqual(ops.preset_pivot(16, 24, (0.5, 1.0)), (8, 24))
        self.assertEqual(ops.preset_pivot(15, 9, (0.5, 0.5)), (7, 4))
        self.assertEqual(ops.preset_pivot(15, 9, (1.0, 0.0)), (15, 0))

    def test_rotated_module_round_trip(self):
        mod = Module("m", "m", "img", (10, 20, 6, 4), (1, 5), rotated=True)
        visual = ops.visual_pivot(mod)
        self.assertEqual(ops.logical_pivot(mod, visual), (1, 5))
        ops.apply_pivot_preset(mod, (0.5, 1.0))
        self.assertEqual(mod.pivot, (2, 6))  # preset on the unrotated 4×6 module
        self.assertEqual(ops.matching_preset(mod), "Bottom")

    def test_resize_keeps_pivot_pixel(self):
        mod = Module("m", "m", "img", (10, 10, 8, 8), (4, 4))
        ops.resize_keeping_pivot(mod, (12, 10, 6, 8), ops.pivot_on_sheet(mod))
        self.assertEqual(ops.pivot_on_sheet(mod), (14, 14))
        ops.resize_keeping_pivot(mod, (20, 10, 4, 8), ops.pivot_on_sheet(mod))
        self.assertEqual(mod.pivot, (0, 4))  # clamped to the new border


class TestEditing(unittest.TestCase):
    def _project(self):
        project = Project()
        project.images.append(ImageAsset("img_a", "a.png", 32, 32))
        a = ops.create_image_module(project, "img_a", (0, 0, 8, 8), name="a")
        b = ops.create_image_module(project, "img_a", (8, 0, 8, 8), name="b")
        frame = Frame("f", "f", [FModule("p1", "module", a.id, (0, 0)), FModule("p2", "module", a.id, (4, 0))])
        project.frames.append(frame)
        project.mappings.append(ModuleMapping("map", "alt", {a.id: b.id}))
        return project, a, b

    def test_usage_and_description(self):
        project, a, b = self._project()
        self.assertEqual(ops.usage(project, [a.id]), (2, 1, 1))
        self.assertEqual(ops.usage(project, [b.id]), (0, 0, 1))
        self.assertEqual(ops.describe_usage(2, 1, 1), "2 parts in 1 frame, 1 mapping entry")
        self.assertEqual(ops.part_counts(project), {a.id: 2})

    def test_duplicate_and_delete(self):
        project, a, b = self._project()
        copies = ops.duplicate_modules(project, [a.id], offset=(0, 8))
        self.assertEqual(project.modules.index(copies[0]), 1)
        self.assertEqual(copies[0].rect, (0, 8, 8, 8))
        self.assertEqual(copies[0].name, "a copy")
        self.assertNotEqual(copies[0].id, a.id)
        self.assertEqual(ops.delete_modules(project, [a.id, copies[0].id]), 2)
        self.assertEqual(project.modules, [b])

    def test_shapes_and_sheets(self):
        project, a, b = self._project()
        shape = ops.create_shape_module(project, "MD_FILL_TRIANGLE", (0, 0, -10, 10), (255, 0, 0))
        self.assertEqual(shape.rect, (-10, 0, 10, 10))
        self.assertEqual(shape.params, [50.0, 0.0, 100.0, 100.0, 0.0, 100.0])
        self.assertEqual(ops.modules_of_sheet(project, ops.SHAPES_KEY), [shape])
        orphan = Module("o", "o", "gone", (0, 0, 4, 4), (0, 0))
        project.modules.append(orphan)
        self.assertTrue(ops.has_orphans(project))
        self.assertEqual(ops.modules_of_sheet(project, ops.ORPHANS_KEY), [orphan])
        self.assertEqual(ops.remove_image(project, "img_a"), 2)
        self.assertEqual(project.modules, [shape, orphan])

    def test_legacy_shape_points(self):
        mod = Module("s", "s", "missing", (0, 0, 20, 10), (0, 0), type="MD_LINE", params=[10.0, 5.0])
        self.assertEqual(ops.shape_points(mod), [0.0, 0.0, 50.0, 50.0])

    def test_rect_helpers(self):
        self.assertEqual(ops.rect_from_points((5.5, 2.2), (1.1, 4.9)), (1, 2, 5, 3))
        self.assertEqual(ops.normalize((10, 10, -4, -2)), (6, 8, 4, 2))
        self.assertEqual(ops.numbered_names("s", 3, {"s_02"}), ["s_01", "s_03", "s_04"])


if __name__ == "__main__":
    unittest.main()
