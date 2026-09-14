#!/usr/bin/env python3
"""Converge the Military Sheer Romper against the actual Siroino _Large body.

The older v12 path extracted garment vertices from the Basis mesh and then copied
nearest body shape-key deltas onto the garment. Hosted evidence exposed a
10.97 cm outlier in that mapping. This product-only manufacturing path instead
bakes the configured _Large profile first, extracts panels from that evaluated
surface, transfers weights from the same evaluated surface, and then enforces a
bounded measured body-clearance envelope.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_fit_product as product  # noqa: E402

fit = product.fit
ORIGINAL_BUILD = product.build
ORIGINAL_AUDIT = product.target_fit_audit
ORIGINAL_SCENE = product.ORIGINAL_SCENE

TARGET_CLEARANCE = {
    "Military_Opaque_Bodice": 0.012,
    "Military_Sheer_Back": 0.007,
    "Military_Fitted_Shorts": 0.014,
    "Military_Asymmetric_Front_Flap": 0.018,
    "Military_Standing_Collar": 0.010,
    "Military_Sleeve_L": 0.010,
    "Military_Sleeve_R": 0.010,
    "Military_Waist_Belt": 0.014,
}


def evaluated_bounds(body: bpy.types.Object) -> tuple[Vector, Vector]:
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def transfer_current_weights(
    obj: bpy.types.Object,
    body: bpy.types.Object,
) -> None:
    """Transfer source weights using current-profile body positions as lookup."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        tree = KDTree(len(mesh.vertices))
        for vertex in mesh.vertices:
            tree.insert(evaluated.matrix_world @ vertex.co, vertex.index)
        tree.balance()
        groups = {
            group.name: obj.vertex_groups.new(name=group.name)
            for group in body.vertex_groups
        }
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            _, source_index, _ = tree.find(world)
            assignments = body.data.vertices[source_index].groups
            total = sum(item.weight for item in assignments)
            if total <= 0.0:
                continue
            for assignment in assignments:
                source_group = body.vertex_groups[assignment.group]
                groups[source_group.name].add(
                    [vertex.index],
                    assignment.weight / total,
                    "REPLACE",
                )
    finally:
        evaluated.to_mesh_clear()


def finish(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
    *,
    fit_audit: bool,
) -> bpy.types.Object:
    """Finish a panel whose configured target profile is already baked in."""
    del values
    world = obj.matrix_world.copy()
    fit.clean_mesh(obj)
    transfer_current_weights(obj, body)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    obj["image2outfit_role"] = "garment"
    obj["image2outfit_fit_audit"] = fit_audit
    obj["image2outfit_profile_baked"] = True
    for polygon in obj.data.polygons:
        polygon.use_smooth = True

    # Preserve the same imported parent space as the target body while keeping
    # the armature modifier established above.
    obj.parent = body.parent
    obj.parent_type = body.parent_type
    obj.parent_bone = body.parent_bone
    if body.parent is not None:
        obj.matrix_parent_inverse = body.matrix_parent_inverse.copy()
    obj.matrix_world = world
    bpy.context.view_layer.update()
    return obj


def extract(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    predicate,
    material: bpy.types.Material,
    values: dict[str, float],
    *,
    offset: float,
    thickness: float,
    fit_audit: bool = True,
) -> bpy.types.Object:
    """Extract from the evaluated _Large surface, never from Basis + copied deltas."""
    target = TARGET_CLEARANCE.get(name, offset)
    audited = fit_audit or name in {
        "Military_Asymmetric_Front_Flap",
        "Military_Waist_Belt",
    }
    source_uv = body.data.uv_layers.active
    used: dict[int, int] = {}
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    face_uvs: list[list[tuple[float, float]]] = []

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        if len(evaluated_mesh.polygons) != len(body.data.polygons):
            raise RuntimeError("target profile evaluation changed Siroino topology")
        for source_polygon in body.data.polygons:
            polygon = evaluated_mesh.polygons[source_polygon.index]
            center = evaluated.matrix_world @ polygon.center
            if not predicate(center):
                continue
            face: list[int] = []
            uvs: list[tuple[float, float]] = []
            for loop_index in source_polygon.loop_indices:
                source_index = body.data.loops[loop_index].vertex_index
                if source_index not in used:
                    source = evaluated_mesh.vertices[source_index]
                    used[source_index] = len(vertices)
                    vertices.append(
                        tuple(source.co + source.normal.normalized() * target)
                    )
                face.append(used[source_index])
                if source_uv is not None:
                    uv = source_uv.data[loop_index].uv
                    uvs.append((float(uv.x), float(uv.y)))
                else:
                    uvs.append((0.0, 0.0))
            faces.append(face)
            face_uvs.append(uvs)
    finally:
        evaluated.to_mesh_clear()

    if not faces:
        raise RuntimeError(f"target surface selection produced no faces: {name}")

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, uvs in zip(mesh.polygons, face_uvs):
        for loop_index, uv in zip(polygon.loop_indices, uvs):
            uv_layer.data[loop_index].uv = uv

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.matrix_world = body.matrix_world.copy()
    obj = fit.finish_skinned(
        obj,
        body,
        armature,
        values,
        fit_audit=audited,
    )
    obj["image2outfit_base_vertex_count"] = len(obj.data.vertices)

    solidify = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 1.0
    solidify.use_even_offset = True
    bevel = obj.modifiers.new("Finished edge", "BEVEL")
    bevel.width = min(0.0012, thickness * 0.42)
    bevel.segments = 2
    bevel.limit_method = "ANGLE"
    return obj


def _apply_vertex_delta(obj: bpy.types.Object, index: int, delta: Vector) -> None:
    obj.data.vertices[index].co += delta


def project_to_clearance(
    body: bpy.types.Object,
    obj: bpy.types.Object,
    target: float,
    *,
    iterations: int = 3,
) -> dict[str, float | int]:
    """Project the evaluated base surface to one measured body-clearance shell."""
    moved_total = 0
    largest_move = 0.0
    for _ in range(iterations):
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        body_tree = BVHTree.FromObject(body, depsgraph)
        if body_tree is None:
            raise RuntimeError("cannot build Siroino body BVH for fit convergence")
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        count = min(
            int(obj.get("image2outfit_base_vertex_count", len(mesh.vertices))),
            len(mesh.vertices),
            len(obj.data.vertices),
        )
        body_inverse = body.matrix_world.inverted()
        object_inverse = obj.matrix_world.inverted()
        corrections: list[tuple[int, Vector]] = []
        try:
            for index, vertex in enumerate(mesh.vertices[:count]):
                world = evaluated.matrix_world @ vertex.co
                body_local = body_inverse @ world
                nearest = body_tree.find_nearest(body_local)
                point, normal = nearest[0], nearest[1]
                if point is None or normal is None or normal.length_squared <= 1e-12:
                    continue
                normal = normal.normalized()
                desired_body = point + normal * target
                desired_world = body.matrix_world @ desired_body
                desired_local = object_inverse @ desired_world
                current_local = object_inverse @ world
                delta = desired_local - current_local
                if delta.length > 0.060:
                    raise RuntimeError(
                        f"non-local clearance correction {obj.name}[{index}] "
                        f"requires {delta.length:.6f} m"
                    )
                if delta.length > 0.00025:
                    corrections.append((index, delta))
        finally:
            evaluated.to_mesh_clear()

        if not corrections:
            break
        for index, delta in corrections:
            _apply_vertex_delta(obj, index, delta)
            largest_move = max(largest_move, float(delta.length))
        moved_total += len(corrections)
        obj.data.update()

    bpy.context.view_layer.update()
    obj["image2outfit_clearance_target_m"] = float(target)
    return {
        "targetClearanceMeters": float(target),
        "movedVerticesAcrossIterations": moved_total,
        "largestSingleCorrectionMeters": largest_move,
    }


def build(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    cloth: bpy.types.Material,
    sheer: bpy.types.Material,
    gold: bpy.types.Material,
    values: dict[str, float],
) -> list[bpy.types.Object]:
    garments = ORIGINAL_BUILD(body, armature, cloth, sheer, gold, values)
    convergence: dict[str, dict[str, float | int]] = {}
    for obj in garments:
        target = TARGET_CLEARANCE.get(obj.name)
        if target is None:
            continue
        obj["image2outfit_fit_audit"] = True
        convergence[obj.name] = project_to_clearance(body, obj, target)
    bpy.context.scene["militaryRomperClearanceConvergence"] = json.dumps(
        convergence,
        sort_keys=True,
    )
    return garments


def target_fit_audit(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
) -> dict[str, object]:
    result = ORIGINAL_AUDIT(body, garments)
    median = result.get("medianClearanceMeters")
    maximum = result.get("maximumClearanceMeters")
    object_medians = {
        name: values.get("medianClearanceMeters")
        for name, values in result.get("objects", {}).items()
        if isinstance(values, dict)
    }
    excessive = {
        name: value
        for name, value in object_medians.items()
        if isinstance(value, (int, float))
        and value > TARGET_CLEARANCE.get(name, 0.018) + 0.006
    }
    envelope_passed = (
        isinstance(median, (int, float))
        and median <= 0.020
        and isinstance(maximum, (int, float))
        and maximum <= 0.045
        and not excessive
    )
    result["clearanceEnvelope"] = {
        "medianMaximumMeters": 0.020,
        "absoluteMaximumMeters": 0.045,
        "excessiveMedianObjects": excessive,
        "passed": envelope_passed,
    }
    result["passed"] = bool(result.get("passed")) and envelope_passed
    return result


def scene(body: bpy.types.Object) -> bpy.types.Object:
    camera = ORIGINAL_SCENE(body)
    render = bpy.context.scene.render
    render.resolution_x = 512
    render.resolution_y = 512
    render.resolution_percentage = 100
    return camera


def main() -> int:
    product.bounds = evaluated_bounds
    product.finish = finish
    product.extract = extract
    product.build = build
    product.target_fit_audit = target_fit_audit
    product.scene = scene
    return product.main()


if __name__ == "__main__":
    raise SystemExit(main())
