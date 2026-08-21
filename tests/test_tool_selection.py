from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.pipeline import PIPELINE_STAGES, PipelineStage
from image2outfit.tooling import ToolDescriptor, choose_tool
from pipeline_stage_adapters import build_registry, load_profile


class ToolSelectionTests(unittest.TestCase):
    def test_priority_resolves_compatible_tie_deterministically(self) -> None:
        selection = choose_tool(
            "draft-patterns",
            [
                ToolDescriptor(
                    "pattern.second",
                    "second",
                    "out.json",
                    capabilities=frozenset({"pattern"}),
                    priority=20,
                ),
                ToolDescriptor(
                    "pattern.first",
                    "first",
                    "out.json",
                    capabilities=frozenset({"pattern"}),
                    priority=10,
                ),
            ],
            required_capabilities=["pattern"],
        )
        self.assertEqual(selection.descriptor.tool_name, "pattern.first")
        self.assertFalse(selection.pinned)

    def test_pin_is_still_rejected_when_contract_is_incompatible(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing capabilities"):
            choose_tool(
                "draft-patterns",
                [
                    ToolDescriptor(
                        "pattern.closed",
                        "closed",
                        "out.json",
                        capabilities=frozenset({"pattern.closed"}),
                    )
                ],
                required_capabilities=["pattern.explicit"],
                pin="pattern.closed",
            )


class ModularProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(
            ROOT / "config/pipeline-profiles/garment-reconstruction-modular-v1.json"
        )
        self.request = json.loads(
            (ROOT / "config/pipeline/requests/siroino-white-ghost-gown.json").read_text(
                encoding="utf-8"
            )
        )

    def test_ghost_gown_resolves_required_panel_sewn_toolchain(self) -> None:
        registry = build_registry(
            self.profile,
            bindings=self.request["stageBindings"],
            variables={"productId": self.request["productId"]},
            tool_requirements=self.request["toolRequirements"],
            tool_pins=self.request["toolPins"],
        )
        self.assertEqual(registry.missing(PIPELINE_STAGES), ())
        self.assertEqual(
            registry.descriptor(PipelineStage.DRAFT_PATTERNS).tool_name,
            "pattern.explicit-2d",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.INFER_STITCHES).tool_name,
            "stitch.explicit-graph",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.BUILD_BLENDER).tool_name,
            "build.blender.pattern-sewn",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.SIMULATE_CLOTH).tool_name,
            "simulate.blender.sewing-springs",
        )
        plan = registry.selection_plan()
        self.assertEqual(len(plan), len(PIPELINE_STAGES))
        self.assertTrue(
            next(item for item in plan if item["stage"] == "draft-patterns")["pinned"]
        )

    def test_closed_component_alternative_can_be_selected_without_code_changes(self) -> None:
        registry = build_registry(
            self.profile,
            bindings=self.request["stageBindings"],
            variables={"productId": "alternative-test"},
            tool_requirements={
                "draft-patterns": ["pattern.closed-components"],
                "infer-stitches": ["stitch.closed-components"],
                "build-blender": ["garment.closed-components"],
                "simulate-cloth": ["simulate.bounded-clearance"],
            },
            tool_pins={
                "draft-patterns": "pattern.closed-components",
                "infer-stitches": "stitch.closed-components",
                "build-blender": "build.blender.closed-components",
                "simulate-cloth": "simulate.closed-components-clearance",
            },
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.DRAFT_PATTERNS).tool_name,
            "pattern.closed-components",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.SIMULATE_CLOTH).tool_name,
            "simulate.closed-components-clearance",
        )

    def test_incompatible_cross_family_pin_fails_before_execution(self) -> None:
        pins = dict(self.request["toolPins"])
        pins["build-blender"] = "build.blender.closed-components"
        with self.assertRaisesRegex(ValueError, "missing prerequisites"):
            build_registry(
                self.profile,
                bindings=self.request["stageBindings"],
                variables={"productId": self.request["productId"]},
                tool_requirements=self.request["toolRequirements"],
                tool_pins=pins,
            )


if __name__ == "__main__":
    unittest.main()
