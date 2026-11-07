from __future__ import annotations

import itertools
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.styling import (  # noqa: E402
    ConstraintTargetKind,
    StylingOperationKind,
    StylingSpec,
)
from image2outfit.styling_registry import (  # noqa: E402
    FAMILIES,
    PRESETS,
    REGISTRY_VERSION,
    StylingRequest,
    compile_styling_requests,
    gather_allocation,
    registry_manifest,
    registry_sha256,
)


def request(operation_id: str, preset_id: str, **kwargs: object) -> StylingRequest:
    return StylingRequest(
        operation_id=operation_id,
        preset_id=preset_id,
        target_ids=tuple(kwargs.pop("targets", ("front-hem",))),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


class StylingRegistryTests(unittest.TestCase):
    def test_registry_covers_all_nine_operation_families(self) -> None:
        self.assertEqual(
            (
                "asymmetric-hem",
                "closure",
                "collar-fold",
                "gather",
                "layer-order",
                "neckline-offset",
                "shoulder-drape",
                "sleeve-roll",
                "tuck",
            ),
            FAMILIES,
        )

    def test_empty_request_set_is_the_reversible_base_state(self) -> None:
        base = compile_styling_requests(())
        self.assertEqual((), base.operations)

        spec = compile_styling_requests(
            (
                request("tuck-front", "front-tuck", anchor_target_ids=("waistband",)),
                request(
                    "sleeve-left",
                    "rolled-cuff",
                    targets=("left-cuff",),
                    side="left",
                ),
            )
        )
        self.assertEqual(base, spec.without("tuck-front", "sleeve-left"))

    def test_front_tuck_constrains_only_declared_targets(self) -> None:
        spec = compile_styling_requests(
            (
                request(
                    "tuck-front",
                    "front-tuck",
                    targets=("front-hem",),
                    anchor_target_ids=("waistband",),
                    parameters={"depth_mm": 40.0},
                ),
            )
        )
        (operation,) = spec.operations
        self.assertEqual(StylingOperationKind.TUCK, operation.kind)
        self.assertEqual(("front-hem",), operation.target_ids)
        self.assertEqual(("waistband",), operation.anchor_target_ids)
        self.assertEqual(40.0, operation.parameters["depth_mm"])
        self.assertEqual(120.0, operation.parameters["width_mm"])

    def test_side_tuck_keeps_the_declared_side_without_mirroring(self) -> None:
        spec = compile_styling_requests(
            (
                request(
                    "tuck-left",
                    "side-tuck",
                    targets=("left-hem",),
                    anchor_target_ids=("left-waistband",),
                    side="left",
                ),
            )
        )
        self.assertEqual(
            ("tuck-left",), tuple(op.operation_id for op in spec.operations)
        )
        self.assertEqual("left", spec.operations[0].parameters["side"])

    def test_sleeve_roll_asymmetry_is_preserved(self) -> None:
        spec = compile_styling_requests(
            (
                request(
                    "cuff-left",
                    "rolled-cuff",
                    targets=("left-cuff",),
                    side="left",
                    parameters={"turns": 3},
                ),
                request(
                    "cuff-right",
                    "rolled-cuff",
                    targets=("right-cuff",),
                    side="right",
                    parameters={"turns": 1, "width_mm": 60.0},
                ),
            )
        )
        turns = {op.operation_id: op.parameters["turns"] for op in spec.operations}
        self.assertEqual({"cuff-left": 3, "cuff-right": 1}, turns)
        self.assertIsInstance(turns["cuff-left"], int)

    def test_collar_fold_line_and_seam_must_be_distinct(self) -> None:
        with self.assertRaisesRegex(ValueError, "distinct"):
            compile_styling_requests(
                (
                    request(
                        "collar",
                        "popped-collar",
                        targets=("collar-edge",),
                        anchor_target_ids=("collar-edge",),
                    ),
                )
            )
        spec = compile_styling_requests(
            (
                request(
                    "collar",
                    "popped-collar",
                    targets=("collar-fold-line",),
                    anchor_target_ids=("collar-seam",),
                ),
            )
        )
        self.assertEqual(StylingOperationKind.FOLD, spec.operations[0].kind)

    def test_neckline_offset_rejects_whole_garment_targets(self) -> None:
        with self.assertRaisesRegex(ValueError, "neckline region"):
            compile_styling_requests(
                (
                    request(
                        "off-shoulder",
                        "off-shoulder-both",
                        targets=("whole-garment",),
                        anchor_target_ids=("shoulder-left", "shoulder-right"),
                        side="both",
                    ),
                )
            )
        with self.assertRaisesRegex(ValueError, "at least 1 anchor"):
            compile_styling_requests(
                (request("rear", "neckline-rear-offset", targets=("neckline",)),)
            )

    def test_closure_states_share_one_topology(self) -> None:
        topology = ("zip-tape-left", "zip-tape-right")
        states = {}
        for fraction in (0.0, 0.5, 1.0):
            spec = compile_styling_requests(
                (
                    request(
                        "front-closure",
                        "closure",
                        targets=topology,
                        parameters={"fastener": "zipper", "open_fraction": fraction},
                    ),
                )
            )
            operation = spec.operations[0]
            self.assertEqual(topology, operation.target_ids)
            states[fraction] = operation.parameters["open_state"]
        self.assertEqual(
            {0.0: "closed", 0.5: "partial", 1.0: "open"},
            states,
        )

    def test_closure_requires_a_topology_with_two_elements(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 2 target"):
            compile_styling_requests(
                (request("front-closure", "closure", targets=("zip-tape",)),)
            )

    def test_one_arm_drape_rejects_the_unworn_arm(self) -> None:
        with self.assertRaisesRegex(ValueError, "unworn arm"):
            compile_styling_requests(
                (
                    request(
                        "worn-arm",
                        "one-arm",
                        targets=("sleeve.left",),
                        anchor_target_ids=("shoulder.right",),
                        side="left",
                    ),
                )
            )
        spec = compile_styling_requests(
            (
                request(
                    "worn-arm",
                    "one-arm",
                    targets=("sleeve.left",),
                    anchor_target_ids=("shoulder.left",),
                    side="left",
                ),
            )
        )
        self.assertEqual(("sleeve.left",), spec.operations[0].target_ids)

    def test_both_arms_drape_accepts_both_arms(self) -> None:
        spec = compile_styling_requests(
            (
                request(
                    "both",
                    "both-arms",
                    targets=("sleeve.left", "sleeve.right"),
                    anchor_target_ids=("shoulder.left", "shoulder.right"),
                    side="both",
                ),
            )
        )
        self.assertEqual(1, len(spec.operations))
        self.assertEqual(StylingOperationKind.REGION_ANCHOR, spec.operations[0].kind)

    def test_gather_allocation_conserves_excess_for_each_distribution(self) -> None:
        for distribution in ("uniform", "front-weighted", "back-weighted"):
            with self.subTest(distribution=distribution):
                shares = gather_allocation(137.5, 5, distribution)
                self.assertEqual(5, len(shares))
                self.assertAlmostEqual(137.5, sum(shares), places=9)
                self.assertTrue(all(share > 0 for share in shares))
        front = gather_allocation(100.0, 4, "front-weighted")
        back = gather_allocation(100.0, 4, "back-weighted")
        self.assertEqual(tuple(sorted(front, reverse=True)), front)
        self.assertEqual(tuple(sorted(back)), back)

    def test_gather_compiles_with_segment_count_and_rejects_bad_input(self) -> None:
        spec = compile_styling_requests(
            (
                request(
                    "blouse",
                    "blouse-gather",
                    targets=("seg-1", "seg-2", "seg-3"),
                    parameters={"excess_mm": 240.0, "distribution": "back-weighted"},
                ),
            )
        )
        parameters = spec.operations[0].parameters
        self.assertEqual(3, parameters["segment_count"])
        self.assertEqual(240.0, parameters["excess_mm"])
        with self.assertRaisesRegex(ValueError, "at least 2 target"):
            compile_styling_requests(
                (request("blouse", "blouse-gather", targets=("seg-1",)),)
            )
        with self.assertRaisesRegex(ValueError, "must be positive"):
            gather_allocation(0.0, 3, "uniform")

    def test_asymmetric_hem_is_never_mirrored(self) -> None:
        spec = compile_styling_requests(
            (
                request(
                    "hem-left",
                    "asymmetric-hem",
                    targets=("left-hem",),
                    side="left",
                    parameters={"drop_mm": 90.0},
                ),
                request(
                    "hem-right",
                    "asymmetric-hem",
                    targets=("right-hem",),
                    side="right",
                    parameters={"drop_mm": 30.0},
                ),
            )
        )
        drops = {op.operation_id: op.parameters["drop_mm"] for op in spec.operations}
        self.assertEqual({"hem-left": 90.0, "hem-right": 30.0}, drops)
        with self.assertRaisesRegex(ValueError, "does not accept side"):
            compile_styling_requests(
                (request("hem", "asymmetric-hem", targets=("hem",), side="none"),)
            )

    def test_layer_order_is_independent_of_request_order(self) -> None:
        inner = request(
            "layer-0",
            "layer-order",
            targets=("base-top",),
            order=0,
            parameters={"layer_index": 0},
        )
        middle = request(
            "layer-1",
            "layer-order",
            targets=("cardigan",),
            order=1,
            depends_on=("layer-0",),
            parameters={"layer_index": 1},
        )
        outer = request(
            "layer-2",
            "layer-order",
            targets=("coat",),
            order=2,
            depends_on=("layer-1",),
            parameters={"layer_index": 2},
        )
        specs = [
            compile_styling_requests(permutation)
            for permutation in itertools.permutations((inner, middle, outer))
        ]
        self.assertTrue(all(item == specs[0] for item in specs))
        spec = specs[0]
        self.assertEqual(
            ("layer-0", "layer-1", "layer-2"),
            tuple(op.operation_id for op in spec.application_order()),
        )

    def test_layer_contact_must_go_inner_to_outer(self) -> None:
        with self.assertRaisesRegex(ValueError, "inner to outer"):
            compile_styling_requests(
                (
                    request(
                        "outer",
                        "layer-order",
                        targets=("coat",),
                        order=0,
                        parameters={"layer_index": 0},
                    ),
                    request(
                        "inner",
                        "layer-order",
                        targets=("base-top",),
                        order=0,
                        depends_on=("outer",),
                        parameters={"layer_index": 0},
                    ),
                )
            )
        with self.assertRaisesRegex(ValueError, "order must equal layer_index"):
            compile_styling_requests(
                (
                    request(
                        "layer",
                        "layer-order",
                        targets=("coat",),
                        order=3,
                        parameters={"layer_index": 1},
                    ),
                )
            )

    def test_conflicting_tucks_on_one_target_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflict"):
            compile_styling_requests(
                (
                    request("tuck-a", "front-tuck", anchor_target_ids=("waist",)),
                    request("tuck-b", "half-tuck", anchor_target_ids=("waist",)),
                )
            )

    def test_dependency_cycles_and_unknown_dependencies_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "cycle"):
            compile_styling_requests(
                (
                    request(
                        "a",
                        "cape-drape",
                        targets=("cape-a",),
                        anchor_target_ids=("shoulder",),
                        depends_on=("b",),
                    ),
                    request(
                        "b",
                        "cape-drape",
                        targets=("cape-b",),
                        anchor_target_ids=("shoulder",),
                        depends_on=("a",),
                    ),
                )
            )
        with self.assertRaisesRegex(ValueError, "unknown operations"):
            compile_styling_requests(
                (
                    request(
                        "a",
                        "shoulder-drape",
                        anchor_target_ids=("shoulder",),
                        depends_on=("missing",),
                    ),
                )
            )

    def test_invalid_requests_are_rejected(self) -> None:
        waist = ("waist",)
        cases = {
            "unknown preset": request("x", "no-such-preset"),
            "unknown parameter": request(
                "x", "front-tuck", anchor_target_ids=waist, parameters={"bogus": 1}
            ),
            "out of range": request(
                "x",
                "front-tuck",
                anchor_target_ids=waist,
                parameters={"depth_mm": 999.0},
            ),
            "non-integer count": request(
                "x", "rolled-cuff", side="left", parameters={"turns": 2.5}
            ),
            "boolean number": request(
                "x",
                "front-tuck",
                anchor_target_ids=waist,
                parameters={"depth_mm": True},
            ),
            "non-finite number": request(
                "x",
                "front-tuck",
                anchor_target_ids=waist,
                parameters={"depth_mm": float("nan")},
            ),
            "missing required anchor": request("x", "front-tuck"),
            "invalid choice": request(
                "x", "closure", targets=("a", "b"), parameters={"fastener": "tie"}
            ),
            "invalid side": request("x", "rolled-cuff", side="both"),
        }
        for label, bad in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    compile_styling_requests((bad,))

    def test_removing_one_operation_restores_the_remaining_state(self) -> None:
        kept = request("tuck-front", "front-tuck", anchor_target_ids=("waistband",))
        removed = request(
            "cuff-left", "rolled-cuff", targets=("left-cuff",), side="left"
        )
        full = compile_styling_requests((kept, removed))
        self.assertEqual(
            compile_styling_requests((kept,)),
            full.without("cuff-left"),
        )

    def test_compiled_spec_uses_registry_kinds_and_targets(self) -> None:
        spec = compile_styling_requests(
            (
                request(
                    "closure",
                    "closure",
                    targets=("tape-a", "tape-b"),
                    parameters={"open_fraction": 0.25},
                ),
            )
        )
        self.assertIsInstance(spec, StylingSpec)
        operation = spec.operations[0]
        self.assertEqual(ConstraintTargetKind.GARMENT_EDGE, operation.target_kind)
        self.assertEqual(StylingOperationKind.CLOSURE, operation.kind)
        self.assertEqual(REGISTRY_VERSION, operation.parameters["registry_version"])
        self.assertEqual("closure", operation.parameters["family"])

    def test_registry_manifest_is_machine_readable_and_stable(self) -> None:
        manifest = registry_manifest()
        self.assertEqual(REGISTRY_VERSION, manifest["registry_version"])
        presets = manifest["presets"]
        self.assertEqual(len(PRESETS), len(presets))
        self.assertEqual(
            sorted(PRESETS),
            [item["preset_id"] for item in presets],
        )
        encoded = json.dumps(manifest, sort_keys=True)
        self.assertEqual(manifest, json.loads(encoded))
        self.assertEqual(registry_sha256(), registry_sha256())
        self.assertEqual(64, len(registry_sha256()))


if __name__ == "__main__":
    unittest.main()
