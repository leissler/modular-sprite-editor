"""The console database: consistent entries, and the budget profiles and screen guides it now provides unchanged."""

import unittest

import consoles
import hardware_budget as hb


class DatabaseTest(unittest.TestCase):
    def test_every_entry_is_consistent(self) -> None:
        keys = [c.key for c in consoles.CONSOLES]
        self.assertEqual(len(keys), len(set(keys)))
        for console in consoles.CONSOLES:
            with self.subTest(console.key):
                self.assertTrue(console.modes and console.refresh_rates)
                self.assertIn(60, console.refresh_rates)
                for mode in console.modes:
                    self.assertGreater(mode.width, 0)
                    self.assertGreater(mode.sprites_per_screen, 0)
                    self.assertLessEqual(mode.sprites_per_line, mode.sprites_per_screen)
                for w, h in console.sprites.sizes:
                    self.assertEqual((w % console.tile_size, h % console.tile_size), (0, 0))
                for size_set in console.sprites.size_sets:
                    self.assertTrue(set(size_set) <= set(console.sprites.sizes))
                palette = console.palette
                self.assertGreaterEqual(palette.colours, 2)
                self.assertLess(palette.transparent_index, palette.colours)
                self.assertEqual(palette.visible, palette.colours - 1)
                self.assertEqual(2 ** console.sprites.bits_per_pixel, palette.colours, "a sprite pixel picks a slot")
                self.assertIn(palette.colour_model, ("rgb333", "bgr555", "fixed"))
                if palette.colour_model == "fixed":
                    self.assertGreaterEqual(len(palette.fixed_colours), palette.colours)
                for setup in console.budgets:
                    self.assertIsNotNone(console.mode(setup.mode), setup.key)
                    if setup.sizes != (0, 0):
                        self.assertIn(((setup.sizes[0],) * 2, (setup.sizes[1],) * 2), console.sprites.size_sets)

    def test_lookups(self) -> None:
        self.assertIs(consoles.console_by_key("snes"), consoles.SNES)
        self.assertIs(consoles.console_by_key("no such console"), consoles.MEGA_DRIVE)
        self.assertIs(consoles.console_by_key(None), consoles.DEFAULT)
        self.assertEqual(consoles.palette_consoles(), [consoles.MEGA_DRIVE], "only the Mega Drive has palettes so far")

    def test_the_mega_drive(self) -> None:
        md = consoles.MEGA_DRIVE
        self.assertEqual((md.palette.colours, md.palette.palettes, md.palette.visible), (16, 4, 15))
        self.assertEqual(md.sprites.tiles, 1424)
        self.assertEqual(len(md.sprites.sizes), 16, "1 to 4 tiles wide and high")
        self.assertEqual(md.exporter, "SGDK")


class ProvidedListsTest(unittest.TestCase):
    def test_budget_profiles_as_they_were(self) -> None:
        found = [(p.key, p.name, p.sprites_per_screen, p.sprites_per_line, p.pixels_per_line, p.sizes, p.vram_tiles)
                 for p in hb.PROFILES]
        self.assertEqual(found, [
            ("md_h40", "Mega Drive H40 (320 px)", 80, 20, 320, (0, 0), 1424),
            ("md_h32", "Mega Drive H32 (256 px)", 64, 16, 256, (0, 0), 1424),
            ("snes_8_16", "SNES, 8×8 and 16×16 sprites", 128, 32, 272, (8, 16), 0),
            ("snes_16_32", "SNES, 16×16 and 32×32 sprites", 128, 32, 272, (16, 32), 0),
        ])
        self.assertEqual(hb.MEGA_DRIVE_H40.max_sprite_tiles, 4)

    def test_screen_guides_in_the_order_the_preferences_keep(self) -> None:
        self.assertEqual(consoles.screen_guides(), [
            ("Mega Drive 320×224", (320, 224)), ("Mega Drive 256×224", (256, 224)), ("SNES 256×224", (256, 224)),
            ("NES 256×240", (256, 240)), ("GBA 240×160", (240, 160)), ("Game Boy 160×144", (160, 144)),
        ])


if __name__ == "__main__":
    unittest.main()
