"""SGDK export of timeline scenes: object transforms like the stage, objects with their own module mapping."""

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "examples" / "sgdk" / "tools"))

from models import TIMELINE_MAPPING_ORIGINAL, FModule, ModuleMapping, Project, TimelineKeyframe  # noqa: E402


def _project(folder: Path) -> Project:
    """One frame showing module 'small' (one tile wide); mapping 'Wide' swaps it for 'wide' (two tiles)."""
    sheet = folder / "sheet.png"
    image = Image.new("RGBA", (24, 8), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (0, 0, 8, 8))
    image.paste((0, 0, 255, 255), (8, 0, 24, 8))
    image.save(sheet)
    project = Project()
    asset = project.create_image(str(sheet), 24, 8)
    small = project.create_module("small", asset.id, (0, 0, 8, 8), (0, 0))
    wide = project.create_module("wide", asset.id, (8, 0, 16, 8), (0, 0))
    frame = project.create_frame("pose")
    frame.fmodules.append(FModule(id="p", ref_type="module", ref_id=small.id, position=(0, 0)))
    project.mappings.append(ModuleMapping(id="map_wide", name="Wide", map={small.id: wide.id}))

    scene = project.create_timeline_scene("Fight")
    for name, x, mapping_id, parent in (
        ("follows", 0, None, None),
        ("wide", 32, "map_wide", None),
        ("original", 64, TIMELINE_MAPPING_ORIGINAL, None),
    ):
        obj = scene.create_object(name, "frame", frame.id)
        obj.mapping_id = mapping_id
        obj.keyframes = [TimelineKeyframe(id=f"k_{name}", time=0.0, x=float(x))]
    child = scene.create_object("child of wide", "frame", frame.id, parent_id=scene.objects[1].id)
    child.keyframes = [TimelineKeyframe(id="k_child", time=0.0, x=0.0, y=16.0)]
    return project


class TestSceneObjectMappings(unittest.TestCase):
    def test_objects_keep_their_mapping_in_every_baked_mapping(self):
        import export_sgdk_example as sg

        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            ctx = sg.SGDKBakeContext(project, [None, project.mappings[0]], Path(tmp) / "out")
            ctx.bake()
            shown = []
            for record in ctx.scene_records:  # one per baked mapping (a single scene)
                span = ctx.render_frames[ctx.scene_samples[record.first_sample]]
                parts = ctx.parts[span.first_part:span.first_part + span.part_count]
                shown.append(sorted((x, y, ctx.variants[variant].tile_w) for variant, x, y, _h, _v in parts))
            # (x, y, tiles wide): "follows" takes the baked mapping, the others keep theirs; the child inherits.
            self.assertEqual(shown[0], [(0, 0, 1), (32, 0, 2), (32, 16, 2), (64, 0, 1)])
            self.assertEqual(shown[1], [(0, 0, 2), (32, 0, 2), (32, 16, 2), (64, 0, 1)])


class TestSceneObjectTransforms(unittest.TestCase):
    def test_local_matrix_matches_the_stage(self):
        """Root motion and swap offsets are mirrored and turned with the object, in the exporter as on the stage."""
        import itertools

        import export_sgdk_example as sg
        from ui.scene_editor import ops

        for flip_x, flip_y, rotation, source_flip, source_rotation in itertools.product(
            (False, True), (False, True), (0.0, 90.0, 270.0), (False, True), (0.0, 90.0)
        ):
            state = {"x": 100.0, "y": -20.0, "rotation_degrees": rotation, "flip_x": flip_x, "flip_y": flip_y,
                     "source_offset": (10.0, -3.0), "source_flip_x": source_flip, "source_flip_y": False,
                     "source_rotation": source_rotation}
            with self.subTest(**{k: v for k, v in state.items() if k != "source_offset"}):
                for v1, v2 in zip(sg.SGDKBakeContext._build_local_matrix(state), ops.local_matrix(state)):
                    self.assertAlmostEqual(v1, v2, places=9)


if __name__ == "__main__":
    unittest.main()
