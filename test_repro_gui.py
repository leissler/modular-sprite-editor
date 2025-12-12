
import wx
import os
import time
from models import Project, Module, ImageAsset
from ui.frame_editor import FrameEditorPanel

# Mock objects to avoid full app setup
class MockProject(Project):
    pass

def create_mock_project(name, img_path):
    p = MockProject()
    p.name = name
    p.images = [ImageAsset(id=img_path, file_path=img_path, width=64, height=64)]
    p.modules = [Module(id="m1", name=f"Mod_{name}", image_id=img_path, rect=(0,0,64,64), pivot=(0,0))]
    return p

def main():
    app = wx.App()
    frame = wx.Frame(None)
    
    # Create dummy images
    img1 = "img1.png"
    img2 = "img2.png"
    
    # Create valid dummy images so wx.Image doesn't fail
    bmp = wx.Bitmap(64, 64)
    bmp.SaveFile(img1, wx.BITMAP_TYPE_PNG)
    bmp.SaveFile(img2, wx.BITMAP_TYPE_PNG)
    
    try:
        p1 = create_mock_project("P1", os.path.abspath(img1))
        p2 = create_mock_project("P2", os.path.abspath(img2))
        
        panel = FrameEditorPanel(frame, p1)
        
        print("\n--- Loading P1 ---")
        panel.set_project(p1)
        panel.palette.refresh_modules()
        
        print("\n--- Loading P2 ---")
        panel.set_project(p2)
        panel.palette.refresh_modules()
        
        print("\n--- Listing Items ---")
        count = panel.palette.GetItemCount()
        print(f"Item Count: {count}")
        for i in range(count):
            item = panel.palette.GetItem(i)
            print(f"Item {i}: {item.GetText()}")
            
    finally:
        if os.path.exists(img1): os.remove(img1)
        if os.path.exists(img2): os.remove(img2)
        
if __name__ == "__main__":
    main()
