"""Render the product card for the Bionic Productions catalog (bionic-productions.com).

The Swordfight's clash (the Prince's slash meets the guard's block), drawn by the editor's renderer, over a pixel
wordmark: the same build as the catalog's Story Engine card (pixel art and wordmark on #101010, so the card's
letterbox bars are invisible). Art and letters share one pixel size.

Usage (from the repository root):
    python3 website/scripts/make_catalog_card.py ../Web/bionic-site/public/assets/modular-sprite-editor-card.png
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402

import make_site_art as art  # noqa: E402
from models import Project  # noqa: E402

SIZE = (1280, 640)
BACKGROUND = (16, 16, 16, 255)
WORDMARK = (237, 248, 255, 255)
RULE = (52, 60, 70, 255)
ORNAMENT = (105, 230, 255, 255)
ART_SCALE = 6
TEXT_SCALE = 6

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
# A module's selection box with its pivot: the ornament under the wordmark
ORNAMENT_ROWS = ["XX.X.XX", "X.....X", "...X...", "X.XXX.X", "...X...", "X.....X", "XX.X.XX"]
LETTER_GAP, WORD_GAP = 1, 4


def text_image(text: str, colour) -> Image.Image:
    """`text` in the pixel font, one image pixel per font pixel."""
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
                    image.putpixel((x + dx, y), colour)
        x += len(GLYPHS[c][0]) + LETTER_GAP
    return image


def pixels(rows, colour) -> Image.Image:
    image = Image.new("RGBA", (len(rows[0]), len(rows)), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            if cell == "X":
                image.putpixel((x, y), colour)
    return image


def scaled(image: Image.Image, scale: int) -> Image.Image:
    return image.resize((image.width * scale, image.height * scale), Image.NEAREST)


def main() -> None:
    out = Path(sys.argv[1])
    frame = int(sys.argv[2]) if len(sys.argv) > 2 else 23
    project = Project.from_json(str(REPO / "examples" / "sgdk" / "PoP_WW.json"))
    scene = next(s for s in project.timeline_scenes if s.name == "Swordfight")

    fight = art.scene_image(project, scene, frame, (-120, -80, 120, 20), 1, background=(0, 0, 0, 0))
    fight = scaled(fight.crop(fight.getbbox()), ART_SCALE)
    wordmark = scaled(text_image("MODULAR SPRITE EDITOR", WORDMARK), TEXT_SCALE)
    ornament = scaled(pixels(ORNAMENT_ROWS, ORNAMENT), 4)

    gap_art, gap_rule = 64, 40
    height = fight.height + gap_art + wordmark.height + gap_rule + ornament.height
    top = (SIZE[1] - height) // 2
    card = Image.new("RGBA", SIZE, BACKGROUND)
    card.alpha_composite(fight, ((SIZE[0] - fight.width) // 2, top))
    y = top + fight.height + gap_art
    card.alpha_composite(wordmark, ((SIZE[0] - wordmark.width) // 2, y))
    y += wordmark.height + gap_rule
    cx = SIZE[0] // 2
    card.alpha_composite(ornament, (cx - ornament.width // 2, y))
    rule_y = y + ornament.height // 2 - 2
    reach = wordmark.width // 2 - 60
    lines = ImageDraw.Draw(card)
    lines.rectangle((cx - reach, rule_y, cx - ornament.width // 2 - 20, rule_y + 3), fill=RULE)
    lines.rectangle((cx + ornament.width // 2 + 20, rule_y, cx + reach, rule_y + 3), fill=RULE)
    card.convert("RGB").save(out, optimize=True)
    print(f"{out}: {card.width}x{card.height}, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
