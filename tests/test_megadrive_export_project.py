"""The Mega Drive export as the editor runs it: export_project writes into a game folder and reports what the game
gets; the game's own resources stay in res/resources.res."""

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "examples" / "megadrive" / "tools"))

import project_check as pc  # noqa: E402
from models import AFrame, Animation, FModule, Frame, ImageAsset, Module, Project  # noqa: E402


def _project(folder: Path) -> Project:
    sheet = folder / "sheet.png"
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for x in range(4, 12):
        for y in range(2, 14):
            image.putpixel((x, y), (200, 60, 40, 255) if y < 8 else (40, 60, 200, 255))
    image.save(sheet)
    project = Project()
    project.images.append(ImageAsset("img", str(sheet), 16, 16))
    project.modules.append(Module("m", "body", "img", (0, 0, 16, 16), (8, 16)))
    project.frames.append(Frame("f", "stand", fmodules=[FModule("p", "module", "m", (0, 0))]))
    project.animations.append(Animation("a", "idle", aframes=[AFrame("f", 4), AFrame("f", 4, flip_x=True)]))
    return project


class TestMergedResources(unittest.TestCase):
    def setUp(self):
        import export_megadrive as sg

        self.sg = sg

    def test_new_file_gets_the_blob_line(self):
        self.assertEqual(self.sg.merged_resources(None), self.sg.RESOURCE_LINE + "\n")
        self.assertEqual(self.sg.merged_resources(""), self.sg.RESOURCE_LINE + "\n")

    def test_the_games_resources_stay(self):
        game = 'IMAGE BG_TITLE "title.png" BEST\nXGM2 MUSIC "music.vgm"\n'
        merged = self.sg.merged_resources(game)
        self.assertEqual(merged, game + self.sg.RESOURCE_LINE + "\n")
        self.assertEqual(self.sg.merged_resources(merged), merged)  # exporting again changes nothing

    def test_an_older_blob_line_is_replaced_in_place(self):
        old = 'IMAGE A "a.png" BEST\nBIN MS_BLOB "old/blob.bin" 2\nIMAGE B "b.png" BEST\nBIN MS_BLOB "x.bin"\n'
        merged = self.sg.merged_resources(old).splitlines()
        self.assertEqual(merged, ['IMAGE A "a.png" BEST', self.sg.RESOURCE_LINE, 'IMAGE B "b.png" BEST'])

    def test_older_exporters_sprite_lines_are_dropped(self):
        old = ('SPRITE MS_VAR_0000 "gen/var_0000.png" 1 1 NONE\nSPRITE HERO "hero.png" 4 4 NONE\n'
               'SPRITE MS_VAR_0001 "gen/var_0001.png" 1 1 NONE\n')
        self.assertEqual(self.sg.merged_resources(old).splitlines(),
                         ['SPRITE HERO "hero.png" 4 4 NONE', self.sg.RESOURCE_LINE])


class TestExportProject(unittest.TestCase):
    def setUp(self):
        import export_megadrive as sg

        self.sg = sg
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.game = (self.folder / "game").resolve()  # export_project resolves it (macOS: /var is /private/var)
        (self.game / "res").mkdir(parents=True)
        (self.game / "res" / "resources.res").write_text('IMAGE BG_TITLE "title.png" BEST\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_the_data_and_keeps_the_games_resources(self):
        result = self.sg.export_project(_project(self.folder), self.game)
        self.assertEqual([path.relative_to(self.game).as_posix() for path in result.files],
                         ["res/gen/modsprite_blob.bin", "inc/modsprite_data.h", "src/modsprite_data.c",
                          "res/resources.res"])
        for path in result.files:
            self.assertTrue(path.exists(), path)
        resources = (self.game / "res" / "resources.res").read_text()
        self.assertIn("IMAGE BG_TITLE", resources)
        self.assertIn(self.sg.RESOURCE_LINE, resources)
        self.assertEqual(result.summary["animations"], 1)
        self.assertEqual(result.summary["anim_steps"], 2)
        self.assertGreater(result.summary["tiles"], 0)
        # a clean project: only the note about video memory
        self.assertEqual([(issue.level, issue.code) for issue in result.issues], [(pc.INFO, "tiles")])

    def test_only_older_exporters_files_are_removed(self):
        gen = self.game / "res" / "gen"
        gen.mkdir()
        for name in ("var_0000.png", "var_0164.png", "title.png", "music.bin", "var_hero.png"):
            (gen / name).write_bytes(b"x")
        self.sg.export_project(_project(self.folder), self.game)
        self.assertEqual(sorted(path.name for path in gen.iterdir()),
                         ["modsprite_blob.bin", "music.bin", "title.png", "var_hero.png"])

    def test_reports_what_the_game_would_lose(self):
        project = _project(self.folder)
        project.animations[0].aframes.append(AFrame("gone", 2))  # its frame was deleted
        project.frames[0].fmodules.append(FModule("q", "module", "gone", (4, 4)))
        result = self.sg.export_project(project, self.game)
        found = [(issue.level, issue.code) for issue in result.issues]
        self.assertIn((pc.ERROR, "missing-step"), found)
        self.assertIn((pc.ERROR, "missing-part"), found)
        self.assertEqual(found[-1], (pc.INFO, "tiles"))  # errors first, notes last
        self.assertEqual(result.summary["anim_steps"], 2)  # the export drops the missing step, now it says so

    def test_tile_capacity(self):
        self.assertEqual(pc.megadrive_tile_issue(100).level, pc.INFO)
        self.assertEqual(pc.megadrive_tile_issue(pc.MD_TILE_CAPACITY).level, pc.WARNING)
        self.assertEqual(pc.megadrive_tile_issue(pc.MD_TILE_CAPACITY + 1).level, pc.ERROR)


if __name__ == "__main__":
    unittest.main()
