"""Upgrade native Modular Sprite Editor project files to the current format version.

The migration works on the raw JSON (it does not round-trip through the data model),
so image paths, key order and unknown keys are preserved. Only the changes defined in
models.migrate_project_dict are applied.

Usage:
    python3 tools/migrate_projects.py [--dry-run] [--backup-zip PATH] FILE_OR_DIR [...]

Directories are searched recursively for *.json files. Files that are not native
project files (for example RetroAnimator exports) are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from typing import Iterable, List, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from models import PROJECT_FORMAT_VERSION, migrate_project_dict  # noqa: E402


def is_native_project(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if str(data.get("ProjectType", "")).strip().lower() == "retroanimator":
        return False
    return isinstance(data.get("frames"), list) and isinstance(data.get("modules"), list)


def iter_candidate_files(paths: Iterable[str]) -> Iterable[str]:
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in sorted(files):
                    if name.lower().endswith(".json"):
                        yield os.path.join(root, name)
        elif os.path.isfile(path):
            yield path


def migrate_file(path: str, dry_run: bool) -> Tuple[str, List[str]]:
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return ("skipped (not JSON)", [])
    if not is_native_project(data):
        return ("skipped (not a native project)", [])

    current = data.get("format_version", 1)
    if current == PROJECT_FORMAT_VERSION:
        return ("already current", [])

    migrated, notes = migrate_project_dict(data)
    if migrated.get("format_version") != PROJECT_FORMAT_VERSION:
        return ("skipped (newer format)", notes)

    if not dry_run:
        tmp_path = path + ".migrating"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(migrated, f, indent=2)
        os.replace(tmp_path, path)
    return (f"migrated v{current} -> v{PROJECT_FORMAT_VERSION}", notes)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="Project files or directories")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    parser.add_argument("--backup-zip", help="Store the original bytes of every migrated file in this zip first")
    args = parser.parse_args(argv)

    files = list(dict.fromkeys(os.path.abspath(p) for p in iter_candidate_files(args.paths)))
    to_backup: List[str] = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                continue
        if is_native_project(data) and data.get("format_version", 1) != PROJECT_FORMAT_VERSION:
            to_backup.append(path)

    if args.backup_zip and to_backup and not args.dry_run:
        with zipfile.ZipFile(args.backup_zip, "a", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in to_backup:
                zf.write(path, arcname=path.lstrip(os.sep))
        print(f"Backed up {len(to_backup)} file(s) to {args.backup_zip}")

    for path in files:
        status, notes = migrate_file(path, args.dry_run)
        print(f"{status:32s} {path}")
        for note in notes:
            print(f"    - {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
