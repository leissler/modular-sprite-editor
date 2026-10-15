"""The theme (ui/theme.py): its colours, the setting in the preferences, controls and listeners following a change."""

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
class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)  # one per process: other test modules may have made it

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(self.tmp.name, "prefs.ini")
        self.store = wx.FileConfig(localFilename=path, style=wx.CONFIG_USE_LOCAL_FILE)
        self.previous = wx.Config.Set(self.store)  # never the user's own store

    def tearDown(self):
        wx.Config.Set(self.previous)
        self.store.Flush()  # unsaved, it would be saved at exit into the deleted folder (an error dialog that blocks)
        self.tmp.cleanup()

    def test_every_colour_has_a_dark_and_a_light_version(self):
        from ui import theme

        for name, versions in theme.COLOURS.items():
            with self.subTest(name=name):
                self.assertEqual(len(versions), 2)
                for rgb in versions:
                    self.assertEqual(len(rgb), 3)
                    self.assertTrue(all(0 <= c <= 255 for c in rgb))
        dark, light = theme.Palette(True), theme.Palette(False)
        self.assertEqual(dark.rgb("row"), theme.COLOURS["row"][0])
        self.assertEqual(light.rgb("row"), theme.COLOURS["row"][1])
        self.assertEqual(theme.on("text", False), theme.COLOURS["text"][1])
        self.assertEqual(light.text, wx.Colour(*theme.COLOURS["text"][1]))

    def test_the_setting_is_kept_and_restyles_controls(self):
        from ui import theme

        t = theme.Theme()
        t.load()
        self.assertEqual(t.mode, theme.SYSTEM, "Like the system without a setting")
        frame = wx.Frame(None)
        try:
            label = t.style(wx.StaticText(frame, label="hint"), fg="hint")
            calls = []
            t.on_change(lambda: calls.append(t.dark))
            target = theme.LIGHT if t.dark else theme.DARK
            t.set_mode(target)
            self.assertEqual(self.store.Read(theme.CONFIG_KEY, ""), target)
            self.assertEqual(t.dark, target == theme.DARK)
            self.assertEqual(calls, [t.dark], "listeners hear of the change")
            self.assertEqual(label.GetForegroundColour(), t.hint, "styled controls take the new colours")
            self.assertEqual(t.row, t.palette.row)

            t.system_changed()  # a chosen theme ignores the system's appearance
            self.assertEqual(calls, [t.dark])
            t.set_mode(target)  # the same colours again: nothing to redraw
            self.assertEqual(len(calls), 1)

            again = theme.Theme()
            again.load()
            self.assertEqual((again.mode, again.dark), (target, t.dark), "the next start reads the setting")
            label.Destroy()
            t.set_mode(theme.DARK if target == theme.LIGHT else theme.LIGHT)  # a destroyed control is left out
            self.assertEqual(len(t._styled), 0)
        finally:
            theme._set_macos_appearance(theme.SYSTEM)
            frame.Destroy()

    def test_unknown_settings_mean_like_the_system(self):
        from ui import theme

        self.store.Write(theme.CONFIG_KEY, "purple")
        t = theme.Theme()
        t.load()
        self.assertEqual(t.mode, theme.SYSTEM)
        self.assertEqual(theme.LABELS[theme.SYSTEM], "Like the system")


if __name__ == "__main__":
    unittest.main()
