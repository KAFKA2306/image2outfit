from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "review_console.py"
SPEC = importlib.util.spec_from_file_location("review_console_v2", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReviewConsoleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.output = self.root / ".image2outfit" / "review-console"
        (self.root / "config").mkdir(parents=True)
        (self.root / "config" / "release-policy.json").write_text(
            json.dumps(
                {
                    "required_views": ["front", "back"],
                    "required_poses": ["arms-up"],
                }
            ),
            encoding="utf-8",
        )
        product = self.root / "Assets" / "GenWorks" / "demo-outfit"
        (product / "Previews" / "Poses").mkdir(parents=True)
        (product / "Evidence").mkdir()
        (product / "Logs").mkdir()
        (product / "Previews" / "front.png").write_bytes(b"front-image")
        (product / "Evidence" / "review.json").write_text("{}", encoding="utf-8")
        (product / "Logs" / "runtime.txt").write_text(
            "missing screenshot", encoding="utf-8"
        )
        expected_review_hash = MODULE.digest(product / "Evidence" / "review.json")
        (product / "ProductManifest.json").write_text(
            json.dumps(
                {
                    "state": "WORKING",
                    "updated_at": "2026-08-04T00:00:00Z",
                    "resume_point": "human review",
                    "candidate_hash": "candidate-abc",
                    "human_review_url": "https://github.com/KAFKA2306/image2outfit/pull/100#pullrequestreview-1",
                    "blockers": [
                        {
                            "severity": "major",
                            "message": "back clipping",
                            "status": "open",
                        },
                        {
                            "severity": "minor",
                            "message": "resolved note",
                            "status": "resolved",
                        },
                    ],
                    "gates": {
                        "fit": {"status": "PASS"},
                        "runtime": {
                            "status": "FAIL",
                            "message": "missing screenshot",
                            "log": "Logs/runtime.txt",
                        },
                    },
                    "evidence": [
                        {
                            "label": "human review",
                            "path": "Evidence/review.json",
                            "status": "PASS",
                            "sha256": expected_review_hash,
                        },
                        {
                            "label": "tampered evidence",
                            "path": "Evidence/review.json",
                            "status": "PASS",
                            "sha256": "wrong-hash",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        report_dir = (
            self.root / ".image2outfit" / "products" / "demo-outfit" / "reports"
        )
        report_dir.mkdir(parents=True)
        (report_dir / "customer-quality.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "candidateManifestSha256": "candidate-quality-sha",
                    "evidence": {
                        "qualitySpec": {
                            "specPath": "contracts/quality/quality-spec.json",
                            "passed": False,
                            "candidateManifestSha256": "candidate-quality-sha",
                            "aspects": {
                                "topology": {
                                    "status": "FAIL",
                                    "metric": {
                                        "name": "invalidTopologyFindingCount",
                                        "value": 2,
                                        "operator": "lte",
                                        "threshold": 0,
                                    },
                                    "recommendedReturnStage": "build-blender",
                                    "evidence": [
                                        {
                                            "kind": "geometry-audit",
                                            "path": "Assets/GenWorks/demo-outfit/Evidence/review.json",
                                            "sha256": expected_review_hash,
                                            "verified": True,
                                            "view": None,
                                            "pose": "neutral",
                                        }
                                    ],
                                }
                            },
                            "visualAppearanceReview": {
                                "status": "PASS",
                                "reviewMethod": "DIRECT_IMAGE_REVIEW",
                                "reviewer": "human:reviewer",
                                "evidence": [],
                            },
                            "defects": [
                                {
                                    "code": "TOPOLOGY_INVALID",
                                    "aspect": "topology",
                                    "recommendedReturnStage": "build-blender",
                                    "reasons": ["non-manifold edge"],
                                }
                            ],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_build_reports_state_blockers_assets_gates_and_hashes(self) -> None:
        data = MODULE.build(self.root, self.output)
        self.assertEqual(data["schema_version"], "review-console.v2")
        self.assertEqual(data["required_views"], ["front", "back"])
        self.assertEqual(data["required_poses"], ["arms-up"])
        self.assertEqual(len(data["products"]), 1)

        record = data["products"][0]
        self.assertEqual(record["slug"], "demo-outfit")
        self.assertEqual(record["state"], "WORKING")
        self.assertEqual(record["blocker_count"], 2)
        self.assertEqual(record["blockers"][0]["severity"], "MAJOR")
        self.assertIn("TOPOLOGY_INVALID", record["blockers"][1]["message"])
        self.assertIn("return build-blender", record["blockers"][1]["message"])
        self.assertEqual(record["resume_point"], "human review")
        self.assertEqual(record["candidate_hash"], "candidate-quality-sha")
        self.assertEqual(
            [asset["status"] for asset in record["assets"]],
            ["PASS", "MISSING", "MISSING"],
        )
        self.assertIsNotNone(record["assets"][0]["sha256"])
        gates = {gate["name"]: gate for gate in record["gates"]}
        self.assertEqual(gates["fit"]["status"], "PASS")
        self.assertEqual(gates["runtime"]["status"], "FAIL")
        self.assertTrue(gates["runtime"]["href"].endswith("Logs/runtime.txt"))
        self.assertEqual(gates["quality:topology"]["status"], "FAIL")
        self.assertIn("build-blender", gates["quality:topology"]["detail"])
        self.assertEqual(gates["quality:visualAppearanceReview"]["status"], "PASS")
        evidence = {item["label"]: item for item in record["evidence"]}
        self.assertEqual(evidence["human review"]["status"], "PASS")
        self.assertEqual(evidence["tampered evidence"]["status"], "HASH_MISMATCH")
        self.assertEqual(evidence["topology:geometry-audit:neutral"]["status"], "PASS")
        self.assertEqual(evidence["QualitySpec release projection"]["status"], "FAIL")

    def test_html_is_read_only_keyboard_operable_and_has_unique_landmarks(self) -> None:
        MODULE.build(self.root, self.output)
        document = (self.output / "index.html").read_text(encoding="utf-8")

        self.assertEqual(document.count('id="product-list"'), 1)
        self.assertEqual(document.count('id="product-buttons"'), 1)
        self.assertEqual(document.count('id="product-detail"'), 1)
        for marker in (
            "READ ONLY · RELEASE EVIDENCE",
            "未解決blocker",
            "必須ビュー・ポーズ",
            "release gate",
            "QualitySpec release projection",
            "window.REVIEW_CONSOLE_DATA",
            "new URLSearchParams(location.search)",
            "history.replaceState",
            "ArrowLeft",
            "ArrowRight",
            "Escape",
            "min-height:44px",
            "prefers-reduced-motion",
            "読み取り専用",
        ):
            self.assertIn(marker, document)
        for forbidden in (
            "subprocess.run",
            "os.system(",
            "task release",
            "task candidate",
        ):
            self.assertNotIn(forbidden, document)

    def test_falls_back_to_latest_rejected_render_without_changing_product_state(self) -> None:
        product = self.root / "Assets" / "GenWorks" / "demo-outfit"
        for path in (product / "Previews").rglob("*"):
            if path.is_file():
                path.unlink()
        rejected = product / "Evidence" / "Rejected" / "run-2" / "Previews"
        rejected.mkdir(parents=True)
        (rejected / "front.webp").write_bytes(b"rejected-front")
        (rejected / "back.webp").write_bytes(b"rejected-back")
        manifest = json.loads((product / "ProductManifest.json").read_text(encoding="utf-8"))
        manifest["technicalGates"] = {"visualAppearanceReview": "FAIL"}
        (product / "ProductManifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        data = MODULE.build(self.root, self.output)
        record = data["products"][0]
        self.assertEqual(record["state"], "WORKING")
        assets = {(item["kind"], item["name"]): item for item in record["assets"]}
        self.assertEqual(assets[("view", "front")]["status"], "PASS")
        self.assertTrue(assets[("view", "front")]["href"].endswith("front.webp"))
        gates = {gate["name"]: gate for gate in record["gates"]}
        self.assertEqual(gates["visualAppearanceReview"]["status"], "FAIL")

    def test_empty_repository_still_generates_valid_console(self) -> None:
        empty_root = Path(self.temp.name) / "empty"
        (empty_root / "config").mkdir(parents=True)
        (empty_root / "config" / "release-policy.json").write_text(
            "{}", encoding="utf-8"
        )
        output = empty_root / ".image2outfit" / "review-console"
        data = MODULE.build(empty_root, output)
        self.assertEqual(data["products"], [])
        self.assertTrue((output / "index.html").is_file())
        self.assertTrue((output / "review-console.json").is_file())


if __name__ == "__main__":
    unittest.main()
