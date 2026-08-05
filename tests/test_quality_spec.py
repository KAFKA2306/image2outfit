from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.quality import validate_quality_assessment


class QualitySpecTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.spec = json.loads(
            (ROOT / "config" / "quality-spec.json").read_text(encoding="utf-8")
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
        self.assertEqual(
            "FAIL", result["aspects"]["evidence-completeness"]["status"]
        )
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
