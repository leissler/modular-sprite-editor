"""SGDK export of timeline scenes: object transforms like the stage, objects with their own module mapping."""

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "examples" / "megadrive" / "tools"))

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
        import export_megadrive as sg

        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            ctx = sg.MegaDriveBakeContext(project, [None, project.mappings[0]], Path(tmp) / "out")
            ctx.bake()
            shown = []
            for record in ctx.scene_records:  # one per baked mapping (a single scene)
                span = ctx.render_frames[ctx.scene_samples[record.first_sample]]
                parts = ctx.parts[span.first_part:span.first_part + span.part_count]
                shown.append(sorted((x, y, ctx.variants[variant].tile_w) for variant, x, y, _h, _v in parts))
            # (x, y, tiles wide): "follows" takes the baked mapping, the others keep theirs; the child inherits.
            self.assertEqual(shown[0], [(0, 0, 1), (32, 0, 2), (32, 16, 2), (64, 0, 1)])
            self.assertEqual(shown[1], [(0, 0, 2), (32, 0, 2), (32, 16, 2), (64, 0, 1)])


class TestScenePlayback(unittest.TestCase):
    def test_objects_play_their_animation_as_animated(self):
        """The baked scene plays like the Animations tab: Play once ends, then the follow-up takes over."""
        import export_megadrive as sg
        from models import AFrame, Animation

        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            small = project.modules[0]
            for i in range(3):  # the module 8, 16 and 24 pixels to the right
                frame = project.create_frame(f"at {i}")
                frame.fmodules.append(FModule(id=f"p{i}", ref_type="module", ref_id=small.id, position=(8 + 8 * i, 0)))
            ids = [f.id for f in project.frames[1:]]
            strike = Animation(id="strike", name="strike", playback_type="forward", fps=10, next_animation_id="rest",
                               aframes=[AFrame(frame_id=frame_id, duration_frames=1) for frame_id in ids[:2]])
            rest = Animation(id="rest", name="rest", fps=10, aframes=[AFrame(frame_id=ids[2], duration_frames=1)])
            project.animations += [strike, rest]
            scene = project.create_timeline_scene("Strike")
            scene.fps, scene.duration_seconds = 10, 0.5
            scene.create_object("Hero", "animation", "strike")
            ctx = sg.MegaDriveBakeContext(project, [None], Path(tmp) / "out")
            ctx.bake()
            record = ctx.scene_records[-1]
            xs = []
            for sample in ctx.scene_samples[record.first_sample:record.first_sample + record.sample_count]:
                span = ctx.render_frames[sample]
                xs.append([x for _v, x, _y, _h, _f in ctx.parts[span.first_part:span.first_part + span.part_count]])
            self.assertEqual(xs, [[8], [16], [24], [24], [24]])


class TestSceneObjectTransforms(unittest.TestCase):
    def test_local_matrix_matches_the_stage(self):
        """Root motion and swap offsets are mirrored and turned with the object, in the exporter as on the stage."""
        import itertools

        import export_megadrive as sg
        from ui.scene_editor import ops

        for flip_x, flip_y, rotation, source_flip, source_rotation in itertools.product(
            (False, True), (False, True), (0.0, 90.0, 270.0), (False, True), (0.0, 90.0)
        ):
            state = {"x": 100.0, "y": -20.0, "rotation_degrees": rotation, "flip_x": flip_x, "flip_y": flip_y,
                     "source_offset": (10.0, -3.0), "source_flip_x": source_flip, "source_flip_y": False,
                     "source_rotation": source_rotation, "attach_offset": (5.0, -7.0)}
            with self.subTest(**{k: v for k, v in state.items() if k not in ("source_offset", "attach_offset")}):
                for v1, v2 in zip(sg.MegaDriveBakeContext._build_local_matrix(state), ops.local_matrix(state)):
                    self.assertAlmostEqual(v1, v2, places=9)



class TestAttachedObjects(unittest.TestCase):
    def test_an_object_follows_its_parents_point(self):
        """A sword on the hero's hand point: it moves with the point from step to step, mirrors with the hero and
        hides on the step whose frame has no such point; the export bakes it where the stage shows it."""
        import export_megadrive as sg
        from models import AFrame, Animation, ControlPoint, PointType
        from ui.scene_editor import ops

        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp))
            project.timeline_scenes.clear()
            small = project.modules[0]
            project.point_types.append(PointType("pt_hand", "Hand", (0, 0, 255)))
            frames = []
            for i, point in enumerate([(12, 4), (20, 6), None]):
                frame = project.create_frame(f"hero {i}")
                frame.fmodules.append(FModule(id=f"h{i}", ref_type="module", ref_id=small.id, position=(0, 0)))
                if point:
                    frame.control_points.append(ControlPoint(f"cp{i}", "pt_hand", point[0], point[1], role="hand"))
                frames.append(frame)
            project.animations.append(Animation(id="swing", name="swing", fps=10, aframes=[
                AFrame(frame_id=f.id, duration_frames=1) for f in frames]))
            scene = project.create_timeline_scene("Duel")
            scene.fps, scene.duration_seconds = 10, 0.3  # three samples, one per step
            hero = scene.create_object("Hero", "animation", "swing")
            hero.keyframes = [TimelineKeyframe(id="k_hero", time=0.0, x=100.0)]
            sword = scene.create_object("Sword", "frame", project.frames[0].id, parent_id=hero.id)
            sword.keyframes = [TimelineKeyframe(id="k_sword", time=0.0)]
            sword.attach_point_role = "hand"

            def baked():
                ctx = sg.MegaDriveBakeContext(project, [None], Path(tmp) / "out")
                ctx.bake()
                record = ctx.scene_records[-1]
                out = []
                for sample in ctx.scene_samples[record.first_sample:record.first_sample + record.sample_count]:
                    span = ctx.render_frames[sample]
                    out.append(sorted((x, y) for _v, x, y, _h, _f in ctx.parts[span.first_part:span.first_part + span.part_count]))
                return out

            self.assertEqual(baked(), [[(100, 0), (112, 4)], [(100, 0), (120, 6)], [(100, 0)]])
            states = ops.evaluate_states(project, scene, 0.1)
            self.assertEqual(ops.world_matrix(scene, states, sword.id)[4:], (120.0, 6.0), "the stage agrees")
            hidden = ops.evaluate_states(project, scene, 0.2)[sword.id]
            self.assertTrue(hidden["attach_missing"])
            self.assertTrue(hidden["visible"], "the key's own visibility stays (a new key keeps it)")
            hero.keyframes[0].flip_x = True  # the point's pixel mirrors to -x - 1: the sword's origin lands on -x
            self.assertEqual(baked(), [[(80, 4), (92, 0)], [(72, 6), (92, 0)], [(92, 0)]])


if __name__ == "__main__":
    unittest.main()
