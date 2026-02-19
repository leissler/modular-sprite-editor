import hashlib
import wx
from collections import deque
from itertools import combinations
from typing import List, Tuple, Dict, Optional, Any
import math
from rect_packer import MaxRectsBinPack
from models import Project, Module, generate_id, ImageAsset, Frame, FModule
from PIL import Image
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

def _load_sheet_rgba(asset: ImageAsset) -> Image.Image:
    img = Image.open(asset.file_path).convert("RGBA")
    if not asset.transparent_color:
        return img

    tr, tg, tb = asset.transparent_color
    pixels = []
    for r, g, b, a in img.getdata():
        if r == tr and g == tg and b == tb:
            pixels.append((r, g, b, 0))
        else:
            pixels.append((r, g, b, a))
    img.putdata(pixels)
    return img


def _build_alpha_mask(img: Image.Image, alpha_threshold: int) -> List[List[bool]]:
    w, h = img.size
    alpha = img.getchannel("A").tobytes()
    mask: List[List[bool]] = []
    for y in range(h):
        row_start = y * w
        row = alpha[row_start : row_start + w]
        mask.append([px > alpha_threshold for px in row])
    return mask


def _build_integral(mask: List[List[bool]]) -> List[List[int]]:
    h = len(mask)
    w = len(mask[0]) if h > 0 else 0
    integral = [[0] * (w + 1) for _ in range(h + 1)]
    for y in range(h):
        row_sum = 0
        for x in range(w):
            row_sum += 1 if mask[y][x] else 0
            integral[y + 1][x + 1] = integral[y][x + 1] + row_sum
    return integral


def _count_opaque(integral: List[List[int]], x: int, y: int, w: int, h: int) -> int:
    if w <= 0 or h <= 0:
        return 0
    x2 = x + w
    y2 = y + h
    return (
        integral[y2][x2]
        - integral[y][x2]
        - integral[y2][x]
        + integral[y][x]
    )


def _tight_bbox(
    mask: List[List[bool]], x: int, y: int, w: int, h: int
) -> Optional[Tuple[int, int, int, int]]:
    min_x = x + w
    min_y = y + h
    max_x = -1
    max_y = -1

    for yy in range(y, y + h):
        row = mask[yy]
        for xx in range(x, x + w):
            if row[xx]:
                if xx < min_x:
                    min_x = xx
                if yy < min_y:
                    min_y = yy
                if xx > max_x:
                    max_x = xx
                if yy > max_y:
                    max_y = yy

    if max_x < min_x or max_y < min_y:
        return None
    return (min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def _connected_component_boxes(mask: List[List[bool]]) -> List[Tuple[int, int, int, int]]:
    h = len(mask)
    w = len(mask[0]) if h > 0 else 0
    visited = [[False] * w for _ in range(h)]
    components: List[Tuple[int, int, int, int]] = []
    neighbors = [
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (1, -1), (-1, 1), (1, 1),
    ]

    for y in range(h):
        for x in range(w):
            if visited[y][x] or not mask[y][x]:
                continue

            q = deque([(x, y)])
            visited[y][x] = True
            min_x = max_x = x
            min_y = max_y = y

            while q:
                cx, cy = q.popleft()
                if cx < min_x:
                    min_x = cx
                if cy < min_y:
                    min_y = cy
                if cx > max_x:
                    max_x = cx
                if cy > max_y:
                    max_y = cy

                for dx, dy in neighbors:
                    nx = cx + dx
                    ny = cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx] and mask[ny][nx]:
                        visited[ny][nx] = True
                        q.append((nx, ny))

            components.append((min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))

    return components


def _row_projection(integral: List[List[int]], x: int, y: int, w: int, h: int) -> List[int]:
    return [_count_opaque(integral, x, y + ry, w, 1) for ry in range(h)]


def _col_projection(integral: List[List[int]], x: int, y: int, w: int, h: int) -> List[int]:
    return [_count_opaque(integral, x + cx, y, 1, h) for cx in range(w)]


def _best_gap_split(counts: List[int]) -> Optional[int]:
    n = len(counts)
    run_start: Optional[int] = None
    best_start = -1
    best_end = -1

    for idx, val in enumerate(counts + [1]):  # Sentinel
        if val == 0 and run_start is None:
            run_start = idx
            continue
        if val != 0 and run_start is not None:
            run_end = idx
            if run_start > 0 and run_end < n:
                if (run_end - run_start) > (best_end - best_start):
                    best_start = run_start
                    best_end = run_end
            run_start = None

    if best_start < 0:
        return None

    split = (best_start + best_end) // 2
    if 0 < split < n:
        return split
    return None


def _best_sparse_split(counts: List[int]) -> Optional[int]:
    n = len(counts)
    if n <= 2:
        return None

    candidates = list(range(1, n - 1))
    if not candidates:
        return None

    min_count = min(counts[i] for i in candidates)
    center = (n - 1) / 2.0
    best_idx = min(
        (i for i in candidates if counts[i] == min_count),
        key=lambda i: abs(i - center),
    )
    split = best_idx + 1
    if 0 < split < n:
        return split
    return None


def _split_sparse_region(
    mask: List[List[bool]],
    integral: List[List[int]],
    rect: Tuple[int, int, int, int],
    min_density: float,
    min_part_area: int,
    min_split_side: int,
    max_split_depth: int,
    depth: int = 0,
) -> List[Tuple[int, int, int, int]]:
    x, y, w, h = rect
    opaque = _count_opaque(integral, x, y, w, h)
    if opaque <= 0:
        return []

    tight = _tight_bbox(mask, x, y, w, h)
    if not tight:
        return []
    if tight != rect:
        return _split_sparse_region(
            mask,
            integral,
            tight,
            min_density,
            min_part_area,
            min_split_side,
            max_split_depth,
            depth,
        )

    area = max(1, w * h)
    density = opaque / float(area)
    if (
        depth >= max_split_depth
        or w <= min_split_side
        or h <= min_split_side
        or opaque <= min_part_area
        or density >= min_density
    ):
        return [rect]

    row_counts = _row_projection(integral, x, y, w, h)
    col_counts = _col_projection(integral, x, y, w, h)
    children: Optional[List[Tuple[int, int, int, int]]] = None

    # Prefer clean cuts first where rows/cols are fully empty.
    y_split = _best_gap_split(row_counts)
    if y_split is not None:
        top_h = y_split
        bottom_h = h - y_split
        if top_h > 0 and bottom_h > 0:
            children = [(x, y, w, top_h), (x, y + y_split, w, bottom_h)]

    if children is None:
        x_split = _best_gap_split(col_counts)
        if x_split is not None:
            left_w = x_split
            right_w = w - x_split
            if left_w > 0 and right_w > 0:
                children = [(x, y, left_w, h), (x + x_split, y, right_w, h)]

    # If there are no empty gaps, split at sparsest internal line.
    if children is None:
        y_sparse = _best_sparse_split(row_counts) if h > 2 else None
        x_sparse = _best_sparse_split(col_counts) if w > 2 else None

        split_h = False
        split_v = False

        if y_sparse is not None and x_sparse is not None:
            row_min = min(row_counts[1:-1]) if h > 2 else row_counts[0]
            col_min = min(col_counts[1:-1]) if w > 2 else col_counts[0]
            row_ratio = row_min / float(max(1, w))
            col_ratio = col_min / float(max(1, h))
            if row_ratio <= col_ratio:
                split_h = True
            else:
                split_v = True
        elif y_sparse is not None:
            split_h = True
        elif x_sparse is not None:
            split_v = True

        if split_h and y_sparse is not None:
            top_h = y_sparse
            bottom_h = h - y_sparse
            if top_h > 0 and bottom_h > 0:
                children = [(x, y, w, top_h), (x, y + y_sparse, w, bottom_h)]
        elif split_v and x_sparse is not None:
            left_w = x_sparse
            right_w = w - x_sparse
            if left_w > 0 and right_w > 0:
                children = [(x, y, left_w, h), (x + x_sparse, y, right_w, h)]

    if children is None:
        return [rect]

    valid_children = [
        child
        for child in children
        if _count_opaque(integral, child[0], child[1], child[2], child[3]) > 0
    ]
    if len(valid_children) <= 1:
        return [rect]

    out: List[Tuple[int, int, int, int]] = []
    for child in valid_children:
        out.extend(
            _split_sparse_region(
                mask,
                integral,
                child,
                min_density,
                min_part_area,
                min_split_side,
                max_split_depth,
                depth + 1,
            )
        )
    return out


def _rects_near(r1: Tuple[int, int, int, int], r2: Tuple[int, int, int, int], gap: int) -> bool:
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    return not (
        x1 + w1 + gap <= x2
        or x2 + w2 + gap <= x1
        or y1 + h1 + gap <= y2
        or y2 + h2 + gap <= y1
    )


def _merge_rects_with_density(
    rects: List[Tuple[int, int, int, int]],
    integral: List[List[int]],
    max_transparent_ratio: float,
    merge_gap: int,
) -> List[Tuple[int, int, int, int]]:
    merged = rects[:]
    changed = True

    while changed and len(merged) > 1:
        changed = False
        for i in range(len(merged)):
            did_merge = False
            for j in range(i + 1, len(merged)):
                r1 = merged[i]
                r2 = merged[j]
                if not _rects_near(r1, r2, merge_gap):
                    continue

                ux = min(r1[0], r2[0])
                uy = min(r1[1], r2[1])
                uw = max(r1[0] + r1[2], r2[0] + r2[2]) - ux
                uh = max(r1[1] + r1[3], r2[1] + r2[3]) - uy
                area = uw * uh
                if area <= 0:
                    continue

                opaque = _count_opaque(integral, ux, uy, uw, uh)
                transparent_ratio = 1.0 - (opaque / float(area))
                if transparent_ratio <= max_transparent_ratio:
                    merged[i] = (ux, uy, uw, uh)
                    merged.pop(j)
                    changed = True
                    did_merge = True
                    break
            if did_merge:
                break

    unique: List[Tuple[int, int, int, int]] = []
    seen = set()
    for rect in merged:
        if rect[2] <= 0 or rect[3] <= 0:
            continue
        if rect in seen:
            continue
        seen.add(rect)
        unique.append(rect)
    unique.sort(key=lambda r: (r[1], r[0], r[2], r[3]))
    return unique


def _rect_transparent_ratio(
    integral: List[List[int]],
    rect: Tuple[int, int, int, int],
) -> float:
    x, y, w, h = rect
    area = max(1, int(w) * int(h))
    opaque = _count_opaque(integral, int(x), int(y), int(w), int(h))
    return 1.0 - (opaque / float(area))


def _refine_sparse_rects(
    mask: List[List[bool]],
    integral: List[List[int]],
    rects: List[Tuple[int, int, int, int]],
    max_transparent_ratio: float,
    min_density: float,
    min_part_area: int,
    min_split_side: int,
    max_split_depth: int,
) -> List[Tuple[int, int, int, int]]:
    """
    Second split pass for large sparse leftovers.

    The first pass may exhaust max_split_depth on repeatedly unbalanced cuts
    (common on diagonals), leaving oversized sparse rects. Re-split only those
    leftovers with a deeper local budget, then keep tiny terminal strips as-is.
    """
    if not rects:
        return []

    refined_depth = max(max_split_depth, 24)
    pending = list(rects)
    changed = True

    while changed:
        changed = False
        next_rects: List[Tuple[int, int, int, int]] = []
        for rect in pending:
            x, y, w, h = rect
            if w <= 0 or h <= 0:
                continue

            transparent_ratio = _rect_transparent_ratio(integral, rect)
            if (
                transparent_ratio <= max_transparent_ratio
                or w <= min_split_side
                or h <= min_split_side
            ):
                next_rects.append(rect)
                continue

            split_rects = _split_sparse_region(
                mask,
                integral,
                rect,
                min_density,
                min_part_area,
                min_split_side,
                refined_depth,
            )
            split_rects = [
                r
                for r in split_rects
                if r[2] > 0 and r[3] > 0 and _count_opaque(integral, r[0], r[1], r[2], r[3]) > 0
            ]

            if len(split_rects) <= 1 or (len(split_rects) == 1 and split_rects[0] == rect):
                next_rects.append(rect)
                continue

            changed = True
            next_rects.extend(split_rects)

        pending = next_rects

    unique: List[Tuple[int, int, int, int]] = []
    seen = set()
    for rect in pending:
        if rect in seen:
            continue
        seen.add(rect)
        unique.append(rect)
    unique.sort(key=lambda r: (r[1], r[0], r[2], r[3]))
    return unique


def _hash_patch_rgba(patch: Image.Image) -> str:
    return hashlib.sha1(patch.tobytes()).hexdigest()


def _mask_has_opaque(mask: List[List[bool]]) -> bool:
    for row in mask:
        for v in row:
            if v:
                return True
    return False


def _count_new_opaque_pixels(
    mask: List[List[bool]],
    covered: List[List[bool]],
    x: int,
    y: int,
    w: int,
    h: int,
) -> int:
    max_h = len(mask)
    max_w = len(mask[0]) if max_h > 0 else 0
    c = 0
    y_end = min(max_h, y + h)
    x_end = min(max_w, x + w)
    for yy in range(max(0, y), y_end):
        mrow = mask[yy]
        crow = covered[yy]
        for xx in range(max(0, x), x_end):
            if mrow[xx] and not crow[xx]:
                c += 1
    return c


def _mark_covered(
    mask: List[List[bool]],
    covered: List[List[bool]],
    x: int,
    y: int,
    w: int,
    h: int,
) -> None:
    max_h = len(mask)
    max_w = len(mask[0]) if max_h > 0 else 0
    y_end = min(max_h, y + h)
    x_end = min(max_w, x + w)
    for yy in range(max(0, y), y_end):
        mrow = mask[yy]
        crow = covered[yy]
        for xx in range(max(0, x), x_end):
            if mrow[xx]:
                crow[xx] = True


def _build_module_context(
    sheet_img: Image.Image,
    src_mod: Module,
    alpha_threshold: int,
) -> Optional[Dict[str, Any]]:
    mx, my, mw, mh = src_mod.rect
    if mw <= 0 or mh <= 0:
        return None

    sheet_w, sheet_h = sheet_img.size
    x0 = max(0, mx)
    y0 = max(0, my)
    x1 = min(sheet_w, mx + mw)
    y1 = min(sheet_h, my + mh)

    offset_x = x0 - mx
    offset_y = y0 - my

    crop = None
    mask_clip: List[List[bool]] = []
    integral_clip: List[List[int]] = [[0]]
    clip_w = 0
    clip_h = 0

    if x1 > x0 and y1 > y0:
        crop = sheet_img.crop((x0, y0, x1, y1))
        mask_clip = _build_alpha_mask(crop, alpha_threshold)
        integral_clip = _build_integral(mask_clip)
        clip_w = x1 - x0
        clip_h = y1 - y0

    full_mask = [[False] * mw for _ in range(mh)]
    if crop is not None:
        for yy in range(clip_h):
            fy = offset_y + yy
            if fy < 0 or fy >= mh:
                continue
            src_row = mask_clip[yy]
            dst_row = full_mask[fy]
            for xx in range(clip_w):
                fx = offset_x + xx
                if 0 <= fx < mw and src_row[xx]:
                    dst_row[fx] = True

    full_integral = _build_integral(full_mask)
    covered = [[False] * mw for _ in range(mh)]

    return {
        "mod": src_mod,
        "crop": crop,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "mask_clip": mask_clip,
        "integral_clip": integral_clip,
        "full_mask": full_mask,
        "full_integral": full_integral,
        "covered": covered,
    }


def _mine_pattern_groups(
    module_contexts: Dict[str, Dict[str, Any]],
    config: Dict,
) -> List[Dict[str, Any]]:
    min_patch_size = max(2, int(config.get("pattern_min_size", 6)))
    max_patch_size = max(min_patch_size, int(config.get("pattern_max_size", 20)))
    patch_size_step = max(1, int(config.get("pattern_size_step", 2)))
    patch_stride = max(1, int(config.get("pattern_stride", 1)))
    min_pattern_occurrences = max(2, int(config.get("min_pattern_occurrences", 3)))
    min_pattern_area = max(1, int(config.get("min_pattern_area", 16)))
    min_pattern_opaque = max(1, int(config.get("min_pattern_opaque", 8)))
    allow_flip_x = bool(config.get("pattern_allow_flip_x", True))
    max_pattern_candidates = max(1, int(config.get("max_pattern_candidates", 300)))
    max_occ_per_module = max(1, int(config.get("max_pattern_occurrences_per_module", 1)))

    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}

    for mod_id, ctx in module_contexts.items():
        crop = ctx.get("crop")
        mask_clip = ctx.get("mask_clip")
        integral_clip = ctx.get("integral_clip")
        if crop is None or not mask_clip:
            continue

        h = len(mask_clip)
        w = len(mask_clip[0]) if h > 0 else 0
        if w <= 0 or h <= 0:
            continue

        seen_tight_boxes = set()
        off_x = int(ctx["offset_x"])
        off_y = int(ctx["offset_y"])

        for ph in range(min_patch_size, max_patch_size + 1, patch_size_step):
            if ph > h:
                continue
            for pw in range(min_patch_size, max_patch_size + 1, patch_size_step):
                if pw > w or pw * ph < min_pattern_area:
                    continue

                for y in range(0, h - ph + 1, patch_stride):
                    for x in range(0, w - pw + 1, patch_stride):
                        opaque = _count_opaque(integral_clip, x, y, pw, ph)
                        if opaque < min_pattern_opaque:
                            continue

                        tight = _tight_bbox(mask_clip, x, y, pw, ph)
                        if not tight:
                            continue

                        tx, ty, tw, th = tight
                        if tw * th < min_pattern_area:
                            continue

                        tight_key = (tx, ty, tw, th)
                        if tight_key in seen_tight_boxes:
                            continue
                        seen_tight_boxes.add(tight_key)

                        tight_opaque = _count_opaque(integral_clip, tx, ty, tw, th)
                        if tight_opaque < min_pattern_opaque:
                            continue

                        patch = crop.crop((tx, ty, tx + tw, ty + th))
                        digest_orig = _hash_patch_rgba(patch)
                        digest_flip = digest_orig
                        if allow_flip_x:
                            digest_flip = _hash_patch_rgba(
                                patch.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                            )
                            gkey = (tw, th, min(digest_orig, digest_flip), max(digest_orig, digest_flip))
                        else:
                            gkey = (tw, th, digest_orig)

                        grouped.setdefault(gkey, []).append(
                            {
                                "mod_id": mod_id,
                                "x": off_x + tx,
                                "y": off_y + ty,
                                "w": tw,
                                "h": th,
                                "opaque": tight_opaque,
                                "digest_orig": digest_orig,
                                "digest_flip": digest_flip,
                            }
                        )

    groups: List[Dict[str, Any]] = []

    for gkey, occs in grouped.items():
        uniq_map: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for occ in occs:
            ukey = (occ["mod_id"], occ["x"], occ["y"], occ["w"], occ["h"], occ["digest_orig"])
            uniq_map[ukey] = occ
        uniq_occs = list(uniq_map.values())

        if len(uniq_occs) < min_pattern_occurrences:
            continue

        digest_counts: Dict[str, int] = {}
        for occ in uniq_occs:
            d = occ["digest_orig"]
            digest_counts[d] = digest_counts.get(d, 0) + 1
        rep_digest = max(digest_counts.items(), key=lambda kv: kv[1])[0]

        normalized_occs: List[Dict[str, Any]] = []
        for occ in uniq_occs:
            if occ["digest_orig"] == rep_digest:
                occ_flip = False
            elif allow_flip_x and occ["digest_flip"] == rep_digest:
                occ_flip = True
            else:
                continue

            normalized_occs.append(
                {
                    "mod_id": occ["mod_id"],
                    "x": occ["x"],
                    "y": occ["y"],
                    "flip_x": occ_flip,
                    "opaque": occ["opaque"],
                }
            )

        if len(normalized_occs) < min_pattern_occurrences:
            continue

        tw = int(uniq_occs[0]["w"])
        th = int(uniq_occs[0]["h"])
        # Avoid over-valuing shifted duplicates inside a single module cell.
        by_module: Dict[str, List[Dict[str, Any]]] = {}
        for occ in normalized_occs:
            by_module.setdefault(str(occ["mod_id"]), []).append(occ)
        limited_occs: List[Dict[str, Any]] = []
        for _mod_id, occ_list in by_module.items():
            occ_list.sort(key=lambda o: int(o.get("opaque", 0)), reverse=True)
            limited_occs.extend(occ_list[:max_occ_per_module])

        if len(limited_occs) < min_pattern_occurrences:
            continue

        avg_opaque = sum(int(o["opaque"]) for o in limited_occs) / float(len(limited_occs))
        score = avg_opaque * max(1, len(limited_occs) - 1)

        groups.append(
            {
                "w": tw,
                "h": th,
                "rep_digest": rep_digest,
                "occurrences": limited_occs,
                "score": score,
            }
        )

    groups.sort(
        key=lambda g: (
            -float(g["score"]),
            -(int(g["w"]) * int(g["h"])),
            -len(g["occurrences"]),
        )
    )
    return groups[:max_pattern_candidates]


def _prune_redundant_placements(
    ctx: Dict[str, Any],
    placements: List[Tuple[str, int, int, bool]],
    project: Project,
    min_unique_opaque: int,
    min_unique_ratio: float,
) -> List[Tuple[str, int, int, bool]]:
    if not placements:
        return []

    full_mask = ctx["full_mask"]
    full_integral = ctx["full_integral"]
    h = len(full_mask)
    w = len(full_mask[0]) if h > 0 else 0
    covered = [[False] * w for _ in range(h)]

    enriched: List[Tuple[int, int, int, int, Tuple[str, int, int, bool]]] = []
    for place in placements:
        part_mod = project.get_module(place[0])
        if not part_mod:
            continue
        pw, ph = int(part_mod.rect[2]), int(part_mod.rect[3])
        opaque = _count_opaque(full_integral, int(place[1]), int(place[2]), pw, ph)
        enriched.append((opaque, pw * ph, int(place[2]), int(place[1]), place))

    enriched.sort(key=lambda e: (-e[0], -e[1], e[2], e[3]))
    kept: List[Tuple[str, int, int, bool]] = []

    for opaque, _area, _y, _x, place in enriched:
        part_mod = project.get_module(place[0])
        if not part_mod:
            continue
        px, py = int(place[1]), int(place[2])
        pw, ph = int(part_mod.rect[2]), int(part_mod.rect[3])
        occ_opaque = max(1, int(opaque))
        new_px = _count_new_opaque_pixels(full_mask, covered, px, py, pw, ph)
        ratio = new_px / float(occ_opaque)
        required_new_px = max(1, min(int(min_unique_opaque), occ_opaque))
        if new_px < required_new_px or ratio < min_unique_ratio:
            continue
        kept.append(place)
        _mark_covered(full_mask, covered, px, py, pw, ph)

    kept.sort(key=lambda p: (p[2], p[1], p[0], int(p[3])))
    return kept


def run_auto_modularization(project: Project, image_or_module_ids, config: Dict) -> Tuple[bool, str]:
    """
    Auto-modularize a spritesheet by decomposing existing image modules into smaller parts.

    Supports both:
    - New API: run_auto_modularization(project, image_id, config)
    - Legacy API: run_auto_modularization(project, [module_ids...], config)
    """
    source_modules: List[Module] = []
    image_id: Optional[str] = None

    if isinstance(image_or_module_ids, list):
        source_modules = [
            m
            for m in (project.get_module(mid) for mid in image_or_module_ids)
            if m and m.type == "MD_IMAGE"
        ]
        if not source_modules:
            return False, "No image-modules selected."
        image_ids = {m.image_id for m in source_modules}
        if len(image_ids) != 1:
            return False, "Selected modules must belong to one spritesheet image."
        image_id = next(iter(image_ids))
    else:
        image_id = str(image_or_module_ids)
        source_modules = [
            m for m in project.modules if m.image_id == image_id and m.type == "MD_IMAGE"
        ]

    if not image_id:
        return False, "No spritesheet image selected."

    asset = project.get_image(image_id)
    if not asset:
        return False, "Spritesheet image not found."

    if not source_modules:
        return False, "No image-modules found on this spritesheet."

    alpha_threshold = int(config.get("alpha_threshold", 0))
    min_part_area = max(1, int(config.get("min_part_area", 1)))
    max_transparent_ratio = float(config.get("max_transparent_ratio", 0.5))
    max_transparent_ratio = min(0.95, max(0.0, max_transparent_ratio))
    min_density = 1.0 - max_transparent_ratio
    merge_gap = max(0, int(config.get("merge_gap", 1)))
    max_split_depth = max(1, int(config.get("max_split_depth", 8)))
    min_split_side = max(2, int(config.get("min_split_side", 2)))
    deduplicate = bool(config.get("deduplicate", True))
    replace_in_frames = bool(config.get("replace_in_frames", True))
    delete_original_modules = bool(config.get("delete_original_modules", True))
    pattern_mining = bool(config.get("pattern_mining", True))
    min_pattern_active_occurrences = max(2, int(config.get("min_pattern_active_occurrences", 2)))
    min_pattern_new_opaque = max(1, int(config.get("min_pattern_new_opaque", 4)))
    min_pattern_new_coverage = float(config.get("min_pattern_new_coverage", 0.55))
    min_pattern_new_coverage = min(1.0, max(0.0, min_pattern_new_coverage))
    placement_min_unique_opaque = max(1, int(config.get("placement_min_unique_opaque", 2)))
    placement_min_unique_ratio = float(config.get("placement_min_unique_ratio", 0.25))
    placement_min_unique_ratio = min(1.0, max(0.0, placement_min_unique_ratio))

    modules_to_process = [m for m in source_modules if not getattr(m, "rotated", False)]
    skipped_rotated = len(source_modules) - len(modules_to_process)
    if not modules_to_process:
        return False, "All candidate modules are rotated; auto-modularize skips rotated modules."

    old_module_ids = {m.id for m in modules_to_process}
    if delete_original_modules and not replace_in_frames:
        for frame in project.frames:
            for fm in frame.fmodules:
                if fm.ref_type == "module" and fm.ref_id in old_module_ids:
                    return False, "Cannot delete originals while frame replacement is disabled."

    try:
        sheet_img = _load_sheet_rgba(asset)
    except Exception as exc:
        return False, f"Failed to load spritesheet image: {exc}"

    source_by_id = {m.id: m for m in modules_to_process}
    part_hash_to_module: Dict[Tuple[int, int, str], str] = {}
    placements_by_source: Dict[str, List[Tuple[str, int, int, bool]]] = {
        m.id: [] for m in modules_to_process
    }
    placement_seen_by_source: Dict[str, set] = {m.id: set() for m in modules_to_process}
    module_contexts: Dict[str, Dict[str, Any]] = {}

    created_unique_parts = 0
    reused_parts = 0
    total_part_instances = 0
    pattern_groups_used = 0
    pattern_instances = 0

    for src_mod in modules_to_process:
        ctx = _build_module_context(sheet_img, src_mod, alpha_threshold)
        if ctx:
            module_contexts[src_mod.id] = ctx

    # Stage 1: Pattern mining across all modules (copy/paste awareness).
    if pattern_mining and deduplicate:
        pattern_groups = _mine_pattern_groups(module_contexts, config)
        for group in pattern_groups:
            gw = int(group["w"])
            gh = int(group["h"])
            group_area = max(1, gw * gh)
            occurrences = group["occurrences"]

            # Evaluate occurrences greedily against temporary coverage to avoid redundant overlap.
            module_ids_in_group = sorted(
                {str(occ["mod_id"]) for occ in occurrences if str(occ["mod_id"]) in module_contexts}
            )
            temp_covered: Dict[str, List[List[bool]]] = {}
            for mid in module_ids_in_group:
                temp_covered[mid] = [row[:] for row in module_contexts[mid]["covered"]]

            ordered_occurrences = sorted(occurrences, key=lambda o: int(o.get("opaque", 0)), reverse=True)
            accepted: List[Tuple[Dict[str, Any], int]] = []
            for occ in ordered_occurrences:
                mod_id = str(occ["mod_id"])
                ctx = module_contexts.get(mod_id)
                if not ctx or mod_id not in temp_covered:
                    continue

                # Keep pattern-mined parts aligned with the global transparency constraint.
                occ_opaque = max(1, int(occ.get("opaque", 1)))
                occ_transparent_ratio = 1.0 - (occ_opaque / float(group_area))
                if occ_transparent_ratio > max_transparent_ratio:
                    continue

                new_px = _count_new_opaque_pixels(
                    ctx["full_mask"],
                    temp_covered[mod_id],
                    int(occ["x"]),
                    int(occ["y"]),
                    gw,
                    gh,
                )
                new_ratio = new_px / float(occ_opaque)
                if new_px < min_pattern_new_opaque or new_ratio < min_pattern_new_coverage:
                    continue

                accepted.append((occ, new_px))
                _mark_covered(
                    ctx["full_mask"],
                    temp_covered[mod_id],
                    int(occ["x"]),
                    int(occ["y"]),
                    gw,
                    gh,
                )

            if len(accepted) < min_pattern_active_occurrences:
                continue

            seed_occ = next((occ for occ, _ in accepted if not bool(occ["flip_x"])), accepted[0][0])
            seed_mod = source_by_id.get(str(seed_occ["mod_id"]))
            if not seed_mod:
                continue

            part_key = (gw, gh, str(group["rep_digest"]))
            part_module_id = part_hash_to_module.get(part_key)
            if not part_module_id:
                created_unique_parts += 1
                part_name = f"AutoPart {created_unique_parts:04d}"
                abs_x = seed_mod.rect[0] + int(seed_occ["x"])
                abs_y = seed_mod.rect[1] + int(seed_occ["y"])
                new_mod = project.create_module(
                    part_name,
                    image_id,
                    (abs_x, abs_y, gw, gh),
                    (gw // 2, gh // 2),
                )
                part_module_id = new_mod.id
                part_hash_to_module[part_key] = part_module_id
                reused_parts += max(0, len(accepted) - 1)
            else:
                reused_parts += len(accepted)

            pattern_groups_used += 1
            pattern_instances += len(accepted)

            for occ, _ in accepted:
                mod_id = str(occ["mod_id"])
                ctx = module_contexts.get(mod_id)
                if not ctx:
                    continue

                lx = int(occ["x"])
                ly = int(occ["y"])
                place_key = (part_module_id, lx, ly, bool(occ["flip_x"]))
                seen_set = placement_seen_by_source.setdefault(mod_id, set())
                if place_key in seen_set:
                    continue
                seen_set.add(place_key)
                placements_by_source.setdefault(mod_id, []).append(place_key)
                _mark_covered(ctx["full_mask"], ctx["covered"], lx, ly, gw, gh)
                total_part_instances += 1

    # Stage 2: residual decomposition per module (fallback for uncovered pixels).
    for src_mod in modules_to_process:
        ctx = module_contexts.get(src_mod.id)
        if not ctx:
            continue

        full_mask = ctx["full_mask"]
        covered = ctx["covered"]
        mw = src_mod.rect[2]
        mh = src_mod.rect[3]

        residual_mask: List[List[bool]] = []
        for yy in range(mh):
            row = []
            mrow = full_mask[yy]
            crow = covered[yy]
            for xx in range(mw):
                row.append(mrow[xx] and not crow[xx])
            residual_mask.append(row)

        if not _mask_has_opaque(residual_mask):
            continue

        residual_integral = _build_integral(residual_mask)
        components = _connected_component_boxes(residual_mask)

        local_rects: List[Tuple[int, int, int, int]] = []
        for component_rect in components:
            local_rects.extend(
                _split_sparse_region(
                    residual_mask,
                    residual_integral,
                    component_rect,
                    min_density,
                    min_part_area,
                    min_split_side,
                    max_split_depth,
                )
            )

        local_rects = _refine_sparse_rects(
            residual_mask,
            residual_integral,
            local_rects,
            max_transparent_ratio,
            min_density,
            min_part_area,
            min_split_side,
            max_split_depth,
        )

        local_rects = _merge_rects_with_density(
            local_rects, residual_integral, max_transparent_ratio, merge_gap
        )

        for rx, ry, rw, rh in local_rects:
            abs_x = src_mod.rect[0] + rx
            abs_y = src_mod.rect[1] + ry
            part_img = sheet_img.crop((abs_x, abs_y, abs_x + rw, abs_y + rh))
            digest = _hash_patch_rgba(part_img)
            hash_key = (rw, rh, digest)

            part_module_id: Optional[str] = None
            if deduplicate:
                part_module_id = part_hash_to_module.get(hash_key)

            if not part_module_id:
                created_unique_parts += 1
                part_name = f"AutoPart {created_unique_parts:04d}"
                new_mod = project.create_module(
                    part_name,
                    image_id,
                    (abs_x, abs_y, rw, rh),
                    (rw // 2, rh // 2),
                )
                part_module_id = new_mod.id
                if deduplicate:
                    part_hash_to_module[hash_key] = part_module_id
            else:
                reused_parts += 1

            place_key = (part_module_id, rx, ry, False)
            seen_set = placement_seen_by_source.setdefault(src_mod.id, set())
            if place_key in seen_set:
                continue
            seen_set.add(place_key)
            placements_by_source.setdefault(src_mod.id, []).append(place_key)
            _mark_covered(full_mask, covered, rx, ry, rw, rh)
            total_part_instances += 1

    # Stage 3: prune low-contribution overlapping placements (large-first set cover).
    pruned_placements = 0
    for src_mod in modules_to_process:
        ctx = module_contexts.get(src_mod.id)
        if not ctx:
            continue
        before = placements_by_source.get(src_mod.id, [])
        after = _prune_redundant_placements(
            ctx,
            before,
            project,
            placement_min_unique_opaque,
            placement_min_unique_ratio,
        )
        placements_by_source[src_mod.id] = after
        pruned_placements += max(0, len(before) - len(after))

    total_part_instances = sum(len(v) for v in placements_by_source.values())

    if created_unique_parts <= 0:
        return False, "No non-transparent sub-parts detected in selected modules."

    replaced_refs = 0
    inserted_part_refs = 0
    removed_refs = 0

    if replace_in_frames:
        source_by_id = {m.id: m for m in modules_to_process}

        for frame in project.frames:
            changed = False
            new_fmodules: List[FModule] = []

            for fm in frame.fmodules:
                if fm.ref_type != "module" or fm.ref_id not in source_by_id:
                    new_fmodules.append(fm)
                    continue

                src_mod = source_by_id[fm.ref_id]
                placements = placements_by_source.get(src_mod.id, [])

                if not placements:
                    if delete_original_modules:
                        removed_refs += 1
                        changed = True
                        continue
                    # Keep original module reference if caller chose not to delete originals.
                    new_fmodules.append(fm)
                    continue

                changed = True
                replaced_refs += 1

                # Replace this single old module entry with directly placed part modules.
                for part_module_id, lx, ly, part_flip_x in placements:
                    part_mod = project.get_module(part_module_id)
                    if not part_mod:
                        continue

                    dx = lx + part_mod.pivot[0] - src_mod.pivot[0]
                    dy = ly + part_mod.pivot[1] - src_mod.pivot[1]

                    if fm.flip_x:
                        dx = -dx
                    if fm.flip_y:
                        dy = -dy

                    rad = math.radians(fm.rotation_degrees)
                    cos_a = math.cos(rad)
                    sin_a = math.sin(rad)
                    rdx = dx * cos_a - dy * sin_a
                    rdy = dx * sin_a + dy * cos_a

                    new_fmodules.append(
                        FModule(
                            id=generate_id("fm"),
                            ref_type="module",
                            ref_id=part_module_id,
                            position=(
                                int(round(fm.position[0] + rdx)),
                                int(round(fm.position[1] + rdy)),
                            ),
                            flip_x=(fm.flip_x ^ part_flip_x),
                            flip_y=fm.flip_y,
                            rotation_degrees=fm.rotation_degrees,
                        )
                    )
                    inserted_part_refs += 1

            if changed:
                frame.fmodules = new_fmodules

    removed_originals = 0
    if delete_original_modules:
        before = len(project.modules)
        project.modules = [m for m in project.modules if m.id not in old_module_ids]
        removed_originals = before - len(project.modules)

        # Cleanup mappings that target or key old modules.
        for mapping in project.mappings:
            for old_id in old_module_ids:
                mapping.map.pop(old_id, None)
            for src_id, target_id in list(mapping.map.items()):
                if target_id in old_module_ids:
                    mapping.map[src_id] = None

    msg = (
        f"Auto modularize complete. Analyzed {len(modules_to_process)} modules, "
        f"created {created_unique_parts} unique parts ({total_part_instances} placements, "
        f"{reused_parts} deduplicated reuses)."
    )
    if pattern_mining and deduplicate:
        msg += f" Pattern mining reused {pattern_instances} placements across {pattern_groups_used} groups."
    if pruned_placements > 0:
        msg += f" Pruned {pruned_placements} redundant overlapping placements."
    if delete_original_modules:
        msg += f" Removed {removed_originals} original modules."
    if replace_in_frames:
        msg += (
            f" Updated {replaced_refs} frame module references in-place and inserted "
            f"{inserted_part_refs} part references"
        )
        if removed_refs > 0:
            msg += f" (removed {removed_refs} empty references)."
        else:
            msg += "."
    if skipped_rotated > 0:
        msg += f" Skipped {skipped_rotated} rotated modules."

    return True, msg


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
