"""Assemble the Windows kit: the editor, the SGDK exporter, the example projects and the SGDK demo with the
part of SGDK it builds with, plus the README and helper scripts from packaging/windows_kit.

Only git-tracked files go in (no build output). Unpacked, the kit has the repo's examples/ layout, so the
exporter's defaults and examples/sgdk/README.md apply.

Usage:
    python3 tools/make_windows_kit.py EDITOR_EXE EXPORTER_EXE OUT_ZIP [--version 0.4]
"""
from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[1]
KIT_DIR = "ModularSpriteEditor-windows"  # the folder inside the zip
PACKAGING = REPO / "packaging" / "windows_kit"
EXAMPLES = ["examples/sgdk/PoP_WW.json", "examples/sgdk/modules_POP.bmp", "examples/sgdk/README.md", "examples/sonic/",
            "examples/adventurer/"]
DEMO = "examples/sgdk/sgdk_demo/"
SGDK = DEMO + "third_party/sgdk/"
# What building the demo needs (Windows tools, headers, prebuilt libraries, boot code) and SGDK's license;
# its samples, docs and tool sources stay out.
SGDK_KEEP = ("bin/", "inc/", "lib/", "src/", "res/", "common.mk", "makefile.gen", "makelib.gen", "md.ld",
             "license.txt", "COPYING.RUNTIME", "readme.md", "changelog.txt")


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
    return files


def windows_text(path: Path, version: str) -> bytes:
    """README / batch files with CRLF line ends (cmd.exe needs them for labels) and the version filled in."""
    text = path.read_text(encoding="utf-8").replace("@VERSION@", version)
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("editor_exe", type=Path)
    parser.add_argument("exporter_exe", type=Path)
    parser.add_argument("out_zip", type=Path)
    parser.add_argument("--version", default="")
    args = parser.parse_args()

    files = kit_files()
    args.out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as kit:
        kit.write(args.editor_exe, f"{KIT_DIR}/ModularSpriteEditor.exe")
        kit.write(args.exporter_exe, f"{KIT_DIR}/export_sgdk.exe")
        for extra in sorted(PACKAGING.iterdir()):
            kit.writestr(f"{KIT_DIR}/{extra.name}", windows_text(extra, args.version))
        for path in files:
            kit.write(REPO / path, f"{KIT_DIR}/{path}")
    size = args.out_zip.stat().st_size
    print(f"{args.out_zip}: {len(files) + 2 + len(list(PACKAGING.iterdir()))} files, {size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
