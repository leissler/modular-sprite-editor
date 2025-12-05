"""Data models and JSON serialization for the sprite editor."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


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

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "image_id": self.image_id,
            "rect": list(self.rect),
            "pivot": list(self.pivot),
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
    z_order: int = 0

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "position": list(self.position),
            "flip_x": self.flip_x,
            "flip_y": self.flip_y,
            "rotation_degrees": self.rotation_degrees,
            "z_order": self.z_order,
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
            z_order=int(data.get("z_order", 0)),
        )


@dataclass
class CollisionRect:
    name: str
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }

    @staticmethod
    def from_dict(data: Dict) -> "CollisionRect":
        return CollisionRect(
            name=data.get("name", ""),
            x=int(data["x"]),
            y=int(data["y"]),
            width=int(data["width"]),
            height=int(data["height"]),
        )


@dataclass
class ControlPoint:
    name: str
    x: int
    y: int

    def to_dict(self) -> Dict:
        return {"name": self.name, "x": self.x, "y": self.y}

    @staticmethod
    def from_dict(data: Dict) -> "ControlPoint":
        return ControlPoint(name=data["name"], x=int(data["x"]), y=int(data["y"]))


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

    @staticmethod
    def from_dict(data: Dict) -> "Frame":
        return Frame(
            id=data["id"],
            name=data["name"],
            fmodules=[FModule.from_dict(fm) for fm in data.get("fmodules", [])],
            collision_rects=[
                CollisionRect.from_dict(cr) for cr in data.get("collision_rects", [])
            ],
            control_points=[
                ControlPoint.from_dict(cp) for cp in data.get("control_points", [])
            ],
        )


@dataclass
class AFrame:
    frame_id: str
    duration_ms: int
    offset: Tuple[int, int] = (0, 0)

    def to_dict(self) -> Dict:
        return {
            "frame_id": self.frame_id,
            "duration_ms": self.duration_ms,
            "offset": list(self.offset),
        }

    @staticmethod
    def from_dict(data: Dict) -> "AFrame":
        return AFrame(
            frame_id=data["frame_id"],
            duration_ms=int(data["duration_ms"]),
            offset=tuple(int(v) for v in data.get("offset", (0, 0))),  # type: ignore[arg-type]
        )


@dataclass
class Animation:
    id: str
    name: str
    playback_type: str
    loop_count: Optional[int]
    aframes: List[AFrame] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "playback_type": self.playback_type,
            "loop_count": self.loop_count,
            "aframes": [af.to_dict() for af in self.aframes],
        }

    @staticmethod
    def from_dict(data: Dict) -> "Animation":
        return Animation(
            id=data["id"],
            name=data["name"],
            playback_type=data["playback_type"],
            loop_count=data.get("loop_count"),
            aframes=[AFrame.from_dict(af) for af in data.get("aframes", [])],
        )


class Project:
    def __init__(self) -> None:
        self.images: List[ImageAsset] = []
        self.modules: List[Module] = []
        self.frames: List[Frame] = []
        self.animations: List[Animation] = []

    # Lookup helpers
    def get_image(self, image_id: str) -> Optional[ImageAsset]:
        return next((img for img in self.images if img.id == image_id), None)

    def get_module(self, module_id: str) -> Optional[Module]:
        return next((m for m in self.modules if m.id == module_id), None)

    def get_frame(self, frame_id: str) -> Optional[Frame]:
        return next((f for f in self.frames if f.id == frame_id), None)

    def get_animation(self, animation_id: str) -> Optional[Animation]:
        return next((a for a in self.animations if a.id == animation_id), None)

    # Persistence
    def to_dict(self) -> Dict:
        return {
            "images": [img.to_dict() for img in self.images],
            "modules": [m.to_dict() for m in self.modules],
            "frames": [f.to_dict() for f in self.frames],
            "animations": [a.to_dict() for a in self.animations],
        }

    def to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def from_dict(data: Dict) -> "Project":
        project = Project()
        project.images = [ImageAsset.from_dict(img) for img in data.get("images", [])]
        project.modules = [Module.from_dict(m) for m in data.get("modules", [])]
        project.frames = [Frame.from_dict(fr) for fr in data.get("frames", [])]
        project.animations = [Animation.from_dict(a) for a in data.get("animations", [])]
        return project

    @staticmethod
    def from_json(path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Project.from_dict(data)

    # Cycle detection for frames that nest frames
    def frame_has_cycle(self, frame_id: str) -> bool:
        visited = set()

        def visit(fid: str, stack: List[str]) -> bool:
            if fid in stack:
                return True
            frame = self.get_frame(fid)
            if not frame:
                return False
            stack.append(fid)
            for fm in frame.fmodules:
                if fm.ref_type == "frame" and visit(fm.ref_id, stack):
                    return True
            stack.pop()
            visited.add(fid)
            return False

        return visit(frame_id, [])

    # Convenience creators
    def create_image(self, file_path: str, width: int, height: int) -> ImageAsset:
        image = ImageAsset(
            id=generate_id("img"), file_path=file_path, width=width, height=height
        )
        self.images.append(image)
        return image

    def create_module(
        self, name: str, image_id: str, rect: Tuple[int, int, int, int], pivot: Tuple[int, int]
    ) -> Module:
        module = Module(
            id=generate_id("mod"), name=name, image_id=image_id, rect=rect, pivot=pivot
        )
        self.modules.append(module)
        return module

    def create_frame(self, name: str) -> Frame:
        frame = Frame(id=generate_id("frm"), name=name)
        self.frames.append(frame)
        return frame

    def create_animation(self, name: str) -> Animation:
        anim = Animation(
            id=generate_id("anim"),
            name=name,
            playback_type="loop",
            loop_count=-1,
            aframes=[],
        )
        self.animations.append(anim)
        return anim
