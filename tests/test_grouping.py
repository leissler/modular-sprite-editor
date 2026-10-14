"""Groups and sort orders of the Frames and Animations lists (ui/grouping.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import Animation, Frame  # noqa: E402
from ui import grouping  # noqa: E402


def _anims(*entries):
    return [Animation(id=f"a{i}", name=name, group=group) for i, (name, group) in enumerate(entries)]


class GroupingTest(unittest.TestCase):
    def test_numbers_in_names_sort_as_numbers(self):
        names = ["Walk 10", "walk 2", "Attack", "C34 Attack", "C4 Run", "Walk 1b", "Walk 1"]
        self.assertEqual(sorted(names, key=grouping.natural_key),
                         ["Attack", "C4 Run", "C34 Attack", "Walk 1", "Walk 1b", "walk 2", "Walk 10"])
        self.assertEqual(sorted(["10 steps", "9 steps", "steps"], key=grouping.natural_key),
                         ["9 steps", "10 steps", "steps"], "names that start with a number")

    def test_groups_and_filters(self):
        items = _anims(("Run", "Sonic"), ("Idle", ""), ("Fly", "Tails"), ("Spin", "Sonic"), ("Jump 10", "Sonic"),
                       ("Jump 9", "Sonic"))
        self.assertEqual(grouping.groups_of(items), [("Sonic", 4), ("Tails", 1)])
        names = lambda found: [a.name for a in found]  # noqa: E731
        self.assertEqual(names(grouping.shown(items)), [a.name for a in items], "everything, in list order")
        self.assertEqual(names(grouping.shown(items, group="Sonic")), ["Run", "Spin", "Jump 10", "Jump 9"])
        self.assertEqual(names(grouping.shown(items, group="")), ["Idle"], "the items without a group")
        self.assertEqual(names(grouping.shown(items, text="tails")), ["Fly"], "the filter text finds groups too")
        self.assertEqual(names(grouping.shown(items, sort="name")), ["Fly", "Idle", "Jump 9", "Jump 10", "Run", "Spin"])
        self.assertEqual(names(grouping.shown(items, sort="group")),
                         ["Run", "Spin", "Jump 10", "Jump 9", "Fly", "Idle"], "by group, list order inside, none last")
        frames = [Frame(id="f1", name="b", group="x"), Frame(id="f2", name="a")]
        self.assertEqual([f.id for f in grouping.shown(frames, sort="name")], ["f2", "f1"])


if __name__ == "__main__":
    unittest.main()
