"""Benchmark auto-modularisation on real projects.

Flattens a project the way an artist's sheet looks (every frame rendered to one whole sprite, one module per frame,
packed on one image), runs auto-modularisation on it and reports, next to the flat input and the original project:

- exact: every frame, rendered again, equals the original pixel for pixel (anything else is a bug)
- modules / module px: modules the frames use and their pixel area (the sheet you would keep)
- tiles: unique 8x8 tiles in video memory for the frames (on the Mega Drive as the SGDK exporter bakes them; for
  another console's budget profile, each distinct module image's tiles as its cut counts them)
- sprites: hardware sprites per frame, average / worst (the console's per-frame cost)
- parts: parts per frame, average / worst (CPU cost of drawing and of editing)
- seconds: time the modulariser took

Every row measures the frames alone: the modules they use, without the project's animations, scenes, mappings or
unused modules, so the original project compares with the flattened and the modularised ones.

Usage:
    python3 tools/automod_bench.py PROJECT.json... [--config NAME]... [--console PROFILE]   (configs: see CONFIGS;
    profiles: the budget's, md_h40 by default)
    python3 tools/automod_bench.py examples/sonic/sonic.json examples/adventurer/adventurer.json examples/sgdk/PoP_WW.json
"""
from __future__ import annotations

import argparse
import copy
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "examples" / "sgdk" / "tools"))

from PIL import Image  # noqa: E402

import hardware_budget  # noqa: E402
from models import FModule, Frame, Project, generate_id  # noqa: E402

PixelMap = Dict[Tuple[int, int], bytes]


def _new(**settings: Any) -> Callable[[Project, str, Any], Tuple[bool, str]]:
    def run(project: Project, image_id: str, profile: Any) -> Tuple[bool, str]:
        import modularize
        from ui.frame_render import FrameRenderer

        renderer = FrameRenderer()
        modules = [m for m in project.modules if m.image_id == image_id and m.type == "MD_IMAGE"]
        sprites = {m.id: renderer.module(project, m) for m in modules}
        result = modularize.plan(sprites, modularize.Settings(hardware=profile.hardware, **settings))
        sheet = Path(project.get_image(image_id).file_path).with_name(f"parts_{generate_id('sheet')}.png")
        modularize.apply_plan(project, image_id, [m.id for m in modules], result, str(sheet))
        return True, f"{len(result.parts)} parts"

    return run


# The Auto Modularize dialog's goal stops (sprite_weight), sharing off, and the thorough search.
CONFIGS: Dict[str, Callable[[Project, str, Any], Tuple[bool, str]]] = {
    "fewest-tiles": _new(sprite_weight=0.25),
    "fewer-tiles": _new(sprite_weight=0.5),
    "balanced": _new(sprite_weight=2.0),
    "fewer-sprites": _new(sprite_weight=8.0),
    "fewest-sprites": _new(sprite_weight=16.0),
    "balanced-no-sharing": _new(sprite_weight=2.0, share=False),
    "balanced-thorough": _new(sprite_weight=2.0, window=4),
    "balanced-no-underdraw": _new(sprite_weight=2.0, underdraw=False),
}
DEFAULT_CONFIGS = ["fewer-tiles", "balanced", "fewer-sprites"]


def frame_pixels(renderer: Any, project: Project, frame: Frame) -> PixelMap:
    """Opaque pixels of a frame by position relative to its origin."""
    image, hx, hy = renderer.render(project, frame, None)
    rgba = image.convert("RGBA")
    w = rgba.width
    data = rgba.tobytes()
    out: PixelMap = {}
    for i in range(0, len(data), 4):
        if data[i + 3]:
            p = i // 4
            out[(hx + p % w, hy + p // w)] = data[i:i + 4]
    return out


def flatten(project: Project, workdir: Path) -> Tuple[Project, Dict[str, PixelMap]]:
    """The project's frames as whole sprites: one image with every frame, one module per frame (pivot at the
    frame origin), frames with that one part. Returns the flat project and every frame's pixels."""
    from ui.frame_render import FrameRenderer

    renderer = FrameRenderer()
    renders = []
    for frame in project.frames:
        image, hx, hy = renderer.render(project, frame, None)
        renders.append((frame, image.convert("RGBA"), int(hx), int(hy)))
    # Rows of cells with a 2 px gutter, about square.
    gutter = 2
    area = sum((im.width + gutter) * (im.height + gutter) for _f, im, _x, _y in renders) or 1
    row_w = max(max((im.width for _f, im, _x, _y in renders), default=1) + gutter, int(area ** 0.5 * 1.2))
    x = y = row_h = 0
    places = []
    for _frame, im, _hx, _hy in renders:
        if x and x + im.width > row_w:
            x, y, row_h = 0, y + row_h + gutter, 0
        places.append((x, y))
        x += im.width + gutter
        row_h = max(row_h, im.height)
    sheet = Image.new("RGBA", (max(1, row_w), max(1, y + row_h)), (0, 0, 0, 0))
    for (frame, im, _hx, _hy), (px, py) in zip(renders, places):
        sheet.paste(im, (px, py))
    path = workdir / f"flat_{generate_id('sheet')}.png"
    sheet.save(path)

    flat = Project()
    asset = flat.create_image(str(path), sheet.width, sheet.height)
    originals: Dict[str, PixelMap] = {}
    for (frame, im, hx, hy), (px, py) in zip(renders, places):
        mod = flat.create_module(frame.name or frame.id, asset.id, (px, py, max(1, im.width), max(1, im.height)), (-hx, -hy))
        flat.frames.append(Frame(id=frame.id, name=frame.name, fmodules=[
            FModule(id=generate_id("fm"), ref_type="module", ref_id=mod.id, position=(0, 0))]))
    renderer = FrameRenderer()
    for frame in flat.frames:
        originals[frame.id] = frame_pixels(renderer, flat, frame)
    return flat, originals


def frames_only(project: Project, used: set) -> Project:
    """The project as its frames need it: the modules they use, no animations, scenes or mappings."""
    pruned = copy.deepcopy(project)
    pruned.modules = [m for m in pruned.modules if m.id in used]
    pruned.animations, pruned.timeline_scenes, pruned.mappings = [], [], []
    return pruned


def measure(project: Project, workdir: Path, profile: Any = None) -> Dict[str, Any]:
    import export_sgdk_example as sg

    profile = profile or hardware_budget.MEGA_DRIVE_H40
    used = set()
    parts = []

    def leaf_parts(frame: Frame, depth: int = 0) -> int:
        n = 0
        for fm in frame.fmodules:
            if fm.ref_type == "frame":
                child = project.get_frame(fm.ref_id)
                n += leaf_parts(child, depth + 1) if child and depth < 16 else 0
            else:
                used.add(fm.ref_id)
                n += 1
        return n

    for frame in project.frames:
        parts.append(leaf_parts(frame))
    area = sum(m.rect[2] * m.rect[3] for m in project.modules if m.id in used)
    pruned = frames_only(project, used)
    if profile.vram_tiles:  # the Mega Drive: exactly as the SGDK exporter bakes the frames
        ctx = sg.SGDKBakeContext(pruned, [None], workdir)
        ctx.bake()
        tiles = len(ctx.tile_data) // 32
        sprites = [ctx.render_frame_extent(ctx.render_frames[i])[0] for i in ctx.frame_render_frames]
    else:
        import modularize
        from ui.frame_render import FrameRenderer

        renderer, seen, tiles = FrameRenderer(), set(), 0
        for mod in pruned.modules:
            image = modularize._normalised(renderer.module(pruned, mod))
            box = image.getchannel("A").getbbox()
            digest = modularize._digest(image.crop(box)) if box else None
            if digest and digest not in seen:
                seen.add(digest)
                tiles += modularize.part_tiles(image.crop(box), profile.hardware)[0]
        calc = hardware_budget.BudgetCalculator()
        sprites = [calc.frame_budget(pruned, frame, None, profile).sprite_count for frame in pruned.frames]
    n = max(1, len(project.frames))
    return {
        "modules": len(used), "module_px": area, "tiles": tiles,
        "sprites_avg": sum(sprites) / n, "sprites_max": max(sprites, default=0),
        "parts_avg": sum(parts) / n, "parts_max": max(parts, default=0),
    }


def check_exact(project: Project, originals: Dict[str, PixelMap]) -> List[str]:
    from ui.frame_render import FrameRenderer

    renderer = FrameRenderer()
    bad = []
    for frame in project.frames:
        if frame.id in originals and frame_pixels(renderer, project, frame) != originals[frame.id]:
            bad.append(frame.name or frame.id)
    return bad


def run_config(name: str, flat: Project, originals: Dict[str, PixelMap], workdir: Path,
               profile: Any = None) -> Dict[str, Any]:
    profile = profile or hardware_budget.MEGA_DRIVE_H40
    project = copy.deepcopy(flat)
    image_id = project.images[0].id
    started = time.perf_counter()
    ok, message = CONFIGS[name](project, image_id, profile)
    seconds = time.perf_counter() - started
    if not ok:
        return {"config": name, "error": message, "seconds": seconds}
    result = measure(project, workdir, profile)
    bad = check_exact(project, originals)
    result.update({"config": name, "seconds": seconds, "exact": not bad, "wrong_frames": bad[:5],
                   "wrong_count": len(bad)})
    return result


def format_row(label: str, r: Dict[str, Any]) -> str:
    if "error" in r:
        return f"  {label:22} ERROR {r['error']}"
    exact = "" if "exact" not in r else ("exact" if r["exact"] else f"WRONG {r['wrong_count']} {r['wrong_frames']}")
    secs = f"{r['seconds']:6.1f}s" if "seconds" in r else "       "
    return (f"  {label:22} modules {r['modules']:4}  module px {r['module_px']:7}  tiles {r['tiles']:5}  "
            f"sprites {r['sprites_avg']:5.1f}/{r['sprites_max']:3}  parts {r['parts_avg']:5.1f}/{r['parts_max']:3}  "
            f"{secs}  {exact}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("projects", nargs="+")
    parser.add_argument("--config", action="append", choices=sorted(CONFIGS))
    parser.add_argument("--console", default="md_h40", choices=[p.key for p in hardware_budget.PROFILES],
                        help="the budget profile whose sprites and tiles count (default: md_h40)")
    args = parser.parse_args(argv)
    names = args.config or DEFAULT_CONFIGS
    profile = hardware_budget.profile_by_key(args.console)
    failed = False
    for path in args.projects:
        project = Project.from_json(path)
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            flat, originals = flatten(project, workdir)
            print(f"{Path(path).name}: {len(project.frames)} frames, {profile.name}")
            print(format_row("original project", measure(project, workdir, profile)))
            print(format_row("flat (whole sprites)", measure(flat, workdir, profile)))
            for name in names:
                result = run_config(name, flat, originals, workdir, profile)
                print(format_row(name, result), flush=True)
                failed |= "error" in result or not result.get("exact", False)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
