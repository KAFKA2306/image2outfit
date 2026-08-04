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
    feather,
    frustum_shell,
    panel,
    rigid_weight,
    sphere,
    transfer_weights,
)


def build(body, armature, mats):
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    center = (minimum + maximum) * 0.5

    def z(ratio):
        return minimum.z + height * ratio

    deforming = []
    rigid = []

    bodice = frustum_shell(
        "Nocturne_Cropped_Bodice",
        center,
        [
            (z(0.60), height * 0.122, height * 0.082, 0.0),
            (z(0.65), height * 0.126, height * 0.087, 0.0),
            (z(0.70), height * 0.134, height * 0.094, -height * 0.003),
            (z(0.76), height * 0.145, height * 0.101, -height * 0.005),
            (z(0.82), height * 0.151, height * 0.105, -height * 0.004),
            (z(0.87), height * 0.142, height * 0.098, -height * 0.002),
            (z(0.91), height * 0.126, height * 0.088, 0.0),
        ],
        mats["black"],
    )
    deforming.append(bodice)

    front_y = center.y - height * 0.102
    back_y = center.y + height * 0.102
    left_collar = panel(
        "Nocturne_Sailor_Collar_L",
        [
            (center.x - height * 0.145, front_y, z(0.865)),
            (center.x - height * 0.030, front_y, z(0.895)),
            (center.x - height * 0.010, front_y, z(0.745)),
            (center.x - height * 0.112, front_y, z(0.790)),
        ],
        mats["beige"],
        height * 0.0025,
    )
    right_collar = panel(
        "Nocturne_Sailor_Collar_R",
        [
            (2 * center.x - x, y, zz)
            for x, y, zz in reversed(
                [
                    (center.x - height * 0.145, front_y, z(0.865)),
                    (center.x - height * 0.030, front_y, z(0.895)),
                    (center.x - height * 0.010, front_y, z(0.745)),
                    (center.x - height * 0.112, front_y, z(0.790)),
                ]
            )
        ],
        mats["beige"],
        height * 0.0025,
    )
    back_collar = panel(
        "Nocturne_Sailor_Collar_Back",
        [
            (center.x - height * 0.145, back_y, z(0.865)),
            (center.x + height * 0.145, back_y, z(0.865)),
            (center.x + height * 0.105, back_y, z(0.755)),
            (center.x, back_y, z(0.705)),
            (center.x - height * 0.105, back_y, z(0.755)),
        ],
        mats["beige"],
        height * 0.0025,
    )
    rigid.extend(
        [
            (left_collar, "chest"),
            (right_collar, "chest"),
            (back_collar, "chest"),
        ]
    )

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
    deforming.append(skirt)
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
    deforming.extend([frill, waist])

    for side, upper, lower in (
        ("L", "upper_arm_l", "lower_arm_l"),
        ("R", "upper_arm_r", "lower_arm_r"),
    ):
        upper_start, upper_end = bone_segment(armature, upper)
        lower_start, lower_end = bone_segment(armature, lower)
        upper_axis = upper_end - upper_start
        puff = axis_shell(
            f"Nocturne_Puff_Sleeve_{side}",
            upper_start + upper_axis * 0.04,
            upper_start + upper_axis * 0.43,
            [
                height * 0.040,
                height * 0.052,
                height * 0.058,
                height * 0.052,
                height * 0.038,
            ],
            mats["black"],
        )
        warmer = axis_shell(
            f"Nocturne_Detached_Arm_Warmer_{side}",
            upper_start + upper_axis * 0.56,
            lower_start.lerp(lower_end, 0.91),
            [
                height * 0.034,
                height * 0.039,
                height * 0.037,
                height * 0.032,
                height * 0.027,
            ],
            mats["black"],
        )
        cuff = axis_shell(
            f"Nocturne_Lace_Cuff_{side}",
            lower_start.lerp(lower_end, 0.80),
            lower_start.lerp(lower_end, 0.98),
            [height * 0.039, height * 0.043, height * 0.039, height * 0.032],
            mats["cream"],
        )
        deforming.extend([puff, warmer, cuff])

    for side, lower in (("L", "lower_leg_l"), ("R", "lower_leg_r")):
        lower_start, lower_end = bone_segment(armature, lower)
        warmer = axis_shell(
            f"Nocturne_Leg_Warmer_{side}",
            lower_start.lerp(lower_end, 0.08),
            lower_start.lerp(lower_end, 0.88),
            [
                height * 0.050,
                height * 0.058,
                height * 0.060,
                height * 0.056,
                height * 0.047,
            ],
            mats["beige"],
        )
        shoe = cube(
            f"Nocturne_Shoe_{side}",
            lower_end + Vector((0.0, -height * 0.035, -height * 0.018)),
            (height * 0.046, height * 0.078, height * 0.034),
            mats["brown"],
        )
        deforming.extend([warmer, shoe])

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
                head
                + Vector((sign * height * 0.055, height * 0.010, height * 0.075)),
                head
                + Vector((sign * height * 0.090, height * 0.006, height * 0.145)),
                head
                + Vector((sign * height * 0.040, height * 0.004, height * 0.122)),
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
    choker.data.materials.append(mats["beige"])
    choker["image2outfit_role"] = "garment"
    amber = sphere(
        "Nocturne_Amber_Charm",
        neck + Vector((0.0, -height * 0.050, -height * 0.018)),
        (height * 0.016, height * 0.010, height * 0.022),
        mats["gold"],
    )
    rigid.extend([(choker, "neck"), (amber, "chest")])

    bow = Vector((center.x, front_y - height * 0.010, z(0.745)))
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
    rigid.extend(
        [(bow_left, "chest"), (bow_right, "chest"), (rabbit, "chest")]
    )

    chest_start, chest_end = bone_segment(armature, "chest")
    wing_origin = chest_start.lerp(chest_end, 0.60) + Vector(
        (0.0, height * 0.115, height * 0.010)
    )
    for side, sign in (("L", 1.0), ("R", -1.0)):
        for index in range(6):
            angle = math.radians(38 - index * 13)
            length = height * (0.155 + index * 0.022)
            root = wing_origin + Vector(
                (sign * height * (0.018 + index * 0.004), 0.0, -index * height * 0.008)
            )
            tip = root + Vector(
                (
                    sign * length * math.cos(angle),
                    0.0,
                    length * math.sin(angle),
                )
            )
            wing = feather(
                f"Nocturne_Wing_{side}_{index:02d}",
                root,
                tip,
                height * (0.032 + index * 0.003),
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
