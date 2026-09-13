from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit import runner_audit as audit

PROFILE = {
    "schemaVersion": 1,
    "profileId": "runner-only-machine-audit-v1",
    "fitBands": {"close": [0.002, 0.03]},
    "epsilonArea": 1e-12,
    "epsilonPenetrationMeters": 0.002,
    "metrics": [
        {
            "id": "geometry.degenerate_triangles",
            "stage": "geometry",
            "operator": "eq",
            "threshold": 0,
            "direction": "lower",
            "scale": 1,
            "tolerance": 0,
            "minImprovement": 1,
            "required": True,
        },
        {
            "id": "silhouette.min_iou",
            "stage": "silhouette-fidelity",
            "operator": "gte",
            "threshold": 0.85,
            "direction": "higher",
            "scale": 0.15,
            "tolerance": 0,
            "minImprovement": 0.01,
            "required": True,
        },
    ],
}


def draft() -> dict:
    return {
        "requestId": "request-1",
        "productId": "garment",
        "referenceImages": [{"path": "ref.png", "sha256": "a" * 64}],
        "targetAvatarAuthoritySha256": "b" * 64,
        "garmentType": "top",
        "regionFitClass": {"torso": "close"},
        "requiredViews": ["front"],
        "requiredPoses": ["neutral"],
        "materialTargets": {},
        "thresholdProfileId": "runner-only-machine-audit-v1",
        "randomSeed": 7,
        "blenderVersion": "4.4.0",
        "producerVersions": {"geometry-audit": "1"},
        "maxAttemptsPerBlocker": 8,
        "maxTotalAttempts": 24,
        "maxRunnerMinutes": 120,
    }


class RunnerAuditTests(unittest.TestCase):
    def test_freeze_binds_thresholds_into_request_digest(self) -> None:
        first = audit.freeze_request_manifest(draft(), PROFILE)
        changed = dict(PROFILE)
        changed["metrics"] = [dict(item) for item in PROFILE["metrics"]]
        changed["metrics"][1]["threshold"] = 0.9
        second = audit.freeze_request_manifest(draft(), changed)
        self.assertNotEqual(audit.request_sha256(first), audit.request_sha256(second))

    def test_missing_producer_is_unverified_not_zero(self) -> None:
        request = audit.freeze_request_manifest(draft(), PROFILE)
        results = audit.evaluate_metrics(PROFILE, request, {}, root=Path("."))
        result = results["geometry.degenerate_triangles"]
        self.assertEqual(result.state, audit.MetricState.UNVERIFIED)
        self.assertIsNone(result.value)
        self.assertEqual(result.cause, "OBSERVATION_MISSING")

    def test_hash_mismatch_is_unverified(self) -> None:
        request = audit.freeze_request_manifest(draft(), PROFILE)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "metric.json"
            evidence.write_text("{}", encoding="utf-8")
            results = audit.evaluate_metrics(
                PROFILE,
                request,
                {
                    "geometry.degenerate_triangles": {
                        "value": 0,
                        "producer": "geometry-audit",
                        "evidencePath": "metric.json",
                        "evidenceSha256": "0" * 64,
                    }
                },
                root=root,
            )
        result = results["geometry.degenerate_triangles"]
        self.assertEqual(result.state, audit.MetricState.UNVERIFIED)
        self.assertEqual(result.cause, "EVIDENCE_HASH_MISMATCH")

    def test_required_evidence_zero_is_unverified(self) -> None:
        result = audit.verified_evidence_ratio(
            [], root=Path("."), product_id="garment", request_digest="a" * 64
        )
        self.assertEqual(result.state, audit.MetricState.UNVERIFIED)

    def test_verified_evidence_ratio_requires_identity_and_hash(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "evidence.json"
            path.write_text('{"ok":true}', encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result = audit.verified_evidence_ratio(
                [
                    {
                        "required": True,
                        "path": "evidence.json",
                        "sha256": digest,
                        "productId": "garment",
                        "requestSha256": "c" * 64,
                    }
                ],
                root=root,
                product_id="garment",
                request_digest="c" * 64,
            )
        self.assertEqual(result.state, audit.MetricState.PASS)
        self.assertEqual(result.value, 1.0)

    def test_blocker_uses_fixed_stage_order(self) -> None:
        results = {
            "silhouette.min_iou": audit.MetricResult(
                "silhouette.min_iou", "silhouette-fidelity", 0.3, 0.85,
                audit.MetricState.FAIL, "silhouette", "a" * 64
            ),
            "geometry.degenerate_triangles": audit.MetricResult(
                "geometry.degenerate_triangles", "geometry", 1, 0,
                audit.MetricState.FAIL, "geometry", "b" * 64
            ),
        }
        self.assertEqual(
            audit.select_blocker(PROFILE, results), "geometry.degenerate_triangles"
        )

    def test_pareto_equal_candidate_reverts(self) -> None:
        current = {
            "geometry.degenerate_triangles": audit.MetricResult(
                "geometry.degenerate_triangles", "geometry", 0, 0,
                audit.MetricState.PASS, "geometry", "a" * 64
            ),
            "silhouette.min_iou": audit.MetricResult(
                "silhouette.min_iou", "silhouette-fidelity", 0.9, 0.85,
                audit.MetricState.PASS, "silhouette", "b" * 64
            ),
        }
        self.assertEqual(
            audit.pareto_decision(PROFILE, current, current), audit.Decision.REVERT
        )

    def test_pareto_keeps_strict_non_regressing_improvement(self) -> None:
        current = {
            "geometry.degenerate_triangles": audit.MetricResult(
                "geometry.degenerate_triangles", "geometry", 0, 0,
                audit.MetricState.PASS, "geometry", "a" * 64
            ),
            "silhouette.min_iou": audit.MetricResult(
                "silhouette.min_iou", "silhouette-fidelity", 0.86, 0.85,
                audit.MetricState.PASS, "silhouette", "b" * 64
            ),
        }
        new = dict(current)
        new["silhouette.min_iou"] = audit.MetricResult(
            "silhouette.min_iou", "silhouette-fidelity", 0.88, 0.85,
            audit.MetricState.PASS, "silhouette", "c" * 64
        )
        self.assertEqual(
            audit.pareto_decision(PROFILE, current, new), audit.Decision.KEEP
        )

    def test_unverified_candidate_cannot_be_kept(self) -> None:
        current = {
            "geometry.degenerate_triangles": audit.MetricResult(
                "geometry.degenerate_triangles", "geometry", 0, 0,
                audit.MetricState.PASS, "geometry", "a" * 64
            )
        }
        new = {
            "geometry.degenerate_triangles": audit.MetricResult(
                "geometry.degenerate_triangles", "geometry", None, 0,
                audit.MetricState.UNVERIFIED, None, None
            )
        }
        self.assertEqual(
            audit.pareto_decision(PROFILE, current, new), audit.Decision.REVERT
        )

    def test_stop_reason_has_no_human_wait_state(self) -> None:
        self.assertEqual(
            audit.stop_reason(
                complete=False,
                failed_hard=False,
                total_attempts=8,
                elapsed_minutes=20,
                max_total_attempts=24,
                max_runner_minutes=120,
                blocker_attempts=8,
                max_attempts_per_blocker=8,
                accepted_for_blocker=0,
            ),
            audit.StopReason.STALLED,
        )


if __name__ == "__main__":
    unittest.main()
