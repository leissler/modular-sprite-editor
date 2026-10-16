"""Zip the SNES demo for the release page: the ROM the release workflow built (and checked in Mesen) with the README
from packaging/snes_demo, and the demo's PVSnesLib project in the repository's examples/ layout, so its README and the
user guide's paths apply (unpacked next to the example projects, it joins their examples/ folder).

Only git-tracked files go in, besides the ROM; PVSnesLib does not (its README says where to get it).

Usage:
    python3 tools/make_snes_demo_zip.py ROM OUT_ZIP [--version 0.10.1]
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from make_windows_kit import tracked

REPO = Path(__file__).resolve().parents[1]
PROJECT = ["examples/snes/README.md", "examples/snes/snes_demo/"]
README = REPO / "packaging" / "snes_demo" / "README.txt"
ROM_NAME = "modular_sprite_snes_demo.sfc"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("out_zip", type=Path)
    parser.add_argument("--version", default="")
    args = parser.parse_args()

    if args.rom.stat().st_size % 0x8000:
        raise SystemExit(f"{args.rom} is no SNES ROM (not whole 32 KB banks)")
    files = []
    for item in PROJECT:
        found = tracked(item)
        if not found:
            raise SystemExit(f"not in git: {item}")
        files += found
    args.out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        out.writestr("README.txt", README.read_text(encoding="utf-8").replace("@VERSION@", args.version))
        out.write(args.rom, ROM_NAME)
        for path in files:
            out.write(REPO / path, path)
    print(f"{args.out_zip}: {len(files) + 2} files, {args.out_zip.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
