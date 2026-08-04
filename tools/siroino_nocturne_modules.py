"""Modular garment assembly for the Nocturne Angel set."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from siroino_nocturne_geometry import (
    bake_skirt,
    bone_segment,
    bounds,
    cone,
    cube,
    finish,
    panel,
    sphere,
    transfer_weights,
    tube,
)


def build(body, armature, mats):
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    center = (minimum + maximum) * 0.5

    def z(ratio):
        return minimum.z + height * ratio

    items = []
    items.append(
        cone(
            "Nocturne_Cropped_Bodice",
            Vector((center.x, center.y, z(0.69))),
            height * 0.13,
            height * 0.11,
            height * 0.27,
            mats["black"],
        )
    )
    front_y = center.y - height * 0.09
    back_y = center.y + height * 0.09
    left = [
        (center.x - height * 0.14, front_y, z(0.80)),
        (center.x - height * 0.03, front_y, z(0.65)),
        (center.x - height * 0.01, front_y, z(0.75)),
    ]
    items.extend(
        [
            panel(
                "Nocturne_Sailor_Collar_L",
                left,
                mats["beige"],
                height * 0.002,
            ),
            panel(
                "Nocturne_Sailor_Collar_R",
                [(2 * center.x - x, y, zz) for x, y, zz in reversed(left)],
                mats["beige"],
                height * 0.002,
            ),
            panel(
                "Nocturne_Sailor_Collar_Back",
                [
                    (center.x - height * 0.14, back_y, z(0.80)),
                    (center.x + height * 0.14, back_y, z(0.80)),
                    (center.x + height * 0.10, back_y, z(0.67)),
                    (center.x - height * 0.10, back_y, z(0.67)),
                ],
                mats["beige"],
                height * 0.002,
            ),
        ]
    )
    skirt = cone(
        "Nocturne_Cloth_Skirt",
        Vector((center.x, center.y, z(0.45))),
        height * 0.25,
        height * 0.13,
        height * 0.26,
        mats["black"],
        end_fill_type="NOTHING",
    )
    cloth = [bake_skirt(skirt, body)]
    solidify = skirt.modifiers.new("Skirt thickness", "SOLIDIFY")
    solidify.thickness = height * 0.002
    bpy.context.view_layer.objects.active = skirt
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    items.extend(
        [
            skirt,
            cone(
                "Nocturne_Cream_Hem_Frill",
                Vector((center.x, center.y, z(0.31))),
                height * 0.27,
                height * 0.24,
                height * 0.05,
                mats["cream"],
            ),
            cone(
                "Nocturne_Waist_Band",
                Vector((center.x, center.y, z(0.57))),
                height * 0.135,
                height * 0.135,
                height * 0.03,
                mats["beige"],
            ),
        ]
    )
    for side, upper, lower in (
        ("L", "upper_arm_l", "lower_arm_l"),
        ("R", "upper_arm_r", "lower_arm_r"),
    ):
        upper_start, upper_end = bone_segment(armature, upper)
        lower_start, lower_end = bone_segment(armature, lower)
        axis = upper_end - upper_start
        items.extend(
            [
                tube(
                    f"Nocturne_Puff_Sleeve_{side}",
                    upper_start + axis * 0.05,
                    upper_start + axis * 0.46,
                    height * 0.075,
                    height * 0.055,
                    mats["black"],
                ),
                tube(
                    f"Nocturne_Detached_Arm_Warmer_{side}",
                    upper_start + axis * 0.58,
                    lower_start.lerp(lower_end, 0.93),
                    height * 0.052,
                    height * 0.038,
                    mats["black"],
                ),
                tube(
                    f"Nocturne_Lace_Cuff_{side}",
                    lower_start.lerp(lower_end, 0.86),
                    lower_start.lerp(lower_end, 0.99),
                    height * 0.05,
                    height * 0.045,
                    mats["cream"],
                ),
            ]
        )
    for side, upper, lower in (
        ("L", "upper_leg_l", "lower_leg_l"),
        ("R", "upper_leg_r", "lower_leg_r"),
    ):
        _, upper_end = bone_segment(armature, upper)
        lower_start, lower_end = bone_segment(armature, lower)
        items.extend(
            [
                tube(
                    f"Nocturne_Leg_Warmer_{side}",
                    upper_end.lerp(lower_start, 0.7),
                    lower_start.lerp(lower_end, 0.94),
                    height * 0.07,
                    height * 0.06,
                    mats["beige"],
                ),
                cube(
                    f"Nocturne_Shoe_{side}",
                    lower_end
                    + Vector((0.0, -height * 0.04, -height * 0.015)),
                    (height * 0.055, height * 0.10, height * 0.04),
                    mats["brown"],
                ),
            ]
        )
    head_start, head_end = bone_segment(armature, "head")
    head = head_start.lerp(head_end, 0.68)
    items.append(
        sphere(
            "Nocturne_Beret",
            head + Vector((0.0, 0.0, height * 0.08)),
            (height * 0.11, height * 0.095, height * 0.04),
            mats["beige"],
        )
    )
    for side, sign in (("L", 1.0), ("R", -1.0)):
        items.append(
            cone(
                f"Nocturne_Animal_Ear_{side}",
                head + Vector((sign * height * 0.07, 0.0, height * 0.14)),
                height * 0.03,
                height * 0.006,
                height * 0.09,
                mats["brown"],
            )
        )
    neck_start, neck_end = bone_segment(armature, "neck")
    neck = neck_start.lerp(neck_end, 0.42)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=height * 0.05,
        minor_radius=height * 0.006,
        location=neck,
    )
    choker = finish(bpy.context.object, mats["beige"])
    choker.name = "Nocturne_Choker"
    items.extend(
        [
            choker,
            sphere(
                "Nocturne_Amber_Charm",
                neck + Vector((0.0, -height * 0.055, -height * 0.02)),
                (height * 0.018, height * 0.012, height * 0.024),
                mats["gold"],
            ),
        ]
    )
    bow = Vector((center.x, front_y - height * 0.02, z(0.66)))
    items.extend(
        [
            sphere(
                "Nocturne_Bow_Loop_L",
                bow + Vector((-height * 0.045, 0.0, 0.0)),
                (height * 0.052, height * 0.012, height * 0.032),
                mats["black"],
            ),
            sphere(
                "Nocturne_Bow_Loop_R",
                bow + Vector((height * 0.045, 0.0, 0.0)),
                (height * 0.052, height * 0.012, height * 0.032),
                mats["black"],
            ),
            sphere(
                "Nocturne_Rabbit_Charm",
                bow + Vector((0.0, -height * 0.015, 0.0)),
                (height * 0.025, height * 0.014, height * 0.032),
                mats["beige"],
            ),
        ]
    )
    chest_start, chest_end = bone_segment(armature, "chest")
    origin = chest_start.lerp(chest_end, 0.62) + Vector(
        (0.0, height * 0.09, 0.0)
    )
    for side, sign in (("L", 1.0), ("R", -1.0)):
        for index in range(12):
            angle = math.radians(18 + index * 5)
            distance = height * (0.10 + index * 0.025)
            location = origin + Vector(
                (
                    sign * distance * math.cos(angle),
                    height * 0.015,
                    distance * math.sin(angle) - height * 0.04,
                )
            )
            items.append(
                sphere(
                    f"Nocturne_Wing_{side}_{index:02d}",
                    location,
                    (
                        height * (0.06 + index * 0.003),
                        height * 0.012,
                        height * 0.025,
                    ),
                    mats["white"],
                    (0.0, sign * angle, sign * math.radians(18)),
                )
            )
    items.append(
        sphere(
            "Nocturne_Tail",
            Vector((center.x, center.y + height * 0.16, z(0.49))),
            (height * 0.075,) * 3,
            mats["brown"],
        )
    )
    for obj in items:
        transfer_weights(obj, body, armature)
    return items, cloth
