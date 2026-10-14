"""Timeline scenes: keyframed objects, easing, linear / spline paths, source switches and what an object shows at
a time (evaluate_object_state)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import playback
from models.core import ModuleMapping, PaletteSwap, generate_id

if TYPE_CHECKING:
    from models.project import Project


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
    playback_mode: str = playback.AS_ANIMATED  # or an override: playback.OBJECT_MODES
    path_mode: str = "linear"
    use_source_root_motion: bool = False
    mapping_id: Optional[str] = None
    palette_swap_id: Optional[str] = None  # like mapping_id: None inherits, TIMELINE_MAPPING_ORIGINAL, or a swap's id
    keyframes: List[TimelineKeyframe] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "mapping_id": self.mapping_id,
            "palette_swap_id": self.palette_swap_id,
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
        playback_mode = str(data.get("playback_mode") or playback.AS_ANIMATED).strip().lower()
        if playback_mode not in playback.OBJECT_MODES:
            playback_mode = playback.AS_ANIMATED
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
            palette_swap_id=str(data.get("palette_swap_id")) if data.get("palette_swap_id") else None,
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

    def object_palette_swap(
        self, project: "Project", object_id: str, default: Optional["PaletteSwap"]
    ) -> Optional["PaletteSwap"]:
        """The palette swap an object is drawn with, found like its mapping: its own, else its nearest ancestor's,
        else ``default`` (the preview's in the editor). TIMELINE_MAPPING_ORIGINAL draws the palettes as they are;
        an id that no longer exists counts as unset."""
        seen: set = set()
        obj = self.get_object(object_id)
        while obj and obj.id not in seen:
            seen.add(obj.id)
            if obj.palette_swap_id == TIMELINE_MAPPING_ORIGINAL:
                return None
            if obj.palette_swap_id:
                swap = project.get_palette_swap(obj.palette_swap_id)
                if swap:
                    return swap
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
        # The same rules as the Animations tab and the game (playback.py), at the animation's own tick rate.
        local_time = (scene_time - started_at) * obj.playback_speed + obj.playback_offset
        shown, index = playback.animation_at(
            anim, local_time, playback.object_rules(anim, obj.playback_mode), project.get_animation
        )
        af = shown.aframes[index]
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
        at_next = float(time) >= float(next_key.time) - 1e-9
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
            # Flips and visibility hold until the next key's frame (like stepped keys in animation tools).
            "flip_x": next_key.flip_x if at_next else prev_key.flip_x,
            "flip_y": next_key.flip_y if at_next else prev_key.flip_y,
            "visible": next_key.visible if at_next else prev_key.visible,
            "opacity": _timeline_clamp01(_timeline_lerp(prev_key.opacity, next_key.opacity, eased_t)),
            "source_key_offset": key_source_offset,
            **sampled_source,
        }
