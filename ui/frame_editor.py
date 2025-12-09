"""Frame editor panel for assembling modules with visual palette."""

from __future__ import annotations

from typing import Optional
import wx

from models import Project, Frame, generate_id
from ui.canvas import FrameCanvas

class ModulePalette(wx.ListCtrl):
    """Visual list of modules draggable onto the canvas."""
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, style=wx.LC_ICON | wx.LC_SINGLE_SEL | wx.LC_AUTOARRANGE)
        self.project = project
        self.image_list = wx.ImageList(64, 64)
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.on_begin_drag)

    def refresh_modules(self):
        self.DeleteAllItems()
        self.image_list.RemoveAll()
        
        # Cache loaded images to avoid re-reading from disk for every module
        # Key: image_id, Value: wx.Image
        source_images = {}
        
        for mod in self.project.modules:
            # Create thumbnail
            bmp = wx.Bitmap(64, 64)
            dc = wx.MemoryDC(bmp)
            dc.SetBackground(wx.Brush(wx.Colour(50, 50, 50)))
            dc.Clear()
            
            asset = self.project.get_image(mod.image_id)
            if asset:
                try:
                    # Check cache first
                    if asset.id in source_images:
                        img = source_images[asset.id]
                    else:
                        img = wx.Image(asset.file_path)
                        # Apply mask if transparent color is set
                        if asset.transparent_color:
                             # transparent_color is (r, g, b)
                             img.SetMaskColour(*asset.transparent_color)
                        source_images[asset.id] = img
                    
                    # Crop module rect from source image
                    # mod.rect is (x, y, w, h)
                    rx, ry, rw, rh = mod.rect
                    
                    # Validate rect is within image bounds
                    img_w, img_h = img.GetWidth(), img.GetHeight()
                    if rx + rw <= img_w and ry + rh <= img_h:
                        sub_img = img.GetSubImage(wx.Rect(rx, ry, rw, rh))
                        
                        # Calculate scale to MAXIMIZE size within 56x56 box (with padding)
                        available_w, available_h = 56, 56
                        
                        # Calculate scale factor to fit
                        scale_w = available_w / rw
                        scale_h = available_h / rh
                        final_scale = min(scale_w, scale_h)
                        
                        # Enforce at least 1.0 (don't downscale if it fits, actually we typically want validation,
                        # but here we want to Maximize, so upscaling IS desired for small sprites)
                        
                        new_w = int(rw * final_scale)
                        new_h = int(rh * final_scale)
                        
                        # Only rescale if dimensions change
                        if new_w != rw or new_h != rh:
                             sub_img.Rescale(new_w, new_h, wx.IMAGE_QUALITY_NEAREST)
                        
                        # Draw centered horizontally, but aligned to BOTTOM vertically
                        # to reduce gap between image and text.
                        # Box is 64x64. Reserve 0px padding at bottom (User requested minimal gap).
                        off_x = (64 - new_w) // 2
                        off_y = 64 - new_h 
                        dc.DrawBitmap(sub_img.ConvertToBitmap(), off_x, off_y, True)
                    else:
                        dc.SetPen(wx.Pen(wx.Colour(200, 50, 50)))
                        dc.DrawLine(0, 0, 64, 64)
                        dc.DrawLine(64, 0, 0, 64)
                except Exception as e:
                    # print(f"Failed to load thumb for {mod.name}: {e}")
                    dc.SetPen(wx.Pen(wx.Colour(200, 50, 50)))
                    dc.DrawLine(0, 0, 64, 64)
                    dc.DrawLine(64, 0, 0, 64)
            else:
                 # Draw "module" placeholder
                dc.SetPen(wx.Pen(wx.Colour(100, 100, 100)))
                dc.SetBrush(wx.Brush(wx.Colour(70, 70, 70)))
                dc.DrawRectangle(4, 4, 56, 56)
            
            dc.SelectObject(wx.NullBitmap)
            
            idx = self.image_list.Add(bmp)
            self.InsertItem(self.GetItemCount(), mod.name, idx)
            item_idx = self.GetItemCount() - 1
            self.SetItemData(item_idx, item_idx) 
                
        self.module_ids = [m.id for m in self.project.modules]

    def on_begin_drag(self, event):
        idx = event.GetIndex()
        if idx >= 0 and idx < len(self.module_ids):
            mid = self.module_ids[idx]
            text_data = wx.TextDataObject(f"MODULE:{mid}")
            source = wx.DropSource(self)
            source.SetData(text_data)
            source.DoDragDrop(wx.Drag_CopyOnly)

class FrameEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_frame_id: Optional[str] = None
        
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Left Split: Palette & Frames
        left_panel = wx.Panel(self, size=(250, -1))
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Frames List
        left_sizer.Add(wx.StaticText(left_panel, label="Frames"), 0, wx.ALL, 5)
        self.frame_list = wx.ListBox(left_panel)
        left_sizer.Add(self.frame_list, 1, wx.EXPAND | wx.ALL, 5)
        
        frame_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(left_panel, label="+")
        self.btn_del = wx.Button(left_panel, label="-")
        frame_btns.Add(self.btn_add, 1)
        frame_btns.Add(self.btn_del, 1)
        left_sizer.Add(frame_btns, 0, wx.EXPAND | wx.ALL, 5)

        # Module Palette
        left_sizer.Add(wx.StaticText(left_panel, label="Modules (Drag to Canvas)"), 0, wx.ALL, 5)
        self.palette = ModulePalette(left_panel, project)
        left_sizer.Add(self.palette, 1, wx.EXPAND | wx.ALL, 5)
        
        left_panel.SetSizer(left_sizer)
        
        # Center: Canvas
        self.canvas = FrameCanvas(self, project)
        self.canvas.on_create_frame_needed = self.on_auto_create_frame
        
        main_sizer.Add(left_panel, 0, wx.EXPAND)
        main_sizer.Add(self.canvas, 1, wx.EXPAND)
        
        self.SetSizer(main_sizer)
        
        # Bindings
        self.Bind(wx.EVT_LISTBOX, self.on_select_frame, self.frame_list)
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add_frame)
        self.btn_del.Bind(wx.EVT_BUTTON, self.on_delete_frame)
        
        self.palette.refresh_modules()
        self.refresh_frames()

    def on_auto_create_frame(self) -> Optional[Frame]:
        # Called by canvas when dropping on empty
        self.on_add_frame(None)
        # on_add_frame selects the new frame, so we can retrieve it
        if self.selected_frame_id:
            return self.project.get_frame(self.selected_frame_id)
        return None

    def refresh_frames(self, select_id: Optional[str] = None):
        self.frame_list.Clear()
        for idx, f in enumerate(self.project.frames):
            self.frame_list.Append(f.name, clientData=f.id)
            if select_id and f.id == select_id:
                self.frame_list.SetSelection(idx)
        if select_id and self.frame_list.GetSelection() == wx.NOT_FOUND:
            self.frame_list.SetSelection(wx.NOT_FOUND)
            
    def refresh_choices(self):
        """Called by app.py when switching tools."""
        self.palette.refresh_modules()
        # In new design, frame list is always visible, but good update point
        self.refresh_frames(self.selected_frame_id)
            
    def set_project(self, project: Project):
        self.project = project
        self.canvas.project = project
        self.palette.project = project
        self.palette.refresh_modules()
        self.refresh_frames()
        self.canvas.set_frame(None)

    def on_select_frame(self, event):
        idx = event.GetSelection()
        if idx != wx.NOT_FOUND:
            fid = self.frame_list.GetClientData(idx)
            self.selected_frame_id = fid
            frame = self.project.get_frame(fid)
            self.canvas.set_frame(frame)
    
    def on_add_frame(self, _):
        frame = self.project.create_frame(f"Frame {len(self.project.frames)+1}")
        self.selected_frame_id = frame.id
        self.refresh_frames(select_id=frame.id)
        self.canvas.set_frame(frame)
        
    def on_delete_frame(self, _):
        if self.selected_frame_id:
             self.project.frames = [f for f in self.project.frames if f.id != self.selected_frame_id]
             self.selected_frame_id = None
             self.refresh_frames()
             self.canvas.set_frame(None)
