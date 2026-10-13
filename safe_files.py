"""Writing files so that a failed or interrupted write never destroys the previous version (wx-free).

The new content goes to a temporary file next to the target, is flushed to the disk and then takes the target's
place in one step (``os.replace``): the file holds either the old or the new content, never a mix. Optionally the
previous version is kept as ``<name>.bak``.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import time

BACKUP_SUFFIX = ".bak"


def backup_path(path: str) -> str:
    """Where the previous version of ``path`` is kept: ``hero.json`` -> ``hero.json.bak``."""
    return path + BACKUP_SUFFIX


def _new_file_mode(path: str) -> int:
    """The target's permissions, or what a newly created file would get (the temporary file starts as 0600)."""
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def _replace(source: str, target: str) -> None:
    # Windows refuses while another program (a virus scanner, a sync client) briefly holds the target open.
    attempts = 5 if sys.platform == "win32" else 1
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))


def _sync_folder(folder: str) -> None:
    """Make the rename itself durable (POSIX; Windows has no folder handles for this)."""
    if sys.platform == "win32":
        return
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_text_atomically(path: str, text: str, keep_backup: bool = False, encoding: str = "utf-8") -> None:
    """Replace ``path`` with ``text`` in one step.

    With ``keep_backup`` the previous content is copied to ``backup_path(path)`` first. A symbolic link is followed:
    the file it points to is replaced and the link stays.
    """
    target = os.path.realpath(path)
    folder = os.path.dirname(target) or "."
    fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(target)}.", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, _new_file_mode(target))
        if keep_backup and os.path.exists(target):
            shutil.copy2(target, backup_path(target))
        _replace(temporary, target)
    except BaseException:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise
    _sync_folder(folder)
