from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "visual_review_bundle_blueprint",
    ROOT / "tools" / "visual_review_bundle.py",
)
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class VisualReviewBlueprintBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_root = M.ROOT

    def tearDown(self) -> None:
        M.ROOT = self.original_root

    def fixture(self, root: Path) -> tuple[Path, Path, Path]:
        M.ROOT = root
        product_id = "garment"
        source_sha = "a" * 64

        quality_dir = root / "contracts" / "quality"
        quality_dir.mkdir(parents=True)
        quality_dir.joinpath("quality-spec.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "specId": "q1",
                    "directImageReview": {
                        "requiredViews": ["front"],
                        "requiredPoses": ["neutral"],
                    },
                    "aspects": [
                        {
                            "id": "silhouette",
                            "defectCode": "SILHOUETTE_FIDELITY_INVALID",
                            "returnStage": "build-blender",
                            "completionGate": "visualAppearanceReview",
                            "targetViews": ["front"],
                            "targetPoses": ["neutral"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        product_root = root / "Assets" / "GenWorks" / product_id
        (product_root / "Previews" / "Poses").mkdir(parents=True)
        product_root.joinpath("Previews/front.png").write_bytes(b"front")
        product_root.joinpath("Previews/Poses/neutral.png").write_bytes(b"neutral")
        product_root.joinpath("ProductManifest.json").write_text(
            json.dumps({"schemaVersion": 1, "productId": product_id}),
            encoding="utf-8",
        )

        config_dir = root / "config" / "products" / product_id
        config_dir.mkdir(parents=True)
        config_dir.joinpath("reference.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "productId": product_id,
                    "sha256": source_sha,
                    "observedViews": ["front"],
                }
            ),
            encoding="utf-8",
        )
        blueprint = {
            "schemaVersion": 1,
            "blueprintId": "initial-v1",
            "revision": 1,
            "productId": product_id,
            "sourceSha256": source_sha,
            "consumingStage": "initialize-3d",
            "targetAvatar": {
                "avatarId": "SiroinoSotai_PC",
                "sourceAsset": "Assets/SiroinoSotai_PC.fbx",
                "tPoseId": "canonical-t-pose-v1",
                "armatureId": "SiroinoSotai_PC/Armature",
                "coordinateSystem": "blender-z-up-meter",
                "unitScaleM": 1.0,
                "garmentOriginReference": "Armature/Hips",
            },
            "observations": [
                {"state": "OBSERVED", "region": "front"},
                {"state": "UNKNOWN", "region": "back"},
            ],
            "mustPreserveRegions": ["collar"],
            "allowedFreedom": ["sleeve"],
            "expectedArtifactKinds": ["mesh-draft"],
        }
        blueprint_path = config_dir / "blueprint.json"
        blueprint_path.write_text(json.dumps(blueprint), encoding="utf-8")

        job = {
            "schemaVersion": 2,
            "id": product_id,
            "adapterId": "adapter",
            "renderLoopRevision": "r1",
            "productManifestPath": f"Assets/GenWorks/{product_id}/ProductManifest.json",
            "previewPaths": {
                "front": f"Assets/GenWorks/{product_id}/Previews/front.png"
            },
            "posePaths": {
                "neutral": f"Assets/GenWorks/{product_id}/Previews/Poses/neutral.png"
            },
            "garmentPipeline": {
                "blueprintPath": f"config/products/{product_id}/blueprint.json"
            },
        }
        job_path = config_dir / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        request_path = root / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "productId": product_id,
                    "revisionId": "v1",
                    "sourceReference": "private-reference://sha256/" + source_sha,
                }
            ),
            encoding="utf-8",
        )
        return job_path, request_path, blueprint_path

    def test_bundle_hash_binds_blueprint_but_does_not_treat_it_as_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_path, request_path, _ = self.fixture(Path(tmp))
            bundle = M.build_review_bundle(job_path, request_path)
            self.assertEqual(bundle["blueprint"]["blueprintId"], "initial-v1")
            self.assertFalse(bundle["blueprint"]["isEvidence"])
            self.assertEqual(bundle["bundleSha256"], M._bundle_digest(bundle))

    def test_review_must_bind_same_blueprint_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_path, request_path, _ = self.fixture(Path(tmp))
            bundle = M.build_review_bundle(job_path, request_path)
            review = {
                "schemaVersion": 1,
                "productId": "garment",
                "reviewBundleSha256": bundle["bundleSha256"],
                "candidateManifestSha256": bundle["candidateManifest"]["sha256"],
                "renderProtocolSha256": bundle["renderProtocolSha256"],
                "blueprintSha256": "0" * 64,
                "opinions": [
                    {
                        "criterionId": "silhouette",
                        "status": "PASS",
                        "view": "front",
                        "pose": "neutral",
                        "confidence": 1.0,
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "blueprintSha256"):
                M.validate_review_result(review, bundle)
            review["blueprintSha256"] = bundle["blueprint"]["blueprintSha256"]
            self.assertEqual(M.validate_review_result(review, bundle), [])

    def test_blueprint_source_hash_must_match_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_path, request_path, blueprint_path = self.fixture(Path(tmp))
            blueprint = json.loads(blueprint_path.read_text(encoding="utf-8"))
            blueprint["sourceSha256"] = "f" * 64
            blueprint_path.write_text(json.dumps(blueprint), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                M.build_review_bundle(job_path, request_path)


if __name__ == "__main__":
    unittest.main()
