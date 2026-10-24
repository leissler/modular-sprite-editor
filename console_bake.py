"""The console-independent half of a console export (wx-free): what a game on any console needs from a project,
baked once per mapping, with each part's picture handed to the console's exporter.

``ConsoleBake.bake()`` walks the project the way the editor draws it: modules; frames (nested frames flattened into
module parts with their flips and quarter turns; a part a hardware flip cannot show, at another angle, is drawn into a
picture of its own); animation steps with the game's timing (``playback.console_frames``), events, loop-from step,
follow-up and repeat count; scene samples at the scene's frame rate, each object with its own mapping and palette
swap. Identical render frames (parts with their hitboxes and points) are kept once.

Its one hook is ``_store_part(image, palette_id, entry) -> int``: the console's exporter turns a part's picture into
what its hardware draws (tiles, hardware sprites) and returns its number. A part is then (that number, x, y, hflip,
vflip); a hardware flip mirrors the picture padded to whole tiles. Palette entries (``palettes.export_entries``: every
palette, then each swap's version of the palettes it changes) are named per part as an entry index, ``FIXED_ENTRY``
set where a scene object's own swap (or "original") fixes the colours.

Each console's exporter subclasses it: the Mega Drive's (``MegaDriveBakeContext`` in
examples/megadrive/tools/export_megadrive.py: VDP tiles, the hardware sprite cut, CRAM words, the blob) and the SNES's
(``SNESBakeContext`` in examples/snes/tools/export_snes.py: 4 bpp tiles in two sprite tables, OAM-ready sprites, chunks
of a ROM bank). They also share what their command lines and the editor's export dialogs choose: the mappings
(``resolve_mappings``), the copy of the sources (``copy_sources``) and the options every console's exporter takes
(``export_arguments``, ``print_result``). docs/CONSOLES.md lists what full support of a console means.

A frame marked so (``Frame.store_whole``) is stored whole: flattened into one picture per palette
(``compositor.palette_layers``, the part on top owning each pixel), which the console's exporter cuts into the fewest
hardware sprites like any part. It is drawn that way wherever it shows: on its own, as an animation step, in a scene,
nested in a frame of parts. Moved or mirrored it shows its upright pictures with hardware flips; turned, pictures of
its own. The export mode that stores every frame whole sets ``whole_frames`` (export_modes.py, docs/EXPORT_MODES.md).
The console's exporter says what a stored part is in hardware sprites and tiles (``_stored_part``), from which every
render frame's sprites (``render_frame_sprites``) and the tiles it shows (``load_list``: what a streamed export would
upload) follow.
"""

from __future__ import annotations

import argparse
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from PIL import Image

import compositor
import palettes
import playback
import project_check
from models import (
    TIMELINE_MAPPING_ORIGINAL, Frame, Module, ModuleMapping, PaletteSwap, Project, TimelineScene, state_shows,
)

Matrix2 = Tuple[Tuple[float, float], Tuple[float, float]]
Vec2 = Tuple[float, float]
Matrix2x3 = Tuple[float, float, float, float, float, float]
PartEntry = Tuple[int, int, int, int, int]  # (stored part number, x, y, hflip, vflip)
BoxEntry = Tuple[int, int, int, int, int, int]  # (type, role, x, y, w, h)
PointEntry = Tuple[int, int, int, int]  # (type, role, x, y)
Layer = Tuple[Image.Image, int, int, str]  # a whole frame's picture of one palette, where it goes, the palette


class StoredPart(NamedTuple):
    """A stored part as its console draws it (``ConsoleBake._stored_part``): its picture padded to whole tiles, which
    a hardware flip mirrors, and its hardware sprites, unflipped, as (x, y, width, height, tile block, tiles); the same
    tiles stored once are one block."""
    width: int
    height: int
    sprites: Tuple[Tuple[int, int, int, int, int, int], ...]

# A part's palette entry: the entry's index, FIXED_ENTRY set when its colours stay as they are (a scene object's own
# swap or "original"), not recoloured by the swap the game draws with.
FIXED_ENTRY = 0x80
MAX_PALETTE_ENTRIES = 0x7F
NO_ANIMATION = 0xFFFF
NO_ROLE = 0xFFFF
UNKNOWN_TYPE = 0xFF


@dataclass(frozen=True)
class RenderFrameSpan:
    first_part: int
    part_count: int
    first_box: int = 0
    box_count: int = 0
    first_point: int = 0
    point_count: int = 0


@dataclass(frozen=True)
class AnimRecord:
    first_step: int
    step_count: int
    fps: int
    playback: int
    loop_start: int = 0  # exported step index later loop passes start at
    next_animation: int = 0xFFFF  # animation index to continue with when this one ends (0xFFFF = none)
    loop_count: int = 0  # 0 = repeat forever


@dataclass(frozen=True)
class SceneRecord:
    first_sample: int
    sample_count: int
    fps: int
    duration_ticks: int
    loop: int


def resolve_mappings(project: Project, selector: str) -> List[Optional[ModuleMapping]]:
    """The mappings an export bakes, ``None`` (no mapping) first: every one for "all" (the default; "auto" and "*"
    say the same), none for "none", else the one with that id or name."""
    lower = str(selector or "all").strip().lower()
    if lower in ("none", "off", "null"):
        return [None]
    if lower in ("all", "auto", "*"):
        return [None] + list(project.mappings)
    for item in project.mappings:
        if item.id == selector or item.name.strip().lower() == lower:
            return [None, item]
    raise ValueError(f"Mapping '{selector}' was not found. Available: {[m.name for m in project.mappings]}")


def copy_sources(project: Project, project_path: Optional[Path], folder: Path) -> None:
    """The project file and the images it uses, copied into the game's folder (``source/``) for reference."""
    if project_path is None:
        return
    target = Path(folder) / "source"
    sources = [Path(project_path)] + [Path(asset.file_path) for asset in project.images]
    for source in sources:
        if source.exists() and source.resolve() != (target / source.name).resolve():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / source.name)


def export_arguments(console: str, default_project: Path, default_folder: Path,
                     modes: Sequence[str] = ()) -> argparse.ArgumentParser:
    """The command line every console's exporter takes (a console adds its own options, such as the SNES's --setup);
    ``modes``: the ways it can store the sprites (export_modes), --mode when there is more than one."""
    parser = argparse.ArgumentParser(description=f"Export a modular sprite project for the {console}: the data a game "
                                                 "with the runtime draws, plays and checks its sprites with.")
    parser.add_argument("--project-json", default=str(default_project), help="The project file.")
    parser.add_argument("--output-dir", default=str(default_folder),
                        help="The game's project folder, with the console's runtime (as the demo has it).")
    parser.add_argument("--output-demo-dir", dest="output_dir", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)  # the Mega Drive exporter's name for --output-dir up to 0.10.2
    parser.add_argument("--mapping", default="all", help="A mapping's name or id, 'all' (default) or 'none'.")
    parser.add_argument("--copy-assets", action="store_true",
                        help="Also copy the project file and its images into the folder's source/.")
    parser.add_argument("--strict", action="store_true", help="Exit with 1 when Check Project finds errors.")
    if len(modes) > 1:
        parser.add_argument("--mode", choices=list(modes), default=modes[0],
                            help=f"How the sprites are stored (docs/EXPORT_MODES.md); default: {modes[0]}.")
    return parser


def print_result(result: Any, strict: bool) -> int:
    """An export's summary and issues as the command line prints them; the exit code (1 for errors with --strict)."""
    for key, value in result.summary.items():
        print(f"{key}: {value}")
    for issue in result.issues:
        print(f"{'note' if issue.level == project_check.INFO else issue.level}: {issue.text}")
    return 1 if strict and any(issue.level == project_check.ERROR for issue in result.issues) else 0


def _event_symbols(names: Sequence[str], prefix: str = "MS_EVENT_", fallback: str = "EVENT") -> List[str]:
    """C identifiers for names: MS_EVENT_HIT_ON, unique, never starting with a digit (Check Project warns about
    names that clash)."""
    return project_check.c_symbols(names, prefix, fallback)


class ConsoleBake:
    """A project baked for a console: render frames (parts, hitboxes, points), module and frame render frames,
    animation steps and records, scene samples and records, one set per mapping (``mappings``, None = no mapping)."""

    def __init__(self, project: Project, mappings: List[Optional[ModuleMapping]]) -> None:
        self.project = project
        self.mappings = mappings
        self.mapping = mappings[0] if mappings else None
        self.mapping_key = self.mapping.id if self.mapping else "none"

        self.full_image_cache: Dict[str, Any] = {}
        self.module_cache: Dict[str, Any] = {}

        self.parts: List[PartEntry] = []
        self.boxes: List[BoxEntry] = []
        self.points: List[PointEntry] = []
        self.render_frames: List[RenderFrameSpan] = []
        self.render_frame_lookup: Dict[Tuple[Any, ...], int] = {}
        self.box_type_index: Dict[str, int] = {t.id: i for i, t in enumerate(project.collision_types)}
        self.point_type_index: Dict[str, int] = {t.id: i for i, t in enumerate(project.point_types)}
        self.box_type_symbols: List[str] = _event_symbols([t.name for t in project.collision_types], "MS_HITBOX_", "HITBOX")
        self.point_type_symbols: List[str] = _event_symbols([t.name for t in project.point_types], "MS_POINT_", "POINT")
        self.role_names: List[str] = project_check.role_names(project)
        self.role_index: Dict[str, int] = {name: i for i, name in enumerate(self.role_names)}
        self.role_symbols: List[str] = _event_symbols(self.role_names, "MS_ROLE_", "ROLE")
        self.transformed_frame_parts_cache: Dict[Tuple[Any, ...], Tuple[PartEntry, ...]] = {}

        self.module_render_frames: List[int] = []
        self.frame_render_frames: List[int] = []

        self.anim_steps: List[Tuple[int, int, int, int]] = []  # (render frame, ticks, first event, event count)
        self.anim_records: List[AnimRecord] = []
        self.step_events: List[Tuple[int, int]] = []  # (event type index, value)
        self.event_type_index: Dict[str, int] = {t.id: i for i, t in enumerate(project.event_types)}
        self.event_symbols: List[str] = _event_symbols([t.name for t in project.event_types])

        self.scene_samples: List[int] = []
        self.scene_records: List[SceneRecord] = []

        # Every frame whole instead of its parts (set before bake(): the frames_streamed mode); otherwise the frames
        # marked store_whole only.
        self.whole_frames = False
        self.upright_layers: Dict[Tuple[str, str], Tuple[Layer, ...]] = {}  # (mapping, frame) -> its layers

        self.mapping_ids: List[str] = [m.id if m else "" for m in self.mappings]
        self.mapping_names: List[str] = [m.name if m else "<none>" for m in self.mappings]

        # Palette entries: every palette, then every swap's version of the palettes it changes. Pixels are stored in
        # their palette's slots; a part names the entry its colours come from.
        self.palette_entries: List[palettes.Entry] = palettes.export_entries(project)
        if len(self.palette_entries) > MAX_PALETTE_ENTRIES:
            raise RuntimeError(f"Too many palettes and palette swaps for the blob: {len(self.palette_entries)} entries "
                               f"> {MAX_PALETTE_ENTRIES}")
        self.entry_of: Dict[Tuple[str, Optional[str]], int] = {
            (entry.palette_id, entry.swap_id): index for index, entry in enumerate(self.palette_entries)}
        self.palette_ids: List[str] = [palette.id for palette in project.palettes]
        self.swaps: List[PaletteSwap] = list(project.palette_swaps)
        self.palette_colours: Dict[str, List[Tuple[int, int, int]]] = {
            palette.id: palettes.colours_of(project, palette) for palette in project.palettes}
        self.palette_lookup_caches: Dict[str, Dict[Tuple[int, int, int], int]] = {pid: {} for pid in self.palette_colours}
        self.palette_swap: Optional[PaletteSwap] = None  # scene objects with a swap (or "original") of their own
        self.palette_fixed = False

    def _store_part(self, image: Image.Image, palette: str, entry: int) -> int:
        """The console's exporter stores a part's picture (in palette ``palette``'s slots, drawn from palette entry
        ``entry``) as its hardware draws it and returns its number (the same picture with the same entry gets the same
        number)."""
        raise NotImplementedError("a console's exporter stores the parts")

    def _stored_part(self, stored: int) -> StoredPart:
        """The console's exporter: a stored part's padded size and hardware sprites, for measuring (export_modes)."""
        raise NotImplementedError("a console's exporter knows its hardware sprites")

    def stored_whole(self, frame: Frame) -> bool:
        """Whether the frame is stored as its pictures: every frame in the whole frames mode, else those marked so."""
        return self.whole_frames or frame.store_whole

    def marked_whole(self) -> int:
        """How many frames are marked to be stored whole, outside the mode that stores them all whole (for the
        export's summary: ``frames_stored_whole``)."""
        return 0 if self.whole_frames else sum(1 for frame in self.project.frames if frame.store_whole)

    # ---------------------------------------------------------------- measuring
    def render_frame_parts(self, index: int) -> List[PartEntry]:
        span = self.render_frames[index]
        return self.parts[span.first_part:span.first_part + span.part_count]

    def sprites_of(self, parts: Sequence[PartEntry]) -> List[Tuple[int, int, int, int]]:
        """The parts' hardware sprites as (x, y, width, height), relative to where they are drawn: a flipped part's
        sprites swap places inside its padded picture."""
        out: List[Tuple[int, int, int, int]] = []
        for stored, x, y, hflip, vflip in parts:
            part = self._stored_part(stored)
            for sx, sy, w, h, _block, _tiles in part.sprites:
                out.append((x + (part.width - sx - w if hflip else sx), y + (part.height - sy - h if vflip else sy), w, h))
        return out

    def blocks_of(self, parts: Sequence[PartEntry]) -> Dict[int, int]:
        """The tile blocks the parts show, each once, in the order they first need them: {block: tiles}."""
        blocks: Dict[int, int] = {}
        for stored, *_placement in parts:
            for *_box, block, tiles in self._stored_part(stored).sprites:
                blocks.setdefault(block, tiles)
        return blocks

    def render_frame_sprites(self, index: int) -> List[Tuple[int, int, int, int]]:
        return self.sprites_of(self.render_frame_parts(index))

    def load_list(self, index: int) -> Dict[int, int]:
        """The tile blocks a render frame shows ({block: tiles}): what a streamed export would upload into the slot of
        whatever draws it."""
        return self.blocks_of(self.render_frame_parts(index))

    def stream_slots(self) -> Tuple[int, int]:
        """A streamed export's slots in tiles of video memory: a player's (the most tiles a module, frame or animation
        step shows) and a scene's (the most one of its samples shows). A console whose slots hold more than the tiles
        (the SNES's: whole rows of its sprite tables) works them out its way."""
        tiles = lambda render: sum(self.load_list(render).values())  # noqa: E731
        players = set(self.module_render_frames) | set(self.frame_render_frames) | {step[0] for step in self.anim_steps}
        return (max((tiles(render) for render in players), default=0),
                max((tiles(render) for render in set(self.scene_samples)), default=0))

    def stream_upload_cost(self, tile_bytes: int) -> int:
        """What filling a slot costs at most in vertical blank, in bytes of DMA: the most tiles a render frame shows
        (a console whose runtime spends noticeable time per DMA run counts that in too, the SNES's)."""
        tiles = (sum(self.load_list(render).values()) for render in range(len(self.render_frames)))
        return max(tiles, default=0) * tile_bytes

    @staticmethod
    def _identity_matrix() -> Matrix2:
        return ((1.0, 0.0), (0.0, 1.0))

    @staticmethod
    def _identity_offset() -> Vec2:
        return (0.0, 0.0)

    @staticmethod
    def _roundf(value: float, digits: int = 4) -> float:
        return round(float(value), digits)

    @staticmethod
    def _playback_code(playback_type: str) -> int:
        mode = str(playback_type or "loop").strip().lower()
        if mode in ("once", "forward"):
            return 1
        if mode == "ping_pong":
            return 2
        if mode == "backward":
            return 3
        return 0

    def _set_current_mapping(self, mapping: Optional[ModuleMapping]) -> None:
        self.mapping = mapping
        self.mapping_key = mapping.id if mapping else "none"

    def _set_palette_state(self, swap: Optional[PaletteSwap], fixed: bool) -> None:
        """How the parts baked next get their colours: (None, False) follows the swap the game draws with; a swap
        or (None, True) for "original" is fixed in the pieces."""
        self.palette_swap = swap
        self.palette_fixed = bool(fixed)

    def _palette_key(self) -> Tuple[str, bool]:
        return (self.palette_swap.id if self.palette_swap else "", self.palette_fixed)

    def _entry_byte(self, palette_id: str) -> int:
        """The palette entry a part of this palette draws from (see _set_palette_state)."""
        swap = self.palette_swap
        if swap is not None and (palette_id, swap.id) in self.entry_of:
            return self.entry_of[(palette_id, swap.id)] | FIXED_ENTRY
        return self.entry_of[(palette_id, None)] | (FIXED_ENTRY if self.palette_fixed else 0)

    def _object_colours(self, scene: TimelineScene, object_id: str) -> Tuple[Optional[PaletteSwap], bool]:
        """A scene object's own palette swap (its own or an ancestor's, like the mapping), or (None, False) when it
        follows the swap the scene is drawn with."""
        seen: set = set()
        obj = scene.get_object(object_id)
        while obj and obj.id not in seen:
            seen.add(obj.id)
            if obj.palette_swap_id == TIMELINE_MAPPING_ORIGINAL:
                return None, True
            if obj.palette_swap_id:
                swap = self.project.get_palette_swap(obj.palette_swap_id)
                if swap is not None:
                    return swap, True
            obj = scene.get_object(obj.parent_id) if obj.parent_id else None
        return None, False

    @staticmethod
    def _is_hidden_module(mod: Optional[Module]) -> bool:
        if mod is None:
            return True
        return int(mod.rect[2]) <= 0 or int(mod.rect[3]) <= 0

    def _resolve_module(self, module_id: str) -> Optional[Module]:
        mod = compositor.resolve_module(self.project, module_id, self.mapping)
        if self._is_hidden_module(mod):
            return None
        return mod

    def _palette_of_module(self, mod: Module) -> str:
        """The palette a module's pixels use: its image's (vector shapes use the first)."""
        asset = self.project.get_image(mod.image_id) if mod.type == "MD_IMAGE" else None
        return self.project.image_palette(asset).id

    @staticmethod
    def _rgb_distance_sq(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
        dr = int(a[0]) - int(b[0])
        dg = int(a[1]) - int(b[1])
        db = int(a[2]) - int(b[2])
        return dr * dr + dg * dg + db * db

    def _nearest_palette_index(self, rgb: Tuple[int, int, int], palette: str) -> int:
        """0-14: the palette slot a colour takes, as palettes.nearest picks it (the tile stores it + 1, 0 is
        transparent)."""
        return palettes.nearest(rgb, self.palette_colours.get(palette, []), self.palette_lookup_caches.setdefault(palette, {}))

    def _to_indexed(self, rgba: Image.Image, palette: str) -> Image.Image:
        """The picture as palette slots: each pixel's slot + 1 (palettes.nearest), 0 where it is transparent."""
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        src_rgb = rgb.tobytes()
        src_alpha = alpha.tobytes()
        out_idx = bytearray(len(src_alpha))
        for i in range(len(src_alpha)):
            if src_alpha[i] != 0:
                j = i * 3
                out_idx[i] = self._nearest_palette_index((src_rgb[j], src_rgb[j + 1], src_rgb[j + 2]), palette) + 1

        colours = [0] * (256 * 3)
        for i, rgb_color in enumerate(self.palette_colours.get(palette, [])):
            dst_off = (i + 1) * 3
            colours[dst_off] = int(rgb_color[0])
            colours[dst_off + 1] = int(rgb_color[1])
            colours[dst_off + 2] = int(rgb_color[2])

        out = Image.frombytes("P", rgba.size, bytes(out_idx))
        out.putpalette(colours)
        return out

    def _intern_render_frame(
        self,
        part_list: Sequence[PartEntry],
        boxes: Sequence[BoxEntry] = (),
        points: Sequence[PointEntry] = (),
    ) -> int:
        parts_key = tuple((int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4])) for p in part_list)
        key = (parts_key, tuple(boxes), tuple(points))
        found = self.render_frame_lookup.get(key)
        if found is not None:
            return found

        span = RenderFrameSpan(
            first_part=len(self.parts), part_count=len(parts_key),
            first_box=len(self.boxes), box_count=len(boxes),
            first_point=len(self.points), point_count=len(points),
        )
        self.parts.extend(parts_key)
        self.boxes.extend(boxes)
        self.points.extend(points)
        idx = len(self.render_frames)
        self.render_frames.append(span)
        self.render_frame_lookup[key] = idx
        return idx

    def _frame_markers(
        self, frame: Frame, offset: Vec2, rotation_degrees: float, flip_x: bool, flip_y: bool
    ) -> Tuple[Tuple[BoxEntry, ...], Tuple[PointEntry, ...]]:
        """The frame's own hitboxes and points, moved like the frame (flip, then rotate, then offset)."""
        a_mat = compositor.mat_mul(
            compositor.rotation_matrix(rotation_degrees),
            compositor.flip_matrix(flip_x, flip_y),
        )

        def move(x: float, y: float) -> Vec2:
            tx, ty = compositor.mat_vec_mul(a_mat, (float(x), float(y)))
            return (tx + float(offset[0]), ty + float(offset[1]))

        boxes: List[BoxEntry] = []
        for cr in frame.collision_rects:
            x, y, w, h = (int(v) for v in cr.rect)
            if w <= 0 or h <= 0:
                continue
            corners = [move(x, y), move(x + w, y + h)]
            x0 = int(round(min(c[0] for c in corners)))
            y0 = int(round(min(c[1] for c in corners)))
            x1 = int(round(max(c[0] for c in corners)))
            y1 = int(round(max(c[1] for c in corners)))
            role = self.role_index.get(str(cr.role or "").strip(), NO_ROLE)
            boxes.append((self.box_type_index.get(cr.type_id, UNKNOWN_TYPE), role, x0, y0, x1 - x0, y1 - y0))
        points: List[PointEntry] = []
        for cp in frame.control_points:
            # A point marks a pixel: move the pixel's centre and take the pixel it lands in, so a mirrored or turned
            # step marks the same pixel of the art (like hitboxes, which move pixel-exactly).
            px, py = move(cp.x + 0.5, cp.y + 0.5)
            role = self.role_index.get(str(cp.role or "").strip(), NO_ROLE)
            points.append((self.point_type_index.get(cp.type_id, UNKNOWN_TYPE), role, math.floor(px), math.floor(py)))
        return tuple(boxes), tuple(points)

    @staticmethod
    def _extract_geom_axis_flip(a_mat: Matrix2) -> Optional[Tuple[bool, bool]]:
        a = float(a_mat[0][0])
        b = float(a_mat[0][1])
        c = float(a_mat[1][0])
        d = float(a_mat[1][1])
        eps = 1e-5

        # Hardware flip path can represent only axis-aligned transforms here
        # (identity / 180deg equivalent with optional geometric mirror).
        if abs(b) > eps or abs(c) > eps:
            return None
        if abs(abs(a) - 1.0) > eps or abs(abs(d) - 1.0) > eps:
            return None
        return (a < 0.0, d < 0.0)

    def _render_leaf_part(
        self,
        mod: Module,
        a_mat: Matrix2,
        b_vec: Vec2,
        rotation_degrees: float,
        flip_x: bool,
        flip_y: bool,
        local_flip_x: bool = False,
        local_flip_y: bool = False,
    ) -> Optional[PartEntry]:
        base = compositor.load_module_rgba(
            project=self.project,
            mod=mod,
            full_image_cache=self.full_image_cache,
            module_cache=self.module_cache,
        )
        w, h = base.size
        if w <= 0 or h <= 0:
            return None

        geom = self._extract_geom_axis_flip(a_mat)
        if geom is not None:
            geom_hflip, geom_vflip = geom
            hflip = bool(geom_hflip) ^ bool(local_flip_x)
            vflip = bool(geom_vflip) ^ bool(local_flip_y)

            # Local (module-level) flip in the editor is an in-place pixel mirror.
            # In geometric form this is equivalent to flipping with shifted pivot.
            px = int(mod.pivot[0])
            py = int(mod.pivot[1])
            px_eff = (int(w) - px) if local_flip_x else px
            py_eff = (int(h) - py) if local_flip_y else py

            bx = int(round(float(b_vec[0])))
            by = int(round(float(b_vec[1])))
            pad_w = max(8, ((int(w) + 7) // 8) * 8)
            pad_h = max(8, ((int(h) + 7) // 8) * 8)

            if hflip:
                draw_x = bx + px_eff - pad_w
            else:
                draw_x = bx - px_eff
            if vflip:
                draw_y = by + py_eff - pad_h
            else:
                draw_y = by - py_eff

            palette = self._palette_of_module(mod)
            variant_index = self._store_part(base, palette, self._entry_byte(palette))
            return (variant_index, int(draw_x), int(draw_y), int(hflip), int(vflip))

        rendered = self._render_transformed_instance_with_local_flip(
            mod=mod,
            a_mat=a_mat,
            b_vec=(float(b_vec[0]), float(b_vec[1])),
            local_flip_x=bool(local_flip_x),
            local_flip_y=bool(local_flip_y),
        )
        if not rendered:
            return None
        img, draw_x, draw_y = rendered
        palette = self._palette_of_module(mod)
        variant_index = self._store_part(img, palette, self._entry_byte(palette))
        return (variant_index, int(draw_x), int(draw_y), 0, 0)

    def _render_transformed_instance_with_local_flip(
        self,
        mod: Module,
        a_mat: Matrix2,
        b_vec: Vec2,
        local_flip_x: bool,
        local_flip_y: bool,
    ) -> Optional[Tuple[Image.Image, int, int]]:
        base = compositor.load_module_rgba(
            project=self.project,
            mod=mod,
            full_image_cache=self.full_image_cache,
            module_cache=self.module_cache,
        )

        if local_flip_x:
            base = base.transpose(Image.FLIP_LEFT_RIGHT)
        if local_flip_y:
            base = base.transpose(Image.FLIP_TOP_BOTTOM)

        w, h = base.size
        if w <= 0 or h <= 0:
            return None

        piv = (float(mod.pivot[0]), float(mod.pivot[1]))
        ap = compositor.mat_vec_mul(a_mat, piv)
        c_vec = (float(b_vec[0]) - ap[0], float(b_vec[1]) - ap[1])

        corners = (
            (0.0, 0.0),
            (float(w), 0.0),
            (0.0, float(h)),
            (float(w), float(h)),
        )
        xs: List[float] = []
        ys: List[float] = []
        for u, v in corners:
            tx, ty = compositor.mat_vec_mul(a_mat, (u, v))
            xs.append(tx + c_vec[0])
            ys.append(ty + c_vec[1])

        min_x = int(math.floor(min(xs)))
        min_y = int(math.floor(min(ys)))
        max_x = int(math.ceil(max(xs)))
        max_y = int(math.ceil(max(ys)))
        out_w = max_x - min_x
        out_h = max_y - min_y
        if out_w <= 0 or out_h <= 0:
            return None

        inv = compositor.invert(a_mat)
        if not inv:
            return None

        dx = float(min_x) - c_vec[0]
        dy = float(min_y) - c_vec[1]
        coeff = (
            inv[0][0],
            inv[0][1],
            inv[0][0] * dx + inv[0][1] * dy,
            inv[1][0],
            inv[1][1],
            inv[1][0] * dx + inv[1][1] * dy,
        )
        transformed = base.transform(
            (out_w, out_h),
            Image.AFFINE,
            coeff,
            resample=Image.NEAREST,
            fillcolor=(0, 0, 0, 0),
        )
        if not transformed.getbbox():
            return None

        return transformed, min_x, min_y

    def _collect_leaf_instances_canvas_like(
        self,
        frame_id: str,
        parent_a: Matrix2,
        parent_b: Vec2,
        parent_rot: float,
        parent_flip_x: bool,
        parent_flip_y: bool,
        out: List[
            Tuple[
                Module,
                Matrix2,
                Vec2,
                float,
                bool,
                bool,
                bool,
                bool,
            ]
        ],
        depth: int,
        stack: set[str],
        whole: bool = False,
    ) -> None:
        """The frame's module parts through nested frames, as ``compositor.collect_leaf_instances`` (hidden modules
        left out); with ``whole`` a nested frame stored whole is one entry, the frame in the module's place."""
        if depth > 48:
            return
        frame = self.project.get_frame(frame_id)
        if not frame or frame_id in stack:
            return

        stack.add(frame_id)
        for fm in frame.fmodules:
            local_rot = float(getattr(fm, "rotation_degrees", 0.0))
            local_flip_x = bool(getattr(fm, "flip_x", False))
            local_flip_y = bool(getattr(fm, "flip_y", False))
            local_b = (float(fm.position[0]), float(fm.position[1]))
            rot_a = compositor.rotation_matrix(local_rot)
            flip_a = compositor.flip_matrix(local_flip_x, local_flip_y)

            # Match editor behavior: module-local flips mirror pixels in-place and
            # do not change module bounds/anchor placement.
            if fm.ref_type == "frame":
                local_a = compositor.mat_mul(rot_a, flip_a)
            else:
                local_a = rot_a

            a_next, b_next = compositor.compose(parent_a, parent_b, local_a, local_b)
            parent_flipped = bool(parent_flip_x) ^ bool(parent_flip_y)
            rot_next = float(parent_rot) + (-local_rot if parent_flipped else local_rot)
            flip_x_next = bool(parent_flip_x) ^ local_flip_x
            flip_y_next = bool(parent_flip_y) ^ local_flip_y

            if fm.ref_type == "module":
                mod = self._resolve_module(fm.ref_id)
                if mod:
                    out.append((mod, a_next, b_next, rot_next, flip_x_next, flip_y_next, local_flip_x, local_flip_y))
            elif fm.ref_type == "frame":
                child = self.project.get_frame(fm.ref_id) if whole else None
                if child is not None and child.store_whole:
                    if child.id not in stack and depth < 48:  # a cycle draws nothing, as below
                        out.append((child, a_next, b_next, rot_next, flip_x_next, flip_y_next, local_flip_x,
                                    local_flip_y))
                    continue
                self._collect_leaf_instances_canvas_like(
                    frame_id=fm.ref_id,
                    parent_a=a_next,
                    parent_b=b_next,
                    parent_rot=rot_next,
                    parent_flip_x=flip_x_next,
                    parent_flip_y=flip_y_next,
                    out=out,
                    depth=depth + 1,
                    stack=stack,
                    whole=whole,
                )
        stack.remove(frame_id)

    def _render_module_parts(
        self,
        module_id: str,
        offset: Vec2,
        rotation_degrees: float,
        flip_x: bool,
        flip_y: bool,
    ) -> Tuple[PartEntry, ...]:
        mod = self._resolve_module(module_id)
        if not mod:
            return tuple()
        a_mat = compositor.mat_mul(
            compositor.rotation_matrix(rotation_degrees),
            compositor.flip_matrix(flip_x, flip_y),
        )
        if self.whole_frames:
            return self._whole_frame_parts(None, mod, a_mat, (float(offset[0]), float(offset[1])))

        part = self._render_leaf_part(
            mod=mod,
            a_mat=a_mat,
            b_vec=(float(offset[0]), float(offset[1])),
            rotation_degrees=float(rotation_degrees),
            flip_x=bool(flip_x),
            flip_y=bool(flip_y),
        )
        if not part:
            return tuple()
        return (part,)

    def _render_frame_parts(
        self,
        frame: Frame,
        offset: Vec2,
        rotation_degrees: float,
        flip_x: bool,
        flip_y: bool,
    ) -> Tuple[PartEntry, ...]:
        key = (
            "frame",
            self.mapping_key,
            self._palette_key(),
            frame.id,
            self._roundf(offset[0]),
            self._roundf(offset[1]),
            self._roundf(rotation_degrees),
            int(bool(flip_x)),
            int(bool(flip_y)),
        )
        cached = self.transformed_frame_parts_cache.get(key)
        if cached is not None:
            return cached
        parent_a = compositor.mat_mul(
            compositor.rotation_matrix(rotation_degrees),
            compositor.flip_matrix(flip_x, flip_y),
        )
        parent_b = (float(offset[0]), float(offset[1]))
        if self.stored_whole(frame):
            baked_frame = self._whole_frame_parts(frame, None, parent_a, parent_b)
            self.transformed_frame_parts_cache[key] = baked_frame
            return baked_frame

        instances: List[
            Tuple[
                Module,
                Matrix2,
                Vec2,
                float,
                bool,
                bool,
                bool,
                bool,
            ]
        ] = []
        self._collect_leaf_instances_canvas_like(
            frame_id=frame.id,
            parent_a=parent_a,
            parent_b=parent_b,
            parent_rot=float(rotation_degrees),
            parent_flip_x=bool(flip_x),
            parent_flip_y=bool(flip_y),
            out=instances,
            depth=0,
            stack=set(),
            whole=True,
        )

        out_parts: List[PartEntry] = []
        for mod, a_mat, b_vec, rot_deg, part_flip_x, part_flip_y, local_flip_x, local_flip_y in instances:
            if isinstance(mod, Frame):  # a nested frame stored whole: its pictures in its place
                out_parts.extend(self._whole_frame_parts(mod, None, a_mat, b_vec))
                continue
            part = self._render_leaf_part(
                mod=mod,
                a_mat=a_mat,
                b_vec=b_vec,
                rotation_degrees=float(rot_deg),
                flip_x=bool(part_flip_x),
                flip_y=bool(part_flip_y),
                local_flip_x=bool(local_flip_x),
                local_flip_y=bool(local_flip_y),
            )
            if not part:
                continue
            out_parts.append(part)

        baked = tuple(out_parts)
        self.transformed_frame_parts_cache[key] = baked
        return baked

    def _whole_frame_parts(
        self, frame: Optional[Frame], mod: Optional[Module], a_mat: Matrix2, b_vec: Vec2,
    ) -> Tuple[PartEntry, ...]:
        """A frame stored whole: its layers (or, in the whole frames mode, a module's own, drawn on its own) placed
        like parts, under the transform ``a_mat`` about the point ``b_vec``. Moved or mirrored, it shows its upright
        layers with hardware flips (mirrored about its origin, each in its picture padded to whole tiles); turned, it is
        drawn into layers of its own."""
        geom = self._extract_geom_axis_flip(a_mat)
        if geom is None:
            layers = self._whole_frame_layers(frame, mod, a_mat, (float(b_vec[0]), float(b_vec[1])))
            return tuple((self._store_part(image, palette, self._entry_byte(palette)), x, y, 0, 0)
                         for image, x, y, palette in layers)
        hflip, vflip = geom
        key = ("module", mod.id) if mod is not None else (self.mapping_key, frame.id)  # a module is resolved already
        upright = self.upright_layers.get(key)
        if upright is None:
            upright = self._whole_frame_layers(frame, mod, self._identity_matrix(), self._identity_offset())
            self.upright_layers[key] = upright
        ox, oy = int(round(float(b_vec[0]))), int(round(float(b_vec[1])))
        parts: List[PartEntry] = []
        for image, x, y, palette in upright:
            pad_w = max(8, ((image.width + 7) // 8) * 8)
            pad_h = max(8, ((image.height + 7) // 8) * 8)
            parts.append((self._store_part(image, palette, self._entry_byte(palette)),
                          ox - x - pad_w if hflip else ox + x, oy - y - pad_h if vflip else oy + y, int(hflip), int(vflip)))
        return tuple(parts)

    def _whole_frame_layers(self, frame: Optional[Frame], mod: Optional[Module], a_mat: Matrix2,
                            b_vec: Vec2) -> Tuple[Layer, ...]:
        """The frame (or the module on its own) under a transform, drawn as the editor draws it, as one picture per
        palette and where it goes (``compositor.palette_layers``: the part on top owns each pixel, so the layers never
        overlap). Every leaf, nested frames stored whole included."""
        instances: List[Tuple[Module, Matrix2, Vec2, float, bool, bool, bool, bool]] = []
        if mod is not None:
            instances.append((mod, a_mat, b_vec, 0.0, False, False, False, False))
        elif frame is not None:
            self._collect_leaf_instances_canvas_like(frame.id, a_mat, b_vec, 0.0, False, False, instances, 0, set())
        return compositor.palette_layers(self.project, instances, self.full_image_cache, self.module_cache,
                                         self._palette_of_module)

    @staticmethod
    def _build_local_matrix(state: Dict[str, Any]) -> Matrix2x3:
        """The key's pose applied to what the source adds (root motion, swap offset): a mirrored or turned object
        mirrors or turns where its animation moves it, like the Timeline stage (ui/scene_editor/ops.local_matrix)."""
        source_offset = state.get("source_offset", (0.0, 0.0))
        pose = ConsoleBake._pose_matrix(
            float(state.get("x", 0.0)), float(state.get("y", 0.0)), float(state.get("rotation_degrees", 0.0)),
            bool(state.get("flip_x", False)), bool(state.get("flip_y", False)),
        )
        source = ConsoleBake._pose_matrix(
            float(source_offset[0]), float(source_offset[1]), float(state.get("source_rotation", 0.0)),
            bool(state.get("source_flip_x", False)), bool(state.get("source_flip_y", False)),
        )
        a, b, c, d, tx, ty = ConsoleBake._compose_matrix(pose, source)
        ax, ay = state.get("attach_offset", (0.0, 0.0))  # following a point of the parent's frame
        return (a, b, c, d, tx + float(ax), ty + float(ay))

    @staticmethod
    def _pose_matrix(tx: float, ty: float, rotation: float, flip_x: bool, flip_y: bool) -> Matrix2x3:
        """Flip, then rotate, then move (exact at 90° steps)."""
        quarter = rotation / 90.0
        if abs(quarter - round(quarter)) < 1e-9:
            cos_a, sin_a = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(round(quarter)) % 4]
        else:
            rad = math.radians(rotation)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
        sx = -1.0 if flip_x else 1.0
        sy = -1.0 if flip_y else 1.0
        return (cos_a * sx, sin_a * sx, -sin_a * sy, cos_a * sy, tx, ty)

    @staticmethod
    def _compose_matrix(parent: Matrix2x3, child: Matrix2x3) -> Matrix2x3:
        ap, bp, cp, dp, txp, typ = parent
        ac, bc, cc, dc, txc, tyc = child
        return (
            ap * ac + cp * bc,
            bp * ac + dp * bc,
            ap * cc + cp * dc,
            bp * cc + dp * dc,
            ap * txc + cp * tyc + txp,
            bp * txc + dp * tyc + typ,
        )

    @staticmethod
    def _decompose_matrix_to_frame_transform(matrix: Matrix2x3) -> Tuple[Vec2, float, bool, bool]:
        a, b, c, d, tx, ty = matrix
        sx = math.hypot(a, b)
        sy = math.hypot(c, d)
        if sx <= 1e-6 or sy <= 1e-6:
            return ((tx, ty), 0.0, False, False)

        an = a / sx
        bn = b / sx
        cn = c / sy
        dn = d / sy
        det = an * dn - bn * cn

        render_flip_x = False
        render_flip_y = det < 0.0
        if render_flip_y:
            cn = -cn
            dn = -dn

        render_rotation = math.degrees(math.atan2(bn, an))
        return ((tx, ty), render_rotation, render_flip_x, render_flip_y)

    def _world_matrix_for_object(
        self,
        scene: TimelineScene,
        state_map: Dict[str, Dict[str, Any]],
        object_id: str,
        cache: Dict[str, Matrix2x3],
    ) -> Matrix2x3:
        if object_id in cache:
            return cache[object_id]

        state = state_map.get(object_id)
        if state is None:
            cache[object_id] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            return cache[object_id]

        local = self._build_local_matrix(state)
        obj = scene.get_object(object_id)
        parent_id = obj.parent_id if obj else None
        if parent_id and (parent_id in state_map) and scene.get_object(parent_id):
            parent = self._world_matrix_for_object(scene, state_map, parent_id, cache)
            world = self._compose_matrix(parent, local)
        else:
            world = local

        cache[object_id] = world
        return world

    def _render_scene_parts(self, scene: TimelineScene, time_seconds: float) -> Tuple[PartEntry, ...]:
        state_map: Dict[str, Dict[str, Any]] = {}
        for obj in scene.objects:
            state = scene.evaluate_object_state(self.project, obj.id, time_seconds)
            if state is not None:
                state_map[obj.id] = state

        ordered_objects = sorted(scene.objects, key=lambda item: (item.draw_order, item.name.lower(), item.id))
        world_cache: Dict[str, Matrix2x3] = {}
        scene_parts: List[PartEntry] = []
        baked_mapping = self.mapping
        try:
            for obj in ordered_objects:
                # Objects with their own mapping keep it; the others follow the mapping being baked. Objects with a
                # palette swap of their own have it in their pieces; the others follow the swap the game draws with.
                self._set_current_mapping(scene.object_mapping(self.project, obj.id, baked_mapping))
                self._set_palette_state(*self._object_colours(scene, obj.id))
                scene_parts.extend(self._render_scene_object_parts(scene, state_map, obj.id, world_cache))
        finally:
            self._set_current_mapping(baked_mapping)
            self._set_palette_state(None, False)
        return tuple(scene_parts)

    def _render_scene_object_parts(
        self,
        scene: TimelineScene,
        state_map: Dict[str, Dict[str, Any]],
        object_id: str,
        world_cache: Dict[str, Matrix2x3],
    ) -> Tuple[PartEntry, ...]:
        state = state_map.get(object_id)
        if not state_shows(state):
            return ()
        world_matrix = self._world_matrix_for_object(scene, state_map, object_id, world_cache)
        offset, rotation, flip_x, flip_y = self._decompose_matrix_to_frame_transform(world_matrix)

        source_type = str(state.get("source_type", "none") or "none").strip().lower()
        if source_type == "module":
            source_id = state.get("source_id")
            if source_id is None:
                return ()
            return self._render_module_parts(
                module_id=str(source_id),
                offset=offset,
                rotation_degrees=float(rotation),
                flip_x=bool(flip_x),
                flip_y=bool(flip_y),
            )

        if source_type not in ("frame", "animation"):
            return ()
        frame_id = state.get("frame_id") or state.get("source_id")
        frame = self.project.get_frame(str(frame_id)) if frame_id is not None else None
        if not frame:
            return ()
        return self._render_frame_parts(
            frame=frame,
            offset=offset,
            rotation_degrees=float(rotation),
            flip_x=bool(flip_x),
            flip_y=bool(flip_y),
        )

    def bake(self) -> None:
        """Every mapping in turn: modules, frames, animations, scenes."""
        empty_render = self._intern_render_frame(())

        for mapping in self.mappings:
            frame_render_by_id: Dict[str, int] = {}
            self._set_current_mapping(mapping)

            # 1) Module render entries.
            for mod in self.project.modules:
                parts = self._render_module_parts(mod.id, self._identity_offset(), 0.0, False, False)
                render_idx = self._intern_render_frame(parts)
                self.module_render_frames.append(render_idx)

            # 2) Base frame render entries.
            for frame in self.project.frames:
                parts = self._render_frame_parts(frame, self._identity_offset(), 0.0, False, False)
                boxes, points = self._frame_markers(frame, self._identity_offset(), 0.0, False, False)
                render_idx = self._intern_render_frame(parts, boxes, points)
                self.frame_render_frames.append(render_idx)
                frame_render_by_id[frame.id] = render_idx

            # 3) Animations.
            animation_index = {a.id: i for i, a in enumerate(self.project.animations)}
            for anim in self.project.animations:
                first_step = len(self.anim_steps)
                source_fps = int(anim.fps) if int(anim.fps) > 0 else 10
                exported_step_of: List[int] = []  # editor step index -> exported step index (-1: skipped)
                for af in anim.aframes:
                    frame = self.project.get_frame(af.frame_id)
                    if not frame:
                        exported_step_of.append(-1)
                        continue

                    off = (float(af.offset[0]), float(af.offset[1]))
                    rot = float(getattr(af, "rotation_degrees", 0.0))
                    fx = bool(getattr(af, "flip_x", False))
                    fy = bool(getattr(af, "flip_y", False))
                    is_identity = (off == (0.0, 0.0)) and (not fx) and (not fy) and (abs(rot) <= 1e-9)
                    if is_identity:
                        render_idx = frame_render_by_id.get(frame.id, empty_render)
                    else:
                        parts = self._render_frame_parts(frame, off, rot, fx, fy)
                        boxes, points = self._frame_markers(frame, off, rot, fx, fy)
                        render_idx = self._intern_render_frame(parts, boxes, points)

                    duration_ticks = playback.console_frames(anim, af)  # video frames, as the editor previews them
                    first_event = len(self.step_events)
                    for event in getattr(af, "events", []) or []:
                        type_index = self.event_type_index.get(event.type_id)
                        if type_index is None:
                            continue  # event type no longer exists
                        self.step_events.append((type_index, max(-32768, min(32767, int(event.value)))))
                    event_count = min(255, len(self.step_events) - first_event)
                    exported_step_of.append(len(self.anim_steps) - first_step)
                    self.anim_steps.append((render_idx, duration_ticks, first_event, event_count))

                step_count = len(self.anim_steps) - first_step
                if step_count <= 0:
                    first_step = len(self.anim_steps)
                    self.anim_steps.append((empty_render, 1, 0, 0))
                    step_count = 1

                # "Loop from" points at an editor step; use the first exported step at or after it.
                loop_start = 0
                if str(anim.playback_type) == "loop" and int(getattr(anim, "loop_start", 0) or 0) > 0:
                    later = [i for i in exported_step_of[int(anim.loop_start):] if i >= 0]
                    loop_start = later[0] if later else 0
                next_id = getattr(anim, "next_animation_id", None)
                self.anim_records.append(
                    AnimRecord(
                        first_step=first_step,
                        step_count=step_count,
                        fps=source_fps,
                        playback=self._playback_code(str(anim.playback_type)),
                        loop_start=loop_start,
                        next_animation=animation_index.get(next_id, NO_ANIMATION) if next_id else NO_ANIMATION,
                        loop_count=max(0, min(0xFFFF, int(anim.loop_count or 0))),
                    )
                )

            # 4) Scenes sampled at scene FPS.
            for scene in self.project.timeline_scenes:
                first_sample = len(self.scene_samples)
                duration_frames = max(1, scene.duration_in_frames())
                fps = max(1, int(scene.fps))

                for frame_idx in range(duration_frames):
                    t = float(frame_idx) / float(fps)
                    parts = self._render_scene_parts(scene, t)
                    render_idx = self._intern_render_frame(parts)
                    self.scene_samples.append(render_idx)

                sample_count = len(self.scene_samples) - first_sample
                if sample_count <= 0:
                    first_sample = len(self.scene_samples)
                    self.scene_samples.append(empty_render)
                    sample_count = 1

                duration_ticks = max(1, int(round(float(scene.duration_seconds) * 60.0)))
                self.scene_records.append(
                    SceneRecord(
                        first_sample=first_sample,
                        sample_count=sample_count,
                        fps=fps,
                        duration_ticks=duration_ticks,
                        loop=1 if scene.loop else 0,
                    )
                )

