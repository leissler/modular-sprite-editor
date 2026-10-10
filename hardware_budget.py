"""Hardware sprite budget: how a frame (or a whole scene) maps onto console sprite hardware.

Mega Drive model, matching the SGDK exporter and runtime (examples/sgdk):
- every visible part becomes one SGDK sprite whose image is padded to whole 8×8 tiles; axis-aligned parts use the
  module image with hardware flips, rotated parts are baked (``SGDKBakeContext._render_leaf_part``);
- rescomp cuts each sprite into VDP sprites of at most 4×4 tiles (32×32 px). This model cuts on that grid and
  skips blocks that are completely transparent; rescomp's optimiser can occasionally do a little better, so the
  numbers are a safe estimate;
- the VDP shows a limited number of sprites per screen and per scanline, and a limited number of sprite pixels per
  scanline (the rest of the line's sprites disappear).

No wx here: the editor draws the result, tests check it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from models import Frame, ModuleMapping, Project, RetroAnimatorExporter as _RA

Matrix = Tuple[Tuple[float, float], Tuple[float, float]]
IDENTITY: Matrix = ((1.0, 0.0), (0.0, 1.0))
TILE = 8


@dataclass(frozen=True)
class HardwareProfile:
    key: str
    name: str
    sprites_per_screen: int
    sprites_per_line: int
    pixels_per_line: int
    max_sprite_tiles: int = 4  # VDP sprites are 1–4 tiles wide and high


MEGA_DRIVE_H40 = HardwareProfile("md_h40", "Mega Drive H40 (320 px)", 80, 20, 320)
MEGA_DRIVE_H32 = HardwareProfile("md_h32", "Mega Drive H32 (256 px)", 64, 16, 256)
PROFILES: List[HardwareProfile] = [MEGA_DRIVE_H40, MEGA_DRIVE_H32]


def profile_by_key(key: Optional[str]) -> Optional[HardwareProfile]:
    return next((p for p in PROFILES if p.key == key), None)


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

    @property
    def tiles(self) -> int:
        return sum((s.w // TILE) * (s.h // TILE) for s in self.sprites)


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
            f"{self.sprite_count}/{p.sprites_per_screen} sprites · {self.tile_count} tiles · "
            f"busiest line {count}/{p.sprites_per_line} sprites, {pixels}/{p.pixels_per_line} px"
        )


class BudgetCalculator:
    """Turns frames into hardware sprites. Caches module images and their 8×8 block masks."""

    def __init__(self) -> None:
        self._images: Dict[str, Any] = {}
        self._modules: Dict[str, Any] = {}
        self._module_keys: Dict[str, Any] = {}
        self._blocks: Dict[Any, List[Tuple[int, int, int, int]]] = {}

    def clear(self) -> None:
        self._images.clear()
        self._modules.clear()
        self._module_keys.clear()
        self._blocks.clear()

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
        instances: List[Any] = []
        _RA._collect_leaf_instances(project, frame.id, mapping, a, b, 0.0, False, False, instances, 0, set())
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
        mod = _RA._resolve_module(project, module_id, mapping)
        if mod is None:
            return []
        part = self._leaf_part(project, mod, a, b, False, False, profile)
        return [part] if part else []

    # ------------------------------------------------------------------ internals
    def _module_image(self, project: Project, mod: Any) -> Any:
        key = (mod.type, tuple(mod.rect), tuple(mod.pivot), bool(getattr(mod, "rotated", False)), mod.image_id,
               tuple(mod.color) if mod.color else None, tuple(mod.params) if mod.params else None)
        if self._module_keys.get(mod.id) != key:
            self._modules.pop(mod.id, None)
            self._module_keys[mod.id] = key
        return _RA._load_module_rgba(project, mod, self._images, self._modules)

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
            pad_w, pad_h = _pad(w), _pad(h)
            x = bx + px_eff - pad_w if hflip else bx - px_eff
            y = by + py_eff - pad_h if vflip else by - py_eff
            blocks = self._image_blocks(("module", mod.id, self._module_keys.get(mod.id)), base, profile)
            return _place(x, y, pad_w, pad_h, hflip, vflip, blocks)
        # Rotated (non axis-aligned) parts are baked into a new image, padded right / down.
        image, x, y = _baked(base, mod, a_mat, b_vec, local_fx, local_fy)
        if image is None:
            return None
        key = ("baked", mod.id, self._module_keys.get(mod.id), a_mat, bool(local_fx), bool(local_fy))
        blocks = self._image_blocks(key, image, profile)
        return _place(x, y, _pad(image.size[0]), _pad(image.size[1]), False, False, blocks)

    def _image_blocks(self, key: Any, image: Any, profile: HardwareProfile) -> List[Tuple[int, int, int, int]]:
        """VDP sprite blocks (x, y, w, h in px, in the unflipped padded image) that hold any pixel."""
        cached = self._blocks.get(key)
        if cached is not None:
            return cached
        alpha = image.getchannel("A") if image.mode == "RGBA" else None
        pad_w, pad_h = _pad(image.size[0]), _pad(image.size[1])
        step = profile.max_sprite_tiles * TILE
        blocks = []
        for by in range(0, pad_h, step):
            for bx in range(0, pad_w, step):
                bw, bh = min(step, pad_w - bx), min(step, pad_h - by)
                if alpha is not None:
                    crop = alpha.crop((bx, by, min(bx + bw, image.size[0]), min(by + bh, image.size[1])))
                    if crop.size[0] <= 0 or crop.size[1] <= 0 or not crop.getbbox():
                        continue
                blocks.append((bx, by, bw, bh))
        self._blocks[key] = blocks
        return blocks


def _pad(size: int) -> int:
    return max(TILE, ((int(size) + TILE - 1) // TILE) * TILE)


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
    ap = _RA._mat_vec_mul(a, (float(mod.pivot[0]), float(mod.pivot[1])))
    c = (float(b[0]) - ap[0], float(b[1]) - ap[1])
    xs, ys = [], []
    for u, v in ((0.0, 0.0), (float(w), 0.0), (0.0, float(h)), (float(w), float(h))):
        tx, ty = _RA._mat_vec_mul(a, (u, v))
        xs.append(tx + c[0])
        ys.append(ty + c[1])
    min_x, min_y = int(math.floor(min(xs))), int(math.floor(min(ys)))
    out_w, out_h = int(math.ceil(max(xs))) - min_x, int(math.ceil(max(ys))) - min_y
    inv = _RA._invert(a)
    if out_w <= 0 or out_h <= 0 or not inv:
        return None, 0, 0
    dx, dy = float(min_x) - c[0], float(min_y) - c[1]
    coeff = (inv[0][0], inv[0][1], inv[0][0] * dx + inv[0][1] * dy, inv[1][0], inv[1][1], inv[1][0] * dx + inv[1][1] * dy)
    image = base.transform((out_w, out_h), PILImage.AFFINE, coeff, resample=PILImage.NEAREST, fillcolor=(0, 0, 0, 0))
    if not image.getbbox():
        return None, 0, 0
    return image, min_x, min_y
