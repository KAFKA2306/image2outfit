from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.research import DEFAULT_RESEARCH_PRINCIPLES
from image2outfit.specs import (
    BlenderInvocation,
    ClothSimulationSpec,
    RenderEvidenceSpec,
)


class ResearchAndSpecsTests(unittest.TestCase):
    def test_research_principles_use_primary_paper_urls(self) -> None:
        self.assertGreaterEqual(len(DEFAULT_RESEARCH_PRINCIPLES), 4)
        for principle in DEFAULT_RESEARCH_PRINCIPLES:
            self.assertTrue(principle.paper_url.startswith("https://arxiv.org/abs/"))
            self.assertIn("copied", principle.boundary)

    def test_blender_invocation_is_deterministic(self) -> None:
        invocation = BlenderInvocation(
            executable="blender",
            python_script="tools/example.py",
            script_arguments=("--product", "example-garment"),
        )
        invocation.validate()
        self.assertEqual(
            invocation.argv(),
            (
                "blender",
                "--background",
                "--python",
                "tools/example.py",
                "--",
                "--product",
                "example-garment",
            ),
        )

    def test_cloth_and_render_contracts_validate(self) -> None:
        ClothSimulationSpec().validate()
        RenderEvidenceSpec(poses=("a-pose", "crouch")).validate()
