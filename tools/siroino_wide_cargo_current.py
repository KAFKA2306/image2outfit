#!/usr/bin/env python3
"""Shared Blender runtime helpers for the canonical Wide Cargo product builder."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_build as build


class MeshBuilder:
    def __init__(self) -> None:
        self.vertices: list[tuple[float, float, float]] = []
        self.faces: list[tuple[int, ...]] = []

    def add_ring(self, points: list[tuple[float, float, float]]) -> list[int]:
        start = len(self.vertices)
        self.vertices.extend(points)
        return list(range(start, start + len(points)))


def build_geometry(segments: int = 48) -> MeshBuilder:
    del segments
    raise RuntimeError(
        "Wide Cargo geometry must be supplied by tools/siroino_wide_cargo_product.py"
    )


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


def tune_material(
    material: bpy.types.Material,
    *,
    base: tuple[float, float, float],
    roughness: float,
    metallic: float = 0.0,
) -> None:
    material.diffuse_color = (*base, 1.0)
    material.use_nodes = True
    shader = (
        material.node_tree.nodes.get("Principled BSDF")
        if material.node_tree is not None
        else None
    )
    if shader is None:
        return
    if "Base Color" in shader.inputs:
        shader.inputs["Base Color"].default_value = (*base, 1.0)
    if "Roughness" in shader.inputs:
        shader.inputs["Roughness"].default_value = roughness
    if "Metallic" in shader.inputs:
        shader.inputs["Metallic"].default_value = metallic


def assign_materials(
    garment: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
) -> None:
    tune_material(fabric, base=(0.020, 0.025, 0.036), roughness=0.78)
    tune_material(strap, base=(0.005, 0.007, 0.011), roughness=0.40)
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


def save_distribution_blend() -> None:
    _, job = build.c.load_job()
    blend_path = build.c.repo_path(job["blendPath"])
    for obj in list(bpy.data.objects):
        preview_only = (
            obj.name.startswith("SiroinoSotai_PC")
            or obj.name == "Studio_Floor"
            or obj.name == "Product_Camera"
            or obj.type in {"LIGHT", "CAMERA"}
        )
        if preview_only:
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)


base = sys.modules[__name__]
