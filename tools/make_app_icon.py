"""Draw the app icon as pixel art and write every icon file the builds and the website use.

The icon is an artist's wooden mannequin leaping on its stand: a figure built from parts joined at pivots, posed
into any position, which is what a modular sprite is. The logo's mannequin (MANNEQUIN, also used by tools/make_logo.py)
is drawn on a 128x128 tile for 128 px and up. Below that its limbs are a pixel or two thin and the figure stops
reading, so the small sizes show an M built from the same wooden parts instead: limbs joined by ball joints, in the
same wood and light, hand-drawn on a 32x32 and a 16x16 tile (M_32, M_16). Every size is a whole-number scaling of one
of the three drawings with nearest-neighbour sampling, so every size keeps square pixels.

Writes assets/icon_source.png (1024 px), assets/icon.png (256 px, the window icon), assets/icon.ico,
assets/icon.iconset + assets/icon.icns (macOS, needs iconutil), and for the website logo.svg (the header's 32 px M),
favicon.ico (16, 32 and 48 px), favicon-16.png / favicon-32.png and favicon.png (the 32 px one again, in place of the
theme's own).

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

# 32x32 and 16x16: an M of the mannequin's wooden limbs, over the tile ('.' keeps the tile). Ball joints sit at the
# M's three bends, lit like the mannequin from the top left, each leaving a crevice on the limbs it sits in front of.
M_32 = [  # five-pixel legs, seven-pixel balls
    "................................",
    "................................",
    "................................",
    "................................",
    ".......332............332.......",
    "......34432..........34432......",
    ".....3443221........3443221.....",
    ".....3332211........3332211.....",
    ".....2322211........2322211.....",
    "......221110........022111......",
    "......0111021......4301110......",
    "......2000121......4320001......",
    "......23321221....43223321......",
    "......233212221..432123321......",
    "......233212221..432123321......",
    "......23321222000021123321......",
    "......23321.20333201.23321......",
    "......23321.03443210.23321......",
    "......23321..343221..23321......",
    "......23321..232211..23321......",
    "......23321..222111..23321......",
    "......23321...1111...23321......",
    "......23321..........23321......",
    "......23321..........23321......",
    "......23321..........23321......",
    "......23321..........23321......",
    "......22211..........22211......",
    ".......111............111.......",
    "................................",
    "................................",
    "................................",
    "................................",
]
assert len(M_32) == 32 and all(len(row) == 32 for row in M_32)

M_16 = [  # two-pixel limbs, the joints as caps and a ball
    "................",
    "................",
    "................",
    "...332....332...",
    "...342....342...",
    "...221....221...",
    "...0021..3100...",
    "...31.2131.31...",
    "...31.3432.31...",
    "...31.2321.31...",
    "...31..11..31...",
    "...31......31...",
    "...21......21...",
    "................",
    "................",
    "................",
]
assert len(M_16) == 16 and all(len(row) == 16 for row in M_16)


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
    paste(grid, M_32, 0, 0)
    return grid


def icon_16() -> List[List[str]]:
    grid = tile(16)
    paste(grid, M_16, 0, 0)
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

    docs = os.path.join(REPO, "website", "docs")
    images = os.path.join(docs, "assets", "images")
    write_svg(grid, os.path.join(images, "logo.svg"))
    # A browser shrinks a favicon larger than its tab with smoothing, so each size a tab shows is here as drawn: the
    # pages link the PNGs (website/mkdocs.yml, website/overrides/main.html), the site's root favicon.ico has them all.
    favicon_sizes = [48, 32, 16]
    favicons = [sized(size) for size in favicon_sizes]
    favicons[0].save(os.path.join(docs, "favicon.ico"), format="ICO", sizes=[(size, size) for size in favicon_sizes],
                     append_images=favicons[1:])
    for size in (16, 32):
        sized(size).save(os.path.join(images, f"favicon-{size}.png"))
    # Material copies a favicon.png of its own (a book) to this path unless the docs have one. No page links it any
    # more: ours keeps the theme's out of the site, and old links to it get the M.
    sized(32).save(os.path.join(images, "favicon.png"))
    print("Wrote assets/icon_source.png, icon.png, icon.ico, icon.iconset, icon.icns and the website logo and favicons")


if __name__ == "__main__":
    main()
