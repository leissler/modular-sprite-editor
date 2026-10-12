"""Data models and JSON serialization for the sprite editor."""

from __future__ import annotations

import json
import uuid
import re
import os
import math
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# Native project file format version (top-level "format_version" key).
# 1 = unversioned files written before versioning existed.
# 2 = legacy fields canonicalized (see migrate_project_dict).
# 3 = animation step events (+ project event types), loop-from step and follow-up animation (additive).
# 4 = timeline objects carry a module mapping (mapping_id, additive); an animation swapped in at a later
#     key plays from that key instead of from the scene start.
PROJECT_FORMAT_VERSION = 4


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

    migrated.pop("format_version", None)
    return {"format_version": PROJECT_FORMAT_VERSION, **migrated}, notes


@dataclass
class ImageAsset:
    id: str
    file_path: str
    width: int
    height: int
    transparent_color: Optional[Tuple[int, int, int]] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "width": self.width,
            "height": self.height,
            "transparent_color": list(self.transparent_color) if self.transparent_color else None,
        }

    @staticmethod
    def from_dict(data: Dict) -> "ImageAsset":
        return ImageAsset(
            id=data["id"],
            file_path=data["file_path"],
            width=int(data["width"]),
            height=int(data["height"]),
            transparent_color=tuple(data["transparent_color"]) if data.get("transparent_color") else None,  # type: ignore[arg-type]
        )


@dataclass
class Module:
    id: str
    name: str
    image_id: str
    rect: Tuple[int, int, int, int]
    pivot: Tuple[int, int]
    type: str = "MD_IMAGE"
    color: Tuple[int, int, int] = (255, 255, 255)
    rotated: bool = False
    params: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "image_id": self.image_id,
            "rect": list(self.rect),
            "pivot": list(self.pivot),
            "type": self.type,
            "color": list(self.color),
            "rotated": self.rotated,
            "params": self.params,
        }

    @staticmethod
    def from_dict(data: Dict) -> "Module":
        rect = tuple(int(v) for v in data["rect"])
        pivot = tuple(int(v) for v in data["pivot"])
        return Module(
            id=data["id"],
            name=data["name"],
            image_id=data["image_id"],
            rect=rect,  # type: ignore[arg-type]
            pivot=pivot,  # type: ignore[arg-type]
            type=data.get("type", "MD_IMAGE"),
            color=tuple(data["color"]) if "color" in data else (255, 255, 255), # type: ignore
            rotated=data.get("rotated", False),
            params=data.get("params", []),
        )


@dataclass
class FModule:
    id: str
    ref_type: str  # "module" or "frame"
    ref_id: str
    position: Tuple[int, int]
    flip_x: bool = False
    flip_y: bool = False
    rotation_degrees: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "position": list(self.position),
            "flip_x": self.flip_x,
            "flip_y": self.flip_y,
            "rotation_degrees": self.rotation_degrees,
        }

    @staticmethod
    def from_dict(data: Dict) -> "FModule":
        position = tuple(int(v) for v in data["position"])
        return FModule(
            id=data["id"],
            ref_type=data["ref_type"],
            ref_id=data["ref_id"],
            position=position,  # type: ignore[arg-type]
            flip_x=bool(data.get("flip_x", False)),
            flip_y=bool(data.get("flip_y", False)),
            rotation_degrees=float(data.get("rotation_degrees", 0.0)),
        )


@dataclass
class ModuleMapping:
    id: str
    name: str
    map: Dict[str, Optional[str]] = field(default_factory=dict) # src_id -> target_id (None for hidden)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "map": self.map
        }

    @staticmethod
    def from_dict(data: Dict) -> "ModuleMapping":
        return ModuleMapping(
            id=data["id"],
            name=data["name"],
            map=data.get("map", {})
        )


@dataclass
class CollisionType:
    id: str
    name: str
    color: Tuple[int, int, int] # RGB

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": list(self.color),
        }

    @staticmethod
    def from_dict(data: Dict) -> "CollisionType":
        return CollisionType(
            id=data["id"],
            name=data["name"],
            color=tuple(data["color"]), # type: ignore
        )

@dataclass
class PointType:
    id: str
    name: str
    color: Tuple[int, int, int] # RGB

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": list(self.color),
        }

    @staticmethod
    def from_dict(data: Dict) -> "PointType":
        return PointType(
            id=data["id"],
            name=data["name"],
            color=tuple(data["color"]), # type: ignore
        )

@dataclass
class EventType:
    """A project-wide animation event (e.g. "hit_on", "sfx", "footstep"); steps reference it by id."""

    id: str
    name: str
    color: Tuple[int, int, int]  # RGB, for markers in the editor

    def to_dict(self) -> Dict:
        return {"id": self.id, "name": self.name, "color": list(self.color)}

    @staticmethod
    def from_dict(data: Dict) -> "EventType":
        return EventType(
            id=data["id"],
            name=str(data.get("name", "")),
            color=tuple(int(v) for v in data.get("color", (255, 200, 80)))[:3],  # type: ignore[arg-type]
        )


@dataclass
class StepEvent:
    """An event on an animation step: fires when the step starts and is active while it shows."""

    type_id: str
    value: int = 0  # optional parameter, e.g. which sound or which object to spawn

    def to_dict(self) -> Dict:
        return {"type_id": self.type_id, "value": int(self.value)}

    @staticmethod
    def from_dict(data: Dict) -> "StepEvent":
        return StepEvent(type_id=str(data["type_id"]), value=int(data.get("value", 0)))


@dataclass
class CollisionRect:
    id: str
    type_id: str
    rect: Tuple[int, int, int, int] # x,y,w,h relative to frame origin
    role: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type_id": self.type_id,
            "rect": list(self.rect),
            "role": str(getattr(self, "role", "") or ""),
        }

    @staticmethod
    def from_dict(data: Dict) -> "CollisionRect":
        return CollisionRect(
            id=data["id"],
            type_id=data["type_id"],
            rect=tuple(data["rect"]), # type: ignore
            role=str(data.get("role", "") or ""),
        )


@dataclass
class ControlPoint:
    id: str
    type_id: str
    x: int
    y: int
    role: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type_id": self.type_id,
            "x": self.x,
            "y": self.y,
            "role": str(getattr(self, "role", "") or ""),
        }

    @staticmethod
    def from_dict(data: Dict) -> "ControlPoint":
        # Migration for legacy simple name points?
        # If 'name' in data and 'type_id' not in data...
        # For now assume clean slate or migrated manually.
        role = data.get("role")
        if role is None and isinstance(data.get("name"), str):
            # Legacy project variants may have stored semantic point names in `name`.
            role = data.get("name")
        return ControlPoint(
            id=data.get("id", generate_id("pt")),
            type_id=data.get("type_id", "unknown"),
            x=data["x"],
            y=data["y"],
            role=str(role or ""),
        )



@dataclass
class Frame:
    id: str
    name: str
    fmodules: List[FModule] = field(default_factory=list)
    collision_rects: List[CollisionRect] = field(default_factory=list)
    control_points: List[ControlPoint] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "fmodules": [fm.to_dict() for fm in self.fmodules],
            "collision_rects": [cr.to_dict() for cr in self.collision_rects],
            "control_points": [cp.to_dict() for cp in self.control_points],
        }

    def clone(self) -> "Frame":
        return Frame.from_dict(self.to_dict())

    @staticmethod
    def _norm_role(value: Optional[str]) -> str:
        return str(value or "").strip().lower()

    def find_collision_rect(self, role: str, type_id: Optional[str] = None) -> Optional[CollisionRect]:
        """Find the first collision rect by semantic role (and optional type)."""
        role_key = self._norm_role(role)
        if not role_key:
            return None
        for cr in self.collision_rects:
            if self._norm_role(getattr(cr, "role", "")) != role_key:
                continue
            if type_id is not None and cr.type_id != type_id:
                continue
            return cr
        return None

    def find_control_point(self, role: str, type_id: Optional[str] = None) -> Optional[ControlPoint]:
        """Find the first control point by semantic role (and optional type)."""
        role_key = self._norm_role(role)
        if not role_key:
            return None
        for cp in self.control_points:
            if self._norm_role(getattr(cp, "role", "")) != role_key:
                continue
            if type_id is not None and cp.type_id != type_id:
                continue
            return cp
        return None

    @staticmethod
    def from_dict(data: Dict) -> "Frame":
        fmodules = [FModule.from_dict(fm_data) for fm_data in data.get("fmodules", [])]
        collision_rects = [CollisionRect.from_dict(cr_data) for cr_data in data.get("collision_rects", [])]
        control_points = [ControlPoint.from_dict(cp_data) for cp_data in data.get("control_points", [])]
        return Frame(
            id=data["id"],
            name=data["name"],
            fmodules=fmodules,
            collision_rects=collision_rects,
            control_points=control_points,
        )


@dataclass
class AFrame:
    frame_id: str
    duration_frames: int
    offset: Tuple[int, int] = (0, 0)
    # Adding flip support for Animations as per Aurora format
    flip_x: bool = False
    flip_y: bool = False
    rotation_degrees: float = 0.0
    events: List[StepEvent] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "frame_id": self.frame_id,
            "duration_frames": self.duration_frames,
            "offset": list(self.offset),
            "flip_x": self.flip_x,
            "flip_y": self.flip_y,
            "rotation_degrees": self.rotation_degrees,
            "events": [e.to_dict() for e in self.events],
        }

    def clone(self) -> "AFrame":
        return AFrame.from_dict(self.to_dict())

    @staticmethod
    def from_dict(data: Dict) -> "AFrame":
        # Migration logic
        duration = data.get("duration_frames")
        if duration is None:
            # Fallback to duration_ms
            ms = int(data.get("duration_ms", 1))
            # Heuristic: if ms is large (>=10), it was likely absolute ms from the recent buggy version.
            # We assume a default of 10 FPS for normalization if it's large.
            if ms >= 10:
                duration = max(1, round(ms / 100.0)) # 100ms = 1 frame at 10fps
            else:
                duration = ms
        
        return AFrame(
            frame_id=data["frame_id"],
            duration_frames=int(duration),
            offset=tuple(int(v) for v in data.get("offset", (0, 0))),  # type: ignore[arg-type]
            flip_x=bool(data.get("flip_x", False)),
            flip_y=bool(data.get("flip_y", False)),
            rotation_degrees=float(data.get("rotation_degrees", 0.0)),
            events=[StepEvent.from_dict(e) for e in data.get("events", []) or []],
        )


@dataclass
class Animation:
    id: str
    name: str
    playback_type: str = "loop"
    loop_count: Optional[int] = 0
    fps: int = 10
    aframes: List[AFrame] = field(default_factory=list)
    # "Loop" playback: the first pass plays every step, later passes start at this step (an intro plays once).
    loop_start: int = 0
    # When the animation ends (Play once, or after its repeat count), continue with this animation.
    next_animation_id: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "playback_type": self.playback_type,
            "loop_count": self.loop_count,
            "fps": self.fps,
            "aframes": [af.to_dict() for af in self.aframes],
            "loop_start": self.loop_start,
            "next_animation_id": self.next_animation_id,
        }

    def clone(self) -> "Animation":
        return Animation.from_dict(self.to_dict())

    @staticmethod
    def from_dict(data: Dict) -> "Animation":
        return Animation(
            id=data["id"],
            name=data["name"],
            playback_type=data.get("playback_type", "loop").lower(),
            loop_count=data.get("loop_count"),
            aframes=[AFrame.from_dict(af) for af in data.get("aframes", [])],
            fps=data.get("fps", 10),
            loop_start=max(0, int(data.get("loop_start", 0) or 0)),
            next_animation_id=data.get("next_animation_id") or None,
        )


TIMELINE_SOURCE_TYPES = ("none", "module", "frame", "animation")
TIMELINE_PATH_MODES = ("linear", "spline")
# TimelineObject.mapping_id: None inherits (the parent's mapping; top-level objects use the preview /
# exported mapping), TIMELINE_MAPPING_ORIGINAL draws the original modules, anything else is a mapping id.
TIMELINE_MAPPING_ORIGINAL = "original"
TIMELINE_EASINGS = (
    "step",
    "linear",
    "quad_in",
    "quad_out",
    "quad_in_out",
    "cubic_in",
    "cubic_out",
    "cubic_in_out",
    "quart_in",
    "quart_out",
    "quart_in_out",
    "quint_in",
    "quint_out",
    "quint_in_out",
    "sine_in",
    "sine_out",
    "sine_in_out",
    "expo_in",
    "expo_out",
    "expo_in_out",
    "circ_in",
    "circ_out",
    "circ_in_out",
    "back_in",
    "back_out",
    "back_in_out",
    "elastic_in",
    "elastic_out",
    "elastic_in_out",
    "bounce_in",
    "bounce_out",
    "bounce_in_out",
)


def _timeline_clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _timeline_lerp(a: float, b: float, t: float) -> float:
    return float(a) + (float(b) - float(a)) * float(t)


def _timeline_bounce_out(t: float) -> float:
    n1 = 7.5625
    d1 = 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    if t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


def apply_timeline_easing(name: Optional[str], t: float) -> float:
    t = _timeline_clamp01(t)
    easing = str(name or "linear").strip().lower()
    if easing == "step":
        return 0.0 if t < 1.0 else 1.0
    if easing == "linear":
        return t
    if easing == "quad_in":
        return t * t
    if easing == "quad_out":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if easing == "quad_in_out":
        return 2.0 * t * t if t < 0.5 else 1.0 - math.pow(-2.0 * t + 2.0, 2.0) / 2.0
    if easing == "cubic_in":
        return t * t * t
    if easing == "cubic_out":
        return 1.0 - math.pow(1.0 - t, 3.0)
    if easing == "cubic_in_out":
        return 4.0 * t * t * t if t < 0.5 else 1.0 - math.pow(-2.0 * t + 2.0, 3.0) / 2.0
    if easing == "quart_in":
        return t * t * t * t
    if easing == "quart_out":
        return 1.0 - math.pow(1.0 - t, 4.0)
    if easing == "quart_in_out":
        return 8.0 * math.pow(t, 4.0) if t < 0.5 else 1.0 - math.pow(-2.0 * t + 2.0, 4.0) / 2.0
    if easing == "quint_in":
        return math.pow(t, 5.0)
    if easing == "quint_out":
        return 1.0 - math.pow(1.0 - t, 5.0)
    if easing == "quint_in_out":
        return 16.0 * math.pow(t, 5.0) if t < 0.5 else 1.0 - math.pow(-2.0 * t + 2.0, 5.0) / 2.0
    if easing == "sine_in":
        return 1.0 - math.cos((t * math.pi) / 2.0)
    if easing == "sine_out":
        return math.sin((t * math.pi) / 2.0)
    if easing == "sine_in_out":
        return -(math.cos(math.pi * t) - 1.0) / 2.0
    if easing == "expo_in":
        return 0.0 if t == 0.0 else math.pow(2.0, 10.0 * t - 10.0)
    if easing == "expo_out":
        return 1.0 if t == 1.0 else 1.0 - math.pow(2.0, -10.0 * t)
    if easing == "expo_in_out":
        if t == 0.0:
            return 0.0
        if t == 1.0:
            return 1.0
        if t < 0.5:
            return math.pow(2.0, 20.0 * t - 10.0) / 2.0
        return (2.0 - math.pow(2.0, -20.0 * t + 10.0)) / 2.0
    if easing == "circ_in":
        return 1.0 - math.sqrt(1.0 - t * t)
    if easing == "circ_out":
        return math.sqrt(1.0 - math.pow(t - 1.0, 2.0))
    if easing == "circ_in_out":
        if t < 0.5:
            return (1.0 - math.sqrt(1.0 - math.pow(2.0 * t, 2.0))) / 2.0
        return (math.sqrt(1.0 - math.pow(-2.0 * t + 2.0, 2.0)) + 1.0) / 2.0
    if easing == "back_in":
        c1 = 1.70158
        c3 = c1 + 1.0
        return c3 * t * t * t - c1 * t * t
    if easing == "back_out":
        c1 = 1.70158
        c3 = c1 + 1.0
        return 1.0 + c3 * math.pow(t - 1.0, 3.0) + c1 * math.pow(t - 1.0, 2.0)
    if easing == "back_in_out":
        c1 = 1.70158
        c2 = c1 * 1.525
        if t < 0.5:
            return math.pow(2.0 * t, 2.0) * ((c2 + 1.0) * 2.0 * t - c2) / 2.0
        return (math.pow(2.0 * t - 2.0, 2.0) * ((c2 + 1.0) * (t * 2.0 - 2.0) + c2) + 2.0) / 2.0
    if easing == "elastic_in":
        c4 = (2.0 * math.pi) / 3.0
        if t == 0.0:
            return 0.0
        if t == 1.0:
            return 1.0
        return -math.pow(2.0, 10.0 * t - 10.0) * math.sin((t * 10.0 - 10.75) * c4)
    if easing == "elastic_out":
        c4 = (2.0 * math.pi) / 3.0
        if t == 0.0:
            return 0.0
        if t == 1.0:
            return 1.0
        return math.pow(2.0, -10.0 * t) * math.sin((t * 10.0 - 0.75) * c4) + 1.0
    if easing == "elastic_in_out":
        c5 = (2.0 * math.pi) / 4.5
        if t == 0.0:
            return 0.0
        if t == 1.0:
            return 1.0
        if t < 0.5:
            return -(math.pow(2.0, 20.0 * t - 10.0) * math.sin((20.0 * t - 11.125) * c5)) / 2.0
        return (math.pow(2.0, -20.0 * t + 10.0) * math.sin((20.0 * t - 11.125) * c5)) / 2.0 + 1.0
    if easing == "bounce_in":
        return 1.0 - _timeline_bounce_out(1.0 - t)
    if easing == "bounce_in_out":
        if t < 0.5:
            return (1.0 - _timeline_bounce_out(1.0 - 2.0 * t)) / 2.0
        return (1.0 + _timeline_bounce_out(2.0 * t - 1.0)) / 2.0
    if easing == "bounce_out":
        return _timeline_bounce_out(t)
    return t


def _timeline_cubic_point(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    t: float,
) -> Tuple[float, float]:
    t = _timeline_clamp01(t)
    omt = 1.0 - t
    omt2 = omt * omt
    omt3 = omt2 * omt
    t2 = t * t
    t3 = t2 * t
    x = omt3 * p0[0] + 3.0 * omt2 * t * p1[0] + 3.0 * omt * t2 * p2[0] + t3 * p3[0]
    y = omt3 * p0[1] + 3.0 * omt2 * t * p1[1] + 3.0 * omt * t2 * p2[1] + t3 * p3[1]
    return (x, y)


def _timeline_catmull_rom_point(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    t: float,
) -> Tuple[float, float]:
    t = _timeline_clamp01(t)
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * (
        (2.0 * p1[0])
        + (-p0[0] + p2[0]) * t
        + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
        + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3
    )
    y = 0.5 * (
        (2.0 * p1[1])
        + (-p0[1] + p2[1]) * t
        + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
        + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3
    )
    return (x, y)


@dataclass
class TimelineKeyframe:
    id: str
    time: float
    x: float = 0.0
    y: float = 0.0
    rotation_degrees: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    flip_x: bool = False
    flip_y: bool = False
    visible: bool = True
    opacity: float = 1.0
    easing: str = "linear"
    path_in: Optional[Tuple[float, float]] = None
    path_out: Optional[Tuple[float, float]] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    source_offset: Tuple[float, float] = (0.0, 0.0)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "time": self.time,
            "x": self.x,
            "y": self.y,
            "rotation_degrees": self.rotation_degrees,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "flip_x": self.flip_x,
            "flip_y": self.flip_y,
            "visible": self.visible,
            "opacity": self.opacity,
            "easing": self.easing,
            "path_in": list(self.path_in) if self.path_in is not None else None,
            "path_out": list(self.path_out) if self.path_out is not None else None,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_offset": [float(self.source_offset[0]), float(self.source_offset[1])],
        }

    @staticmethod
    def from_dict(data: Dict) -> "TimelineKeyframe":
        source_type = str(data.get("source_type", "") or "").strip().lower() or None
        if source_type is not None and source_type not in TIMELINE_SOURCE_TYPES:
            source_type = None
        path_in = data.get("path_in")
        path_out = data.get("path_out")
        source_offset = data.get("source_offset", (0.0, 0.0))
        source_offset_values = tuple(float(v) for v in source_offset) if source_offset is not None else (0.0, 0.0)
        if len(source_offset_values) < 2:
            source_offset_values = (0.0, 0.0)
        easing = str(data.get("easing", "linear") or "linear").strip().lower()
        if easing not in TIMELINE_EASINGS:
            easing = "linear"
        return TimelineKeyframe(
            id=str(data.get("id", generate_id("tlk"))),
            time=float(data.get("time", 0.0)),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            rotation_degrees=float(data.get("rotation_degrees", 0.0)),
            scale_x=float(data.get("scale_x", 1.0)),
            scale_y=float(data.get("scale_y", 1.0)),
            flip_x=bool(data.get("flip_x", False)),
            flip_y=bool(data.get("flip_y", False)),
            visible=bool(data.get("visible", True)),
            opacity=float(data.get("opacity", 1.0)),
            easing=easing,
            path_in=tuple(float(v) for v in path_in) if path_in is not None else None,  # type: ignore[arg-type]
            path_out=tuple(float(v) for v in path_out) if path_out is not None else None,  # type: ignore[arg-type]
            source_type=source_type,
            source_id=str(data.get("source_id")) if data.get("source_id") is not None else None,
            source_offset=(float(source_offset_values[0]), float(source_offset_values[1])),
        )


@dataclass
class TimelineObject:
    id: str
    name: str
    parent_id: Optional[str] = None
    source_type: str = "none"
    source_id: Optional[str] = None
    draw_order: int = 0
    playback_offset: float = 0.0
    playback_speed: float = 1.0
    playback_mode: str = "loop"
    path_mode: str = "linear"
    use_source_root_motion: bool = False
    mapping_id: Optional[str] = None
    keyframes: List[TimelineKeyframe] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "mapping_id": self.mapping_id,
            "draw_order": self.draw_order,
            "playback_offset": self.playback_offset,
            "playback_speed": self.playback_speed,
            "playback_mode": self.playback_mode,
            "path_mode": self.path_mode,
            "use_source_root_motion": self.use_source_root_motion,
            "keyframes": [kf.to_dict() for kf in self.keyframes],
        }

    def clone(self) -> "TimelineObject":
        return TimelineObject.from_dict(self.to_dict())

    def sorted_keyframes(self) -> List[TimelineKeyframe]:
        return sorted(self.keyframes, key=lambda kf: (float(kf.time), str(kf.id)))

    @staticmethod
    def from_dict(data: Dict) -> "TimelineObject":
        source_type = str(data.get("source_type", "none") or "none").strip().lower()
        if source_type not in TIMELINE_SOURCE_TYPES:
            source_type = "none"
        playback_mode = str(data.get("playback_mode", "loop") or "loop").strip().lower()
        if playback_mode not in ("loop", "once", "ping_pong"):
            playback_mode = "loop"
        path_mode = str(data.get("path_mode", "linear") or "linear").strip().lower()
        if path_mode not in TIMELINE_PATH_MODES:
            path_mode = "linear"
        keyframes = [TimelineKeyframe.from_dict(kf) for kf in data.get("keyframes", [])]
        if not keyframes:
            keyframes = [TimelineKeyframe(id=generate_id("tlk"), time=0.0)]
        return TimelineObject(
            id=str(data.get("id", generate_id("tlo"))),
            name=str(data.get("name", "Object")),
            parent_id=str(data.get("parent_id")) if data.get("parent_id") is not None else None,
            source_type=source_type,
            source_id=str(data.get("source_id")) if data.get("source_id") is not None else None,
            draw_order=int(data.get("draw_order", 0)),
            playback_offset=float(data.get("playback_offset", 0.0)),
            playback_speed=float(data.get("playback_speed", 1.0)),
            playback_mode=playback_mode,
            path_mode=path_mode,
            use_source_root_motion=bool(data.get("use_source_root_motion", False)),
            mapping_id=str(data.get("mapping_id")) if data.get("mapping_id") else None,
            keyframes=keyframes,
        )


@dataclass
class TimelineScene:
    id: str
    name: str
    fps: int = 12
    duration_seconds: float = 10.0
    loop: bool = True
    background_color: Tuple[int, int, int] = (32, 32, 32)
    objects: List[TimelineObject] = field(default_factory=list)

    def duration_in_frames(self) -> int:
        return max(1, int(round(float(self.duration_seconds) * float(max(1, self.fps)))))

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "fps": self.fps,
            "duration_seconds": self.duration_seconds,
            "duration_frames": self.duration_in_frames(),
            "loop": self.loop,
            "background_color": list(self.background_color),
            "objects": [obj.to_dict() for obj in self.objects],
        }

    def clone(self) -> "TimelineScene":
        return TimelineScene.from_dict(self.to_dict())

    def get_object(self, object_id: str) -> Optional[TimelineObject]:
        return next((obj for obj in self.objects if obj.id == object_id), None)

    def object_mapping(
        self, project: "Project", object_id: str, default: Optional["ModuleMapping"]
    ) -> Optional["ModuleMapping"]:
        """The mapping an object is drawn with: its own, else its nearest ancestor's, else ``default``
        (the preview mapping in the editor, the mapping being baked in exporters). An id that no longer
        exists counts as unset."""
        seen: set = set()
        obj = self.get_object(object_id)
        while obj and obj.id not in seen:
            seen.add(obj.id)
            if obj.mapping_id == TIMELINE_MAPPING_ORIGINAL:
                return None
            if obj.mapping_id:
                mapping = project.get_mapping(obj.mapping_id)
                if mapping:
                    return mapping
            obj = self.get_object(obj.parent_id) if obj.parent_id else None
        return default

    def create_object(
        self,
        name: str,
        source_type: str = "none",
        source_id: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> TimelineObject:
        source_type = str(source_type or "none").strip().lower()
        if source_type not in TIMELINE_SOURCE_TYPES:
            source_type = "none"
        obj = TimelineObject(
            id=generate_id("tlo"),
            name=name,
            parent_id=parent_id,
            source_type=source_type,
            source_id=source_id,
            draw_order=len(self.objects),
            keyframes=[TimelineKeyframe(id=generate_id("tlk"), time=0.0)],
        )
        self.objects.append(obj)
        return obj

    def delete_object(self, object_id: str) -> None:
        self.objects = [obj for obj in self.objects if obj.id != object_id]
        for obj in self.objects:
            if obj.parent_id == object_id:
                obj.parent_id = None

    @staticmethod
    def from_dict(data: Dict) -> "TimelineScene":
        objects = [TimelineObject.from_dict(obj) for obj in data.get("objects", [])]
        color = data.get("background_color", (32, 32, 32))
        fps = max(1, int(data.get("fps", 12)))
        duration_seconds = data.get("duration_seconds")
        legacy_frame_timeline = duration_seconds is None
        if duration_seconds is None:
            legacy_duration_frames = data.get("duration_frames", 120)
            duration_seconds = float(legacy_duration_frames) / float(fps)
        if legacy_frame_timeline:
            frame_to_seconds = 1.0 / float(fps)
            for obj in objects:
                obj.playback_offset = float(obj.playback_offset) * frame_to_seconds
                for keyframe in obj.keyframes:
                    keyframe.time = float(keyframe.time) * frame_to_seconds
        return TimelineScene(
            id=str(data.get("id", generate_id("scene"))),
            name=str(data.get("name", "Scene")),
            fps=fps,
            duration_seconds=max(1.0 / float(fps), float(duration_seconds)),
            loop=bool(data.get("loop", True)),
            background_color=tuple(int(v) for v in color) if color is not None else (32, 32, 32),  # type: ignore[arg-type]
            objects=objects,
        )

    def _sample_source(
        self,
        project: "Project",
        obj: TimelineObject,
        scene_time: float,
        source_type: str,
        source_id: Optional[str],
        started_at: float = 0.0,
    ) -> Dict[str, Any]:
        resolved_type = source_type if source_type in TIMELINE_SOURCE_TYPES else obj.source_type
        resolved_id = source_id if source_id is not None else obj.source_id
        result = {
            "source_type": resolved_type,
            "source_id": resolved_id,
            "frame_id": None,
            "source_offset": (0.0, 0.0),
            "source_flip_x": False,
            "source_flip_y": False,
            "source_rotation": 0.0,
        }
        if not resolved_id or resolved_type in ("none", "module"):
            return result
        if resolved_type == "frame":
            result["frame_id"] = resolved_id
            return result
        anim = project.get_animation(resolved_id)
        if not anim or not anim.aframes:
            return result
        local_time = (scene_time - started_at) * obj.playback_speed + obj.playback_offset
        source_fps = anim.fps if anim.fps > 0 else 10
        sampled = project.sample_animation_frame(
            anim.id,
            round(local_time * float(source_fps), 6),  # (0.7 - 0.4) * 10 must reach tick 3, not 2.999…
            playback_override=obj.playback_mode,
        )
        if not sampled:
            return result
        af, _sample_index = sampled
        result["frame_id"] = af.frame_id
        if obj.use_source_root_motion:
            result["source_offset"] = (float(af.offset[0]), float(af.offset[1]))
            result["source_flip_x"] = bool(af.flip_x)
            result["source_flip_y"] = bool(af.flip_y)
            result["source_rotation"] = float(getattr(af, "rotation_degrees", 0.0))
        return result

    def _resolve_source_at_time(
        self, obj: TimelineObject, keyframes: List[TimelineKeyframe], time: float
    ) -> Tuple[str, Optional[str], float]:
        """(source type, source id, start time) at ``time``. An animation swapped in at a key plays from
        that key; the object's own source and a swap on the first key play from the scene start."""
        resolved_type = obj.source_type if obj.source_type in TIMELINE_SOURCE_TYPES else "none"
        resolved_id = obj.source_id
        started_at = 0.0
        if keyframes and float(time) <= float(keyframes[0].time):
            first = keyframes[0]
            if first.source_type is not None:
                next_type = first.source_type if first.source_type in TIMELINE_SOURCE_TYPES else resolved_type
                resolved_type = next_type
                if resolved_type == "none":
                    resolved_id = None
                elif first.source_id is not None:
                    resolved_id = first.source_id
            elif first.source_id is not None:
                resolved_id = first.source_id
            return (resolved_type, resolved_id, started_at)
        for index, key in enumerate(keyframes):
            if float(key.time) > float(time):
                break
            if key.source_type is not None:
                next_type = key.source_type if key.source_type in TIMELINE_SOURCE_TYPES else resolved_type
                type_changed = next_type != resolved_type
                resolved_type = next_type
                if resolved_type == "none":
                    resolved_id = None
                elif key.source_id is not None:
                    resolved_id = key.source_id
                elif type_changed:
                    resolved_id = None
            elif key.source_id is not None:
                resolved_id = key.source_id
            else:
                continue
            if index > 0:
                started_at = float(key.time)
        return (resolved_type, resolved_id, started_at)

    def evaluate_object_state(self, project: "Project", object_id: str, time: float) -> Optional[Dict[str, Any]]:
        obj = self.get_object(object_id)
        if not obj:
            return None
        keyframes = obj.sorted_keyframes()
        if not keyframes:
            return None
        if len(keyframes) == 1 or time <= keyframes[0].time:
            first = keyframes[0]
            resolved_source_type, resolved_source_id, started_at = self._resolve_source_at_time(obj, keyframes, time)
            sampled_source = self._sample_source(project, obj, time, resolved_source_type, resolved_source_id, started_at)
            key_source_offset = (float(first.source_offset[0]), float(first.source_offset[1]))
            sampled_source["source_offset"] = (
                float(sampled_source["source_offset"][0]) + key_source_offset[0],
                float(sampled_source["source_offset"][1]) + key_source_offset[1],
            )
            return {
                "object_id": obj.id,
                "name": obj.name,
                "parent_id": obj.parent_id,
                "draw_order": obj.draw_order,
                "x": float(first.x),
                "y": float(first.y),
                "rotation_degrees": float(first.rotation_degrees),
                "scale_x": float(first.scale_x),
                "scale_y": float(first.scale_y),
                "flip_x": bool(first.flip_x),
                "flip_y": bool(first.flip_y),
                "visible": bool(first.visible),
                "opacity": _timeline_clamp01(first.opacity),
                "source_key_offset": key_source_offset,
                **sampled_source,
            }

        prev_key = keyframes[0]
        next_key = keyframes[-1]
        prev_idx = 0
        next_idx = len(keyframes) - 1
        for idx in range(len(keyframes) - 1):
            left = keyframes[idx]
            right = keyframes[idx + 1]
            if left.time <= time <= right.time:
                prev_key = left
                next_key = right
                prev_idx = idx
                next_idx = idx + 1
                break
            if time > right.time:
                prev_key = right
                prev_idx = idx + 1
        if time >= keyframes[-1].time:
            last = keyframes[-1]
            resolved_source_type, resolved_source_id, started_at = self._resolve_source_at_time(obj, keyframes, time)
            sampled_source = self._sample_source(project, obj, time, resolved_source_type, resolved_source_id, started_at)
            key_source_offset = (float(last.source_offset[0]), float(last.source_offset[1]))
            sampled_source["source_offset"] = (
                float(sampled_source["source_offset"][0]) + key_source_offset[0],
                float(sampled_source["source_offset"][1]) + key_source_offset[1],
            )
            return {
                "object_id": obj.id,
                "name": obj.name,
                "parent_id": obj.parent_id,
                "draw_order": obj.draw_order,
                "x": float(last.x),
                "y": float(last.y),
                "rotation_degrees": float(last.rotation_degrees),
                "scale_x": float(last.scale_x),
                "scale_y": float(last.scale_y),
                "flip_x": bool(last.flip_x),
                "flip_y": bool(last.flip_y),
                "visible": bool(last.visible),
                "opacity": _timeline_clamp01(last.opacity),
                "source_key_offset": key_source_offset,
                **sampled_source,
            }

        span = max(1e-6, float(next_key.time) - float(prev_key.time))
        raw_t = (float(time) - float(prev_key.time)) / span
        eased_t = apply_timeline_easing(next_key.easing or prev_key.easing, raw_t)
        p0 = (float(prev_key.x), float(prev_key.y))
        p3 = (float(next_key.x), float(next_key.y))
        p1 = tuple(float(v) for v in (prev_key.path_out if prev_key.path_out is not None else p0))  # type: ignore[assignment]
        p2 = tuple(float(v) for v in (next_key.path_in if next_key.path_in is not None else p3))  # type: ignore[assignment]
        has_path = prev_key.path_out is not None or next_key.path_in is not None
        if obj.path_mode == "spline" and has_path:
            pos_x, pos_y = _timeline_cubic_point(p0, p1, p2, p3, eased_t)
        elif obj.path_mode == "spline" and len(keyframes) >= 3 and p0 != p3:
            # Auto curves only between keys at different spots: two keys at the same spot hold
            # still instead of drifting out and back along the neighbours' tangent.
            left_neighbor = keyframes[prev_idx - 1] if prev_idx > 0 else prev_key
            right_neighbor = keyframes[next_idx + 1] if (next_idx + 1) < len(keyframes) else next_key
            pos_x, pos_y = _timeline_catmull_rom_point(
                (float(left_neighbor.x), float(left_neighbor.y)),
                p0,
                p3,
                (float(right_neighbor.x), float(right_neighbor.y)),
                eased_t,
            )
        else:
            pos_x = _timeline_lerp(prev_key.x, next_key.x, eased_t)
            pos_y = _timeline_lerp(prev_key.y, next_key.y, eased_t)
        resolved_source_type, resolved_source_id, started_at = self._resolve_source_at_time(obj, keyframes, time)
        sampled_source = self._sample_source(project, obj, time, resolved_source_type, resolved_source_id, started_at)
        key_source_offset = (float(prev_key.source_offset[0]), float(prev_key.source_offset[1]))
        sampled_source["source_offset"] = (
            float(sampled_source["source_offset"][0]) + key_source_offset[0],
            float(sampled_source["source_offset"][1]) + key_source_offset[1],
        )
        return {
            "object_id": obj.id,
            "name": obj.name,
            "parent_id": obj.parent_id,
            "draw_order": obj.draw_order,
            "x": pos_x,
            "y": pos_y,
            "rotation_degrees": _timeline_lerp(prev_key.rotation_degrees, next_key.rotation_degrees, eased_t),
            "scale_x": _timeline_lerp(prev_key.scale_x, next_key.scale_x, eased_t),
            "scale_y": _timeline_lerp(prev_key.scale_y, next_key.scale_y, eased_t),
            "flip_x": next_key.flip_x if eased_t >= 0.5 else prev_key.flip_x,
            "flip_y": next_key.flip_y if eased_t >= 0.5 else prev_key.flip_y,
            "visible": next_key.visible if eased_t >= 0.5 else prev_key.visible,
            "opacity": _timeline_clamp01(_timeline_lerp(prev_key.opacity, next_key.opacity, eased_t)),
            "source_key_offset": key_source_offset,
            **sampled_source,
        }

    def sample_draw_list(self, project: "Project", time: float) -> List[Dict[str, Any]]:
        states: List[Dict[str, Any]] = []
        for obj in sorted(self.objects, key=lambda item: (item.draw_order, item.name.lower(), item.id)):
            state = self.evaluate_object_state(project, obj.id, time)
            if state is not None:
                states.append(state)
        return states


class AuroraSpriteParser:
    """Parses AuroraGT .sprite format."""

    @staticmethod
    def _parse_color(val: str) -> Tuple[int, int, int]:
        try:
            if val.startswith("0x") or val.startswith("0X"):
                v = int(val, 16)
                r = (v >> 16) & 0xFF
                g = (v >> 8) & 0xFF
                b = v & 0xFF
                return (r, g, b)
            # If plain int, assume it's also packed RGB
            v = int(val)
            r = (v >> 16) & 0xFF
            g = (v >> 8) & 0xFF
            b = v & 0xFF
            return (r, g, b)
        except ValueError:
            return (255, 255, 255)
    
    @staticmethod
    def parse(content: str, base_path: str) -> "Project":
        project = Project()
        images_map = {}
        image_index = 0
        
        current_block = None
        current_obj = None
        
        lines = content.splitlines()
        for raw_line in lines:
            # Strip comments and trim
            line = raw_line.split("//")[0].split("/*")[0].strip()
            if not line:
                continue
            
            # 1. Images
            img_match = re.search(r'IMAGE\s+(0x[\da-fA-F]+)\s+"([^"]+)"(?:\s+TRANSP\s+(0x[\da-fA-F]+))?', line)
            if img_match:
                img_hex_id, filename, transp_hex = img_match.groups()
                trans_color = None
                if transp_hex:
                    val = int(transp_hex, 16)
                    r = (val >> 16) & 0xFF
                    g = (val >> 8) & 0xFF
                    b = val & 0xFF
                    trans_color = (r, g, b)
                
                abs_path = os.path.join(base_path, filename)
                
                # Use generated ID instead of path (User Request)
                # But we map index -> ID for modules to reference
                new_img_id = generate_id("img")
                images_map[image_index] = new_img_id
                
                img_asset = ImageAsset(
                    id=new_img_id,
                    file_path=abs_path,
                    width=0,
                    height=0,
                    transparent_color=trans_color 
                )
                project.images.append(img_asset)
                image_index += 1
                continue

            # 2. Block Starts
            if line.startswith("MODULES"):
                current_block = "MODULES"
                continue
            
            if line.startswith("FRAME"):
                m = re.search(r'FRAME\s+"([^"]*)"', line)
                name = m.group(1) if m else "Unnamed Frame"
                current_block = "FRAME"
                current_obj = Frame(id=generate_id("frm"), name=name)
                continue
            
            if line.startswith("ANIM"):
                m = re.search(r'ANIM\s+"([^"]*)"', line)
                name = m.group(1) if m else "Unnamed Anim"
                current_block = "ANIM"
                current_obj = Animation(id=generate_id("anim"), name=name)
                continue

            if line.startswith("MAPPING"):
                m = re.search(r'MAPPING\s+"([^"]*)"', line)
                name = m.group(1) if m else "Unnamed Mapping"
                current_block = "MAPPING"
                current_obj = ModuleMapping(id=generate_id("map"), name=name)
                continue

            # 3. Block Endings
            if line == "}" or line == "SPRITE_END":
                if current_block == "FRAME":
                    if isinstance(current_obj, Frame):
                        project.frames.append(current_obj)
                elif current_block == "ANIM":
                    if isinstance(current_obj, Animation):
                        project.animations.append(current_obj)
                elif current_block == "MAPPING":
                    if isinstance(current_obj, ModuleMapping):
                        project.mappings.append(current_obj)
                current_block = None
                current_obj = None
                continue

            # 4. Content Parsing based on block
            if current_block == "MODULES":
                if line.startswith("MD"):
                    # MD [id] [type] [params...] ["name"]
                    parts = line.split()
                    if len(parts) >= 3:
                        md_id = parts[1].strip()
                        md_type = parts[2].strip()
                        
                        # Extract name if present
                        name = ""
                        name_match = re.search(r'"([^"]*)"', line)
                        if name_match:
                            name = name_match.group(1)
                        else:
                            name = f"Module {md_id}"

                        # Defaults
                        rect = (0, 0, 0, 0)
                        pivot = (0, 0)
                        image_id = "missing"
                        color = (255, 255, 255)
                        params = []

                        try:
                            # 1. MD_IMAGE: img_idx x y w h
                            if md_type == "MD_IMAGE":
                                img_idx = int(parts[3])
                                x, y, w, h = int(parts[4]), int(parts[5]), int(parts[6]), int(parts[7])
                                rect = (x, y, w, h)
                                pivot = (w // 2, h // 2)
                                
                                target_img_id = images_map.get(img_idx, None)
                                if target_img_id:
                                    image_id = target_img_id
                                elif project.images:
                                    image_id = project.images[0].id

                            # 2. MD_RECT / FILL_RECT / MARKER: color w h
                            elif md_type in ("MD_RECT", "MD_FILL_RECT", "MD_MARKER"):
                                color = AuroraSpriteParser._parse_color(parts[3])
                                w, h = int(parts[4]), int(parts[5])
                                rect = (0, 0, w, h)
                                pivot = (w // 2, h // 2)

                            # 3. MD_ARC / FILL_ARC: color w h start arc
                            elif md_type in ("MD_ARC", "MD_FILL_ARC"):
                                color = AuroraSpriteParser._parse_color(parts[3])
                                w, h = int(parts[4]), int(parts[5])
                                start, arc = float(parts[6]), float(parts[7])
                                rect = (0, 0, w, h)
                                pivot = (w // 2, h // 2)
                                params = [start, arc]

                            # 4. MD_TRIANGLE / FILL: color p2x p2y p3x p3y
                            elif md_type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
                                color = AuroraSpriteParser._parse_color(parts[3])
                                p2x, p2y = int(parts[4]), int(parts[5])
                                p3x, p3y = int(parts[6]), int(parts[7])
                                
                                # Calc bounding box encompassing Origin(0,0), P2, P3
                                min_x, max_x = min(0, p2x, p3x), max(0, p2x, p3x)
                                min_y, max_y = min(0, p2y, p3y), max(0, p2y, p3y)
                                w, h = max(1, max_x - min_x), max(1, max_y - min_y) # Avoid div/0
                                
                                rect = (min_x, min_y, w, h)
                                pivot = (0, 0) # Pivot remains 0,0 relative to origin? Or Center?
                                # User said: "The first point... is always the top left (origin) of the module" (Legacy).
                                # But we want to decouple it.
                                # Pivot usually defaults to center.
                                pivot = (w // 2, h // 2)
                                
                                # Convert 3 Points (0,0), (p2), (p3) to Percentages of Rect
                                # P1 (0,0) relative to Rect Min:
                                p1_rel_x, p1_rel_y = 0 - min_x, 0 - min_y
                                p2_rel_x, p2_rel_y = p2x - min_x, p2y - min_y
                                p3_rel_x, p3_rel_y = p3x - min_x, p3y - min_y
                                
                                params = [
                                    (p1_rel_x / w) * 100.0, (p1_rel_y / h) * 100.0,
                                    (p2_rel_x / w) * 100.0, (p2_rel_y / h) * 100.0,
                                    (p3_rel_x / w) * 100.0, (p3_rel_y / h) * 100.0
                                ]

                            # 5. MD_LINE: color x1 y1 x2 y2 (Percentages) OR color endX endY (Legacy)
                            elif md_type == "MD_LINE":
                                color = AuroraSpriteParser._parse_color(parts[3])
                                
                                # Check for new 4-param format (Percentages)
                                if len(parts) >= 8:
                                    # P1(x,y) P2(x,y) are Percentages? 
                                    # Wait, the parser doesn't know if they are percentages or pixels unless we strictly change the format.
                                    # But since we are changing the internal model to percentages, let's assume if we see 4 numbers, they are the stored percentages.
                                    # Format: MD_LINE color x1 y1 x2 y2
                                    p1x, p1y = float(parts[4]), float(parts[5])
                                    p2x, p2y = float(parts[6]), float(parts[7])
                                    
                                    # For NEW format, we need to know the Rect too?
                                    # But Module definition usually is: MD id type color params... "name"
                                    # Wait, `Module` object has `rect` and `pivot`.
                                    # Legacy format inferred Rect from the vector.
                                    # New format: User defines the Rect in the editor.
                                    # But in the FILE, we need to save the Rect if it's not inferred.
                                    # Actually, `AuroraSpriteParser` infers rect for Shapes because they didn't have explicit rect in legacy.
                                    # BUT if we switch to generic shapes, they should probably behave like primitives.
                                    # Issue: The parser logic for SHAPES here hardcodes `rect = derived`.
                                    # If we want editable rects, we should probably allow the SAVE format to include rect.
                                    # However, sticking to the current task: "Migrate to 4-Point Percentage".
                                    # If the file provides 4 params, it MUST imply we generated it, so we probably saved a Rect somewhere?
                                    # Actually, `models.py` `to_dict` / serialization isn't shown here but usually one saves everything.
                                    # BUT `AuroraSpriteParser` is for IMPORTING the specific Aurora format.
                                    # If I am inventing a new format variation, I should be careful.
                                    # Let's assume for now 4 params = Percentages.
                                    # But we still need a Rect. 
                                    # If I just load params, `rect` will be 0,0,0,0 unless I infer it?
                                    # Problem: Percentage system requires a Rect to be meaningful.
                                    # If I can't reconstruct the Rect from percentages (impossible), I need the Rect saved.
                                    # The `to_dict` DOES save `rect`.
                                    # But this is `AuroraSpriteParser`, which parses a TEXT file format.
                                    # Does the text format save the rect for shapes?
                                    # Lines 487-500 show MD_RECT/ARC getting w/h from params.
                                    # For MD_LINE (New), we might not have pixel dimensions if we only save percentages?
                                    # CONSTRAINT: The Aurora TEXT format might not be suitable for fully "free" shapes unless we change how they are saved (e.g. include explicit W/H).
                                    # Current decision: For this "Migration", legacy files define the rect.
                                    # New files generated by this tool: Do they use this Parser? 
                                    # No, `to_dict`/`from_dict` (JSON) is used for the native project file!
                                    # `AuroraSpriteParser` is likely for IMPORTING external assets.
                                    # So strictly speaking, `AuroraSpriteParser` only needs to handle LEGACY/Simple formats.
                                    # NEW files will be JSON `models.json`.
                                    # SO: This parser update is strictly to allow IMPORTING legacy lines and converting them to our new internal format.
                                    # Legacy Line: `color endX endY` (Absolute, from 0,0).
                                    
                                    endX, endY = int(parts[4]), int(parts[5])
                                    
                                    min_x, max_x = min(0, endX), max(0, endX)
                                    min_y, max_y = min(0, endY), max(0, endY)
                                    w, h = max(1, max_x - min_x), max(1, max_y - min_y)
                                    
                                    rect = (min_x, min_y, w, h)
                                    pivot = (w // 2, h // 2)
                                    
                                    # Convert to Percentages relative to Rect
                                    # P1(0,0):
                                    p1x_pct = (0 - min_x) / w * 100.0
                                    p1y_pct = (0 - min_y) / h * 100.0
                                    # P2(endX, endY):
                                    p2x_pct = (endX - min_x) / w * 100.0
                                    p2y_pct = (endY - min_y) / h * 100.0
                                    
                                    params = [p1x_pct, p1y_pct, p2x_pct, p2y_pct]
                                else:
                                    # Malformed or other legacy?
                                    # Keep legacy "2 params" fallback logic just in case logic above fails?
                                    # Actually, existing logic IS the legacy logic.
                                    endX, endY = int(parts[4]), int(parts[5])
                                    min_x, max_x = min(0, endX), max(0, endX)
                                    min_y, max_y = min(0, endY), max(0, endY)
                                    w, h = max(1, max_x - min_x), max(1, max_y - min_y)
                                    rect = (min_x, min_y, w, h)
                                    pivot = (w // 2, h // 2)
                                    
                                    p1x_pct = (0 - min_x) / w * 100.0
                                    p1y_pct = (0 - min_y) / h * 100.0
                                    p2x_pct = (endX - min_x) / w * 100.0
                                    p2y_pct = (endY - min_y) / h * 100.0
                                    
                                    params = [p1x_pct, p1y_pct, p2x_pct, p2y_pct]
                                    
                                # Note: I collapsed both cases because Aurora Text Parser likely won't see "Percentage" lines unless we change the exporter too.
                                # Detailed Assumption: We only parse Legacy Lines here.
                                # Internal JSON parsing handles the full format.

                            project.modules.append(Module(
                                id=md_id,
                                name=name,
                                image_id=image_id,
                                rect=rect,
                                pivot=pivot,
                                type=md_type,
                                color=color,
                                params=params
                            ))
                        except (ValueError, IndexError):
                            pass
                continue

            if current_block == "FRAME" and isinstance(current_obj, Frame):
                if re.match(r'^0x[\da-fA-F]+$', line):
                    current_obj.id = line
                elif line.startswith("FM"):
                    parts = line.split()
                    if len(parts) >= 4:
                        ref_id = parts[1].strip()
                        try:
                            ox = int(parts[2])
                            oy = int(parts[3])
                            flip_x = "+FLIP_X" in line
                            flip_y = "+FLIP_Y" in line
                            
                            fmod = FModule(
                                id=generate_id("fmod"),
                                ref_type="module",
                                ref_id=ref_id,
                                position=(ox, oy),
                                flip_x=flip_x,
                                flip_y=flip_y
                            )
                            current_obj.fmodules.append(fmod)
                        except ValueError: pass
                elif line.startswith("RC"):
                    parts = line.split()
                    if len(parts) >= 5:
                        try:
                            x1, y1, x2, y2 = map(int, parts[1:5])
                            if x2 <= x1 or y2 <= y1:
                                # "RC 0 0 0 0" marks a frame without a box; that is not a hitbox.
                                continue
                            if not project.collision_types:
                                project.collision_types.append(CollisionType(id="default", name="Default", color=(255, 0, 0)))

                            crect = CollisionRect(
                                id=generate_id("rc"),
                                type_id=project.collision_types[0].id,
                                rect=(x1, y1, x2 - x1, y2 - y1)
                            )
                            current_obj.collision_rects.append(crect)
                        except ValueError: pass
                continue

            if current_block == "ANIM" and isinstance(current_obj, Animation):
                if re.match(r'^0x[\da-fA-F]+$', line):
                    current_obj.id = line
                elif line.startswith("AF"):
                    parts = line.split()
                    if len(parts) >= 5:
                        ref_id = parts[1].strip()
                        try:
                            duration = int(parts[2])
                            ox = int(parts[3])
                            oy = int(parts[4])
                            flip_x = "+FLIP_X" in line
                            flip_y = "+FLIP_Y" in line
                            
                            af = AFrame(
                                frame_id=ref_id,
                                duration_frames=duration,
                                offset=(ox, oy),
                                flip_x=flip_x,
                                flip_y=flip_y
                            )
                            current_obj.aframes.append(af)
                        except ValueError: pass
                continue

            if current_block == "MAPPING" and isinstance(current_obj, ModuleMapping):
                if re.match(r'^0x[\da-fA-F]+$', line):
                    current_obj.id = line
                elif line.startswith("MD_MAP") or line.startswith("MAP"):
                    parts = line.split()
                    if len(parts) >= 3 and parts[0] in ("MD_MAP", "MAP"):
                        src_id = parts[1].strip()
                        dest_id = parts[2].strip()
                        if dest_id.upper() == "NONE":
                            dest_id = None
                        current_obj.map[src_id] = dest_id
                continue

        # 4. Linking Pass: Resolve FModule references
        # Check if ref_id matches a Module or a Frame. Default was "module".
        module_ids = {m.id for m in project.modules}
        frame_ids = {f.id for f in project.frames}
        
        for frame in project.frames:
            for fm in frame.fmodules:
                if fm.ref_id in frame_ids and fm.ref_id not in module_ids:
                    # It's a Frame (and not ambiguously a Module ID, though IDs should be unique)
                    fm.ref_type = "frame"
                elif fm.ref_id not in module_ids and fm.ref_id not in frame_ids:
                    # Unknown ref. Leave as module? or mark broken?
                    # Aurora GT usually links to modules.
                    pass

        return project


class RetroAnimatorParser:
    """Parses RetroAnimator JSON format used by Scorpion Engine tooling."""
    RETRO_TICKS_PER_SECOND = 50

    @staticmethod
    def _to_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    @staticmethod
    def _to_int(value: object, default: int = 0) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_u8(value: int) -> int:
        return max(0, min(255, int(value)))

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path.replace("\\", "/").strip()

    @staticmethod
    def _resolve_case_insensitive(base_path: str, rel_path: str) -> Optional[str]:
        """Resolve a relative path with case-insensitive fallback per path segment."""
        base_abs = os.path.abspath(base_path)
        current = base_abs
        parts = [p for p in RetroAnimatorParser._normalize_path(rel_path).split("/") if p and p != "."]

        for part in parts:
            if part == "..":
                current = os.path.dirname(current)
                continue

            if not os.path.isdir(current):
                return None

            try:
                entries = os.listdir(current)
            except OSError:
                return None

            exact = next((e for e in entries if e == part), None)
            if exact is None:
                lower_part = part.lower()
                exact = next((e for e in entries if e.lower() == lower_part), None)

            if exact is None:
                return None

            current = os.path.join(current, exact)

        return current

    @staticmethod
    def _resolve_frame_path(base_path: str, frame_path: str) -> str:
        normalized = RetroAnimatorParser._normalize_path(frame_path)
        if not normalized:
            return os.path.abspath(base_path)

        if os.path.isabs(normalized):
            candidate = os.path.abspath(normalized)
            if os.path.exists(candidate):
                return candidate
            resolved = RetroAnimatorParser._resolve_case_insensitive(os.path.dirname(candidate), os.path.basename(candidate))
            return resolved or candidate

        candidate = os.path.abspath(os.path.join(base_path, normalized.replace("/", os.sep)))
        if os.path.exists(candidate):
            return candidate

        resolved = RetroAnimatorParser._resolve_case_insensitive(base_path, normalized)
        return resolved or candidate

    @staticmethod
    def parse(data: Dict, base_path: str, project_name: Optional[str] = None) -> "Project":
        project = Project(name=project_name or data.get("Name", "RetroAnimator Import"))

        frames_data = data.get("Frames", {})
        if not isinstance(frames_data, dict):
            frames_data = {}

        animations_data = data.get("Animations", {})
        if not isinstance(animations_data, dict):
            animations_data = {}

        path_to_module_id: Dict[str, str] = {}
        frame_key_to_id: Dict[str, str] = {}
        collision_type_by_name: Dict[str, str] = {}

        def get_or_create_module(frame_path: str) -> Optional[str]:
            normalized = RetroAnimatorParser._normalize_path(frame_path)
            if not normalized:
                return None

            key = normalized.lower()
            if key in path_to_module_id:
                return path_to_module_id[key]

            abs_path = RetroAnimatorParser._resolve_frame_path(base_path, normalized)
            width = 0
            height = 0
            if os.path.exists(abs_path):
                try:
                    from PIL import Image as PILImage
                    with PILImage.open(abs_path) as img:
                        width, height = img.size
                except Exception:
                    width = 0
                    height = 0

            img = ImageAsset(
                id=generate_id("img"),
                file_path=abs_path,
                width=int(width),
                height=int(height),
            )
            project.images.append(img)

            name_source = os.path.basename(abs_path if os.path.exists(abs_path) else normalized)
            module_name = os.path.splitext(name_source)[0] or f"Part {len(project.modules) + 1}"
            mod = Module(
                id=generate_id("mod"),
                name=module_name,
                image_id=img.id,
                rect=(0, 0, int(width), int(height)),
                pivot=(0, 0),
                type="MD_IMAGE",
            )
            project.modules.append(mod)

            path_to_module_id[key] = mod.id
            return mod.id

        # Build frames first so animations can resolve references.
        for frame_key, frame_payload in frames_data.items():
            frame_name = str(frame_key)
            frame_id = frame_name
            frame_key_to_id[frame_name] = frame_id

            frame = Frame(
                id=frame_id,
                name=frame_name,
            )

            payload = frame_payload if isinstance(frame_payload, dict) else {}
            sprites = payload.get("Sprites", [])
            if isinstance(sprites, list):
                for sprite_data in sprites:
                    if not isinstance(sprite_data, dict):
                        continue
                    frame_path = sprite_data.get("FramePath", "")
                    module_id = get_or_create_module(str(frame_path))
                    if not module_id:
                        continue

                    frame.fmodules.append(
                        FModule(
                            id=generate_id("fmod"),
                            ref_type="module",
                            ref_id=module_id,
                            position=(
                                RetroAnimatorParser._to_int(sprite_data.get("HandleX"), 0),
                                RetroAnimatorParser._to_int(sprite_data.get("HandleY"), 0),
                            ),
                            flip_x=RetroAnimatorParser._to_bool(sprite_data.get("XFlip", False)),
                            flip_y=False,
                            rotation_degrees=0.0,
                        )
                    )

            colrects = payload.get("ColRects", {})
            if isinstance(colrects, dict):
                for col_name, col_data in colrects.items():
                    if not isinstance(col_data, dict):
                        continue

                    rect = (
                        RetroAnimatorParser._to_int(col_data.get("X"), 0),
                        RetroAnimatorParser._to_int(col_data.get("Y"), 0),
                        RetroAnimatorParser._to_int(col_data.get("Width"), 0),
                        RetroAnimatorParser._to_int(col_data.get("Height"), 0),
                    )
                    if rect[2] <= 0 or rect[3] <= 0:
                        # RetroAnimator stores a frame without a box as a box of no size; that is not a hitbox.
                        continue
                    name = str(col_name)
                    if name not in collision_type_by_name:
                        ctype = CollisionType(
                            id=generate_id("ctype"),
                            name=name,
                            color=(
                                RetroAnimatorParser._clamp_u8(RetroAnimatorParser._to_int(col_data.get("ColorR"), 255)),
                                RetroAnimatorParser._clamp_u8(RetroAnimatorParser._to_int(col_data.get("ColorG"), 0)),
                                RetroAnimatorParser._clamp_u8(RetroAnimatorParser._to_int(col_data.get("ColorB"), 0)),
                            ),
                        )
                        project.collision_types.append(ctype)
                        collision_type_by_name[name] = ctype.id

                    frame.collision_rects.append(
                        CollisionRect(id=generate_id("crect"), type_id=collision_type_by_name[name], rect=rect)
                    )

            project.frames.append(frame)

        for anim_key, anim_payload in animations_data.items():
            anim_name = str(anim_key)
            anim = Animation(
                id=generate_id("anim"),
                name=anim_name,
                fps=RetroAnimatorParser.RETRO_TICKS_PER_SECOND,
            )

            payload = anim_payload if isinstance(anim_payload, dict) else {}
            frame_data = payload.get("FrameData", [])
            if isinstance(frame_data, list):
                for af_data in frame_data:
                    if not isinstance(af_data, dict):
                        continue

                    source_frame_id = str(af_data.get("FrameID", "")).strip()
                    if not source_frame_id:
                        continue
                    resolved_frame_id = frame_key_to_id.get(source_frame_id)
                    if not resolved_frame_id:
                        continue

                    duration = max(1, RetroAnimatorParser._to_int(af_data.get("Duration"), 1))
                    anim.aframes.append(
                        AFrame(
                            frame_id=resolved_frame_id,
                            duration_frames=duration,
                            offset=(0, 0),
                            flip_x=False,
                            flip_y=False,
                            rotation_degrees=0.0,
                        )
                    )

            project.animations.append(anim)

        return project


class RetroAnimatorExporter:
    """Exports the current project into RetroAnimator JSON + cropped PNG parts."""

    RETRO_TICKS_PER_SECOND = 50
    PARTS_DIRNAME = "Cropped parts"

    @staticmethod
    def _identity_matrix() -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return ((1.0, 0.0), (0.0, 1.0))

    @staticmethod
    def _identity_offset() -> Tuple[float, float]:
        return (0.0, 0.0)

    @staticmethod
    def _flip_matrix(flip_x: bool, flip_y: bool) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return ((-1.0 if flip_x else 1.0, 0.0), (0.0, -1.0 if flip_y else 1.0))

    @staticmethod
    def _rotation_matrix(degrees: float) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        # Exact values for 90° steps: float residue (cos 90° = 6e-17) would otherwise shift
        # floor()-based part bounds by a pixel once nested transforms are composed.
        quarter = float(degrees) / 90.0
        if abs(quarter - round(quarter)) < 1e-9:
            c, s = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(round(quarter)) % 4]
            return ((c, -s), (s, c))
        rad = math.radians(float(degrees))
        c = math.cos(rad)
        s = math.sin(rad)
        return ((c, -s), (s, c))

    @staticmethod
    def _mat_mul(
        a: Tuple[Tuple[float, float], Tuple[float, float]],
        b: Tuple[Tuple[float, float], Tuple[float, float]],
    ) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (
            (a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1]),
            (a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1]),
        )

    @staticmethod
    def _mat_vec_mul(
        a: Tuple[Tuple[float, float], Tuple[float, float]],
        v: Tuple[float, float],
    ) -> Tuple[float, float]:
        return (a[0][0] * v[0] + a[0][1] * v[1], a[1][0] * v[0] + a[1][1] * v[1])

    @staticmethod
    def _compose(
        parent_a: Tuple[Tuple[float, float], Tuple[float, float]],
        parent_b: Tuple[float, float],
        local_a: Tuple[Tuple[float, float], Tuple[float, float]],
        local_b: Tuple[float, float],
    ) -> Tuple[Tuple[Tuple[float, float], Tuple[float, float]], Tuple[float, float]]:
        out_a = RetroAnimatorExporter._mat_mul(parent_a, local_a)
        pb = RetroAnimatorExporter._mat_vec_mul(parent_a, local_b)
        out_b = (pb[0] + parent_b[0], pb[1] + parent_b[1])
        return out_a, out_b

    @staticmethod
    def _invert(
        a: Tuple[Tuple[float, float], Tuple[float, float]]
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
        if abs(det) < 1e-9:
            return None
        inv_det = 1.0 / det
        return (
            (a[1][1] * inv_det, -a[0][1] * inv_det),
            (-a[1][0] * inv_det, a[0][0] * inv_det),
        )

    @staticmethod
    def _sanitize_name(value: str, fallback: str = "item") -> str:
        v = re.sub(r"[^A-Za-z0-9 _.-]+", "_", str(value or "")).strip()
        return v if v else fallback

    @staticmethod
    def _make_unique_name(base: str, used: set[str]) -> str:
        candidate = base
        i = 2
        while candidate in used:
            candidate = f"{base} {i}"
            i += 1
        used.add(candidate)
        return candidate

    @staticmethod
    def _resolve_module(project: "Project", module_id: str, mapping: Optional["ModuleMapping"]) -> Optional["Module"]:
        ref_id = module_id
        if mapping and ref_id in mapping.map:
            ref_id = mapping.map[ref_id]
        if not ref_id:
            return None
        return project.get_module(ref_id)

    @staticmethod
    def _render_shape_module(mod: "Module") -> Any:
        from PIL import Image as PILImage, ImageDraw

        w = max(1, int(mod.rect[2]))
        h = max(1, int(mod.rect[3]))
        img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        color = (int(mod.color[0]), int(mod.color[1]), int(mod.color[2]), 255)
        fill = color if "FILL" in mod.type else None

        if mod.type in ("MD_RECT", "MD_FILL_RECT"):
            draw.rectangle((0, 0, w - 1, h - 1), outline=color, fill=fill)
        elif mod.type == "MD_MARKER":
            draw.line((0, 0, w - 1, h - 1), fill=color, width=1)
            draw.line((w - 1, 0, 0, h - 1), fill=color, width=1)
        elif mod.type in ("MD_ARC", "MD_FILL_ARC"):
            start = float(mod.params[0]) if len(mod.params) >= 1 else 0.0
            sweep = float(mod.params[1]) if len(mod.params) >= 2 else 360.0
            draw.pieslice((0, 0, w - 1, h - 1), start=start, end=start + sweep, outline=color, fill=fill)
        elif mod.type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
            if len(mod.params) >= 6:
                p = mod.params
                points = [
                    (int(round((p[0] / 100.0) * w)), int(round((p[1] / 100.0) * h))),
                    (int(round((p[2] / 100.0) * w)), int(round((p[3] / 100.0) * h))),
                    (int(round((p[4] / 100.0) * w)), int(round((p[5] / 100.0) * h))),
                ]
            else:
                points = [(w // 2, 0), (w - 1, h - 1), (0, h - 1)]
            draw.polygon(points, outline=color, fill=fill)
        elif mod.type == "MD_LINE":
            if len(mod.params) >= 4:
                p1 = (int(round((mod.params[0] / 100.0) * w)), int(round((mod.params[1] / 100.0) * h)))
                p2 = (int(round((mod.params[2] / 100.0) * w)), int(round((mod.params[3] / 100.0) * h)))
            elif len(mod.params) >= 2:
                p1 = (0, 0)
                p2 = (int(round(mod.params[0])), int(round(mod.params[1])))
            else:
                p1 = (0, 0)
                p2 = (w - 1, h - 1)
            draw.line((p1[0], p1[1], p2[0], p2[1]), fill=color, width=1)
        else:
            draw.rectangle((0, 0, w - 1, h - 1), outline=color, fill=fill)
        return img

    @staticmethod
    def _apply_transparent_color_key(img: Any, transparent_color: Optional[Tuple[int, int, int]]) -> Any:
        if not transparent_color:
            return img

        tr, tg, tb = (
            int(transparent_color[0]),
            int(transparent_color[1]),
            int(transparent_color[2]),
        )
        raw = bytearray(img.tobytes())
        for i in range(0, len(raw), 4):
            if raw[i] == tr and raw[i + 1] == tg and raw[i + 2] == tb:
                raw[i + 3] = 0
        out = img.copy()
        out.frombytes(bytes(raw))
        return out

    @staticmethod
    def _load_module_rgba(
        project: "Project",
        mod: "Module",
        full_image_cache: Dict[str, Any],
        module_cache: Dict[str, Any],
    ) -> Any:
        from PIL import Image as PILImage

        if mod.id in module_cache:
            return module_cache[mod.id]

        if mod.type != "MD_IMAGE":
            img = RetroAnimatorExporter._render_shape_module(mod)
            module_cache[mod.id] = img
            return img

        asset = project.get_image(mod.image_id)
        w = max(1, int(mod.rect[2]))
        h = max(1, int(mod.rect[3]))

        if not asset or not os.path.exists(asset.file_path):
            img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
            module_cache[mod.id] = img
            return img

        trans_key = None
        if asset.transparent_color:
            trans_key = (
                int(asset.transparent_color[0]),
                int(asset.transparent_color[1]),
                int(asset.transparent_color[2]),
            )
        cache_key = f"{os.path.abspath(asset.file_path)}|key={trans_key}"
        if cache_key not in full_image_cache:
            loaded = PILImage.open(asset.file_path).convert("RGBA")
            loaded = RetroAnimatorExporter._apply_transparent_color_key(loaded, asset.transparent_color)
            full_image_cache[cache_key] = loaded
        source = full_image_cache[cache_key]

        rx, ry, rw, rh = mod.rect
        left = max(0, int(rx))
        top = max(0, int(ry))
        right = min(source.width, int(rx + rw))
        bottom = min(source.height, int(ry + rh))
        if right <= left or bottom <= top:
            img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
            module_cache[mod.id] = img
            return img

        img = source.crop((left, top, right, bottom))
        if mod.rotated:
            # Match current editor behavior (Rotate90(clockwise=False))
            img = img.transpose(PILImage.ROTATE_90)
        module_cache[mod.id] = img
        return img

    @staticmethod
    def _collect_leaf_instances(
        project: "Project",
        frame_id: str,
        mapping: Optional["ModuleMapping"],
        parent_a: Tuple[Tuple[float, float], Tuple[float, float]],
        parent_b: Tuple[float, float],
        parent_rot: float,
        parent_flip_x: bool,
        parent_flip_y: bool,
        out: List[
            Tuple[
                "Module",
                Tuple[Tuple[float, float], Tuple[float, float]],
                Tuple[float, float],
                float,
                bool,
                bool,
                bool,
                bool,
            ]
        ],
        depth: int,
        stack: set[str],
    ) -> None:
        """
        Flatten a frame into leaf module instances.

        Each entry is (module, matrix, anchor, rotation, flip_x, flip_y, local_flip_x, local_flip_y).
        Matches the editor canvas: a part's own flip mirrors the module image in place (about the
        texture centre, bounds unchanged), so it is *not* part of the matrix; the renderer mirrors the
        texture first. Flips of nested frames and animation steps are geometric mirrors and stay in
        the matrix.
        """
        if depth > 48:
            return
        frame = project.get_frame(frame_id)
        if not frame or frame_id in stack:
            return

        stack.add(frame_id)
        for fm in frame.fmodules:
            local_flip_x = bool(getattr(fm, "flip_x", False))
            local_flip_y = bool(getattr(fm, "flip_y", False))
            rot_a = RetroAnimatorExporter._rotation_matrix(float(getattr(fm, "rotation_degrees", 0.0)))
            if fm.ref_type == "frame":
                local_a = RetroAnimatorExporter._mat_mul(
                    rot_a, RetroAnimatorExporter._flip_matrix(local_flip_x, local_flip_y)
                )
            else:
                local_a = rot_a
            local_b = (float(fm.position[0]), float(fm.position[1]))
            a_next, b_next = RetroAnimatorExporter._compose(parent_a, parent_b, local_a, local_b)
            local_rot = float(getattr(fm, "rotation_degrees", 0.0))
            parent_flipped = bool(parent_flip_x) ^ bool(parent_flip_y)
            rot_next = float(parent_rot) + (-local_rot if parent_flipped else local_rot)
            flip_x_next = bool(parent_flip_x) ^ bool(getattr(fm, "flip_x", False))
            flip_y_next = bool(parent_flip_y) ^ bool(getattr(fm, "flip_y", False))

            if fm.ref_type == "module":
                mod = RetroAnimatorExporter._resolve_module(project, fm.ref_id, mapping)
                if mod:
                    out.append(
                        (mod, a_next, b_next, rot_next, flip_x_next, flip_y_next, local_flip_x, local_flip_y)
                    )
            elif fm.ref_type == "frame":
                RetroAnimatorExporter._collect_leaf_instances(
                    project=project,
                    frame_id=fm.ref_id,
                    mapping=mapping,
                    parent_a=a_next,
                    parent_b=b_next,
                    parent_rot=rot_next,
                    parent_flip_x=flip_x_next,
                    parent_flip_y=flip_y_next,
                    out=out,
                    depth=depth + 1,
                    stack=stack,
                )
        stack.remove(frame_id)

    @staticmethod
    def _transform_rect(
        rect: Tuple[int, int, int, int],
        a: Tuple[Tuple[float, float], Tuple[float, float]],
        b: Tuple[float, float],
    ) -> Tuple[int, int, int, int]:
        x, y, w, h = rect
        corners = (
            (float(x), float(y)),
            (float(x + w), float(y)),
            (float(x), float(y + h)),
            (float(x + w), float(y + h)),
        )
        tx = []
        ty = []
        for cx, cy in corners:
            px, py = RetroAnimatorExporter._mat_vec_mul(a, (cx, cy))
            tx.append(px + b[0])
            ty.append(py + b[1])
        min_x = int(math.floor(min(tx)))
        min_y = int(math.floor(min(ty)))
        max_x = int(math.ceil(max(tx)))
        max_y = int(math.ceil(max(ty)))
        return (min_x, min_y, max(0, max_x - min_x), max(0, max_y - min_y))

    @staticmethod
    def _render_frame_variant(
        project: "Project",
        source_frame: "Frame",
        mapping: Optional["ModuleMapping"],
        extra_a: Tuple[Tuple[float, float], Tuple[float, float]],
        extra_b: Tuple[float, float],
        full_image_cache: Dict[str, Any],
        module_cache: Dict[str, Any],
    ) -> Tuple[Any, int, int, List[Tuple[str, Tuple[int, int, int, int]]]]:
        from PIL import Image as PILImage

        instances: List[
            Tuple[
                Module,
                Tuple[Tuple[float, float], Tuple[float, float]],
                Tuple[float, float],
                float,
                bool,
                bool,
                bool,
                bool,
            ]
        ] = []
        RetroAnimatorExporter._collect_leaf_instances(
            project=project,
            frame_id=source_frame.id,
            mapping=mapping,
            parent_a=extra_a,
            parent_b=extra_b,
            parent_rot=0.0,
            parent_flip_x=False,
            parent_flip_y=False,
            out=instances,
            depth=0,
            stack=set(),
        )

        rendered: List[Tuple[Any, int, int]] = []
        global_min_x = float("inf")
        global_min_y = float("inf")
        global_max_x = float("-inf")
        global_max_y = float("-inf")

        for mod, a_mat, b_vec, rot_deg, flip_x, flip_y, local_flip_x, local_flip_y in instances:
            base = RetroAnimatorExporter._load_module_rgba(project, mod, full_image_cache, module_cache)
            base = RetroAnimatorExporter._mirror_in_place(base, local_flip_x, local_flip_y)
            w, h = base.size
            if w <= 0 or h <= 0:
                continue

            piv = (float(mod.pivot[0]), float(mod.pivot[1]))
            ap = RetroAnimatorExporter._mat_vec_mul(a_mat, piv)
            c_vec = (b_vec[0] - ap[0], b_vec[1] - ap[1])

            corners = (
                (0.0, 0.0),
                (float(w), 0.0),
                (0.0, float(h)),
                (float(w), float(h)),
            )
            xs: List[float] = []
            ys: List[float] = []
            for u, v in corners:
                tx, ty = RetroAnimatorExporter._mat_vec_mul(a_mat, (u, v))
                xs.append(tx + c_vec[0])
                ys.append(ty + c_vec[1])

            min_x = int(math.floor(min(xs)))
            min_y = int(math.floor(min(ys)))
            max_x = int(math.ceil(max(xs)))
            max_y = int(math.ceil(max(ys)))
            out_w = max_x - min_x
            out_h = max_y - min_y
            if out_w <= 0 or out_h <= 0:
                continue

            inv = RetroAnimatorExporter._invert(a_mat)
            if not inv:
                continue

            dx = float(min_x) - c_vec[0]
            dy = float(min_y) - c_vec[1]
            coeff = (
                inv[0][0],
                inv[0][1],
                inv[0][0] * dx + inv[0][1] * dy,
                inv[1][0],
                inv[1][1],
                inv[1][0] * dx + inv[1][1] * dy,
            )
            transformed = base.transform(
                (out_w, out_h),
                PILImage.AFFINE,
                coeff,
                resample=PILImage.NEAREST,
                fillcolor=(0, 0, 0, 0),
            )
            if not transformed.getbbox():
                continue

            rendered.append((transformed, min_x, min_y))
            global_min_x = min(global_min_x, min_x)
            global_min_y = min(global_min_y, min_y)
            global_max_x = max(global_max_x, max_x)
            global_max_y = max(global_max_y, max_y)

        if not rendered:
            image = PILImage.new("RGBA", (1, 1), (0, 0, 0, 0))
            return image, 0, 0, []

        handle_x = int(global_min_x)
        handle_y = int(global_min_y)
        canvas_w = int(max(1, global_max_x - global_min_x))
        canvas_h = int(max(1, global_max_y - global_min_y))
        image = PILImage.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        for sprite, sx, sy in rendered:
            image.alpha_composite(sprite, (int(sx - global_min_x), int(sy - global_min_y)))

        transformed_collisions = [
            (cr.type_id, RetroAnimatorExporter._transform_rect(cr.rect, extra_a, extra_b))
            for cr in source_frame.collision_rects
        ]
        return image, handle_x, handle_y, transformed_collisions

    @staticmethod
    def _mirror_in_place(img: Any, flip_x: bool, flip_y: bool) -> Any:
        from PIL import Image as PILImage

        if flip_x:
            img = img.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
        if flip_y:
            img = img.transpose(PILImage.Transpose.FLIP_TOP_BOTTOM)
        return img

    @staticmethod
    def _module_handle_for_rotation(
        mod: "Module",
        anchor: Tuple[float, float],
        rotation_degrees: float,
    ) -> Tuple[int, int]:
        w = int(mod.rect[2])
        h = int(mod.rect[3])
        if getattr(mod, "rotated", False):
            w, h = h, w

        piv_x = float(mod.pivot[0])
        piv_y = float(mod.pivot[1])
        corners = (
            (0.0 - piv_x, 0.0 - piv_y),
            (float(w) - piv_x, 0.0 - piv_y),
            (0.0 - piv_x, float(h) - piv_y),
            (float(w) - piv_x, float(h) - piv_y),
        )

        rad = math.radians(float(rotation_degrees))
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        xs: List[float] = []
        ys: List[float] = []
        for cx, cy in corners:
            rx = cx * cos_a - cy * sin_a
            ry = cx * sin_a + cy * cos_a
            xs.append(rx + float(anchor[0]))
            ys.append(ry + float(anchor[1]))
        return int(round(min(xs))), int(round(min(ys)))

    @staticmethod
    def _render_transformed_instance(
        project: "Project",
        mod: "Module",
        a_mat: Tuple[Tuple[float, float], Tuple[float, float]],
        b_vec: Tuple[float, float],
        rotation_degrees: float,
        flip_x: bool,
        flip_y: bool,
        full_image_cache: Dict[str, Any],
        module_cache: Dict[str, Any],
        local_flip_x: bool = False,
        local_flip_y: bool = False,
    ) -> Optional[Tuple[Any, int, int]]:
        from PIL import Image as PILImage

        base = RetroAnimatorExporter._load_module_rgba(project, mod, full_image_cache, module_cache)
        # The part's own flip is an in-place mirror of the module image (editor semantics);
        # everything else (rotation, nested/animation flips) is on the affine path below.
        base = RetroAnimatorExporter._mirror_in_place(base, local_flip_x, local_flip_y)
        w, h = base.size
        if w <= 0 or h <= 0:
            return None

        piv = (float(mod.pivot[0]), float(mod.pivot[1]))
        ap = RetroAnimatorExporter._mat_vec_mul(a_mat, piv)
        c_vec = (b_vec[0] - ap[0], b_vec[1] - ap[1])

        corners = (
            (0.0, 0.0),
            (float(w), 0.0),
            (0.0, float(h)),
            (float(w), float(h)),
        )
        xs: List[float] = []
        ys: List[float] = []
        for u, v in corners:
            tx, ty = RetroAnimatorExporter._mat_vec_mul(a_mat, (u, v))
            xs.append(tx + c_vec[0])
            ys.append(ty + c_vec[1])

        min_x = int(math.floor(min(xs)))
        min_y = int(math.floor(min(ys)))
        max_x = int(math.ceil(max(xs)))
        max_y = int(math.ceil(max(ys)))
        out_w = max_x - min_x
        out_h = max_y - min_y
        if out_w <= 0 or out_h <= 0:
            return None

        inv = RetroAnimatorExporter._invert(a_mat)
        if not inv:
            return None

        dx = float(min_x) - c_vec[0]
        dy = float(min_y) - c_vec[1]
        coeff = (
            inv[0][0],
            inv[0][1],
            inv[0][0] * dx + inv[0][1] * dy,
            inv[1][0],
            inv[1][1],
            inv[1][0] * dx + inv[1][1] * dy,
        )
        transformed = base.transform(
            (out_w, out_h),
            PILImage.AFFINE,
            coeff,
            resample=PILImage.NEAREST,
            fillcolor=(0, 0, 0, 0),
        )
        if not transformed.getbbox():
            return None

        return transformed, min_x, min_y

    @staticmethod
    def export(
        project: "Project",
        path: str,
        mapping: Optional["ModuleMapping"] = None,
    ) -> Dict[str, Any]:
        if not path.lower().endswith(".json"):
            path += ".json"

        base_dir = os.path.dirname(os.path.abspath(path))
        os.makedirs(base_dir, exist_ok=True)
        parts_dir = os.path.join(base_dir, RetroAnimatorExporter.PARTS_DIRNAME)
        os.makedirs(parts_dir, exist_ok=True)

        active_mapping = mapping
        full_image_cache: Dict[str, Any] = {}
        module_cache: Dict[str, Any] = {}
        collision_types = {ct.id: ct for ct in project.collision_types}

        used_frame_names: set[str] = set()
        used_anim_names: set[str] = set()
        used_part_file_names: set[str] = set()

        frame_payloads: Dict[str, Dict[str, Any]] = {}
        frame_name_by_id: Dict[str, str] = {}
        variant_cache: Dict[Tuple[Any, ...], str] = {}
        part_hash_to_filename: Dict[str, str] = {}
        part_filename_to_size: Dict[str, Tuple[int, int]] = {}
        written_parts = 0

        def get_or_write_part_filename(part_img: Any, preferred_base: str) -> str:
            nonlocal written_parts
            part_bytes = part_img.tobytes()
            digest = hashlib.sha1(part_bytes).hexdigest()
            if digest in part_hash_to_filename:
                filename = part_hash_to_filename[digest]
                part_filename_to_size.setdefault(
                    filename, (int(getattr(part_img, "width", 0)), int(getattr(part_img, "height", 0)))
                )
                return filename

            part_base = RetroAnimatorExporter._make_unique_name(
                RetroAnimatorExporter._sanitize_name(preferred_base, fallback=f"part_{len(part_hash_to_filename) + 1}"),
                used_part_file_names,
            )
            filename = f"{part_base}.png"
            part_abs_path = os.path.join(parts_dir, filename)
            part_img.save(part_abs_path, format="PNG")
            part_hash_to_filename[digest] = filename
            part_filename_to_size[filename] = (
                int(getattr(part_img, "width", 0)),
                int(getattr(part_img, "height", 0)),
            )
            written_parts += 1
            return filename

        def get_part_size_from_frame_path(frame_path: str) -> Tuple[int, int]:
            normalized = str(frame_path or "").replace("\\", "/")
            filename = normalized.split("/")[-1] if normalized else ""
            if not filename:
                return (0, 0)

            if filename in part_filename_to_size:
                return part_filename_to_size[filename]

            part_abs_path = os.path.join(parts_dir, filename)
            if os.path.exists(part_abs_path):
                try:
                    from PIL import Image as PILImage
                    with PILImage.open(part_abs_path) as img:
                        size = (int(img.width), int(img.height))
                    part_filename_to_size[filename] = size
                    return size
                except Exception:
                    pass
            return (0, 0)

        def write_simple_aframe_variant(
            source_frame: Frame,
            variant_key: Tuple[Any, ...],
            desired_frame_name: str,
            off: Tuple[int, int],
            flip_x: bool,
            flip_y: bool,
            rot: float,
        ) -> Optional[str]:
            if variant_key in variant_cache:
                return variant_cache[variant_key]

            rot_norm = float(rot) % 360.0
            rot_int = int(round(rot_norm)) % 360
            is_orthogonal = abs(rot_norm - float(rot_int)) < 1e-5 and rot_int in (0, 90, 180, 270)
            if not is_orthogonal:
                return None

            base_frame_name = frame_name_by_id.get(source_frame.id)
            if not base_frame_name:
                return None
            base_payload = frame_payloads.get(base_frame_name)
            if not isinstance(base_payload, dict):
                return None

            base_sprites = base_payload.get("Sprites", [])
            if not isinstance(base_sprites, list):
                return None

            dx = int(off[0])
            dy = int(off[1])

            def transform_point(px: float, py: float) -> Tuple[float, float]:
                fx = -px if flip_x else px
                fy = -py if flip_y else py
                if rot_int == 90:
                    return (-fy, fx)
                if rot_int == 180:
                    return (-fx, -fy)
                if rot_int == 270:
                    return (fy, -fx)
                return (fx, fy)

            def load_part_image_from_frame_path(frame_path: str) -> Optional[Any]:
                filename = str(frame_path or "").replace("\\", "/").split("/")[-1]
                if not filename:
                    return None
                abs_path = os.path.join(parts_dir, filename)
                if not os.path.exists(abs_path):
                    return None
                try:
                    from PIL import Image as PILImage
                    return PILImage.open(abs_path).convert("RGBA")
                except Exception:
                    return None

            sprites_json: List[Dict[str, Any]] = []
            for sprite in base_sprites:
                if not isinstance(sprite, dict):
                    continue
                out_sprite = dict(sprite)
                handle_x = int(out_sprite.get("HandleX", 0))
                handle_y = int(out_sprite.get("HandleY", 0))
                x_flipped = bool(out_sprite.get("XFlip", False))
                frame_path = str(out_sprite.get("FramePath", ""))
                width, height = get_part_size_from_frame_path(frame_path)

                # Fast path: preserve existing metadata-only behavior for X-only flip + translation.
                if rot_int == 0 and not flip_y:
                    if flip_x:
                        handle_x = -handle_x - int(width)
                        x_flipped = not x_flipped
                    out_sprite["HandleX"] = int(handle_x + dx)
                    out_sprite["HandleY"] = int(handle_y + dy)
                    out_sprite["XFlip"] = bool(x_flipped)
                    sprites_json.append(out_sprite)
                    continue

                # General orthogonal path: bake aframe transform into the part image, recompute handle
                # from transformed sprite bounds in frame-space.
                base_part = load_part_image_from_frame_path(frame_path)
                if base_part is None:
                    continue
                if x_flipped:
                    from PIL import Image as PILImage
                    base_part = base_part.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)

                transformed_part = base_part
                from PIL import Image as PILImage
                if flip_x:
                    transformed_part = transformed_part.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
                if flip_y:
                    transformed_part = transformed_part.transpose(PILImage.Transpose.FLIP_TOP_BOTTOM)
                if rot_int == 90:
                    transformed_part = transformed_part.transpose(PILImage.Transpose.ROTATE_270)  # clockwise
                elif rot_int == 180:
                    transformed_part = transformed_part.transpose(PILImage.Transpose.ROTATE_180)
                elif rot_int == 270:
                    transformed_part = transformed_part.transpose(PILImage.Transpose.ROTATE_90)   # counter-clockwise

                part_filename = get_or_write_part_filename(
                    transformed_part,
                    preferred_base=os.path.splitext(os.path.basename(frame_path.replace("\\", "/")))[0] or "part",
                )

                corners = (
                    (float(handle_x), float(handle_y)),
                    (float(handle_x + width), float(handle_y)),
                    (float(handle_x), float(handle_y + height)),
                    (float(handle_x + width), float(handle_y + height)),
                )
                tx: List[float] = []
                ty: List[float] = []
                for cx, cy in corners:
                    px, py = transform_point(cx, cy)
                    tx.append(px)
                    ty.append(py)

                out_sprite["FramePath"] = f"{RetroAnimatorExporter.PARTS_DIRNAME}\\{part_filename}"
                out_sprite["HandleX"] = int(round(min(tx))) + dx
                out_sprite["HandleY"] = int(round(min(ty))) + dy
                out_sprite["XFlip"] = False
                sprites_json.append(out_sprite)

            base_colrects = base_payload.get("ColRects", {})
            col_rects_json: Dict[str, Dict[str, Any]] = {}
            if isinstance(base_colrects, dict):
                for key, rect_data in base_colrects.items():
                    if not isinstance(rect_data, dict):
                        continue
                    out_rect = dict(rect_data)
                    x = int(out_rect.get("X", 0))
                    y = int(out_rect.get("Y", 0))
                    w = int(out_rect.get("Width", 0))
                    h = int(out_rect.get("Height", 0))

                    corners = (
                        (float(x), float(y)),
                        (float(x + w), float(y)),
                        (float(x), float(y + h)),
                        (float(x + w), float(y + h)),
                    )
                    tx: List[float] = []
                    ty: List[float] = []
                    for cx, cy in corners:
                        px, py = transform_point(cx, cy)
                        tx.append(px + dx)
                        ty.append(py + dy)

                    min_x = int(math.floor(min(tx)))
                    min_y = int(math.floor(min(ty)))
                    max_x = int(math.ceil(max(tx)))
                    max_y = int(math.ceil(max(ty)))

                    out_rect["X"] = int(min_x)
                    out_rect["Y"] = int(min_y)
                    out_rect["Width"] = int(max(0, max_x - min_x))
                    out_rect["Height"] = int(max(0, max_y - min_y))
                    col_rects_json[str(key)] = out_rect

            frame_name = RetroAnimatorExporter._make_unique_name(
                RetroAnimatorExporter._sanitize_name(desired_frame_name, fallback=source_frame.id),
                used_frame_names,
            )
            frame_payloads[frame_name] = {
                "Sprites": sprites_json,
                "ColRects": col_rects_json,
                "Properties": dict(base_payload.get("Properties", {}))
                if isinstance(base_payload.get("Properties", {}), dict)
                else {},
            }
            variant_cache[variant_key] = frame_name
            return frame_name

        def write_variant(
            source_frame: Frame,
            variant_key: Tuple[Any, ...],
            desired_frame_name: str,
            extra_transform: Tuple[Tuple[Tuple[float, float], Tuple[float, float]], Tuple[float, float]],
            root_rot: float = 0.0,
            root_flip_x: bool = False,
            root_flip_y: bool = False,
        ) -> str:
            if variant_key in variant_cache:
                return variant_cache[variant_key]

            frame_name = RetroAnimatorExporter._make_unique_name(
                RetroAnimatorExporter._sanitize_name(desired_frame_name, fallback=source_frame.id),
                used_frame_names,
            )
            instances: List[
                Tuple[
                    Module,
                    Tuple[Tuple[float, float], Tuple[float, float]],
                    Tuple[float, float],
                    float,
                    bool,
                    bool,
                    bool,
                    bool,
                ]
            ] = []
            RetroAnimatorExporter._collect_leaf_instances(
                project=project,
                frame_id=source_frame.id,
                mapping=active_mapping,
                parent_a=extra_transform[0],
                parent_b=extra_transform[1],
                parent_rot=float(root_rot),
                parent_flip_x=bool(root_flip_x),
                parent_flip_y=bool(root_flip_y),
                out=instances,
                depth=0,
                stack=set(),
            )

            sprites_json: List[Dict[str, Any]] = []
            for idx, (mod, a_mat, b_vec, rot_deg, flip_x, flip_y, local_flip_x, local_flip_y) in enumerate(instances):
                rendered = RetroAnimatorExporter._render_transformed_instance(
                    project=project,
                    mod=mod,
                    a_mat=a_mat,
                    b_vec=b_vec,
                    rotation_degrees=rot_deg,
                    flip_x=flip_x,
                    flip_y=flip_y,
                    full_image_cache=full_image_cache,
                    module_cache=module_cache,
                    local_flip_x=local_flip_x,
                    local_flip_y=local_flip_y,
                )
                if not rendered:
                    continue
                part_img, handle_x, handle_y = rendered
                part_filename = get_or_write_part_filename(part_img, preferred_base=mod.name or f"part_{idx + 1}")
                sprites_json.append(
                    {
                        "FramePath": f"{RetroAnimatorExporter.PARTS_DIRNAME}\\{part_filename}",
                        "HandleX": int(handle_x),
                        "HandleY": int(handle_y),
                        "XFlip": False,
                        "NoFlip": False,
                        "RenderMode": 0,
                        "Properties": {},
                    }
                )

            col_rects_json: Dict[str, Dict[str, Any]] = {}
            col_name_counts: Dict[str, int] = {}
            transformed_colrects = [
                (cr.type_id, RetroAnimatorExporter._transform_rect(cr.rect, extra_transform[0], extra_transform[1]))
                for cr in source_frame.collision_rects
            ]
            for type_id, rect in transformed_colrects:
                ct = collision_types.get(type_id)
                base_name = (ct.name if ct else type_id) or "colrect"
                count = col_name_counts.get(base_name, 0) + 1
                col_name_counts[base_name] = count
                key = base_name if count == 1 else f"{base_name} {count}"
                color = ct.color if ct else (255, 0, 0)
                col_rects_json[key] = {
                    "Value": 0,
                    "X": int(rect[0]),
                    "Y": int(rect[1]),
                    "Width": int(rect[2]),
                    "Height": int(rect[3]),
                    "ColorR": int(color[0]),
                    "ColorG": int(color[1]),
                    "ColorB": int(color[2]),
                    "Properties": {},
                }

            frame_payloads[frame_name] = {
                "Sprites": sprites_json,
                "ColRects": col_rects_json,
                "Properties": {},
            }

            variant_cache[variant_key] = frame_name
            return frame_name

        identity_transform = (RetroAnimatorExporter._identity_matrix(), RetroAnimatorExporter._identity_offset())
        mapping_key = active_mapping.id if active_mapping else None

        # Export all base frames.
        for frame in project.frames:
            base_name = frame.name or frame.id
            key = ("base", frame.id, mapping_key)
            out_name = write_variant(frame, key, base_name, identity_transform)
            frame_name_by_id[frame.id] = out_name

        animations_json: Dict[str, Dict[str, Any]] = {}
        for anim in project.animations:
            anim_name = RetroAnimatorExporter._make_unique_name(
                RetroAnimatorExporter._sanitize_name(anim.name, fallback=anim.id),
                used_anim_names,
            )
            frame_data: List[Dict[str, Any]] = []
            source_fps = anim.fps if anim.fps > 0 else 10

            for idx, af in enumerate(anim.aframes):
                source_frame = project.get_frame(af.frame_id)
                if not source_frame:
                    continue

                rot = float(getattr(af, "rotation_degrees", 0.0))
                rot = round(rot, 4)
                flip_x = bool(getattr(af, "flip_x", False))
                flip_y = bool(getattr(af, "flip_y", False))
                off = (int(af.offset[0]), int(af.offset[1]))
                is_identity = (off == (0, 0) and not flip_x and not flip_y and abs(rot) < 1e-9)

                if is_identity:
                    out_frame_name = frame_name_by_id.get(source_frame.id)
                    if not out_frame_name:
                        out_frame_name = write_variant(
                            source_frame,
                            ("base", source_frame.id, mapping_key),
                            source_frame.name or source_frame.id,
                            identity_transform,
                        )
                else:
                    variant_key = ("aframe", source_frame.id, off, flip_x, flip_y, rot, mapping_key)
                    local_a = RetroAnimatorExporter._mat_mul(
                        RetroAnimatorExporter._rotation_matrix(rot),
                        RetroAnimatorExporter._flip_matrix(flip_x, flip_y),
                    )
                    local_b = (float(off[0]), float(off[1]))
                    desired = f"{source_frame.name or source_frame.id} {anim_name} {idx + 1}"
                    out_frame_name = write_simple_aframe_variant(
                        source_frame,
                        variant_key,
                        desired,
                        off,
                        flip_x,
                        flip_y,
                        rot,
                    )
                    if not out_frame_name:
                        out_frame_name = write_variant(
                            source_frame,
                            variant_key,
                            desired,
                            (local_a, local_b),
                            root_rot=rot,
                            root_flip_x=flip_x,
                            root_flip_y=flip_y,
                        )

                ticks = max(
                    1,
                    int(round((float(af.duration_frames) / float(source_fps)) * RetroAnimatorExporter.RETRO_TICKS_PER_SECOND)),
                )
                frame_data.append(
                    {
                        "FrameID": out_frame_name,
                        "Duration": ticks,
                        "Properties": {},
                    }
                )

            animations_json[anim_name] = {
                "FrameData": frame_data,
                "Properties": {
                    "source_playback_type": str(anim.playback_type),
                    "source_loop_count": str(anim.loop_count if anim.loop_count is not None else 0),
                    "source_fps": str(source_fps),
                },
            }

        losses: List[str] = []
        losses.append("Module mappings are not part of RetroAnimator. The selected active mapping is baked into exported frames.")
        losses.append("Animation playback type/loop semantics are not native in RetroAnimator; only frame sequence + duration are exported.")
        if any(frame.control_points for frame in project.frames):
            losses.append("Control points are not supported in RetroAnimator and are omitted.")
        if any(
            fm.ref_type == "frame" or abs(float(getattr(fm, "rotation_degrees", 0.0))) > 1e-9 or bool(getattr(fm, "flip_y", False))
            for frame in project.frames
            for fm in frame.fmodules
        ):
            losses.append("Nested frames, Y-flips, and rotations are baked into raster frame parts.")
        if any(af.offset != (0, 0) or af.flip_x or af.flip_y or abs(float(getattr(af, "rotation_degrees", 0.0))) > 1e-9
               for anim in project.animations for af in anim.aframes):
            losses.append("Per-animation frame offsets/flips/rotations are baked into generated frame variants.")
        if any(mod.type != "MD_IMAGE" for mod in project.modules):
            losses.append("Procedural shape modules are rasterized during export.")

        data = {
            "ProjectType": "RetroAnimator",
            "Animations": animations_json,
            "Frames": frame_payloads,
            "Properties": {
                "source_project_name": project.name,
            },
        }
        if active_mapping:
            data["Properties"]["active_mapping_name"] = active_mapping.name
            data["Properties"]["active_mapping_id"] = active_mapping.id

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return {
            "path": os.path.abspath(path),
            "parts_dir": os.path.abspath(parts_dir),
            "frames_exported": len(frame_payloads),
            "animations_exported": len(animations_json),
            "parts_written": written_parts,
            "mapping_baked": bool(active_mapping),
            "losses": losses,
        }


@dataclass
class Project:
    name: str = "New Project"
    images: List[ImageAsset] = field(default_factory=list)
    modules: List[Module] = field(default_factory=list)
    frames: List[Frame] = field(default_factory=list)
    animations: List[Animation] = field(default_factory=list)
    timeline_scenes: List[TimelineScene] = field(default_factory=list)
    mappings: List[ModuleMapping] = field(default_factory=list)
    collision_types: List[CollisionType] = field(default_factory=list)
    point_types: List[PointType] = field(default_factory=list)
    event_types: List[EventType] = field(default_factory=list)

    # Runtime state (not serialized)
    active_mapping: Optional[ModuleMapping] = field(default=None, init=False)
    load_notes: List[str] = field(default_factory=list, init=False)

    def get_image(self, image_id: str) -> Optional[ImageAsset]:
        return next((img for img in self.images if img.id == image_id), None)

    def get_module(self, module_id: str) -> Optional[Module]:
        return next((m for m in self.modules if m.id == module_id), None)

    def get_frame(self, frame_id: str) -> Optional[Frame]:
        return next((f for f in self.frames if f.id == frame_id), None)

    def get_animation(self, animation_id: str) -> Optional[Animation]:
        return next((a for a in self.animations if a.id == animation_id), None)

    def get_mapping(self, mapping_id: str) -> Optional[ModuleMapping]:
        return next((m for m in self.mappings if m.id == mapping_id), None)

    def get_event_type(self, type_id: str) -> Optional[EventType]:
        return next((t for t in self.event_types if t.id == type_id), None)

    def get_timeline_scene(self, scene_id: str) -> Optional[TimelineScene]:
        return next((scene for scene in self.timeline_scenes if scene.id == scene_id), None)

    def frame_has_cycle(self, frame_id: str, new_child_id: Optional[str] = None) -> bool:
        """Checks if a cycle exists (or would exist if new_child_id is added to frame_id)."""
        visited = set()
        def visit(fid: str, stack: List[str]) -> bool:
            if fid in stack:
                return True
            frame = self.get_frame(fid)
            if not frame:
                return False
            
            stack.append(fid)
            
            # Existing children
            for fm in frame.fmodules:
                if fm.ref_type == "frame" and visit(fm.ref_id, stack):
                    return True
            
            # Proposed new child (only for the root frame_id we are checking)
            if new_child_id and fid == frame_id:
                if visit(new_child_id, stack):
                    return True
                    
            stack.pop()
            visited.add(fid)
            return False
        return visit(frame_id, [])

    def create_image(self, file_path: str, width: int, height: int, transparent_color: Optional[Tuple[int, int, int]] = None) -> ImageAsset:
        asset = ImageAsset(
            id=generate_id("img"),
            file_path=file_path,
            width=width,
            height=height,
            transparent_color=transparent_color
        )
        self.images.append(asset)
        return asset

    def create_module(self, name: str, image_id: str, rect: Tuple[int, int, int, int], pivot: Tuple[int, int]) -> Module:
        mod = Module(
            id=generate_id("mod"),
            name=name,
            image_id=image_id,
            rect=rect,
            pivot=pivot
        )
        self.modules.append(mod)
        return mod

    def create_frame(self, name: str) -> Frame:
        frame = Frame(
            id=generate_id("frm"),
            name=name
        )
        self.frames.append(frame)
        return frame

    def create_animation(self, name: str) -> Animation:
        anim = Animation(
            id=generate_id("anim"),
            name=name
        )
        self.animations.append(anim)
        return anim

    def create_timeline_scene(self, name: str) -> TimelineScene:
        scene = TimelineScene(
            id=generate_id("scene"),
            name=name,
        )
        self.timeline_scenes.append(scene)
        return scene

    def sample_animation_frame(
        self,
        animation_id: str,
        time_frames: float,
        playback_override: Optional[str] = None,
    ) -> Optional[Tuple[AFrame, int]]:
        anim = self.get_animation(animation_id)
        if not anim or not anim.aframes:
            return None

        durations = [max(1.0, float(af.duration_frames)) for af in anim.aframes]
        total = sum(durations)
        if total <= 0.0:
            return (anim.aframes[0], 0)

        playback = str(playback_override or anim.playback_type or "loop").strip().lower()
        local_time = float(time_frames)
        if playback == "once" or playback == "forward":
            local_time = max(0.0, min(local_time, total - 1e-6))
        elif playback == "backward":
            local_time = total - max(0.0, min(local_time, total - 1e-6)) - 1e-6
        elif playback == "ping_pong":
            if len(anim.aframes) == 1:
                local_time = 0.0
            else:
                cycle = total * 2.0
                local_time = local_time % cycle if cycle > 0.0 else 0.0
                if local_time >= total:
                    local_time = total - (local_time - total) - 1e-6
        else:
            # Loop: the first pass plays every step, later passes start at loop_start.
            intro = sum(durations[: max(0, min(int(anim.loop_start or 0), len(durations) - 1))])
            if local_time >= total and 0.0 < intro < total:
                local_time = intro + (local_time - total) % (total - intro)
            else:
                local_time = local_time % total if total > 0.0 else 0.0

        cursor = 0.0
        for idx, af in enumerate(anim.aframes):
            dur = durations[idx]
            if local_time < cursor + dur or idx == len(anim.aframes) - 1:
                return (af, idx)
            cursor += dur
        return (anim.aframes[-1], len(anim.aframes) - 1)

    def ensure_default_collision_type(self) -> CollisionType:
        """Ensure at least one collision type exists and return it."""
        if self.collision_types:
            return self.collision_types[0]

        default_type = CollisionType(
            id=generate_id("ctype"),
            name="Default",
            color=(255, 0, 0),
        )
        self.collision_types.append(default_type)
        return default_type

    def ensure_default_point_type(self) -> PointType:
        """Ensure at least one control-point type exists and return it."""
        if self.point_types:
            return self.point_types[0]

        default_type = PointType(
            id=generate_id("ptype"),
            name="Default",
            color=(0, 255, 0),
        )
        self.point_types.append(default_type)
        return default_type

    def remove_collision_type(self, type_id: str) -> int:
        """
        Remove a collision type and all frame collision rects using it.
        Returns the number of removed collision rects.
        """
        self.collision_types = [ct for ct in self.collision_types if ct.id != type_id]

        removed = 0
        for frame in self.frames:
            before = len(frame.collision_rects)
            frame.collision_rects = [cr for cr in frame.collision_rects if cr.type_id != type_id]
            removed += before - len(frame.collision_rects)
        return removed

    def remove_point_type(self, type_id: str) -> int:
        """
        Remove a point type and all frame control points using it.
        Returns the number of removed control points.
        """
        self.point_types = [pt for pt in self.point_types if pt.id != type_id]

        removed = 0
        for frame in self.frames:
            before = len(frame.control_points)
            frame.control_points = [cp for cp in frame.control_points if cp.type_id != type_id]
            removed += before - len(frame.control_points)
        return removed

    @staticmethod
    def _norm_role(value: Optional[str]) -> str:
        return str(value or "").strip().lower()

    def compile_animation_role_tables(self, animation_id: str) -> Optional[Dict[str, Any]]:
        """
        Build dense per-frame lookup tables for semantic `type + role` identities.

        Output tables contain control-point/collision indices into each frame list, or -1 when absent.
        """
        anim = self.get_animation(animation_id)
        if not anim:
            return None

        point_roles: List[Tuple[str, str]] = []
        collision_roles: List[Tuple[str, str]] = []
        point_seen: set[Tuple[str, str]] = set()
        collision_seen: set[Tuple[str, str]] = set()
        point_idx_norm: Dict[Tuple[str, str], int] = {}
        collision_idx_norm: Dict[Tuple[str, str], int] = {}

        for af in anim.aframes:
            frame = self.get_frame(af.frame_id)
            if not frame:
                continue
            for cp in frame.control_points:
                role_raw = str(getattr(cp, "role", "") or "").strip()
                role_norm = self._norm_role(role_raw)
                if not role_norm:
                    continue
                key_norm = (cp.type_id, role_norm)
                if key_norm not in point_seen:
                    point_seen.add(key_norm)
                    point_idx_norm[key_norm] = len(point_roles)
                    point_roles.append((cp.type_id, role_raw))
            for cr in frame.collision_rects:
                role_raw = str(getattr(cr, "role", "") or "").strip()
                role_norm = self._norm_role(role_raw)
                if not role_norm:
                    continue
                key_norm = (cr.type_id, role_norm)
                if key_norm not in collision_seen:
                    collision_seen.add(key_norm)
                    collision_idx_norm[key_norm] = len(collision_roles)
                    collision_roles.append((cr.type_id, role_raw))

        point_table: List[List[int]] = []
        collision_table: List[List[int]] = []
        frame_ids: List[str] = []

        for af in anim.aframes:
            frame_ids.append(af.frame_id)
            point_row = [-1] * len(point_roles)
            collision_row = [-1] * len(collision_roles)

            frame = self.get_frame(af.frame_id)
            if frame:
                for i, cp in enumerate(frame.control_points):
                    role_norm = self._norm_role(str(getattr(cp, "role", "") or ""))
                    if not role_norm:
                        continue
                    col = point_idx_norm.get((cp.type_id, role_norm))
                    if col is not None and point_row[col] == -1:
                        point_row[col] = i
                for i, cr in enumerate(frame.collision_rects):
                    role_norm = self._norm_role(str(getattr(cr, "role", "") or ""))
                    if not role_norm:
                        continue
                    col = collision_idx_norm.get((cr.type_id, role_norm))
                    if col is not None and collision_row[col] == -1:
                        collision_row[col] = i

            point_table.append(point_row)
            collision_table.append(collision_row)

        return {
            "animation_id": anim.id,
            "animation_name": anim.name,
            "frame_ids": frame_ids,
            "point_roles": [{"type_id": t, "role": r} for t, r in point_roles],
            "collision_roles": [{"type_id": t, "role": r} for t, r in collision_roles],
            "point_table": point_table,
            "collision_table": collision_table,
        }

    def validate_role_uniqueness(self, frame_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Validate that each frame has at most one item per `(type_id, role)` key.

        Empty roles are ignored.
        """
        frames_to_check: List[Frame]
        if frame_ids is None:
            frames_to_check = list(self.frames)
        else:
            wanted = set(frame_ids)
            frames_to_check = [f for f in self.frames if f.id in wanted]

        issues: List[Dict[str, Any]] = []
        for frame in frames_to_check:
            point_buckets: Dict[Tuple[str, str], List[str]] = {}
            for cp in frame.control_points:
                role_raw = str(getattr(cp, "role", "") or "").strip()
                role_norm = self._norm_role(role_raw)
                if not role_norm:
                    continue
                point_buckets.setdefault((cp.type_id, role_norm), []).append(cp.id)

            for (type_id, role_norm), ids in point_buckets.items():
                if len(ids) <= 1:
                    continue
                issues.append(
                    {
                        "frame_id": frame.id,
                        "frame_name": frame.name,
                        "kind": "point",
                        "type_id": type_id,
                        "role": role_norm,
                        "item_ids": ids,
                    }
                )

            collision_buckets: Dict[Tuple[str, str], List[str]] = {}
            for cr in frame.collision_rects:
                role_raw = str(getattr(cr, "role", "") or "").strip()
                role_norm = self._norm_role(role_raw)
                if not role_norm:
                    continue
                collision_buckets.setdefault((cr.type_id, role_norm), []).append(cr.id)

            for (type_id, role_norm), ids in collision_buckets.items():
                if len(ids) <= 1:
                    continue
                issues.append(
                    {
                        "frame_id": frame.id,
                        "frame_name": frame.name,
                        "kind": "collision",
                        "type_id": type_id,
                        "role": role_norm,
                        "item_ids": ids,
                    }
                )

        return issues


    def to_dict(self, base_path: Optional[str] = None) -> Dict:
        # Helper to relativize paths if base_path is provided
        def get_img_dict(img: ImageAsset) -> Dict:
            d = img.to_dict()
            if base_path and os.path.isabs(img.file_path):
                try:
                    rel = os.path.relpath(img.file_path, base_path)
                    if not rel.startswith(".."): # Only use relative if it's within/nearby? User asked for relative.
                        d["file_path"] = rel
                    else:
                        # Even if it's outside, relative path is valid and requested by user to move folder structures together.
                        d["file_path"] = rel
                except ValueError:
                    # Windows checking for different drives, etc.
                    pass
            return d

        return {
            "format_version": PROJECT_FORMAT_VERSION,
            "name": self.name,
            "images": [get_img_dict(img) for img in self.images],
            "modules": [m.to_dict() for m in self.modules],
            "frames": [f.to_dict() for f in self.frames],
            "animations": [a.to_dict() for a in self.animations],
            "timeline_scenes": [scene.to_dict() for scene in self.timeline_scenes],
            "mappings": [m.to_dict() for m in self.mappings],
            "collision_types": [ct.to_dict() for ct in self.collision_types],
            "point_types": [pt.to_dict() for pt in self.point_types],
            "event_types": [et.to_dict() for et in self.event_types],
        }

    def to_json(self, path: str) -> None:
        base_path = os.path.dirname(os.path.abspath(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(base_path=base_path), f, indent=2)

    def to_retro_animator_json(self, path: str, mapping: Optional[ModuleMapping] = None) -> Dict[str, Any]:
        return RetroAnimatorExporter.export(self, path=path, mapping=mapping)

    @staticmethod
    def from_dict(data: Dict, base_path: Optional[str] = None) -> "Project":
        data, notes = migrate_project_dict(data)

        # Helper to resolve paths
        def resolve_img(d: Dict) -> ImageAsset:
            img = ImageAsset.from_dict(d)
            if base_path and not os.path.isabs(img.file_path):
                img.file_path = os.path.abspath(os.path.join(base_path, img.file_path))
            return img

        images = [resolve_img(img) for img in data.get("images", [])]
        modules = [Module.from_dict(m) for m in data.get("modules", [])]
        frames = [Frame.from_dict(f) for f in data.get("frames", [])]
        animations = [Animation.from_dict(a) for a in data.get("animations", [])]
        timeline_scenes = [TimelineScene.from_dict(scene) for scene in data.get("timeline_scenes", [])]
        mappings = [ModuleMapping.from_dict(m) for m in data.get("mappings", [])]
        collision_types = [CollisionType.from_dict(ct) for ct in data.get("collision_types", [])]
        point_types = [PointType.from_dict(pt) for pt in data.get("point_types", [])]
        event_types = [EventType.from_dict(et) for et in data.get("event_types", [])]

        project = Project(
            name=data.get("name", "New Project"),
            images=images,
            modules=modules,
            frames=frames,
            animations=animations,
            timeline_scenes=timeline_scenes,
            mappings=mappings,
            collision_types=collision_types,
            point_types=point_types,
            event_types=event_types,
        )
        project.load_notes = notes
        return project

    @staticmethod
    def from_json(path: str) -> "Project":
        if path.endswith(".sprite"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return AuroraSpriteParser.parse(content, os.path.dirname(path))

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            project_type = str(data.get("ProjectType", "")).strip().lower()
            if project_type == "retroanimator":
                base_path = os.path.dirname(os.path.abspath(path))
                project_name = os.path.splitext(os.path.basename(path))[0]
                return RetroAnimatorParser.parse(data, base_path=base_path, project_name=project_name)

        return Project.from_dict(data, base_path=os.path.dirname(os.path.abspath(path)))

    @staticmethod
    def from_retro_animator_json(path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict) or str(data.get("ProjectType", "")).strip().lower() != "retroanimator":
            raise ValueError("Selected file is not a RetroAnimator project JSON.")

        base_path = os.path.dirname(os.path.abspath(path))
        project_name = os.path.splitext(os.path.basename(path))[0]
        return RetroAnimatorParser.parse(data, base_path=base_path, project_name=project_name)
