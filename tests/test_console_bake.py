"""console_bake.py: the console-independent half of a console export, as a console's exporter builds on it."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples" / "megadrive" / "tools"))

import console_bake  # noqa: E402
from models import Project  # noqa: E402

POP = ROOT / "examples" / "pop" / "PoP_WW.json"


class RecordingBake(console_bake.ConsoleBake):
    """The least a console's exporter does: number each part picture (with its palette and entry) once."""

    def __init__(self, project, mappings):
        super().__init__(project, mappings)
        self.stored = {}

    def _store_part(self, image, palette, entry):
        rgba = image.convert("RGBA")
        key = (rgba.width, rgba.height, hashlib.sha1(rgba.tobytes()).hexdigest(), palette, entry)
        return self.stored.setdefault(key, len(self.stored))


class ConsoleBakeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Project.from_json(str(POP))

    def test_a_console_must_store_the_parts(self):
        with self.assertRaises(NotImplementedError):
            console_bake.ConsoleBake(self.project, [None]).bake()

    def test_the_mega_drive_export_is_this_bake_plus_its_own_tiles(self):
        """Every mapping, the Swordfight's objects with their own mapping and swap, hitboxes, points and events: the
        shared bake gives the Mega Drive exporter exactly its parts, frames, steps and samples."""
        import export_megadrive as sg

        mappings = [None] + list(self.project.mappings)
        shared = RecordingBake(self.project, mappings)
        shared.bake()
        with tempfile.TemporaryDirectory() as tmp:
            md = sg.MegaDriveBakeContext(self.project, mappings, Path(tmp))
            md.bake()
        self.assertIsInstance(md, console_bake.ConsoleBake)
        for name in ("parts", "render_frames", "boxes", "points", "module_render_frames", "frame_render_frames",
                     "anim_steps", "anim_records", "step_events", "scene_samples", "scene_records", "palette_entries"):
            with self.subTest(name=name):
                self.assertEqual(getattr(shared, name), getattr(md, name))
        self.assertEqual(len(shared.stored), len(md.variants), "one stored picture per Mega Drive variant")
        self.assertEqual(len(md.frame_render_frames), len(self.project.frames) * len(mappings))
        self.assertTrue(any(entry & console_bake.FIXED_ENTRY for *_rest, entry in md.pieces),
                        "the guard's own swap is fixed in his pieces")
        self.assertTrue(shared.step_events and shared.boxes and shared.points, "events, hitboxes and points")


if __name__ == "__main__":
    unittest.main()
