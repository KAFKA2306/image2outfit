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
    enforce_body_clearance,
    finish,
    frustum_shell,
    panel,
    rigid_weight,
    semantic_weights,
    sphere,
    triangulate,
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
    triangulate(obj)
    return obj


def _surface_point(center, x_offset, z_value, radius_x, radius_y, front):
    normalized = min(0.985, abs(x_offset) / max(radius_x, 1e-8))
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
    for index in range(11):
        t = index / 10
        center = root.lerp(tip, t)
        half_width = width * math.sin(math.pi * t) ** 0.62
        upper.append(center + lateral * half_width)
        lower.append(center - lateral * half_width)
    outline = [root, *upper[1:-1], tip, *reversed(lower[1:-1])]
    return panel(name, outline, mat, max(0.0015, width * 0.10))


def _build_bodice(center, height, z, mats):
    radius_x = height * 0.112
    front_radius_y = height * 0.074
    back_radius_y = height * 0.068
    left_front_rows = [
        _surface_row(
            center,
            (-0.96, -0.64, -0.32, 0.0),
            z(0.565),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (-0.96, -0.64, -0.32, 0.0),
            z(0.640),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (-0.92, -0.62, -0.36, -0.12),
            z(0.715),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (-0.72, -0.61, -0.50, -0.38),
            z(0.820),
            radius_x,
            front_radius_y,
            True,
        ),
    ]
    right_front_rows = [
        _surface_row(
            center,
            (0.0, 0.32, 0.64, 0.96),
            z(0.565),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (0.0, 0.32, 0.64, 0.96),
            z(0.640),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (0.12, 0.36, 0.62, 0.92),
            z(0.715),
            radius_x,
            front_radius_y,
            True,
        ),
        _surface_row(
            center,
            (0.38, 0.50, 0.61, 0.72),
            z(0.820),
            radius_x,
            front_radius_y,
            True,
        ),
    ]
    back_rows = [
        _surface_row(
            center,
            (-0.96, -0.64, -0.32, 0.0, 0.32, 0.64, 0.96),
            z(0.565),
            radius_x,
            back_radius_y,
            False,
        ),
        _surface_row(
            center,
            (-0.96, -0.64, -0.32, 0.0, 0.32, 0.64, 0.96),
            z(0.640),
            radius_x,
            back_radius_y,
            False,
        ),
        _surface_row(
            center,
            (-0.92, -0.61, -0.30, 0.0, 0.30, 0.61, 0.92),
            z(0.715),
            radius_x,
            back_radius_y,
            False,
        ),
        _surface_row(
            center,
            (-0.72, -0.48, -0.24, 0.0, 0.24, 0.48, 0.72),
            z(0.820),
            radius_x,
            back_radius_y,
            False,
        ),
    ]
    left_side_rows = []
    right_side_rows = []
    for ratio in (0.565, 0.640, 0.715, 0.775):
        z_value = z(ratio)
        left_side_rows.append(
            [
                _surface_point(
                    center,
                    -radius_x * 0.96,
                    z_value,
                    radius_x,
                    back_radius_y,
                    False,
                ),
                Vector((center.x - radius_x * 1.02, center.y, z_value)),
                _surface_point(
                    center,
                    -radius_x * 0.96,
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
                    radius_x * 0.96,
                    z_value,
                    radius_x,
                    front_radius_y,
                    True,
                ),
                Vector((center.x + radius_x * 1.02, center.y, z_value)),
                _surface_point(
                    center,
                    radius_x * 0.96,
                    z_value,
                    radius_x,
                    back_radius_y,
                    False,
                ),
            ]
        )
    thickness = height * 0.0022
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
    front_y = center.y - front_radius_y * 1.08
    left_collar = panel(
        "Nocturne_Sailor_Collar_L",
        [
            (center.x - radius_x * 0.04, front_y, z(0.710)),
            (center.x - radius_x * 0.42, front_y, z(0.815)),
            (center.x - radius_x * 0.58, front_y, z(0.800)),
            (center.x - radius_x * 0.12, front_y, z(0.680)),
        ],
        mats["beige"],
        thickness,
    )
    right_collar = panel(
        "Nocturne_Sailor_Collar_R",
        [
            (center.x + radius_x * 0.12, front_y, z(0.680)),
            (center.x + radius_x * 0.58, front_y, z(0.800)),
            (center.x + radius_x * 0.42, front_y, z(0.815)),
            (center.x + radius_x * 0.04, front_y, z(0.710)),
        ],
        mats["beige"],
        thickness,
    )
    back_y = center.y + back_radius_y * 1.08
    back_collar = panel(
        "Nocturne_Sailor_Collar_Back",
        [
            (center.x - radius_x * 0.68, back_y, z(0.805)),
            (center.x + radius_x * 0.68, back_y, z(0.805)),
            (center.x + radius_x * 0.50, back_y, z(0.755)),
            (center.x, back_y, z(0.720)),
            (center.x - radius_x * 0.50, back_y, z(0.755)),
        ],
        mats["beige"],
        thickness,
    )
    return panels, [left_collar, right_collar, back_collar], front_y


def _lower_body_weights(obj, armature, center_x, maximum_leg_weight):
    minimum_z = min(vertex.co.z for vertex in obj.data.vertices)
    maximum_z = max(vertex.co.z for vertex in obj.data.vertices)
    span_z = max(maximum_z - minimum_z, 1e-8)
    maximum_x = max(abs(vertex.co.x - center_x) for vertex in obj.data.vertices)
    transition = max(maximum_x * 0.20, 1e-8)
    assignments = {}
    for vertex in obj.data.vertices:
        lower_fraction = (maximum_z - vertex.co.z) / span_z
        leg_weight = maximum_leg_weight * lower_fraction**1.35
        side = 0.5 + 0.5 * math.tanh((vertex.co.x - center_x) / transition)
        assignments[vertex.index] = [
            ("hips", 1.0 - leg_weight),
            ("upper_leg_l", leg_weight * side),
            ("upper_leg_r", leg_weight * (1.0 - side)),
        ]
    semantic_weights(obj, armature, assignments)


def build(body, armature, mats):
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    center = (minimum + maximum) * 0.5

    def z(ratio):
        return minimum.z + height * ratio

    garments = []
    rigid = []
    clearance_objects = []
    bodice_panels, collar_panels, front_y = _build_bodice(center, height, z, mats)
    garments.extend(bodice_panels)
    garments.extend(collar_panels)
    clearance_objects.extend(bodice_panels)
    rigid.extend((obj, "chest") for obj in bodice_panels)
    rigid.extend((obj, "chest") for obj in collar_panels)

    skirt = frustum_shell(
        "Nocturne_Cloth_Skirt",
        center,
        [
            (z(0.390), height * 0.185, height * 0.134, 0.0),
            (z(0.420), height * 0.181, height * 0.130, 0.0),
            (z(0.450), height * 0.174, height * 0.124, 0.0),
            (z(0.480), height * 0.164, height * 0.116, 0.0),
            (z(0.510), height * 0.151, height * 0.105, 0.0),
            (z(0.540), height * 0.137, height * 0.094, 0.0),
            (z(0.565), height * 0.123, height * 0.085, 0.0),
            (z(0.585), height * 0.115, height * 0.079, 0.0),
        ],
        mats["black"],
        segments=72,
    )
    cloth = [bake_skirt(skirt, body)]
    frill = frustum_shell(
        "Nocturne_Cream_Hem_Frill",
        center,
        [
            (z(0.372), height * 0.194, height * 0.141, 0.0),
            (z(0.388), height * 0.190, height * 0.137, 0.0),
            (z(0.405), height * 0.185, height * 0.133, 0.0),
        ],
        mats["cream"],
        segments=72,
        scallops=12,
    )
    waist = frustum_shell(
        "Nocturne_Waist_Band",
        center,
        [
            (z(0.570), height * 0.120, height * 0.082, 0.0),
            (z(0.585), height * 0.117, height * 0.080, 0.0),
            (z(0.600), height * 0.114, height * 0.078, 0.0),
        ],
        mats["beige"],
        segments=64,
    )
    garments.extend([skirt, frill, waist])
    clearance_objects.extend([skirt, frill, waist])

    for side, upper, lower in (
        ("L", "upper_arm_l", "lower_arm_l"),
        ("R", "upper_arm_r", "lower_arm_r"),
    ):
        upper_start, upper_end = bone_segment(armature, upper)
        lower_start, lower_end = bone_segment(armature, lower)
        upper_axis = upper_end - upper_start
        puff = axis_shell(
            f"Nocturne_Puff_Sleeve_{side}",
            upper_start + upper_axis * 0.08,
            upper_start + upper_axis * 0.34,
            [
                height * 0.024,
                height * 0.031,
                height * 0.034,
                height * 0.030,
                height * 0.023,
            ],
            mats["black"],
        )
        warmer = axis_shell(
            f"Nocturne_Detached_Arm_Warmer_{side}",
            lower_start.lerp(lower_end, 0.06),
            lower_start.lerp(lower_end, 0.88),
            [
                height * 0.023,
                height * 0.028,
                height * 0.027,
                height * 0.024,
                height * 0.021,
            ],
            mats["black"],
        )
        cuff = axis_shell(
            f"Nocturne_Lace_Cuff_{side}",
            lower_start.lerp(lower_end, 0.78),
            lower_start.lerp(lower_end, 0.97),
            [height * 0.027, height * 0.030, height * 0.027, height * 0.023],
            mats["cream"],
        )
        garments.extend([puff, warmer, cuff])
        clearance_objects.extend([puff, warmer, cuff])
        rigid.extend([(puff, upper), (warmer, lower), (cuff, lower)])

    for side, lower, foot in (
        ("L", "lower_leg_l", "foot_l"),
        ("R", "lower_leg_r", "foot_r"),
    ):
        lower_start, lower_end = bone_segment(armature, lower)
        foot_start, foot_end = bone_segment(armature, foot)
        warmer = axis_shell(
            f"Nocturne_Leg_Warmer_{side}",
            lower_start.lerp(lower_end, 0.14),
            lower_start.lerp(lower_end, 0.82),
            [
                height * 0.031,
                height * 0.038,
                height * 0.040,
                height * 0.037,
                height * 0.031,
            ],
            mats["beige"],
        )
        shoe = sphere(
            f"Nocturne_Shoe_{side}",
            foot_start.lerp(foot_end, 0.56)
            + Vector((0.0, -height * 0.018, -height * 0.010)),
            (height * 0.040, height * 0.064, height * 0.025),
            mats["brown"],
        )
        garments.extend([warmer, shoe])
        clearance_objects.extend([warmer, shoe])
        rigid.extend([(warmer, lower), (shoe, foot)])

    head_start, head_end = bone_segment(armature, "head")
    head = head_start.lerp(head_end, 0.68)
    beret = sphere(
        "Nocturne_Beret",
        head + Vector((0.0, 0.0, height * 0.067)),
        (height * 0.084, height * 0.075, height * 0.027),
        mats["beige"],
    )
    garments.append(beret)
    rigid.append((beret, "head"))
    for side, sign in (("L", 1.0), ("R", -1.0)):
        ear = panel(
            f"Nocturne_Animal_Ear_{side}",
            [
                head + Vector((sign * height * 0.044, height * 0.006, height * 0.065)),
                head + Vector((sign * height * 0.070, height * 0.004, height * 0.118)),
                head + Vector((sign * height * 0.030, height * 0.003, height * 0.100)),
            ],
            mats["brown"],
            height * 0.003,
        )
        garments.append(ear)
        rigid.append((ear, "head"))

    neck_start, neck_end = bone_segment(armature, "neck")
    neck = neck_start.lerp(neck_end, 0.42)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=height * 0.042,
        minor_radius=height * 0.004,
        location=neck,
    )
    choker = bpy.context.object
    choker.name = "Nocturne_Choker"
    finish(choker, mats["beige"])
    amber = sphere(
        "Nocturne_Amber_Charm",
        neck + Vector((0.0, -height * 0.046, -height * 0.016)),
        (height * 0.012, height * 0.008, height * 0.017),
        mats["gold"],
    )
    garments.extend([choker, amber])
    clearance_objects.append(choker)
    rigid.extend([(choker, "neck"), (amber, "chest")])

    bow = Vector((center.x, front_y - height * 0.008, z(0.690)))
    bow_left = sphere(
        "Nocturne_Bow_Loop_L",
        bow + Vector((-height * 0.024, 0.0, 0.0)),
        (height * 0.027, height * 0.007, height * 0.017),
        mats["black"],
    )
    bow_right = sphere(
        "Nocturne_Bow_Loop_R",
        bow + Vector((height * 0.024, 0.0, 0.0)),
        (height * 0.027, height * 0.007, height * 0.017),
        mats["black"],
    )
    rabbit = sphere(
        "Nocturne_Rabbit_Charm",
        bow + Vector((0.0, -height * 0.007, 0.0)),
        (height * 0.014, height * 0.008, height * 0.019),
        mats["beige"],
    )
    garments.extend([bow_left, bow_right, rabbit])
    rigid.extend([(bow_left, "chest"), (bow_right, "chest"), (rabbit, "chest")])

    chest_start, chest_end = bone_segment(armature, "chest")
    wing_origin = chest_start.lerp(chest_end, 0.58) + Vector(
        (0.0, height * 0.135, height * 0.006)
    )
    wing_specs = (
        (38.0, 0.170, 0.043, 0.000),
        (10.0, 0.185, 0.049, -0.020),
        (-16.0, 0.160, 0.040, -0.040),
    )
    for side, sign in (("L", 1.0), ("R", -1.0)):
        for index, (angle_degrees, length_ratio, width_ratio, drop) in enumerate(
            wing_specs
        ):
            angle = math.radians(angle_degrees)
            root = wing_origin + Vector(
                (sign * height * (0.012 + index * 0.004), 0.0, height * drop)
            )
            length = height * length_ratio
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
                height * width_ratio,
                mats["white"],
            )
            garments.append(wing)
            rigid.append((wing, "chest"))

    tail = sphere(
        "Nocturne_Tail",
        Vector((center.x, center.y + height * 0.190, z(0.500))),
        (height * 0.043,) * 3,
        mats["brown"],
    )
    garments.append(tail)
    rigid.append((tail, "hips"))

    clearance = height * 0.0055
    clearance_records = [
        enforce_body_clearance(obj, body, clearance) for obj in clearance_objects
    ]
    cloth[0]["clearanceAdjustments"] = clearance_records

    _lower_body_weights(skirt, armature, center.x, 0.58)
    _lower_body_weights(frill, armature, center.x, 0.72)
    rigid_weight(waist, armature, "hips")
    for obj, semantic in rigid:
        rigid_weight(obj, armature, semantic)
    return garments, cloth
