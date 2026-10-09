"""Check that the RetroAnimator export places every pixel where the editor canvas draws it.

Renders each frame (and every animation step variant: offset / flip / rotation) with the editor's
own AnimationCanvas into an offscreen bitmap, composites the exported parts at their handles, and
compares the sets of opaque pixels. Needs wxPython (no window is shown).

Usage:
    python3 tools/check_export_parity.py PROJECT_JSON [...]
Exit code 1 if any frame differs.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from typing import Dict, List, Optional, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import wx  # noqa: E402
from PIL import Image  # noqa: E402

from models import Frame, Project  # noqa: E402
from ui.canvas import AnimationCanvas  # noqa: E402

BACKGROUND = (1, 254, 3)
Pixels = Set[Tuple[int, int]]


def canvas_pixels(
    canvas: AnimationCanvas,
    frame: Frame,
    offset: Tuple[float, float] = (0.0, 0.0),
    flip_x: bool = False,
    flip_y: bool = False,
    rotation: float = 0.0,
) -> Pixels:
    with canvas.frame_transform(frame, offset, flip_x, flip_y, rotation):
        corners: List[Tuple[float, float]] = []
        for fm in frame.fmodules:
            x0, y0, x1, y1 = canvas._fmodule_bounds(fm)
            corners.append(canvas.local_to_world((x0, y0)))
            corners.append(canvas.local_to_world((x1, y1)))
        if not corners:
            return set()
        ox = int(math.floor(min(c[0] for c in corners))) - 2
        oy = int(math.floor(min(c[1] for c in corners))) - 2
        width = int(math.ceil(max(c[0] for c in corners))) - ox + 4
        height = int(math.ceil(max(c[1] for c in corners))) - oy + 4

        bitmap = wx.Bitmap(width, height, 24)
        dc = wx.MemoryDC(bitmap)
        dc.SetBackground(wx.Brush(wx.Colour(*BACKGROUND)))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        gc.SetAntialiasMode(wx.ANTIALIAS_NONE)
        gc.SetInterpolationQuality(wx.INTERPOLATION_NONE)
        # Map world pixels 1:1 onto the bitmap, with (ox, oy) at the top-left.
        canvas.world_to_screen = lambda pt: (pt[0] - ox, pt[1] - oy)  # type: ignore[assignment]
        try:
            for fm in frame.fmodules:
                canvas._draw_fmodule_content(gc, fm)
        finally:
            del canvas.world_to_screen
        del gc
        dc.SelectObject(wx.NullBitmap)

    image = bitmap.ConvertToImage()
    data = image.GetData()
    out: Pixels = set()
    for y in range(height):
        row = y * width * 3
        for x in range(width):
            i = row + x * 3
            if (data[i], data[i + 1], data[i + 2]) != BACKGROUND:
                out.add((x + ox, y + oy))
    return out


def export_pixels(export_dir: str, payload: Dict) -> Pixels:
    out: Pixels = set()
    for sprite in payload.get("Sprites", []):
        rel = str(sprite["FramePath"]).replace("\\", os.sep)
        with Image.open(os.path.join(export_dir, rel)) as part:
            part = part.convert("RGBA")
            if sprite.get("XFlip"):
                part = part.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            alpha = part.getchannel("A")
            hx, hy = int(sprite["HandleX"]), int(sprite["HandleY"])
            w, h = part.size
            px = alpha.load()
            for y in range(h):
                for x in range(w):
                    if px[x, y]:
                        out.add((hx + x, hy + y))
    return out


def check_project(path: str, canvas_parent: wx.Window) -> Tuple[int, int, List[str]]:
    project = Project.from_json(path)
    canvas = AnimationCanvas(canvas_parent, project)
    canvas.show_transparency = True
    problems: List[str] = []
    checked = 0
    shape_ids = {m.id for m in project.modules if m.type != "MD_IMAGE"}

    with tempfile.TemporaryDirectory() as tmp:
        out_json = os.path.join(tmp, "export.json")
        project.to_retro_animator_json(out_json)
        with open(out_json, "r", encoding="utf-8") as f:
            exported = json.load(f)
        frames = exported["Frames"]

        def compare(label: str, frame: Frame, payload_name: str, **transform) -> None:
            nonlocal checked
            if any(fm.ref_type == "module" and fm.ref_id in shape_ids for fm in frame.fmodules):
                return  # vector shapes are rasterised differently by wx and PIL
            expected = canvas_pixels(canvas, frame, **transform)
            actual = export_pixels(tmp, frames[payload_name])
            checked += 1
            if expected != actual:
                missing = len(expected - actual)
                extra = len(actual - expected)
                problems.append(f"{label}: {missing} pixel(s) missing, {extra} extra")

        # Base frames are exported in project order under unique names.
        names = list(frames.keys())
        for frame, name in zip(project.frames, names):
            compare(f"frame '{frame.name}'", frame, name)

        for anim, anim_name in zip(project.animations, exported["Animations"].keys()):
            steps = exported["Animations"][anim_name]["FrameData"]
            aframes = [af for af in anim.aframes if project.get_frame(af.frame_id)]
            for idx, (af, step) in enumerate(zip(aframes, steps)):
                frame = project.get_frame(af.frame_id)
                compare(
                    f"animation '{anim.name}' step {idx + 1}",
                    frame,
                    step["FrameID"],
                    offset=(float(af.offset[0]), float(af.offset[1])),
                    flip_x=bool(af.flip_x),
                    flip_y=bool(af.flip_y),
                    rotation=float(getattr(af, "rotation_degrees", 0.0)),
                )

    canvas.Destroy()
    return checked, len(problems), problems


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    app = wx.App(False)
    parent = wx.Frame(None)
    failed = False
    for path in argv:
        checked, bad, problems = check_project(os.path.abspath(path), parent)
        status = "OK" if not bad else "MISMATCH"
        print(f"{status:9s} {os.path.basename(path)}: {checked} frame(s) compared, {bad} differ")
        for line in problems[:15]:
            print("    -", line)
        failed |= bool(bad)
    parent.Destroy()
    app.Destroy()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
