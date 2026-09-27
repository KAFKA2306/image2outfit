from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import production_contract  # noqa: E402
from product_completion import project_product_completion  # noqa: E402

REVIEW_SPEC = importlib.util.spec_from_file_location(
    "review_console_completion_test", TOOLS / "review_console.py"
)
assert REVIEW_SPEC is not None and REVIEW_SPEC.loader is not None
REVIEW = importlib.util.module_from_spec(REVIEW_SPEC)
sys.modules[REVIEW_SPEC.name] = REVIEW
REVIEW_SPEC.loader.exec_module(REVIEW)


POLICY = {
    "schemaVersion": 2,
    "statuses": ["WORKING", "COMPLETE", "REJECTED"],
    "completionStatus": "COMPLETE",
    "requiredCompletionGates": [
        "blender",
        "fiveViewEvidence",
        "poseEvidence",
        "visualAppearanceReview",
    ],
    "outOfScopeGates": [
        "unityImport",
        "modularAvatar",
        "vrchatBuildTest",
        "humanRuntimeReview",
    ],
    "rules": {"fitAuditFailureBlocksCompletion": False},
}


def manifest(*, state: str = "WORKING", visual: str = "FAIL") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "productId": "demo",
        "productRoot": "Assets/GenWorks/demo",
        "state": state,
        "completionGates": {
            "blender": "PASS",
            "fiveViewEvidence": "PASS",
            "poseEvidence": "PASS",
            "visualAppearanceReview": visual,
        },
        "technicalGates": {
            "unityImport": "PENDING",
            "modularAvatar": "PENDING",
            "vrchatBuildAndTest": "PENDING",
            "humanRuntimeReview": "PENDING",
        },
    }


class ProductCompletionProjectionTest(unittest.TestCase):
    def test_tracked_failure_and_runtime_pending_are_separate(self) -> None:
        projection = project_product_completion(manifest(), POLICY)
        self.assertEqual(projection["state"], "WORKING")
        self.assertEqual(
            [(row["name"], row["status"]) for row in projection["completionGates"]],
            [
                ("blender", "PASS"),
                ("fiveViewEvidence", "PASS"),
                ("poseEvidence", "PASS"),
                ("visualAppearanceReview", "FAIL"),
            ],
        )
        self.assertEqual(len(projection["completionBlockers"]), 1)
        self.assertEqual(
            projection["completionBlockers"][0]["gate"], "visualAppearanceReview"
        )
        runtime = {row["name"]: row["status"] for row in projection["runtimeGates"]}
        self.assertEqual(runtime["unityImport"], "PENDING")
        self.assertEqual(runtime["modularAvatar"], "PENDING")
        self.assertEqual(runtime["vrchatBuildAndTest"], "PENDING")
        self.assertEqual(runtime["humanRuntimeReview"], "PENDING")
        self.assertEqual(projection["errors"], [])

    def test_complete_allows_runtime_pending_but_not_missing_required_gate(
        self,
    ) -> None:
        complete = manifest(state="COMPLETE", visual="PASS")
        projection = project_product_completion(complete, POLICY)
        self.assertEqual(projection["completionBlockers"], [])
        self.assertEqual(projection["errors"], [])

        missing = manifest()
        del missing["completionGates"]["poseEvidence"]  # type: ignore[index]
        projection = project_product_completion(missing, POLICY)
        blocker = {
            row["gate"]: row["status"] for row in projection["completionBlockers"]
        }
        self.assertEqual(blocker["poseEvidence"], "MISSING")

    def test_out_of_scope_fail_is_not_a_completion_blocker(self) -> None:
        value = manifest(state="COMPLETE", visual="PASS")
        value["technicalGates"]["unityImport"] = "FAIL"  # type: ignore[index]
        projection = project_product_completion(value, POLICY)
        self.assertEqual(projection["completionBlockers"], [])
        self.assertEqual(projection["errors"], [])

    def test_unknown_or_contradictory_state_and_gate_fail_visibly(self) -> None:
        unknown = manifest()
        unknown["state"] = "READYISH"
        projection = project_product_completion(unknown, POLICY)
        self.assertEqual(projection["state"], "INVALID")
        self.assertTrue(
            any(
                "unknown product lifecycle state" in error
                for error in projection["errors"]
            )
        )

        contradictory = manifest()
        contradictory["status"] = "COMPLETE"
        projection = project_product_completion(contradictory, POLICY)
        self.assertEqual(projection["state"], "INVALID")
        self.assertIn(
            "product lifecycle fields contradict each other", projection["errors"]
        )

        unknown_gate = manifest()
        unknown_gate["completionGates"]["visualAppearanceReview"] = "MAYBE"  # type: ignore[index]
        projection = project_product_completion(unknown_gate, POLICY)
        self.assertTrue(
            any("unknown status" in error for error in projection["errors"])
        )

    def test_review_console_and_production_validation_share_policy_semantics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir(parents=True)
            (root / "config" / "genworks-handoff-policy.json").write_text(
                json.dumps(POLICY), encoding="utf-8"
            )
            (root / "config" / "release-policy.json").write_text(
                json.dumps({"required_views": [], "required_poses": []}),
                encoding="utf-8",
            )
            product = root / "Assets" / "GenWorks" / "demo"
            product.mkdir(parents=True)
            product_manifest = manifest()
            (product / "ProductManifest.json").write_text(
                json.dumps(product_manifest), encoding="utf-8"
            )

            data = REVIEW.build(root, root / ".image2outfit" / "review-console")
            record = data["products"][0]
            self.assertEqual(record["state"], "WORKING")
            self.assertEqual(record["blocker_count"], 1)
            self.assertEqual(
                record["blockers"][0]["message"],
                "completion gate is not PASS: visualAppearanceReview (FAIL)",
            )
            self.assertEqual(
                {row["name"]: row["status"] for row in record["completion_gates"]}[
                    "visualAppearanceReview"
                ],
                "FAIL",
            )
            runtime = {row["name"]: row["status"] for row in record["runtime_gates"]}
            self.assertEqual(runtime["unityImport"], "PENDING")
            self.assertEqual(runtime["vrchatBuildAndTest"], "PENDING")
            self.assertFalse(
                any(row["name"] == "unityImport" for row in record["gates"])
            )

            errors = production_contract.product_state_errors(
                {
                    "id": "demo",
                    "productRoot": "Assets/GenWorks/demo",
                    "productManifestPath": "Assets/GenWorks/demo/ProductManifest.json",
                },
                root,
            )
            self.assertEqual(errors, [])

            product_manifest["state"] = "COMPLETE"
            (product / "ProductManifest.json").write_text(
                json.dumps(product_manifest), encoding="utf-8"
            )
            errors = production_contract.product_state_errors(
                {
                    "id": "demo",
                    "productRoot": "Assets/GenWorks/demo",
                    "productManifestPath": "Assets/GenWorks/demo/ProductManifest.json",
                },
                root,
            )
            self.assertIn(
                "complete product gate is not PASS: visualAppearanceReview", errors
            )

    def test_current_siroino_wide_cargo_keeps_visual_failure_visible(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "genworks-handoff-policy.json").read_text(
                encoding="utf-8"
            )
        )
        value = json.loads(
            (
                ROOT
                / "Assets"
                / "GenWorks"
                / "siroino-wide-cargo"
                / "ProductManifest.json"
            ).read_text(encoding="utf-8")
        )
        projection = project_product_completion(value, policy)
        self.assertEqual(projection["state"], "WORKING")
        blockers = {
            row["gate"]: row["status"] for row in projection["completionBlockers"]
        }
        self.assertEqual(blockers["visualAppearanceReview"], "FAIL")
        runtime = {row["name"]: row["status"] for row in projection["runtimeGates"]}
        self.assertEqual(runtime["unityImport"], "PENDING")
        self.assertEqual(runtime["modularAvatar"], "PENDING")
        self.assertEqual(runtime["vrchatBuildAndTest"], "PENDING")


if __name__ == "__main__":
    unittest.main()
