"""Undo and redo restore every saved field of a project, and never lose the redo steps."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import (  # noqa: E402
    Animation,
    CollisionType,
    EventType,
    Frame,
    ImageAsset,
    Module,
    ModuleMapping,
    Palette,
    PaletteSwap,
    PointType,
    Project,
    TimelineScene,
)
from ui.project_history import SAVED_FIELDS, ProjectHistory, project_fingerprint  # noqa: E402

EXAMPLE = ROOT / "examples" / "sgdk" / "PoP_WW.json"

# One change per saved field; a new field without an entry here fails test_every_field_is_covered.
CHANGES = {
    "name": lambda p: setattr(p, "name", p.name + " changed"),
    "images": lambda p: p.images.append(ImageAsset(id="img_new", file_path="/tmp/x.png", width=8, height=8)),
    "modules": lambda p: p.modules.append(Module(id="mod_new", name="new", image_id="img", rect=(0, 0, 8, 8), pivot=(0, 0))),
    "frames": lambda p: p.frames.append(Frame(id="frm_new", name="new")),
    "animations": lambda p: p.animations.append(Animation(id="anim_new", name="new")),
    "timeline_scenes": lambda p: p.timeline_scenes.append(TimelineScene(id="scene_new", name="new")),
    "mappings": lambda p: p.mappings.append(ModuleMapping(id="map_new", name="new")),
    "collision_types": lambda p: p.collision_types.append(CollisionType(id="ct_new", name="new", color=(1, 2, 3))),
    "point_types": lambda p: p.point_types.append(PointType(id="pt_new", name="new", color=(1, 2, 3))),
    "event_types": lambda p: p.event_types.append(EventType(id="evt_new", name="new", color=(1, 2, 3))),
    "console": lambda p: setattr(p, "console", "snes"),
    "palettes": lambda p: p.palettes.append(Palette(id="pal_new", name="new", colours=[(1, 2, 3)])),
    "palette_swaps": lambda p: p.palette_swaps.append(PaletteSwap(id="swap_new", name="new")),
}


class ProjectHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project.from_json(str(EXAMPLE))
        self.history = ProjectHistory()
        self.history.reset(self.project)
        self.original = project_fingerprint(self.project)[0]

    def test_every_field_is_covered(self) -> None:
        self.assertEqual(set(CHANGES), set(SAVED_FIELDS))

    def test_undo_and_redo_restore_each_field(self) -> None:
        for name, change in CHANGES.items():
            with self.subTest(field=name):
                change(self.project)
                self.history.checkpoint(self.project)
                changed = project_fingerprint(self.project)[0]
                self.assertNotEqual(changed, self.original)
                self.assertTrue(self.history.undo(self.project))
                self.assertEqual(project_fingerprint(self.project)[0], self.original, f"undo restores {name}")
                self.assertTrue(self.history.redo(self.project))
                self.assertEqual(project_fingerprint(self.project)[0], changed, f"redo brings {name} back")
                self.history.undo(self.project)

    def test_renaming_an_event_type_is_undone(self) -> None:
        before = [t.name for t in self.project.event_types]
        self.project.event_types[0].name = "renamed"
        self.history.checkpoint(self.project)
        self.history.undo(self.project)
        self.assertEqual([t.name for t in self.project.event_types], before)

    def test_checkpoint_after_undo_keeps_the_redo_steps(self) -> None:
        self.project.event_types[0].name = "renamed"
        self.history.checkpoint(self.project)
        self.history.undo(self.project)
        self.assertFalse(self.history.checkpoint(self.project), "nothing changed since the undo")
        self.assertTrue(self.history.can_redo())
        self.assertFalse(self.history.is_dirty(self.project))

    def test_preview_mapping_survives_undo(self) -> None:
        mapping = self.project.mappings[0]
        self.project.active_mapping = mapping
        self.project.name = "changed"
        self.history.checkpoint(self.project)
        self.history.undo(self.project)
        self.assertIsNotNone(self.project.active_mapping)
        self.assertEqual(self.project.active_mapping.id, mapping.id)


if __name__ == "__main__":
    unittest.main()
