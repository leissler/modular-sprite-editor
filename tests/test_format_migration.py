import json
import os
import subprocess
import sys
import tempfile
import unittest

from models import PROJECT_FORMAT_VERSION, Project, migrate_project_dict


def _legacy_project_dict():
    return {
        "name": "Legacy",
        "images": [],
        "modules": [
            {"id": "m_line", "name": "line", "image_id": "missing", "rect": [0, 0, 10, 20], "pivot": [0, 0],
             "type": "MD_LINE", "params": [5, 20]},
            {"id": "m_tri", "name": "tri", "image_id": "missing", "rect": [0, 0, 10, 10], "pivot": [0, 0],
             "type": "MD_TRIANGLE", "params": [10, 0, 0, 10]},
        ],
        "frames": [
            {
                "id": "f1",
                "name": "frame",
                "fmodules": [],
                "collision_rects": [{"id": "c1", "type_id": "t", "rect": [0, 0, 4, 4]}],
                "control_points": [{"id": "p1", "type_id": "t", "x": 1, "y": 2, "name": "hand"}],
            }
        ],
        "animations": [
            {"id": "a1", "name": "anim", "aframes": [
                {"frame_id": "f1", "duration_ms": 300},
                {"frame_id": "f1", "duration_ms": 2},
            ]}
        ],
        "timeline_scenes": [
            {"id": "s1", "name": "scene", "fps": 10, "duration_frames": 50, "objects": [
                {"id": "o1", "name": "obj", "playback_offset": 5,
                 "keyframes": [{"id": "k1", "time": 20}]}
            ]}
        ],
        "custom_tool_data": {"keep": True},
    }


class TestFormatMigration(unittest.TestCase):
    def test_v1_migration_canonicalizes_legacy_fields(self):
        source = _legacy_project_dict()
        migrated, notes = migrate_project_dict(source)

        self.assertEqual(migrated["format_version"], PROJECT_FORMAT_VERSION)
        self.assertEqual(list(migrated.keys())[0], "format_version")
        self.assertNotIn("format_version", source, "input dict must not be mutated")
        self.assertEqual(migrated["custom_tool_data"], {"keep": True})

        aframes = migrated["animations"][0]["aframes"]
        self.assertEqual([af["duration_frames"] for af in aframes], [3, 2])
        self.assertTrue(all("duration_ms" not in af for af in aframes))

        cp = migrated["frames"][0]["control_points"][0]
        self.assertEqual(cp["role"], "hand")
        self.assertNotIn("name", cp)
        self.assertEqual(migrated["frames"][0]["collision_rects"][0]["role"], "")

        scene = migrated["timeline_scenes"][0]
        self.assertAlmostEqual(scene["duration_seconds"], 5.0)
        self.assertAlmostEqual(scene["objects"][0]["playback_offset"], 0.5)
        self.assertAlmostEqual(scene["objects"][0]["keyframes"][0]["time"], 2.0)

        line = migrated["modules"][0]["params"]
        self.assertEqual(line, [0.0, 0.0, 50.0, 100.0])
        tri = migrated["modules"][1]["params"]
        self.assertEqual(tri, [0.0, 0.0, 100.0, 0.0, 0.0, 100.0])
        self.assertTrue(notes)

    def test_migrated_dict_loads_like_legacy_dict(self):
        legacy_project = Project.from_dict(_legacy_project_dict())
        migrated, _notes = migrate_project_dict(_legacy_project_dict())
        migrated_project = Project.from_dict(migrated)

        legacy_out = legacy_project.to_dict()
        migrated_out = migrated_project.to_dict()
        self.assertEqual(legacy_out, migrated_out)

    def test_current_version_is_idempotent(self):
        migrated, _ = migrate_project_dict(_legacy_project_dict())
        again, notes = migrate_project_dict(migrated)
        self.assertEqual(migrated, again)
        self.assertEqual(notes, [])

    def test_newer_version_is_left_alone_with_warning(self):
        data = {"format_version": PROJECT_FORMAT_VERSION + 1, "frames": [], "modules": []}
        migrated, notes = migrate_project_dict(data)
        self.assertEqual(migrated["format_version"], PROJECT_FORMAT_VERSION + 1)
        self.assertEqual(len(notes), 1)
        project = Project.from_dict(data)
        self.assertEqual(len(project.load_notes), 1)

    def test_saved_project_carries_version(self):
        project = Project.from_dict(_legacy_project_dict())
        self.assertEqual(project.to_dict()["format_version"], PROJECT_FORMAT_VERSION)

    def test_migration_tool_preserves_unknown_keys_and_backs_up(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = os.path.join(tmpdir, "legacy.json")
            other_path = os.path.join(tmpdir, "retro.json")
            with open(project_path, "w", encoding="utf-8") as f:
                json.dump(_legacy_project_dict(), f)
            with open(other_path, "w", encoding="utf-8") as f:
                json.dump({"ProjectType": "RetroAnimator", "Frames": {}}, f)
            with open(other_path, "rb") as f:
                other_before = f.read()

            backup = os.path.join(tmpdir, "backup.zip")
            subprocess.run(
                [sys.executable, os.path.join(repo_root, "tools", "migrate_projects.py"), "--backup-zip", backup, tmpdir],
                check=True,
                capture_output=True,
            )

            with open(project_path, "r", encoding="utf-8") as f:
                upgraded = json.load(f)
            self.assertEqual(upgraded["format_version"], PROJECT_FORMAT_VERSION)
            self.assertEqual(upgraded["custom_tool_data"], {"keep": True})
            with open(other_path, "rb") as f:
                self.assertEqual(f.read(), other_before)
            self.assertTrue(os.path.exists(backup))


if __name__ == "__main__":
    unittest.main()
