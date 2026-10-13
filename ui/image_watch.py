"""Which project images changed on disk (wx-free).

The main window compares stamps (modification time and size) when it becomes active again, so a sheet edited in
another program shows its new pixels without anyone pressing Reload.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

from models import Project

Stamp = Optional[Tuple[int, int]]  # (modification time in ns, size in bytes); None = the file is missing


def image_stamp(path: str) -> Stamp:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def image_stamps(project: Project) -> Dict[str, Stamp]:
    return {asset.id: image_stamp(asset.file_path) for asset in project.images}


def changed_images(known: Dict[str, Stamp], now: Dict[str, Stamp]) -> List[str]:
    """Ids of images whose file changed, appeared or disappeared since ``known`` (images not known yet are not
    changed: they are just new to the project)."""
    return [image_id for image_id, stamp in now.items() if image_id in known and known[image_id] != stamp]


def update_image_sizes(project: Project, image_ids: Iterable[str]) -> List[str]:
    """Read the size of changed images again (an artist may have enlarged the sheet). Returns the ids whose size
    changed."""
    from PIL import Image as PILImage

    resized: List[str] = []
    for image_id in image_ids:
        asset = project.get_image(image_id)
        if asset is None:
            continue
        try:
            with PILImage.open(asset.file_path) as image:
                size = image.size
        except OSError:
            continue
        if (asset.width, asset.height) != size:
            asset.width, asset.height = size
            resized.append(image_id)
    return resized
