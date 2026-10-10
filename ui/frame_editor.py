"""Frame editor panel for assembling modules with visual palette."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, List, Tuple
import copy
import wx

from models import CollisionRect, ControlPoint, FModule, Project, Frame, generate_id
from optimization import optimize_nested_frame_combos
from ui import app_services
from ui.canvas import FrameCanvas, GHOST_NEXT, GHOST_PREVIOUS
from ui.components.canvas_display_controls import CanvasDisplayControls
from ui.collision_manager import CollisionManagerPanel
from ui.point_manager import PointManagerPanel
from ui.utils import render_pixel_shape_to_bitmap, load_wx_image_safely

# Part/collision/point clipboard shared by all frames (kind is the edit mode it came from).
_FRAME_CLIPBOARD: Dict[str, Any] = {"kind": None, "items": []}

NUDGE_SMALL = 1
NUDGE_LARGE = 8  # one 8x8 hardware tile

class ModulePalette(wx.ListCtrl):
    """Visual list of modules draggable onto the canvas."""
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, style=wx.LC_ICON | wx.LC_SINGLE_SEL | wx.LC_AUTOARRANGE)
        self.project = project
        # Thumbnails are opaque; a masked list makes macOS build a mask per Add (~6 ms each).
        self.image_list = wx.ImageList(96, 96, mask=False)
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
        self.filter_text = ""

    def set_filter(self, text: str) -> None:
        self.filter_text = (text or "").strip().lower()
        self.refresh_modules()

    def _visible_modules(self):
        if not self.filter_text:
            return list(self.project.modules)
        return [m for m in self.project.modules if self.filter_text in m.name.lower()]

    def refresh_modules(self):
        # 1. Check if actually needed (skip if data hasn't changed)
        # Fingerprint covers: count, identities, visual properties (rect, name) and the filter
        current_fingerprint = (
            self.filter_text,
            len(self.project.modules),
            tuple((m.id, m.name, m.rect, m.type, tuple(m.color), tuple(m.params)) for m in self.project.modules),
        )
        if current_fingerprint == self._last_fingerprint:
            return
        self._last_fingerprint = current_fingerprint

        # Aggressive cleanup of ListCtrl state, but NOT our persistent caches
        self.SetImageList(None, wx.IMAGE_LIST_NORMAL)
        self.DeleteAllItems()
        
        item_side = 96
        self.image_list = wx.ImageList(item_side, item_side, mask=False)
        self.SetImageList(self.image_list, wx.IMAGE_LIST_NORMAL)
        self.item_images.clear()
        
        visible_modules = self._visible_modules()
        if not visible_modules:
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

        for mod in visible_modules:
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
                            img = load_wx_image_safely(asset.file_path)
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
                
        self.module_ids = [m.id for m in visible_modules]


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
            
        if self.editor.frame_filter_active():
            app_services.show_status("Clear the frame filter to reorder frames.")
            return False

        # Find target index using helper
        target_idx, _ = self._get_insertion_point(x, y)
        if target_idx == wx.NOT_FOUND:
            target_idx = self.editor.frame_list.GetItemCount()
            
        self.editor.move_frame(src_idx, target_idx)
        return True

class FrameEditorPanel(wx.Panel):
    MODE_KEYS = ("module", "collision", "point")
    MODE_LABELS = ("Parts", "Collision", "Points")
    MODE_HINTS = {
        "module": "Drag modules from the palette  •  Click/Shift+click: select  •  Arrows: nudge (Shift = 8 px)  •  H/V: flip  •  R: rotate",
        "collision": "Drag on empty space: new box  •  Drag box: move  •  Drag corner: resize  •  Right-click: role / delete",
        "point": "Shift+click: new point  •  Drag: move  •  Arrows: nudge  •  Right-click: role / delete",
    }
    ONION_CHOICES = ("Off", "Previous", "Next", "Both")

    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent)
        self.project = project
        self.selected_frame_id: Optional[str] = None
        self._frame_view: List[Frame] = []
        self._last_frames_fingerprint = None
        self.onion_mode = "off"

        # Clipboard for the frame-list "Copy Collision Rects / Control Points" actions
        self._clipboard_col: List = [] 
        self._clipboard_pts: List = []
        
        # Layout: Splitter
        self.splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # Left Panel: Frames List + Module Palette / Type managers
        left_panel = wx.Panel(self.splitter)
        self.left_panel = left_panel
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        self.frames_box = wx.StaticBox(left_panel, label="Frames")
        frames_sizer = wx.StaticBoxSizer(self.frames_box, wx.VERTICAL)
        self.frame_filter = wx.SearchCtrl(self.frames_box, style=wx.TE_PROCESS_ENTER)
        self.frame_filter.SetDescriptiveText("Filter frames")
        self.frame_filter.ShowCancelButton(True)
        frames_sizer.Add(self.frame_filter, 0, wx.EXPAND | wx.ALL, 4)

        # Frames List (ListCtrl for better DnD and Inline Rename)
        self.frame_list = wx.ListCtrl(
            self.frames_box, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.LC_EDIT_LABELS
        )
        self.frame_list.InsertColumn(0, "Frame", width=180)
        self.frame_list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_frame_list_context_menu)
        self.frame_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_frame_dclick)
        # Enable Drag FROM list (to reorder OR drop on canvas)
        self.frame_list.Bind(wx.EVT_LIST_BEGIN_DRAG, self.on_begin_drag_frame)
        self.frame_list.Bind(wx.EVT_LIST_BEGIN_LABEL_EDIT, self.on_begin_label_edit)
        self.frame_list.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.on_end_label_edit)
        self.frame_list.SetDropTarget(FrameListDropTarget(self))
        self.frame_list.Bind(wx.EVT_SIZE, self.on_frame_list_resize)
        frames_sizer.Add(self.frame_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        frame_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(self.frames_box, label="Add")
        self.btn_dup = wx.Button(self.frames_box, label="Duplicate")
        self.btn_del = wx.Button(self.frames_box, label="Delete")
        self.btn_add.SetToolTip("Add an empty frame")
        self.btn_dup.SetToolTip("Duplicate the selected frame")
        self.btn_del.SetToolTip("Delete the selected frame (Delete key in the list)")
        frame_btns.Add(self.btn_add, 1, wx.RIGHT, 4)
        frame_btns.Add(self.btn_dup, 1, wx.RIGHT, 4)
        frame_btns.Add(self.btn_del, 1)
        frames_sizer.Add(frame_btns, 0, wx.EXPAND | wx.ALL, 4)
        left_sizer.Add(frames_sizer, 1, wx.EXPAND | wx.ALL, 4)

        # Mode-dependent side box: module palette, collision types or point types
        self.side_box = wx.StaticBox(left_panel, label="Module Palette")
        self._side_sizer = wx.StaticBoxSizer(self.side_box, wx.VERTICAL)
        self.palette_filter = wx.SearchCtrl(self.side_box, style=wx.TE_PROCESS_ENTER)
        self.palette_filter.SetDescriptiveText("Filter modules")
        self.palette_filter.ShowCancelButton(True)
        self._side_sizer.Add(self.palette_filter, 0, wx.EXPAND | wx.ALL, 4)
        self.palette = ModulePalette(self.side_box, project)
        self.palette.SetToolTip("Drag a module onto the canvas")
        self._side_sizer.Add(self.palette, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self.col_manager = CollisionManagerPanel(self.side_box, project, on_change=self.on_col_type_change)
        self._side_sizer.Add(self.col_manager, 1, wx.EXPAND | wx.ALL, 4)
        self.point_manager = PointManagerPanel(self.side_box, project, on_change=self.on_point_type_change)
        self._side_sizer.Add(self.point_manager, 1, wx.EXPAND | wx.ALL, 4)
        self._side_sizer.Hide(self.col_manager)
        self._side_sizer.Hide(self.point_manager)
        left_sizer.Add(self._side_sizer, 1, wx.EXPAND | wx.ALL, 4)

        left_panel.SetSizer(left_sizer)
        
        # Right Panel: mode bar, canvas, view bar
        right_panel = wx.Panel(self.splitter)
        canvas_sizer = wx.BoxSizer(wx.VERTICAL)

        mode_bar = wx.BoxSizer(wx.HORIZONTAL)
        mode_bar.Add(wx.StaticText(right_panel, label="Edit"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.mode_buttons: List[wx.RadioButton] = []
        for idx, label in enumerate(self.MODE_LABELS):
            btn = wx.RadioButton(right_panel, label=label, style=wx.RB_GROUP if idx == 0 else 0)
            btn.Bind(wx.EVT_RADIOBUTTON, lambda e, i=idx: self.set_edit_mode(self.MODE_KEYS[i]))
            mode_bar.Add(btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
            self.mode_buttons.append(btn)
        self.mode_buttons[0].SetValue(True)
        canvas_sizer.Add(mode_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        
        self.canvas = FrameCanvas(right_panel, project)
        self.canvas.on_create_frame_needed = self.on_auto_create_frame
        canvas_sizer.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 4)

        self.canvas_controls = CanvasDisplayControls(right_panel, self.canvas, view_key="frames", part_bounds=True, budget=True)
        self.canvas_controls.add_separator()
        self.chk_show_col = self.canvas_controls.add_toggle(
            "Collision", False, self.on_toggle_vis_col, "Show collision boxes while editing parts"
        )
        self.chk_show_pts = self.canvas_controls.add_toggle(
            "Points", True, self.on_toggle_vis_pts, "Show control points while editing parts"
        )
        self.onion_choice = wx.Choice(self.canvas_controls, choices=list(self.ONION_CHOICES))
        self.onion_choice.SetSelection(0)
        self.onion_choice.SetMinSize((110, -1))
        self.onion_choice.SetToolTip("Ghost the neighbouring frames of the frame list")
        self.canvas_controls.add_control(self.onion_choice, "Onion")
        canvas_sizer.Add(self.canvas_controls, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        right_panel.SetSizer(canvas_sizer)
        
        # Split
        self.splitter.SplitVertically(left_panel, right_panel, 340)
        self.splitter.SetMinimumPaneSize(200)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(main_sizer)
        
        # Bindings
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_frame, self.frame_list)
        self.Bind(wx.EVT_BUTTON, self.on_add_frame, self.btn_add)
        self.Bind(wx.EVT_BUTTON, lambda e: self.duplicate_selected_frame(), self.btn_dup)
        self.Bind(wx.EVT_BUTTON, self.on_delete_frame, self.btn_del)
        self.frame_filter.Bind(wx.EVT_TEXT, lambda e: self.refresh_frames(self.selected_frame_id))
        self.frame_filter.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.frame_filter.SetValue(""))
        self.palette_filter.Bind(wx.EVT_TEXT, lambda e: self.palette.set_filter(self.palette_filter.GetValue()))
        self.palette_filter.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda e: self.palette_filter.SetValue(""))
        self.onion_choice.Bind(wx.EVT_CHOICE, self.on_onion_changed)
        
        self.palette.refresh_modules()
        self.refresh_frames()
        
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

    def snapshot(self):
        """Mark an undo step (project-wide history lives in the main window)."""
        app_services.request_checkpoint()

    # --- Panel interface used by the main window ---
    def get_active_canvas(self):
        return self.canvas

    def on_active_mapping_changed(self) -> None:
        self.canvas.Refresh(False)

    def refresh_after_history(self) -> None:
        frame = self.project.get_frame(self.selected_frame_id or "")
        if not frame:
            self.selected_frame_id = None
        self._last_frames_fingerprint = None
        self.palette.refresh_modules()
        self.col_manager.set_project(self.project)
        self.point_manager.set_project(self.project)
        self.refresh_frames(self.selected_frame_id)
        self.canvas.set_frame(frame)
        if frame:
            fm_ids = {fm.id for fm in frame.fmodules}
            cr_ids = {cr.id for cr in frame.collision_rects}
            cp_ids = {cp.id for cp in frame.control_points}
            self.canvas.selected_fmodules = [i for i in self.canvas.selected_fmodules if i in fm_ids]
            self.canvas.selected_collision_rects = [i for i in self.canvas.selected_collision_rects if i in cr_ids]
            self.canvas.selected_points = [i for i in self.canvas.selected_points if i in cp_ids]
        self.on_col_type_change()
        self.on_point_type_change()
        self._update_ghosts()

    def frame_filter_active(self) -> bool:
        return bool(self.frame_filter.GetValue().strip())

    def select_frame_by_id(self, frame_id: str) -> None:
        frame = self.project.get_frame(frame_id)
        if not frame:
            return
        if self.frame_filter_active() and frame not in self._frame_view:
            self.frame_filter.ChangeValue("")
            self._last_frames_fingerprint = None
        self.refresh_frames(select_id=frame_id)
        self._switch_canvas_view(frame)

    # --- Edit mode ---
    def set_edit_mode(self, mode: str) -> None:
        if mode not in self.MODE_KEYS:
            return
        idx = self.MODE_KEYS.index(mode)
        if not self.mode_buttons[idx].GetValue():
            self.mode_buttons[idx].SetValue(True)
        self.canvas.edit_mode = mode
        show_palette = mode == "module"
        self._side_sizer.Show(self.palette_filter, show_palette)
        self._side_sizer.Show(self.palette, show_palette)
        self._side_sizer.Show(self.col_manager, mode == "collision")
        self._side_sizer.Show(self.point_manager, mode == "point")
        self.side_box.SetLabel({"module": "Module Palette", "collision": "Collision Types", "point": "Point Types"}[mode])
        if mode != "module":
            self.canvas.selected_fmodules = []
        if mode != "collision":
            self.canvas.selected_collision_rects = []
        if mode != "point":
            self.canvas.selected_points = []
        if mode == "collision" and self.col_manager.active_type_id:
            self.canvas.active_collision_type_id = self.col_manager.active_type_id
        if mode == "point" and self.point_manager.active_type_id:
            self.canvas.active_point_type_id = self.point_manager.active_type_id
        self.left_panel.Layout()
        self.canvas.Refresh()
        app_services.show_status(self.MODE_HINTS[mode])

    # --- Onion skin (neighbours in the frame list) ---
    def on_onion_changed(self, _event: wx.CommandEvent) -> None:
        self.onion_mode = self.ONION_CHOICES[self.onion_choice.GetSelection()].lower()
        self._update_ghosts()

    def _update_ghosts(self) -> None:
        layers: List[Dict[str, Any]] = []
        frame = self.canvas.frame
        if frame and self.onion_mode != "off" and frame in self._frame_view:
            idx = self._frame_view.index(frame)
            if self.onion_mode in ("previous", "both") and idx > 0:
                layers.append({"frame": self._frame_view[idx - 1], "style": GHOST_PREVIOUS})
            if self.onion_mode in ("next", "both") and idx + 1 < len(self._frame_view):
                layers.append({"frame": self._frame_view[idx + 1], "style": GHOST_NEXT})
        self.canvas.ghost_layers = layers
        self.canvas.Refresh(False)

    # --- Selection helpers for edit commands ---
    def _selected_items(self) -> Tuple[str, list]:
        frame = self.canvas.frame
        mode = self.canvas.edit_mode
        if not frame:
            return mode, []
        if mode == "collision":
            ids = set(self.canvas.selected_collision_rects)
            return mode, [cr for cr in frame.collision_rects if cr.id in ids]
        if mode == "point":
            ids = set(self.canvas.selected_points)
            return mode, [cp for cp in frame.control_points if cp.id in ids]
        ids = set(self.canvas.selected_fmodules)
        return mode, [fm for fm in frame.fmodules if fm.id in ids]

    def _select_items(self, mode: str, ids: List[str]) -> None:
        if mode == "collision":
            self.canvas.selected_collision_rects = list(ids)
        elif mode == "point":
            self.canvas.selected_points = list(ids)
        else:
            self.canvas.selected_fmodules = list(ids)
            if self.canvas.on_selection_changed:
                self.canvas.on_selection_changed(self.canvas.selected_fmodules)
        self.canvas.Refresh(False)

    def _focus_in_lists(self) -> bool:
        focus = wx.Window.FindFocus()
        return focus in (self.frame_list, self.palette) or app_services.text_entry_has_focus()

    # --- Edit commands (Edit menu) ---
    def edit_copy(self) -> None:
        mode, items = self._selected_items()
        if not items:
            app_services.show_status("Nothing selected to copy")
            return
        _FRAME_CLIPBOARD["kind"] = mode
        _FRAME_CLIPBOARD["items"] = [item.to_dict() for item in items]
        app_services.show_status(f"Copied {len(items)} item(s)")

    def edit_cut(self) -> None:
        mode, items = self._selected_items()
        if not items:
            return
        self.edit_copy()
        self._delete_selection()

    def edit_paste(self) -> None:
        kind = _FRAME_CLIPBOARD.get("kind")
        items = _FRAME_CLIPBOARD.get("items") or []
        if not kind or not items:
            app_services.show_status("Clipboard is empty")
            return
        frame = self.canvas.frame or self.on_auto_create_frame()
        if not frame:
            return
        if kind != self.canvas.edit_mode:
            self.set_edit_mode(kind)
        new_ids = self._insert_items(frame, kind, items)
        self._select_items(kind, new_ids)
        app_services.show_status(f"Pasted {len(new_ids)} item(s)")

    def edit_duplicate(self) -> None:
        mode, items = self._selected_items()
        if not items or wx.Window.FindFocus() is self.frame_list:
            self.duplicate_selected_frame()
            return
        frame = self.canvas.frame
        new_ids = self._insert_items(frame, mode, [item.to_dict() for item in items])
        self._select_items(mode, new_ids)
        app_services.show_status(f"Duplicated {len(new_ids)} item(s) in place; use the arrow keys to move them")

    def edit_select_all(self) -> None:
        frame = self.canvas.frame
        if not frame:
            return
        mode = self.canvas.edit_mode
        if mode == "collision":
            ids = [cr.id for cr in frame.collision_rects]
        elif mode == "point":
            ids = [cp.id for cp in frame.control_points]
        else:
            ids = [fm.id for fm in frame.fmodules]
        self._select_items(mode, ids)

    def _insert_items(self, frame: Frame, kind: str, item_dicts: List[dict]) -> List[str]:
        new_ids: List[str] = []
        for data in item_dicts:
            data = dict(data)
            if kind == "collision":
                data["id"] = generate_id("crect")
                frame.collision_rects.append(CollisionRect.from_dict(data))
            elif kind == "point":
                data["id"] = generate_id("pt")
                frame.control_points.append(ControlPoint.from_dict(data))
            else:
                if data.get("ref_type") == "frame" and (
                    data.get("ref_id") == frame.id or self.project.frame_has_cycle(frame.id, data.get("ref_id"))
                ):
                    continue
                data["id"] = generate_id("fmod")
                frame.fmodules.append(FModule.from_dict(data))
            new_ids.append(data["id"])
        return new_ids

    def _delete_selection(self) -> None:
        mode = self.canvas.edit_mode
        if mode == "collision":
            self._delete_selected_collision_rects()
        elif mode == "point":
            self._delete_selected_points()
        else:
            self._delete_selected_modules()

    def _nudge_selection(self, dx: int, dy: int) -> None:
        mode, items = self._selected_items()
        if not items:
            return
        for item in items:
            if mode == "collision":
                x, y, w, h = item.rect
                item.rect = (x + dx, y + dy, w, h)
            elif mode == "point":
                item.x += dx
                item.y += dy
            else:
                x, y = item.position
                item.position = (x + dx, y + dy)
        self.canvas.Refresh(False)

    def on_canvas_selection_changed(self, selected_ids: List[str]):
        if not selected_ids:
            return
            
        # Sync the palette to the first selected part
        frame = self.canvas.frame
        if not frame:
            return
        fid = selected_ids[0]
        fm = next((f for f in frame.fmodules if f.id == fid), None)
        if fm and fm.ref_type == "module":
            self.palette.select_module(fm.ref_id)

    def _prompt_role_value(self, title: str, current_value: str) -> Optional[str]:
        dlg = wx.TextEntryDialog(
            self,
            "Enter a stable semantic role name (example: left_foot, torso_main).",
            title,
            value=str(current_value or ""),
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            return str(dlg.GetValue() or "").strip()
        finally:
            dlg.Destroy()

    def _set_selected_collision_role(self) -> None:
        frame = self.canvas.frame
        if not frame or len(self.canvas.selected_collision_rects) != 1:
            return
        target_id = self.canvas.selected_collision_rects[0]
        cr = next((r for r in frame.collision_rects if r.id == target_id), None)
        if not cr:
            return
        current = str(getattr(cr, "role", "") or "")
        new_role = self._prompt_role_value("Collision Role", current)
        if new_role is None or new_role == current:
            return
        self.snapshot()
        cr.role = new_role
        self.canvas.Refresh()
        self.snapshot()

    def _clear_selected_collision_roles(self) -> None:
        frame = self.canvas.frame
        if not frame or not self.canvas.selected_collision_rects:
            return
        selected = set(self.canvas.selected_collision_rects)
        to_clear = [cr for cr in frame.collision_rects if cr.id in selected and str(getattr(cr, "role", "") or "")]
        if not to_clear:
            return
        self.snapshot()
        changed = False
        for cr in to_clear:
            cr.role = ""
            changed = True
        if not changed:
            return
        self.canvas.Refresh()
        self.snapshot()

    def _set_selected_point_role(self) -> None:
        frame = self.canvas.frame
        if not frame or len(self.canvas.selected_points) != 1:
            return
        target_id = self.canvas.selected_points[0]
        cp = next((p for p in frame.control_points if p.id == target_id), None)
        if not cp:
            return
        current = str(getattr(cp, "role", "") or "")
        new_role = self._prompt_role_value("Control Point Role", current)
        if new_role is None or new_role == current:
            return
        self.snapshot()
        cp.role = new_role
        self.canvas.Refresh()
        self.snapshot()

    def _clear_selected_point_roles(self) -> None:
        frame = self.canvas.frame
        if not frame or not self.canvas.selected_points:
            return
        selected = set(self.canvas.selected_points)
        to_clear = [cp for cp in frame.control_points if cp.id in selected and str(getattr(cp, "role", "") or "")]
        if not to_clear:
            return
        self.snapshot()
        changed = False
        for cp in to_clear:
            cp.role = ""
            changed = True
        if not changed:
            return
        self.canvas.Refresh()
        self.snapshot()

    def _show_collision_context_menu(self, event: wx.MouseEvent) -> None:
        frame = self.canvas.frame
        if not frame:
            return
        pos_world = self.canvas.screen_to_world(event.GetPosition())
        hit = self.canvas.hit_test_collision_rect(pos_world)
        if hit:
            if hit.id not in self.canvas.selected_collision_rects:
                self.canvas.selected_collision_rects = [hit.id]
        elif not event.ShiftDown():
            self.canvas.selected_collision_rects = []
        self.canvas.Refresh()

        selected_ids = set(self.canvas.selected_collision_rects)
        selected = [cr for cr in frame.collision_rects if cr.id in selected_ids]
        if not selected:
            return

        menu = wx.Menu()
        item_set_role = menu.Append(wx.ID_ANY, "Set Role...")
        item_clear_role = menu.Append(wx.ID_ANY, "Clear Role")
        menu.AppendSeparator()
        item_delete = menu.Append(wx.ID_ANY, "Delete (Del/Backspace)")

        if len(selected) != 1:
            item_set_role.Enable(False)
        if not any(str(getattr(cr, "role", "") or "").strip() for cr in selected):
            item_clear_role.Enable(False)

        self.Bind(wx.EVT_MENU, lambda e: self._set_selected_collision_role(), id=item_set_role.GetId())
        self.Bind(wx.EVT_MENU, lambda e: self._clear_selected_collision_roles(), id=item_clear_role.GetId())
        self.Bind(wx.EVT_MENU, lambda e: self._delete_selected_collision_rects(), id=item_delete.GetId())
        self.PopupMenu(menu)
        menu.Destroy()

    def _show_point_context_menu(self, event: wx.MouseEvent) -> None:
        frame = self.canvas.frame
        if not frame:
            return
        pos_world = self.canvas.screen_to_world(event.GetPosition())
        hit = self.canvas.hit_test_control_point(pos_world)
        if hit:
            if hit.id not in self.canvas.selected_points:
                self.canvas.selected_points = [hit.id]
        elif not event.ShiftDown():
            self.canvas.selected_points = []
        self.canvas.Refresh()

        selected_ids = set(self.canvas.selected_points)
        selected = [cp for cp in frame.control_points if cp.id in selected_ids]
        if not selected:
            return

        menu = wx.Menu()
        item_set_role = menu.Append(wx.ID_ANY, "Set Role...")
        item_clear_role = menu.Append(wx.ID_ANY, "Clear Role")
        menu.AppendSeparator()
        item_delete = menu.Append(wx.ID_ANY, "Delete (Del/Backspace)")

        if len(selected) != 1:
            item_set_role.Enable(False)
        if not any(str(getattr(cp, "role", "") or "").strip() for cp in selected):
            item_clear_role.Enable(False)

        self.Bind(wx.EVT_MENU, lambda e: self._set_selected_point_role(), id=item_set_role.GetId())
        self.Bind(wx.EVT_MENU, lambda e: self._clear_selected_point_roles(), id=item_clear_role.GetId())
        self.Bind(wx.EVT_MENU, lambda e: self._delete_selected_points(), id=item_delete.GetId())
        self.PopupMenu(menu)
        menu.Destroy()

    def validate_roles(self) -> None:
        issues = self.project.validate_role_uniqueness()
        if not issues:
            wx.MessageBox(
                "No duplicate role keys found.\nEach frame has unique (type, role) pairs.",
                "Role Validation",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        lines = [
            f"{len(issues)} duplicate role key(s) found:",
            "",
        ]
        preview_limit = 20
        for i, issue in enumerate(issues[:preview_limit], start=1):
            lines.append(
                f"{i}. [{issue.get('kind')}] frame='{issue.get('frame_name')}' "
                f"type='{issue.get('type_id')}' role='{issue.get('role')}' "
                f"count={len(issue.get('item_ids', []))}"
            )
        if len(issues) > preview_limit:
            lines.append(f"... and {len(issues) - preview_limit} more.")
        lines.append("")
        lines.append("Tip: keep each (type, role) unique per frame for O(1) runtime lookup tables.")

        wx.MessageBox("\n".join(lines), "Role Validation", wx.OK | wx.ICON_WARNING)

    def _show_readonly_text_dialog(self, title: str, text: str) -> None:
        dlg = wx.Dialog(self, title=title, size=(920, 640))
        try:
            sizer = wx.BoxSizer(wx.VERTICAL)
            txt = wx.TextCtrl(
                dlg,
                value=text,
                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
            )
            txt.SetFont(wx.Font(wx.FontInfo(9).Family(wx.FONTFAMILY_TELETYPE)))
            sizer.Add(txt, 1, wx.EXPAND | wx.ALL, 8)
            btns = dlg.CreateSeparatedButtonSizer(wx.OK)
            if btns:
                sizer.Add(btns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
            dlg.SetSizer(sizer)
            dlg.Layout()
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def inspect_compiled_role_tables(self) -> None:
        if not self.project.animations:
            wx.MessageBox("No animations available.", "Role Table Inspection", wx.OK | wx.ICON_INFORMATION)
            return

        selected_anim = None
        if len(self.project.animations) == 1:
            selected_anim = self.project.animations[0]
        else:
            choices = [
                f"{anim.name} [{anim.id}] ({len(anim.aframes)} frames)"
                for anim in self.project.animations
            ]
            dlg = wx.SingleChoiceDialog(
                self,
                "Choose an animation to compile role tables for inspection.",
                "Inspect Role Tables",
                choices,
            )
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                idx = dlg.GetSelection()
            finally:
                dlg.Destroy()
            if idx < 0 or idx >= len(self.project.animations):
                return
            selected_anim = self.project.animations[idx]

        tables = self.project.compile_animation_role_tables(selected_anim.id)
        if tables is None:
            wx.MessageBox("Failed to compile role tables for selected animation.", "Role Table Inspection", wx.OK | wx.ICON_WARNING)
            return

        payload = {
            "animation_name": selected_anim.name,
            "animation_id": selected_anim.id,
            "tables": tables,
        }
        self._show_readonly_text_dialog(
            f"Role Tables: {selected_anim.name}",
            json.dumps(payload, indent=2),
        )

    def on_canvas_right_down(self, event: wx.MouseEvent):
        if self.canvas.edit_mode == "collision":
            self._show_collision_context_menu(event)
            return
        if self.canvas.edit_mode == "point":
            self._show_point_context_menu(event)
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
            flip_x_item = menu.Append(wx.ID_ANY, "Flip Horizontal (H)")
            flip_y_item = menu.Append(wx.ID_ANY, "Flip Vertical (V)")
            menu.AppendSeparator()
            
            # Use ID for binding, binding to item object is flaky depending on wx version/context
            self.Bind(wx.EVT_MENU, self.on_flip_x, id=flip_x_item.GetId())
            self.Bind(wx.EVT_MENU, self.on_flip_y, id=flip_y_item.GetId())

            rot_cw_item = menu.Append(wx.ID_ANY, "Rotate CW 90° (R)")
            rot_ccw_item = menu.Append(wx.ID_ANY, "Rotate CCW 90° (Shift+R)")
            self.Bind(wx.EVT_MENU, self.on_rotate_cw, id=rot_cw_item.GetId())
            self.Bind(wx.EVT_MENU, self.on_rotate_ccw, id=rot_ccw_item.GetId())
            
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
             rot = int(round(raw_rot)) % 180
             effective_axis = axis
             
             if rot == 90:
                 effective_axis = "y" if axis == "x" else "x"
                 
             if effective_axis == "x":
                 fm.flip_x = not fm.flip_x
             elif effective_axis == "y":
                 fm.flip_y = not fm.flip_y

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
        # CHAR_HOOK sees every key in this tab before the focused control does.
        keycode = event.GetKeyCode()

        if not self.IsShownOnScreen():
            event.Skip()
            return

        # Text fields (rename, filters, spin controls) keep their own keys.
        focus = wx.Window.FindFocus()
        if app_services.text_entry_has_focus():
            event.Skip()
            return

        # The frame list: Delete removes the frame, arrows navigate the list.
        if focus is self.frame_list:
            if keycode in (wx.WXK_DELETE, wx.WXK_BACK) and not event.HasAnyModifiers():
                self.on_delete_frame(None)
                return
            event.Skip()
            return
        if focus is self.palette:
            event.Skip()
            return

        cmd = event.CmdDown() or event.ControlDown()
        if cmd and keycode in (wx.WXK_UP, wx.WXK_DOWN):
            if keycode == wx.WXK_UP:
                self._change_z_order("top" if event.ShiftDown() else "up")
            else:
                self._change_z_order("bottom" if event.ShiftDown() else "down")
            return
        if cmd or event.AltDown():
            event.Skip()  # menu accelerators (copy/paste/undo...)
            return

        if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN):
            step = NUDGE_LARGE if event.ShiftDown() else NUDGE_SMALL
            dx = {wx.WXK_LEFT: -step, wx.WXK_RIGHT: step}.get(keycode, 0)
            dy = {wx.WXK_UP: -step, wx.WXK_DOWN: step}.get(keycode, 0)
            self._nudge_selection(dx, dy)
            return
        if keycode in (ord('H'), ord('X')):
            self._toggle_flip("x")
        elif keycode in (ord('V'), ord('Y')):
            self._toggle_flip("y")
        elif keycode == ord('R'):
            self._rotate_selected(-90 if event.ShiftDown() else 90)
        elif keycode in (wx.WXK_DELETE, wx.WXK_BACK):
            self._delete_selection()
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
        query = self.frame_filter.GetValue().strip().lower()
        # Fingerprint to skip full rebuild if just switching tabs
        current_fingerprint = (query, len(self.project.frames), tuple((f.id, f.name) for f in self.project.frames))
        if current_fingerprint == self._last_frames_fingerprint:
            # Only update selection if needed
            if select_id:
                for i, frame in enumerate(self._frame_view):
                    if frame.id == select_id:
                        if not self.frame_list.IsSelected(i):
                            self.frame_list.Select(i)
                            self.frame_list.EnsureVisible(i)
                        break
            return
        self._last_frames_fingerprint = current_fingerprint

        if query:
            self._frame_view = [f for f in self.project.frames if query in f.name.lower()]
            self.frames_box.SetLabel(f"Frames ({len(self._frame_view)} of {len(self.project.frames)})")
        else:
            self._frame_view = list(self.project.frames)
            self.frames_box.SetLabel(f"Frames ({len(self.project.frames)})")

        self.frame_list.DeleteAllItems()
        target_idx = -1
        for idx, f in enumerate(self._frame_view):
            self.frame_list.InsertItem(idx, f.name)
            if select_id and f.id == select_id:
                target_idx = idx

        if target_idx != -1:
            self.frame_list.Select(target_idx)
            self.frame_list.EnsureVisible(target_idx)

    def _frame_at(self, view_idx: int) -> Optional[Frame]:
        if 0 <= view_idx < len(self._frame_view):
            return self._frame_view[view_idx]
        return None

    def duplicate_selected_frame(self) -> None:
        if self.selected_frame_id:
            self._duplicate_frame(self.selected_frame_id)

    def _duplicate_frame(self, fid: str):
        frame = self.project.get_frame(fid)
        if not frame:
            return

        # Deep copy via serialization, with fresh ids for everything inside
        new_frame = Frame.from_dict(frame.to_dict())
        new_frame.id = generate_id("frm")
        new_frame.name = self._unique_frame_name(f"{frame.name} copy")
        for fm in new_frame.fmodules:
            fm.id = generate_id("fmod")
        for cr in new_frame.collision_rects:
            cr.id = generate_id("crect")
        for cp in new_frame.control_points:
            cp.id = generate_id("pt")

        self.project.frames.insert(self.project.frames.index(frame) + 1, new_frame)
        if self.frame_filter_active():
            self.frame_filter.ChangeValue("")
        self.refresh_frames(new_frame.id)
        self._switch_canvas_view(new_frame)
        self.snapshot()

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
        self.snapshot()

    def refresh_choices(self):
        """Called by app.py when switching tools."""
        self.palette.refresh_modules()
        # In new design, frame list is always visible, but good update point
        self.refresh_frames(self.selected_frame_id)

    # --- Copy / Paste / Propagate Logic ---
    def on_frame_list_context_menu(self, event):
        frame = self._frame_at(self.frame_list.GetFirstSelected())
        if not frame:
            return
        fid = frame.id
        
        menu = wx.Menu()
        
        # Frame Actions
        item_dup = menu.Append(wx.ID_ANY, "Duplicate Frame")
        item_del = menu.Append(wx.ID_ANY, "Delete Frame")
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
        self.Bind(wx.EVT_MENU, lambda e: self.on_delete_frame(None), item_del)
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

    def on_optimize_nested_combos(self, _event: wx.CommandEvent) -> None:
        if not self.project.frames:
            wx.MessageBox("No frames available.", "Info")
            return

        res = wx.MessageBox(
            (
                "Detect repeated module groups across ALL frames and replace them with nested helper frames?\n\n"
                "This keeps visual output but changes frame composition."
            ),
            "Optimize Nested Combos (All Frames)",
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if res != wx.YES:
            return

        with wx.BusyCursor():
            success, msg = optimize_nested_frame_combos(self.project)

        if success:
            wx.MessageBox(msg, "Nested Combo Optimization")
            self.refresh_frames(self.selected_frame_id)
            if self.selected_frame_id:
                frame = self.project.get_frame(self.selected_frame_id)
                if frame:
                    self.canvas.set_frame(frame)
            self.palette.refresh_modules()
            self.canvas.Refresh()
        else:
            wx.MessageBox(msg, "Nested Combo Optimization")
        
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
        frame = self._frame_at(self.frame_list.GetFirstSelected())
        if not frame or not self._clipboard_col:
            return
        clones = self._clone_rects(self._clipboard_col)
        frame.collision_rects.extend(clones)
        self.canvas.Refresh()
        self.snapshot()

    def _propagate_collision(self, src_frame):
        # Propagate to ALL frames (Append)
        # Maybe exclude source?
        src_rects = src_frame.collision_rects
        for f in self.project.frames:
            if f.id == src_frame.id: continue
            clones = self._clone_rects(src_rects)
            f.collision_rects.extend(clones)
        self.canvas.Refresh()
        self.snapshot()
        app_services.show_status(f"Appended {len(src_rects)} collision box(es) to every other frame")

    def _copy_points(self, frame):
        self._clipboard_pts = copy.deepcopy(frame.control_points)

    def _paste_points(self):
        frame = self._frame_at(self.frame_list.GetFirstSelected())
        if not frame or not self._clipboard_pts:
            return
        clones = self._clone_points(self._clipboard_pts)
        frame.control_points.extend(clones)
        self.canvas.Refresh()
        self.snapshot()

    def _propagate_points(self, src_frame):
        src_pts = src_frame.control_points
        for f in self.project.frames:
            if f.id == src_frame.id: continue
            clones = self._clone_points(src_pts)
            f.control_points.extend(clones)
        self.canvas.Refresh()
        self.snapshot()
        app_services.show_status(f"Appended {len(src_pts)} control point(s) to every other frame")

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
        new_name = event.GetLabel().strip()
        frame = self._frame_at(event.GetIndex())
        if frame and new_name and new_name != frame.name:
            frame.name = new_name
            self._last_frames_fingerprint = None
            wx.CallAfter(self.snapshot)

    # Renamed to match binding
    def on_begin_drag_frame(self, event):
        # Drag started: Cancel pending selection switch (if any)
        # This allows dragging a highlighted frame WITHOUT switching the view to it.
        self._pending_frame_switch = None
        
        frame = self._frame_at(event.GetIndex())
        if frame:
            # Send both project index (for reordering) and ID (for canvas drop)
            # Format: FRAME_REF:<idx>:<id>
            project_idx = self.project.frames.index(frame)
            text_data = wx.TextDataObject(f"FRAME_REF:{project_idx}:{frame.id}")
            source = wx.DropSource(self.frame_list)
            source.SetData(text_data)
            source.DoDragDrop(wx.Drag_DefaultMove)
            
            # Post-Drag: Restore selection to the currently active canvas frame
            # (Because clicking to drag selected the dragged frame in the list)
            if self.selected_frame_id:
                # Find index of self.selected_frame_id
                active_idx = -1
                for i, f in enumerate(self._frame_view):
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
            self.snapshot()
            
    def set_project(self, project: Project):
        self.project = project
        self.canvas.project = project
        self.canvas.clear_cache()
        
        # Completely recreate ModulePalette to force-clear wx.ListCtrl/ImageList internal caches
        # This is required because on some platforms (macOS), the ImageList layer is extremely sticky.
        old_palette = self.palette
        sizer = self._side_sizer
        insert_idx = 0
        for i, item in enumerate(sizer.GetChildren()):
            if item.GetWindow() == old_palette:
                insert_idx = i
                break
        was_shown = old_palette.IsShown()
        sizer.Detach(old_palette)
        old_palette.Destroy()

        self.palette = ModulePalette(self.side_box, project)
        self.palette.SetToolTip("Drag a module onto the canvas")
        self.palette.filter_text = self.palette_filter.GetValue().strip().lower()
        sizer.Insert(insert_idx, self.palette, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        sizer.Show(self.palette, was_shown)
        self.left_panel.Layout()
        
        # Update Managers
        self.col_manager.set_project(project)
        self.point_manager.set_project(project)
        
        self.palette.refresh_modules()
        
        self.selected_frame_id = None # Clear previous selection
        self._last_frames_fingerprint = None
        self.refresh_frames()
        self.canvas.set_frame(None)
        self.canvas.ghost_layers = []
        self.canvas.clear_cache() # Fix: FrameCanvas has its own bitmap cache that must be cleared!
        
        # Ensure canvas has correct collision/point colors immediately
        self.on_col_type_change()
        self.on_point_type_change()

    def on_select_frame(self, event):
        idx = event.GetIndex() if event else self.frame_list.GetFirstSelected()
        frame = self._frame_at(idx)
        if frame:
            self._switch_canvas_view(frame)
        else:
            self.canvas.set_frame(None)
            self.canvas.ghost_layers = []

    def _switch_canvas_view(self, frame):
        self.selected_frame_id = frame.id
        self.canvas.set_frame(frame)
        self._update_ghosts()

    def on_toggle_vis_col(self, checked: bool):
        self.canvas.show_collision = checked
        self.canvas.Refresh()

    def on_toggle_vis_pts(self, checked: bool):
        self.canvas.show_points = checked
        self.canvas.Refresh()

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

        if self.canvas.frame:
            valid_ids = {cr.id for cr in self.canvas.frame.collision_rects}
            self.canvas.selected_collision_rects = [cid for cid in self.canvas.selected_collision_rects if cid in valid_ids]
            if self.canvas._col_drag_rect_id not in valid_ids:
                self.canvas._col_drag_mode = "none"
                self.canvas._col_drag_rect_id = None
                self.canvas._col_drag_handle = -1
        self.canvas.Refresh()

    def on_point_type_change(self):
        self.canvas.active_point_type_id = self.point_manager.active_type_id
        visible_map = {}
        for pt in self.project.point_types:
             if self.point_manager.visibility.get(pt.id, True):
                 visible_map[pt.id] = pt.color
        self.canvas.point_type_colors = visible_map

        if self.canvas.frame:
            valid_ids = {cp.id for cp in self.canvas.frame.control_points}
            self.canvas.selected_points = [pid for pid in self.canvas.selected_points if pid in valid_ids]
            if self.canvas._pt_drag_id not in valid_ids:
                self.canvas._pt_drag_mode = "none"
                self.canvas._pt_drag_id = None
        self.canvas.Refresh()

    def on_add_frame(self, _):
        frame = Frame(id=generate_id("frm"), name=self._unique_frame_name(f"Frame {len(self.project.frames) + 1}"))
        current = self.project.get_frame(self.selected_frame_id or "")
        insert_at = self.project.frames.index(current) + 1 if current else len(self.project.frames)
        self.project.frames.insert(insert_at, frame)
        if self.frame_filter_active():
            self.frame_filter.ChangeValue("")
        self.selected_frame_id = frame.id
        self.refresh_frames(select_id=frame.id)
        self._switch_canvas_view(frame)
        self.snapshot()

    def _unique_frame_name(self, base: str) -> str:
        used = {f.name for f in self.project.frames}
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base} ({suffix})"
            suffix += 1
        return candidate

    def frame_references(self, frame_id: str) -> Dict[str, int]:
        """How often a frame is used by animations, other frames and timeline scenes."""
        anims = sum(1 for a in self.project.animations if any(af.frame_id == frame_id for af in a.aframes))
        nested = sum(
            1 for f in self.project.frames if any(fm.ref_type == "frame" and fm.ref_id == frame_id for fm in f.fmodules)
        )
        scene_objects = 0
        for scene in self.project.timeline_scenes:
            for obj in scene.objects:
                if (obj.source_type == "frame" and obj.source_id == frame_id) or any(
                    k.source_type == "frame" and k.source_id == frame_id for k in obj.keyframes
                ):
                    scene_objects += 1
        return {"animations": anims, "frames": nested, "scene_objects": scene_objects}

    def on_delete_frame(self, _):
        frame = self.project.get_frame(self.selected_frame_id or "")
        if not frame:
            return
        refs = self.frame_references(frame.id)
        uses = []
        if refs["animations"]:
            uses.append(f"{refs['animations']} animation(s)")
        if refs["frames"]:
            uses.append(f"{refs['frames']} other frame(s) as a nested part")
        if refs["scene_objects"]:
            uses.append(f"{refs['scene_objects']} timeline object(s)")
        if uses:
            msg = (
                f"Frame '{frame.name}' is used by " + ", ".join(uses) + ".\n"
                "Those references will point to a missing frame.\n\nDelete it anyway? (Undo with Ctrl/Cmd+Z.)"
            )
            if wx.MessageBox(msg, "Delete Frame", wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
                return
        view_idx = self._frame_view.index(frame) if frame in self._frame_view else -1
        self.project.frames = [f for f in self.project.frames if f.id != frame.id]
        self._last_frames_fingerprint = None
        self.selected_frame_id = None
        self.refresh_frames()
        neighbour = self._frame_at(min(view_idx, len(self._frame_view) - 1)) if view_idx >= 0 else None
        if neighbour:
            self.refresh_frames(select_id=neighbour.id)
            self._switch_canvas_view(neighbour)
        else:
            self.canvas.set_frame(None)
            self.canvas.ghost_layers = []
        self.snapshot()
        app_services.show_status(f"Deleted frame '{frame.name}'")

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
        self.snapshot()
