"""Check Project: what exports would drop, show differently or get wrong (wx-free).

Tools ▸ Check Project lists the issues, the Mega Drive export shows them in its report and export_sgdk prints them.
Each issue says in plain words what happens and points at the item it is about; many have a fix that repairs them
in one go (``fix``), which the editor runs as one undoable step.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import palettes
from models import ImageAsset, Project

ERROR, WARNING, INFO = "error", "warning", "info"
LEVEL_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

# Mega Drive with SGDK's default video memory layout: the plane maps start at 0xC000 (1536 tiles); SGDK keeps the
# first 16 tiles and the font's 96 tiles below the maps, so 1424 tiles are left for sprites and backgrounds together.
MD_PALETTE_COLOURS = 15
MD_TILE_CAPACITY = 1424

Target = Tuple[str, str]  # (kind, id), kind: image / module / frame / animation / mapping / scene


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    text: str
    target: Optional[Target] = None
    fix: Optional[str] = None  # a key of FIXES


# ---------------------------------------------------------------------------- names in the game code
def c_symbol_core(name: str, fallback: str) -> str:
    """The part of a C identifier made from a name: HIT_ON for "hit on", never starting with a digit."""
    core = "".join(ch if ch.isalnum() else "_" for ch in str(name).upper()).strip("_") or fallback
    while "__" in core:
        core = core.replace("__", "_")
    if core[0].isdigit():
        core = "E" + core
    return core


def c_symbols(names: Sequence[str], prefix: str, fallback: str) -> List[str]:
    """Unique C identifiers for names, in order; a name that clashes with an earlier one gets _2, _3, ..."""
    used: Dict[str, int] = {}
    out: List[str] = []
    for name in names:
        symbol = f"{prefix}{c_symbol_core(name, fallback)}"
        if symbol in used:
            used[symbol] += 1
            symbol = f"{symbol}_{used[symbol]}"
        else:
            used[symbol] = 1
        out.append(symbol)
    return out


def role_names(project: Project) -> List[str]:
    """Every role used by a hitbox or point, in the order the exporter numbers them."""
    return sorted(
        {str(item.role).strip() for f in project.frames for item in list(f.collision_rects) + list(f.control_points)
         if str(getattr(item, "role", "") or "").strip()}
    )


# ---------------------------------------------------------------------------- helpers
def _plural(count: int, word: str, plural: Optional[str] = None) -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def _says(count: int, singular: str, plural: str) -> str:
    """The verb (phrase) that agrees with a count: _says(1, "shows", "show") -> "shows"."""
    return singular if count == 1 else plural


def _module_ids(project: Project) -> Set[str]:
    return {m.id for m in project.modules}


def _frame_ids(project: Project) -> Set[str]:
    return {f.id for f in project.frames}


def _part_missing(fm, module_ids: Set[str], frame_ids: Set[str]) -> bool:
    return fm.ref_id not in (frame_ids if fm.ref_type == "frame" else module_ids)


def _scene_source_missing(project: Project, source_type: Optional[str], source_id: Optional[str]) -> bool:
    if not source_id or source_type in (None, "none"):
        return False
    if source_type == "module":
        return project.get_module(source_id) is None
    if source_type == "frame":
        return project.get_frame(source_id) is None
    if source_type == "animation":
        return project.get_animation(source_id) is None
    return False


# ---------------------------------------------------------------------------- checks
def _check_images(project: Project, pixels: bool) -> List[Issue]:
    issues: List[Issue] = []
    colours: Dict[int, Set[Tuple[int, int, int]]] = {}  # palette -> the colours its images use
    images_in: Dict[int, List[ImageAsset]] = {}
    modules_on: Counter = Counter(m.image_id for m in project.modules if m.type == "MD_IMAGE")
    for asset in project.images:
        name = os.path.basename(asset.file_path) or asset.id
        if not asset.file_path or not os.path.exists(asset.file_path):
            used = modules_on[asset.id]
            effect = ("" if not used else " Its module draws nothing and exports leave it out." if used == 1
                      else f" Its {used} modules draw nothing and exports leave them out.")
            issues.append(Issue(
                ERROR, "missing-image",
                f"The image '{name}' is missing.{effect} Locate it in the Modules tab.",
                ("image", asset.id),
            ))
            continue
        if not pixels:
            continue
        try:
            from PIL import Image

            with Image.open(asset.file_path) as image:
                rgba = image.convert("RGBA")
        except OSError:
            issues.append(Issue(ERROR, "unreadable-image", f"The image '{name}' cannot be read.", ("image", asset.id)))
            continue
        key = tuple(int(c) for c in asset.transparent_color) if asset.transparent_color else None
        half = 0
        palette = palettes.palette_of(asset)
        images_in.setdefault(palette, []).append(asset)
        for count, (r, g, b, a) in rgba.getcolors(rgba.width * rgba.height) or []:
            if a == 0 or (r, g, b) == key:
                continue
            colours.setdefault(palette, set()).add((r, g, b))
            if a < 255:
                half += count
        if half:
            issues.append(Issue(
                WARNING, "half-transparent",
                f"The image '{name}' has {_plural(half, 'half-transparent pixel')}: the Mega Drive shows them fully "
                "opaque.",
                ("image", asset.id),
            ))
    for palette, used in sorted(colours.items()):
        if len(used) <= MD_PALETTE_COLOURS:
            continue
        members = images_in[palette]
        names = ", ".join(f"'{os.path.basename(a.file_path) or a.id}'" for a in members[:3]) + (" ..." if len(members) > 3 else "")
        issues.append(Issue(
            WARNING, "too-many-colours",
            f"Palette {palette + 1} ({names}) uses {len(used)} colours. A Mega Drive palette holds "
            f"{MD_PALETTE_COLOURS}, so the export merges similar colours"
            + (": put some of its images in another palette (Modules tab, the image's Palette)." if len(members) > 1
               else "."),
            ("image", members[0].id),
        ))
    return issues


def _check_modules(project: Project) -> List[Issue]:
    issues: List[Issue] = []
    # An empty module that mappings put in place of others is a way to hide them (an AuroraGT habit): not a problem.
    replacements = {dest for mapping in project.mappings for dest in mapping.map.values() if dest}
    used_in_frames = {fm.ref_id for frame in project.frames for fm in frame.fmodules if fm.ref_type == "module"}
    for mod in project.modules:
        if int(mod.rect[2]) <= 0 or int(mod.rect[3]) <= 0:
            if mod.id in used_in_frames:
                issues.append(Issue(WARNING, "empty-module", f"Module '{mod.name}' has no size: parts that show it "
                                    "draw nothing.", ("module", mod.id)))
            elif mod.id not in replacements:
                issues.append(Issue(INFO, "empty-module", f"Module '{mod.name}' has no size.", ("module", mod.id)))
            continue
        if mod.type != "MD_IMAGE":
            continue
        asset = project.get_image(mod.image_id)
        if asset is None:
            issues.append(Issue(
                ERROR, "orphan-module",
                f"Module '{mod.name}' belongs to an image that is no longer in the project: it draws nothing.",
                ("module", mod.id),
            ))
            continue
        x, y, w, h = (int(v) for v in mod.rect)
        if asset.width > 0 and asset.height > 0 and (x < 0 or y < 0 or x + w > asset.width or y + h > asset.height):
            issues.append(Issue(
                WARNING, "module-outside-image",
                f"Module '{mod.name}' reaches outside its image: that part stays empty.",
                ("module", mod.id),
            ))
    return issues


def _check_frames(project: Project) -> List[Issue]:
    issues: List[Issue] = []
    module_ids, frame_ids = _module_ids(project), _frame_ids(project)
    box_types = {t.id: t.name for t in project.collision_types}
    point_types = {t.id: t.name for t in project.point_types}
    empty_boxes = empty_frames = 0
    for frame in project.frames:
        missing = sum(1 for fm in frame.fmodules if _part_missing(fm, module_ids, frame_ids))
        if missing:
            issues.append(Issue(
                ERROR, "missing-part",
                f"Frame '{frame.name}': {_plural(missing, 'part')} {_says(missing, 'shows', 'show')} a deleted module "
                f"or frame. Exports leave {_says(missing, 'it', 'them')} out.",
                ("frame", frame.id), "remove-missing-parts",
            ))
        empties = sum(1 for cr in frame.collision_rects if cr.rect[2] <= 0 or cr.rect[3] <= 0)
        if empties:
            empty_boxes += empties
            empty_frames += 1
        unknown = sum(1 for cr in frame.collision_rects if cr.type_id not in box_types)
        unknown += sum(1 for cp in frame.control_points if cp.type_id not in point_types)
        if unknown:
            issues.append(Issue(
                WARNING, "unknown-type",
                f"Frame '{frame.name}': {_plural(unknown, 'hitbox or point', 'hitboxes or points')} "
                f"{_says(unknown, 'has', 'have')} a type that was deleted. The game gets "
                f"{_says(unknown, 'it', 'them')} with an unknown type; choose a type in the inspector.",
                ("frame", frame.id),
            ))
    if empty_boxes:
        issues.append(Issue(
            WARNING, "empty-hitbox",
            f"{_plural(empty_boxes, 'hitbox', 'hitboxes')} in {_plural(empty_frames, 'frame')} "
            f"{_says(empty_boxes, 'has', 'have')} no size. Exports leave {_says(empty_boxes, 'it', 'them')} out.",
            None, "remove-empty-hitboxes",
        ))
    for problem in project.validate_role_uniqueness():
        frame = project.get_frame(problem["frame_id"])
        names = box_types if problem["kind"] == "collision" else point_types
        kind = "hitboxes" if problem["kind"] == "collision" else "points"
        issues.append(Issue(
            WARNING, "duplicate-role",
            f"Frame '{frame.name if frame else problem['frame_id']}': {len(problem['item_ids'])} {kind} of the type "
            f"'{names.get(problem['type_id'], 'unknown')}' have the role '{problem['role']}'. The game finds only the "
            "first.",
            ("frame", problem["frame_id"]),
        ))
    used = {af.frame_id for anim in project.animations for af in anim.aframes}
    for frame in project.frames:
        if frame.id in used and not frame.fmodules:
            issues.append(Issue(INFO, "empty-frame", f"Frame '{frame.name}' is used by animations but shows nothing.",
                                ("frame", frame.id)))
    return issues


def _check_animations(project: Project) -> List[Issue]:
    issues: List[Issue] = []
    frame_ids = _frame_ids(project)
    event_types = {t.id for t in project.event_types}
    for anim in project.animations:
        target = ("animation", anim.id)
        if not anim.aframes:
            issues.append(Issue(INFO, "empty-animation", f"Animation '{anim.name}' has no steps.", target))
        missing = sum(1 for af in anim.aframes if af.frame_id not in frame_ids)
        if missing:
            issues.append(Issue(
                ERROR, "missing-step",
                f"Animation '{anim.name}': {_plural(missing, 'step')} {_says(missing, 'shows', 'show')} a deleted "
                f"frame. Exports drop {_says(missing, 'it', 'them')}.",
                target, "remove-missing-steps",
            ))
        unknown = sum(1 for af in anim.aframes for e in af.events if e.type_id not in event_types)
        if unknown:
            issues.append(Issue(
                WARNING, "unknown-event",
                f"Animation '{anim.name}': {_plural(unknown, 'event')} of a deleted event type.",
                target, "remove-unknown-events",
            ))
        if anim.next_animation_id:
            if project.get_animation(anim.next_animation_id) is None:
                issues.append(Issue(
                    WARNING, "missing-follow-up",
                    f"Animation '{anim.name}' continues with an animation that was deleted.",
                    target, "clear-missing-follow-ups",
                ))
            elif not (anim.playback_type == "forward" or int(anim.loop_count or 0) > 0):
                issues.append(Issue(
                    INFO, "follow-up-never-starts",
                    f"Animation '{anim.name}' never ends, so its follow-up never starts: choose Play once or a repeat "
                    "count.",
                    target,
                ))
    return issues


def _check_mappings(project: Project) -> List[Issue]:
    issues: List[Issue] = []
    module_ids = _module_ids(project)
    for mapping in project.mappings:
        target = ("mapping", mapping.id)
        dead = sum(1 for source in mapping.map if source not in module_ids)
        broken = sum(1 for source, dest in mapping.map.items()
                     if source in module_ids and dest is not None and dest not in module_ids)
        if broken:
            issues.append(Issue(
                WARNING, "missing-replacement",
                f"Mapping '{mapping.name}': {_plural(broken, 'module')} {_says(broken, 'is', 'are')} replaced by a "
                f"deleted module, so {_says(broken, 'it shows', 'they show')} nothing.",
                target, "reset-missing-replacements",
            ))
        if dead:
            issues.append(Issue(
                INFO, "dead-mapping-entries",
                f"Mapping '{mapping.name}' has {_plural(dead, 'entry', 'entries')} for deleted modules.",
                target, "drop-dead-entries",
            ))
    return issues


def _check_scenes(project: Project) -> List[Issue]:
    issues: List[Issue] = []
    mapping_ids = {m.id for m in project.mappings}
    for scene in project.timeline_scenes:
        target = ("scene", scene.id)
        missing = sum(
            1 for obj in scene.objects
            if _scene_source_missing(project, obj.source_type, obj.source_id)
            or any(_scene_source_missing(project, k.source_type or obj.source_type, k.source_id) for k in obj.keyframes)
        )
        if missing:
            issues.append(Issue(
                WARNING, "missing-scene-source",
                f"Scene '{scene.name}': {_plural(missing, 'object')} {_says(missing, 'shows', 'show')} a deleted "
                "animation, frame or module, which exports leave out.",
                target, "clear-missing-scene-sources",
            ))
        lost = sum(1 for obj in scene.objects
                   if obj.mapping_id and obj.mapping_id != "original" and obj.mapping_id not in mapping_ids)
        if lost:
            issues.append(Issue(
                INFO, "missing-object-mapping",
                f"Scene '{scene.name}': {_plural(lost, 'object')} {_says(lost, 'uses', 'use')} a deleted mapping and "
                f"{_says(lost, 'inherits', 'inherit')} one instead.",
                target, "clear-missing-object-mappings",
            ))
    return issues


def _check_symbols(project: Project) -> List[Issue]:
    issues: List[Issue] = []
    groups = [
        ("Event types", [t.name for t in project.event_types], "MS_EVENT_", "EVENT"),
        ("Hitbox types", [t.name for t in project.collision_types], "MS_HITBOX_", "HITBOX"),
        ("Point types", [t.name for t in project.point_types], "MS_POINT_", "POINT"),
        ("Roles", role_names(project), "MS_ROLE_", "ROLE"),
    ]
    for label, names, prefix, fallback in groups:
        first_by_symbol: Dict[str, str] = {}
        for name in names:
            symbol = f"{prefix}{c_symbol_core(name, fallback)}"
            if symbol in first_by_symbol:
                issues.append(Issue(
                    WARNING, "name-clash",
                    f"{label} '{first_by_symbol[symbol]}' and '{name}' get the same name in the game code ({symbol}); "
                    "the export numbers the later one. Rename one of them.",
                ))
            else:
                first_by_symbol[symbol] = name
    return issues


def check_project(project: Project, pixels: bool = True) -> List[Issue]:
    """Every issue, errors first. ``pixels`` False skips reading the images (colours, transparency)."""
    issues: List[Issue] = []
    for check in (_check_modules, _check_frames, _check_animations, _check_mappings, _check_scenes, _check_symbols):
        issues += check(project)
    issues = _check_images(project, pixels) + issues
    return sorted(issues, key=lambda issue: LEVEL_ORDER[issue.level])


def tile_issue(tiles: int, capacity: int = MD_TILE_CAPACITY) -> Issue:
    """How the exported tiles fit the Mega Drive's video memory (SGDK's default layout)."""
    if tiles > capacity:
        return Issue(
            ERROR, "too-many-tiles",
            f"The sprites need {tiles} tiles, but only about {capacity} fit in video memory: the runtime would refuse "
            "to load them (ms_tiles_fit() is false) and draw nothing. Share more parts (Auto Modularize) or split the "
            "project.",
        )
    level = WARNING if tiles > capacity * 3 // 4 else INFO
    return Issue(level, "tiles", f"The sprites need {tiles} of about {capacity} tiles of video memory, leaving "
                                 f"{capacity - tiles} for backgrounds and everything else.")


def palette_issue(lines: int) -> Optional[Issue]:
    """How many palette lines the exported sprites use (None for one: the runtime's default PAL1 fits)."""
    if lines <= 1:
        return None
    if lines >= 4:
        return Issue(WARNING, "palette-lines", "The sprites use all four palette lines: start them at PAL0 with "
                                               "ms_init_ex(tile_index, PAL0), ms_init() starts at PAL1.")
    return Issue(INFO, "palette-lines", f"The sprites use {lines} palette lines, PAL1 to PAL{lines} with ms_init() "
                                        "(ms_init_ex() can start them elsewhere).")


def counts(issues: Iterable[Issue]) -> Dict[str, int]:
    found = Counter(issue.level for issue in issues)
    return {level: found.get(level, 0) for level in (ERROR, WARNING, INFO)}


# ---------------------------------------------------------------------------- fixes
def _fix_missing_parts(project: Project, target: Optional[Target]) -> int:
    module_ids, frame_ids = _module_ids(project), _frame_ids(project)
    removed = 0
    for frame in project.frames:
        if target and target != ("frame", frame.id):
            continue
        kept = [fm for fm in frame.fmodules if not _part_missing(fm, module_ids, frame_ids)]
        removed += len(frame.fmodules) - len(kept)
        frame.fmodules = kept
    return removed


def _fix_missing_steps(project: Project, target: Optional[Target]) -> int:
    frame_ids = _frame_ids(project)
    removed = 0
    for anim in project.animations:
        if target and target != ("animation", anim.id):
            continue
        before_loop = sum(1 for af in anim.aframes[: anim.loop_start] if af.frame_id not in frame_ids)
        kept = [af for af in anim.aframes if af.frame_id in frame_ids]
        removed += len(anim.aframes) - len(kept)
        anim.aframes = kept
        anim.loop_start = max(0, min(anim.loop_start - before_loop, len(kept) - 1)) if kept else 0
    return removed


def _fix_unknown_events(project: Project, target: Optional[Target]) -> int:
    known = {t.id for t in project.event_types}
    removed = 0
    for anim in project.animations:
        if target and target != ("animation", anim.id):
            continue
        for af in anim.aframes:
            kept = [e for e in af.events if e.type_id in known]
            removed += len(af.events) - len(kept)
            af.events = kept
    return removed


def _fix_missing_follow_ups(project: Project, target: Optional[Target]) -> int:
    changed = 0
    for anim in project.animations:
        if target and target != ("animation", anim.id):
            continue
        if anim.next_animation_id and project.get_animation(anim.next_animation_id) is None:
            anim.next_animation_id = None
            changed += 1
    return changed


def _fix_missing_replacements(project: Project, target: Optional[Target]) -> int:
    module_ids = _module_ids(project)
    changed = 0
    for mapping in project.mappings:
        if target and target != ("mapping", mapping.id):
            continue
        for source in [s for s, d in mapping.map.items() if s in module_ids and d is not None and d not in module_ids]:
            del mapping.map[source]  # back to the original module
            changed += 1
    return changed


def _fix_dead_entries(project: Project, target: Optional[Target]) -> int:
    module_ids = _module_ids(project)
    changed = 0
    for mapping in project.mappings:
        if target and target != ("mapping", mapping.id):
            continue
        for source in [s for s in mapping.map if s not in module_ids]:
            del mapping.map[source]
            changed += 1
    return changed


def _fix_object_mappings(project: Project, target: Optional[Target]) -> int:
    mapping_ids = {m.id for m in project.mappings}
    changed = 0
    for scene in project.timeline_scenes:
        if target and target != ("scene", scene.id):
            continue
        for obj in scene.objects:
            if obj.mapping_id and obj.mapping_id != "original" and obj.mapping_id not in mapping_ids:
                obj.mapping_id = None
                changed += 1
    return changed


def _fix_missing_scene_sources(project: Project, target: Optional[Target]) -> int:
    """Objects and key swaps that show something deleted show nothing; their keys and motion stay."""
    changed = 0
    for scene in project.timeline_scenes:
        if target and target != ("scene", scene.id):
            continue
        for obj in scene.objects:
            for key in obj.keyframes:  # before the object: a key without a type of its own uses the object's
                if _scene_source_missing(project, key.source_type or obj.source_type, key.source_id):
                    key.source_type, key.source_id = None, None
                    changed += 1
            if _scene_source_missing(project, obj.source_type, obj.source_id):
                obj.source_type, obj.source_id = "none", None
                changed += 1
    return changed


def _fix_empty_hitboxes(project: Project, target: Optional[Target]) -> int:
    removed = 0
    for frame in project.frames:
        if target and target != ("frame", frame.id):
            continue
        kept = [cr for cr in frame.collision_rects if cr.rect[2] > 0 and cr.rect[3] > 0]
        removed += len(frame.collision_rects) - len(kept)
        frame.collision_rects = kept
    return removed


# key -> (button label, what it does to the project; returns how many things changed)
FIXES: Dict[str, Tuple[str, Callable[[Project, Optional[Target]], int]]] = {
    "remove-missing-parts": ("Remove those parts", _fix_missing_parts),
    "remove-missing-steps": ("Remove those steps", _fix_missing_steps),
    "remove-unknown-events": ("Remove those events", _fix_unknown_events),
    "clear-missing-follow-ups": ("Clear the follow-up", _fix_missing_follow_ups),
    "reset-missing-replacements": ("Show the original modules", _fix_missing_replacements),
    "drop-dead-entries": ("Remove those entries", _fix_dead_entries),
    "clear-missing-object-mappings": ("Inherit the mapping", _fix_object_mappings),
    "clear-missing-scene-sources": ("Clear those sources", _fix_missing_scene_sources),
    "remove-empty-hitboxes": ("Remove empty hitboxes", _fix_empty_hitboxes),
}


def fix(project: Project, issue: Issue) -> int:
    """Repair what an issue is about (only its target, or everywhere for project-wide issues)."""
    if not issue.fix or issue.fix not in FIXES:
        return 0
    return FIXES[issue.fix][1](project, issue.target)


def fix_all(project: Project, issues: Iterable[Issue]) -> int:
    """Repair every issue that has a fix. Returns how many things changed."""
    changed = 0
    for key in sorted({issue.fix for issue in issues if issue.fix in FIXES}):
        changed += FIXES[key][1](project, None)
    return changed
