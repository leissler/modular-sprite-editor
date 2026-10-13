"""Copying the settings older versions kept in wx's default store into the editor's store, once (ui/preferences.py)."""

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
class AdoptOldStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)  # one per process: other test modules may have made it

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return wx.FileConfig(localFilename=path, style=wx.CONFIG_USE_LOCAL_FILE)

    def test_missing_entries_are_copied_once(self):
        from ui import preferences

        old = self.store("app", "[SceneEditor]\nScreenGuide=2\n[View]\n[View/Backdrop]\nframes=solid\n"
                                "modules=checker\n[View/Budget]\ntimeline=\n")
        new = self.store("editor", "file1=/a.json\n[View/Backdrop]\nframes=checker\n")
        self.assertEqual(preferences.adopt_old_store(new, old, "app"), 3)  # "frames" is there already
        self.assertEqual(new.ReadInt("/SceneEditor/ScreenGuide", 0), 2)
        self.assertEqual(new.Read("/View/Backdrop/frames"), "checker", "settings the editor's store has stay")
        self.assertEqual(new.Read("/View/Backdrop/modules"), "checker")
        self.assertTrue(new.HasEntry("/View/Budget/timeline"))
        self.assertEqual(new.Read("/file1"), "/a.json")
        old.Write("/SceneEditor/Later", "1")
        self.assertEqual(preferences.adopt_old_store(new, old, "app"), 0, "only once")
        self.assertFalse(new.HasEntry("/SceneEditor/Later"))


if __name__ == "__main__":
    unittest.main()
