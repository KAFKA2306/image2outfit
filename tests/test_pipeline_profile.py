from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.pipeline import PIPELINE_STAGES
from pipeline_stage_adapters import build_registry, load_profile


class PipelineProfileTests(unittest.TestCase):
    def test_default_profile_matches_canonical_pipeline(self) -> None:
        profile = load_profile(
            ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json"
        )
        registry = build_registry(profile)
        self.assertEqual(registry.missing(PIPELINE_STAGES), ())
