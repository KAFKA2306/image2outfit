from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.material import (  # noqa: E402
    AnisotropicFabricProperties,
    load_material_library,
)
from image2outfit.material_blender import (  # noqa: E402
    load_blender_calibration_profile,
    project_material_library_to_blender,
)


class BlenderMaterialProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library_path = (
            ROOT / "config" / "materials" / "kes-woven-fabrics-2025.v1.json"
        )
        self.profile_path = (
            ROOT / "config" / "materials" / "blender-4.4-kes-calibration.v1.json"
        )
        self.materials = load_material_library(self.library_path)
        self.profile = load_blender_calibration_profile(self.profile_path)
        self.projections = project_material_library_to_blender(
            self.materials, self.profile
        )

    def test_six_materials_have_deterministic_blender_mappings(self) -> None:
        first = project_material_library_to_blender(self.materials, self.profile)
        second = project_material_library_to_blender(self.materials, self.profile)
        self.assertEqual(6, len(first))
        self.assertEqual(
            [item.fingerprint() for item in first],
            [item.fingerprint() for item in second],
        )
        self.assertEqual(
            {item.material_id for item in self.materials},
            {item.material_id for item in first},
        )

    def test_anisotropy_is_preserved_and_scalar_loss_is_explicit(self) -> None:
        self.assertTrue(
            all(
                item.stretch_projection.anisotropy_ratio > 1
                for item in self.projections
            )
        )
        self.assertTrue(
            all(
                item.bending_projection.anisotropy_ratio >= 1
                for item in self.projections
            )
        )
        self.assertTrue(
            any(
                item.conversion_error["bendingScalarMaximumRelativeError"] > 0.25
                for item in self.projections
            )
        )
        self.assertTrue(
            all(
                "scalar" in " ".join(item.warnings).lower() for item in self.projections
            )
        )

    def test_through_thickness_compression_is_not_mapped_as_surface_compression(
        self,
    ) -> None:
        for material, projection in zip(self.materials, self.projections, strict=True):
            self.assertIsNone(material.properties.compression_kpa)
            self.assertIsNone(
                projection.unmapped_source_properties["throughThicknessCompressionKpa"]
            )
            expected = (
                projection.cloth_settings["tension_stiffness"]
                * self.profile.buckling_compression_ratio
            )
            self.assertAlmostEqual(
                expected, projection.cloth_settings["compression_stiffness"]
            )

    def test_missing_measured_friction_remains_a_low_confidence_hypothesis(
        self,
    ) -> None:
        for material, projection in zip(self.materials, self.projections, strict=True):
            self.assertIsNone(material.properties.static_friction)
            self.assertIsNone(material.properties.dynamic_friction)
            self.assertFalse(projection.contact_hypothesis.measured)
            self.assertLess(projection.contact_hypothesis.confidence, 0.5)
            self.assertEqual(
                projection.contact_hypothesis.dynamic_friction,
                projection.cloth_settings["collider_friction"],
            )
            self.assertEqual(
                projection.contact_hypothesis.static_friction * 100.0,
                projection.collider_settings["cloth_friction"],
            )
            self.assertLessEqual(projection.collider_settings["cloth_friction"], 80.0)

    def test_collision_and_render_thickness_remain_separate_fields(self) -> None:
        for material, projection in zip(self.materials, self.projections, strict=True):
            self.assertAlmostEqual(
                material.properties.collision_thickness_mm / 1000,
                projection.cloth_collision_settings["distance_min"],
            )
            self.assertAlmostEqual(
                material.properties.render_thickness_mm / 1000,
                projection.render_settings["solidify_thickness"],
            )
        changed = replace(
            self.materials[0].properties,
            collision_thickness_mm=0.4,
            render_thickness_mm=0.8,
        )
        material = replace(self.materials[0], properties=changed)
        projection = project_material_library_to_blender(
            (material, self.materials[1]), self.profile
        )[0]
        self.assertNotEqual(
            projection.cloth_collision_settings["distance_min"],
            projection.render_settings["solidify_thickness"],
        )

    def test_vertex_mass_uses_area_density_and_mesh_discretization(self) -> None:
        projection = self.projections[0]
        expected = projection.surface_density_kg_m2 * 2.25 / 625
        self.assertAlmostEqual(expected, projection.vertex_mass_kg(2.25, 625))
        with self.assertRaises(ValueError):
            projection.vertex_mass_kg(0, 625)
        with self.assertRaises(ValueError):
            projection.vertex_mass_kg(2.25, 0)

    def test_unit_and_contact_errors_are_rejected(self) -> None:
        properties = self.materials[0].properties
        with self.assertRaisesRegex(ValueError, "positive"):
            AnisotropicFabricProperties(
                areal_mass_g_m2=properties.areal_mass_g_m2,
                physical_thickness_mm=-properties.physical_thickness_mm,
                collision_thickness_mm=properties.collision_thickness_mm,
                render_thickness_mm=properties.render_thickness_mm,
                stretch_warp_g_s2=properties.stretch_warp_g_s2,
                stretch_weft_g_s2=properties.stretch_weft_g_s2,
                shear_g_s2=properties.shear_g_s2,
                bending_warp_g_mm2_s2=properties.bending_warp_g_mm2_s2,
                bending_weft_g_mm2_s2=properties.bending_weft_g_mm2_s2,
            )
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        payload["contactHypothesis"]["dynamicFriction"] = 0.8
        invalid_path = ROOT / ".image2outfit-test-invalid-profile.json"
        try:
            invalid_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "dynamic"):
                load_blender_calibration_profile(invalid_path)
        finally:
            invalid_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
