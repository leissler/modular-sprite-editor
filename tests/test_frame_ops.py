"""Frames tab operations (ui/frame_editor/ops.py) and the shared part geometry (ui/frame_geometry.py)."""

import unittest

from models import AFrame, Animation, CollisionRect, ControlPoint, FModule, Frame, ImageAsset, Module, ModuleMapping, Project
from ui.frame_editor import ops
from ui.frame_geometry import part_bounds


def _project():
    project = Project()
    project.images.append(ImageAsset("img", "sheet.png", 64, 64))
    project.modules += [
        Module("wide", "wide", "img", (0, 0, 8, 4), (2, 1)),
        Module("tall", "tall", "img", (8, 0, 2, 6), (0, 0)),
    ]
    frame = Frame("f1", "Hero", [
        FModule("p1", "module", "wide", (0, 0)),
        FModule("p2", "module", "tall", (10, -3), rotation_degrees=90.0),
        FModule("p3", "module", "wide", (-5, 4), flip_x=True),
    ], [CollisionRect("c1", "ct", (-4, -8, 8, 8))], [ControlPoint("k1", "pt", 3, -2)])
    holder = Frame("f2", "Holder", [FModule("n1", "frame", "f1", (20, 0), flip_y=True, rotation_degrees=90.0)])
    project.frames += [frame, holder]
    return project, frame, holder


def _state(frame):
    return [frame.to_dict()]


class TestGeometry(unittest.TestCase):
    def test_module_and_nested_bounds(self):
        project, frame, holder = _project()
        self.assertEqual(part_bounds(project, frame.fmodules[0], None), (-2, -1, 6, 3))
        # 90° about the pivot (0, 0): the 2×6 module covers x -6..0, y 0..2 around (10, -3)
        self.assertEqual(part_bounds(project, frame.fmodules[1], None), (4, -3, 10, -1))
        nested = part_bounds(project, holder.fmodules[0], None)
        # Hero spans 17 × 10 px; turned by 90° inside Holder it spans 10 × 17
        self.assertEqual((nested[2] - nested[0], nested[3] - nested[1]), (10, 17))

    def test_hidden_module_falls_back_to_a_box(self):
        project, frame, _ = _project()
        mapping = ModuleMapping("m", "m", {"wide": None})
        self.assertEqual(part_bounds(project, frame.fmodules[0], mapping), (-16, -16, 16, 16))


class TestTransforms(unittest.TestCase):
    def test_flip_selection_twice_is_identity(self):
        project, frame, _ = _project()
        before = _state(frame)
        for axis in ("x", "y"):
            ops.flip_parts(project, frame, ["p1", "p2"], axis, None)
            self.assertNotEqual(_state(frame), before)
            ops.flip_parts(project, frame, ["p1", "p2"], axis, None)
            self.assertEqual(_state(frame), before)

    def test_flip_rotated_part_uses_its_other_axis(self):
        project, frame, _ = _project()
        bounds = part_bounds(project, frame.fmodules[1], None)
        ops.flip_parts(project, frame, ["p2"], "x", None)
        part = frame.fmodules[1]
        self.assertEqual((part.flip_x, part.flip_y), (False, True))  # 90°: a screen-horizontal flip is the image's vertical
        self.assertEqual(part_bounds(project, part, None), bounds)  # a single part flips in place

    def test_mirror_frame_mirrors_parts_and_markers(self):
        project, frame, _ = _project()
        before = _state(frame)
        boxes = {fm.id: part_bounds(project, fm, None) for fm in frame.fmodules}
        ops.mirror_frame(project, frame, "x", None)
        for fm in frame.fmodules:
            b = part_bounds(project, fm, None)
            old = boxes[fm.id]
            self.assertAlmostEqual((b[0] + b[2]) / 2, -(old[0] + old[2]) / 2, delta=1)
        self.assertEqual(frame.collision_rects[0].rect, (-4, -8, 8, 8))
        self.assertEqual((frame.control_points[0].x, frame.control_points[0].y), (-4, -2), "the mirrored pixel")
        ops.mirror_frame(project, frame, "x", None)
        self.assertEqual(_state(frame), before)

    def test_rotate_frame_four_times_is_identity(self):
        project, frame, _ = _project()
        before = _state(frame)
        ops.rotate_frame(frame, 90)
        self.assertEqual(frame.fmodules[1].position, (3, 10))
        self.assertEqual(frame.collision_rects[0].rect, (0, -4, 8, 8))
        self.assertEqual((frame.control_points[0].x, frame.control_points[0].y), (1, 3), "the turned pixel")
        ops.rotate_frame(frame, -90)
        self.assertEqual(_state(frame), before)
        for _ in range(4):
            ops.rotate_frame(frame, 90)
        self.assertEqual(_state(frame), before)

    def test_origin_offset(self):
        project, frame, _ = _project()
        dx, dy = ops.origin_offset(project, frame, None, "feet")
        ops.offset_frame(frame, dx, dy)
        box = [part_bounds(project, fm, None) for fm in frame.fmodules]
        self.assertEqual(max(b[3] for b in box), 0)
        self.assertLessEqual(abs(min(b[0] for b in box) + max(b[2] for b in box)), 1)


class TestOrderAndItems(unittest.TestCase):
    def test_reorder(self):
        _project_, frame, _ = _project()
        self.assertTrue(ops.reorder_parts(frame, ["p1"], "up"))
        self.assertEqual([fm.id for fm in frame.fmodules], ["p2", "p1", "p3"])
        ops.reorder_parts(frame, ["p1", "p2"], "top")
        self.assertEqual([fm.id for fm in frame.fmodules], ["p3", "p2", "p1"])
        ops.reorder_parts(frame, ["p1"], "bottom")
        self.assertEqual([fm.id for fm in frame.fmodules], ["p1", "p3", "p2"])
        self.assertFalse(ops.reorder_parts(frame, ["p1"], "down"))
        ops.move_item(frame, "parts", "p2", "p1")
        self.assertEqual([fm.id for fm in frame.fmodules], ["p2", "p1", "p3"])

    def test_paste_skips_cycles_and_gets_fresh_ids(self):
        project, frame, holder = _project()
        new = ops.insert_items(project, frame, "parts", [holder.fmodules[0].to_dict(), frame.fmodules[0].to_dict()])
        self.assertEqual(len(new), 1)  # pasting "Holder" into "Hero" would nest Hero in itself
        self.assertNotIn("p1", new)
        self.assertIsNone(ops.add_part(project, frame, "frame", "f2", (0, 0)))
        self.assertEqual(ops.swap_source(project, frame, ["p1"], "frame", "f2"), 0)
        self.assertEqual(ops.swap_source(project, frame, ["p1"], "module", "tall"), 1)

    def test_nudge_and_delete(self):
        _p, frame, _ = _project()
        ops.nudge(frame, "hitboxes", ["c1"], 2, 3)
        self.assertEqual(frame.collision_rects[0].rect, (-2, -5, 8, 8))
        ops.nudge(frame, "points", ["k1"], -3, 0)
        self.assertEqual(frame.control_points[0].x, 0)
        self.assertEqual(ops.delete_items(frame, "parts", ["p1", "p3"]), 2)

    def test_copy_markers_to_other_frames(self):
        project, frame, holder = _project()
        self.assertEqual(ops.copy_markers_to(project, frame, "hitboxes", project.frames), 1)
        self.assertEqual(len(holder.collision_rects), 1)
        self.assertNotEqual(holder.collision_rects[0].id, "c1")
        ops.copy_markers_to(project, frame, "hitboxes", project.frames, replace=True)
        self.assertEqual(len(holder.collision_rects), 1)


class TestFramesAndTypes(unittest.TestCase):
    def test_new_duplicate_references(self):
        project, frame, holder = _project()
        project.animations.append(Animation("a", "walk", aframes=[AFrame(frame_id="f1", duration_frames=1), AFrame(frame_id="f1", duration_frames=2)]))
        refs = ops.frame_references(project, "f1")
        self.assertEqual((refs["animations"], refs["steps"], refs["frames"]), (1, 2, 1))
        self.assertEqual(ops.describe_references(refs), "1 animation, 1 other frame")
        copy = ops.duplicate_frame(project, "f1")
        self.assertEqual(project.frames.index(copy), 1)
        self.assertEqual(copy.name, "Hero copy")
        self.assertTrue(all(fm.id not in {"p1", "p2", "p3"} for fm in copy.fmodules))
        created = ops.new_frame(project, after_id="f1", name="Hero")
        self.assertEqual(created.name, "Hero (2)")
        self.assertEqual(project.frames.index(created), 1)
        ops.move_frame(project, created.id, None)
        self.assertIs(project.frames[-1], created)
        self.assertEqual(ops.summary(frame), "3 parts · 1 box · 1 point")

    def test_remove_empty_hitboxes(self):
        project, frame, holder = _project()
        holder.collision_rects.append(CollisionRect("z", "ct", (0, 0, 0, 0)))
        frame.collision_rects.append(CollisionRect("z2", "ct", (3, 3, 5, 0)))
        self.assertEqual(ops.empty_hitboxes(project), 2)
        self.assertEqual(ops.remove_empty_hitboxes(project), 2)
        self.assertEqual([c.id for c in frame.collision_rects], ["c1"])

    def test_types(self):
        project, frame, _ = _project()
        project.collision_types = []
        project.ensure_default_collision_type()
        hurt = ops.add_type(project, "hitboxes", "Hurt")
        frame.collision_rects[0].type_id = hurt.id
        self.assertEqual(ops.type_usage(project, "hitboxes", hurt.id), (1, 1))
        self.assertEqual(ops.delete_type(project, "hitboxes", hurt.id), 1)
        self.assertEqual(frame.collision_rects, [])
        for t in list(project.collision_types):
            ops.delete_type(project, "hitboxes", t.id)
        self.assertEqual(len(project.collision_types), 1)  # a default type always remains


class TestStoreWhole(unittest.TestCase):
    def test_a_frame_and_a_group(self):
        project, frame, holder = _project()
        frame.group = holder.group = "Traps"
        project.frames.append(Frame("f3", "Other", group="Props"))
        self.assertEqual(ops.store_whole([frame], True), 1)
        self.assertEqual(ops.store_whole([frame], True), 0, "already whole")
        self.assertEqual([f.id for f in ops.group_frames(project, "Traps")], ["f1", "f2"])
        self.assertEqual(ops.group_frames(project, ""), [], "no group is no group of frames")
        self.assertEqual(ops.store_whole(ops.group_frames(project, "Traps"), True), 1)
        self.assertEqual([f.store_whole for f in project.frames], [True, True, False])
        duplicate = ops.duplicate_frame(project, frame.id)
        self.assertTrue(duplicate.store_whole, "a duplicate is stored like its frame")

    def test_the_comparison_names_both_ways(self):
        import tempfile
        from pathlib import Path

        import hardware_budget as hb
        import mixed_frames

        with tempfile.TemporaryDirectory() as tmp:
            project = mixed_frames.nested_project(Path(tmp))
            calc = hb.BudgetCalculator()
            nests = project.get_frame("nests")
            parts, whole = calc.whole_or_parts(project, nests, None, hb.MEGA_DRIVE_H40)
            self.assertGreater(parts.sprite_count, whole.sprite_count)
            self.assertEqual([len(p.sprites) for p in whole.parts], [len(p.sprites) for p in calc.frame_parts(
                project, nests, None, hb.MEGA_DRIVE_H40, whole_frames=True)])
            text = ops.whole_comparison(project, nests, None, calc, hb.MEGA_DRIVE_H40)
            self.assertIn(f"{parts.sprite_count} hardware sprites as parts, {whole.sprite_count} whole", text)
            self.assertIn(f"(its pictures: {whole.unique_tiles} tiles)", text)
            self.assertFalse(nests.store_whole, "comparing marks nothing")


if __name__ == "__main__":
    unittest.main()
