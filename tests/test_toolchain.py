from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_toolchain


class ToolchainAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for folder in ("config", "Packages", "ProjectSettings"):
            (self.root / folder).mkdir(parents=True)
        self.lock = json.loads(
            (PROJECT / "config" / "toolchain-lock.json").read_text(encoding="utf-8")
        )
        self.manifest = json.loads(
            (PROJECT / "Packages" / "vpm-manifest.json").read_text(encoding="utf-8")
        )
        self.write_json(self.root / "config" / "toolchain-lock.json", self.lock)
        self.write_json(self.root / "Packages" / "vpm-manifest.json", self.manifest)
        (self.root / "ProjectSettings" / "ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.22f1\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_source_lock_passes_before_unity_resolution(self) -> None:
        result = audit_toolchain.audit(self.root)
        self.assertTrue(result["passed"])
        self.assertFalse(result["unityPackageLockPresent"])
        self.assertTrue(result["warnings"])

    def test_unity_lock_is_mandatory_after_resolution(self) -> None:
        result = audit_toolchain.audit(self.root, require_unity_lock=True)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("packages-lock.json" in error for error in result["errors"])
        )

    def test_prerelease_pin_is_rejected(self) -> None:
        package = self.lock["vpmPackages"]["nadena.dev.modular-avatar"]
        package["version"] = "1.18.0-rc.1"
        self.write_json(self.root / "config" / "toolchain-lock.json", self.lock)
        result = audit_toolchain.audit(self.root)
        self.assertFalse(result["passed"])
        self.assertTrue(any("prerelease" in error for error in result["errors"]))

    def test_dependency_contract_drift_is_rejected(self) -> None:
        dependencies = self.manifest["locked"]["com.anatawa12.avatar-optimizer"][
            "dependencies"
        ]
        dependencies["com.vrchat.avatars"] = ">=3.7.0 <4.0.0"
        self.write_json(self.root / "Packages" / "vpm-manifest.json", self.manifest)
        result = audit_toolchain.audit(self.root)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("dependency contract" in error for error in result["errors"])
        )


if __name__ == "__main__":
    unittest.main()
