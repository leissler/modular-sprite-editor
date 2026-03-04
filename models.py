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

    def clone(self) -> "Frame":
        return Frame.from_dict(self.to_dict())

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

    def to_dict(self) -> Dict:
        return {
            "frame_id": self.frame_id,
            "duration_frames": self.duration_frames,
            "offset": list(self.offset),
            "flip_x": self.flip_x,
            "flip_y": self.flip_y,
            "rotation_degrees": self.rotation_degrees,
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
        )


@dataclass
class Animation:
    id: str
    name: str
    playback_type: str = "loop"
    loop_count: Optional[int] = 0
    fps: int = 10
    aframes: List[AFrame] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "playback_type": self.playback_type,
            "loop_count": self.loop_count,
            "fps": self.fps,
            "aframes": [af.to_dict() for af in self.aframes],
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
        )


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
                        CollisionRect(
                            id=generate_id("crect"),
                            type_id=collision_type_by_name[name],
                            rect=(
                                RetroAnimatorParser._to_int(col_data.get("X"), 0),
                                RetroAnimatorParser._to_int(col_data.get("Y"), 0),
                                RetroAnimatorParser._to_int(col_data.get("Width"), 0),
                                RetroAnimatorParser._to_int(col_data.get("Height"), 0),
                            ),
                        )
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
            ]
        ],
        depth: int,
        stack: set[str],
    ) -> None:
        if depth > 48:
            return
        frame = project.get_frame(frame_id)
        if not frame or frame_id in stack:
            return

        stack.add(frame_id)
        for fm in frame.fmodules:
            local_a = RetroAnimatorExporter._mat_mul(
                RetroAnimatorExporter._rotation_matrix(float(getattr(fm, "rotation_degrees", 0.0))),
                RetroAnimatorExporter._flip_matrix(bool(getattr(fm, "flip_x", False)), bool(getattr(fm, "flip_y", False))),
            )
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
                    out.append((mod, a_next, b_next, rot_next, flip_x_next, flip_y_next))
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

        for mod, a_mat, b_vec, rot_deg, flip_x, flip_y in instances:
            base = RetroAnimatorExporter._load_module_rgba(project, mod, full_image_cache, module_cache)
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
    ) -> Optional[Tuple[Any, int, int]]:
        from PIL import Image as PILImage

        base = RetroAnimatorExporter._load_module_rgba(project, mod, full_image_cache, module_cache)
        w, h = base.size
        if w <= 0 or h <= 0:
            return None

        rot_norm = float(rotation_degrees) % 360.0
        rot_int = int(round(rot_norm)) % 360
        orthogonal = abs(rot_norm - float(rot_int)) < 1e-5 and rot_int in (0, 90, 180, 270)
        if orthogonal:
            transformed = base
            if flip_x:
                transformed = transformed.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
            if flip_y:
                transformed = transformed.transpose(PILImage.Transpose.FLIP_TOP_BOTTOM)
            if rot_int == 90:
                transformed = transformed.transpose(PILImage.Transpose.ROTATE_270)  # clockwise
            elif rot_int == 180:
                transformed = transformed.transpose(PILImage.Transpose.ROTATE_180)
            elif rot_int == 270:
                transformed = transformed.transpose(PILImage.Transpose.ROTATE_90)   # counter-clockwise

            handle_x, handle_y = RetroAnimatorExporter._module_handle_for_rotation(
                mod, anchor=b_vec, rotation_degrees=float(rot_int)
            )
            if not transformed.getbbox():
                return None
            return transformed, handle_x, handle_y

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
            for idx, (mod, a_mat, b_vec, rot_deg, flip_x, flip_y) in enumerate(instances):
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
    mappings: List[ModuleMapping] = field(default_factory=list)
    collision_types: List[CollisionType] = field(default_factory=list)
    point_types: List[PointType] = field(default_factory=list)
    
    # Runtime state (not serialized)
    active_mapping: Optional[ModuleMapping] = field(default=None, init=False)

    def get_image(self, image_id: str) -> Optional[ImageAsset]:
        return next((img for img in self.images if img.id == image_id), None)

    def get_module(self, module_id: str) -> Optional[Module]:
        return next((m for m in self.modules if m.id == module_id), None)

    def get_frame(self, frame_id: str) -> Optional[Frame]:
        return next((f for f in self.frames if f.id == frame_id), None)

    def get_animation(self, animation_id: str) -> Optional[Animation]:
        return next((a for a in self.animations if a.id == animation_id), None)

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
            "name": self.name,
            "images": [get_img_dict(img) for img in self.images],
            "modules": [m.to_dict() for m in self.modules],
            "frames": [f.to_dict() for f in self.frames],
            "animations": [a.to_dict() for a in self.animations],
            "mappings": [m.to_dict() for m in self.mappings],
            "collision_types": [ct.to_dict() for ct in self.collision_types],
            "point_types": [pt.to_dict() for pt in self.point_types],
        }

    def to_json(self, path: str) -> None:
        base_path = os.path.dirname(os.path.abspath(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(base_path=base_path), f, indent=2)

    def to_retro_animator_json(self, path: str, mapping: Optional[ModuleMapping] = None) -> Dict[str, Any]:
        return RetroAnimatorExporter.export(self, path=path, mapping=mapping)

    @staticmethod
    def from_dict(data: Dict, base_path: Optional[str] = None) -> "Project":
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
        mappings = [ModuleMapping.from_dict(m) for m in data.get("mappings", [])]
        collision_types = [CollisionType.from_dict(ct) for ct in data.get("collision_types", [])]
        point_types = [PointType.from_dict(pt) for pt in data.get("point_types", [])]
        
        return Project(
            name=data.get("name", "New Project"),
            images=images,
            modules=modules,
            frames=frames,
            animations=animations,
            mappings=mappings,
            collision_types=collision_types,
            point_types=point_types,
        )

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
