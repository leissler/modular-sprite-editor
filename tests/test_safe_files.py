"""Saving never leaves a damaged file behind (safe_files.write_text_atomically, Project.to_json)."""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import Project  # noqa: E402
from safe_files import backup_path, write_text_atomically  # noqa: E402

EXAMPLE = ROOT / "examples" / "adventurer" / "adventurer.json"


class SafeFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.dir = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def leftovers(self):
        return sorted(p.name for p in self.dir.iterdir() if p.name.endswith(".tmp"))

    def test_writes_new_file_and_replaces_with_backup(self) -> None:
        path = self.dir / "a.json"
        write_text_atomically(str(path), "first", keep_backup=True)
        self.assertEqual(path.read_text(), "first")
        self.assertFalse(Path(backup_path(str(path))).exists(), "no backup of a file that did not exist")
        write_text_atomically(str(path), "second", keep_backup=True)
        self.assertEqual(path.read_text(), "second")
        self.assertEqual(Path(backup_path(str(path))).read_text(), "first")
        self.assertEqual(self.leftovers(), [])

    def test_keeps_permissions(self) -> None:
        if sys.platform == "win32":
            self.skipTest("POSIX permissions")
        path = self.dir / "shared.json"
        path.write_text("old")
        os.chmod(path, 0o664)
        write_text_atomically(str(path), "new")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o664)

    def test_follows_symlinks(self) -> None:
        if sys.platform == "win32":
            self.skipTest("symlinks need privileges on Windows")
        real = self.dir / "real.json"
        real.write_text("old")
        link = self.dir / "link.json"
        link.symlink_to(real)
        write_text_atomically(str(link), "new")
        self.assertTrue(link.is_symlink())
        self.assertEqual(real.read_text(), "new")

    def test_failed_project_save_keeps_the_old_file(self) -> None:
        path = self.dir / "adventurer.json"
        path.write_bytes(EXAMPLE.read_bytes())
        before = path.read_bytes()
        project = Project.from_json(str(path))
        project.animations = []
        project.name = {"json", "cannot", "write", "a", "set"}  # type: ignore[assignment]
        with self.assertRaises(TypeError):
            project.to_json(str(path))
        self.assertEqual(path.read_bytes(), before, "the project file is untouched")
        self.assertEqual(self.leftovers(), [])
        self.assertFalse(Path(backup_path(str(path))).exists())

    def test_project_save_keeps_the_previous_version(self) -> None:
        path = self.dir / "adventurer.json"
        path.write_bytes(EXAMPLE.read_bytes())
        project = Project.from_json(str(path))
        project.name = "renamed"
        project.to_json(str(path))
        self.assertEqual(json.loads(path.read_text())["name"], "renamed")
        self.assertEqual(Path(backup_path(str(path))).read_bytes(), EXAMPLE.read_bytes())
        project.to_json(str(path), keep_backup=False)
        self.assertEqual(Path(backup_path(str(path))).read_bytes(), EXAMPLE.read_bytes(), "unchanged without a backup")


if __name__ == "__main__":
    unittest.main()
