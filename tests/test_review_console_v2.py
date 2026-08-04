from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "review_console.py"
SPEC = importlib.util.spec_from_file_location("review_console_v2", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
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
        (product / "Logs" / "runtime.txt").write_text("missing screenshot", encoding="utf-8")
        expected_review_hash = MODULE.digest(product / "Evidence" / "review.json")
        (product / "ProductManifest.json").write_text(
            json.dumps(
                {
                    "state": "HUMAN_REVIEW_PENDING",
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
        self.assertEqual(record["state"], "HUMAN_REVIEW_PENDING")
        self.assertEqual(record["blocker_count"], 1)
        self.assertEqual(record["blockers"][0]["severity"], "MAJOR")
        self.assertEqual(record["resume_point"], "human review")
        self.assertEqual(record["candidate_hash"], "candidate-abc")
        self.assertEqual(
            [asset["status"] for asset in record["assets"]],
            ["PASS", "MISSING", "MISSING"],
        )
        self.assertIsNotNone(record["assets"][0]["sha256"])
        self.assertEqual([gate["status"] for gate in record["gates"]], ["PASS", "FAIL"])
        self.assertTrue(record["gates"][1]["href"].endswith("Logs/runtime.txt"))
        self.assertEqual(record["evidence"][0]["status"], "PASS")
        self.assertEqual(record["evidence"][1]["status"], "HASH_MISMATCH")

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

    def test_empty_repository_still_generates_valid_console(self) -> None:
        empty_root = Path(self.temp.name) / "empty"
        (empty_root / "config").mkdir(parents=True)
        (empty_root / "config" / "release-policy.json").write_text("{}", encoding="utf-8")
        output = empty_root / ".image2outfit" / "review-console"
        data = MODULE.build(empty_root, output)
        self.assertEqual(data["products"], [])
        self.assertTrue((output / "index.html").is_file())
        self.assertTrue((output / "review-console.json").is_file())


if __name__ == "__main__":
    unittest.main()
