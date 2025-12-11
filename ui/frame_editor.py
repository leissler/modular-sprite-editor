"""Frame editor panel for assembling modules with visual palette."""

from __future__ import annotations

from typing import Optional
import wx

from models import Project, Frame, generate_id
from models import Project, Frame, generate_id
from ui.canvas import FrameCanvas
from ui.collision_manager import CollisionManagerPanel

class ModulePalette(wx.ListCtrl):
    """Visual list of modules draggable onto the canvas."""
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, style=wx.LC_ICON | wx.LC_SINGLE_SEL | wx.LC_AUTOARRANGE)
        self.project = project
        self.image_list = wx.ImageList(64, 64)
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.on_begin_drag)
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)
        
        # Map item_idx -> (normal_image_idx, selected_image_idx)
        self.item_images = {}

    def refresh_modules(self):
        self.DeleteAllItems()
        self.image_list.RemoveAll()
        self.item_images.clear()
        
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
                        # Box is 64x64. Reserve 2px padding at bottom for border.
                        # (Previously 0 padding caused overlap with highlight)
                        off_x = (64 - new_w) // 2
                        off_y = 64 - new_h - 2
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
            
            # Create Selected Version
            sel_bmp = bmp.GetSubBitmap(wx.Rect(0, 0, 64, 64))
            dc_sel = wx.MemoryDC(sel_bmp)
            
            # Draw highlight border ONLY (no fill)
            # Content is max 56x56 centered (approx 4px margin).
            # Draw border at edges to avoid overlap.
            # Using 1,1 62x62 with 2px pen implies striking approx pixels 0-2 and 61-63.
            dc_sel.SetBrush(wx.TRANSPARENT_BRUSH)
            # Pen alignment is usually CENTER. width 2 -> +/- 1 pixel.
            # Drawing at 1 -> range 0 to 2.
            # Drawing at 62 -> range 61 to 63.
            # Grid 0..63.
            dc_sel.SetPen(wx.Pen(wx.Colour(0, 120, 215), 2))
            dc_sel.DrawRoundedRectangle(1, 1, 62, 62, 4)
            dc_sel.SelectObject(wx.NullBitmap)
            
            idx_norm = self.image_list.Add(bmp)
            idx_sel = self.image_list.Add(sel_bmp)
            
            self.InsertItem(self.GetItemCount(), mod.name, idx_norm)
            item_idx = self.GetItemCount() - 1
            self.SetItemData(item_idx, item_idx) 
            self.item_images[item_idx] = (idx_norm, idx_sel)
                
        self.module_ids = [m.id for m in self.project.modules]

    def on_item_selected(self, event):
        idx = event.GetIndex()
        if idx in self.item_images:
            self.SetItemImage(idx, self.item_images[idx][1]) # Set Selected Image

    def on_item_deselected(self, event):
        idx = event.GetIndex()
        if idx in self.item_images:
             self.SetItemImage(idx, self.item_images[idx][0]) # Set Normal Image

    def on_begin_drag(self, event):
        idx = event.GetIndex()
        if idx >= 0 and idx < len(self.module_ids):
            mid = self.module_ids[idx]
            text_data = wx.TextDataObject(f"MODULE:{mid}")
            source = wx.DropSource(self)
            source.SetData(text_data)
            source.DoDragDrop(wx.Drag_CopyOnly)

    def select_module(self, module_id: str):
        try:
            idx = self.module_ids.index(module_id)
            # Deselect all? The control handles graphical deselect if we change focus,
            # but modifying image requires triggering deselect event or manual.
            # Programmatic SetItemState triggers EVT_LIST_ITEM_SELECTED/DESELECTED usually?
            # Let's hope so. If not, manual update needed.
            
            # Native ListCtrl behavior: setting state to selected usually deselects others if SINGLE_SEL.
            
            # Ensure visible
            self.EnsureVisible(idx)
            
            # Set State
            self.SetItemState(idx, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
            
        except ValueError:
            pass # Module not found

class FrameListDropTarget(wx.TextDropTarget):
    def __init__(self, editor: FrameEditorPanel):
        super().__init__()
        self.editor = editor
        self.last_item = -1
        self.last_scroll_time = 0.0
        self.last_line_y = -1
        self.overlay = wx.Overlay()
        
    def _get_insertion_point(self, x, y) -> Tuple[int, int]:
        """Calculates (insert_index, y_coord) for the insertion line."""
        list_ctrl = self.editor.frame_list
        idx, flags = list_ctrl.HitTest(wx.Point(x, y))
        
        if idx != wx.NOT_FOUND:
            rect = list_ctrl.GetItemRect(idx)
            mid = rect.y + rect.height // 2
            
            if y < mid:
                # Insert Before
                return idx, rect.y
            else:
                # Insert After
                return idx + 1, rect.y + rect.height
        else:
            # Below limits?
            count = list_ctrl.GetItemCount()
            if count > 0:
                rect = list_ctrl.GetItemRect(count - 1)
                if y > rect.y + rect.height:
                    return count, rect.y + rect.height
                
            # Empty list
            if count == 0:
                return 0, 0
                
            return wx.NOT_FOUND, -1
        
    def OnDragOver(self, x, y, defResult):
        # Auto-scroll
        # Throttled to avoid rocketing through the list
        import time
        now = time.time()
        
        list_ctrl = self.editor.frame_list
        w, h = list_ctrl.GetClientSize()
        
        # Only scroll if "near edge" (overshoot isn't reliably detected by DropTarget)
        should_scroll = False
        scroll_dy = 0
        
        offset = 20
        if y < offset:
            scroll_dy = -20 # Scroll Up 20px
            should_scroll = True
        elif y > h - offset:
            scroll_dy = 20 # Scroll Down 20px
            should_scroll = True
            
        if should_scroll and (now - self.last_scroll_time > 0.1): # 0.1s throttle (~10 items/sec)
            top = list_ctrl.GetTopItem()
            count_per_page = list_ctrl.GetCountPerPage()
            total = list_ctrl.GetItemCount()
            
            if scroll_dy < 0: # Up
                 if top > 0:
                     list_ctrl.EnsureVisible(top - 1)
                     self.last_scroll_time = now
            elif scroll_dy > 0: # Down
                 # Calculate last visible item
                 # EnsureVisible(last + 1) scrolls it into view (usually 1 step)
                 next_idx = top + count_per_page
                 if next_idx < total:
                     list_ctrl.EnsureVisible(next_idx)
                     self.last_scroll_time = now

        # Visual Feedback: Insertion Line using Overlay
        ins_idx, line_y = self._get_insertion_point(x, y)
        
        if line_y != self.last_line_y:
            dc = wx.ClientDC(list_ctrl)
            odc = wx.DCOverlay(self.overlay, dc)
            odc.Clear()
            
            if line_y != -1:
                dc.SetPen(wx.Pen(wx.Colour(0, 120, 215), 2))
                dc.DrawLine(0, line_y, w, line_y)
                
            del odc # Finishes the overlay drawing
            self.last_line_y = line_y
        
        return defResult

    def OnLeave(self):
        self.editor.frame_list.Refresh() 
        # Overlay clear usually needs DCOverlay.Clear() but we don't catch OnLeave reliably?
        # Creating a temp overlay context to clear:
        dc = wx.ClientDC(self.editor.frame_list)
        odc = wx.DCOverlay(self.overlay, dc)
        odc.Clear()
        del odc
        self.overlay.Reset()
        self.last_line_y = -1

    def OnDropText(self, x, y, data):
        # Cleanup
        self.OnLeave()
        
        if not data.startswith("FRAME:"):
            return False
            
        try:
            src_idx = int(data.split(":")[1])
        except ValueError:
            return False
            
        # Find target index using helper
        target_idx, _ = self._get_insertion_point(x, y)
        if target_idx == wx.NOT_FOUND:
            target_idx = self.editor.frame_list.GetItemCount()
            
        self.editor.move_frame(src_idx, target_idx)
        return True

class FrameEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_frame_id: Optional[str] = None
        
        # Layout
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Left Panel: Frames List + Module Palette
        left_panel = wx.Panel(self)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Frames List (ListCtrl for better DnD and Inline Rename)
        left_sizer.Add(wx.StaticText(left_panel, label="Frames"), 0, wx.ALL, 5)
        self.frame_list = wx.ListCtrl(left_panel, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.LC_EDIT_LABELS)
        self.frame_list.InsertColumn(0, "Frame", width=180) # Auto-size later?
        self.frame_list.Bind(wx.EVT_CONTEXT_MENU, self.on_frame_list_context_menu)
        
        # QoL: Rename & Reorder
        self.frame_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_frame_dclick) # Double click
        self.frame_list.Bind(wx.EVT_LIST_BEGIN_DRAG, self.on_frame_begin_drag)
        self.frame_list.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.on_frame_end_edit)
        self.frame_list.SetDropTarget(FrameListDropTarget(self))
        
        left_sizer.Add(self.frame_list, 1, wx.EXPAND | wx.ALL, 5)
        
        frame_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(left_panel, label="+")
        self.btn_del = wx.Button(left_panel, label="-")
        self.btn_mode = wx.ToggleButton(left_panel, label="Mode: Modules")
        self.chk_show_col = wx.CheckBox(left_panel, label="Show Colliders")
        
        frame_btns.Add(self.btn_add, 0)
        frame_btns.Add(self.btn_del, 0)
        frame_btns.Add(self.btn_mode, 1, wx.LEFT, 5)
        
        left_sizer.Add(frame_btns, 0, wx.EXPAND | wx.ALL, 5)
        left_sizer.Add(self.chk_show_col, 0, wx.ALL, 5)

        # Module Palette
        self.lbl_modules = wx.StaticText(left_panel, label="Modules (Drag to Canvas)")
        left_sizer.Add(self.lbl_modules, 0, wx.ALL, 5)
        self.palette = ModulePalette(left_panel, project)
        left_sizer.Add(self.palette, 1, wx.EXPAND | wx.ALL, 5)
        
        # Collision Manager (Hidden by default)
        self.col_manager = CollisionManagerPanel(left_panel, project, on_change=self.on_col_type_change)
        left_sizer.Add(self.col_manager, 1, wx.EXPAND | wx.ALL, 5)
        left_sizer.Hide(self.col_manager)
        
        left_panel.SetSizer(left_sizer)
        
        # Center: Canvas
        self.canvas = FrameCanvas(self, project)
        self.canvas.on_create_frame_needed = self.on_auto_create_frame
        
        main_sizer.Add(left_panel, 0, wx.EXPAND)
        main_sizer.Add(self.canvas, 1, wx.EXPAND)
        
        self.SetSizer(main_sizer)
        
        # Bindings
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_frame, self.frame_list)
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add_frame)
        self.btn_del.Bind(wx.EVT_BUTTON, self.on_delete_frame)
        self.btn_mode.Bind(wx.EVT_TOGGLEBUTTON, self.on_toggle_mode)
        self.chk_show_col.Bind(wx.EVT_CHECKBOX, self.on_toggle_show_col)
        
        self.palette.refresh_modules()
        self.refresh_frames()
        self.on_col_type_change() # Init color map
        
        # Canvas Interaction Events
        # Canvas Interaction Events
        self.canvas.Bind(wx.EVT_RIGHT_DOWN, self.on_canvas_right_down)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        # Sync selection
        self.canvas.on_selection_changed = self.on_canvas_selection_changed
        
    def on_canvas_selection_changed(self, selected_ids: List[str]):
        if not selected_ids:
            return
            
        # For now just sync different module types if one selected
        # If multiple, maybe just the first one?
        fid = selected_ids[0]
        fm = next((f for f in self.project.get_frame(self.selected_frame_id).fmodules if f.id == fid), None)
        if fm and fm.ref_type == "module":
            self.palette.select_module(fm.ref_id)

    def on_canvas_right_down(self, event: wx.MouseEvent):
        # Suppress context menu if in collision mode
        if self.canvas.edit_mode == "collision":
            return

        # Hit test to see if we clicked a module
        pos = self.canvas.screen_to_world(event.GetPosition())
        clicked_fmod = self.canvas.hit_test(pos)
        
        menu = wx.Menu()
        
        if clicked_fmod:
            # clicked_fmod is an object, but selected_fmodules stores IDs
            if clicked_fmod.id not in self.canvas.selected_fmodules:
                self.canvas.selected_fmodules = [clicked_fmod.id]
                self.canvas.Refresh()
                
            # Module actions
            flip_x_item = menu.Append(wx.ID_ANY, "Flip Horizontal (X)")
            flip_y_item = menu.Append(wx.ID_ANY, "Flip Vertical (Y)")
            menu.AppendSeparator()
            
            # Use ID for binding, binding to item object is flaky depending on wx version/context
            self.Bind(wx.EVT_MENU, self.on_flip_x, id=flip_x_item.GetId())
            self.Bind(wx.EVT_MENU, self.on_flip_y, id=flip_y_item.GetId())
            
            menu.AppendSeparator()
            menu.AppendSeparator()
            z_up_item = menu.Append(wx.ID_ANY, "Move Forward (Cmd \u2191)")
            z_down_item = menu.Append(wx.ID_ANY, "Move Backwards (Cmd \u2193)")
            z_top_item = menu.Append(wx.ID_ANY, "To Front (Shift Cmd \u2191)")
            z_bottom_item = menu.Append(wx.ID_ANY, "To Back (Shift Cmd \u2193)")
            
            self.Bind(wx.EVT_MENU, lambda e: self._change_z_order("up"), id=z_up_item.GetId())
            self.Bind(wx.EVT_MENU, lambda e: self._change_z_order("down"), id=z_down_item.GetId())
            self.Bind(wx.EVT_MENU, lambda e: self._change_z_order("top"), id=z_top_item.GetId())
            self.Bind(wx.EVT_MENU, lambda e: self._change_z_order("bottom"), id=z_bottom_item.GetId())
            
            menu.AppendSeparator()
            delete_item = menu.Append(wx.ID_ANY, "Delete (Del/Backspace)")
            self.Bind(wx.EVT_MENU, lambda e: self._delete_selected_modules(), id=delete_item.GetId())

        if menu.GetMenuItemCount() > 0:
            self.PopupMenu(menu)
        menu.Destroy()

    def on_flip_x(self, event):
        self._toggle_flip(param="x")

    def on_flip_y(self, event):
        self._toggle_flip(param="y")

    def _toggle_flip(self, param: str):
         frame = self.canvas.frame
         if not frame: return
         
         changed = False
         for fm in frame.fmodules:
             if fm.id in self.canvas.selected_fmodules:
                 if param == "x":
                     fm.flip_x = not fm.flip_x
                 elif param == "y":
                     fm.flip_y = not fm.flip_y
                 changed = True
         
         if changed:
             self.canvas.Refresh()

    def _change_z_order(self, direction: str):
        if not self.canvas.frame or not self.canvas.selected_fmodules:
            return
            
        fmodules = self.canvas.frame.fmodules
        selected_ids = set(self.canvas.selected_fmodules)
        
        # Get indices of all selected items
        # Create list of (index, item) tuples
        indices = [i for i, f in enumerate(fmodules) if f.id in selected_ids]
        
        if not indices: 
            return

        if direction == "up":
            # Move UP: Iterate from highest index down. 
            # Swap with next item if next item is NOT selected.
            # This allows a block to move up past unselected items, but stay relative to each other.
            for i in reversed(indices):
                if i < len(fmodules) - 1:
                    # Check if next item is unselected. If it IS selected, we can't "move up" into it (it will move too)
                    # Actually simpler: just swap with next if next is not in current active selection set (indices).
                    # But we are modifying list in place.
                    next_idx = i + 1
                    if fmodules[next_idx].id not in selected_ids:
                         fmodules[i], fmodules[next_idx] = fmodules[next_idx], fmodules[i]
                         
        elif direction == "down":
            # Move DOWN: Iterate from lowest index up.
            for i in indices:
                if i > 0:
                    prev_idx = i - 1
                    if fmodules[prev_idx].id not in selected_ids:
                        fmodules[i], fmodules[prev_idx] = fmodules[prev_idx], fmodules[i]

        elif direction == "top":
            # Extract all selected, append to end
            # Maintain relative order of selected
            selected_items = [fmodules[i] for i in indices]
            # Remove from list (indices change, so filter)
            fmodules[:] = [f for f in fmodules if f.id not in selected_ids]
            fmodules.extend(selected_items)
            
        elif direction == "bottom":
             # Extract all selected, insert at front
             selected_items = [fmodules[i] for i in indices]
             fmodules[:] = [f for f in fmodules if f.id not in selected_ids]
             fmodules[0:0] = selected_items
             
        self.canvas.Refresh()

    def _delete_selected_modules(self):
        if not self.canvas.frame or not self.canvas.selected_fmodules:
            return
            
        # Ensure we don't modify list while iterating if we were doing that
        # Rebuild list excluding deleted ones
        selected = set(self.canvas.selected_fmodules)
        new_list = [fm for fm in self.canvas.frame.fmodules if fm.id not in selected]
        
        self.canvas.frame.fmodules = new_list
        self.canvas.selected_fmodules = []
        self.canvas.Refresh()

    def _delete_selected_collision_rects(self):
        if not self.canvas.frame or not self.canvas.selected_collision_rects:
            return
            
        selected = set(self.canvas.selected_collision_rects)
        new_list = [cr for cr in self.canvas.frame.collision_rects if cr.id not in selected]
        
        self.canvas.frame.collision_rects = new_list
        self.canvas.selected_collision_rects = []
        self.canvas.Refresh()

    def on_key_down(self, event: wx.KeyEvent):
        # Checking if canvas or panel has focus might be needed, 
        # but CHAR_HOOK catches globally in this window.
        keycode = event.GetKeyCode()
        
        # Only process if we are visible?
        if not self.IsShownOnScreen():
            event.Skip()
            return
            
        # If a text control has focus (e.g. rename list item), skip CHAR_HOOK logic
        # so the native widget handles Backspace/Delete.
        focus = wx.Window.FindFocus()
        if focus and isinstance(focus, wx.TextCtrl):
             event.Skip()
             return

        if keycode == ord('X'):
            self._toggle_flip("x")
        elif keycode == ord('Y'):
            self._toggle_flip("y")
        elif (keycode == wx.WXK_UP) and (event.CmdDown() or event.ControlDown()):
             if event.ShiftDown():
                 self._change_z_order("top")
             else:
                 self._change_z_order("up")
        elif (keycode == wx.WXK_DOWN) and (event.CmdDown() or event.ControlDown()):
             if event.ShiftDown():
                 self._change_z_order("bottom")
             else:
                 self._change_z_order("down")
        elif keycode == wx.WXK_DELETE or keycode == wx.WXK_BACK:
             if self.canvas.edit_mode == "collision":
                 self._delete_selected_collision_rects()
             else:
                 self._delete_selected_modules()
        else:
            event.Skip()

    def on_auto_create_frame(self) -> Optional[Frame]:
        # Called by canvas when dropping on empty
        self.on_add_frame(None)
        # on_add_frame selects the new frame, so we can retrieve it
        if self.selected_frame_id:
            return self.project.get_frame(self.selected_frame_id)
        return None

    def refresh_frames(self, select_id: Optional[str] = None):
        self.frame_list.DeleteAllItems()
        target_idx = -1
        for idx, f in enumerate(self.project.frames):
            self.frame_list.InsertItem(idx, f.name)
            self.frame_list.SetItemData(idx, idx) # We track by index mostly now, or map later if needed.
            # Storing ID would require String->Int map in C++, py ListCtrl is finicky. 
            # We assume order matches project.frames.
            
            if select_id and f.id == select_id:
                target_idx = idx
                
        if target_idx != -1:
            self.frame_list.Select(target_idx)
            self.frame_list.EnsureVisible(target_idx)
            
    def on_frame_list_context_menu(self, event):
        sel = self.frame_list.GetFirstSelected()
        if sel == wx.NOT_FOUND:
            return
            
        # Assuming list order == project order
        fid = self.project.frames[sel].id
        
        menu = wx.Menu()
        dup_item = menu.Append(wx.ID_ANY, "Duplicate Frame")
        menu.AppendSeparator()
        flip_h_item = menu.Append(wx.ID_ANY, "Flip Horizontal (X)")
        flip_v_item = menu.Append(wx.ID_ANY, "Flip Vertical (Y)")
        
        self.Bind(wx.EVT_MENU, lambda e: self._duplicate_frame(fid), id=dup_item.GetId())
        self.Bind(wx.EVT_MENU, lambda e: self._flip_frame(fid, "x"), id=flip_h_item.GetId())
        self.Bind(wx.EVT_MENU, lambda e: self._flip_frame(fid, "y"), id=flip_v_item.GetId())
        
        self.PopupMenu(menu)
        menu.Destroy()
        
    def _duplicate_frame(self, fid: str):
        frame = self.project.get_frame(fid)
        if not frame: return
        
        # Deep copy via serialization
        data = frame.to_dict()
        new_frame = Frame.from_dict(data)
        
        # Ensure unique IDs
        new_frame.id = generate_id("frame")
        new_frame.name = f"{frame.name} (Copy)"
        
        # Regenerate FModule IDs to avoid sharing references
        for fm in new_frame.fmodules:
            fm.id = generate_id("fmod")
            
        self.project.frames.append(new_frame)
        self.refresh_frames(select_id=new_frame.id)
        self.on_select_frame(None) # Event arg ignored manually called
        self.canvas.Refresh()

    def _flip_frame(self, fid: str, axis: str):
        frame = self.project.get_frame(fid)
        if not frame: return
        
        for fm in frame.fmodules:
            # Need module info for bounds/pivot compensation
            mod = self.project.get_module(fm.ref_id)
            if not mod: continue
            
            w, h = mod.rect[2], mod.rect[3]
            px, py = mod.pivot
            
            if axis == "x":
                # Flip X pos relative to 0 (origin)
                # Formula: new_x = -old_x + (2*px - w)
                # This compensates for the pivot remaining fixed in image-space even when flipped.
                new_x = -fm.position[0] + (2 * px - w)
                fm.position = (new_x, fm.position[1])
                # Flip the module itself
                fm.flip_x = not fm.flip_x
            elif axis == "y":
                # Formula: new_y = -old_y + (2*py - h)
                new_y = -fm.position[1] + (2 * py - h)
                fm.position = (fm.position[0], new_y)
                fm.flip_y = not fm.flip_y
                
        self.canvas.Refresh()
            
    def refresh_choices(self):
        """Called by app.py when switching tools."""
        self.palette.refresh_modules()
        # In new design, frame list is always visible, but good update point
        self.refresh_frames(self.selected_frame_id)

    # QoL Implementations
    def on_frame_dclick(self, event):
        idx = event.GetIndex()
        if idx != -1:
            self.frame_list.EditLabel(idx)

    def on_frame_end_edit(self, event):
        if event.IsEditCancelled():
            return
            
        new_name = event.GetLabel()
        idx = event.GetIndex()
        
        if 0 <= idx < len(self.project.frames):
            frame = self.project.frames[idx]
            if new_name and new_name != frame.name:
                frame.name = new_name
                # self.refresh_frames(frame.id) # No need to refresh entire list, label is updated by Ctrl
                
    def on_frame_begin_drag(self, event):
        idx = event.GetIndex()
        if idx != -1:
            text_data = wx.TextDataObject(f"FRAME:{idx}")
            source = wx.DropSource(self.frame_list)
            source.SetData(text_data)
            source.DoDragDrop(wx.Drag_DefaultMove)
            
    def move_frame(self, src_idx: int, target_idx: int):
        if src_idx == target_idx:
            return
            
        # Reorder in project
        if 0 <= src_idx < len(self.project.frames):
            frame = self.project.frames.pop(src_idx)
            
            # Adjust target index if shifting
            if target_idx > src_idx:
                target_idx -= 1
            
            # Clamp
            target_idx = max(0, min(target_idx, len(self.project.frames)))
            
            self.project.frames.insert(target_idx, frame)
            self.refresh_frames(frame.id)
            self.on_select_frame(None)
            
    def set_project(self, project: Project):
        self.project = project
        self.canvas.project = project
        self.palette.project = project
        self.col_manager.project = project # Fix: Update manager
        self.col_manager.refresh_list()    # Fix: Refresh UI
        self.palette.refresh_modules()
        self.refresh_frames()
        self.canvas.set_frame(None)
        
        # Ensure canvas has correct collision colors immediately
        self.on_col_type_change()

    def on_select_frame(self, event):
        idx = event.GetIndex() if event else self.frame_list.GetFirstSelected()
        if idx != -1:
            # Assume list order == project order
            if 0 <= idx < len(self.project.frames):
                frame = self.project.frames[idx]
                self.selected_frame_id = frame.id
                self.canvas.set_frame(frame)
        else:
            self.canvas.set_frame(None)
    
    def on_toggle_mode(self, event):
        is_col = self.btn_mode.GetValue()
        if is_col:
            self.btn_mode.SetLabel("Mode: Collisions")
            self.canvas.edit_mode = "collision"
            
            self.lbl_modules.Hide()
            self.palette.Hide()
            self.col_manager.Show()
            
            # Sync active type
            if self.col_manager.active_type_id:
                self.canvas.active_collision_type_id = self.col_manager.active_type_id
        else:
            self.btn_mode.SetLabel("Mode: Modules")
            self.canvas.edit_mode = "module"
            
            self.lbl_modules.Show()
            self.palette.Show()
            self.col_manager.Hide()
            
        self.left_panel_layout()
        self.canvas.Refresh()
        
    def left_panel_layout(self):
        # Trigger layout on the parent of the hidden/shown items
        self.frame_list.GetParent().Layout()

    def on_col_type_change(self):
        self.canvas.active_collision_type_id = self.col_manager.active_type_id
        # Sync visibility AND color map
        # Optimization: Pass a map of {id: color} for ONLY visible types.
        # Canvas then just does: color = self.collision_type_colors.get(cr.type_id)
        # If None, don't draw.
        visible_map = {}
        for ct in self.project.collision_types:
             if self.col_manager.visibility.get(ct.id, True):
                 visible_map[ct.id] = ct.color
                 
        self.canvas.collision_type_colors = visible_map
        self.canvas.Refresh()

    def on_toggle_show_col(self, event):
        self.canvas.show_collision = self.chk_show_col.GetValue()
        self.canvas.Refresh()

    def on_add_frame(self, _):
        # Manually create frame (models.py doesn't have create_frame helper on Project)
        new_frame_id = generate_id("frm")
        frame = Frame(
            id=new_frame_id,
            name=f"Frame {len(self.project.frames)+1}"
        )
        self.project.frames.append(frame)
        
        self.selected_frame_id = frame.id
        self.refresh_frames(select_id=frame.id)
        self.canvas.set_frame(frame)
        
    def on_delete_frame(self, _):
        if self.selected_frame_id:
             self.project.frames = [f for f in self.project.frames if f.id != self.selected_frame_id]
             self.selected_frame_id = None
             self.refresh_frames()
             self.canvas.set_frame(None)
