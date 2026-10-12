"""Auto-modularisation (modularize.py): exact plans, shared parts, the hardware cut and rewriting projects."""

import random
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import modularize as mz  # noqa: E402
from models import FModule, Frame, Project  # noqa: E402


def _blob(w, h, seed):
    """A random opaque blob with a transparent border and holes (like a sprite part)."""
    rng = random.Random(seed)
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for y in range(h):
        for x in range(w):
            if rng.random() < 0.8 and 0 < x < w - 1:
                image.putpixel((x, y), (rng.randrange(256), rng.randrange(256), rng.randrange(256), 255))
    return image


def _sprite(size, pieces):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    for piece, (x, y) in pieces:
        image.alpha_composite(piece, (x, y))
    return image


def _pixels(image):
    image = image.convert("RGBA")
    return {(x, y): image.getpixel((x, y)) for y in range(image.height) for x in range(image.width) if image.getpixel((x, y))[3]}


class TestHardwareCut(unittest.TestCase):
    def test_rectangles_cover_every_pixel_and_fit_the_hardware(self):
        image = _sprite((53, 41), [(_blob(20, 30, 1), (0, 0)), (_blob(25, 12, 2), (27, 28)), (_blob(6, 6, 3), (40, 2))])
        bits = mz._bits(mz._opaque(image))
        for weight in (0.0, 2.0, 8.0):
            _cost, rects = mz.hardware_cut(bits, image.width, image.height, weight)
            covered = 0
            for x, y, w, h in rects:
                self.assertTrue(w in (8, 16, 24, 32) and h in (8, 16, 24, 32), (x, y, w, h))
                covered |= mz._region_bits(image.width, image.height, [(x, y, w, h)])[0]
            self.assertEqual(bits & ~covered, 0, f"weight {weight}: pixels left uncovered")

    def test_a_higher_sprite_weight_gives_fewer_rectangles(self):
        image = _sprite((60, 60), [(_blob(14, 14, n), (n * 9 % 46, n * 13 % 46)) for n in range(6)])
        bits = mz._bits(mz._opaque(image))
        few = len(mz.hardware_cut(bits, 60, 60, 16.0)[1])
        many = len(mz.hardware_cut(bits, 60, 60, 0.0)[1])
        self.assertLessEqual(few, many)


class TestPlan(unittest.TestCase):
    def assertExact(self, sprites, plan):
        for key, image in sprites.items():
            self.assertEqual(_pixels(mz.compose(plan, key, image.size)), _pixels(image), f"sprite {key} differs")

    def test_shared_part_found_at_other_offsets_and_mirrored(self):
        head, a, b = _blob(24, 20, 10), _blob(18, 22, 11), _blob(20, 16, 12)
        mirrored = head.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        sprites = {
            "one": _sprite((48, 48), [(head, (3, 1)), (a, (8, 22))]),
            "two": _sprite((52, 44), [(head, (20, 4)), (b, (2, 26))]),
            "three": _sprite((40, 50), [(mirrored, (10, 0)), (a, (0, 25))]),
        }
        plan = mz.plan(sprites, mz.Settings(sprite_weight=1.0))
        self.assertExact(sprites, plan)
        shared = [p for p, n in plan.uses().items() if n == 3]
        self.assertTrue(shared, "the head is in all three sprites")
        flipped = [pl for pl in plan.placements["three"] if pl.part in shared and pl.flip_x]
        self.assertTrue(flipped, "the mirrored head reuses the part, flipped")

    def test_identical_and_mirrored_sprites_are_built_once(self):
        base = _sprite((30, 30), [(_blob(26, 26, 20), (2, 2))])
        sprites = {"a": base, "b": base.copy(), "c": base.transpose(Image.Transpose.FLIP_TOP_BOTTOM)}
        plan = mz.plan(sprites)
        self.assertExact(sprites, plan)
        self.assertEqual({pl.part for pl in plan.placements["a"]}, {pl.part for pl in plan.placements["c"]})

    def test_parts_are_hardware_sprites(self):
        sprites = {str(n): _sprite((70, 60), [(_blob(30, 28, n), (n, 5)), (_blob(40, 20, n + 50), (20, 38))]) for n in range(4)}
        plan = mz.plan(sprites)
        self.assertExact(sprites, plan)
        for part in plan.parts:
            self.assertLessEqual(max(part.size), 32)
            self.assertEqual(mz.part_tiles(part)[1], 1)

    def test_empty_sprites_and_cancel(self):
        sprites = {"empty": Image.new("RGBA", (8, 8)), "dot": _sprite((9, 9), [(_blob(3, 3, 5), (4, 4))])}
        plan = mz.plan(sprites)
        self.assertEqual(plan.placements["empty"], [])
        self.assertExact(sprites, plan)
        with self.assertRaises(mz.Cancelled):
            mz.plan({str(n): _blob(40, 40, n) for n in range(10)}, cancelled=lambda: True)


class TestApply(unittest.TestCase):
    def test_frames_render_the_same_under_flips_and_rotations(self):
        from ui.frame_render import FrameRenderer

        shared = _blob(20, 18, 30)
        sprites = [_sprite((44, 40), [(shared, (2, 3)), (_blob(16, 18, 31), (24, 20))]),
                   _sprite((36, 46), [(shared, (14, 0)), (_blob(30, 22, 32), (3, 22))])]
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Image.new("RGBA", (90, 50), (0, 0, 0, 0))
            sheet.paste(sprites[0], (0, 0))
            sheet.paste(sprites[1], (50, 2))
            sheet_path = Path(tmp) / "sheet.png"
            sheet.save(sheet_path)
            project = Project()
            asset = project.create_image(str(sheet_path), 90, 50)
            m1 = project.create_module("walk 1", asset.id, (0, 0, 44, 40), (13, 37))
            m2 = project.create_module("walk 2", asset.id, (50, 2, 36, 46), (5, 9))
            m3 = project.create_module("unused", asset.id, (0, 0, 20, 20), (10, 10))
            for n, (flip_x, flip_y, rotation) in enumerate([(False, False, 0), (True, False, 0), (False, True, 90),
                                                           (True, True, 180), (True, False, 270)]):
                project.frames.append(Frame(id=f"f{n}", name=f"frame {n}", fmodules=[
                    FModule(id=f"a{n}", ref_type="module", ref_id=m1.id, position=(3 * n, -n), flip_x=flip_x,
                            flip_y=flip_y, rotation_degrees=rotation),
                    FModule(id=f"b{n}", ref_type="module", ref_id=m2.id, position=(20, 7), flip_x=not flip_x,
                            rotation_degrees=rotation)]))
            renderer = FrameRenderer()

            def render(frame):
                image, hx, hy = renderer.render(project, frame, None)
                return {(x + hx, y + hy): px for (x, y), px in _pixels(image).items()}

            before = {f.id: render(f) for f in project.frames}
            modules = [m1.id, m2.id, m3.id]
            images = {mid: renderer.module(project, project.get_module(mid)) for mid in modules}
            plan = mz.plan(images, mz.Settings(sprite_weight=1.0))
            applied = mz.apply_plan(project, asset.id, modules, plan, str(Path(tmp) / "parts.png"))

            renderer = FrameRenderer()
            for frame in project.frames:
                if frame.id in before:
                    self.assertEqual(render(frame), before[frame.id], f"{frame.name} changed")
            self.assertEqual(applied.new_frames, 1, "the unused sprite gets a frame of its own")
            self.assertEqual(applied.removed_modules, 3)
            self.assertIsNone(project.get_module(m1.id))
            new_frame = project.frames[-1]
            self.assertEqual(new_frame.name, "unused")
            expected = {(x - 10, y - 10): px for (x, y), px in _pixels(images[m3.id]).items()}
            self.assertEqual(render(new_frame), expected)

    def test_free_rotation_keeps_the_whole_sprite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.png"
            _sprite((30, 30), [(_blob(26, 26, 40), (2, 2))]).save(path)
            project = Project()
            asset = project.create_image(str(path), 30, 30)
            mod = project.create_module("tilted", asset.id, (0, 0, 30, 30), (15, 15))
            project.frames.append(Frame(id="f", name="f", fmodules=[
                FModule(id="a", ref_type="module", ref_id=mod.id, position=(0, 0), rotation_degrees=45.0),
                FModule(id="b", ref_type="module", ref_id=mod.id, position=(40, 0))]))
            from ui.frame_render import FrameRenderer

            plan = mz.plan({mod.id: FrameRenderer().module(project, mod)})
            applied = mz.apply_plan(project, asset.id, [mod.id], plan, str(Path(tmp) / "p.png"))
            self.assertEqual(applied.kept_modules, 1)
            self.assertIsNotNone(project.get_module(mod.id))
            refs = [fm.ref_id for fm in project.frames[0].fmodules]
            self.assertEqual(refs[0], mod.id)
            self.assertTrue(all(r != mod.id for r in refs[1:]))


if __name__ == "__main__":
    unittest.main()
