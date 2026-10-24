"""The reference compositor (Pillow, wx-free): a frame's parts flattened into module instances with their
transforms, and pixel-exact images of frames, as the editor canvas draws them. Previews (ui/frame_render.py), the
hardware budget, Optimize Sprite Sheet and the exporters all render through it. A frame the console exports store
whole is flattened into one picture per palette here too (``palette_layers``), for the exports and the budget alike."""

from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from models import Frame, Module, ModuleMapping, PaletteSwap, Project

Matrix = Tuple[Tuple[float, float], Tuple[float, float]]
Vector = Tuple[float, float]
# (module, matrix, anchor, rotation, flip_x, flip_y, local_flip_x, local_flip_y), see collect_leaf_instances; with
# ``whole`` a nested frame stored whole stands in the module's place
LeafInstance = Tuple["Module", Matrix, Vector, float, bool, bool, bool, bool]
# A whole frame's picture of one palette: (image, left, top, palette id), see palette_layers
Layer = Tuple[Any, int, int, str]

IDENTITY: Matrix = ((1.0, 0.0), (0.0, 1.0))


# ---------------------------------------------------------------- 2×2 matrices (the translation is kept apart)
def flip_matrix(flip_x: bool, flip_y: bool) -> Matrix:
    return ((-1.0 if flip_x else 1.0, 0.0), (0.0, -1.0 if flip_y else 1.0))


def rotation_matrix(degrees: float) -> Matrix:
    # Exact values for 90° steps: float residue (cos 90° = 6e-17) would otherwise shift
    # floor()-based part bounds by a pixel once nested transforms are composed.
    quarter = float(degrees) / 90.0
    if abs(quarter - round(quarter)) < 1e-9:
        c, s = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(round(quarter)) % 4]
        return ((c, -s), (s, c))
    rad = math.radians(float(degrees))
    c = math.cos(rad)
    s = math.sin(rad)
    return ((c, -s), (s, c))


def mat_mul(a: Matrix, b: Matrix) -> Matrix:
    return (
        (a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1]),
        (a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1]),
    )


def mat_vec_mul(a: Matrix, v: Vector) -> Vector:
    return (a[0][0] * v[0] + a[0][1] * v[1], a[1][0] * v[0] + a[1][1] * v[1])


def compose(parent_a: Matrix, parent_b: Vector, local_a: Matrix, local_b: Vector) -> Tuple[Matrix, Vector]:
    out_a = mat_mul(parent_a, local_a)
    pb = mat_vec_mul(parent_a, local_b)
    out_b = (pb[0] + parent_b[0], pb[1] + parent_b[1])
    return out_a, out_b


def invert(a: Matrix) -> Optional[Matrix]:
    det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
    if abs(det) < 1e-9:
        return None
    inv_det = 1.0 / det
    return (
        (a[1][1] * inv_det, -a[0][1] * inv_det),
        (-a[1][0] * inv_det, a[0][0] * inv_det),
    )


def transform_rect(rect: Tuple[int, int, int, int], a: Matrix, b: Vector) -> Tuple[int, int, int, int]:
    x, y, w, h = rect
    corners = (
        (float(x), float(y)),
        (float(x + w), float(y)),
        (float(x), float(y + h)),
        (float(x + w), float(y + h)),
    )
    tx = []
    ty = []
    for cx, cy in corners:
        px, py = mat_vec_mul(a, (cx, cy))
        tx.append(px + b[0])
        ty.append(py + b[1])
    min_x = int(math.floor(min(tx)))
    min_y = int(math.floor(min(ty)))
    max_x = int(math.ceil(max(tx)))
    max_y = int(math.ceil(max(ty)))
    return (min_x, min_y, max(0, max_x - min_x), max(0, max_y - min_y))


# ---------------------------------------------------------------- module images
def resolve_module(project: "Project", module_id: str, mapping: Optional["ModuleMapping"]) -> Optional["Module"]:
    ref_id = module_id
    if mapping and ref_id in mapping.map:
        ref_id = mapping.map[ref_id]
    if not ref_id:
        return None
    return project.get_module(ref_id)


def render_shape_module(mod: "Module") -> Any:
    from PIL import Image as PILImage, ImageDraw

    w = max(1, int(mod.rect[2]))
    h = max(1, int(mod.rect[3]))
    img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (int(mod.color[0]), int(mod.color[1]), int(mod.color[2]), 255)
    fill = color if "FILL" in mod.type else None

    if mod.type in ("MD_RECT", "MD_FILL_RECT"):
        draw.rectangle((0, 0, w - 1, h - 1), outline=color, fill=fill)
    elif mod.type == "MD_MARKER":
        draw.line((0, 0, w - 1, h - 1), fill=color, width=1)
        draw.line((w - 1, 0, 0, h - 1), fill=color, width=1)
    elif mod.type in ("MD_ARC", "MD_FILL_ARC"):
        start = float(mod.params[0]) if len(mod.params) >= 1 else 0.0
        sweep = float(mod.params[1]) if len(mod.params) >= 2 else 360.0
        draw.pieslice((0, 0, w - 1, h - 1), start=start, end=start + sweep, outline=color, fill=fill)
    elif mod.type in ("MD_TRIANGLE", "MD_FILL_TRIANGLE"):
        if len(mod.params) >= 6:
            p = mod.params
            points = [
                (int(round((p[0] / 100.0) * w)), int(round((p[1] / 100.0) * h))),
                (int(round((p[2] / 100.0) * w)), int(round((p[3] / 100.0) * h))),
                (int(round((p[4] / 100.0) * w)), int(round((p[5] / 100.0) * h))),
            ]
        else:
            points = [(w // 2, 0), (w - 1, h - 1), (0, h - 1)]
        draw.polygon(points, outline=color, fill=fill)
    elif mod.type == "MD_LINE":
        if len(mod.params) >= 4:
            p1 = (int(round((mod.params[0] / 100.0) * w)), int(round((mod.params[1] / 100.0) * h)))
            p2 = (int(round((mod.params[2] / 100.0) * w)), int(round((mod.params[3] / 100.0) * h)))
        elif len(mod.params) >= 2:
            p1 = (0, 0)
            p2 = (int(round(mod.params[0])), int(round(mod.params[1])))
        else:
            p1 = (0, 0)
            p2 = (w - 1, h - 1)
        draw.line((p1[0], p1[1], p2[0], p2[1]), fill=color, width=1)
    else:
        draw.rectangle((0, 0, w - 1, h - 1), outline=color, fill=fill)
    return img


def apply_key_colour(img: Any, transparent_color: Optional[Tuple[int, int, int]]) -> Any:
    """The RGBA image with the sheet's key colour made transparent."""
    if not transparent_color:
        return img

    tr, tg, tb = (
        int(transparent_color[0]),
        int(transparent_color[1]),
        int(transparent_color[2]),
    )
    raw = bytearray(img.tobytes())
    for i in range(0, len(raw), 4):
        if raw[i] == tr and raw[i + 1] == tg and raw[i + 2] == tb:
            raw[i + 3] = 0
    out = img.copy()
    out.frombytes(bytes(raw))
    return out


def swap_colours(project: "Project", mod: "Module", swap: Optional["PaletteSwap"]) -> Optional[Tuple[Tuple[Any, ...], Tuple[Any, ...]]]:
    """(the palette's colours, the swap's version of them) for the module's palette, or None when the swap leaves
    its colours as they are (vector shapes use the first palette)."""
    if swap is None:
        return None
    import palettes

    asset = project.get_image(mod.image_id) if mod.type == "MD_IMAGE" else None
    palette = project.image_palette(asset)
    if palette.id not in swap.palettes:
        return None
    base = palettes.colours_of(project, palette)
    if not palettes.recolours(palette, swap, None, base):
        return None
    return tuple(base), tuple(palettes.swapped_colours(palette, swap, base))


def load_module_rgba(
    project: "Project",
    mod: "Module",
    full_image_cache: Dict[Any, Any],
    module_cache: Dict[Any, Any],
    swap: Optional["PaletteSwap"] = None,
) -> Any:
    """The module's RGBA image as used (key colour cut, a packed module turned upright, recoloured by ``swap``); empty
    if its image is missing. Sheets go into ``full_image_cache``, modules into ``module_cache``."""
    from PIL import Image as PILImage

    colours = swap_colours(project, mod, swap)
    module_key: Any = mod.id if colours is None else (mod.id, colours)
    if module_key in module_cache:
        return module_cache[module_key]

    if mod.type != "MD_IMAGE":
        img = render_shape_module(mod)
        if colours is not None:
            import palettes

            img = palettes.recolour(img, colours[0], colours[1])
        module_cache[module_key] = img
        return img

    asset = project.get_image(mod.image_id)
    w = max(1, int(mod.rect[2]))
    h = max(1, int(mod.rect[3]))

    if not asset or not os.path.exists(asset.file_path):
        img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
        module_cache[module_key] = img
        return img

    trans_key = None
    if asset.transparent_color:
        trans_key = (
            int(asset.transparent_color[0]),
            int(asset.transparent_color[1]),
            int(asset.transparent_color[2]),
        )
    cache_key = f"{os.path.abspath(asset.file_path)}|key={trans_key}"
    if cache_key not in full_image_cache:
        loaded = PILImage.open(asset.file_path).convert("RGBA")
        loaded = apply_key_colour(loaded, asset.transparent_color)
        full_image_cache[cache_key] = loaded
    source = full_image_cache[cache_key]
    if colours is not None:
        import palettes

        swapped_key = (cache_key, colours)
        if swapped_key not in full_image_cache:
            full_image_cache[swapped_key] = palettes.recolour(source, colours[0], colours[1])
        source = full_image_cache[swapped_key]

    rx, ry, rw, rh = mod.rect
    left = max(0, int(rx))
    top = max(0, int(ry))
    right = min(source.width, int(rx + rw))
    bottom = min(source.height, int(ry + rh))
    if right <= left or bottom <= top:
        img = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
        module_cache[module_key] = img
        return img

    img = source.crop((left, top, right, bottom))
    if mod.rotated:
        # Match current editor behavior (Rotate90(clockwise=False))
        img = img.transpose(PILImage.ROTATE_90)
    module_cache[module_key] = img
    return img


def mirror_in_place(img: Any, flip_x: bool, flip_y: bool) -> Any:
    from PIL import Image as PILImage

    if flip_x:
        img = img.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
    if flip_y:
        img = img.transpose(PILImage.Transpose.FLIP_TOP_BOTTOM)
    return img


# ---------------------------------------------------------------- frames
def collect_leaf_instances(
    project: "Project",
    frame_id: str,
    mapping: Optional["ModuleMapping"],
    parent_a: Matrix,
    parent_b: Vector,
    parent_rot: float,
    parent_flip_x: bool,
    parent_flip_y: bool,
    out: List[LeafInstance],
    depth: int,
    stack: set[str],
    whole: bool = False,
) -> None:
    """
    Flatten a frame into leaf module instances.

    Each entry is (module, matrix, anchor, rotation, flip_x, flip_y, local_flip_x, local_flip_y).
    Matches the editor canvas: a part's own flip mirrors the module image in place (about the
    texture centre, bounds unchanged), so it is *not* part of the matrix; the renderer mirrors the
    texture first. Flips of nested frames and animation steps are geometric mirrors and stay in
    the matrix.

    With ``whole`` (what the console exports store), a nested frame stored whole (``Frame.store_whole``) is one
    entry, the frame in the module's place, instead of its leaves: the exports draw its pictures (``palette_layers``).
    """
    if depth > 48:
        return
    frame = project.get_frame(frame_id)
    if not frame or frame_id in stack:
        return

    stack.add(frame_id)
    for fm in frame.fmodules:
        local_flip_x = bool(getattr(fm, "flip_x", False))
        local_flip_y = bool(getattr(fm, "flip_y", False))
        rot_a = rotation_matrix(float(getattr(fm, "rotation_degrees", 0.0)))
        if fm.ref_type == "frame":
            local_a = mat_mul(rot_a, flip_matrix(local_flip_x, local_flip_y))
        else:
            local_a = rot_a
        local_b = (float(fm.position[0]), float(fm.position[1]))
        a_next, b_next = compose(parent_a, parent_b, local_a, local_b)
        local_rot = float(getattr(fm, "rotation_degrees", 0.0))
        parent_flipped = bool(parent_flip_x) ^ bool(parent_flip_y)
        rot_next = float(parent_rot) + (-local_rot if parent_flipped else local_rot)
        flip_x_next = bool(parent_flip_x) ^ bool(getattr(fm, "flip_x", False))
        flip_y_next = bool(parent_flip_y) ^ bool(getattr(fm, "flip_y", False))

        if fm.ref_type == "module":
            mod = resolve_module(project, fm.ref_id, mapping)
            if mod:
                out.append(
                    (mod, a_next, b_next, rot_next, flip_x_next, flip_y_next, local_flip_x, local_flip_y)
                )
        elif fm.ref_type == "frame":
            child = project.get_frame(fm.ref_id) if whole else None
            if child is not None and child.store_whole:
                if child.id not in stack and depth < 48:  # a cycle draws nothing, as below
                    out.append((child, a_next, b_next, rot_next, flip_x_next, flip_y_next, local_flip_x, local_flip_y))
                continue
            collect_leaf_instances(
                project=project,
                frame_id=fm.ref_id,
                mapping=mapping,
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


def render_instance(
    project: "Project",
    mod: "Module",
    a_mat: Matrix,
    b_vec: Vector,
    full_image_cache: Dict[Any, Any],
    module_cache: Dict[Any, Any],
    local_flip_x: bool = False,
    local_flip_y: bool = False,
    swap: Optional["PaletteSwap"] = None,
) -> Optional[Tuple[Any, int, int]]:
    """One module instance as an image and its top-left corner; None if nothing of it shows."""
    from PIL import Image as PILImage

    base = load_module_rgba(project, mod, full_image_cache, module_cache, swap)
    # The part's own flip is an in-place mirror of the module image (editor semantics);
    # everything else (rotation, nested/animation flips) is on the affine path below.
    base = mirror_in_place(base, local_flip_x, local_flip_y)
    w, h = base.size
    if w <= 0 or h <= 0:
        return None

    piv = (float(mod.pivot[0]), float(mod.pivot[1]))
    ap = mat_vec_mul(a_mat, piv)
    c_vec = (b_vec[0] - ap[0], b_vec[1] - ap[1])

    corners = (
        (0.0, 0.0),
        (float(w), 0.0),
        (0.0, float(h)),
        (float(w), float(h)),
    )
    xs: List[float] = []
    ys: List[float] = []
    for u, v in corners:
        tx, ty = mat_vec_mul(a_mat, (u, v))
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

    inv = invert(a_mat)
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
        PILImage.AFFINE,
        coeff,
        resample=PILImage.NEAREST,
        fillcolor=(0, 0, 0, 0),
    )
    if not transformed.getbbox():
        return None

    return transformed, min_x, min_y


def palette_layers(
    project: "Project",
    instances: List[LeafInstance],
    full_image_cache: Dict[Any, Any],
    module_cache: Dict[Any, Any],
    palette_of: Callable[["Module"], str],
) -> Tuple[Layer, ...]:
    """Module instances (``collect_leaf_instances``) drawn as the editor draws them, in order, as one picture per
    palette (``palette_of``: a module's palette id) and where it goes, each cropped to what shows: how the console
    exports store a frame whole. Each pixel is in the layer of the part on top, so the layers never overlap and draw
    the frame in any order (the consoles draw no partly transparent pixels). Modules without an area are hidden, as the
    exports hide them."""
    from PIL import Image as PILImage

    rendered: List[Layer] = []
    for mod, a_mat, b_vec, _rot, _flip_x, _flip_y, local_flip_x, local_flip_y in instances:
        if int(mod.rect[2]) <= 0 or int(mod.rect[3]) <= 0:
            continue
        piece = render_instance(project, mod, a_mat, b_vec, full_image_cache, module_cache, local_flip_x, local_flip_y)
        if piece is not None:
            rendered.append((piece[0], piece[1], piece[2], palette_of(mod)))
    if not rendered:
        return ()
    left = min(x for _image, x, _y, _palette in rendered)
    top = min(y for _image, _x, y, _palette in rendered)
    size = (max(x + image.width for image, x, _y, _palette in rendered) - left,
            max(y + image.height for image, _x, y, _palette in rendered) - top)
    layers: Dict[str, Any] = {}
    for image, x, y, palette in rendered:
        at = (x - left, y - top)
        covered = image.getchannel("A").point(lambda value: 255 if value else 0)
        for other, layer in layers.items():
            if other != palette:
                layer.paste((0, 0, 0, 0), at, covered)
        if palette not in layers:
            layers[palette] = PILImage.new("RGBA", size, (0, 0, 0, 0))
        layers[palette].alpha_composite(image, at)
    out: List[Layer] = []
    for palette, layer in layers.items():
        box = layer.getbbox()
        if box:
            out.append((layer.crop(box), left + box[0], top + box[1], palette))
    return tuple(out)


def render_frame(
    project: "Project",
    source_frame: "Frame",
    mapping: Optional["ModuleMapping"],
    extra_a: Matrix,
    extra_b: Vector,
    full_image_cache: Dict[Any, Any],
    module_cache: Dict[Any, Any],
    swap: Optional["PaletteSwap"] = None,
) -> Tuple[Any, int, int, List[Tuple[str, Tuple[int, int, int, int]]]]:
    """The frame under the extra transform, recoloured by ``swap``: (image, left, top, [(hitbox type id, transformed
    rect)]); a 1×1 transparent image at (0, 0) if nothing shows."""
    from PIL import Image as PILImage

    instances: List[LeafInstance] = []
    collect_leaf_instances(
        project=project,
        frame_id=source_frame.id,
        mapping=mapping,
        parent_a=extra_a,
        parent_b=extra_b,
        parent_rot=0.0,
        parent_flip_x=False,
        parent_flip_y=False,
        out=instances,
        depth=0,
        stack=set(),
    )

    rendered: List[Tuple[Any, int, int]] = []
    for mod, a_mat, b_vec, _rot, _flip_x, _flip_y, local_flip_x, local_flip_y in instances:
        piece = render_instance(project, mod, a_mat, b_vec, full_image_cache, module_cache, local_flip_x, local_flip_y,
                                swap)
        if piece is not None:
            rendered.append(piece)

    if not rendered:
        image = PILImage.new("RGBA", (1, 1), (0, 0, 0, 0))
        return image, 0, 0, []

    handle_x = min(x for _img, x, _y in rendered)
    handle_y = min(y for _img, _x, y in rendered)
    canvas_w = max(1, max(x + img.width for img, x, _y in rendered) - handle_x)
    canvas_h = max(1, max(y + img.height for img, _x, y in rendered) - handle_y)
    image = PILImage.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    for sprite, sx, sy in rendered:
        image.alpha_composite(sprite, (sx - handle_x, sy - handle_y))

    transformed_collisions = [
        (cr.type_id, transform_rect(cr.rect, extra_a, extra_b))
        for cr in source_frame.collision_rects
    ]
    return image, handle_x, handle_y, transformed_collisions
