import wx
from typing import List, Tuple, Dict
from rect_packer import MaxRectsBinPack
from models import Project, Module, generate_id, ImageAsset

def optimize_modules(project: Project, module_ids: List[str], config: Dict) -> Tuple[bool, str]:
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
            # Skip empty modules to avoid packing failures
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
    import os
    base_dir = os.path.dirname(project.images[0].file_path) if project.images else "."
    
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
             
    return True, "Optimization successful."
