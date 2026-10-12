import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import (
    TIMELINE_MAPPING_ORIGINAL,
    AFrame,
    Animation,
    Frame,
    FModule,
    ModuleMapping,
    Project,
    TimelineKeyframe,
)


class TestTimelineScenes(unittest.TestCase):
    def test_timeline_scene_serialization_round_trip(self):
        project = Project(name="Timeline Test")
        image = project.create_image("/tmp/test.png", 32, 32)
        module = project.create_module("Body", image.id, (0, 0, 32, 32), (16, 16))
        frame = project.create_frame("Idle")
        frame.fmodules.append(
            FModule(
                id="fmod_a",
                ref_type="module",
                ref_id=module.id,
                position=(16, 16),
            )
        )
        anim = project.create_animation("Run")
        anim.aframes.append(AFrame(frame_id=frame.id, duration_frames=2))

        scene = project.create_timeline_scene("Cutscene")
        obj = scene.create_object("Hero", source_type="animation", source_id=anim.id)
        obj.keyframes = [
            TimelineKeyframe(id="k0", time=0.0, x=0.0, y=0.0, easing="linear"),
            TimelineKeyframe(
                id="k1",
                time=1.0,
                x=32.0,
                y=8.0,
                easing="back_out",
                path_out=(12.0, 0.0),
            ),
        ]

        payload = project.to_dict()
        self.assertIn("timeline_scenes", payload)
        self.assertEqual(payload["timeline_scenes"][0]["name"], "Cutscene")

        loaded = Project.from_dict(payload)
        self.assertEqual(len(loaded.timeline_scenes), 1)
        loaded_scene = loaded.timeline_scenes[0]
        self.assertEqual(loaded_scene.name, "Cutscene")
        self.assertEqual(len(loaded_scene.objects), 1)
        self.assertEqual(loaded_scene.objects[0].source_type, "animation")
        self.assertEqual(loaded_scene.objects[0].path_mode, "linear")
        self.assertEqual(len(loaded_scene.objects[0].keyframes), 2)
        self.assertEqual(loaded_scene.objects[0].keyframes[1].path_out, (12.0, 0.0))
        self.assertEqual(loaded_scene.objects[0].keyframes[0].source_offset, (0.0, 0.0))
        self.assertAlmostEqual(loaded_scene.duration_seconds, 10.0)

    def test_scene_sampling_interpolates_and_resolves_animation_source(self):
        project = Project(name="Timeline Test")
        frame_a = Frame(id="frm_a", name="A")
        frame_b = Frame(id="frm_b", name="B")
        project.frames.extend([frame_a, frame_b])
        anim = Animation(
            id="anim_run",
            name="Run",
            aframes=[
                AFrame(frame_id="frm_a", duration_frames=2),
                AFrame(frame_id="frm_b", duration_frames=3),
            ],
        )
        project.animations.append(anim)

        scene = project.create_timeline_scene("Boss")
        obj = scene.create_object("Runner", source_type="animation", source_id=anim.id)
        obj.keyframes = [
            TimelineKeyframe(id="k0", time=0.0, x=0.0, y=0.0),
            TimelineKeyframe(id="k1", time=1.0, x=20.0, y=10.0, easing="quad_out"),
        ]

        state = scene.evaluate_object_state(project, obj.id, 0.3)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertGreater(state["x"], 10.0)
        self.assertGreater(state["y"], 5.0)
        self.assertEqual(state["frame_id"], "frm_b")

    def test_scene_sampling_supports_linear_and_spline_path_modes(self):
        project = Project(name="Timeline Path Modes")
        scene = project.create_timeline_scene("Path Scene")
        linear_obj = scene.create_object("Linear", source_type="none", source_id=None)
        spline_obj = scene.create_object("Spline", source_type="none", source_id=None)
        spline_obj.path_mode = "spline"
        keys = [
            TimelineKeyframe(id="k0", time=0.0, x=0.0, y=0.0, easing="linear"),
            TimelineKeyframe(id="k1", time=1.0, x=10.0, y=10.0, easing="linear"),
            TimelineKeyframe(id="k2", time=2.0, x=20.0, y=0.0, easing="linear"),
        ]
        linear_obj.keyframes = [TimelineKeyframe.from_dict(k.to_dict()) for k in keys]
        spline_obj.keyframes = [TimelineKeyframe.from_dict(k.to_dict()) for k in keys]

        linear_state = scene.evaluate_object_state(project, linear_obj.id, 0.5)
        spline_state = scene.evaluate_object_state(project, spline_obj.id, 0.5)
        self.assertIsNotNone(linear_state)
        self.assertIsNotNone(spline_state)
        assert linear_state is not None and spline_state is not None
        self.assertAlmostEqual(linear_state["y"], 5.0, places=6)
        self.assertGreater(spline_state["y"], linear_state["y"])

    def test_spline_holds_still_between_keys_at_the_same_spot(self):
        project = Project(name="Timeline Spline Hold")
        scene = project.create_timeline_scene("Hold Scene")
        obj = scene.create_object("Spline", source_type="none", source_id=None)
        obj.path_mode = "spline"
        obj.keyframes = [
            TimelineKeyframe(id="k0", time=0.0, x=0.0, y=0.0, easing="linear"),
            TimelineKeyframe(id="k1", time=1.0, x=10.0, y=10.0, easing="linear"),
            TimelineKeyframe(id="k2", time=2.0, x=10.0, y=10.0, easing="linear"),
            TimelineKeyframe(id="k3", time=3.0, x=30.0, y=0.0, easing="linear"),
            TimelineKeyframe(id="k4", time=4.0, x=40.0, y=20.0, easing="linear"),
        ]
        for time in (1.25, 1.5, 1.75):
            state = scene.evaluate_object_state(project, obj.id, time)
            assert state is not None
            self.assertAlmostEqual(state["x"], 10.0, places=6)
            self.assertAlmostEqual(state["y"], 10.0, places=6)
        # Neighbouring segments still curve.
        curved = scene.evaluate_object_state(project, obj.id, 2.5)
        assert curved is not None
        self.assertNotAlmostEqual(curved["y"], 5.0, places=3)
        # An explicit handle still shapes the segment between equal keys.
        obj.keyframes[1].path_out = (20.0, 10.0)
        shaped = scene.evaluate_object_state(project, obj.id, 1.5)
        assert shaped is not None
        self.assertGreater(shaped["x"], 10.0)

    def test_linear_mode_ignores_explicit_path_handles(self):
        project = Project(name="Timeline Path Handles")
        scene = project.create_timeline_scene("Handle Scene")
        linear_obj = scene.create_object("Linear", source_type="none", source_id=None)
        spline_obj = scene.create_object("Spline", source_type="none", source_id=None)
        spline_obj.path_mode = "spline"
        keys = [
            TimelineKeyframe(
                id="k0",
                time=0.0,
                x=0.0,
                y=0.0,
                easing="linear",
                path_out=(0.0, 20.0),
            ),
            TimelineKeyframe(
                id="k1",
                time=1.0,
                x=20.0,
                y=0.0,
                easing="linear",
                path_in=(20.0, 20.0),
            ),
        ]
        linear_obj.keyframes = [TimelineKeyframe.from_dict(k.to_dict()) for k in keys]
        spline_obj.keyframes = [TimelineKeyframe.from_dict(k.to_dict()) for k in keys]

        linear_state = scene.evaluate_object_state(project, linear_obj.id, 0.5)
        spline_state = scene.evaluate_object_state(project, spline_obj.id, 0.5)
        self.assertIsNotNone(linear_state)
        self.assertIsNotNone(spline_state)
        assert linear_state is not None and spline_state is not None
        self.assertAlmostEqual(linear_state["x"], 10.0, places=6)
        self.assertAlmostEqual(linear_state["y"], 0.0, places=6)
        self.assertGreater(spline_state["y"], 0.0)

    def test_project_json_round_trip_keeps_timeline_scenes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, "dummy.png")
            with open(image_path, "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n")

            project = Project(name="Timeline File")
            project.create_image(image_path, 16, 16)
            scene = project.create_timeline_scene("Title")
            scene.create_object("Logo", source_type="none", source_id=None)

            json_path = os.path.join(tmpdir, "timeline.json")
            project.to_json(json_path)
            loaded = Project.from_json(json_path)

            self.assertEqual(len(loaded.timeline_scenes), 1)
            self.assertEqual(loaded.timeline_scenes[0].name, "Title")

    def test_scene_sampling_holds_key_source_until_next_override(self):
        project = Project(name="Timeline Source Hold")
        frame_a = Frame(id="frm_a", name="A")
        frame_b = Frame(id="frm_b", name="B")
        frame_c = Frame(id="frm_c", name="C")
        project.frames.extend([frame_a, frame_b, frame_c])

        scene = project.create_timeline_scene("Source Hold")
        obj = scene.create_object("Actor", source_type="frame", source_id="frm_a")
        obj.keyframes = [
            TimelineKeyframe(id="k0", time=0.0, x=0.0, y=0.0),
            TimelineKeyframe(id="k1", time=1.0, x=10.0, y=0.0, source_type="frame", source_id="frm_b"),
            TimelineKeyframe(id="k2", time=2.0, x=20.0, y=0.0),
            TimelineKeyframe(id="k3", time=3.0, x=30.0, y=0.0, source_type="frame", source_id="frm_c"),
        ]

        state_0_5 = scene.evaluate_object_state(project, obj.id, 0.5)
        state_1_5 = scene.evaluate_object_state(project, obj.id, 1.5)
        state_2_5 = scene.evaluate_object_state(project, obj.id, 2.5)
        state_3_2 = scene.evaluate_object_state(project, obj.id, 3.2)
        self.assertIsNotNone(state_0_5)
        self.assertIsNotNone(state_1_5)
        self.assertIsNotNone(state_2_5)
        self.assertIsNotNone(state_3_2)
        assert state_0_5 is not None and state_1_5 is not None and state_2_5 is not None and state_3_2 is not None
        self.assertEqual(state_0_5["frame_id"], "frm_a")
        self.assertEqual(state_1_5["frame_id"], "frm_b")
        self.assertEqual(state_2_5["frame_id"], "frm_b")
        self.assertEqual(state_3_2["frame_id"], "frm_c")

    def test_scene_sampling_applies_step_key_source_offset(self):
        project = Project(name="Timeline Source Offset")
        scene = project.create_timeline_scene("Source Offset")
        obj = scene.create_object("Actor", source_type="none", source_id=None)
        obj.keyframes = [
            TimelineKeyframe(id="k0", time=0.0, x=0.0, y=0.0, source_offset=(0.0, 0.0)),
            TimelineKeyframe(id="k1", time=1.0, x=10.0, y=0.0, source_offset=(5.0, 1.0)),
            TimelineKeyframe(id="k2", time=2.0, x=20.0, y=0.0, source_offset=(-2.0, 3.0)),
        ]

        state_0_5 = scene.evaluate_object_state(project, obj.id, 0.5)
        state_1_5 = scene.evaluate_object_state(project, obj.id, 1.5)
        state_2_5 = scene.evaluate_object_state(project, obj.id, 2.5)
        self.assertIsNotNone(state_0_5)
        self.assertIsNotNone(state_1_5)
        self.assertIsNotNone(state_2_5)
        assert state_0_5 is not None and state_1_5 is not None and state_2_5 is not None
        self.assertEqual(tuple(state_0_5["source_offset"]), (0.0, 0.0))
        self.assertEqual(tuple(state_1_5["source_offset"]), (5.0, 1.0))
        self.assertEqual(tuple(state_2_5["source_offset"]), (-2.0, 3.0))
        self.assertEqual(tuple(state_1_5["source_key_offset"]), (5.0, 1.0))

    def test_animation_swapped_in_at_a_later_key_plays_from_that_key(self):
        project = Project(name="Swap Restart")
        anim = Animation(id="a", name="strike", fps=10)
        anim.aframes = [AFrame(frame_id=f"f{i}", duration_frames=1) for i in range(4)]
        project.animations.append(anim)
        scene = project.create_timeline_scene("Swap")
        scene.fps = 10
        obj = scene.create_object("Fighter", source_type="animation", source_id="a")
        obj.playback_mode = "once"
        obj.keyframes = [
            TimelineKeyframe(id="k0", time=0.0),
            TimelineKeyframe(id="k1", time=1.0, source_type="animation", source_id="a"),
            TimelineKeyframe(id="k2", time=1.5),
            TimelineKeyframe(id="k3", time=2.0, source_type="animation", source_id="a"),
        ]

        def shown(t: float) -> str:
            return scene.evaluate_object_state(project, obj.id, t)["frame_id"]

        self.assertEqual([shown(t) for t in (0.05, 0.35, 0.95)], ["f0", "f3", "f3"])  # own source: from the start
        self.assertEqual([shown(t) for t in (1.05, 1.25, 1.65)], ["f0", "f2", "f3"])  # swapped in at 1.0
        self.assertEqual([shown(t) for t in (2.05, 2.15)], ["f0", "f1"])  # the same animation again restarts

        # A swap on the first key replaces the object's source from the scene start, offset included.
        obj.keyframes[0].source_type, obj.keyframes[0].source_id = "animation", "a"
        obj.playback_offset = 0.2
        self.assertEqual(shown(0.05), "f2")

    def test_object_mapping_inherits_from_parent_then_default(self):
        project = Project(name="Mappings")
        guard = ModuleMapping(id="map_guard", name="Normal", map={"m1": "m2"})
        hidden = ModuleMapping(id="map_hide", name="Hidden", map={"m1": None})
        project.mappings += [guard, hidden]
        scene = project.create_timeline_scene("Fight")
        group = scene.create_object("Guard group")
        guard_obj = scene.create_object("Guard", source_type="frame", source_id="f", parent_id=group.id)
        prince = scene.create_object("Prince", source_type="frame", source_id="f")

        self.assertIs(scene.object_mapping(project, prince.id, hidden), hidden)  # top level: the default
        self.assertIsNone(scene.object_mapping(project, prince.id, None))
        group.mapping_id = guard.id
        self.assertIs(scene.object_mapping(project, guard_obj.id, hidden), guard)  # from the parent
        guard_obj.mapping_id = TIMELINE_MAPPING_ORIGINAL
        self.assertIsNone(scene.object_mapping(project, guard_obj.id, hidden))
        guard_obj.mapping_id = "deleted_mapping"  # dangling ids count as unset
        self.assertIs(scene.object_mapping(project, guard_obj.id, hidden), guard)

        loaded = Project.from_dict(project.to_dict()).timeline_scenes[0]
        self.assertEqual([o.mapping_id for o in loaded.objects], [guard.id, "deleted_mapping", None])

    def test_legacy_duration_frames_scene_loads_as_seconds(self):
        payload = {
            "id": "scene_legacy",
            "name": "Legacy",
            "fps": 25,
            "duration_frames": 50,
            "loop": True,
            "background_color": [32, 32, 32],
            "objects": [
                {
                    "id": "obj_1",
                    "name": "Legacy Object",
                    "source_type": "none",
                    "playback_offset": 10.0,
                    "keyframes": [{"id": "k0", "time": 25.0}],
                }
            ],
        }

        scene = Project.from_dict({"name": "Legacy Test", "timeline_scenes": [payload]}).timeline_scenes[0]
        self.assertAlmostEqual(scene.duration_seconds, 2.0)
        self.assertEqual(scene.duration_in_frames(), 50)
        self.assertAlmostEqual(scene.objects[0].playback_offset, 0.4)
        self.assertAlmostEqual(scene.objects[0].keyframes[0].time, 1.0)


if __name__ == "__main__":
    unittest.main()
