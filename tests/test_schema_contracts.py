from __future__ import annotations

import json
import sys
import unittest
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.arrangement import ArrangementPlan
from image2outfit.avatar import AvatarSpec
from image2outfit.construction import ConstructionSpec
from image2outfit.decomposition import GarmentDecomposition
from image2outfit.fit import FitSpec
from image2outfit.material import MaterialSpec
from image2outfit.normalization import NormalizedReferenceSet
from image2outfit.pattern_stage import PatternHypothesisSet
from image2outfit.reference import ReferenceSet
from image2outfit.seam_stage import SeamHypothesisSet
from image2outfit.styling import StylingSpec


def assert_schema_matches(
    case: unittest.TestCase,
    schema_path: Path,
    classes: dict[str, type],
) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for name, cls in classes.items():
        with case.subTest(name=name):
            case.assertEqual(
                {item.name for item in fields(cls)},
                set(schema["$defs"][name]["required"]),
            )
            case.assertFalse(schema["$defs"][name]["additionalProperties"])


class DomainSectionSchemaTests(unittest.TestCase):
    def test_required_root_fields_match_python_dataclasses(self) -> None:
        assert_schema_matches(
            self,
            ROOT / "config/schema/domain-sections.schema.v1.json",
            {
                "AvatarSpec": AvatarSpec,
                "ConstructionSpec": ConstructionSpec,
                "FitSpec": FitSpec,
                "MaterialSpec": MaterialSpec,
                "StylingSpec": StylingSpec,
            },
        )


class PreBlenderStageSchemaTests(unittest.TestCase):
    def test_required_root_fields_match_python_dataclasses(self) -> None:
        assert_schema_matches(
            self,
            ROOT / "config/schema/pre-blender-stages.schema.v1.json",
            {
                "ReferenceSet": ReferenceSet,
                "NormalizedReferenceSet": NormalizedReferenceSet,
                "GarmentDecomposition": GarmentDecomposition,
                "PatternHypothesisSet": PatternHypothesisSet,
                "SeamHypothesisSet": SeamHypothesisSet,
                "ArrangementPlan": ArrangementPlan,
            },
        )
