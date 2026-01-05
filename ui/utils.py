import wx
from models import Project, Frame, Module
from typing import Optional

class ThumbnailGenerator:
    def __init__(self):
        self.asset_cache = {} # image_id -> wx.Image

    def clear_cache(self):
        self.asset_cache = {}

    def render_thumbnail(self, project: Project, item, width: int, height: int, custom_scale: float = 0.0, flip_x: bool = False, flip_y: bool = False, rotation: float = 0.0, mapping: Optional['ModuleMapping'] = None) -> wx.Bitmap:
        # DEBUG: PROBE
        type_str = "Unknown"
        if getattr(item, 'fmodules', None) is not None: type_str = "Frame"
        elif getattr(item, 'image_id', None) is not None: type_str = "Module"
        # Debug removed
        
        bmp = wx.Bitmap(width, height)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(50, 50, 50)))
        dc.Clear()
        
        self.draw_thumbnail_direct(dc, project, item, wx.Rect(0, 0, width, height), custom_scale, flip_x, flip_y, rotation, mapping)
        
        dc.SelectObject(wx.NullBitmap)
        return bmp

    def draw_thumbnail_direct(self, dc: wx.DC, project: Project, item, rect: wx.Rect, custom_scale: float = 0.0, flip_x: bool = False, flip_y: bool = False, rotation: float = 0.0, mapping: Optional['ModuleMapping'] = None):
        """Draws the item directly onto the provided DC within the target rect."""
        width, height = rect.width, rect.height
        x_off, y_off = rect.x, rect.y
        
        
         # Handle Module Rendering (Duck Typed)
        if getattr(item, 'image_id', None) is not None and getattr(item, 'rect', None) is not None and not hasattr(item, 'fmodules'):
            mod = item
            mw, mh = mod.rect[2], mod.rect[3]
            
            # Scale calculation
            content_w = max(1, mw)
            content_h = max(1, mh)
            if custom_scale > 0:
                scale = custom_scale
            else:
                scale = min(width / content_w, height / content_h)
            
            # Center in rect
            off_x = x_off + (width - content_w * scale) / 2
            off_y = y_off + (height - content_h * scale) / 2
            
            # Direct Draw
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
                        
                        if flip_x: sub = sub.Mirror(True)
                        if flip_y: sub = sub.Mirror(False)
                        
                        w_scaled = int(rw * scale)
                        h_scaled = int(rh * scale)
                        
                        if w_scaled > 0 and h_scaled > 0:
                            sub = sub.Scale(w_scaled, h_scaled, wx.IMAGE_QUALITY_NEAREST)
                            sub_bmp = sub.ConvertToBitmap()
                            dc.DrawBitmap(sub_bmp, int(off_x), int(off_y), True) 
                 except Exception:
                     pass
            return

        # Handle Frame
        frame = None
        if hasattr(item, 'fmodules'):
             frame = item
        
        if not frame:
             return

        if not frame.fmodules:
             return

        # Calculate Bounds
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        has_content = False
        
        for fm in frame.fmodules:
            if fm.ref_type == "module":
                ref_id = fm.ref_id
                if mapping and ref_id in mapping.map:
                    ref_id = mapping.map[ref_id]

                if not ref_id: continue

                mod = project.get_module(ref_id)
                if mod:
                    mw, mh = mod.rect[2], mod.rect[3]
                    piv_x, piv_y = mod.pivot
                    x0 = fm.position[0] - piv_x
                    y0 = fm.position[1] - piv_y
                    
                    min_x = min(min_x, x0)
                    min_y = min(min_y, y0)
                    max_x = max(max_x, x0 + mw)
                    max_y = max(max_y, y0 + mh)
                    has_content = True

        if not has_content:
             return

        # Rotation Logic for Content Size
        content_w = max(1, max_x - min_x)
        content_h = max(1, max_y - min_y)
        
        rot_int = int(rotation) % 360
        eff_w, eff_h = content_w, content_h
        if rot_int == 90 or rot_int == 270:
            eff_w, eff_h = content_h, content_w
            
        # Calc Scale
        if custom_scale > 0:
            scale = custom_scale
        else:
            scale = min(width / eff_w, height / eff_h)
            scale = min(scale, 32.0)
            
        if eff_w == 0 or eff_h == 0:
             return

        # Calculate Offset to center in RECT
        off_x = x_off + (width - eff_w * scale) / 2
        off_y = y_off + (height - eff_h * scale) / 2
        
        # We will do manual transform
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
                            if asset.id not in self.asset_cache:
                                full_img = wx.Image(asset.file_path)
                                if asset.transparent_color:
                                    full_img.SetMaskColour(*asset.transparent_color)
                                self.asset_cache[asset.id] = full_img
                            
                            full_img = self.asset_cache[asset.id]
                            
                            rx, ry, rw, rh = mod.rect
                            if rx + rw <= full_img.GetWidth() and ry + rh <= full_img.GetHeight():
                                sub = full_img.GetSubImage(wx.Rect(int(rx), int(ry), int(rw), int(rh)))
                                
                                # Module Flips
                                if fm.flip_x: sub = sub.Mirror(True)
                                if fm.flip_y: sub = sub.Mirror(False)
                                
                                # Position
                                piv_x, piv_y = mod.pivot
                                raw_x = fm.position[0] - piv_x
                                raw_y = fm.position[1] - piv_y
                                
                                rel_x = raw_x - min_x
                                rel_y = raw_y - min_y
                                
                                # Global Flip X -> Flip around center of content rectangle
                                if flip_x:
                                    rel_x = content_w - rel_x - rw
                                    sub = sub.Mirror(True)
                                if flip_y:
                                    rel_y = content_h - rel_y - rh
                                    sub = sub.Mirror(False)
                                
                                # Apply Rotation to Coordinates and Image
                                rot_int = int(rotation) % 360
                                if rot_int == 90:
                                    # (x, y) -> (content_h - y - rh, x)
                                    # New Width is content_h
                                    new_x = content_h - rel_y - rh
                                    new_y = rel_x
                                    rel_x, rel_y = new_x, new_y
                                    sub = sub.Rotate90(True) # Clockwise
                                    rw, rh = rh, rw
                                elif rot_int == 180:
                                    # (x, y) -> (content_w - x - rw, content_h - y - rh)
                                    new_x = content_w - rel_x - rw
                                    new_y = content_h - rel_y - rh
                                    rel_x, rel_y = new_x, new_y
                                    sub = sub.Rotate180()
                                elif rot_int == 270:
                                    # (x, y) -> (y, content_w - x - rw)
                                    new_x = rel_y
                                    new_y = content_w - rel_x - rw
                                    rel_x, rel_y = new_x, new_y
                                    sub = sub.Rotate90(False) # Counter-Clockwise
                                    rw, rh = rh, rw

                                # Scale
                                dest_x = off_x + rel_x * scale
                                dest_y = off_y + rel_y * scale
                                dest_w = rw * scale
                                dest_h = rh * scale
                                
                                if dest_w > 0 and dest_h > 0:
                                     sub = sub.Scale(int(dest_w), int(dest_h), wx.IMAGE_QUALITY_NEAREST)
                                     sub_bmp = sub.ConvertToBitmap()
                                     dc.DrawBitmap(sub_bmp, int(dest_x), int(dest_y), True)
                        except Exception:
                             pass
        
        # DEBUG: Fall through - Check if we reached end
        # If nothing drawn, but arrived here
        # dc.SetBrush(wx.Brush(wx.Colour(0, 255, 0))) # Green
        # dc.DrawRectangle(rect.x + rect.width - 5, rect.y + rect.height - 5, 5, 5)
