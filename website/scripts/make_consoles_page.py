"""Write docs/reference/consoles.md from the editor's console database (consoles.py).

Run it after changing a console entry, from the repository root:
    python3 website/scripts/make_consoles_page.py
"""

import sys
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "website" / "docs" / "reference" / "consoles.md"
sys.path.insert(0, str(REPO))

import consoles  # noqa: E402

INTRO = """# Consoles

Every console draws sprites with its own hardware: a screen size, a number of hardware sprites per screen and per
line, the shapes a sprite can have, and palettes of a few colours. The editor keeps these facts in one place and uses
them for the [budget overlay](../guide/hardware-budget.md), the Timeline's screen guides and the
[palettes](../guide/palettes.md).

The Mega Drive is the first console the editor exports for, and the one its palettes follow. The others are listed
with what the editor already knows about them: their screen guides on the Timeline, and for the SNES the budget
overlay. More consoles will follow.
"""

MODELS = {
    "rgb333": "3 bits a channel: 512 colours",
    "bgr555": "5 bits a channel: 32,768 colours",
    "fixed": "chosen from a fixed set",
}


def size(w: int, h: int) -> str:
    return f"{w}×{h}"


def sprite_sizes(console: consoles.Console) -> str:
    sprites = console.sprites
    if sprites.size_sets:
        sets = []
        for pair in sprites.size_sets:
            sets.append(" and ".join(size(*s) for s in pair))
        return "one set per game: " + "; ".join(sets)
    widths = sorted({w for w, _h in sprites.sizes})
    heights = sorted({h for _w, h in sprites.sizes})
    if len(sprites.sizes) == len(widths) * len(heights) and widths == heights:
        step = widths[0]
        if widths == list(range(step, widths[-1] + 1, step)):
            return f"any multiple of {step} from {size(step, step)} to {size(widths[-1], widths[-1])}"
    return ", ".join(size(*s) for s in sprites.sizes)


def support(console: consoles.Console) -> str:
    parts = []
    if console.exporter:
        parts.append(f"export ({console.exporter})")
    if console.palettes_supported:
        parts.append("palettes")
    if console.budgets:
        parts.append("budget overlay")
    parts.append("screen guide")
    return ", ".join(parts)


def colours(console: consoles.Console) -> str:
    palette = console.palette
    return f"{palette.palettes} × {palette.visible} + transparent"


def section(console: consoles.Console) -> List[str]:
    sprites, palette = console.sprites, console.palette
    rates = " or ".join(f"{hz} Hz" for hz in console.refresh_rates)
    lines = ["", f"## {console.name}", "", f"*{console.full_name}*", ""]
    rows = []
    for mode in console.modes:
        limit = f"{mode.sprites_per_screen} sprites on screen, {mode.sprites_per_line} on a line"
        if mode.sprite_pixels_per_line:
            limit += f", {mode.sprite_pixels_per_line} sprite pixels on a line"
        rows.append(("Screen", f"{size(mode.width, mode.height)}: {limit}"))
    rows.append(("Refresh rate", rates + (" (NTSC, PAL)" if len(console.refresh_rates) > 1 else "")))
    rows.append(("Sprite sizes", sprite_sizes(console)))
    flips = "horizontal and vertical" if sprites.flip_h and sprites.flip_v else "none"
    rows.append(("Sprite flips", flips + " (free: a mirrored part needs no art of its own)" if flips != "none" else flips))
    rows.append(("Sprite rotation", "any angle and scale, through a few shared matrices"
                 if sprites.rotation == "affine" else "none: turns are drawn as their own art"))
    rows.append(("Sprite pixels", f"{sprites.bits_per_pixel} bits: {2 ** sprites.bits_per_pixel} colours, one transparent"))
    if sprites.tiles:
        rows.append(("Sprite tiles", f"{sprites.tiles} tiles of {console.tile_size}×{console.tile_size} pixels"
                     + (f"; {sprites.tiles_note}" if sprites.tiles_note else "")))
    rows.append(("Palettes for sprites", f"{palette.palettes}, of {palette.visible} colours and transparent each"
                 + ("" if not palette.shared_with_backgrounds else ", shared with the backgrounds")))
    model = MODELS.get(palette.colour_model, palette.colour_model)
    if palette.colour_model == "fixed" and palette.fixed_note:
        model += f" ({palette.fixed_note})"
    rows.append(("Colours", model))
    bg_rotation = {"mode7": "one layer turns and scales (Mode 7)", "affine": "layers turn and scale"}
    rows.append(("Background tiles", ("flip horizontally and vertically" if console.backgrounds.flips else "no flips")
                 + (f"; {bg_rotation[console.backgrounds.rotation]}" if console.backgrounds.rotation in bg_rotation else "")))
    if console.vram_note:
        rows.append(("Video memory", console.vram_note))
    if console.budgets:
        rows.append(("Budget overlay", "; ".join(b.name for b in console.budgets)))
    rows.append(("In the editor", support(console)))
    lines += ["| | |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    return lines


def page() -> str:
    lines = [INTRO, "| Console | Screen | Sprites on screen / on a line | Colours for sprites | In the editor |",
             "| --- | --- | --- | --- | --- |"]
    for console in consoles.CONSOLES:
        mode = console.modes[0]
        screens = " or ".join(size(m.width, m.height) for m in console.modes)
        lines.append(f"| {console.name} | {screens} | {mode.sprites_per_screen} / {mode.sprites_per_line} | "
                     f"{colours(console)} | {support(console)} |")
    for console in consoles.CONSOLES:
        lines += section(console)
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.write_text(page(), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
