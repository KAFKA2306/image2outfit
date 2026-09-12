from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.hypothesis_contracts import (
    validate_blueprint,
    validate_blueprint_actual_audit,
    validate_generation_assignments,
    validate_hypothesis_set,
    validate_reconciliation_contract,
    validate_render_back_contract,
    validate_target_avatar_authority,
)


class HypothesisContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.product_id = "garment"
        self.source_sha = "a" * 64
        self.target_avatar = {
            "avatarId": "SiroinoSotai_PC",
            "sourceAsset": "Assets/SiroinoSotai_PC.fbx",
            "tPoseId": "canonical-t-pose-v1",
            "armatureId": "SiroinoSotai_PC/Armature",
            "coordinateSystem": "blender-z-up-meter",
            "unitScaleM": 1.0,
            "garmentOriginReference": "Armature/Hips",
        }
        authority = validate_target_avatar_authority(self.target_avatar)
        self.authority_sha = authority["authoritySha256"]
        self.blueprint = {
            "schemaVersion": 1,
            "blueprintId": "bp-initial",
            "revision": 1,
            "productId": self.product_id,
            "sourceSha256": self.source_sha,
            "consumingStage": "initialize-3d",
            "targetAvatar": self.target_avatar,
            "observations": [
                {"state": "OBSERVED", "region": "front-torso"},
                {"state": "INFERRED", "region": "back-torso"},
                {"state": "UNKNOWN", "region": "inside-lining"},
            ],
            "mustPreserveRegions": ["collar"],
            "allowedFreedom": ["sleeve"],
            "expectedArtifactKinds": ["mesh-draft", "contact-sheet"],
            "reviewImage": {"path": "review.webp", "sha256": "b" * 64},
        }
        self.blueprint_summary = validate_blueprint(
            self.blueprint,
            expected_product_id=self.product_id,
            expected_source_sha256=self.source_sha,
            expected_avatar_id="SiroinoSotai_PC",
        )

    def test_blueprint_separates_observed_inferred_unknown_and_is_not_evidence(self) -> None:
        summary = self.blueprint_summary
        self.assertEqual(summary["observationCounts"]["OBSERVED"], 1)
        self.assertEqual(summary["observationCounts"]["INFERRED"], 1)
        self.assertEqual(summary["observationCounts"]["UNKNOWN"], 1)
        self.assertFalse(summary["isEvidence"])

    def test_blueprint_rejects_overlap_between_preserved_and_free_regions(self) -> None:
        payload = dict(self.blueprint)
        payload["allowedFreedom"] = ["collar"]
        with self.assertRaisesRegex(ValueError, "mustPreserveRegions"):
            validate_blueprint(payload, expected_product_id=self.product_id)

    def test_generation_assignment_keeps_semantics_separate_from_method(self) -> None:
        summary = validate_generation_assignments(
            {
                "schemaVersion": 1,
                "productId": self.product_id,
                "parts": [
                    {
                        "partId": "body",
                        "semanticRole": "cloth",
                        "generationMode": "pattern-first",
                    },
                    {
                        "partId": "buckle",
                        "semanticRole": "rigid",
                        "generationMode": "hybrid",
                    },
                    {
                        "partId": "trim",
                        "semanticRole": "trim",
                        "generationMode": "tripo-draft",
                    },
                ],
            },
            expected_product_id=self.product_id,
        )
        self.assertEqual(summary["partCount"], 3)
        self.assertEqual(summary["generationModeCounts"]["tripo-draft"], 1)

    def _hypothesis_set(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "productId": self.product_id,
            "blueprintSha256": self.blueprint_summary["blueprintSha256"],
            "targetAvatarAuthoritySha256": self.authority_sha,
            "silentFallbackUsed": False,
            "selectedHypothesisId": "tripo-1",
            "hypotheses": [
                {
                    "hypothesisId": "pattern-1",
                    "source": "pattern-first",
                    "artifactSha256": "c" * 64,
                    "targetAvatarAuthoritySha256": self.authority_sha,
                    "canonicalSource": True,
                },
                {
                    "hypothesisId": "tripo-1",
                    "source": "tripo-draft",
                    "artifactSha256": "d" * 64,
                    "targetAvatarAuthoritySha256": self.authority_sha,
                    "canonicalSource": False,
                    "generatorProvenance": {
                        "tool": "tripo",
                        "version": "p2-preview",
                    },
                },
            ],
        }

    def test_external_hypothesis_is_selectable_but_not_canonical(self) -> None:
        summary = validate_hypothesis_set(
            self._hypothesis_set(),
            expected_product_id=self.product_id,
            expected_blueprint_sha256=self.blueprint_summary["blueprintSha256"],
        )
        self.assertEqual(summary["selectedHypothesisId"], "tripo-1")
        self.assertEqual(summary["externalHypothesisCount"], 1)

    def test_external_hypothesis_cannot_be_promoted_to_canonical_source(self) -> None:
        payload = self._hypothesis_set()
        payload["hypotheses"][1]["canonicalSource"] = True  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "cannot be promoted"):
            validate_hypothesis_set(payload, expected_product_id=self.product_id)

    def test_hypothesis_set_rejects_silent_fallback(self) -> None:
        payload = self._hypothesis_set()
        payload["silentFallbackUsed"] = True
        with self.assertRaisesRegex(ValueError, "silentFallbackUsed=false"):
            validate_hypothesis_set(payload, expected_product_id=self.product_id)

    def test_reconciliation_bounds_local_changes(self) -> None:
        summary = validate_reconciliation_contract(
            {
                "schemaVersion": 1,
                "productId": self.product_id,
                "blueprintSha256": self.blueprint_summary["blueprintSha256"],
                "hypothesisSetSha256": "e" * 64,
                "changedRegions": ["sleeve"],
                "mustPreserveRegions": ["collar", "torso"],
                "allowedOperations": ["move-vertices", "reweight"],
                "disallowedOperations": ["replace-avatar", "global-rescale"],
                "preserveSilhouette": True,
                "preserveProportions": True,
            },
            expected_product_id=self.product_id,
        )
        self.assertEqual(summary["changedRegionCount"], 1)
        self.assertEqual(summary["preservedRegionCount"], 2)

    def test_reconciliation_rejects_changed_preserved_overlap(self) -> None:
        with self.assertRaisesRegex(ValueError, "mustPreserveRegions"):
            validate_reconciliation_contract(
                {
                    "schemaVersion": 1,
                    "productId": self.product_id,
                    "blueprintSha256": self.blueprint_summary["blueprintSha256"],
                    "hypothesisSetSha256": "e" * 64,
                    "changedRegions": ["collar"],
                    "mustPreserveRegions": ["collar"],
                    "allowedOperations": [],
                    "disallowedOperations": [],
                    "preserveSilhouette": True,
                    "preserveProportions": True,
                },
                expected_product_id=self.product_id,
            )

    def test_render_back_is_explicitly_not_canonical_quality_evidence(self) -> None:
        summary = validate_render_back_contract(
            {
                "schemaVersion": 1,
                "productId": self.product_id,
                "purpose": "ai-reinput",
                "canonicalQualityEvidence": False,
                "protocol": {
                    "camera": "front-ortho",
                    "pose": "t-pose",
                    "lighting": "neutral-v1",
                    "exposure": 0.0,
                    "resolution": [1024, 1024],
                    "framing": "full-body",
                },
            },
            expected_product_id=self.product_id,
        )
        self.assertFalse(summary["canonicalQualityEvidence"])

    def test_blueprint_actual_audit_requires_explicit_routing_decision(self) -> None:
        summary = validate_blueprint_actual_audit(
            {
                "schemaVersion": 1,
                "productId": self.product_id,
                "blueprintSha256": self.blueprint_summary["blueprintSha256"],
                "actualArtifactSha256": "f" * 64,
                "decision": "RETURN_STAGE",
                "deviations": [
                    {
                        "metric": "silhouette-iou",
                        "status": "FAIL",
                        "value": 0.72,
                    },
                    {
                        "metric": "back-detail",
                        "status": "NOT_ASSESSABLE",
                    },
                ],
            },
            expected_product_id=self.product_id,
        )
        self.assertEqual(summary["decision"], "RETURN_STAGE")
        self.assertEqual(summary["deviationCount"], 2)


if __name__ == "__main__":
    unittest.main()
