from __future__ import annotations

import shutil
import subprocess
import unittest
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = PROJECT_ROOT / "scripts" / "bootstrap_runtime.ps1"


class BootstrapRuntimeTests(unittest.TestCase):
    def test_bootstrap_derives_the_required_root_from_its_own_location(self) -> None:
        script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("$PSScriptRoot", script)
        self.assertNotIn("D:\\coding\\knowledgebase", script)

    def test_rejects_an_unrelated_project_root_before_any_runtime_or_wheel_directory_can_be_created(
        self,
    ) -> None:
        powershell = shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("powershell.exe is required to exercise the bootstrap entry point")

        rejected_root = Path(
            r"C:\Users\PC\Documents\Codex"
        ) / f"rejected-bootstrap-{uuid.uuid4()}"
        self.assertFalse(rejected_root.exists())
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(BOOTSTRAP_SCRIPT),
                "-ProjectRoot",
                str(rejected_root),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        combined_output = result.stdout + result.stderr
        self.assertNotEqual(0, result.returncode, combined_output)
        self.assertIn("ProjectRoot must resolve to", combined_output)
        self.assertFalse(rejected_root.exists())
        self.assertFalse((rejected_root / "data" / "runtime_cache").exists())
        self.assertFalse((rejected_root / "data" / "vendor_wheels").exists())


if __name__ == "__main__":
    unittest.main()
