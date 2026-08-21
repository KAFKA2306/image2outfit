from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TOOLS))

import dagu_fixture_preflight as fixture_preflight  # noqa: E402
import run_garment_pipeline as pipeline_runner  # noqa: E402
import run_product_execution as execution  # noqa: E402
from image2outfit.pipeline import PIPELINE_STAGES  # noqa: E402


class ProductExecutionSchedulerTests(unittest.TestCase):
    def test_dagu_schedules_one_canonical_pipeline_instead_of_redefining_stages(
        self,
    ) -> None:
        workflow = (ROOT / "ops/dagu/product-execution.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("queue: product-execution", workflow)
        self.assertIn("tools/run_product_execution.py", workflow)
        self.assertEqual(workflow.count("  - id:"), 1)
        for stage in PIPELINE_STAGES:
            with self.subTest(stage=stage.value):
                self.assertNotIn(f"id: {stage.value}", workflow)
        for forbidden in (
            "ProductManifest",
            "COMPLETE",
            "customer_quality",
            "release_gate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, workflow)

    def test_product_queue_is_explicitly_serialized_in_example_config(self) -> None:
        config = (ROOT / "ops/dagu/config.example.yaml").read_text(encoding="utf-8")
        self.assertIn("name: product-execution", config)
        self.assertIn("max_concurrency: 1", config)

    def test_wrapper_derives_checkpoint_from_existing_runtime_layout(self) -> None:
        product_id, request, checkpoint = execution.execution_paths(
            Path("config/pipeline/requests/siroino-blue-happi.json")
        )
        self.assertEqual(product_id, "siroino-blue-happi")
        self.assertEqual(
            request.relative_to(ROOT).as_posix(),
            "config/pipeline/requests/siroino-blue-happi.json",
        )
        self.assertEqual(
            checkpoint.relative_to(ROOT).as_posix(),
            ".image2outfit/products/siroino-blue-happi/reports/pipeline-state.json",
        )

    def test_wrapper_delegates_execution_and_only_adds_resume_for_existing_checkpoint(
        self,
    ) -> None:
        request = ROOT / "config/pipeline/requests/siroino-blue-happi.json"
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "pipeline-state.json"
            fresh = execution.build_pipeline_command(request, checkpoint)
            self.assertIn(str(execution.PIPELINE_RUNNER), fresh)
            self.assertIn("--execute", fresh)
            self.assertIn("--checkpoint-output", fresh)
            self.assertNotIn("--resume-state", fresh)

            checkpoint.write_text("{}", encoding="utf-8")
            resumed = execution.build_pipeline_command(request, checkpoint)
            self.assertIn("--resume-state", resumed)
            self.assertEqual(resumed[-1], str(checkpoint))

    def test_terminal_resume_reuses_immutable_audit_only_for_matching_mode(
        self,
    ) -> None:
        audit = {"manifestPath": ".image2outfit/audit/example/manifest.json"}
        executed = {"status": "EXECUTED", "audit": audit}
        planned = {"status": "PLANNED", "audit": audit}
        failed = {"status": "FAILED", "audit": audit}

        self.assertEqual(
            pipeline_runner._terminal_audit(
                executed, pipeline_runner.ExecutionMode.EXECUTE
            ),
            audit,
        )
        self.assertEqual(
            pipeline_runner._terminal_audit(
                planned, pipeline_runner.ExecutionMode.PLAN
            ),
            audit,
        )
        self.assertIsNone(
            pipeline_runner._terminal_audit(
                executed, pipeline_runner.ExecutionMode.PLAN
            )
        )
        self.assertIsNone(
            pipeline_runner._terminal_audit(
                failed, pipeline_runner.ExecutionMode.EXECUTE
            )
        )

    def test_fixture_preflight_covers_exact_canonical_benchmark_set(self) -> None:
        fixture_config = json.loads(
            (ROOT / fixture_preflight.FIXTURE_CONFIG).read_text(encoding="utf-8")
        )
        expected = {
            (fixture["fixtureId"], fixture["productId"])
            for fixture in fixture_config["fixtures"]
        }
        plan = fixture_preflight.build_preflight()
        actual = {(entry["fixtureId"], entry["productId"]) for entry in plan["entries"]}
        self.assertEqual(actual, expected)
        self.assertEqual(plan["queue"], "product-execution")
        self.assertFalse(plan["schedulerOwnsCompletion"])
        self.assertEqual(
            plan["readyCount"] + plan["blockedCount"],
            len(expected),
        )

    def test_fixture_preflight_never_queues_unbound_or_invented_requests(self) -> None:
        plan = fixture_preflight.build_preflight()
        candidates = {entry["productId"]: entry for entry in plan["queueCandidates"]}
        for entry in plan["entries"]:
            product_id = entry["productId"]
            request_path = entry["requestPath"]
            identity_path = entry["referenceIdentityPath"]
            if entry["status"] == "READY":
                self.assertIsNotNone(request_path)
                self.assertIsNotNone(identity_path)
                self.assertIn(product_id, candidates)
                self.assertEqual(candidates[product_id]["request"], request_path)
                self.assertTrue((ROOT / request_path).is_file())
                self.assertTrue((ROOT / identity_path).is_file())
            else:
                self.assertNotIn(product_id, candidates)
                if request_path is None:
                    self.assertIn("missing-canonical-request", entry["blockers"])
                if identity_path is None:
                    self.assertIn("missing-reference-identity", entry["blockers"])


if __name__ == "__main__":
    unittest.main()
