from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import product_flow_model as flow  # noqa: E402

LILAC = "siroino-lilac-lame-fencing-practice-set"


class ProductFlowModelTest(unittest.TestCase):
    def test_every_product_flow_model_is_current_and_consistent(self) -> None:
        errors = [
            error
            for product_id in flow._product_ids()
            for error in flow.check_product(product_id)
        ]
        self.assertEqual([], errors)

    def test_lilac_main_flow_is_a_star_over_stages_with_stitch_triples(self) -> None:
        model = flow.build_model(LILAC)
        stage_ids = [row["id"] for row in model["dimensions"]["stage"]]
        self.assertEqual([stage.value for stage in flow.PIPELINE_STAGES], stage_ids)
        self.assertEqual(f"product:{LILAC}", model["mainFlow"]["hub"])
        self.assertEqual(len(stage_ids), len(model["facts"]["stageRun"]))
        self.assertEqual(61, len(model["facts"]["stitch"]))
        self.assertEqual(2, len(model["facts"]["overlayAttachment"]))
        predicates = {triple["predicate"] for triple in model["triples"]}
        self.assertEqual({"precedes", "stitchedTo", "attachedTo"}, predicates)
        self.assertEqual([], flow.validate_model(model))

    def test_every_triple_is_traceable_to_evidence(self) -> None:
        for product_id in flow._product_ids():
            model = flow.build_model(product_id)
            for triple in model["triples"]:
                self.assertTrue(triple["evidence"], (product_id, triple))

    def test_product_without_stitch_graph_still_has_stage_star(self) -> None:
        model = flow.build_model("siroino-wide-cargo")
        self.assertEqual([], model["facts"]["stitch"])
        self.assertEqual(
            len(flow.PIPELINE_STAGES) - 1,
            sum(1 for triple in model["triples"] if triple["predicate"] == "precedes"),
        )


if __name__ == "__main__":
    unittest.main()
