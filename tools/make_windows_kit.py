"""Assemble the Windows kit: the editor, the SGDK and SNES exporters, the example projects, the SGDK demo with the part
of SGDK it builds with and the SNES demo with the part of PVSnesLib's Windows release it builds with, plus the README
and helper scripts from packaging/windows_kit.

Only git-tracked files go in (no build output), and from PVSnesLib (not in git) what the build needs. Unpacked, the kit
has the repo's examples/ layout, so the exporters' defaults and examples/megadrive/README.md and examples/snes/README.md
apply.

Usage:
    python3 tools/make_windows_kit.py EDITOR_EXE EXPORTER_EXE OUT_ZIP --snes-exporter EXE --pvsneslib DIR [--version 0.4]

DIR is PVSnesLib's Windows release unpacked (the folder with devkitsnes/ and pvsneslib/).
"""
from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path
from typing import List, Tuple

REPO = Path(__file__).resolve().parents[1]
KIT_DIR = "ModularSpriteEditor-windows"  # the folder inside the zip
PACKAGING = REPO / "packaging" / "windows_kit"
EXAMPLES = ["examples/pop/PoP_WW.json", "examples/pop/modules_POP.bmp", "examples/megadrive/README.md", "examples/sonic/",
            "examples/adventurer/"]
DEMO = "examples/megadrive/megadrive_demo/"
SGDK = DEMO + "third_party/sgdk/"
# What building the demo needs (Windows tools, headers, prebuilt libraries, boot code) and SGDK's license;
# its samples, docs and tool sources stay out.
SGDK_KEEP = ("bin/", "inc/", "lib/", "src/", "res/", "common.mk", "makefile.gen", "makelib.gen", "md.ld",
             "license.txt", "COPYING.RUNTIME", "readme.md", "changelog.txt")
SNES = ["examples/snes/README.md", "examples/snes/snes_demo/"]
PVSNESLIB = "examples/snes/snes_demo/third_party/pvsneslib/"  # where the demo's build looks for it
# What building the SNES demo needs from PVSnesLib's Windows release (tools, headers, libraries) and its license;
# its documentation, examples and editor template stay out.
PVSNESLIB_KEEP = ("devkitsnes/", "pvsneslib/include/", "pvsneslib/lib/", "pvsneslib/pvsneslib_license.txt",
                  "pvsneslib/pvsneslib_snesmod.txt", "pvsneslib/pvsneslib_version.txt")


def tracked(path: str) -> List[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--", path], cwd=REPO, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def kit_files() -> List[str]:
    files: List[str] = []
    for item in EXAMPLES:
        found = tracked(item)
        if not found:
            raise SystemExit(f"not in git: {item}")
        files += found
    for path in tracked(DEMO):
        if path.startswith(SGDK) and not path[len(SGDK):].startswith(SGDK_KEEP):
            continue
        files.append(path)
    if not any(p.startswith(SGDK + "lib/") for p in files):
        raise SystemExit("SGDK's prebuilt libraries are missing (" + SGDK + "lib/)")
    for item in SNES:
        found = tracked(item)
        if not found:
            raise SystemExit(f"not in git: {item}")
        files += found
    return files


def pvsneslib_files(folder: Path) -> List[Tuple[Path, str]]:
    """(file, its path in the kit) for what the kit takes from PVSnesLib's unpacked Windows release."""
    for tool in ("devkitsnes/bin/816-tcc.exe", "devkitsnes/bin/wla-65816.exe", "devkitsnes/bin/wlalink.exe",
                 "devkitsnes/tools/816-opt.exe", "devkitsnes/include/hdr.asm.in", "pvsneslib/lib/LoROM_FastROM"):
        if not (folder / tool).exists():
            raise SystemExit(f"not PVSnesLib's Windows release (no {tool}): {folder}")
    found = []
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if path.is_file() and name.startswith(PVSNESLIB_KEEP) and path.name != ".keepme":
            found.append((path, PVSNESLIB + name))
    return found


def windows_text(path: Path, version: str) -> bytes:
    """README / batch files with CRLF line ends (cmd.exe needs them for labels) and the version filled in."""
    text = path.read_text(encoding="utf-8").replace("@VERSION@", version)
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("editor_exe", type=Path)
    parser.add_argument("exporter_exe", type=Path)
    parser.add_argument("out_zip", type=Path)
    parser.add_argument("--snes-exporter", type=Path, required=True, help="export_snes.exe")
    parser.add_argument("--pvsneslib", type=Path, required=True, help="PVSnesLib's Windows release, unpacked")
    parser.add_argument("--version", default="")
    args = parser.parse_args()

    files = kit_files()
    pvsneslib = pvsneslib_files(args.pvsneslib)
    args.out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as kit:
        kit.write(args.editor_exe, f"{KIT_DIR}/ModularSpriteEditor.exe")
        kit.write(args.exporter_exe, f"{KIT_DIR}/export_megadrive.exe")
        kit.write(args.snes_exporter, f"{KIT_DIR}/export_snes.exe")
        for extra in sorted(PACKAGING.iterdir()):
            kit.writestr(f"{KIT_DIR}/{extra.name}", windows_text(extra, args.version))
        for path in files:
            kit.write(REPO / path, f"{KIT_DIR}/{path}")
        for path, name in pvsneslib:
            kit.write(path, f"{KIT_DIR}/{name}")
    size = args.out_zip.stat().st_size
    count = len(files) + len(pvsneslib) + 3 + len(list(PACKAGING.iterdir()))
    print(f"{args.out_zip}: {count} files ({len(pvsneslib)} of PVSnesLib), {size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
