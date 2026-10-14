"""Groups and sort orders for long lists (frames and animations): which items a list shows, in which order (wx-free).

``Frame.group`` and ``Animation.group`` name where an item sits ("" = no group). The lists show every group or one
of them, and sort in list order (the project's, which drag-and-drop changes), by name (numbers in names count as
numbers: "C2" comes before "C10") or by group (groups by name, items without one last, list order within each).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, List, Optional, Sequence, Tuple

ALL: Optional[str] = None  # the group filter that shows every item ("" shows the items without a group)
SORTS: List[Tuple[str, str]] = [("List order", "order"), ("Name", "name"), ("Group", "group")]

_NUMBERS = re.compile(r"(\d+)")


def natural_key(text: str) -> Tuple[Any, ...]:
    """Sort key that reads the numbers in a name as numbers ("Walk 2" before "Walk 10")."""
    # re.split with a group alternates text and digits, always text first: the parts compare type by type.
    return tuple(int(part) if index % 2 else part.lower() for index, part in enumerate(_NUMBERS.split(text)))


def groups_of(items: Sequence[Any]) -> List[Tuple[str, int]]:
    """The groups the items use, by name, with how many items each holds."""
    counts = Counter(item.group for item in items if item.group)
    return sorted(counts.items(), key=lambda entry: natural_key(entry[0]))


def shown(items: Sequence[Any], text: str = "", group: Optional[str] = ALL, sort: str = "order") -> List[Any]:
    """The items a list shows: those whose name or group contains ``text``, in ``group`` (ALL: any), sorted."""
    text = text.strip().lower()
    out = [
        item for item in items
        if (group is ALL or item.group == group)
        and (not text or text in item.name.lower() or text in item.group.lower())
    ]
    if sort == "name":
        out.sort(key=lambda item: natural_key(item.name))
    elif sort == "group":
        out.sort(key=lambda item: (item.group == "", natural_key(item.group)))  # stable: list order within a group
    return out


def clean_name(name: str) -> str:
    return " ".join(str(name).split())
