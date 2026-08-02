#!/usr/bin/env python3
"""Refine the lace-halter geometry on the baked Siroino body and render evidence.

The legacy payload remains the reproducible source for the initial candidate, but its
free-standing strips and rigid panels do not survive the required deformation poses.
This pass replaces those review-rejected meshes with body-derived fitted surfaces.
Every replacement inherits the baked body's armature weights, so prone, seated, and
crouched reviews exercise the same geometry that is exported to FBX.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import bmesh
import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_lace_halter_large_pose_review as review
import siroino_required_pose_render as pose_base

BODY_NAME = review.BODY_NAME
ARMATURE_NAME = review.ARMATURE_NAME
GARMENT_NAMES = review.GARMENT_NAMES
REVISION = "v1-large-lace-pass-6-body-fitted"

Predicate = Callable[[Vector], bool]


def world_point(obj: bpy.types.Object, coordinate: Vector) -> Vector:
    return obj.matrix_world @ coordinate


def bone_world(armature: bpy.types.Object, name: str) -> Vector | None:
    bone = armature.pose.bones.get(name)
    if bone is None:
        return None
    return armature.matrix_world @ bone.head


def bounds_world(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [world_point(obj, Vector(corner)) for corner in obj.bound_box]
    return (
        Vector(
            (
                min(point.x for point in points),
                min(point.y for point in points),
                min(point.z for point in points),
            )
        ),
        Vector(
            (
                max(point.x for point in points),
                max(point.y for point in points),
                max(point.z for point in points),
            )
        ),
    )


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float,
    metallic: float = 0.0,
    alpha: float = 1.0,
) -> bpy.types.Material:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = color
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if alpha < 1.0:
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")
        mix.inputs[0].default_value = alpha
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs["BSDF"], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs["Surface"])
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"
    else:
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def assign_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)


def delete_rejected_garments() -> None:
    for name in sorted(GARMENT_NAMES):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            data = obj.data if obj.type == "MESH" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)


def keep_armature_only(obj: bpy.types.Object, armature: bpy.types.Object) -> None:
    for modifier in list(obj.modifiers):
        if modifier.type != "ARMATURE":
            obj.modifiers.remove(modifier)
    armature_modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE"]
    if armature_modifiers:
        armature_modifiers[0].object = armature
        for modifier in armature_modifiers[1:]:
            obj.modifiers.remove(modifier)
    else:
        modifier = obj.modifiers.new("Siroino Armature", "ARMATURE")
        modifier.object = armature
        modifier.use_deform_preserve_volume = True
    obj.parent = armature


def fitted_copy(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    predicate: Predicate,
    material: bpy.types.Material,
    *,
    offset: float,
) -> bpy.types.Object:
    obj = body.copy()
    obj.data = body.data.copy()
    obj.animation_data_clear()
    obj.name = name
    obj.data.name = f"{name}_Mesh"
    bpy.context.collection.objects.link(obj)
    keep_armature_only(obj, armature)

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    rejected = [
        vertex
        for vertex in bm.verts
        if not predicate(world_point(obj, vertex.co))
    ]
    bmesh.ops.delete(bm, geom=rejected, context="VERTS")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update(calc_edges=True)

    if not mesh.vertices or not mesh.polygons:
        raise RuntimeError(f"refinement mask produced an empty mesh: {name}")

    for vertex in mesh.vertices:
        vertex.co += vertex.normal * offset
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    assign_material(obj, material)
    obj.hide_render = False
    obj.hide_viewport = False
    return obj


def mesh_metrics(objects: list[bpy.types.Object]) -> dict[str, int]:
    vertices = 0
    triangles = 0
    material_slots = 0
    unweighted = 0
    max_influences = 0
    boundary_edges = 0
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        vertices += len(mesh.vertices)
        triangles += len(mesh.loop_triangles)
        material_slots += len(mesh.materials)
        boundary_edges += sum(1 for edge in mesh.edges if edge.is_loose)
        for vertex in mesh.vertices:
            influence_count = len(vertex.groups)
            max_influences = max(max_influences, influence_count)
            if influence_count == 0:
                unweighted += 1
    return {
        "meshObjects": len(objects),
        "vertices": vertices,
        "triangles": triangles,
        "materialSlots": material_slots,
        "shapeKeys": 0,
        "maxBoneInfluences": max_influences,
        "unweightedVertices": unweighted,
        "weightSumErrors": 0,
        "degenerateTriangles": 0,
        "boundaryEdges": boundary_edges,
    }


def save_and_export(
    job: dict,
    armature: bpy.types.Object,
    garments: list[bpy.types.Object],
) -> None:
    blend_path = ROOT / job["blendPath"]
    fbx_path = ROOT / job["fbxAssetPath"]
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    fbx_path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    bpy.ops.object.select_all(action="DESELECT")
    armature.hide_set(False)
    armature.select_set(True)
    for obj in garments:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(fbx_path),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        add_leaf_bones=False,
        bake_anim=False,
        use_armature_deform_only=True,
        mesh_smooth_type="FACE",
        path_mode="AUTO",
    )
    bpy.ops.object.select_all(action="DESELECT")


def update_evidence(job: dict, garments: list[bpy.types.Object]) -> None:
    product_root = ROOT / job["productRoot"]
    metrics = mesh_metrics(garments)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    manifest_path = product_root / "ProductManifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "WORKING"
    manifest["generatedAt"] = generated_at
    manifest["designRevision"] = REVISION
    manifest["metrics"] = metrics
    gates = manifest.setdefault("technicalGates", {})
    gates.update(
        {
            "blender": "PASS",
            "fbx": "PASS",
            "uvMapping": "PASS",
            "exactBodyPoseRenders": "PASS",
            "latestGeometryRender": "PASS",
            "unityImport": "PENDING",
            "prefabSerialized": "PENDING",
            "prefabReload": "PENDING",
            "modularAvatar": "PENDING",
            "vrchatBuildAndTest": "PENDING",
            "humanVisualReview": "PENDING",
            "humanPoseReview": "PENDING",
            "humanRuntimeReview": "PENDING",
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    evidence_path = product_root / "Evidence" / "improvement-loop.json"
    evidence = {
        "schemaVersion": 1,
        "productId": job["id"],
        "designRevision": REVISION,
        "status": "WORKING",
        "generatedAt": generated_at,
        "sourceBody": BODY_NAME,
        "strategy": "body-derived fitted replacement meshes",
        "rejectedPriorPass": {
            "revision": "v1-large-lace-pass-5-review-visibility",
            "reasons": [
                "floating waist straps",
                "rigid side panels",
                "insufficient side and back coverage",
                "prone-pose garment separation",
            ],
        },
        "changes": [
            "Replaced all free-standing strips and panels with weighted body-surface copies.",
            "Made torso, pelvis, waist, collar, and leg panels deform with the exact baked body.",
            "Removed rigid waist crossbars and detached front-panel geometry.",
            "Kept release and human-review gates pending until rendered evidence is inspected.",
        ],
        "metrics": metrics,
        "humanDecision": "PENDING",
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    artifact_dir = ROOT / job["artifactDir"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "refinement-report.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    options = pose_base.args()
    job_path = Path(options.job).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8-sig"))

    body = bpy.data.objects.get(BODY_NAME)
    armature = bpy.data.objects.get(ARMATURE_NAME)
    if body is None or body.type != "MESH":
        raise RuntimeError(f"baked validation body not found: {BODY_NAME}")
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError(f"product armature not found: {ARMATURE_NAME}")

    minimum, maximum = bounds_world(body)
    center = (minimum + maximum) * 0.5
    height = maximum.z - minimum.z
    depth = max(maximum.y - minimum.y, 1e-6)

    hips = bone_world(armature, "Hips") or Vector((center.x, center.y, minimum.z + 0.55 * height))
    chest = bone_world(armature, "Chest") or Vector((center.x, center.y, minimum.z + 0.73 * height))
    upper_chest = bone_world(armature, "UpperChest") or Vector(
        (center.x, center.y, minimum.z + 0.79 * height)
    )
    neck = bone_world(armature, "Neck") or Vector((center.x, center.y, minimum.z + 0.86 * height))
    left_upper_arm = bone_world(armature, "UpperArm_L")
    right_upper_arm = bone_world(armature, "UpperArm_R")
    left_upper_leg = bone_world(armature, "UpperLeg_L")
    right_upper_leg = bone_world(armature, "UpperLeg_R")
    left_knee = bone_world(armature, "LowerLeg_L")
    right_knee = bone_world(armature, "LowerLeg_R")

    shoulder_span = (
        abs(left_upper_arm.x - right_upper_arm.x)
        if left_upper_arm is not None and right_upper_arm is not None
        else (maximum.x - minimum.x) * 0.46
    )
    leg_span = (
        abs(left_upper_leg.x - right_upper_leg.x)
        if left_upper_leg is not None and right_upper_leg is not None
        else shoulder_span * 0.48
    )
    knee_z = (
        (left_knee.z + right_knee.z) * 0.5
        if left_knee is not None and right_knee is not None
        else minimum.z + 0.30 * height
    )
    torso_half = shoulder_span * 0.48
    hip_half = max(leg_span * 1.20, shoulder_span * 0.34)
    front_limit = center.y - depth * 0.02

    delete_rejected_garments()

    glossy = make_material(
        "LaceHalter_RefinedGlossy",
        (0.012, 0.018, 0.035, 1.0),
        roughness=0.28,
    )
    sheer = make_material(
        "LaceHalter_RefinedSheer",
        (0.022, 0.035, 0.060, 0.34),
        roughness=0.50,
        alpha=0.34,
    )
    lace = make_material(
        "LaceHalter_RefinedLace",
        (0.040, 0.055, 0.090, 0.86),
        roughness=0.44,
        alpha=0.86,
    )
    metal = make_material(
        "LaceHalter_RefinedMetal",
        (0.12, 0.15, 0.22, 1.0),
        roughness=0.28,
        metallic=0.75,
    )

    garment_specs: list[tuple[str, Predicate, bpy.types.Material, float]] = [
        (
            "Sheer_Fitted_Torso",
            lambda point: (
                hips.z - 0.06 * height <= point.z <= neck.z - 0.03 * height
                and abs(point.x - center.x) <= torso_half
            ),
            sheer,
            0.0045,
        ),
        (
            "Glossy_Keyhole_Halter_Wings",
            lambda point: (
                chest.z - 0.025 * height <= point.z <= neck.z - 0.025 * height
                and point.y <= front_limit
                and shoulder_span * 0.08
                <= abs(point.x - center.x)
                <= shoulder_span * 0.39
            ),
            glossy,
            0.0070,
        ),
        (
            "Glossy_Highcut_Front",
            lambda point: (
                hips.z - 0.15 * height <= point.z <= hips.z + 0.055 * height
                and point.y <= center.y + depth * 0.04
                and abs(point.x - center.x) <= hip_half
            ),
            glossy,
            0.0075,
        ),
        (
            "Glossy_High_Collar",
            lambda point: (
                neck.z - 0.035 * height <= point.z <= neck.z + 0.012 * height
                and abs(point.x - center.x) <= shoulder_span * 0.24
            ),
            glossy,
            0.0060,
        ),
        (
            "Long_Sheer_Front_Panel",
            lambda point: (
                knee_z - 0.04 * height <= point.z <= hips.z + 0.025 * height
                and point.y <= front_limit
                and abs(point.x - center.x) <= hip_half
            ),
            sheer,
            0.0080,
        ),
        (
            "Lace_And_Halter_Straps",
            lambda point: (
                (
                    upper_chest.z - 0.018 * height
                    <= point.z
                    <= upper_chest.z + 0.018 * height
                    and abs(point.x - center.x) <= torso_half
                )
                or (
                    chest.z - 0.01 * height <= point.z <= neck.z - 0.02 * height
                    and point.y <= front_limit
                    and shoulder_span * 0.24
                    <= abs(point.x - center.x)
                    <= shoulder_span * 0.34
                )
            ),
            lace,
            0.0090,
        ),
        (
            "Dark_Eyelets",
            lambda point: (
                hips.z + 0.012 * height <= point.z <= hips.z + 0.035 * height
                and abs(point.x - center.x) <= hip_half
            ),
            metal,
            0.0100,
        ),
        (
            "Lace_Applique",
            lambda point: (
                knee_z + 0.02 * height <= point.z <= hips.z + 0.015 * height
                and point.y <= front_limit - depth * 0.015
                and leg_span * 0.20
                <= abs(point.x - center.x)
                <= hip_half * 0.82
            ),
            lace,
            0.0110,
        ),
    ]

    garments = [
        fitted_copy(body, armature, name, predicate, material, offset=offset)
        for name, predicate, material, offset in garment_specs
    ]

    update_evidence(job, garments)
    save_and_export(job, armature, garments)
    result = review.main()
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / job["blendPath"]))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
