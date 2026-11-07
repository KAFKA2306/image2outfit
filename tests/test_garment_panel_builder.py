from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import garment_panel_builder as builder_module  # noqa: E402
import siroino_wide_cargo_panel_layout as layout  # noqa: E402
from garment_panel_builder import (  # noqa: E402
    CentreInner,
    FanPanel,
    MeshBuilder,
    PanelBuildError,
    SewnGarmentBuilder,
    SewnSection,
    SideInner,
)

PRODUCT_SOURCE = ROOT / "tools" / "siroino_wide_cargo_product.py"
PATTERN_SOURCE = layout.PATTERN_SPEC_PATH

# Digest (coordinates rounded to 1e-6) of the Wide Cargo panel mesh produced by
# origin/main's product script before the generic builder extraction. The
# extraction must not change output.
EXPECTED_VERTEX_COUNT = 1745
EXPECTED_FACE_COUNT = 1680
EXPECTED_MESH_SHA256 = (
    "83e56c540548a82d9dc1bf8166a8914ae0836b07ecffbe36eb3f0020d5b7acb5"
)


def _mesh_digest(mesh: MeshBuilder) -> str:
    # Coordinates are rounded to micrometres: sin/cos last-bit differences
    # between platform math libraries must not change the digest.
    payload = {
        "vertexCount": len(mesh.vertices),
        "faceCount": len(mesh.faces),
        "vertices": [
            [round(float(value), 6) for value in vertex] for vertex in mesh.vertices
        ],
        "faces": [list(face) for face in mesh.faces],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _load_document() -> dict[str, object]:
    return json.loads(PATTERN_SOURCE.read_text(encoding="utf-8-sig"))


class WideCargoPanelLayoutTests(unittest.TestCase):
    def test_pattern_layout_reproduces_reviewed_mesh(self) -> None:
        mesh = layout.build_wide_cargo_mesh()
        self.assertEqual(len(mesh.vertices), EXPECTED_VERTEX_COUNT)
        self.assertEqual(len(mesh.faces), EXPECTED_FACE_COUNT)
        self.assertEqual(_mesh_digest(mesh), EXPECTED_MESH_SHA256)

    def test_single_pattern_dimension_change_propagates_to_geometry(self) -> None:
        document = _load_document()
        baseline = layout.parse_pattern_baseline(document)
        original = layout.build_wide_cargo_mesh(baseline)

        changed_document = copy.deepcopy(document)
        rows = changed_document["baselineGeometry"]["upperRows"]
        waist_z, waist_half_width = rows[-1]
        rows[-1] = [waist_z, waist_half_width + 0.01]
        changed = layout.build_wide_cargo_mesh(
            layout.parse_pattern_baseline(changed_document)
        )

        self.assertEqual(len(changed.vertices), len(original.vertices))
        self.assertEqual(len(changed.faces), len(original.faces))
        self.assertNotEqual(_mesh_digest(changed), _mesh_digest(original))

        def max_abs_x_at(mesh: MeshBuilder, z: float) -> float:
            xs = [
                abs(vertex[0]) for vertex in mesh.vertices if abs(vertex[2] - z) <= 1e-9
            ]
            self.assertTrue(xs, f"no vertices at z={z}")
            return max(xs)

        self.assertAlmostEqual(
            max_abs_x_at(changed, waist_z) - max_abs_x_at(original, waist_z),
            0.01,
            places=9,
        )

    def test_wrong_product_id_is_rejected(self) -> None:
        document = _load_document()
        document["productId"] = "other-product"
        with self.assertRaisesRegex(ValueError, "wrong productId"):
            layout.parse_pattern_baseline(document)

    def test_unknown_seam_reference_is_rejected(self) -> None:
        document = _load_document()
        document["seamPairs"][0][0] = "front-left:no-such-boundary"
        with self.assertRaisesRegex(ValueError, "unknown boundary"):
            layout.parse_pattern_baseline(document)

    def test_sewn_and_open_boundary_overlap_is_rejected(self) -> None:
        document = _load_document()
        document["openBoundaries"].append(document["seamPairs"][0][0])
        with self.assertRaises(ValueError):
            layout.parse_pattern_baseline(document)

    def test_product_script_owns_no_panel_topology(self) -> None:
        source = PRODUCT_SOURCE.read_text(encoding="utf-8")
        for forbidden in (
            "def _panel_curve",
            "def add_side_pocket_panel",
            "def _bridge_chains",
            "faces.append",
            "_add_vertex(",
        ):
            self.assertNotIn(forbidden, source)


class SewnGarmentBuilderTests(unittest.TestCase):
    PROFILE = ((0.0, 0.05), (1.0, 0.05))

    def _builder(self, samples: int = 3) -> tuple[MeshBuilder, SewnGarmentBuilder]:
        mesh = MeshBuilder()
        return mesh, SewnGarmentBuilder(
            mesh,
            front_depth=self.PROFILE,
            rear_depth=self.PROFILE,
            samples=samples,
        )

    def test_side_sections_bridge_into_quads(self) -> None:
        mesh, builder = self._builder(samples=3)
        builder.add_section(SewnSection(z=0.0, outer_x=0.2, inner=SideInner(0.1)))
        builder.add_section(SewnSection(z=0.5, outer_x=0.2, inner=SideInner(0.1)))
        builder.bridge_panels()
        # Four panels, each with one bridged span of samples - 1 = 2 quads.
        self.assertEqual(len(mesh.faces), 8)
        self.assertTrue(all(len(face) == 4 for face in mesh.faces))

    def test_centre_inner_on_axis_shares_one_vertex(self) -> None:
        mesh, builder = self._builder()
        builder.add_section(
            SewnSection(z=0.3, outer_x=0.2, inner=CentreInner(front_y=0.0, back_y=0.0))
        )
        axis_vertices = [v for v in mesh.vertices if v[0] == 0.0 and v[1] == 0.0]
        self.assertEqual(len(axis_vertices), 1)

    def test_centre_inner_off_axis_keeps_front_and_back_apart(self) -> None:
        mesh, builder = self._builder()
        builder.add_section(
            SewnSection(
                z=0.3, outer_x=0.2, inner=CentreInner(front_y=-0.05, back_y=0.04)
            )
        )
        centre_vertices = [v for v in mesh.vertices if v[0] == 0.0]
        self.assertEqual(len(centre_vertices), 2)

    def test_sections_must_increase_in_z(self) -> None:
        _, builder = self._builder()
        builder.add_section(SewnSection(z=0.5, outer_x=0.2, inner=SideInner(0.1)))
        with self.assertRaises(PanelBuildError):
            builder.add_section(SewnSection(z=0.5, outer_x=0.2, inner=SideInner(0.1)))

    def test_fan_panel_triangulates_closed_outline(self) -> None:
        mesh, builder = self._builder()
        panel = FanPanel(
            x_base=0.18,
            y_half=0.03,
            z_min=0.4,
            z_max=0.5,
            corner_radius=0.01,
        )
        builder.add_fan_panel(panel, side=1.0)
        self.assertEqual(len(mesh.faces), 8)
        self.assertTrue(all(len(face) == 3 for face in mesh.faces))

    def test_fan_panel_rejects_invalid_side_and_outline(self) -> None:
        _, builder = self._builder()
        panel = FanPanel(
            x_base=0.18, y_half=0.03, z_min=0.4, z_max=0.5, corner_radius=0.01
        )
        with self.assertRaises(PanelBuildError):
            builder.add_fan_panel(panel, side=0.5)
        degenerate = FanPanel(
            x_base=0.18, y_half=0.03, z_min=0.5, z_max=0.4, corner_radius=0.01
        )
        with self.assertRaises(PanelBuildError):
            builder.add_fan_panel(degenerate, side=1.0)

    def test_builder_module_has_no_blender_dependency(self) -> None:
        source = Path(builder_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import bpy", source)
        self.assertNotIn("mathutils", source)


if __name__ == "__main__":
    unittest.main()
