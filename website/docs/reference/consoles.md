# Consoles

Every console draws sprites with its own hardware: a screen size, a number of hardware sprites per screen and per
line, the shapes a sprite can have, and palettes of a few colours. The editor keeps these facts in one place and uses
them for the [budget overlay](../guide/hardware-budget.md), the Timeline's screen guides and the
[palettes](../guide/palettes.md).

The Mega Drive is the first console the editor exports for, and the one its palettes follow. The others are listed
with what the editor already knows about them: their screen guides on the Timeline, and for the SNES the budget
overlay. More consoles will follow.

| Console | Screen | Sprites on screen / on a line | Colours for sprites | In the editor |
| --- | --- | --- | --- | --- |
| Mega Drive | 320×224 or 256×224 | 80 / 20 | 4 × 15 + transparent | export (SGDK), palettes, budget overlay, screen guide |
| SNES | 256×224 | 128 / 32 | 8 × 15 + transparent | budget overlay, screen guide |
| NES | 256×240 | 64 / 8 | 4 × 3 + transparent | screen guide |
| Game Boy Advance | 240×160 | 128 / 128 | 16 × 15 + transparent | screen guide |
| Game Boy | 160×144 | 40 / 10 | 2 × 3 + transparent | screen guide |

## Mega Drive

*Sega Mega Drive / Genesis*

| | |
| --- | --- |
| Screen | 320×224: 80 sprites on screen, 20 on a line, 320 sprite pixels on a line |
| Screen | 256×224: 64 sprites on screen, 16 on a line, 256 sprite pixels on a line |
| Refresh rate | 60 Hz or 50 Hz (NTSC, PAL) |
| Sprite sizes | any multiple of 8 from 8×8 to 32×32 |
| Sprite flips | horizontal and vertical (free: a mirrored part needs no art of its own) |
| Sprite rotation | none: turns are drawn as their own art |
| Sprite pixels | 4 bits: 16 colours, one transparent |
| Sprite tiles | 1424 tiles of 8×8 pixels; video memory is shared with the backgrounds; 1424 tiles are free in SGDK's default layout |
| Palettes for sprites | 4, of 15 colours and transparent each, shared with the backgrounds |
| Colours | 3 bits a channel: 512 colours |
| Background tiles | flip horizontally and vertically |
| Video memory | 64 KB (2048 tiles) for tiles, plane maps, the sprite table and scroll tables together |
| Budget overlay | Mega Drive H40 (320 px); Mega Drive H32 (256 px) |
| In the editor | export (SGDK), palettes, budget overlay, screen guide |

## SNES

*Super Nintendo Entertainment System / Super Famicom*

| | |
| --- | --- |
| Screen | 256×224: 128 sprites on screen, 32 on a line, 272 sprite pixels on a line |
| Refresh rate | 60 Hz or 50 Hz (NTSC, PAL) |
| Sprite sizes | one set per game: 8×8 and 16×16; 8×8 and 32×32; 8×8 and 64×64; 16×16 and 32×32; 16×16 and 64×64; 32×32 and 64×64 |
| Sprite flips | horizontal and vertical (free: a mirrored part needs no art of its own) |
| Sprite rotation | none: turns are drawn as their own art |
| Sprite pixels | 4 bits: 16 colours, one transparent |
| Sprite tiles | 512 tiles of 8×8 pixels; two tables of 256 tiles (16 KB of video memory) |
| Palettes for sprites | 8, of 15 colours and transparent each |
| Colours | 5 bits a channel: 32,768 colours |
| Background tiles | flip horizontally and vertically; one layer turns and scales (Mode 7) |
| Video memory | 64 KB for tiles and maps |
| Budget overlay | SNES, 8×8 and 16×16 sprites; SNES, 16×16 and 32×32 sprites |
| In the editor | budget overlay, screen guide |

## NES

*Nintendo Entertainment System / Famicom*

| | |
| --- | --- |
| Screen | 256×240: 64 sprites on screen, 8 on a line |
| Refresh rate | 60 Hz or 50 Hz (NTSC, PAL) |
| Sprite sizes | one set per game: 8×8; 8×16 |
| Sprite flips | horizontal and vertical (free: a mirrored part needs no art of its own) |
| Sprite rotation | none: turns are drawn as their own art |
| Sprite pixels | 2 bits: 4 colours, one transparent |
| Sprite tiles | 256 tiles of 8×8 pixels; one pattern table of 256 tiles; 8×16 sprites can use both tables |
| Palettes for sprites | 4, of 3 colours and transparent each |
| Colours | chosen from a fixed set (a palette picks its colours from the PPU's 64 entries) |
| Background tiles | no flips |
| Video memory | 2 KB for name tables; tiles come from the cartridge's CHR memory |
| In the editor | screen guide |

## Game Boy Advance

*Nintendo Game Boy Advance*

| | |
| --- | --- |
| Screen | 240×160: 128 sprites on screen, 128 on a line, 1210 sprite pixels on a line |
| Refresh rate | 60 Hz |
| Sprite sizes | 8×8, 16×16, 32×32, 64×64, 16×8, 32×8, 32×16, 64×32, 8×16, 8×32, 16×32, 32×64 |
| Sprite flips | horizontal and vertical (free: a mirrored part needs no art of its own) |
| Sprite rotation | any angle and scale, through a few shared matrices |
| Sprite pixels | 4 bits: 16 colours, one transparent |
| Sprite tiles | 1024 tiles of 8×8 pixels; 32 KB of sprite tiles in the tile modes (16 KB in the bitmap modes) |
| Palettes for sprites | 16, of 15 colours and transparent each |
| Colours | 5 bits a channel: 32,768 colours |
| Background tiles | flip horizontally and vertically; layers turn and scale |
| Video memory | 96 KB, 32 KB of it for sprite tiles |
| In the editor | screen guide |

## Game Boy

*Nintendo Game Boy*

| | |
| --- | --- |
| Screen | 160×144: 40 sprites on screen, 10 on a line |
| Refresh rate | 60 Hz |
| Sprite sizes | one set per game: 8×8; 8×16 |
| Sprite flips | horizontal and vertical (free: a mirrored part needs no art of its own) |
| Sprite rotation | none: turns are drawn as their own art |
| Sprite pixels | 2 bits: 4 colours, one transparent |
| Sprite tiles | 256 tiles of 8×8 pixels; 256 sprite tiles, half of them shared with the backgrounds |
| Palettes for sprites | 2, of 3 colours and transparent each |
| Colours | chosen from a fixed set (four shades of the green screen, as usually shown) |
| Background tiles | no flips |
| Video memory | 8 KB for tiles and maps |
| In the editor | screen guide |
