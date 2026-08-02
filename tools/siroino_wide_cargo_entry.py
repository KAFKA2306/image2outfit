#!/usr/bin/env python3
"""Production entry point for the Siroino Wide Cargo product.

This layer keeps the reproducible base generator while enforcing a continuous,
avatar-fitted wide-pants silhouette suitable for VRChat:

- close low-rise waist instead of floating rings,
- continuous front/back crotch and upper-thigh coverage,
- broad frontal leg width with a controlled side profile,
- intentional but compact knee openings,
- hems above the floor and shoes,
- smaller pockets and hardware,
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
            hips_weight = 0.58 * clamp((z - 0.59) / 0.18, 0.0, 1.0)
            upper_weight = 1.0 - hips_weight
            weights["Hips"].append((vertex.index, hips_weight))
            weights[upper_bone].append((vertex.index, upper_weight))
        else:
            upper_weight = 0.26 * clamp((z - 0.30) / 0.10, 0.0, 1.0)
            lower_weight = 1.0 - upper_weight
            weights[upper_bone].append((vertex.index, upper_weight))
            weights[lower_bone].append((vertex.index, lower_weight))
    replace_vertex_weights(obj, weights)


def fitted_leg_shell(name, side, rings, material, armature, body, segments=48):
    """Produce wide-from-front, thin-in-profile pant legs."""
    side_name = "L" if side < 0 else "R"
    if "UpperLeg" in name:
        rings = [
            (0.782, 0.006, 0.148, 0.068, 0.066),
            (0.714, 0.008, 0.154, 0.070, 0.068),
            (0.623, 0.010, 0.164, 0.073, 0.071),
            (0.526, 0.014, 0.174, 0.076, 0.074),
            (0.458, 0.020, 0.182, 0.078, 0.076),
        ]
        upper = True
    elif "LowerLeg" in name:
        rings = [
            (0.404, 0.027, 0.184, 0.073, 0.071),
            (0.320, 0.025, 0.195, 0.076, 0.074),
            (0.231, 0.023, 0.207, 0.079, 0.077),
            (0.142, 0.022, 0.219, 0.082, 0.080),
            (0.072, 0.028, 0.228, 0.084, 0.082),
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
        radius_x, radius_y, z, width = 0.136, 0.088, 0.783, 0.012
    elif name == "Asymmetric_Waist_Belt":
        radius_x, radius_y, z, width = 0.141, 0.091, 0.794, 0.009
        kwargs["slope"] = 0.008
    elif name.startswith("Knee_Strap_"):
        center_x = math.copysign(0.105, center_x)
        radius_x = 0.080
        radius_y = 0.078
        if name.endswith("_1"):
            z, width = 0.432, 0.008
        else:
            z, width = 0.411, 0.0045
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
            (math.copysign(min(abs(x), 0.145), x), y * 0.72, z - 0.004)
            for x, y, z in adjusted
        ]
        width = min(width, 0.0058)
    elif name.startswith("Knee_Zipper_"):
        adjusted = [
            (math.copysign(min(abs(x), 0.177), x), y * 0.70, z - 0.011)
            for x, y, z in adjusted
        ]
        width = min(width, 0.0030)
    elif name == "Long_Center_Zipper":
        adjusted = [(x, y * 0.73, z) for x, y, z in adjusted]
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
        x = math.copysign(0.172, x)
        y = -0.029
        z = 0.600
        sx, sy, sz = 0.039, 0.0038, 0.011
        kwargs["bevel"] = 0.0022
    elif name.startswith("Cargo_Pocket_"):
        x = math.copysign(0.171, x)
        y = -0.014
        z = 0.552
        sx, sy, sz = 0.035, 0.010, 0.047
        kwargs["bevel"] = 0.0035
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
        center, width, height = (0.058, -0.090, 0.787), 0.010, 0.009
    elif name == "Side_Belt_Buckle":
        center, width, height = (-0.131, -0.032, 0.802), 0.009, 0.008
    elif name == "Center_Zip_Pull":
        center, width, height = (0.0, -0.092, 0.614), 0.0045, 0.007
    elif name.startswith("Knee_Zip_Pull_"):
        center = (math.copysign(0.178, x), y * 0.70, z - 0.011)
        width, height = 0.004, 0.006
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
    """Close the crotch while retaining small intentional outer-hip cutouts."""
    tune_material(fabric, base=(0.010, 0.012, 0.018), roughness=0.68)
    tune_material(strap, base=(0.004, 0.005, 0.008), roughness=0.39)
    tune_material(metal, base=(0.24, 0.26, 0.31), roughness=0.21, metallic=0.90)

    objects = _original_create_outfit(body, armature, fabric, strap, metal)

    # The first-pass pants exposed the complete inner thigh and read as chaps.
    # These body-derived panels close the front and back through the crotch and
    # overlap the upper-leg shells enough to remain continuous in animation.
    front = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Front_Pelvis",
        lambda point: (
            0.445 <= point.z <= 0.790
            and point.y < 0.012
            and abs(point.x)
            <= 0.094 + max(0.0, point.z - 0.445) * 0.12
        ),
        fabric,
        0.0052,
    )
    back = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Back_Yoke",
        lambda point: (
            0.442 <= point.z <= 0.790
            and point.y >= -0.014
            and abs(point.x)
            <= 0.100 + max(0.0, point.z - 0.442) * 0.10
        ),
        fabric,
        0.0052,
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
