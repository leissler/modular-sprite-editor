"""The sprite data: images, modules, frames (parts, hitboxes, points), animations, mappings and the types of
hitboxes, points and step events, with their JSON (to_dict / from_dict)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"  # 64 random bits: no clash among a project's thousands of parts


@dataclass
class ImageAsset:
    id: str
    file_path: str
    width: int
    height: int
    transparent_color: Optional[Tuple[int, int, int]] = None
    palette: int = 0  # Mega Drive palette (0-3) its colours go into, see palettes.py

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "width": self.width,
            "height": self.height,
            "transparent_color": list(self.transparent_color) if self.transparent_color else None,
            "palette": self.palette,
        }

    @staticmethod
    def from_dict(data: Dict) -> "ImageAsset":
        palette = data.get("palette", 0)
        return ImageAsset(
            id=data["id"],
            file_path=data["file_path"],
            width=int(data["width"]),
            height=int(data["height"]),
            transparent_color=tuple(data["transparent_color"]) if data.get("transparent_color") else None,  # type: ignore[arg-type]
            palette=int(palette) if isinstance(palette, int) and 0 <= palette <= 3 else 0,
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
