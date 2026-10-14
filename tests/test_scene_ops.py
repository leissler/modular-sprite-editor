import re
import unittest
from pathlib import Path

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

    def test_several_layers_act_through_their_top_ones(self):
        project, scene, a, b, c = self._three()
        ops.move_layer(project, scene, b.id, a.id, None)
        self.assertEqual(ops.top_objects(scene, [b.id, c.id, a.id, "gone"]), [c, a], "b follows its parent a")
        self.assertEqual(ops.top_objects(scene, [b.id]), [b])

    def test_copy_layers_into_another_scene(self):
        project, scene, a, b, c = self._three()
        ops.move_layer(project, scene, b.id, a.id, None)
        a.mapping_id, c.palette_swap_id = "map", "swap"
        ops.ensure_key(project, scene, c, 6)
        data = ops.copy_objects(scene, [c.id, b.id, a.id])
        self.assertEqual([d["id"] for d in data], [a.id, b.id, c.id], "parents first, in draw order")
        other = project.create_timeline_scene("Other")
        there = ops.add_object(project, other, "none", None, 0)
        tops = ops.paste_objects(other, data)
        self.assertEqual([o.name for o in tops], [a.name, c.name], "another scene: the names stay")
        pasted_a, pasted_c = tops
        kids = ops.children_of(other, pasted_a.id)
        self.assertEqual([k.name for k in kids], [b.name], "the child came along, under its parent's copy")
        self.assertEqual((pasted_a.mapping_id, pasted_c.palette_swap_id), ("map", "swap"))
        self.assertEqual([k.time for k in pasted_c.keyframes], [k.time for k in c.keyframes])
        ids = {o.id for o in scene.objects}
        self.assertFalse({o.id for o in other.objects} & ids, "new ids")
        keys = {k.id for o in scene.objects for k in o.keyframes}
        self.assertFalse({k.id for o in other.objects for k in o.keyframes} & keys)
        rows = [r[0] for r in ops.tree_rows(other, set())]
        self.assertEqual(rows, [there, pasted_a, kids[0], pasted_c], "in front of what the scene had")
        self.assertEqual([o.draw_order for o in rows], list(range(len(rows))))
        again = ops.paste_objects(scene, ops.copy_objects(scene, [c.id]))
        self.assertEqual(again[0].name, f"{c.name} copy", "next to the original: told apart")


class TestRootMotion(unittest.TestCase):
    def _fighter(self, offset=(10.0, -2.0), step_flip=False, step_rotation=0.0):
        from models import AFrame, Animation

        project, scene = _scene(fps=10)
        anim = Animation(id="a", name="step", fps=10)
        anim.aframes = [AFrame(frame_id="f", duration_frames=1, offset=offset, flip_x=step_flip, rotation_degrees=step_rotation)]
        project.animations.append(anim)
        obj = ops.add_object(project, scene, "animation", "a", 0, (100.0, 0.0))
        obj.use_source_root_motion = True
        return project, scene, obj

    def _world(self, project, scene, obj):
        return ops.world_matrix(scene, ops.evaluate_states(project, scene, 0.0), obj.id)

    def test_root_motion_follows_the_objects_mirror_and_rotation(self):
        project, scene, obj = self._fighter()
        self.assertEqual(self._world(project, scene, obj)[4:], (110.0, -2.0))
        obj.keyframes[0].flip_x = True  # facing left: the step moves left
        self.assertEqual(self._world(project, scene, obj)[4:], (90.0, -2.0))
        obj.keyframes[0].flip_x = False
        obj.keyframes[0].rotation_degrees = 90.0  # turned: so is the step's offset
        self.assertEqual(self._world(project, scene, obj)[4:], (102.0, 10.0))

    def test_step_flip_and_rotation_combine_like_a_mirrored_parent(self):
        project, scene, obj = self._fighter(step_flip=True, step_rotation=90.0)
        obj.keyframes[0].flip_x = True
        a, b, c, d, _tx, _ty = self._world(project, scene, obj)
        # flip · (rotate 90° · flip) = rotate -90°: a mirrored object turns its step the other way
        self.assertEqual((a, b, c, d), (0.0, -1.0, 1.0, 0.0))

    def test_reparent_keeps_world_pose_with_root_motion(self):
        project, scene, obj = self._fighter(step_flip=True, step_rotation=90.0)
        obj.keyframes[0].flip_x = True
        parent = ops.add_object(project, scene, "none", None, 0, (30.0, 40.0))
        parent.keyframes[0].rotation_degrees = 90.0
        parent.keyframes[0].flip_y = True
        before = self._world(project, scene, obj)
        self.assertTrue(ops.move_layer(project, scene, obj.id, parent.id, None))
        for v1, v2 in zip(before, self._world(project, scene, obj)):
            self.assertAlmostEqual(v1, v2, places=6)



class TestScreenGuide(unittest.TestCase):
    def test_origin_is_where_the_sgdk_demo_draws_scenes(self):
        main_c = (Path(__file__).resolve().parents[1] / "examples" / "sgdk" / "sgdk_demo" / "src" / "main.c").read_text()
        x = int(re.search(r"#define SPRITE_DRAW_X (\d+)", main_c).group(1))
        y = int(re.search(r"#define SPRITE_DRAW_Y (\d+)", main_c).group(1))
        self.assertEqual(ops.screen_origin((320, 224)), (x, y))
        self.assertEqual(ops.screen_rect((320, 224)), (-160, -168, 160, 56))
        self.assertEqual(ops.screen_rect((160, 144)), (-80, -108, 80, 36))


if __name__ == "__main__":
    unittest.main()
