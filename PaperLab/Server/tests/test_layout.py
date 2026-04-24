from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAPERLAB_ROOT = ROOT.parent


class LayoutTest(unittest.TestCase):
    def test_expected_entrypoints_exist(self) -> None:
        self.assertTrue((ROOT / "api/main.py").exists())
        self.assertTrue((ROOT / "src/orchestration/supervisor.py").exists())
        self.assertTrue((ROOT / "pyproject.toml").exists())
        self.assertTrue((ROOT / "dev.py").exists())
        self.assertTrue((PAPERLAB_ROOT / "Docs/README.md").exists())


if __name__ == "__main__":
    unittest.main()
