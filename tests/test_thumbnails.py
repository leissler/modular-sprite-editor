"""Frame thumbnails (palettes, libraries, mapping preview) must show what the editor canvas shows.

Skipped when wxPython cannot start (e.g. headless CI without a display).
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_export_canvas_parity as parity  # noqa: E402  (builds the synthetic nested / rotated project)

from models import Project  # noqa: E402

BACKGROUND = (50, 50, 50)
SIZE = 640  # wider than the widest synthetic frame, so nothing is clipped at scale 1


@unittest.skipIf(parity.wx is None, "wxPython display not available")
class TestFrameThumbnails(unittest.TestCase):
    def test_thumbnails_match_the_canvas(self):
        import wx

        from ui.animation_editor.stage import AnimationStage
        from ui.utils import ThumbnailGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            sheet = os.path.join(tmpdir, "sheet.png")
            parity._asymmetric_sheet(sheet)
            path = os.path.join(tmpdir, "thumbs.json")
            parity._build_project(sheet).to_json(path)
            project = Project.from_json(path)
            canvas = AnimationStage(parity._PARENT, project)
            generator = ThumbnailGenerator()
            checked = 0
            for frame in project.frames:
                expected = parity.check_export_parity.canvas_pixels(canvas, frame)
                if not expected:
                    continue
                bmp = generator.render_thumbnail(project, frame, SIZE, SIZE, custom_scale=1.0)
                data = bmp.ConvertToImage().GetData()
                actual = {
                    (x, y)
                    for y in range(SIZE)
                    for x in range(SIZE)
                    if tuple(data[(y * SIZE + x) * 3:(y * SIZE + x) * 3 + 3]) != BACKGROUND
                }
                ex = min(x for x, _y in expected), min(y for _x, y in expected)
                ax = min(x for x, _y in actual), min(y for _x, y in actual)
                expected = {(x - ex[0], y - ex[1]) for x, y in expected}
                actual = {(x - ax[0], y - ax[1]) for x, y in actual}
                self.assertEqual(expected, actual, f"thumbnail of '{frame.name}' differs from the canvas")
                checked += 1
            canvas.Destroy()
        self.assertGreaterEqual(checked, 4)


if __name__ == "__main__":
    unittest.main()
