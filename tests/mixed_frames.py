"""Projects whose console exports store some frames whole and keep the others as parts (Frame.store_whole), shared by
the runtime, budget and bake tests."""

from pathlib import Path
from typing import List, Sequence

from PIL import Image

import palettes
from models import AFrame, Animation, FModule, Frame, ImageAsset, Module, Palette, Project

ROOT = Path(__file__).resolve().parents[1]
POP = ROOT / "examples" / "pop" / "PoP_WW.json"
TURNS = ("A01 turn", "A17 crouched turn", "A18 crouched turn_s")  # steps mirrored; the guard's mapping changes them
MIRRORING = TURNS + ("C21 multi stab throw enemy",)


def pop_mixed(animations: Sequence[str] = MIRRORING, every: int = 7) -> Project:
    """PoP with the frames of ``animations`` stored whole (by default every animation that mirrors steps) and every
    ``every``-th other frame (0: none); 50 frames by default. The SNES's 512 tiles hold the turns' 9 (every=0)."""
    project = Project.from_json(str(POP))
    whole = {af.frame_id for anim in project.animations if anim.name in animations for af in anim.aframes}
    for index, frame in enumerate(project.frames):
        frame.store_whole = frame.id in whole or bool(every and index % every == 0)
    return project


def _sheet(path: Path, size, colours) -> None:
    """A picture with holes and a pattern, so every flip and turn shows."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    for y in range(size[1]):
        for x in range(size[0]):
            if (x * 7 + y * 3) % 5 and (x + 2 * y) % 11:
                image.putpixel((x, y), colours[(x // 2 + y) % len(colours)] + (255,))
    image.save(path)


def nested_project(folder: Path) -> Project:
    """Two palettes (a warm and a cool sheet); a frame stored whole of both, nested in a frame of parts as it is,
    mirrored each way and turned; a frame stored whole that nests parts and a whole frame; a frame of parts nesting
    those two levels deep; and an animation that moves, mirrors and turns them, including a step turned 90°."""
    project = Project()
    project.palettes = [Palette("warm", "Warm"), Palette("cool", "Cool")]
    sheets = (("warm.png", (29, 23), "warm", [(200, 60, 40), (240, 160, 60), (120, 40, 20), (250, 220, 120)]),
              ("cool.png", (21, 26), "cool", [(40, 80, 210), (60, 200, 220), (20, 40, 120), (160, 200, 250)]))
    for index, (name, size, palette, colours) in enumerate(sheets):
        _sheet(folder / name, size, colours)
        project.images.append(ImageAsset(f"img{index}", str(folder / name), size[0], size[1], palette_id=palette))
    project.modules += [
        Module("m0", "warm big", "img0", (0, 0, 13, 11), (3, 4)),
        Module("m1", "cool tall", "img1", (0, 0, 10, 14), (5, 2)),
        Module("m2", "warm wide", "img0", (2, 9, 27, 14), (0, 0)),
        Module("m3", "cool small", "img1", (11, 15, 7, 5), (2, 2)),
        Module("m4", "cool square", "img1", (3, 3, 18, 18), (9, 9)),
    ]
    for palette in project.palettes:
        palettes.add_missing_colours(project, palette)

    def frame(frame_id: str, parts: List[FModule], whole: bool) -> Frame:
        made = Frame(id=frame_id, name=frame_id, fmodules=parts, store_whole=whole)
        project.frames.append(made)
        return made

    def part(part_id: str, ref: str, x: int, y: int, kind: str = "module", flip_x: bool = False, flip_y: bool = False,
             rotation: float = 0.0) -> FModule:
        return FModule(part_id, kind, ref, (x, y), flip_x=flip_x, flip_y=flip_y, rotation_degrees=rotation)

    frame("both", [part("a", "m0", 0, 0), part("b", "m1", 6, 3, flip_x=True), part("c", "m2", -20, 5, rotation=90),
                   part("d", "m3", 10, -8, flip_y=True), part("e", "m4", 4, 14)], True)
    frame("plain", [part("a", "m0", 0, 0), part("b", "m1", 9, 1)], False)
    frame("nests", [part("a", "m3", -10, -10), part("b", "both", 30, 4, "frame"),
                    part("c", "both", -30, 20, "frame", flip_x=True), part("d", "both", 0, 40, "frame", rotation=90),
                    part("e", "both", 40, 40, "frame", flip_x=True, flip_y=True, rotation=270),
                    part("f", "m0", 5, 5)], False)
    frame("whole of parts", [part("a", "plain", 0, 0, "frame"), part("b", "both", 12, 6, "frame", flip_y=True),
                             part("c", "m1", -4, 2)], True)
    frame("deep", [part("a", "nests", 5, -3, "frame", flip_x=True), part("b", "whole of parts", -40, 0, "frame",
                                                                          rotation=180)], False)
    anim = Animation(id="anim", name="moves", fps=10)
    anim.aframes = [AFrame("both", 2), AFrame("both", 2, (5, -7), flip_x=True), AFrame("both", 2, rotation_degrees=90),
                    AFrame("nests", 2, flip_y=True), AFrame("whole of parts", 2, (3, 3), flip_x=True,
                                                            rotation_degrees=180),
                    AFrame("deep", 2, (-6, 4)), AFrame("whole of parts", 2, rotation_degrees=270)]
    project.animations.append(anim)
    return project
