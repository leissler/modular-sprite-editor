import unittest

from models import Project
from ui.scene_editor import ops


def _scene(fps=12, seconds=4.0):
    project = Project()
    scene = project.create_timeline_scene("S")
    scene.fps = fps
    scene.duration_seconds = seconds
    return project, scene


class TestTime(unittest.TestCase):
    def test_frame_time_round_trip_and_length(self):
        _p, scene = _scene(fps=60, seconds=2.0)
        self.assertEqual(ops.scene_length_frames(scene), 120)
        self.assertEqual(ops.frame_of(ops.time_of(37, 60), 60), 37)
        ops.set_scene_length_frames(scene, 90)
        self.assertAlmostEqual(scene.duration_seconds, 1.5)

    def test_changing_fps_keeps_keys_in_time(self):
        project, scene = _scene(fps=12)
        obj = ops.add_object(project, scene, "none", None, 0)
        key = ops.ensure_key(project, scene, obj, 6)  # 0.5 s
        ops.set_scene_fps(scene, 60)
        self.assertEqual(ops.frame_of(key.time, scene.fps), 30)


class TestKeys(unittest.TestCase):
    def test_keys_sharing_a_frame_resolve_to_the_selected_one(self):
        # Files from the old editor can hold two keys at the same time.
        project, scene = _scene(fps=60)
        obj = ops.add_object(project, scene, "none", None, 0)
        first = obj.keyframes[0]
        second = ops.ensure_key(project, scene, obj, 10)
        second.time = first.time
        stack = ops.keys_at_frame(obj, 0, 60)
        self.assertEqual([k.id for k in stack], [k.id for k in obj.sorted_keyframes()])
        self.assertIs(ops.key_at_frame(obj, 0, 60), stack[0])
        self.assertIs(ops.key_at_frame(obj, 0, 60, {stack[1].id}), stack[1])
        self.assertIs(ops.key_at_frame(obj, 0, 60, {"elsewhere"}), stack[0])
        self.assertIsNone(ops.key_at_frame(obj, 5, 60))

    def test_ensure_key_uses_interpolated_pose_and_keeps_segment_easing(self):
        project, scene = _scene()
        obj = ops.add_object(project, scene, "none", None, 0, (0, 0))
        end = ops.ensure_key(project, scene, obj, 10)
        end.x = 100.0
        end.easing = "cubic_in_out"
        mid = ops.ensure_key(project, scene, obj, 5)
        self.assertAlmostEqual(mid.x, 50.0)
        self.assertEqual(mid.easing, "cubic_in_out")
        self.assertIs(ops.ensure_key(project, scene, obj, 5), mid)

    def test_segment_easing_is_stored_on_the_segment_end(self):
        project, scene = _scene()
        obj = ops.add_object(project, scene, "none", None, 0)
        first = obj.keyframes[0]
        second = ops.ensure_key(project, scene, obj, 8)
        self.assertTrue(ops.set_segment_easing(obj, first.id, "bounce_out"))
        self.assertEqual(second.easing, "bounce_out")
        self.assertEqual(ops.segment_easing(obj, first.id), "bounce_out")
        self.assertIsNone(ops.segment_easing(obj, second.id))

    def test_move_keys_clamps_snaps_and_replaces_collisions(self):
        project, scene = _scene(fps=10, seconds=2.0)  # 20 frames
        obj = ops.add_object(project, scene, "none", None, 0)
        k5 = ops.ensure_key(project, scene, obj, 5)
        k8 = ops.ensure_key(project, scene, obj, 8)
        applied = ops.move_keys(scene, {obj.id: {k5.id}}, 3)
        self.assertEqual(applied, 3)
        frames = ops.key_frames(obj, scene.fps)
        self.assertEqual(frames, [0, 8])  # k5 landed on 8 and replaced the old key there
        self.assertIn(k5, obj.keyframes)
        self.assertNotIn(k8, obj.keyframes)
        applied = ops.move_keys(scene, {obj.id: {k5.id}}, 50)
        self.assertEqual(applied, 12)  # clamped to the last frame
        self.assertEqual(ops.frame_of(k5.time, scene.fps), 20)

    def test_move_keys_with_drag_origins_is_stable(self):
        project, scene = _scene(fps=10)
        obj = ops.add_object(project, scene, "none", None, 0)
        key = ops.ensure_key(project, scene, obj, 4)
        origins = {(obj.id, key.id): 4}
        for delta in (1, 2, 3, 2):
            ops.move_keys(scene, {obj.id: {key.id}}, delta, origins)
        self.assertEqual(ops.frame_of(key.time, scene.fps), 6)

    def test_delete_keeps_at_least_one_key(self):
        project, scene = _scene()
        obj = ops.add_object(project, scene, "none", None, 0)
        k = ops.ensure_key(project, scene, obj, 3)
        removed = ops.delete_keys(obj, [kk.id for kk in obj.keyframes])
        self.assertEqual(removed, 1)
        self.assertEqual(len(obj.keyframes), 1)
        self.assertNotIn(k, obj.keyframes)

    def test_copy_paste_keys_relative_to_playhead(self):
        project, scene = _scene(fps=10)
        a = ops.add_object(project, scene, "none", None, 0)
        b = ops.add_object(project, scene, "none", None, 0)
        k2 = ops.ensure_key(project, scene, a, 2)
        k5 = ops.ensure_key(project, scene, a, 5)
        k5.x = 7.0
        clip = ops.copy_keys(scene, {a.id: {k2.id, k5.id}})
        pasted = ops.paste_keys(scene, clip, 10, target_object_id=b.id)
        self.assertEqual(ops.key_frames(b, scene.fps), [0, 10, 13])
        self.assertEqual(len(pasted[b.id]), 2)
        self.assertEqual(ops.key_at_frame(b, 13, scene.fps).x, 7.0)

    def test_neighbour_key_frame(self):
        project, scene = _scene()
        obj = ops.add_object(project, scene, "none", None, 0)
        ops.ensure_key(project, scene, obj, 6)
        self.assertEqual(ops.neighbour_key_frame(scene, obj, 3, +1), 6)
        self.assertEqual(ops.neighbour_key_frame(scene, obj, 3, -1), 0)
        self.assertIsNone(ops.neighbour_key_frame(scene, obj, 6, +1))


class TestEasingNames(unittest.TestCase):
    def test_split_join_round_trip_for_all_easings(self):
        from models import TIMELINE_EASINGS

        for name in TIMELINE_EASINGS:
            shape, direction = ops.split_easing(name)
            self.assertEqual(ops.join_easing(shape, direction), name)
            self.assertTrue(ops.easing_label(name))


class TestLayers(unittest.TestCase):
    def _three(self):
        project, scene = _scene()
        a = ops.add_object(project, scene, "none", None, 0, (10, 0))
        b = ops.add_object(project, scene, "none", None, 0, (20, 0))
        c = ops.add_object(project, scene, "none", None, 0, (30, 0))
        return project, scene, a, b, c

    def test_new_objects_go_in_front_and_rows_follow_draw_order(self):
        _p, scene, a, b, c = self._three()
        self.assertEqual([r[0] for r in ops.tree_rows(scene, set())], [a, b, c])
        self.assertEqual([a.draw_order, b.draw_order, c.draw_order], [0, 1, 2])

    def test_reparent_keeps_world_position_and_draw_order_is_depth_first(self):
        project, scene, a, b, c = self._three()
        a.keyframes[0].rotation_degrees = 90.0
        a.keyframes[0].flip_x = True
        before = ops.evaluate_states(project, scene, 0.0)
        world_before = ops.world_matrix(scene, before, c.id)
        self.assertTrue(ops.move_layer(project, scene, c.id, a.id, None))
        after = ops.evaluate_states(project, scene, 0.0)
        world_after = ops.world_matrix(scene, after, c.id)
        for v1, v2 in zip(world_before, world_after):
            self.assertAlmostEqual(v1, v2, places=6)
        rows = ops.tree_rows(scene, set())
        self.assertEqual([(r[0], r[1]) for r in rows], [(a, 0), (c, 1), (b, 0)])
        self.assertEqual([r[0].draw_order for r in rows], [0, 1, 2])

    def test_cannot_parent_into_own_subtree(self):
        project, scene, a, b, _c = self._three()
        ops.move_layer(project, scene, b.id, a.id, None)
        self.assertFalse(ops.move_layer(project, scene, a.id, b.id, None))
        self.assertIsNone(a.parent_id)

    def test_reorder_and_step(self):
        project, scene, a, b, c = self._three()
        ops.move_layer(project, scene, c.id, None, a.id)
        self.assertEqual([r[0] for r in ops.tree_rows(scene, set())], [c, a, b])
        ops.step_layer(project, scene, c.id, +1)
        self.assertEqual([r[0] for r in ops.tree_rows(scene, set())], [a, c, b])

    def test_delete_parent_keeps_children_in_place(self):
        project, scene, a, b, _c = self._three()
        a.keyframes[0].x = 50.0
        ops.move_layer(project, scene, b.id, a.id, None)
        world_before = ops.world_matrix(scene, ops.evaluate_states(project, scene, 0.0), b.id)
        ops.delete_object(project, scene, a.id)
        self.assertIsNone(b.parent_id)
        world_after = ops.world_matrix(scene, ops.evaluate_states(project, scene, 0.0), b.id)
        self.assertAlmostEqual(world_before[4], world_after[4])

    def test_duplicate_copies_subtree_with_fresh_ids(self):
        project, scene, a, b, _c = self._three()
        ops.move_layer(project, scene, b.id, a.id, None)
        copy = ops.duplicate_object(scene, a.id)
        kids = ops.children_of(scene, copy.id)
        self.assertEqual(len(kids), 1)
        self.assertNotEqual(kids[0].id, b.id)
        self.assertNotEqual(kids[0].keyframes[0].id, b.keyframes[0].id)
        rows = [r[0] for r in ops.tree_rows(scene, set())]
        self.assertEqual(rows.index(copy), rows.index(b) + 1)


if __name__ == "__main__":
    unittest.main()
