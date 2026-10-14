"""Project.get_*: fast lookups by id that stay right however the lists are edited in place."""

import unittest

from models import Frame, Project


def frames(*ids: str):
    return [Frame(id=i, name=i) for i in ids]


class TestLookups(unittest.TestCase):
    def setUp(self):
        self.project = Project()
        self.project.frames = frames("a", "b", "c")

    def check_all(self):
        for frame in self.project.frames:
            first = next(f for f in self.project.frames if f.id == frame.id)
            self.assertIs(self.project.get_frame(frame.id), first, frame.id)

    def test_found_and_missing(self):
        self.check_all()
        self.assertIsNone(self.project.get_frame("nope"))
        self.assertIsNone(self.project.get_frame(None))

    def test_the_editors_ways_of_changing_a_list(self):
        p = self.project
        self.check_all()  # positions remembered
        p.frames.insert(0, Frame(id="front", name="front"))  # every position shifts
        self.check_all()
        del p.frames[2]
        self.assertIsNone(p.get_frame("b"))
        self.check_all()
        p.frames[1] = Frame(id="swapped", name="swapped")  # same length, another id in place
        self.assertIsNone(p.get_frame("a"))
        self.check_all()
        p.frames.reverse()
        self.check_all()
        p.frames.append(Frame(id="end", name="end"))
        self.check_all()
        p.frames = frames("x", "y")  # undo / redo replace the lists
        self.assertIsNone(p.get_frame("front"))
        self.check_all()
        p.frames[0].id = "renamed"  # an id changed on the object itself
        self.assertIsNone(p.get_frame("x"))
        self.assertIs(p.get_frame("renamed"), p.frames[0])

    def test_two_with_one_id_a_scan_finds_the_first(self):
        p = self.project
        p.frames.append(Frame(id="a", name="second a"))
        self.assertEqual(p.get_frame("a").name, "a")
        p.frames.insert(0, Frame(id="a", name="new first a"))
        self.assertEqual(p.get_frame("a").name, "new first a")

    def test_every_kind_has_its_own_positions(self):
        p = Project.from_dict({"modules": [{"id": "a", "name": "m", "image_id": "i", "rect": [0, 0, 1, 1], "pivot": [0, 0]}],
                               "frames": [{"id": "a", "name": "f"}]})
        self.assertEqual((p.get_module("a").name, p.get_frame("a").name), ("m", "f"))


if __name__ == "__main__":
    unittest.main()
