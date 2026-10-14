"""sprite_cut.py: how hardware sprites cover a part, shared by the Mega Drive export, the budget and Auto Modularize."""

import random
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import hardware_budget as hb  # noqa: E402
import sprite_cut as sc  # noqa: E402


def _part(w, h, seed, fill=0.5, blobs=3):
    """A part with a few opaque blobs and transparent space around them."""
    rng = random.Random(seed)
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for _ in range(blobs):
        bw, bh = rng.randint(1, max(1, w // 2)), rng.randint(1, max(1, h // 2))
        x0, y0 = rng.randrange(w), rng.randrange(h)
        for y in range(y0, min(h, y0 + bh)):
            for x in range(x0, min(w, x0 + bw)):
                if rng.random() < fill + 0.4:
                    image.putpixel((x, y), (rng.randrange(1, 256), 40, 90, 255))
    return image


def _covered(image, rects):
    """Whether the rectangles cover every opaque pixel."""
    alpha = image.getchannel("A")
    inside = set()
    for x, y, w, h in rects:
        inside |= {(px, py) for py in range(y, y + h) for px in range(x, x + w)}
    return all((x, y) in inside for y in range(image.height) for x in range(image.width) if alpha.getpixel((x, y)))


class ExportCutTest(unittest.TestCase):
    def test_never_worse_than_the_grid_and_covers_every_pixel(self):
        for seed in range(150):
            image = _part(random.Random(seed).randint(1, 90), random.Random(seed + 1000).randint(1, 90), seed)
            rects = sc.export_cut(image)
            grid = sc.grid_cut(image)
            with self.subTest(seed=seed, size=image.size):
                self.assertLessEqual((len(rects), sc.tiles_of(rects)), (len(grid), sc.tiles_of(grid)))
                self.assertTrue(_covered(image, rects))
                pad_w, pad_h = sc.pad(image.width), sc.pad(image.height)
                for x, y, w, h in rects:
                    self.assertIn((w, h), sc.MEGA_DRIVE.sizes)
                    self.assertTrue(0 <= x and x + w <= pad_w and 0 <= y and y + h <= pad_h, (x, y, w, h))

    def test_empty_space_costs_no_tiles(self):
        # A 32x32 cell (as a grid slice cuts a sheet) with a 10x10 sprite in the middle: one 16x16 sprite, not 32x32.
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        image.paste((200, 50, 50, 255), (11, 11, 21, 21))
        self.assertEqual(sc.export_cut(image), [(11, 11, 16, 16)])
        self.assertEqual(sc.grid_cut(image), [(0, 0, 32, 32)])
        # A wide part of two islands: two sprites, tight around each; the grid splits the second island in two.
        image = Image.new("RGBA", (72, 16), (0, 0, 0, 0))
        image.paste((200, 50, 50, 255), (2, 3, 12, 11))
        image.paste((200, 50, 50, 255), (58, 0, 70, 16))
        rects = sc.export_cut(image)
        self.assertEqual((len(rects), sc.tiles_of(rects)), (2, 6))
        grid = sc.grid_cut(image)
        self.assertEqual((len(grid), sc.tiles_of(grid)), (3, 18))

    def test_equal_cuts_keep_the_grid(self):
        image = Image.new("RGBA", (40, 40), (90, 90, 90, 255))
        self.assertEqual(sc.export_cut(image), sc.grid_cut(image))


class TightCutTest(unittest.TestCase):
    def test_every_console_covers_with_its_sizes(self):
        image = _part(70, 50, 7, blobs=5)
        bits = sc.bits_of(sc.opaque_mask(image))
        for profile in hb.PROFILES:
            sizes = set(profile.hardware.sizes)
            for weight in (0.0, 2.0, 64.0):
                with self.subTest(profile=profile.key, weight=weight):
                    _cost, rects = sc.tight_cut(bits, image.width, image.height, weight, profile.hardware.sizes)
                    self.assertTrue(all((w, h) in sizes for _x, _y, w, h in rects))
                    self.assertTrue(_covered(image, rects))

    def test_the_faster_cover_finds_the_same_costs(self):
        """For every run start only the longest reach of each width is tried; that loses nothing."""
        rng = random.Random(5)
        for _ in range(300):
            width = rng.choice((8, 16, 24, 40, 64))
            occupied = rng.getrandbits(width)
            widths = (8, 16, 24, 32)
            cost, _runs = sc._cover_1d(occupied, width, 16, 2.0, widths)
            xs = [x for x in range(width) if occupied >> (width - 1 - x) & 1]
            best = [0.0] * (len(xs) + 1)
            for i in range(len(xs) - 1, -1, -1):  # the plain search: every end column
                best[i] = min(((xs[j] - xs[i] + 8) // 8) * 2 + 2.0 + best[j + 1]
                              for j in range(i, len(xs)) if xs[j] - xs[i] < 32)
            self.assertAlmostEqual(cost, best[0])


class ConsoleCutTest(unittest.TestCase):
    def test_every_profile_covers_the_part(self):
        image = _part(60, 44, 11, blobs=4)
        for profile in hb.PROFILES:
            with self.subTest(profile=profile.key):
                rects = sc.cut(image, profile.hardware)
                self.assertTrue(_covered(image, rects))
                tiles, sprites = sc.tiles_and_sprites(image, profile.hardware)
                self.assertEqual((tiles, sprites), (sc.tiles_of(rects), len(rects)))


if __name__ == "__main__":
    unittest.main()
