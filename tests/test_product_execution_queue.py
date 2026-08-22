from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TOOLS))

import bind_private_reference as private_reference  # noqa: E402
import dagu_fixture_preflight as fixture_preflight  # noqa: E402
import run_product_execution as execution  # noqa: E402
from image2outfit.identity import IdentityStatus  # noqa: E402
from image2outfit.pipeline import PIPELINE_STAGES  # noqa: E402


class ProductExecutionQueueTests(unittest.TestCase):
    def test_dagu_only_schedules_one_canonical_pipeline_call(self) -> None:
        workflow = (ROOT / "ops/dagu/product-execution.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("queue: product-execution", workflow)
        self.assertIn("tools/run_product_execution.py", workflow)
        self.assertEqual(workflow.count("  - id:"), 1)
        for stage in PIPELINE_STAGES:
            with self.subTest(stage=stage.value):
                self.assertNotIn(f"id: {stage.value}", workflow)
        for forbidden in ("ProductManifest", "COMPLETE", "release_gate"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, workflow)

    def test_product_queue_is_serialized(self) -> None:
        config = (ROOT / "ops/dagu/config.example.yaml").read_text(encoding="utf-8")
        self.assertIn("name: product-execution", config)
        self.assertIn("max_concurrency: 1", config)

    def test_preflight_covers_three_fixtures_and_only_emits_ready_candidates(self) -> None:
        plan = fixture_preflight.build_preflight()
        fixture_config = json.loads(
            (ROOT / fixture_preflight.FIXTURE_CONFIG).read_text(encoding="utf-8")
        )
        expected = {
            (fixture["fixtureId"], fixture["productId"])
            for fixture in fixture_config["fixtures"]
        }
        actual = {
            (entry["fixtureId"], entry["productId"]) for entry in plan["entries"]
        }
        self.assertEqual(actual, expected)
        self.assertEqual(plan["schemaVersion"], 2)
        self.assertFalse(plan["schedulerOwnsCompletion"])
        candidates = {entry["productId"] for entry in plan["queueCandidates"]}
        for entry in plan["entries"]:
            with self.subTest(product=entry["productId"]):
                self.assertEqual(entry["status"] == "READY", not entry["blockers"])
                self.assertEqual(entry["productId"] in candidates, not entry["blockers"])

    def test_tuxedo_is_ready_but_unbound_private_fixtures_remain_blocked(self) -> None:
        entries = {
            entry["productId"]: entry
            for entry in fixture_preflight.build_preflight()["entries"]
        }
        self.assertEqual(entries["siroino-tuxedo-halter-dress-large"]["status"], "READY")
        for product_id in (
            "siroino-heather-hooded-bodysuit",
            "siroino-cyber-kawaii-large",
        ):
            with self.subTest(product=product_id):
                self.assertEqual(entries[product_id]["status"], "BLOCKED")
                self.assertIn("missing-canonical-request", entries[product_id]["blockers"])
                self.assertIn("missing-reference-identity", entries[product_id]["blockers"])

    def test_request_preflight_rejects_missing_canonical_stage_binding(self) -> None:
        product_id = "siroino-tuxedo-halter-dress-large"
        job = json.loads(
            (ROOT / f"config/products/{product_id}/job.json").read_text(encoding="utf-8")
        )
        request = json.loads(
            (ROOT / f"config/pipeline/requests/{product_id}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(fixture_preflight.request_contract_blockers(job, request), [])
        mutated = dict(request)
        mutated["stageBindings"] = dict(request["stageBindings"])
        mutated["stageBindings"].pop("build-blender")
        self.assertIn(
            "missing-stage-binding:build-blender",
            fixture_preflight.request_contract_blockers(job, mutated),
        )

    def test_visual_review_pause_is_scheduler_review_required_not_success(self) -> None:
        checkpoint = {
            "status": "FAILED",
            "current_stage": "visual-review",
            "errors": [
                "visual-review: FileNotFoundError: "
                "direct visual review is not recorded yet"
            ],
        }
        self.assertEqual(execution.classify_checkpoint(checkpoint), "REVIEW_REQUIRED")
        self.assertEqual(execution.classify_checkpoint({"status": "EXECUTED"}), "SUCCEEDED")
        self.assertEqual(
            execution.classify_checkpoint(
                {"status": "FAILED", "current_stage": "build-blender", "errors": []}
            ),
            "FAILED",
        )

    def test_execution_state_never_claims_product_completion_or_release(self) -> None:
        payload = execution.execution_state_payload(
            product_id="product-a",
            request_path=ROOT / "config/pipeline/requests/product-a.json",
            checkpoint_path=(
                ROOT / ".image2outfit/products/product-a/reports/pipeline-state.json"
            ),
            checkpoint={
                "status": "EXECUTED",
                "current_stage": "finalize-candidate",
                "completed_stages": [stage.value for stage in PIPELINE_STAGES],
            },
            scheduler_state="SUCCEEDED",
            cached_terminal=False,
        )
        self.assertFalse(payload["schedulerOwnsCompletion"])
        self.assertFalse(payload["productCompletionClaimed"])
        self.assertFalse(payload["releaseEligibilityEvaluated"])

    def test_matching_terminal_checkpoint_can_be_reused_without_new_audit(self) -> None:
        request = {
            "productId": "product-a",
            "targetAvatar": "Avatar",
            "sourceReference": "private-reference://sha256/" + "a" * 64,
            "revisionId": "r1",
        }
        checkpoint = {
            "schema_version": 1,
            "product_id": "product-a",
            "target_avatar": "Avatar",
            "source_reference": request["sourceReference"],
            "revision_id": "r1",
            "source_fingerprint": "b" * 64,
            "execution_mode": "execute",
            "status": "EXECUTED",
        }
        self.assertTrue(
            execution.checkpoint_matches_request(checkpoint, request, "b" * 64)
        )
        checkpoint["source_fingerprint"] = "c" * 64
        self.assertFalse(
            execution.checkpoint_matches_request(checkpoint, request, "b" * 64)
        )

    def test_private_reference_manifest_requires_real_content_address(self) -> None:
        source_reference = "private-reference://sha256/" + "d" * 64
        manifest = private_reference.build_manifest(
            product_id="fixture-product",
            source_reference=source_reference,
            recorded_at="2026-08-22T06:00:00+00:00",
        )
        self.assertEqual(manifest.source_reference, source_reference)
        self.assertEqual(len(manifest.claims), 12)
        self.assertTrue(
            all(claim.status is IdentityStatus.UNVERIFIED for claim in manifest.claims)
        )
        self.assertEqual(manifest.verified_market_identifiers, {})
        self.assertEqual(len(manifest.history), 12)
        serialized = json.dumps(manifest.to_mapping())
        self.assertNotIn("/home/", serialized)
        self.assertNotIn("Assets/_Local", serialized)


if __name__ == "__main__":
    unittest.main()
