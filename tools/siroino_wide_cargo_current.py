#!/usr/bin/env python3
"""Fully procedural, source-face-free Siroino wide cargo trousers.

All garment geometry is generated in one mesh and only skin weights are sampled
from the target body. This prevents malformed source polygons from reappearing
as hem-to-waist spikes while preserving a fitted seat, straight-wide legs,
continuous inner-thigh coverage, waistband, knee panels, and cargo pockets.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v23 as v23

build = v23.build
base = v23.base


class MeshBuilder:
    def __init__(self) -> None:
        self.vertices: list[tuple[float, float, float]] = []
        self.faces: list[tuple[int, ...]] = []

    def add_ring(self, points: list[tuple[float, float, float]]) -> list[int]:
        start = len(self.vertices)
        self.vertices.extend(points)
        return list(range(start, start + len(points)))

    def bridge(self, lower: list[int], upper: list[int]) -> None:
        if len(lower) != len(upper):
            raise ValueError("ring sizes differ")
        count = len(lower)
        for index in range(count):
            nxt = (index + 1) % count
            self.faces.append((lower[index], lower[nxt], upper[nxt], upper[index]))

    def add_box(
        self,
        minimum: tuple[float, float, float],
        maximum: tuple[float, float, float],
    ) -> None:
        x0, y0, z0 = minimum
        x1, y1, z1 = maximum
        start = len(self.vertices)
        self.vertices.extend(
            [
                (x0, y0, z0),
                (x1, y0, z0),
                (x1, y1, z0),
                (x0, y1, z0),
                (x0, y0, z1),
                (x1, y0, z1),
                (x1, y1, z1),
                (x0, y1, z1),
            ]
        )
        self.faces.extend(
            [
                (start + 0, start + 3, start + 2, start + 1),
                (start + 4, start + 5, start + 6, start + 7),
                (start + 0, start + 1, start + 5, start + 4),
                (start + 1, start + 2, start + 6, start + 5),
                (start + 2, start + 3, start + 7, start + 6),
                (start + 3, start + 0, start + 4, start + 7),
            ]
        )


def asymmetric_ellipse_ring(
    *,
    center_x: float,
    inner_radius: float,
    outer_radius: float,
    front_depth: float,
    rear_depth: float,
    z: float,
    side: float,
    segments: int,
) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for index in range(segments):
        angle = 2.0 * math.pi * index / segments
        cosine = math.cos(angle)
        sine = math.sin(angle)
        radius_x = outer_radius if side * cosine >= 0.0 else inner_radius
        radius_y = rear_depth if sine >= 0.0 else front_depth
        points.append((side * center_x + cosine * radius_x, sine * radius_y, z))
    return points


def pelvis_ring(
    *,
    half_width: float,
    front_depth: float,
    rear_depth: float,
    z: float,
    segments: int,
) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for index in range(segments):
        angle = 2.0 * math.pi * index / segments
        sine = math.sin(angle)
        depth = rear_depth if sine >= 0.0 else front_depth
        points.append((math.cos(angle) * half_width, sine * depth, z))
    return points


def build_geometry(segments: int = 48) -> MeshBuilder:
    mesh = MeshBuilder()

    # Fitted waist and seat. The lower ring overlaps the upper leg rings, so no
    # horizontal skin gap exists even though components remain topologically
    # independent within one exported mesh object.
    pelvis_specs = [
        (0.555, 0.160, 0.100, 0.110),
        (0.625, 0.158, 0.098, 0.110),
        (0.715, 0.151, 0.094, 0.106),
        (0.805, 0.138, 0.088, 0.097),
    ]
    pelvis_rings = [
        mesh.add_ring(
            pelvis_ring(
                half_width=width,
                front_depth=front,
                rear_depth=rear,
                z=z,
                segments=segments,
            )
        )
        for z, width, front, rear in pelvis_specs
    ]
    for lower, upper in zip(pelvis_rings, pelvis_rings[1:]):
        mesh.bridge(lower, upper)

    # Straight-wide legs with centre overlap at the upper thigh and a controlled
    # 20–24 mm gap below the crotch. Width changes only modestly to avoid the
    # oversized cylindrical silhouette rejected in v30.
    leg_specs = [
        (0.105, 0.071, 0.055, 0.086, 0.080, 0.084),
        (0.200, 0.072, 0.056, 0.087, 0.082, 0.086),
        (0.320, 0.073, 0.058, 0.088, 0.084, 0.088),
        (0.440, 0.074, 0.063, 0.089, 0.086, 0.090),
        (0.540, 0.075, 0.076, 0.089, 0.088, 0.093),
        (0.625, 0.075, 0.084, 0.087, 0.090, 0.097),
        (0.700, 0.075, 0.086, 0.084, 0.091, 0.098),
    ]
    for side in (-1.0, 1.0):
        rings = [
            mesh.add_ring(
                asymmetric_ellipse_ring(
                    center_x=center,
                    inner_radius=inner,
                    outer_radius=outer,
                    front_depth=front,
                    rear_depth=rear,
                    z=z,
                    side=side,
                    segments=segments,
                )
            )
            for z, center, inner, outer, front, rear in leg_specs
        ]
        for lower, upper in zip(rings, rings[1:]):
            mesh.bridge(lower, upper)

    # Low-profile cargo pockets on the outer thighs. They remain part of the
    # same mesh object and receive the same armature deformation.
    mesh.add_box((-0.172, -0.060, 0.475), (-0.151, 0.064, 0.605))
    mesh.add_box((0.151, -0.060, 0.475), (0.172, 0.064, 0.605))
    return mesh


def transfer_weights(
    body: bpy.types.Object,
    garment: bpy.types.Object,
) -> None:
    for group in body.vertex_groups:
        garment.vertex_groups.new(name=group.name)

    bpy.ops.object.select_all(action="DESELECT")
    garment.select_set(True)
    bpy.context.view_layer.objects.active = garment
    modifier = garment.modifiers.new(name="Body Weight Transfer", type="DATA_TRANSFER")
    modifier.object = body
    modifier.use_vert_data = True
    modifier.data_types_verts = {"VGROUP_WEIGHTS"}
    modifier.vert_mapping = "POLYINTERP_NEAREST"
    modifier.layers_vgroup_select_src = "ALL"
    modifier.layers_vgroup_select_dst = "NAME"
    modifier.mix_mode = "REPLACE"
    modifier.mix_factor = 1.0
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    unweighted = [vertex.index for vertex in garment.data.vertices if not vertex.groups]
    if unweighted:
        raise RuntimeError(
            f"Interpolated body weight transfer left {len(unweighted)} vertices unweighted"
        )


def create_uv(garment: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    garment.select_set(True)
    bpy.context.view_layer.objects.active = garment
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")


def assign_materials(
    garment: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
) -> None:
    base.tune_material(fabric, base=(0.020, 0.025, 0.036), roughness=0.78)
    base.tune_material(strap, base=(0.005, 0.007, 0.011), roughness=0.40)
    garment.data.materials.clear()
    garment.data.materials.append(fabric)
    garment.data.materials.append(strap)
    for polygon in garment.data.polygons:
        center = Vector((0.0, 0.0, 0.0))
        for vertex_index in polygon.vertices:
            center += garment.data.vertices[vertex_index].co
        center /= len(polygon.vertices)
        waistband = center.z >= 0.758
        knee_panel = 0.365 <= center.z <= 0.415
        pocket = abs(center.x) >= 0.145 and 0.470 <= center.z <= 0.610
        polygon.material_index = 1 if waistband or knee_panel or pocket else 0
        polygon.use_smooth = not pocket
    garment.data.update()


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
    metal: bpy.types.Material,
):
    del metal
    geometry = build_geometry()
    mesh = bpy.data.meshes.new("Cargo_Continuous_Pants_Mesh")
    mesh.from_pydata(geometry.vertices, [], geometry.faces)
    mesh.update(calc_edges=True)
    garment = bpy.data.objects.new("Cargo_Continuous_Pants", mesh)
    bpy.context.collection.objects.link(garment)
    transfer_weights(body, garment)
    modifier = garment.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature
    create_uv(garment)
    assign_materials(garment, fabric, strap)
    return [garment]


def triangle_degenerates(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    total = 0
    for triangle in obj.data.loop_triangles:
        a, b, c = (obj.data.vertices[index].co for index in triangle.vertices)
        if (b - a).cross(c - a).length_squared <= 1e-20:
            total += 1
    return total


def band(obj: bpy.types.Object, z0: float, z1: float) -> dict[str, float]:
    points = [vertex.co for vertex in obj.data.vertices if z0 <= vertex.co.z <= z1]
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    return {
        "width": max(xs) - min(xs) if xs else 0.0,
        "depth": max(ys) - min(ys) if ys else 0.0,
        "rear": max(ys) if ys else 0.0,
    }


def audit() -> dict[str, object]:
    garment = bpy.data.objects.get("Cargo_Continuous_Pants")
    garment_names = sorted(
        obj.name
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith("SiroinoSotai_PC")
        and obj.name != "Studio_Floor"
    )
    if garment is None:
        return {
            "schemaVersion": 1,
            "passed": False,
            "checks": {"garmentMeshNames": garment_names},
        }

    garment.data.calc_loop_triangles()
    coordinates = [
        component for vertex in garment.data.vertices for component in vertex.co
    ]
    xs = [vertex.co.x for vertex in garment.data.vertices]
    ys = [vertex.co.y for vertex in garment.data.vertices]
    zs = [vertex.co.z for vertex in garment.data.vertices]
    maximum_edge = 0.0
    maximum_z_span = 0.0
    for edge in garment.data.edges:
        a = garment.data.vertices[edge.vertices[0]].co
        b = garment.data.vertices[edge.vertices[1]].co
        maximum_edge = max(maximum_edge, (a - b).length)
        maximum_z_span = max(maximum_z_span, abs(a.z - b.z))
    degenerates = triangle_degenerates(garment)
    seat = band(garment, 0.620, 0.750)
    thigh = band(garment, 0.500, 0.570)
    knee = band(garment, 0.300, 0.405)
    hem = band(garment, 0.105, 0.185)
    center_coverage = sum(
        1
        for vertex in garment.data.vertices
        if 0.535 <= vertex.co.z <= 0.705 and abs(vertex.co.x) <= 0.012
    )
    shape_keys = (
        0
        if garment.data.shape_keys is None
        else max(0, len(garment.data.shape_keys.key_blocks) - 1)
    )
    foot_intrusions = sum(
        1
        for vertex in garment.data.vertices
        if vertex.co.z < 0.10 or (vertex.co.z < 0.18 and abs(vertex.co.y) > 0.100)
    )
    unweighted = sum(1 for vertex in garment.data.vertices if not vertex.groups)
    total_width = max(xs) - min(xs)
    total_depth = max(ys) - min(ys)

    metrics = {
        "vertices": len(garment.data.vertices),
        "triangles": len(garment.data.loop_triangles),
        "minimumZ": min(zs),
        "maximumZ": max(zs),
        "totalWidth": total_width,
        "totalDepth": total_depth,
        "maximumEdgeLength": maximum_edge,
        "maximumEdgeZSpan": maximum_z_span,
        "degenerateTriangles": degenerates,
        "uvLayers": len(garment.data.uv_layers),
        "materialSlots": len(garment.data.materials),
        "shapeKeys": shape_keys,
        "footIntrusionVertices": foot_intrusions,
        "unweightedVertices": unweighted,
        "centerCoverageVertices": center_coverage,
        "bands": {"seat": seat, "thigh": thigh, "knee": knee, "hem": hem},
    }
    checks = {
        "garmentMeshNames": garment_names,
        "metrics": metrics,
        "singleMeshObjectPassed": garment_names == ["Cargo_Continuous_Pants"],
        "finiteCoordinatesPassed": all(
            math.isfinite(float(value)) for value in coordinates
        ),
        "topologyPassed": degenerates == 0,
        "sourceFaceIndependencePassed": min(zs) >= 0.10 and max(zs) <= 0.81,
        "spikeGuardPassed": maximum_edge <= 0.135 and maximum_z_span <= 0.105,
        "uvPassed": len(garment.data.uv_layers) > 0,
        "materialSeparationPassed": len(garment.data.materials) >= 2,
        "shapeKeyIsolationPassed": shape_keys == 0,
        "weightingPassed": unweighted == 0,
        "footAndFloorClearancePassed": foot_intrusions == 0,
        "controlledVolumePassed": 0.315 <= total_width <= 0.355
        and 0.195 <= total_depth <= 0.235,
        "fittedSeatPassed": seat["width"] <= 0.330 and seat["rear"] >= 0.095,
        "innerThighCoveragePassed": center_coverage >= 12,
        "straightWideProfilePassed": (
            abs(thigh["width"] - knee["width"]) <= 0.050
            and abs(knee["width"] - hem["width"]) <= 0.035
            and abs(thigh["depth"] - knee["depth"]) <= 0.035
        ),
    }
    required = [
        "singleMeshObjectPassed",
        "finiteCoordinatesPassed",
        "topologyPassed",
        "sourceFaceIndependencePassed",
        "spikeGuardPassed",
        "uvPassed",
        "materialSeparationPassed",
        "shapeKeyIsolationPassed",
        "weightingPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "fittedSeatPassed",
        "innerThighCoveragePassed",
        "straightWideProfilePassed",
    ]
    return {
        "schemaVersion": 1,
        "passed": all(bool(checks[name]) for name in required),
        "checks": checks,
    }


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v32-procedural-source-face-free"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


build.create_outfit = create_outfit


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v32 procedural garment audit failed: {result}")
    raise SystemExit(0)
