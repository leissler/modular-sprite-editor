"""The SNES demo outside the source tree: its Windows build and what the release and the Windows kit carry.

- examples/snes/snes_demo/build_windows.ps1 builds the demo the way PVSnesLib's make does (CI builds it on Windows and
  plays the ROM next to the Linux build, tools/compare_snes_roms.py): it must know every setting the demo's Makefile
  and the exporter's modsprite_rom.mk (which CI checks is what the exporter writes) give.
- tools/make_windows_kit.py takes what the build needs from PVSnesLib's Windows release, and tools/make_snes_demo_zip.py
  zips the ROM with the demo's whole project.
"""

import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import make_snes_demo_zip  # noqa: E402
import make_windows_kit  # noqa: E402

DEMO = REPO / "examples" / "snes" / "snes_demo"


def settings(text: str) -> set:
    return {m.group(1) for m in re.finditer(r"^\s*(?:export\s+)?([A-Za-z_]\w*)\s*:?=", text, re.M)}


class WindowsBuildTest(unittest.TestCase):
    def test_it_knows_every_setting(self):
        script = (DEMO / "build_windows.ps1").read_text(encoding="utf-8")
        given = settings((DEMO / "Makefile").read_text()) | settings((DEMO / "modsprite_rom.mk").read_text())
        self.assertIn("ROMBANKS", given)
        for name in given - {"PVSNESLIB_HOME"}:  # the script looks for PVSnesLib itself
            self.assertIn(f'"{name}"', script, f"build_windows.ps1 does not read the Makefile's {name}")

    def test_it_is_plain_ascii(self):
        """Windows PowerShell 5.1 reads a script without a byte order mark in the system's code page."""
        (DEMO / "build_windows.ps1").read_bytes().decode("ascii")


class PackagingTest(unittest.TestCase):
    def test_the_kit_takes_the_tools_headers_libraries_and_license(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("devkitsnes/bin/816-tcc.exe", "devkitsnes/bin/wla-65816.exe", "devkitsnes/bin/wlalink.exe",
                         "devkitsnes/bin/.keepme", "devkitsnes/tools/816-opt.exe", "devkitsnes/include/hdr.asm.in",
                         "devkitsnes/snes_rules", "pvsneslib/include/snes.h", "pvsneslib/lib/LoROM_FastROM/libc.obj",
                         "pvsneslib/pvsneslib_license.txt", "pvsneslib/html/index.html",
                         "snes-examples/hello_world/Makefile", "vscode-template/README.md"):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text("x")
            kept = {name for _path, name in make_windows_kit.pvsneslib_files(root)}
        base = make_windows_kit.PVSNESLIB
        self.assertEqual(kept, {base + n for n in (
            "devkitsnes/bin/816-tcc.exe", "devkitsnes/bin/wla-65816.exe", "devkitsnes/bin/wlalink.exe",
            "devkitsnes/tools/816-opt.exe", "devkitsnes/include/hdr.asm.in", "devkitsnes/snes_rules",
            "pvsneslib/include/snes.h", "pvsneslib/lib/LoROM_FastROM/libc.obj", "pvsneslib/pvsneslib_license.txt")})
        self.assertTrue(base.startswith("examples/snes/snes_demo/third_party/pvsneslib"),
                        "where build_windows.ps1 looks without PVSNESLIB_HOME")

    def test_the_kit_has_the_demo_and_its_windows_build(self):
        files = make_windows_kit.kit_files()
        for name in ("examples/snes/README.md", "examples/snes/snes_demo/build_windows.ps1",
                     "examples/snes/snes_demo/src/modsprite_draw.asm", "examples/snes/snes_demo/res/ms_chunk_00.bin"):
            self.assertIn(name, files)
        self.assertTrue((make_windows_kit.PACKAGING / "build_snes_demo.bat").exists())

    def test_the_demo_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            rom, out = Path(tmp) / "demo.sfc", Path(tmp) / "demo.zip"
            rom.write_bytes(bytes(0x8000 * 16))
            argv = sys.argv
            sys.argv = ["make_snes_demo_zip.py", str(rom), str(out), "--version", "9.9"]
            try:
                self.assertEqual(make_snes_demo_zip.main(), 0)
            finally:
                sys.argv = argv
            with zipfile.ZipFile(out) as archive:
                names = set(archive.namelist())
                readme = archive.read("README.txt").decode("utf-8")
        self.assertIn("modular_sprite_snes_demo.sfc", names)
        self.assertIn("9.9", readme)
        self.assertEqual({n for n in names if n.startswith("examples/")},
                         set(make_windows_kit.tracked("examples/snes/snes_demo/")) | {"examples/snes/README.md"})


if __name__ == "__main__":
    unittest.main()
