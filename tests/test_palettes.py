"""palettes.py: Mega Drive colours, one palette per image group, the console preview matches the export."""

import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples" / "sgdk" / "tools"))

import palettes  # noqa: E402
import project_check as pc  # noqa: E402
from models import ImageAsset, Project  # noqa: E402


def _sheet(folder: Path, name: str, colours, palette: int = 0) -> ImageAsset:
    """An image with these colours, one pixel each (more pixels for the first ones), and a transparent pixel."""
    image = Image.new("RGBA", (len(colours) + 4, 2), (0, 0, 0, 0))
    for x, rgb in enumerate(colours):
        image.putpixel((x, 0), rgb + (255,))
        image.putpixel((x, 1), (colours[0] if x < 4 else rgb) + (255,))
    path = folder / name
    image.save(path)
    return ImageAsset(name, str(path), image.width, image.height, palette=palette)


def _shades(count: int, base=(40, 60, 200)):
    return [((base[0] + 7 * i) % 256, (base[1] + 3 * i) % 256, (base[2] + 11 * i) % 256) for i in range(count)]


class ColoursTest(unittest.TestCase):
    def test_console_levels_and_words(self):
        self.assertEqual([palettes.md_level(v) for v in (0, 31, 32, 128, 255)], [0, 0, 36, 145, 255])
        self.assertEqual(palettes.md_word((255, 0, 0)), 0x000E)
        self.assertEqual(palettes.md_word((0, 255, 0)), 0x00E0)
        self.assertEqual(palettes.md_word((0, 0, 255)), 0x0E00)

    def test_a_palette_keeps_up_to_15_colours_most_used_first(self):
        counts = Counter({(10, 10, 10): 5, (200, 0, 0): 9, (0, 0, 200): 1})
        self.assertEqual(palettes.build_palette(counts)[:3], [(200, 0, 0), (10, 10, 10), (0, 0, 200)])
        self.assertEqual(len(palettes.build_palette(counts)), 15)
        many = Counter({rgb: 1 for rgb in _shades(30)})
        self.assertEqual(len(palettes.build_palette(many)), 15)


class ProjectPalettesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_palette_per_group_and_gaps_get_the_first(self):
        project = Project()
        project.images += [_sheet(self.folder, "hero.png", [(250, 0, 0), (200, 0, 0)]),
                           _sheet(self.folder, "slime.png", [(0, 250, 0)], palette=2)]
        built = palettes.project_palettes(project)
        self.assertEqual(sorted(built), [0, 1, 2])
        self.assertEqual(built[0][:2], [(250, 0, 0), (200, 0, 0)])
        self.assertEqual(built[2][0], (0, 250, 0))
        self.assertEqual(built[1], built[0], "a gap between used palettes gets the first one's colours")

    def test_the_preview_shows_what_the_export_stores(self):
        import export_sgdk_example as sg

        project = Project()
        project.images.append(_sheet(self.folder, "many.png", _shades(24)))
        ctx = sg.SGDKBakeContext(project, [None], self.folder / "out")
        with Image.open(project.images[0].file_path) as source:
            rgba = source.convert("RGBA")
        shown = palettes.console_image(rgba, ctx.palettes[0])
        for (x, y) in ((0, 0), (5, 0), (17, 0), (3, 1), (20, 1)):
            r, g, b, a = rgba.getpixel((x, y))
            if a:
                index = ctx._nearest_palette_index((r, g, b), 0)
                self.assertEqual(shown.getpixel((x, y))[:3], palettes.md_colour(ctx.palettes[0][index]))
        self.assertEqual(shown.getpixel((rgba.width - 1, 0))[3], 0, "transparent stays transparent")

    def test_check_project_counts_colours_per_palette(self):
        project = Project()
        warm, cool = _shades(10, (200, 40, 20)), _shades(10, (20, 40, 200))
        project.images += [_sheet(self.folder, "warm.png", warm), _sheet(self.folder, "cool.png", cool)]
        found = [i for i in pc.check_project(project) if i.code == "too-many-colours"]
        self.assertEqual(len(found), 1)
        self.assertIn("Palette 1 ('warm.png', 'cool.png') uses 20 colours", found[0].text)
        project.images[1].palette = 1
        self.assertEqual([i for i in pc.check_project(project) if i.code == "too-many-colours"], [],
                         "ten colours in each of two palettes fit")

    def test_palette_lines_note(self):
        self.assertIsNone(pc.palette_issue(1))
        self.assertEqual(pc.palette_issue(3).level, pc.INFO)
        self.assertEqual(pc.palette_issue(4).level, pc.WARNING)


if __name__ == "__main__":
    unittest.main()
