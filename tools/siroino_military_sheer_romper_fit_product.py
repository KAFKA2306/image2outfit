#!/usr/bin/env python3
"""Generate a measured SiroinoSotai_PC fit for the military romper."""
from __future__ import annotations

import json
import statistics
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

ORIGINAL_FINISH = fit.finish_skinned
ORIGINAL_SCENE = fit.configure_scene
ORIGINAL_SKIN = fit.assign_review_skin
ORIGINAL_FABRIC = fit.base.fabric_material

ALIASES = {
    "hips": ("Hips", "Hips.1", "J_Bip_C_Hips"),
    "chest": ("Chest", "Chest.1", "UpperChest", "J_Bip_C_Chest"),
    "neck": ("Neck", "Neck.1", "J_Bip_C_Neck"),
    "upper_arm_l": (
        "UpperArm_L",
        "UpperArm_L.1",
        "LeftUpperArm",
        "J_Bip_L_UpperArm",
    ),
    "upper_arm_r": (
        "UpperArm_R",
        "UpperArm_R.1",
        "RightUpperArm",
        "J_Bip_R_UpperArm",
    ),
}


def bounds(body: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def resolve_bone(armature: bpy.types.Object, semantic: str):
    for name in ALIASES[semantic]:
        found = armature.data.bones.get(name)
        if found is not None:
            return found
    lowered = {item.name.lower(): item for item in armature.data.bones}
    for name in ALIASES[semantic]:
        found = lowered.get(name.lower())
        if found is not None:
            return found
    return None


def segment(
    armature: bpy.types.Object,
    semantic: str,
) -> tuple[Vector, Vector] | None:
    item = resolve_bone(armature, semantic)
    if item is None:
        return None
    return (
        armature.matrix_world @ item.head_local,
        armature.matrix_world @ item.tail_local,
    )


def capsule(
    start: Vector,
    end: Vector,
    radius: float,
) -> Callable[[Vector], bool]:
    axis = end - start
    denominator = axis.length_squared

    def predicate(point: Vector) -> bool:
        if denominator <= 1e-12:
            return (point - start).length <= radius
        t = max(0.0, min(1.0, (point - start).dot(axis) / denominator))
        return (point - (start + axis * t)).length <= radius

    return predicate


def collar_region(
    body: bpy.types.Object,
    armature: bpy.types.Object,
) -> Callable[[Vector], bool]:
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    neck = segment(armature, "neck")
    if neck is not None:
        start, end = neck
        center = (start + end) * 0.5
        return lambda point: (
            min(start.z, end.z) - height * 0.020
            <= point.z
            <= max(start.z, end.z) + height * 0.042
            and abs(point.x - center.x) <= height * 0.078
            and abs(point.y - center.y) <= height * 0.062
        )
    center = (minimum + maximum) * 0.5
    return lambda point: (
        minimum.z + height * 0.82 <= point.z <= minimum.z + height * 0.95
        and abs(point.x - center.x) <= height * 0.078
        and abs(point.y - center.y) <= height * 0.062
    )


def finish(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
    *,
    fit_audit: bool,
) -> bpy.types.Object:
    """Transfer Siroino weights/shape keys while preserving imported parent space."""
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
) -> bpy.types.Object:
    """Extract an editable target-surface panel without baking its thickness."""
    source_uv = body.data.uv_layers.active
    used: dict[int, int] = {}
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    face_uvs: list[list[tuple[float, float]]] = []

    for polygon in body.data.polygons:
        center = body.matrix_world @ polygon.center
        if not predicate(center):
            continue
        face: list[int] = []
        uvs: list[tuple[float, float]] = []
        for loop_index in polygon.loop_indices:
            source_index = body.data.loops[loop_index].vertex_index
            if source_index not in used:
                source = body.data.vertices[source_index]
                used[source_index] = len(vertices)
                vertices.append(
                    tuple(source.co + source.normal.normalized() * offset)
                )
            face.append(used[source_index])
            if source_uv is not None:
                uv = source_uv.data[loop_index].uv
                uvs.append((float(uv.x), float(uv.y)))
            else:
                uvs.append((0.0, 0.0))
        faces.append(face)
        face_uvs.append(uvs)

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
        fit_audit=fit_audit,
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


def skin(body: bpy.types.Object) -> None:
    ORIGINAL_SKIN(body)
    for polygon in body.data.polygons:
        polygon.material_index = 0


def fabric(textures: dict[str, Path]) -> bpy.types.Material:
    material = ORIGINAL_FABRIC(textures)
    shader = next(
        (
            node
            for node in material.node_tree.nodes
            if node.type == "BSDF_PRINCIPLED"
        ),
        None,
    )
    if shader is not None:
        for socket_name in ("Base Color", "Roughness", "Normal"):
            socket = shader.inputs.get(socket_name)
            if socket is not None:
                for link in list(socket.links):
                    material.node_tree.links.remove(link)
        shader.inputs["Base Color"].default_value = (0.002, 0.003, 0.005, 1.0)
        shader.inputs["Roughness"].default_value = 0.70
        if "Specular IOR Level" in shader.inputs:
            shader.inputs["Specular IOR Level"].default_value = 0.18
        if "Sheen Weight" in shader.inputs:
            shader.inputs["Sheen Weight"].default_value = 0.08
    material.diffuse_color = (0.002, 0.003, 0.005, 1.0)
    return material


def parent_rigid(
    obj: bpy.types.Object,
    armature: bpy.types.Object,
    semantic: str,
) -> bpy.types.Object:
    item = resolve_bone(armature, semantic)
    world = obj.matrix_world.copy()
    obj.parent = armature
    if item is not None:
        obj.parent_type = "BONE"
        obj.parent_bone = item.name
    obj.matrix_world = world
    obj["image2outfit_role"] = "garment"
    obj["image2outfit_fit_audit"] = False
    return obj


def rigid_box(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    semantic: str,
    bevel: float,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    modifier = obj.modifiers.new("Hardware edge", "BEVEL")
    modifier.width = bevel
    modifier.segments = 3
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return parent_rigid(obj, armature, semantic)


def rigid_button(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    semantic: str,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=28,
        ring_count=14,
        location=location,
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return parent_rigid(obj, armature, semantic)


def hardware(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    gold: bpy.types.Material,
    cloth: bpy.types.Material,
    center: Vector,
    height: float,
    torso_width: float,
    front: float,
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    minimum, _ = bounds(body)
    z = lambda ratio: minimum.z + height * ratio

    objects.append(
        rigid_box(
            "Military_Gold_Nameplate",
            (center.x + torso_width * 0.24, front, z(0.735)),
            (height * 0.034, height * 0.004, height * 0.010),
            gold,
            armature,
            "chest",
            height * 0.0025,
        )
    )
    objects.append(
        rigid_box(
            "Military_Belt_Buckle",
            (center.x + torso_width * 0.08, front, z(0.555)),
            (height * 0.021, height * 0.0045, height * 0.025),
            gold,
            armature,
            "hips",
            height * 0.0025,
        )
    )
    for index, ratio in enumerate((0.80, 0.72, 0.64), start=1):
        objects.append(
            rigid_button(
                f"Military_Front_Button_{index}",
                (center.x - torso_width * 0.24, front, z(ratio)),
                (height * 0.008, height * 0.004, height * 0.008),
                gold,
                armature,
                "chest" if ratio >= 0.68 else "hips",
            )
        )

    for side, semantic in (("L", "upper_arm_l"), ("R", "upper_arm_r")):
        arm = segment(armature, semantic)
        if arm is None:
            continue
        shoulder = arm[0]
        sign = 1.0 if shoulder.x >= center.x else -1.0
        objects.append(
            rigid_box(
                f"Military_Epaulette_{side}",
                (
                    shoulder.x - sign * height * 0.018,
                    shoulder.y - height * 0.010,
                    shoulder.z + height * 0.008,
                ),
                (height * 0.038, height * 0.021, height * 0.005),
                cloth,
                armature,
                semantic,
                height * 0.0025,
            )
        )
        objects.append(
            rigid_button(
                f"Military_Epaulette_Button_{side}",
                (
                    shoulder.x - sign * height * 0.014,
                    shoulder.y - height * 0.031,
                    shoulder.z + height * 0.012,
                ),
                (height * 0.007, height * 0.0035, height * 0.007),
                gold,
                armature,
                semantic,
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
        max(abs(point.x - center.x) for point in shoulders) * 1.05
        if shoulders
        else height * 0.15
    )
    torso_width = max(height * 0.125, min(torso_width, height * 0.20))
    front_candidates = [
        (body.matrix_world @ vertex.co).y
        for vertex in body.data.vertices
        if z(0.64) <= (body.matrix_world @ vertex.co).z <= z(0.74)
        and abs((body.matrix_world @ vertex.co).x - center.x) <= torso_width
    ]
    front = (
        min(front_candidates) if front_candidates else minimum.y
    ) - height * 0.018

    objects: list[bpy.types.Object] = []
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Opaque_Bodice",
            lambda point: (
                z(0.53) <= point.z <= z(0.93)
                and abs(point.x - center.x) <= torso_width
                and (
                    point.y <= center.y + height * 0.010
                    or point.z <= z(0.60)
                    or abs(point.x - center.x) >= torso_width * 0.72
                )
            ),
            cloth,
            values,
            offset=0.034,
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
            offset=0.016,
            thickness=0.0008,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Fitted_Shorts",
            lambda point: z(0.42) <= point.z <= z(0.56),
            cloth,
            values,
            offset=0.040,
            thickness=0.0028,
        )
    )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Asymmetric_Front_Flap",
            lambda point: (
                z(0.42) <= point.z <= z(0.565)
                and point.y <= center.y
                and point.x <= center.x + torso_width * 0.55
            ),
            cloth,
            values,
            offset=0.047,
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
            offset=0.036,
            thickness=0.0024,
        )
    )
    for side, semantic in (("L", "upper_arm_l"), ("R", "upper_arm_r")):
        arm = segment(armature, semantic)
        if arm is None:
            continue
        start, end = arm
        short_end = start + (end - start) * 0.62
        objects.append(
            fit.extract_surface(
                body,
                armature,
                f"Military_Sleeve_{side}",
                capsule(start, short_end, height * 0.075),
                cloth,
                values,
                offset=0.036,
                thickness=0.0023,
            )
        )
    objects.append(
        fit.extract_surface(
            body,
            armature,
            "Military_Waist_Belt",
            lambda point: z(0.545) <= point.z <= z(0.570),
            cloth,
            values,
            offset=0.042,
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
            center,
            height,
            torso_width,
            front,
        )
    )
    return objects


def target_fit_audit(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
) -> dict[str, object]:
    """Audit the deformed garment base surfaces, not decorative sidewalls."""
    clearances: list[float] = []
    per_object: dict[str, dict[str, object]] = {}
    total_penetrating = 0
    total_vertices = 0

    for obj in garments:
        if obj.type != "MESH" or not bool(
            obj.get("image2outfit_fit_audit", False)
        ):
            continue

        modifier_states = [
            (modifier, modifier.show_viewport)
            for modifier in obj.modifiers
            if modifier.type != "ARMATURE"
        ]
        for modifier, _ in modifier_states:
            modifier.show_viewport = False

        try:
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            tree = BVHTree.FromObject(body, depsgraph)
            evaluated = obj.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh()
            body_inverse = body.matrix_world.inverted()
            base_count = min(
                int(obj.get("image2outfit_base_vertex_count", len(mesh.vertices))),
                len(mesh.vertices),
            )
            local_clearances: list[float] = []
            try:
                for vertex in mesh.vertices[:base_count]:
                    world = evaluated.matrix_world @ vertex.co
                    point = body_inverse @ world
                    nearest = tree.find_nearest(point)
                    if nearest[0] is None or nearest[1] is None:
                        continue
                    local_clearances.append(
                        float((point - nearest[0]).dot(nearest[1]))
                    )
            finally:
                evaluated.to_mesh_clear()
        finally:
            for modifier, state in modifier_states:
                modifier.show_viewport = state
            bpy.context.view_layer.update()

        penetrating = sum(value < -0.0015 for value in local_clearances)
        total_penetrating += penetrating
        total_vertices += len(local_clearances)
        clearances.extend(local_clearances)
        per_object[obj.name] = {
            "vertices": len(local_clearances),
            "penetratingVertices": penetrating,
            "minimumClearanceMeters": (
                min(local_clearances) if local_clearances else None
            ),
            "medianClearanceMeters": (
                statistics.median(local_clearances)
                if local_clearances
                else None
            ),
        }

    ratio = total_penetrating / max(1, total_vertices)
    minimum = min(clearances) if clearances else None
    passed = (
        bool(clearances)
        and ratio <= 0.005
        and minimum is not None
        and minimum >= -0.003
    )
    return {
        "schemaVersion": 1,
        "target": "SiroinoSotai_PC",
        "usesActualTargetSource": True,
        "auditSurface": "deformed-garment-base",
        "auditedVertices": total_vertices,
        "penetratingVertices": total_penetrating,
        "penetrationRatio": ratio,
        "minimumClearanceMeters": minimum,
        "medianClearanceMeters": (
            statistics.median(clearances) if clearances else None
        ),
        "maximumClearanceMeters": max(clearances) if clearances else None,
        "objects": per_object,
        "passed": passed,
    }


def scene(body: bpy.types.Object) -> bpy.types.Object:
    camera = ORIGINAL_SCENE(body)
    render = bpy.context.scene.render
    render.resolution_x = 512
    render.resolution_y = 512
    render.resolution_percentage = 100
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            obj.data.energy *= 0.30
    return camera


def main() -> int:
    fit.finish_skinned = finish
    fit.extract_surface = extract
    fit.assign_review_skin = skin
    fit.base.fabric_material = fabric
    fit.build_outfit = build
    fit.target_fit_audit = target_fit_audit
    fit.configure_scene = scene
    fit.REVISION = "siroino-pc-base-surface-fit-v12"
    return fit.main()


if __name__ == "__main__":
    raise SystemExit(main())
