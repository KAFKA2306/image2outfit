from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit import improvement
from review_console_with_improvement import collect_product_with_improvement


class ImprovementReviewProjectionTests(unittest.TestCase):
    def test_existing_review_console_receives_improvement_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            product = "example"
            workspace = root / "Assets" / "GenWorks" / product
            workspace.mkdir(parents=True)
            (workspace / "ProductManifest.json").write_text(
                json.dumps({"status": "WORKING"}),
                encoding="utf-8",
            )
            plan = {
                "schemaVersion": 1,
                "productId": product,
                "candidateHash": "a" * 64,
                "status": "ACTIONABLE",
                "missingCapability": "structured-patterns",
                "selectedMethod": {"candidateId": "pattern-tool"},
                "nextAction": "IMPLEMENT_EXPERIMENT_BINDING",
                "createdAt": "2026-08-20T00:00:00Z",
            }
            plan["planDigest"] = improvement.digest_value(plan)
            improvement.persist_plan(root, product, plan)
            output = root / ".image2outfit" / "review-console"
            output.mkdir(parents=True)

            projected = collect_product_with_improvement(
                root,
                workspace,
                output,
                ["front"],
                [],
            )

            self.assertEqual(
                projected.resume_point,
                "IMPLEMENT_EXPERIMENT_BINDING",
            )
            self.assertTrue(
                any(
                    row["severity"] == "IMPROVEMENT"
                    for row in projected.blockers
                )
            )
            self.assertTrue(
                any(
                    gate.name == "improvement:next-action"
                    for gate in projected.gates
                )
            )
            self.assertTrue(
                any(
                    evidence.label == "Improvement plan"
                    for evidence in projected.evidence
                )
            )


if __name__ == "__main__":
    unittest.main()
