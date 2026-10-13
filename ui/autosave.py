"""Crash recovery: autosaved copies of unsaved changes, offered again after the editor quit unexpectedly (wx-free).

While a project has unsaved changes, the main window writes a copy of it every AUTOSAVE_INTERVAL_MS into the
recovery folder (not next to the project, so project folders and version control stay clean). The copy is removed
when the changes are saved or discarded. A copy whose editor is no longer running was left by a crash: the next
start offers to restore it.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from models import Project
from safe_files import write_text_atomically

AUTOSAVE_INTERVAL_MS = 30_000
RECOVERY_VERSION = 1


@dataclass
class Recovery:
    path: str                    # the recovery file
    project_path: Optional[str]  # where the project was saved last (None: never saved)
    saved_at: float              # time.time() of the autosave
    pid: int                     # the editor process that wrote it


def recovery_dir() -> str:
    """The user's recovery folder. Tests (MSE_PREFERENCES_FILE set) keep it next to their own preferences file."""
    prefs = os.environ.get("MSE_PREFERENCES_FILE")
    if prefs:
        return os.path.join(os.path.dirname(os.path.abspath(prefs)), "Recovery")
    if sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~/Library/Application Support"), "Modular Sprite Editor")
    elif sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Modular Sprite Editor")
    else:
        base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "modular-sprite-editor")
    return os.path.join(base, "Recovery")


def recovery_file_for(project_path: Optional[str], session_key: str) -> str:
    """One recovery file per project file; an unsaved new project gets one per editor session."""
    key = os.path.abspath(project_path) if project_path else f"untitled:{session_key}"
    return os.path.join(recovery_dir(), hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".json")


def write_recovery(path: str, project: Project, project_path: Optional[str]) -> None:
    """Write a recovery copy. Image paths stay absolute, so the copy opens from the recovery folder."""
    data: Dict[str, Any] = {
        "recovery_version": RECOVERY_VERSION,
        "pid": os.getpid(),
        "saved_at": time.time(),
        "project_path": os.path.abspath(project_path) if project_path else None,
        "project": project.to_dict(),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text_atomically(path, json.dumps(data, separators=(",", ":")))


def remove_recovery(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("project"), dict) else None


def process_alive(pid: int) -> bool:
    """Whether a process with this id is still running."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        process_query_limited_information, still_active = 0x1000, 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, it just belongs to someone else
    return True


def stale_recoveries() -> List[Recovery]:
    """Recovery copies left by editors that are no longer running (they quit unexpectedly), newest first."""
    folder = recovery_dir()
    try:
        names = [name for name in os.listdir(folder) if name.endswith(".json")]
    except OSError:
        return []
    found: List[Recovery] = []
    for name in names:
        path = os.path.join(folder, name)
        data = _read(path)
        if data is None:
            continue
        pid = int(data.get("pid") or 0)
        if process_alive(pid):
            continue  # another editor is working on it right now
        project_path = data.get("project_path")
        found.append(Recovery(path, str(project_path) if project_path else None, float(data.get("saved_at") or 0.0), pid))
    return sorted(found, key=lambda rec: rec.saved_at, reverse=True)


def load_recovery(recovery: Recovery) -> Project:
    data = _read(recovery.path)
    if data is None:
        raise ValueError("the autosaved copy is damaged")
    return Project.from_dict(data["project"])
