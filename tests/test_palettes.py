"""palettes.py: palettes in the project, sized and coloured by the console; swaps, colour cycles, the console view and
the export agree."""

import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples" / "megadrive" / "tools"))

import consoles  # noqa: E402
import palettes  # noqa: E402
import project_check as pc  # noqa: E402
from models import ColourCycle, ImageAsset, Palette, PaletteChange, PaletteSwap, Project  # noqa: E402


def _sheet(folder: Path, name: str, colours, palette_id: str = "pal_1") -> ImageAsset:
    """An image with these colours, one pixel each (more pixels for the first ones), and a transparent pixel."""
    image = Image.new("RGBA", (len(colours) + 4, 2), (0, 0, 0, 0))
    for x, rgb in enumerate(colours):
        image.putpixel((x, 0), rgb + (255,))
        image.putpixel((x, 1), (colours[0] if x < 4 else rgb) + (255,))
    path = folder / name
    image.save(path)
    return ImageAsset(name, str(path), image.width, image.height, palette_id=palette_id)


def _shades(count: int, base=(40, 60, 200)):
    return [((base[0] + 7 * i) % 256, (base[1] + 3 * i) % 256, (base[2] + 11 * i) % 256) for i in range(count)]


RED, DARK, BLUE, GREEN = (200, 0, 0), (10, 10, 10), (0, 0, 200), (0, 200, 0)


class ColoursTest(unittest.TestCase):
    def test_mega_drive_levels_and_words(self):
        self.assertEqual([palettes.md_level(v) for v in (0, 31, 32, 128, 255)], [0, 0, 36, 145, 255])
        self.assertEqual(palettes.md_word((255, 0, 0)), 0x000E)
        self.assertEqual(palettes.md_word((0, 255, 0)), 0x00E0)
        self.assertEqual(palettes.md_word((0, 0, 255)), 0x0E00)

    def test_every_colour_model(self):
        self.assertEqual(palettes.console_colour(consoles.MEGA_DRIVE.palette, (100, 150, 255)), (109, 145, 255))
        self.assertEqual(palettes.console_colour(consoles.SNES.palette, (100, 150, 255)), (98, 148, 255), "5 bits")
        self.assertEqual(palettes.console_colour(consoles.GAME_BOY.palette, (255, 255, 255)), (0x9B, 0xBC, 0x0F))
        self.assertIn(palettes.console_colour(consoles.NES.palette, (250, 0, 0)), consoles.NES.palette.fixed_colours)

    def test_the_console_sets_the_size(self):
        project = Project()
        self.assertEqual(palettes.capacity(project), 15)
        project.console = "gameboy"
        self.assertEqual(palettes.capacity(project), 3)

    def test_nearest_takes_the_first_exact_match(self):
        self.assertEqual(palettes.nearest(RED, [DARK, RED, RED]), 1)
        self.assertEqual(palettes.nearest((190, 5, 5), [DARK, RED]), 1)
        self.assertEqual(palettes.nearest(RED, []), 0)

    def test_format_6_rules(self):
        counts = Counter({DARK: 5, RED: 9, BLUE: 1})
        self.assertEqual(palettes.build_colours(counts, 15), [RED, DARK, BLUE], "most used first, no padding")
        self.assertEqual(len(palettes.build_colours(Counter({rgb: 1 for rgb in _shades(30)}), 15)), 15, "merged")
        self.assertEqual(palettes.build_colours(Counter(), 15), [])


class CyclesAndSwapsTest(unittest.TestCase):
    def setUp(self):
        self.palette = Palette("p", "P", colours=[RED, DARK, BLUE, GREEN])

    def test_a_cycle_moves_its_colours_up_one_slot_a_step(self):
        cycle = ColourCycle(first=2, count=3, frames=4)
        self.assertEqual(palettes.rotate(self.palette.colours, [cycle], None), self.palette.colours)
        self.assertEqual(palettes.rotate(self.palette.colours, [cycle], 3), self.palette.colours, "a step is 4 frames")
        self.assertEqual(palettes.rotate(self.palette.colours, [cycle], 4), [RED, GREEN, DARK, BLUE])
        self.assertEqual(palettes.rotate(self.palette.colours, [cycle], 12), self.palette.colours, "round again")
        back = ColourCycle(first=2, count=3, frames=4, reverse=True)
        self.assertEqual(palettes.rotate(self.palette.colours, [back], 4), [RED, BLUE, GREEN, DARK])
        self.assertEqual(palettes.rotate(self.palette.colours, [ColourCycle(first=3, count=5)], 99), self.palette.colours,
                         "a run past the palette's end does nothing")

    def test_a_swap_replaces_slots_and_may_bring_its_own_cycles(self):
        swap = PaletteSwap("s", "Guard", {"p": PaletteChange(colours=[None, (1, 2, 3)])})
        self.assertEqual(palettes.swapped_colours(self.palette, swap), [RED, (1, 2, 3), BLUE, GREEN])
        self.assertTrue(palettes.recolours(self.palette, swap, None))
        self.assertFalse(palettes.recolours(self.palette, None, None))
        self.palette.cycles = [ColourCycle(first=1, count=2, frames=1)]
        self.assertTrue(palettes.recolours(self.palette, None, 1))
        self.assertEqual(palettes.cycles_of(self.palette, swap), self.palette.cycles, "the palette's, unless its own")
        swap.palettes["p"].cycles = []
        self.assertFalse(palettes.recolours(self.palette, PaletteSwap("s2", "None", {"p": PaletteChange(cycles=[])}), 1))
        project = Project()
        shown = palettes.shown_colours(project, self.palette, swap, 1, console_view=True)
        self.assertEqual(shown[1], palettes.md_colour((1, 2, 3)))

    def test_recolour_maps_every_pixel_through_its_slot(self):
        image = Image.new("RGBA", (3, 1), (0, 0, 0, 0))
        image.putpixel((0, 0), RED + (255,))
        image.putpixel((1, 0), (190, 4, 4, 128))  # not in the palette: the nearest slot, its alpha kept
        out = palettes.recolour(image, [RED, DARK], [BLUE, DARK])
        self.assertEqual(out.getpixel((0, 0)), BLUE + (255,))
        self.assertEqual(out.getpixel((1, 0)), BLUE + (128,))
        self.assertEqual(out.getpixel((2, 0))[3], 0)
        opaque = palettes.recolour(image, [RED, DARK], [BLUE, DARK], opaque=True)
        self.assertEqual(opaque.getpixel((1, 0))[3], 255, "the console shows half-transparent pixels opaque")


class ProjectPalettesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.project = Project()
        self.palette = self.project.default_palette()
        self.palette.id = "pal_1"
        self.palette.colours = []  # built and emptied: the artist's from here on

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_colours_go_into_free_slots(self):
        self.project.images.append(_sheet(self.folder, "hero.png", [RED, DARK, BLUE]))
        self.assertEqual(palettes.missing_colours(self.project, self.palette), [RED, BLUE, DARK], "most used first")
        self.assertEqual(palettes.add_missing_colours(self.project, self.palette), 3)
        self.assertEqual(self.palette.colours, [RED, BLUE, DARK])
        self.assertEqual(palettes.add_missing_colours(self.project, self.palette), 0)
        self.project.images.append(_sheet(self.folder, "many.png", _shades(20)))
        self.assertEqual(palettes.add_missing_colours(self.project, self.palette), 12, "only as many as fit")
        self.assertEqual(len(self.palette.colours), 15)
        self.assertEqual(palettes.unused_slots(self.project, self.palette), [])

    def test_reordering_moves_the_swaps_and_keeps_cycles_that_stay_together(self):
        self.palette.colours = [RED, DARK, BLUE, GREEN]
        self.palette.cycles = [ColourCycle(first=1, count=2), ColourCycle(first=3, count=2)]
        swap = PaletteSwap("s", "S", {"pal_1": PaletteChange(colours=[None, None, (9, 9, 9)])})
        self.project.palette_swaps.append(swap)
        dropped = palettes.reorder(self.project, self.palette, [2, 3, 0, 1])  # blue, green, red, dark
        self.assertEqual(self.palette.colours, [BLUE, GREEN, RED, DARK])
        self.assertEqual(swap.palettes["pal_1"].colours, [(9, 9, 9)], "the replacement moved with its slot")
        self.assertEqual([(c.first, c.count) for c in self.palette.cycles], [(3, 2), (1, 2)])
        self.assertEqual(dropped, 0)
        self.assertEqual(palettes.reorder(self.project, self.palette, [1, 0, 2, 3]), 1, "a split cycle is removed")
        palettes.remove_slots(self.project, self.palette, [0])
        self.assertEqual(self.palette.colours, [BLUE, RED, DARK])

    def test_sorting(self):
        self.palette.colours = [(250, 250, 250), DARK, RED]
        self.assertEqual(palettes.sort_order(self.project, self.palette, "brightness"), [1, 2, 0])

    def test_a_palette_not_built_yet_follows_its_images(self):
        self.project.images.append(_sheet(self.folder, "hero.png", [RED, DARK]))
        self.palette.colours = None
        self.assertEqual(palettes.colours_of(self.project, self.palette), [RED, DARK])
        self.assertEqual(palettes.missing_colours(self.project, self.palette), [])
        self.assertEqual([i.code for i in pc.check_project(self.project) if i.code == "colours-not-in-palette"], [])

    def test_built_from_the_images_once(self):
        self.project.images.append(_sheet(self.folder, "hero.png", [RED, DARK]))
        self.palette.colours = None
        self.assertEqual(palettes.build_missing(self.project), [self.palette])
        self.assertEqual(self.palette.colours, [RED, DARK])
        self.assertEqual(palettes.build_missing(self.project), [], "already built")

    def test_export_entries_list_the_palettes_then_the_swaps(self):
        second = Palette("pal_2", "Slime", colours=[GREEN])
        self.palette.colours = [RED, DARK]
        self.project.palettes.append(second)
        self.project.palette_swaps.append(PaletteSwap("s", "Guard", {"pal_1": PaletteChange(colours=[BLUE])}))
        entries = palettes.export_entries(self.project)
        self.assertEqual([(e.palette_id, e.swap_id, e.name) for e in entries],
                         [("pal_1", None, "Palette 1"), ("pal_2", None, "Slime"), ("pal_1", "s", "Palette 1: Guard")])
        self.assertEqual(entries[2].colours, (BLUE, DARK))

    def test_the_preview_shows_what_the_export_stores(self):
        import export_megadrive as sg

        self.project.images.append(_sheet(self.folder, "many.png", _shades(24)))
        palettes.add_missing_colours(self.project, self.palette)
        ctx = sg.MegaDriveBakeContext(self.project, [None], self.folder / "out")
        with Image.open(self.project.images[0].file_path) as source:
            rgba = source.convert("RGBA")
        colours = ctx.palette_colours["pal_1"]
        shown = palettes.console_image(rgba, colours)
        for (x, y) in ((0, 0), (5, 0), (17, 0), (3, 1), (20, 1)):
            r, g, b, a = rgba.getpixel((x, y))
            if a:
                index = ctx._nearest_palette_index((r, g, b), "pal_1")
                self.assertEqual(shown.getpixel((x, y))[:3], palettes.md_colour(colours[index]))
        self.assertEqual(shown.getpixel((rgba.width - 1, 0))[3], 0, "transparent stays transparent")

    def test_check_project_counts_colours_per_palette(self):
        warm, cool = _shades(10, (200, 40, 20)), _shades(10, (20, 40, 200))
        self.project.images += [_sheet(self.folder, "warm.png", warm), _sheet(self.folder, "cool.png", cool)]
        found = [i for i in pc.check_project(self.project) if i.code == "too-many-colours"]
        self.assertEqual(len(found), 1)
        self.assertIn("Palette 'Palette 1' ('warm.png', 'cool.png') uses 20 colours", found[0].text)
        self.project.palettes.append(Palette("pal_2", "Cool", colours=[]))
        self.project.images[1].palette_id = "pal_2"
        issues = pc.check_project(self.project)
        self.assertEqual([i for i in issues if i.code == "too-many-colours"], [], "ten colours in each of two palettes fit")
        lacking = [i for i in issues if i.code == "colours-not-in-palette"]
        self.assertEqual(len(lacking), 2, "neither palette holds its colours yet")
        self.assertEqual(pc.fix_all(self.project, lacking), 20)
        self.assertEqual([i for i in pc.check_project(self.project) if i.code == "colours-not-in-palette"], [])

    def test_palette_lines_note(self):
        self.assertIsNone(pc.megadrive_palette_issue(1))
        self.assertEqual(pc.megadrive_palette_issue(3).level, pc.INFO)
        self.assertEqual(pc.megadrive_palette_issue(4).level, pc.WARNING)
        self.assertIn("ms_load_palette", pc.megadrive_palette_issue(5).text)



class OtherConsolesTest(unittest.TestCase):
    """A project's palettes follow its console: a NES palette holds 3 colours, picked from the PPU's 64."""

    YELLOW = (220, 220, 0)

    def setUp(self):
        from ui.palette_editor import ops

        self.ops = ops
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.project = Project()
        self.palette = self.project.default_palette()
        self.palette.id = "pal_1"
        # Pixels: red 5, yellow 2, dark, blue and green 1 each.
        self.project.images.append(_sheet(self.folder, "hero.png", [RED, DARK, BLUE, GREEN, self.YELLOW]))
        self.palette.colours = [DARK, BLUE, GREEN, RED, self.YELLOW]

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_console_can_be_the_target(self):
        for console in consoles.CONSOLES:
            self.ops.set_console(self.project, console.key)
            self.assertEqual(self.project.console, console.key)
            self.assertEqual(palettes.capacity(self.project), console.palette.visible)
        self.ops.set_console(self.project, "no such console")
        self.assertEqual(self.project.console, "megadrive")

    def test_a_smaller_console_shows_the_first_colours_and_keeps_the_rest(self):
        self.assertEqual(self.ops.longer_palettes(self.project, "nes"), [self.palette])
        self.assertEqual(self.ops.longer_palettes(self.project, "snes"), [])
        self.assertEqual(self.ops.set_console(self.project, "nes"), 0)
        self.assertEqual(self.project.console_setup, "nes_8x8", "the console's first setup")
        self.ops.set_console(self.project, "snes", setup_key="snes_16_32")
        self.assertEqual((self.project.console, self.project.console_setup), ("snes", "snes_16_32"))
        self.ops.set_console(self.project, "nes")
        self.assertEqual(palettes.colours_of(self.project, self.palette), [DARK, BLUE, GREEN])
        self.assertEqual(palettes.stored_colours(self.project, self.palette), self.palette.colours)
        self.assertEqual(palettes.over_capacity(self.project), [self.palette])
        self.assertEqual(palettes.export_entries(self.project)[0].colours, (DARK, BLUE, GREEN))
        usage = palettes.slot_usage(self.project, self.palette)
        self.assertEqual((len(usage), usage[3:], sum(usage)), (5, [0, 0], 10), "the waiting slots draw nothing")
        self.assertEqual(palettes.unused_slots(self.project, self.palette)[-2:], [3, 4])
        codes = [i.code for i in pc.check_project(self.project)]
        self.assertIn("palette-too-long", codes)
        self.assertIn("too-many-colours", codes, "the art has five colours")
        self.assertNotIn("colours-not-in-palette", codes, "the palette's length is the issue, not missing colours")
        # Back on the Mega Drive every colour shows again.
        self.ops.set_console(self.project, "megadrive")
        self.assertEqual(palettes.colours_of(self.project, self.palette), self.palette.colours)
        self.assertNotIn("palette-too-long", [i.code for i in pc.check_project(self.project)])

    def test_keeping_the_most_used_colours(self):
        swap = PaletteSwap("s", "S", {"pal_1": PaletteChange(colours=[None, (1, 2, 3), None, None, (4, 5, 6)])})
        self.project.palette_swaps.append(swap)
        self.assertEqual(self.ops.set_console(self.project, "nes", keep_most_used=True), 2)
        self.assertEqual(self.palette.colours, [DARK, RED, self.YELLOW], "red and yellow, then the first of the rest")
        self.assertEqual(swap.palettes["pal_1"].colours, [None, None, (4, 5, 6)], "yellow's replacement moved with it")
        self.assertEqual(palettes.over_capacity(self.project), [])

    def test_check_project_fixes_a_long_palette(self):
        self.project.console = "gameboy"
        issue = next(i for i in pc.check_project(self.project) if i.code == "palette-too-long")
        self.assertEqual((issue.level, issue.target, issue.fix), (pc.WARNING, ("palette", "pal_1"), "keep-most-used-colours"))
        self.assertIn("a Game Boy palette 3", issue.text)
        self.assertEqual(pc.fix(self.project, issue), 2)
        self.assertEqual(self.palette.colours, [DARK, RED, self.YELLOW])

    def test_fixed_colours_in_the_console_view(self):
        self.project.console = "nes"
        shown = palettes.shown_colours(self.project, self.palette, console_view=True)
        self.assertTrue(all(rgb in consoles.NES.palette.fixed_colours for rgb in shown))
        self.assertEqual(shown[0], (0, 0, 0), "dark grey shows as the NES's black")

    def test_the_mega_drive_export_of_another_console(self):
        import export_megadrive as sg

        self.assertIsNone(pc.console_issue(self.project, consoles.MEGA_DRIVE))
        self.project.console = "nes"
        issue = pc.console_issue(self.project, consoles.MEGA_DRIVE)
        self.assertEqual((issue.level, issue.code), (pc.WARNING, "other-console"))
        self.assertIn("made for the NES", issue.text)
        self.assertIn("Mega Drive palettes", issue.text)
        snes = pc.console_issue(self.project, consoles.SNES, ", with 8×8 and 16×16 sprites")
        self.assertIn("SNES palettes of its palettes, 15 colours each", snes.text)
        self.assertTrue(snes.text.endswith("16×16 sprites."))
        words = sg.MegaDriveBakeContext(self.project, [None], self.folder / "out").packed_palette_words()
        self.assertEqual(len(words), 16, "a Mega Drive palette line, whatever the console")
        self.assertEqual(words[1:4], [palettes.md_word(c) for c in (DARK, BLUE, GREEN)])
        self.assertEqual(words[4:], [0] * 12, "the slots the NES has no room for are black")


if __name__ == "__main__":
    unittest.main()
