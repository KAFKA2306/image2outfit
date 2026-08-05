from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-tuxedo-halter-dress-large"
PRODUCT_CONFIG = ROOT / "config" / "products" / PRODUCT_ID
REQUEST = ROOT / "config" / "pipeline" / "requests" / f"{PRODUCT_ID}.json"
CANONICAL_STAGES = (
    "ingest-reference",
    "normalize-view",
    "decompose-garment",
    "draft-patterns",
    "infer-stitches",
    "initialize-3d",
    "build-blender",
    "simulate-cloth",
    "skin-and-export",
    "render-evidence",
    "audit-geometry",
    "visual-review",
    "finalize-candidate",
)


def read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError(path)
    return payload


class ReferenceProductContractTests(unittest.TestCase):
    def test_private_reference_is_bound_by_hash_without_redistribution(self) -> None:
        audit = read(PRODUCT_CONFIG / "reference-audit.json")
        identity = read(PRODUCT_CONFIG / "reference-identity.json")
        self.assertEqual(audit["productId"], PRODUCT_ID)
        self.assertEqual(identity["productId"], PRODUCT_ID)
        self.assertEqual(audit["modelIdentification"]["status"], "UNVERIFIED")
        self.assertTrue(
            all(claim["status"] == "UNVERIFIED" for claim in identity["claims"])
        )
        self.assertTrue(all(claim["value"] is None for claim in identity["claims"]))
        self.assertFalse(
            audit["source"]["sourceRetention"]["repositoryContainsSourceImage"]
        )
        source_reference = (
            "private-reference://sha256/"
            + audit["source"]["originalSha256"]
        )
        self.assertEqual(identity["sourceReference"], source_reference)
        self.assertEqual(len(audit["source"]["originalSha256"]), 64)
        int(audit["source"]["originalSha256"], 16)
        self.assertFalse(any(PRODUCT_CONFIG.glob("*.png")))
        self.assertFalse(any(PRODUCT_CONFIG.glob("*.webp")))
        self.assertFalse(any(PRODUCT_CONFIG.glob("*.b64")))

    def test_request_binds_every_canonical_stage_and_revision(self) -> None:
        request = read(REQUEST)
        self.assertEqual(request["productId"], PRODUCT_ID)
        self.assertTrue(request["revisionId"])
        self.assertEqual(tuple(request["stageBindings"]), CANONICAL_STAGES)
        for stage, binding in request["stageBindings"].items():
            self.assertEqual(binding["command"][2:4], ["--stage", stage])
            self.assertTrue(binding["resultPath"].startswith(".image2outfit/"))
        self.assertEqual(
            request["stageBindings"]["ingest-reference"]["command"][1],
            "tools/run_ingest_reference_stage.py",
        )

    def test_observation_pattern_and_stitch_contracts_are_nonempty(self) -> None:
        decomposition = read(PRODUCT_CONFIG / "garment-decomposition.json")
        pattern = read(PRODUCT_CONFIG / "pattern-draft.json")
        stitch = read(PRODUCT_CONFIG / "stitch-graph.json")
        self.assertGreaterEqual(len(decomposition["parts"]), 12)
        self.assertGreaterEqual(len(pattern["pieces"]), 8)
        self.assertGreaterEqual(len(stitch["stitches"]), 8)
        self.assertEqual(
            decomposition["sourceReference"],
            "private-reference://sha256/"
            "66cd898014d3f503da8015207a0240d946aac72b596f28bef8d6574a0afb678b",
        )

    def test_job_paths_and_scripts_are_closed_over_the_product_namespace(self) -> None:
        job = read(PRODUCT_CONFIG / "job.json")
        root = f"Assets/GenWorks/{PRODUCT_ID}"
        self.assertEqual(job["productRoot"], root)
        self.assertTrue(job["blendPath"].startswith(root + "/"))
        self.assertTrue(job["fbxAssetPath"].startswith(root + "/"))
        self.assertEqual(
            job["buildScript"],
            "tools/siroino_tuxedo_halter_dress_large_build.py",
        )
        for script in (
            ROOT / job["buildScript"],
            ROOT / "tools" / "run_reference_product_stage.py",
            ROOT / "tools" / "run_ingest_reference_stage.py",
        ):
            self.assertTrue(script.is_file(), str(script))
            hashlib.sha256(script.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
