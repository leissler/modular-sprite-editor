"""RetroAnimator JSON import (the Scorpion Engine tooling's format)."""

from __future__ import annotations

import os
from typing import Dict, Optional

from models import AFrame, Animation, CollisionRect, CollisionType, FModule, Frame, ImageAsset, Module, Project, generate_id


RETRO_TICKS_PER_SECOND = 50


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _clamp_u8(value: int) -> int:
    return max(0, min(255, int(value)))


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip()


def _resolve_case_insensitive(base_path: str, rel_path: str) -> Optional[str]:
    """Resolve a relative path with case-insensitive fallback per path segment."""
    base_abs = os.path.abspath(base_path)
    current = base_abs
    parts = [p for p in _normalize_path(rel_path).split("/") if p and p != "."]

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


def _resolve_frame_path(base_path: str, frame_path: str) -> str:
    normalized = _normalize_path(frame_path)
    if not normalized:
        return os.path.abspath(base_path)

    if os.path.isabs(normalized):
        candidate = os.path.abspath(normalized)
        if os.path.exists(candidate):
            return candidate
        resolved = _resolve_case_insensitive(os.path.dirname(candidate), os.path.basename(candidate))
        return resolved or candidate

    candidate = os.path.abspath(os.path.join(base_path, normalized.replace("/", os.sep)))
    if os.path.exists(candidate):
        return candidate

    resolved = _resolve_case_insensitive(base_path, normalized)
    return resolved or candidate


def parse(data: Dict, base_path: str, project_name: Optional[str] = None) -> Project:
    """A project from a RetroAnimator JSON dict; part image paths are relative to ``base_path``."""
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
        normalized = _normalize_path(frame_path)
        if not normalized:
            return None

        key = normalized.lower()
        if key in path_to_module_id:
            return path_to_module_id[key]

        abs_path = _resolve_frame_path(base_path, normalized)
        width = 0
        height = 0
        if os.path.exists(abs_path):
            try:
                from PIL import Image as PILImage
                with PILImage.open(abs_path) as img:
                    width, height = img.size
            except (OSError, ValueError):  # not an image Pillow reads
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
                            _to_int(sprite_data.get("HandleX"), 0),
                            _to_int(sprite_data.get("HandleY"), 0),
                        ),
                        flip_x=_to_bool(sprite_data.get("XFlip", False)),
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
                    _to_int(col_data.get("X"), 0),
                    _to_int(col_data.get("Y"), 0),
                    _to_int(col_data.get("Width"), 0),
                    _to_int(col_data.get("Height"), 0),
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
                            _clamp_u8(_to_int(col_data.get("ColorR"), 255)),
                            _clamp_u8(_to_int(col_data.get("ColorG"), 0)),
                            _clamp_u8(_to_int(col_data.get("ColorB"), 0)),
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
            fps=RETRO_TICKS_PER_SECOND,
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

                duration = max(1, _to_int(af_data.get("Duration"), 1))
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
