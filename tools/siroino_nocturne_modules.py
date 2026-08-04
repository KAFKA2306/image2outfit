"""Modular garment assembly for the Nocturne Angel set."""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

from siroino_nocturne_geometry import (
    axis_shell,
    bake_skirt,
    bone_segment,
    bounds,
    cube,
    finish,
    frustum_shell,
    panel,
    rigid_weight,
    sphere,
    transfer_weights,
)


def _grid_panel(name, rows, mat, thickness):
    columns = len(rows[0])
    if columns < 2 or any(len(row) != columns for row in rows):
        raise ValueError("grid panel rows must have one consistent width")
    vertices = [tuple(point) for row in rows for point in row]
    faces = []
    for row_index in range(len(rows) - 1):
        for column in range(columns - 1):
            first = row_index * columns + column
            faces.append((first, first + 1, first + 1 + columns, first + columns))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row_index, column = divmod(vertex_index, columns)
            uv.data[loop_index].uv = (
                column / (columns - 1),
                row_index / (len(rows) - 1),
            )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    finish(obj, mat)
    solidify = obj.modifiers.new("Pattern panel thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    obj.select_set(False)
    return obj


def _surface_point(center, x_offset, z_value, radius_x, radius_y, front):
    normalized = min(1.0, abs(x_offset) / max(radius_x, 1e-8))
    depth = radius_y * math.sqrt(max(0.0, 1.0 - normalized * normalized))
    sign = -1.0 if front else 1.0
    return Vector((center.x + x_offset, center.y + sign * depth, z_value))


def _surface_row(center, fractions, z_value, radius_x, radius_y, front):
    return [
        _surface_point(
            center,
            fraction * radius_x,
            z_value,
            radius_x,
            radius_y,
            front,
        )
        for fraction in fractions
    ]


def _rounded_feather(name, root, tip, width, mat):
    axis = tip - root
    normal = Vector((0.0, 1.0, 0.0))
    lateral = normal.cross(axis).normalized()
    upper = []
    lower = []
    for index in range(9):
        t = index / 8
        center = root.lerp(tip, t)
        half_width = width * math.sin(math.pi * t) ** 0.72
        upper.append(center + lateral * half_width)
        lower.append(center - lateral * half_width)
    outline = [root, *upper[1:-1], tip, *reversed(lower[1:-1])]
    return panel(name, outline, mat, max(0.0012, width * 0.06))


def _build_bodice(center, height, z, mats):
    radius_x = height * 0.150
    front_radius_y = height * 0.100
    back_radius_y = height * 0.094
    left_front_rows = [
        _surface_row(
            center,
            (-1.0, -0.67, -0.33, 0.0),
            z(0.60),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (-1.0, -0.67, -0.33, 0.0),
            z(0.70),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (-1.0, -0.72, -0.45, -0.18),
            z(0.80),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (-0.82, -0.65, -0.48, -0.30),
            z(0.89),
            radius_x,
            front_radius_y,
            True,
        ),
    ]
    right_front_rows = [
        _surface_row(
            center,
            (0.0, 0.33, 0.67, 1.0),
            z(0.60),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (0.0, 0.33, 0.67, 1.0),
            z(0.70),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (0.18, 0.45, 0.72, 1.0),
            z(0.80),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (0.30, 0.48, 0.65, 0.82),
            z(0.89),
            radius_x,
            front_radius_y,
            True,
        ),
    ]
    back_rows = [
        _surface_row(
            center,
            (-1.0, -0.66, -0.33, 0.0, 0.33, 0.66, 1.0),
            z(0.60),
            radius_x,
            back_radius_y,
            False,
        ),
        _surface_row(
            center,
            (-1.0, -0.66, -0.33, 0.0, 0.33, 0.66, 1.0),
            z(0.70),
            radius_x,
            back_radius_y,
            False,
        ),
        _surface_row(
            center,
            (-1.0, -0.66, -0.33, 0.0, 0.33, 0.66, 1.0),
            z(0.80),
            radius_x,
            back_radius_y,
            False,
        ),
        _surface_row(
            center,
            (-0.82, -0.55, -0.28, 0.0, 0.28, 0.55, 0.82),
            z(0.89),
            radius_x,
            back_radius_y,
            False,
        ),
    ]
    left_side_rows = []
    right_side_rows = []
    for ratio in (0.60, 0.67, 0.74, 0.80):
        z_value = z(ratio)
        left_side_rows.append(
            [
                _surface_point(
                    center,
                    -radius_x,
                    z_value,
                    radius_x,
                    back_radius_y,
                    False,
                ),
                Vector((center.x - radius_x * 1.025, center.y, z_value)),
                _surface_point(
                    center,
                    -radius_x,
                    z_value,
                    radius_x,
                    front_radius_y,
                    True,
                ),
            ]
        )
        right_side_rows.append(
            [
                _surface_point(
                    center,
                    radius_x,
                    z_value,
                    radius_x,
                    front_radius_y,
                    True,
                ),
                Vector((center.x + radius_x * 1.025, center.y, z_value)),
                _surface_point(
                    center,
                    radius_x,
                    z_value,
                    radius_x,
                    back_radius_y,
                    False,
                ),
            ]
        )
    thickness = height * 0.0025
    panels = [
        _grid_panel(
            "Nocturne_Bodice_Front_L",
            left_front_rows,
            mats["black"],
            thickness,
        ),
        _grid_panel(
            "Nocturne_Bodice_Front_R",
            right_front_rows,
            mats["black"],
            thickness,
        ),
        _grid_panel(
            "Nocturne_Bodice_Back",
            back_rows,
            mats["black"],
            thickness,
        ),
        _grid_panel(
            "Nocturne_Bodice_Side_L",
            left_side_rows,
            mats["black"],
            thickness,
        ),
        _grid_panel(
            "Nocturne_Bodice_Side_R",
            right_side_rows,
            mats["black"],
            thickness,
        ),
    ]
    front_y = center.y - front_radius_y * 1.02
    left_collar = panel(
        "Nocturne_Sailor_Collar_L",
        [
            (center.x, front_y, z(0.745)),
            (center.x - radius_x * 0.30, front_y, z(0.890)),
            (center.x - radius_x * 0.48, front_y, z(0.875)),
            (center.x - radius_x * 0.08, front_y, z(0.715)),
        ],
        mats["beige"],
        thickness,
    )
    right_collar = panel(
        "Nocturne_Sailor_Collar_R",
        [
            (center.x + radius_x * 0.08, front_y, z(0.715)),
            (center.x + radius_x * 0.48, front_y, z(0.875)),
            (center.x + radius_x * 0.30, front_y, z(0.890)),
            (center.x, front_y, z(0.745)),
        ],
        mats["beige"],
        thickness,
    )
    back_y = center.y + back_radius_y * 1.02
    back_collar = panel(
        "Nocturne_Sailor_Collar_Back",
        [
            (center.x - radius_x * 0.72, back_y, z(0.875)),
            (center.x + radius_x * 0.72, back_y, z(0.875)),
            (center.x + radius_x * 0.55, back_y, z(0.815)),
            (center.x, back_y, z(0.775)),
            (center.x - radius_x * 0.55, back_y, z(0.815)),
        ],
        mats["beige"],
        thickness,
    )
    return panels, [left_collar, right_collar, back_collar], front_y


def build(body, armature, mats):
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    center = (minimum + maximum) * 0.5

    def z(ratio):
        return minimum.z + height * ratio

    deforming = []
    rigid = []
    bodice_panels, collar_panels, front_y = _build_bodice(center, height, z, mats)
    deforming.extend(bodice_panels)
    rigid.extend((obj, "chest") for obj in collar_panels)

    skirt = frustum_shell(
        "Nocturne_Cloth_Skirt",
        center,
        [
            (z(0.385), height * 0.225, height * 0.160, 0.0),
            (z(0.415), height * 0.220, height * 0.155, 0.0),
            (z(0.450), height * 0.208, height * 0.145, 0.0),
            (z(0.485), height * 0.194, height * 0.133, 0.0),
            (z(0.520), height * 0.178, height * 0.120, 0.0),
            (z(0.555), height * 0.160, height * 0.106, 0.0),
            (z(0.585), height * 0.149, height * 0.098, 0.0),
            (z(0.610), height * 0.143, height * 0.094, 0.0),
        ],
        mats["black"],
        segments=72,
    )
    cloth = [bake_skirt(skirt, body)]
    frill = frustum_shell(
        "Nocturne_Cream_Hem_Frill",
        center,
        [
            (z(0.365), height * 0.238, height * 0.171, 0.0),
            (z(0.382), height * 0.231, height * 0.165, 0.0),
            (z(0.402), height * 0.222, height * 0.157, 0.0),
        ],
        mats["cream"],
        segments=72,
        scallops=12,
    )
    waist = frustum_shell(
        "Nocturne_Waist_Band",
        center,
        [
            (z(0.590), height * 0.146, height * 0.097, 0.0),
            (z(0.606), height * 0.144, height * 0.095, 0.0),
            (z(0.625), height * 0.142, height * 0.093, 0.0),
        ],
        mats["beige"],
        segments=64,
    )
    rigid.extend([(skirt, "hips"), (frill, "hips"), (waist, "hips")])

    for side, upper, lower in (
        ("L", "upper_arm_l", "lower_arm_l"),
        ("R", "upper_arm_r", "lower_arm_r"),
    ):
        upper_start, upper_end = bone_segment(armature, upper)
        lower_start, lower_end = bone_segment(armature, lower)
        upper_axis = upper_end - upper_start
        puff = axis_shell(
            f"Nocturne_Puff_Sleeve_{side}",
            upper_start + upper_axis * 0.06,
            upper_start + upper_axis * 0.42,
            [
                height * 0.036,
                height * 0.048,
                height * 0.053,
                height * 0.047,
                height * 0.034,
            ],
            mats["black"],
        )
        warmer = axis_shell(
            f"Nocturne_Detached_Arm_Warmer_{side}",
            upper_start + upper_axis * 0.56,
            lower_start.lerp(lower_end, 0.91),
            [
                height * 0.031,
                height * 0.036,
                height * 0.034,
                height * 0.030,
                height * 0.025,
            ],
            mats["black"],
        )
        cuff = axis_shell(
            f"Nocturne_Lace_Cuff_{side}",
            lower_start.lerp(lower_end, 0.80),
            lower_start.lerp(lower_end, 0.98),
            [height * 0.036, height * 0.040, height * 0.036, height * 0.030],
            mats["cream"],
        )
        deforming.extend([puff, warmer, cuff])

    for side, lower, foot in (
        ("L", "lower_leg_l", "foot_l"),
        ("R", "lower_leg_r", "foot_r"),
    ):
        lower_start, lower_end = bone_segment(armature, lower)
        warmer = axis_shell(
            f"Nocturne_Leg_Warmer_{side}",
            lower_start.lerp(lower_end, 0.08),
            lower_start.lerp(lower_end, 0.88),
            [
                height * 0.046,
                height * 0.054,
                height * 0.056,
                height * 0.052,
                height * 0.044,
            ],
            mats["beige"],
        )
        shoe = cube(
            f"Nocturne_Shoe_{side}",
            lower_end + Vector((0.0, -height * 0.035, -height * 0.018)),
            (height * 0.046, height * 0.078, height * 0.034),
            mats["brown"],
        )
        rigid.extend([(warmer, lower), (shoe, foot)])

    head_start, head_end = bone_segment(armature, "head")
    head = head_start.lerp(head_end, 0.68)
    beret = sphere(
        "Nocturne_Beret",
        head + Vector((0.0, 0.0, height * 0.074)),
        (height * 0.105, height * 0.092, height * 0.036),
        mats["beige"],
    )
    rigid.append((beret, "head"))
    for side, sign in (("L", 1.0), ("R", -1.0)):
        ear = panel(
            f"Nocturne_Animal_Ear_{side}",
            [
                head + Vector((sign * height * 0.055, height * 0.010, height * 0.075)),
                head + Vector((sign * height * 0.090, height * 0.006, height * 0.145)),
                head + Vector((sign * height * 0.040, height * 0.004, height * 0.122)),
            ],
            mats["brown"],
            height * 0.004,
        )
        rigid.append((ear, "head"))

    neck_start, neck_end = bone_segment(armature, "neck")
    neck = neck_start.lerp(neck_end, 0.42)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=height * 0.046,
        minor_radius=height * 0.005,
        location=neck,
    )
    choker = bpy.context.object
    choker.name = "Nocturne_Choker"
    finish(choker, mats["beige"])
    amber = sphere(
        "Nocturne_Amber_Charm",
        neck + Vector((0.0, -height * 0.050, -height * 0.018)),
        (height * 0.016, height * 0.010, height * 0.022),
        mats["gold"],
    )
    rigid.extend([(choker, "neck"), (amber, "chest")])

    bow = Vector((center.x, front_y - height * 0.010, z(0.742)))
    bow_left = sphere(
        "Nocturne_Bow_Loop_L",
        bow + Vector((-height * 0.040, 0.0, 0.0)),
        (height * 0.045, height * 0.009, height * 0.027),
        mats["black"],
    )
    bow_right = sphere(
        "Nocturne_Bow_Loop_R",
        bow + Vector((height * 0.040, 0.0, 0.0)),
        (height * 0.045, height * 0.009, height * 0.027),
        mats["black"],
    )
    rabbit = sphere(
        "Nocturne_Rabbit_Charm",
        bow + Vector((0.0, -height * 0.010, 0.0)),
        (height * 0.021, height * 0.011, height * 0.028),
        mats["beige"],
    )
    rigid.extend([(bow_left, "chest"), (bow_right, "chest"), (rabbit, "chest")])

    chest_start, chest_end = bone_segment(armature, "chest")
    wing_origin = chest_start.lerp(chest_end, 0.60) + Vector(
        (0.0, height * 0.115, height * 0.010)
    )
    for side, sign in (("L", 1.0), ("R", -1.0)):
        for index in range(6):
            angle = math.radians(42 - index * 12)
            length = height * (0.145 + index * 0.021)
            root = wing_origin + Vector(
                (
                    sign * height * (0.018 + index * 0.004),
                    0.0,
                    -index * height * 0.008,
                )
            )
            tip = root + Vector(
                (
                    sign * length * math.cos(angle),
                    0.0,
                    length * math.sin(angle),
                )
            )
            wing = _rounded_feather(
                f"Nocturne_Wing_{side}_{index:02d}",
                root,
                tip,
                height * (0.028 + index * 0.003),
                mats["white"],
            )
            rigid.append((wing, "chest"))

    tail = sphere(
        "Nocturne_Tail",
        Vector((center.x, center.y + height * 0.145, z(0.505))),
        (height * 0.060,) * 3,
        mats["brown"],
    )
    rigid.append((tail, "hips"))

    for obj in deforming:
        transfer_weights(obj, body, armature)
    for obj, semantic in rigid:
        rigid_weight(obj, armature, semantic)
    return deforming + [obj for obj, _ in rigid], cloth
