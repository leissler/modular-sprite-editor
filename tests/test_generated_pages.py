"""The guide pages made from the editor's own data are up to date (regenerate them with the scripts named)."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "website" / "scripts"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GeneratedPagesTest(unittest.TestCase):
    def test_pages_match_their_sources(self):
        for name in ("make_shortcuts_page", "make_consoles_page"):
            script = _script(name)
            with self.subTest(page=script.OUT.name):
                self.assertEqual(script.OUT.read_text(encoding="utf-8"), script.page(),
                                 f"run python3 website/scripts/{name}.py")


if __name__ == "__main__":
    unittest.main()
