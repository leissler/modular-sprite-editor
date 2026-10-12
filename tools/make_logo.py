"""Draw the product logo as pixel art: the wooden mannequin over a pixel wordmark.

The logo is drawn at one image pixel per art pixel and only ever scaled by whole numbers with nearest-neighbour
sampling. The emblem is the app icon's mannequin (tools/make_app_icon.py MANNEQUIN: a figure built from parts joined
at pivots, leaping on its stand); the wordmark uses a bold 7-pixel font drawn here, in the mannequin's lightest wood
tone, over a rule with a wooden ball joint. The logo uses no example art.

Writes website/docs/assets/images/logo-title.png (the landing page shows it at 2x) and, with --card, the
product card for the Bionic Productions catalog: the logo on #101010, the background of the catalog's pixel-art cards,
so the card's letterbox bars are invisible.

Usage (from the repository root):
    python3 tools/make_logo.py [--card ../Web/bionic-site/public/assets/modular-sprite-editor-logo.png]
"""

import os
import sys
from typing import List

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import make_app_icon as icon  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE = os.path.join(REPO, "website", "docs", "assets", "images", "logo-title.png")

WORDMARK = icon.PALETTE["4"]
RULE = (92, 78, 64, 255)
CARD_BACKGROUND = (16, 16, 16, 255)
CARD_SIZE = (1280, 640)
CARD_SCALE = 5

# A bold 7-pixel font: two-pixel stems, one-pixel bars, like an 8x8 console font
GLYPHS = {
    "A": ["..XXX..", ".XX.XX.", "XX...XX", "XXXXXXX", "XX...XX", "XX...XX", "XX...XX"],
    "D": ["XXXXX..", "XX..XX.", "XX...XX", "XX...XX", "XX...XX", "XX..XX.", "XXXXX.."],
    "E": ["XXXXXXX", "XX.....", "XX.....", "XXXXX..", "XX.....", "XX.....", "XXXXXXX"],
    "I": ["XXXXXX", "..XX..", "..XX..", "..XX..", "..XX..", "..XX..", "XXXXXX"],
    "L": ["XX.....", "XX.....", "XX.....", "XX.....", "XX.....", "XX.....", "XXXXXXX"],
    "M": ["XX...XX", "XXX.XXX", "XXXXXXX", "XX.X.XX", "XX...XX", "XX...XX", "XX...XX"],
    "O": [".XXXXX.", "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX", ".XXXXX."],
    "P": ["XXXXXX.", "XX...XX", "XX...XX", "XXXXXX.", "XX.....", "XX.....", "XX....."],
    "R": ["XXXXXX.", "XX...XX", "XX...XX", "XXXXXX.", "XX.XX..", "XX..XX.", "XX...XX"],
    "S": [".XXXXX.", "XX...XX", "XX.....", ".XXXXX.", ".....XX", "XX...XX", ".XXXXX."],
    "T": ["XXXXXX", "..XX..", "..XX..", "..XX..", "..XX..", "..XX..", "..XX.."],
    "U": ["XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX", ".XXXXX."],
}
LETTER_GAP, WORD_GAP = 1, 4
# One of the mannequin's ball joints, between the two rules under the wordmark
ORNAMENT = [".342.", "34431", "33321", "22211", ".211."]


def pixels(rows: List[str]) -> Image.Image:
    image = Image.new("RGBA", (len(rows[0]), len(rows)))
    image.putdata([icon.PALETTE[ch] for row in rows for ch in row])
    return image


def wordmark(text: str = "MODULAR SPRITE EDITOR") -> Image.Image:
    width = sum(WORD_GAP if c == " " else len(GLYPHS[c][0]) + LETTER_GAP for c in text) - LETTER_GAP
    image = Image.new("RGBA", (width, 7), (0, 0, 0, 0))
    x = 0
    for c in text:
        if c == " ":
            x += WORD_GAP
            continue
        for y, row in enumerate(GLYPHS[c]):
            for dx, cell in enumerate(row):
                if cell == "X":
                    image.putpixel((x + dx, y), WORDMARK)
        x += len(GLYPHS[c][0]) + LETTER_GAP
    return image


def lockup() -> Image.Image:
    """The mannequin, the wordmark and the rule with its ornament, one image pixel per art pixel. The stand's base sits
    on the centre line, so the leaning figure looks grounded rather than pushed aside."""
    mark, words, ornament = pixels(icon.MANNEQUIN), wordmark(), pixels(ORNAMENT)
    base = [x for x, ch in enumerate(icon.MANNEQUIN[-1]) if ch != "."]
    base_centre = (base[0] + base[-1]) // 2
    gap_mark, gap_rule = 8, 6
    width = words.width
    height = mark.height + gap_mark + words.height + gap_rule + ornament.height
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    image.alpha_composite(mark, (width // 2 - base_centre, 0))
    y = mark.height + gap_mark
    image.alpha_composite(words, (0, y))
    y += words.height + gap_rule
    cx = width // 2
    image.alpha_composite(ornament, (cx - ornament.width // 2, y))
    rule_y = y + ornament.height // 2
    lines = ImageDraw.Draw(image)
    lines.line((10, rule_y, cx - ornament.width // 2 - 4, rule_y), fill=RULE)
    lines.line((cx + ornament.width // 2 + 4, rule_y, width - 11, rule_y), fill=RULE)
    return image


def scaled(image: Image.Image, scale: int) -> Image.Image:
    return image.resize((image.width * scale, image.height * scale), Image.NEAREST)


def card(path: str) -> None:
    logo = scaled(lockup(), CARD_SCALE)
    image = Image.new("RGBA", CARD_SIZE, CARD_BACKGROUND)
    image.alpha_composite(logo, ((CARD_SIZE[0] - logo.width) // 2, (CARD_SIZE[1] - logo.height) // 2))
    image.convert("RGB").save(path, optimize=True)
    print(f"{path}: {image.width}x{image.height}")


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--card":
        card(sys.argv[2])
        return
    os.makedirs(os.path.dirname(TITLE), exist_ok=True)
    image = lockup()
    image.save(TITLE, optimize=True)
    print(f"{os.path.relpath(TITLE, REPO)}: {image.width}x{image.height}")


if __name__ == "__main__":
    main()
