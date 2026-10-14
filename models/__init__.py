"""The data model (wx-free): everything a project holds, its JSON and the format migration.

``core`` has the sprite data (images, modules, frames, animations, mappings, palettes, swaps, types), ``timeline`` the scenes and their
evaluation, ``migration`` the format version and the upgrade of older files, ``project`` the Project. Import from
``models``; importers, exporters and the compositor live in their own packages (``importers``, ``exporters``,
``compositor``).
"""

from models.core import (
    RGB,
    AFrame,
    Animation,
    CollisionRect,
    ColourCycle,
    CollisionType,
    ControlPoint,
    EventType,
    FModule,
    Frame,
    ImageAsset,
    Module,
    ModuleMapping,
    Palette,
    PaletteChange,
    PaletteSwap,
    PointType,
    StepEvent,
    generate_id,
)
from models.migration import PROJECT_FORMAT_VERSION, migrate_project_dict
from models.project import Project
from models.timeline import (
    TIMELINE_EASINGS,
    TIMELINE_MAPPING_ORIGINAL,
    TIMELINE_PATH_MODES,
    TIMELINE_SOURCE_TYPES,
    TimelineKeyframe,
    TimelineObject,
    TimelineScene,
    apply_timeline_easing,
)

__all__ = [
    "RGB",
    "AFrame",
    "Animation",
    "CollisionRect",
    "ColourCycle",
    "CollisionType",
    "ControlPoint",
    "EventType",
    "FModule",
    "Frame",
    "ImageAsset",
    "Module",
    "ModuleMapping",
    "Palette",
    "PaletteChange",
    "PaletteSwap",
    "PointType",
    "StepEvent",
    "generate_id",
    "PROJECT_FORMAT_VERSION",
    "migrate_project_dict",
    "Project",
    "TIMELINE_EASINGS",
    "TIMELINE_MAPPING_ORIGINAL",
    "TIMELINE_PATH_MODES",
    "TIMELINE_SOURCE_TYPES",
    "TimelineKeyframe",
    "TimelineObject",
    "TimelineScene",
    "apply_timeline_easing",
]
