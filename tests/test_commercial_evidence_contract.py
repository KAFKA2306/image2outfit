from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()
