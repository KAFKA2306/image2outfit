from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "visual_review_bundle",
    ROOT / "tools" / "visual_review_bundle.py",
)
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class VisualReviewBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_root = M.ROOT

    def tearDown(self) -> None:
        M.ROOT = self.original_root

    def fixture(self, root: Path) -> tuple[Path, Path]:
        M.ROOT = root
        (root / "contracts" / "quality").mkdir(parents=True)
        quality = {
            "schemaVersion": 1,
            "specId": "q1",
            "directImageReview": {
                "requiredViews": ["front", "back"],
                "requiredPoses": ["neutral"],
            },
            "aspects": [
                {
                    "id": "silhouette",
                    "defectCode": "SILHOUETTE_FIDELITY_INVALID",
                    "returnStage": "build-blender",
                    "completionGate": "visualAppearanceReview",
                    "targetViews": ["front", "back"],
                    "targetPoses": ["neutral"],
                },
                {
                    "id": "evidence-completeness",
                    "computed": True,
                    "defectCode": "E",
                    "returnStage": "render-evidence",
                    "completionGate": "fiveViewEvidence",
                },
            ],
        }
        (root / "contracts" / "quality" / "quality-spec.json").write_text(
            json.dumps(quality),
            encoding="utf-8",
        )

        product = "garment"
        product_root = root / "Assets" / "GenWorks" / product
        (product_root / "Previews" / "Poses").mkdir(parents=True)
        for relative in (
            "Previews/front.png",
            "Previews/back.png",
            "Previews/Poses/neutral.png",
        ):
            path = product_root / relative
            path.write_bytes(relative.encode())

        manifest = {"schemaVersion": 1, "productId": product}
        (product_root / "ProductManifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

        reference_dir = root / "config" / "products" / product
        reference_dir.mkdir(parents=True)
        reference = {
            "schemaVersion": 1,
            "productId": product,
            "sha256": "a" * 64,
            "observedViews": ["front"],
        }
        (reference_dir / "reference.json").write_text(
            json.dumps(reference),
            encoding="utf-8",
        )

        job = {
            "schemaVersion": 2,
            "id": product,
            "adapterId": "adapter",
            "renderLoopRevision": "r1",
            "productManifestPath": (f"Assets/GenWorks/{product}/ProductManifest.json"),
            "previewPaths": {
                "front": f"Assets/GenWorks/{product}/Previews/front.png",
                "back": f"Assets/GenWorks/{product}/Previews/back.png",
            },
            "posePaths": {
                "neutral": (f"Assets/GenWorks/{product}/Previews/Poses/neutral.png")
            },
        }
        job_path = reference_dir / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")

        request = {
            "schemaVersion": 1,
            "productId": product,
            "revisionId": "v1",
            "sourceReference": "private-reference://sha256/" + "a" * 64,
        }
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return job_path, request_path

    def test_bundle_binds_candidate_reference_protocol_and_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job, request = self.fixture(Path(tmp))
            bundle = M.build_review_bundle(job, request)

            self.assertEqual(bundle["reference"]["sourceSha256"], "a" * 64)
            self.assertEqual(
                bundle["referenceAssessability"]["back"],
                "NOT_ASSESSABLE",
            )
            self.assertEqual(len(bundle["currentImages"]), 3)
            self.assertEqual(
                bundle["bundleSha256"],
                M._bundle_digest(bundle),
            )

    def test_unobserved_reference_view_cannot_pass_fidelity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job, request = self.fixture(Path(tmp))
            bundle = M.build_review_bundle(job, request)
            review = {
                "schemaVersion": 1,
                "productId": "garment",
                "reviewBundleSha256": bundle["bundleSha256"],
                "candidateManifestSha256": bundle["candidateManifest"]["sha256"],
                "renderProtocolSha256": bundle["renderProtocolSha256"],
                "opinions": [
                    {
                        "criterionId": "silhouette",
                        "status": "PASS",
                        "view": "back",
                        "pose": "neutral",
                        "confidence": 0.8,
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "cannot PASS"):
                M.validate_review_result(review, bundle)

    def test_fail_maps_to_existing_defect_and_return_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job, request = self.fixture(Path(tmp))
            bundle = M.build_review_bundle(job, request)
            review = {
                "schemaVersion": 1,
                "productId": "garment",
                "reviewBundleSha256": bundle["bundleSha256"],
                "candidateManifestSha256": bundle["candidateManifest"]["sha256"],
                "renderProtocolSha256": bundle["renderProtocolSha256"],
                "opinions": [
                    {
                        "criterionId": "silhouette",
                        "status": "FAIL",
                        "view": "front",
                        "pose": "neutral",
                        "confidence": 0.9,
                        "observedDefect": "too wide",
                        "probableCause": "pattern width",
                    }
                ],
            }
            findings = M.validate_review_result(review, bundle)
            self.assertEqual(
                findings[0]["code"],
                "SILHOUETTE_FIDELITY_INVALID",
            )
            self.assertEqual(
                findings[0]["recommendedReturnStage"],
                "build-blender",
            )

    def test_stale_candidate_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job, request = self.fixture(Path(tmp))
            bundle = M.build_review_bundle(job, request)
            review = {
                "schemaVersion": 1,
                "productId": "garment",
                "reviewBundleSha256": bundle["bundleSha256"],
                "candidateManifestSha256": "0" * 64,
                "renderProtocolSha256": bundle["renderProtocolSha256"],
                "opinions": [
                    {
                        "criterionId": "silhouette",
                        "status": "NOT_ASSESSABLE",
                        "view": "back",
                        "pose": "neutral",
                        "confidence": 0.5,
                    }
                ],
            }
            with self.assertRaisesRegex(
                ValueError,
                "candidateManifestSha256",
            ):
                M.validate_review_result(review, bundle)

    def test_tracked_wide_cargo_builds_real_bundle(self) -> None:
        product_id = "siroino-wide-cargo"
        job_path = self.original_root / "config" / "products" / product_id / "job.json"
        with tempfile.TemporaryDirectory(dir=self.original_root) as tmp:
            request_path = Path(tmp) / "request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "productId": product_id,
                        "revisionId": "tracked-wide-cargo-smoke",
                        "sourceReference": ("private-reference://sha256/" + "b" * 64),
                    }
                ),
                encoding="utf-8",
            )
            bundle = M.build_review_bundle(job_path, request_path)

        self.assertEqual(bundle["productId"], product_id)
        self.assertEqual(len(bundle["currentImages"]), 11)
        self.assertEqual(
            {item["kind"] for item in bundle["currentImages"]},
            {"view", "pose"},
        )
        self.assertEqual(
            bundle["reference"]["sourceSha256"],
            "b" * 64,
        )


if __name__ == "__main__":
    unittest.main()
