import wx
from models import Project, Frame, Module

class ThumbnailGenerator:
    def __init__(self):
        self.asset_cache = {} # image_id -> wx.Image

    def clear_cache(self):
        self.asset_cache = {}

    def render_thumbnail(self, project: Project, frame: Frame, width: int, height: int, custom_scale: float = 0.0) -> wx.Bitmap:
        bmp = wx.Bitmap(width, height)
        dc = wx.MemoryDC(bmp)
        
        # Background
        dc.SetBackground(wx.Brush(wx.Colour(50, 50, 50)))
        dc.Clear()
        
        if not frame.fmodules:
             # Empty frame text
            font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
            # Scale font if small?
            dc.SetFont(font)
            dc.SetTextForeground(wx.Colour(150, 150, 150))
            dc.DrawText("Empty", 2, height // 2 - 10)
            dc.SelectObject(wx.NullBitmap)
            return bmp

        # Calculate Bounds of content to center/scale
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        
        has_content = False
        
        for fm in frame.fmodules:
            if fm.ref_type == "module":
                mod = project.get_module(fm.ref_id)
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
             dc.SelectObject(wx.NullBitmap)
             return bmp

        # Determine scale
        if custom_scale > 0:
            scale = custom_scale
        else:
            content_w = max(1, max_x - min_x)
            content_h = max(1, max_y - min_y)
            
            scale = min(width / content_w, height / content_h)
            # Remove cap (or set very high) to allow small sprites to fill box
            scale = min(scale, 32.0) 
        
        content_w = max(1, max_x - min_x)
        content_h = max(1, max_y - min_y)
        
        off_x = (width - content_w * scale) / 2
        off_y = (height - content_h * scale) / 2
        
        # Draw Modules
        gc = wx.GraphicsContext.Create(dc)
        # gc.SetInterpolationQuality(wx.INTERPOLATION_NONE) # Nearest neighbor if possible
        
        gc.Scale(scale, scale)
        gc.Translate(off_x / scale - min_x, off_y / scale - min_y)
        
        for fm in frame.fmodules:
            if fm.ref_type == "module":
                mod = project.get_module(fm.ref_id)
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
                        except:
                            pass
                             
        dc.SelectObject(wx.NullBitmap)
        return bmp
