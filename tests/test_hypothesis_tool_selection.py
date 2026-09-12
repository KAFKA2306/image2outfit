from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.pipeline import PipelineStage
from pipeline_stage_adapters import build_registry, load_profile


class HypothesisToolSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(
            ROOT / "config/pipeline-profiles/garment-reconstruction-modular-v1.json"
        )

    def test_default_path_remains_pattern_first(self) -> None:
        registry = build_registry(self.profile)
        self.assertEqual(
            registry.descriptor(PipelineStage.INITIALIZE_3D).tool_name,
            "initialize.pattern-around-avatar",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.BUILD_BLENDER).tool_name,
            "build.blender.pattern-sewn",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.RENDER_EVIDENCE).tool_name,
            "render.bpy-review",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.AUDIT_GEOMETRY).tool_name,
            "verify.geometry-fit",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.VISUAL_REVIEW).tool_name,
            "review.direct-image-inspection",
        )

    def test_external_hypothesis_path_requires_explicit_capabilities_and_pins(
        self,
    ) -> None:
        registry = build_registry(
            self.profile,
            tool_requirements={
                "initialize-3d": ["initialize.multi-hypothesis", "generator.tripo"],
                "build-blender": ["build.reconcile-hypothesis"],
                "render-evidence": ["render.ai-reinput"],
                "audit-geometry": ["verify.blueprint-actual"],
                "visual-review": ["review.blueprint-bound"],
            },
            tool_pins={
                "initialize-3d": "initialize.external-hypothesis",
                "build-blender": "build.blender.reconcile-hypothesis",
                "render-evidence": "render.bpy-review-with-render-back",
                "audit-geometry": "verify.geometry-fit-blueprint",
                "visual-review": "review.blueprint-bound-direct-image-inspection",
            },
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.INITIALIZE_3D).tool_name,
            "initialize.external-hypothesis",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.BUILD_BLENDER).tool_name,
            "build.blender.reconcile-hypothesis",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.RENDER_EVIDENCE).tool_name,
            "render.bpy-review-with-render-back",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.AUDIT_GEOMETRY).tool_name,
            "verify.geometry-fit-blueprint",
        )
        self.assertEqual(
            registry.descriptor(PipelineStage.VISUAL_REVIEW).tool_name,
            "review.blueprint-bound-direct-image-inspection",
        )

    def test_external_initialize_fails_closed_without_execution_binding(self) -> None:
        registry = build_registry(
            self.profile,
            execute=True,
            tool_requirements={
                "initialize-3d": ["initialize.multi-hypothesis", "generator.tripo"],
                "build-blender": ["build.reconcile-hypothesis"],
            },
            tool_pins={
                "initialize-3d": "initialize.external-hypothesis",
                "build-blender": "build.blender.reconcile-hypothesis",
            },
        )
        with self.assertRaisesRegex(RuntimeError, "execution binding is incomplete"):
            registry.invoke(
                PipelineStage.INITIALIZE_3D,
                {"product_id": "garment"},
            )

    def test_external_tool_declares_fail_closed_result_fields(self) -> None:
        stage = next(
            item for item in self.profile["stages"] if item["stage"] == "initialize-3d"
        )
        external = next(
            tool
            for tool in stage["tools"]
            if tool["toolName"] == "initialize.external-hypothesis"
        )
        self.assertEqual(
            external["requiredResultFields"],
            {
                "hypothesisContractValidated": True,
                "blueprintBound": True,
                "targetAvatarAuthorityValidated": True,
                "externalDraftCanonicalSource": False,
                "silentFallbackUsed": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
