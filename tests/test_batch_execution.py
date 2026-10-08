from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TOOLS))

from image2outfit.batch import BatchManifest, summarize  # noqa: E402
import batch_execution  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class BatchContractTests(unittest.TestCase):
    def test_manifest_requires_serial_execution_and_canonical_requests(self) -> None:
        manifest = BatchManifest.from_mapping(
            {
                "schemaVersion": 1,
                "batchId": "fixture",
                "requests": [
                    "config/pipeline/requests/a.json",
                    "config/pipeline/requests/b.json",
                ],
                "maxConcurrency": 1,
                "continueOnError": True,
                "resumePolicy": "canonical-checkpoint",
                "terminalCachePolicy": "reuse-executed",
            }
        )
        self.assertEqual(manifest.max_concurrency, 1)
        self.assertEqual(len(manifest.requests), 2)

        with self.assertRaisesRegex(ValueError, "maxConcurrency"):
            BatchManifest.from_mapping(
                {
                    "schemaVersion": 1,
                    "batchId": "fixture",
                    "requests": ["config/pipeline/requests/a.json"],
                    "maxConcurrency": 2,
                    "continueOnError": True,
                    "resumePolicy": "canonical-checkpoint",
                    "terminalCachePolicy": "reuse-executed",
                }
            )

        with self.assertRaisesRegex(ValueError, "config/pipeline/requests"):
            BatchManifest.from_mapping(
                {
                    "schemaVersion": 1,
                    "batchId": "fixture",
                    "requests": ["tmp/a.json"],
                    "maxConcurrency": 1,
                    "continueOnError": True,
                    "resumePolicy": "canonical-checkpoint",
                    "terminalCachePolicy": "reuse-executed",
                }
            )

    def test_summary_never_claims_product_completion(self) -> None:
        manifest = BatchManifest(
            batch_id="fixture",
            requests=("config/pipeline/requests/a.json",),
            max_concurrency=1,
            continue_on_error=True,
        )
        report = summarize(
            manifest,
            [
                {
                    "request": "config/pipeline/requests/a.json",
                    "productId": "a",
                    "schedulerState": "REVIEW_REQUIRED",
                    "currentStage": "visual-review",
                    "cachedTerminal": False,
                    "returnCode": 0,
                }
            ],
        )
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertFalse(report["schedulerOwnsCompletion"])
        self.assertFalse(report["productCompletionClaimed"])
        self.assertFalse(report["releaseEligibilityEvaluated"])

    def test_status_reads_existing_product_execution_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = "config/pipeline/requests/a.json"
            write_json(
                root / request,
                {"schemaVersion": 1, "productId": "product-a"},
            )
            write_json(
                root
                / ".image2outfit/products/product-a/reports/product-execution-state.json",
                {
                    "productId": "product-a",
                    "schedulerState": "FAILED",
                    "currentStage": "build-blender",
                    "cachedTerminal": False,
                },
            )

            item = batch_execution.read_request_state(root, request)

            self.assertEqual(item["productId"], "product-a")
            self.assertEqual(item["schedulerState"], "FAILED")
            self.assertEqual(item["currentStage"], "build-blender")

    def test_run_continues_after_failure_and_observes_every_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            requests = [
                "config/pipeline/requests/a.json",
                "config/pipeline/requests/b.json",
            ]
            for name, product_id in zip(requests, ("product-a", "product-b"), strict=True):
                write_json(
                    root / name,
                    {"schemaVersion": 1, "productId": product_id},
                )
            manifest_path = root / "config/batch/fixture.json"
            write_json(
                manifest_path,
                {
                    "schemaVersion": 1,
                    "batchId": "fixture",
                    "requests": requests,
                    "maxConcurrency": 1,
                    "continueOnError": True,
                    "resumePolicy": "canonical-checkpoint",
                    "terminalCachePolicy": "reuse-executed",
                },
            )

            calls: list[str] = []

            def fake_run(command, **_kwargs):
                request_path = Path(command[-1])
                request = json.loads(request_path.read_text(encoding="utf-8"))
                product_id = request["productId"]
                calls.append(product_id)
                state = "FAILED" if product_id == "product-a" else "SUCCEEDED"
                write_json(
                    root
                    / f".image2outfit/products/{product_id}/reports/"
                    "product-execution-state.json",
                    {
                        "productId": product_id,
                        "schedulerState": state,
                        "currentStage": (
                            "build-blender" if state == "FAILED" else "finalize-candidate"
                        ),
                        "cachedTerminal": False,
                    },
                )

                class Result:
                    returncode = 1 if state == "FAILED" else 0

                return Result()

            with patch("batch_execution.subprocess.run", side_effect=fake_run):
                report, return_code = batch_execution.run_batch(
                    root,
                    manifest_path.relative_to(root),
                    execute=True,
                )

            self.assertEqual(calls, ["product-a", "product-b"])
            self.assertEqual(report["status"], "FAILED")
            self.assertEqual(return_code, 1)
            self.assertEqual(
                [item["schedulerState"] for item in report["items"]],
                ["FAILED", "SUCCEEDED"],
            )

    def test_missing_request_is_blocked_without_stopping_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "config/batch/fixture.json"
            write_json(
                manifest_path,
                {
                    "schemaVersion": 1,
                    "batchId": "fixture",
                    "requests": ["config/pipeline/requests/missing.json"],
                    "maxConcurrency": 1,
                    "continueOnError": True,
                    "resumePolicy": "canonical-checkpoint",
                    "terminalCachePolicy": "reuse-executed",
                },
            )

            report, return_code = batch_execution.run_batch(
                root,
                manifest_path.relative_to(root),
                execute=False,
            )

            self.assertEqual(report["status"], "FAILED")
            self.assertEqual(report["items"][0]["schedulerState"], "BLOCKED")
            self.assertEqual(return_code, 1)


if __name__ == "__main__":
    unittest.main()
