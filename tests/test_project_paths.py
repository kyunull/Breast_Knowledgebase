from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.project_paths import ProjectRootDiscoveryError, discover_project_root


class ProjectRootDiscoveryTests(unittest.TestCase):
    def test_discovers_repository_from_nested_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            (root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
            (root / "app").mkdir()
            nested = root / "tests" / "fixtures" / "nested"
            nested.mkdir(parents=True)

            self.assertEqual(root.resolve(), discover_project_root(nested))

    def test_rejects_anchor_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            anchor = Path(temporary_root)

            with self.assertRaises(ProjectRootDiscoveryError):
                discover_project_root(anchor)


if __name__ == "__main__":
    unittest.main()
