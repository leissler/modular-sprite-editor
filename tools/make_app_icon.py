"""Draw the app icon as pixel art and write every icon file the builds and the website use.

The icon is an artist's wooden mannequin leaping on its stand: a figure built from parts joined at pivots, posed
into any position, which is what a modular sprite is. It is drawn three times, on a dark tile: the logo's mannequin
(MANNEQUIN, also used by tools/make_logo.py) on a 128x128 tile for the large sizes, and simplified hand-drawn
versions on 32x32 and 16x16 tiles for the small ones. Every size is a whole-number scaling of one of them with
nearest-neighbour sampling, so every size keeps square pixels.

Writes assets/icon_source.png (1024 px), assets/icon.png (256 px, the window icon), assets/icon.ico,
assets/icon.iconset + assets/icon.icns (macOS, needs iconutil) and the website's logo.svg and favicon.png.

Usage:
    python3 tools/make_app_icon.py [--preview OUT.png]
"""

import os
import subprocess
import sys
from typing import Dict, List, Tuple

from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PALETTE: Dict[str, Tuple[int, int, int, int]] = {
    ".": (0, 0, 0, 0),
    "T": (38, 42, 51, 255),     # tile
    "E": (24, 26, 32, 255),     # tile rim
    "0": (118, 92, 66, 255),    # wood: the crevice between two parts
    "1": (168, 138, 104, 255),  # wood, shadow
    "2": (206, 180, 146, 255),  # wood
    "3": (230, 212, 182, 255),  # wood, light
    "4": (250, 240, 220, 255),  # wood, highlight
    "m": (160, 166, 176, 255),  # the stand's metal rod
}

# The mannequin on its own (41x86), lit from the top left; parts in front leave a dark crevice on the parts behind.
# The pose follows a photo of a real mannequin: a backward leap on tiptoe, one arm raised over the thrown-back head.
MANNEQUIN = [  # the far arm and leg are a tone darker
    "....................................2211.",
    "..................................332211.",
    "...............................312221111.",
    ".............................3301211111..",
    "..........................23322201111....",
    "........................13222111100......",
    ".......................210211111.........",
    "......................22110111...........",
    "......................111100..33.........",
    ".....................01110.44433322......",
    ".....................200044443332221.....",
    ".....................220244333322211.....",
    ".....................202333332222111.....",
    ".....................00412222221111......",
    "....................31430222211111.......",
    ".................444313220.11111.........",
    "................4444311110...............",
    "...............444433310000..............",
    "..............34443333200432.............",
    "..............33333322044332.............",
    "..............33333220443321.............",
    "..............33322004432211.............",
    "..............2222044332211..............",
    ".44332........00000233211................",
    "343322113333333314320211.................",
    "33221113333333331332101..................",
    ".11110222222222202211....................",
    ".....111111111111011.....................",
    ".............1110000.....................",
    ".............222111......................",
    "............4421110......................",
    "...........444333222.....................",
    "...........3333322211....................",
    "..........33333222111....................",
    "...........232222111.....................",
    "...........222221111.....................",
    "............0001000......................",
    "............4320432......................",
    "...........333044322.....................",
    "...........222033322.....................",
    "...........011033322.....................",
    "............000333221....................",
    ".............10233222...........333222111",
    "..............1033322.........22211111111",
    "...............0233221......33100000.....",
    "................0332220...3332211111.....",
    "................0333220.3332211111.......",
    ".................233221112211111.........",
    ".................m3322201011111..........",
    ".................m33322010111............",
    ".................m233221001..............",
    ".................m.332210................",
    ".................m.23322.................",
    ".................m..31000................",
    ".................m..04432................",
    ".................m...3322................",
    ".................m...32210...............",
    ".................m...111101..............",
    ".................m....11022..............",
    ".................m....233221.............",
    ".................m.....23222.............",
    ".................m.....233221............",
    ".................m......23322............",
    ".................m.......2322............",
    ".................m.......23322...........",
    ".................m........2322...........",
    ".................m........23322..........",
    ".................m.........2322..........",
    ".................m.........233043........",
    ".................m..........214432.......",
    ".................m...........14432.......",
    ".................m...........04432.......",
    ".................m............33321......",
    ".................m............33321......",
    ".................m.............3321......",
    ".................m.............3221......",
    ".................m.............2221......",
    ".............344444433.........2211......",
    "..........344443333333333.......111......",
    ".........33443333333333332......111......",
    ".........23333333333333331.......11......",
    ".........22223333333331111...............",
    ".........22222222111111111...............",
    ".........12222222111111110...............",
    "..........112222211111100................",
    ".............000000000...................",
]
assert all(len(row) == 41 for row in MANNEQUIN), [len(row) for row in MANNEQUIN]

# 32x32 and 16x16: the same mannequin with fewer pixels, over the tile ('.' keeps the tile).
FIGURE_32 = [  # two-pixel limbs where they fit
    "................................",
    "................................",
    "................................",
    ".....................32.........",
    "...................221..........",
    ".................221............",
    "................21..34..........",
    "................1.34433.........",
    "................1.33322.........",
    "..............3432.221..........",
    ".............34432..............",
    ".......34....34322..............",
    ".......43333123221..............",
    ".......221111.221...............",
    "..............10................",
    ".............3432...221.........",
    ".............2321..21...........",
    "..............m3221.............",
    "..............m32...............",
    "..............m.32..............",
    "..............m.21..............",
    "..............m..32.............",
    "..............m..32.............",
    "..............m...32............",
    "..............m...21............",
    "..............m....32...........",
    "...........3333333.32...........",
    "..........22222111121...........",
    "...........0000000..............",
    "................................",
    "................................",
    "................................",
]
assert len(FIGURE_32) == 32 and all(len(row) == 32 for row in FIGURE_32)

FIGURE_16 = [  # a silhouette: head, arms, legs, rod and base
    "................",
    "................",
    "...........3....",
    ".........22.....",
    "........1.343...",
    ".......342221...",
    "......3432......",
    "..43323321......",
    ".......21.21....",
    ".......322......",
    ".......m32......",
    ".......m.21.....",
    ".....333..3.....",
    "....22211.2.....",
    "................",
    "................",
]
assert len(FIGURE_16) == 16 and all(len(row) == 16 for row in FIGURE_16)


def tile(size: int) -> List[List[str]]:
    """The 16x16 tile: a rounded square with a darker rim, leaving a transparent margin."""
    grid = [["." for _ in range(size)] for _ in range(size)]
    margin = 1
    inset = {0: 1}
    last = size - 1 - margin
    for y in range(margin, last + 1):
        cut = inset.get(min(y - margin, last - y), 0)
        for x in range(margin + cut, last + 1 - cut):
            grid[y][x] = "T"
    _rim(grid)
    return grid


def tile_32() -> List[List[str]]:
    grid = [["." for _ in range(32)] for _ in range(32)]
    inset = {2: 3, 3: 1, 4: 1, 27: 1, 28: 1, 29: 3}  # rounded corners: row -> pixels cut on each side
    for y in range(2, 30):
        cut = inset.get(y, 0)
        for x in range(2 + cut, 30 - cut):
            grid[y][x] = "T"
    _rim(grid)
    return grid


def tile_128() -> List[List[str]]:
    """The 32x32 tile's proportions at 128x128: margin 8, corners of radius 16, a rim 4 pixels wide."""
    def inside(x: int, y: int, inset: int) -> bool:
        lo, hi, r = 8 + inset, 119 - inset, 16 - inset
        cx = min(max(x, lo + r), hi - r)
        cy = min(max(y, lo + r), hi - r)
        return lo <= x <= hi and lo <= y <= hi and (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    return [["E" if inside(x, y, 0) and not inside(x, y, 4) else "T" if inside(x, y, 0) else "." for x in range(128)]
            for y in range(128)]


def _rim(grid: List[List[str]]) -> None:
    """Every tile pixel next to the outside becomes the rim."""
    size = len(grid)
    for y in range(size):
        for x in range(size):
            if grid[y][x] == "T" and any(not (0 <= y + dy < size and 0 <= x + dx < size) or grid[y + dy][x + dx] == "."
                                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                grid[y][x] = "E"


def paste(grid: List[List[str]], art: List[str], ox: int, oy: int) -> None:
    for dy, row in enumerate(art):
        for dx, ch in enumerate(row):
            if ch != ".":
                grid[oy + dy][ox + dx] = ch


def icon_128() -> List[List[str]]:
    grid = tile_128()
    paste(grid, MANNEQUIN, (128 - len(MANNEQUIN[0])) // 2, (128 - len(MANNEQUIN)) // 2)
    return grid


def icon_32() -> List[List[str]]:
    grid = tile_32()
    paste(grid, FIGURE_32, 0, 0)
    return grid


def icon_16() -> List[List[str]]:
    grid = tile(16)
    paste(grid, FIGURE_16, 0, 0)
    return grid


def to_image(grid: List[List[str]], scale: int) -> Image.Image:
    height, width = len(grid), len(grid[0])
    image = Image.new("RGBA", (width, height))
    image.putdata([PALETTE[ch] for row in grid for ch in row])
    return image.resize((width * scale, height * scale), Image.NEAREST)


def write_svg(grid: List[List[str]], path: str) -> None:
    """A drawing as an SVG: one rectangle per horizontal run of a colour, sharp at any size."""
    rects = []
    for y, row in enumerate(grid):
        x = 0
        while x < len(row):
            ch = row[x]
            run = 1
            while x + run < len(row) and row[x + run] == ch:
                run += 1
            if ch != ".":
                r, g, b, _a = PALETTE[ch]
                rects.append(f'<rect x="{x}" y="{y}" width="{run}" height="1" fill="#{r:02x}{g:02x}{b:02x}"/>')
            x += run
    size = len(grid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
                + "".join(rects) + "</svg>\n")


def main() -> None:
    large, grid, small = icon_128(), icon_32(), icon_16()
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        sheet = Image.new("RGBA", (256 + 32 * 8 + 16 * 8 + 48 + 80, 256), (235, 235, 235, 255))
        sheet.alpha_composite(to_image(large, 2), (0, 0))
        sheet.alpha_composite(to_image(grid, 8), (256 + 16, 0))
        sheet.alpha_composite(to_image(small, 8), (256 + 32 * 8 + 32, 0))
        x = 256 + 32 * 8 + 16 * 8 + 48
        for image, y in ((to_image(grid, 2), 0), (to_image(grid, 1), 80), (to_image(small, 2), 130), (to_image(small, 1), 180)):
            sheet.alpha_composite(image, (x, y))
        sheet.save(sys.argv[2])
        return

    def sized(pixels: int) -> Image.Image:
        """An exact size: whole-number scaling of the 128 drawing, else the 32 one, else the 16 one."""
        for drawing, size in ((large, 128), (grid, 32), (small, 16)):
            if pixels % size == 0:
                return to_image(drawing, pixels // size)
        raise ValueError(f"no drawing scales to {pixels} px")

    assets = os.path.join(REPO, "assets")
    sized(1024).save(os.path.join(assets, "icon_source.png"))
    sized(256).save(os.path.join(assets, "icon.png"))
    ico_sizes = [256, 128, 64, 48, 32, 16]
    ico_images = [sized(px) for px in ico_sizes]
    ico_images[0].save(os.path.join(assets, "icon.ico"), format="ICO", sizes=[(px, px) for px in ico_sizes],
                       append_images=ico_images[1:])

    iconset = os.path.join(assets, "icon.iconset")
    os.makedirs(iconset, exist_ok=True)
    for points in (16, 32, 128, 256, 512):
        sized(points).save(os.path.join(iconset, f"icon_{points}x{points}.png"))
        sized(points * 2).save(os.path.join(iconset, f"icon_{points}x{points}@2x.png"))
    if sys.platform == "darwin":
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(assets, "icon.icns")], check=True)
    else:
        print("assets/icon.icns not updated: iconutil needs macOS")

    images = os.path.join(REPO, "website", "docs", "assets", "images")
    write_svg(grid, os.path.join(images, "logo.svg"))
    sized(64).save(os.path.join(images, "favicon.png"))
    print("Wrote assets/icon_source.png, icon.png, icon.ico, icon.iconset, icon.icns and the website logo and favicon")


if __name__ == "__main__":
    main()
