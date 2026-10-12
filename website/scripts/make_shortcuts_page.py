"""Write docs/reference/shortcuts.md from the editor's own shortcut list (ui/shortcuts_dialog.py).

Run it after changing a shortcut, from the repository root:
    python3 website/scripts/make_shortcuts_page.py
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "website" / "docs" / "reference" / "shortcuts.md"

INTRO = """# Keyboard and mouse

On a Mac, **Cmd** is the Command key. On Windows and Linux, use **Ctrl** wherever this page says Cmd. The editor
shows the same list under **Help ▸ Keyboard & Mouse Shortcuts**.

Shortcuts only reach a canvas when you are not typing in a text field. Click the canvas first if a key does nothing.
"""


def shortcuts():
    """The SHORTCUTS table, read without importing wx: f-strings with MOD become Cmd."""
    tree = ast.parse((REPO / "ui" / "shortcuts_dialog.py").read_text())
    table = next(node.value for node in tree.body if isinstance(node, ast.AnnAssign) and node.target.id == "SHORTCUTS")
    rows = []
    for item in table.elts:
        cells = []
        for value in item.elts:
            if isinstance(value, ast.JoinedStr):
                cells.append("".join(part.value if isinstance(part, ast.Constant) else "Cmd" for part in value.values))
            else:
                cells.append(value.value)
        rows.append(tuple(cells))
    return rows


def clean(text: str) -> str:
    return text.replace("…", "to").replace("|", "\\|")


def main() -> None:
    lines = [INTRO]
    current = None
    for where, action, keys in shortcuts():
        if where != current:
            current = where
            lines += ["", f"## {where}", "", "| Action | Shortcut |", "| --- | --- |"]
        lines.append(f"| {clean(action)} | {clean(keys)} |")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
