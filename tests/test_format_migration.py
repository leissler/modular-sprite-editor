import json
import os
import subprocess
import sys
import tempfile
import unittest

from models import PROJECT_FORMAT_VERSION, Palette, Project, migrate_project_dict


def _legacy_project_dict():
    return {
        "name": "Legacy",
        "images": [],
        "modules": [
            {"id": "m_line", "name": "line", "image_id": "missing", "rect": [0, 0, 10, 20], "pivot": [0, 0],
             "type": "MD_LINE", "params": [5, 20]},
            {"id": "m_tri", "name": "tri", "image_id": "missing", "rect": [0, 0, 10, 10], "pivot": [0, 0],
             "type": "MD_TRIANGLE", "params": [10, 0, 0, 10]},
        ],
        "frames": [
            {
                "id": "f1",
                "name": "frame",
                "fmodules": [],
                "collision_rects": [{"id": "c1", "type_id": "t", "rect": [0, 0, 4, 4]}],
                "control_points": [{"id": "p1", "type_id": "t", "x": 1, "y": 2, "name": "hand"}],
            }
        ],
        "animations": [
            {"id": "a1", "name": "anim", "aframes": [
                {"frame_id": "f1", "duration_ms": 300},
                {"frame_id": "f1", "duration_ms": 2},
            ]}
        ],
        "timeline_scenes": [
            {"id": "s1", "name": "scene", "fps": 10, "duration_frames": 50, "objects": [
                {"id": "o1", "name": "obj", "playback_offset": 5,
                 "keyframes": [{"id": "k1", "time": 20}]}
            ]}
        ],
        "custom_tool_data": {"keep": True},
    }


class TestFormatMigration(unittest.TestCase):
    def test_v1_migration_canonicalizes_legacy_fields(self):
        source = _legacy_project_dict()
        migrated, notes = migrate_project_dict(source)

        self.assertEqual(migrated["format_version"], PROJECT_FORMAT_VERSION)
        self.assertEqual(list(migrated.keys())[0], "format_version")
        self.assertNotIn("format_version", source, "input dict must not be mutated")
        self.assertEqual(migrated["custom_tool_data"], {"keep": True})

        aframes = migrated["animations"][0]["aframes"]
        self.assertEqual([af["duration_frames"] for af in aframes], [3, 2])
        self.assertTrue(all("duration_ms" not in af for af in aframes))

        cp = migrated["frames"][0]["control_points"][0]
        self.assertEqual(cp["role"], "hand")
        self.assertNotIn("name", cp)
        self.assertEqual(migrated["frames"][0]["collision_rects"][0]["role"], "")

        scene = migrated["timeline_scenes"][0]
        self.assertAlmostEqual(scene["duration_seconds"], 5.0)
        self.assertAlmostEqual(scene["objects"][0]["playback_offset"], 0.5)
        self.assertAlmostEqual(scene["objects"][0]["keyframes"][0]["time"], 2.0)

        line = migrated["modules"][0]["params"]
        self.assertEqual(line, [0.0, 0.0, 50.0, 100.0])
        tri = migrated["modules"][1]["params"]
        self.assertEqual(tri, [0.0, 0.0, 100.0, 0.0, 0.0, 100.0])
        self.assertTrue(notes)

    def test_migrated_dict_loads_like_legacy_dict(self):
        legacy_project = Project.from_dict(_legacy_project_dict())
        migrated, _notes = migrate_project_dict(_legacy_project_dict())
        migrated_project = Project.from_dict(migrated)

        legacy_out = legacy_project.to_dict()
        migrated_out = migrated_project.to_dict()
        self.assertEqual(legacy_out, migrated_out)

    def test_v2_to_v3_adds_event_and_loop_fields(self):
        v2 = {"format_version": 2, "name": "v2", "images": [], "modules": [], "frames": [],
              "animations": [{"id": "a1", "name": "anim", "aframes": [{"frame_id": "f1", "duration_frames": 2}]}]}
        migrated, notes = migrate_project_dict(v2)
        self.assertEqual(migrated["format_version"], PROJECT_FORMAT_VERSION)
        self.assertEqual(migrated["event_types"], [])
        anim = migrated["animations"][0]
        self.assertEqual((anim["loop_start"], anim["next_animation_id"]), (0, None))
        self.assertEqual(anim["aframes"][0]["events"], [])
        self.assertEqual(anim["aframes"][0]["duration_frames"], 2)  # untouched
        self.assertEqual(notes, [])

    def test_v3_to_v4_scene_objects_inherit_their_mapping(self):
        v3 = {"format_version": 3, "name": "v3", "images": [], "modules": [], "frames": [], "mappings": [],
              "timeline_scenes": [{"id": "s", "name": "scene", "fps": 10, "duration_seconds": 1.0, "objects": [
                  {"id": "o", "name": "obj", "source_type": "none", "keyframes": [{"id": "k", "time": 0.0}]}]}]}
        migrated, notes = migrate_project_dict(v3)
        self.assertEqual(migrated["format_version"], PROJECT_FORMAT_VERSION)
        self.assertIsNone(migrated["timeline_scenes"][0]["objects"][0]["mapping_id"])
        self.assertEqual(notes, [])
        self.assertIsNone(Project.from_dict(migrated).timeline_scenes[0].objects[0].mapping_id)

    def test_v4_to_v5_objects_keep_their_playback_mode(self):
        def obj(ident, mode, keys, source="a_pp"):
            data = {"id": ident, "name": ident, "source_type": "animation", "source_id": source, "keyframes": keys}
            if mode is not None:
                data["playback_mode"] = mode
            return data

        still = [{"id": "k0", "time": 0.0}, {"id": "k1", "time": 1.0, "x": 5.0}]
        turning = [{"id": "k0", "time": 0.0}, {"id": "k1", "time": 1.0, "flip_x": True}]
        v4 = {"format_version": 4, "name": "v4", "images": [], "modules": [], "frames": [], "mappings": [],
              "animations": [{"id": "a_pp", "name": "pp", "aframes": [{"frame_id": "f", "duration_frames": 1}] * 3}],
              "timeline_scenes": [
                  {"id": "s1", "name": "Calm", "fps": 10, "duration_seconds": 1.0, "objects": [
                      obj("unset", None, still), obj("once", "once", still), obj("pp", "ping_pong", still)]},
                  {"id": "s2", "name": "Duel", "fps": 10, "duration_seconds": 1.0, "objects": [
                      obj("turns", "loop", turning)]},
              ]}
        migrated, notes = migrate_project_dict(v4)
        modes = [o["playback_mode"] for scene in migrated["timeline_scenes"] for o in scene["objects"]]
        self.assertEqual(modes, ["loop", "once", "ping_pong", "loop"], "the old default was Loop")
        self.assertEqual(len(notes), 2)
        self.assertIn("1 Timeline object(s) set to Ping-pong", notes[0])
        self.assertIn("scene(s): Duel.", notes[1])
        loaded = Project.from_dict(migrated)
        self.assertEqual([o.playback_mode for o in loaded.timeline_scenes[0].objects], ["loop", "once", "ping_pong"])
        self.assertEqual(loaded.timeline_scenes[0].create_object("new").playback_mode, "as_animated")
        again, notes = migrate_project_dict(migrated)
        self.assertEqual((again, notes), (migrated, []))

    def test_v5_images_start_in_the_first_palette(self):
        v5 = {"format_version": 5, "name": "v5", "modules": [], "frames": [],
              "images": [{"id": "img", "file_path": "sheet.png", "width": 8, "height": 8, "transparent_color": None}]}
        migrated, notes = migrate_project_dict(v5)
        self.assertEqual((migrated["format_version"], migrated["images"][0]["palette_id"], notes),
                         (PROJECT_FORMAT_VERSION, "pal_1", []))
        self.assertEqual(migrated["palettes"], [{"id": "pal_1", "name": "Palette 1", "colours": None, "cycles": []}])
        project = Project.from_dict(migrated)
        self.assertIsNone(project.palettes[0].colours, "its image can't be read yet: built once it can")
        project.palettes.append(Palette("pal_x", "Second"))
        project.images[0].palette_id = "pal_x"
        self.assertEqual(Project.from_dict(project.to_dict()).images[0].palette_id, "pal_x")
        broken = dict(migrated, images=[dict(migrated["images"][0], palette_id="gone")])
        loaded = Project.from_dict(broken)
        self.assertIs(loaded.image_palette(loaded.images[0]), loaded.palettes[0], "an unknown palette counts as the first")

    def test_v6_to_v7_palettes_keep_their_numbers_and_colours(self):
        import tempfile
        from collections import Counter

        import palettes
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            colours = {"hero.png": [(200, 40, 40)] * 3 + [(20, 20, 20)], "slime.png": [(0, 250, 0), (0, 120, 0)]}
            for name, pixels in colours.items():
                image = Image.new("RGBA", (len(pixels), 1), (0, 0, 0, 0))
                for x, rgb in enumerate(pixels):
                    image.putpixel((x, 0), rgb + (255,))
                image.save(os.path.join(folder, name))
            v6 = {"format_version": 6, "name": "v6", "modules": [],
                  "images": [{"id": "hero", "file_path": "hero.png", "width": 4, "height": 1, "palette": 0},
                             {"id": "slime", "file_path": "slime.png", "width": 2, "height": 1, "palette": 2}],
                  "frames": [{"id": "f", "name": "f"}], "animations": [{"id": "a", "name": "a"}],
                  "timeline_scenes": [{"id": "s", "name": "s", "objects": [{"id": "o", "name": "o"}]}]}
            migrated, notes = migrate_project_dict(v6)
            self.assertEqual(notes, [])
            self.assertEqual([(p["id"], p["name"]) for p in migrated["palettes"]],
                             [("pal_1", "Palette 1"), ("pal_3", "Palette 3")], "the numbers images use, and the first")
            self.assertEqual([i["palette_id"] for i in migrated["images"]], ["pal_1", "pal_3"])
            self.assertTrue(all("palette" not in i for i in migrated["images"]))
            obj = migrated["timeline_scenes"][0]["objects"][0]
            self.assertIsNone(obj["palette_swap_id"])
            self.assertEqual((migrated["console"], migrated["palette_swaps"]), ("megadrive", []))

            project = Project.from_dict(migrated, base_path=folder)  # the colours come from the images, as in format 6
            hero, slime = project.palettes
            self.assertEqual(hero.colours, [(200, 40, 40), (20, 20, 20)], "most used first")
            self.assertEqual(slime.colours, palettes.build_colours(Counter({(0, 250, 0): 1, (0, 120, 0): 1}), 15))
            again, notes = migrate_project_dict(migrated)
            self.assertEqual((again, notes), (migrated, []))
            saved = Project.from_dict(json.loads(json.dumps(project.to_dict())))
            self.assertEqual(saved.palettes[0].colours, hero.colours, "once built, the colours are stored")

    def test_v3_events_loop_and_follow_up_round_trip(self):
        from models import AFrame, Animation, EventType, StepEvent

        project = Project()
        project.event_types.append(EventType(id="ev_hit", name="hit_on", color=(255, 80, 80)))
        idle = Animation(id="a_idle", name="idle")
        attack = Animation(id="a_atk", name="attack", playback_type="forward", loop_start=1, next_animation_id="a_idle")
        attack.aframes = [AFrame(frame_id="f", duration_frames=1, events=[StepEvent("ev_hit", 3)]),
                          AFrame(frame_id="f", duration_frames=2)]
        project.animations += [idle, attack]
        again = Project.from_dict(json.loads(json.dumps(project.to_dict())))
        self.assertEqual(again.event_types[0].name, "hit_on")
        a = again.get_animation("a_atk")
        self.assertEqual((a.loop_start, a.next_animation_id), (1, "a_idle"))
        self.assertEqual([(e.type_id, e.value) for e in a.aframes[0].events], [("ev_hit", 3)])
        self.assertEqual(a.aframes[1].events, [])

    def test_loop_start_keeps_the_intro_out_of_later_passes(self):
        import playback
        from models import AFrame, Animation

        anim = Animation(id="a", name="a", playback_type="loop", loop_start=1)
        anim.aframes = [AFrame(frame_id=f"f{i}", duration_frames=1) for i in range(3)]
        self.assertEqual(playback.steps_shown(anim, 9), [0, 1, 2, 1, 2, 1, 2, 1, 2])

    def test_current_version_is_idempotent(self):
        migrated, _ = migrate_project_dict(_legacy_project_dict())
        again, notes = migrate_project_dict(migrated)
        self.assertEqual(migrated, again)
        self.assertEqual(notes, [])

    def test_newer_version_is_left_alone_with_warning(self):
        data = {"format_version": PROJECT_FORMAT_VERSION + 1, "frames": [], "modules": []}
        migrated, notes = migrate_project_dict(data)
        self.assertEqual(migrated["format_version"], PROJECT_FORMAT_VERSION + 1)
        self.assertEqual(len(notes), 1)
        project = Project.from_dict(data)
        self.assertEqual(len(project.load_notes), 1)

    def test_saved_project_carries_version(self):
        project = Project.from_dict(_legacy_project_dict())
        self.assertEqual(project.to_dict()["format_version"], PROJECT_FORMAT_VERSION)

    def test_migration_tool_preserves_unknown_keys_and_backs_up(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = os.path.join(tmpdir, "legacy.json")
            other_path = os.path.join(tmpdir, "retro.json")
            with open(project_path, "w", encoding="utf-8") as f:
                json.dump(_legacy_project_dict(), f)
            with open(other_path, "w", encoding="utf-8") as f:
                json.dump({"ProjectType": "RetroAnimator", "Frames": {}}, f)
            with open(other_path, "rb") as f:
                other_before = f.read()

            backup = os.path.join(tmpdir, "backup.zip")
            subprocess.run(
                [sys.executable, os.path.join(repo_root, "tools", "migrate_projects.py"), "--backup-zip", backup, tmpdir],
                check=True,
                capture_output=True,
            )

            with open(project_path, "r", encoding="utf-8") as f:
                upgraded = json.load(f)
            self.assertEqual(upgraded["format_version"], PROJECT_FORMAT_VERSION)
            self.assertEqual(upgraded["custom_tool_data"], {"keep": True})
            with open(other_path, "rb") as f:
                self.assertEqual(f.read(), other_before)
            self.assertTrue(os.path.exists(backup))


if __name__ == "__main__":
    unittest.main()
