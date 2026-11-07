from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.pipeline import PipelineStage
from pipeline_stage_adapters import build_registry, load_profile


class TripoPipelineBindingTests(unittest.TestCase):
    def test_existing_pipeline_command_path_can_bind_real_tripo_adapter(self) -> None:
        profile = load_profile(
            ROOT / "config/pipeline-profiles/garment-reconstruction-modular-v1.json"
        )
        registry = build_registry(
            profile,
            bindings={
                "initialize.external-hypothesis": {
                    "command": [
                        "python",
                        "tools/tripo_hypothesis_adapter.py",
                        "--request",
                        "{tripoRequest}",
                        "--result",
                        "{tripoResult}",
                    ],
                    "resultPath": "{tripoResult}",
                }
            },
            variables={
                "tripoRequest": ".image2outfit/products/demo/tripo-request.json",
                "tripoResult": ".image2outfit/products/demo/tripo-stage-result.json",
            },
            tool_requirements={
                "initialize-3d": ["initialize.multi-hypothesis", "generator.tripo"],
                "build-blender": ["build.reconcile-hypothesis"],
            },
            tool_pins={
                "initialize-3d": "initialize.external-hypothesis",
                "build-blender": "build.blender.reconcile-hypothesis",
            },
        )
        planned = registry.invoke(
            PipelineStage.INITIALIZE_3D,
            {"product_id": "demo"},
        )
        self.assertTrue(planned["bound"])
        self.assertEqual(planned["toolName"], "initialize.external-hypothesis")
        self.assertEqual(
            planned["command"],
            [
                "python",
                "tools/tripo_hypothesis_adapter.py",
                "--request",
                ".image2outfit/products/demo/tripo-request.json",
                "--result",
                ".image2outfit/products/demo/tripo-stage-result.json",
            ],
        )
        self.assertEqual(
            planned["resultPath"],
            ".image2outfit/products/demo/tripo-stage-result.json",
        )


if __name__ == "__main__":
    unittest.main()
