from __future__ import annotations

import copy
import unittest

from image2outfit.experiment_eval import (
    compare_experiment_records,
    validate_experiment_record,
)


class HypothesisExperimentEvaluationTests(unittest.TestCase):
    def record(
        self,
        route: str,
        *,
        elapsed: float,
        findings: int,
        gate: bool = True,
        status: str = "PASS",
        cost: float | None = 1.0,
    ) -> dict:
        digest = "a" * 64
        record = {
            "schemaVersion": 1,
            "route": route,
            "productId": "demo",
            "referenceSha256": digest,
            "initialBlueprintSha256": "b" * 64,
            "targetAvatarAuthoritySha256": "c" * 64,
            "qualitySpecSha256": "d" * 64,
            "status": status,
            "canonicalQualityGatePassed": gate,
            "metrics": {
                "elapsedSeconds": elapsed,
                "artifactBytes": 1000,
                "machineCost": cost,
                "invalidTopologyFindingCount": 0,
                "uvFindingCount": 0,
                "normalFindingCount": 0,
                "materialRegionFindingCount": 0,
                "silhouetteFindingCount": findings,
                "skinningFindingCount": 0,
                "collisionFindingCount": 0,
                "canonicalQualityFindingCount": findings,
            },
            "semanticMasks": [],
        }
        if route == "C" and status == "PASS":
            record["semanticMasks"] = [
                {"role": "wrinkle", "artifactSha256": "e" * 64}
            ]
        return record

    def test_c_is_selected_when_quality_does_not_regress_and_elapsed_improves(self) -> None:
        result = compare_experiment_records(
            [
                self.record("A", elapsed=100, findings=2),
                self.record("B", elapsed=80, findings=2),
                self.record("C", elapsed=60, findings=1),
            ]
        )
        self.assertEqual(result["decision"], "CONTINUE")
        self.assertEqual(result["selectedRoute"], "C")

    def test_b_is_limited_adoption_when_c_does_not_qualify(self) -> None:
        result = compare_experiment_records(
            [
                self.record("A", elapsed=100, findings=2),
                self.record("B", elapsed=70, findings=2),
                self.record("C", elapsed=60, findings=5, gate=False),
            ]
        )
        self.assertEqual(result["decision"], "LIMITED_ADOPTION")
        self.assertEqual(result["selectedRoute"], "B")

    def test_regressing_candidates_are_rejected(self) -> None:
        result = compare_experiment_records(
            [
                self.record("A", elapsed=100, findings=1),
                self.record("B", elapsed=50, findings=3),
                self.record("C", elapsed=40, findings=4),
            ]
        )
        self.assertEqual(result["decision"], "REJECT")
        self.assertEqual(result["selectedRoute"], "A")

    def test_identity_drift_is_rejected(self) -> None:
        a = self.record("A", elapsed=100, findings=1)
        b = self.record("B", elapsed=80, findings=1)
        c = self.record("C", elapsed=70, findings=1)
        b["referenceSha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            compare_experiment_records([a, b, c])

    def test_passing_c_requires_semantic_mask_evidence(self) -> None:
        c = self.record("C", elapsed=70, findings=1)
        c["semanticMasks"] = []
        with self.assertRaisesRegex(ValueError, "semantic mask"):
            validate_experiment_record(c)

    def test_input_record_is_not_mutated(self) -> None:
        record = self.record("B", elapsed=70, findings=1)
        before = copy.deepcopy(record)
        validate_experiment_record(record)
        self.assertEqual(record, before)


if __name__ == "__main__":
    unittest.main()
