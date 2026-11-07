#!/usr/bin/env python3
"""Runtime support for the Siroino heather bodysuit v11 generator."""

from __future__ import annotations

from dataclasses import dataclass

import bpy
from mathutils import Vector

import siroino_heather_hooded_pattern as helper


@dataclass(frozen=True)
class SurfaceSample:
    y: float
    normal: Vector


class SurfaceSampler:
    """Interpolate the avatar surface at exact X/Z coordinates."""

    def __init__(self, body: bpy.types.Object) -> None:
        self.body = body
        normal_matrix = body.matrix_world.to_3x3()
        self.samples = [
            (
                body.matrix_world @ vertex.co,
                (normal_matrix @ vertex.normal).normalized(),
            )
            for vertex in body.data.vertices
        ]
        self.z_bins: dict[int, list[tuple[Vector, Vector]]] = {}
        for point, normal in self.samples:
            self.z_bins.setdefault(round(point.z * 100), []).append((point, normal))

    def sample(self, x: float, z: float, *, front: bool) -> SurfaceSample:
        candidates: list[tuple[Vector, Vector]] = []
        center_bin = round(z * 100)
        for delta in range(-5, 6):
            candidates.extend(self.z_bins.get(center_bin + delta, []))
        if not candidates:
            candidates = self.samples
        ranked = sorted(
            candidates,
            key=lambda item: (item[0].x - x) ** 2 + (item[0].z - z) ** 2,
        )[:24]
        side_ranked = sorted(ranked, key=lambda item: item[0].y)
        side = side_ranked[:12] if front else side_ranked[-12:]
        weights = [
            1.0 / max(1e-7, (point.x - x) ** 2 + (point.z - z) ** 2)
            for point, _normal in side
        ]
        total = sum(weights)
        y = sum(weight * item[0].y for weight, item in zip(weights, side)) / total
        normal = Vector((0.0, 0.0, 0.0))
        for weight, (_point, item_normal) in zip(weights, side):
            normal += item_normal * weight
        if normal.length_squared <= 1e-12:
            normal = Vector((0.0, -1.0 if front else 1.0, 0.0))
        else:
            normal.normalize()
        if front and normal.y > 0.0:
            normal = -normal
        if not front and normal.y < 0.0:
            normal = -normal
        return SurfaceSample(y=y, normal=normal)

    def point(self, x: float, z: float, *, front: bool, offset: float) -> Vector:
        sampled = self.sample(x, z, front=front)
        return Vector((x, sampled.y, z)) + sampled.normal * offset

    def side_y(self, x: float, z: float) -> float:
        return 0.5 * (
            self.sample(x, z, front=True).y + self.sample(x, z, front=False).y
        )


def grid_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    rows: int,
    columns: int,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    thickness: float,
    bevel: float,
    subdivision: int = 0,
) -> bpy.types.Object:
    stride = columns + 1
    faces = [
        (
            row * stride + column,
            row * stride + column + 1,
            (row + 1) * stride + column + 1,
            (row + 1) * stride + column,
        )
        for row in range(rows - 1)
        for column in range(columns)
    ]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row, column = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (
                column / max(1, columns),
                1.0 - row / max(1, rows - 1),
            )
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True
    helper.base.transfer_nearest_body_weights(obj, body)
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if subdivision:
        smooth = obj.modifiers.new("Pattern smoothing", "SUBSURF")
        smooth.subdivision_type = "CATMULL_CLARK"
        smooth.levels = subdivision
        smooth.render_levels = subdivision
        while obj.modifiers.find(smooth.name) > 0:
            bpy.ops.object.modifier_move_up(modifier=smooth.name)
        bpy.ops.object.modifier_apply(modifier=smooth.name)
    solidify = obj.modifiers.new("Outward fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 1.0
    solidify.use_even_offset = True
    while obj.modifiers.find(solidify.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=solidify.name)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    edge_finish = obj.modifiers.new("Finished pattern edge", "BEVEL")
    edge_finish.width = bevel
    edge_finish.segments = 2
    while obj.modifiers.find(edge_finish.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=edge_finish.name)
    bpy.ops.object.modifier_apply(modifier=edge_finish.name)
    obj.select_set(False)
    return obj


def placket_and_buttons(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
    buttons: bpy.types.Material,
) -> list[bpy.types.Object]:
    point = sampler.point(0.0, 0.978, front=True, offset=0.017)
    placket = helper.legacy.rounded_box(
        "Heather_Henley_Placket",
        (point.x, point.y, point.z),
        (0.014, 0.0028, 0.042),
        trim,
        armature,
        "Chest",
        bevel=0.0014,
    )
    result = [placket]
    for index, z in enumerate((1.002, 0.980, 0.958), start=1):
        button_point = sampler.point(0.0, z, front=True, offset=0.021)
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=24,
            ring_count=12,
            location=(button_point.x, button_point.y, button_point.z),
            scale=(0.0048, 0.0023, 0.0048),
        )
        button = bpy.context.active_object
        button.name = f"Heather_Henley_Button_{index:02d}"
        button.data.materials.append(buttons)
        helper.base.rigid_mesh_weight(button, armature, "Chest")
        for polygon in button.data.polygons:
            polygon.use_smooth = True
        result.append(button)
    return result


def install() -> None:
    """Install only the compatibility surface required by the v11 module."""
    helper.SurfaceSampler = SurfaceSampler
    helper._grid_object = grid_object
    helper._placket_and_buttons = placket_and_buttons
