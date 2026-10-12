"""Sheet repacking (Tools ▸ Optimize Sprite Sheet) and nested-frame combo optimisation.

Auto-modularisation lives in modularize.py.
"""
import wx
from itertools import combinations
from typing import List, Tuple, Dict, Optional, Any
import math
from rect_packer import MaxRectsBinPack
from models import Project, generate_id, Frame, FModule
import os


def optimize_modules(project: Project, module_ids: List[str], config: Dict, output_dir: str = None, name_hint: str = None) -> Tuple[bool, str]:
    """
    Optimizes the packing of specified modules into a new sprite sheet.
    Returns (Success, Message).
    """
    if not module_ids:
        return False, "No modules to optimize."

    modules = [project.get_module(mid) for mid in module_ids if project.get_module(mid)]
    if not modules:
        return False, "Modules not found."

    # Group by current image_id to verify they exist on the specific image if needed?
    # Actually, we can assume they might come from multiple images if we wanted to merge sheets.
    # But for now, let's assume they are from the selected image as per UI logic.
    
    # 1. Extract Source Bitmaps
    # We need to get the sub-bitmap for each module
    
    # Cache source images
    source_images = {} # asset_id -> wx.Image
    
    padding = config.get("padding", 2)
    border = config.get("border_padding", 2)
    max_w = config.get("max_w", 2048)
    max_h = config.get("max_h", 2048)
    allow_rotation = config.get("allow_rotation", False)
    
    # List of (w, h, module)
    rects_to_pack = []
    
    for mod in modules:
        if mod.image_id not in source_images:
            asset = project.get_image(mod.image_id)
            if not asset:
                continue # Skip modules with missing assets
            
            # Load wx.Image
            img = wx.Image(asset.file_path)
            if not img.IsOk():
                continue
            
            # Apply transparency if needed?
            # Ideally we work with RGBA buffers.
            if not img.HasAlpha() and asset.transparent_color:
                img.SetMaskColour(*asset.transparent_color)
                img.InitAlpha() # Converts mask to alpha
            
            source_images[mod.image_id] = img

        # Validate size
        if mod.rect[2] <= 0 or mod.rect[3] <= 0:
            # Skip packing for empty modules, BUT preserve them as "null" modules (e.g. for hiding)
            # We will update their image_id later so they don't hold onto the old image.
            continue

        rects_to_pack.append((mod.rect[2] + padding, mod.rect[3] + padding, mod))

    if not rects_to_pack:
         return False, "No valid modules/images found."

    # 2. Pack
    # 2. Pack - Iterative Sizing with Multi-Heuristic
    heuristics = [
        MaxRectsBinPack.FreeRectChoiceHeuristic.RectBestShortSideFit,
        MaxRectsBinPack.FreeRectChoiceHeuristic.RectBestLongSideFit,
        MaxRectsBinPack.FreeRectChoiceHeuristic.RectBestAreaFit,
        MaxRectsBinPack.FreeRectChoiceHeuristic.RectBottomLeftRule,
        MaxRectsBinPack.FreeRectChoiceHeuristic.RectContactPointRule
    ]
    
    # Sort modules by max dimension descending for better stability
    rects_to_pack.sort(key=lambda x: max(x[0], x[1]), reverse=True)
    
    # Determine minimum starting dimensions
    total_area = sum(w*h for w, h, _ in rects_to_pack)
    max_mod_w = max(w for w, h, _ in rects_to_pack) if rects_to_pack else 0
    max_mod_h = max(h for w, h, _ in rects_to_pack) if rects_to_pack else 0
    
    import math
    min_side = int(math.ceil(math.sqrt(total_area)))
    start_dim = max(min_side, max_mod_w, max_mod_h)
    
    # Quantize start_dim to next multiple of 32 for cleaner steps
    start_dim = ((start_dim + 31) // 32) * 32
    
    best_result = None
    min_used_area_overall = float('inf')
    
    current_dim = start_dim
    step_size = 32
    
    # Upper bound protection
    limit_w = max_w
    limit_h = max_h
    
    while current_dim <= max(limit_w, limit_h):
        # We try a square bin of current_dim (clamped to limits)
        # Note: We can allow rectangular growth, but square is a robust strategy for "texture atlases".
        # If current_dim > limit_w, we clamp w but let h grow? 
        # For simplicity, let's keep it squareish but respect max limits.
        
        test_w = min(current_dim, limit_w)
        test_h = min(current_dim, limit_h)
        
        # If we reached limits and fail, we break loop
        # We need to track if THIS size produced ANY valid results
        valid_results_for_dim = []
        
        for h_type in heuristics:
            packer = MaxRectsBinPack(test_w, test_h, allow_flip=allow_rotation)
            current_packed = []
            failed = False
            
            # Track bounds
            mx = 0
            my = 0
            
            for w, h, mod in rects_to_pack:
                packed_rect = packer.insert(w, h, h_type)
                if packed_rect.height == 0:
                    failed = True
                    break
                current_packed.append((packed_rect, mod))
                mx = max(mx, packed_rect.x + packed_rect.width)
                my = max(my, packed_rect.y + packed_rect.height)
                
            if not failed:
                area = mx * my
                valid_results_for_dim.append((area, current_packed))
        
        if valid_results_for_dim:
            # We found at least one fit at this dimension size!
            # Pick the best one (smallest used area)
            valid_results_for_dim.sort(key=lambda x: x[0])
            best_at_dim = valid_results_for_dim[0]
            
            best_result = best_at_dim[1]
            break # Stop growing! We found the smallest dimension that fits.
            
        # Prepare next step
        if test_w == limit_w and test_h == limit_h:
            # Cannot grow anymore
            break
            
        current_dim += step_size

    if not best_result:
        return False, "Could not pack modules. Sheet size limit reached or modules too large."
        
    packed_modules = best_result
        
    # 3. Generate New Image
    # Determine actual size needed
    final_w = 0
    final_h = 0
    for r, _ in packed_modules:
        final_w = max(final_w, r.x + r.width)
        final_h = max(final_h, r.y + r.height)
        
    # Add border padding?
    # The 'border_padding' from config is usually for the edge of the sheet.
    # Our packer started at 0,0.
    # We should offset everything by 'border' and increase size by 2*border.
    
    final_w += 2 * border
    final_h += 2 * border
    
    # Create empty bitmap
    out_img = wx.Image(final_w, final_h)
    out_img.InitAlpha()
    # Set completely transparent
    # wx.Image default is black. Alpha default is ? usually 0 if InitAlpha called fresh?
    # Let's ensure it.
    out_img.SetAlpha(bytes([0]*(final_w*final_h)))
    
    # Blit sub-images
    # We need to iterate and place each module.
    
    for r, mod in packed_modules:
        src_img = source_images[mod.image_id]
        
        # Source Rect
        ox, oy, ow, oh = mod.rect
        # Extraction might fail if out of bounds? Module rects should be valid.
        sub = src_img.GetSubImage(wx.Rect(ox, oy, ow, oh))
        
        # Dest Rect
        # r is the packed rect (including intra-module padding). 
        # We need to strip the padding we added (which was appended to width/height).
        # We treated 'padding' as "space dedicated to this module".
        # Let's center the module in the packed rect or top-left?
        # Usually padding is simply "gap".
        # If we asked for W+P, H+P...
        # Let's just place at r.x + border, r.y + border. 
        # But wait, r includes padding.
        # If we place at r.x, the next module might be at r.x + r.width.
        # So the gap is effectively built-in on the right/bottom?
        # It's cleaner to just not add padding to the rect size, but modify `insert` to check gaps, 
        # but MaxRects doesn't support gaps natively.
        # So inflating size is the standard way.
        # We will place the image at (r.x + border, r.y + border).
        # The visual gap will be the `padding` value on right/bottom edges mostly.
        
        dest_x = r.x + border
        dest_y = r.y + border
        
        # Check for rotation
        # If r.width != (mod.rect[2] + padding), it means it was flipped?
        # Wait, comparison with float/int?
        rotated = False
        if allow_rotation:
             # Check if dimensions are swapped
             # We also check if w != h to avoid treating squares as rotated 
             # (Packer prefers upright for ties, so squares stay upright)
             if (r.width == (mod.rect[3] + padding) and 
                 r.width != (mod.rect[2] + padding)):
                 rotated = True
        
        if rotated:
             sub = sub.Rotate90(clockwise=True)
             pass
        
        out_img.Paste(sub, dest_x, dest_y)
        
        # 4. Update Module Data
        # We need to update the module's rect and image_id to the new sheet.
        # BUT we shouldn't modify the `mod` object yet until we save the image successfully.
        # We'll do a second pass after saving.
        
    # generate unique filename
    if output_dir and os.path.exists(output_dir):
        base_dir = output_dir
    else:
        base_dir = os.path.dirname(project.images[0].file_path) if project.images else "."
    
    if name_hint:
        # Counter-based naming: name_hint_1.png, name_hint_2.png...
        counter = 1
        filename = f"{name_hint}.png"
        while os.path.exists(os.path.join(base_dir, filename)):
             filename = f"{name_hint}_{counter}.png"
             counter += 1
    else:
        filename = f"optimized_sheet_{generate_id('img')}.png"
        
    out_path = os.path.join(base_dir, filename)
    
    try:
        out_img.SaveFile(out_path, wx.BITMAP_TYPE_PNG)
    except Exception as e:
        return False, f"Failed to save image: {e}"
        
    # Create new Asset
    new_asset = project.create_image(out_path, final_w, final_h)
    
    # 5. Commit Module Changes
    for r, mod in packed_modules:
        mod.image_id = new_asset.id
        
        # Calculate new rect on the sheet
        dest_x = r.x + border
        dest_y = r.y + border
        
        w_orig = mod.rect[2]
        h_orig = mod.rect[3]
        
        # Check if rotated (SAME logic as above)
        is_rotated = False
        if allow_rotation:
             if (r.width == (h_orig + padding) and 
                 r.width != (w_orig + padding)):
                 is_rotated = True
        
        if is_rotated:
             # It is rotated 90 CW.
             # Rect: w=h_orig, h=w_orig on the sheet
             mod.rect = (dest_x, dest_y, h_orig, w_orig)
             mod.rotated = True
             
             # Pivot remains logical (original px, py relative to upright image)
             # We rely on the renderer to un-rotate the image 
             # and use the original pivot.
        else:
             mod.rect = (dest_x, dest_y, w_orig, h_orig)
             mod.rotated = False
             
    # 5b. Update Skipped Modules (0x0 or otherwise skipped)
    # They should also point to the new image so we can delete the old one.
    packed_mods_set = {m.id for _, m in packed_modules}
    for mod in modules:
        if mod.id not in packed_mods_set:
            # It was skipped (likely 0x0). Repoint it.
            mod.image_id = new_asset.id
            # Leave rect as is (presumably 0x0)
             
    # 6. Cleanup Old Images
    # Find all images that are no longer used by any module
    used_image_ids = {m.image_id for m in project.modules}
    # Reassign the list entirely to filter out unused images
    project.images = [img for img in project.images if img.id in used_image_ids]
    
    return True, "Optimization successful. Old images removed."


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
