"""Mappings tab operations without wx: replacement states, bulk matching, mapping list management."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

from models import Frame, ModuleMapping, Project, generate_id

ORIGINAL, HIDDEN, REPLACED, MISSING = "original", "hidden", "replaced", "missing"


def state(project: Project, mapping: ModuleMapping, module_id: str) -> str:
    if module_id not in mapping.map:
        return ORIGINAL
    target = mapping.map[module_id]
    if target is None:
        return HIDDEN
    return REPLACED if project.get_module(target) is not None else MISSING


def assign(mapping: ModuleMapping, module_ids: Iterable[str], target_id: Optional[str]) -> int:
    """Replace modules with ``target_id`` (None hides them). Mapping a module to itself resets it."""
    changed = 0
    for module_id in module_ids:
        if target_id == module_id:
            changed += int(mapping.map.pop(module_id, "absent") != "absent")
            continue
        if mapping.map.get(module_id, "absent") != target_id:
            mapping.map[module_id] = target_id
            changed += 1
    return changed


def reset(mapping: ModuleMapping, module_ids: Iterable[str]) -> int:
    changed = 0
    for module_id in module_ids:
        if module_id in mapping.map:
            del mapping.map[module_id]
            changed += 1
    return changed


def counts(project: Project, mapping: ModuleMapping) -> Tuple[int, int, int]:
    """(replaced, hidden, broken) entries; entries of deleted source modules are ignored."""
    replaced = hidden = broken = 0
    for source, target in mapping.map.items():
        if project.get_module(source) is None:
            continue
        if target is None:
            hidden += 1
        elif project.get_module(target) is None:
            broken += 1
        else:
            replaced += 1
    return replaced, hidden, broken


def describe(project: Project, mapping: ModuleMapping) -> str:
    replaced, hidden, broken = counts(project, mapping)
    bits = []
    if replaced:
        bits.append(f"{replaced} replaced")
    if hidden:
        bits.append(f"{hidden} hidden")
    if broken:
        bits.append(f"{broken} missing")
    return " · ".join(bits) if bits else "no changes"


def match_by_position(project: Project, mapping: ModuleMapping, source_image: str, target_image: str) -> int:
    """Map every module of one image to the module at the same rect on another image (a recoloured or
    re-dressed copy of the sheet). Returns how many modules were mapped."""
    targets: Dict[Tuple[int, ...], str] = {}
    for m in project.modules:
        if m.type == "MD_IMAGE" and m.image_id == target_image:
            targets.setdefault(tuple(m.rect), m.id)
    sources = [m for m in project.modules if m.type == "MD_IMAGE" and m.image_id == source_image]
    mapped = 0
    for m in sources:
        target = targets.get(tuple(m.rect))
        if target is not None and target != m.id:
            mapping.map[m.id] = target
            mapped += 1
    return mapped


def match_by_name(project: Project, mapping: ModuleMapping, find: str, replace: str,
                  module_ids: Optional[Iterable[str]] = None) -> List[Tuple[str, str]]:
    """Map modules whose name contains ``find`` to the module named with ``replace`` instead
    (e.g. "_red" → "_blue"). Returns the (source, target) pairs that were mapped."""
    if not find:
        return []
    by_name: Dict[str, str] = {}
    for m in project.modules:
        by_name.setdefault(m.name, m.id)
    allowed: Optional[Set[str]] = set(module_ids) if module_ids is not None else None
    pairs = []
    for m in project.modules:
        if allowed is not None and m.id not in allowed:
            continue
        if find not in m.name:
            continue
        target = by_name.get(m.name.replace(find, replace))
        if target is not None and target != m.id:
            mapping.map[m.id] = target
            pairs.append((m.id, target))
    return pairs


def frames_using(project: Project, module_ids: Iterable[str]) -> List[Frame]:
    """Frames that show any of the modules, directly or through nested frames."""
    wanted = set(module_ids)
    direct = {f.id for f in project.frames if any(fm.ref_type == "module" and fm.ref_id in wanted for fm in f.fmodules)}
    result = set(direct)
    changed = True
    while changed:
        changed = False
        for f in project.frames:
            if f.id not in result and any(fm.ref_type == "frame" and fm.ref_id in result for fm in f.fmodules):
                result.add(f.id)
                changed = True
    return [f for f in project.frames if f.id in result]


def unique_name(project: Project, base: str) -> str:
    used = {m.name for m in project.mappings}
    name, n = base, 2
    while name in used:
        name = f"{base} ({n})"
        n += 1
    return name


def new_mapping(project: Project, after_id: Optional[str] = None) -> ModuleMapping:
    mapping = ModuleMapping(id=generate_id("map"), name=unique_name(project, f"Mapping {len(project.mappings) + 1}"))
    after = next((m for m in project.mappings if m.id == after_id), None)
    project.mappings.insert(project.mappings.index(after) + 1 if after else len(project.mappings), mapping)
    return mapping


def duplicate_mapping(project: Project, mapping_id: str) -> Optional[ModuleMapping]:
    source = next((m for m in project.mappings if m.id == mapping_id), None)
    if source is None:
        return None
    copy = ModuleMapping(id=generate_id("map"), name=unique_name(project, f"{source.name} copy"), map=dict(source.map))
    project.mappings.insert(project.mappings.index(source) + 1, copy)
    return copy


def delete_mapping(project: Project, mapping_id: str) -> None:
    project.mappings = [m for m in project.mappings if m.id != mapping_id]
    if project.active_mapping is not None and project.active_mapping.id == mapping_id:
        project.active_mapping = None


def move_mapping(project: Project, mapping_id: str, before_id: Optional[str]) -> None:
    mapping = next((m for m in project.mappings if m.id == mapping_id), None)
    if mapping is None or mapping_id == before_id:
        return
    project.mappings.remove(mapping)
    anchor = next((m for m in project.mappings if m.id == before_id), None) if before_id else None
    project.mappings.insert(project.mappings.index(anchor) if anchor else len(project.mappings), mapping)


def drop_dead_entries(project: Project, mapping: ModuleMapping) -> int:
    """Remove entries whose source module no longer exists."""
    dead = [k for k in mapping.map if project.get_module(k) is None]
    for k in dead:
        del mapping.map[k]
    return len(dead)
