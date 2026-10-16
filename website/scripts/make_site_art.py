"""Render the website's pixel art from the PoP example with the editor's own renderer.

Writes to docs/assets/images/art/:
- swordfight.webp: the Swordfight scene, looping, for the landing page
- step-modules.png, step-frame.png, step-animation.png, step-scene.png: one picture per step of the workflow
- mapping-pair.png: the same pose without and with the "Normal" mapping
- attack.gif: the Prince's attack as the editor's Export GIF... writes it (one cycle, 1x)

Pixel art is scaled by whole numbers only; the page shows it with image-rendering: pixelated.

Usage (from the repository root):
    python3 website/scripts/make_site_art.py
"""

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "website" / "docs" / "assets" / "images" / "art"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from PIL import Image, ImageDraw  # noqa: E402

import compositor  # noqa: E402
import make_readme_banner as banner  # noqa: E402
from models import Project, state_shows  # noqa: E402
from ui.frame_geometry import part_bounds  # noqa: E402
from ui.scene_editor import ops  # noqa: E402

STAGE = (22, 24, 28, 255)  # the landing page's canvas colour
PART_BOUNDS = (90, 210, 255, 150)
MODULE_OUTLINE = (150, 152, 160, 150)


def place(art: Image.Image, hx: int, hy: int, size, origin, scale: int, canvas: Image.Image) -> None:
    sprite = art.resize((art.width * scale, art.height * scale), Image.NEAREST)
    canvas.alpha_composite(sprite, (origin[0] + hx * scale, origin[1] + hy * scale))


def scene_image(project: Project, scene, frame: int, crop, scale: int, background=STAGE) -> Image.Image:
    """The scene at `frame`, the area `crop` = (x0, y0, x1, y1) in scene pixels, scaled."""
    x0, y0, x1, y1 = crop
    canvas = Image.new("RGBA", ((x1 - x0) * scale, (y1 - y0) * scale), background)
    states = ops.evaluate_states(project, scene, ops.time_of(frame, scene.fps))
    cache: dict = {}
    for obj, _depth, _kids in ops.tree_rows(scene, set()):
        state = states.get(obj.id)
        source = project.get_frame(state.get("frame_id")) if state and state.get("frame_id") else None
        if not source or not state_shows(state):
            continue
        a, _b, _c, _d, tx, ty = ops.world_matrix(scene, states, obj.id, cache)
        art, hx, hy = banner.render(project, source, scene.object_mapping(project, obj.id, None), flip_x=a < 0,
                                    offset=(tx, ty), swap=scene.object_palette_swap(project, obj.id, None))
        place(art, hx, hy, None, (-x0 * scale, -y0 * scale), scale, canvas)
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    project = Project.from_json(str(REPO / "examples" / "pop" / "PoP_WW.json"))
    frames = {f.name.strip(): f for f in project.frames}
    normal = next(m for m in project.mappings if m.name == "Normal")
    scene = next(s for s in project.timeline_scenes if s.name == "Swordfight")

    # The Swordfight, looping (the scene's own 10 fps), 2x: the page shows it at its own size
    crop, scale = (-92, -62, 118, 6), 2
    shots = [scene_image(project, scene, f, crop, scale) for f in range(ops.scene_length_frames(scene))]
    shots[0].save(OUT / "swordfight.webp", save_all=True, append_images=shots[1:], duration=100, loop=0,
                  lossless=True, method=6)

    # Step pictures, 4x on a transparent background
    scale = 4
    pose = frames["stand attack01_arthur"]

    # 1 Modules: the pose's parts, loose, each with its outline
    seen = []
    for fm in pose.fmodules:
        if fm.ref_type == "module" and fm.ref_id not in seen:
            seen.append(fm.ref_id)
    modules = sorted((project.get_module(i) for i in seen), key=lambda m: -m.rect[3])
    columns, gap = 5, 3
    rows = [modules[i:i + columns] for i in range(0, len(modules), columns)]
    cell_w = max(m.rect[2] for m in modules) + gap
    heights = [max(m.rect[3] for m in r) + gap for r in rows]
    image = Image.new("RGBA", ((columns * cell_w + gap) * scale, (sum(heights) + gap) * scale), (0, 0, 0, 0))
    lines = ImageDraw.Draw(image)
    y = gap
    for r, row_h in zip(rows, heights):
        x = gap
        for module in r:
            art = compositor.load_module_rgba(project, module, banner._images, banner._modules)
            ox = x + (cell_w - gap - module.rect[2]) // 2
            oy = y + (row_h - gap - module.rect[3]) // 2
            image.alpha_composite(art.resize((art.width * scale, art.height * scale), Image.NEAREST), (ox * scale, oy * scale))
            lines.rectangle((ox * scale - 2, oy * scale - 2, (ox + module.rect[2]) * scale + 1, (oy + module.rect[3]) * scale + 1),
                            outline=MODULE_OUTLINE, width=2)
            x += cell_w
        y += row_h
    image.save(OUT / "step-modules.png", optimize=True)

    # 2 Frame: the pose with its part bounds
    art, hx, hy = banner.render(project, pose, None)
    pad = 3
    image = Image.new("RGBA", ((art.width + 2 * pad) * scale, (art.height + 2 * pad) * scale), (0, 0, 0, 0))
    origin = ((pad - hx) * scale, (pad - hy) * scale)
    place(art, hx, hy, None, origin, scale, image)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    lines = ImageDraw.Draw(overlay)
    for fm in pose.fmodules:
        bx0, by0, bx1, by1 = part_bounds(project, fm, None)
        lines.rectangle((origin[0] + math.floor(bx0) * scale, origin[1] + math.floor(by0) * scale,
                         origin[0] + math.ceil(bx1) * scale - 1, origin[1] + math.ceil(by1) * scale - 1), outline=PART_BOUNDS, width=2)
    image.alpha_composite(overlay)
    image.save(OUT / "step-frame.png", optimize=True)

    # 3 Animation: a slash over the previous step (onion skin)
    slash = next(a for a in project.animations if a.name.strip() == "C06 slash")
    parts = []
    for af, ghost in ((slash.aframes[0], True), (slash.aframes[1], False)):
        art, hx, hy = banner.render(project, project.get_frame(af.frame_id), None, offset=(float(af.offset[0]), float(af.offset[1])))
        parts.append((banner.tint(art, banner.GHOST_PREVIOUS) if ghost else art, hx, hy))
    x0 = min(hx for _a, hx, _y in parts) - pad
    y0 = min(hy for _a, _x, hy in parts) - pad
    x1 = max(hx + a.width for a, hx, _y in parts) + pad
    y1 = max(hy + a.height for a, _x, hy in parts) + pad
    image = Image.new("RGBA", ((x1 - x0) * scale, (y1 - y0) * scale), (0, 0, 0, 0))
    for art, hx, hy in parts:
        place(art, hx, hy, None, (-x0 * scale, -y0 * scale), scale, image)
    image.save(OUT / "step-animation.png", optimize=True)

    # 4 Scene: the guard blocks the Prince's slash
    scene_image(project, scene, 23, (-62, -50, 40, 4), scale, background=(0, 0, 0, 0)).save(OUT / "step-scene.png", optimize=True)

    # Mappings: the same pose, original and with "Normal"
    images = []
    for mapping in (None, normal):
        art, hx, hy = banner.render(project, pose, mapping)
        images.append((art, hx, hy))
    x0 = min(hx for _a, hx, _y in images) - pad
    y0 = min(hy for _a, _x, hy in images) - pad
    w = max(hx + a.width for a, hx, _y in images) + pad - x0
    h = max(hy + a.height for a, _x, hy in images) + pad - y0
    image = Image.new("RGBA", ((2 * w + 6) * scale, h * scale), (0, 0, 0, 0))
    for index, (art, hx, hy) in enumerate(images):
        place(art, hx, hy, None, ((index * (w + 6) - x0) * scale, -y0 * scale), scale, image)
    image.save(OUT / "mapping-pair.png", optimize=True)

    # Export GIF: exactly the file the Animations tab writes
    from ui.animation_editor.render import export_gif

    attack = next(a for a in project.animations if a.name.strip() == "C34 Attack")
    export_gif(project, attack, str(OUT / "attack.gif"), None)

    for path in sorted(OUT.iterdir()):
        with Image.open(path) as im:
            print(f"{path.relative_to(REPO)}: {im.width}x{im.height}, {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
