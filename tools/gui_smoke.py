"""GUI smoke test: drive the real main window programmatically against a project.

Opens a window (needs a display), exercises every tab (view commands, geometry edits,
copy/paste, nudging, onion skin, playback, filters, global undo/redo, mapping sync) and
exits non-zero on any exception or failed check. Nothing is saved.

Usage:
    python3 tools/gui_smoke.py [PROJECT_JSON]     (default: examples/sgdk/PoP_WW.json)
"""
import os
import sys
import traceback

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(repo, "examples", "sgdk", "PoP_WW.json")
sys.path.insert(0, repo)
os.chdir(repo)

import wx  # noqa: E402

# Auto-answer modal dialogs.
wx.MessageBox = lambda *a, **k: wx.YES  # type: ignore[assignment]

import app as app_mod  # noqa: E402
from ui.project_history import project_fingerprint  # noqa: E402

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


def step(name, fn):
    try:
        fn()
        pump()
        print("ok  ", name)
    except Exception:
        errors.append(name + "\n" + traceback.format_exc())
        print("FAIL", name)
        traceback.print_exc()


def run():
    proj = None

    def load():
        nonlocal proj
        frame.load_project(project_path)
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
        frame.select_tab(0)
        pump()
        img = proj.images[0]
        me.select_image(img.id)
        mod = next(m for m in proj.modules if m.image_id == img.id)
        me.select_module(mod.id, center_view=True)
        pump()
        check(me.spin_rect_w.GetValue() == mod.rect[2], "rect width shown")
        before = tuple(mod.rect)
        frame.history_checkpoint()
        me.spin_rect_x.SetValue(before[0] + 3)
        me.on_geometry_spin(wx.CommandEvent())
        check(tuple(mod.rect)[0] == before[0] + 3, "spin edits module rect")
        frame.on_undo(None)
        pump()
        restored = proj.get_module(mod.id)
        check(tuple(restored.rect) == before, f"undo restores rect {restored.rect} vs {before}")
        frame.on_redo(None)
        pump()
        check(proj.get_module(mod.id).rect[0] == before[0] + 3, "redo reapplies rect")
        frame.on_undo(None)
        me.module_filter.SetValue(mod.name[:3])
        pump()
        check(len(me._modules_view) >= 1, "module filter keeps matches")
        me.module_filter.SetValue("")

    step("modules: geometry spins + undo/redo + filter", modules)

    # ---- Frames
    fe = frame.frame_editor

    def frames():
        frame.select_tab(1)
        pump()
        target = next(f for f in proj.frames if f.fmodules)
        fe.select_frame_by_id(target.id)
        pump()
        check(fe.canvas.frame is target, "frame shown on canvas")
        fe.edit_select_all()
        check(len(fe.canvas.selected_fmodules) == len(target.fmodules), "select all parts")
        pos_before = [fm.position for fm in target.fmodules]
        fe._nudge_selection(1, 0)
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
        check(fe.canvas.frame is restored, "canvas re-bound to restored frame")
        frame.on_undo(None)
        pump()
        check([fm.position for fm in proj.get_frame(target.id).fmodules] == pos_before, "undo nudge")
        n_frames = len(proj.frames)
        fe.duplicate_selected_frame()
        check(len(proj.frames) == n_frames + 1, "duplicate frame")
        dup = proj.get_frame(fe.selected_frame_id)
        check(dup.id != target.id and all(fm.id not in {x.id for x in target.fmodules} for fm in dup.fmodules), "fresh ids")
        fe.on_delete_frame(None)
        check(len(proj.frames) == n_frames, "delete frame")
        for mode in ("collision", "point", "module"):
            fe.set_edit_mode(mode)
            pump()
        fe.onion_choice.SetSelection(3)
        fe.on_onion_changed(None)
        pump()
        fe.canvas.Refresh()
        fe.canvas.Update()
        fe.frame_filter.SetValue("stand")
        pump()
        check(all("stand" in f.name.lower() for f in fe._frame_view), "frame filter")
        fe.frame_filter.SetValue("")
        fe._toggle_flip("x")
        fe._rotate_selected(90)
        frame.on_undo(None)
        frame.on_undo(None)

    step("frames: select/nudge/copy/paste/undo/dup/delete/modes/onion/filter", frames)

    # ---- Animations
    ae = frame.animation_editor

    def animations():
        import tempfile
        from ui.animation_editor import ops as aops
        from ui.animation_editor.render import export_gif

        frame.select_tab(2)
        pump(5)
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
            getattr(widget, handler)(evt)
            pump(1)

        frame.select_tab(2)
        anim = max(proj.animations, key=lambda a: len(a.aframes))
        ae.select_animation(anim.id)
        ae.sequence.tick_w = 40.0
        ae.sequence.set_scroll(0)
        pump()
        sq = ae.sequence
        y = 28 + 30  # inside the cells row

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
        te.screen_choice.SetSelection(1)
        te._on_screen_choice(None)
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

    # ---- Mappings
    def mappings():
        frame.select_tab(4)
        pump()
        if not proj.mappings:
            return
        frame.on_preview_mapping_selected(proj.mappings[0].id)
        pump()
        check(proj.active_mapping is proj.mappings[0], "preview mapping set")
        check(frame.mapping_editor.current_mapping is proj.mappings[0], "mapping editor synced")
        frame.select_tab(1)
        pump()
        frame.on_preview_mapping_selected(None)
        check(proj.active_mapping is None, "preview mapping cleared")

    step("mappings: global preview selector sync", mappings)

    def dirty():
        frame.history_checkpoint()
        fp_now = project_fingerprint(proj)[0]
        check(isinstance(fp_now, str), "fingerprint")
        frame._update_title()
        print("   title:", frame.GetTitle(), "dirty:", frame.history.is_dirty())

    step("dirty tracking/title", dirty)

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
