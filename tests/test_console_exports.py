"""The consoles the editor exports for (console_exports.py): every entry has what full support needs behind it
(docs/CONSOLES.md), named after the console's key, and the editor's build specs bundle every exporter."""

import inspect
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from PIL import Image

import console_exports
import consoles
import hardware_budget as hb
import project_check as pc
from models import AFrame, Animation, FModule, Frame, ImageAsset, Module, Project

REPO = Path(__file__).resolve().parents[1]
EDITOR_SPECS = ("build_mac.spec", "build_windows.spec", "build_linux.spec")


def _project(folder: Path) -> Project:
    """A small project: one module, a frame, an animation that mirrors it."""
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


def run_spec(name: str) -> dict:
    """What a PyInstaller spec passes to Analysis, EXE, ... (stand-ins that keep their arguments)."""
    made = {}

    def stand_in(kind):
        def make(*args, **kwargs):
            made[kind] = types.SimpleNamespace(args=args, kwargs=kwargs, pure=[], zipped_data=[], scripts=[],
                                               binaries=[], zipfiles=[], datas=[])
            return made[kind]
        return make

    path = REPO / name
    namespace = {kind: stand_in(kind) for kind in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")}
    namespace.update(SPECPATH=str(REPO), SPEC=str(path), __name__="__main__")
    path_before = list(sys.path)
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    finally:
        sys.path[:] = path_before
    return made


class RegistryTest(unittest.TestCase):
    def test_one_entry_per_console_with_an_export(self):
        keys = [export.key for export in console_exports.EXPORTS]
        self.assertEqual(keys, ["megadrive", "snes"])
        self.assertEqual(len({export.preference for export in console_exports.EXPORTS}), len(keys))
        for console in consoles.CONSOLES:
            export = console_exports.for_console(console.key)
            with self.subTest(console.key):
                self.assertEqual(console.exporter, export.sdk if export else "")
                profile = hb.profile_by_key(console.budgets[0].key)
                self.assertEqual(bool(profile.vram_tiles), export is not None, "video memory where an export counts it")
                if export:
                    self.assertIs(export.console, console)
                    self.assertEqual(profile.vram_model, export.key)
        self.assertIs(console_exports.for_console(""), console_exports.MEGA_DRIVE, "the default console's")
        self.assertIsNone(console_exports.for_console("nes"))

    def test_the_labels(self):
        self.assertEqual([e.title for e in console_exports.EXPORTS], ["Mega Drive (SGDK)", "SNES (PVSnesLib)"])
        self.assertEqual(console_exports.SNES.runtime_names(),
                         "src/modsprite.c, src/modsprite_draw.asm and inc/modsprite.h")
        self.assertEqual(console_exports.MEGA_DRIVE.runtime_names(), "src/modsprite.c and inc/modsprite.h")

    def test_every_entry_has_what_full_support_needs(self):
        tracked = set(subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                                     check=True).stdout.decode("utf-8").split("\0"))
        for export in console_exports.EXPORTS:
            with self.subTest(export.key):
                for path in (export.script, export.spec, export.readme):
                    self.assertIn(path, tracked)
                self.assertTrue((REPO / export.demo).is_dir(), export.demo)
                self.assertTrue(export.has_runtime(str(REPO / export.demo)), "the demo has the runtime")
                for script in export.kit_scripts:
                    self.assertIn(f"packaging/windows_kit/{script}", tracked)
                self.assertIn("{runtime}", export.intro, "the dialog names the runtime's files")
                self.assertTrue(export.sdk_folder and export.sdk_keep and export.sdk_needs)
                if export.sdk_in_git:
                    for need in export.sdk_needs:
                        self.assertTrue(any(p.startswith(export.sdk_path + need) for p in tracked), need)
                if export.setups:
                    self.assertGreater(len(export.console.budgets), 1, "setups to choose from")

    def test_the_exporters(self):
        for export in console_exports.EXPORTS:
            with self.subTest(export.key):
                module = export.load()
                self.assertEqual(module.__name__, export.module)
                for name in ("export_project", "report_line", "main"):
                    self.assertTrue(callable(getattr(module, name, None)), name)
                takes = inspect.signature(module.export_project).parameters
                self.assertEqual("setup_key" in takes, bool(export.setups), "a setup where the export has setups")

    def test_the_checks(self):
        for export in console_exports.EXPORTS:
            capacity = export.console.sprites.tiles
            with self.subTest(export.key):
                self.assertEqual(export.tile_issue(1).level, pc.INFO)
                self.assertEqual(export.tile_issue(capacity + 1).level, pc.ERROR)
                self.assertEqual(export.tile_issue(capacity + 1).code, "too-many-tiles")
                self.assertIsNone(export.palette_issue(1), "one palette always fits")
                self.assertEqual(export.palette_issue(export.console.palette.palettes + 1).code, "palette-lines")

    def test_an_export_into_a_game_folder(self):
        for export in console_exports.EXPORTS:
            with self.subTest(export.key), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp).resolve()
                project = _project(folder)
                setup = export.console.budgets[-1].key if export.setups else ""
                result = export.export(project, str(folder / "game"), "all", setup)
                self.assertTrue(result.files and all(path.exists() for path in result.files))
                profile = hb.profile_by_key(setup or export.console.budgets[0].key)
                tiles = hb.BudgetCalculator().export_tiles(project, [None], profile)
                self.assertEqual(result.summary["tiles"], tiles, "what the budget counts")
                self.assertIn(str(tiles), export.report_line(result.summary))


class BuildTest(unittest.TestCase):
    def test_the_editor_specs_bundle_every_exporter(self):
        for name in EDITOR_SPECS:
            with self.subTest(name):
                analysis = run_spec(name)["Analysis"].kwargs
                for export in console_exports.EXPORTS:
                    self.assertIn(export.tools, analysis["pathex"])
                    self.assertIn(export.module, analysis["hiddenimports"])

    def test_every_exporter_spec(self):
        for export in console_exports.EXPORTS:
            with self.subTest(export.spec):
                made = run_spec(export.spec)
                self.assertEqual(made["Analysis"].args[0], [export.script])
                self.assertEqual(made["EXE"].kwargs["name"], export.module)


if __name__ == "__main__":
    unittest.main()
