from __future__ import annotations

import json
import sys
import unittest
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.arrangement import ArrangementPlan
from image2outfit.decomposition import GarmentDecomposition
from image2outfit.normalization import NormalizedReferenceSet
from image2outfit.pattern_stage import PatternHypothesisSet
from image2outfit.reference import ReferenceSet
from image2outfit.seam_stage import SeamHypothesisSet


class PreBlenderStageSchemaTests(unittest.TestCase):
    def test_required_root_fields_match_python_dataclasses(self) -> None:
        schema = json.loads(
            (ROOT / "config/schema/pre-blender-stages.schema.v1.json").read_text(
                encoding="utf-8"
            )
        )
        classes = {
            "ReferenceSet": ReferenceSet,
            "NormalizedReferenceSet": NormalizedReferenceSet,
            "GarmentDecomposition": GarmentDecomposition,
            "PatternHypothesisSet": PatternHypothesisSet,
            "SeamHypothesisSet": SeamHypothesisSet,
            "ArrangementPlan": ArrangementPlan,
        }
        for name, cls in classes.items():
            with self.subTest(name=name):
                self.assertEqual(
                    {item.name for item in fields(cls)},
                    set(schema["$defs"][name]["required"]),
                )
                self.assertFalse(schema["$defs"][name]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
