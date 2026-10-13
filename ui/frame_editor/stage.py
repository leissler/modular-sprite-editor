"""Frames stage: the frame canvas plus everything the mouse edits there (parts, hitboxes, points), marquee selection,
an origin marker and drops from the library."""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

import wx

from models import CollisionRect, ControlPoint, FModule, Module, Project, generate_id
from ui import first_steps
from ui.canvas import FrameCanvas
from ui.frame_geometry import orthogonal_cos_sin


class _StageDropTarget(wx.TextDropTarget):
    """Modules ("MODULE:<id>") and frames ("FRAME:<id>[,<id>...]", the first of several) from the library or list."""

    def __init__(self, stage: "FrameStage"):
        super().__init__()
        self.stage = stage

    def OnDropText(self, x, y, data):
        if data.startswith("MODULE:"):
            self.stage.handle_dropped_module(data.split(":", 1)[1], wx.Point(x, y), ref_type="module")
            return True
        if data.startswith("FRAME:"):
            first = data.split(":", 1)[1].split(",")[0]
            self.stage.handle_dropped_module(first, wx.Point(x, y), ref_type="frame")
            return True
        return False


class FrameStage(FrameCanvas):
    def __init__(self, parent: wx.Window, project: Project):
        super().__init__(parent, project)
        self.zoom = 4.0
        self.max_zoom = 32.0
        self.show_collision = False
        self.show_points = True
        self.empty_hint = ""
        # What the mouse edits: "module" (parts), "collision" (hitboxes) or "point" (ops.CANVAS_MODE).
        self.edit_mode = "module"
        self.selected_fmodules: List[str] = []
        self.selected_collision_rects: List[str] = []
        self.selected_points: List[str] = []
        # The type new hitboxes / points get (the panel's type choice).
        self.active_collision_type_id: Optional[str] = None
        self.active_point_type_id: Optional[str] = None

        # Parts: dragging the selection; clicking again on stacked parts picks the next one down.
        self._dragging_ids: List[str] = []
        self._drag_start_world: Optional[Tuple[float, float]] = None
        self._drag_start_positions: Dict[str, Tuple[int, int]] = {}
        self._last_module_hit_cycle_key: Optional[Tuple[int, int, Tuple[str, ...]]] = None
        self._last_module_hit_cycle_index = -1
        self._selected_hit_on_mouse_down_id: Optional[str] = None
        # Hitboxes: "none", "move", "resize" (by a corner handle: 0 TL, 1 TR, 2 BL, 3 BR) or "create".
        self._col_drag_mode = "none"
        self._col_drag_handle = -1
        self._col_drag_rect_id: Optional[str] = None
        self._col_drag_start_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
        # Points: "none" or "move".
        self._pt_drag_mode = "none"
        self._pt_drag_id: Optional[str] = None
        self._marquee: Optional[Tuple[wx.Point, wx.Point]] = None
        self._marquee_base: List[str] = []

        # Callbacks (set by the panel)
        self.on_interaction: Optional[Callable[[], None]] = None  # a click or drag ended: selection / data may differ
        self.on_live: Optional[Callable[[], None]] = None         # while dragging
        self.on_modify_ended: Optional[Callable[[], None]] = None  # a drag changed the frame: commit it
        self.on_drop: Optional[Callable[[str, str, Tuple[float, float]], None]] = None  # (ref type, id, world point)

        self.SetDropTarget(_StageDropTarget(self))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_MOTION, self.on_mouse_drag)

    def set_frame(self, frame) -> None:
        self._reset_module_hit_cycle()
        self._selected_hit_on_mouse_down_id = None
        super().set_frame(frame)

    # ------------------------------------------------------------------ drop (library, frame list)
    def handle_dropped_module(self, ref_id: str, pos: wx.Point, ref_type: str = "module") -> None:
        if self.on_drop:
            self.on_drop(ref_type, ref_id, self.screen_to_world(pos))

    # ------------------------------------------------------------------ mouse
    def on_left_down(self, event: wx.MouseEvent) -> None:
        self.SetFocus()
        if self.begin_pan_if_requested(event):
            return
        if self.frame is None:
            return
        pos = event.GetPosition()
        if self.edit_mode == "collision":
            self._hitbox_down(pos)
        elif self.edit_mode == "point":
            self._point_down(event, pos)
        elif not self.hit_test_all(self.screen_to_world(pos)):
            self._marquee = (pos, pos)
            self._marquee_base = list(self.selected_fmodules) if (event.ShiftDown() or event.CmdDown()) else []
            self.selected_fmodules = list(self._marquee_base)
            if not self.HasCapture():
                self.CaptureMouse()
            self._notify()
            self.Refresh(False)
            return
        else:
            self._part_down(event, self.screen_to_world(pos))
        self._notify()

    def on_mouse_drag(self, event: wx.MouseEvent) -> None:
        if self.handle_pan_motion(event):
            return
        if self._marquee is not None:
            if event.Dragging() and event.LeftIsDown():
                self._drag_marquee(event.GetPosition())
            return
        if self.frame is None:
            return
        if self.edit_mode == "collision" and not event.Dragging():
            self._update_handle_cursor(event.GetPosition())
        elif not self._dragging_ids and self._col_drag_mode == "none":
            self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        if not event.Dragging() or not event.LeftIsDown():
            return

        world = self.screen_to_world(event.GetPosition())
        if self.edit_mode == "collision":
            self._drag_hitbox(world)
        elif self.edit_mode == "point":
            self._drag_points(world)
        elif self._dragging_ids:
            self._drag_parts(world)
        else:
            return
        self.Refresh(False)
        if self.on_live:
            self.on_live()

    def on_left_up(self, event: wx.MouseEvent) -> None:
        if self._marquee is not None:
            if self.HasCapture():
                self.ReleaseMouse()
            self._marquee = None
            self.Refresh(False)
            self._notify()
            return
        if self._panning:
            self.on_pan_end(event)
            return
        if self.edit_mode == "collision":
            modified = self._hitbox_up()
        elif self.edit_mode == "point":
            modified = self._pt_drag_mode != "none"
            self._pt_drag_mode = "none"
            self._pt_drag_id = None
            self._drag_start_positions = {}
        else:
            self._part_click_up(event)
            modified = bool(self._dragging_ids)
            self._dragging_ids = []
            self._selected_hit_on_mouse_down_id = None
        self._drag_start_world = None
        if self.HasCapture():
            self.ReleaseMouse()
        if modified and self.on_modify_ended:
            self.on_modify_ended()
        self._notify()

    def _notify(self, live: bool = False) -> None:
        callback = self.on_live if live else self.on_interaction
        if callback:
            callback()

    # ------------------------------------------------------------------ parts
    def _part_down(self, event: wx.MouseEvent, world: Tuple[float, float]) -> None:
        """Select the part under the mouse (Shift adds, Cmd adds or removes) and start dragging the selection."""
        local = self.world_to_local(world)
        hits = self._hit_test_all_local(local)
        additive = event.ShiftDown() or event.CmdDown()
        if additive:
            clicked = hits[0]
            self._reset_module_hit_cycle()
            self._selected_hit_on_mouse_down_id = None
        else:
            selected_hit = next((fm for fm in hits if fm.id in self.selected_fmodules), None)
            if selected_hit:
                # Keep the selected part for an immediate drag; a click cycles on mouse-up.
                clicked = selected_hit
                self._selected_hit_on_mouse_down_id = selected_hit.id
            else:
                self._selected_hit_on_mouse_down_id = None
                cycle_key = (int(math.floor(local[0])), int(math.floor(local[1])), tuple(fm.id for fm in hits))
                if cycle_key == self._last_module_hit_cycle_key:
                    self._last_module_hit_cycle_index = (self._last_module_hit_cycle_index + 1) % len(hits)
                else:
                    self._last_module_hit_cycle_key = cycle_key
                    self._last_module_hit_cycle_index = 0
                clicked = hits[self._last_module_hit_cycle_index]

        if event.CmdDown() and clicked.id in self.selected_fmodules:
            self.selected_fmodules.remove(clicked.id)
        elif additive:
            if clicked.id not in self.selected_fmodules:
                self.selected_fmodules.append(clicked.id)
        elif clicked.id not in self.selected_fmodules:
            self.selected_fmodules = [clicked.id]  # a click on a selected part keeps the others: a group drag

        self._dragging_ids = self.selected_fmodules[:]
        self._drag_start_world = world
        self._drag_start_positions = {fm.id: fm.position for fm in self.frame.fmodules if fm.id in self._dragging_ids}
        self.CaptureMouse()
        self.Refresh(False)

    def _drag_parts(self, world: Tuple[float, float]) -> None:
        curr_local = self.world_to_local(world)
        start_local = self.world_to_local(self._drag_start_world)
        dx = curr_local[0] - start_local[0]
        dy = curr_local[1] - start_local[1]
        for fm in self.frame.fmodules:
            if fm.id in self._dragging_ids:
                start = self._drag_start_positions.get(fm.id, (0, 0))
                fm.position = (int(start[0] + dx), int(start[1] + dy))

    def _part_click_up(self, event: wx.MouseEvent) -> None:
        """A click without a drag: on stacked selected parts, pick the next one down; on one part of a multiple
        selection, select just that one."""
        if not self._drag_start_world or event.ShiftDown():
            return
        world = self.screen_to_world(event.GetPosition())
        dx = world[0] - self._drag_start_world[0]
        dy = world[1] - self._drag_start_world[1]
        if dx * dx + dy * dy >= 9:  # moved: a drag
            return
        hits = self._hit_test_all_local(self.world_to_local(world))
        held = self._selected_hit_on_mouse_down_id
        if held and any(fm.id == held for fm in hits):
            index = next(i for i, fm in enumerate(hits) if fm.id == held)
            if len(hits) > 1:
                following = hits[(index + 1) % len(hits)]
                self.selected_fmodules = [following.id]
                self._selected_hit_on_mouse_down_id = following.id
                self.Refresh(False)
        elif hits and len(self.selected_fmodules) > 1:
            self.selected_fmodules = [hits[0].id]
            self.Refresh(False)

    def _drag_marquee(self, pos: wx.Point) -> None:
        self._marquee = (self._marquee[0], pos)
        rect = self._marquee_rect()
        hits = []
        for fm in self.frame.fmodules if self.frame else []:
            x0, y0, x1, y1 = self._fmodule_bounds(fm)
            a = self.world_to_screen(self.local_to_world((x0, y0)))
            b = self.world_to_screen(self.local_to_world((x1, y1)))
            box = wx.Rect(wx.Point(int(min(a[0], b[0])), int(min(a[1], b[1]))),
                          wx.Point(int(max(a[0], b[0])), int(max(a[1], b[1]))))
            if rect.Intersects(box):
                hits.append(fm.id)
        selection = self._marquee_base + [i for i in hits if i not in self._marquee_base]
        if selection != self.selected_fmodules:
            self.selected_fmodules = selection
            self._notify(live=True)
        self.Refresh(False)

    def _marquee_rect(self) -> wx.Rect:
        a, b = self._marquee  # type: ignore[misc]
        return wx.Rect(wx.Point(min(a.x, b.x), min(a.y, b.y)), wx.Point(max(a.x, b.x), max(a.y, b.y)))

    def _reset_module_hit_cycle(self) -> None:
        self._last_module_hit_cycle_key = None
        self._last_module_hit_cycle_index = -1

    # ------------------------------------------------------------------ hitboxes
    def _hitbox_down(self, pos: wx.Point) -> None:
        """Grab a corner handle of the selected hitbox, else the hitbox under the mouse, else draw a new one."""
        world = self.screen_to_world(pos)
        if len(self.selected_collision_rects) == 1:
            cr = self._hitbox(self.selected_collision_rects[0])
            handle = self._hit_test_handle(cr, pos) if cr else -1
            if handle != -1:
                self._start_hitbox_drag("resize", cr, cr.rect, world, handle)
                return
        hit = self.hit_test_collision_rect(world)
        if hit:
            self.selected_collision_rects = [hit.id]
            self._start_hitbox_drag("move", hit, hit.rect, world)
            return
        type_id = self._resolve_active_collision_type_id()
        if type_id:
            x, y = int(world[0] - self.frame_offset[0]), int(world[1] - self.frame_offset[1])
            box = CollisionRect(id=generate_id("crect"), type_id=type_id, rect=(x, y, 0, 0))
            self.frame.collision_rects.append(box)
            self.selected_collision_rects = [box.id]
            self._start_hitbox_drag("create", box, (x, y, 0, 0), world)  # the corner it is drawn from
        else:
            self.selected_collision_rects = []
            self._col_drag_mode = "none"
            self._col_drag_rect_id = None
            self._drag_start_world = None
            self.Refresh(False)

    def _start_hitbox_drag(self, mode: str, cr: CollisionRect, start_rect, world: Tuple[float, float],
                           handle: int = -1) -> None:
        self._col_drag_mode = mode
        self._col_drag_handle = handle
        self._col_drag_rect_id = cr.id
        self._col_drag_start_rect = start_rect
        self._drag_start_world = world
        self.CaptureMouse()
        self.Refresh(False)

    def _drag_hitbox(self, world: Tuple[float, float]) -> None:
        cr = self._hitbox(self._col_drag_rect_id) if self._col_drag_mode != "none" else None
        if cr is None:
            return
        ox, oy, ow, oh = self._col_drag_start_rect
        if self._col_drag_mode == "create":
            x = int(world[0] - self.frame_offset[0])
            y = int(world[1] - self.frame_offset[1])
            cr.rect = (min(ox, x), min(oy, y), abs(x - ox), abs(y - oy))
            return
        dx = int(world[0] - self._drag_start_world[0])
        dy = int(world[1] - self._drag_start_world[1])
        if self._col_drag_mode == "move":
            cr.rect = (ox + dx, oy + dy, ow, oh)
        elif self._col_drag_mode == "resize":
            nx, ny, nw, nh = ox, oy, ow, oh
            handle = self._col_drag_handle
            if handle == 0:
                nx += dx; ny += dy; nw -= dx; nh -= dy
            elif handle == 1:
                ny += dy; nw += dx; nh -= dy
            elif handle == 2:
                nx += dx; nw -= dx; nh += dy
            elif handle == 3:
                nw += dx; nh += dy
            cr.rect = (nx, ny, nw if nw >= 0 else 1, nh if nh >= 0 else 1)  # no turning inside out

    def _hitbox_up(self) -> bool:
        """End a hitbox drag; whether it changed something."""
        modified = self._col_drag_mode != "none"
        if self._col_drag_mode == "create":
            box = self._hitbox(self._col_drag_rect_id)
            if box is not None and (box.rect[2] <= 0 or box.rect[3] <= 0):
                # A click without a drag: no box (the old editor left an invisible 0×0 one behind).
                self.frame.collision_rects.remove(box)
                self.selected_collision_rects = []
        self._col_drag_mode = "none"
        self._col_drag_rect_id = None
        self._col_drag_handle = -1
        return modified

    def _update_handle_cursor(self, pos: wx.Point) -> None:
        for cid in self.selected_collision_rects:
            cr = self._hitbox(cid)
            handle = self._hit_test_handle(cr, pos) if cr else -1
            if handle != -1:
                self.SetCursor(wx.Cursor(wx.CURSOR_SIZENWSE if handle in (0, 3) else wx.CURSOR_SIZENESW))
                return
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))

    def _hitbox(self, box_id: Optional[str]) -> Optional[CollisionRect]:
        return next((cr for cr in self.frame.collision_rects if cr.id == box_id), None)

    def _resolve_active_collision_type_id(self) -> Optional[str]:
        if not self.project.collision_types:
            self.active_collision_type_id = None
            return None
        if self.active_collision_type_id not in {ct.id for ct in self.project.collision_types}:
            self.active_collision_type_id = self.project.collision_types[0].id
        return self.active_collision_type_id

    # ------------------------------------------------------------------ points
    def _point_down(self, event: wx.MouseEvent, pos: wx.Point) -> None:
        """A click on a point selects and moves it (Shift adds it to the selection, Cmd adds or removes it); a click
        on empty space makes a new point there, like a drag makes a hitbox."""
        world = self.screen_to_world(pos)
        cp = self.hit_test_control_point(world)
        additive = event.ShiftDown() or event.CmdDown()
        if cp:
            if event.CmdDown() and cp.id in self.selected_points:
                self.selected_points.remove(cp.id)  # just deselected: nothing to drag
                self.Refresh()
                return
            if additive:
                if cp.id not in self.selected_points:
                    self.selected_points.append(cp.id)
            elif cp.id not in self.selected_points:
                self.selected_points = [cp.id]
            self._start_point_drag(cp.id, world)
        elif additive:
            return  # Shift / Cmd on empty space keeps the selection
        else:
            type_id = self._resolve_active_point_type_id()
            if type_id:
                # floor: the pixel under the mouse, also left of / above the origin
                x = int(math.floor(world[0] - self.frame_offset[0]))
                y = int(math.floor(world[1] - self.frame_offset[1]))
                point = ControlPoint(id=generate_id("pt"), type_id=type_id, x=x, y=y)
                self.frame.control_points.append(point)
                self.selected_points = [point.id]
                self._start_point_drag(point.id, world)  # the new point follows the mouse right away
            else:
                self.selected_points = []
                self._pt_drag_mode = "none"
                self._pt_drag_id = None
                self._drag_start_world = None
                self._drag_start_positions = {}
                self.Refresh()

    def _start_point_drag(self, point_id: str, world: Tuple[float, float]) -> None:
        self._pt_drag_mode = "move"
        self._pt_drag_id = point_id
        self._drag_start_world = world
        self._drag_start_positions = {
            cp.id: (cp.x, cp.y) for cp in self.frame.control_points if cp.id in self.selected_points
        }
        self.CaptureMouse()
        self.Refresh()

    def _drag_points(self, world: Tuple[float, float]) -> None:
        if self._pt_drag_mode != "move" or not self._drag_start_world:
            return
        dx = world[0] - self._drag_start_world[0]
        dy = world[1] - self._drag_start_world[1]
        for cp in self.frame.control_points:
            start = self._drag_start_positions.get(cp.id)
            if start and cp.id in self.selected_points:
                cp.x = int(start[0] + dx)
                cp.y = int(start[1] + dy)

    def _resolve_active_point_type_id(self) -> Optional[str]:
        if not self.project.point_types:
            self.active_point_type_id = None
            return None
        if self.active_point_type_id not in {pt.id for pt in self.project.point_types}:
            self.active_point_type_id = self.project.point_types[0].id
        return self.active_point_type_id

    # ------------------------------------------------------------------ hit-testing
    def hit_test_all(self, world_pt: Tuple[float, float]) -> List[FModule]:
        """Every part with a visible pixel under the point, top-most first."""
        return self._hit_test_all_local(self.world_to_local(world_pt))

    def hit_test_collision_rect(self, world_pt: Tuple[float, float]) -> Optional[CollisionRect]:
        if not self.frame:
            return None
        x, y = world_pt
        off_x, off_y = self.frame_offset
        for cr in reversed(self.frame.collision_rects):
            rx, ry, rw, rh = cr.rect
            if wx.Rect(int(rx + off_x), int(ry + off_y), rw, rh).Contains(int(x), int(y)):
                return cr
        return None

    def hit_test_control_point(self, world_pt: Tuple[float, float]) -> Optional[ControlPoint]:
        """The nearest point within 4 pixels."""
        if not self.frame:
            return None
        x, y = world_pt
        off_x, off_y = self.frame_offset
        best, best_dist = None, 4.0 * 4.0
        for cp in self.frame.control_points:
            dist = (cp.x + off_x - x) ** 2 + (cp.y + off_y - y) ** 2
            if dist <= best_dist and (best is None or dist < best_dist):
                best, best_dist = cp, dist
        return best

    def _hit_test_handle(self, cr: CollisionRect, screen_pos: wx.Point) -> int:
        """The hitbox corner within 8 screen pixels: 0 top left, 1 top right, 2 bottom left, 3 bottom right; -1 none."""
        rx, ry, rw, rh = cr.rect
        x0, y0 = rx + self.frame_offset[0], ry + self.frame_offset[1]
        mx, my = screen_pos
        for i, corner in enumerate(((x0, y0), (x0 + rw, y0), (x0, y0 + rh), (x0 + rw, y0 + rh))):
            sx, sy = self.world_to_screen(corner)
            if abs(mx - sx) <= 8 and abs(my - sy) <= 8:
                return i
        return -1

    def _hit_test_all_local(self, local_pt: Tuple[float, float]) -> List[FModule]:
        if not self.frame:
            return []
        return [fm for fm in reversed(self.frame.fmodules) if self._fmodule_contains_local_point(fm, local_pt)]

    def _fmodule_contains_local_point(self, fm: FModule, local_pt: Tuple[float, float], depth: int = 0) -> bool:
        if depth > 16:
            return False
        x0, y0, x1, y1 = self._fmodule_bounds(fm)
        min_x, min_y = min(x0, x1), min(y0, y1)
        max_x, max_y = max(x0, x1), max(y0, y1)

        # Half-open interval avoids double-hits on exact border pixels.
        if not (min_x <= local_pt[0] < max_x and min_y <= local_pt[1] < max_y):
            return False

        if fm.ref_type == "frame":
            ref_frame = self.project.get_frame(fm.ref_id)
            if not ref_frame:
                return True

            # Undo this frame-reference transform to test children in their own local space.
            test_x = local_pt[0] - fm.position[0]
            test_y = local_pt[1] - fm.position[1]
            cos_a, sin_a = orthogonal_cos_sin(-float(fm.rotation_degrees))
            rot_x = test_x * cos_a - test_y * sin_a
            rot_y = test_x * sin_a + test_y * cos_a
            if fm.flip_x:
                rot_x = -rot_x
            if fm.flip_y:
                rot_y = -rot_y
            return any(
                self._fmodule_contains_local_point(child_fm, (rot_x, rot_y), depth + 1)
                for child_fm in reversed(ref_frame.fmodules)
            )

        if fm.ref_type != "module":
            return True

        ref_id = fm.ref_id
        mapping = self.mapping
        if mapping and ref_id in mapping.map:
            ref_id = mapping.map[ref_id]
        if not ref_id:
            return False

        mod = self.project.get_module(ref_id)
        if not mod:
            return True

        target_w = max(1, int(round(max_x - min_x)))
        target_h = max(1, int(round(max_y - min_y)))
        px = int(math.floor(local_pt[0] - min_x))
        py = int(math.floor(local_pt[1] - min_y))
        if not (0 <= px < target_w and 0 <= py < target_h):
            return False

        if mod.type == "MD_IMAGE":
            base_img = self._get_module_source_image(mod)
        else:
            bmp = self._get_module_bitmap(mod)
            if not bmp or not bmp.IsOk():
                return True
            base_img = bmp.ConvertToImage()

        if not base_img or not base_img.IsOk():
            return True

        img = base_img.Copy()
        if fm.flip_x:
            img = img.Mirror(horizontally=True)
        if fm.flip_y:
            img = img.Mirror(horizontally=False)

        rot = int(fm.rotation_degrees) % 360
        if rot == 90:
            img = img.Rotate90(clockwise=True)
        elif rot == 180:
            img = img.Rotate180()
        elif rot == 270:
            img = img.Rotate90(clockwise=False)

        if img.GetWidth() != target_w or img.GetHeight() != target_h:
            img.Rescale(target_w, target_h, wx.IMAGE_QUALITY_NEAREST)

        if mod.type == "MD_IMAGE" and self.apply_key_colour:
            asset = self.project.get_image(mod.image_id)
            if asset and asset.transparent_color:
                tr, tg, tb = asset.transparent_color
                if img.GetRed(px, py) == tr and img.GetGreen(px, py) == tg and img.GetBlue(px, py) == tb:
                    return False

        if img.HasAlpha():
            return img.GetAlpha(px, py) > 0
        if img.HasMask():
            return not (
                img.GetRed(px, py) == img.GetMaskRed()
                and img.GetGreen(px, py) == img.GetMaskGreen()
                and img.GetBlue(px, py) == img.GetMaskBlue()
            )
        return True

    def _get_module_source_image(self, mod: Module) -> Optional[wx.Image]:
        """The module's pixels as used (a packed module turned upright), for hit-testing."""
        if mod.type != "MD_IMAGE":
            return None
        full_img = self._get_asset_source_image(mod.image_id)
        if not full_img:
            return None
        rx, ry, rw, rh = mod.rect
        if rw <= 0 or rh <= 0:
            return None
        if rx < 0 or ry < 0 or rx + rw > full_img.GetWidth() or ry + rh > full_img.GetHeight():
            return None
        sub_img = full_img.GetSubImage(wx.Rect(int(rx), int(ry), int(rw), int(rh)))
        if getattr(mod, "rotated", False):
            sub_img = sub_img.Rotate90(clockwise=False)
        return sub_img

    # ------------------------------------------------------------------ paint
    def draw_content(self, gc: wx.GraphicsContext) -> None:
        if self.frame is None:
            self._draw_hint(gc, self.empty_hint or first_steps.frames(self.project) or "Select a frame, or click + New in the list")
            return
        super().draw_content(gc)
        if not self.show_grid:
            self._draw_origin(gc)
        if not self.frame.fmodules and self.edit_mode == "module":
            self._draw_hint(gc, "Empty frame: drag modules or frames from the library onto the stage")
        if self._marquee is not None:
            rect = self._marquee_rect()
            gc.SetBrush(wx.Brush(wx.Colour(90, 170, 255, 40)))
            gc.SetPen(wx.Pen(wx.Colour(90, 170, 255), 1))
            gc.DrawRectangle(rect.x, rect.y, rect.width, rect.height)

    def draw_markers(self, gc: wx.GraphicsContext) -> None:
        """Hitboxes and points as the mode edits them: the parts dimmed under hitboxes / points, the ones being edited
        always shown with their roles, selected ones outlined white (a selected hitbox with corner handles); in parts
        mode the selected parts get a dashed outline over the hitboxes."""
        editing = self.edit_mode in ("collision", "point")
        if editing:
            gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 100)))
            gc.SetPen(wx.TRANSPARENT_PEN)
            size = self.GetClientSize()
            gc.DrawRectangle(0, 0, size.width, size.height)
        if self.show_collision or self.edit_mode == "collision":
            boxes = self.edit_mode == "collision"
            for cr in self.visible_hitboxes():
                selected = boxes and cr.id in self.selected_collision_rects
                x, y, w, h = self.draw_hitbox(gc, cr, selected)
                role = (cr.role or "").strip()
                if boxes and role:
                    self._draw_role(gc, role, x + 3, max(0, y - 16))
                if selected:
                    self._draw_resize_handles(gc, x, y, w, h)
        if self.edit_mode == "module":
            for fm in self.frame.fmodules:
                if fm.id in self.selected_fmodules:
                    self._draw_part_selection(gc, fm)
        if self.show_points or self.edit_mode == "point":
            points = self.edit_mode == "point"
            for cp in self.visible_points():
                x, y, size = self.draw_point(gc, cp, cp.id in self.selected_points)
                role = (cp.role or "").strip()
                if points and role:
                    self._draw_role(gc, role, x + size + 4, y - 2)

    def _draw_part_selection(self, gc: wx.GraphicsContext, fm: FModule) -> None:
        x0, y0, x1, y1 = self._fmodule_bounds(fm)
        p0 = self.world_to_screen(self.local_to_world((x0, y0)))
        p1 = self.world_to_screen(self.local_to_world((x1, y1)))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(wx.Colour(255, 255, 255), width=1, style=wx.PENSTYLE_SHORT_DASH))
        gc.DrawRectangle(min(p0[0], p1[0]), min(p0[1], p1[1]), abs(p1[0] - p0[0]), abs(p1[1] - p0[1]))

    def _draw_resize_handles(self, gc: wx.GraphicsContext, x: float, y: float, w: float, h: float) -> None:
        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255)))
        gc.SetPen(wx.Pen(wx.Colour(0, 0, 0)))
        for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
            gc.DrawRectangle(cx - 3, cy - 3, 6, 6)

    def _draw_role(self, gc: wx.GraphicsContext, role: str, x: float, y: float) -> None:
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(255, 255, 255))
        gc.DrawText(role, x, y)

    def _draw_origin(self, gc: wx.GraphicsContext) -> None:
        sx, sy = self.world_to_screen((0, 0))
        gc.SetPen(wx.Pen(wx.Colour(200, 200, 210, 150), 1))
        arm = 10
        gc.StrokeLine(sx - arm, sy, sx + arm, sy)
        gc.StrokeLine(sx, sy - arm, sx, sy + arm)

    def _draw_hint(self, gc: wx.GraphicsContext, text: str) -> None:
        gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT), wx.Colour(225, 228, 235))
        tw, th = gc.GetTextExtent(text)
        size = self.GetClientSize()
        x, y = (size.width - tw) / 2, 18
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(wx.Colour(20, 21, 24, 210)))
        gc.DrawRoundedRectangle(x - 12, y - 7, tw + 24, th + 14, 6)
        gc.DrawText(text, x, y)
