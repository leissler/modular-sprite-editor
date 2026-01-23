"""Frame editor panel for assembling modules with visual palette."""

from __future__ import annotations

from typing import Optional, List, Tuple
import copy
import wx

from models import Project, Frame, generate_id
from ui.canvas import FrameCanvas
from ui.collision_manager import CollisionManagerPanel
from ui.point_manager import PointManagerPanel
from ui.utils import render_pixel_shape_to_bitmap

class ModulePalette(wx.ListCtrl):
    """Visual list of modules draggable onto the canvas."""
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, style=wx.LC_ICON | wx.LC_SINGLE_SEL | wx.LC_AUTOARRANGE)
        self.project = project
        self.image_list = wx.ImageList(96, 96)
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.Bind(wx.EVT_LIST_BEGIN_DRAG, self.on_begin_drag)
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)
        
        # Map item_idx -> (normal_image_idx, selected_image_idx)
        self.item_images = {}
        self.module_ids = []

        # Persistent Caches
        self._source_images = {} # asset_id -> wx.Image
        self._thumb_cache = {}   # (mod_id, rect, scale, trans_color) -> (bmp, sel_bmp)
        self._last_scale = 0.0
        self._last_fingerprint = None

    def refresh_modules(self):
        # 1. Check if actually needed (skip if data hasn't changed)
        # Fingerprint covers: count, identities, and visual properties (rect, name)
        current_fingerprint = (len(self.project.modules), tuple((m.id, m.name, m.rect) for m in self.project.modules))
        if current_fingerprint == self._last_fingerprint:
            return
        self._last_fingerprint = current_fingerprint

        # Aggressive cleanup of ListCtrl state, but NOT our persistent caches
        self.SetImageList(None, wx.IMAGE_LIST_NORMAL)
        self.DeleteAllItems()
        
        item_side = 96
        self.image_list = wx.ImageList(item_side, item_side)
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.item_images.clear()
        
        if not self.project.modules:
            self.module_ids = []
            return

        # 1. Calculate Global Uniform Scale
        # Find max dimension across ALL modules to preserve relative sizes
        max_mod_w, max_mod_h = 0, 0
        for m in self.project.modules:
            max_mod_w = max(max_mod_w, m.rect[2])
            max_mod_h = max(max_mod_h, m.rect[3])
        
        # Available area inside 96x96 box (leaving margin for highlight/padding)
        available_w, available_h = 86, 86
        if max_mod_w > 0 and max_mod_h > 0:
            scale_w = available_w / max_mod_w
            scale_h = available_h / max_mod_h
            uniform_scale = min(scale_w, scale_h)
        else:
            uniform_scale = 1.0

        # Invalidate thumbnail cache if global scale changed
        if abs(self._last_scale - uniform_scale) > 0.001:
            self._thumb_cache.clear()
            self._last_scale = uniform_scale

        for mod in self.project.modules:
            asset = self.project.get_image(mod.image_id)
            trans_color = asset.transparent_color if asset else None
            
            # Key for thumbnail cache: mod ID + geometry + scale context
            cache_key = (mod.id, mod.rect, uniform_scale, trans_color)
            
            if cache_key in self._thumb_cache:
                bmp, sel_bmp = self._thumb_cache[cache_key]
            else:
                # Need to generate
                bmp = wx.Bitmap(item_side, item_side)
                dc = wx.MemoryDC(bmp)
                dc.SetBackground(wx.Brush(wx.Colour(50, 50, 50)))
                dc.Clear()
                
                if asset:
                    try:
                        # Use persistent source image cache
                        if asset.id not in self._source_images:
                            img = wx.Image(asset.file_path)
                            if trans_color:
                                 img.SetMaskColour(*trans_color)
                            self._source_images[asset.id] = img
                        else:
                            img = self._source_images[asset.id]
                        
                        rx, ry, rw, rh = mod.rect
                        img_w, img_h = img.GetWidth(), img.GetHeight()
                        if rx + rw <= img_w and ry + rh <= img_h:
                            sub_img = img.GetSubImage(wx.Rect(rx, ry, rw, rh))
                            
                            # Apply global uniform scale
                            new_w = max(1, int(rw * uniform_scale))
                            new_h = max(1, int(rh * uniform_scale))
                            
                            # Only rescale if dimensions change
                            if new_w != rw or new_h != rh:
                                 sub_img.Rescale(new_w, new_h, wx.IMAGE_QUALITY_NEAREST)
                            
                            # Draw perfectly centered
                            off_x = (item_side - new_w) // 2
                            off_y = (item_side - new_h) // 2
                            dc.DrawBitmap(sub_img.ConvertToBitmap(), off_x, off_y, True)
                        else:
                            dc.SetPen(wx.Pen(wx.Colour(200, 50, 50)))
                            dc.DrawLine(0, 0, item_side, item_side)
                            dc.DrawLine(item_side, 0, 0, item_side)
                    except Exception:
                        dc.SetPen(wx.Pen(wx.Colour(200, 50, 50)))
                        dc.DrawLine(0, 0, item_side, item_side)
                        dc.DrawLine(item_side, 0, 0, item_side)
                else:
                    # Shape Module Rendering using Shared Utility
                    w, h = mod.rect[2], mod.rect[3]
                    shape_bmp = render_pixel_shape_to_bitmap(mod.type, w, h, mod.color, mod.params)
                    
                    if shape_bmp:
                        # 1. Calc scale
                        new_w = max(1, int(w * uniform_scale))
                        new_h = max(1, int(h * uniform_scale))
                        
                        # 2. Rescale (Nearest Neighbor)
                        img = shape_bmp.ConvertToImage()
                        img.Rescale(new_w, new_h, wx.IMAGE_QUALITY_NEAREST)
                        
                        # 3. Draw Centered
                        off_x = (item_side - new_w) // 2
                        off_y = (item_side - new_h) // 2
                        dc.DrawBitmap(img.ConvertToBitmap(), off_x, off_y, True)
                    else:
                        dc.SetPen(wx.Pen(wx.Colour(100, 100, 100)))
                        dc.SetBrush(wx.Brush(wx.Colour(70, 70, 70)))
                        dc.DrawRectangle(4, 4, item_side-8, item_side-8)
                
                dc.SelectObject(wx.NullBitmap)
                
                # Create Selected Version
                sel_bmp = bmp.GetSubBitmap(wx.Rect(0, 0, item_side, item_side))
                dc_sel = wx.MemoryDC(sel_bmp)
                dc_sel.SetBrush(wx.TRANSPARENT_BRUSH)
                dc_sel.SetPen(wx.Pen(wx.Colour(0, 120, 215), 2))
                dc_sel.DrawRoundedRectangle(1, 1, item_side-2, item_side-2, 4)
                dc_sel.SelectObject(wx.NullBitmap)
                
                # Store in cache
                self._thumb_cache[cache_key] = (bmp, sel_bmp)

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
    def __init__(self, editor: "FrameEditorPanel"):
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
        
        if not data.startswith("FRAME_REF:"):
            return False
            
        try:
            # Parse FRAME_REF:<idx>:<id>
            parts = data.split(":")
            src_idx = int(parts[1])
        except (ValueError, IndexError):
            return False
            
        # Find target index using helper
        target_idx, _ = self._get_insertion_point(x, y)
        if target_idx == wx.NOT_FOUND:
            target_idx = self.editor.frame_list.GetItemCount()
            
        self.editor.move_frame(src_idx, target_idx)
        return True

from ui.undo_manager import UndoManager

class FrameEditorPanel(wx.Panel):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_frame_id: Optional[str] = None
        
        self.undo_manager = UndoManager()
        
        # Clipboard
        self._clipboard_col: List = [] 
        self._clipboard_pts: List = []
        
        # Layout: Splitter
        self.splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # Left Panel: Frames List + Module Palette
        left_panel = wx.Panel(self.splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        # Frames List (ListCtrl for better DnD and Inline Rename)
        left_sizer.Add(wx.StaticText(left_panel, label="Frames"), 0, wx.ALL, 5)
        self.frame_list = wx.ListCtrl(left_panel, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.LC_EDIT_LABELS)
        self.frame_list.InsertColumn(0, "Frame", width=180) # Auto-size later?
        self.frame_list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_frame_list_context_menu)
        self.frame_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_frame_dclick)
        # Enable Drag FROM list (to reorder OR drop on canvas)
        self.frame_list.Bind(wx.EVT_LIST_BEGIN_DRAG, self.on_begin_drag_frame)
        self.frame_list.Bind(wx.EVT_LIST_BEGIN_LABEL_EDIT, self.on_begin_label_edit)
        self.frame_list.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.on_end_label_edit)
        # MouseUp binding removed
        self.frame_list.SetDropTarget(FrameListDropTarget(self))
        self.frame_list.Bind(wx.EVT_SIZE, self.on_frame_list_resize)
        
        left_sizer.Add(self.frame_list, 1, wx.EXPAND | wx.ALL, 5)
        
        frame_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(left_panel, label="+", size=(30,-1))
        self.btn_del = wx.Button(left_panel, label="-", size=(30,-1))
        
        # Mode Selection
        self.mode_choices = ["Modules", "Collision", "Points"]
        self.choice_mode = wx.Choice(left_panel, choices=self.mode_choices)
        self.choice_mode.SetSelection(0)
        
        frame_btns.Add(self.btn_add, 0)
        frame_btns.Add(self.btn_del, 0)
        frame_btns.Add(self.choice_mode, 1, wx.LEFT, 5)
        
        left_sizer.Add(frame_btns, 0, wx.EXPAND | wx.ALL, 5)
        
        # Visualization Toggles
        vvis_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_show_col = wx.CheckBox(left_panel, label="Colliders")
        self.chk_show_pts = wx.CheckBox(left_panel, label="Points")
        self.chk_show_pts.SetValue(True) 
        
        vvis_sizer.Add(self.chk_show_col, 0, wx.RIGHT, 5)
        vvis_sizer.Add(self.chk_show_pts, 0)
        
        left_sizer.Add(vvis_sizer, 0, wx.ALL, 5)

        # Module Palette
        self.lbl_modules = wx.StaticText(left_panel, label="Modules (Drag to Canvas)")
        left_sizer.Add(self.lbl_modules, 0, wx.ALL, 5)
        self.palette = ModulePalette(left_panel, project)
        left_sizer.Add(self.palette, 1, wx.EXPAND | wx.ALL, 5)
        
        # Collision Manager (Hidden by default)
        self.col_manager = CollisionManagerPanel(left_panel, project, on_change=self.on_col_type_change)
        left_sizer.Add(self.col_manager, 1, wx.EXPAND | wx.ALL, 5)
        left_sizer.Hide(self.col_manager)

        # Point Manager (Hidden by default)
        self.point_manager = PointManagerPanel(left_panel, project, on_change=self.on_point_type_change)
        left_sizer.Add(self.point_manager, 1, wx.EXPAND | wx.ALL, 5)
        left_sizer.Hide(self.point_manager)
        
        left_panel.SetSizer(left_sizer)
        
        # Right Panel: Canvas
        right_panel = wx.Panel(self.splitter)
        canvas_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.canvas = FrameCanvas(right_panel, project)
        self.canvas.on_create_frame_needed = self.on_auto_create_frame
        
        canvas_sizer.Add(self.canvas, 1, wx.EXPAND)
        right_panel.SetSizer(canvas_sizer)
        
        # Split
        self.splitter.SplitVertically(left_panel, right_panel, 340)
        self.splitter.SetMinimumPaneSize(200)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(main_sizer)
        
        # Bindings
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_frame, self.frame_list)
        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_frame_list_context_menu, self.frame_list)
        self.Bind(wx.EVT_BUTTON, self.on_add_frame, self.btn_add)
        self.Bind(wx.EVT_BUTTON, self.on_delete_frame, self.btn_del)
        self.Bind(wx.EVT_CHOICE, self.on_mode_change, self.choice_mode)
        self.Bind(wx.EVT_CHECKBOX, self.on_toggle_vis_col, self.chk_show_col)
        self.Bind(wx.EVT_CHECKBOX, self.on_toggle_vis_pts, self.chk_show_pts)
        
        self.palette.refresh_modules()
        self.refresh_frames()
        
        # Accelerators
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('Z'), wx.ID_UNDO),
            (wx.ACCEL_CTRL, ord('Y'), wx.ID_REDO),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('Z'), wx.ID_REDO)
        ])
        self.SetAcceleratorTable(accel_tbl)
        
        self.Bind(wx.EVT_MENU, self.on_undo, id=wx.ID_UNDO)
        self.Bind(wx.EVT_MENU, self.on_redo, id=wx.ID_REDO)
        
        # Init color maps
        self.on_col_type_change() 
        self.on_point_type_change()

        # Canvas Interaction Events
        self.canvas.Bind(wx.EVT_RIGHT_DOWN, self.on_canvas_right_down)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        # Sync selection
        self.canvas.on_selection_changed = self.on_canvas_selection_changed
        self.canvas.on_modify_ended = self.snapshot
        self.canvas.on_modify_started = self.snapshot
        
        # Initial Snapshot
        self.snapshot()

    def snapshot(self):
        """Captures the current state of the active frame for Undo."""
        if self.canvas.frame:
            self.undo_manager.push_state(self.canvas.frame.clone())

    def on_undo(self, event):
        state = self.undo_manager.undo()
        if state:
            self._restore_state(state)

    def on_redo(self, event):
        state = self.undo_manager.redo()
        if state:
            self._restore_state(state)

    def _restore_state(self, new_frame: Frame):
        # 1. Update Project Data
        # Find index of frame with same ID
        found = False
        for i, f in enumerate(self.project.frames):
            if f.id == new_frame.id:
                self.project.frames[i] = new_frame
                found = True
                break
        
        if not found:
            print(f"Warning: Frame {new_frame.id} not found in project to restore.")
            return

        # 2. Update Canvas
        self.canvas.set_frame(new_frame)
        self.canvas.Refresh()
        
        # 3. Update Point Manager / Collision Manager
        if hasattr(self.point_manager, 'refresh_list'):
            self.point_manager.refresh_list()
        if hasattr(self.col_manager, 'refresh_list'):
            self.col_manager.refresh_list()
        
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
        # Suppress context menu if in collision or point mode
        if self.canvas.edit_mode in ("collision", "point"):
            return

        # Hit test to see if we clicked a module
        pos = self.canvas.screen_to_world(event.GetPosition())
        hits = self.canvas.hit_test_all(pos)
        
        clicked_fmod = None
        
        # Priority 1: If any currently selected module is under cursor, use it (preserve selection)
        for hit in hits:
            if hit.id in self.canvas.selected_fmodules:
                clicked_fmod = hit
                break
        
        # Priority 2: If no selected module is hit, take the top-most hit (idx 0)
        if not clicked_fmod and hits:
            clicked_fmod = hits[0]
        
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

            rot_cw_item = menu.Append(wx.ID_ANY, "Rotate CW (90°)")
            rot_ccw_item = menu.Append(wx.ID_ANY, "Rotate CCW (90°)")
            self.Bind(wx.EVT_MENU, self.on_rotate_cw, id=rot_cw_item.GetId())
            self.Bind(wx.EVT_MENU, self.on_rotate_ccw, id=rot_ccw_item.GetId())
            
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
         
         self.snapshot()
         
         # Identify targets
         # Pass explicit list if selection exists, else None (to imply All)
         targets = None
         if self.canvas.selected_fmodules:
             targets = [fm for fm in frame.fmodules if fm.id in self.canvas.selected_fmodules]
             
         self._perform_group_flip(frame, param, targets)

    def _perform_group_flip(self, frame, axis, targets=None):
         """
         Robust Group Flip logic handling Rotation Awareness and Visual Center preservation.
         If targets is None, applies to ALL modules in frame AND pivots around Origin (0,0).
         If targets is list, pivots around Selection Center.
         """
         pivot_at_origin = False
         if targets is None:
             targets = frame.fmodules[:]
             pivot_at_origin = True
             
         if not targets: return

         # 1. Calculate Group Bounds/Center
         min_x, min_y = 99999, 99999
         max_x, max_y = -99999, -99999
         
         valid_bounds = False
         
         # Pre-calculate Centers
         vm_centers = {} # Visual Middle Centers
         
         for fm in targets:
             # Use canvas helper to get bounding box (recurses for nested frames)
             b = self.canvas._fmodule_bounds(fm)
             cx = (b[0] + b[2]) / 2.0
             cy = (b[1] + b[3]) / 2.0
             vm_centers[fm.id] = (cx, cy)
             
             min_x = min(min_x, b[0])
             min_y = min(min_y, b[1])
             max_x = max(max_x, b[2])
             max_y = max(max_y, b[3])
             valid_bounds = True
             
         if not valid_bounds: return
         
         if pivot_at_origin:
             group_cx, group_cy = 0.0, 0.0
         else:
             group_cx = (min_x + max_x) / 2.0
             group_cy = (min_y + max_y) / 2.0
         
         changed = False
         
         for fm in targets:
             # --- Step A: Flip In Place (with Center Comp) ---
             
             # 1. Old Center
             old_cx, old_cy = vm_centers[fm.id] 
             
             # 2. Apply Flip (Rotation Aware)
             # Use round() to avoid floating point truncation errors
             raw_rot = fm.rotation_degrees
             raw_rot = fm.rotation_degrees
             rot = int(round(raw_rot)) % 180
             effective_axis = axis
             
             if rot == 90:
                 effective_axis = "y" if axis == "x" else "x"
                 
             if effective_axis == "x":
                 fm.flip_x = not fm.flip_x
             elif effective_axis == "y":
                 fm.flip_y = not fm.flip_y

             try:
                 with open("safe_debug.txt", "a") as f:
                     f.write(f"  EffectiveAxis={effective_axis} FinalFlipX={fm.flip_x} FinalFlipY={fm.flip_y}\n")
             except: pass

             # 3. New Center (Pre-Move)
             new_bounds = self.canvas._fmodule_bounds(fm)
             curr_cx = (new_bounds[0] + new_bounds[2]) / 2.0
             curr_cy = (new_bounds[1] + new_bounds[3]) / 2.0
             
             # 4. Center Compensation (Pin to Old Center)
             dx_comp = old_cx - curr_cx
             dy_comp = old_cy - curr_cy
             
             fm.position = (int(fm.position[0] + dx_comp), int(fm.position[1] + dy_comp))
             
             # --- Step B: Group Mirroring ---
             # Mirror position across Group Center
             
             rel_x = old_cx - group_cx
             rel_y = old_cy - group_cy
             
             target_rel_x = rel_x
             target_rel_y = rel_y
             
             if axis == "x":
                 target_rel_x = -rel_x
             elif axis == "y":
                 target_rel_y = -rel_y
                 
             target_cx = group_cx + target_rel_x
             target_cy = group_cy + target_rel_y
             
             # Delta to move from Current Center (old_cx) to Target Center
             move_dx = target_cx - old_cx
             move_dy = target_cy - old_cy
             
             try:
                 with open("safe_debug.txt", "a") as f:
                     f.write(f"  GroupCX={group_cx} OldCenter=({old_cx},{old_cy}) MoveDX={move_dx}\n")
             except: pass
             
             fm.position = (int(fm.position[0] + move_dx), int(fm.position[1] + move_dy))
             
             changed = True
         
         if changed:
             self.canvas.Refresh()
             self.snapshot()

    def on_rotate_cw(self, event):
        self._rotate_selected(90)

    def on_rotate_ccw(self, event):
        self._rotate_selected(-90)

    def _rotate_selected(self, delta_degrees: float):
         frame = self.canvas.frame
         if not frame: return
         
         self.snapshot()
         
         changed = False
         for fm in frame.fmodules:
             if fm.id in self.canvas.selected_fmodules:
                 fm.rotation_degrees = (fm.rotation_degrees + delta_degrees) % 360.0
                 changed = True
         
         if changed:
             self.canvas.Refresh()
             self.snapshot()

    def _change_z_order(self, direction: str):
        if not self.canvas.frame or not self.canvas.selected_fmodules:
            return
            
        self.snapshot()
        
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
        self.snapshot()
        self.snapshot()

    def _delete_selected_modules(self):
        if not self.canvas.frame or not self.canvas.selected_fmodules:
            return
            
        self.snapshot()
            
        # Ensure we don't modify list while iterating if we were doing that
        # Rebuild list excluding deleted ones
        selected = set(self.canvas.selected_fmodules)
        new_list = [fm for fm in self.canvas.frame.fmodules if fm.id not in selected]
        
        self.canvas.frame.fmodules = new_list
        self.canvas.selected_fmodules = []
        self.canvas.Refresh()
        self.snapshot()

    def _delete_selected_collision_rects(self):
        if not self.canvas.frame or not self.canvas.selected_collision_rects:
            return
            
        self.snapshot()
            
        selected = set(self.canvas.selected_collision_rects)
        new_list = [cr for cr in self.canvas.frame.collision_rects if cr.id not in selected]
        
        self.canvas.frame.collision_rects = new_list
        self.canvas.selected_collision_rects = []
        self.canvas.Refresh()
        self.snapshot()

    def _delete_selected_points(self):
        if not self.canvas.frame or not self.canvas.selected_points:
            return

        self.snapshot()
            
        selected = set(self.canvas.selected_points)
        new_list = [cp for cp in self.canvas.frame.control_points if cp.id not in selected]
        
        self.canvas.frame.control_points = new_list
        self.canvas.selected_points = []
        self.canvas.Refresh()
        self.snapshot()

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
             elif self.canvas.edit_mode == "point":
                 self._delete_selected_points()
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
        # Fingerprint to skip full rebuild if just switching tabs
        current_fingerprint = (len(self.project.frames), tuple((f.id, f.name) for f in self.project.frames))
        if current_fingerprint == getattr(self, "_last_frames_fingerprint", None):
            # Only update selection if needed
            if select_id:
                for i in range(self.frame_list.GetItemCount()):
                    if self.project.frames[i].id == select_id:
                         if not self.frame_list.IsSelected(i):
                            self.frame_list.Select(i)
                            self.frame_list.EnsureVisible(i)
                         break
            return
        self._last_frames_fingerprint = current_fingerprint

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
        self.refresh_frames(new_frame.id)
        
    def _mirror_frame(self, fid: str, axis: str):
        frame = self.project.get_frame(fid)
        if not frame: return
        
        self._perform_group_flip(frame, axis, targets=None)

        # Mirror Collision Rects
        for cr in frame.collision_rects:
            rx, ry, rw, rh = cr.rect
            if axis == "x":
                # x -> -x - w
                cr.rect = (-rx - rw, ry, rw, rh)
            elif axis == "y":
                # y -> -y - h
                cr.rect = (rx, -ry - rh, rw, rh)
                
        # Mirror Control Points
        for cp in frame.control_points:
            if axis == "x":
                cp.x = -cp.x
            elif axis == "y":
                cp.y = -cp.y
                
        self.canvas.Refresh()

    def _flip_frame(self, fid: str, axis: str):
        frame = self.project.get_frame(fid)
        if not frame: return
        
        self._perform_group_flip(frame, axis, targets=None)
        self.canvas.Refresh()
            
    def refresh_choices(self):
        """Called by app.py when switching tools."""
        self.palette.refresh_modules()
        # In new design, frame list is always visible, but good update point
        self.refresh_frames(self.selected_frame_id)

    # --- Copy / Paste / Propagate Logic ---
    def on_frame_list_context_menu(self, event):
        idx = self.frame_list.GetFirstSelected()
        if idx == -1: return
        
        fid = self.project.frames[idx].id
        frame = self.project.get_frame(fid)
        
        menu = wx.Menu()
        
        # Frame Actions
        item_dup = menu.Append(wx.ID_ANY, "Duplicate Frame")
        menu.AppendSeparator()
        item_mirror_x = menu.Append(wx.ID_ANY, "Mirror Horizontal (X)")
        item_mirror_y = menu.Append(wx.ID_ANY, "Mirror Vertical (Y)")
        menu.AppendSeparator()
        
        item_rot_cw = menu.Append(wx.ID_ANY, "Rotate Frame CW (90°)")
        item_rot_ccw = menu.Append(wx.ID_ANY, "Rotate Frame CCW (90°)")
        menu.AppendSeparator()
        
        # Collision
        item_copy_c = menu.Append(wx.ID_ANY, "Copy Collision Rects")
        item_paste_c = menu.Append(wx.ID_ANY, "Paste Collision Rects (Append)")
        item_prop_c = menu.Append(wx.ID_ANY, "Propagate Collision Rects to ALL Frames")
        if not self._clipboard_col: item_paste_c.Enable(False)
        
        menu.AppendSeparator()
        
        # Points
        item_copy_p = menu.Append(wx.ID_ANY, "Copy Control Points")
        item_paste_p = menu.Append(wx.ID_ANY, "Paste Control Points (Append)")
        item_prop_p = menu.Append(wx.ID_ANY, "Propagate Control Points to ALL Frames")
        if not self._clipboard_pts: item_paste_p.Enable(False)

        # Bind
        self.Bind(wx.EVT_MENU, lambda e: self._duplicate_frame(fid), item_dup)
        self.Bind(wx.EVT_MENU, lambda e: self._mirror_frame(fid, "x"), item_mirror_x)
        self.Bind(wx.EVT_MENU, lambda e: self._mirror_frame(fid, "y"), item_mirror_y)
        self.Bind(wx.EVT_MENU, lambda e: self._rotate_frame(90), item_rot_cw)
        self.Bind(wx.EVT_MENU, lambda e: self._rotate_frame(-90), item_rot_ccw)

        self.Bind(wx.EVT_MENU, lambda e: self._copy_collision(frame), item_copy_c)
        self.Bind(wx.EVT_MENU, lambda e: self._paste_collision(), item_paste_c)
        self.Bind(wx.EVT_MENU, lambda e: self._propagate_collision(frame), item_prop_c)
        
        self.Bind(wx.EVT_MENU, lambda e: self._copy_points(frame), item_copy_p)
        self.Bind(wx.EVT_MENU, lambda e: self._paste_points(), item_paste_p)
        self.Bind(wx.EVT_MENU, lambda e: self._propagate_points(frame), item_prop_p)
        
        self.PopupMenu(menu)
        menu.Destroy()
        
    def _clone_rects(self, rects):
        new_list = []
        for cr in rects:
            new_cr = copy.deepcopy(cr)
            new_cr.id = generate_id("crect")
            new_list.append(new_cr)
        return new_list

    def _clone_points(self, points):
        new_list = []
        for cp in points:
            new_cp = copy.deepcopy(cp)
            new_cp.id = generate_id("pt")
            new_list.append(new_cp)
        return new_list

    def _copy_collision(self, frame):
        self._clipboard_col = copy.deepcopy(frame.collision_rects)
        
    def _paste_collision(self):
        # Paste to currently selected frame
        idx = self.frame_list.GetFirstSelected()
        if idx == -1 or not self._clipboard_col: return
        fid = self.project.frames[idx].id
        frame = self.project.get_frame(fid)
        
        clones = self._clone_rects(self._clipboard_col)
        frame.collision_rects.extend(clones)
        self.canvas.Refresh()
        
    def _propagate_collision(self, src_frame):
        # Propagate to ALL frames (Append)
        # Maybe exclude source?
        src_rects = src_frame.collision_rects
        for f in self.project.frames:
            if f.id == src_frame.id: continue
            clones = self._clone_rects(src_rects)
            f.collision_rects.extend(clones)
        self.canvas.Refresh()

    def _copy_points(self, frame):
        self._clipboard_pts = copy.deepcopy(frame.control_points)

    def _paste_points(self):
        idx = self.frame_list.GetFirstSelected()
        if idx == -1 or not self._clipboard_pts: return
        fid = self.project.frames[idx].id
        frame = self.project.get_frame(fid)
        
        clones = self._clone_points(self._clipboard_pts)
        frame.control_points.extend(clones)
        self.canvas.Refresh()

    def _propagate_points(self, src_frame):
        src_pts = src_frame.control_points
        for f in self.project.frames:
            if f.id == src_frame.id: continue
            clones = self._clone_points(src_pts)
            f.control_points.extend(clones)
        self.canvas.Refresh()

    # QoL Implementations
    def on_frame_list_resize(self, event):
        width = self.frame_list.GetClientSize().width
        self.frame_list.SetColumnWidth(0, width)
        event.Skip()

    def on_frame_dclick(self, event):
        idx = event.GetIndex()
        if idx != -1:
            self.frame_list.EditLabel(idx)

    def on_begin_label_edit(self, event):
        event.Allow()

    def on_end_label_edit(self, event):
        if event.IsEditCancelled():
            return
            
        new_name = event.GetLabel()
        idx = event.GetIndex()
        
        if 0 <= idx < len(self.project.frames):
            frame = self.project.frames[idx]
            if new_name and new_name != frame.name:
                frame.name = new_name
                # self.refresh_frames(frame.id) # No need to refresh entire list, label is updated by Ctrl
                
    # Renamed to match binding
    def on_begin_drag_frame(self, event):
        # Drag started: Cancel pending selection switch (if any)
        # This allows dragging a highlighted frame WITHOUT switching the view to it.
        self._pending_frame_switch = None
        
        idx = event.GetIndex()
        if idx != -1:
            # Send both Index (for reordering) and ID (for canvas drop)
            # Format: FRAME_REF:<idx>:<id>
            frame_id = self.project.frames[idx].id
            text_data = wx.TextDataObject(f"FRAME_REF:{idx}:{frame_id}")
            source = wx.DropSource(self.frame_list)
            source.SetData(text_data)
            source.DoDragDrop(wx.Drag_DefaultMove)
            
            # Post-Drag: Restore selection to the currently active canvas frame
            # (Because clicking to drag selected the dragged frame in the list)
            if self.selected_frame_id:
                # Find index of self.selected_frame_id
                active_idx = -1
                for i, f in enumerate(self.project.frames):
                    if f.id == self.selected_frame_id:
                        active_idx = i
                        break
                
                if active_idx != -1:
                    # Restore selection to visual context
                    self.frame_list.SetItemState(active_idx, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
                    # We might want to ensure visible too
                    self.frame_list.EnsureVisible(active_idx)
            
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
        self.canvas.clear_cache()
        
        # Completely recreate ModulePalette to force-clear wx.ListCtrl/ImageList internal caches
        # This is required because on some platforms (macOS), the ImageList layer is extremely sticky.
        old_palette = self.palette
        parent = old_palette.GetParent()
        sizer = parent.GetSizer()
        
        # Find position
        sizer_items = sizer.GetChildren()
        insert_idx = 0
        for i, item in enumerate(sizer_items):
             if item.GetWindow() == old_palette:
                 insert_idx = i
                 break
        
        sizer.Detach(old_palette)
        old_palette.Destroy()
        
        # Create new
        self.palette = ModulePalette(parent, project)
        sizer.Insert(insert_idx, self.palette, 1, wx.EXPAND | wx.ALL, 5)
        parent.Layout()
        
        # Update Managers
        self.col_manager.project = project 
        self.col_manager.refresh_list()
        self.point_manager.project = project 
        self.point_manager.refresh_list()
        
        self.palette.refresh_modules()
        
        self.selected_frame_id = None # Clear previous selection
        self.refresh_frames()
        self.canvas.set_frame(None)
        self.canvas.clear_cache() # Fix: FrameCanvas has its own bitmap cache that must be cleared!
        
        # Ensure canvas has correct collision/point colors immediately
        self.on_col_type_change()
        self.on_point_type_change()

    def on_select_frame(self, event):
        idx = event.GetIndex() if event else self.frame_list.GetFirstSelected()
        if idx != -1:
            # Assume list order == project order
            if 0 <= idx < len(self.project.frames):
                frame = self.project.frames[idx]
                self._switch_canvas_view(frame)
        else:
            self.canvas.set_frame(None)
            
    # on_frame_list_mouseup removed
            
    def _switch_canvas_view(self, frame):
        self.selected_frame_id = frame.id
        self.canvas.set_frame(frame)
    
    def on_mode_change(self, event):
        sel = self.choice_mode.GetSelection()
        
        if sel == 0: # Modules
            self.canvas.edit_mode = "module"
            self.lbl_modules.Show()
            self.palette.Show()
            self.col_manager.Hide()
            self.point_manager.Hide()
            
            # Clear other selections
            self.canvas.selected_collision_rects = []
            self.canvas.selected_points = []
            
        elif sel == 1: # Collision
            self.canvas.edit_mode = "collision"
            self.lbl_modules.Hide()
            self.palette.Hide()
            self.col_manager.Show()
            self.point_manager.Hide()
            
            # Clear other selections
            self.canvas.selected_fmodules = []
            self.canvas.selected_points = []
            
            if self.col_manager.active_type_id:
                self.canvas.active_collision_type_id = self.col_manager.active_type_id
        elif sel == 2: # Points
            self.canvas.edit_mode = "point"
            self.lbl_modules.Hide()
            self.palette.Hide()
            self.col_manager.Hide()
            self.point_manager.Show()
            
            # Clear other selections
            self.canvas.selected_fmodules = []
            self.canvas.selected_collision_rects = []
            
            if self.point_manager.active_type_id:
                self.canvas.active_point_type_id = self.point_manager.active_type_id
                
        self.left_panel_layout()
        self.canvas.Refresh()

    def on_toggle_vis_col(self, event):
        self.canvas.show_collision = event.IsChecked()
        self.canvas.Refresh()

    def on_toggle_vis_pts(self, event):
        self.canvas.show_points = event.IsChecked()
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

    def on_point_type_change(self):
        self.canvas.active_point_type_id = self.point_manager.active_type_id
        visible_map = {}
        for pt in self.project.point_types:
             if self.point_manager.visibility.get(pt.id, True):
                 visible_map[pt.id] = pt.color
        self.canvas.point_type_colors = visible_map
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
    def _rotate_frame(self, degrees: float):
        frame = self.project.get_frame(self.selected_frame_id)
        if not frame: return
        
        # We rotate 90 degrees intervals
        rot_steps = int(degrees / 90) % 4
        if rot_steps == 0: return

        # Rotate Modules
        for fm in frame.fmodules:
            # Update rotation
            fm.rotation_degrees = (fm.rotation_degrees + degrees) % 360.0
            
            # Update Position (Rotate around 0,0)
            x, y = fm.position
            
            if degrees == 90 or degrees == -270: # CW
                # (x, y) -> (-y, x)
                fm.position = (-y, x)
            elif degrees == -90 or degrees == 270: # CCW
                # (x, y) -> (y, -x)
                fm.position = (y, -x)
            elif degrees == 180 or degrees == -180:
                # (x, y) -> (-x, -y)
                fm.position = (-x, -y)
                
        # Rotate Collision Rects
        # Rect (x, y, w, h). 
        # CW 90: new_x = -y - h, new_y = x, new_w = h, new_h = w
        # CCW 90: new_x = y, new_y = -x - w, new_w = h, new_h = w
        for cr in frame.collision_rects:
            rx, ry, rw, rh = cr.rect
            if degrees == 90 or degrees == -270: # CW
                cr.rect = (-ry - rh, rx, rh, rw)
            elif degrees == -90 or degrees == 270: # CCW
                cr.rect = (ry, -rx - rw, rh, rw)
            elif degrees == 180 or degrees == -180:
                cr.rect = (-rx - rw, -ry - rh, rw, rh)

        # Rotate Control Points
        for cp in frame.control_points:
             x, y = cp.x, cp.y
             if degrees == 90 or degrees == -270: # CW
                 cp.x, cp.y = -y, x
             elif degrees == -90 or degrees == 270: # CCW
                 cp.x, cp.y = y, -x
             elif degrees == 180 or degrees == -180:
                 cp.x, cp.y = -x, -y

        self.canvas.Refresh()
