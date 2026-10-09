#!/usr/bin/env python3
"""Rig the current UniformFrontBack OSS meshes to the repository avatar skeleton.

This is an asset-generation adapter for the local benchmark.  The input GLBs are
full human-shaped meshes without an armature; the exported FBX keeps the generated
surface and receives the Siroino skeleton and transferred weights so Unity can use
it as a character mesh. The exported FBX is re-imported and checked for bone,
weight, and pose-deformation integrity before the report can pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TOOLS))

from blender_weight_transfer import (  # noqa: E402
    _apply_data_transfer,
    _armature_hash,
    _ensure_armature_modifier,
    _expected_laterality,
    _mesh_hash,
    _read_weights,
    _write_weights,
)
from image2outfit.weight_transfer import (  # noqa: E402
    WeightTransferArtifact,
    WeightTransferMethod,
    WeightTransferPolicy,
    constrain_vertex_weights,
)


BODY_FBX = ROOT / "Assets/SiroinoWorks/SiroinoSotai/FBX/SiroinoSotai_PC.fbx"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=("TripoSG", "Hunyuan3D-2.1"))
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-fbx", required=True, type=Path)
    parser.add_argument("--output-blend", required=True, type=Path)
    parser.add_argument("--output-report", required=True, type=Path)
    parser.add_argument("--crop-z", type=float, default=-0.75)
    parser.add_argument(
        "--max-triangles",
        type=int,
        help="Optionally decimate the generated surface to this triangle budget.",
    )
    parser.add_argument(
        "--single-garment-material",
        action="store_true",
        help="Assign one garment material to every polygon in the generated mesh.",
    )
    parser.add_argument(
        "--voxel-remesh-size",
        type=float,
        help="Optionally close reconstruction holes with Blender voxel remesh before decimation.",
    )
    parser.add_argument(
        "--fill-holes",
        action="store_true",
        help="Fill remaining boundary loops after remesh before decimation.",
    )
    return parser.parse_args(values)


def repo_path(path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {path}")
    return resolved


def bounds(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    return (
        Vector(min(point[index] for point in points) for index in range(3)),
        Vector(max(point[index] for point in points) for index in range(3)),
    )


def delete_below_z(obj: bpy.types.Object, threshold: float) -> int:
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        doomed = [vertex for vertex in bm.verts if vertex.co.z < threshold]
        if doomed:
            bmesh.ops.delete(bm, geom=doomed, context="VERTS")
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
        bm.faces.ensure_lookup_table()
        degenerate = [face for face in bm.faces if face.calc_area() <= 1e-12]
        if degenerate:
            bmesh.ops.delete(bm, geom=degenerate, context="FACES")
        bm.to_mesh(mesh)
        mesh.update(calc_edges=True)
        return len(doomed)
    finally:
        bm.free()


def apply_surface_materials(
    obj: bpy.types.Object,
    *,
    single_garment_material: bool = False,
) -> None:
    garment = bpy.data.materials.new(f"OSS {obj.name} Garment")
    garment.diffuse_color = (0.035, 0.07, 0.12, 1.0)
    garment.use_nodes = True
    garment.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (
        0.035,
        0.07,
        0.12,
        1.0,
    )
    skin = bpy.data.materials.new(f"OSS {obj.name} Skin")
    skin.diffuse_color = (0.58, 0.38, 0.28, 1.0)
    skin.use_nodes = True
    skin.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (
        0.58,
        0.38,
        0.28,
        1.0,
    )
    obj.data.materials.clear()
    obj.data.materials.append(garment)
    if single_garment_material:
        for polygon in obj.data.polygons:
            polygon.material_index = 0
        return

    obj.data.materials.append(skin)
    for polygon in obj.data.polygons:
        center = polygon.center
        is_skin = (
            center.z > 0.99
            or center.z < 0.27
            or (abs(center.x) > 0.34 and center.z < 0.91)
        )
        polygon.material_index = 1 if is_skin else 0


def decimate_to_triangle_budget(
    obj: bpy.types.Object,
    max_triangles: int | None,
) -> int:
    current_triangles = sum(len(polygon.vertices) - 2 for polygon in obj.data.polygons)
    if max_triangles is None or current_triangles <= max_triangles:
        return 0
    if max_triangles < 3:
        raise ValueError("--max-triangles must be at least 3")

    modifier = obj.modifiers.new(name="TripoSGTriangleBudget", type="DECIMATE")
    modifier.ratio = max(0.001, min(1.0, max_triangles / current_triangles))
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.data.update(calc_edges=True)
    return current_triangles - sum(
        len(polygon.vertices) - 2 for polygon in obj.data.polygons
    )


def voxel_remesh(obj: bpy.types.Object, voxel_size: float | None) -> None:
    if voxel_size is None:
        return
    if voxel_size <= 0.0:
        raise ValueError("--voxel-remesh-size must be positive")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    obj.data.remesh_voxel_size = voxel_size
    bpy.ops.object.voxel_remesh()
    obj.data.update(calc_edges=True)


def fill_boundary_holes(obj: bpy.types.Object) -> int:
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        boundary_edges = [edge for edge in bm.edges if edge.is_boundary]
        if not boundary_edges:
            return 0
        bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=0)
        bm.to_mesh(mesh)
        mesh.update(calc_edges=True)
        return len(boundary_edges)
    finally:
        bm.free()


def transfer_weights(source: bpy.types.Object, target: bpy.types.Object, armature: bpy.types.Object) -> dict[str, object]:
    deform_bones = {bone.name for bone in armature.data.bones if bone.use_deform}
    for bone_name in sorted(deform_bones):
        if target.vertex_groups.get(bone_name) is None:
            target.vertex_groups.new(name=bone_name)
    _apply_data_transfer(
        bpy,
        source=source,
        target=target,
        mapping="nearest-face-interpolated",
        max_distance=0.0,
    )
    left_bones = {name for name in deform_bones if name.lower().endswith((".l", "_l", "-l"))}
    right_bones = {name for name in deform_bones if name.lower().endswith((".r", "_r", "-r"))}
    policy = WeightTransferPolicy(
        max_influences=4,
        minimum_weight=1e-8,
        normalization_tolerance=1e-5,
        laterality_contamination_limit=0.05,
    )
    result = constrain_vertex_weights(
        _read_weights(target),
        deform_bones=deform_bones,
        policy=policy,
        expected_laterality=_expected_laterality(
            target,
            axis="X",
            center_tolerance=0.05,
            left_positive=True,
        ),
        left_bones=left_bones,
        right_bones=right_bones,
    )
    _write_weights(target, result.weights)
    _ensure_armature_modifier(target, armature)
    artifact = WeightTransferArtifact(
        source_mesh_hash=_mesh_hash(source),
        target_mesh_hash=_mesh_hash(target),
        armature_hash=_armature_hash(armature, include_bind_pose=False),
        bind_pose_hash=_armature_hash(armature, include_bind_pose=True),
        method=WeightTransferMethod.BLENDER_DATA_TRANSFER,
        method_version=bpy.app.version_string,
        parameters={
            "mapping": "nearest-face-interpolated",
            "maxInfluences": 4,
            "minimumWeight": 1e-8,
            "lateralityAxis": "X",
            "lateralityCenterTolerance": 0.05,
            "leftPositive": True,
        },
        result=result,
    )
    return {"targetObject": target.name, **artifact.to_dict(), "artifactDigest": artifact.digest()}


def export_fbx(path: Path, armature: bpy.types.Object, target: bpy.types.Object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_scale_options="FBX_SCALE_ALL",
        use_space_transform=True,
        bake_space_transform=False,
        mesh_smooth_type="OFF",
        use_subsurf=False,
        use_mesh_modifiers=True,
        use_mesh_edges=False,
        use_tspace=False,
        use_armature_deform_only=True,
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        armature_nodetype="NULL",
        bake_anim=False,
        apply_unit_scale=True,
        path_mode="RELATIVE",
        embed_textures=False,
    )


def inspect_exported_fbx(
    path: Path,
    *,
    expected_deform_bones: set[str],
    expected_vertex_count: int,
) -> dict[str, object]:
    digest = file_sha256(path)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    issues: list[str] = []
    if len(armatures) != 1:
        issues.append(f"expected one armature, imported {len(armatures)}")
    if len(meshes) != 1:
        issues.append(f"expected one mesh, imported {len(meshes)}")

    result: dict[str, object] = {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": digest,
        "fileSizeBytes": path.stat().st_size,
        "armatureCount": len(armatures),
        "meshObjectCount": len(meshes),
        "expectedVertexCount": expected_vertex_count,
        "issues": issues,
    }
    if len(armatures) != 1 or len(meshes) != 1:
        result["passed"] = False
        return result

    armature = armatures[0]
    mesh = meshes[0]
    exported_bones = {bone.name for bone in armature.data.bones}
    deform_bones = {
        bone.name for bone in armature.data.bones if bone.use_deform
    }
    missing_bones = sorted(expected_deform_bones - exported_bones)
    if missing_bones:
        issues.append(f"FBX is missing deform bones: {missing_bones}")

    group_names = {group.index: group.name for group in mesh.vertex_groups}
    armature_modifiers = [
        modifier
        for modifier in mesh.modifiers
        if modifier.type == "ARMATURE" and modifier.object == armature
    ]
    if not armature_modifiers:
        issues.append("mesh has no modifier targeting the imported armature")

    zero_weight_vertices = 0
    non_normalized_vertices = 0
    over_limit_vertices = 0
    unknown_weight_groups: set[str] = set()
    weighted_group_vertex_counts: dict[str, int] = {}
    for vertex in mesh.data.vertices:
        weights = []
        for membership in vertex.groups:
            group_name = group_names.get(membership.group)
            if group_name is None:
                unknown_weight_groups.add(f"index:{membership.group}")
                continue
            if group_name not in exported_bones:
                unknown_weight_groups.add(group_name)
            if membership.weight > 1e-8:
                weights.append(membership.weight)
                weighted_group_vertex_counts[group_name] = (
                    weighted_group_vertex_counts.get(group_name, 0) + 1
                )
        if not weights:
            zero_weight_vertices += 1
            continue
        if abs(sum(weights) - 1.0) > 1e-5:
            non_normalized_vertices += 1
        if len(weights) > 4:
            over_limit_vertices += 1

    if zero_weight_vertices:
        issues.append(f"{zero_weight_vertices} vertices have no positive weights")
    if non_normalized_vertices:
        issues.append(f"{non_normalized_vertices} vertices have non-normalized weights")
    if over_limit_vertices:
        issues.append(f"{over_limit_vertices} vertices exceed four bone influences")
    if unknown_weight_groups:
        issues.append(f"weights reference unknown bone groups: {sorted(unknown_weight_groups)}")
    if len(mesh.data.vertices) != expected_vertex_count:
        issues.append(
            f"vertex count changed across FBX export: {expected_vertex_count} -> {len(mesh.data.vertices)}"
        )

    pose_candidates = {
        name: count
        for name, count in weighted_group_vertex_counts.items()
        if name in deform_bones and armature.pose.bones.get(name) is not None
    }
    pose_test: dict[str, object] = {
        "method": "10-degree single-bone rotation with evaluated mesh displacement",
        "passed": False,
    }
    if pose_candidates and armature_modifiers:
        bone_name = max(pose_candidates, key=pose_candidates.get)
        pose_bone = armature.pose.bones[bone_name]
        original_basis = pose_bone.matrix_basis.copy()
        original_rotation_mode = pose_bone.rotation_mode
        original_rotation_euler = pose_bone.rotation_euler.copy()
        original_rotation_quaternion = pose_bone.rotation_quaternion.copy()
        original_rotation_axis_angle = tuple(pose_bone.rotation_axis_angle)
        try:
            evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
            base_mesh = evaluated.to_mesh()
            base_coordinates = [vertex.co.copy() for vertex in base_mesh.vertices]
            evaluated.to_mesh_clear()
            axis_results = []
            for axis_index, axis_name in enumerate(("X", "Y", "Z")):
                pose_bone.rotation_mode = "XYZ"
                pose_bone.matrix_basis = original_basis
                pose_bone.rotation_euler[axis_index] += math.radians(10.0)
                bpy.context.view_layer.update()
                evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
                posed_mesh = evaluated.to_mesh()
                displacements = [
                    (posed_mesh.vertices[index].co - base_coordinates[index]).length
                    for index in range(min(len(base_coordinates), len(posed_mesh.vertices)))
                ]
                evaluated.to_mesh_clear()
                axis_results.append(
                    {
                        "axis": axis_name,
                        "movedVertexCount": sum(value > 1e-6 for value in displacements),
                        "maximumDisplacement": max(displacements, default=0.0),
                    }
                )
            pose_bone.matrix_basis = original_basis
            pose_bone.rotation_mode = original_rotation_mode
            pose_bone.rotation_euler = original_rotation_euler
            pose_bone.rotation_quaternion = original_rotation_quaternion
            pose_bone.rotation_axis_angle = original_rotation_axis_angle
            best_axis = max(
                axis_results,
                key=lambda value: (
                    value["movedVertexCount"],
                    value["maximumDisplacement"],
                ),
            )
            pose_test.update(
                {
                    "boneName": bone_name,
                    "weightedVertexCount": pose_candidates[bone_name],
                    "angleDegrees": 10,
                    "axisResults": axis_results,
                    "bestAxis": best_axis["axis"],
                    "movedVertexCount": best_axis["movedVertexCount"],
                    "maximumDisplacement": best_axis["maximumDisplacement"],
                    "passed": best_axis["movedVertexCount"] > 0,
                }
            )
            if not pose_test["passed"]:
                issues.append("a weighted bone pose did not deform any mesh vertices")
        finally:
            pose_bone.matrix_basis = original_basis
            pose_bone.rotation_mode = original_rotation_mode
            pose_bone.rotation_euler = original_rotation_euler
            pose_bone.rotation_quaternion = original_rotation_quaternion
            pose_bone.rotation_axis_angle = original_rotation_axis_angle
    else:
        issues.append("no weighted deform bone is available for a pose deformation check")

    result.update(
        {
            "armatureName": armature.name,
            "boneCount": len(exported_bones),
            "deformBoneCount": len(deform_bones),
            "expectedDeformBoneCount": len(expected_deform_bones),
            "missingDeformBones": missing_bones,
            "meshName": mesh.name,
            "vertexCount": len(mesh.data.vertices),
            "vertexGroupCount": len(mesh.vertex_groups),
            "armatureModifierCount": len(armature_modifiers),
            "zeroWeightVertexCount": zero_weight_vertices,
            "nonNormalizedVertexCount": non_normalized_vertices,
            "overFourInfluenceVertexCount": over_limit_vertices,
            "unknownWeightGroups": sorted(unknown_weight_groups),
            "poseDeformationTest": pose_test,
        }
    )
    result["issues"] = issues
    result["passed"] = not issues
    return result


def main() -> int:
    args = parse_args()
    source_path = repo_path(args.input)
    output_fbx = repo_path(args.output_fbx)
    output_blend = repo_path(args.output_blend)
    output_report = repo_path(args.output_report)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if not BODY_FBX.is_file():
        raise FileNotFoundError(BODY_FBX)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(BODY_FBX))
    source = bpy.data.objects.get("SiroinoSotai_PC")
    armature = bpy.data.objects.get("Armature")
    if source is None or armature is None:
        raise RuntimeError("Siroino base mesh or Armature was not imported")
    bpy.ops.import_scene.gltf(filepath=str(source_path))
    imported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj != source]
    if len(imported) != 1:
        raise RuntimeError(f"expected one OSS mesh, got {[obj.name for obj in imported]}")
    target = imported[0]
    target.name = f"{args.model}_CharacterMesh"

    removed_vertices = 0
    if args.model == "Hunyuan3D-2.1":
        removed_vertices = delete_below_z(target, args.crop_z)

    body_min, body_max = bounds(source)
    target_min, target_max = bounds(target)
    body_height = body_max.z - body_min.z
    target_height = target_max.z - target_min.z
    if target_height <= 0 or body_height <= 0:
        raise RuntimeError("invalid source or target height")
    target.scale *= body_height / target_height
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    target_min, target_max = bounds(target)
    target.location += Vector(
        (
            (body_min.x + body_max.x) * 0.5 - (target_min.x + target_max.x) * 0.5,
            (body_min.y + body_max.y) * 0.5 - (target_min.y + target_max.y) * 0.5,
            body_min.z - target_min.z,
        )
    )
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    voxel_remesh(target, args.voxel_remesh_size)
    filled_boundary_edges = fill_boundary_holes(target) if args.fill_holes else 0
    decimated_triangles = decimate_to_triangle_budget(target, args.max_triangles)
    apply_surface_materials(
        target,
        single_garment_material=args.single_garment_material,
    )
    weight_artifact = transfer_weights(source, target, armature)
    expected_deform_bones = {
        bone.name for bone in armature.data.bones if bone.use_deform
    }
    expected_vertex_count = len(target.data.vertices)
    target_name = target.name
    target_face_count = len(target.data.polygons)
    final_triangle_count = sum(
        len(polygon.vertices) - 2 for polygon in target.data.polygons
    )
    material_names = [material.name for material in target.data.materials]
    final_min, final_max = bounds(target)
    export_fbx(output_fbx, armature, target)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), check_existing=False, compress=True)
    fbx_readback = inspect_exported_fbx(
        output_fbx,
        expected_deform_bones=expected_deform_bones,
        expected_vertex_count=expected_vertex_count,
    )

    report = {
        "schemaVersion": 1,
        "kind": "oss-character-rig",
        "model": args.model,
        "input": str(source_path.relative_to(ROOT)).replace("\\", "/"),
        "inputSha256": file_sha256(source_path),
        "outputFbx": str(output_fbx.relative_to(ROOT)).replace("\\", "/"),
        "outputFbxSha256": fbx_readback["sha256"],
        "outputBlend": str(output_blend.relative_to(ROOT)).replace("\\", "/"),
        "outputBlendSha256": file_sha256(output_blend),
        "blenderVersion": bpy.app.version_string,
        "skeleton": "Assets/SiroinoWorks/SiroinoSotai/FBX/SiroinoSotai_PC.fbx",
        "targetObject": target_name,
        "inputVertexCountAfterCleanup": expected_vertex_count,
        "inputFaceCountAfterCleanup": target_face_count,
        "triangleBudget": args.max_triangles,
        "decimatedTriangles": decimated_triangles,
        "finalTriangleCount": final_triangle_count,
        "singleGarmentMaterial": args.single_garment_material,
        "voxelRemeshSize": args.voxel_remesh_size,
        "filledBoundaryEdges": filled_boundary_edges,
        "removedVerticesBelowCrop": removed_vertices,
        "normalizedBounds": {"min": list(final_min), "max": list(final_max)},
        "weightTransfer": weight_artifact,
        "fbxReadback": fbx_readback,
        "materials": material_names,
        "status": "PASS"
        if weight_artifact["audit"]["passed"] and fbx_readback["passed"]
        else "FAIL",
    }
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
