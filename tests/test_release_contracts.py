from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import production_gate_core  # noqa: E402
import release_gate  # noqa: E402
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
    def test_imported_release_route_has_one_validator(self) -> None:
        self.assertIs(
            production_gate_core._run_release,
            release_orchestrator._run_release,
        )
        self.assertFalse(hasattr(release_gate, "evidence_gate"))
        self.assertFalse(hasattr(release_gate, "run_release"))

    def test_direct_legacy_release_is_disabled(self) -> None:
        source = (TOOLS / "release_gate.py").read_text(encoding="utf-8")
        self.assertIn("direct release_gate release is disabled", source)
        self.assertIn("tools/production_gate.py", source)


class ReleaseRawEvidenceContractTest(unittest.TestCase):
    def test_packager_copies_raw_evidence_before_manifesting_release(self) -> None:
        source = (TOOLS / "release_packager.py").read_text(encoding="utf-8")
        human = source.index('package / "Evidence" / "Human"')
        commercial = source.index('package / "Evidence" / "Commercial"')
        release_manifest = source.index('release / "release-manifest.json"')
        self.assertLess(human, release_manifest)
        self.assertLess(commercial, release_manifest)
