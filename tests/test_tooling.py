from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_tool_ownership  # noqa: E402
import audit_toolchain  # noqa: E402


class ToolOwnershipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = audit_tool_ownership.audit(ROOT)

    def test_all_tools_and_payloads_are_owned(self) -> None:
        failures = {
            name: self.result[name]
            for name in (
                "unreferenced",
                "duplicateGroups",
                "semanticDuplicateGroups",
                "invalidOpaqueLoaders",
                "unreferencedResources",
                "duplicateResourceGroups",
                "excessiveProductImportChains",
                "productImportCycles",
            )
            if self.result[name]
        }
        self.assertTrue(self.result["passed"], failures)

    def test_manage_is_the_taskfile_entrypoint(self) -> None:
        manage = next(
            item
            for item in self.result["inventory"]
            if item["path"] == "tools/manage.py"
        )
        self.assertIn("Taskfile.yml", manage["references"])
        self.assertFalse(manage["unreferenced"])

    def test_production_has_one_canonical_entrypoint_without_legacy_facades(self) -> None:
        for removed in ("production_gate_core.py", "release_gate.py", "pipeline.py"):
            self.assertFalse((TOOLS / removed).exists(), removed)

        production = (TOOLS / "production_gate.py").read_text(encoding="utf-8")
        self.assertIn("from candidate_orchestrator import", production)
        self.assertIn("from release_orchestrator import", production)

        for name in (
            "production_gate.py",
            "candidate_orchestrator.py",
            "release_orchestrator.py",
            "candidate_manifest.py",
            "technical_candidate.py",
        ):
            source = (TOOLS / name).read_text(encoding="utf-8")
            self.assertNotIn("production_gate_core", source, name)
            self.assertNotIn("release_gate", source, name)
            self.assertNotIn("import pipeline", source, name)
            self.assertNotIn("legacy-blender-gate-job", source, name)


class ToolchainAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for folder in ("config", "Packages", "ProjectSettings"):
            (self.root / folder).mkdir(parents=True)
        self.lock = json.loads(
            (ROOT / "config" / "toolchain-lock.json").read_text(encoding="utf-8")
        )
        self.manifest = json.loads(
            (ROOT / "Packages" / "vpm-manifest.json").read_text(encoding="utf-8")
        )
        self.write_json(self.root / "config" / "toolchain-lock.json", self.lock)
        (self.root / "pyproject.toml").write_text(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
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

    def test_blender_python_dependency_drift_is_rejected(self) -> None:
        pyproject = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        (self.root / "pyproject.toml").write_text(
            pyproject.replace("Pillow==12.3.0", "Pillow==12.2.0"),
            encoding="utf-8",
        )
        result = audit_toolchain.audit(self.root)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any(
                "Blender Python dependency mismatch" in error
                for error in result["errors"]
            )
        )

    def test_blender_python_version_drift_is_rejected(self) -> None:
        self.lock["blender"]["python"]["version"] = "3.12.0"
        self.write_json(self.root / "config" / "toolchain-lock.json", self.lock)
        result = audit_toolchain.audit(self.root)
        self.assertFalse(result["passed"])
        self.assertTrue(any("exact 3.11 patch" in error for error in result["errors"]))
