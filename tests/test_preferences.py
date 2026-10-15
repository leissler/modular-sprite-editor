"""Settings of older versions: copied from wx's default store into the editor's store, once (ui/preferences.py), and the
Timeline's screen from before projects named their console (ui/scene_editor/panel.stored_screen)."""

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


@unittest.skipIf(wx is None, "wxPython not available")
class TimelineScreenTest(unittest.TestCase):
    """The Timeline's Screen setting (ui/scene_editor/panel.stored_screen)."""

    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def screen(self, guide=None, screen=None):
        from ui.scene_editor.panel import stored_screen

        config = wx.FileConfig(localFilename=os.path.join(self.tmp.name, f"{guide}-{screen}"),
                               style=wx.CONFIG_USE_LOCAL_FILE)
        if guide is not None:
            config.WriteInt("/SceneEditor/ScreenGuide", guide)
        if screen is not None:
            config.Write("/SceneEditor/Screen", screen)
        return stored_screen(config)

    def test_an_older_editors_screen_follows_the_project(self):
        """Up to 0.9 the editor kept one screen for every project, a position in its list (6: the Game Boy's): a Mega
        Drive project showed the Game Boy's screen as a comparison nobody asked for."""
        self.assertEqual(self.screen(guide=6), "project")
        self.assertEqual(self.screen(guide=1), "project")
        self.assertEqual(self.screen(guide=0), "", "no outline stays no outline")
        self.assertEqual(self.screen(guide=99), "")
        self.assertEqual(self.screen(), "", "nothing stored: no outline")

    def test_a_choice_since_0_10_stays(self):
        self.assertEqual(self.screen(guide=6, screen=""), "")
        self.assertEqual(self.screen(guide=6, screen="project"), "project")
        self.assertEqual(self.screen(guide=1, screen="Game Boy 160×144"), "Game Boy 160×144", "a comparison")


if __name__ == "__main__":
    unittest.main()
