#!/usr/bin/env python3
"""Build the military romper directly on the actual SiroinoSotai_PC surface."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Callable, Iterable

import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_target_fit as fit  # noqa: E402

ORIGINAL_EXTRACT = fit.extract_surface
ORIGINAL_FINISH_SKINNED = fit.finish_skinned
ORIGINAL_CONFIGURE_SCENE = fit.configure_scene
ORIGINAL_ASSIGN_REVIEW_SKIN = fit.assign_review_skin
ORIGINAL_FABRIC_MATERIAL = fit.base.fabric_material

BONE_ALIASES = {
    "neck": ("Neck", "Neck.1", "J_Bip_C_Neck"),
    "chest": ("Chest", "Chest.1", "UpperChest", "J_Bip_C_Chest"),
    "upper_arm_l": ("UpperArm_L", "UpperArm_L.1", "LeftUpperArm", "J_Bip_L_UpperArm"),
    "upper_arm_r": ("UpperArm_R", "UpperArm_R.1", "RightUpperArm", "J_Bip_R_UpperArm"),
}


def world_bounds(body: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    return (
        Vector((
            min(point.x for point in points),
            min(point.y for point in points),
            min(point.z for point in points),
        )),
        Vector((
            max(point.x for point in points),
            max(point.y for point in points),
            max(point.z for point in points),
        )),
    )


def find_bone(armature: bpy.types.Object, semantic: str):
    aliases = BONE_ALIASES[semantic]
    for name in aliases:
        bone = armature.data.bones.get(name)
        if bone is not None:
            return bone
    lowered = {bone.name.lower(): bone for bone in armature.data.bones}
    for name in aliases:
        bone = lowered.get(name.lower())
        if bone is not None:
            return bone
    return None


def bone_segment(armature: bpy.types.Object, semantic: str) -> tuple[Vector, Vector] | None:
    bone = find_bone(armature, semantic)
    if bone is None:
        return None
    return (
        armature.matrix_world @ bone.head_local,
        armature.matrix_world @ bone.tail_local,
    )


def point_segment_distance(point: Vector, start: Vector, end: Vector) -> tuple[float, float]:
    axis = end - start
    denominator = axis.length_squared
    if denominator <= 1e-12:
        return (point - start).length, 0.0
    t = max(0.0, min(1.0, (point - start).dot(axis) / denominator))
    nearest = start + axis * t
    return (point - nearest).length, t


def capsule_predicate(
    start: Vector,
    end: Vector,
    radius: float,
    *,
    t_min: float = 0.0,
    t_max: float = 1.0,
) -> Callable[[Vector], bool]:
    def predicate(point: Vector) -> bool:
        distance, t = point_segment_distance(point, start, end)
        return t_min <= t <= t_max and distance <= radius

    return predicate


def neck_predicate(body: bpy.types.Object, armature: bpy.types.Object) -> Callable[[Vector], bool]:
    minimum, maximum = world_bounds(body)
    height = maximum.z - minimum.z
    segment = bone_segment(armature, "neck")
    if segment is not None:
        start, end = segment
        center = (start + end) * 0.5
        low = min(start.z, end.z) - height * 0.020
        high = max(start.z, end.z) + height * 0.035
        radius_x = height * 0.070
        radius_y = height * 0.055
        return lambda point: (
            low <= point.z <= high
            and abs(point.x - center.x) <= radius_x
            and abs(point.y - center.y) <= radius_y
        )
    center = (minimum + maximum) * 0.5
    return lambda point: (
        minimum.z + height * 0.82 <= point.z <= minimum.z + height * 0.94
        and abs(point.x - center.x) <= height * 0.075
        and abs(point.y - center.y) <= height * 0.060
    )


def front_y_at(body: bpy.types.Object, z: float, band: float, half_width: float) -> float:
    minimum, maximum = world_bounds(body)
    center_x = (minimum.x + maximum.x) * 0.5
    values = [
        (body.matrix_world @ vertex.co).y
        for vertex in body.data.vertices
        if abs((body.matrix_world @ vertex.co).z - z) <= band
        and abs((body.matrix_world @ vertex.co).x - center_x) <= half_width
    ]
    return min(values) if values else minimum.y


def mirror_target_parent_space(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
    *,
    fit_audit: bool,
) -> bpy.types.Object:
    world = obj.matrix_world.copy()
    result = ORIGINAL_FINISH_SKINNED(
        obj,
        body,
        armature,
        values,
        fit_audit=fit_audit,
    )
    result.parent = body.parent
    result.parent_type = body.parent_type
    result.parent_bone = body.parent_bone
    if body.parent is not None:
        result.matrix_parent_inverse = body.matrix_parent_inverse.copy()
    result.matrix_world = world
    bpy.context.view_layer.update()
    return result


def robust_extract(
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
):
    minimum_offsets = {
        "Military_Opaque_Bodice": 0.030,
        "Military_Sheer_Back": 0.016,
        "Military_Fitted_Shorts": 0.026,
        "Military_Asymmetric_Front_Flap": 0.034,
        "Military_Standing_Collar": 0.032,
        "Military_Sleeve_L": 0.018,
        "Military_Sleeve_R": 0.018,
        "Military_Waist_Belt": 0.030,
    }
    offset = max(offset, minimum_offsets.get(name, offset))
    if name == "Military_Asymmetric_Front_Flap":
        fit_audit = False
    return ORIGINAL_EXTRACT(
        body,
        armature,
        name,
        predicate,
        material,
        values,
        offset=offset,
        thickness=thickness,
        fit_audit=fit_audit,
    )


def assign_review_skin(body: bpy.types.Object) -> None:
    ORIGINAL_ASSIGN_REVIEW_SKIN(body)
    for polygon in body.data.polygons:
        polygon.material_index = 0


def fabric_material(textures: dict[str, Path]) -> bpy.types.Material:
    material = ORIGINAL_FABRIC_MATERIAL(textures)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
    if shader is not None:
        for input_name in ("Base Color", "Roughness", "Normal"):
            socket = shader.inputs.get(input_name)
            if socket is not None:
                for link in list(socket.links):
                    links.remove(link)
        shader.inputs["Base Color"].default_value = (0.003, 0.004, 0.006, 1.0)
        shader.inputs["Roughness"].default_value = 0.68
        if "Specular IOR Level" in shader.inputs:
            shader.inputs["Specular IOR Level"].default_value = 0.22
        if "Sheen Weight" in shader.inputs:
            shader.inputs["Sheen Weight"].default_value = 0.08
        if "Coat Weight" in shader.inputs:
            shader.inputs["Coat Weight"].default_value = 0.0
    material.diffuse_color = (0.003, 0.004, 0.006, 1.0)
    return material


def add_hardware(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    gold: bpy.types.Material,
    fabric: bpy.types.Material,
    values: dict[str, float],
    *,
    center: Vector,
    height: float,
    torso_half_width: float,
    front_y: float,
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    chest_z = center.z + height * 0.165
    waist_z = center.z - height * 0.095
    front = front_y - height * 0.018
    objects.append(
        fit.add_box(
            "Military_Gold_Nameplate",
            (center.x + torso_half_width * 0.35, front, chest_z),
            (height * 0.035, height * 0.0045, height * 0.010),
            gold,
            body,
            armature,
            values,
            bevel=height * 0.003,
        )
    )
    objects.append(
        fit.add_box(
            "Military_Belt_Buckle",
            (center.x + torso_half_width * 0.10, front - height * 0.004, waist_z),
            (height * 0.022, height * 0.005, height * 0.028),
            gold,
            body,
            armature,
            values,
            bevel=height * 0.003,
        )
    )
    for index, z in enumerate(
        (center.z + height * 0.245, center.z + height * 0.175, center.z + height * 0.035),
        start=1,
    ):
        objects.append(
            fit.add_button(
                f"Military_Front_Button_{index}",
                (center.x - torso_half_width * 0.34, front, z),
                (height * 0.009, height * 0.0045, height * 0.009),
                gold,
                body,
                armature,
                values,
            )
        )

    left_segment = bone_segment(armature, "upper_arm_l")
    right_segment = bone_segment(armature, "upper_arm_r")
    for side, segment in (("L", left_segment), ("R", right_segment)):
        if segment is None:
            continue
        shoulder = segment[0]
        sign = 1.0 if shoulder.x >= center.x else -1.0
        objects.append(
            fit.add_box(
                f"Military_Epaulette_{side}",
                (
                    shoulder.x - sign * height * 0.018,
                    shoulder.y - height * 0.012,
                    shoulder.z + height * 0.010,
                ),
                (height * 0.045, height * 0.026, height * 0.006),
                fabric,
                body,
                armature,
                values,
                bevel=height * 0.003,
            )
        )
        objects.append(
            fit.add_button(
                f"Military_Epaulette_Button_{side}",
                (
                    shoulder.x - sign * height * 0.015,
                    shoulder.y - height * 0.040,
                    shoulder.z + height * 0.014,
                ),
                (height * 0.008, height * 0.004, height * 0.008),
                gold,
                body,
                armature,
                values,
            )
        )

    if left_segment is not None:
        shoulder = left_segment[0]
        anchor = Vector((
            center.x + torso_half_width * 0.48,
            front,
            center.z + height * 0.245,
        ))
        for index, sag in enumerate((0.035, 0.055, 0.075), start=1):
            mid = (shoulder + anchor) * 0.5
            mid.y -= height * sag
            mid.z -= height * sag * 0.55
            objects.append(
                fit.add_chain(
                    f"Military_Shoulder_Chain_{index}",
                    [tuple(shoulder), tuple(mid), tuple(anchor)],
                    gold,
                    body,
                    armature,
                    values,
                )
            )
    return objects


def build_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    sheer: bpy.types.Material,
    gold: bpy.types.Material,
    values: dict[str, float],
) -> list[bpy.types.Object]:
    minimum, maximum = world_bounds(body)
    height = maximum.z - minimum.z
    center = (minimum + maximum) * 0.5

    shoulder_points = []
    for semantic in ("upper_arm_l", "upper_arm_r"):
        segment = bone_segment(armature, semantic)
        if segment is not None:
            shoulder_points.append(segment[0])
    torso_half_width = (
        max(abs(point.x - center.x) for point in shoulder_points) * 1.06
        if shoulder_points
        else height * 0.145
    )
    torso_half_width = max(height * 0.125, min(torso_half_width, height * 0.205))
    front_y = front_y_at(
        body,
        minimum.z + height * 0.64,
        height * 0.045,
        torso_half_width,
    )

    z = lambda ratio: minimum.z + height * ratio
    opaque_back_bottom = z(0.545)
    objects: list[bpy.types.Object] = []
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Opaque_Bodice",
            lambda point: (
                z(0.49) <= point.z <= z(0.88)
                and abs(point.x - center.x) <= torso_half_width
                and (
                    point.y <= center.y + height * 0.008
                    or point.z <= opaque_back_bottom
                    or abs(point.x - center.x) >= torso_half_width * 0.70
                )
            ),
            fabric,
            values,
            offset=0.030,
            thickness=0.0025,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Sheer_Back",
            lambda point: (
                z(0.55) <= point.z <= z(0.875)
                and point.y > center.y
                and abs(point.x - center.x) < torso_half_width * 0.74
            ),
            sheer,
            values,
            offset=0.016,
            thickness=0.0008,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Fitted_Shorts",
            lambda point: z(0.335) <= point.z <= z(0.525),
            fabric,
            values,
            offset=0.026,
            thickness=0.0028,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Asymmetric_Front_Flap",
            lambda point: (
                z(0.35) <= point.z <= z(0.525)
                and point.y <= center.y
                and point.x <= center.x + torso_half_width * 0.55
            ),
            fabric,
            values,
            offset=0.034,
            thickness=0.0022,
            fit_audit=False,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Standing_Collar",
            neck_predicate(body, armature),
            fabric,
            values,
            offset=0.032,
            thickness=0.0024,
        )
    )
    for side, semantic in (("L", "upper_arm_l"), ("R", "upper_arm_r")):
        segment = bone_segment(armature, semantic)
        if segment is None:
            continue
        start, end = segment
        shortened_end = start + (end - start) * 0.63
        objects.append(
            fit.extract_surface(
                body,
                armature,
                f"Military_Sleeve_{side}",
                capsule_predicate(
                    start,
                    shortened_end,
                    height * 0.075,
                    t_min=0.0,
                    t_max=1.0,
                ),
                fabric,
                values,
                offset=0.018,
                thickness=0.0023,
            )
        )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Waist_Belt",
            lambda point: z(0.505) <= point.z <= z(0.535),
            fabric,
            values,
            offset=0.030,
            thickness=0.0030,
            fit_audit=False,
        )
    )
    objects.extend(
        add_hardware(
            body,
            armature,
            gold,
            fabric,
            values,
            center=center,
            height=height,
            torso_half_width=torso_half_width,
            front_y=front_y,
        )
    )
    return objects


def configure_review_scene(body: bpy.types.Object) -> bpy.types.Object:
    camera = ORIGINAL_CONFIGURE_SCENE(body)
    scene = bpy.context.scene
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.view_settings.look = "AgX - Medium High Contrast"
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            obj.data.energy *= 0.32
    return camera


def main() -> int:
    fit.finish_skinned = mirror_target_parent_space
    fit.extract_surface = robust_extract
    fit.assign_review_skin = assign_review_skin
    fit.base.fabric_material = fabric_material
    fit.build_outfit = build_outfit
    fit.configure_scene = configure_review_scene
    fit.REVISION = "siroino-pc-semantic-fit-v10"
    return fit.main()


if __name__ == "__main__":
    raise SystemExit(main())
