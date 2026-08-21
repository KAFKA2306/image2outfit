from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import customer_quality
from candidate_quality import (
    QUALITY_PASS,
    QUALITY_PENDING,
    QUALITY_REJECT,
    candidate_status,
    geometry_quality,
    validate_visual_review,
    verify_inspected_images,
)
from image2outfit.quality import validate_quality_assessment


class CandidateQualityTests(unittest.TestCase):
    def test_geometry_reject_is_a_quality_decision_not_an_exception(self) -> None:
        decision = geometry_quality(
            {
                "passed": False,
                "metrics": {
                    "unweightedVertices": 0,
                    "degenerateTriangles": 116,
                },
                "geometryGate": {
                    "passed": False,
                    "checks": {
                        "unweightedVertices==0": True,
                        "degenerateTriangles==0": False,
                    },
                },
            }
        )
        self.assertEqual(decision["decision"], QUALITY_REJECT)
        self.assertFalse(decision["passed"])
        self.assertIn("degenerateTriangles==0", decision["failedChecks"])

    def test_geometry_pass_requires_all_declared_checks(self) -> None:
        decision = geometry_quality(
            {
                "passed": True,
                "metrics": {
                    "unweightedVertices": 0,
                    "degenerateTriangles": 0,
                },
                "geometryGate": {
                    "passed": True,
                    "checks": {
                        "unweightedVertices==0": True,
                        "degenerateTriangles==0": True,
                    },
                },
            }
        )
        self.assertEqual(decision["decision"], QUALITY_PASS)
        self.assertTrue(decision["passed"])
        self.assertEqual(decision["failedChecks"], [])

    def test_direct_review_accepts_explicit_rejection(self) -> None:
        review = validate_visual_review(
            {
                "schemaVersion": 1,
                "productId": "ghost-gown",
                "status": "REJECTED",
                "decision": "REJECT",
                "reviewMethod": "direct-image-inspection",
                "reviewedRevision": "v1",
                "inspectedImages": {"front.png": "a" * 64},
                "findings": [{"code": "silhouette"}],
            },
            product_id="ghost-gown",
            revision_id="v1",
        )
        self.assertEqual(review["decision"], QUALITY_REJECT)

    def test_direct_review_rejects_inconsistent_status_and_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            validate_visual_review(
                {
                    "schemaVersion": 1,
                    "productId": "ghost-gown",
                    "status": "REJECTED",
                    "decision": "PASS",
                    "reviewMethod": "direct-image-inspection",
                    "reviewedRevision": "v1",
                    "inspectedImages": {"front.png": "a" * 64},
                    "findings": [{"code": "silhouette"}],
                },
                product_id="ghost-gown",
                revision_id="v1",
            )

    def test_review_is_bound_to_exact_render_hashes(self) -> None:
        inspected = {"front.png": "a" * 64, "back.png": "b" * 64}
        verify_inspected_images(inspected, dict(inspected))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_inspected_images(
                inspected,
                {"front.png": "c" * 64, "back.png": "b" * 64},
            )

    def test_candidate_status_distinguishes_rejected_from_working(self) -> None:
        passing = {"geometry": True, "visual": True, "artifact": True}
        self.assertEqual(
            candidate_status(
                passing,
                geometry_decision=QUALITY_PASS,
                visual_decision=QUALITY_PASS,
            ),
            "COMPLETE",
        )
        self.assertEqual(
            candidate_status(
                {**passing, "geometry": False},
                geometry_decision=QUALITY_REJECT,
                visual_decision=QUALITY_PASS,
            ),
            "REJECTED",
        )
        self.assertEqual(
            candidate_status(
                {**passing, "visual": False},
                geometry_decision=QUALITY_PASS,
                visual_decision=QUALITY_REJECT,
            ),
            "REJECTED",
        )
        self.assertEqual(
            candidate_status(
                {**passing, "visual": False},
                geometry_decision=QUALITY_PASS,
                visual_decision=QUALITY_PENDING,
            ),
            "WORKING",
        )

    def test_candidate_status_rejects_unknown_quality_decisions(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown quality decision"):
            candidate_status(
                {"geometry": False, "visual": False},
                geometry_decision="UNKNOWN",
                visual_decision=QUALITY_PENDING,
            )


class CustomerQualityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = json.loads(
            (ROOT / "config" / "release-policy.json").read_text(encoding="utf-8")
        )
        self.job = {
            "id": "test-product",
            "adapterId": "test-adapter-v1",
            "humanEvidence": {},
        }
        self.candidate_files = [
            {"path": f"Preview/{view}.png", "bytes": 24, "sha256": "0" * 64}
            for view in self.policy["minimumPreview"]["requiredViews"]
        ]
        self.candidate_files.extend(
            {
                "path": f"Pose/{pose}.png",
                "bytes": 24,
                "sha256": f"{index + 1:x}" * 64,
            }
            for index, pose in enumerate(self.policy["requiredPoses"])
        )
        self.manifest = {
            "schemaVersion": 2,
            "kind": "image2outfit-candidate",
            "jobId": self.job["id"],
            "adapterId": self.job["adapterId"],
            "createdAt": "2026-08-02T00:00:00Z",
            "files": self.candidate_files,
        }
        self.candidate_hash = "a" * 64
        runtime = self.root / "Evidence" / "runtime.png"
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\x0dIHDR"
            + struct.pack(">II", 1920, 1080)
        )
        self.runtime_path = "Evidence/runtime.png"
        self.runtime_hash = self.digest(runtime)
        self.evidence = self.passing_evidence()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def resolve(self, value: str) -> Path:
        path = (self.root / value).resolve()
        path.relative_to(self.root.resolve())
        return path

    def passing_evidence(self) -> dict[str, dict]:
        common = {
            "schemaVersion": 2,
            "jobId": self.job["id"],
            "adapterId": self.job["adapterId"],
            "candidateManifestSha256": self.candidate_hash,
            "status": "PASS",
            "checkedAt": "2026-08-02T00:01:00Z",
            "reviewer": "human:test-reviewer",
            "reviewerReference": (
                "https://github.com/KAFKA2306/image2outfit/"
                "pull/123#pullrequestreview-456"
            ),
            "defects": [],
        }
        previews = [
            f"Preview/{view}.png"
            for view in self.policy["minimumPreview"]["requiredViews"]
        ]
        poses = {pose: f"Pose/{pose}.png" for pose in self.policy["requiredPoses"]}
        score_fields = self.policy["humanEvidenceContracts"]["visual-review"][
            "scoreFields"
        ]
        return {
            "visual-review": {
                **common,
                "kind": "visual-review",
                "scores": {field: 5 for field in score_fields},
                "criticalDefects": 0,
                "reviewedAssets": previews,
                "reviewSummary": "All required views were inspected at full resolution.",
                "customerUseCase": (
                    "VRChat avatar outfit installation and normal social use."
                ),
            },
            "pose-penetration-review": {
                **common,
                "kind": "pose-penetration-review",
                "poses": {pose: "PASS" for pose in poses},
                "poseEvidence": poses,
                "criticalPenetrations": 0,
                "reviewedAssets": list(poses.values()),
                "poseNotes": (
                    "Required motion set shows no blocking penetration or detached parts."
                ),
            },
            "vrchat-runtime-review": {
                **common,
                "kind": "vrchat-runtime-review",
                "vrchatBuildAndTest": "PASS",
                "testedInVRChat": True,
                "runtimeScreenshot": self.runtime_path,
                "runtimeScreenshotSha256": self.runtime_hash,
                "runtimeNotes": "Installed, toggled and exercised in VRChat Build & Test.",
                "testedPlatform": "Windows PCVR",
                "installationStepsVerified": True,
                "customerReady": True,
                "customerAcceptance": {
                    field: "PASS"
                    for field in self.policy["humanEvidenceContracts"][
                        "vrchat-runtime-review"
                    ]["customerAcceptanceFields"]
                },
            },
        }

    def validate(self) -> tuple[dict, list[str]]:
        return customer_quality.validate(
            job=self.job,
            policy=self.policy,
            candidate_manifest=self.manifest,
            candidate_hash=self.candidate_hash,
            evidence=self.evidence,
            resolve_repo_path=self.resolve,
            digest=self.digest,
        )

    def test_complete_customer_evidence_passes(self) -> None:
        result, errors = self.validate()
        self.assertEqual([], errors)
        self.assertTrue(all(item["passed"] for item in result.values()))

    def test_visual_review_must_cover_every_required_view(self) -> None:
        self.evidence["visual-review"]["reviewedAssets"].remove("Preview/back.png")
        _, errors = self.validate()
        self.assertIn("visual-review: reviewedAssets.required:Preview/back.png", errors)

    def test_unresolved_major_defect_blocks_release(self) -> None:
        self.evidence["visual-review"]["defects"] = [
            {
                "id": "FIT-001",
                "severity": "major",
                "status": "OPEN",
                "category": "fit",
                "description": "Body penetration is visible at the inner thigh.",
                "evidencePaths": ["Preview/back.png"],
            }
        ]
        _, errors = self.validate()
        self.assertIn("visual-review: blockingDefects", errors)

    def test_runtime_screenshot_is_hash_bound(self) -> None:
        self.evidence["vrchat-runtime-review"]["runtimeScreenshotSha256"] = "f" * 64
        _, errors = self.validate()
        self.assertIn("vrchat-runtime-review: runtimeScreenshotSha256", errors)

    def test_review_cannot_predate_candidate(self) -> None:
        self.evidence["visual-review"]["checkedAt"] = "2026-08-01T23:59:00Z"
        _, errors = self.validate()
        self.assertIn("visual-review: checkedAfterCandidate", errors)

    def test_review_requires_auditable_github_reference(self) -> None:
        self.evidence["visual-review"]["reviewerReference"] = "manual"
        _, errors = self.validate()
        self.assertIn("visual-review: reviewerReference", errors)

    def test_one_image_cannot_prove_two_required_poses(self) -> None:
        self.evidence["pose-penetration-review"]["poseEvidence"]["sit"] = (
            "Pose/crouch.png"
        )
        _, errors = self.validate()
        self.assertIn(
            "pose-penetration-review: poseEvidence.duplicate:Pose/crouch.png", errors
        )


class QualitySpecTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.spec = json.loads(
            (ROOT / "contracts" / "quality" / "quality-spec.json").read_text(
                encoding="utf-8"
            )
        )
        self.candidate_hash = "a" * 64
        self.assessment = self._passing_assessment()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def resolve(self, value: str) -> Path:
        path = (self.root / value).resolve()
        path.relative_to(self.root.resolve())
        return path

    def _evidence(
        self,
        name: str,
        kind: str,
        *,
        view: str | None = None,
        pose: str | None = None,
    ) -> dict[str, str]:
        path = self.root / "Evidence" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"evidence:{name}".encode())
        value = {
            "kind": kind,
            "path": path.relative_to(self.root).as_posix(),
            "sha256": self.digest(path),
        }
        if view is not None:
            value["view"] = view
        if pose is not None:
            value["pose"] = pose
        return value

    def _passing_assessment(self) -> dict:
        results: dict[str, dict] = {}
        for aspect in self.spec["aspects"]:
            if aspect.get("computed"):
                continue
            aspect_id = aspect["id"]
            method = aspect["allowedReviewMethods"][0]
            evidence = [
                self._evidence(
                    f"{aspect_id}-{index}.png"
                    if method == "DIRECT_IMAGE_REVIEW"
                    else f"{aspect_id}-{index}.json",
                    kind,
                    view=aspect.get("targetViews", [None])[0]
                    if aspect.get("targetViews")
                    else None,
                    pose=aspect.get("targetPoses", [None])[0]
                    if aspect.get("targetPoses")
                    else None,
                )
                for index, kind in enumerate(aspect["requiredEvidenceKinds"])
            ]
            results[aspect_id] = {
                "status": "PASS",
                "metricValue": 0,
                "targetViews": aspect["targetViews"],
                "targetPoses": aspect["targetPoses"],
                "reviewMethod": method,
                "reviewer": (
                    "human:test-reviewer"
                    if method == "DIRECT_IMAGE_REVIEW"
                    else f"tool:{aspect_id}-audit"
                ),
                "reviewerReference": "https://github.com/example/review/1",
                "evidence": evidence,
            }
        direct_evidence: list[dict[str, str]] = []
        for view in self.spec["directImageReview"]["requiredViews"]:
            direct_evidence.append(
                self._evidence(
                    f"view-{view}.png",
                    "direct-render-image",
                    view=view,
                    pose="neutral" if view == "front" else None,
                )
            )
        for pose in self.spec["directImageReview"]["requiredPoses"]:
            if pose == "neutral":
                continue
            direct_evidence.append(
                self._evidence(
                    f"pose-{pose}.png",
                    "direct-render-image",
                    pose=pose,
                )
            )
        return {
            "schemaVersion": 1,
            "specId": self.spec["specId"],
            "jobId": "test-product",
            "adapterId": "test-adapter-v1",
            "candidateManifestSha256": self.candidate_hash,
            "results": results,
            "visualAppearanceReview": {
                "status": "PASS",
                "reviewMethod": "DIRECT_IMAGE_REVIEW",
                "reviewer": "human:test-reviewer",
                "reviewerReference": "https://github.com/example/review/1",
                "evidence": direct_evidence,
            },
        }

    def validate(self) -> tuple[dict, list[str]]:
        return validate_quality_assessment(
            spec_data=self.spec,
            assessment=self.assessment,
            job_id="test-product",
            adapter_id="test-adapter-v1",
            candidate_manifest_sha256=self.candidate_hash,
            resolve_repo_path=self.resolve,
            digest=self.digest,
        )

    def test_all_quality_axes_and_direct_review_pass(self) -> None:
        result, errors = self.validate()
        self.assertEqual([], errors)
        self.assertTrue(result["passed"])
        self.assertEqual(10, len(result["aspects"]))
        self.assertEqual("PASS", result["visualAppearanceReview"]["status"])

    def test_metric_failure_expands_to_cause_specific_defect(self) -> None:
        self.assessment["results"]["collision"]["metricValue"] = 2
        result, errors = self.validate()
        self.assertIn("results.collision.metricThreshold", errors)
        collision = [
            item for item in result["defects"] if item["aspect"] == "collision"
        ]
        self.assertEqual("COLLISION_BLOCKING", collision[0]["code"])
        self.assertEqual("simulate-cloth", collision[0]["recommendedReturnStage"])

    def test_hash_mismatch_blocks_axis_and_evidence_completeness(self) -> None:
        self.assessment["results"]["topology"]["evidence"][0]["sha256"] = "f" * 64
        result, errors = self.validate()
        self.assertTrue(any("sha256Mismatch" in item for item in errors))
        self.assertEqual("FAIL", result["aspects"]["topology"]["status"])
        self.assertEqual("FAIL", result["aspects"]["evidence-completeness"]["status"])
        self.assertFalse(result["passed"])

    def test_visual_appearance_requires_direct_image_review(self) -> None:
        self.assessment["visualAppearanceReview"]["reviewMethod"] = "AUTOMATED"
        result, errors = self.validate()
        self.assertIn("visualAppearanceReview.reviewMethod", errors)
        self.assertEqual("FAIL", result["visualAppearanceReview"]["status"])

    def test_allowed_out_of_scope_is_not_counted_as_failure(self) -> None:
        seam = self.assessment["results"]["seam"]
        seam.update(
            status="OUT_OF_SCOPE",
            outOfScopeReason="The fitted construction profile has no explicit seams.",
            evidence=[],
        )
        result, errors = self.validate()
        self.assertEqual([], errors)
        self.assertEqual("OUT_OF_SCOPE", result["aspects"]["seam"]["status"])
        self.assertIn("seam", result["outOfScopeAspects"])
        self.assertTrue(result["passed"])

    def test_candidate_hash_binding_is_required(self) -> None:
        self.assessment["candidateManifestSha256"] = "b" * 64
        result, errors = self.validate()
        self.assertIn("candidateManifestSha256", errors)
        self.assertFalse(result["releaseReady"])


if __name__ == "__main__":
    unittest.main()
