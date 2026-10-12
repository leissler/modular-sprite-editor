"""Capture the editor screenshots the website shows, from the example projects (macOS, needs the screen).

Opens the real editor, puts each tab into a state worth showing and saves the window with `screencapture`
(2x on a Retina display) to docs/assets/images/screens/. Uses throwaway preferences and restores the recent
files list; nothing is saved to the projects.

Usage (from the repository root):
    python3 website/scripts/capture_screenshots.py [NAME ...]
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "website" / "docs" / "assets" / "images" / "screens"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)

prefs_dir = tempfile.mkdtemp(prefix="mse_capture_")
os.environ["MSE_PREFERENCES_FILE"] = os.path.join(prefs_dir, "preferences.ini")

import wx  # noqa: E402

wx.MessageBox = lambda *a, **k: wx.YES  # type: ignore[assignment]

import app as app_mod  # noqa: E402

WINDOW = (1440, 900)
POP = REPO / "examples" / "sgdk" / "PoP_WW.json"
SONIC = REPO / "examples" / "sonic" / "sonic.json"
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


def shoot(name: str, window=None) -> None:
    window = window or frame
    window.Raise()
    pump(0.8)
    r = window.GetScreenRect()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    subprocess.run(["screencapture", "-x", "-o", "-R", f"{r.x},{r.y},{r.width},{r.height}", str(path)], check=True)
    # 256 colours are enough for the editor's flat UI and the pixel art, at a fraction of the size.
    from PIL import Image

    image = Image.open(path).convert("RGB")
    image.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)
    print("captured", path.relative_to(REPO), f"{path.stat().st_size // 1024} KB")


def wanted(name: str) -> bool:
    return not only or name in only


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


def run() -> None:
    try:
        load(POP)
        proj = frame.project
        pose = frame_named("stand attack01_arthur")

        if wanted("modules"):
            frame.select_tab(0)
            me = frame.module_editor
            me.select_sheet(proj.images[0].id, fit=True)
            module = proj.get_module(pose.fmodules[3].ref_id)
            me.select_module(module.id)
            me.canvas.set_zoom_level(4)
            x, y, w, h = module.rect
            me.canvas.center_view((x + w / 2 + 40, y + h / 2 + 20))
            shoot("modules")

        fe = frame.frame_editor
        if wanted("frames"):
            frame.select_tab(1)
            fe.set_mode("parts")
            fe.select_frame_by_id(pose.id)
            fe.canvas_controls.chk_part_bounds.SetValue(True)
            fe.canvas.set_show_part_bounds(True)
            fe.canvas.fit_to_content()
            fe.set_selected([pose.fmodules[5].id])
            shoot("frames")

        if wanted("budget"):
            frame.select_tab(1)
            fe.select_frame_by_id(frame_named("slash3").id)
            fe.set_selected([])
            fe.canvas_controls.chk_part_bounds.SetValue(False)
            fe.canvas.set_show_part_bounds(False)
            fe.canvas_controls._set_budget("md_h40", persist=False)
            fe.canvas.fit_to_content()
            shoot("budget")
            fe.canvas_controls._set_budget("", persist=False)

        if wanted("animations"):
            frame.select_tab(2)
            ae = frame.animation_editor
            attack = animation_named("C34 Attack")
            ae.select_animation(attack.id)
            ae.onion_choice.SetSelection(1)  # previous step
            ae.select_steps([7])
            ae.seek_step(7)
            ae.stage.fit_to_content()
            shoot("animations")

        if wanted("timeline"):
            frame.select_tab(3)
            te = frame.timeline_editor
            scene = next(s for s in proj.timeline_scenes if s.name == "Swordfight")
            te.refresh_scenes(select_id=scene.id)
            te.on_tab_activated()
            te.screen_choice.SetSelection(1)  # Mega Drive 320x224
            te._on_screen_choice(None)
            te.select_object(next(o for o in scene.objects if o.name == "Guard").id)
            te.seek(44)
            pump(1.0)  # the panel fits a newly shown scene once, deferred; zoom after that
            te.stage.set_zoom_level(2)
            te.stage.center_view((0, -56))  # the middle of the 320x224 screen guide
            shoot("timeline")

        if wanted("mappings"):
            frame.select_tab(4)
            normal = next(m for m in proj.mappings if m.name == "Normal")
            frame.on_preview_mapping_selected(normal.id)
            mp = frame.mapping_editor
            mp.chk_changed.SetValue(True)
            mp.refresh_table()
            mp.table.set_selected(mp.visible_module_ids()[:4])
            mp._on_table_select()
            shoot("mappings")
            frame.on_preview_mapping_selected(None)

        if wanted("automod"):
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
            shoot("automod", dialog)
            dialog.Destroy()
    except Exception:
        import traceback
        traceback.print_exc()
        errors.append(1)
    frame.recent_files = saved_recent
    frame._save_recent_files()
    wx.CallAfter(lambda: (frame.Destroy(), app.ExitMainLoop()))


wx.CallLater(800, run)
app.MainLoop()
sys.exit(1 if errors else 0)
