"""Data models and JSON serialization for the sprite editor."""

from __future__ import annotations

import json
import uuid
import re
import os
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
class CollisionRect:
    id: str
    type_id: str
    rect: Tuple[int, int, int, int] # x,y,w,h relative to frame origin

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type_id": self.type_id,
            "rect": list(self.rect),
        }

    @staticmethod
    def from_dict(data: Dict) -> "CollisionRect":
        return CollisionRect(
            id=data["id"],
            type_id=data["type_id"],
            rect=tuple(data["rect"]), # type: ignore
        )


@dataclass
class ControlPoint:
    id: str
    type_id: str
    x: int
    y: int

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type_id": self.type_id,
            "x": self.x,
            "y": self.y
        }

    @staticmethod
    def from_dict(data: Dict) -> "ControlPoint":
        # Migration for legacy simple name points?
        # If 'name' in data and 'type_id' not in data...
        # For now assume clean slate or migrated manually.
        return ControlPoint(
            id=data.get("id", generate_id("pt")),
            type_id=data.get("type_id", "unknown"),
            x=data["x"],
            y=data["y"]
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
    duration_ms: int
    offset: Tuple[int, int] = (0, 0)
    # Adding flip support for Animations as per Aurora format
    flip_x: bool = False
    flip_y: bool = False

    def to_dict(self) -> Dict:
        return {
            "frame_id": self.frame_id,
            "duration_ms": self.duration_ms,
            "offset": list(self.offset),
            "flip_x": self.flip_x,
            "flip_y": self.flip_y,
        }

    @staticmethod
    def from_dict(data: Dict) -> "AFrame":
        return AFrame(
            frame_id=data["frame_id"],
            duration_ms=int(data["duration_ms"]),
            offset=tuple(int(v) for v in data.get("offset", (0, 0))),  # type: ignore[arg-type]
            flip_x=bool(data.get("flip_x", False)),
            flip_y=bool(data.get("flip_y", False)),
        )


@dataclass
class Animation:
    id: str
    name: str
    playback_type: str = "Loop"
    loop_count: Optional[int] = 0
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
            playback_type=data.get("playback_type", "Loop"),
            loop_count=data.get("loop_count"),
            aframes=[AFrame.from_dict(af) for af in data.get("aframes", [])],
        )


class AuroraSpriteParser:
    """Parses AuroraGT .sprite format."""
    
    @staticmethod
    def parse(content: str, base_path: str) -> "Project":
        project = Project()
        
        # 1. Parse Images
        image_pattern = re.compile(r'IMAGE\s+(0x[\da-fA-F]+)\s+"([^"]+)"')
        images_map = {} # Map index to absolute path
        
        image_index = 0
        for match in image_pattern.finditer(content):
            img_hex_id, filename = match.groups()
            
            # Construct absolute path
            abs_path = os.path.join(base_path, filename)
            
            # Create ImageAsset
            # Using filename as ID or hex ID? 
            # Modules refer to it by index in my previous logic, but actually 
            # MD line has `MD_IMAGE 0` (index?) or `MD_IMAGE id`?
            # Start of file: IMAGE 0x0001 "..."
            # Module line: MD 0x1000 MD_IMAGE 0 ...
            # The '0' is likely the image index in the list of IMAGE definitions.
            
            # Let's create an asset
            # We use abs_path as ID to deduplicate? Or just use the hex ID?
            # Let's use the absolute path as ID for simplicity in loading, 
            # Or better, generate a clean ID and store path.
            
            # In existing code, I used images list to look up by index.
            images_map[image_index] = abs_path
            
            # Add to project.images so app can load it
            # We don't know width/height yet without loading, but ImageAsset requires it.
            # We can put 0, 0 for now or try to check file? 
            # app.py might load it.
            # Actually, standard flow: App loads Project -> App loads Bitmaps from Assets.
            
            img_asset = ImageAsset(
                id=abs_path, # Use path as ID so Modules can reference it easily
                file_path=abs_path,
                width=0, # Unknown until load
                height=0 
            )
            project.images.append(img_asset)
            image_index += 1

        # 2. Parse Modules
        md_pattern = re.compile(r'MD\s+(0x[\da-fA-F]+)\s+MD_IMAGE\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+"([^"]+)"')
        
        for match in md_pattern.finditer(content):
            md_id, img_idx, x, y, w, h, name = match.groups()
            
            img_idx_int = int(img_idx)
            # Lookup path
            img_path = images_map.get(img_idx_int, "missing.png")
            
            module = Module(
                id=md_id, # Keep Hex ID
                name=name,
                image_id=img_path, # This matches the ImageAsset.id we set above
                rect=(int(x), int(y), int(w), int(h)),
                pivot=(0, 0)
            )
            project.modules.append(module)

        # 3. Parse Frames and Animations using line scanning
        current_block = None
        current_obj = None
        
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            if not line or line.startswith("//"):
                continue
                
            if line.startswith("FRAME"):
                match = re.search(r'FRAME\s+"([^"]+)"', line)
                if match:
                    name = match.group(1)
                    current_block = "FRAME"
                    current_obj = Frame(id=generate_id("frm"), name=name)
                    
            elif line.startswith("ANIM"):
                match = re.search(r'ANIM\s+"([^"]+)"', line)
                if match:
                    name = match.group(1)
                    current_block = "ANIM"
                    current_obj = Animation(id=generate_id("anim"), name=name)
                    
            elif line.startswith("}"):
                if current_block == "FRAME":
                    if isinstance(current_obj, Frame):
                        project.frames.append(current_obj)
                elif current_block == "ANIM":
                    if isinstance(current_obj, Animation):
                        project.animations.append(current_obj)
                current_block = None
                current_obj = None
            else:
                if current_block == "FRAME" and isinstance(current_obj, Frame):
                    if re.match(r'^0x[\da-fA-F]+$', line):
                        current_obj.id = line
                    elif line.startswith("FM"):
                        parts = line.split()
                        ref_id = parts[1]
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
                        
                elif current_block == "ANIM" and isinstance(current_obj, Animation):
                    if re.match(r'^0x[\da-fA-F]+$', line):
                        current_obj.id = line
                    elif line.startswith("AF"):
                        parts = line.split()
                        ref_id = parts[1]
                        duration = int(parts[2])
                        ox = int(parts[3])
                        oy = int(parts[4])
                        flip_x = "+FLIP_X" in line
                        
                        af = AFrame(
                            frame_id=ref_id,
                            duration_ms=duration, # Assuming these are ticks/ms
                            offset=(ox, oy),
                            flip_x=flip_x
                        )
                        current_obj.aframes.append(af)

        return project


@dataclass
class Project:
    name: str = "New Project"
    images: List[ImageAsset] = field(default_factory=list)
    modules: List[Module] = field(default_factory=list)
    frames: List[Frame] = field(default_factory=list)
    animations: List[Animation] = field(default_factory=list)
    collision_types: List[CollisionType] = field(default_factory=list)
    point_types: List[PointType] = field(default_factory=list)

    def get_image(self, image_id: str) -> Optional[ImageAsset]:
        return next((img for img in self.images if img.id == image_id), None)

    def get_module(self, module_id: str) -> Optional[Module]:
        return next((m for m in self.modules if m.id == module_id), None)

    def get_frame(self, frame_id: str) -> Optional[Frame]:
        return next((f for f in self.frames if f.id == frame_id), None)

    def get_animation(self, animation_id: str) -> Optional[Animation]:
        return next((a for a in self.animations if a.id == animation_id), None)

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

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "images": [img.to_dict() for img in self.images],
            "modules": [m.to_dict() for m in self.modules],
            "frames": [f.to_dict() for f in self.frames],
            "animations": [a.to_dict() for a in self.animations],
            "animations": [a.to_dict() for a in self.animations],
            "collision_types": [ct.to_dict() for ct in self.collision_types],
            "point_types": [pt.to_dict() for pt in self.point_types],
        }

    def to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def from_dict(data: Dict) -> "Project":
        images = [ImageAsset.from_dict(img) for img in data.get("images", [])]
        modules = [Module.from_dict(m) for m in data.get("modules", [])]
        frames = [Frame.from_dict(f) for f in data.get("frames", [])]
        animations = [Animation.from_dict(a) for a in data.get("animations", [])]
        collision_types = [CollisionType.from_dict(ct) for ct in data.get("collision_types", [])]
        point_types = [PointType.from_dict(pt) for pt in data.get("point_types", [])]
        
        return Project(
            name=data.get("name", "New Project"),
            images=images,
            modules=modules,
            frames=frames,
            animations=animations,
            collision_types=collision_types,
            point_types=point_types,
        )

    @staticmethod
    def from_json(path: str) -> "Project":
        if path.endswith(".sprite"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return AuroraSpriteParser.parse(content, os.path.dirname(path))
            
        with open(path, "r") as f:
            data = json.load(f)
        return Project.from_dict(data)
