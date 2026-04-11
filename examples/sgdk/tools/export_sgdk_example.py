#!/usr/bin/env python3
"""Bake editor JSON into an SGDK example project (resources + C data tables)."""

from __future__ import annotations

import argparse
import hashlib
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import Frame, Module, ModuleMapping, Project, RetroAnimatorExporter, TimelineScene  # noqa: E402


Matrix2 = Tuple[Tuple[float, float], Tuple[float, float]]
Vec2 = Tuple[float, float]
Matrix2x3 = Tuple[float, float, float, float, float, float]
PartEntry = Tuple[int, int, int, int, int]


@dataclass(frozen=True)
class VariantMeta:
    symbol: str
    filename: str
    tile_w: int
    tile_h: int


@dataclass(frozen=True)
class RenderFrameSpan:
    first_part: int
    part_count: int


@dataclass(frozen=True)
class AnimRecord:
    first_step: int
    step_count: int
    fps: int
    playback: int


@dataclass(frozen=True)
class SceneRecord:
    first_sample: int
    sample_count: int
    fps: int
    duration_ticks: int
    loop: int


class SGDKBakeContext:
    def __init__(self, project: Project, mappings: List[Optional[ModuleMapping]], output_demo_dir: Path) -> None:
        self.project = project
        self.mappings = mappings
        self.mapping = mappings[0] if mappings else None
        self.mapping_key = self.mapping.id if self.mapping else "none"
        self.output_demo_dir = output_demo_dir
        self.output_gen_dir = output_demo_dir / "res" / "gen"

        self.full_image_cache: Dict[str, Any] = {}
        self.module_cache: Dict[str, Any] = {}

        self.variant_lookup: Dict[Tuple[int, int, str], int] = {}
        self.variants: List[VariantMeta] = []

        self.parts: List[PartEntry] = []
        self.render_frames: List[RenderFrameSpan] = []
        self.render_frame_lookup: Dict[Tuple[PartEntry, ...], int] = {}
        self.transformed_frame_parts_cache: Dict[Tuple[Any, ...], Tuple[PartEntry, ...]] = {}

        self.module_render_frames: List[int] = []
        self.frame_render_frames: List[int] = []

        self.anim_steps: List[Tuple[int, int]] = []
        self.anim_records: List[AnimRecord] = []

        self.scene_samples: List[int] = []
        self.scene_records: List[SceneRecord] = []

        self.mapping_ids: List[str] = [m.id if m else "" for m in self.mappings]
        self.mapping_names: List[str] = [m.name if m else "<none>" for m in self.mappings]

        self.master_palette_15: List[Tuple[int, int, int]] = self._build_master_palette()
        self.palette_lookup_cache: Dict[Tuple[int, int, int], int] = {}

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
    def _c_string(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

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

    def _prepare_output_dirs(self) -> None:
        self.output_gen_dir.mkdir(parents=True, exist_ok=True)
        for child in self.output_gen_dir.iterdir():
            if child.is_file() and child.suffix.lower() == ".png":
                child.unlink()

    def _set_current_mapping(self, mapping: Optional[ModuleMapping]) -> None:
        self.mapping = mapping
        self.mapping_key = mapping.id if mapping else "none"

    @staticmethod
    def _is_hidden_module(mod: Optional[Module]) -> bool:
        if mod is None:
            return True
        return int(mod.rect[2]) <= 0 or int(mod.rect[3]) <= 0

    def _resolve_module(self, module_id: str) -> Optional[Module]:
        mod = RetroAnimatorExporter._resolve_module(self.project, module_id, self.mapping)
        if self._is_hidden_module(mod):
            return None
        return mod

    def _ensure_variant(self, image: Image.Image) -> int:
        rgba = image.convert("RGBA")
        digest = hashlib.sha1(rgba.tobytes()).hexdigest()
        key = (rgba.width, rgba.height, digest)
        found = self.variant_lookup.get(key)
        if found is not None:
            return found

        idx = len(self.variants)
        symbol = f"MS_VAR_{idx:04d}"
        filename = f"var_{idx:04d}.png"

        out_w = max(8, ((rgba.width + 7) // 8) * 8)
        out_h = max(8, ((rgba.height + 7) // 8) * 8)
        padded = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        padded.alpha_composite(rgba, (0, 0))

        # SGDK 3.99 rescomp expects indexed source images for regular sprite assets
        # unless RGB images embed palette tiles (which we do not want here).
        indexed = self._to_indexed_4bpp(padded)
        indexed.save(self.output_gen_dir / filename)

        self.variant_lookup[key] = idx
        self.variants.append(
            VariantMeta(
                symbol=symbol,
                filename=filename,
                tile_w=out_w // 8,
                tile_h=out_h // 8,
            )
        )
        return idx

    @staticmethod
    def _rgb_distance_sq(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
        dr = int(a[0]) - int(b[0])
        dg = int(a[1]) - int(b[1])
        db = int(a[2]) - int(b[2])
        return dr * dr + dg * dg + db * db

    def _build_master_palette(self) -> List[Tuple[int, int, int]]:
        counts: Dict[Tuple[int, int, int], int] = {}

        for asset in self.project.images:
            path = Path(asset.file_path)
            if not path.exists():
                continue

            image = Image.open(path).convert("RGB")
            transparent = tuple(int(v) for v in asset.transparent_color) if asset.transparent_color else None
            for px in image.getdata():
                rgb = (int(px[0]), int(px[1]), int(px[2]))
                if transparent is not None and rgb == transparent:
                    continue
                counts[rgb] = counts.get(rgb, 0) + 1

        if not counts:
            return [(255, 255, 255)] + [(0, 0, 0)] * 14

        if len(counts) <= 15:
            ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            base = [rgb for rgb, _count in ordered]
        else:
            canvas = Image.new("RGB", (len(counts), 1), (0, 0, 0))
            for x, rgb in enumerate(counts.keys()):
                canvas.putpixel((x, 0), rgb)
            quant = canvas.quantize(colors=15, dither=Image.Dither.NONE)
            raw_pal = quant.getpalette() or []
            base = []
            for i in range(15):
                off = i * 3
                if off + 2 >= len(raw_pal):
                    break
                base.append((int(raw_pal[off]), int(raw_pal[off + 1]), int(raw_pal[off + 2])))

        if not base:
            base = [(255, 255, 255)]
        while len(base) < 15:
            base.append(base[-1])
        return base[:15]

    def _nearest_master_palette_index(self, rgb: Tuple[int, int, int]) -> int:
        cached = self.palette_lookup_cache.get(rgb)
        if cached is not None:
            return cached

        best_index = 0
        best_dist = self._rgb_distance_sq(rgb, self.master_palette_15[0])
        for idx in range(1, 15):
            dist = self._rgb_distance_sq(rgb, self.master_palette_15[idx])
            if dist < best_dist:
                best_dist = dist
                best_index = idx

        self.palette_lookup_cache[rgb] = best_index
        return best_index

    def _to_indexed_4bpp(self, rgba: Image.Image) -> Image.Image:
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        src_rgb = list(rgb.getdata())
        src_alpha = alpha.tobytes()
        out_idx = bytearray(len(src_rgb))
        for i in range(len(src_rgb)):
            if src_alpha[i] == 0:
                out_idx[i] = 0
            else:
                px = src_rgb[i]
                nearest = self._nearest_master_palette_index((int(px[0]), int(px[1]), int(px[2])))
                out_idx[i] = int(nearest + 1)

        palette = [0] * (256 * 3)
        for i, rgb_color in enumerate(self.master_palette_15):
            dst_off = (i + 1) * 3
            palette[dst_off] = int(rgb_color[0])
            palette[dst_off + 1] = int(rgb_color[1])
            palette[dst_off + 2] = int(rgb_color[2])

        out = Image.frombytes("P", rgba.size, bytes(out_idx))
        out.putpalette(palette)
        return out

    def _intern_render_frame(self, part_list: Sequence[PartEntry]) -> int:
        key = tuple((int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4])) for p in part_list)
        found = self.render_frame_lookup.get(key)
        if found is not None:
            return found

        first = len(self.parts)
        self.parts.extend(key)
        span = RenderFrameSpan(first_part=first, part_count=len(key))
        idx = len(self.render_frames)
        self.render_frames.append(span)
        self.render_frame_lookup[key] = idx
        return idx

    @staticmethod
    def _effective_hw_flip(rotation_degrees: float, flip_x: bool, flip_y: bool) -> Optional[Tuple[bool, bool]]:
        rot_norm = float(rotation_degrees) % 360.0
        rot_int = int(round(rot_norm)) % 360
        if abs(rot_norm - float(rot_int)) > 1e-5:
            return None
        if rot_int not in (0, 180):
            return None

        hflip = bool(flip_x)
        vflip = bool(flip_y)
        if rot_int == 180:
            hflip = not hflip
            vflip = not vflip
        return (hflip, vflip)

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
        base = RetroAnimatorExporter._load_module_rgba(
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

            variant_index = self._ensure_variant(base)
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
        variant_index = self._ensure_variant(img)
        return (variant_index, int(draw_x), int(draw_y), 0, 0)

    def _render_transformed_instance_with_local_flip(
        self,
        mod: Module,
        a_mat: Matrix2,
        b_vec: Vec2,
        local_flip_x: bool,
        local_flip_y: bool,
    ) -> Optional[Tuple[Image.Image, int, int]]:
        base = RetroAnimatorExporter._load_module_rgba(
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
        ap = RetroAnimatorExporter._mat_vec_mul(a_mat, piv)
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
            tx, ty = RetroAnimatorExporter._mat_vec_mul(a_mat, (u, v))
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

        inv = RetroAnimatorExporter._invert(a_mat)
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
    ) -> None:
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
            rot_a = RetroAnimatorExporter._rotation_matrix(local_rot)
            flip_a = RetroAnimatorExporter._flip_matrix(local_flip_x, local_flip_y)

            # Match editor behavior: module-local flips mirror pixels in-place and
            # do not change module bounds/anchor placement.
            if fm.ref_type == "frame":
                local_a = RetroAnimatorExporter._mat_mul(rot_a, flip_a)
            else:
                local_a = rot_a

            a_next, b_next = RetroAnimatorExporter._compose(parent_a, parent_b, local_a, local_b)
            parent_flipped = bool(parent_flip_x) ^ bool(parent_flip_y)
            rot_next = float(parent_rot) + (-local_rot if parent_flipped else local_rot)
            flip_x_next = bool(parent_flip_x) ^ local_flip_x
            flip_y_next = bool(parent_flip_y) ^ local_flip_y

            if fm.ref_type == "module":
                mod = self._resolve_module(fm.ref_id)
                if mod:
                    out.append((mod, a_next, b_next, rot_next, flip_x_next, flip_y_next, local_flip_x, local_flip_y))
            elif fm.ref_type == "frame":
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

        a_mat = RetroAnimatorExporter._mat_mul(
            RetroAnimatorExporter._rotation_matrix(rotation_degrees),
            RetroAnimatorExporter._flip_matrix(flip_x, flip_y),
        )
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

        parent_a = RetroAnimatorExporter._mat_mul(
            RetroAnimatorExporter._rotation_matrix(rotation_degrees),
            RetroAnimatorExporter._flip_matrix(flip_x, flip_y),
        )
        parent_b = (float(offset[0]), float(offset[1]))

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
        )

        out_parts: List[PartEntry] = []
        for mod, a_mat, b_vec, rot_deg, part_flip_x, part_flip_y, local_flip_x, local_flip_y in instances:
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

    @staticmethod
    def _build_local_matrix(state: Dict[str, Any]) -> Matrix2x3:
        source_offset = state.get("source_offset", (0.0, 0.0))
        tx = float(state.get("x", 0.0)) + float(source_offset[0])
        ty = float(state.get("y", 0.0)) + float(source_offset[1])

        total_rotation = float(state.get("rotation_degrees", 0.0)) + float(state.get("source_rotation", 0.0))
        rad = math.radians(total_rotation)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        fx = bool(state.get("flip_x", False)) ^ bool(state.get("source_flip_x", False))
        fy = bool(state.get("flip_y", False)) ^ bool(state.get("source_flip_y", False))
        sx = -1.0 if fx else 1.0
        sy = -1.0 if fy else 1.0

        a = cos_a * sx
        b = sin_a * sx
        c = -sin_a * sy
        d = cos_a * sy
        return (a, b, c, d, tx, ty)

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

        for obj in ordered_objects:
            state = state_map.get(obj.id)
            if not state:
                continue
            if not bool(state.get("visible", True)):
                continue

            world_matrix = self._world_matrix_for_object(scene, state_map, obj.id, world_cache)
            offset, rotation, flip_x, flip_y = self._decompose_matrix_to_frame_transform(world_matrix)

            source_type = str(state.get("source_type", "none") or "none").strip().lower()
            if source_type == "module":
                source_id = state.get("source_id")
                if source_id is None:
                    continue
                parts = self._render_module_parts(
                    module_id=str(source_id),
                    offset=offset,
                    rotation_degrees=float(rotation),
                    flip_x=bool(flip_x),
                    flip_y=bool(flip_y),
                )
                scene_parts.extend(parts)
                continue

            if source_type not in ("frame", "animation"):
                continue

            frame_id = state.get("frame_id") or state.get("source_id")
            if frame_id is None:
                continue
            frame = self.project.get_frame(str(frame_id))
            if not frame:
                continue

            parts = self._render_frame_parts(
                frame=frame,
                offset=offset,
                rotation_degrees=float(rotation),
                flip_x=bool(flip_x),
                flip_y=bool(flip_y),
            )
            scene_parts.extend(parts)

        return tuple(scene_parts)

    def bake(self) -> None:
        self._prepare_output_dirs()

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
                render_idx = self._intern_render_frame(parts)
                self.frame_render_frames.append(render_idx)
                frame_render_by_id[frame.id] = render_idx

            # 3) Animations.
            for anim in self.project.animations:
                first_step = len(self.anim_steps)
                source_fps = int(anim.fps) if int(anim.fps) > 0 else 10
                for af in anim.aframes:
                    frame = self.project.get_frame(af.frame_id)
                    if not frame:
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
                        render_idx = self._intern_render_frame(parts)

                    duration_ticks = max(
                        1,
                        int(round((max(1.0, float(af.duration_frames)) / float(source_fps)) * 60.0)),
                    )
                    self.anim_steps.append((render_idx, duration_ticks))

                step_count = len(self.anim_steps) - first_step
                if step_count <= 0:
                    first_step = len(self.anim_steps)
                    self.anim_steps.append((empty_render, 1))
                    step_count = 1

                self.anim_records.append(
                    AnimRecord(
                        first_step=first_step,
                        step_count=step_count,
                        fps=source_fps,
                        playback=self._playback_code(str(anim.playback_type)),
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

    def _emit_header(self, path: Path) -> None:
        text = f"""#ifndef MODSPRITE_DATA_H
#define MODSPRITE_DATA_H

#include <genesis.h>

typedef struct
{{
    u16 variant_index;
    s16 x;
    s16 y;
    u8 hflip;
    u8 vflip;
}} MS_Part;

typedef struct
{{
    u32 first_part;
    u16 part_count;
}} MS_RenderFrame;

typedef struct
{{
    u16 frame_index;
    u16 duration_ticks;
}} MS_AnimStep;

typedef struct
{{
    u32 first_step;
    u16 step_count;
    u16 fps;
    u8 playback;
}} MS_Animation;

typedef struct
{{
    u32 first_sample;
    u16 sample_count;
    u16 fps;
    u16 duration_ticks;
    u8 loop;
}} MS_Scene;

#define MS_VARIANT_COUNT {len(self.variants)}U
#define MS_PART_COUNT {len(self.parts)}U
#define MS_RENDER_FRAME_COUNT {len(self.render_frames)}U

#define MS_MODULE_COUNT {len(self.project.modules)}U
#define MS_FRAME_COUNT {len(self.project.frames)}U
#define MS_ANIMATION_COUNT {len(self.project.animations)}U
#define MS_SCENE_COUNT {len(self.project.timeline_scenes)}U
#define MS_MAPPING_COUNT {len(self.mappings)}U

#define MS_ANIM_STEP_COUNT {len(self.anim_steps)}U
#define MS_SCENE_SAMPLE_COUNT {len(self.scene_samples)}U
#define MS_ANIMATION_RECORD_COUNT {len(self.anim_records)}U
#define MS_SCENE_RECORD_COUNT {len(self.scene_records)}U

extern const SpriteDefinition *const ms_variant_defs[];
extern const MS_Part ms_parts[];
extern const MS_RenderFrame ms_render_frames[];

extern const u16 ms_module_render_frames[];
extern const char *const ms_mapping_ids[];
extern const char *const ms_mapping_names[];
extern const char *const ms_module_ids[];
extern const char *const ms_module_names[];

extern const u16 ms_frame_render_frames[];
extern const char *const ms_frame_ids[];
extern const char *const ms_frame_names[];

extern const MS_AnimStep ms_anim_steps[];
extern const MS_Animation ms_animations[];
extern const char *const ms_animation_ids[];
extern const char *const ms_animation_names[];

extern const u16 ms_scene_samples[];
extern const MS_Scene ms_scenes[];
extern const char *const ms_scene_ids[];
extern const char *const ms_scene_names[];

#endif
"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _emit_resources(self, path: Path) -> None:
        lines: List[str] = []
        for variant in self.variants:
            lines.append(
                f'SPRITE {variant.symbol} "gen/{variant.filename}" {variant.tile_w} {variant.tile_h} NONE'
            )
        lines.append("")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _emit_c_array(name: str, ctype: str, items: Sequence[str], empty_value: str) -> str:
        if items:
            body = "\n".join(f"    {item}," for item in items)
        else:
            body = f"    {empty_value},"
        return f"const {ctype} {name}[] = {{\n{body}\n}};\n"

    def _emit_data_c(self, path: Path) -> None:
        variant_ptrs = [f"&{v.symbol}" for v in self.variants]
        part_rows = [f"{{ {p[0]}u, {p[1]}, {p[2]}, {p[3]}u, {p[4]}u }}" for p in self.parts]
        render_rows = [f"{{ {rf.first_part}u, {rf.part_count}u }}" for rf in self.render_frames]

        mod_rf_rows = [f"{idx}u" for idx in self.module_render_frames]
        map_id_rows = [self._c_string(value) for value in self.mapping_ids]
        map_name_rows = [self._c_string(value) for value in self.mapping_names]
        mod_id_rows = [self._c_string(mod.id) for mod in self.project.modules]
        mod_name_rows = [self._c_string(mod.name) for mod in self.project.modules]

        frm_rf_rows = [f"{idx}u" for idx in self.frame_render_frames]
        frm_id_rows = [self._c_string(frm.id) for frm in self.project.frames]
        frm_name_rows = [self._c_string(frm.name) for frm in self.project.frames]

        anim_step_rows = [f"{{ {step[0]}u, {step[1]}u }}" for step in self.anim_steps]
        anim_rows = [
            f"{{ {a.first_step}u, {a.step_count}u, {a.fps}u, {a.playback}u }}"
            for a in self.anim_records
        ]
        anim_id_rows = [self._c_string(anim.id) for anim in self.project.animations]
        anim_name_rows = [self._c_string(anim.name) for anim in self.project.animations]

        scene_sample_rows = [f"{idx}u" for idx in self.scene_samples]
        scene_rows = [
            f"{{ {s.first_sample}u, {s.sample_count}u, {s.fps}u, {s.duration_ticks}u, {s.loop}u }}"
            for s in self.scene_records
        ]
        scene_id_rows = [self._c_string(scene.id) for scene in self.project.timeline_scenes]
        scene_name_rows = [self._c_string(scene.name) for scene in self.project.timeline_scenes]

        sections = [
            "#include <genesis.h>",
            "#include \"modsprite_data.h\"",
            "#include \"resources.h\"",
            "",
            self._emit_c_array(
                "ms_variant_defs",
                "SpriteDefinition *const",
                variant_ptrs,
                "NULL",
            ),
            self._emit_c_array("ms_parts", "MS_Part", part_rows, "{ 0u, 0, 0, 0u, 0u }"),
            self._emit_c_array("ms_render_frames", "MS_RenderFrame", render_rows, "{ 0u, 0u }"),
            "",
            self._emit_c_array("ms_module_render_frames", "u16", mod_rf_rows, "0u"),
            self._emit_c_array("ms_mapping_ids", "char *const", map_id_rows, "\"\""),
            self._emit_c_array("ms_mapping_names", "char *const", map_name_rows, "\"\""),
            self._emit_c_array("ms_module_ids", "char *const", mod_id_rows, "\"\""),
            self._emit_c_array("ms_module_names", "char *const", mod_name_rows, "\"\""),
            "",
            self._emit_c_array("ms_frame_render_frames", "u16", frm_rf_rows, "0u"),
            self._emit_c_array("ms_frame_ids", "char *const", frm_id_rows, "\"\""),
            self._emit_c_array("ms_frame_names", "char *const", frm_name_rows, "\"\""),
            "",
            self._emit_c_array("ms_anim_steps", "MS_AnimStep", anim_step_rows, "{ 0u, 1u }"),
            self._emit_c_array("ms_animations", "MS_Animation", anim_rows, "{ 0u, 1u, 10u, 0u }"),
            self._emit_c_array("ms_animation_ids", "char *const", anim_id_rows, "\"\""),
            self._emit_c_array("ms_animation_names", "char *const", anim_name_rows, "\"\""),
            "",
            self._emit_c_array("ms_scene_samples", "u16", scene_sample_rows, "0u"),
            self._emit_c_array("ms_scenes", "MS_Scene", scene_rows, "{ 0u, 1u, 60u, 1u, 1u }"),
            self._emit_c_array("ms_scene_ids", "char *const", scene_id_rows, "\"\""),
            self._emit_c_array("ms_scene_names", "char *const", scene_name_rows, "\"\""),
            "",
        ]

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(sections), encoding="utf-8")


def _resolve_mappings(project: Project, mapping_selector: str) -> List[Optional[ModuleMapping]]:
    selector = str(mapping_selector or "auto").strip()
    lower = selector.lower()

    if lower in ("none", "off", "null"):
        return [None]

    if lower in ("auto", "all", "*"):
        return [None] + list(project.mappings)

    for item in project.mappings:
        if item.id == selector:
            return [None, item]
        if item.name.strip().lower() == lower:
            return [None, item]
    raise ValueError(f"Mapping '{mapping_selector}' was not found. Available: {[m.name for m in project.mappings]}")


def _copy_if_needed(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bake modular sprite project JSON into SGDK demo assets.")
    parser.add_argument(
        "--project-json",
        default=str((REPO_ROOT / "examples" / "sgdk" / "PoP_WW.json").resolve()),
        help="Path to source project JSON.",
    )
    parser.add_argument(
        "--output-demo-dir",
        default=str((REPO_ROOT / "examples" / "sgdk" / "sgdk_demo").resolve()),
        help="Target SGDK demo directory.",
    )
    parser.add_argument(
        "--mapping",
        default="all",
        help="Mapping name/id, 'all' (default), 'auto', or 'none'.",
    )
    parser.add_argument(
        "--copy-assets",
        action="store_true",
        help="Copy source JSON and source atlas image into the demo directory for reference.",
    )

    args = parser.parse_args()
    project_json_path = Path(args.project_json).resolve()
    output_demo_dir = Path(args.output_demo_dir).resolve()

    project = Project.from_json(str(project_json_path))
    mappings = _resolve_mappings(project, args.mapping)

    bake = SGDKBakeContext(project=project, mappings=mappings, output_demo_dir=output_demo_dir)
    bake.bake()

    bake._emit_header(output_demo_dir / "inc" / "modsprite_data.h")
    bake._emit_data_c(output_demo_dir / "src" / "modsprite_data.c")
    bake._emit_resources(output_demo_dir / "res" / "resources.res")

    if args.copy_assets:
        _copy_if_needed(project_json_path, output_demo_dir / "source" / project_json_path.name)
        if project.images:
            image_path = Path(project.images[0].file_path)
            if image_path.exists():
                _copy_if_needed(image_path, output_demo_dir / "source" / image_path.name)

    summary = {
        "mapping_count": len(mappings),
        "mappings": ", ".join(bake.mapping_names),
        "variants": len(bake.variants),
        "parts": len(bake.parts),
        "render_frames": len(bake.render_frames),
        "modules": len(project.modules),
        "frames": len(project.frames),
        "animations": len(project.animations),
        "scenes": len(project.timeline_scenes),
        "anim_steps": len(bake.anim_steps),
        "scene_samples": len(bake.scene_samples),
    }

    for key, value in summary.items():
        print(f"{key}: {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
