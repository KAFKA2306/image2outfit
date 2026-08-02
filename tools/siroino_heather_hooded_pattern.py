#!/usr/bin/env python3
"""Production panel layout for the Siroino heather hooded bodysuit."""
from __future__ import annotations

import math

import bpy

import siroino_heather_hooded_geometry as geometry
import siroino_strappy_knit_build as base

bone_segment = geometry.bone_segment
clean_meshes = geometry.clean_meshes


def _mesh_from_grid(
    name: str,
    vertices: list[tuple[float, float, float]],
    rows: int,
    columns: int,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    thickness: float,
    subdivision: int = 1,
) -> bpy.types.Object:
    faces: list[tuple[int, int, int, int]] = []
    stride = columns + 1
    for row in range(rows - 1):
        for column in range(columns):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
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
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    base.transfer_nearest_body_weights(obj, body)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solidify = obj.modifiers.new("Jersey thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    if subdivision:
        smooth = obj.modifiers.new("Pattern smoothing", "SUBSURF")
        smooth.subdivision_type = "CATMULL_CLARK"
        smooth.levels = subdivision
        smooth.render_levels = subdivision
        bpy.ops.object.modifier_apply(modifier=smooth.name)
    bevel = obj.modifiers.new("Finished pattern edge", "BEVEL")
    bevel.width = 0.00065
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def fitted_sleeve(
    armature: bpy.types.Object,
    side: str,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    """Create a continuous close-fit sleeve extending through the wrist."""
    upper_start, upper_end = bone_segment(armature, f"UpperArm_{side}")
    lower_start, lower_end = bone_segment(armature, f"LowerArm_{side}")
    hand_start, hand_end = bone_segment(armature, f"Hand_{side}")
    upper = upper_end - upper_start
    lower = lower_end - lower_start
    hand = hand_end - hand_start
    points = [
        upper_start - upper * 0.055,
        upper_start + upper * 0.18,
        upper_start + upper * 0.46,
        upper_start + upper * 0.75,
        upper_end,
        lower_start + lower * 0.26,
        lower_start + lower * 0.55,
        lower_start + lower * 0.82,
        lower_end,
        hand_start + hand * 0.035,
    ]
    radii = [0.038, 0.036, 0.034, 0.032, 0.030, 0.0285, 0.027, 0.0255, 0.0245, 0.024]
    weights = [
        {f"UpperArm_{side}": 1.0},
        {f"UpperArm_{side}": 1.0},
        {f"UpperArm_{side}": 1.0},
        {f"UpperArm_{side}": 0.88, f"LowerArm_{side}": 0.12},
        {f"UpperArm_{side}": 0.48, f"LowerArm_{side}": 0.52},
        {f"UpperArm_{side}": 0.10, f"LowerArm_{side}": 0.90},
        {f"LowerArm_{side}": 1.0},
        {f"LowerArm_{side}": 1.0},
        {f"LowerArm_{side}": 0.82, f"Hand_{side}": 0.18},
        {f"LowerArm_{side}": 0.35, f"Hand_{side}": 0.65},
    ]
    sleeve = geometry.weighted_tube(
        f"Heather_Long_Sleeve_{side}",
        points,
        radii,
        weights,
        fabric,
        armature,
        segments=44,
        thickness=0.00135,
    )
    cuff_points = [
        lower_end - lower * 0.055,
        lower_end,
        hand_start + hand * 0.050,
        hand_start + hand * 0.105,
    ]
    cuff_weights = [
        {f"LowerArm_{side}": 1.0},
        {f"LowerArm_{side}": 0.85, f"Hand_{side}": 0.15},
        {f"LowerArm_{side}": 0.30, f"Hand_{side}": 0.70},
        {f"Hand_{side}": 1.0},
    ]
    cuff = geometry.weighted_tube(
        f"Heather_Rib_Cuff_{side}",
        cuff_points,
        [0.0255, 0.0250, 0.0245, 0.0240],
        cuff_weights,
        trim,
        armature,
        segments=40,
        thickness=0.00165,
    )
    return [sleeve, cuff]


def hood_neck_band(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    """Create the editable neck opening and rolled hood edge."""
    segments = 52
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    rings = (
        (0.064, 0.041, 1.034),
        (0.050, 0.029, 1.020),
    )
    for radius_x, radius_y, z in rings:
        for index in range(segments + 1):
            angle = math.pi * index / segments
            bulge = math.sin(angle)
            vertices.append(
                (
                    radius_x * math.cos(angle),
                    0.006 + radius_y * bulge,
                    z - 0.004 * bulge,
                )
            )
    stride = segments + 1
    for index in range(segments):
        faces.append((index, index + 1, stride + index + 1, stride + index))
    mesh = bpy.data.meshes.new("Heather_Hood_Cowl_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row, column = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (column / segments, float(row))
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Heather_Hood_Cowl", mesh)
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
    solidify = obj.modifiers.new("Rolled hood edge", "SOLIDIFY")
    solidify.thickness = 0.0024
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Hood edge finish", "BEVEL")
    bevel.width = 0.0008
    bevel.segments = 3
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def hood_shell_side(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    """Create one half of the folded hood shell with a central back seam."""
    sign = -1.0 if side == "L" else 1.0
    rows = [
        (1.034, 0.047, 0.040),
        (1.010, 0.060, 0.052),
        (0.982, 0.068, 0.063),
        (0.952, 0.064, 0.072),
        (0.925, 0.049, 0.079),
        (0.902, 0.026, 0.083),
        (0.890, 0.004, 0.085),
    ]
    columns = 14
    vertices: list[tuple[float, float, float]] = []
    for z, half_width, center_y in rows:
        for column in range(columns + 1):
            u = column / columns
            x = sign * half_width * u
            center_bulge = 0.010 * (1.0 - u) ** 2
            outer_fold = 0.004 * math.sin(math.pi * u)
            y = center_y + center_bulge + outer_fold
            vertices.append((x, y, z - 0.003 * math.sin(math.pi * u)))
    return _mesh_from_grid(
        f"Heather_Hood_Back_Drape_{side}",
        vertices,
        len(rows),
        columns,
        material,
        armature,
        body,
        thickness=0.0020,
        subdivision=1,
    )


def seam_geometry(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> bpy.types.Object:
    """Author visible seam piping as a separate editable structure."""
    curves: list[bpy.types.Object] = []
    front_points = []
    for z in (0.800, 0.835, 0.870, 0.905, 0.940):
        y = geometry._body_surface_y(body, 0.0, z, front=True) - 0.0100
        front_points.append((0.0, y, z))
    back_points = []
    for z in (0.800, 0.830, 0.860, 0.890):
        y = geometry._body_surface_y(body, 0.0, z, front=False) + 0.0100
        back_points.append((0.0, y, z))
    curves.append(
        base.curve_tube(
            "Heather_Center_Front_Seam",
            front_points,
            0.00055,
            trim,
            armature,
            "Spine",
            resolution=2,
        )
    )
    curves.append(
        base.curve_tube(
            "Heather_Center_Back_Seam",
            back_points,
            0.00055,
            trim,
            armature,
            "Spine",
            resolution=2,
        )
    )
    curves.append(
        base.curve_tube(
            "Heather_Hood_Center_Seam",
            [(0.0, 0.050, 1.020), (0.0, 0.070, 0.970), (0.0, 0.083, 0.915), (0.0, 0.085, 0.892)],
            0.00065,
            trim,
            armature,
            "Chest",
            resolution=2,
        )
    )
    joined = base.join_objects("Heather_Editable_Seams", curves)
    base.transfer_nearest_body_weights(joined, body)
    return joined


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
            "Heather_Long_Sleeve_L",
            "Heather_Rib_Cuff_L",
            "Heather_Long_Sleeve_R",
            "Heather_Rib_Cuff_R",
            "Heather_Highcut_Front_Panel",
            "Heather_Highcut_Back_Panel",
            "Heather_Hood_Cowl",
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
                    (0.635, 0.005),
                    (0.670, 0.017),
                    (0.710, 0.036),
                    (0.752, 0.064),
                    (0.798, 0.097),
                    (0.820, 0.108),
                ],
                front=True,
                segments=26,
            ),
            geometry.fitted_center_panel(
                "Heather_Highcut_Back_Panel",
                body,
                armature,
                fabric,
                [
                    (0.632, 0.008),
                    (0.670, 0.021),
                    (0.710, 0.043),
                    (0.752, 0.070),
                    (0.798, 0.101),
                    (0.820, 0.112),
                ],
                front=False,
                segments=26,
            ),
            hood_neck_band(body, armature, fabric),
            hood_shell_side(body, armature, fabric, "L"),
            hood_shell_side(body, armature, fabric, "R"),
        ]
    )
    for side in ("L", "R"):
        garments.extend(fitted_sleeve(armature, side, fabric, trim))
    garments.append(seam_geometry(body, armature, trim))
    return garments
