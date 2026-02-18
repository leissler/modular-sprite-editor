import unittest

from models import Project, Frame, FModule
from optimization import optimize_nested_frame_combos


class TestNestedFrameComboOptimization(unittest.TestCase):
    def _seed_modules(self, project: Project):
        asset = project.create_image("dummy.png", 64, 64)
        m1 = project.create_module("M1", asset.id, (0, 0, 8, 8), (4, 4))
        m2 = project.create_module("M2", asset.id, (8, 0, 8, 8), (4, 4))
        m3 = project.create_module("M3", asset.id, (16, 0, 8, 8), (4, 4))
        return m1, m2, m3

    def test_repeated_triple_is_extracted_to_helper_frame(self):
        project = Project()
        m1, m2, m3 = self._seed_modules(project)

        f1 = Frame(
            id="frm_a",
            name="A",
            fmodules=[
                FModule(id="fm_a1", ref_type="module", ref_id=m1.id, position=(10, 20)),
                FModule(id="fm_a2", ref_type="module", ref_id=m2.id, position=(14, 20)),
                FModule(id="fm_a3", ref_type="module", ref_id=m3.id, position=(18, 22)),
            ],
        )
        f2 = Frame(
            id="frm_b",
            name="B",
            fmodules=[
                FModule(id="fm_b1", ref_type="module", ref_id=m1.id, position=(40, 10)),
                FModule(id="fm_b2", ref_type="module", ref_id=m2.id, position=(44, 10)),
                FModule(id="fm_b3", ref_type="module", ref_id=m3.id, position=(48, 12)),
            ],
        )
        project.frames.extend([f1, f2])

        success, msg = optimize_nested_frame_combos(
            project,
            {
                "min_combo_size": 3,
                "max_combo_size": 3,
                "min_support": 2,
                "min_net_savings": 1,
            },
        )
        self.assertTrue(success, msg)

        frame_a = project.get_frame("frm_a")
        frame_b = project.get_frame("frm_b")
        self.assertIsNotNone(frame_a)
        self.assertIsNotNone(frame_b)
        self.assertEqual(len(frame_a.fmodules), 1)
        self.assertEqual(len(frame_b.fmodules), 1)
        self.assertEqual(frame_a.fmodules[0].ref_type, "frame")
        self.assertEqual(frame_b.fmodules[0].ref_type, "frame")
        self.assertEqual(frame_a.fmodules[0].ref_id, frame_b.fmodules[0].ref_id)

        helper = project.get_frame(frame_a.fmodules[0].ref_id)
        self.assertIsNotNone(helper)
        self.assertEqual(len(helper.fmodules), 3)
        self.assertTrue(all(fm.ref_type == "module" for fm in helper.fmodules))

    def test_no_benefit_pair_combo_is_not_applied(self):
        project = Project()
        m1, m2, _m3 = self._seed_modules(project)

        f1 = Frame(
            id="frm_c",
            name="C",
            fmodules=[
                FModule(id="fm_c1", ref_type="module", ref_id=m1.id, position=(0, 0)),
                FModule(id="fm_c2", ref_type="module", ref_id=m2.id, position=(4, 0)),
            ],
        )
        f2 = Frame(
            id="frm_d",
            name="D",
            fmodules=[
                FModule(id="fm_d1", ref_type="module", ref_id=m1.id, position=(20, 5)),
                FModule(id="fm_d2", ref_type="module", ref_id=m2.id, position=(24, 5)),
            ],
        )
        project.frames.extend([f1, f2])

        success, msg = optimize_nested_frame_combos(
            project,
            {
                "min_combo_size": 2,
                "max_combo_size": 2,
                "min_support": 2,
                "min_net_savings": 1,
            },
        )
        self.assertFalse(success)
        self.assertIn("No beneficial", msg)


if __name__ == "__main__":
    unittest.main()
