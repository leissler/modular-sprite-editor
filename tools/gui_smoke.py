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
        frame.select_tab(2)
        pump()
        if not proj.animations:
            return
        anim = max(proj.animations, key=lambda a: len(a.aframes))
        ae.refresh_animations(anim.id)
        ae.on_select_animation(None)
        pump()
        check(ae.get_selected_anim() is anim, "animation selected")
        ae.onion_choice.SetSelection(3)
        ae.on_onion_changed(None)
        ae.step(1)
        pump()
        check(len(ae.canvas.ghost_layers) >= 1, "onion ghosts present")
        ae.canvas.Refresh()
        ae.canvas.Update()
        ae.on_play(None)
        pump()
        ae.on_play(None)
        off = anim.aframes[ae.current_index].offset
        ae._nudge_offset(wx.WXK_RIGHT, 1)
        check(anim.aframes[ae.current_index].offset == (off[0] + 1, off[1]), "nudge offset")
        frame.history_checkpoint()
        frame.on_undo(None)
        pump()
        a2 = proj.get_animation(anim.id)
        check(a2.aframes[ae.current_index].offset == off, "undo offset nudge")
        ae.chk_mirror_x.SetValue(True)
        ae.on_toggle_global_flip(None)
        ae.canvas.fit_to_content()
        ae.on_duplicate_animation(None)
        check(any(a.name.endswith("copy") for a in proj.animations), "duplicate animation")
        frame.on_undo(None)
        ae.anim_filter.SetValue(anim.name[:2])
        pump()
        ae.anim_filter.SetValue("")

    step("animations: select/onion/play/nudge/undo/mirror/dup/filter", animations)

    # ---- Timeline
    te = frame.timeline_editor

    def timeline():
        frame.select_tab(3)
        pump()
        if not proj.timeline_scenes:
            te.on_add_scene(None)
        te.refresh_scenes()
        n = len(te.get_selected_scene().objects)
        te.on_add_null_object(None)
        check(len(te.get_selected_scene().objects) == n + 1, "add null")
        frame.on_undo(None)
        pump()
        check(len(te.get_selected_scene().objects) == n, "undo add null")
        te.on_play(None)
        pump(5)
        te.on_play(None)
        te.seek_relative(1.0)
        te.path_mode_choice.SetStringSelection("spline")
        te._update_path_handle_ui_enabled()
        te.on_duplicate_scene(None)
        frame.on_undo(None)

    step("timeline: add/undo null, play toggle, spline rows, dup scene", timeline)

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
