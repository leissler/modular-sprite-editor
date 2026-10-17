"""Other ways to export (export_modes.py, ConsoleBake.whole_frames): whole frames draw exactly what the editor draws,
their layers never overlap, and the parts the exports store are what the budget counts."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import compositor  # noqa: E402
import console_bake  # noqa: E402
import console_exports  # noqa: E402
import export_modes  # noqa: E402
import hardware_budget  # noqa: E402
import palettes  # noqa: E402
from models import FModule, ImageAsset, Module, Palette, Project  # noqa: E402

POP = ROOT / "examples" / "pop" / "PoP_WW.json"


class PictureBake(console_bake.ConsoleBake):
    """Keeps every stored picture, numbered once per picture, palette and entry."""

    def __init__(self, project, mappings):
        super().__init__(project, mappings)
        self.pictures = []
        self.palettes_of = []
        self.lookup = {}

    def _store_part(self, image, palette, entry):
        rgba = image.convert("RGBA")
        key = (rgba.size, hashlib.sha1(rgba.tobytes()).hexdigest(), palette, entry)
        if key not in self.lookup:
            self.lookup[key] = len(self.pictures)
            self.pictures.append(rgba)
            self.palettes_of.append(palette)
        return self.lookup[key]


def _opaque(image):
    """The image with every transparent pixel cleared, cropped to what shows, and where that starts."""
    mask = image.getchannel("A").point(lambda value: 255 if value else 0)
    box = mask.getbbox()
    if box is None:
        return None, (0, 0)
    clean = Image.composite(image, Image.new("RGBA", image.size, (0, 0, 0, 0)), mask)
    return clean.crop(box), (box[0], box[1])


def _rebuild(bake, parts):
    """A render frame drawn from its stored pictures (a flip mirrors a picture padded to whole tiles): (image, left,
    top) and the pixels two pictures both cover."""
    placed = []
    for stored, x, y, hflip, vflip in parts:
        picture = bake.pictures[stored]
        padded = Image.new("RGBA", (max(8, -(-picture.width // 8) * 8), max(8, -(-picture.height // 8) * 8)), (0, 0, 0, 0))
        padded.paste(picture, (0, 0))
        if hflip:
            padded = padded.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if vflip:
            padded = padded.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        placed.append((padded, x, y))
    if not placed:
        return None, 0, 0, 0
    left, top = min(x for _p, x, _y in placed), min(y for _p, _x, y in placed)
    size = (max(x + p.width for p, x, _y in placed) - left, max(y + p.height for p, _x, y in placed) - top)
    canvas, covered, twice = Image.new("RGBA", size, (0, 0, 0, 0)), Image.new("L", size, 0), 0
    for padded, x, y in placed:
        mask = Image.new("L", size, 0)
        mask.paste(padded.getchannel("A").point(lambda value: 255 if value else 0), (x - left, y - top))
        overlap = ImageChops.multiply(covered, mask).getbbox()
        twice += 0 if overlap is None else 1
        covered = ImageChops.lighter(covered, mask)
        canvas.paste(padded, (x - left, y - top), padded.getchannel("A").point(lambda value: 255 if value else 0))
    return canvas, left, top, twice


class WholeFramesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Project.from_json(str(POP))
        cls.mappings = [None] + list(cls.project.mappings)
        cls.bake = PictureBake(cls.project, cls.mappings)
        cls.bake.whole_frames = True
        cls.bake.bake()

    def assertDraws(self, render, expected, what):
        image, left, top, twice = _rebuild(self.bake, self.bake.render_frame_parts(render))
        self.assertEqual(twice, 0, f"{what}: layers overlap")
        got, at = _opaque(image) if image is not None else (None, (0, 0))
        want, want_at = _opaque(expected[0]) if expected is not None else (None, (0, 0))
        if want is None:
            self.assertIsNone(got, what)
            return
        self.assertIsNotNone(got, what)
        self.assertEqual((left + at[0], top + at[1]), (expected[1] + want_at[0], expected[2] + want_at[1]), what)
        self.assertEqual(got.size, want.size, what)
        self.assertIsNone(ImageChops.difference(got, want).getbbox(), f"{what}: other pixels")

    def test_every_frame_step_and_module_as_the_editor_draws_it(self):
        from ui.frame_render import FrameRenderer

        renderer, project, bake, seen = FrameRenderer(), self.project, self.bake, set()
        caches = ({}, {})
        frames, modules = project.frames, project.modules
        step = 0
        for m, mapping in enumerate(self.mappings):
            for i, frame in enumerate(frames):
                render = bake.frame_render_frames[m * len(frames) + i]
                if render not in seen:
                    seen.add(render)
                    self.assertDraws(render, renderer.render(project, frame, mapping), f"frame {frame.name}, {m}")
            for i, module in enumerate(modules):
                render = bake.module_render_frames[m * len(modules) + i]
                mod = compositor.resolve_module(project, module.id, mapping)
                if render not in seen and mod is not None and mod.rect[2] > 0 and mod.rect[3] > 0:
                    seen.add(render)
                    expected = compositor.render_instance(project, mod, compositor.IDENTITY, (0.0, 0.0), *caches)
                    self.assertDraws(render, expected, f"module {module.name}, {m}")
            for anim in project.animations:
                shown = 0
                for af in anim.aframes:
                    frame = project.get_frame(af.frame_id)
                    if frame is None:
                        continue
                    render = bake.anim_steps[step][0]
                    step, shown = step + 1, shown + 1
                    if render in seen:
                        continue
                    seen.add(render)
                    a = compositor.mat_mul(compositor.rotation_matrix(float(getattr(af, "rotation_degrees", 0.0))),
                                           compositor.flip_matrix(bool(af.flip_x), bool(af.flip_y)))
                    b = (float(af.offset[0]), float(af.offset[1]))
                    self.assertDraws(render, renderer.render(project, frame, mapping, a, b), f"{anim.name} step, {m}")
                step += 0 if shown else 1  # an animation without steps gets an empty one
        self.assertEqual(step, len(bake.anim_steps))
        self.assertGreater(len(seen), 900)
        self.assertTrue(any(hflip for _s, _x, _y, hflip, _v in bake.parts), "mirrored steps reuse pictures, flipped")

    def test_a_frame_is_a_few_pictures(self):
        """PoP's frames are many parts drawn over each other; whole, each is one picture of its one palette."""
        frame_parts = [self.bake.render_frame_parts(r) for r in self.bake.frame_render_frames]
        self.assertTrue(all(len(parts) <= 1 for parts in frame_parts))


class LayersTest(unittest.TestCase):
    def test_one_layer_per_palette_and_the_part_on_top_wins(self):
        """A cool part drawn over half of a warm one: the warm layer keeps only what still shows."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Project()
            project.palettes = [Palette("p0", "Warm"), Palette("p1", "Cool")]
            for index, (name, colour) in enumerate((("warm.png", (200, 60, 40)), ("cool.png", (40, 80, 210)))):
                Image.new("RGBA", (8, 8), colour + (255,)).save(Path(tmp) / name)
                project.images.append(ImageAsset(f"img{index}", str(Path(tmp) / name), 8, 8, palette_id=f"p{index}"))
                project.modules.append(Module(f"m{index}", name, f"img{index}", (0, 0, 8, 8), (0, 0)))
            for palette in project.palettes:
                palettes.add_missing_colours(project, palette)
            frame = project.create_frame("both")
            frame.fmodules += [FModule("a", "module", "m0", (0, 0)), FModule("b", "module", "m1", (4, 2))]
            bake = PictureBake(project, [None])
            bake.whole_frames = True
            bake.bake()
            parts = bake.render_frame_parts(bake.frame_render_frames[0])
            layers = {bake.palettes_of[stored]: (bake.pictures[stored].size, (x, y)) for stored, x, y, _h, _v in parts}
            self.assertEqual(layers, {"p0": ((8, 8), (0, 0)), "p1": ((8, 8), (4, 2))})
            warm = bake.pictures[next(s for s, *_rest in parts if bake.palettes_of[s] == "p0")]
            self.assertEqual(warm.getpixel((5, 5))[3], 0, "hidden under the cool part")
            self.assertEqual(warm.getpixel((5, 1))[3], 255, "above it")
            self.assertEqual(sorted(bake._entry_byte(p) for p in layers), [0, 1], "each layer draws from its palette")


class MeasureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Project.from_json(str(POP))

    def test_the_parts_are_what_the_budget_counts(self):
        mappings = [None] + list(self.project.mappings)
        for export in console_exports.EXPORTS:
            setups = [export.console.budgets[0], export.console.budgets[-1]] if export.setups else export.console.budgets[:1]
            for setup in setups:
                with self.subTest(setup.key):
                    costs = export_modes.measure(self.project, export, setup.key if export.setups else "")
                    self.assertEqual([c.mode for c in costs], list(export_modes.MODES))
                    parts, streamed, frames = costs
                    budget = hardware_budget.BudgetCalculator().export_tiles(
                        self.project, mappings, hardware_budget.profile_by_key(setup.key))
                    self.assertEqual(parts.video_tiles, budget)
                    self.assertEqual((parts.cartridge_tiles, streamed.cartridge_tiles), (budget, budget))
                    self.assertLess(streamed.video_tiles, parts.video_tiles, "a slot holds one frame's tiles")
                    self.assertEqual((parts.upload_max, streamed.upload_max > 0), (0, True))
                    self.assertLessEqual(streamed.upload_max, streamed.video_tiles * 32, "a step fits its slot")
                    self.assertLess(frames.sprites_avg, parts.sprites_avg, "PoP's parts overlap")
                    self.assertGreater(frames.cartridge_tiles, parts.cartridge_tiles)

    def test_the_swordfight_needs_two_slots(self):
        parts, streamed, _frames = export_modes.measure(self.project, console_exports.MEGA_DRIVE, mappings=[None])
        self.assertEqual(parts.scene_line_max, 20, "the Swordfight's busiest line: the H40 limit")
        self.assertGreater(streamed.scene_video_tiles, streamed.video_tiles, "the Prince's slot and the guard's")

    def test_a_busiest_line(self):
        self.assertEqual(export_modes.busiest_line([(0, 0, 8, 8), (8, 4, 8, 8), (0, 12, 8, 8)]), 2)
        self.assertEqual(export_modes.busiest_line([]), 0)


if __name__ == "__main__":
    unittest.main()
