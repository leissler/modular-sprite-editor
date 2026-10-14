"""Load the sprite sheet exports for Godot and Unity in the engines themselves and play them (needs Godot 4 and / or
Unity 6 installed; neither is needed by the editor or its tests).

Exports the Prince of Persia example (some animations switched to harder playback: a follow-up, loop from a step,
ping-pong with repeats, backward with repeats, a step with two events) for each engine, writes what every clip must
show (``expected.json``, from exporters/sheet.py), and runs a check inside the engine (tools/engine_checks):

- Godot (headless, a project in the work folder): the scene's AnimationPlayer seeks every clip to the middle of each
  step and compares the sprite's picture, every hitbox and point, the clip's length, loop and follow-up; then plays
  every clip with events or a follow-up through the main loop and compares the events and what plays next.
- Unity (batch mode, a project created once in the work folder, a few minutes): samples every clip on the prefab
  (sprite ids, pivots, colliders, points), compares the events, the controller's states and transitions, runs the
  Animator into each follow-up and lets a script receive the events.

Usage (from the repository root):
    python3 tools/check_engine_exports.py [--godot PATH] [--unity PATH] [--work DIR] [--scale N] [--only godot|unity]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKS = os.path.join(REPO, "tools", "engine_checks")
sys.path.insert(0, REPO)

from exporters import sheet as sheets  # noqa: E402
from exporters import unity  # noqa: E402
from models import Project, StepEvent  # noqa: E402


def find_godot(given: Optional[str]) -> Optional[str]:
    candidates = [given, os.environ.get("GODOT"), shutil.which("godot"), shutil.which("godot4")]
    candidates += sorted(glob.glob("/Applications/Godot*.app/Contents/MacOS/Godot"))
    return next((c for c in candidates if c and os.path.exists(c)), None)


def find_unity(given: Optional[str]) -> Optional[str]:
    candidates = [given, os.environ.get("UNITY")]
    candidates += sorted(glob.glob("/Applications/Unity/Hub/Editor/6*/Unity.app/Contents/MacOS/Unity"), reverse=True)
    candidates += sorted(glob.glob(r"C:\Program Files\Unity\Hub\Editor\6*\Editor\Unity.exe"), reverse=True)
    candidates += sorted(glob.glob(os.path.expanduser("~/Unity/Hub/Editor/6*/Editor/Unity")), reverse=True)
    return next((c for c in candidates if c and os.path.exists(c)), None)


def make_case(fmt: str, folder: str, scale: int) -> int:
    """Export the case into ``folder`` (pop.png and the engine's files) with expected.json; returns the clip count."""
    project = Project.from_json(os.path.join(REPO, "examples", "sgdk", "PoP_WW.json"))
    long = [a for a in project.animations if len(a.aframes) >= 4]
    long[0].playback_type, long[0].next_animation_id = "forward", long[1].id
    long[1].playback_type, long[1].loop_start = "loop", 2
    long[2].playback_type, long[2].loop_count, long[2].next_animation_id = "ping_pong", 2, long[0].id
    long[3].playback_type = "backward"
    long[4].playback_type = "ping_pong"
    long[5].playback_type, long[5].loop_count = "backward", 3
    long[5].aframes[1].events.append(StepEvent(project.event_types[0].id, 7))
    long[5].aframes[1].events.append(StepEvent(project.event_types[1].id, 2))
    os.makedirs(folder, exist_ok=True)
    png = os.path.abspath(os.path.join(folder, "pop.png"))
    report = sheets.export_sheet(project, png, fmt, scale=scale)
    built = sheets.build_sheet(project)
    if scale > 1:
        built = sheets._scaled(built, scale)
    clips = []
    for clip in sheets.clips(built):
        times = clip.times(built)
        keys = []
        for k, index in enumerate(clip.entries):
            entry = built.entries[index]
            cell = built.cells[entry.cell]
            keys.append({
                "t": (times[k] + times[k + 1]) / 2.0, "start": times[k], "tag": built.tags[clip.tag].name,
                "cell": entry.cell, "cell_x": cell.x, "cell_y": cell.y,
                "sprite_id": str(unity.sprite_id(png, entry.cell)),
                "boxes": {n: [b.x + b.w / 2.0, b.y + b.h / 2.0, b.w, b.h]
                          for n, b in zip(sheets.slot_names(entry.boxes), entry.boxes)},
                "points": {n: [p.x + p.size / 2.0, p.y + p.size / 2.0]
                           for n, p in zip(sheets.slot_names(entry.points), entry.points)},
                "events": [[name, value] for name, value in entry.events]})
        clips.append({"name": clip.name, "loops": clip.loops, "next": clip.next, "length": times[-1], "keys": keys})
    cells = [{"left": c.left, "top": c.top, "w": c.size[0], "h": c.size[1]} for c in built.cells]
    with open(os.path.join(folder, "expected.json"), "w", encoding="utf-8") as out:
        json.dump({"cells": cells, "clips": clips, "boxes": sheets.slots(built, "boxes"),
                   "points": sheets.slots(built, "points")}, out)
    return int(report["clips"])


def run(command: List[str], log: str) -> str:
    """Run an engine; returns its output (also kept in ``log``)."""
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    with open(log, "w", encoding="utf-8") as out:
        out.write(result.stdout)
    return result.stdout


def run_unity(command: List[str], log: str) -> str:
    """Run Unity with its log in ``log`` and return the log. (Not through a pipe: Unity's package manager server
    outlives the editor and would hold the pipe open.)"""
    if os.path.exists(log):
        os.remove(log)
    subprocess.run(command + ["-logFile", log], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(log, encoding="utf-8", errors="replace") as source:
        return source.read()


def check_godot(godot: str, work: str, scale: int) -> bool:
    project = os.path.join(work, "godot")
    shutil.rmtree(os.path.join(project, "pop"), ignore_errors=True)
    os.makedirs(project, exist_ok=True)
    with open(os.path.join(project, "project.godot"), "w", encoding="utf-8") as out:
        out.write('config_version=5\n\n[application]\nconfig/name="EngineCheck"\n')
    shutil.copy(os.path.join(CHECKS, "check.gd"), project)
    clips = make_case("godot", os.path.join(project, "pop"), scale)
    run([godot, "--headless", "--path", project, "--import"], os.path.join(work, "godot_import.log"))
    output = run([godot, "--headless", "--path", project, "--script", "res://check.gd"], os.path.join(work, "godot.log"))
    lines = [line for line in output.splitlines() if line.startswith(("FAIL", "CHECKED", "SCRIPT ERROR", "ERROR"))]
    print("\n".join(f"  godot: {line}" for line in lines) or "  godot: no result (see godot.log)")
    return any(line.startswith("CHECKED") and line.endswith("failures=0") for line in lines) and clips > 0


def check_unity(unity_path: str, work: str, scale: int) -> bool:
    project = os.path.join(work, "unity")
    if not os.path.isdir(os.path.join(project, "Assets")):
        print("  unity: creating the check project (once)")
        run_unity([unity_path, "-batchmode", "-nographics", "-quit", "-createProject", project],
                  os.path.join(work, "unity_create.log"))
    editor, scripts, case = (os.path.join(project, "Assets", name) for name in ("Editor", "Scripts", "Pop"))
    for folder in (editor, scripts):
        os.makedirs(folder, exist_ok=True)
    for name in ("CheckExport.cs", "MiniJson.cs"):
        shutil.copy(os.path.join(CHECKS, name), editor)
    shutil.copy(os.path.join(CHECKS, "EventProbe.cs"), scripts)
    shutil.rmtree(case, ignore_errors=True)
    make_case("unity", case, scale)
    output = run_unity([unity_path, "-batchmode", "-nographics", "-projectPath", project, "-executeMethod",
                        "CheckExport.Run"], os.path.join(work, "unity.log"))
    lines = [line for line in output.splitlines() if line.startswith(("FAIL", "CHECKED")) or "error CS" in line]
    print("\n".join(f"  unity: {line}" for line in lines) or "  unity: no result (see unity.log)")
    return any(line.startswith("CHECKED") and line.endswith("failures=0") for line in lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--godot", help="the Godot 4 executable (default: GODOT, PATH, /Applications)")
    parser.add_argument("--unity", help="the Unity 6 editor executable (default: UNITY, the Unity Hub's newest 6)")
    parser.add_argument("--work", default=os.path.join(tempfile.gettempdir(), "mse_engine_checks"),
                        help="where the check projects and logs go (the Unity project is kept for next time)")
    parser.add_argument("--scale", type=int, default=1, help="export with every pixel this many times as large")
    parser.add_argument("--only", choices=("godot", "unity"))
    args = parser.parse_args()
    os.makedirs(args.work, exist_ok=True)
    ok = True
    for name, find, check in (("godot", find_godot, check_godot), ("unity", find_unity, check_unity)):
        if args.only and args.only != name:
            continue
        engine = find(getattr(args, name))
        if engine is None:
            print(f"{name}: not found (pass --{name})")
            ok = False
            continue
        print(f"{name}: {engine}")
        ok = check(engine, args.work, args.scale) and ok
    print("PASS" if ok else f"FAIL (logs in {args.work})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
