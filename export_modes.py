"""Ways to export a project for a console, and what each would cost there (wx-free); docs/EXPORT_MODES.md explains
them.

By default a console export stores parts (each module's tiles once; a frame is its parts, put together when it is
drawn) and keeps every tile in video memory: the runtime only writes the sprite table. Two other ways, which a
console's export offers where its runtime plays them (``ConsoleExport.modes``: the Mega Drive's), are measured here
too:

- parts, streamed: the same parts and tiles in the cartridge, but video memory holds only the tiles of what each
  player shows, in a slot of its own; a step uploads its frame's tiles when it starts (``ConsoleBake.load_list``), and
  a scene streams through one slot, a sample's tiles at a time;
- whole frames, streamed: each frame flattened into one picture per palette (``ConsoleBake.whole_frames``) and cut
  into the console's hardware sprites like a part: the fewest sprites and the most tiles in the cartridge, and a
  mapping is baked again rather than swapped when it is drawn.

Between them, the frames marked so (``Frame.store_whole``: a platform, a crusher, a torch) are stored whole in the
parts modes too, and every other frame stays parts: the fewest sprites where a frame of many parts shows often, parts
where frames share them (characters, their mappings).

``measure`` bakes the project with the console's own exporter (``ConsoleExport.bake_context``: the same cut and the
same tiles as its export, nothing written), once with parts (the marked frames whole) and once with every frame whole.
Modules drawn on their own stay parts in the parts modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import console_bake
from console_exports import ConsoleExport
from models import ModuleMapping, Project

Sprite = Tuple[int, int, int, int]  # (x, y, width, height)


@dataclass(frozen=True)
class Mode:
    key: str
    name: str
    whole_frames: bool  # the cartridge holds whole frames, not parts
    streamed: bool  # video memory holds the tiles each player shows, uploaded when a step starts


PARTS = Mode("parts", "Parts, resident", False, False)  # what the exports do
PARTS_STREAMED = Mode("parts_streamed", "Parts, streamed", False, True)
FRAMES_STREAMED = Mode("frames_streamed", "Whole frames, streamed", True, True)
MODES: Tuple[Mode, ...] = (PARTS, PARTS_STREAMED, FRAMES_STREAMED)


@dataclass(frozen=True)
class Costs:
    mode: Mode
    video_tiles: int  # resident: every tile; streamed: a player's slot (the most a module, frame or step shows;
    # the SNES's slots are whole rows of 16 tiles: ConsoleBake.stream_slots)
    cartridge_tiles: int  # every tile the export stores, once
    tile_bytes: int  # bytes per tile: 32 at 4 bits a pixel
    shown: str  # what the sprite counts are over: "animation steps", or "frames" in a project without animations
    sprites_avg: float  # hardware sprites a step shows, on average
    sprites_max: int
    line_max: int  # hardware sprites on the busiest line of a step
    upload_avg: float  # bytes a step uploads when it starts (streamed), on average
    upload_max: int
    upload_cost_max: int  # streamed: what filling a slot costs at most in vertical blank, in bytes of DMA
    scene_video_tiles: int  # resident: every tile; streamed: a scene's slot (the most tiles one sample shows)
    scene_sprites_max: int  # hardware sprites of a scene sample (every object, on screen or not)
    scene_line_max: int

    @property
    def cartridge_bytes(self) -> int:
        return self.cartridge_tiles * self.tile_bytes


def measure(project: Project, export: ConsoleExport, setup_key: str = "",
            mappings: Optional[Sequence[Optional[ModuleMapping]]] = None) -> List[Costs]:
    """Every mode's costs for the project on the export's console, in MODES' order. ``setup_key``: one of the
    console's setups, for an export with setups (else the exporter's choice); ``mappings``: what the export bakes,
    no mapping and every mapping by default."""
    chosen = [None] + list(project.mappings) if mappings is None else list(mappings)
    tile_bytes = export.console.sprites.bits_per_pixel * 8
    parts = _bake(project, export, chosen, setup_key, whole_frames=False)
    frames = _bake(project, export, chosen, setup_key, whole_frames=True)
    return [_costs(mode, frames if mode.whole_frames else parts, tile_bytes) for mode in MODES]


def measure_mode(project: Project, export: ConsoleExport, mode: Mode, setup_key: str = "",
                 mappings: Optional[Sequence[Optional[ModuleMapping]]] = None) -> Costs:
    """One mode's costs (one bake), as ``measure`` reports them."""
    chosen = [None] + list(project.mappings) if mappings is None else list(mappings)
    bake = _bake(project, export, chosen, setup_key, whole_frames=mode.whole_frames)
    return _costs(mode, bake, export.console.sprites.bits_per_pixel * 8)


def mode_by_key(key: str) -> Mode:
    """The mode with this key (PARTS for anything else)."""
    return next((mode for mode in MODES if mode.key == key), PARTS)


def _bake(project: Project, export: ConsoleExport, mappings: List[Optional[ModuleMapping]], setup_key: str,
          whole_frames: bool) -> console_bake.ConsoleBake:
    bake = export.bake_context(project, mappings, setup_key)
    bake.whole_frames = whole_frames
    console_bake.ConsoleBake.bake(bake)  # the walk alone: no files, no sprite tables (whole frames may not fit them)
    return bake


def busiest_line(sprites: Iterable[Sprite]) -> int:
    """The most sprites any one line of pixels crosses."""
    rows: Dict[int, int] = {}
    for _x, y, _w, h in sprites:
        for row in range(y, y + h):
            rows[row] = rows.get(row, 0) + 1
    return max(rows.values(), default=0)


def _costs(mode: Mode, bake: console_bake.ConsoleBake, tile_bytes: int) -> Costs:
    tiles_of: Dict[int, int] = {}  # render frame -> the tiles it shows
    sprites_of: Dict[int, List[Sprite]] = {}

    def tiles(render: int) -> int:
        if render not in tiles_of:
            tiles_of[render] = sum(bake.load_list(render).values())
        return tiles_of[render]

    def sprites(render: int) -> List[Sprite]:
        if render not in sprites_of:
            sprites_of[render] = bake.render_frame_sprites(render)
        return sprites_of[render]

    every: Dict[int, int] = {}
    for render in range(len(bake.render_frames)):
        every.update(bake.load_list(render))
    stored = sum(every.values())

    shows = lambda render: bake.render_frames[render].part_count > 0  # noqa: E731
    frames = [render for render in bake.frame_render_frames if shows(render)]
    steps = [render for render, *_rest in bake.anim_steps if shows(render)]
    shown = "animation steps"
    if not steps:
        steps, shown = frames, "frames"
    counts = [len(sprites(render)) for render in steps]
    uploads = [tiles(render) * tile_bytes for render in steps] if mode.streamed else []
    slot, scene_slots = bake.stream_slots() if mode.streamed else (0, 0)
    samples = set(bake.scene_samples)
    scene_sprites = max((len(sprites(render)) for render in samples), default=0)
    scene_line = max((busiest_line(sprites(render)) for render in samples), default=0)

    return Costs(
        mode=mode,
        video_tiles=slot if mode.streamed else stored,
        cartridge_tiles=stored,
        tile_bytes=tile_bytes,
        shown=shown,
        sprites_avg=sum(counts) / len(counts) if counts else 0.0,
        sprites_max=max(counts, default=0),
        line_max=max((busiest_line(sprites(render)) for render in steps), default=0),
        upload_avg=sum(uploads) / len(uploads) if uploads else 0.0,
        upload_max=max(uploads, default=0),
        upload_cost_max=bake.stream_upload_cost(tile_bytes) if mode.streamed else 0,
        scene_video_tiles=scene_slots if mode.streamed else stored,
        scene_sprites_max=scene_sprites,
        scene_line_max=scene_line,
    )
