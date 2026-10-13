"""GUI smoke test: drive the real main window programmatically against a project.

Opens a window (needs a display), exercises every tab (view commands, geometry edits,
copy/paste, nudging, onion skin, playback, filters, global undo/redo, mapping sync) and
exits non-zero on any exception or failed check. Nothing is saved.

Usage:
    python3 tools/gui_smoke.py [PROJECT_JSON]     (default: examples/sgdk/PoP_WW.json)
"""
import atexit
import faulthandler
import os
import shutil
import sys
import tempfile
import traceback

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(repo, "examples", "sgdk", "PoP_WW.json")
sys.path.insert(0, repo)
os.chdir(repo)
if not os.environ.get("MSE_PREFERENCES_FILE"):
    # This run's preferences and crash-recovery copies go to a throwaway folder, never the user's.
    _prefs_dir = tempfile.mkdtemp(prefix="mse_gui_smoke_")
    atexit.register(shutil.rmtree, _prefs_dir, True)
    os.environ["MSE_PREFERENCES_FILE"] = os.path.join(_prefs_dir, "preferences.ini")

import wx  # noqa: E402

# Auto-answer modal dialogs.
wx.MessageBox = lambda *a, **k: wx.YES  # type: ignore[assignment]

# Synthetic drags hold no real mouse button. Report the button as held during them, like a real drag, so the
# main window's checkpoint timer does not split them into several undo steps (MainFrame._on_checkpoint_timer).
synthetic_button = [False]
_real_mouse_state = wx.GetMouseState


def _mouse_state():
    state = _real_mouse_state()
    if synthetic_button[0]:
        state.SetLeftDown(True)
    return state


wx.GetMouseState = _mouse_state  # type: ignore[assignment]

import app as app_mod  # noqa: E402
from ui.components import confirm  # noqa: E402
from ui.project_history import project_fingerprint  # noqa: E402

# Deleting something that is still used asks whether to remove its uses too; the steps keep them as missing.
confirm.ask_remove_uses = lambda *a, **k: confirm.KEEP

errors = []
orig_hook = sys.excepthook


def hook(exc_type, exc, tb):
    errors.append("".join(traceback.format_exception(exc_type, exc, tb)))
    orig_hook(exc_type, exc, tb)


sys.excepthook = hook

a = app_mod.SpriteEditorApp(False)
# Failed wx assertions raise exceptions instead of opening a modal dialog that would block the run.
a.SetAssertMode(wx.APP_ASSERT_EXCEPTION)
frame = a.GetTopWindow()
frame.SetSize((1500, 950))
frame.confirm_discard_changes = lambda: True  # no save prompts in the smoke test


def pump(n=3):
    for _ in range(n):
        wx.Yield()


def check(cond, msg):
    if not cond:
        errors.append("CHECK FAILED: " + msg)
        print("CHECK FAILED:", msg)


STEP_TIMEOUT = 180  # seconds; a step that hangs (e.g. a modal dialog) dumps the stacks and ends the run with 1


def step(name, fn):
    faulthandler.dump_traceback_later(STEP_TIMEOUT, exit=True, file=sys.stderr)
    try:
        fn()
        pump()
        print("ok  ", name)
    except Exception:
        errors.append(name + "\n" + traceback.format_exc())
        print("FAIL", name)
        traceback.print_exc()
    finally:
        faulthandler.cancel_dump_traceback_later()


def run():
    proj = None

    saved_recent = list(frame.recent_files)

    def load():
        nonlocal proj
        frame.load_project(project_path)
        frame.recent_files = saved_recent  # the smoke test must not reorder the user's recent files
        frame._save_recent_files()
        proj = frame.project
        check(len(proj.frames) > 0, "frames loaded")
        check(not frame.history.is_dirty(), "clean after load")

    step("load project", load)

    def tabs():
        for i in range(5):
            frame.select_tab(i)
            pump()
            canvas = frame._active_canvas()
            if canvas is not None:
                canvas.fit_to_content()
                canvas.zoom_step(1)
                canvas.zoom_step(-1)
                canvas.set_zoom_level(1.0)
                canvas.fit_to_content()

    step("cycle tabs + view commands", tabs)

    # ---- Modules
    me = frame.module_editor

    def modules():
        from ui.module_editor import ops as mops

        frame.select_tab(0)
        pump()
        img = proj.images[0]
        me.select_sheet(img.id)
        mod = next(m for m in proj.modules if m.image_id == img.id)
        me.select_module(mod.id)
        pump()
        check(me.selection == [mod.id], "module selected")
        check(me.inspector.w.GetValue() == mod.rect[2], "rect width shown")
        before = tuple(mod.rect)
        frame.history_checkpoint()
        me._on_field("x", before[0] + 3)
        check(tuple(mod.rect)[0] == before[0] + 3, "inspector edits module rect")
        frame.on_undo(None)
        pump()
        restored = proj.get_module(mod.id)
        check(tuple(restored.rect) == before, f"undo restores rect {restored.rect} vs {before}")
        frame.on_redo(None)
        pump()
        check(proj.get_module(mod.id).rect[0] == before[0] + 3, "redo reapplies rect")
        frame.on_undo(None)
        pump()
        me.modules.search.SetValue(mod.name[:3])
        pump()
        check(len(me.modules.list.rows) >= 1, "module filter keeps matches")
        me.modules.search.SetValue("")
        # Draw a new module on the sheet, set its pivot preset, trim it, nudge it, then undo it all
        count = len(proj.modules)
        me._create_from_canvas((0, 0, 24, 24))
        new = proj.get_module(me.selection[0])
        check(len(proj.modules) == count + 1 and new.image_id == img.id, "canvas drag creates a module")
        me._on_preset((0.5, 1.0))
        check(tuple(new.pivot) == (12, 24), "pivot preset")
        me.trim_modules()
        me.nudge(1, 0)
        me.canvas.Refresh()
        me.canvas.Update()
        for _ in range(5):
            frame.on_undo(None)
        pump()
        check(len(proj.modules) == count, "undo removes the new module")
        # Detect sprites keeps existing modules (adds only new areas)
        sheet = me._keyed_sheet()
        if sheet is not None:
            regions = mops.detect_regions(sheet.getchannel("A").tobytes(), sheet.width, sheet.height)
            me._add_cut_modules(regions, False, "Detect sprites")
            check(all(proj.get_module(m.id) for m in mops.modules_of_sheet(proj, img.id)), "detect keeps modules")
            frame.on_undo(None)
            pump()
            check(len(proj.modules) == count, "undo detect")
        me.select_sheet(mops.SHAPES_KEY)
        me._create_from_canvas((0, 0, 16, 12))
        shape = proj.get_module(me.selection[0])
        check(shape is not None and shape.type != "MD_IMAGE", "shape drawn on the Shapes sheet")
        frame.on_undo(None)
        pump()
        me.select_sheet(img.id)
        me.edit_select_all()
        check(len(me.selection) == len(mops.modules_of_sheet(proj, img.id)), "select all modules")
        me.select_modules([])

    step("modules: inspector + undo/redo + filter + draw/preset/trim + detect + shapes", modules)

    # ---- Frames
    fe = frame.frame_editor

    def frames():
        from ui.frame_editor import ops as fops

        frame.select_tab(1)
        pump()
        target = next(f for f in proj.frames if f.fmodules)
        fe.select_frame_by_id(target.id)
        pump()
        check(fe.stage.frame is target, "frame shown on the stage")
        fe.edit_select_all()
        check(len(fe.stage.selected_fmodules) == len(target.fmodules), "select all parts")
        check(len(fe.contents.list.selected_ids()) == len(target.fmodules), "contents list follows the selection")
        pos_before = [fm.position for fm in target.fmodules]
        fe.nudge(1, 0)
        check([fm.position for fm in target.fmodules] == [(x + 1, y) for x, y in pos_before], "nudge moves parts")
        frame.history_checkpoint()
        fe.edit_copy()
        count = len(target.fmodules)
        fe.edit_paste()
        check(len(target.fmodules) == 2 * count, "paste duplicates parts")
        frame.on_undo(None)
        pump()
        restored = proj.get_frame(target.id)
        check(len(restored.fmodules) == count, "undo removes pasted parts")
        check(fe.stage.frame is restored, "stage re-bound to the restored frame")
        frame.on_undo(None)
        pump()
        check([fm.position for fm in proj.get_frame(target.id).fmodules] == pos_before, "undo nudge")
        n_frames = len(proj.frames)
        fe.duplicate_frame()
        check(len(proj.frames) == n_frames + 1, "duplicate frame")
        dup = proj.get_frame(fe.selected_frame_id)
        check(dup.id != target.id and all(fm.id not in {x.id for x in target.fmodules} for fm in dup.fmodules), "fresh ids")
        fe.delete_frame()
        check(len(proj.frames) == n_frames, "delete frame")
        for mode in ("hitboxes", "points", "parts"):
            fe.set_mode(mode)
            pump()
            fe.stage.Refresh()
            fe.stage.Update()
        fe.select_frame_by_id(target.id)
        fe.onion_choice.SetSelection(3)
        fe._update_ghosts()
        pump()
        fe.stage.Refresh()
        fe.stage.Update()
        fe.browser.search.SetValue("stand")
        pump()
        check(all("stand" in f.name.lower() for f in fe._view), "frame filter")
        fe.browser.search.SetValue("")
        pump()
        fe.select_frame_by_id(target.id)
        fe.set_selected([target.fmodules[0].id])
        fe._flip("x")
        fe._on_part_tool("rot_cw")
        fe._on_part_tool("top")
        frame.on_undo(None)
        frame.on_undo(None)
        frame.on_undo(None)
        pump()
        # Add a part from the library, a hitbox and a point, then undo them
        fe.add_part("module", proj.modules[0].id, (0, 0))
        check(len(proj.get_frame(target.id).fmodules) == count + 1, "library part added")
        fe.set_mode("hitboxes")
        f = proj.get_frame(target.id)
        boxes = len(f.collision_rects)
        fops.insert_items(proj, f, "hitboxes", [{"id": "x", "type_id": proj.collision_types[0].id, "rect": [0, 0, 8, 8]}])
        fe.refresh()
        fe.set_selected([f.collision_rects[-1].id])
        fe._on_marker_field("role", "body")
        check(f.collision_rects[-1].role == "body", "hitbox role from the inspector")
        fe.set_mode("parts")
        for _ in range(3):
            frame.on_undo(None)
        pump()
        f = proj.get_frame(target.id)
        check(len(f.fmodules) == count and len(f.collision_rects) == boxes, "undo part and hitbox")
        fe.on_tab_activated()

    step("frames: select/nudge/copy/paste/undo/dup/delete/modes/onion/filter/flip/add/hitbox", frames)

    def editors_mouse():
        from ui.module_editor import ops as mops

        def mouse(handler, kind, pos, shift=False, cmd=False, left=True):
            evt = wx.MouseEvent(kind)
            evt.SetPosition(wx.Point(int(pos[0]), int(pos[1])))
            evt.SetLeftDown(left)
            evt.SetShiftDown(shift)
            evt.SetControlDown(cmd)
            synthetic_button[0] = left and kind != wx.wxEVT_LEFT_UP
            handler(evt)
            pump(1)

        def drag(widget, names, a, b, **keys):
            down, move, up = (getattr(widget, n) for n in names)
            mouse(down, wx.wxEVT_LEFT_DOWN, a, **keys)
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            mouse(move, wx.wxEVT_MOTION, mid, **keys)
            mouse(move, wx.wxEVT_MOTION, b, **keys)
            mouse(up, wx.wxEVT_LEFT_UP, b, left=False, **keys)

        # Modules: draw, move, resize, pivot, marquee, click to deselect
        frame.select_tab(0)
        pump()
        img = proj.images[0]
        me.select_sheet(img.id)
        cv = me.canvas
        cv.set_zoom_level(4.0)
        rects = [tuple(m.rect) for m in mops.modules_of_sheet(proj, img.id)]
        spot = next(((x, y) for y in range(0, img.height - 12, 4) for x in range(0, img.width - 12, 4)
                     if not any(mops.overlaps((x - 2, y - 2, 16, 16), r) for r in rects)), None)
        check(spot is not None, "free space on the sheet")
        if spot is None:
            return
        cv.center_view((spot[0] + 5, spot[1] + 5))
        pump()
        names = ("_on_left_down", "_on_motion", "_on_left_up")
        screen = lambda x, y: cv.world_to_screen((x + 0.5, y + 0.5))
        count = len(proj.modules)
        drag(cv, names, screen(*spot), screen(spot[0] + 7, spot[1] + 9))
        new = proj.get_module(me.selection[0]) if me.selection else None
        check(len(proj.modules) == count + 1 and new is not None and tuple(new.rect) == (spot[0], spot[1], 8, 10), f"drag draws a module {new.rect if new else None}")
        if new is None:
            return
        drag(cv, names, screen(spot[0] + 3, spot[1] + 3), screen(spot[0] + 5, spot[1] + 4))
        check(tuple(new.rect)[:2] == (spot[0] + 2, spot[1] + 1), f"drag moves the module {new.rect}")
        x, y, w, h = new.rect
        se = cv.world_to_screen((x + w, y + h))
        drag(cv, names, se, (se[0] + 8, se[1] + 8))
        check(tuple(new.rect)[2:] == (w + 2, h + 2), f"handle resizes the module {new.rect}")
        mouse(cv._on_left_down, wx.wxEVT_LEFT_DOWN, screen(x + 1, y + 1), shift=True)
        mouse(cv._on_left_up, wx.wxEVT_LEFT_UP, screen(x + 1, y + 1), shift=True, left=False)
        check(tuple(new.pivot) == (1, 1), f"Shift+click sets the pivot {new.pivot}")
        mouse(cv._on_left_down, wx.wxEVT_LEFT_DOWN, screen(spot[0] - 1, spot[1] - 1))
        mouse(cv._on_left_up, wx.wxEVT_LEFT_UP, screen(spot[0] - 1, spot[1] - 1), left=False)
        check(me.selection == [], "click on empty space deselects")
        drag(cv, names, screen(spot[0] - 1, spot[1] - 1), screen(spot[0] + 4, spot[1] + 4), cmd=True)
        check(me.selection == [new.id], "Cmd+drag selects with a marquee")
        for _ in range(4):
            frame.on_undo(None)
        pump()
        check(len(proj.modules) == count, "undo the drawn module")

        # Frames: marquee, hitbox drag, click without drag
        frame.select_tab(1)
        pump()
        target = max(proj.frames, key=lambda f: len(f.fmodules))
        fe.select_frame_by_id(target.id)
        st = fe.stage
        st.fit_to_content()
        pump()
        fe.set_mode("parts")
        w, h = st.GetClientSize()
        fnames = ("on_left_down", "on_mouse_drag", "on_left_up")
        drag(st, fnames, (3, 3), (w - 3, h - 3))
        check(len(st.selected_fmodules) == len(target.fmodules), "marquee over the stage selects every part")
        fe.set_mode("hitboxes")
        boxes = len(target.collision_rects)
        corner = (3, 3)
        mouse(st.on_left_down, wx.wxEVT_LEFT_DOWN, corner)
        mouse(st.on_left_up, wx.wxEVT_LEFT_UP, corner, left=False)
        check(len(proj.get_frame(target.id).collision_rects) == boxes, "a click draws no empty hitbox")
        drag(st, fnames, (10, 10), (10 + 6 * st.zoom, 10 + 5 * st.zoom))
        f = proj.get_frame(target.id)
        check(len(f.collision_rects) == boxes + 1 and f.collision_rects[-1].rect[2:] == (6, 5), "drag draws a hitbox")
        check(fe.inspector.marker_panel.IsShown(), "the new hitbox shows in the inspector")
        frame.on_undo(None)
        pump()
        check(len(proj.get_frame(target.id).collision_rects) == boxes, "undo the hitbox")
        fe.set_mode("parts")

    step("modules + frames: mouse on the canvases", editors_mouse)

    # ---- Animations
    ae = frame.animation_editor

    def animations():
        import tempfile
        from ui.animation_editor import ops as aops
        from ui.animation_editor.render import export_gif

        frame.select_tab(2)
        pump(5)
        if sum(1 for a in proj.animations if len(a.aframes) >= 3) < 2 and len(proj.frames) >= 2:
            # A project without animations (e.g. a sheet of whole sprites) gets two from its frames, so every
            # animation check below has steps to work on.
            from models import AFrame, Animation

            frames = [f for f in proj.frames if f.fmodules] or proj.frames
            for n, name in enumerate(("smoke test A", "smoke test B")):
                steps = [AFrame(frame_id=f.id, duration_frames=4) for f in (frames[n:] + frames[:n])[:6]]
                proj.animations.append(Animation(id=f"smoke_anim_{n}", name=name, aframes=steps))
            frame.history_checkpoint()
            ae.refresh_after_history()
            pump()
        if not proj.animations:
            ae.new_animation()
        anim = max(proj.animations, key=lambda a: len(a.aframes))
        ae.select_animation(anim.id)
        pump()
        check(ae.animation() is anim, "animation selected")
        check(ae.browser.list.selected_animation() is anim, "list follows the selection")

        # Playhead, onion skin, playback through the runtime-like player
        ae.onion_choice.SetSelection(3)
        ae.seek_step(1)
        check(ae.current_step() == 1, "seek to step")
        check(len(ae.stage.ghost_layers) >= 1, "onion ghosts present")
        ae.step(1)
        check(ae.current_step() == 2, "next step")
        ae.toggle_play()
        pump(5)
        ae.toggle_play()
        check(not ae.is_playing, "playback stopped")

        # Offsets: nudge, stage drag, undo
        ae.select_steps([0])
        off = anim.aframes[0].offset
        ae.nudge_selected(1, 0)
        check(anim.aframes[0].offset == (off[0] + 1, off[1]), "nudge offset")
        frame.history_checkpoint()
        frame.on_undo(None)
        pump()
        anim = proj.get_animation(anim.id)
        check(anim.aframes[0].offset == off, "undo offset nudge")
        ae.select_steps([0, 1])
        bases = [anim.aframes[i].offset for i in (0, 1)]
        ae._stage_drag_begin()
        ae._stage_drag(3, -2)
        ae._stage_drag_end(True)
        check([anim.aframes[i].offset for i in (0, 1)] == [(x + 3, y - 2) for x, y in bases], "stage drag moves the selection")

        # Holds: keys and edge drag
        ae.select_steps([0])
        before = aops.hold(anim.aframes[0])
        ae.change_hold(1)
        check(anim.aframes[0].duration_frames == before + 1, "] lengthens the hold")
        ae._hold_drag_begin(0)
        ae._hold_drag(2)
        ae._commit()
        check(anim.aframes[0].duration_frames == before + 3, "edge drag sets the hold")

        # Steps: insert from the library, move, copy/paste, flip, delete
        count = len(anim.aframes)
        ae.insert_frame(proj.frames[0].id, 0)
        check(len(anim.aframes) == count + 1 and anim.aframes[0].frame_id == proj.frames[0].id, "insert frame from library")
        ae.move_steps([0], 3, False)
        check(anim.aframes[2].frame_id == proj.frames[0].id, "move step")
        ae.move_steps([2], 0, True)
        check(len(anim.aframes) == count + 2, "alt-drag copies")
        ae.select_steps([0])
        flipped = anim.aframes[0].flip_x
        ae.flip_selected("x")
        check(anim.aframes[0].flip_x != flipped, "flip step")
        ae.edit_select_all()
        ae.edit_copy()
        ae.select_steps([len(anim.aframes) - 1])
        ae.edit_paste()
        check(len(anim.aframes) == 2 * (count + 2), "paste steps")
        ae.edit_select_all()
        ae.edit_duplicate()
        ae.delete_steps()
        check(len(anim.aframes) == 2 * (count + 2), "delete duplicated steps")

        # Whole animation: mirror twice is identity
        offsets = [af.offset for af in anim.aframes]
        ae._on_animation_tool("mirror_x")
        ae._on_animation_tool("mirror_x")
        check([af.offset for af in anim.aframes] == offsets, "mirror whole animation twice")

        # Settings through the inspector
        ae._on_animation_field("playback", "ping_pong")
        ae._on_animation_field("fps", 20)
        check(anim.playback_type == "ping_pong" and anim.fps == 20, "playback settings")
        ae.toggle_play()
        pump(5)
        ae.toggle_play()

        # GIF export (pixel-exact renderer, one cycle)
        path = os.path.join(tempfile.mkdtemp(), "smoke.gif")
        frames_written = export_gif(proj, anim, path, proj.active_mapping, (True, False))
        check(frames_written > 0 and os.path.getsize(path) > 0, "GIF export")

        # Animations: new / rename / duplicate / delete, filter
        n = len(proj.animations)
        ae.new_animation()
        pump()
        new_anim = ae.animation()
        ae._rename_animation(new_anim.id, "Smoke anim")
        check(new_anim.name == "Smoke anim", "rename animation")
        ae.insert_frame(proj.frames[0].id, 0)
        ae.duplicate_animation()
        check(len(proj.animations) == n + 2, "new + duplicate animation")
        ae.delete_animation()
        ae.select_animation(new_anim.id)
        ae.delete_animation()
        check(len(proj.animations) == n, "delete animations")
        ae.browser.search.SetValue(anim.name[:3])
        pump()
        check(anim in ae._view, "filter keeps matches")
        ae.browser.search.SetValue("")
        ae.mirror_choice.SetSelection(1)
        ae._refresh_stage()
        ae.stage.fit_to_content()
        for _ in range(8):
            frame.on_undo(None)
        pump()

    step("animations: select/onion/play/nudge/drag/hold/steps/mirror/gif/new/delete/undo", animations)

    def animation_mouse():
        from ui.animation_editor import ops as aops

        def mouse(widget, kind, x, y, shift=False, alt=False, left=True):
            evt = wx.MouseEvent(kind)
            evt.SetPosition(wx.Point(int(x), int(y)))
            evt.SetLeftDown(left)
            evt.SetShiftDown(shift)
            evt.SetAltDown(alt)
            handler = {wx.wxEVT_LEFT_DOWN: "_on_left_down", wx.wxEVT_MOTION: "_on_motion", wx.wxEVT_LEFT_UP: "_on_left_up"}[kind]
            synthetic_button[0] = left and kind != wx.wxEVT_LEFT_UP
            getattr(widget, handler)(evt)
            pump(1)

        frame.select_tab(2)
        anim = max(proj.animations, key=lambda a: len(a.aframes))
        ae.select_animation(anim.id)
        ae.sequence.tick_w = 40.0
        ae.sequence.set_scroll(0)
        pump()
        sq = ae.sequence
        from ui.animation_editor.sequence import CELL_TOP

        y = CELL_TOP + 30  # inside the cells row

        def centre(i):
            r = sq.cell_rect(i)
            return r.x + r.width // 2

        mouse(sq, wx.wxEVT_LEFT_DOWN, centre(2), y)
        mouse(sq, wx.wxEVT_LEFT_UP, centre(2), y, left=False)
        check(ae.selection == {2} and ae.current_step() == 2, "click selects a step")
        mouse(sq, wx.wxEVT_LEFT_DOWN, centre(4), y, shift=True)
        mouse(sq, wx.wxEVT_LEFT_UP, centre(4), y, shift=True, left=False)
        check(ae.selection == {2, 3, 4}, "shift-click selects a range")

        # Drag step 0's right edge two ticks to the right
        before = aops.hold(anim.aframes[0])
        edge = sq.cell_rect(0)
        ex = edge.x + edge.width
        mouse(sq, wx.wxEVT_LEFT_DOWN, ex, y)
        mouse(sq, wx.wxEVT_MOTION, ex + 2 * sq.tick_w, y)
        mouse(sq, wx.wxEVT_LEFT_UP, ex + 2 * sq.tick_w, y, left=False)
        check(aops.hold(anim.aframes[0]) == before + 2, "edge drag changes the hold")

        # Drag step 1 behind step 3
        moving = anim.aframes[1]
        mouse(sq, wx.wxEVT_LEFT_DOWN, centre(1), y)
        target = sq.cell_rect(3)
        mouse(sq, wx.wxEVT_MOTION, target.x + target.width - 3, y)
        mouse(sq, wx.wxEVT_LEFT_UP, target.x + target.width - 3, y, left=False)
        check(anim.aframes[3] is moving, "drag reorders steps")

        # Ruler scrub
        mouse(sq, wx.wxEVT_LEFT_DOWN, sq.x_of_tick(5) + 2, 8)
        mouse(sq, wx.wxEVT_LEFT_UP, sq.x_of_tick(5) + 2, 8, left=False)
        check(ae.tick == 5, "ruler scrubs the playhead")

        # Animation list: rename in place and drag to reorder
        lst = ae.browser.list
        lst.begin_rename()
        if lst._editor:
            lst._editor.SetValue("Renamed in place")
            lst._finish_rename(True, anim.id)
        check(anim.name == "Renamed in place", "rename in the list")
        for _ in range(4):
            frame.on_undo(None)
        pump()

    step("animations: mouse in the sequence and the list", animation_mouse)

    def animation_events_loop_next():
        import time as _time

        from ui.animation_editor import ops as aops

        frame.select_tab(2)
        anims = sorted(proj.animations, key=lambda a: -len(a.aframes))
        anim, other = anims[0], anims[1]
        ae.select_animation(anim.id)
        ae.select_steps([0, 1])
        ae._on_event_field("add", "smoke_hit", 0)
        etype = aops.event_type_by_name(proj, "smoke_hit")
        check(etype is not None and all(any(e.type_id == etype.id for e in anim.aframes[i].events) for i in (0, 1)),
              "event added to the selected steps (type created from its name)")
        ae._on_event_field("value", etype.id, 5)
        check(anim.aframes[0].events[-1].value == 5, "event value")
        check(ae.inspector._event_spins.get(etype.id) is not None, "inspector shows the event row")
        ae.select_steps([1])
        ae._on_event_field("remove", etype.id, None)
        check(not any(e.type_id == etype.id for e in anim.aframes[1].events), "event removed")

        # The preview shows the step's events on the stage; they light up when the step starts while playing
        ae.seek_step(0)
        pump()
        check(("smoke_hit=5", tuple(etype.color)) in ae.stage.events and ae.stage.event_flash == 0,
              "stage shows the paused step's events, not lit")
        ae.toggle_play()  # starts on step 0: its events fire (checked before pumping: the flash fades in 0.6 s)
        check(ae.stage.event_flash > 0.5 and ae.sequence.flash_step == 0, "events light up when their step starts")
        pump()
        check(ae.sequence.flash_step in (0, -1), "the sequence lights up the step that fired")
        ae.stop_playback()
        pump()
        check(ae.stage.event_flash == 0 and ae.sequence.flash_step == -1, "stopping ends the flash")
        ae.seek_step(1)
        pump()
        check(not ae.stage.events, "a step without events shows none")

        # Loop from: the intro plays once, edits keep the loop point on its step
        ae._on_animation_field("playback", "loop")
        ae._on_animation_field("loop_start", 2)
        check(anim.loop_start == 2, "loop from")
        anchor = anim.aframes[2]
        ae.insert_frame(proj.frames[0].id, 0)
        check(anim.aframes[anim.loop_start] is anchor, "insert keeps the loop point on its step")

        # Follow-up: a short Play-once animation hands over to another one when it ends
        ae._on_animation_field("playback", "forward")
        ae._on_animation_field("fps", 60)
        ae._on_animation_field("next", other.id)
        check(anim.next_animation_id == other.id, "then play")
        ae.chk_repeat.SetValue(False)
        ae.repeat = False
        ae.seek_step(len(anim.aframes) - 1)
        ae.toggle_play()
        deadline = _time.monotonic() + 3.0
        while _time.monotonic() < deadline and ae.selected_animation_id == anim.id:
            pump(1)
            _time.sleep(0.02)
        check(ae.selected_animation_id == other.id, "playback continues with the follow-up animation")
        ae.stop_playback()
        ae.chk_repeat.SetValue(True)
        ae.repeat = True
        for _ in range(12):
            frame.on_undo(None)
        pump()

    step("animations: events, loop from, follow-up", animation_events_loop_next)


    # ---- Timeline (scene editor)
    te = frame.timeline_editor

    def timeline():
        from ui.scene_editor import ops

        frame.select_tab(3)
        pump(5)
        if not proj.timeline_scenes:
            te.new_scene()
        te.refresh_scenes()
        scene = te.scene()
        check(scene is not None, "scene selected")
        n = len(scene.objects)

        # Add from the library (animation if any, else a frame), then a group
        if proj.animations:
            te.add_object("animation", proj.animations[0].id, (10, 20))
        else:
            te.add_object("frame", proj.frames[0].id, (10, 20))
        pump()
        obj = te.obj()
        check(obj is not None and len(scene.objects) == n + 1, "add object from library")
        te.add_object("none", None, (0, 0))
        group = te.obj()

        # Clicking (no drag) must not create keys
        keys_before = len(obj.keyframes)
        te.select_object(obj.id)
        te.seek(5)
        te._stage_drag_begin(obj.id)
        te._stage_drag(obj.id, 0.0, 0.0)
        te._stage_drag_end()
        check(len(obj.keyframes) == keys_before, "click without drag adds no key")

        # Auto-Key on: dragging at frame 5 creates a key there
        te._stage_drag_begin(obj.id)
        te._stage_drag(obj.id, 6.0, -3.0)
        te._stage_drag_end()
        key5 = ops.key_at_frame(obj, 5, scene.fps)
        check(key5 is not None and (key5.x, key5.y) == (16.0, 17.0), "auto-key drag sets a key")

        # Auto-Key off between keys: moving shifts the whole animation
        te.auto_key = False
        te.seek(2)
        before = [(k.x, k.y) for k in obj.sorted_keyframes()]
        te._on_transform_field("x", 30)
        after = [(k.x, k.y) for k in obj.sorted_keyframes()]
        check(len(after) == len(before) and all(a[0] != b[0] for a, b in zip(after, before)), "auto-key off shifts all keys")
        te.auto_key = True

        # Easing via inspector path, retime, parent, play, delete, undo
        first = obj.sorted_keyframes()[0]
        te.seek(ops.frame_of(first.time, scene.fps))
        te._on_easing("cubic_out")
        check(ops.segment_easing(obj, first.id) == "cubic_out", "segment easing set")
        te.set_key_selection({obj.id: {key5.id}})
        te._timeline_move_keys(3, {(obj.id, key5.id): 5})
        te._commit()
        check(ops.frame_of(key5.time, scene.fps) == 8, "retime key")
        te._move_layer(obj.id, group.id, None)
        check(obj.parent_id == group.id, "parent via layer drag")
        if proj.mappings:
            # A group's own mapping reaches its children; the inspector offers inherit / original / each mapping
            te.select_object(group.id)
            te._on_object_field("mapping", proj.mappings[0].id)
            check(te.stage.object_mapping(obj.id) is proj.mappings[0], "child inherits the group's mapping")
            te.select_object(obj.id)
            choice = te.inspector.obj_mapping
            check(choice.GetSelection() == 0 and "parent" in choice.GetString(0), "inspector: inherit from the parent")
            choice.SetSelection(1)
            te.inspector._on_mapping_choice(None)
            check(obj.mapping_id == "original" and te.stage.object_mapping(obj.id) is None, "inspector: original modules")
            te.stage.Refresh()
            te.stage.Update()
        if obj.source_type == "animation":
            # New objects play as animated; the inspector offers the overrides and the stage follows them
            check(obj.playback_mode == "as_animated", "new objects play as animated")
            te.select_object(obj.id)
            modes = [mode for _label, mode in ops.PLAYBACK_MODES]
            check(te.inspector.pb_mode.GetCount() == len(modes) and te.inspector.pb_mode.GetSelection() == 0,
                  "inspector: As animated and the overrides")
            te.inspector.pb_mode.SetSelection(modes.index("backward"))
            te._on_object_field("playback_mode", "backward")
            check(obj.playback_mode == "backward", "playback override set")
            te.stage.Refresh()
            te.stage.Update()
        te.toggle_play()
        pump(8)
        te.toggle_play()
        te.flip_selected("x")
        te.rotate_selected(90)
        te.edit_select_all()
        te.edit_copy()
        te.seek(ops.scene_length_frames(scene) // 2)
        te.edit_paste()
        te.inspector.show_context(proj, scene, te.obj(), te.frame)
        te.select_object(None)  # scene settings
        te._on_scene_field("fps", 30)
        from ui.scene_editor.panel import CONFIG_SCREEN_GUIDE

        saved_guide = wx.Config.Get().ReadInt(CONFIG_SCREEN_GUIDE, 0)
        te.screen_choice.SetSelection(1)
        te._on_screen_choice(None)
        wx.Config.Get().WriteInt(CONFIG_SCREEN_GUIDE, saved_guide)  # the smoke test must not change preferences
        wx.Config.Get().Flush()
        te.stage.Refresh()
        te.stage.Update()
        te.timeline.Refresh()
        te.timeline.Update()
        count = len(scene.objects)
        te.select_object(group.id)
        te.delete_selection()
        check(len(scene.objects) == count - 1 and obj.parent_id is None, "delete group keeps child")
        for _ in range(12):
            frame.on_undo(None)
        pump()
        check(len(te.scene().objects) >= n, "undo through scene edits")

    step("timeline: add, auto-key, easing, retime, parent, play, copy/paste, delete, undo", timeline)

    def slow_playback():
        # A slow machine: every frame takes longer to draw than the playback interval. Waiting for events while
        # playing must still return and frames must keep coming (on Windows wx.Yield never returned while the
        # timer was armed before the frame had been drawn).
        import time as _time

        anim = max(frame.project.animations, key=lambda a: len(a.aframes), default=None)
        for tab, panel, label in ((2, ae, "Animations"), (3, te, "Timeline")):
            frame.select_tab(tab)
            if tab == 2 and anim is not None:
                ae.select_animation(anim.id)
            pump()
            canvas, shown = panel.stage, [0]
            canvas.Unbind(wx.EVT_PAINT)
            canvas.Bind(wx.EVT_PAINT, lambda event, c=canvas: (c.on_paint(event), _time.sleep(0.03)))
            play_frame = panel._play_frame
            panel._play_frame = lambda f=play_frame: (shown.__setitem__(0, shown[0] + 1), f())
            try:
                panel.toggle_play()
                if not panel.is_playing:
                    continue  # nothing to play (no animation or scene)
                start = _time.monotonic()
                while _time.monotonic() - start < 1.0:
                    pump(1)
                    _time.sleep(0.002)
                check(shown[0] >= 3, f"{label}: playback keeps showing frames that draw slowly ({shown[0]} in 1 s)")
            finally:
                panel.stop_playback()
                del panel._play_frame
                canvas.Unbind(wx.EVT_PAINT)
                canvas.Bind(wx.EVT_PAINT, canvas.on_paint)

    step("playback with slow drawing: waiting for events returns, frames keep coming", slow_playback)

    def budget():
        import hardware_budget as hb

        # Frames tab
        frame.select_tab(1)
        pump()
        fe = frame.frame_editor
        fe.canvas_controls._set_budget("md_h40", persist=False)
        target = next((f for f in proj.frames if f.fmodules), None)
        if target:
            fe.select_frame_by_id(target.id)
            pump()
            b = fe.canvas.compute_budget()
            check(b is not None and b.sprite_count > 0, "frames: budget counts hardware sprites")
            fe.canvas.Refresh()
            fe.canvas.Update()
        fe.canvas_controls._set_budget("", persist=False)
        check(fe.canvas.budget_profile is None, "frames: budget off")

        # Animations tab: overlay plus the worst step in the inspector
        frame.select_tab(2)
        pump()
        anim = max(proj.animations, key=lambda a: len(a.aframes)) if proj.animations else None
        if anim:
            ae.select_animation(anim.id)
            ae.canvas_controls._set_budget("md_h32", persist=False)
            ae.refresh()
            pump()
            check(ae.stage.budget_profile is hb.MEGA_DRIVE_H32, "animations: budget profile")
            label = " ".join(ae.inspector.budget_info.GetLabel().split())  # the label wraps
            check(ae.inspector.budget_info.IsShown() and "worst step" in label, "animations: worst step shown")
            ae.stage.Refresh()
            ae.stage.Update()
            ae.canvas_controls._set_budget("", persist=False)
            ae.refresh()

        # Timeline: whole scene
        frame.select_tab(3)
        pump()
        te.canvas_controls._set_budget("md_h40", persist=False)
        b = te.stage.compute_budget()
        check(b is not None, "timeline: scene budget")
        te.stage.Refresh()
        te.stage.Update()
        te.canvas_controls._set_budget("", persist=False)

    step("budget overlay: frames / animations / timeline", budget)

    # ---- Palettes, Mega Drive colours, SNES budgets, video memory
    def palettes_and_memory():
        import hardware_budget as hb
        from ui.canvas import BUDGET, EXPORT_TILES
        from ui.console_colours import CONSOLE

        frame.select_tab(0)
        pump()
        img = proj.images[0]
        me.select_sheet(img.id)
        pump()
        check(me.inspector.palette_choice.IsShown(), "modules: a sheet shows its palette")
        frame.history_checkpoint()
        me._set_palette(1)
        check(proj.get_image(img.id).palette == 1, "modules: the image moves to Palette 2")
        frame.on_undo(None)
        pump()
        check(proj.get_image(img.id).palette == 0, "undo restores the palette")
        frame.set_console_colours(True)
        check(CONSOLE.enabled and frame.m_console.IsChecked(), "View > Mega Drive Colours on")
        me.canvas.Refresh()
        me.canvas.Update()
        shown = CONSOLE.image(proj, proj.get_image(img.id))
        levels = {v * 255 // 7 for v in range(8)}
        visible = {rgba[:3] for _n, rgba in (shown.getcolors(1 << 22) or []) if rgba[3]} if shown is not None else set()
        check(bool(visible) and all(v in levels for rgb in visible for v in rgb), "console colours: 3 bits per channel")
        frame.select_tab(1)
        pump()
        fe.canvas.Refresh()
        fe.canvas.Update()
        frame.set_console_colours(False)
        check(not CONSOLE.enabled and not frame.m_console.IsChecked(), "Mega Drive Colours off")

        target = next((f for f in proj.frames if f.fmodules), None)
        if target:
            fe.select_frame_by_id(target.id)
            fe.canvas_controls._set_budget("snes_16_32", persist=False)
            pump()
            b = fe.canvas.compute_budget()
            check(b is not None and b.profile is hb.SNES_16_32 and b.sprite_count > 0, "frames: SNES budget")
            fe.canvas.Refresh()
            fe.canvas.Update()
            fe.canvas_controls._set_budget("md_h40", persist=False)
            b = fe.canvas.compute_budget()
            check(0 < b.unique_tiles <= b.tile_count, "frames: the frame's tiles of video memory")
            total = EXPORT_TILES.get(proj)
            check(total == BUDGET.export_tiles(proj, [None] + proj.mappings) and total >= b.unique_tiles,
                  "the whole project's tiles")
            fe.canvas.Refresh()
            fe.canvas.Update()
            fe.canvas_controls._set_budget("", persist=False)
        frame.select_tab(2)
        pump()
        anim = max(proj.animations, key=lambda a: len(a.aframes)) if proj.animations else None
        if anim:
            ae.select_animation(anim.id)
            ae.canvas_controls._set_budget("md_h40", persist=False)
            ae.refresh()
            pump()
            label = " ".join(ae.inspector.budget_info.GetLabel().split())  # the label wraps
            check("video memory" in label, "animations: the animation's video memory")
            ae.canvas_controls._set_budget("snes_8_16", persist=False)
            ae.refresh()
            pump()
            label = " ".join(ae.inspector.budget_info.GetLabel().split())
            check("worst step" in label and "video memory" not in label, "animations: SNES budget, no video memory")
            ae.stage.Refresh()
            ae.stage.Update()
            ae.canvas_controls._set_budget("", persist=False)
            ae.refresh()

    step("palettes, Mega Drive colours, SNES budgets, video memory", palettes_and_memory)

    # ---- Mappings
    def mappings():
        frame.select_tab(4)
        pump()
        if not proj.mappings:
            return
        frame.on_preview_mapping_selected(proj.mappings[0].id)
        pump()
        check(proj.active_mapping is proj.mappings[0], "preview mapping set")
        mp = frame.mapping_editor
        check(mp.current_mapping is proj.mappings[0], "mapping editor synced")
        mapping = proj.mappings[0]
        before = dict(mapping.map)
        ids = mp.visible_module_ids()[:3]
        mp.table.set_selected(ids)
        mp._on_table_select()
        mp.apply(None)
        check(all(mapping.map.get(i, "x") is None for i in ids), "hide selected modules")
        mp.apply(proj.modules[-1].id)
        check(all(mapping.map.get(i) == proj.modules[-1].id or i == proj.modules[-1].id for i in ids), "replace selected modules")
        mp.apply(None, reset=True)
        frame.on_undo(None)
        frame.on_undo(None)
        frame.on_undo(None)
        pump()
        check(dict(proj.mappings[0].map) == before, "undo mapping edits")
        mp.chk_changed.SetValue(True)
        mp.refresh_table()
        check(all(i in proj.mappings[0].map for i in mp.visible_module_ids()), "changed-only filter")
        mp.chk_changed.SetValue(False)
        mp.refresh_table()
        frame.select_tab(1)
        pump()
        frame.on_preview_mapping_selected(None)
        check(proj.active_mapping is None, "preview mapping cleared")
        check(mp.current_mapping is None, "mapping editor follows the context bar")

    step("mappings: preview selector sync, hide/replace/reset, undo, filter", mappings)

    def automod():
        import tempfile
        import time

        from ui.frame_render import FrameRenderer
        from ui.module_editor.modularize_dialog import ModularizeDialog

        frame.select_tab(0)
        pump()
        me = frame.module_editor
        asset = next((img for img in proj.images
                      if any(m.image_id == img.id and m.type == "MD_IMAGE" for m in proj.modules)), None)
        check(asset is not None, "an image with modules to modularize")
        if asset is None:
            return
        modules = [m for m in proj.modules if m.image_id == asset.id and m.type == "MD_IMAGE"]

        def wait_plan(dlg):
            for _ in range(1500):
                pump(1)
                if dlg.plan is not None:
                    return dlg.plan
                time.sleep(0.01)
            return None

        dlg = ModularizeDialog(me, proj, asset, modules)
        dlg.Show()
        check(wait_plan(dlg) is not None, "the dialog plans in the background")
        dlg.goal.SetValue(5)
        dlg._settings_changed(delay=1)
        check(dlg.plan is None and not dlg.apply_button.IsEnabled(), "a new setting invalidates the plan")
        plan = wait_plan(dlg)
        check(plan is not None and dlg.apply_button.IsEnabled(), "the new plan arrives and can be applied")
        dlg.view_choice.SetStringSelection("Parts sheet")
        dlg._show_selected(fit=True)
        dlg._closing = True
        dlg.Destroy()
        pump()
        if plan is None:
            return

        def pixels(renderer, fr):
            image, hx, hy = renderer.render(proj, fr, None)
            rgba = image.convert("RGBA")
            data = rgba.tobytes()
            return {(hx + i // 4 % rgba.width, hy + i // 4 // rgba.width): data[i:i + 4]
                    for i in range(0, len(data), 4) if data[i + 3]}

        renderer = FrameRenderer()
        before = {fr.id: pixels(renderer, fr) for fr in proj.frames}
        count = len(proj.modules)
        frame.history_checkpoint()
        folder = tempfile.mkdtemp(prefix="mse_smoke_")
        applied = me.apply_modularize(asset, modules, plan, os.path.join(folder, "parts.png"))
        pump()
        renderer = FrameRenderer()
        changed = [fr.name for fr in proj.frames if fr.id in before and pixels(renderer, fr) != before[fr.id]]
        check(not changed, f"frames look the same after modularizing (changed: {changed[:3]})")
        check(me.sheet_key == applied.image_id, "the parts image is shown")
        check(all(m.image_id != asset.id for m in proj.modules if m.type == "MD_IMAGE"), "the sprites were replaced")
        frame.on_undo(None)
        pump()
        check(len(proj.modules) == count, "undo brings the modules back")
        print("   modularized:", applied.parts, "parts,", applied.rewritten_refs, "frame parts rebuilt")
        import shutil

        shutil.rmtree(folder, ignore_errors=True)

    step("modules: auto modularize (dialog, apply keeps every frame, undo)", automod)

    def dirty():
        frame.history_checkpoint()
        fp_now = project_fingerprint(proj)[0]
        check(isinstance(fp_now, str), "fingerprint")
        frame._update_title()
        print("   title:", frame.GetTitle(), "dirty:", frame.history.is_dirty())

    step("dirty tracking/title", dirty)

    def images_on_disk():
        from ui.canvas import BUDGET
        from ui.components.module_palette import THUMBNAILS
        from ui.frame_render import SHARED

        cleared = []
        caches = (("renderer", SHARED), ("thumbnails", THUMBNAILS), ("budget", BUDGET))
        for name, cache in caches:
            cache.clear = (lambda n=name, original=cache.clear: (cleared.append(n), original()))
        try:
            frame.module_editor.reload_image()
        finally:
            for _name, cache in caches:
                del cache.clear
        check({"renderer", "thumbnails", "budget"} <= set(cleared), f"Reload clears every image cache ({cleared})")
        asset = frame.project.images[0]
        frame._image_stamps[asset.id] = (0, 0)  # as if the file had been different when the editor last looked
        check(frame.check_images_on_disk() == [asset.id], "an image changed on disk is reloaded on activation")
        check(frame.check_images_on_disk() == [], "and only once")

    step("images: Reload and files changed on disk refresh every cache", images_on_disk)

    def check_and_export():
        import tempfile

        from ui.check_dialog import CheckProjectDialog
        from ui.sgdk_export_dialog import ExportReportDialog, MegaDriveExportDialog, has_runtime

        project = frame.project
        anim = next(a for a in project.animations if a.aframes)
        doomed = anim.aframes[0].frame_id
        project.frames = [f for f in project.frames if f.id != doomed]  # deleted, its steps kept as missing
        frame.history_checkpoint()
        dlg = CheckProjectDialog(frame, project, frame._after_fix)
        try:
            issue = next((i for i in dlg.issues if i.code == "missing-step"), None)
            check(issue is not None, "Check Project finds steps whose frame was deleted")
            dlg.list.Select(dlg.issues.index(issue))
            dlg._show_selected()
            check(dlg.btn_fix.IsEnabled(), "and offers a fix")
            dlg.fix_selected()
            check(not any(i.code == "missing-step" and i.target == issue.target for i in dlg.issues), "Fix repairs it")
            check(all(af.frame_id != doomed for af in anim.aframes), "the steps are gone")
        finally:
            dlg.Destroy()
        frame.go_to(("animation", anim.id))
        pump()
        check(frame.book.GetSelection() == 2 and frame.animation_editor.selected_animation_id == anim.id,
              "Go to shows the animation")
        frame.on_undo(None)
        frame.on_undo(None)
        pump()
        check(frame.project.get_frame(doomed) is not None, "undo brings the frame and its steps back")

        folder = tempfile.mkdtemp(prefix="mse_sgdk_")
        try:
            for path, text in (("src/modsprite.c", "/* runtime */"), ("inc/modsprite.h", "/* runtime */"),
                               ("res/resources.res", 'IMAGE TITLE "title.png" BEST\n')):
                os.makedirs(os.path.dirname(os.path.join(folder, path)), exist_ok=True)
                with open(os.path.join(folder, path), "w", encoding="utf-8") as handle:
                    handle.write(text)
            check(has_runtime(folder), "a game folder with the runtime")
            dlg = MegaDriveExportDialog(frame, frame.project, folder, "all")
            check(dlg.values() == (folder, "all"), "the export dialog offers the folder and all mappings")
            dlg.Destroy()
            result = frame.export_sgdk(folder, "all")
            check(result is not None and result.summary["tiles"] > 0, "the Mega Drive export writes the data")
            check(result is not None and all(os.path.exists(path) for path in result.files), "every data file is there")
            with open(os.path.join(folder, "res", "resources.res"), encoding="utf-8") as handle:
                resources = handle.read()
            check("IMAGE TITLE" in resources and "MS_BLOB" in resources, "the game's own resources stay")
            if result is not None:
                ExportReportDialog(frame, folder, result).Destroy()
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    step("check project and the Mega Drive export: find, fix, go to, export into a game folder", check_and_export)

    def recovery():
        import json

        from ui import autosave

        path = frame.current_path
        anim = frame.project.animations[0]
        original_name = anim.name
        anim.name = original_name + " (autosave test)"
        frame.autosave_now()
        copy = frame._recovery_file
        check(bool(copy) and os.path.exists(copy), "unsaved changes get a recovery copy")
        check(not autosave.stale_recoveries(), "a running editor's copy is not offered")
        dead_pid = next(pid for pid in (999_983, 888_887, 777_773) if not autosave.process_alive(pid))
        with open(copy, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["pid"] = dead_pid  # the editor that wrote it is gone: it crashed
        with open(copy, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        stale = autosave.stale_recoveries()
        check(len(stale) == 1 and stale[0].project_path == os.path.abspath(path), "a crashed editor's copy is offered")
        anim.name = original_name
        frame._ask_recovery = lambda recovery: "restore"
        try:
            restored = frame.offer_recovery()
        finally:
            del frame._ask_recovery
        pump()
        check(restored and frame.project.animations[0].name == original_name + " (autosave test)",
              "Restore brings back the autosaved changes")
        check(frame.history.is_dirty() and frame.current_path == path, "restored changes are unsaved, in their file")
        frame.load_project(path)  # discards the restored changes
        pump()
        check(not os.path.exists(copy), "the copy goes once the changes are discarded")
        decoy = autosave.recovery_file_for(None, "decoy")
        autosave.write_recovery(decoy, frame.project, None)
        with open(decoy, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["pid"] = dead_pid
        with open(decoy, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        frame._ask_recovery = lambda recovery: "discard"
        try:
            check(not frame.offer_recovery() and not os.path.exists(decoy), "Discard deletes the copy")
        finally:
            del frame._ask_recovery

    step("autosave: a recovery copy while unsaved, offered after a crash, restore / discard", recovery)

    def laptop_ui():
        """Milestone 4: bars wrap instead of cutting controls off, inspector sections fold, the step comes first,
        the welcome screen, sheet-to-animation shortcuts, points by a click, window memory."""
        from ui.components.inspector_kit import Section
        from ui.welcome import example_paths

        project = frame.project
        old_size = frame.GetSize()
        frame.SetSize((1100, 760))
        pump(4)
        for index, panel in enumerate(frame.panels[:4]):
            frame.select_tab(index)
            pump(4)
            bar = panel.canvas_controls
            area = bar.GetClientRect()
            cut = [w for w in bar.GetChildren() if w.IsShown() and not area.Contains(w.GetRect())]
            check(not cut, f"{app_mod.TAB_NAMES[index]}: every view bar control is on screen at 1100 px ({len(cut)} cut)")
        frame.SetSize(old_size)
        pump(2)

        # Inspector sections fold away (remembered in the preferences file) and the step section comes first
        ae = frame.animation_editor
        frame.select_tab(2)
        anim = next((a for a in project.animations if len(a.aframes) > 1), None)
        if anim is not None:
            ae.select_animation(anim.id)
            ae.select_steps([1])
            pump(2)
            inspector = ae.inspector
            order = [item.GetWindow() for item in inspector.GetSizer().GetChildren()]
            check(order.index(inspector.step_panel) < order.index(inspector.anim_panel),
                  "the selected step's section comes first")
            section = inspector.anim_panel
            check(isinstance(section, Section) and not section.folded, "the Animation section is open")
            section.set_folded(True)
            check(not section.body.IsShown() and wx.Config.Get().ReadBool(section.key, False), "folded, and remembered")
            section.set_folded(False)
            check(section.body.IsShown(), "and open again")

        # The welcome screen takes the tabs' place and gives them back
        frame.show_welcome()
        pump(2)
        check(frame.welcome.IsShown() and not frame.book.IsShown(), "the welcome screen shows instead of the tabs")
        frame.show_welcome(False)
        pump(2)
        check(frame.book.IsShown() and not frame.welcome.IsShown(), "back to the tabs")
        if os.path.isdir(os.path.join(repo, "examples")) and not getattr(sys, "frozen", False):
            check(len(example_paths()) == 3, "the three examples are found from source")

        # A row of modules becomes frames and an animation (Modules tab), library frames become an animation
        me = frame.module_editor
        frame.select_tab(0)
        mods = [m for m in project.modules if m.type == "MD_IMAGE"][:3]
        me.select_modules([m.id for m in mods])
        frames_before, anims_before = len(project.frames), len(project.animations)
        me.new_animation_from_modules()
        pump(2)
        made = ae.animation()
        check(len(project.frames) == frames_before + 3 and made is not None and len(made.aframes) == 3
              and frame.book.GetSelection() == 2, "New animation from 3 modules: 3 frames, an animation, shown")
        frame.on_undo(None)
        pump()
        check(len(frame.project.animations) == anims_before, "one undo takes it all back")
        ids = [f.id for f in frame.project.frames[:4]]
        ae.library.palette.selected_ids = ids
        ae.new_animation_from_frames(ids)
        check(ae.animation() is not None and [af.frame_id for af in ae.animation().aframes] == ids,
              "New animation from 4 library frames, in order")
        frame.on_undo(None)
        pump()

        # A click on empty space makes a point (Points mode)
        fe = frame.frame_editor
        frame.select_tab(1)
        pump()
        if fe.frame() is not None and frame.project.point_types:
            fe.set_mode("points")
            points_before = len(fe.frame().control_points)
            event = wx.MouseEvent(wx.wxEVT_LEFT_DOWN)
            fe.stage.on_point_left_down(event, wx.Point(5, 5))
            if fe.stage.HasCapture():
                fe.stage.ReleaseMouse()
            check(len(fe.frame().control_points) == points_before + 1, "a click on empty space makes a point")
            frame.on_undo(None) if frame.history.is_dirty() else None
            fe.set_mode("parts")

        # The window opens where it was, at a size that fits the screen it is on (CI screens are small)
        area = wx.Display(max(0, wx.Display.GetFromWindow(frame))).GetClientArea()
        size = (max(800, min(1000, area.width - 40)), max(560, min(700, area.height - 40)))
        frame.SetSize(area.x + 20, area.y + 20, *size)
        frame._save_geometry()
        frame.SetSize((800, 560))
        frame._restore_geometry()
        check(tuple(frame.GetSize()) == size, f"the window keeps its size ({tuple(frame.GetSize())}, saved {size})")
        frame.SetSize(old_size)
        pump()

    step("laptop UI: wrapping view bars, folding sections, welcome screen, sheet to animation, points, window", laptop_ui)

    def close():
        frame.Close(True)

    step("close", close)
    wx.CallAfter(a.ExitMainLoop)


wx.CallLater(800, run)
a.MainLoop()
print("\n==== RESULT:", "PASS" if not errors else f"{len(errors)} problem(s)")
for e in errors:
    print(e)
sys.exit(1 if errors else 0)
