"""Native project format version and the upgrade of older project dicts (works on raw dicts, wx-free)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple


# Native project file format version (top-level "format_version" key).
# 1 = unversioned files written before versioning existed.
# 2 = legacy fields canonicalized (see migrate_project_dict).
# 3 = animation step events (+ project event types), loop-from step and follow-up animation (additive).
# 4 = timeline objects carry a module mapping (mapping_id, additive); an animation swapped in at a later
#     key plays from that key instead of from the scene start.
# 5 = timeline objects play an animation "as animated" (playback_mode "as_animated", the new default: its own
#     playback, repeat count, loop-from step and follow-up, like the Animations tab and the game); existing objects
#     keep their mode, "backward" joins the overrides. Flips and visibility switch at a key, not half-way to it.
# 6 = images belong to one of four palettes (ImageAsset.palette, 0-3, additive: existing images use the first).
# 7 = palettes are project data (palettes: colours in hardware order and colour cycles; images name theirs with
#     palette_id), palette swaps (palette_swaps) that scene objects choose like mappings (palette_swap_id), the target
#     console (console), scene objects that follow a parent's point (attach_point_role / attach_point_type), groups for
#     frames and animations (group). Additive: format 6's palettes keep their numbers, and their colours are built
#     from the images when the project opens, with that format's rules (palettes.build_missing).
# 8 = the target console's setup (console_setup: a consoles.BudgetSetup key such as "md_h40" or "snes_16_32", the
#     screen mode and, where games pick them, the sprite sizes). Additive: the console's first setup.
PROJECT_FORMAT_VERSION = 8


def _legacy_duration_ms_to_frames(ms_value: Any) -> int:
    # Same heuristic AFrame.from_dict has always applied to unversioned files:
    # large values were absolute milliseconds at an assumed 10 FPS.
    ms = int(ms_value)
    if ms >= 10:
        return max(1, round(ms / 100.0))
    return ms


def _migrate_v1_to_v2(data: Dict[str, Any], notes: List[str]) -> None:
    converted_durations = 0
    for anim in data.get("animations", []) or []:
        for af in anim.get("aframes", []) or []:
            if af.get("duration_frames") is None:
                af["duration_frames"] = _legacy_duration_ms_to_frames(af.get("duration_ms", 1))
                af.pop("duration_ms", None)
                converted_durations += 1
    if converted_durations:
        notes.append(f"Converted {converted_durations} legacy duration_ms value(s) to duration_frames.")

    for frame in data.get("frames", []) or []:
        for cp in frame.get("control_points", []) or []:
            if cp.get("role") is None:
                legacy_name = cp.get("name")
                cp["role"] = legacy_name if isinstance(legacy_name, str) else ""
            cp.pop("name", None)
        for cr in frame.get("collision_rects", []) or []:
            if cr.get("role") is None:
                cr["role"] = ""

    converted_scenes = 0
    for scene in data.get("timeline_scenes", []) or []:
        if scene.get("duration_seconds") is not None:
            continue
        fps = max(1, int(scene.get("fps", 12)))
        to_seconds = 1.0 / float(fps)
        scene["duration_seconds"] = float(scene.get("duration_frames", 120)) * to_seconds
        for obj in scene.get("objects", []) or []:
            obj["playback_offset"] = float(obj.get("playback_offset", 0.0)) * to_seconds
            for key in obj.get("keyframes", []) or []:
                key["time"] = float(key.get("time", 0.0)) * to_seconds
        converted_scenes += 1
    if converted_scenes:
        notes.append(f"Converted {converted_scenes} frame-based timeline scene(s) to seconds.")

    converted_shapes = 0
    for mod in data.get("modules", []) or []:
        mod_type = mod.get("type", "MD_IMAGE")
        params = list(mod.get("params", []) or [])
        rect = mod.get("rect", [0, 0, 1, 1])
        w = max(1, int(rect[2]) if len(rect) > 2 else 1)
        h = max(1, int(rect[3]) if len(rect) > 3 else 1)
        if mod_type == "MD_LINE" and len(params) == 2:
            # Legacy: end point in pixels relative to the module origin.
            mod["params"] = [0.0, 0.0, params[0] / w * 100.0, params[1] / h * 100.0]
            converted_shapes += 1
        elif mod_type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE") and len(params) == 4:
            # Legacy: P2/P3 in pixels relative to P1 at the module origin.
            mod["params"] = [
                0.0,
                0.0,
                params[0] / w * 100.0,
                params[1] / h * 100.0,
                params[2] / w * 100.0,
                params[3] / h * 100.0,
            ]
            converted_shapes += 1
    if converted_shapes:
        notes.append(f"Converted {converted_shapes} legacy line/triangle shape module(s) to percentage points.")


def _migrate_v2_to_v3(data: Dict[str, Any], notes: List[str]) -> None:
    """Additive: write the new fields with their defaults so v3 files always carry them."""
    data.setdefault("event_types", [])
    for anim in data.get("animations", []) or []:
        anim.setdefault("loop_start", 0)
        anim.setdefault("next_animation_id", None)
        for af in anim.get("aframes", []) or []:
            af.setdefault("events", [])


def _migrate_v3_to_v4(data: Dict[str, Any], notes: List[str]) -> None:
    """Additive: timeline objects inherit their mapping (the preview mapping at the top level)."""
    for scene in data.get("timeline_scenes", []) or []:
        for obj in scene.get("objects", []) or []:
            obj.setdefault("mapping_id", None)


def _migrate_v4_to_v5(data: Dict[str, Any], notes: List[str]) -> None:
    """Timeline objects keep the mode they played with ("loop" was the default); notes for what plays differently."""
    steps = {anim.get("id"): len(anim.get("aframes", []) or []) for anim in data.get("animations", []) or []}
    ping_pong = 0
    flip_scenes: List[str] = []
    for scene in data.get("timeline_scenes", []) or []:
        switches = False
        for obj in scene.get("objects", []) or []:
            mode = str(obj.get("playback_mode") or "loop").strip().lower()
            obj["playback_mode"] = mode if mode in ("loop", "once", "ping_pong") else "loop"
            keys = sorted(obj.get("keyframes", []) or [], key=lambda key: float(key.get("time", 0.0) or 0.0))
            sources = [obj.get("source_id")] + [key.get("source_id") for key in keys]
            if obj["playback_mode"] == "ping_pong" and any(steps.get(source, 0) > 1 for source in sources):
                ping_pong += 1
            for before, after in zip(keys, keys[1:]):
                if any(before.get(name, default) != after.get(name, default)
                       for name, default in (("flip_x", False), ("flip_y", False), ("visible", True))):
                    switches = True
        if switches:
            flip_scenes.append(str(scene.get("name", "Scene")))
    if ping_pong:
        notes.append(f"{ping_pong} Timeline object(s) set to Ping-pong no longer show an animation's first and last "
                     "steps twice, like the Animations tab and the game.")
    if flip_scenes:
        notes.append("Flips and visibility now change exactly at a key instead of half-way to it. Check the "
                     f"scene(s): {', '.join(flip_scenes)}.")


def _migrate_v5_to_v6(data: Dict[str, Any], notes: List[str]) -> None:
    """Additive: every image starts in the first palette, which is where the export put all colours before."""
    for image in data.get("images", []) or []:
        image.setdefault("palette", 0)


def _migrate_v6_to_v7(data: Dict[str, Any], notes: List[str]) -> None:
    """Palettes become project data. Format 6's Palette 1-4 keep their numbers (those the images use, and the first,
    which vector shapes use); their colours are left unset to be built from the images once the project is open. The
    rest is additive: no swaps, objects inherit theirs and follow no point, frames and animations sit in no group."""
    data.setdefault("console", "megadrive")
    images = data.get("images", []) or []

    def number(image: Dict[str, Any]) -> int:
        value = image.get("palette", 0)
        return value if isinstance(value, int) and 0 <= value <= 3 else 0

    if "palettes" not in data:
        used = sorted({0} | {number(image) for image in images})
        data["palettes"] = [{"id": f"pal_{i + 1}", "name": f"Palette {i + 1}", "colours": None, "cycles": []}
                            for i in used]
    for image in images:
        image.setdefault("palette_id", f"pal_{number(image) + 1}")
        image.pop("palette", None)
    data.setdefault("palette_swaps", [])
    for scene in data.get("timeline_scenes", []) or []:
        for obj in scene.get("objects", []) or []:
            obj.setdefault("palette_swap_id", None)
            obj.setdefault("attach_point_role", "")
            obj.setdefault("attach_point_type", None)
    for item in (data.get("frames", []) or []) + (data.get("animations", []) or []):
        item.setdefault("group", "")


def _migrate_v7_to_v8(data: Dict[str, Any], notes: List[str]) -> None:
    """The target console gets its setup: the console's first (Mega Drive H40, SNES 8x8 and 16x16 sprites, ...)."""
    import consoles  # wx-free, imports nothing of the model

    if not data.get("console_setup"):
        data["console_setup"] = consoles.target(data.get("console"))[1].key


def migrate_project_dict(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Upgrade a native project dict to PROJECT_FORMAT_VERSION.

    Works on a deep copy, keeps unknown keys, and returns (migrated_data, notes).
    Files newer than this build are returned unchanged with a warning note.
    """
    migrated = json.loads(json.dumps(data))
    notes: List[str] = []
    try:
        version = int(migrated.get("format_version", 1))
    except (TypeError, ValueError):
        version = 1

    if version > PROJECT_FORMAT_VERSION:
        notes.append(
            f"File format version {version} is newer than this editor supports "
            f"({PROJECT_FORMAT_VERSION}). Unknown data may be lost when saving."
        )
        return migrated, notes

    if version < 2:
        _migrate_v1_to_v2(migrated, notes)
    if version < 3:
        _migrate_v2_to_v3(migrated, notes)
    if version < 4:
        _migrate_v3_to_v4(migrated, notes)
    if version < 5:
        _migrate_v4_to_v5(migrated, notes)
    if version < 6:
        _migrate_v5_to_v6(migrated, notes)
    if version < 7:
        _migrate_v6_to_v7(migrated, notes)
    if version < 8:
        _migrate_v7_to_v8(migrated, notes)

    migrated.pop("format_version", None)
    return {"format_version": PROJECT_FORMAT_VERSION, **migrated}, notes
