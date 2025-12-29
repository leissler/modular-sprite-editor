import wx
from models import Project, Frame, Module

class ThumbnailGenerator:
    def __init__(self):
        self.asset_cache = {} # image_id -> wx.Image

    def clear_cache(self):
        self.asset_cache = {}

    def render_thumbnail(self, project: Project, item, width: int, height: int, custom_scale: float = 0.0, flip_x: bool = False, flip_y: bool = False, rotation: float = 0.0, mapping: Optional['ModuleMapping'] = None) -> wx.Bitmap:
        bmp = wx.Bitmap(width, height)
        dc = wx.MemoryDC(bmp)
        
        # Background
        dc.SetBackground(wx.Brush(wx.Colour(50, 50, 50)))
        dc.Clear()
        
        # Handle Module Rendering
        if isinstance(item, Module):
            mod = item
            mw, mh = mod.rect[2], mod.rect[3]
            
            # Scale calculation
            content_w = max(1, mw)
            content_h = max(1, mh)
            if custom_scale > 0:
                scale = custom_scale
            else:
                scale = min(width / content_w, height / content_h)
            
            off_x = (width - content_w * scale) / 2
            off_y = (height - content_h * scale) / 2
            
            gc = wx.GraphicsContext.Create(dc)
            
            asset = project.get_image(mod.image_id)
            if asset:
                 try:
                    if asset.id not in self.asset_cache:
                        full_img = wx.Image(asset.file_path)
                        if asset.transparent_color:
                            full_img.SetMaskColour(*asset.transparent_color)
                        self.asset_cache[asset.id] = full_img
                    
                    full_img = self.asset_cache[asset.id]
                    rx, ry, rw, rh = mod.rect
                    if rx + rw <= full_img.GetWidth() and ry + rh <= full_img.GetHeight():
                        sub = full_img.GetSubImage(wx.Rect(int(rx), int(ry), int(rw), int(rh)))
                        
                        # Module level flip?
                        if flip_x: sub = sub.Mirror(True)
                        if flip_y: sub = sub.Mirror(False)

                        # Explicit Nearest Neighbor Scaling
                        w_scaled = int(rw * scale)
                        h_scaled = int(rh * scale)
                        if w_scaled > 0 and h_scaled > 0:
                            sub = sub.Scale(w_scaled, h_scaled, wx.IMAGE_QUALITY_NEAREST)
                            sub_bmp = sub.ConvertToBitmap()
                            gc.DrawBitmap(sub_bmp, off_x, off_y, w_scaled, h_scaled)
                 except: pass
            
            dc.SelectObject(wx.NullBitmap)
            return bmp

        # Handle Frame (Assuming item is Frame)
        if hasattr(item, 'fmodules'):
             frame = item
        else:
             # Just return empty if not frame
             dc.SelectObject(wx.NullBitmap)
             return bmp

        if not frame.fmodules:
             # Empty
             font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
             dc.SetFont(font)
             dc.SetTextForeground(wx.Colour(150, 150, 150))
             dc.DrawText("Empty", 2, height // 2 - 10)
             dc.SelectObject(wx.NullBitmap)
             return bmp

        # Calculate Bounds
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        has_content = False
        
        for fm in frame.fmodules:
            if fm.ref_type == "module":
                ref_id = fm.ref_id
                ref_id = fm.ref_id
                # Note: We intentionally ignore mapping for bounds calculation
                # to ensure scale/centering is "locked" to the original frame structure.
                # This prevents UI jumping when switching mappings.
                # if mapping and ref_id in mapping.map:
                #     ref_id = mapping.map[ref_id]

                if not ref_id: continue

                mod = project.get_module(ref_id)
                if mod:
                    mw, mh = mod.rect[2], mod.rect[3]
                    piv_x, piv_y = mod.pivot
                    x0 = fm.position[0] - piv_x
                    y0 = fm.position[1] - piv_y
                    
                    # Logic note: Use rotated bounds of module?
                    # FModule rotation is handled in drawing, bounds check here ignores it?
                    # Ideally we should include fmodule rotation in bounds calc. 
                    # But for thumbnails, approximate bounds is okay.
                    
                    min_x = min(min_x, x0)
                    min_y = min(min_y, y0)
                    max_x = max(max_x, x0 + mw)
                    max_y = max(max_y, y0 + mh)
                    has_content = True

        if not has_content:
             dc.SelectObject(wx.NullBitmap)
             return bmp

        # Rotation Logic for Content Size
        content_w = max(1, max_x - min_x)
        content_h = max(1, max_y - min_y)
        
        rot = int(rotation) % 360
        eff_w, eff_h = content_w, content_h
        if rot == 90 or rot == 270:
            eff_w, eff_h = content_h, content_w
            
        # Calc Scale
        if custom_scale > 0:
            scale = custom_scale
        else:
            scale = min(width / eff_w, height / eff_h)
            scale = min(scale, 32.0)
            
        off_x = (width - eff_w * scale) / 2
        off_y = (height - eff_h * scale) / 2
        
        # Draw
        gc = wx.GraphicsContext.Create(dc)
        
        # Transform:
        # 1. Translate to Center of Slot
        # 2. Scale
        # 3. Rotate
        # 4. Flip
        # 5. Translate back relative to content
        
        # GC Matrix Order: last applied is first in code? No, usually Start -> T -> S -> R -> Draw
        
        # Center of content relative to min_x/min_y
        cx = content_w / 2
        cy = content_h / 2
        
        # Center of slot
        sx = width / 2
        sy = height / 2
        
        # Start at center of slot
        gc.Translate(sx, sy)
        gc.Scale(scale, scale)
        
        # Rotate
        import math
        gc.Rotate(math.radians(rot))
        
        # Flip (around center)
        if flip_x: gc.Scale(-1, 1)
        if flip_y: gc.Scale(1, -1)
        
        # Move back by half-size of content to align top-left
        gc.Translate(-cx, -cy)
        
        # Translate by min_x/min_y to map content to 0,0
        gc.Translate(-min_x, -min_y)
        
        
        for fm in frame.fmodules:
            if fm.ref_type == "module":
                ref_id = fm.ref_id
                if mapping and ref_id in mapping.map:
                    ref_id = mapping.map[ref_id]

                if not ref_id: continue

                mod = project.get_module(ref_id)
                if mod:
                    asset = project.get_image(mod.image_id)
                    if asset:
                        try:
                            # Asset Cache Check
                            if asset.id not in self.asset_cache:
                                full_img = wx.Image(asset.file_path)
                                if asset.transparent_color:
                                    full_img.SetMaskColour(*asset.transparent_color)
                                self.asset_cache[asset.id] = full_img
                            
                            full_img = self.asset_cache[asset.id]
                            
                            rx, ry, rw, rh = mod.rect
                            if rx + rw <= full_img.GetWidth() and ry + rh <= full_img.GetHeight():
                                sub = full_img.GetSubImage(wx.Rect(int(rx), int(ry), int(rw), int(rh)))
                                
                                if fm.flip_x: sub = sub.Mirror(True)
                                if fm.flip_y: sub = sub.Mirror(False)
                                
                                sub_bmp = sub.ConvertToBitmap()
                                piv_x, piv_y = mod.pivot
                                gc.DrawBitmap(sub_bmp, fm.position[0] - piv_x, fm.position[1] - piv_y, rw, rh)
                        except: pass
                             
        dc.SelectObject(wx.NullBitmap)
        return bmp

