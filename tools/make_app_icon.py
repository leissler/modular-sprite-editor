"""Draw the app icon as pixel art and write every icon file the builds and the website use.

The icon is drawn on a 32x32 pixel grid, with a separate 16x16 drawing for the smallest sizes, and only ever
scaled by whole numbers with nearest-neighbour sampling, so every size keeps square pixels. It shows a small
knight whose helmet is a separate part, selected the way the Modules tab selects a module.

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
    "o": (14, 16, 20, 255),     # outline
    "w": (244, 247, 251, 255),  # highlight
    "1": (199, 209, 220, 255),  # steel, light
    "2": (142, 155, 171, 255),  # steel
    "3": (90, 101, 118, 255),   # steel, dark
    "4": (214, 76, 60, 255),    # red
    "5": (142, 46, 41, 255),    # red, dark
    "6": (232, 181, 77, 255),   # gold
    "7": (240, 180, 140, 255),  # skin
    "8": (30, 34, 42, 255),     # visor
    "b": (110, 76, 54, 255),    # leather
    "c": (63, 198, 255, 255),   # selection (the editor's)
    "p": (255, 90, 79, 255),    # pivot (the editor's)
}

# 32x32: the tile is drawn by code; the knight is pasted on top. "." keeps what is below.
KNIGHT_32 = [  # symmetric about column 8.5
    "........oo........",
    ".......o44o.......",
    ".......o45o.......",
    "......oooooo......",
    "....oo1w1112oo....",
    "...o11w1111222o...",
    "..o111111122223o..",
    "..o888888888888o..",
    "..o111118822233o..",
    "..o111228823333o..",
    "...o1122882333o...",
    "....oo228823oo....",
    "......oooooo......",
    "..................",
    "....oooooooooo....",
    "..o112o4445o233o..",
    "..o123o4455o333o..",
    "...ooo444455ooo...",
    "..o7o44444455o7o..",
    "...oo66666666oo...",
    "....o223oo233o....",
    "....o223oo333o....",
    "...obbbboobbbbo...",
    "...oooooooooooo...",
]
assert all(len(row) == 18 for row in KNIGHT_32), [len(row) for row in KNIGHT_32]


# 16x16: the same knight with fewer pixels, for the smallest icon sizes.
KNIGHT_16 = [  # symmetric about column 4.5
    "....44....",
    "..oooooo..",
    ".o11w122o.",
    ".o888888o.",
    ".o118823o.",
    "..o1883o..",
    "...oooo...",
    "o2o4445o3o",
    "o7o4455o7o",
    ".oo6666oo.",
    "..o2oo3o..",
    "..obo.obo.",
]
assert all(len(row) == 10 for row in KNIGHT_16), [len(row) for row in KNIGHT_16]


def tile(size: int) -> List[List[str]]:
    """The rounded tile with a darker rim, leaving a transparent margin."""
    grid = [["." for _ in range(size)] for _ in range(size)]
    margin = 2 if size == 32 else 1
    inset = {0: 3, 1: 1, 2: 1} if size == 32 else {0: 1}
    last = size - 1 - margin
    for y in range(margin, last + 1):
        cut = inset.get(min(y - margin, last - y), 0)
        for x in range(margin + cut, last + 1 - cut):
            grid[y][x] = "T"
    for y in range(size):  # the rim: every tile pixel next to the outside
        for x in range(size):
            if grid[y][x] == "T" and any(grid[y + dy][x + dx] == "." for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                grid[y][x] = "E"
    return grid


def tile_32() -> List[List[str]]:
    grid = [["." for _ in range(32)] for _ in range(32)]
    inset = {2: 3, 3: 1, 4: 1, 27: 1, 28: 1, 29: 3}  # rounded corners: row -> pixels cut on each side
    for y in range(2, 30):
        cut = inset.get(y, 0)
        for x in range(2 + cut, 30 - cut):
            grid[y][x] = "T"
    for y in range(2, 30):  # the rim: every tile pixel next to the outside
        for x in range(2, 30):
            if grid[y][x] == "T" and any(grid[y + dy][x + dx] == "." for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                grid[y][x] = "E"
    return grid


def paste(grid: List[List[str]], art: List[str], ox: int, oy: int) -> None:
    for dy, row in enumerate(art):
        for dx, ch in enumerate(row):
            if ch != ".":
                grid[oy + dy][ox + dx] = ch


def draw_selection(grid: List[List[str]], x0: int, y0: int, x1: int, y1: int) -> None:
    """The Modules tab's selected module: a cyan frame with square handles in its corners."""
    for x in range(x0, x1 + 1):
        for y in (y0, y1):
            if grid[y][x] in "TE.":
                grid[y][x] = "c"
    for y in range(y0, y1 + 1):
        for x in (x0, x1):
            if grid[y][x] in "TE.":
                grid[y][x] = "c"
    for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        grid[cy][cx] = "w"


def icon_32() -> List[List[str]]:
    grid = tile_32()
    ox, oy = 7, 4
    paste(grid, KNIGHT_32, ox, oy)
    draw_selection(grid, ox + 1, oy + 2, ox + 16, oy + 13)
    grid[oy + 13][ox + 8] = grid[oy + 13][ox + 9] = "p"  # the helmet's pivot, where it sits on the neck
    return grid


def icon_16() -> List[List[str]]:
    grid = tile(16)
    paste(grid, KNIGHT_16, 3, 2)
    for x, y in ((3, 2), (12, 2), (3, 8), (12, 8)):  # the selection's corner handles
        if grid[y][x] in "TE.":
            grid[y][x] = "c"
    return grid


def to_image(grid: List[List[str]], scale: int) -> Image.Image:
    size = len(grid)
    image = Image.new("RGBA", (size, size))
    image.putdata([PALETTE[ch] for row in grid for ch in row])
    return image.resize((size * scale, size * scale), Image.NEAREST)


def write_svg(grid: List[List[str]], path: str) -> None:
    """The 32x32 drawing as an SVG: one rectangle per horizontal run of a colour, sharp at any size."""
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
    grid, small = icon_32(), icon_16()
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        sheet = Image.new("RGBA", (32 * 16 + 16 * 16 + 48 + 80, 32 * 16), (235, 235, 235, 255))
        sheet.alpha_composite(to_image(grid, 16), (0, 0))
        sheet.alpha_composite(to_image(small, 16), (32 * 16 + 16, 0))
        x = 32 * 16 + 16 * 16 + 32
        for image, y in ((to_image(grid, 2), 0), (to_image(grid, 1), 80), (to_image(small, 2), 130), (to_image(small, 1), 180)):
            sheet.alpha_composite(image, (x, y))
        sheet.save(sys.argv[2])
        return

    def sized(pixels: int) -> Image.Image:
        """An exact size: whole-number scaling of the 32 drawing, or of the 16 drawing when only that fits."""
        return to_image(grid, pixels // 32) if pixels % 32 == 0 else to_image(small, pixels // 16)

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
