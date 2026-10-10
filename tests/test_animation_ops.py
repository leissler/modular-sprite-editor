import unittest

from models import AFrame, Animation, Project, TimelineKeyframe
from ui.animation_editor import ops


def _anim(holds=(1, 2, 3), mode="loop", loops=0):
    anim = Animation(id="a", name="A", playback_type=mode, loop_count=loops, fps=10)
    anim.aframes = [AFrame(frame_id=f"f{i}", duration_frames=h) for i, h in enumerate(holds)]
    return anim


def _play(anim, ticks, repeat=False):
    player = ops.Player(anim, repeat=repeat)
    player.start()
    shown = [player.step]
    for _ in range(ticks - 1):
        if not player.advance():
            break
        shown.append(player.step)
    return shown, player


class TestTiming(unittest.TestCase):
    def test_ticks_and_steps(self):
        anim = _anim((1, 2, 0))  # a hold of 0 counts as 1 tick, like the exporters
        self.assertEqual(ops.total_ticks(anim), 4)
        self.assertEqual(ops.step_starts(anim), [0, 1, 3])
        self.assertEqual([ops.step_at_tick(anim, t) for t in range(6)], [0, 1, 1, 2, 2, 2])
        self.assertEqual(ops.describe_length(anim), "3 steps · 4 ticks · 0.40 s")


class TestPlayer(unittest.TestCase):
    def test_loop_follows_holds_and_wraps(self):
        shown, _ = _play(_anim((1, 2)), 7)
        self.assertEqual(shown, [0, 1, 1, 0, 1, 1, 0])

    def test_play_once_stops_on_last_step(self):
        shown, player = _play(_anim((1, 1, 1), "forward"), 10)
        self.assertEqual(shown, [0, 1, 2])
        self.assertTrue(player.finished)
        self.assertEqual(player.step, 2)

    def test_ping_pong_does_not_repeat_the_ends(self):
        shown, _ = _play(_anim((1, 1, 1), "ping_pong"), 9)
        self.assertEqual(shown, [0, 1, 2, 1, 0, 1, 2, 1, 0])

    def test_backward_repeats_like_the_runtime(self):
        shown, _ = _play(_anim((1, 1, 1), "backward"), 7)
        self.assertEqual(shown, [2, 1, 0, 2, 1, 0, 2])

    def test_loop_count_stops_and_repeat_restarts(self):
        shown, player = _play(_anim((1, 1), "loop", loops=2), 10)
        self.assertEqual(shown, [0, 1, 0, 1])
        self.assertTrue(player.finished)
        shown, _ = _play(_anim((1, 1), "loop", loops=2), 6, repeat=True)
        self.assertEqual(shown, [0, 1, 0, 1, 0, 1])

    def test_position_moves_through_a_hold(self):
        anim = _anim((3,))
        player = ops.Player(anim)
        player.start()
        positions = [player.position()]
        for _ in range(3):
            player.advance()
            positions.append(player.position())
        self.assertEqual(positions, [0, 1, 2, 0])


class TestStepEdits(unittest.TestCase):
    def test_move_steps_keeps_order(self):
        anim = _anim((1, 1, 1, 1, 1))
        new = ops.move_steps(anim, [0, 1], 4)
        self.assertEqual([af.frame_id for af in anim.aframes], ["f2", "f3", "f0", "f1", "f4"])
        self.assertEqual(new, [2, 3])
        new = ops.move_steps(anim, [4], 0)
        self.assertEqual(anim.aframes[0].frame_id, "f4")
        self.assertEqual(new, [0])

    def test_duplicate_copy_paste_delete(self):
        anim = _anim((1, 2, 3))
        self.assertEqual(ops.duplicate_steps(anim, [0, 1]), [2, 3])
        self.assertEqual([af.frame_id for af in anim.aframes], ["f0", "f1", "f0", "f1", "f2"])
        self.assertIsNot(anim.aframes[2], anim.aframes[0])
        data = ops.copy_steps(anim, [4])
        self.assertEqual(ops.paste_steps(anim, 0, data), [0])
        self.assertEqual(anim.aframes[0].frame_id, "f2")
        self.assertEqual(ops.delete_steps(anim, [0, 1, 99]), 2)
        self.assertEqual(len(anim.aframes), 4)

    def test_hold_flip_rotate_nudge_reverse(self):
        anim = _anim((1, 2, 3))
        ops.change_hold(anim, [0, 1], -5)
        self.assertEqual([af.duration_frames for af in anim.aframes], [1, 1, 3])
        ops.set_hold(anim, [2], 4)
        self.assertEqual(anim.aframes[2].duration_frames, 4)
        self.assertTrue(ops.toggle_flip(anim, [0, 1], "x"))
        self.assertTrue(anim.aframes[1].flip_x)
        ops.rotate_steps(anim, [0], -90)
        self.assertEqual(anim.aframes[0].rotation_degrees, 270.0)
        ops.nudge(anim, [1, 2], 3, -1)
        self.assertEqual(anim.aframes[2].offset, (3, -1))
        ops.reverse_steps(anim, [])
        self.assertEqual([af.frame_id for af in anim.aframes], ["f2", "f1", "f0"])


class TestWholeAnimation(unittest.TestCase):
    def test_mirror_swaps_flip_axis_for_quarter_turns(self):
        anim = _anim((1, 1))
        anim.aframes[0].offset = (5, 2)
        anim.aframes[1].rotation_degrees = 90.0
        ops.mirror_animation(anim, "x")
        self.assertEqual(anim.aframes[0].offset, (-5, 2))
        self.assertTrue(anim.aframes[0].flip_x)
        self.assertTrue(anim.aframes[1].flip_y)
        self.assertFalse(anim.aframes[1].flip_x)

    def test_rotate_turns_motion_clockwise(self):
        anim = _anim((1,))
        anim.aframes[0].offset = (4, 0)
        ops.rotate_animation(anim, 90)
        self.assertEqual(anim.aframes[0].offset, (0, 4))  # right -> down on screen
        self.assertEqual(anim.aframes[0].rotation_degrees, 90.0)
        ops.rotate_animation(anim, -90)
        self.assertEqual(anim.aframes[0].offset, (4, 0))
        self.assertEqual(anim.aframes[0].rotation_degrees, 0.0)


class TestAnimations(unittest.TestCase):
    def test_new_duplicate_move_and_usage(self):
        project = Project()
        a = ops.new_animation(project)
        b = ops.new_animation(project, after_id=a.id)
        self.assertEqual([x.name for x in project.animations], ["New Animation", "New Animation 2"])
        c = ops.duplicate_animation(project, a)
        self.assertEqual(project.animations.index(c), 1)
        self.assertEqual(c.name, "New Animation copy")
        ops.move_animation(project, b.id, 0)
        self.assertIs(project.animations[0], b)
        scene = project.create_timeline_scene("S")
        obj = scene.create_object("o", source_type="animation", source_id=a.id)
        obj.keyframes.append(TimelineKeyframe(id="k", time=1.0, source_type="animation", source_id=a.id))
        other = scene.create_object("p", source_type="none", source_id=None)
        other.keyframes.append(TimelineKeyframe(id="k2", time=1.0, source_type="animation", source_id=a.id))
        self.assertEqual(ops.scene_usage(project, a.id), 2)
        self.assertEqual(ops.scene_usage(project, b.id), 0)


if __name__ == "__main__":
    unittest.main()
