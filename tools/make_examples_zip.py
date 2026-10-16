"""Zip the example projects for the release page: each project with its image (and credits) in the repository's
examples/ layout, so the user guide's paths apply, plus the README from packaging/examples.

Only git-tracked files go in. Every image a project uses must be in the zip, where the project looks for it.

Usage:
    python3 tools/make_examples_zip.py OUT_ZIP [--version 0.7]
"""
from __future__ import annotations

import argparse
import json
import posixpath
import zipfile
from pathlib import Path
from typing import List

from make_windows_kit import tracked

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = ["examples/pop/PoP_WW.json", "examples/pop/modules_POP.bmp", "examples/sonic/", "examples/adventurer/"]
README = REPO / "packaging" / "examples" / "README.txt"


def example_files() -> List[str]:
    files: List[str] = []
    for item in EXAMPLES:
        found = tracked(item)
        if not found:
            raise SystemExit(f"not in git: {item}")
        files += found
    return files


def check_images(files: List[str]) -> None:
    present = set(files)
    for path in files:
        if not path.endswith(".json"):
            continue
        project = json.loads((REPO / path).read_text(encoding="utf-8"))
        for image in project.get("images", []):
            wanted = posixpath.normpath(posixpath.join(posixpath.dirname(path), image["file_path"]))
            if wanted not in present:
                raise SystemExit(f"{path} uses {image['file_path']}, which would not be in the zip")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_zip", type=Path)
    parser.add_argument("--version", default="")
    args = parser.parse_args()

    files = example_files()
    check_images(files)
    args.out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        out.writestr("examples/README.txt", README.read_text(encoding="utf-8").replace("@VERSION@", args.version))
        for path in files:
            out.write(REPO / path, path)
    print(f"{args.out_zip}: {len(files) + 1} files, {args.out_zip.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
