"""Where a project was left, kept in the preferences per project file (ui/view_memory.py)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import wx
except ImportError:  # pragma: no cover
    wx = None


@unittest.skipIf(wx is None, "wxPython not available")
class ViewMemoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)  # one per process: other test modules may have made it

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = wx.FileConfig(localFilename=os.path.join(self.tmp.name, "prefs"), style=wx.CONFIG_USE_LOCAL_FILE)

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_project_keeps_its_own(self):
        from ui import view_memory

        a, b = os.path.join(self.tmp.name, "a.json"), os.path.join(self.tmp.name, "b.json")
        view_memory.save(self.config, a, {"tab": 2, "tabs": {"Frames": {"frame": "f1"}}})
        view_memory.save(self.config, b, {"tab": 4})
        self.assertEqual(view_memory.load(self.config, a), {"tab": 2, "tabs": {"Frames": {"frame": "f1"}}})
        self.assertEqual(view_memory.load(self.config, b), {"tab": 4})
        self.assertEqual(view_memory.load(self.config, os.path.join(self.tmp.name, "c.json")), {})
        self.assertEqual(view_memory.load(self.config, None), {}, "an unsaved project has none")
        view_memory.save(self.config, None, {"tab": 1})  # nothing to keep it under
        self.assertEqual(view_memory.load(self.config, a)["tab"], 2)

    def test_the_projects_opened_longest_ago_are_forgotten(self):
        from ui import view_memory

        paths = [os.path.join(self.tmp.name, f"p{i}.json") for i in range(view_memory.KEEP + 3)]
        for i, path in enumerate(paths):
            view_memory.save(self.config, path, {"tab": i % 6})
        view_memory.save(self.config, paths[0], {"tab": 5})  # opened again: kept, the next three are dropped
        self.assertEqual(view_memory.load(self.config, paths[0]), {"tab": 5})
        for path in paths[1:4]:
            self.assertEqual(view_memory.load(self.config, path), {})
            self.assertFalse(self.config.HasEntry(view_memory.PREFIX + view_memory.key_of(path)))
        self.assertEqual(view_memory.load(self.config, paths[-1]), {"tab": (len(paths) - 1) % 6})

    def test_broken_entries_read_as_nothing(self):
        from ui import view_memory

        path = os.path.join(self.tmp.name, "a.json")
        self.config.Write(view_memory.PREFIX + view_memory.key_of(path), "{not json")
        self.assertEqual(view_memory.load(self.config, path), {})
        self.config.Write(view_memory.PREFIX + view_memory.key_of(path), "[1, 2]")
        self.assertEqual(view_memory.load(self.config, path), {})
        self.config.Write(view_memory.ORDER_KEY, "{}")
        view_memory.save(self.config, path, {"tab": 1})  # a broken order list starts again
        self.assertEqual(view_memory.load(self.config, path), {"tab": 1})

    def test_views_and_ids_are_checked(self):
        from ui import view_memory

        view = ((12.5, -3.0), 4.0)
        self.assertEqual(view_memory.parse_view(view_memory.view_dict(view)), view)
        for broken in (None, [], {"pan": [1]}, {"pan": [1, 2], "zoom": 0}, {"pan": ["x", 2], "zoom": 2},
                       {"pan": [1, 2], "zoom": float("nan")}, {"pan": [1e9, 2], "zoom": 2}, {"zoom": 2}):
            self.assertIsNone(view_memory.parse_view(broken), broken)
        self.assertEqual(view_memory.ids(["a", 3, None, "b"]), ["a", "b"])
        self.assertEqual(view_memory.ids("ab"), [])
        self.assertIsNone(view_memory.text(3))


if __name__ == "__main__":
    unittest.main()
