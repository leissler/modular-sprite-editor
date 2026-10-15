"""The consoles the editor knows: screens, sprite hardware, palettes and limits (wx-free).

One entry per console, the single source for the budget overlay's profiles, the Timeline's screen guides and the
rules of a project's target console (``Project.console`` with its setup, ``Project.console_setup``: one of the
console's budget setups, e.g. the SNES's two sprite sizes; ``target`` resolves the pair). Adding a console is adding an entry; the editor
supports it where the entry says so (budget profiles, palettes, an exporter) and the code behind that exists.

Numbers are for sprites (objects) unless they say otherwise. Sources: the consoles' documentation as collected by
SGDK, fullsnes, nesdev, GBATEK and Pan Docs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

RGB = Tuple[int, int, int]
Size = Tuple[int, int]


@dataclass(frozen=True)
class ScreenMode:
    key: str
    width: int
    height: int
    sprites_per_screen: int
    sprites_per_line: int
    sprite_pixels_per_line: int = 0  # sprite pixels a line can show; 0: only the count per line limits it


@dataclass(frozen=True)
class SpriteHardware:
    bits_per_pixel: int
    sizes: Tuple[Size, ...]  # the shapes a hardware sprite can have (width, height in px)
    size_sets: Tuple[Tuple[Size, ...], ...] = ()  # sizes a game picks for all its sprites at once (SNES, NES, GB)
    flip_h: bool = True
    flip_v: bool = True
    rotation: str = "none"  # "none", or "affine": any angle (and scaling) through a few matrices
    tiles: int = 0  # sprite tiles the hardware can use at once
    tiles_note: str = ""


@dataclass(frozen=True)
class TileHardware:
    """Background tiles."""
    flips: bool  # each tile can be mirrored horizontally and vertically
    rotation: str = "none"  # "none", "mode7" (one rotating, scaling layer) or "affine"


@dataclass(frozen=True)
class PaletteHardware:
    colours: int  # per palette, the transparent one included
    palettes: int  # palettes sprites can use at once
    colour_model: str  # "rgb333" (3 bits a channel), "bgr555" (5 bits a channel) or "fixed" (pick from fixed_colours)
    shared_with_backgrounds: bool
    transparent_index: int = 0
    fixed_colours: Tuple[RGB, ...] = ()
    fixed_note: str = ""

    @property
    def visible(self) -> int:
        """Colours an artist can choose per palette (the transparent index is not one of them)."""
        return self.colours - 1


@dataclass(frozen=True)
class BudgetSetup:
    """A console setup: one screen mode, and for consoles whose games pick their sprite sizes (SNES, NES, Game Boy),
    the size set. A project targets one (``Project.console_setup``); the budget overlay offers each as a profile."""
    key: str
    name: str
    mode: str
    sizes: Tuple[Size, ...] = ()  # one of the console's size sets; (): any of its sizes


@dataclass(frozen=True)
class Console:
    key: str
    name: str  # as menus show it
    short: str  # as the screen guide shows it
    full_name: str
    refresh_rates: Tuple[int, ...]  # Hz: NTSC first, then PAL where there is one
    tile_size: int
    modes: Tuple[ScreenMode, ...]
    sprites: SpriteHardware
    backgrounds: TileHardware
    palette: PaletteHardware
    budgets: Tuple[BudgetSetup, ...] = ()  # profiles the budget overlay offers
    palettes_supported: bool = False  # the editor's palettes follow this console (a project can target it)
    exporter: str = ""  # the export the editor has for it
    vram_note: str = ""

    def mode(self, key: str) -> Optional[ScreenMode]:
        return next((m for m in self.modes if m.key == key), None)

    def setup(self, key: Optional[str]) -> BudgetSetup:
        """The setup with this key, else the console's first (its usual one)."""
        return next((b for b in self.budgets if b.key == key), self.budgets[0])


def _grid(step: int, largest: int) -> Tuple[Size, ...]:
    values = range(step, largest + 1, step)
    return tuple((w, h) for h in values for w in values)


# A widely used RGB rendering of the NES PPU's 64 colours (the console outputs composite video, so every RGB palette
# is an approximation), in hardware order; the black entries (0x0D-0x0F, 0x1D-0x1F, 0x2E-0x2F, 0x3E-0x3F) included.
_NES_COLOURS: Tuple[RGB, ...] = tuple(
    (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)) for h in (
        "7C7C7C 0000FC 0000BC 4428BC 940084 A80020 A81000 881400 503000 007800 006800 005800 004058 000000 000000 000000 "
        "BCBCBC 0078F8 0058F8 6844FC D800CC E40058 F83800 E45C10 AC7C00 00B800 00A800 00A844 008888 000000 000000 000000 "
        "F8F8F8 3CBCFC 6888FC 9878F8 F878F8 F85898 F87858 FCA044 F8B800 B8F818 58D854 58F898 00E8D8 787878 000000 000000 "
        "FCFCFC A4E4FC B8B8F8 D8B8F8 F8B8F8 F8A4C0 F0D0B0 FCE0A8 F8D878 D8F878 B8F8B8 B8F8D8 00FCFC F8D8F8 000000 000000"
    ).split()
)

MEGA_DRIVE = Console(
    key="megadrive",
    name="Mega Drive",
    short="Mega Drive",
    full_name="Sega Mega Drive / Genesis",
    refresh_rates=(60, 50),
    tile_size=8,
    modes=(
        ScreenMode("h40", 320, 224, sprites_per_screen=80, sprites_per_line=20, sprite_pixels_per_line=320),
        ScreenMode("h32", 256, 224, sprites_per_screen=64, sprites_per_line=16, sprite_pixels_per_line=256),
    ),
    sprites=SpriteHardware(
        bits_per_pixel=4, sizes=_grid(8, 32), tiles=1424,
        tiles_note="video memory is shared with the backgrounds; 1424 tiles are free in SGDK's default layout",
    ),
    backgrounds=TileHardware(flips=True),
    palette=PaletteHardware(colours=16, palettes=4, colour_model="rgb333", shared_with_backgrounds=True),
    budgets=(
        BudgetSetup("md_h40", "Mega Drive H40 (320 px)", "h40"),
        BudgetSetup("md_h32", "Mega Drive H32 (256 px)", "h32"),
    ),
    palettes_supported=True,
    exporter="SGDK",
    vram_note="64 KB (2048 tiles) for tiles, plane maps, the sprite table and scroll tables together",
)

SNES = Console(
    key="snes",
    name="SNES",
    short="SNES",
    full_name="Super Nintendo Entertainment System / Super Famicom",
    refresh_rates=(60, 50),
    tile_size=8,
    modes=(ScreenMode("256x224", 256, 224, sprites_per_screen=128, sprites_per_line=32, sprite_pixels_per_line=272),),
    sprites=SpriteHardware(
        bits_per_pixel=4,
        sizes=((8, 8), (16, 16), (32, 32), (64, 64)),
        size_sets=(
            ((8, 8), (16, 16)), ((8, 8), (32, 32)), ((8, 8), (64, 64)),
            ((16, 16), (32, 32)), ((16, 16), (64, 64)), ((32, 32), (64, 64)),
        ),
        tiles=512, tiles_note="two tables of 256 tiles (16 KB of video memory)",
    ),
    backgrounds=TileHardware(flips=True, rotation="mode7"),
    palette=PaletteHardware(colours=16, palettes=8, colour_model="bgr555", shared_with_backgrounds=False),
    budgets=(  # the six size pairs a game can choose (OBSEL)
        BudgetSetup("snes_8_16", "SNES, 8×8 and 16×16 sprites", "256x224", ((8, 8), (16, 16))),
        BudgetSetup("snes_8_32", "SNES, 8×8 and 32×32 sprites", "256x224", ((8, 8), (32, 32))),
        BudgetSetup("snes_8_64", "SNES, 8×8 and 64×64 sprites", "256x224", ((8, 8), (64, 64))),
        BudgetSetup("snes_16_32", "SNES, 16×16 and 32×32 sprites", "256x224", ((16, 16), (32, 32))),
        BudgetSetup("snes_16_64", "SNES, 16×16 and 64×64 sprites", "256x224", ((16, 16), (64, 64))),
        BudgetSetup("snes_32_64", "SNES, 32×32 and 64×64 sprites", "256x224", ((32, 32), (64, 64))),
    ),
    palettes_supported=True,
    exporter="PVSnesLib",
    vram_note="64 KB for tiles and maps",
)

NES = Console(
    key="nes",
    name="NES",
    short="NES",
    full_name="Nintendo Entertainment System / Famicom",
    refresh_rates=(60, 50),
    tile_size=8,
    modes=(ScreenMode("256x240", 256, 240, sprites_per_screen=64, sprites_per_line=8),),
    sprites=SpriteHardware(
        bits_per_pixel=2, sizes=((8, 8), (8, 16)), size_sets=(((8, 8),), ((8, 16),)),
        tiles=256, tiles_note="one pattern table of 256 tiles; 8×16 sprites can use both tables",
    ),
    backgrounds=TileHardware(flips=False),
    palette=PaletteHardware(
        colours=4, palettes=4, colour_model="fixed", shared_with_backgrounds=False, fixed_colours=_NES_COLOURS,
        fixed_note="a palette picks its colours from the PPU's 64 entries",
    ),
    budgets=(
        BudgetSetup("nes_8x8", "NES, 8×8 sprites", "256x240", ((8, 8),)),
        BudgetSetup("nes_8x16", "NES, 8×16 sprites", "256x240", ((8, 16),)),
    ),
    palettes_supported=True,
    vram_note="2 KB for name tables; tiles come from the cartridge's CHR memory",
)

GBA = Console(
    key="gba",
    name="Game Boy Advance",
    short="GBA",
    full_name="Nintendo Game Boy Advance",
    refresh_rates=(60,),
    tile_size=8,
    # The per-line limit is a budget of drawing cycles (1210 a line, 954 with H-blank access): about 1210 pixels of
    # ordinary sprites, fewer for rotated ones.
    modes=(ScreenMode("240x160", 240, 160, sprites_per_screen=128, sprites_per_line=128, sprite_pixels_per_line=1210),),
    sprites=SpriteHardware(
        bits_per_pixel=4,
        sizes=((8, 8), (16, 16), (32, 32), (64, 64), (16, 8), (32, 8), (32, 16), (64, 32),
               (8, 16), (8, 32), (16, 32), (32, 64)),
        rotation="affine",
        tiles=1024, tiles_note="32 KB of sprite tiles in the tile modes (16 KB in the bitmap modes)",
    ),
    backgrounds=TileHardware(flips=True, rotation="affine"),
    palette=PaletteHardware(colours=16, palettes=16, colour_model="bgr555", shared_with_backgrounds=False),
    budgets=(BudgetSetup("gba", "Game Boy Advance", "240x160"),),
    palettes_supported=True,
    vram_note="96 KB, 32 KB of it for sprite tiles",
)

GAME_BOY = Console(
    key="gameboy",
    name="Game Boy",
    short="Game Boy",
    full_name="Nintendo Game Boy",
    refresh_rates=(60,),
    tile_size=8,
    modes=(ScreenMode("160x144", 160, 144, sprites_per_screen=40, sprites_per_line=10),),
    sprites=SpriteHardware(
        bits_per_pixel=2, sizes=((8, 8), (8, 16)), size_sets=(((8, 8),), ((8, 16),)),
        tiles=256, tiles_note="256 sprite tiles, half of them shared with the backgrounds",
    ),
    backgrounds=TileHardware(flips=False),
    palette=PaletteHardware(
        colours=4, palettes=2, colour_model="fixed", shared_with_backgrounds=False,
        fixed_colours=((0x9B, 0xBC, 0x0F), (0x8B, 0xAC, 0x0F), (0x30, 0x62, 0x30), (0x0F, 0x38, 0x0F)),
        fixed_note="four shades of the green screen, as usually shown",
    ),
    budgets=(
        BudgetSetup("gb_8x8", "Game Boy, 8×8 sprites", "160x144", ((8, 8),)),
        BudgetSetup("gb_8x16", "Game Boy, 8×16 sprites", "160x144", ((8, 16),)),
    ),
    palettes_supported=True,
    vram_note="8 KB for tiles and maps",
)

CONSOLES: Tuple[Console, ...] = (MEGA_DRIVE, SNES, NES, GBA, GAME_BOY)
DEFAULT = MEGA_DRIVE
_BY_KEY: Dict[str, Console] = {c.key: c for c in CONSOLES}


def console_by_key(key: Optional[str]) -> Console:
    """The console with this key; the default (Mega Drive) for anything else."""
    return _BY_KEY.get(str(key or ""), DEFAULT)


def palette_consoles() -> List[Console]:
    """Consoles a project can target: those the palettes support."""
    return [c for c in CONSOLES if c.palettes_supported]


def screen_guides() -> List[Tuple[str, Tuple[int, int]]]:
    """Every console screen, in the database's order: ("Mega Drive 320×224", (320, 224)), ..."""
    return [(f"{c.short} {m.width}×{m.height}", (m.width, m.height)) for c in CONSOLES for m in c.modes]


def budget_setups() -> List[Tuple[Console, BudgetSetup]]:
    return [(c, b) for c in CONSOLES for b in c.budgets]


def setup_by_key(key: Optional[str]) -> Optional[Tuple[Console, BudgetSetup]]:
    """The console and setup of a setup key ("snes_16_32"), or None."""
    return next(((c, b) for c, b in budget_setups() if b.key == key), None)


def target(console_key: Optional[str], setup_key: Optional[str] = None) -> Tuple[Console, BudgetSetup]:
    """A project's target: its console (``Project.console``) and that console's setup (``Project.console_setup``;
    the console's first when the key is unknown or another console's)."""
    console = console_by_key(console_key)
    return console, console.setup(setup_key)


def target_screen(console: Console, setup: BudgetSetup) -> Tuple[int, int]:
    """The width and height of the setup's screen."""
    mode = console.mode(setup.mode) or console.modes[0]
    return mode.width, mode.height
