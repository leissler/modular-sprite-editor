"""Crash recovery copies (ui/autosave.py) and images changed on disk (ui/image_watch.py)."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import Project  # noqa: E402
from ui import autosave  # noqa: E402
from ui.image_watch import changed_images, image_stamps, update_image_sizes  # noqa: E402

EXAMPLE = ROOT / "examples" / "adventurer" / "adventurer.json"


def dead_pid() -> int:
    return next(pid for pid in (999_983, 888_887, 777_773, 666_667) if not autosave.process_alive(pid))


class AutosaveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        prefs = os.path.join(self.folder.name, "preferences.ini")
        self.env = mock.patch.dict(os.environ, {"MSE_PREFERENCES_FILE": prefs})
        self.env.start()
        self.project = Project.from_json(str(EXAMPLE))

    def tearDown(self) -> None:
        self.env.stop()
        self.folder.cleanup()

    def crash(self, path: str) -> None:
        """Make a copy look as if its editor had quit unexpectedly."""
        data = json.loads(Path(path).read_text())
        data["pid"] = dead_pid()
        Path(path).write_text(json.dumps(data))

    def test_recovery_folder_follows_the_test_preferences(self) -> None:
        self.assertEqual(autosave.recovery_dir(), os.path.join(self.folder.name, "Recovery"))

    def test_one_copy_per_project_file(self) -> None:
        a = autosave.recovery_file_for("/projects/hero.json", "s1")
        self.assertEqual(a, autosave.recovery_file_for("/projects/hero.json", "s2"), "the same file in every session")
        self.assertNotEqual(a, autosave.recovery_file_for("/projects/enemy.json", "s1"))
        self.assertNotEqual(autosave.recovery_file_for(None, "s1"), autosave.recovery_file_for(None, "s2"))

    def test_running_editors_copies_are_not_offered(self) -> None:
        path = autosave.recovery_file_for(str(EXAMPLE), "s")
        autosave.write_recovery(path, self.project, str(EXAMPLE))
        self.assertEqual(autosave.stale_recoveries(), [])

    def test_a_crashed_editors_copy_is_offered_and_restores_the_project(self) -> None:
        path = autosave.recovery_file_for(str(EXAMPLE), "s")
        self.project.name = "changed before the crash"
        autosave.write_recovery(path, self.project, str(EXAMPLE))
        self.crash(path)
        stale = autosave.stale_recoveries()
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].project_path, str(EXAMPLE))
        self.assertLess(abs(stale[0].saved_at - time.time()), 60)
        restored = autosave.load_recovery(stale[0])
        self.assertEqual(restored.name, "changed before the crash")
        self.assertEqual(restored.to_dict(), self.project.to_dict())
        for asset in restored.images:
            self.assertTrue(os.path.isabs(asset.file_path) and os.path.exists(asset.file_path), "images still found")

    def test_newest_first_and_removal(self) -> None:
        first = autosave.recovery_file_for(None, "older")
        second = autosave.recovery_file_for(None, "newer")
        autosave.write_recovery(first, self.project, None)
        time.sleep(0.01)
        autosave.write_recovery(second, self.project, None)
        self.crash(first)
        self.crash(second)
        self.assertEqual([r.path for r in autosave.stale_recoveries()], [second, first])
        autosave.remove_recovery(second)
        autosave.remove_recovery(None)
        self.assertEqual([r.path for r in autosave.stale_recoveries()], [first])

    def test_damaged_copies_are_skipped(self) -> None:
        os.makedirs(autosave.recovery_dir(), exist_ok=True)
        Path(autosave.recovery_dir(), "broken.json").write_text("{not json")
        self.assertEqual(autosave.stale_recoveries(), [])

    def test_process_alive(self) -> None:
        self.assertTrue(autosave.process_alive(os.getpid()))
        self.assertFalse(autosave.process_alive(0))
        self.assertFalse(autosave.process_alive(dead_pid()))


class ImageWatchTest(unittest.TestCase):
    def test_changed_appeared_and_missing_images(self) -> None:
        known = {"a": (1, 10), "b": None, "c": (5, 50)}
        now = {"a": (2, 10), "b": (3, 30), "c": (5, 50), "new": (9, 90)}
        self.assertEqual(changed_images(known, now), ["a", "b"])
        self.assertEqual(changed_images(now, {"a": None}), ["a"])

    def test_stamps_and_sizes_follow_the_file(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            sheet = os.path.join(folder, "sheet.png")
            Image.new("RGBA", (16, 16)).save(sheet)
            project = Project()
            asset = project.create_image(sheet, 16, 16)
            before = image_stamps(project)
            time.sleep(0.01)
            Image.new("RGBA", (32, 24)).save(sheet)
            os.utime(sheet, ns=(time.time_ns(), time.time_ns() + 1_000_000))
            self.assertEqual(changed_images(before, image_stamps(project)), [asset.id])
            self.assertEqual(update_image_sizes(project, [asset.id]), [asset.id])
            self.assertEqual((asset.width, asset.height), (32, 24))
            self.assertEqual(update_image_sizes(project, [asset.id]), [], "the size is known now")


if __name__ == "__main__":
    unittest.main()
