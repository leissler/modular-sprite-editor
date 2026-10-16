"""Sprite sheets for other engines (exporters/sheet.py) and the Aseprite import (importers/aseprite.py)."""

import json
import os
import re
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import compositor  # noqa: E402
from exporters import sheet  # noqa: E402
from importers import aseprite  # noqa: E402
from models import Project  # noqa: E402

POP = ROOT / "examples" / "pop" / "PoP_WW.json"
IDENTITY = ((1.0, 0.0), (0.0, 1.0))


def _cut(image, left, top):
    image = image.convert("RGBA")
    box = image.getbbox()
    if box is None:
        return None
    return image.crop(box).tobytes(), image.crop(box).size, left + box[0], top + box[1]


def _frame_picture(project, frame, a=IDENTITY, b=(0.0, 0.0)):
    image, left, top, _boxes = compositor.render_frame(project, frame, None, a, b, {}, {})
    return _cut(image, left, top)


class SheetExportTest(unittest.TestCase):
    def test_json_round_trip_draws_every_step_the_same(self):
        """Export PoP's animations as a sheet with JSON, import that: every imported frame draws exactly the step it
        came from, at the same place relative to the origin; tags come back as the animations."""
        project = Project.from_json(str(POP))
        project.animations = project.animations[:20]  # (enough steps, and quick)
        with tempfile.TemporaryDirectory() as tmp:
            report = sheet.export_sheet(project, os.path.join(tmp, "pop.png"), "json")
            data = json.load(open(report["data"], encoding="utf-8"))
            self.assertEqual(len(data["frames"]), report["entries"])
            self.assertEqual(len(data["meta"]["frameTags"]), len(project.animations))
            imported = aseprite.parse_sheet_json(report["data"])
            steps = [(anim, af) for anim in project.animations for af in anim.aframes if project.get_frame(af.frame_id)]
            self.assertEqual(len(imported.frames), len(steps))
            self.assertLess(len(imported.modules), len(steps), "identical pictures are stored once")
            for frame, (anim, af) in zip(imported.frames, steps):  # (the sheet is still there)
                a, b = sheet.step_transform(af)
                expected = _frame_picture(project, project.get_frame(af.frame_id), a, b)
                self.assertIsNotNone(expected)
                self.assertEqual(_frame_picture(imported, frame), expected, f"{anim.name}: {frame.name}")
        for original, back in zip(project.animations, imported.animations):
            self.assertEqual(back.name, original.name)
            self.assertEqual([af.duration_frames * 1000 // back.fps for af in back.aframes],  # the same timing
                             [max(1, af.duration_frames) * 1000 // original.fps for af in original.aframes], original.name)

    def test_godot_and_unity_files(self):
        project = Project.from_json(str(POP))
        anims = project.animations[:3]
        with tempfile.TemporaryDirectory() as tmp:
            godot = sheet.export_sheet(project, os.path.join(tmp, "g.png"), "godot", animations=anims)
            unity = sheet.export_sheet(project, os.path.join(tmp, "u.png"), "unity", animations=anims, scale=2)
            tres = open(godot["data"], encoding="utf-8").read()
            meta = open(unity["data"], encoding="utf-8").read()
            self.assertTrue(godot["data"].endswith("g.tres") and unity["data"].endswith("u.png.meta"))
            self.assertEqual(tres.count('type="AtlasTexture"'), godot["cells"])
            self.assertEqual(len(re.findall(r'"name": &"', tres)), 3)
            self.assertIn('path="g.png"', tres)
            self.assertEqual(meta.count("      name: "), unity["cells"])
            self.assertIn("spriteMode: 2", meta)
            self.assertIn("filterMode: 0", meta)
            self.assertEqual(unity["size"][0] % 2, 0, "scaled ×2")

    def test_png_sequence_on_one_canvas(self):
        project = Project.from_json(str(POP))
        anim = next(a for a in project.animations if len(a.aframes) >= 3)
        with tempfile.TemporaryDirectory() as tmp:
            steps = sheet.export_png_sequence(project, anim, os.path.join(tmp, "s"))
            ticks = sheet.export_png_sequence(project, anim, os.path.join(tmp, "t"), per_tick=True)
            from PIL import Image

            sizes = {Image.open(p).size for p in steps}
        self.assertEqual(len(steps), len(sheet.cycle(anim)))
        self.assertEqual(len(ticks), sum(max(1, anim.aframes[i].duration_frames) for i in sheet.cycle(anim)))
        self.assertEqual(len(sizes), 1, "one canvas: the origin stays put")


def _clip_project(folder):
    """Five frames of different pictures, and animations in every playback mode with uneven holds."""
    from PIL import Image

    from models import AFrame, FModule, generate_id

    path = os.path.join(folder, "strip.png")
    image = Image.new("RGBA", (40, 8), (0, 0, 0, 0))
    for i in range(5):
        image.paste((40 * i, 200, 100, 255), (8 * i, 0, 8 * i + 4 + i % 4, 8))
    image.save(path)
    project = Project()
    asset = project.create_image(path, 40, 8)
    frames = []
    for i in range(5):
        module = project.create_module(f"m{i}", asset.id, (8 * i, 0, 8, 8), (0, 0))
        frame = project.create_frame(f"f{i}")
        frame.fmodules.append(FModule(id=generate_id("fm"), ref_type="module", ref_id=module.id, position=(0, 0)))
        frames.append(frame)
    holds = [1, 2, 3, 1, 2]

    def anim(name, playback, loop_count=0, loop_start=0, steps=5):
        made = project.create_animation(name)
        made.playback_type, made.loop_count, made.loop_start, made.fps = playback, loop_count, loop_start, 12
        made.aframes = [AFrame(frame_id=frames[i].id, duration_frames=holds[i]) for i in range(steps)]
        return made

    cases = [anim("once", "forward"), anim("loop", "loop"), anim("loop from 2", "loop", loop_start=2),
             anim("loop 3 times from 1", "loop", 3, 1), anim("backward", "backward"), anim("backward twice", "backward", 2),
             anim("ping-pong", "ping_pong"), anim("ping-pong twice", "ping_pong", 2), anim("ping-pong one step", "ping_pong", steps=1),
             anim("ping-pong two steps", "ping_pong", steps=2)]
    cases[0].next_animation_id = cases[2].id  # once, then loop from 2
    cases[7].next_animation_id = cases[0].id  # ping-pong twice, then once
    cases[1].next_animation_id = cases[0].id  # loops forever: never follows up
    return project, cases


class EngineClipsTest(unittest.TestCase):
    """What Godot and Unity get: clips that play like the editor, game data moved like the pictures."""

    def test_clips_play_every_mode_like_the_editor(self):
        import playback

        with tempfile.TemporaryDirectory() as tmp:
            project, cases = _clip_project(tmp)
            built = sheet.build_sheet(project)
        clips = sheet.clips(built)
        by_name = {c.name: c for c in clips}
        self.assertEqual([c.name for c in clips if built.tags[c.tag].name == "loop from 2"], ["loop from 2", "loop from 2 loop"])
        self.assertEqual(by_name["once"].next, "loop from 2")
        self.assertIsNone(by_name["loop"].next, "it never ends")

        def engine_shows(name, ticks):
            """(tag, step) an engine shows ``ticks`` ticks after it starts the clip ``name``."""
            clip = by_name[name]
            while True:
                holds = [built.entries[i].hold for i in clip.entries]
                total = sum(holds)
                if ticks >= total and clip.loops:
                    ticks %= total
                if ticks < total:
                    for index, hold in zip(clip.entries, holds):
                        if ticks < hold:
                            return clip.tag, index - built.tags[clip.tag].first
                        ticks -= hold
                if clip.next is None:
                    return clip.tag, clip.entries[-1] - built.tags[clip.tag].first
                ticks -= total
                clip = by_name[clip.next]

        def editor_shows(anim, ticks):
            """(tag, step) the editor shows: the animation, then its follow-ups once it ends."""
            while True:
                step, ended = playback.step_after(anim, ticks, playback.own_rules(anim))
                follow = project.get_animation(anim.next_animation_id or "")
                if ended is None or follow is None:
                    return tag_of[anim.name], step
                anim, ticks = follow, ticks - ended

        tag_of = {t.name: i for i, t in enumerate(built.tags)}
        for anim in cases:
            for ticks in range(120):
                with self.subTest(animation=anim.name, ticks=ticks):
                    self.assertEqual(engine_shows(anim.name, ticks), editor_shows(anim, ticks))

    def test_names_stay_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cases = _clip_project(tmp)
            cases[1].name = cases[2].name = ""
            built = sheet.build_sheet(project)
        names = [t.name for t in built.tags]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("Animation", names)
        self.assertIn("Animation 2", names)

    def test_markers_move_like_the_mega_drive_export(self):
        """A step's hitboxes and points, flipped, turned and moved, land where the SGDK export puts them."""
        sys.path.insert(0, str(ROOT / "examples" / "megadrive" / "tools"))
        import export_megadrive as sg

        project = Project.from_json(str(POP))
        frame = next(f for f in project.frames if f.collision_rects and f.control_points)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = sg.MegaDriveBakeContext(project, [None], Path(tmp))
        for flip_x in (False, True):
            for flip_y in (False, True):
                for rotation in (0.0, 90.0, 180.0, 270.0):
                    a = compositor.mat_mul(compositor.rotation_matrix(rotation), compositor.flip_matrix(flip_x, flip_y))
                    boxes, points = sheet.step_markers(project, frame, a, (3.0, -2.0))
                    want_boxes, want_points = ctx._frame_markers(frame, (3.0, -2.0), rotation, flip_x, flip_y)
                    self.assertEqual([(b.x, b.y, b.w, b.h) for b in boxes], [tuple(w[2:]) for w in want_boxes])
                    self.assertEqual([(p.x, p.y) for p in points], [tuple(w[2:]) for w in want_points])
        self.assertEqual({b.kind for b in boxes}, {"Hurt"})
        self.assertIn("head", {b.role for b in boxes})

    def test_godot_scene(self):
        project = Project.from_json(str(POP))
        anims = [a for a in project.animations if any(af.events for af in a.aframes)][:2] + project.animations[:2]
        anims[2].playback_type, anims[2].loop_start = "loop", 1
        with tempfile.TemporaryDirectory() as tmp:
            report = sheet.export_sheet(project, os.path.join(tmp, "hero.png"), "godot", animations=anims)
            names = sorted(os.path.basename(f) for f in report["files"])
            scene = open(os.path.join(tmp, "hero.tscn"), encoding="utf-8").read()
        self.assertEqual(names, ["hero.gd", "hero.tres", "hero.tscn"])
        self.assertEqual(report["clips"], 5, "four animations, one with an intro before its loop")
        self.assertEqual(scene.count('[sub_resource type="Animation"'), 5)
        for node in ('[node name="Sprite" type="AnimatedSprite2D"', '[node name="Hurt head" type="Area2D" parent="Hitboxes"]',
                     '[node name="Shape" type="CollisionShape2D" parent="Hitboxes/Hurt head"]',
                     '[node name="Ground feet" type="Marker2D" parent="Points"]', 'script = ExtResource("2_events")',
                     f'"next/{anims[2].name}" = &"{anims[2].name} loop"', '"method": &"_sprite_events"',
                     'NodePath("Hitboxes/Hurt head/Shape:shape:size")', "texture_filter = 1"):
            self.assertIn(node, scene)

    def test_unity_assets(self):
        import zlib

        from exporters import unity

        project = Project.from_json(str(POP))
        anims = [a for a in project.animations if any(af.events for af in a.aframes)][:2]
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "hero.png")
            report = sheet.export_sheet(project, png, "unity", animations=anims)
            meta = open(png + ".meta", encoding="utf-8").read()
            clip = open(next(f for f in report["files"] if f.endswith(".anim")), encoding="utf-8").read()
            controller = open(os.path.join(tmp, "hero.controller"), encoding="utf-8").read()
            prefab = open(os.path.join(tmp, "hero.prefab"), encoding="utf-8").read()
            files = {os.path.relpath(f, tmp) for f in report["files"]}
        self.assertIn(os.path.join("hero Animations", sheet.safe_name(anims[0].name) + ".anim.meta"), files)
        self.assertEqual(len([f for f in files if f.endswith(".anim")]), report["clips"])
        self.assertIn("serializedVersion: 13", meta)
        self.assertIn("nameFileIdTable:", meta, "Unity keeps the sprite ids the clips use")
        seed = os.path.abspath(png)
        for index in range(report["cells"]):
            self.assertIn(f"internalID: {unity.sprite_id(seed, index)}", meta)
        self.assertIn(f"guid: {unity.guid(seed)}, type: 3", clip)
        self.assertIn(f"path: {zlib.crc32('Hitboxes/Hurt head'.encode())}", clip)
        self.assertIn(f"attribute: {zlib.crc32(b'm_Offset.x')}", clip)
        self.assertIn("functionName: OnSpriteEvent", clip)
        self.assertIn("messageOptions: 1", clip, "silent without a receiver")
        self.assertEqual(controller.count("--- !u!1102 "), report["clips"])
        self.assertIn(f"guid: {unity.guid(os.path.join(tmp, 'hero.controller'))}, type: 2", prefab)
        self.assertIn("m_IsTrigger: 1", prefab)
        self.assertIn("m_Name: Hitboxes", prefab)

    def test_json_carries_the_game_data(self):
        project = Project.from_json(str(POP))
        anim = next(a for a in project.animations if any(af.events for af in a.aframes))
        with tempfile.TemporaryDirectory() as tmp:
            report = sheet.export_sheet(project, os.path.join(tmp, "hero.png"), "json", animations=[anim], scale=2)
            frames = json.load(open(report["data"], encoding="utf-8"))["frames"]
        first = next(iter(frames.values()))
        self.assertTrue(first["hitboxes"] and first["points"])
        self.assertEqual({"type", "role", "x", "y", "w", "h"}, set(first["hitboxes"][0]))
        self.assertTrue(all(v % 2 == 0 for box in first["hitboxes"] for v in (box["x"], box["y"], box["w"], box["h"])),
                        "scaled ×2 with the pictures")
        self.assertTrue(any("events" in f for f in frames.values()))

# ---------------------------------------------------------------------------- a tiny Aseprite writer for the tests
def _chunk(kind, body):
    return struct.pack("<IH", len(body) + 6, kind) + body


def _string(text):
    raw = text.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def _layer(name, flags=1, kind=0, level=0, opacity=255):
    return _chunk(0x2004, struct.pack("<HHHHHH", flags, kind, level, 0, 0, 0) + bytes([opacity, 0, 0, 0]) + _string(name))


def _cel(layer, x, y, w, h, pixels, opacity=255, compressed=True):
    head = struct.pack("<HhhBHh", layer, x, y, opacity, 2 if compressed else 0, 0) + bytes(5)
    data = zlib.compress(pixels) if compressed else pixels
    return _chunk(0x2005, head + struct.pack("<HH", w, h) + data)


def _linked(layer, frame):
    return _chunk(0x2005, struct.pack("<HhhBHh", layer, 0, 0, 255, 1, 0) + bytes(5) + struct.pack("<H", frame))


def _tags(tags):
    body = struct.pack("<H", len(tags)) + bytes(8)
    for name, first, last, direction, repeat in tags:
        body += struct.pack("<HHBH", first, last, direction, repeat) + bytes(6) + bytes(3) + bytes(1) + _string(name)
    return _chunk(0x2018, body)


def _palette(colours):
    body = struct.pack("<III", len(colours), 0, len(colours) - 1) + bytes(8)
    for r, g, b, a in colours:
        body += struct.pack("<H", 0) + bytes([r, g, b, a])
    return _chunk(0x2019, body)


def _file(width, height, depth, frames, transparent=0):
    out = b""
    for duration, chunks in frames:
        body = b"".join(chunks)
        out += struct.pack("<IHHHBBI", 16 + len(body), 0xF1FA, len(chunks), duration, 0, 0, len(chunks)) + body
    header = struct.pack("<IHHHHHIHIIB", 128 + len(out), 0xA5E0, len(frames), width, height, depth, 1, 100, 0, 0,
                         transparent)
    header += bytes(3) + struct.pack("<H", 0)
    return header + bytes(128 - len(header)) + out


class AsepriteTest(unittest.TestCase):
    def test_layers_opacity_links_tags(self):
        """Two layers (a hidden group hides its child), cel opacity blends like Aseprite, a linked cel repeats a
        picture, tags become animations with their direction and repeats."""
        red, blue = bytes([255, 0, 0, 255]), bytes([0, 0, 255, 255])
        frames = [
            (100, [_layer("body"), _layer("group", flags=0, kind=1), _layer("hidden child", level=1),
                   _layer("top"), _palette([(0, 0, 0, 0)]),
                   _cel(0, 2, 1, 2, 2, red * 4), _cel(2, 0, 0, 1, 1, blue), _cel(3, 3, 2, 1, 1, blue, opacity=128),
                   _tags([("Walk", 0, 1, 0, 0), ("Hit", 2, 2, 0, 1), ("Back", 0, 2, 2, 3)])]),
            (100, [_linked(0, 0), _linked(3, 0)]),
            (200, [_cel(0, 0, 0, 1, 1, blue, compressed=False)]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hero.aseprite")
            with open(path, "wb") as handle:
                handle.write(_file(6, 4, 32, frames))
            doc = aseprite.read_aseprite(path)
            first = doc.frames[0]
            self.assertEqual(first.getpixel((2, 1)), (255, 0, 0, 255))
            self.assertEqual(first.getpixel((0, 0)), (0, 0, 0, 0), "the hidden group's child stays out")
            self.assertEqual(first.getpixel((3, 2)), (127, 0, 128, 255), "half-opaque blue over red, Aseprite's way")
            self.assertEqual(doc.frames[1].getpixel((2, 1)), (255, 0, 0, 255), "the linked cel")
            self.assertEqual(doc.durations, [100, 100, 200])
            project = aseprite.parse_aseprite(path)
            self.assertTrue(os.path.exists(os.path.join(tmp, "hero.sheet.png")))
            again = aseprite.parse_aseprite(path)
            self.assertTrue(again.images[0].file_path.endswith("hero.sheet_2.png"), "never over an existing file")
        self.assertEqual([f.name for f in project.frames], ["Walk 1", "Walk 2", "Hit 1"])
        self.assertEqual(len(project.modules), 2, "the linked frame shares its picture")
        walk, hit, back = project.animations
        self.assertEqual((walk.playback_type, walk.fps, [af.duration_frames for af in walk.aframes]), ("loop", 10, [1, 1]))
        self.assertEqual((hit.playback_type, hit.loop_count), ("forward", 0))
        self.assertEqual((back.playback_type, back.loop_count, [af.duration_frames for af in back.aframes]),
                         ("ping_pong", 3, [1, 1, 2]))
        part = project.frames[0].fmodules[0]
        self.assertEqual(part.position, (2 - 3, 1 - 4), "the canvas' bottom centre is the origin")

    def test_indexed_colours_and_the_transparent_index(self):
        frames = [(80, [_layer("art"), _palette([(0, 0, 0, 255), (10, 200, 30, 255)]),
                        _cel(0, 0, 0, 2, 1, bytes([1, 0]))])]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "idx.aseprite")
            with open(path, "wb") as handle:
                handle.write(_file(2, 1, 8, frames, transparent=0))
            doc = aseprite.read_aseprite(path)
        self.assertEqual([doc.frames[0].getpixel((x, 0)) for x in range(2)], [(10, 200, 30, 255), (0, 0, 0, 0)])

    def test_tick_rates_from_durations(self):
        self.assertEqual(aseprite.tick_rate_for([100, 100, 200]), 10)
        self.assertEqual(aseprite.tick_rate_for([100, 150]), 20)
        self.assertEqual(aseprite.tick_rate_for([83, 83, 84]), 12)
        self.assertEqual(aseprite.tick_rate_for([33, 34, 33]), 30)

    def test_not_an_aseprite_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.aseprite")
            with open(path, "wb") as handle:
                handle.write(b"PNG" * 50)
            with self.assertRaises(ValueError):
                aseprite.read_aseprite(path)


if __name__ == "__main__":
    unittest.main()
