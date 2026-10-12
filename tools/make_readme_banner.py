"""Render the README banner (assets/readme_banner.png) from the PoP example with the editor's own renderer.

Four small canvases in the editor's colours: modules cut on the sheet, a frame built from them (part bounds),
an animation step over its onion skin, and the Swordfight scene with the guard's mapping. The image is 2x an
880 px README column and the pixel art 2 CSS px per pixel, so it stays sharp on normal and Retina screens.

Usage:
    python3 tools/make_readme_banner.py [OUT.png]
"""

import math
import os
import sys
from typing import Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from models import Frame, ModuleMapping, Project, RetroAnimatorExporter as RA  # noqa: E402
from ui.frame_geometry import part_bounds  # noqa: E402
from ui.scene_editor import ops  # noqa: E402

S = 2  # image pixels per CSS pixel
ART = 2  # CSS pixels per art pixel
PX = S * ART

BG = (30, 31, 34)
CANVAS = (40, 41, 45)
CANVAS_BORDER = (56, 58, 64)
TEXT = (235, 238, 245)
TEXT_DIM = (150, 156, 170)
MODULE_OUTLINE = (150, 152, 160)
PART_BOUNDS = (90, 210, 255)
PIVOT = (255, 90, 80)
GHOST_PREVIOUS = (1.0, 0.55, 0.55, 0.38)  # ui/canvas.py

FONT = "/System/Library/Fonts/SFNS.ttf"
_images: dict = {}
_modules: dict = {}


def font(size: float, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    try:
        f = ImageFont.truetype(FONT, int(size * S))
        f.set_variation_by_name(weight)
        return f
    except OSError:
        return ImageFont.load_default(int(size * S))


def render(project: Project, frame: Frame, mapping: Optional[ModuleMapping], flip_x: bool = False,
           offset: Tuple[float, float] = (0.0, 0.0)) -> Tuple[Image.Image, int, int]:
    """The frame in art pixels and the position of its top-left relative to the origin."""
    a = RA._mat_mul(RA._rotation_matrix(0.0), RA._flip_matrix(flip_x, False))
    image, hx, hy, _ = RA._render_frame_variant(project, frame, mapping, a, offset, _images, _modules)
    return image, hx, hy


def scaled(image: Image.Image) -> Image.Image:
    return image.resize((image.width * PX, image.height * PX), Image.NEAREST)


def tint(image: Image.Image, style: Tuple[float, float, float, float]) -> Image.Image:
    r, g, b, a = image.split()
    return Image.merge("RGBA", (r.point(lambda v: int(v * style[0])), g.point(lambda v: int(v * style[1])),
                                b.point(lambda v: int(v * style[2])), a.point(lambda v: int(v * style[3]))))


def tile(banner: Image.Image, box: Tuple[int, int, int, int], label: str) -> Tuple[int, int, int, int]:
    """Draw an empty canvas with its label; returns the canvas box in image pixels."""
    x0, y0, x1, y1 = (v * S for v in box)
    draw = ImageDraw.Draw(banner)
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=CANVAS, outline=CANVAS_BORDER, width=S // 2 or 1)
    draw.text((x0 + 8 * S, y0 + 6 * S), label, font=font(9.5, "Bold"), fill=TEXT_DIM)
    return x0, y0, x1, y1


def paste_at_origin(banner: Image.Image, art: Image.Image, hx: int, hy: int, origin: Tuple[int, int]) -> None:
    sprite = scaled(art)
    banner.alpha_composite(sprite, (origin[0] + hx * PX, origin[1] + hy * PX))


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "assets", "readme_banner.png")
    project = Project.from_json(os.path.join(REPO, "examples", "sgdk", "PoP_WW.json"))
    frames = {f.name.strip(): f for f in project.frames}

    width, height = 880, 236
    banner = Image.new("RGBA", (width * S, height * S), BG + (255,))
    draw = ImageDraw.Draw(banner)
    draw.text((24 * S, 20 * S), "Modular Sprite Editor", font=font(30, "Semibold"), fill=TEXT)
    draw.text((24 * S, 60 * S), "Cut pixel-art sprites into modules, build frames, animate them and compose scenes "
              "for the Mega Drive and other retro consoles.", font=font(13.5), fill=TEXT_DIM)

    top, bottom = 92, 220
    pose = frames["stand attack01_arthur"]

    # MODULES: the parts of the frame next to it, cut from the sheet (like the module palette)
    x0, y0, x1, y1 = tile(banner, (24, top, 254, bottom), "MODULES")
    overlay = Image.new("RGBA", banner.size, (0, 0, 0, 0))
    lines = ImageDraw.Draw(overlay)
    seen = []
    for fm in pose.fmodules:
        if fm.ref_type == "module" and fm.ref_id not in seen:
            seen.append(fm.ref_id)
    modules = sorted((project.get_module(module_id) for module_id in seen), key=lambda m: -m.rect[3])
    gap, left, right = 6 * S, x0 + 12 * S, x1 - 12 * S
    rows, row, row_width = [], [], 0
    for module in modules:
        w = module.rect[2] * PX
        if row and row_width + gap + w > right - left:
            rows.append(row)
            row, row_width = [], 0
        row.append(module)
        row_width += (gap if row_width else 0) + w
    rows.append(row)
    heights = [max(m.rect[3] for m in r) * PX for r in rows]
    y = y0 + 24 * S + ((y1 - y0 - 30 * S) - sum(heights) - gap * (len(rows) - 1)) // 2
    for r, row_height in zip(rows, heights):
        x = left + (right - left - sum(m.rect[2] * PX for m in r) - gap * (len(r) - 1)) // 2
        for module in r:
            mw, mh = module.rect[2] * PX, module.rect[3] * PX
            my = y + (row_height - mh) // 2
            art = RA._load_module_rgba(project, module, _images, _modules)
            banner.alpha_composite(scaled(art), (x, my))
            lines.rectangle((x - S, my - S, x + mw + S - 1, my + mh + S - 1), outline=MODULE_OUTLINE + (150,), width=S)
            x += mw + gap
        y += row_height + gap
    banner.alpha_composite(overlay)

    # FRAME: the pose built from its modules, every part outlined, the origin marked
    x0, y0, x1, y1 = tile(banner, (268, top, 398, bottom), "FRAME")
    art, hx, hy = render(project, pose, None)
    origin = ((x0 + x1) // 2 - 2 * PX, y1 - 10 * PX)
    paste_at_origin(banner, art, hx, hy, origin)
    overlay = Image.new("RGBA", banner.size, (0, 0, 0, 0))
    lines = ImageDraw.Draw(overlay)
    for fm in pose.fmodules:
        bx0, by0, bx1, by1 = part_bounds(project, fm, None)
        lines.rectangle((origin[0] + math.floor(bx0) * PX, origin[1] + math.floor(by0) * PX,
                         origin[0] + math.ceil(bx1) * PX - 1, origin[1] + math.ceil(by1) * PX - 1),
                        outline=PART_BOUNDS + (150,), width=S)
    banner.alpha_composite(overlay)
    draw.line((origin[0] - 5 * S, origin[1], origin[0] + 5 * S, origin[1]), fill=PIVOT, width=S)
    draw.line((origin[0], origin[1] - 5 * S, origin[0], origin[1] + 5 * S), fill=PIVOT, width=S)

    # ANIMATION: a slash with the previous step as onion skin
    x0, y0, x1, y1 = tile(banner, (412, top, 572, bottom), "ANIMATION")
    slash = next(a for a in project.animations if a.name.strip() == "C06 slash")
    origin = ((x0 + x1) // 2 - 6 * PX, y1 - 10 * PX)
    for af, style in ((slash.aframes[0], GHOST_PREVIOUS), (slash.aframes[1], None)):
        art, hx, hy = render(project, project.get_frame(af.frame_id), None, offset=(float(af.offset[0]), float(af.offset[1])))
        paste_at_origin(banner, tint(art, style) if style else art, hx, hy, origin)

    # SCENE + MAPPING: the Swordfight, the guard drawn from the Prince's animations with "Normal"
    x0, y0, x1, y1 = tile(banner, (586, top, 856, bottom), "SCENE  +  MAPPING")
    scene = next(s for s in project.timeline_scenes if s.name == "Swordfight")
    states = ops.evaluate_states(project, scene, ops.time_of(23, scene.fps))
    origin = ((x0 + x1) // 2 + 6 * PX, y1 - 10 * PX)
    cache: dict = {}
    for obj, _depth, _kids in ops.tree_rows(scene, set()):
        state = states.get(obj.id)
        frame = project.get_frame(state.get("frame_id")) if state and state.get("frame_id") else None
        if not frame:
            continue
        a, b, c, d, tx, ty = ops.world_matrix(scene, states, obj.id, cache)
        art, hx, hy = render(project, frame, scene.object_mapping(project, obj.id, None), flip_x=a < 0, offset=(tx, ty))
        paste_at_origin(banner, art, hx, hy, origin)

    # The steps between the canvases
    for x in (261, 405, 579):
        draw.text((x * S, ((top + bottom) // 2 - 7) * S), "›", font=font(13, "Semibold"), fill=TEXT_DIM, anchor="mt")

    banner.convert("RGB").save(out, optimize=True)
    print(f"{out}: {banner.width}×{banner.height}")


if __name__ == "__main__":
    main()
