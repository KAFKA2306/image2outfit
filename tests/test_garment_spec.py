from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.garment_spec import (
    EvidenceRef,
    GarmentSpec,
    ProvenanceSpec,
    SpecSection,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def section(name: str, suffix: str) -> SpecSection:
    return SpecSection(
        section_id=name,
        schema_version=1,
        artifact_path=f"config/products/example/{name}.json",
        content_sha256=HASH_B,
        hypothesis_id="base-hypothesis",
        confidence=0.8,
        evidence=(
            EvidenceRef(
                path=f"evidence/{name}-{suffix}.json",
                sha256=HASH_C,
                role="stage-result",
            ),
        ),
    )


def fixture() -> GarmentSpec:
    return GarmentSpec(
        garment_id="example-garment",
        hypothesis_id="base-hypothesis",
        avatar=section("avatar", "avatar"),
        construction=section("construction", "construction"),
        fit=section("fit", "fit"),
        materials=section("materials", "materials"),
        styling=section("styling", "styling"),
        quality=section("quality", "quality"),
        provenance=ProvenanceSpec(
            source_reference="reference://example",
            source_sha256=HASH_A,
            producer="image2outfit",
        ),
        extensions={"image2outfit.example": {"enabled": True}},
    )


class GarmentSpecTests(unittest.TestCase):
    def test_round_trip_is_lossless_and_deterministic(self) -> None:
        original = fixture()
        encoded = original.to_json()
        restored = GarmentSpec.from_json(encoded)
        self.assertEqual(restored, original)
        self.assertEqual(restored.to_json(), encoded)

    def test_section_hypothesis_cannot_drift(self) -> None:
        invalid = replace(section("avatar", "avatar"), hypothesis_id="other-hypothesis")
        with self.assertRaisesRegex(ValueError, "another hypothesis"):
            replace(fixture(), avatar=invalid)

    def test_unknown_root_fields_are_rejected(self) -> None:
        payload = fixture().to_dict()
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            GarmentSpec.from_dict(payload)

    def test_extensions_require_namespace(self) -> None:
        values = fixture().to_dict()
        values["extensions"] = {"bad": True}
        with self.assertRaisesRegex(ValueError, "namespaced"):
            GarmentSpec.from_dict(values)

    def test_schema_declares_same_required_root_fields(self) -> None:
        schema = json.loads(
            (ROOT / "config/schema/garment-spec.schema.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(schema["required"]), set(fixture().to_dict()))


if __name__ == "__main__":
    unittest.main()
