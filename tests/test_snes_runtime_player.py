"""The SNES runtime's animation player, hitboxes and points must be the editor's.

examples/snes/snes_demo/src/modsprite.c has the Mega Drive runtime's player. Built for the host with the SNES export's
real data (examples/snes/tools/snes_host.py), it plays, video frame by video frame:
- the Mega Drive player test's cases (tests/test_megadrive_runtime_player.py: every playback mode, repeat counts, loop-from
  steps, follow-up animations, step events) and every animation of the Prince of Persia example with the game's timing,
  against playback.Player as the editor's preview runs it;
- the hitboxes and points of every frame and of every step the players show, against what the bake stores for them,
  and the Mega Drive marker test's frame (tests/test_megadrive_markers.py), plain, mirrored and offset, and turned.
Skipped without a C compiler.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "examples" / "snes" / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import playback  # noqa: E402
import snes_host  # noqa: E402
from models import AFrame, Animation, EventType, Frame, Project, StepEvent  # noqa: E402
from test_megadrive_runtime_player import CASES, TICKS  # noqa: E402
from test_megadrive_markers import _project as marker_project  # noqa: E402

POP = REPO_ROOT / "examples" / "pop" / "PoP_WW.json"
MAX_TICKS = 1200  # 20 seconds of the longest animation


def _cases_project() -> Project:
    """The Mega Drive player test's cases as a project the SNES export bakes: one frame for every step, 60 ticks a
    second (a tick is a video frame, so the cases' holds are the game's)."""
    project = Project()
    project.event_types = [EventType("evt_0", "a", (255, 0, 0)), EventType("evt_1", "b", (0, 255, 0))]
    project.frames.append(Frame("f", "pose"))
    anims = []
    for i, (name, playback_type, holds, loop_start, _next, loop_count, step_events) in enumerate(CASES):
        anim = Animation(id=f"a{i}", name=name, playback_type=playback_type, loop_count=loop_count, loop_start=loop_start)
        anim.fps = 60
        anim.aframes = [
            AFrame(frame_id="f", duration_frames=h, events=[StepEvent(f"evt_{t}", v) for t, v in step_events.get(s, [])])
            for s, h in enumerate(holds)
        ]
        anims.append(anim)
    for anim, case in zip(anims, CASES):
        anim.next_animation_id = anims[case[4]].id if case[4] is not None else None
    project.animations = anims
    return project


def _editor_trace(project: Project, start: int, ticks: int):
    """The editor's preview video frame by video frame (playback.Player with the game's holds), handing over to
    follow-up animations: (animation, step, finished, an event of type 0 started, the value of type 1's) per frame."""
    anims = project.animations
    types = [t.id for t in project.event_types] + [None, None]

    def player_of(index):
        player = playback.Player(anims[index], repeat=False, hold_of=playback.console_hold(anims[index]))
        player.start()
        return player

    index = start
    player = player_of(index)
    out = []
    for t in range(ticks):
        if t > 0 and not player.advance() and anims[index].next_animation_id:
            index = next(i for i, a in enumerate(anims) if a.id == anims[index].next_animation_id)
            player = player_of(index)
        events = anims[index].aframes[player.step].events
        started = int(player.step_started and any(e.type_id == types[0] for e in events))
        value = next((e.value for e in events if e.type_id == types[1]), 0)
        out.append((index, player.step, int(player.finished), started, value))
    return out


def _runtime_trace(line: str):
    """A harness "player" line as (the trace like _editor_trace's, the hitboxes and points on every frame)."""
    trace, markers = [], []
    for token in line.split()[1:]:
        animation, step, finished, started, value, rest = token.split(":", 5)
        trace.append((int(animation), int(step), int(finished), int(started), int(value)))
        markers.append(snes_host.parse_markers(rest))
    return trace, markers


def _baked_markers(ctx, render_index: int):
    """The hitboxes and points the bake stores for a render frame, as the runtime's records hold them."""
    span = ctx.render_frames[render_index]
    boxes = [(t & 0xFF, r & 0xFFFF, x, y, w, h)
             for t, r, x, y, w, h in ctx.boxes[span.first_box:span.first_box + span.box_count]]
    points = [(t & 0xFF, r & 0xFFFF, x, y) for t, r, x, y in ctx.points[span.first_point:span.first_point + span.point_count]]
    return boxes, points


def _step_render_frame(ctx, animation: int, step: int) -> int:
    """The render frame an animation's step shows (mapping 0: the first block of records)."""
    return ctx.anim_steps[ctx.anim_records[animation].first_step + step][0]


def _run(project: Project, commands):
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        ctx = snes_host.export(project, folder, "none")
        exe = snes_host.build(ctx, folder)
        _head, lines = snes_host.run(exe, folder, commands)
    return ctx, lines


@unittest.skipUnless(snes_host.have_compiler(), "no C compiler")
class SNESPlayerTest(unittest.TestCase):
    def test_the_mega_drive_cases(self):
        """Every playback mode, repeat counts, loop-from steps, follow-ups and events, as the Mega Drive's runtime
        is tested, through the SNES export."""
        project = _cases_project()
        _ctx, lines = _run(project, [f"player {i} {TICKS}" for i in range(len(CASES))])
        self.assertEqual(len(lines), len(CASES))
        for index, (line, case) in enumerate(zip(lines, CASES)):
            trace, _markers = _runtime_trace(line)
            self.assertEqual(trace, _editor_trace(project, index, TICKS), f"case '{case[0]}'")

    def test_every_animation_of_the_prince(self):
        """The example's animations with the game's timing (tick rates of 8 to 30 a second), and the hitboxes and points
        of every step they show; then every frame's."""
        project = Project.from_json(str(POP))
        ticks = []
        for anim in project.animations:
            hold = playback.console_hold(anim)
            ticks.append(min(MAX_TICKS, 2 * sum(hold(af) for af in anim.aframes) + 30))  # two passes, a hand-over
        commands = [f"player {i} {n}" for i, n in enumerate(ticks)]
        commands += [f"markers {f}" for f in range(len(project.frames))]
        ctx, lines = _run(project, commands)
        animations, frames = lines[:len(ticks)], lines[len(ticks):]
        shown, with_markers = set(), 0
        for index, (line, n) in enumerate(zip(animations, ticks)):
            name = project.animations[index].name
            trace, markers = _runtime_trace(line)
            self.assertEqual(trace, _editor_trace(project, index, n), f"'{name}'")
            for (animation, step, _finished, _started, _value), found in zip(trace, markers):
                self.assertEqual(found, _baked_markers(ctx, _step_render_frame(ctx, animation, step)),
                                 f"'{name}': hitboxes and points of '{project.animations[animation].name}' step {step}")
                shown.add((animation, step))
                with_markers += bool(found[0] or found[1])
        self.assertEqual(shown, {(a, s) for a, anim in enumerate(project.animations) for s in range(len(anim.aframes))},
                         "every step of every animation was shown")
        self.assertGreater(with_markers, len(shown), "the example's steps have hitboxes and points to compare")
        self.assertEqual(len(frames), len(project.frames))
        for index, line in enumerate(frames):
            self.assertEqual(snes_host.parse_markers(line.split(" ", 1)[1]),
                             _baked_markers(ctx, ctx.frame_render_frames[index]), project.frames[index].name)

    def test_markers_like_the_mega_drive_test(self):
        """The marker test's frame on its own and in a step that is mirrored and moved, and one that is turned: the
        values worked out by hand there."""
        project = marker_project()
        project.animations[0].fps = 60  # a step a video frame
        _ctx, lines = _run(project, ["markers 0", "player 0 3"])
        boxes, points = snes_host.parse_markers(lines[0].split(" ", 1)[1])
        self.assertEqual(boxes, [(0, 0, -4, -16, 8, 16), (1, 0xFFFF, 4, -12, 10, 4), (0xFF, 0xFFFF, 0, 0, 2, 2)],
                         "types and roles (a deleted type is 0xFF, no role 0xFFFF); a box without area is left out")
        self.assertEqual(points, [(0, 1, 6, -10)])
        trace, markers = _runtime_trace(lines[1])
        self.assertEqual([step for _a, step, *_rest in trace], [0, 1, 2])
        plain, mirrored, turned = markers
        self.assertEqual(plain, (boxes, points))
        self.assertEqual(mirrored[0][0], (0, 0, -1, -16, 8, 16), "flip x, then offset (3, 0)")
        self.assertEqual(mirrored[1], [(0, 1, -4, -10)], "a point marks a pixel: 3 - x - 1")
        self.assertEqual(turned[0][0], (0, 0, 0, -4, 16, 8), "90° clockwise")
        self.assertEqual(turned[1], [(0, 1, 9, 6)])


if __name__ == "__main__":
    unittest.main()
