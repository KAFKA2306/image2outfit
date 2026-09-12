from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.blueprint import (
    BlueprintOutcome,
    digest_blueprint,
    make_blueprint_audit,
    validate_blueprint,
)
from image2outfit.tripo_adapter import (
    SMART_MESH_MODEL_VERSION,
    TripoClient,
    build_multiview_request,
    build_smart_mesh_request,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def mesh_blueprint() -> dict:
    return {
        "schemaVersion": 1,
        "blueprintId": "coat-mesh-draft",
        "revision": 1,
        "role": "mesh-draft",
        "productId": "coat-a",
        "targetAvatar": "SiroinoSotai_PC",
        "targetAvatarSha256": HASH_A,
        "sourceReferenceSha256": HASH_B,
        "consumingStage": "initialize-3d",
        "upstreamArtifacts": [
            {"path": "artifacts/turnaround.png", "sha256": HASH_C}
        ],
        "regions": [
            {
                "id": "body-cloth",
                "epistemicStatus": "observed",
                "kind": "cloth",
            },
            {
                "id": "buckle",
                "epistemicStatus": "observed",
                "kind": "hard-surface",
                "manualReviewRequired": True,
            },
            {
                "id": "back-panel",
                "epistemicStatus": "inferred",
                "kind": "cloth",
            },
        ],
        "mustPreserve": ["T-pose", "front/back silhouette"],
        "allowedFreedom": ["hidden seam placement"],
        "knownAmbiguity": ["back seam inferred from front reference"],
        "expectedArtifactKinds": ["tripo-smart-mesh-draft"],
    }


class BlueprintTests(unittest.TestCase):
    def test_valid_blueprint_is_bound_to_canonical_stage(self) -> None:
        value = mesh_blueprint()
        result = validate_blueprint(value)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["consumingStage"], "initialize-3d")
        self.assertEqual(result["blueprintDigest"], digest_blueprint(value))

    def test_role_cannot_move_to_unrelated_stage(self) -> None:
        value = mesh_blueprint()
        value["consumingStage"] = "render-evidence"
        result = validate_blueprint(value)
        self.assertFalse(result["passed"])
        self.assertTrue(any("must consume stage" in error for error in result["errors"]))

    def test_hard_surface_requires_manual_review_flag(self) -> None:
        value = mesh_blueprint()
        value["regions"][1].pop("manualReviewRequired")
        result = validate_blueprint(value)
        self.assertFalse(result["passed"])
        self.assertTrue(any("hard-surface" in error for error in result["errors"]))

    def test_revision_two_requires_parent_digest(self) -> None:
        value = mesh_blueprint()
        value["revision"] = 2
        result = validate_blueprint(value)
        self.assertFalse(result["passed"])
        self.assertIn("revision > 1 requires parentBlueprintSha256", result["errors"])

    def test_blueprint_audit_cannot_hide_out_of_tolerance_result(self) -> None:
        with self.assertRaisesRegex(ValueError, "PASS cannot contain"):
            make_blueprint_audit(
                mesh_blueprint(),
                actual_artifact_sha256=HASH_C,
                deviations=[
                    {
                        "metric": "silhouette-iou",
                        "expected": ">=0.90",
                        "actual": 0.72,
                        "withinTolerance": False,
                    }
                ],
                outcome=BlueprintOutcome.PASS,
            )

    def test_audit_does_not_claim_quality_pass(self) -> None:
        audit = make_blueprint_audit(
            mesh_blueprint(),
            actual_artifact_sha256=HASH_C,
            deviations=[
                {
                    "metric": "view-count",
                    "expected": 4,
                    "actual": 4,
                    "withinTolerance": True,
                }
            ],
        )
        self.assertEqual(audit["outcome"], "PASS")
        self.assertFalse(audit["qualityPassClaimed"])


class TripoAdapterTests(unittest.TestCase):
    def test_multiview_order_is_front_left_back_right(self) -> None:
        request = build_multiview_request(
            front={"type": "png", "url": "https://example.test/front.png"},
            back={"type": "png", "url": "https://example.test/back.png"},
        )
        self.assertEqual(request["type"], "multiview_to_model")
        self.assertEqual(request["files"][0]["url"], "https://example.test/front.png")
        self.assertEqual(request["files"][1], {})
        self.assertEqual(request["files"][2]["url"], "https://example.test/back.png")
        self.assertEqual(request["files"][3], {})
        self.assertFalse(request["texture"])

    def test_multiview_requires_two_views(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two views"):
            build_multiview_request(
                front={"type": "png", "url": "https://example.test/front.png"}
            )

    def test_smart_mesh_is_quad_p2_and_bounded(self) -> None:
        request = build_smart_mesh_request("task-123", face_limit=12000)
        self.assertEqual(request["type"], "highpoly_to_lowpoly")
        self.assertEqual(request["model_version"], SMART_MESH_MODEL_VERSION)
        self.assertTrue(request["quad"])
        self.assertEqual(request["face_limit"], 12000)
        with self.assertRaisesRegex(ValueError, "between 500 and 25000"):
            build_smart_mesh_request("task-123", face_limit=26000)

    def test_api_key_is_never_optional(self) -> None:
        with self.assertRaisesRegex(ValueError, "API key"):
            TripoClient("")


if __name__ == "__main__":
    unittest.main()
