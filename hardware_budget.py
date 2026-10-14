"""Hardware sprite budget: how a frame (or a whole scene) maps onto console sprite hardware.

Mega Drive model, matching the SGDK exporter and runtime (examples/sgdk):
- every visible part becomes one SGDK sprite whose image is padded to whole 8×8 tiles; axis-aligned parts use the
  module image with hardware flips, rotated parts are baked (``SGDKBakeContext._render_leaf_part``);
- rescomp cuts each sprite into VDP sprites of at most 4×4 tiles (32×32 px). This model cuts on that grid and
  skips blocks that are completely transparent; rescomp's optimiser can occasionally do a little better, so the
  numbers are a safe estimate;
- the VDP shows a limited number of sprites per screen and per scanline, and a limited number of sprite pixels per
  scanline (the rest of the line's sprites disappear);
- video memory: the export stores each part image once (flips are hardware bits) as 4 bpp tiles in palette indices,
  and hardware sprite blocks with the same pixels share their tiles (``SGDKBakeContext._ensure_variant``). The runtime
  keeps every tile in VRAM, so the project's total (``export_tiles``) is what has to fit.

SNES model (budget only, no exporter yet): a game uses two square sprite sizes (OBSEL, e.g. 8×8 and 16×16). Every part
is padded to the large size and cut on that grid; a cell whose pixels sit in at most half of its small squares takes
small sprites, otherwise one large sprite. The PPU shows 128 sprites, 32 per scanline and 34 tiles (272 px) per line.

No wx here: the editor draws the result, tests check it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import compositor
import consoles
import palettes
from models import Frame, ModuleMapping, Project, state_shows

Matrix = Tuple[Tuple[float, float], Tuple[float, float]]
IDENTITY: Matrix = ((1.0, 0.0), (0.0, 1.0))
TILE = 8
SPRITE_BLOCK = 32  # the export cuts part images into hardware sprites of at most 32×32 px


@dataclass(frozen=True)
class HardwareProfile:
    key: str
    name: str
    sprites_per_screen: int
    sprites_per_line: int
    pixels_per_line: int
    max_sprite_tiles: int = 4  # VDP sprites are 1–4 tiles wide and high
    sizes: Tuple[int, int] = (0, 0)  # square sprites of two sizes (small, large px), as on the SNES; (0, 0): any size
    vram_tiles: int = 0  # tiles the Mega Drive export can keep in video memory (0: not counted for this console)


def _profile(console: consoles.Console, setup: consoles.BudgetSetup) -> HardwareProfile:
    """A budget profile from the console database: the setup's screen mode, and video memory where an export keeps
    the tiles (the Mega Drive's SGDK export)."""
    mode = console.mode(setup.mode)
    assert mode is not None, setup.key
    largest = max(max(w, h) for w, h in console.sprites.sizes)
    return HardwareProfile(
        setup.key, setup.name, mode.sprites_per_screen, mode.sprites_per_line, mode.sprite_pixels_per_line,
        max_sprite_tiles=largest // console.tile_size, sizes=setup.sizes,
        vram_tiles=console.sprites.tiles if console.exporter else 0,
    )


PROFILES: List[HardwareProfile] = [_profile(console, setup) for console, setup in consoles.budget_setups()]


def profile_by_key(key: Optional[str]) -> Optional[HardwareProfile]:
    return next((p for p in PROFILES if p.key == key), None)


MEGA_DRIVE_H40, MEGA_DRIVE_H32 = profile_by_key("md_h40"), profile_by_key("md_h32")
SNES_8_16, SNES_16_32 = profile_by_key("snes_8_16"), profile_by_key("snes_16_32")


@dataclass
class HwSprite:
    """One hardware (VDP) sprite on screen, in pixels."""

    x: int
    y: int
    w: int
    h: int


@dataclass
class HwPart:
    """One exported part (one SGDK sprite): its padded area on screen and the VDP sprites it needs."""

    x: int
    y: int
    w: int
    h: int
    hflip: bool
    vflip: bool
    sprites: List[HwSprite] = field(default_factory=list)
    vram: Tuple[Tuple[int, int], ...] = ()  # (tile block id, tiles) of each block the export stores for this part

    @property
    def tiles(self) -> int:
        return sum((s.w // TILE) * (s.h // TILE) for s in self.sprites)


def vram_tiles(parts: Iterable[HwPart]) -> int:
    """Tiles of video memory these parts need: each stored block once, however often it is drawn or flipped."""
    blocks: Dict[int, int] = {}
    for part in parts:
        blocks.update(part.vram)
    return sum(blocks.values())


@dataclass
class Budget:
    profile: HardwareProfile
    parts: List[HwPart]

    @property
    def sprites(self) -> List[HwSprite]:
        return [s for part in self.parts for s in part.sprites]

    @property
    def sprite_count(self) -> int:
        return sum(len(part.sprites) for part in self.parts)

    @property
    def tile_count(self) -> int:
        return sum(part.tiles for part in self.parts)

    @property
    def unique_tiles(self) -> int:
        """Tiles of video memory what is shown needs (a part drawn twice or flipped needs its tiles once)."""
        return vram_tiles(self.parts)

    def lines(self) -> Dict[int, Tuple[int, int]]:
        """Scanline y -> (sprites on it, sprite pixels on it)."""
        usage: Dict[int, List[int]] = {}
        for s in self.sprites:
            for y in range(s.y, s.y + s.h):
                entry = usage.setdefault(y, [0, 0])
                entry[0] += 1
                entry[1] += s.w
        return {y: (v[0], v[1]) for y, v in usage.items()}

    def worst_line(self) -> Tuple[int, int]:
        """(most sprites on one line, most sprite pixels on one line)."""
        lines = self.lines().values()
        return (max((c for c, _p in lines), default=0), max((p for _c, p in lines), default=0))

    def over_lines(self) -> List[Tuple[int, int]]:
        """Runs of scanlines (first, last) where sprites would drop out."""
        bad = sorted(
            y for y, (count, pixels) in self.lines().items()
            if count > self.profile.sprites_per_line or pixels > self.profile.pixels_per_line
        )
        runs: List[Tuple[int, int]] = []
        for y in bad:
            if runs and y == runs[-1][1] + 1:
                runs[-1] = (runs[-1][0], y)
            else:
                runs.append((y, y))
        return runs

    def over_budget(self) -> bool:
        return self.sprite_count > self.profile.sprites_per_screen or bool(self.over_lines())

    def summary(self) -> str:
        count, pixels = self.worst_line()
        p = self.profile
        return (
            f"{self.sprite_count}/{p.sprites_per_screen} sprites · "
            f"busiest line {count}/{p.sprites_per_line} sprites, {pixels}/{p.pixels_per_line} px"
        )


class BudgetCalculator:
    """Turns frames into hardware sprites. Caches module images and their 8×8 block masks."""

    def __init__(self) -> None:
        self.generation = 0  # counts clear(): what was worked out before belongs to older pixels
        self._images: Dict[str, Any] = {}
        self._modules: Dict[str, Any] = {}
        self._module_keys: Dict[str, Any] = {}
        self._blocks: Dict[Any, List[Tuple[int, int, int, int]]] = {}
        # Video memory: the export's palettes, each image's stored blocks and one id per distinct block of tiles.
        self._palette_state: Any = None
        self._image_info: Dict[str, Tuple[str, Tuple[int, ...]]] = {}  # image id -> (palette id, key colour)
        self._palettes: Dict[str, List[palettes.RGB]] = {}  # palette id -> colours
        self._first_palette = ""  # vector shapes use it
        self._nearest: Dict[str, Dict[palettes.RGB, int]] = {}
        self._vram: Dict[Any, Tuple[Tuple[int, int], ...]] = {}
        self._block_ids: Dict[bytes, int] = {}

    def clear(self) -> None:
        self.generation += 1
        self._images.clear()
        self._modules.clear()
        self._module_keys.clear()
        self._blocks.clear()
        self._palette_state = None
        self._image_info.clear()
        self._palettes.clear()
        self._nearest.clear()
        self._vram.clear()
        self._block_ids.clear()

    # ------------------------------------------------------------------ public
    def frame_budget(
        self,
        project: Project,
        frame: Optional[Frame],
        mapping: Optional[ModuleMapping],
        profile: HardwareProfile,
        a: Matrix = IDENTITY,
        b: Tuple[float, float] = (0.0, 0.0),
    ) -> Budget:
        return Budget(profile, self.frame_parts(project, frame, mapping, profile, a, b) if frame else [])

    def frame_parts(
        self,
        project: Project,
        frame: Frame,
        mapping: Optional[ModuleMapping],
        profile: HardwareProfile,
        a: Matrix = IDENTITY,
        b: Tuple[float, float] = (0.0, 0.0),
    ) -> List[HwPart]:
        self._sync_palettes(project)
        instances: List[Any] = []
        compositor.collect_leaf_instances(project, frame.id, mapping, a, b, 0.0, False, False, instances, 0, set())
        parts: List[HwPart] = []
        for mod, a_mat, b_vec, _rot, _fx, _fy, local_fx, local_fy in instances:
            part = self._leaf_part(project, mod, a_mat, b_vec, local_fx, local_fy, profile)
            if part is not None:
                parts.append(part)
        return parts

    def module_parts(
        self,
        project: Project,
        module_id: str,
        mapping: Optional[ModuleMapping],
        profile: HardwareProfile,
        a: Matrix = IDENTITY,
        b: Tuple[float, float] = (0.0, 0.0),
    ) -> List[HwPart]:
        self._sync_palettes(project)
        mod = compositor.resolve_module(project, module_id, mapping)
        if mod is None:
            return []
        part = self._leaf_part(project, mod, a, b, False, False, profile)
        return [part] if part else []

    def export_tiles(self, project: Project, mappings: Sequence[Optional[ModuleMapping]]) -> int:
        """Tiles of video memory the Mega Drive export of the whole project needs: every module, frame, animation
        step and scene sample for each mapping, as ``SGDKBakeContext.bake`` stores them."""
        profile = MEGA_DRIVE_H40  # the stored blocks do not depend on the screen mode
        blocks: Dict[int, int] = {}
        seen: Dict[Any, Tuple[Tuple[int, int], ...]] = {}

        def add_frame(frame: Frame, mapping: Optional[ModuleMapping], a: Matrix = IDENTITY,
                      b: Tuple[float, float] = (0.0, 0.0)) -> None:
            # Moved by whole pixels and turned in 90° steps, a frame's images stay the same (exactly): reuse them.
            whole = all(v in (-1.0, 0.0, 1.0) for row in a for v in row) and all(float(v).is_integer() for v in b)
            key = (frame.id, mapping.id if mapping else None, a) if whole else None
            found = seen.get(key) if key is not None else None
            if found is None:
                found = tuple(pair for part in self.frame_parts(project, frame, mapping, profile, a, b) for pair in part.vram)
                if key is not None:
                    seen[key] = found
            blocks.update(found)

        for mapping in mappings:
            for mod in project.modules:
                for part in self.module_parts(project, mod.id, mapping, profile):
                    blocks.update(part.vram)
            for frame in project.frames:
                add_frame(frame, mapping)
            for anim in project.animations:
                for af in anim.aframes:
                    frame = project.get_frame(af.frame_id)
                    if frame is not None:
                        add_frame(frame, mapping, *frame_transform(
                            af.offset, float(getattr(af, "rotation_degrees", 0.0)), bool(af.flip_x), bool(af.flip_y)))
            for scene in project.timeline_scenes:
                for uses in scene_uses(project, scene, mapping):
                    for kind, source, use_mapping, a, b in uses:
                        if kind == "module":
                            for part in self.module_parts(project, source, use_mapping, profile, a, b):
                                blocks.update(part.vram)
                        else:
                            add_frame(source, use_mapping, a, b)
        return sum(blocks.values())

    # ------------------------------------------------------------------ internals
    def _sync_palettes(self, project: Project) -> None:
        """Blocks are compared in palette slots like the export's: start over when a palette, an image's palette or key
        colour changes (edited image files clear the whole calculator)."""
        state = palettes.signature(project)
        if state != self._palette_state:
            self._palette_state = state
            self._image_info = {a.id: (project.image_palette(a).id, tuple(a.transparent_color or ()))
                                for a in project.images}
            self._palettes = {p.id: palettes.colours_of(project, p) for p in project.palettes}
            self._first_palette = project.default_palette().id
            self._nearest = {pid: {} for pid in self._palettes}
            self._vram.clear()
            self._block_ids.clear()

    def _palette_of(self, mod: Any) -> str:
        """The module's palette: its image's (vector shapes use the first), as SGDKBakeContext._palette_of_module."""
        info = self._image_info.get(mod.image_id) if mod.type == "MD_IMAGE" else None
        return info[0] if info else self._first_palette

    def _stored_blocks(self, key: Any, image: Any, palette: str) -> Tuple[Tuple[int, int], ...]:
        """(block id, tiles) of each hardware sprite block the export stores for this image: padded to whole tiles,
        cut on the 32 px grid, empty blocks skipped; blocks with the same tiles (in palette indices) share an id."""
        found = self._vram.get((key, palette))
        if found is not None:
            return found
        from PIL import Image as PILImage

        rgba = image.convert("RGBA")
        colours = self._palettes.get(palette) or self._palettes.get(self._first_palette) or []
        lookup = self._nearest.setdefault(palette, {})
        data = rgba.tobytes()
        table: Dict[bytes, int] = {}
        indices = bytearray(len(data) // 4)
        for i in range(0, len(data), 4):
            pixel = data[i:i + 4]
            value = table.get(pixel)
            if value is None:
                value = 0 if pixel[3] == 0 else palettes.nearest((pixel[0], pixel[1], pixel[2]), colours, lookup) + 1
                table[pixel] = value
            indices[i >> 2] = value
        pad_w, pad_h = _pad(rgba.width), _pad(rgba.height)
        padded = PILImage.new("L", (pad_w, pad_h), 0)
        padded.paste(PILImage.frombytes("L", rgba.size, bytes(indices)), (0, 0))
        stored = []
        for by in range(0, pad_h, SPRITE_BLOCK):
            for bx in range(0, pad_w, SPRITE_BLOCK):
                tiles_w, tiles_h = min(SPRITE_BLOCK, pad_w - bx) // TILE, min(SPRITE_BLOCK, pad_h - by) // TILE
                if not padded.crop((bx, by, bx + tiles_w * TILE, by + tiles_h * TILE)).getbbox():
                    continue
                # Tiles in VDP sprite order: down each column, then the next column.
                tiles = b"".join(
                    padded.crop((bx + tx * TILE, by + ty * TILE, bx + (tx + 1) * TILE, by + (ty + 1) * TILE)).tobytes()
                    for tx in range(tiles_w) for ty in range(tiles_h)
                )
                stored.append((self._block_ids.setdefault(tiles, len(self._block_ids)), tiles_w * tiles_h))
        found = self._vram[(key, palette)] = tuple(stored)
        return found

    def _module_image(self, project: Project, mod: Any) -> Any:
        info = self._image_info.get(mod.image_id) if mod.type == "MD_IMAGE" else None
        key = (mod.type, tuple(mod.rect), tuple(mod.pivot), bool(getattr(mod, "rotated", False)), mod.image_id,
               tuple(mod.color) if mod.color else None, tuple(mod.params) if mod.params else None,
               info[1] if info else None)  # the image's key colour decides which pixels are transparent
        if self._module_keys.get(mod.id) != key:
            self._modules.pop(mod.id, None)
            self._module_keys[mod.id] = key
        return compositor.load_module_rgba(project, mod, self._images, self._modules)

    def _leaf_part(
        self,
        project: Project,
        mod: Any,
        a_mat: Matrix,
        b_vec: Tuple[float, float],
        local_fx: bool,
        local_fy: bool,
        profile: HardwareProfile,
    ) -> Optional[HwPart]:
        if int(mod.rect[2]) <= 0 or int(mod.rect[3]) <= 0:
            return None  # hidden, like the SGDK exporter
        base = self._module_image(project, mod)
        w, h = base.size
        if w <= 0 or h <= 0:
            return None
        geom = _axis_flip(a_mat)
        if geom is not None:
            # Uploaded as the plain module image; flips are hardware bits (SGDK _render_leaf_part).
            hflip = geom[0] ^ bool(local_fx)
            vflip = geom[1] ^ bool(local_fy)
            px, py = int(mod.pivot[0]), int(mod.pivot[1])
            px_eff = w - px if local_fx else px
            py_eff = h - py if local_fy else py
            bx, by = int(round(b_vec[0])), int(round(b_vec[1]))
            pad_w, pad_h = _pad(w, profile), _pad(h, profile)
            x = bx + px_eff - pad_w if hflip else bx - px_eff
            y = by + py_eff - pad_h if vflip else by - py_eff
            key = ("module", mod.id, self._module_keys.get(mod.id))
            part = _place(x, y, pad_w, pad_h, hflip, vflip, self._image_blocks(key, base, profile))
            part.vram = self._stored_blocks(key, base, self._palette_of(mod))
            return part
        # Rotated (non axis-aligned) parts are baked into a new image, padded right / down.
        image, x, y = _baked(base, mod, a_mat, b_vec, local_fx, local_fy)
        if image is None:
            return None
        key = ("baked", mod.id, self._module_keys.get(mod.id), a_mat, bool(local_fx), bool(local_fy))
        part = _place(x, y, _pad(image.size[0], profile), _pad(image.size[1], profile), False, False,
                      self._image_blocks(key, image, profile))
        part.vram = self._stored_blocks(key, image, self._palette_of(mod))
        return part

    def _image_blocks(self, key: Any, image: Any, profile: HardwareProfile) -> List[Tuple[int, int, int, int]]:
        """Hardware sprite blocks (x, y, w, h in px, in the unflipped padded image) that hold any pixel."""
        cache_key = (key, profile.max_sprite_tiles, profile.sizes)
        cached = self._blocks.get(cache_key)
        if cached is not None:
            return cached
        alpha = image.getchannel("A") if image.mode == "RGBA" else None
        width, height = image.size

        def filled(x: int, y: int, w: int, h: int) -> bool:
            if alpha is None:
                return x < width and y < height
            if x >= width or y >= height:
                return False
            return bool(alpha.crop((x, y, min(x + w, width), min(y + h, height))).getbbox())

        pad_w, pad_h = _pad(width, profile), _pad(height, profile)
        blocks = []
        small, large = profile.sizes
        if large:
            # Square sprites: a large one per cell, or small ones where the pixels fill at most half of the cell.
            for by in range(0, pad_h, large):
                for bx in range(0, pad_w, large):
                    squares = [(bx + sx, by + sy) for sy in range(0, large, small) for sx in range(0, large, small)]
                    used = [(x, y) for x, y in squares if filled(x, y, small, small)]
                    if not used:
                        continue
                    if 2 * len(used) <= len(squares):
                        blocks += [(x, y, small, small) for x, y in used]
                    else:
                        blocks.append((bx, by, large, large))
        else:
            step = profile.max_sprite_tiles * TILE
            for by in range(0, pad_h, step):
                for bx in range(0, pad_w, step):
                    bw, bh = min(step, pad_w - bx), min(step, pad_h - by)
                    if filled(bx, by, bw, bh):
                        blocks.append((bx, by, bw, bh))
        self._blocks[cache_key] = blocks
        return blocks


def frame_transform(offset: Sequence[float], rotation: float, flip_x: bool, flip_y: bool) -> Tuple[Matrix, Tuple[float, float]]:
    """A frame drawn flipped, then rotated, then moved (an animation step, a scene object): the export's matrix."""
    a = compositor.mat_mul(compositor.rotation_matrix(float(rotation)), compositor.flip_matrix(bool(flip_x), bool(flip_y)))
    return a, (float(offset[0]), float(offset[1]))


def scene_uses(project: Project, scene: Any, mapping: Optional[ModuleMapping]) -> Iterable[List[Tuple[str, Any, Any, Matrix, Tuple[float, float]]]]:
    """Per sample of a scene (at its fps, as the export samples it): (kind, module id or frame, mapping, a, b) of every
    visible object. Objects with their own mapping keep it, the others follow ``mapping``."""
    from ui.scene_editor import ops as scene_ops  # wx-free

    fps = max(1, int(scene.fps))
    for index in range(max(1, scene.duration_in_frames())):
        states = scene_ops.evaluate_states(project, scene, float(index) / float(fps))
        cache: Dict[str, Any] = {}
        uses: List[Tuple[str, Any, Any, Matrix, Tuple[float, float]]] = []
        for obj in scene.objects:
            state = states.get(obj.id)
            if not state_shows(state):
                continue
            offset, rotation, flip_x, flip_y = _decompose(scene_ops.world_matrix(scene, states, obj.id, cache))
            a, b = frame_transform(offset, rotation, flip_x, flip_y)
            use_mapping = scene.object_mapping(project, obj.id, mapping)
            source_type = str(state.get("source_type", "none") or "none").strip().lower()
            if source_type == "module" and state.get("source_id") is not None:
                uses.append(("module", str(state["source_id"]), use_mapping, a, b))
            elif source_type in ("frame", "animation"):
                frame_id = state.get("frame_id") or state.get("source_id")
                frame = project.get_frame(str(frame_id)) if frame_id is not None else None
                if frame is not None:
                    uses.append(("frame", frame, use_mapping, a, b))
        yield uses


def _decompose(matrix: Sequence[float]) -> Tuple[Tuple[float, float], float, bool, bool]:
    """(offset, rotation, flip x, flip y) of an object's matrix, as SGDKBakeContext._decompose_matrix_to_frame_transform."""
    a, b, c, d, tx, ty = matrix
    sx, sy = math.hypot(a, b), math.hypot(c, d)
    if sx <= 1e-6 or sy <= 1e-6:
        return (tx, ty), 0.0, False, False
    flip_y = (a / sx) * (d / sy) - (b / sx) * (c / sy) < 0.0
    return (tx, ty), math.degrees(math.atan2(b / sx, a / sx)), False, flip_y


def _pad(size: int, profile: Optional[HardwareProfile] = None) -> int:
    """Whole tiles (the export's padding); whole large sprites for a console with square sprites."""
    grid = profile.sizes[1] if profile is not None and profile.sizes[1] else TILE
    return max(grid, ((int(size) + grid - 1) // grid) * grid)


def _axis_flip(a: Matrix) -> Optional[Tuple[bool, bool]]:
    """Hardware can only flip: identity / mirror / 180° (SGDK _extract_geom_axis_flip)."""
    eps = 1e-5
    if abs(a[0][1]) > eps or abs(a[1][0]) > eps:
        return None
    if abs(abs(a[0][0]) - 1.0) > eps or abs(abs(a[1][1]) - 1.0) > eps:
        return None
    return (a[0][0] < 0.0, a[1][1] < 0.0)


def _place(x: int, y: int, pad_w: int, pad_h: int, hflip: bool, vflip: bool,
           blocks: Sequence[Tuple[int, int, int, int]]) -> HwPart:
    part = HwPart(x, y, pad_w, pad_h, hflip, vflip)
    for bx, by, bw, bh in blocks:
        sx = x + (pad_w - bx - bw if hflip else bx)
        sy = y + (pad_h - by - bh if vflip else by)
        part.sprites.append(HwSprite(sx, sy, bw, bh))
    return part


def _baked(base: Any, mod: Any, a: Matrix, b: Tuple[float, float], local_fx: bool, local_fy: bool) -> Tuple[Any, int, int]:
    """Bake a rotated part like SGDKBakeContext._render_transformed_instance_with_local_flip."""
    from PIL import Image as PILImage

    if local_fx:
        base = base.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
    if local_fy:
        base = base.transpose(PILImage.Transpose.FLIP_TOP_BOTTOM)
    w, h = base.size
    ap = compositor.mat_vec_mul(a, (float(mod.pivot[0]), float(mod.pivot[1])))
    c = (float(b[0]) - ap[0], float(b[1]) - ap[1])
    xs, ys = [], []
    for u, v in ((0.0, 0.0), (float(w), 0.0), (0.0, float(h)), (float(w), float(h))):
        tx, ty = compositor.mat_vec_mul(a, (u, v))
        xs.append(tx + c[0])
        ys.append(ty + c[1])
    min_x, min_y = int(math.floor(min(xs))), int(math.floor(min(ys)))
    out_w, out_h = int(math.ceil(max(xs))) - min_x, int(math.ceil(max(ys))) - min_y
    inv = compositor.invert(a)
    if out_w <= 0 or out_h <= 0 or not inv:
        return None, 0, 0
    dx, dy = float(min_x) - c[0], float(min_y) - c[1]
    coeff = (inv[0][0], inv[0][1], inv[0][0] * dx + inv[0][1] * dy, inv[1][0], inv[1][1], inv[1][0] * dx + inv[1][1] * dy)
    image = base.transform((out_w, out_h), PILImage.AFFINE, coeff, resample=PILImage.NEAREST, fillcolor=(0, 0, 0, 0))
    if not image.getbbox():
        return None, 0, 0
    return image, min_x, min_y
