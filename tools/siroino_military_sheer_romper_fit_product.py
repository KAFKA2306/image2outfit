#!/usr/bin/env python3
"""Generate a SiroinoSotai_PC-fitted military romper and measured fit evidence."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_target_fit as fit  # noqa: E402

ORIGINAL_EXTRACT = fit.extract_surface
ORIGINAL_FINISH = fit.finish_skinned
ORIGINAL_SCENE = fit.configure_scene
ORIGINAL_SKIN = fit.assign_review_skin
ORIGINAL_FABRIC = fit.base.fabric_material

ALIASES = {
    "neck": ("Neck", "Neck.1", "J_Bip_C_Neck"),
    "upper_arm_l": ("UpperArm_L", "UpperArm_L.1", "LeftUpperArm", "J_Bip_L_UpperArm"),
    "upper_arm_r": ("UpperArm_R", "UpperArm_R.1", "RightUpperArm", "J_Bip_R_UpperArm"),
}


def bounds(body: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def bone(armature: bpy.types.Object, semantic: str):
    for name in ALIASES[semantic]:
        found = armature.data.bones.get(name)
        if found is not None:
            return found
    names = {item.name.lower(): item for item in armature.data.bones}
    for name in ALIASES[semantic]:
        found = names.get(name.lower())
        if found is not None:
            return found
    return None


def segment(armature: bpy.types.Object, semantic: str) -> tuple[Vector, Vector] | None:
    item = bone(armature, semantic)
    if item is None:
        return None
    return (
        armature.matrix_world @ item.head_local,
        armature.matrix_world @ item.tail_local,
    )


def capsule(start: Vector, end: Vector, radius: float) -> Callable[[Vector], bool]:
    axis = end - start
    denominator = axis.length_squared

    def predicate(point: Vector) -> bool:
        if denominator <= 1e-12:
            return (point - start).length <= radius
        t = max(0.0, min(1.0, (point - start).dot(axis) / denominator))
        return (point - (start + axis * t)).length <= radius

    return predicate


def collar_region(body: bpy.types.Object, armature: bpy.types.Object) -> Callable[[Vector], bool]:
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    neck = segment(armature, "neck")
    if neck is not None:
        start, end = neck
        center = (start + end) * 0.5
        return lambda point: (
            min(start.z, end.z) - height * 0.018
            <= point.z
            <= max(start.z, end.z) + height * 0.040
            and abs(point.x - center.x) <= height * 0.075
            and abs(point.y - center.y) <= height * 0.060
        )
    center = (minimum + maximum) * 0.5
    return lambda point: (
        minimum.z + height * 0.83 <= point.z <= minimum.z + height * 0.95
        and abs(point.x - center.x) <= height * 0.075
        and abs(point.y - center.y) <= height * 0.060
    )


def finish(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
    *,
    fit_audit: bool,
) -> bpy.types.Object:
    world = obj.matrix_world.copy()
    result = ORIGINAL_FINISH(
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
):
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


def skin(body: bpy.types.Object) -> None:
    ORIGINAL_SKIN(body)
    for polygon in body.data.polygons:
        polygon.material_index = 0


def fabric(textures: dict[str, Path]) -> bpy.types.Material:
    material = ORIGINAL_FABRIC(textures)
    shader = next(
        (node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"),
        None,
    )
    if shader is not None:
        for socket_name in ("Base Color", "Roughness", "Normal"):
            socket = shader.inputs.get(socket_name)
            if socket is not None:
                for link in list(socket.links):
                    material.node_tree.links.remove(link)
        shader.inputs["Base Color"].default_value = (0.002, 0.003, 0.005, 1.0)
        shader.inputs["Roughness"].default_value = 0.72
        if "Specular IOR Level" in shader.inputs:
            shader.inputs["Specular IOR Level"].default_value = 0.18
        if "Sheen Weight" in shader.inputs:
            shader.inputs["Sheen Weight"].default_value = 0.06
    material.diffuse_color = (0.002, 0.003, 0.005, 1.0)
    return material


def force_clearance(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
    clearance: float = 0.007,
    iterations: int = 4,
) -> None:
    """Push audited garment bases outward until the active target shape clears."""
    for _ in range(iterations):
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        tree = BVHTree.FromObject(body, depsgraph)
        body_inverse = body.matrix_world.inverted()
        body_to_world = body.matrix_world.to_3x3()
        changed = 0
        for obj in garments:
            if obj.type != "MESH" or not bool(obj.get("image2outfit_fit_audit", False)):
                continue
            evaluated = obj.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh()
            try:
                count = min(len(mesh.vertices), len(obj.data.vertices))
                world_to_local = obj.matrix_world.inverted().to_3x3()
                for index in range(count):
                    world = evaluated.matrix_world @ mesh.vertices[index].co
                    point = body_inverse @ world
                    nearest = tree.find_nearest(point)
                    if nearest[0] is None or nearest[1] is None:
                        continue
                    signed = float((point - nearest[0]).dot(nearest[1]))
                    if signed >= clearance:
                        continue
                    correction_body = nearest[1].normalized() * (clearance - signed)
                    correction_local = world_to_local @ (body_to_world @ correction_body)
                    obj.data.vertices[index].co += correction_local
                    changed += 1
            finally:
                evaluated.to_mesh_clear()
            obj.data.update()
        if changed == 0:
            break


def hardware(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    gold: bpy.types.Material,
    cloth: bpy.types.Material,
    values: dict[str, float],
    center: Vector,
    height: float,
    torso_width: float,
    front: float,
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    z = lambda ratio: center.z - height * 0.5 + height * ratio
    objects.append(
        fit.add_box(
            "Military_Gold_Nameplate",
            (center.x + torso_width * 0.22, front, z(0.73)),
            (height * 0.034, height * 0.004, height * 0.010),
            gold,
            body,
            armature,
            values,
            bevel=height * 0.0025,
        )
    )
    objects.append(
        fit.add_box(
            "Military_Belt_Buckle",
            (center.x + torso_width * 0.06, front, z(0.555)),
            (height * 0.021, height * 0.0045, height * 0.025),
            gold,
            body,
            armature,
            values,
            bevel=height * 0.0025,
        )
    )
    for index, ratio in enumerate((0.80, 0.72, 0.63), start=1):
        objects.append(
            fit.add_button(
                f"Military_Front_Button_{index}",
                (center.x - torso_width * 0.24, front, z(ratio)),
                (height * 0.008, height * 0.004, height * 0.008),
                gold,
                body,
                armature,
                values,
            )
        )
    for side, semantic in (("L", "upper_arm_l"), ("R", "upper_arm_r")):
        arm = segment(armature, semantic)
        if arm is None:
            continue
        shoulder = arm[0]
        sign = 1.0 if shoulder.x >= center.x else -1.0
        objects.append(
            fit.add_box(
                f"Military_Epaulette_{side}",
                (
                    shoulder.x - sign * height * 0.018,
                    shoulder.y - height * 0.010,
                    shoulder.z + height * 0.008,
                ),
                (height * 0.040, height * 0.022, height * 0.005),
                cloth,
                body,
                armature,
                values,
                bevel=height * 0.0025,
            )
        )
        objects.append(
            fit.add_button(
                f"Military_Epaulette_Button_{side}",
                (
                    shoulder.x - sign * height * 0.014,
                    shoulder.y - height * 0.032,
                    shoulder.z + height * 0.012,
                ),
                (height * 0.007, height * 0.0035, height * 0.007),
                gold,
                body,
                armature,
                values,
            )
        )
    return objects


def build(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    cloth: bpy.types.Material,
    sheer: bpy.types.Material,
    gold: bpy.types.Material,
    values: dict[str, float],
) -> list[bpy.types.Object]:
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    center = (minimum + maximum) * 0.5
    z = lambda ratio: minimum.z + height * ratio

    shoulders = [
        item[0]
        for semantic in ("upper_arm_l", "upper_arm_r")
        if (item := segment(armature, semantic)) is not None
    ]
    torso_width = (
        max(abs(point.x - center.x) for point in shoulders) * 1.04
        if shoulders
        else height * 0.15
    )
    torso_width = max(height * 0.125, min(torso_width, height * 0.20))
    front_candidates = [
        (body.matrix_world @ vertex.co).y
        for vertex in body.data.vertices
        if z(0.64) <= (body.matrix_world @ vertex.co).z <= z(0.72)
        and abs((body.matrix_world @ vertex.co).x - center.x) <= torso_width
    ]
    front = (min(front_candidates) if front_candidates else minimum.y) - height * 0.018

    objects: list[bpy.types.Object] = []
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Opaque_Bodice",
            lambda point: (
                z(0.54) <= point.z <= z(0.93)
                and abs(point.x - center.x) <= torso_width
                and (
                    point.y <= center.y + height * 0.010
                    or point.z <= z(0.60)
                    or abs(point.x - center.x) >= torso_width * 0.72
                )
            ),
            cloth,
            values,
            offset=0.018,
            thickness=0.0025,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Sheer_Back",
            lambda point: (
                z(0.60) <= point.z <= z(0.91)
                and point.y > center.y
                and abs(point.x - center.x) < torso_width * 0.75
            ),
            sheer,
            values,
            offset=0.013,
            thickness=0.0008,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Fitted_Shorts",
            lambda point: z(0.43) <= point.z <= z(0.56),
            cloth,
            values,
            offset=0.020,
            thickness=0.0028,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Asymmetric_Front_Flap",
            lambda point: (
                z(0.43) <= point.z <= z(0.565)
                and point.y <= center.y
                and point.x <= center.x + torso_width * 0.55
            ),
            cloth,
            values,
            offset=0.029,
            thickness=0.0022,
            fit_audit=False,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Standing_Collar",
            collar_region(body, armature),
            cloth,
            values,
            offset=0.020,
            thickness=0.0024,
        )
    )
    for side, semantic in (("L", "upper_arm_l"), ("R", "upper_arm_r")):
        arm = segment(armature, semantic)
        if arm is None:
            continue
        start, end = arm
        end = start + (end - start) * 0.62
        objects.append(
            fit.extract_surface(
                body,
                armature,
                f"Military_Sleeve_{side}",
                capsule(start, end, height * 0.075),
                cloth,
                values,
                offset=0.016,
                thickness=0.0023,
            )
        )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Waist_Belt",
            lambda point: z(0.545) <= point.z <= z(0.568),
            cloth,
            values,
            offset=0.025,
            thickness=0.0030,
            fit_audit=False,
        )
    )
    objects.extend(
        hardware(
            body,
            armature,
            gold,
            cloth,
            values,
            center,
            height,
            torso_width,
            front,
        )
    )
    force_clearance(body, objects)
    return objects


def scene(body: bpy.types.Object) -> bpy.types.Object:
    camera = ORIGINAL_SCENE(body)
    bpy.context.scene.render.resolution_x = 512
    bpy.context.scene.render.resolution_y = 512
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            obj.data.energy *= 0.28
    return camera


def main() -> int:
    fit.finish_skinned = finish
    fit.extract_surface = extract
    fit.assign_review_skin = skin
    fit.base.fabric_material = fabric
    fit.build_outfit = build
    fit.configure_scene = scene
    fit.REVISION = "siroino-pc-measured-fit-v11"
    return fit.main()


if __name__ == "__main__":
    raise SystemExit(main())
