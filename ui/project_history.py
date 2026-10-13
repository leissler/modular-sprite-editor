"""Project-wide undo/redo history and unsaved-change tracking.

Every history entry is a compressed snapshot of ``Project.to_dict()``. A snapshot of the
Prince of Persia testbed costs a few milliseconds and ~40 KB compressed, so the main window
can simply checkpoint whenever the project fingerprint changes instead of every editor
instrumenting each operation.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import zlib
from typing import Any, Dict, List, Optional, Tuple

from models import Project

# Everything a project saves: the dataclass fields set by its constructor (active_mapping and load_notes are not).
SAVED_FIELDS = tuple(f.name for f in dataclasses.fields(Project) if f.init)


def project_fingerprint(project: Project) -> Tuple[str, bytes]:
    payload = json.dumps(project.to_dict(), separators=(",", ":")).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).hexdigest(), payload


def replace_project_contents(target: Project, source: Project) -> None:
    """Swap all saved data of ``target`` for ``source`` while keeping the same object (panels hold on to it).

    Every saved field is copied, so a field added to Project later cannot be forgotten here."""
    active_mapping_id = target.active_mapping.id if target.active_mapping else None
    for name in SAVED_FIELDS:
        setattr(target, name, getattr(source, name))
    target.active_mapping = next((m for m in target.mappings if m.id == active_mapping_id), None)


class ProjectHistory:
    def __init__(self, max_steps: int = 200) -> None:
        self.max_steps = max(2, int(max_steps))
        self._entries: List[Tuple[str, bytes]] = []
        self._index = -1
        self._saved_fingerprint: Optional[str] = None
        self._last_fingerprint: Optional[str] = None

    def reset(self, project: Project, saved: bool = True) -> None:
        fingerprint, payload = project_fingerprint(project)
        self._entries = [(fingerprint, zlib.compress(payload, 6))]
        self._index = 0
        self._last_fingerprint = fingerprint
        self._saved_fingerprint = fingerprint if saved else None

    def checkpoint(self, project: Project) -> bool:
        """Record the current project state if it differs from the current history entry."""
        fingerprint, payload = project_fingerprint(project)
        self._last_fingerprint = fingerprint
        if self._index >= 0 and self._entries[self._index][0] == fingerprint:
            return False
        del self._entries[self._index + 1 :]
        self._entries.append((fingerprint, zlib.compress(payload, 6)))
        if len(self._entries) > self.max_steps:
            overflow = len(self._entries) - self.max_steps
            del self._entries[:overflow]
        self._index = len(self._entries) - 1
        return True

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return 0 <= self._index < len(self._entries) - 1

    def _entry_data(self, index: int) -> Dict[str, Any]:
        return json.loads(zlib.decompress(self._entries[index][1]).decode("utf-8"))

    def undo(self, project: Project) -> bool:
        # Pending edits become the redo target instead of being lost.
        self.checkpoint(project)
        if not self.can_undo():
            return False
        self._index -= 1
        self._restore(project, self._index)
        return True

    def redo(self, project: Project) -> bool:
        self.checkpoint(project)
        if not self.can_redo():
            return False
        self._index += 1
        self._restore(project, self._index)
        return True

    def _restore(self, project: Project, index: int) -> None:
        restored = Project.from_dict(self._entry_data(index))
        replace_project_contents(project, restored)
        self._last_fingerprint = self._entries[index][0]

    @property
    def fingerprint(self) -> Optional[str]:
        """Fingerprint of the project as last checkpointed or checked."""
        return self._last_fingerprint

    def mark_saved(self, project: Project) -> None:
        fingerprint, _payload = project_fingerprint(project)
        self._saved_fingerprint = fingerprint
        self._last_fingerprint = fingerprint

    def is_dirty(self, project: Optional[Project] = None) -> bool:
        if project is not None:
            self._last_fingerprint = project_fingerprint(project)[0]
        return self._last_fingerprint != self._saved_fingerprint
