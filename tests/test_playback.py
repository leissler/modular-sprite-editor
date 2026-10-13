"""playback.py: the shortcut Timeline objects use (step_after, animation_at) leaves exactly what the tick-by-tick
Player (= the Mega Drive runtime, see test_runtime_player.py) shows, follow-up animations included."""

import copy
import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import playback  # noqa: E402
from models import AFrame, Animation, Project  # noqa: E402

TESTBEDS = [ROOT / "examples" / "sgdk" / "PoP_WW.json", ROOT / "examples" / "sonic" / "sonic.json",
            ROOT / "examples" / "adventurer" / "adventurer.json"]


def _anim(ident, holds, playback_type="loop", loop_count=0, loop_start=0, fps=10, follow=None):
    anim = Animation(id=ident, name=ident, playback_type=playback_type, loop_count=loop_count, fps=fps,
                     loop_start=loop_start, next_animation_id=follow)
    anim.aframes = [AFrame(frame_id=f"{ident}{i}", duration_frames=hold) for i, hold in enumerate(holds)]
    return anim


def _player_trace(anim, ticks):
    """[(step, ended tick or None)] after 0 .. ticks - 1 advances of the Player."""
    player = playback.Player(anim, repeat=False)
    player.start()
    trace, ended = [], None
    for tick in range(ticks):
        trace.append((player.step, ended))
        if not player.advance() and ended is None:
            ended = tick + 1
    return trace


def _runtime_chain(anims, first, ticks):
    """What the runtime shows tick by tick when an animation that ends hands over to its follow-up
    (ms_anim_finish: the follow-up's first step shows from that very tick)."""
    player = playback.Player(anims[first], repeat=False)
    player.start()
    shown = []
    for _ in range(ticks):
        shown.append((player.anim.id, player.step))
        if not player.advance():
            follow = anims.get(player.anim.next_animation_id or "")
            if follow is not None and follow.aframes:
                player = playback.Player(follow, repeat=False)
                player.start()
    return shown


class StepAfterTest(unittest.TestCase):
    def assert_like_player(self, anim, rules=None):
        rules = rules or playback.own_rules(anim)
        ticks = 3 * sum(playback.hold(af) for af in anim.aframes) * max(1, rules.loop_count + 1) + 7
        trace = _player_trace(anim, ticks)
        got = [playback.step_after(anim, tick, rules) for tick in range(ticks)]
        self.assertEqual([step for step, _ in got], [step for step, _ in trace])
        finished = next((ended for _, ended in trace if ended is not None), None)
        self.assertEqual({ended for _, ended in got if ended is not None} or {None}, {finished})

    def test_every_playback_repeat_count_and_loop_start(self):
        for kind, holds, limit in itertools.product(
            playback.PLAYBACKS, ([1], [2], [1, 3], [2, 1, 1], [1, 2, 3, 1]), (0, 1, 2, 3)
        ):
            for start in range(len(holds)):
                anim = _anim("a", holds, kind, limit, start)
                with self.subTest(kind=kind, holds=holds, loop_count=limit, loop_start=start):
                    self.assert_like_player(anim)

    def test_testbed_animations(self):
        for path in TESTBEDS:
            project = Project.from_json(str(path))
            for anim in project.animations:
                if anim.aframes:
                    with self.subTest(project=path.name, animation=anim.name):
                        self.assert_like_player(anim)

    def test_scene_overrides_play_like_an_animation_set_that_way(self):
        anim = _anim("a", [1, 2, 1, 3], "forward", loop_count=2, loop_start=2, follow="b")
        for mode, kind in (("once", "forward"), ("loop", "loop"), ("ping_pong", "ping_pong"), ("backward", "backward")):
            rules = playback.object_rules(anim, mode)
            self.assertFalse(rules.follow_up)
            as_set = copy.deepcopy(anim)
            as_set.playback_type, as_set.loop_count = kind, 0
            with self.subTest(mode=mode):
                self.assert_like_player(as_set, rules)
        self.assertEqual(playback.object_rules(anim, "loop").loop_start, 2, "Loop keeps the loop-from step")
        self.assertEqual(playback.object_rules(anim, playback.AS_ANIMATED), playback.own_rules(anim))

    def test_single_step_ping_pong_never_ends(self):
        anim = _anim("a", [2], "ping_pong", loop_count=1)
        self.assertEqual(playback.step_after(anim, 100, playback.own_rules(anim)), (0, None))

    def test_once_is_forward(self):
        anim = _anim("a", [1, 1], "once")
        self.assertEqual(playback.own_rules(anim).playback, "forward")
        self.assertEqual(playback.steps_shown(anim, 4), [0, 1, 1, 1])


class AnimationAtTest(unittest.TestCase):
    def test_follow_up_chains_like_the_runtime(self):
        anims = {a.id: a for a in (
            _anim("a", [1, 2], "forward", follow="b"),
            _anim("b", [1, 1, 1], "loop", loop_count=2, loop_start=1, follow="c"),
            _anim("c", [2, 1], "ping_pong", loop_count=1, follow="a"),  # back to the start: a chain that repeats
            _anim("d", [1, 1], "backward", loop_count=3, follow="e"),
            _anim("e", [3], "loop"),  # ends the chain d -> e
        )}
        for first in ("a", "d"):
            expected = _runtime_chain(anims, first, 400)
            got = []
            for tick in range(400):
                anim, step = playback.animation_at(anims[first], tick / 10, playback.own_rules(anims[first]), anims.get)
                got.append((anim.id, step))
            with self.subTest(first=first):
                self.assertEqual(got, expected)

    def test_a_follow_up_plays_at_its_own_tick_rate(self):
        anims = {a.id: a for a in (_anim("a", [1, 2], "forward", fps=10, follow="b"), _anim("b", [1] * 6, fps=20))}
        rules = playback.own_rules(anims["a"])
        at = [playback.animation_at(anims["a"], t, rules, anims.get) for t in (0.05, 0.15, 0.3, 0.35, 0.4, 0.55)]
        self.assertEqual([(a.id, step) for a, step in at], [("a", 0), ("a", 1), ("b", 0), ("b", 1), ("b", 2), ("b", 5)])

    def test_overrides_and_missing_follow_ups_stay_on_the_animation(self):
        anims = {a.id: a for a in (_anim("a", [1, 1], "forward", follow="b"), _anim("b", [1]),
                                   _anim("c", [1, 1], "forward", follow="gone"), _anim("e", [], follow=None))}
        anims["d"] = _anim("d", [1], "forward", follow="e")  # a follow-up without steps is not followed
        once = playback.object_rules(anims["a"], "once")
        self.assertEqual(playback.animation_at(anims["a"], 5.0, once, anims.get)[0].id, "a")
        for ident in ("c", "d"):
            anim, step = playback.animation_at(anims[ident], 5.0, playback.own_rules(anims[ident]), anims.get)
            self.assertEqual((anim.id, step), (ident, len(anims[ident].aframes) - 1))

    def test_before_the_start_the_first_step_shows(self):
        anim = _anim("a", [1, 1, 1], "backward")
        self.assertEqual(playback.animation_at(anim, -0.5, playback.own_rules(anim), lambda _id: None)[1], 2)


if __name__ == "__main__":
    unittest.main()
