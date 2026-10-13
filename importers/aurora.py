"""AuroraGT .sprite import (the text format of the AuroraGT editor)."""

from __future__ import annotations

import os
import re
from typing import Tuple

from models import (
    AFrame,
    Animation,
    CollisionRect,
    CollisionType,
    FModule,
    Frame,
    ImageAsset,
    Module,
    ModuleMapping,
    Project,
    generate_id,
)


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


def parse(content: str, base_path: str) -> Project:
    """A project from the text of a .sprite file; image paths are relative to ``base_path``."""
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
                            color = _parse_color(parts[3])
                            w, h = int(parts[4]), int(parts[5])
                            rect = (0, 0, w, h)
                            pivot = (w // 2, h // 2)

                        # 3. MD_ARC / FILL_ARC: color w h start arc
                        elif md_type in ("MD_ARC", "MD_FILL_ARC"):
                            color = _parse_color(parts[3])
                            w, h = int(parts[4]), int(parts[5])
                            start, arc = float(parts[6]), float(parts[7])
                            rect = (0, 0, w, h)
                            pivot = (w // 2, h // 2)
                            params = [start, arc]

                        # 4. MD_TRIANGLE / FILL: color p2x p2y p3x p3y
                        elif md_type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
                            color = _parse_color(parts[3])
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

                        # 5. MD_LINE: color endX endY, a line from (0, 0); stored as percentages of its rect
                        elif md_type == "MD_LINE":
                            color = _parse_color(parts[3])
                            endX, endY = int(parts[4]), int(parts[5])
                            min_x, max_x = min(0, endX), max(0, endX)
                            min_y, max_y = min(0, endY), max(0, endY)
                            w, h = max(1, max_x - min_x), max(1, max_y - min_y)
                            rect = (min_x, min_y, w, h)
                            pivot = (w // 2, h // 2)
                            params = [
                                (0 - min_x) / w * 100.0, (0 - min_y) / h * 100.0,
                                (endX - min_x) / w * 100.0, (endY - min_y) / h * 100.0,
                            ]

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
