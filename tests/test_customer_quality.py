from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import customer_quality  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class CustomerQualityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = json.loads(
            (ROOT / "config" / "release-policy.json").read_text(encoding="utf-8")
        )
        self.job = {"id": "test-product", "adapterId": "test-adapter-v1"}
        self.candidate_files = [
            {"path": f"Preview/{view}.png", "bytes": 24, "sha256": "0" * 64}
            for view in self.policy["minimumPreview"]["requiredViews"]
        ]
        self.candidate_files.extend(
            {"path": f"Pose/{pose}.png", "bytes": 24, "sha256": "1" * 64}
            for pose in self.policy["requiredPoses"]
        )
        self.manifest = {
            "schemaVersion": 2,
            "kind": "image2outfit-candidate",
            "jobId": self.job["id"],
            "adapterId": self.job["adapterId"],
            "createdAt": "2026-08-02T00:00:00Z",
            "files": self.candidate_files,
        }
        self.candidate_hash = "2" * 64
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
            "defects": [],
        }
        previews = [
            f"Preview/{view}.png"
            for view in self.policy["minimumPreview"]["requiredViews"]
        ]
        poses = {
            pose: f"Pose/{pose}.png" for pose in self.policy["requiredPoses"]
        }
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
                "customerUseCase": "VRChat avatar outfit installation and normal social use.",
            },
            "pose-penetration-review": {
                **common,
                "kind": "pose-penetration-review",
                "poses": {pose: "PASS" for pose in poses},
                "poseEvidence": poses,
                "criticalPenetrations": 0,
                "reviewedAssets": list(poses.values()),
                "poseNotes": "Required motion set shows no blocking penetration or detached parts.",
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
        self.assertIn(
            "visual-review: reviewedAssets.required:Preview/back.png", errors
        )

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


if __name__ == "__main__":
    unittest.main()
