"""Godot 4: a sprite sheet (``exporters/sheet.py``) as a SpriteFrames resource and a scene that plays it with its game
data (wx-free).

- ``<name>.tres``: SpriteFrames for an AnimatedSprite2D, one animation per animation (speed = tick rate, each step's
  duration = its hold), every texture padded to the shared canvas so the origin stays put.
- ``<name>.tscn``: a Node2D whose origin is the editor's, with
  - ``Sprite``: an AnimatedSprite2D on those SpriteFrames (nearest-neighbour filtering);
  - ``Hitboxes/<slot>``: an Area2D with a CollisionShape2D (a RectangleShape2D of its own) for each hitbox slot
    (``sheet.slots``: type and role, "Hurt head");
  - ``Points/<slot>``: a Marker2D for each point slot;
  - ``AnimationPlayer``: an animation per clip (``sheet.clips``) that sets the sprite's animation and frame, moves,
    sizes and switches the hitboxes, moves and shows the points, and calls the root's ``_sprite_events`` at steps with
    events. Loops and follow-ups (``next/``) play as in the editor; the first clip plays on start.
- ``<name>.gd`` (only when steps have events): the root's script, which emits ``sprite_event(name, value)``.

Positions are in pixels from the origin, y down, like the editor; a point sits at the centre of the pixel it marks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from exporters import sheet as sheets

SCRIPT = '''extends Node2D
## Made by the Modular Sprite Editor: the root of an exported character. Its AnimationPlayer calls _sprite_events
## when a step with events starts; connect to sprite_event to react (play a sound, deal a hit, spawn dust).

signal sprite_event(event_name: StringName, value: int)


func _sprite_events(events: Array) -> void:
	for event in events:
		sprite_event.emit(event[0], event[1])
'''


def text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def node_name(name: str) -> str:
    """A name Godot accepts for a node or an animation (it refuses . : @ / " % [ and ,)."""
    for char in '.:@/"%[,':
        name = name.replace(char, "_")
    return name.strip() or "_"


def _num(value: float) -> str:
    return f"{float(value):.6g}"


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _num(value)
    if isinstance(value, tuple):  # a Vector2
        return f"Vector2({_num(value[0])}, {_num(value[1])})"
    if isinstance(value, StringName):
        return f'&"{text(value)}"'
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    raise TypeError(value)


class StringName(str):
    """A string Godot reads as a StringName (&"…")."""


def frame_order(tag: sheets.Tag) -> List[int]:
    """The tag's entries (0-based within it) in the order its SpriteFrames animation lists them."""
    order = list(range(tag.last - tag.first + 1))
    if tag.direction == "reverse":
        order.reverse()
    elif tag.direction == "pingpong" and len(order) > 2:
        order = order + order[-2:0:-1]
    return order


def spriteframes(sheet: sheets.Sheet, image_name: str) -> str:
    """A Godot 4 SpriteFrames resource; textures padded to the shared canvas (AtlasTexture margins)."""
    left, top, width, height = sheet.canvas
    lines = [
        f'[gd_resource type="SpriteFrames" load_steps={len(sheet.cells) + 2} format=3]',
        "",
        f'; Made by the Modular Sprite Editor. Every texture is {width}×{height} px with the editor\'s origin at '
        f'({-left}, {-top}): on a centred AnimatedSprite2D set offset = ({width / 2.0 + left:g}, {height / 2.0 + top:g}).',
        "",
        f'[ext_resource type="Texture2D" path="{image_name}" id="1_sheet"]',
        "",
    ]
    for index, cell in enumerate(sheet.cells):
        w, h = cell.size
        lines += [
            f'[sub_resource type="AtlasTexture" id="AtlasTexture_{index}"]',
            'atlas = ExtResource("1_sheet")',
            f"region = Rect2({cell.x}, {cell.y}, {w}, {h})",
            f"margin = Rect2({cell.left - left}, {cell.top - top}, {width - w}, {height - h})",
            "",
        ]
    animations = []
    for tag in sheet.tags:
        entries = sheet.entries[tag.first:tag.last + 1]
        frames = ",\n".join(
            "{\n" f'"duration": {float(entries[i].hold):g},\n' f'"texture": SubResource("AtlasTexture_{entries[i].cell}")\n' "}"
            for i in frame_order(tag))
        animations.append(
            "{\n" f'"frames": [{frames}],\n' f'"loop": {"true" if tag.repeats == 0 else "false"},\n'
            f'"name": &"{text(tag.name)}",\n' f'"speed": {float(tag.fps):g}\n' "}")
    lines += ["[resource]", "animations = [" + ", ".join(animations) + "]", ""]
    return "\n".join(lines)


def _keys(times: Sequence[float], values: Sequence[Any]) -> List[tuple]:
    """Discrete keys: the first, then one wherever the value changes."""
    out: List[tuple] = []
    for time, value in zip(times, values):
        if not out or out[-1][1] != value:
            out.append((time, value))
    return out


def _track(index: int, kind: str, path: str, keys: Sequence[tuple]) -> List[str]:
    head = [f'tracks/{index}/type = "{kind}"', f"tracks/{index}/imported = false", f"tracks/{index}/enabled = true",
            f'tracks/{index}/path = NodePath("{text(path)}")', f"tracks/{index}/interp = 1",
            f"tracks/{index}/loop_wrap = true"]
    times = ", ".join(_num(t) for t, _v in keys)
    transitions = ", ".join("1" for _k in keys)
    if kind == "method":
        values = ", ".join('{\n"args": ' + _value(v) + ',\n"method": &"_sprite_events"\n}' for _t, v in keys)
        body = [f'"times": PackedFloat32Array({times}),', f'"transitions": PackedFloat32Array({transitions}),',
                f'"values": [{values}]']
    else:
        body = [f'"times": PackedFloat32Array({times}),', f'"transitions": PackedFloat32Array({transitions}),',
                '"update": 1,', f'"values": [{", ".join(_value(v) for _t, v in keys)}]']
    return head + [f"tracks/{index}/keys = {{"] + body + ["}"]


def _carried(values: List[Optional[Any]], fallback: Any) -> List[Any]:
    """Each missing value as the one before it (the first known one at the start), so a switched-off hitbox or a
    hidden point does not jump."""
    known = next((v for v in values if v is not None), fallback)
    out = []
    for value in values:
        known = value if value is not None else known
        out.append(known)
    return out


def scene(sheet: sheets.Sheet, root: str, frames_path: str, script_path: Optional[str]) -> str:
    """The ``.tscn`` text (see the module docstring)."""
    clips = sheets.clips(sheet)
    box_slots, point_slots = sheets.slots(sheet, "boxes"), sheets.slots(sheet, "points")
    left, top, _width, _height = sheet.canvas
    events = any(entry.events for entry in sheet.entries)
    resources = [f'[ext_resource type="SpriteFrames" path="{text(frames_path)}" id="1_frames"]']
    if script_path and events:
        resources.append(f'[ext_resource type="Script" path="{text(script_path)}" id="2_events"]')

    def box_values(entry: sheets.Entry) -> Dict[str, sheets.Box]:
        return dict(zip(sheets.slot_names(entry.boxes), entry.boxes))

    def point_values(entry: sheets.Entry) -> Dict[str, sheets.Point]:
        return dict(zip(sheets.slot_names(entry.points), entry.points))

    subs: List[str] = []
    for index, _slot in enumerate(box_slots):
        subs += [f'[sub_resource type="RectangleShape2D" id="RectangleShape2D_{index}"]', ""]
    taken: Dict[str, int] = {}
    names = [sheets.unique(node_name(clip.name), taken) for clip in clips]
    name_of = {clip.name: name for clip, name in zip(clips, names)}
    for number, clip in enumerate(clips):
        tag = sheet.tags[clip.tag]
        times = clip.times(sheet)
        starts, length = times[:-1], times[-1]
        entries = [sheet.entries[i] for i in clip.entries]
        order = frame_order(tag)
        lines = [f'[sub_resource type="Animation" id="Animation_{number}"]', f'resource_name = "{text(names[number])}"',
                 f"length = {_num(length)}"]
        if clip.loops:
            lines.append("loop_mode = 1")
        lines.append(f"step = {_num(1.0 / tag.fps)}")
        tracks = [("value", "Sprite:animation", [(0.0, StringName(tag.name))]),
                  ("value", "Sprite:frame", _keys(starts, [order.index(i - tag.first) for i in clip.entries]))]
        for slot in box_slots:
            found = [box_values(e).get(slot) for e in entries]
            base = f"Hitboxes/{slot}/Shape"
            centres = _carried([(b.x + b.w / 2.0, b.y + b.h / 2.0) if b else None for b in found], (0.0, 0.0))
            sizes = _carried([(float(b.w), float(b.h)) if b else None for b in found], (1.0, 1.0))
            tracks += [("value", f"{base}:position", _keys(starts, centres)),
                       ("value", f"{base}:shape:size", _keys(starts, sizes)),
                       ("value", f"{base}:disabled", _keys(starts, [b is None for b in found]))]
        for slot in point_slots:
            found = [point_values(e).get(slot) for e in entries]
            places = _carried([(p.x + p.size / 2.0, p.y + p.size / 2.0) if p else None for p in found], (0.0, 0.0))
            tracks += [("value", f"Points/{slot}:position", _keys(starts, places)),
                       ("value", f"Points/{slot}:visible", _keys(starts, [p is not None for p in found]))]
        fired = [(t, [[StringName(name), value] for name, value in e.events]) for t, e in zip(starts, entries) if e.events]
        if fired and events and script_path:
            tracks.append(("method", ".", [(t, [calls]) for t, calls in fired]))
        for index, (kind, path, keys) in enumerate(tracks):
            lines += _track(index, kind, path, keys)
        subs += lines + [""]
    library = ",\n".join(f'&"{text(name)}": SubResource("Animation_{n}")' for n, name in enumerate(names))
    subs += ['[sub_resource type="AnimationLibrary" id="AnimationLibrary_0"]', f"_data = {{\n{library}\n}}", ""]

    first = sheet.entries[clips[0].entries[0]] if clips else None
    first_boxes = box_values(first) if first else {}
    first_points = point_values(first) if first else {}
    nodes = [f'[node name="{text(node_name(root))}" type="Node2D"]', "texture_filter = 1"]
    if script_path and events:
        nodes.append('script = ExtResource("2_events")')
    nodes += ["", '[node name="Sprite" type="AnimatedSprite2D" parent="."]', 'sprite_frames = ExtResource("1_frames")']
    if clips:
        nodes.append(f'animation = &"{text(sheet.tags[clips[0].tag].name)}"')
    nodes += ["centered = false", f"offset = Vector2({left}, {top})", ""]
    if box_slots:
        nodes += ['[node name="Hitboxes" type="Node2D" parent="."]', ""]
        for index, slot in enumerate(box_slots):
            box = first_boxes.get(slot)
            nodes += [f'[node name="{text(slot)}" type="Area2D" parent="Hitboxes"]', "",
                      f'[node name="Shape" type="CollisionShape2D" parent="Hitboxes/{text(slot)}"]']
            if box:
                nodes.append(f"position = Vector2({_num(box.x + box.w / 2.0)}, {_num(box.y + box.h / 2.0)})")
            nodes.append(f'shape = SubResource("RectangleShape2D_{index}")')
            if not box:
                nodes.append("disabled = true")
            nodes.append("")
    if point_slots:
        nodes += ['[node name="Points" type="Node2D" parent="."]', ""]
        for slot in point_slots:
            point = first_points.get(slot)
            nodes.append(f'[node name="{text(slot)}" type="Marker2D" parent="Points"]')
            nodes.append(f"position = Vector2({_num(point.x + point.size / 2.0)}, {_num(point.y + point.size / 2.0)})"
                         if point else "visible = false")
            nodes.append("")
    nodes += ['[node name="AnimationPlayer" type="AnimationPlayer" parent="."]',
              'libraries = {\n&"": SubResource("AnimationLibrary_0")\n}']
    if clips:
        nodes.append(f'autoplay = &"{text(names[0])}"')
    for clip, name in zip(clips, names):
        if clip.next:
            nodes.append(f'"next/{text(name)}" = &"{text(name_of[clip.next])}"')
    steps = len(resources) + len(box_slots) + len(clips) + 2
    return "\n".join([f"[gd_scene load_steps={steps} format=3]", ""] + resources + [""] + subs + nodes) + "\n"
