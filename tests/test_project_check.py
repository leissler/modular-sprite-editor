"""Check Project: issues for things exports would drop or get wrong, and their fixes (project_check.py)."""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import project_check as pc  # noqa: E402
from models import CollisionRect, ControlPoint, EventType, Project, StepEvent, TimelineKeyframe  # noqa: E402
from ui.module_editor import ops as module_ops  # noqa: E402

POP = ROOT / "examples" / "sgdk" / "PoP_WW.json"
SONIC = ROOT / "examples" / "sonic" / "sonic.json"
ADVENTURER = ROOT / "examples" / "adventurer" / "adventurer.json"


def codes(issues):
    return sorted(issue.code for issue in issues)


class ExamplesTest(unittest.TestCase):
    def test_examples_are_clean(self) -> None:
        self.assertEqual(codes(pc.check_project(Project.from_json(str(POP)))), [])
        self.assertEqual(codes(pc.check_project(Project.from_json(str(SONIC)))), [])
        issues = pc.check_project(Project.from_json(str(ADVENTURER)))
        self.assertEqual(codes(issues), ["too-many-colours"])
        self.assertIn("21 colours", issues[0].text, "transparent pixels do not count as a colour")


class BrokenReferencesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project.from_json(str(POP))

    def test_deleted_modules_and_frames(self) -> None:
        counts = module_ops.part_counts(self.project)
        victim = max(counts, key=counts.get)
        module_ops.delete_modules(self.project, [victim])
        shown = {af.frame_id for a in self.project.animations for af in a.aframes}
        frame = next(f for f in self.project.frames if f.id in shown)
        self.project.frames.remove(frame)
        issues = pc.check_project(self.project, pixels=False)
        self.assertIn("missing-part", codes(issues))
        self.assertIn("missing-step", codes(issues))
        self.assertTrue(all(i.level == pc.ERROR for i in issues if i.code in ("missing-part", "missing-step")))
        part_issue = next(i for i in issues if i.code == "missing-part")
        self.assertEqual(part_issue.target[0], "frame")
        self.assertGreater(pc.fix(self.project, part_issue), 0)
        remaining = [i for i in pc.check_project(self.project, pixels=False) if i.code == "missing-part"]
        self.assertEqual(len(remaining), len([i for i in issues if i.code == "missing-part"]) - 1, "only that frame")
        self.assertGreater(pc.fix_all(self.project, pc.check_project(self.project, pixels=False)), 0)
        self.assertEqual([i for i in pc.check_project(self.project, pixels=False) if i.level == pc.ERROR], [])

    def test_removing_steps_keeps_loop_from_on_its_step(self) -> None:
        anim = next(a for a in self.project.animations
                    if len(a.aframes) >= 4 and a.aframes[0].frame_id != a.aframes[2].frame_id)
        anim.playback_type = "loop"
        anim.loop_start = 2
        anchor = anim.aframes[2]
        gone = anim.aframes[0].frame_id  # the first step's frame is deleted; the loop's first step stays
        self.project.frames = [f for f in self.project.frames if f.id != gone]
        pc.fix(self.project, next(i for i in pc.check_project(self.project, pixels=False)
                                  if i.code == "missing-step" and i.target == ("animation", anim.id)))
        self.assertIs(anim.aframes[anim.loop_start], anchor)

    def test_mappings_follow_ups_scenes_events(self) -> None:
        p = self.project
        mapping = p.mappings[0]
        source = next(iter(mapping.map))
        target = mapping.map[source]
        p.modules = [m for m in p.modules if m.id != target]
        mapping.map["deleted_source"] = None
        anim, other = p.animations[0], p.animations[1]
        anim.next_animation_id = "deleted_animation"
        other.aframes[0].events.append(StepEvent(type_id="deleted_event"))
        scene = p.timeline_scenes[0]
        scene.objects[0].mapping_id = "deleted_mapping"
        scene.objects[1].source_id = "deleted_animation"
        scene.objects[0].keyframes.append(TimelineKeyframe(id="swap", time=1.0, source_type="frame",
                                                           source_id="deleted_frame"))
        found = codes(pc.check_project(p, pixels=False))
        for code in ("missing-replacement", "dead-mapping-entries", "missing-follow-up", "unknown-event",
                     "missing-object-mapping", "missing-scene-source"):
            self.assertIn(code, found)
        pc.fix_all(p, pc.check_project(p, pixels=False))
        self.assertNotIn(source, mapping.map, "the module shows its original again")
        self.assertNotIn("deleted_source", mapping.map)
        self.assertIsNone(anim.next_animation_id)
        self.assertEqual(other.aframes[0].events, [e for e in other.aframes[0].events if e.type_id != "deleted_event"])
        self.assertIsNone(scene.objects[0].mapping_id)
        self.assertEqual((scene.objects[1].source_type, scene.objects[1].source_id), ("none", None))
        swap = next(k for k in scene.objects[0].keyframes if k.id == "swap")
        self.assertIsNone(swap.source_id, "the key stays, without its swap")
        self.assertEqual(codes(pc.check_project(p, pixels=False)), [])


class MarkersAndNamesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project.from_json(str(POP))
        self.frame = self.project.frames[0]

    def test_empty_unknown_and_duplicate_markers(self) -> None:
        hurt = self.project.collision_types[0].id
        self.frame.collision_rects.append(CollisionRect(id="empty", type_id=hurt, rect=(0, 0, 0, 5)))
        self.frame.collision_rects.append(CollisionRect(id="lost", type_id="deleted_type", rect=(0, 0, 4, 4)))
        role = self.frame.collision_rects[0].role or "body"
        self.frame.collision_rects[0].role = role
        self.frame.collision_rects.append(CollisionRect(id="twin", type_id=self.frame.collision_rects[0].type_id,
                                                        rect=(1, 1, 2, 2), role=role))
        self.frame.control_points.append(ControlPoint(id="pt", type_id="deleted_point_type", x=0, y=0))
        found = codes(pc.check_project(self.project, pixels=False))
        self.assertIn("empty-hitbox", found)
        self.assertIn("unknown-type", found)
        self.assertIn("duplicate-role", found)
        pc.fix_all(self.project, pc.check_project(self.project, pixels=False))
        self.assertNotIn("empty", [cr.id for cr in self.frame.collision_rects])

    def test_names_that_clash_in_the_game_code(self) -> None:
        self.project.event_types.append(EventType(id="e1", name="Hit", color=(1, 1, 1)))
        issues = [i for i in pc.check_project(self.project, pixels=False) if i.code == "name-clash"]
        self.assertEqual(len(issues), 1)
        self.assertIn("MS_EVENT_HIT", issues[0].text)
        self.assertEqual(pc.c_symbols(["hit", "Hit", "foot step", "3d"], "MS_EVENT_", "EVENT"),
                         ["MS_EVENT_HIT", "MS_EVENT_HIT_2", "MS_EVENT_FOOT_STEP", "MS_EVENT_E3D"])


def doubled(items, index=0):
    """Appends a copy of items[index] that keeps its id (a project file edited by hand)."""
    twin = copy.deepcopy(items[index])
    if hasattr(twin, "name"):
        twin.name = f"{twin.name} copy"
    items.append(twin)
    return twin


def id_issues(project):
    return [i for i in pc.check_project(project, pixels=False) if i.code == "duplicate-id"]


class DuplicateIdsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project.from_json(str(POP))

    def test_lists_everything_refers_to(self) -> None:
        p = self.project
        frame = next(f for f in p.frames if any(af.frame_id == f.id for a in p.animations for af in a.aframes))
        self.assertIs(p.get_frame(frame.id), frame)  # the lookup remembers where the id is
        frame_twin = doubled(p.frames, p.frames.index(frame))
        doubled(p.modules, 0)
        doubled(p.modules, 1)
        type_twin = doubled(p.collision_types)
        issues = {i.fix: i for i in id_issues(p)}
        self.assertEqual(set(issues), {"new-ids-frames", "new-ids-modules", "new-ids-collision_types"})
        self.assertTrue(all(i.level == pc.ERROR for i in issues.values()))
        self.assertEqual(issues["new-ids-frames"].target, ("frame", frame.id))
        self.assertIn(f"Frames '{frame.name}' and '{frame.name} copy' have the same id", issues["new-ids-frames"].text)
        self.assertIn(f"keeps '{frame.name}'", issues["new-ids-frames"].text)
        self.assertIn("4 modules have doubled ids", issues["new-ids-modules"].text)
        self.assertIn("and 1 more", issues["new-ids-modules"].text)
        self.assertIsNone(issues["new-ids-collision_types"].target, "no tab to go to for types")

        old_id = frame.id
        self.assertEqual(pc.fix(p, issues["new-ids-frames"]), 1)
        self.assertEqual(frame.id, old_id, "the first keeps the id, so its animations still show it")
        self.assertTrue(frame_twin.id.startswith("frm_") and frame_twin.id != old_id)
        self.assertIs(p.get_frame(frame.id), frame, "whatever refers to the id shows the first")
        self.assertIs(p.get_frame(frame_twin.id), frame_twin)
        self.assertEqual({i.fix for i in id_issues(p)}, {"new-ids-modules", "new-ids-collision_types"}, "only frames")
        old_type = type_twin.id
        self.assertEqual(pc.fix_all(p, id_issues(p)), 3)
        self.assertNotEqual(type_twin.id, old_type)
        self.assertTrue(all(cr.type_id != type_twin.id for f in p.frames for cr in f.collision_rects))
        self.assertEqual(codes(pc.check_project(p, pixels=False)), [], "the copies are simply unused now")

    def test_parts_points_scene_objects_and_keys(self) -> None:
        p = self.project
        first, second = p.frames[0], p.frames[1]
        part_twin = doubled(first.fmodules)
        doubled(first.collision_rects)
        doubled(second.fmodules)
        scene = p.timeline_scenes[0]
        parent = scene.objects[0]
        child = copy.deepcopy(scene.objects[1])
        child.id, child.parent_id = "child", parent.id
        scene.objects.append(child)
        object_twin = doubled(scene.objects, 0)
        key_twin = doubled(parent.keyframes)
        issues = id_issues(p)
        notes = [i for i in issues if i.level == pc.INFO]
        self.assertEqual(sorted(i.target for i in notes),
                         sorted([("frame", first.id), ("frame", second.id), ("scene", scene.id)]))
        self.assertIn("(2 parts and 2 hitboxes)", next(i for i in notes if i.target == ("frame", first.id)).text)
        errors = [i for i in issues if i.level == pc.ERROR]
        self.assertEqual([i.target for i in errors], [("scene", scene.id)], "objects: exports mix them up")

        self.assertEqual(pc.fix(p, next(i for i in notes if i.target == ("frame", first.id))), 2)
        self.assertTrue(part_twin.id.startswith("fmod_"))
        self.assertEqual(_doubled_ids(first.fmodules) | _doubled_ids(first.collision_rects), set())
        self.assertEqual(len(_doubled_ids(second.fmodules)), 1, "only that frame")
        self.assertEqual(pc.fix(p, errors[0]), 2, "the object and the key")
        self.assertTrue(object_twin.id.startswith("tlo_") and key_twin.id.startswith("tlk_"))
        self.assertIs(scene.get_object(child.parent_id), parent, "attached objects follow the first")
        pc.fix_all(p, id_issues(p))
        self.assertEqual(id_issues(p), [])


def _doubled_ids(items):
    ids = [item.id for item in items]
    return {i for i in ids if ids.count(i) > 1}


class ImagesTest(unittest.TestCase):
    def test_missing_outside_and_half_transparent(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            sheet = os.path.join(folder, "sheet.png")
            image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            image.putpixel((1, 1), (255, 0, 0, 255))
            image.putpixel((2, 2), (0, 255, 0, 128))
            image.save(sheet)
            project = Project()
            asset = project.create_image(sheet, 16, 16)
            module_ops.create_image_module(project, asset.id, (8, 8, 16, 16), name="wide")
            missing = project.create_image(os.path.join(folder, "gone.png"), 8, 8)
            module_ops.create_image_module(project, missing.id, (0, 0, 8, 8), name="lost")
            issues = pc.check_project(project)
            found = {i.code: i for i in issues}
            self.assertEqual(found["missing-image"].level, pc.ERROR)
            self.assertIn("Its module draws nothing", found["missing-image"].text)
            self.assertEqual(found["module-outside-image"].target[1], project.modules[0].id)
            self.assertIn("1 half-transparent pixel", found["half-transparent"].text)
            self.assertEqual(issues[0].level, pc.ERROR, "errors come first")

    def test_tiles(self) -> None:
        self.assertEqual(pc.tile_issue(309).level, pc.INFO)
        self.assertEqual(pc.tile_issue(1200).level, pc.WARNING)
        self.assertEqual(pc.tile_issue(2000).level, pc.ERROR)


if __name__ == "__main__":
    unittest.main()
