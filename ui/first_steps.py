"""What a tab needs before it can do anything, as a hint for its empty state (wx-free).

The order of work is modules → frames → animations → scenes, with mappings swapping modules and palettes holding the
images' colours; an empty tab points to the step before it instead of to a button that cannot help yet.
"""

from __future__ import annotations

from typing import Optional

from models import Project


def frames(project: Optional[Project]) -> Optional[str]:
    if project is not None and not project.modules:
        return "Frames are built from modules: cut them from a sprite sheet in the Modules tab first."
    return None


def animations(project: Optional[Project]) -> Optional[str]:
    if project is not None and not project.frames:
        return "Animations play frames: build some in the Frames tab first."
    return None


def scenes(project: Optional[Project]) -> Optional[str]:
    if project is not None and not (project.animations or project.frames or project.modules):
        return "Scenes arrange animations, frames and modules: make some in the other tabs first."
    return None


def mappings(project: Optional[Project]) -> Optional[str]:
    if project is not None and not project.modules:
        return "Mappings swap one module for another: cut modules in the Modules tab first."
    return None


def palettes(project: Optional[Project]) -> Optional[str]:
    if project is not None and not project.images:
        return "Palettes hold the colours of your images: add an image in the Modules tab first."
    return None
