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
    ellipsoid_between,
    enforce_body_clearance,
    finish,
    frustum_shell,
    panel,
    pleated_shell,
    rigid_weight,
    sphere,
    transfer_weights,
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


def _angular_row(center, angles, z_value, radius_x, radius_y):
    return [
        Vector(
            (
                center.x + radius_x * math.cos(math.radians(angle)),
                center.y + radius_y * math.sin(math.radians(angle)),
                z_value,
            )
        )
        for angle in angles
    ]


def _build_bodice(center, height, z, mats):
    radius_x = height * 0.125
    radius_y = height * 0.082
    levels = (0.525, 0.585, 0.645, 0.705, 0.780)
    left_angles = (
        (-170, -150, -130, -110, -90),
        (-170, -150, -130, -110, -90),
        (-168, -148, -128, -108, -92),
        (-165, -148, -132, -118, -104),
        (-158, -146, -136, -126, -116),
    )
    right_angles = tuple(
        tuple(-angle - 180 for angle in reversed(row)) for row in left_angles
    )
    back_angles = (
        (20, 55, 90, 125, 160),
        (20, 55, 90, 125, 160),
        (22, 56, 90, 124, 158),
        (28, 60, 90, 120, 152),
        (36, 64, 90, 116, 144),
    )
    side_levels = levels[:-1]
    left_side_angles = ((160, 180, 200),) * len(side_levels)
    right_side_angles = ((-20, 0, 20),) * len(side_levels)

    def rows(angle_rows, ratios):
        return [
            _angular_row(center, angle_row, z(ratio), radius_x, radius_y)
            for angle_row, ratio in zip(angle_rows, ratios, strict=True)
        ]

    thickness = height * 0.0020
    panels = [
        _grid_panel(
            "Nocturne_Bodice_Front_L",
            rows(left_angles, levels),
            mats["black"],
            thickness,
        ),
        _grid_panel(
            "Nocturne_Bodice_Front_R",
            rows(right_angles, levels),
            mats["black"],
            thickness,
        ),
        _grid_panel(
            "Nocturne_Bodice_Back",
            rows(back_angles, levels),
            mats["black"],
            thickness,
        ),
        _grid_panel(
            "Nocturne_Bodice_Side_L",
            rows(left_side_angles, side_levels),
            mats["black"],
            thickness,
        ),
        _grid_panel(
            "Nocturne_Bodice_Side_R",
            rows(right_side_angles, side_levels),
            mats["black"],
            thickness,
        ),
    ]
    front_y = center.y - radius_y * 1.08
    left_collar = panel(
        "Nocturne_Sailor_Collar_L",
        [
            (center.x - radius_x * 0.12, front_y, z(0.690)),
            (center.x - radius_x * 0.50, front_y, z(0.785)),
            (center.x - radius_x * 0.67, front_y, z(0.770)),
            (center.x - radius_x * 0.20, front_y, z(0.665)),
        ],
        mats["beige"],
        thickness,
    )
    right_collar = panel(
        "Nocturne_Sailor_Collar_R",
        [
            (center.x + radius_x * 0.20, front_y, z(0.665)),
            (center.x + radius_x * 0.67, front_y, z(0.770)),
            (center.x + radius_x * 0.50, front_y, z(0.785)),
            (center.x + radius_x * 0.12, front_y, z(0.690)),
        ],
        mats["beige"],
        thickness,
    )
    back_y = center.y + radius_y * 1.08
    back_collar = panel(
        "Nocturne_Sailor_Collar_Back",
        [
            (center.x - radius_x * 0.62, back_y, z(0.785)),
            (center.x + radius_x * 0.62, back_y, z(0.785)),
            (center.x + radius_x * 0.46, back_y, z(0.735)),
            (center.x, back_y, z(0.705)),
            (center.x - radius_x * 0.46, back_y, z(0.735)),
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

    garments = []
    skinweighted = []
    rigid = []
    clearance_specs = []

    bodice_panels, collar_panels, front_y = _build_bodice(center, height, z, mats)
    garments.extend(bodice_panels)
    garments.extend(collar_panels)
    skinweighted.extend(bodice_panels)
    skinweighted.extend(collar_panels)
    clearance_specs.extend((obj, {}) for obj in bodice_panels + collar_panels)

    skirt = pleated_shell(
        "Nocturne_Cloth_Skirt",
        center,
        [
            (z(0.418), height * 0.158, height * 0.112, 0.0),
            (z(0.442), height * 0.154, height * 0.109, 0.0),
            (z(0.466), height * 0.148, height * 0.104, 0.0),
            (z(0.490), height * 0.140, height * 0.098, 0.0),
            (z(0.514), height * 0.131, height * 0.091, 0.0),
            (z(0.538), height * 0.122, height * 0.085, 0.0),
            (z(0.562), height * 0.115, height * 0.079, 0.0),
        ],
        mats["black"],
        segments=96,
        pleats=12,
        fold=0.085,
    )
    cloth = [bake_skirt(skirt, body)]
    frill = pleated_shell(
        "Nocturne_Cream_Hem_Frill",
        center,
        [
            (z(0.402), height * 0.166, height * 0.118, 0.0),
            (z(0.420), height * 0.162, height * 0.115, 0.0),
            (z(0.438), height * 0.157, height * 0.111, 0.0),
        ],
        mats["cream"],
        segments=96,
        pleats=12,
        fold=0.105,
    )
    waist = frustum_shell(
        "Nocturne_Waist_Band",
        center,
        [
            (z(0.548), height * 0.120, height * 0.083, 0.0),
            (z(0.560), height * 0.117, height * 0.081, 0.0),
            (z(0.572), height * 0.114, height * 0.079, 0.0),
        ],
        mats["beige"],
        segments=64,
    )
    garments.extend([skirt, frill, waist])
    skinweighted.extend([skirt, frill, waist])
    clearance_specs.extend(
        [
            (skirt, {"only_above": z(0.525)}),
            (waist, {}),
        ]
    )

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
            upper_start + upper_axis * 0.31,
            [
                height * 0.017,
                height * 0.022,
                height * 0.025,
                height * 0.022,
                height * 0.017,
            ],
            mats["black"],
        )
        warmer = axis_shell(
            f"Nocturne_Detached_Arm_Warmer_{side}",
            lower_start.lerp(lower_end, 0.10),
            lower_start.lerp(lower_end, 0.82),
            [
                height * 0.017,
                height * 0.021,
                height * 0.022,
                height * 0.020,
                height * 0.017,
            ],
            mats["black"],
        )
        cuff = axis_shell(
            f"Nocturne_Lace_Cuff_{side}",
            lower_start.lerp(lower_end, 0.76),
            lower_start.lerp(lower_end, 0.93),
            [height * 0.020, height * 0.023, height * 0.021, height * 0.018],
            mats["cream"],
        )
        garments.extend([puff, warmer, cuff])
        skinweighted.extend([puff, warmer, cuff])
        clearance_specs.extend((obj, {}) for obj in (puff, warmer, cuff))

    for side, lower, foot in (
        ("L", "lower_leg_l", "foot_l"),
        ("R", "lower_leg_r", "foot_r"),
    ):
        lower_start, lower_end = bone_segment(armature, lower)
        foot_start, foot_end = bone_segment(armature, foot)
        warmer = axis_shell(
            f"Nocturne_Leg_Warmer_{side}",
            lower_start.lerp(lower_end, 0.17),
            lower_start.lerp(lower_end, 0.76),
            [
                height * 0.024,
                height * 0.029,
                height * 0.031,
                height * 0.029,
                height * 0.024,
            ],
            mats["beige"],
        )
        shoe = sphere(
            f"Nocturne_Shoe_{side}",
            foot_start.lerp(foot_end, 0.58)
            + Vector((0.0, -height * 0.012, -height * 0.007)),
            (height * 0.030, height * 0.047, height * 0.019),
            mats["brown"],
        )
        garments.extend([warmer, shoe])
        skinweighted.extend([warmer, shoe])
        clearance_specs.extend((obj, {}) for obj in (warmer, shoe))

    head_start, head_end = bone_segment(armature, "head")
    head = head_start.lerp(head_end, 0.25)
    beret = sphere(
        "Nocturne_Beret",
        head + Vector((0.0, 0.0, height * 0.020)),
        (height * 0.063, height * 0.056, height * 0.018),
        mats["beige"],
    )
    garments.append(beret)
    rigid.append((beret, "head"))
    for side, sign in (("L", 1.0), ("R", -1.0)):
        ear = panel(
            f"Nocturne_Animal_Ear_{side}",
            [
                head + Vector((sign * height * 0.030, 0.0, height * 0.028)),
                head + Vector((sign * height * 0.051, 0.0, height * 0.071)),
                head + Vector((sign * height * 0.018, 0.0, height * 0.058)),
            ],
            mats["brown"],
            height * 0.0025,
        )
        garments.append(ear)
        rigid.append((ear, "head"))

    neck_start, neck_end = bone_segment(armature, "neck")
    neck = neck_start.lerp(neck_end, 0.40)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=height * 0.040,
        minor_radius=height * 0.0035,
        location=neck,
    )
    choker = bpy.context.object
    choker.name = "Nocturne_Choker"
    finish(choker, mats["beige"])
    amber = sphere(
        "Nocturne_Amber_Charm",
        neck + Vector((0.0, -height * 0.043, -height * 0.014)),
        (height * 0.011, height * 0.007, height * 0.015),
        mats["gold"],
    )
    garments.extend([choker, amber])
    skinweighted.append(choker)
    clearance_specs.append((choker, {}))
    rigid.append((amber, "chest"))

    bow = Vector((center.x, front_y - height * 0.006, z(0.655)))
    bow_left = sphere(
        "Nocturne_Bow_Loop_L",
        bow + Vector((-height * 0.021, 0.0, 0.0)),
        (height * 0.023, height * 0.006, height * 0.014),
        mats["black"],
    )
    bow_right = sphere(
        "Nocturne_Bow_Loop_R",
        bow + Vector((height * 0.021, 0.0, 0.0)),
        (height * 0.023, height * 0.006, height * 0.014),
        mats["black"],
    )
    rabbit = sphere(
        "Nocturne_Rabbit_Charm",
        bow + Vector((0.0, -height * 0.006, -height * 0.003)),
        (height * 0.012, height * 0.007, height * 0.016),
        mats["beige"],
    )
    garments.extend([bow_left, bow_right, rabbit])
    rigid.extend([(bow_left, "chest"), (bow_right, "chest"), (rabbit, "chest")])

    chest_start, chest_end = bone_segment(armature, "chest")
    wing_origin = chest_start.lerp(chest_end, 0.58) + Vector(
        (0.0, height * 0.110, height * 0.005)
    )
    wing_specs = (
        (48.0, 0.125, 0.020, 0.009, 0.012),
        (20.0, 0.145, 0.023, 0.010, -0.006),
        (-8.0, 0.138, 0.022, 0.010, -0.024),
        (-34.0, 0.112, 0.019, 0.009, -0.040),
    )
    for side, sign in (("L", 1.0), ("R", -1.0)):
        for index, (angle_degrees, length_ratio, width_ratio, depth_ratio, drop) in enumerate(
            wing_specs
        ):
            angle = math.radians(angle_degrees)
            root = wing_origin + Vector(
                (sign * height * (0.010 + index * 0.003), 0.0, height * drop)
            )
            length = height * length_ratio
            tip = root + Vector(
                (
                    sign * length * math.cos(angle),
                    height * 0.008,
                    length * math.sin(angle),
                )
            )
            wing = ellipsoid_between(
                f"Nocturne_Wing_{side}_{index:02d}",
                root,
                tip,
                height * width_ratio,
                height * depth_ratio,
                mats["white"],
            )
            garments.append(wing)
            rigid.append((wing, "chest"))

    tail = sphere(
        "Nocturne_Tail",
        Vector((center.x, center.y + height * 0.155, z(0.500))),
        (height * 0.030,) * 3,
        mats["brown"],
    )
    garments.append(tail)
    rigid.append((tail, "hips"))

    clearance = height * 0.0065
    clearance_records = [
        enforce_body_clearance(
            obj,
            body,
            clearance,
            maximum_search=height * 0.060,
            **options,
        )
        for obj, options in clearance_specs
    ]
    cloth[0]["clearanceAdjustments"] = clearance_records

    for obj in skinweighted:
        transfer_weights(obj, body, armature)
    for obj, semantic in rigid:
        rigid_weight(obj, armature, semantic)
    return garments, cloth
