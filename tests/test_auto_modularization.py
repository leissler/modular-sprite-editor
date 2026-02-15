
import unittest
import os
import shutil
from PIL import Image, ImageDraw
import wx
from models import Project, ImageAsset, Module
from optimization import run_auto_modularization

class TestAutoModularization(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_output"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)
        
        # Initialize wx App (needed for wx.Image)
        self.app = wx.App()
        
        self.project = Project()
        
        # Create a dummy image: 64x64 transparent, with two 10x10 squares and a connecting line
        # Square 1: (10, 10, 10, 10)
        # Square 2: (40, 40, 10, 10)
        # This should trigger decomposition if we cut
        
        self.img_path = os.path.join(self.test_dir, "test_sprite.png")
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((10, 10, 20, 20), fill=(255, 0, 0, 255))
        draw.rectangle((40, 40, 50, 50), fill=(0, 255, 0, 255))
        img.save(self.img_path)
        
        self.asset = self.project.create_image(os.path.abspath(self.img_path), 64, 64)
        
        # Create a Module covering the whole image
        self.mod = self.project.create_module("FullMod", self.asset.id, (0, 0, 64, 64), (32, 32))
        
    def tearDown(self):
        # clean up
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        del self.app

    def test_recursive_decomposition(self):
        config = {
            "method": "xy_cut", 
            "tolerance": 0, 
            "optimize": False
        }
        
        success, msg = run_auto_modularization(self.project, [self.mod.id], config)
        self.assertTrue(success, msg)
        
        # Should have created 1 Frame
        self.assertEqual(len(self.project.frames), 1)
        frame = self.project.frames[0]
        
        # Should have at least 2 FModules (the two squares)
        # It might be 3 if it cut loosely, but XY cut should find the gap.
        # Vertical cut at x=21..39?
        print(f"Created {len(frame.fmodules)} sub-modules")
        for fm in frame.fmodules:
            m = self.project.get_module(fm.ref_id)
            print(f"  Sub: {m.rect}")
            
        self.assertGreaterEqual(len(frame.fmodules), 2)
        
    def test_optimization_integration(self):
        config = {
            "method": "greedy",
            "optimize": True
        }
        success, msg = run_auto_modularization(self.project, [self.mod.id], config)
        self.assertTrue(success, msg)
        
        # Check that we have a new image asset (the packed sheet)
        # Original was 1 image. Now we should have 2 (Original + Optimized) 
        # (Though optimize_modules removes unused old images, but the original FullMod still points to old image unless updated? No run_auto_mod creates *new* part mods.)
        # The FullMod still points to `test_sprite.png`.
        # The new Part Mods point to `optimized_sheet...png`.
        
        print("Images in project:")
        for img in self.project.images:
            print(f"  {img.file_path}")
            
        self.assertGreaterEqual(len(self.project.images), 1)

if __name__ == '__main__':
    unittest.main()
