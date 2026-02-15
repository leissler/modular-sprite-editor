import wx
from collections import Counter
from typing import List, Tuple, Optional, Dict
from PIL import Image, ImageChops, ImageFilter, ImageMath

class Decomposition:
    """
    Algorithms for decomposing sprite images into optimal sub-modules.
    """

    @staticmethod
    def wx_image_to_pil(wx_img: wx.Image) -> Image.Image:
        """Converts a wx.Image to a Pillow Image (RBGA)."""
        w, h = wx_img.GetWidth(), wx_img.GetHeight()
        data = wx_img.GetData()
        
        # Create RGB image
        pil_img = Image.frombuffer("RGB", (w, h), data)
        
        # Add Alpha
        if wx_img.HasAlpha():
            alpha_data = wx_img.GetAlpha()
            alpha = Image.frombuffer("L", (w, h), alpha_data)
            pil_img.putalpha(alpha)
        else:
            # If mask, convert to alpha
            if wx_img.HasMask():
                pil_img = pil_img.convert("RGBA")
                datas = pil_img.getdata()
                new_data = []
                mask_color = wx_img.GetMaskColour()
                for item in datas:
                    if item[0] == mask_color[0] and item[1] == mask_color[1] and item[2] == mask_color[2]:
                        new_data.append((0, 0, 0, 0))
                    else:
                        new_data.append(item)
                pil_img.putdata(new_data)
            else:
                pil_img = pil_img.convert("RGBA")
                
        return pil_img

    @staticmethod
    def pil_to_wx_image(pil_img: Image.Image) -> wx.Image:
        """Converts a Pillow Image to wx.Image."""
        if pil_img.mode != "RGBA":
            pil_img = pil_img.convert("RGBA")
            
        w, h = pil_img.size
        data = pil_img.convert("RGB").tobytes()
        alpha = pil_img.split()[3].tobytes()
        
        wx_img = wx.Image(w, h, data)
        wx_img.SetAlpha(alpha)
        return wx_img

    @staticmethod
    def get_alpha_mask(pil_img: Image.Image, tolerance_px: int = 0) -> Image.Image:
        """
        Returns a binary mask (L mode) of non-transparent pixels.
        Applies morphological closing if tolerance_px > 0 to bridge gaps.
        """
        # Extract alpha
        alpha = pil_img.split()[3]
        # Threshold: >0 is solid
        mask = alpha.point(lambda p: 255 if p > 0 else 0)
        
        if tolerance_px > 0:
            # Morphological Closing: Dilation then Erosion
            # MaxFilter = Dilation, MinFilter = Erosion
            # Box-shaped kernel of size (2*r + 1)
            # Filter size is diameter, so size = 2*tolerance + 1
            kernel_size = 2 * tolerance_px + 1
            mask = mask.filter(ImageFilter.MaxFilter(kernel_size))
            mask = mask.filter(ImageFilter.MinFilter(kernel_size))
            
        return mask

    @staticmethod
    def recursive_xy_cut(mask: Image.Image, bounds: Tuple[int, int, int, int]) -> List[Tuple[int, int, int, int]]:
        """
        Recursively slices the mask into rectangular regions separated by empty rows/cols.
        bounds = (x, y, w, h) absolute coordinates in the original image.
        Returns a list of (x, y, w, h) rects.
        """
        x, y, w, h = bounds
        
        # Get crop of the mask for this region
        region = mask.crop((x, y, x + w, y + h))
        bbox = region.getbbox()
        
        if not bbox:
            return []
            
        # Refine bounds based on actual content
        l, t, r, b = bbox
        # Update absolute bounds
        abs_x = x + l
        abs_y = y + t
        abs_w = r - l
        abs_h = b - t
        
        # If the trimmed size is small, just return it
        if abs_w <= 1 or abs_h <= 1:
            return [(abs_x, abs_y, abs_w, abs_h)]
            
        # Re-crop to the trimmed region for analysis
        region = region.crop((l, t, r, b))
        
        # Project Phase
        # Horizontal Projection (sum of pixels in rows)
        # Vertical Projection (sum of pixels in cols)
        
        # We need to find "Gutters" of 0s.
        # Getting raw data allows fast scan
        data = region.load()
        
        # Scan Rows (Y-axis) for a split
        # We prefer splitting along the longer dimension? Or just any split?
        # Standard XY-Cut usually prioritizes one axis or alternates. 
        # Let's verify "Empty Rows".
        
        def find_gap(length, is_row_check):
            # is_row_check=True: length is height, check rows 0..h-1
            # is_row_check=False: length is width, check cols 0..w-1
            
            # Simple heuristic: Split at the *widest* gap? Or first gap?
            # Standard: First gap helps recursion.
            
            # Check for ANY empty row/col inside the bounds (exclude edges)
            
            # Optimization: If the region is solid, we can't cut.
            # We can use getbbox logic again on sub-strips, but that's slow.
            
            has_gap = False
            split_start = -1
            
            best_split_start = -1
            best_split_len = 0
            
            current_gap_start = -1
            
            # Scan
            limit = length
            # If checking rows, we iterate y from 0 to h
            # For each y, we check if ALL x are 0
            
            # This pixel access can be slow in Python.
            # Optimization: Use projection list.
            pass
        
        # Optimization: Use getprojection() if available? No.
        # Use simple pixel access.
        
        # Y-Projection (Rows)
        rows_empty = []
        for ry in range(abs_h):
            is_empty = True
            for rx in range(abs_w):
                if data[rx, ry] > 0:
                    is_empty = False
                    break
            rows_empty.append(is_empty)
            
        # X-Projection (Cols)
        cols_empty = []
        for rx in range(abs_w):
            is_empty = True
            for ry in range(abs_h):
                if data[rx, ry] > 0:
                    is_empty = False
                    break
            cols_empty.append(is_empty)
            
        # Find Split Point
        # We look for a sequence of Trues in rows_empty or cols_empty.
        
        def get_best_split(empty_list):
            # Find largest gap to split? Or center gap?
            # Splits must be separate non-empty regions.
            # So a gap of "True" must be bordered by "False" on both sides (eventually).
            # We know the bbox is tight, so index 0 and index len-1 must have some content?
            # Actually no, we already trimmed using bbox. So row 0 and row -1 MUST be non-empty?
            # Actually, `region.getbbox()` ensures top/bottom/left/right are touching content.
            # So empty_list[0] and empty_list[-1] are FALSE.
            
            # We just need ONE gap.
            # Let's find any True.
            try:
                first_gap = empty_list.index(True)
                # Find end of gap
                end_gap = first_gap
                while end_gap < len(empty_list) and empty_list[end_gap]:
                    end_gap += 1
                return first_gap, end_gap
            except ValueError:
                return None
                
        y_split = get_best_split(rows_empty)
        x_split = get_best_split(cols_empty)
        
        # Heuristic: Cut the larger dimension or biggest gap?
        # Let's cut the biggest gap to separate distant objects first.
        
        split_y = False
        split_x = False
        
        if y_split and x_split:
            y_gap_size = y_split[1] - y_split[0]
            x_gap_size = x_split[1] - x_split[0]
            if y_gap_size >= x_gap_size:
                split_y = True
            else:
                split_x = True
        elif y_split:
            split_y = True
        elif x_split:
            split_x = True
            
        if split_y:
            y0, y1 = y_split
            # Split into Top and Bottom
            # Region 1: 0 to y0
            # Region 2: y1 to abs_h
            
            rects = []
            rects.extend(Decomposition.recursive_xy_cut(mask, (abs_x, abs_y, abs_w, y0)))
            rects.extend(Decomposition.recursive_xy_cut(mask, (abs_x, abs_y + y1, abs_w, abs_h - y1)))
            return rects
            
        if split_x:
            x0, x1 = x_split
            rects = []
            rects.extend(Decomposition.recursive_xy_cut(mask, (abs_x, abs_y, x0, abs_h)))
            rects.extend(Decomposition.recursive_xy_cut(mask, (abs_x + x1, abs_y, abs_w - x1, abs_h)))
            return rects
            
        # No splits found -> Atomic Module
        return [(abs_x, abs_y, abs_w, abs_h)]

    @staticmethod
    def greedy_maximal_rects(mask: Image.Image, bounds: Tuple[int, int, int, int]) -> List[Tuple[int, int, int, int]]:
        """
        Extracts maximal solid rectangles from the mask within bounds.
        Destructive: Zeros out the mask as it finds rects.
        """
        # Work on a copy/region
        x, y, w, h = bounds
        region = mask.crop((x, y, x + w, y + h))
        
        # Get flattened data simply 0 or 255
        # For efficient calc, we might need a 2D array or list of strings
        # Given standard sprite sizes (e.g. 64x64 or 256x256), Python loops are okay-ish,
        # but pure python pixel looping is slow.
        # Optimization: Use histogram algorithm for "Largest Rectangle in Histogram".
        
        # We need to find the global maximum rectangle of 1s.
        # Then remove it. Repeat.
        
        width, height = region.size
        pixels = list(region.getdata()) # Flat list
        
        # Helper to get/set
        def get_px(px, py):
            if 0 <= px < width and 0 <= py < height:
                return pixels[py * width + px] > 0
            return False

        def set_px_zero(px, py):
            pixels[py * width + px] = 0

        rects = []
        
        while True:
            # 1. Update Heights Histogram
            # For each pixel, 'height' is number of consecutive 1s above it (including itself)
            # Efficient implementation:
            # We just need to search for the best rect.
            
            best_area = 0
            best_rect = None # (lx, ly, w, h)
            
            # Naive approach usually too slow for repeated solving.
            # But the mask gets emptier.
            
            # Simple heuristic optimization:
            # Find the First "1" pixel (Top-Left priority).
            # Grow unique maximal rect from there? 
            # No, greedy means Global Max Area.
            
            # Let's try "First Fit" maximal expansion?
            # It segments logically. "Find first 1. Try to encompass as much as possible right/down."
            # That's faster than global max and usually produces decent scanline-like strips.
            # But "Maximal Rects" usually implies Global Max.
            
            # Let's do "First Solid Pixel -> Expand Max"
            # Valid for retro (scanlines).
            
            found = False
            start_x, start_y = -1, -1
            
            for i, val in enumerate(pixels):
                if val > 0:
                    start_y = i // width
                    start_x = i % width
                    found = True
                    break
            
            if not found:
                break
                
            # Expand Right
            rw = 0
            while get_px(start_x + rw, start_y):
                rw += 1
                
            # Expand Down
            # We must maintain width 'rw' for all rows
            rh = 1
            while True:
                # Check next row
                next_y = start_y + rh
                if next_y >= height:
                    break
                
                # Check line segment
                ok = True
                for k in range(rw):
                    if not get_px(start_x + k, next_y):
                        ok = False
                        break
                if not ok:
                    break
                rh += 1
                
            # We have a rect (start_x, start_y, rw, rh)
            # Add to list
            rects.append((x + start_x, y + start_y, rw, rh))
            
            # Zero out
            for dy in range(rh):
                for dx in range(rw):
                    set_px_zero(start_x + dx, start_y + dy)
                    
        return rects

    @staticmethod
    def reconstruct_background(pil_images: List[Image.Image], threshold: float = 0.5) -> Tuple[Image.Image, List[Image.Image]]:
        """
        Analyzes a stack of images (same size) and reconstructs a common background
        based on pixel mode frequency.
        
        Returns:
            (Common_Image, List[Residual_Images])
            Common_Image: The reconstructed static part.
            Residual_Images: The input images with the common part erased (transparent).
        """
        if not pil_images:
            return None, []
        
        w, h = pil_images[0].size
        count = len(pil_images)
        min_freq = int(count * threshold)
        
        # Prepare pixel access
        pixels_list = [img.load() for img in pil_images]
        
        # Output
        common = Image.new("RGBA", (w, h))
        common_px = common.load()
        
        # Valid Mask (where we found a common pixel)
        # We can just check common alpha.
        
        for y in range(h):
            for x in range(w):
                # Collect colors at this px (excluding transparent)
                colors = []
                for p_idx in range(count):
                    c = pixels_list[p_idx][x, y]
                    if c[3] > 0: # Alpha > 0
                        colors.append(c)
                
                if not colors:
                     continue
                     
                # Find Mode
                most_common = Counter(colors).most_common(1)
                if not most_common:
                    continue
                    
                color, freq = most_common[0]
                
                if freq > min_freq:
                    # We found a background pixel!
                    common_px[x, y] = color
                    
        # Generate Residuals
        residuals = []
        for i, img in enumerate(pil_images):
            res = Image.new("RGBA", (w, h))
            res_px = res.load()
            src_px = pixels_list[i]
            
            for y in range(h):
                for x in range(w):
                    c_src = src_px[x, y]
                    c_com = common_px[x, y]
                    
                    if c_src[3] == 0:
                        continue # Source was empty
                        
                    if c_com[3] > 0:
                        # Common exists here. Does source match?
                        # Fuzzy match? Or exact? exact for now.
                        if c_src == c_com:
                            continue # It matches common, so remove from residual (leave transparent)
                            
                    # Does not match common, or common not present -> Keep in residual
                    res_px[x, y] = c_src
            
            residuals.append(res)
            
        return common, residuals
