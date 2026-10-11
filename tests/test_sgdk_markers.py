"""SGDK export of hitboxes and points: per frame and per animation step, moved like the step."""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "examples" / "sgdk" / "tools"))

from models import (  # noqa: E402
    AFrame, Animation, CollisionRect, CollisionType, ControlPoint, Frame, PointType, Project,
)


def _project():
    project = Project()
    project.collision_types = [CollisionType("ct_hurt", "Hurt", (255, 0, 0)), CollisionType("ct_hit", "Hit box", (0, 255, 0))]
    project.point_types = [PointType("pt_hand", "Hand", (0, 0, 255))]
    frame = Frame("f", "pose", collision_rects=[
        CollisionRect("c1", "ct_hurt", (-4, -16, 8, 16), role="body"),
        CollisionRect("c2", "ct_hit", (4, -12, 10, 4)),
        CollisionRect("c3", "ct_gone", (0, 0, 2, 2)),     # its type was deleted
        CollisionRect("c4", "ct_hurt", (0, 0, 0, 0)),     # no area: not exported
    ], control_points=[ControlPoint("p1", "pt_hand", 6, -10, role="weapon tip")])
    project.frames.append(frame)
    anim = Animation("a", "attack", aframes=[
        AFrame(frame_id="f", duration_frames=1),
        AFrame(frame_id="f", duration_frames=1, offset=(3, 0), flip_x=True),
        AFrame(frame_id="f", duration_frames=1, rotation_degrees=90.0),
    ])
    project.animations.append(anim)
    return project


class TestMarkerExport(unittest.TestCase):
    def setUp(self):
        import export_sgdk_example as sg

        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = sg.SGDKBakeContext(_project(), [None], Path(self.tmp.name))
        self.ctx.bake()

    def tearDown(self):
        self.tmp.cleanup()

    def markers(self, render_index):
        span = self.ctx.render_frames[render_index]
        boxes = self.ctx.boxes[span.first_box:span.first_box + span.box_count]
        points = self.ctx.points[span.first_point:span.first_point + span.point_count]
        return boxes, points

    def test_frame_markers_types_and_roles(self):
        boxes, points = self.markers(self.ctx.frame_render_frames[0])
        roles = self.ctx.role_names
        self.assertEqual(roles, ["body", "weapon tip"])
        self.assertEqual(boxes, [(0, 0, -4, -16, 8, 16), (1, 0xFFFF, 4, -12, 10, 4), (0xFF, 0xFFFF, 0, 0, 2, 2)])
        self.assertEqual(points, [(0, 1, 6, -10)])

    def test_step_markers_follow_the_step(self):
        steps = self.ctx.anim_steps
        plain, mirrored, turned = (self.markers(step[0]) for step in steps)
        self.assertEqual(plain, self.markers(self.ctx.frame_render_frames[0]))
        # Flip x then offset (3, 0): x -> 3 - x, boxes keep their size
        self.assertEqual(mirrored[0][0], (0, 0, -1, -16, 8, 16))
        self.assertEqual(mirrored[1], [(0, 1, -3, -10)])
        # 90° clockwise: (x, y) -> (-y, x)
        self.assertEqual(turned[0][0], (0, 0, 0, -4, 16, 8))
        self.assertEqual(turned[1], [(0, 1, 10, 6)])

    def test_header_defines(self):
        path = Path(self.tmp.name) / "modsprite_data.h"
        self.ctx._emit_header(path)
        text = path.read_text()
        for define in ("MS_HITBOX_HURT 0u", "MS_HITBOX_HIT_BOX 1u", "MS_POINT_HAND 0u", "MS_ROLE_BODY 0u", "MS_ROLE_WEAPON_TIP 1u"):
            self.assertIn(f"#define {define}", text)


if __name__ == "__main__":
    unittest.main()
