"""What each tab showed for a project (its selected items, the canvas' zoom and pan, the grid), kept in the preferences
under the project file's path, so reopening a project brings the artist back to where they left it.

Each tab reports a small dict (``view_state``) and takes it back (``restore_view_state``); the main window keeps them
per project. Anything stored may refer to things that are gone by now: the tabs check every id before using it.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

PREFIX = "ProjectView/"
ORDER_KEY = PREFIX + "order"
KEEP = 40  # projects remembered; the one opened longest ago is forgotten first

View = Tuple[Tuple[float, float], float]  # a canvas' (pan, zoom), as BaseCanvas.get_view_state gives it


def key_of(path: str) -> str:
    return hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:12]


def _order(config: Any) -> List[str]:
    try:
        order = json.loads(config.Read(ORDER_KEY, "[]"))
    except ValueError:
        return []
    return [k for k in order if isinstance(k, str)] if isinstance(order, list) else []


def load(config: Any, path: Optional[str]) -> Dict[str, Any]:
    """The view state kept for the project at ``path`` ({} when there is none or it can't be read)."""
    if config is None or not path:
        return {}
    try:
        state = json.loads(config.Read(PREFIX + key_of(path), "{}"))
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def save(config: Any, path: Optional[str], state: Dict[str, Any]) -> None:
    """Keep ``state`` for the project at ``path``, forgetting the projects opened longest ago beyond ``KEEP``."""
    if config is None or not path:
        return
    key = key_of(path)
    config.Write(PREFIX + key, json.dumps(state, separators=(",", ":")))
    order = [key] + [k for k in _order(config) if k != key]
    for old in order[KEEP:]:
        config.DeleteEntry(PREFIX + old)
    config.Write(ORDER_KEY, json.dumps(order[:KEEP]))
    config.Flush()


def canvas_view(canvas: Any) -> Dict[str, Any]:
    """A canvas' zoom and pan to store."""
    (pan_x, pan_y), zoom = canvas.get_view_state()
    return view_dict(((pan_x, pan_y), zoom))


def view_dict(view: View) -> Dict[str, Any]:
    (pan_x, pan_y), zoom = view
    return {"pan": [round(float(pan_x), 2), round(float(pan_y), 2)], "zoom": float(zoom)}


def parse_view(data: Any) -> Optional[View]:
    """(pan, zoom) from a stored canvas view; None when it is missing or not a view."""
    if not isinstance(data, dict):
        return None
    try:
        pan_x, pan_y = (float(v) for v in data["pan"])
        zoom = float(data["zoom"])
    except (KeyError, TypeError, ValueError):
        return None
    if not zoom > 0 or any(v != v or abs(v) > 1e7 for v in (pan_x, pan_y, zoom)):  # NaN or nonsense
        return None
    return (pan_x, pan_y), zoom


def ids(data: Any) -> List[str]:
    """A stored list of ids (anything else in it is dropped)."""
    return [i for i in data if isinstance(i, str)] if isinstance(data, list) else []


def text(data: Any) -> Optional[str]:
    return data if isinstance(data, str) else None
