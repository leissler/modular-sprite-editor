"""Capture the editor screenshots the website shows, from the example projects (macOS, needs the screen).

Opens the real editor, puts each tab into a state worth showing and saves the window, a dialog or a part of the
window with `screencapture` (2x on a Retina display) to docs/assets/images/screens/. It also walks through the first
lesson on the Adventurer sheet in a new project (screens/lesson-*.png and art/lesson-run.gif, the GIF the editor
exports). Uses throwaway preferences and restores the recent files list; nothing is saved to the projects.

Usage (from the repository root):
    python3 website/scripts/capture_screenshots.py [NAME ...]

NAME is a shot name (for example `hitboxes`) or a group: `welcome`, `pop`, `sonic`, `lesson`, `automod`, `check`.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "website" / "docs" / "assets" / "images" / "screens"
ART = REPO / "website" / "docs" / "assets" / "images" / "art"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)

prefs_dir = tempfile.mkdtemp(prefix="mse_capture_")
os.environ["MSE_PREFERENCES_FILE"] = os.path.join(prefs_dir, "preferences.ini")

import wx  # noqa: E402

wx.MessageBox = lambda *a, **k: wx.YES  # type: ignore[assignment]

import app as app_mod  # noqa: E402
from ui.animation_editor.render import export_gif  # noqa: E402
from ui.module_editor import dialogs as module_dialogs  # noqa: E402

WINDOW = (1440, 900)
POP = REPO / "examples" / "sgdk" / "PoP_WW.json"
SONIC = REPO / "examples" / "sonic" / "sonic.json"
ADVENTURER = REPO / "examples" / "adventurer" / "adventurer_sprite_sheet_v1.1.png"
GROUPS = {"welcome", "pop", "sonic", "lesson", "automod", "check"}
only = set(sys.argv[1:])
errors = []

app = app_mod.SpriteEditorApp(False)
app.SetAssertMode(wx.APP_ASSERT_EXCEPTION)
frame = app.GetTopWindow()
frame.confirm_discard_changes = lambda: True
saved_recent = list(frame.recent_files)


def pump(seconds: float = 0.4) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wx.SafeYield()
        time.sleep(0.02)


def trim_right(name: str, margin: int = 24) -> None:
    """Cut the empty right end of a wide strip (the sequence of a short animation): the last column whose middle band
    differs from the background, plus a margin."""
    from PIL import Image

    path = OUT / f"{name}.png"
    image = Image.open(path).convert("RGB")
    band = image.crop((0, image.height // 3, image.width, image.height * 2 // 3))
    background = band.getpixel((band.width - 2, band.height // 2))
    last = max((x for x in range(band.width)
                if any(sum(abs(a - b) for a, b in zip(band.getpixel((x, y)), background)) > 24 for y in range(0, band.height, 3))),
               default=band.width - 1)
    image.crop((0, 0, min(image.width, last + margin), image.height)).quantize(
        256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)


def window_number(window: wx.Window) -> int:
    """The macOS window number of a top-level window, for `screencapture -l`."""
    import ctypes
    import ctypes.util

    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = objc.objc_msgSend
    send.restype = ctypes.c_void_p
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    ns_window = send(ctypes.c_void_p(window.GetHandle()), objc.sel_registerName(b"window"))
    send.restype = ctypes.c_long
    return int(send(ctypes.c_void_p(ns_window), objc.sel_registerName(b"windowNumber")))


def capture(name: str, rect: wx.Rect, window=None) -> None:
    """Save the screen rectangle `rect` of a window (the editor's unless given). The window alone is captured and then
    cut, so other programs' windows in front of it never end up in a picture."""
    from PIL import Image

    window = window or frame
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    subprocess.run(["screencapture", "-x", "-o", "-l", str(window_number(window)), str(path)], check=True)
    image = Image.open(path).convert("RGBA")  # the window's rounded corners stay transparent
    outer = window.GetScreenRect()
    scale = image.width / outer.width
    box = (rect.x - outer.x, rect.y - outer.y, rect.Right + 1 - outer.x, rect.Bottom + 1 - outer.y)
    image = image.crop(tuple(int(round(v * scale)) for v in box))
    # 256 colours are enough for the editor's flat UI and the pixel art, at a fraction of the size; the last one is
    # kept for the transparent corners of a whole window.
    quantized = image.convert("RGB").quantize(255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] < 128:
        colours = quantized.getpalette() or []
        quantized.putpalette(colours[:765] + [0] * (768 - len(colours[:765])))  # index 255 exists
        quantized.paste(255, mask=alpha.point(lambda a: 255 if a < 128 else 0))
        quantized.save(path, optimize=True, transparency=255)
    else:
        quantized.save(path, optimize=True)
    print("captured", path.relative_to(REPO), f"{image.width}x{image.height}", f"{path.stat().st_size // 1024} KB")


def shoot(name: str, window=None) -> None:
    """The whole window (or dialog)."""
    window = window or frame
    window.Raise()
    pump(0.8)
    capture(name, window.GetScreenRect(), window)


def part(name: str, *widgets: wx.Window, pad: int = 6, top: Optional[wx.Window] = None,
         bottom: Optional[wx.Window] = None, window=None) -> None:
    """The union of the widgets' rectangles, optionally cut to start at `top` and end at `bottom`, plus a margin."""
    (window or frame).Raise()
    pump(0.8)
    rect = widgets[0].GetScreenRect()
    for widget in widgets[1:]:
        rect = rect.Union(widget.GetScreenRect())
    if top is not None:
        y = top.GetScreenRect().y
        rect = wx.Rect(rect.x, y, rect.width, rect.Bottom - y + 1)
    if bottom is not None:
        rect = wx.Rect(rect.x, rect.y, rect.width, bottom.GetScreenRect().Bottom - rect.y + 1)
    rect.Inflate(pad, pad)
    capture(name, rect, window)


def canvas_part(name: str, canvas, box: Tuple[float, float, float, float], pad: int = 16) -> None:
    """A part of a canvas around the world rectangle `box` (x0, y0, x1, y1), clipped to the canvas."""
    frame.Raise()
    pump(0.8)
    (sx0, sy0), (sx1, sy1) = canvas.world_to_screen(box[:2]), canvas.world_to_screen(box[2:])
    p0 = canvas.ClientToScreen(wx.Point(int(sx0) - pad, int(sy0) - pad))
    p1 = canvas.ClientToScreen(wx.Point(int(sx1) + pad, int(sy1) + pad))
    rect = wx.Rect(p0, p1).Intersect(canvas.GetScreenRect())
    capture(name, rect)


def scroll_to(inspector: wx.ScrolledWindow, widget: wx.Window) -> None:
    """Scroll an inspector so that `widget` is near its top (sections below the fold are not on screen)."""
    unit = max(1, inspector.GetScrollPixelsPerUnit()[1])
    y = inspector.CalcUnscrolledPosition(inspector.ScreenToClient(widget.GetScreenPosition())).y
    inspector.Scroll(0, max(0, (y - 12) // unit))
    pump(0.3)


def toggle(checkbox: wx.CheckBox, handler, value: bool = True) -> None:
    checkbox.SetValue(value)
    handler(value)


def wanted(name: str, group: str) -> bool:
    return not only or name in only or group in only


def load(path: Path) -> None:
    frame.load_project(str(path))
    frame.recent_files = saved_recent
    frame._save_recent_files()
    frame.SetSize(WINDOW)
    frame.CentreOnScreen()
    pump()


def frame_named(name: str):
    return next(f for f in frame.project.frames if f.name.strip() == name)


def animation_named(name: str):
    return next(a for a in frame.project.animations if a.name.strip() == name)


def item_box(frame_obj, roles: Sequence[str] = ()) -> Tuple[float, float, float, float]:
    """World bounds of a frame's parts, hitboxes and points, for close-ups."""
    from ui.frame_geometry import part_bounds

    xs, ys = [], []
    for fm in frame_obj.fmodules:
        x0, y0, x1, y1 = part_bounds(frame.project, fm, None)
        xs += [x0, x1]
        ys += [y0, y1]
    for cr in frame_obj.collision_rects:
        x, y, w, h = cr.rect
        xs += [x, x + w]
        ys += [y, y + h]
    return min(xs), min(ys), max(xs), max(ys)


def run_welcome() -> None:
    """The welcome screen as a first start shows it: no recent projects yet, the examples, the guide."""
    if not wanted("welcome", "welcome"):
        return
    frame.recent_files = []
    frame.SetSize(WINDOW)
    frame.CentreOnScreen()
    frame.show_welcome()
    shoot("welcome")
    frame.show_welcome(False)
    frame.recent_files = list(saved_recent)


def run_pop() -> None:
    load(POP)
    proj = frame.project
    pose = frame_named("stand attack01_arthur")
    slash = frame_named("slash3")
    group = "pop"

    # ---------------------------------------------------------------- the window, the tour
    if wanted("tour-top", group):
        frame.select_tab(1)
        pump()
        top = frame.context_bar.GetScreenRect()
        page = frame.frame_editor.GetScreenRect()
        frame.Raise()
        pump(0.8)
        left = top.x + top.width * 34 // 100  # from just before the tabs to the preview mapping on the right
        capture("tour-top", wx.Rect(left, top.y - 4, top.Right + 6 - left, page.y - top.y + 4))

    # ---------------------------------------------------------------- Modules
    me = frame.module_editor
    if wanted("modules", group) or wanted("modules-inspector", group) or wanted("modules-names", group):
        frame.select_tab(0)
        me.select_sheet(proj.images[0].id, fit=True)
        module = proj.get_module(pose.fmodules[3].ref_id)
        me.select_module(module.id)
        me.canvas.set_zoom_level(4)
        x, y, w, h = module.rect
        me.canvas.center_view((x + w / 2 + 40, y + h / 2 + 20))
        if wanted("modules", group):
            shoot("modules")
        if wanted("modules-inspector", group):
            part("modules-inspector", me.inspector, pad=0, bottom=me.inspector.btn_trim)
        if wanted("modules-names", group):
            toggle(me.chk_names, me._on_names)
            toggle(me.chk_pivots, me._on_pivots)
            me.canvas.set_zoom_level(8)
            me.canvas.center_view((212, 48))  # torso, hip and leg parts
            canvas_part("modules-names", me.canvas, (160, 24, 264, 72), pad=0)
            toggle(me.chk_names, me._on_names, False)
            toggle(me.chk_pivots, me._on_pivots, False)

    if wanted("modules-palette", group):
        frame.select_tab(0)
        me.select_sheet(proj.images[0].id)
        me.select_modules([])
        pump()
        part("modules-palette", me.inspector, pad=0, top=me.inspector.palette_choice, bottom=me.inspector.palette_strip)

    # ---------------------------------------------------------------- Frames
    fe = frame.frame_editor
    toggle(fe.chk_points, fe._on_show_points, False)  # the pose itself; hitboxes and points have their own shots
    if any(wanted(n, group) for n in ("frames", "frames-library", "frames-part", "tour-viewbar", "tour-list")):
        frame.select_tab(1)
        fe.set_mode("parts")
        fe.select_frame_by_id(pose.id)
        fe.canvas_controls.chk_part_bounds.SetValue(True)
        fe.canvas.set_show_part_bounds(True)
        fe.canvas.fit_to_content()
        fe.set_selected([pose.fmodules[5].id])
        if wanted("frames", group):
            shoot("frames")
        if wanted("frames-library", group):
            part("frames-library", fe.library, pad=0)
        if wanted("frames-part", group):
            part("frames-part", fe.inspector, pad=0, bottom=fe.inspector.btn_bottom)
        if wanted("tour-viewbar", group):
            part("tour-viewbar", fe.canvas_controls, pad=2)
        if wanted("tour-list", group):
            part("tour-list", fe.browser, pad=0)
        fe.canvas_controls.chk_part_bounds.SetValue(False)
        fe.canvas.set_show_part_bounds(False)

    if wanted("frames-whole", group):
        frame.select_tab(1)
        fe.set_mode("parts")
        fe.select_frame_by_id(pose.id)
        fe.set_selected([])
        part("frames-whole", fe.inspector, pad=0, bottom=fe.inspector.btn_centre)

    if wanted("frames-onion", group):
        frame.select_tab(1)
        fe.set_mode("parts")
        run = animation_named("A05 run")
        fe.select_frame_by_id(run.aframes[2].frame_id)
        pump(0.6)  # selecting a frame fits the stage a moment later; zoom after that
        fe.set_selected([])
        fe.onion_choice.SetSelection(3)  # both neighbours
        fe._update_ghosts()
        fe.canvas.set_zoom_level(6)
        fe.canvas.center_view((4, -13))
        canvas_part("frames-onion", fe.canvas, (-30, -34, 38, 6), pad=0)
        fe.onion_choice.SetSelection(0)
        fe._update_ghosts()

    # ---------------------------------------------------------------- Hitboxes and points
    if wanted("hitboxes", group) or wanted("hitboxes-stage", group):
        frame.select_tab(1)
        fe.select_frame_by_id(slash.id)
        pump(0.6)
        fe.set_mode("hitboxes")
        attack = next(c for c in slash.collision_rects if c.type_id == "attack")
        fe.set_selected([attack.id])
        fe.canvas.set_zoom_level(10)
        fe.canvas.center_view((10, -17))
        if wanted("hitboxes", group):
            shoot("hitboxes")
        if wanted("hitboxes-stage", group):
            canvas_part("hitboxes-stage", fe.canvas, (-14, -42, 34, 6), pad=0)

    if wanted("points", group):
        frame.select_tab(1)
        stab = frame_named("stab3")
        fe.select_frame_by_id(stab.id)
        pump(0.6)
        fe.set_mode("points")
        tip = next(p for p in stab.control_points if p.role == "blade_tip")
        fe.set_selected([tip.id])
        fe.canvas.set_zoom_level(10)
        fe.canvas.center_view((12, -14))
        shoot("points")

    if wanted("hitboxes-types", group):
        frame.select_tab(1)
        fe.select_frame_by_id(slash.id)
        fe.set_mode("hitboxes")
        fe.set_selected([])
        scroll_to(fe.inspector, fe.inspector.types_title)
        part("hitboxes-types", fe.inspector, pad=0, top=fe.inspector.types_title, bottom=fe.inspector.btn_add_type)
    fe.set_mode("parts")

    # ---------------------------------------------------------------- Budget
    if wanted("budget", group) or wanted("budget-readout", group):
        frame.select_tab(1)
        fe.select_frame_by_id(slash.id)
        pump(0.6)
        fe.set_selected([])
        fe.canvas_controls._set_budget("md_h40", persist=False)
        fe.canvas.fit_to_content()
        pump(0.6)
        if wanted("budget", group):
            shoot("budget")
        if wanted("budget-readout", group):
            canvas = fe.canvas
            x, y, w, h = canvas.budget_hud_rect
            origin = canvas.ClientToScreen(wx.Point(int(x) - 4, int(y) - 4))
            capture("budget-readout", wx.Rect(origin.x, origin.y, int(w) + 8, int(h) + 8))
        fe.canvas_controls._set_budget("", persist=False)

    # ---------------------------------------------------------------- Animations
    ae = frame.animation_editor
    if wanted("animations", group) or wanted("anim-sequence", group) or wanted("anim-settings", group):
        frame.select_tab(2)
        attack = animation_named("C34 Attack")
        ae.select_animation(attack.id)
        ae.onion_choice.SetSelection(1)  # previous step
        ae._refresh_stage()
        ae.select_steps([7])
        ae.seek_step(7)
        ae.stage.fit_to_content()
        if wanted("animations", group):
            shoot("animations")
        if wanted("anim-sequence", group):
            ae.sequence.fit()
            part("anim-sequence", ae.sequence_view, pad=0)
            trim_right("anim-sequence")
        if wanted("anim-settings", group):
            ae.select_steps([])
            part("anim-settings", ae.inspector, pad=0, bottom=ae.inspector.next_info)
        ae.onion_choice.SetSelection(0)
        ae._refresh_stage()

    if wanted("anim-path", group):
        frame.select_tab(2)
        jump = animation_named("A24 jump start stand")
        ae.select_animation(jump.id)
        ae.select_steps([4])
        ae.seek_step(4)
        pump(0.6)
        ae.stage.set_zoom_level(6)
        ae.stage.center_view((14, -24))
        canvas_part("anim-path", ae.stage, (-22, -52, 52, 6), pad=0)

    if wanted("anim-events", group) or wanted("hitboxes-animation", group):
        frame.select_tab(2)
        slash_anim = animation_named("C06 slash")
        ae.select_animation(slash_anim.id)
        ae.select_steps([1])
        ae.seek_step(1)
        toggle(ae.chk_collision, ae._on_toggle_collision)
        toggle(ae.chk_points, ae._on_toggle_points)
        ae.stage.set_zoom_level(5)
        ae.stage.center_view((10, -18))
        if wanted("hitboxes-animation", group):
            canvas_part("hitboxes-animation", ae.stage, (-18, -44, 36, 8), pad=0)
        if wanted("anim-events", group):
            ae.stage.set_zoom_level(4)
            ae.stage.center_view((10, -18))
            scroll_to(ae.inspector, ae.inspector.event_name)
            shoot("anim-events")
        toggle(ae.chk_collision, ae._on_toggle_collision, False)
        toggle(ae.chk_points, ae._on_toggle_points, False)

    if wanted("budget-animation", group):
        frame.select_tab(2)
        ae.select_animation(animation_named("C34 Attack").id)
        ae.select_steps([])
        ae.canvas_controls._set_budget("md_h40", persist=False)
        ae.refresh()
        pump()
        scroll_to(ae.inspector, ae.inspector.budget_label)
        part("budget-animation", ae.inspector, pad=0, top=ae.inspector.budget_info, bottom=ae.inspector.budget_info)
        ae.canvas_controls._set_budget("", persist=False)

    # ---------------------------------------------------------------- Timeline
    te = frame.timeline_editor
    scene = next(s for s in proj.timeline_scenes if s.name == "Swordfight")
    guard = next(o for o in scene.objects if o.name == "Guard")
    prince = next(o for o in scene.objects if o.name != "Guard")
    if any(wanted(n, group) for n in ("timeline", "scene-timeline", "scene-mapping", "scene-swap", "budget-lines")):
        frame.select_tab(3)
        te.refresh_scenes(select_id=scene.id)
        te.on_tab_activated()
        te.screen_choice.SetSelection(1)  # Mega Drive 320x224
        te._on_screen_choice(None)
        te.select_object(guard.id)
        te.seek(44)
        pump(1.0)  # the panel fits a newly shown scene once, deferred; zoom after that
        te.stage.set_zoom_level(2)
        te.stage.center_view((0, -56))  # the middle of the 320x224 screen guide
        if wanted("timeline", group):
            shoot("timeline")
        if wanted("scene-timeline", group):
            te.timeline.fit_scene()
            part("scene-timeline", te.timeline_view, pad=0)
        if wanted("scene-mapping", group):
            part("scene-mapping", te.inspector, pad=0, bottom=te.inspector.obj_mapping)
        swap_key = next(k for k in prince.keyframes if round(k.time * scene.fps) == 22)  # the Prince's slash
        if wanted("scene-swap", group):
            te.seek(22)  # the swap settings work on the key under the playhead
            te.set_key_selection({prince.id: {swap_key.id}})
            pump()
            scroll_to(te.inspector, te.inspector.swap_enable)
            part("scene-swap", te.inspector, pad=0, top=te.inspector.swap_enable, bottom=te.inspector.swap_off_y)
        if wanted("budget-lines", group):
            te.set_key_selection({})
            te.select_object(None)
            te.seek(23)
            te.canvas_controls._set_budget("md_h32", persist=False)
            te.stage.set_zoom_level(3)
            te.stage.center_view((0, -30))
            canvas_part("budget-lines", te.stage, (-110, -78, 110, 14), pad=0)
            te.canvas_controls._set_budget("", persist=False)

    if wanted("scene-motion", group) or wanted("scene-path", group):
        from models import TimelineKeyframe, TimelineObject, TimelineScene, generate_id

        demo = TimelineScene(id=generate_id("scene"), name="Motion", fps=10, duration_seconds=3.2, loop=True,
                             background_color=(32, 32, 32))
        runner = TimelineObject(id=generate_id("obj"), name="Prince", source_type="animation",
                                source_id=animation_named("A05 run").id, path_mode="spline")
        runner.keyframes = [
            TimelineKeyframe(id=generate_id("key"), time=0.0, x=-90, y=10, easing="linear"),
            TimelineKeyframe(id=generate_id("key"), time=1.5, x=0, y=-40, easing="back_out"),
            TimelineKeyframe(id=generate_id("key"), time=3.0, x=90, y=10, easing="quad_in_out"),
        ]
        demo.objects.append(runner)
        proj.timeline_scenes.append(demo)
        frame.select_tab(3)
        te.refresh_scenes(select_id=demo.id)
        te.on_tab_activated()
        te.screen_choice.SetSelection(0)
        te._on_screen_choice(None)
        te.select_object(runner.id)
        te.set_key_selection({runner.id: {runner.keyframes[0].id}})
        te.seek(9)
        pump(1.0)
        te.stage.set_zoom_level(3)
        te.stage.center_view((0, -20))
        if wanted("scene-motion", group):
            scroll_to(te.inspector, te.inspector.motion_info)
            part("scene-motion", te.inspector, pad=0, top=te.inspector.motion_info, bottom=te.inspector.reset_handles)
        if wanted("scene-path", group):
            canvas_part("scene-path", te.stage, (-112, -76, 112, 22), pad=0)
        proj.timeline_scenes.remove(demo)
        te.refresh_scenes(select_id=scene.id)

    # ---------------------------------------------------------------- Mappings
    if any(wanted(n, group) for n in ("mappings", "mappings-table", "mapping-chooser")):
        frame.select_tab(4)
        normal = next(m for m in proj.mappings if m.name == "Normal")
        frame.on_preview_mapping_selected(normal.id)
        mp = frame.mapping_editor
        mp.chk_changed.SetValue(True)
        mp.refresh_table()
        mp.table.set_selected(mp.visible_module_ids()[:4])
        mp._on_table_select()
        if wanted("mappings", group):
            shoot("mappings")
        if wanted("mappings-table", group):
            part("mappings-table", mp.table, pad=0)
        if wanted("mapping-chooser", group):
            bar = frame.context_bar.GetScreenRect()
            frame.Raise()
            pump(0.8)
            capture("mapping-chooser", wx.Rect(bar.Right - 300, bar.y - 4, 306, bar.height + 8))
        frame.on_preview_mapping_selected(None)


def run_sonic() -> None:
    group = "sonic"
    if not any(wanted(n, group) for n in ("modules-detect", "example-sonic")):
        return
    load(SONIC)
    me = frame.module_editor
    if wanted("modules-detect", group):
        frame.select_tab(0)
        me.select_sheet(frame.project.images[0].id, fit=True)
        original = module_dialogs.DetectDialog.ShowModal

        def show(dialog):
            dialog.Show()
            dialog.gap.SetValue(2)
            dialog._update()
            shoot("modules-detect", dialog)
            dialog.Hide()
            return wx.ID_CANCEL

        module_dialogs.DetectDialog.ShowModal = show
        try:
            me.detect_sprites()
        finally:
            module_dialogs.DetectDialog.ShowModal = original
    if wanted("example-sonic", group):
        frame.select_tab(2)
        ae = frame.animation_editor
        anim = next(a for a in frame.project.animations if a.name == "Walk")
        ae.select_animation(anim.id)
        ae.select_steps([1])
        ae.seek_step(1)
        ae.stage.fit_to_content()
        shoot("example-sonic")


def run_lesson() -> None:
    """Your first animated sprite, step by step, in a new project."""
    group = "lesson"
    if not any(wanted(n, group) for n in ("lesson-sheet", "lesson-grid", "lesson-sliced", "lesson-row",
                                         "lesson-animation", "lesson-timing", "lesson-onion", "lesson-run")):
        return
    frame.on_new(None)
    frame.SetSize(WINDOW)
    frame.CentreOnScreen()
    pump()
    me = frame.module_editor
    frame.select_tab(0)
    asset = me._import(str(ADVENTURER))
    me.refresh_sheets()
    me.select_sheet(asset.id, fit=True)
    pump()
    if wanted("lesson-sheet", group):
        shoot("lesson-sheet")

    original = module_dialogs.GridSliceDialog.ShowModal

    def show(dialog):
        dialog.Show()
        for key, value in (("tile_w", 32), ("tile_h", 32)):
            dialog.spins[key].SetValue(value)
        dialog.skip_empty.SetValue(True)
        dialog._update()
        if wanted("lesson-grid", group):
            shoot("lesson-grid", dialog)
        dialog.Hide()
        return wx.ID_OK

    module_dialogs.GridSliceDialog.ShowModal = show
    try:
        me.grid_slice()
    finally:
        module_dialogs.GridSliceDialog.ShowModal = original
    modules = sorted((m for m in frame.project.modules if m.image_id == asset.id), key=lambda m: (m.rect[1], m.rect[0]))
    run_modules = [m for m in modules if m.rect[1] == 32]
    me.select_module(run_modules[0].id)
    pump()
    if wanted("lesson-sliced", group):
        shoot("lesson-sliced")

    # The run's row selected (a click, then Cmd+drag over the rest), then New animation in the inspector
    me.select_modules([m.id for m in run_modules])
    pump()
    if wanted("lesson-row", group):
        shoot("lesson-row")
    me.new_animation_from_modules()
    pump()
    ae = frame.animation_editor
    anim = ae.animation()
    anim.name, anim.fps = "run", 12
    ae.refresh_animations()
    ae.select_animation(anim.id)
    ae.select_steps([3])
    ae.seek_step(3)
    ae.onion_choice.SetSelection(1)  # previous step
    ae._refresh_stage()
    ae.stage.set_zoom_level(8)
    ae.stage.fit_to_content()
    pump()
    if wanted("lesson-animation", group):
        shoot("lesson-animation")
    if wanted("lesson-timing", group):
        ae.select_steps([])
        part("lesson-timing", ae.inspector, pad=0, bottom=ae.inspector.tick_ms)
    if wanted("lesson-onion", group):
        ae.select_steps([3])
        x0, y0, x1, y1 = item_box(frame.project.get_frame(anim.aframes[3].frame_id))
        canvas_part("lesson-onion", ae.stage, (x0 - 2, y0 - 2, x1 + 2, y1 + 2), pad=0)  # the step and its ghost
    ae.onion_choice.SetSelection(0)
    ae._refresh_stage()
    if wanted("lesson-run", group):
        ART.mkdir(parents=True, exist_ok=True)
        count = export_gif(frame.project, anim, str(ART / "lesson-run.gif"), None)
        print("exported", (ART / "lesson-run.gif").relative_to(REPO), count, "frames")


def run_automod() -> None:
    if not wanted("automod", "automod") and not wanted("automod-sheet", "automod"):
        return
    import automod_bench
    from ui.module_editor.modularize_dialog import ModularizeDialog

    work = Path(tempfile.mkdtemp(prefix="mse_flat_"))
    flat, _originals = automod_bench.flatten(app_mod.Project.from_json(str(SONIC)), work)
    flat.to_json(str(work / "sonic_sheet.json"))
    load(work / "sonic_sheet.json")
    frame.select_tab(0)
    asset = frame.project.images[0]
    modules = [m for m in frame.project.modules if m.image_id == asset.id]
    dialog = ModularizeDialog(frame, frame.project, asset, modules)
    dialog.SetSize((1300, 820))
    dialog.CentreOnScreen()
    dialog.Show()
    for _ in range(1500):
        pump(0.02)
        if dialog.plan is not None:
            break
    pump(0.5)
    if wanted("automod", "automod"):
        shoot("automod", dialog)
    if wanted("automod-sheet", "automod"):
        dialog.view_choice.SetSelection(2)  # Parts sheet
        dialog._show_selected(fit=True)
        pump(0.6)
        shoot("automod-sheet", dialog)
    dialog.Destroy()


def run_check() -> None:
    """The Mega Drive export's report for PoP, then Check Project after a few typical slips."""
    group = "check"
    if not any(wanted(name, group) for name in ("export-report", "check-project")):
        return
    from collections import Counter

    from models import Animation
    from ui.check_dialog import CheckProjectDialog
    from ui.sgdk_export_dialog import ExportReportDialog, short_path

    load(POP)
    proj = frame.project
    if wanted("export-report", group):
        folder = os.path.join(prefs_dir, "swordfight")
        os.makedirs(folder)
        result = frame.export_sgdk(folder, "all")
        dialog = ExportReportDialog(frame, folder, result)
        # a neutral example path instead of the temporary folder
        dialog.lines.SetLabel(dialog.lines.GetLabel().replace(short_path(folder), "~/Games/swordfight"))
        dialog.SetSize((760, 260))
        dialog.CentreOnScreen()
        dialog.Show()
        shoot("export-report", dialog)
        dialog.Destroy()
    if wanted("check-project", group):
        # a frame one animation shows and a module one frame uses are deleted, keeping their uses as missing; one box
        # loses its size; a new animation has no steps yet
        steps = Counter(af.frame_id for anim in proj.animations for af in anim.aframes)
        shown_by = Counter(fid for anim in proj.animations for fid in {af.frame_id for af in anim.aframes})
        doomed_frame = next(f for f in proj.frames if shown_by[f.id] == 1 and steps[f.id] >= 2)
        proj.frames.remove(doomed_frame)
        targets = {t for m in proj.mappings for t in m.map.values() if t}
        uses = Counter(fm.ref_id for f in proj.frames for fm in f.fmodules if fm.ref_type == "module")
        doomed_module = next(m for m in proj.modules if uses[m.id] == 1 and m.id not in targets)
        proj.modules.remove(doomed_module)
        box = next(cr for f in proj.frames for cr in f.collision_rects)
        box.rect = (box.rect[0], box.rect[1], 0, box.rect[3])
        proj.animations.append(Animation("anim_check_shot", "new animation"))
        dialog = CheckProjectDialog(frame, proj, lambda message: None)
        dialog.SetSize((820, 360))
        dialog.CentreOnScreen()
        dialog.Show()
        pump(0.3)
        dialog._wrap_details()
        dialog.Layout()
        shoot("check-project", dialog)
        dialog.Destroy()
    load(POP)  # nothing above is saved


def run() -> None:
    for step in (run_welcome, run_pop, run_sonic, run_lesson, run_automod, run_check):
        try:
            step()
        except Exception:
            import traceback

            traceback.print_exc()
            errors.append(step.__name__)
    frame.recent_files = saved_recent
    frame._save_recent_files()
    wx.CallAfter(lambda: (frame.Close(True), app.ExitMainLoop()))  # Close stops the window's timers (on_close)


wx.CallLater(800, run)
app.MainLoop()
if errors:
    print("failed:", ", ".join(errors))
sys.exit(1 if errors else 0)
