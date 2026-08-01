#!/usr/bin/env python3
"""Production entry point for the Siroino Wide Cargo product.

This layer keeps the reproducible base generator but replaces its first-pass
cone-like proportions with an avatar-fitted, VRChat-readable silhouette:

- a close low-rise waist instead of a floating ring,
- a substantially thinner hip and upper-thigh volume,
- wide legs that read broad from the front but remain controlled in profile,
- shorter hems that clear the floor and shoes,
- smaller pockets and straps that remain legible without floating,
- explicit leg-bone weights for crouch and sitting deformation,
- UV generation and a distribution-safe Blender file.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_build as build

_original_mesh_object = build.mesh_object
_original_create_outfit = build.create_outfit
_original_asymmetric_leg_shell = build.asymmetric_leg_shell
_original_flat_ellipse_band = build.flat_ellipse_band
_original_flat_path_ribbon = build.flat_path_ribbon
_original_rounded_box = build.rounded_box
_original_buckle = build.buckle


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def mesh_object_with_uv(*args, **kwargs):
    obj = _original_mesh_object(*args, **kwargs)
    mesh = obj.data
    if mesh.uv_layers.active is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        coordinates = [vertex.co for vertex in mesh.vertices]
        center_x = sum(co.x for co in coordinates) / max(1, len(coordinates))
        center_y = sum(co.y for co in coordinates) / max(1, len(coordinates))
        minimum_z = min((co.z for co in coordinates), default=0.0)
        maximum_z = max((co.z for co in coordinates), default=1.0)
        span_z = max(maximum_z - minimum_z, 1e-6)
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                vertex_index = mesh.loops[loop_index].vertex_index
                coordinate = mesh.vertices[vertex_index].co
                angle = math.atan2(coordinate.y - center_y, coordinate.x - center_x)
                uv_layer.data[loop_index].uv = (
                    (angle / math.tau) % 1.0,
                    (coordinate.z - minimum_z) / span_z,
                )
    mesh.update()
    return obj


def replace_vertex_weights(
    obj: bpy.types.Object,
    weights: dict[str, list[tuple[int, float]]],
) -> None:
    """Replace transferred weights with a deterministic garment-specific map."""
    for group in list(obj.vertex_groups):
        obj.vertex_groups.remove(group)
    for bone_name, assignments in weights.items():
        group = obj.vertex_groups.new(name=bone_name)
        for vertex_index, weight in assignments:
            if weight > 1e-8:
                group.add([vertex_index], weight, "REPLACE")


def reweight_leg_shell(obj: bpy.types.Object, side_name: str, upper: bool) -> None:
    upper_bone = f"UpperLeg_{side_name}"
    lower_bone = f"LowerLeg_{side_name}"
    weights: dict[str, list[tuple[int, float]]] = {
        "Hips": [],
        upper_bone: [],
        lower_bone: [],
    }
    for vertex in obj.data.vertices:
        z = vertex.co.z
        if upper:
            # The waistband follows Hips, then transitions quickly to UpperLeg.
            hips_weight = 0.62 * clamp((z - 0.585) / 0.19, 0.0, 1.0)
            upper_weight = 1.0 - hips_weight
            weights["Hips"].append((vertex.index, hips_weight))
            weights[upper_bone].append((vertex.index, upper_weight))
        else:
            # Only the knee edge receives a small UpperLeg contribution.
            upper_weight = 0.30 * clamp((z - 0.285) / 0.115, 0.0, 1.0)
            lower_weight = 1.0 - upper_weight
            weights[upper_bone].append((vertex.index, upper_weight))
            weights[lower_bone].append((vertex.index, lower_weight))
    replace_vertex_weights(obj, weights)


def fitted_leg_shell(name, side, rings, material, armature, body, segments=48):
    """Replace the oversized first pass with a controlled wide-leg profile."""
    side_name = "L" if side < 0 else "R"
    if "UpperLeg" in name:
        rings = [
            (0.782, 0.012, 0.145, 0.082, 0.078),
            (0.714, 0.014, 0.151, 0.086, 0.082),
            (0.623, 0.017, 0.159, 0.090, 0.087),
            (0.526, 0.021, 0.168, 0.094, 0.091),
            (0.458, 0.027, 0.174, 0.096, 0.094),
        ]
        upper = True
    elif "LowerLeg" in name:
        rings = [
            (0.394, 0.035, 0.178, 0.091, 0.089),
            (0.315, 0.034, 0.187, 0.095, 0.093),
            (0.226, 0.033, 0.198, 0.099, 0.097),
            (0.137, 0.032, 0.211, 0.103, 0.101),
            (0.066, 0.035, 0.224, 0.107, 0.105),
        ]
        upper = False
    else:
        upper = False

    obj = _original_asymmetric_leg_shell(
        name,
        side,
        rings,
        material,
        armature,
        body,
        segments=segments,
    )
    reweight_leg_shell(obj, side_name, upper)
    return obj


def fitted_waist_band(
    name,
    center_x,
    radius_x,
    radius_y,
    z,
    width,
    material,
    armature,
    body,
    **kwargs,
):
    if name == "Primary_Waist_Belt":
        radius_x, radius_y, z, width = 0.148, 0.096, 0.785, 0.013
    elif name == "Asymmetric_Waist_Belt":
        radius_x, radius_y, z, width = 0.153, 0.100, 0.797, 0.010
        kwargs["slope"] = 0.010
    elif name.startswith("Knee_Strap_"):
        # Keep straps close to the redesigned upper/lower-leg seam.
        center_x = math.copysign(0.1065, center_x)
        radius_x = 0.076
        radius_y = 0.096
        z = 0.424 if name.endswith("_1") else 0.405
        width = 0.009
    return _original_flat_ellipse_band(
        name,
        center_x,
        radius_x,
        radius_y,
        z,
        width,
        material,
        armature,
        body,
        **kwargs,
    )


def trimmed_path_ribbon(name, points, width, material, armature, body):
    adjusted = list(points)
    if name.startswith("Hip_Cutout_Strap_"):
        adjusted = [
            (
                math.copysign(min(abs(x), 0.151), x),
                y * 0.86,
                z - 0.003,
            )
            for x, y, z in adjusted
        ]
        width = min(width, 0.0065)
    elif name.startswith("Knee_Zipper_"):
        adjusted = [
            (
                math.copysign(min(abs(x), 0.171), x),
                y * 0.84,
                z - 0.012,
            )
            for x, y, z in adjusted
        ]
        width = min(width, 0.0032)
    elif name == "Long_Center_Zipper":
        adjusted = [(x, y * 0.86, z) for x, y, z in adjusted]
    return _original_flat_path_ribbon(
        name,
        adjusted,
        width,
        material,
        armature,
        body,
    )


def fitted_rounded_box(
    name,
    location,
    scale,
    material,
    armature,
    body,
    **kwargs,
):
    x, y, z = location
    sx, sy, sz = scale
    if name.startswith("Cargo_Pocket_Flap_"):
        x = math.copysign(0.166, x)
        y = -0.037
        z = 0.610
        sx, sy, sz = 0.043, 0.0045, 0.013
        kwargs["bevel"] = 0.0025
    elif name.startswith("Cargo_Pocket_"):
        x = math.copysign(0.165, x)
        y = -0.018
        z = 0.560
        sx, sy, sz = 0.039, 0.014, 0.052
        kwargs["bevel"] = 0.004
    return _original_rounded_box(
        name,
        (x, y, z),
        (sx, sy, sz),
        material,
        armature,
        body,
        **kwargs,
    )


def fitted_buckle(name, center, width, height, material, armature, body):
    x, y, z = center
    if name == "Front_Belt_Buckle":
        center, width, height = (0.064, -0.101, 0.789), 0.012, 0.011
    elif name == "Side_Belt_Buckle":
        center, width, height = (-0.139, -0.038, 0.806), 0.010, 0.009
    elif name == "Center_Zip_Pull":
        center, width, height = (0.0, -0.107, 0.614), 0.005, 0.008
    elif name.startswith("Knee_Zip_Pull_"):
        center = (math.copysign(0.172, x), y * 0.84, z - 0.012)
        width, height = 0.0045, 0.0065
    return _original_buckle(
        name,
        center,
        width,
        height,
        material,
        armature,
        body,
    )


def tune_material(material: bpy.types.Material, *, base, roughness, metallic=0.0) -> None:
    material.diffuse_color = (*base, 1.0)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if shader is None:
        return
    if "Base Color" in shader.inputs:
        shader.inputs["Base Color"].default_value = (*base, 1.0)
    if "Roughness" in shader.inputs:
        shader.inputs["Roughness"].default_value = roughness
    if "Metallic" in shader.inputs:
        shader.inputs["Metallic"].default_value = metallic


def create_outfit_with_fitted_pelvis(body, armature, fabric, strap, metal):
    """Create a fitted pelvis and retain intentional outer-hip cutouts."""
    tune_material(fabric, base=(0.012, 0.014, 0.020), roughness=0.63)
    tune_material(strap, base=(0.006, 0.007, 0.010), roughness=0.42)
    tune_material(metal, base=(0.22, 0.24, 0.28), roughness=0.24, metallic=0.88)

    objects = _original_create_outfit(body, armature, fabric, strap, metal)

    front = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Front_Pelvis",
        lambda point: (
            0.520 <= point.z <= 0.790
            and point.y < 0.005
            and abs(point.x)
            <= 0.026 + max(0.0, point.z - 0.520) * 0.37
        ),
        fabric,
        0.0047,
    )
    back = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Back_Yoke",
        lambda point: (
            0.515 <= point.z <= 0.790
            and point.y >= -0.007
            and abs(point.x)
            <= 0.032 + max(0.0, point.z - 0.515) * 0.34
        ),
        fabric,
        0.0047,
    )
    build.finish_skinned(front, body)
    build.finish_skinned(back, body)
    return [front, back, *objects]


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
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)


build.mesh_object = mesh_object_with_uv
build.asymmetric_leg_shell = fitted_leg_shell
build.flat_ellipse_band = fitted_waist_band
build.flat_path_ribbon = trimmed_path_ribbon
build.rounded_box = fitted_rounded_box
build.buckle = fitted_buckle
build.create_outfit = create_outfit_with_fitted_pelvis

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        save_distribution_blend()
    raise SystemExit(exit_code)
