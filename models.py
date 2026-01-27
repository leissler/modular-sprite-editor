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
            
        with open(path, "r") as f:
            data = json.load(f)
        return Project.from_dict(data, base_path=os.path.dirname(os.path.abspath(path)))
