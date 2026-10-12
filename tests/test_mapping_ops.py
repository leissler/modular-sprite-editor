"""Mappings tab operations (ui/mapping_editor/ops.py)."""

import unittest

from models import FModule, Frame, ImageAsset, Module, ModuleMapping, Project
from ui.mapping_editor import ops


def _project():
    project = Project()
    project.images += [ImageAsset("red", "red.png", 32, 32), ImageAsset("blue", "blue.png", 32, 32)]
    project.modules += [
        Module("head_red", "head_red", "red", (0, 0, 8, 8), (4, 4)),
        Module("body_red", "body_red", "red", (8, 0, 8, 16), (4, 8)),
        Module("head_blue", "head_blue", "blue", (0, 0, 8, 8), (4, 4)),
        Module("body_blue", "body_blue", "blue", (8, 0, 8, 16), (4, 8)),
        Module("cape_red", "cape_red", "red", (16, 0, 8, 8), (0, 0)),
    ]
    torso = Frame("torso", "torso", [FModule("p1", "module", "body_red", (0, 0))])
    hero = Frame("hero", "hero", [FModule("p2", "module", "head_red", (0, -8)), FModule("p3", "frame", "torso", (0, 0))])
    other = Frame("other", "other", [FModule("p4", "module", "cape_red", (0, 0))])
    project.frames += [torso, hero, other]
    return project


class TestMappingOps(unittest.TestCase):
    def test_states_assign_reset(self):
        project = _project()
        mapping = ModuleMapping("m", "Blue")
        self.assertEqual(ops.state(project, mapping, "head_red"), ops.ORIGINAL)
        self.assertEqual(ops.assign(mapping, ["head_red", "body_red"], "head_blue"), 2)
        self.assertEqual(ops.state(project, mapping, "body_red"), ops.REPLACED)
        self.assertEqual(ops.assign(mapping, ["cape_red"], None), 1)
        self.assertEqual(ops.state(project, mapping, "cape_red"), ops.HIDDEN)
        mapping.map["body_red"] = "gone"
        self.assertEqual(ops.state(project, mapping, "body_red"), ops.MISSING)
        self.assertEqual(ops.counts(project, mapping), (1, 1, 1))
        self.assertEqual(ops.describe(project, mapping), "1 replaced · 1 hidden · 1 missing")
        self.assertEqual(ops.assign(mapping, ["head_red"], "head_red"), 1)  # to itself = original
        self.assertNotIn("head_red", mapping.map)
        self.assertEqual(ops.reset(mapping, ["cape_red", "head_red"]), 1)

    def test_match_by_position(self):
        project = _project()
        mapping = ModuleMapping("m", "Blue")
        self.assertEqual(ops.match_by_position(project, mapping, "red", "blue"), 2)
        self.assertEqual(mapping.map, {"head_red": "head_blue", "body_red": "body_blue"})

    def test_match_by_name(self):
        project = _project()
        mapping = ModuleMapping("m", "Blue")
        pairs = ops.match_by_name(project, mapping, "_red", "_blue")
        self.assertEqual(sorted(pairs), [("body_red", "body_blue"), ("head_red", "head_blue")])
        mapping.map.clear()
        self.assertEqual(ops.match_by_name(project, mapping, "_red", "_blue", ["head_red"]), [("head_red", "head_blue")])

    def test_frames_using_follows_nesting(self):
        project = _project()
        self.assertEqual([f.id for f in ops.frames_using(project, ["body_red"])], ["torso", "hero"])
        self.assertEqual([f.id for f in ops.frames_using(project, ["cape_red"])], ["other"])

    def test_list_management(self):
        project = _project()
        a = ops.new_mapping(project)
        b = ops.duplicate_mapping(project, a.id)
        self.assertEqual(b.name, "Mapping 1 copy")
        c = ops.new_mapping(project, after_id=a.id)
        self.assertEqual([m.id for m in project.mappings], [a.id, c.id, b.id])
        ops.move_mapping(project, a.id, None)
        self.assertEqual(project.mappings[-1], a)
        project.active_mapping = b
        ops.delete_mapping(project, b.id)
        self.assertIsNone(project.active_mapping)
        a.map["deleted_module"] = "head_blue"
        self.assertEqual(ops.drop_dead_entries(project, a), 1)

    def test_deleting_a_mapping_lets_scene_objects_inherit_again(self):
        project = _project()
        guard = ops.new_mapping(project)
        scene = project.create_timeline_scene("Fight")
        user = scene.create_object("Guard", "frame", "hero")
        user.mapping_id = guard.id
        other = scene.create_object("Prince", "frame", "hero")
        other.mapping_id = "original"
        self.assertEqual([obj.id for _s, obj in ops.scene_objects_using(project, guard.id)], [user.id])
        ops.delete_mapping(project, guard.id)
        self.assertEqual((user.mapping_id, other.mapping_id), (None, "original"))


if __name__ == "__main__":
    unittest.main()
