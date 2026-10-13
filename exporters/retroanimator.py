"""RetroAnimator JSON export: every frame and animation step baked into cropped PNG parts (the active mapping
baked in)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import compositor
from models import Frame, ModuleMapping, Project
from safe_files import write_text_atomically


RETRO_TICKS_PER_SECOND = 50
PARTS_DIRNAME = "Cropped parts"


def _sanitize_name(value: str, fallback: str = "item") -> str:
    v = re.sub(r"[^A-Za-z0-9 _.-]+", "_", str(value or "")).strip()
    return v if v else fallback


def _make_unique_name(base: str, used: set[str]) -> str:
    candidate = base
    i = 2
    while candidate in used:
        candidate = f"{base} {i}"
        i += 1
    used.add(candidate)
    return candidate


def export(project: Project, path: str, mapping: Optional[ModuleMapping] = None) -> Dict[str, Any]:
    """Write ``path`` (.json added if missing) and the part images next to it; returns a report (counts, what the
    format cannot hold)."""
    from PIL import Image as PILImage

    if not path.lower().endswith(".json"):
        path += ".json"

    base_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(base_dir, exist_ok=True)
    parts_dir = os.path.join(base_dir, PARTS_DIRNAME)
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

        part_base = _make_unique_name(
            _sanitize_name(preferred_base, fallback=f"part_{len(part_hash_to_filename) + 1}"),
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
                with PILImage.open(part_abs_path) as img:
                    size = (int(img.width), int(img.height))
                part_filename_to_size[filename] = size
                return size
            except (OSError, ValueError):  # not an image Pillow reads
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
                return PILImage.open(abs_path).convert("RGBA")
            except (OSError, ValueError):  # not an image Pillow reads
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
                base_part = base_part.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)

            transformed_part = base_part
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

            out_sprite["FramePath"] = f"{PARTS_DIRNAME}\\{part_filename}"
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

        frame_name = _make_unique_name(
            _sanitize_name(desired_frame_name, fallback=source_frame.id),
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
        extra_transform: Tuple[compositor.Matrix, compositor.Vector],
        root_rot: float = 0.0,
        root_flip_x: bool = False,
        root_flip_y: bool = False,
    ) -> str:
        if variant_key in variant_cache:
            return variant_cache[variant_key]

        frame_name = _make_unique_name(
            _sanitize_name(desired_frame_name, fallback=source_frame.id),
            used_frame_names,
        )
        instances: List[compositor.LeafInstance] = []
        compositor.collect_leaf_instances(
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
        for idx, (mod, a_mat, b_vec, _rot, _flip_x, _flip_y, local_flip_x, local_flip_y) in enumerate(instances):
            rendered = compositor.render_instance(
                project, mod, a_mat, b_vec, full_image_cache, module_cache, local_flip_x, local_flip_y
            )
            if not rendered:
                continue
            part_img, handle_x, handle_y = rendered
            part_filename = get_or_write_part_filename(part_img, preferred_base=mod.name or f"part_{idx + 1}")
            sprites_json.append(
                {
                    "FramePath": f"{PARTS_DIRNAME}\\{part_filename}",
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
            (cr.type_id, compositor.transform_rect(cr.rect, extra_transform[0], extra_transform[1]))
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

    identity_transform = (compositor.IDENTITY, (0.0, 0.0))
    mapping_key = active_mapping.id if active_mapping else None

    # Export all base frames.
    for frame in project.frames:
        base_name = frame.name or frame.id
        key = ("base", frame.id, mapping_key)
        out_name = write_variant(frame, key, base_name, identity_transform)
        frame_name_by_id[frame.id] = out_name

    animations_json: Dict[str, Dict[str, Any]] = {}
    for anim in project.animations:
        anim_name = _make_unique_name(
            _sanitize_name(anim.name, fallback=anim.id),
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
                local_a = compositor.mat_mul(
                    compositor.rotation_matrix(rot),
                    compositor.flip_matrix(flip_x, flip_y),
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
                int(round((float(af.duration_frames) / float(source_fps)) * RETRO_TICKS_PER_SECOND)),
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

    write_text_atomically(path, json.dumps(data, indent=2))

    return {
        "path": os.path.abspath(path),
        "parts_dir": os.path.abspath(parts_dir),
        "frames_exported": len(frame_payloads),
        "animations_exported": len(animations_json),
        "parts_written": written_parts,
        "mapping_baked": bool(active_mapping),
        "losses": losses,
    }
