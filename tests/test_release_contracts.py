from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import production_gate  # noqa: E402
import release_orchestrator  # noqa: E402


class CommercialEvidenceContractTest(unittest.TestCase):
    def test_evidence_requires_tool_identity_and_hashed_artifacts(self) -> None:
        policy = json.loads(
            (ROOT / "config/release-policy.json").read_text(encoding="utf-8")
        )
        evidence = policy["commercialMethodPolicy"]["evidenceContract"]
        self.assertEqual(evidence["schemaVersion"], 2)
        self.assertEqual(
            evidence["toolContract"]["requiredFields"],
            ["id", "version", "command"],
        )
        self.assertEqual(
            evidence["sourceArtifactContract"]["requiredFields"],
            ["path", "sha256"],
        )
        self.assertIs(
            evidence["sourceArtifactContract"]["candidateHashBindingRequired"],
            True,
        )


class PoseContractTest(unittest.TestCase):
    def test_release_policy_is_the_only_product_pose_contract(self) -> None:
        policy = json.loads(
            (ROOT / "config/release-policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            policy["requiredPoses"],
            ["neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"],
        )
        conflicts = []
        for path in (ROOT / "config/products").glob("*/construction.json"):
            construction = json.loads(path.read_text(encoding="utf-8"))
            if "requiredPoses" in construction:
                conflicts.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], conflicts)


class ReleaseIntegrationTest(unittest.TestCase):
    def test_production_gate_has_one_release_orchestrator(self) -> None:
        self.assertIs(production_gate.run_release, release_orchestrator._run_release)

    def test_legacy_release_facades_are_absent(self) -> None:
        for removed in (
            "production_gate_core.py",
            "release_gate.py",
            "pipeline.py",
            "release_packager.py",
            "workspace_transaction.py",
        ):
            self.assertFalse((TOOLS / removed).exists(), removed)


class ReleaseRawEvidenceContractTest(unittest.TestCase):
    def test_packager_copies_raw_evidence_before_manifesting_release(self) -> None:
        source = (TOOLS / "production_contract.py").read_text(encoding="utf-8")
        human = source.index('package / "Evidence" / "Human"')
        commercial = source.index('package / "Evidence" / "Commercial"')
        release_manifest = source.index('release / "release-manifest.json"')
        self.assertLess(human, release_manifest)
        self.assertLess(commercial, release_manifest)
