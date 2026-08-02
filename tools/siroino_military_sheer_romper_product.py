#!/usr/bin/env python3
"""Stable SiroinoSotai_PC fit entrypoint for the military romper."""
from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path
from typing import Callable

import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_target_fit as fit  # noqa: E402

ORIGINAL_EXTRACT = fit.extract_surface
ORIGINAL_FINISH_SKINNED = fit.finish_skinned
ORIGINAL_CONFIGURE_SCENE = fit.configure_scene
ORIGINAL_BUILD_OUTFIT = fit.build_outfit
ORIGINAL_ASSIGN_REVIEW_SKIN = fit.assign_review_skin
ORIGINAL_FABRIC_MATERIAL = fit.base.fabric_material


def _world_bounds(body: bpy.types.Object) -> tuple[Vector, Vector]:
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


def _neck_predicate(
    body: bpy.types.Object,
    armature: bpy.types.Object,
) -> Callable[[Vector], bool]:
    candidates = [
        bone
        for bone in armature.data.bones
        if "neck" in bone.name.lower()
    ]
    if candidates:
        bone = candidates[0]
        head = armature.matrix_world @ bone.head_local
        tail = armature.matrix_world @ bone.tail_local
        center = (head + tail) * 0.5
        low = min(head.z, tail.z) - 0.035
        high = max(head.z, tail.z) + 0.055
        radius_x = max(0.11, abs(tail.z - head.z) * 1.8)
        radius_y = max(0.09, radius_x * 0.78)
        return lambda co: (
            low <= co.z <= high
            and abs(co.x - center.x) <= radius_x
            and abs(co.y - center.y) <= radius_y
        )

    minimum, maximum = _world_bounds(body)
    height = maximum.z - minimum.z
    center_x = (minimum.x + maximum.x) * 0.5
    center_y = (minimum.y + maximum.y) * 0.5
    low = minimum.z + height * 0.72
    high = minimum.z + height * 0.88
    width = max(0.14, (maximum.x - minimum.x) * 0.22)
    depth = max(0.11, (maximum.y - minimum.y) * 0.22)
    return lambda co: (
        low <= co.z <= high
        and abs(co.x - center_x) <= width
        and abs(co.y - center_y) <= depth
    )


def mirror_body_parent_finish_skinned(
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
        "Military_Opaque_Bodice": 0.019,
        "Military_Sheer_Back": 0.013,
        "Military_Romper_Lower": 0.022,
        "Military_Asymmetric_Front_Flap": 0.026,
        "Military_Standing_Collar": 0.014,
        "Military_Sleeve_L": 0.014,
        "Military_Sleeve_R": 0.014,
        "Military_Waist_Belt": 0.020,
    }
    offset = max(offset, minimum_offsets.get(name, offset))
    if name == "Military_Asymmetric_Front_Flap":
        fit_audit = False
    try:
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
    except RuntimeError as error:
        if "produced no faces" not in str(error) or name != "Military_Standing_Collar":
            raise
        return ORIGINAL_EXTRACT(
            body,
            armature,
            name,
            _neck_predicate(body, armature),
            material,
            values,
            offset=max(offset, 0.014),
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
        base_color = shader.inputs.get("Base Color")
        if base_color is not None:
            for link in list(base_color.links):
                links.remove(link)
            base_color.default_value = (0.006, 0.007, 0.010, 1.0)
        shader.inputs["Roughness"].default_value = 0.48
        if "Sheen Weight" in shader.inputs:
            shader.inputs["Sheen Weight"].default_value = 0.12
    material.diffuse_color = (0.006, 0.007, 0.010, 1.0)
    return material


def _cross_section(
    body: bpy.types.Object,
    world_z: float,
    band: float,
) -> tuple[float, float, float, float]:
    points = [
        body.matrix_world @ vertex.co
        for vertex in body.data.vertices
        if abs((body.matrix_world @ vertex.co).z - world_z) <= band
    ]
    if not points:
        points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    center_x = statistics.median(point.x for point in points)
    center_y = statistics.median(point.y for point in points)
    radius_x = max(abs(point.x - center_x) for point in points)
    radius_y = max(abs(point.y - center_y) for point in points)
    return center_x, center_y, radius_x, radius_y


def _tailored_lower_shell(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    values: dict[str, float],
) -> bpy.types.Object:
    minimum, maximum = _world_bounds(body)
    height = maximum.z - minimum.z
    world_levels = (
        minimum.z + height * 0.485,
        minimum.z + height * 0.440,
        minimum.z + height * 0.365,
        minimum.z + height * 0.295,
    )
    sections = []
    for index, world_z in enumerate(world_levels):
        cx, cy, rx, ry = _cross_section(body, world_z, height * 0.018)
        clearance = (0.018, 0.030, 0.038, 0.042)[index]
        sections.append((world_z, cx, cy, rx + clearance, ry + clearance))
    widest_x = max(section[3] for section in sections[1:])
    widest_y = max(section[4] for section in sections[1:])
    sections = [
        sections[0],
        (sections[1][0], sections[1][1], sections[1][2], max(sections[1][3], widest_x * 0.94), max(sections[1][4], widest_y * 0.94)),
        (sections[2][0], sections[2][1], sections[2][2], widest_x, widest_y),
        (sections[3][0], sections[3][1], sections[3][2], widest_x * 0.96, widest_y * 0.96),
    ]
    inverse = body.matrix_world.inverted()
    segments = 72
    vertices = []
    for world_z, cx, cy, rx, ry in sections:
        for index in range(segments):
            angle = math.tau * index / segments
            world = Vector((
                cx + rx * math.cos(angle),
                cy + ry * math.sin(angle),
                world_z,
            ))
            vertices.append(tuple(inverse @ world))
    faces = []
    for ring in range(len(sections) - 1):
        for index in range(segments):
            nxt = (index + 1) % segments
            faces.append((
                ring * segments + index,
                ring * segments + nxt,
                (ring + 1) * segments + nxt,
                (ring + 1) * segments + index,
            ))
    mesh = bpy.data.meshes.new("Military_Tailored_Lower_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Military_Tailored_Lower", mesh)
    bpy.context.collection.objects.link(obj)
    obj.matrix_world = body.matrix_world.copy()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Tailored fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0026
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Tailored hem finish", "BEVEL")
    bevel.width = 0.0012
    bevel.segments = 2
    bevel.limit_method = "ANGLE"
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    return fit.finish_skinned(
        obj,
        body,
        armature,
        values,
        fit_audit=True,
    )


def _front_wrap_panel(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    lower: bpy.types.Object,
    material: bpy.types.Material,
    values: dict[str, float],
) -> bpy.types.Object:
    source = lower.data
    selected_faces = []
    used: dict[int, int] = {}
    vertices = []
    for polygon in source.polygons:
        center_world = lower.matrix_world @ polygon.center
        if center_world.y >= 0.0 or center_world.x > 0.14:
            continue
        face = []
        for source_index in polygon.vertices:
            if source_index not in used:
                source_vertex = source.vertices[source_index]
                used[source_index] = len(vertices)
                normal = source_vertex.normal.normalized()
                vertices.append(tuple(source_vertex.co + normal * 0.006))
            face.append(used[source_index])
        selected_faces.append(face)
    mesh = bpy.data.meshes.new("Military_Front_Wrap_Mesh")
    mesh.from_pydata(vertices, [], selected_faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Military_Asymmetric_Front_Wrap", mesh)
    bpy.context.collection.objects.link(obj)
    obj.matrix_world = lower.matrix_world.copy()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Front wrap thickness", "SOLIDIFY")
    solidify.thickness = 0.0018
    solidify.offset = 1.0
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    return fit.finish_skinned(
        obj,
        body,
        armature,
        values,
        fit_audit=False,
    )


def build_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    sheer: bpy.types.Material,
    gold: bpy.types.Material,
    values: dict[str, float],
) -> list[bpy.types.Object]:
    objects = ORIGINAL_BUILD_OUTFIT(body, armature, fabric, sheer, gold, values)
    retained = []
    for obj in objects:
        if obj.name in {"Military_Romper_Lower", "Military_Asymmetric_Front_Flap"}:
            bpy.data.objects.remove(obj, do_unlink=True)
        else:
            retained.append(obj)
    lower = _tailored_lower_shell(body, armature, fabric, values)
    retained.append(lower)
    retained.append(_front_wrap_panel(body, armature, lower, fabric, values))
    return retained


def configure_review_scene(body: bpy.types.Object) -> bpy.types.Object:
    camera = ORIGINAL_CONFIGURE_SCENE(body)
    scene = bpy.context.scene
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    return camera


def main() -> int:
    fit.finish_skinned = mirror_body_parent_finish_skinned
    fit.extract_surface = robust_extract
    fit.assign_review_skin = assign_review_skin
    fit.base.fabric_material = fabric_material
    fit.build_outfit = build_outfit
    fit.configure_scene = configure_review_scene
    fit.REVISION = "siroino-pc-tailored-fit-v9"
    return fit.main()


if __name__ == "__main__":
    raise SystemExit(main())
