"""What an import leaves out or can't find, for the project's load notes (shown once after importing)."""

from __future__ import annotations

from typing import Dict, List


class Notes:
    """Grouped notes: one line per kind of problem, with a few examples, however many times it happens."""

    def __init__(self) -> None:
        self._groups: Dict[str, List[str]] = {}

    def add(self, message: str, example: str = "") -> None:
        examples = self._groups.setdefault(message, [])
        if example and example not in examples:
            examples.append(example)

    def lines(self, shown: int = 4) -> List[str]:
        out = []
        for message, examples in self._groups.items():
            if not examples:
                out.append(message + ".")
                continue
            listed = ", ".join(examples[:shown])
            if len(examples) > shown:
                listed += f" and {len(examples) - shown} more"
            out.append(f"{message}: {listed}.")
        return out
