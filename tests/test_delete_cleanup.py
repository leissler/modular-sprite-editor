"""Deleting with "remove uses too": nothing is left pointing at what was deleted (module / frame / scene ops)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import project_check as pc  # noqa: E402
from models import Project, TimelineKeyframe  # noqa: E402
from ui.frame_editor import ops as frame_ops  # noqa: E402
from ui.module_editor import ops as module_ops  # noqa: E402
from ui.scene_editor import ops as scene_ops  # noqa: E402

POP = ROOT / "examples" / "sgdk" / "PoP_WW.json"


def errors_and_warnings(project):
    return [i for i in pc.check_project(project, pixels=False) if i.level in (pc.ERROR, pc.WARNING)]


class DeleteCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project.from_json(str(POP))

    def test_modules_and_their_parts_entries_and_scene_uses(self) -> None:
        p = self.project
        mapping = p.mappings[0]
        source, target = next(iter(mapping.map.items()))
        counts = module_ops.part_counts(p)
        used = max(counts, key=counts.get)
        scene = p.timeline_scenes[0]
        obj = scene_ops.add_object(p, scene, "module", used, 0)
        doomed = [used, target]
        self.assertEqual(module_ops.scene_uses(p, doomed), 1, "the delete prompt counts the object")
        self.assertIn("1 timeline object", module_ops.describe_usage(*module_ops.usage(p, doomed), 1))
        parts, entries, scene_uses = module_ops.remove_module_uses(p, doomed)
        module_ops.delete_modules(p, doomed)
        self.assertEqual(parts, counts[used] + counts.get(target, 0))
        self.assertGreaterEqual(entries, 1)
        self.assertEqual(scene_uses, 1)
        self.assertEqual(obj.source_type, "none")
        self.assertEqual(module_ops.scene_uses(p, doomed), 0)
        self.assertNotIn(source, mapping.map, "the replaced module shows its original again")
        self.assertEqual(errors_and_warnings(p), [])

    def test_frame_and_its_steps_nested_parts_and_key_swaps(self) -> None:
        p = self.project
        frame = next(f for f in p.frames if any(af.frame_id == f.id for a in p.animations for af in a.aframes))
        holder = next(f for f in p.frames if f is not frame)
        self.assertIsNotNone(frame_ops.add_part(p, holder, "frame", frame.id, (0, 0)), "nest the frame in another")
        scene = p.timeline_scenes[0]
        obj = scene.objects[0]
        obj.keyframes.append(TimelineKeyframe(id="swap", time=1.0, source_type="frame", source_id=frame.id))
        steps_before = sum(1 for a in p.animations for af in a.aframes if af.frame_id == frame.id)
        steps, nested, scene_uses = frame_ops.remove_frame_uses(p, frame.id)
        frame_ops.delete_frame(p, frame.id)
        self.assertEqual(steps, steps_before)
        self.assertEqual(nested, 1)
        self.assertEqual(scene_uses, 1)
        swap = next(k for k in obj.keyframes if k.id == "swap")
        self.assertIsNone(swap.source_id)
        self.assertEqual(errors_and_warnings(p), [])

    def test_keep_as_missing_is_what_check_project_reports(self) -> None:
        p = self.project
        frame = next(f for f in p.frames if any(af.frame_id == f.id for a in p.animations for af in a.aframes))
        frame_ops.delete_frame(p, frame.id)
        self.assertIn("missing-step", [i.code for i in errors_and_warnings(p)])


if __name__ == "__main__":
    unittest.main()
