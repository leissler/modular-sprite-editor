"""The project: every list of the data model, lookups by id, and the native JSON file (opening imports AuroraGT
and RetroAnimator files too)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from models.core import (
    Animation,
    CollisionType,
    EventType,
    Frame,
    ImageAsset,
    Module,
    ModuleMapping,
    Palette,
    PaletteSwap,
    PointType,
    generate_id,
)
from models.migration import PROJECT_FORMAT_VERSION, migrate_project_dict
from models.timeline import TimelineScene
from safe_files import write_text_atomically


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
    console: str = "megadrive"  # the target console (consoles.py): its palettes' size, colours and limits
    # The console's setup (consoles.BudgetSetup: screen mode, sprite sizes). Read it through consoles.target, which
    # takes the console's first for a key that is unknown or another console's.
    console_setup: str = "md_h40"
    palettes: List[Palette] = field(default_factory=list)
    palette_swaps: List[PaletteSwap] = field(default_factory=list)

    # Runtime state (not serialized)
    active_mapping: Optional[ModuleMapping] = field(default=None, init=False)
    active_palette_swap: Optional[PaletteSwap] = field(default=None, init=False)  # the preview's, like the mapping
    load_notes: List[str] = field(default_factory=list, init=False)
    imported_from: str = field(default="", init=False)  # e.g. "AuroraGT sprite"; empty for the editor's own files
    # Where each id was found in its list (see _find); the lists are edited in place everywhere, so positions are
    # checked on every use, never trusted.
    _positions: Dict[str, Dict[str, int]] = field(default_factory=dict, init=False, repr=False, compare=False)

    def _find(self, kind: str, items: List[Any], item_id: Optional[str]) -> Any:
        """The item with this id. A hit costs O(1): the position found last time, checked; anything else scans the list
        as a plain lookup would and remembers every position again if the id is there. Two items with one id (only a
        broken project has them): a scan finds the first, a remembered position may later hold the other."""
        positions = self._positions.get(kind)
        if positions is not None:
            index = positions.get(item_id)  # type: ignore[arg-type]
            if index is not None and index < len(items) and items[index].id == item_id:
                return items[index]
        for index, item in enumerate(items):
            if item.id == item_id:
                fresh: Dict[str, int] = {}
                for n in range(len(items) - 1, -1, -1):  # backwards: the first of two equal ids wins
                    fresh[items[n].id] = n
                self._positions[kind] = fresh
                return item
        return None

    def get_image(self, image_id: str) -> Optional[ImageAsset]:
        return self._find("images", self.images, image_id)

    def get_module(self, module_id: str) -> Optional[Module]:
        return self._find("modules", self.modules, module_id)

    def get_frame(self, frame_id: str) -> Optional[Frame]:
        return self._find("frames", self.frames, frame_id)

    def get_animation(self, animation_id: str) -> Optional[Animation]:
        return self._find("animations", self.animations, animation_id)

    def get_mapping(self, mapping_id: str) -> Optional[ModuleMapping]:
        return self._find("mappings", self.mappings, mapping_id)

    def get_event_type(self, type_id: str) -> Optional[EventType]:
        return self._find("event_types", self.event_types, type_id)

    def get_palette(self, palette_id: Optional[str]) -> Optional[Palette]:
        return self._find("palettes", self.palettes, palette_id)

    def get_palette_swap(self, swap_id: Optional[str]) -> Optional[PaletteSwap]:
        return self._find("palette_swaps", self.palette_swaps, swap_id)

    def default_palette(self) -> Palette:
        """The first palette (vector shapes and images without one use it), made when the project has none."""
        if not self.palettes:
            self.palettes.append(Palette(id=generate_id("pal"), name="Palette 1"))
        return self.palettes[0]

    def image_palette(self, asset: Optional[ImageAsset]) -> Palette:
        """The palette an image's colours go into: its own, else the first."""
        palette = self.get_palette(asset.palette_id) if asset is not None else None
        return palette or self.default_palette()

    def get_timeline_scene(self, scene_id: str) -> Optional[TimelineScene]:
        return self._find("timeline_scenes", self.timeline_scenes, scene_id)

    def frame_has_cycle(self, frame_id: str, new_child_id: Optional[str] = None) -> bool:
        """Checks if a cycle exists (or would exist if new_child_id is added to frame_id)."""
        visited = set()  # explored without finding a cycle: shared nested frames are walked once
        def visit(fid: str, stack: List[str]) -> bool:
            if fid in stack:
                return True
            if fid in visited:
                return False
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
            transparent_color=transparent_color,
            palette_id=self.default_palette().id,
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
            "console": self.console,
            "console_setup": self.console_setup,
            "palettes": [palette.to_dict() for palette in self.palettes],
            "palette_swaps": [swap.to_dict() for swap in self.palette_swaps],
        }

    def to_json(self, path: str, keep_backup: bool = True) -> None:
        """Save the project. The file is replaced in one step, so a failed or interrupted save leaves the previous
        version intact; with ``keep_backup`` that version also stays next to it as ``<name>.bak``."""
        base_path = os.path.dirname(os.path.abspath(path))
        text = json.dumps(self.to_dict(base_path=base_path), indent=2)  # fails before the file is touched
        write_text_atomically(path, text, keep_backup=keep_backup)

    def to_retro_animator_json(self, path: str, mapping: Optional[ModuleMapping] = None,
                               swap: Optional[PaletteSwap] = None) -> Dict[str, Any]:
        from exporters import retroanimator  # the exporters import the model

        return retroanimator.export(self, path=path, mapping=mapping, swap=swap)

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
        palette_list = [Palette.from_dict(p) for p in data.get("palettes", []) or []]
        palette_swaps = [PaletteSwap.from_dict(s) for s in data.get("palette_swaps", []) or []]

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
            console=str(data.get("console") or "megadrive"),
            console_setup=str(data.get("console_setup") or ""),
            palettes=palette_list,
            palette_swaps=palette_swaps,
        )
        project.load_notes = notes
        import palettes  # the palette rules import the model

        palettes.build_missing(project)  # a project from format 6: its palettes from the images, as that format did
        return project

    @staticmethod
    def from_json(path: str) -> "Project":
        """Open a project file; AuroraGT .sprite and RetroAnimator JSON files are imported."""
        from importers import aurora, retroanimator  # the importers import the model

        if path.endswith(".sprite"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            project = aurora.parse(content, os.path.dirname(path))
            project.imported_from = "AuroraGT sprite"
            return project

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            project_type = str(data.get("ProjectType", "")).strip().lower()
            if project_type == "retroanimator":
                base_path = os.path.dirname(os.path.abspath(path))
                project_name = os.path.splitext(os.path.basename(path))[0]
                project = retroanimator.parse(data, base_path=base_path, project_name=project_name)
                project.imported_from = "RetroAnimator project"
                return project

        return Project.from_dict(data, base_path=os.path.dirname(os.path.abspath(path)))

    @staticmethod
    def from_retro_animator_json(path: str) -> "Project":
        from importers import retroanimator

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict) or str(data.get("ProjectType", "")).strip().lower() != "retroanimator":
            raise ValueError("Selected file is not a RetroAnimator project JSON.")

        base_path = os.path.dirname(os.path.abspath(path))
        project_name = os.path.splitext(os.path.basename(path))[0]
        project = retroanimator.parse(data, base_path=base_path, project_name=project_name)
        project.imported_from = "RetroAnimator project"
        return project
