from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.hypothesis_tree import (
    compare_facet,
    plan_beam,
    validate_hypothesis_tree,
)


def _digest(seed: int) -> str:
    return f"{seed:064x}"


class HypothesisTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.product_id = "garment"
        self.blueprint_sha = "a" * 64
        self.seed = 0
        self.nodes: list[dict[str, object]] = [
            self._node("decomp", "decomposition", None, prior=0.9, confidence=0.8),
        ]
        for index, prior in enumerate((0.7, 0.5, 0.3), start=1):
            self.nodes.append(
                self._node(
                    f"pattern-{index}", "pattern", "decomp", prior=prior, confidence=0.6
                )
            )
        for index, prior in enumerate((0.6, 0.4, 0.2), start=1):
            self.nodes.append(
                self._node(
                    f"material-{index}",
                    "material",
                    "decomp",
                    prior=prior,
                    confidence=0.5,
                )
            )

    def _node(
        self,
        hypothesis_id: str,
        facet: str,
        parent_id: str | None,
        *,
        prior: float,
        confidence: float,
    ) -> dict[str, object]:
        self.seed += 1
        return {
            "hypothesisId": hypothesis_id,
            "facet": facet,
            "parentId": parent_id,
            "prior": prior,
            "confidence": confidence,
            "observationRefs": ["front-torso"],
            "unknownFields": ["back-closure"],
            "artifacts": {
                "pattern-set": _digest(self.seed * 2),
                "preview": _digest(self.seed * 2 + 1),
            },
        }

    def _tree(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "productId": self.product_id,
            "blueprintSha256": self.blueprint_sha,
            "nodes": self.nodes,
        }

    def _validated(self) -> list[dict[str, object]]:
        summary = validate_hypothesis_tree(
            self._tree(),
            expected_product_id=self.product_id,
            expected_blueprint_sha256=self.blueprint_sha,
        )
        return summary["nodes"]  # type: ignore[return-value]

    def test_tree_keeps_facets_parents_and_separate_artifact_hashes(self) -> None:
        summary = validate_hypothesis_tree(
            self._tree(),
            expected_product_id=self.product_id,
            expected_blueprint_sha256=self.blueprint_sha,
        )
        self.assertEqual(summary["nodeCount"], 7)
        self.assertEqual(summary["facetCounts"]["pattern"], 3)
        self.assertEqual(summary["facetCounts"]["material"], 3)
        self.assertEqual(summary["rootIds"], ["decomp"])
        self.assertFalse(summary["isEvidence"])

    def test_tree_rejects_artifact_hash_shared_across_hypotheses(self) -> None:
        self.nodes[2]["artifacts"] = {"pattern-set": _digest(2 * 1)}  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "shared by hypotheses"):
            validate_hypothesis_tree(self._tree(), expected_product_id=self.product_id)

    def test_tree_rejects_missing_parent_and_cycle(self) -> None:
        self.nodes[1]["parentId"] = "absent"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "missing parent"):
            validate_hypothesis_tree(self._tree(), expected_product_id=self.product_id)

        self.nodes = [
            self._node("a", "pattern", "b", prior=0.5, confidence=0.5),
            self._node("b", "pattern", "a", prior=0.5, confidence=0.5),
        ]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_hypothesis_tree(self._tree(), expected_product_id=self.product_id)

    def test_tree_rejects_out_of_range_prior(self) -> None:
        self.nodes[1]["prior"] = 1.5  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "prior"):
            validate_hypothesis_tree(self._tree(), expected_product_id=self.product_id)

    def test_beam_prunes_per_facet_and_cascades_to_children(self) -> None:
        nodes = self._validated()
        nodes_with_child = [
            *nodes,
            self._node(
                "pattern-1-seam", "seam", "pattern-3", prior=0.9, confidence=0.9
            ),
        ]
        plan = plan_beam(nodes_with_child, beam_width=2, max_combinations=100)  # type: ignore[arg-type]
        self.assertEqual(plan["beamWidth"], 2)
        self.assertNotIn("pattern-3", plan["kept"])
        self.assertIn("pattern-3", plan["pruned"])
        self.assertEqual(plan["pruned"]["pattern-1-seam"], "parent-pruned:pattern-3")
        self.assertIn("material-3", plan["pruned"])

    def test_beam_reduces_width_to_fit_combination_budget(self) -> None:
        nodes = self._validated()
        plan = plan_beam(nodes, beam_width=3, max_combinations=4)  # type: ignore[arg-type]
        self.assertEqual(plan["beamWidth"], 2)
        self.assertLessEqual(plan["combinationCount"], 4)
        self.assertEqual(plan["combinationCount"], 4)

    def test_tightest_budget_reduces_to_width_one_and_keeps_top_prior(self) -> None:
        nodes = self._validated()
        plan = plan_beam(nodes, beam_width=3, max_combinations=1)  # type: ignore[arg-type]
        self.assertEqual(plan["beamWidth"], 1)
        self.assertEqual(plan["combinationCount"], 1)
        self.assertIn("pattern-1", plan["kept"])
        self.assertIn("material-1", plan["kept"])
        self.assertNotIn("material-2", plan["kept"])

    def test_beam_rejects_non_positive_parameters(self) -> None:
        nodes = self._validated()
        with self.assertRaisesRegex(ValueError, "beam_width"):
            plan_beam(nodes, beam_width=0, max_combinations=4)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "max_combinations"):
            plan_beam(nodes, beam_width=2, max_combinations=True)  # type: ignore[arg-type]

    def test_compare_requires_three_comparable_candidates(self) -> None:
        nodes = [n for n in self._validated() if n["facet"] == "pattern"][:2]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "at least 3"):
            compare_facet(nodes, [], facet="pattern")  # type: ignore[arg-type]

    def test_selects_only_with_visual_review_pass_and_clear_margin(self) -> None:
        nodes = self._validated()
        evaluations = [
            {
                "hypothesisId": "pattern-1",
                "evidence": {
                    "visualReview": {"decision": "PASS"},
                    "fit": {"status": "PASS", "score": 0.6},
                },
            },
            {
                "hypothesisId": "pattern-2",
                "evidence": {
                    "visualReview": {"decision": "PASS"},
                    "fit": {"status": "PASS", "score": 0.8},
                },
            },
            {
                "hypothesisId": "pattern-3",
                "evidence": {"visualReview": {"decision": "REVISE"}},
            },
        ]
        result = compare_facet(nodes, evaluations, facet="pattern")  # type: ignore[arg-type]
        self.assertEqual(result["state"], "SELECTED")
        self.assertEqual(result["selectedHypothesisId"], "pattern-2")
        self.assertFalse(result["bestScoreReplacesVisualReview"])

    def test_highest_score_without_visual_pass_is_not_selected(self) -> None:
        nodes = self._validated()
        evaluations = [
            {
                "hypothesisId": "pattern-1",
                "evidence": {
                    "visualReview": {"decision": "REVISE"},
                    "fit": {"status": "PASS", "score": 0.99},
                },
            },
            {
                "hypothesisId": "pattern-2",
                "evidence": {
                    "visualReview": {"decision": "PASS"},
                    "fit": {"status": "PASS", "score": 0.4},
                },
            },
            {
                "hypothesisId": "pattern-3",
                "evidence": {
                    "visualReview": {"decision": "PASS"},
                    "fit": {"status": "PASS", "score": 0.2},
                },
            },
        ]
        result = compare_facet(nodes, evaluations, facet="pattern")  # type: ignore[arg-type]
        self.assertEqual(result["selectedHypothesisId"], "pattern-2")
        self.assertEqual(result["state"], "SELECTED")

    def test_without_any_visual_pass_state_stays_working(self) -> None:
        nodes = self._validated()
        evaluations = [
            {
                "hypothesisId": "material-1",
                "evidence": {"simulation": {"status": "PASS", "score": 0.9}},
            },
        ]
        result = compare_facet(nodes, evaluations, facet="material")  # type: ignore[arg-type]
        self.assertEqual(result["state"], "WORKING")
        self.assertIsNone(result["selectedHypothesisId"])
        self.assertEqual(result["candidates"][0]["status"], "UNVERIFIED")

    def test_failed_evidence_rejects_with_recorded_reason(self) -> None:
        nodes = self._validated()
        evaluations = [
            {
                "hypothesisId": "material-1",
                "evidence": {
                    "visualReview": {"decision": "PASS"},
                    "simulation": {"status": "FAIL"},
                },
            },
            {
                "hypothesisId": "material-2",
                "evidence": {
                    "visualReview": {"decision": "PASS"},
                    "render": {"status": "PASS", "score": 0.7},
                },
            },
        ]
        result = compare_facet(nodes, evaluations, facet="material")  # type: ignore[arg-type]
        self.assertEqual(result["rejectedReasons"], {"material-1": ["simulation:FAIL"]})
        self.assertEqual(result["selectedHypothesisId"], "material-2")

    def test_scores_within_margin_keep_state_working(self) -> None:
        nodes = self._validated()
        evaluations = [
            {
                "hypothesisId": "material-1",
                "evidence": {
                    "visualReview": {"decision": "PASS"},
                    "fit": {"status": "PASS", "score": 0.80},
                },
            },
            {
                "hypothesisId": "material-2",
                "evidence": {
                    "visualReview": {"decision": "PASS"},
                    "fit": {"status": "PASS", "score": 0.78},
                },
            },
        ]
        result = compare_facet(
            nodes, evaluations, facet="material", min_score_margin=0.05
        )  # type: ignore[arg-type]
        self.assertEqual(result["state"], "WORKING")
        self.assertIsNone(result["selectedHypothesisId"])
        self.assertEqual(result["unresolvedUnknownFields"], ["back-closure"])


if __name__ == "__main__":
    unittest.main()
