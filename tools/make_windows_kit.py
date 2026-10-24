"""Assemble the Windows kit: the editor, every console's exporter (console_exports.py), the example projects, and each
console's demo with the part of its SDK it builds with (SGDK is in git; PVSnesLib's Windows release is given unpacked),
plus the README and helper scripts from packaging/windows_kit.

Only git-tracked files go in (no build output), and from an SDK that is not in git what the build needs. Unpacked, the
kit has the repo's examples/ layout, so the exporters' defaults and each examples/<console>/README.md apply.

Usage:
    python3 tools/make_windows_kit.py EDITOR_EXE OUT_ZIP --exporters DIR --sdk snes=DIR [--version 0.4]

--exporters is the folder with every console's exporter (export_megadrive.exe, export_snes.exe, ...: the release
workflow builds them into dist/exporter). --sdk KEY=DIR gives the SDK of a console whose SDK is not in git, unpacked:
for the SNES, PVSnesLib's Windows release (the folder with devkitsnes/ and pvsneslib/).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import console_exports  # noqa: E402
from console_exports import ConsoleExport  # noqa: E402

KIT_DIR = "ModularSpriteEditor-windows"  # the folder inside the zip
PACKAGING = REPO / "packaging" / "windows_kit"
EXAMPLES = ["examples/pop/PoP_WW.json", "examples/pop/modules_POP.bmp", "examples/sonic/", "examples/adventurer/"]
PVSNESLIB = console_exports.SNES.sdk_path  # where the SNES demo's build looks for PVSnesLib


def tracked(path: str) -> List[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--", path], cwd=REPO, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _tracked_items(items: List[str]) -> List[str]:
    files: List[str] = []
    for item in items:
        found = tracked(item)
        if not found:
            raise SystemExit(f"not in git: {item}")
        files += found
    return files


def demo_files(export: ConsoleExport) -> List[str]:
    """The console's README and demo, with what the kit keeps of an SDK in git (its build tools, headers, libraries
    and license; its samples, docs and tool sources stay out)."""
    sdk = export.sdk_path
    files = [path for path in _tracked_items([export.readme, export.demo + "/"])
             if not path.startswith(sdk) or path[len(sdk):].startswith(export.sdk_keep)]
    for name in export.runtime:  # the demo builds with every file of the runtime (console_exports)
        if f"{export.demo}/{name}" not in files:
            raise SystemExit(f"not in git: {export.demo}/{name} ({export.name}'s runtime)")
    if export.sdk_in_git:
        for need in export.sdk_needs:
            if not any(path == sdk + need or path.startswith(sdk + need) for path in files):
                raise SystemExit(f"{export.sdk} has no {need} in git ({sdk})")
    return files


def kit_files() -> List[str]:
    files = _tracked_items(EXAMPLES)
    for export in console_exports.EXPORTS:
        files += demo_files(export)
    return files


def sdk_files(export: ConsoleExport, folder: Path) -> List[Tuple[Path, str]]:
    """(file, its path in the kit) for what the kit takes from an SDK that is not in git, unpacked in ``folder``."""
    for need in export.sdk_needs:
        if not (folder / need).exists():
            raise SystemExit(f"not {export.sdk}'s Windows release (no {need}): {folder}")
    found = []
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if path.is_file() and name.startswith(export.sdk_keep) and path.name != ".keepme":
            found.append((path, export.sdk_path + name))
    return found


def pvsneslib_files(folder: Path) -> List[Tuple[Path, str]]:
    """What the kit takes from PVSnesLib's Windows release (the SNES's SDK)."""
    return sdk_files(console_exports.SNES, folder)


def windows_text(path: Path, version: str) -> bytes:
    """README / batch files with CRLF line ends (cmd.exe needs them for labels) and the version filled in."""
    text = path.read_text(encoding="utf-8").replace("@VERSION@", version)
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def sdk_folders(given: List[str]) -> Dict[str, Path]:
    """--sdk KEY=DIR for every console whose SDK is not in git."""
    keys = [export.key for export in console_exports.EXPORTS]
    folders: Dict[str, Path] = {}
    for item in given:
        key, _, folder = item.partition("=")
        if key not in keys or not folder:
            raise SystemExit(f"--sdk {item}: KEY=DIR, KEY one of {', '.join(keys)}")
        folders[key] = Path(folder)
    for export in console_exports.EXPORTS:
        if not export.sdk_in_git and export.key not in folders:
            raise SystemExit(f"--sdk {export.key}=DIR: {export.sdk}'s Windows release, unpacked")
    return folders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("editor_exe", type=Path)
    parser.add_argument("out_zip", type=Path)
    parser.add_argument("--exporters", type=Path, required=True,
                        help="the folder with every console's exporter (export_<console>.exe)")
    parser.add_argument("--sdk", action="append", default=[], metavar="KEY=DIR",
                        help="the SDK of a console whose SDK is not in git, unpacked (snes=PVSnesLib's Windows release)")
    parser.add_argument("--version", default="")
    args = parser.parse_args()

    exporters = [args.exporters / f"{export.module}.exe" for export in console_exports.EXPORTS]
    for path in exporters:
        if not path.is_file():
            raise SystemExit(f"no exporter: {path}")
    files = kit_files()
    sdks = {key: sdk_files(console_exports.for_console(key), folder)
            for key, folder in sdk_folders(args.sdk).items()}
    args.out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as kit:
        kit.write(args.editor_exe, f"{KIT_DIR}/ModularSpriteEditor.exe")
        for path in exporters:
            kit.write(path, f"{KIT_DIR}/{path.name}")
        for extra in sorted(PACKAGING.iterdir()):
            kit.writestr(f"{KIT_DIR}/{extra.name}", windows_text(extra, args.version))
        for path in files:
            kit.write(REPO / path, f"{KIT_DIR}/{path}")
        for found in sdks.values():
            for path, name in found:
                kit.write(path, f"{KIT_DIR}/{name}")
    size = args.out_zip.stat().st_size
    count = len(files) + sum(len(found) for found in sdks.values()) + 1 + len(exporters) + len(list(PACKAGING.iterdir()))
    taken = ", ".join(f"{len(found)} of {console_exports.for_console(key).sdk}" for key, found in sdks.items())
    print(f"{args.out_zip}: {count} files{f' ({taken})' if taken else ''}, {size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
