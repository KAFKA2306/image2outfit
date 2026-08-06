"""Static contract checks for the Siroino blue happi product."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-blue-happi"
PRODUCT_CONFIG = ROOT / "config" / "products" / PRODUCT_ID
PRODUCT_ROOT = ROOT / "Assets" / "GenWorks" / PRODUCT_ID
EXPECTED_STAGES = (
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
EXPECTED_AXES = {
    "topology",
    "seam",
    "fit",
    "material-response",
    "layering",
    "skinning",
    "collision",
    "silhouette",
    "styling-fidelity",
    "evidence-completeness",
}


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"expected object: {path}")
    return payload


class BlueHappiContractTests(unittest.TestCase):
    def test_private_reference_identity_and_retention(self) -> None:
        audit = read_json(PRODUCT_CONFIG / "reference-audit.json")
        digest = audit["source"]["originalSha256"]
        self.assertRegex(digest, re.compile(r"^[0-9a-f]{64}$"))
        self.assertEqual(
            digest,
            "9fc40516ae446274dc869cd695ea217fb741089d26dda43d685bba2d82da0423",
        )
        self.assertFalse(
            audit["source"]["sourceRetention"]["repositoryContainsSourceImage"]
        )

    def test_request_binds_exactly_thirteen_stages(self) -> None:
        request = read_json(
            ROOT / "config" / "pipeline" / "requests" / f"{PRODUCT_ID}.json"
        )
        self.assertEqual(tuple(request["stageBindings"]), EXPECTED_STAGES)
        for stage, binding in request["stageBindings"].items():
            self.assertIn(stage, binding["command"])
            self.assertEqual(
                binding["resultPath"],
                f".image2outfit/products/{{productId}}/stages/{stage}.json",
            )

    def test_pattern_and_stitch_graph_are_referentially_valid(self) -> None:
        pattern = read_json(PRODUCT_CONFIG / "pattern-draft.json")
        stitches = read_json(PRODUCT_CONFIG / "stitch-graph.json")
        piece_edges = {piece["id"]: set(piece["edges"]) for piece in pattern["pieces"]}
        self.assertGreaterEqual(len(piece_edges), 8)
        for stitch in stitches["stitches"]:
            for endpoint in (stitch["a"], stitch["b"]):
                piece, edge = endpoint.split(".", 1)
                self.assertIn(piece, piece_edges)
                self.assertIn(edge, piece_edges[piece])

    def test_quality_contract_has_exact_ten_axes(self) -> None:
        contract = read_json(PRODUCT_CONFIG / "quality-audit-contract.json")
        self.assertEqual(
            {axis["id"] for axis in contract["axes"]}, EXPECTED_AXES
        )
        self.assertEqual(len(contract["axes"]), 10)

    def test_manifest_stays_working_before_direct_review(self) -> None:
        manifest = read_json(PRODUCT_ROOT / "ProductManifest.json")
        self.assertEqual(manifest["status"], "WORKING")
        self.assertEqual(
            manifest["technicalGates"]["visualAppearanceReview"], "PENDING"
        )
        self.assertFalse((PRODUCT_CONFIG / "visual-review.json").exists())
        self.assertTrue((PRODUCT_CONFIG / "visual-review.template.json").is_file())

    def test_declared_executables_exist(self) -> None:
        job = read_json(PRODUCT_CONFIG / "job.json")
        self.assertTrue((ROOT / job["buildScript"]).is_file())
        request = read_json(
            ROOT / "config" / "pipeline" / "requests" / f"{PRODUCT_ID}.json"
        )
        for binding in request["stageBindings"].values():
            self.assertTrue((ROOT / binding["command"][1]).is_file())


if __name__ == "__main__":
    unittest.main()
