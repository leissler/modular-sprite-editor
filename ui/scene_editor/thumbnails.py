"""Scene pictures: what a scene shows at a moment, drawn like the stage draws it (its objects in draw order, each
with its mapping and palette swap) through the shared renderer, for the Scenes list."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

import compositor
import hardware_budget as hb
from models import Project, TimelineScene, state_shows
from ui.frame_render import SHARED
from ui.scene_editor import ops


def scene_image(project: Project, scene: TimelineScene, time: float = 0.0) -> Optional[Any]:
    """The scene at ``time`` seconds as one RGBA image (None when nothing shows)."""
    picture = scene_picture(project, scene, time)
    return picture[0] if picture else None


def scene_picture(project: Project, scene: TimelineScene, time: float = 0.0) -> Optional[Tuple[Any, int, int]]:
    """(RGBA image, left, top): the scene at ``time`` seconds and where its top-left sits in scene space (None when
    nothing shows)."""
    from PIL import Image

    states = ops.evaluate_states(project, scene, time)
    cache: dict = {}
    pieces: List[Tuple[Any, int, int]] = []
    for obj, _depth, _kids in ops.tree_rows(scene, set()):
        state = states.get(obj.id)
        if not state_shows(state):
            continue
        offset, rotation, flip_x, flip_y = hb._decompose(ops.world_matrix(scene, states, obj.id, cache))
        a, b = hb.frame_transform(offset, rotation, flip_x, flip_y)
        mapping = scene.object_mapping(project, obj.id, project.active_mapping)
        swap = scene.object_palette_swap(project, obj.id, project.active_palette_swap)
        source_type = str(state.get("source_type", "none") or "none")
        if source_type in ("frame", "animation"):
            frame = project.get_frame(str(state.get("frame_id") or state.get("source_id") or ""))
            if frame is not None:
                pieces.append(SHARED.render(project, frame, mapping, a, b, swap))
        elif source_type == "module" and state.get("source_id"):
            mod = compositor.resolve_module(project, str(state["source_id"]), mapping)
            if mod is not None:
                rendered = compositor.render_instance(project, mod, a, b, {}, {}, swap=swap)
                if rendered is not None:
                    pieces.append(rendered)
    pieces = [(image, x, y) for image, x, y in pieces if image.getbbox()]
    if not pieces:
        return None
    left = min(x for _image, x, _y in pieces)
    top = min(y for _image, _x, y in pieces)
    right = max(x + image.width for image, x, _y in pieces)
    bottom = max(y + image.height for image, _x, y in pieces)
    canvas = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    for image, x, y in pieces:
        canvas.alpha_composite(image.convert("RGBA"), (x - left, y - top))
    return canvas, left, top
