"""Sheet repacking (Tools ▸ Optimize Sprite Sheet) and nested-frame combo optimisation (wx-free).

Auto-modularisation lives in modularize.py.
"""
import math
import os
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

import compositor
import palettes
from models import FModule, Frame, Project, generate_id
from rect_packer import MaxRectsBinPack

HEURISTICS = (
    MaxRectsBinPack.FreeRectChoiceHeuristic.RectBestShortSideFit,
    MaxRectsBinPack.FreeRectChoiceHeuristic.RectBestLongSideFit,
    MaxRectsBinPack.FreeRectChoiceHeuristic.RectBestAreaFit,
    MaxRectsBinPack.FreeRectChoiceHeuristic.RectBottomLeftRule,
    MaxRectsBinPack.FreeRectChoiceHeuristic.RectContactPointRule,
)


def optimize_modules(project: Project, module_ids: List[str], config: Dict, output_dir: Optional[str] = None,
                     name_hint: Optional[str] = None) -> Tuple[bool, str]:
    """Repack these modules' pixels into a new, smaller sheet and point the modules at it. Returns (success, message).

    Every module keeps its pixels and its pivot: the new sheet holds each module's upright image (the key colour cut
    out), turned a quarter clockwise where ``allow_rotation`` packs it so (``Module.rotated``). Modules without
    pixels (0×0) move to the new sheet too; images the repack left without modules leave the project (their files
    stay)."""
    from PIL import Image

    modules = [m for m in (project.get_module(mid) for mid in module_ids) if m is not None]
    if not modules:
        return False, "No modules to optimize."
    padding = int(config.get("padding", 2))
    border = int(config.get("border_padding", 2))
    max_w = int(config.get("max_w", 2048))
    max_h = int(config.get("max_h", 2048))
    allow_rotation = bool(config.get("allow_rotation", False))

    # Each module's upright image exactly as the renderers take it (key colour cut out, packed ones turned back):
    # (padded width, padded height, module, image).
    full_images: Dict[str, Any] = {}
    module_images: Dict[str, Any] = {}
    rects_to_pack: List[Tuple[int, int, Any, Any]] = []
    empty = []
    for mod in modules:
        asset = project.get_image(mod.image_id) if mod.type == "MD_IMAGE" else None
        if asset is None or not os.path.exists(asset.file_path):
            continue  # shapes and modules of missing images stay as they are
        if int(mod.rect[2]) <= 0 or int(mod.rect[3]) <= 0:
            empty.append(mod)  # kept, without pixels (e.g. to hide parts in a mapping)
            continue
        try:
            image = compositor.load_module_rgba(project, mod, full_images, module_images)
        except (OSError, ValueError):
            continue
        rects_to_pack.append((image.width + padding, image.height + padding, mod, image))
    if not rects_to_pack:
        return False, "No valid modules/images found."
    used_palettes = {palettes.palette_of(project.get_image(mod.image_id)) for _w, _h, mod, _img in rects_to_pack}
    if len(used_palettes) > 1:
        return False, ("These images use different palettes, and one sheet has one palette: optimize them one image "
                       "at a time (Local).")

    packed = _pack(rects_to_pack, max_w, max_h, allow_rotation)
    if packed is None:
        return False, "Could not pack modules. Sheet size limit reached or modules too large."

    final_w = max(r.x + r.width for r, _entry in packed) + 2 * border
    final_h = max(r.y + r.height for r, _entry in packed) + 2 * border
    sheet = Image.new("RGBA", (final_w, final_h), (0, 0, 0, 0))
    placed = []
    for r, (_w, _h, mod, image) in packed:
        # The packer reports a quarter turn as swapped sides (a square never turns).
        turned = allow_rotation and image.width != image.height and r.width == image.height + padding
        stored = image.transpose(Image.Transpose.ROTATE_270) if turned else image
        sheet.paste(stored, (r.x + border, r.y + border))
        placed.append((mod, (r.x + border, r.y + border, stored.width, stored.height), turned))

    base_dir = output_dir if output_dir and os.path.isdir(output_dir) else (
        os.path.dirname(project.images[0].file_path) if project.images else ".")
    if name_hint:
        filename, counter = f"{name_hint}.png", 1
        while os.path.exists(os.path.join(base_dir, filename)):
            filename, counter = f"{name_hint}_{counter}.png", counter + 1
    else:
        filename = f"optimized_sheet_{generate_id('img')}.png"
    out_path = os.path.join(base_dir, filename)
    try:
        sheet.save(out_path, "PNG")
    except (OSError, ValueError) as exc:
        return False, f"Failed to save image: {exc}"

    sources = {mod.image_id for mod, _rect, _turned in placed} | {mod.image_id for mod in empty}
    new_asset = project.create_image(out_path, final_w, final_h)
    new_asset.palette = used_palettes.pop()
    for mod, rect, turned in placed:
        mod.image_id, mod.rect, mod.rotated = new_asset.id, rect, turned  # the pivot stays: it is the upright one's
    for mod in empty:
        mod.image_id = new_asset.id
    still_used = {m.image_id for m in project.modules}
    project.images = [img for img in project.images if img.id not in sources or img.id in still_used]
    return True, "Optimization successful. Old images removed."


def _pack(rects_to_pack: List[Tuple[int, int, Any, Any]], max_w: int, max_h: int, allow_rotation: bool) -> Optional[list]:
    """The smallest square-ish bin (growing in 32 px steps) any heuristic fits everything into: [(rect, entry)]."""
    rects_to_pack = sorted(rects_to_pack, key=lambda entry: max(entry[0], entry[1]), reverse=True)
    total_area = sum(w * h for w, h, _mod, _img in rects_to_pack)
    start = max(int(math.ceil(math.sqrt(total_area))), max(w for w, *_ in rects_to_pack), max(h for _w, h, *_ in rects_to_pack))
    dim = ((start + 31) // 32) * 32
    while dim <= max(max_w, max_h):
        test_w, test_h = min(dim, max_w), min(dim, max_h)
        best = None
        for heuristic in HEURISTICS:
            packer = MaxRectsBinPack(test_w, test_h, allow_flip=allow_rotation)
            result = []
            for entry in rects_to_pack:
                rect = packer.insert(entry[0], entry[1], heuristic)
                if rect.height == 0:
                    break
                result.append((rect, entry))
            else:
                area = max(r.x + r.width for r, _e in result) * max(r.y + r.height for r, _e in result)
                if best is None or area < best[0]:
                    best = (area, result)
        if best is not None:
            return best[1]
        if test_w == max_w and test_h == max_h:
            return None
        dim += 32
    return None


def _rot_key(deg: float) -> int:
    return int(round(float(deg) * 1000.0))


def _combo_signature_and_anchor(fmods: List[FModule]) -> Tuple[Tuple[Tuple[Any, ...], ...], Tuple[int, int]]:
    min_x = min(int(fm.position[0]) for fm in fmods)
    min_y = min(int(fm.position[1]) for fm in fmods)
    items: List[Tuple[Any, ...]] = []
    for fm in fmods:
        items.append(
            (
                fm.ref_id,
                bool(fm.flip_x),
                bool(fm.flip_y),
                _rot_key(fm.rotation_degrees),
                int(fm.position[0]) - min_x,
                int(fm.position[1]) - min_y,
            )
        )
    items.sort()
    return tuple(items), (min_x, min_y)


def _module_only_frame_signature(frame: Frame) -> Optional[Tuple[Tuple[Any, ...], ...]]:
    if not frame.fmodules:
        return None
    if any(fm.ref_type != "module" for fm in frame.fmodules):
        return None
    sig, _anchor = _combo_signature_and_anchor(frame.fmodules)
    return sig


def optimize_nested_frame_combos(project: Project, config: Optional[Dict] = None) -> Tuple[bool, str]:
    """
    Detect repeated module groups with identical relative transforms, extract them into
    helper frames, and replace occurrences with nested frame references.
    """
    cfg = config or {}
    min_combo_size = max(2, int(cfg.get("min_combo_size", 3)))
    max_combo_size = max(min_combo_size, int(cfg.get("max_combo_size", 4)))
    min_support = max(2, int(cfg.get("min_support", 4)))
    min_net_savings = int(cfg.get("min_net_savings", 2))
    max_modules_per_frame = max(3, int(cfg.get("max_modules_per_frame", 18)))
    helper_prefix = str(cfg.get("helper_prefix", "Combo"))

    source_frames = list(project.frames)
    if not source_frames:
        return False, "No frames available."

    source_frames_to_mine = [f for f in source_frames if not f.name.startswith(helper_prefix)]
    if not source_frames_to_mine:
        return False, "No non-helper frames available."

    groups: Dict[Tuple[Tuple[Any, ...], ...], List[Dict[str, Any]]] = {}
    skipped_large_frames = 0

    for frame in source_frames_to_mine:
        module_fmods = [fm for fm in frame.fmodules if fm.ref_type == "module"]
        if len(module_fmods) < min_combo_size:
            continue
        if len(module_fmods) > max_modules_per_frame:
            skipped_large_frames += 1
            continue

        n = len(module_fmods)
        for k in range(min_combo_size, min(max_combo_size, n) + 1):
            for idxs in combinations(range(n), k):
                combo = [module_fmods[i] for i in idxs]
                sig, anchor = _combo_signature_and_anchor(combo)
                occ = {
                    "frame_id": frame.id,
                    "ids": tuple(sorted(fm.id for fm in combo)),
                    "anchor": anchor,
                    "k": k,
                }
                groups.setdefault(sig, []).append(occ)

    candidates: List[Dict[str, Any]] = []
    for sig, occs in groups.items():
        uniq: Dict[Tuple[str, Tuple[str, ...]], Dict[str, Any]] = {}
        for occ in occs:
            uniq[(occ["frame_id"], occ["ids"])] = occ
        unique_occs = list(uniq.values())

        support = len(unique_occs)
        k = len(sig)
        if support < min_support:
            continue
        net_savings = (k - 1) * support - k
        if net_savings <= 0 or net_savings < min_net_savings:
            continue

        candidates.append(
            {
                "sig": sig,
                "k": k,
                "support": support,
                "net_savings": net_savings,
                "occs": unique_occs,
            }
        )

    if not candidates:
        if skipped_large_frames > 0:
            return False, (
                f"No beneficial repeated combos found. Skipped {skipped_large_frames} frames "
                f"that exceed {max_modules_per_frame} module refs."
            )
        return False, "No beneficial repeated combos found."

    candidates.sort(
        key=lambda c: (
            -int(c["net_savings"]),
            -int(c["k"]),
            -int(c["support"]),
        )
    )

    existing_helper_by_sig: Dict[Tuple[Tuple[Any, ...], ...], str] = {}
    for frame in project.frames:
        if not frame.name.startswith(helper_prefix):
            continue
        sig = _module_only_frame_signature(frame)
        if sig:
            existing_helper_by_sig.setdefault(sig, frame.id)

    consumed_ids_by_frame: Dict[str, set] = {}
    replacements_by_frame: Dict[str, List[Dict[str, Any]]] = {}

    helpers_created = 0
    helpers_reused = 0
    occurrences_replaced = 0
    module_refs_replaced = 0

    for cand in candidates:
        non_conflicting: List[Dict[str, Any]] = []
        for occ in cand["occs"]:
            frame_used = consumed_ids_by_frame.setdefault(occ["frame_id"], set())
            occ_ids = set(occ["ids"])
            if frame_used.intersection(occ_ids):
                continue
            non_conflicting.append(occ)

        support = len(non_conflicting)
        if support < min_support:
            continue

        k = int(cand["k"])
        net_savings = (k - 1) * support - k
        if net_savings <= 0 or net_savings < min_net_savings:
            continue

        sig = cand["sig"]
        helper_frame_id = existing_helper_by_sig.get(sig)
        if not helper_frame_id:
            helper_frame = Frame(
                id=generate_id("frm"),
                name=f"{helper_prefix} {len(project.frames) + 1}",
                fmodules=[],
            )
            for item in sig:
                helper_frame.fmodules.append(
                    FModule(
                        id=generate_id("fm"),
                        ref_type="module",
                        ref_id=str(item[0]),
                        position=(int(item[4]), int(item[5])),
                        flip_x=bool(item[1]),
                        flip_y=bool(item[2]),
                        rotation_degrees=float(int(item[3]) / 1000.0),
                    )
                )
            project.frames.append(helper_frame)
            helper_frame_id = helper_frame.id
            existing_helper_by_sig[sig] = helper_frame_id
            helpers_created += 1
        else:
            helpers_reused += 1

        for occ in non_conflicting:
            frame_used = consumed_ids_by_frame.setdefault(occ["frame_id"], set())
            occ_ids = set(occ["ids"])
            if frame_used.intersection(occ_ids):
                continue
            frame_used.update(occ_ids)
            replacements_by_frame.setdefault(occ["frame_id"], []).append(
                {
                    "ids": occ_ids,
                    "anchor": occ["anchor"],
                    "helper_id": helper_frame_id,
                }
            )
            occurrences_replaced += 1
            module_refs_replaced += k

    if not replacements_by_frame:
        return False, "No non-overlapping beneficial combo replacements found."

    frame_refs_inserted = 0
    for frame_id, repls in replacements_by_frame.items():
        frame = project.get_frame(frame_id)
        if not frame:
            continue

        id_to_idx = {fm.id: idx for idx, fm in enumerate(frame.fmodules)}
        prepared: List[Dict[str, Any]] = []
        for repl in repls:
            idxs = [id_to_idx[mid] for mid in repl["ids"] if mid in id_to_idx]
            if not idxs:
                continue
            repl2 = dict(repl)
            repl2["start_idx"] = min(idxs)
            prepared.append(repl2)

        if not prepared:
            continue

        prepared.sort(key=lambda r: int(r["start_idx"]))
        skip_ids = set()
        insert_by_idx: Dict[int, List[Dict[str, Any]]] = {}
        for repl in prepared:
            skip_ids.update(repl["ids"])
            insert_by_idx.setdefault(int(repl["start_idx"]), []).append(repl)

        new_fmods: List[FModule] = []
        for idx, fm in enumerate(frame.fmodules):
            if idx in insert_by_idx:
                for repl in insert_by_idx[idx]:
                    new_fmods.append(
                        FModule(
                            id=generate_id("fm"),
                            ref_type="frame",
                            ref_id=str(repl["helper_id"]),
                            position=(int(repl["anchor"][0]), int(repl["anchor"][1])),
                            flip_x=False,
                            flip_y=False,
                            rotation_degrees=0.0,
                        )
                    )
                    frame_refs_inserted += 1
            if fm.id in skip_ids:
                continue
            new_fmods.append(fm)

        frame.fmodules = new_fmods

    msg = (
        f"Nested combo optimization complete. Replaced {occurrences_replaced} occurrences "
        f"({module_refs_replaced} module refs -> {frame_refs_inserted} frame refs), "
        f"created {helpers_created} helper frames"
    )
    if helpers_reused > 0:
        msg += f", reused {helpers_reused} existing helper frames"
    if skipped_large_frames > 0:
        msg += f". Skipped {skipped_large_frames} large frames (> {max_modules_per_frame} modules)."
    else:
        msg += "."
    return True, msg
