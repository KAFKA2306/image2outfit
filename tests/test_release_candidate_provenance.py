from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import release_orchestrator  # noqa: E402


class ReleaseCandidateProvenanceTest(unittest.TestCase):
    def test_strict_release_audit_propagates_candidate_provenance_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            candidate.mkdir()
            manifest_path = candidate / "candidate-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "kind": "image2outfit-candidate",
                        "jobId": "product",
                        "adapterId": "adapter",
                        "inputHashes": {},
                        "poseContract": {"requiredPoses": []},
                        "researchBaseline": {
                            "path": "research.json",
                            "baselineId": "baseline",
                            "surveyYear": 2026,
                            "reviewedAt": "2026-09-11T00:00:00Z",
                            "sha256": "research-sha",
                            "requiredCapabilities": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            job = {
                "id": "product",
                "adapterId": "adapter",
                "candidateDir": "candidate",
                "humanEvidence": {},
            }
            policy = {
                "blockedReleaseAdapterIds": [],
                "requiredHumanEvidenceKinds": [],
                "requiredPoses": [],
            }
            research = {"passed": True, "path": "research.json"}
            baseline = {
                "baselineId": "baseline",
                "surveyYear": 2026,
                "reviewedAt": "2026-09-11T00:00:00Z",
                "requiredCapabilities": [],
            }
            provenance_error = "candidate inputs missing: executionSource"

            with (
                patch.object(release_orchestrator.candidate_contract, "ROOT", root),
                patch.object(
                    release_orchestrator.candidate_contract,
                    "verify_candidate",
                    return_value=[provenance_error],
                ) as verify_candidate,
                patch.object(
                    release_orchestrator,
                    "_research_state",
                    return_value=(research, baseline, "research-sha"),
                ),
                patch.object(
                    release_orchestrator.customer_quality,
                    "validate",
                    return_value=({}, []),
                ),
                patch.object(
                    release_orchestrator,
                    "_quality_spec_audit",
                    return_value=({}, []),
                ),
            ):
                _, _, errors, _ = release_orchestrator._strict_release_audit(
                    Path("job.json"), job, policy
                )

            verify_candidate.assert_called_once()
            self.assertIn(provenance_error, errors)


if __name__ == "__main__":
    unittest.main()
