#!/usr/bin/env python3
"""Final panel layout for the Siroino heather hooded bodysuit."""
from __future__ import annotations

import math

import bpy

import siroino_heather_hooded_geometry as geometry
import siroino_strappy_knit_build as base

bone_segment = geometry.bone_segment
clean_meshes = geometry.clean_meshes


def hood_pouch(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    """Create a centered, rounded hood pouch that falls down the upper back."""
    rows = [
        (1.030, 0.056, 0.046),
        (1.006, 0.080, 0.058),
        (0.976, 0.091, 0.071),
        (0.945, 0.077, 0.084),
        (0.918, 0.048, 0.092),
        (0.898, 0.010, 0.095),
    ]
    columns = 24
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for z, half_width, center_y in rows:
        for column in range(columns + 1):
            u = -1.0 + 2.0 * column / columns
            x = half_width * u
            bulge = max(0.0, 1.0 - u * u)
            y = center_y + 0.018 * bulge
            vertices.append((x, y, z - 0.004 * bulge))
    stride = columns + 1
    for row in range(len(rows) - 1):
        for column in range(columns):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
    mesh = bpy.data.meshes.new("Heather_Hood_Pouch_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row, column = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (
                column / columns,
                1.0 - row / (len(rows) - 1),
            )
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Heather_Hood_Pouch", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    base.transfer_nearest_body_weights(obj, body)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solidify = obj.modifiers.new("Hood pouch thickness", "SOLIDIFY")
    solidify.thickness = 0.0022
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    subdivision = obj.modifiers.new("Hood pouch smoothing", "SUBSURF")
    subdivision.subdivision_type = "CATMULL_CLARK"
    subdivision.levels = 2
    subdivision.render_levels = 2
    bpy.ops.object.modifier_apply(modifier=subdivision.name)
    bevel = obj.modifiers.new("Hood pouch finished edge", "BEVEL")
    bevel.width = 0.0008
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def _remove_generated(
    garments: list[bpy.types.Object],
    names: set[str],
) -> list[bpy.types.Object]:
    retained: list[bpy.types.Object] = []
    for obj in garments:
        if obj.name in names:
            bpy.data.objects.remove(obj, do_unlink=True)
        else:
            retained.append(obj)
    return retained


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    garments = geometry.create_outfit(
        body,
        armature,
        fabric,
        trim,
        button_material,
    )
    garments = _remove_generated(
        garments,
        {
            "Heather_Highcut_Front_Panel",
            "Heather_Highcut_Back_Panel",
            "Heather_Hood_Back_Drape",
        },
    )
    garments.extend(
        [
            geometry.fitted_center_panel(
                "Heather_Highcut_Front_Panel",
                body,
                armature,
                fabric,
                [
                    (0.640, 0.004),
                    (0.675, 0.018),
                    (0.715, 0.039),
                    (0.755, 0.067),
                    (0.795, 0.094),
                ],
                front=True,
                segments=24,
            ),
            geometry.fitted_center_panel(
                "Heather_Highcut_Back_Panel",
                body,
                armature,
                fabric,
                [
                    (0.635, 0.010),
                    (0.675, 0.025),
                    (0.715, 0.047),
                    (0.755, 0.073),
                    (0.795, 0.098),
                ],
                front=False,
                segments=24,
            ),
            hood_pouch(body, armature, fabric),
        ]
    )
    return garments
