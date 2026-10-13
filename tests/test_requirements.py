"""wxPython is pinned twice: requirements.txt (the build scripts) and the release workflow. Both name one version."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WxPythonPinTest(unittest.TestCase):
    def test_workflow_installs_the_pinned_version(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        pins = re.findall(r"^wxPython==(\S+)", requirements, re.I | re.M)
        self.assertEqual(len(pins), 1, "requirements.txt pins wxPython to one version")
        workflow = (ROOT / ".github" / "workflows" / "build-and-release.yml").read_text(encoding="utf-8")
        named = re.findall(r"wxpython(?:==|-)(\d[\w.]*?)(?=-|\s|$)", workflow, re.I | re.M)
        self.assertEqual(len(named), 3, f"the workflow's pip install, Linux wheel and its cache key: {named}")
        self.assertEqual(set(named), set(pins), "the workflow installs the wxPython of requirements.txt")


if __name__ == "__main__":
    unittest.main()
