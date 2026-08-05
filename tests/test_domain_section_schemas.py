from __future__ import annotations

import json
import sys
import unittest
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.avatar import AvatarSpec
from image2outfit.construction import ConstructionSpec
from image2outfit.fit import FitSpec
from image2outfit.material import MaterialSpec
from image2outfit.styling import StylingSpec


class DomainSectionSchemaTests(unittest.TestCase):
    def test_required_root_fields_match_python_dataclasses(self) -> None:
        schema = json.loads(
            (ROOT / "config/schema/domain-sections.schema.v1.json").read_text(
                encoding="utf-8"
            )
        )
        classes = {
            "AvatarSpec": AvatarSpec,
            "ConstructionSpec": ConstructionSpec,
            "FitSpec": FitSpec,
            "MaterialSpec": MaterialSpec,
            "StylingSpec": StylingSpec,
        }
        for name, cls in classes.items():
            with self.subTest(name=name):
                self.assertEqual(
                    {item.name for item in fields(cls)},
                    set(schema["$defs"][name]["required"]),
                )
                self.assertFalse(
                    schema["$defs"][name]["additionalProperties"]
                )


if __name__ == "__main__":
    unittest.main()
