"""Scene pictures: what a scene shows at a moment, drawn like the stage draws it (its objects in draw order, each
with its mapping and palette swap) through the shared renderer, for the Scenes list and the scene GIF export."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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


GIF_SHORTEST_MS = 20  # browsers play shorter GIF delays as 100 ms


def export_scene_gif(project: Project, scene: TimelineScene, path: str, scale: int = 1) -> int:
    """One pass of the scene as an animated GIF, drawn like the stage (each object's mapping and colours) on the
    scene's background colour, at the scene's frame rate (50 pictures a second at most: GIF can't do faster). Pictures
    that repeat merge into one longer one. Returns the GIF's frame count."""
    from PIL import Image

    fps = max(1, int(scene.fps))
    frames = ops.scene_length_frames(scene) + 1  # frame 0 up to the last one, like the stage plays them
    seconds = frames / float(fps)
    step = max(1.0 / fps, GIF_SHORTEST_MS / 1000.0)
    times = [i * step for i in range(max(1, int(round(seconds / step))))]
    pictures = [scene_picture(project, scene, t) for t in times]
    shown = [p for p in pictures if p is not None]
    background = tuple(int(v) for v in (scene.background_color or (0, 0, 0))[:3])
    if not shown:
        left, top, width, height = 0, 0, 1, 1
    else:
        left = min(x for _i, x, _y in shown)
        top = min(y for _i, _x, y in shown)
        width = max(x + i.size[0] for i, x, _y in shown) - left
        height = max(y + i.size[1] for i, _x, y in shown) - top
    out: List[Any] = []
    durations: List[int] = []
    for index, picture in enumerate(pictures):
        canvas = Image.new("RGBA", (width, height), background + (255,))
        if picture is not None:
            image, x, y = picture
            canvas.alpha_composite(image, (x - left, y - top))
        if scale > 1:
            canvas = canvas.resize((width * scale, height * scale), Image.NEAREST)
        # Whole tens of milliseconds (GIF counts hundredths of a second) that add up to the real time.
        ms = int(round((index + 1) * step * 100)) * 10 - int(round(index * step * 100)) * 10
        if out and canvas.tobytes() == out[-1].tobytes():
            durations[-1] += ms
        else:
            out.append(canvas)
            durations.append(ms)
    rgb = [frame.convert("RGB") for frame in out]
    options: Dict[str, Any] = {"loop": 0} if scene.loop else {}
    rgb[0].save(path, save_all=True, append_images=rgb[1:], duration=durations, **options)
    return len(rgb)
