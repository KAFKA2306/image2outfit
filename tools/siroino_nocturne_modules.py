"""Modular garment assembly for the Nocturne Angel set."""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

from siroino_nocturne_geometry import (
    add_outward_thickness,
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
    project_to_body,
    rigid_weight,
    sewn_bodice_shell,
    sphere,
    transfer_weights,
    triangulate,
)


def _build_sewn_bodice(body, center, height, z, mats):
    bodice = sewn_bodice_shell(
        "Nocturne_Sewn_Bodice",
        center,
        [
            (z(0.520), height * 0.128, height * 0.086, 0.0),
            (z(0.570), height * 0.130, height * 0.088, 0.0),
            (z(0.620), height * 0.134, height * 0.091, 0.0),
            (z(0.680), height * 0.139, height * 0.095, 0.0),
            (z(0.765), height * 0.144, height * 0.099, 0.0),
        ],
        mats["black"],
        segments=72,
    )
    project_to_body(bodice, body, height * 0.0090)
    add_outward_thickness(bodice, height * 0.0022)
    triangulate(bodice)

    front_y = center.y - height * 0.090
    collar_left = panel(
        "Nocturne_Sailor_Collar_L",
        [
            (center.x - height * 0.010, front_y, z(0.690)),
            (center.x - height * 0.050, front_y, z(0.770)),
            (center.x - height * 0.078, front_y, z(0.756)),
            (center.x - height * 0.020, front_y, z(0.668)),
        ],
        mats["beige"],
        height * 0.0018,
    )
    collar_right = panel(
        "Nocturne_Sailor_Collar_R",
        [
            (center.x + height * 0.020, front_y, z(0.668)),
            (center.x + height * 0.078, front_y, z(0.756)),
            (center.x + height * 0.050, front_y, z(0.770)),
            (center.x + height * 0.010, front_y, z(0.690)),
        ],
        mats["beige"],
        height * 0.0018,
    )
    for collar in (collar_left, collar_right):
        project_to_body(collar, body, height * 0.012)
    return bodice, [collar_left, collar_right], front_y


def _build_limb_accessories(armature, height, mats):
    garments = []
    weighted = []
    clearance = []
    for side, upper, lower in (
        ("L", "upper_arm_l", "lower_arm_l"),
        ("R", "upper_arm_r", "lower_arm_r"),
    ):
        upper_start, upper_end = bone_segment(armature, upper)
        lower_start, lower_end = bone_segment(armature, lower)
        upper_axis = upper_end - upper_start
        puff = axis_shell(
            f"Nocturne_Puff_Sleeve_{side}",
            upper_start + upper_axis * 0.10,
            upper_start + upper_axis * 0.28,
            [height * 0.014, height * 0.018, height * 0.020, height * 0.017],
            mats["black"],
            segments=36,
        )
        warmer = axis_shell(
            f"Nocturne_Detached_Arm_Warmer_{side}",
            lower_start.lerp(lower_end, 0.16),
            lower_start.lerp(lower_end, 0.76),
            [height * 0.014, height * 0.017, height * 0.017, height * 0.014],
            mats["black"],
            segments=36,
        )
        cuff = axis_shell(
            f"Nocturne_Lace_Cuff_{side}",
            lower_start.lerp(lower_end, 0.72),
            lower_start.lerp(lower_end, 0.88),
            [height * 0.017, height * 0.019, height * 0.016],
            mats["cream"],
            segments=36,
        )
        garments.extend([puff, warmer, cuff])
        weighted.extend([puff, warmer, cuff])
        clearance.extend([puff, warmer, cuff])

    for side, lower, foot in (
        ("L", "lower_leg_l", "foot_l"),
        ("R", "lower_leg_r", "foot_r"),
    ):
        lower_start, lower_end = bone_segment(armature, lower)
        foot_start, foot_end = bone_segment(armature, foot)
        warmer = axis_shell(
            f"Nocturne_Leg_Warmer_{side}",
            lower_start.lerp(lower_end, 0.22),
            lower_start.lerp(lower_end, 0.70),
            [height * 0.020, height * 0.024, height * 0.024, height * 0.020],
            mats["beige"],
            segments=36,
        )
        shoe = sphere(
            f"Nocturne_Shoe_{side}",
            foot_start.lerp(foot_end, 0.56)
            + Vector((0.0, -height * 0.010, -height * 0.005)),
            (height * 0.026, height * 0.041, height * 0.016),
            mats["brown"],
        )
        garments.extend([warmer, shoe])
        weighted.extend([warmer, shoe])
        clearance.extend([warmer, shoe])
    return garments, weighted, clearance


def _build_wings(armature, height, mats):
    chest_start, chest_end = bone_segment(armature, "chest")
    origin = chest_start.lerp(chest_end, 0.58) + Vector(
        (0.0, height * 0.098, height * 0.004)
    )
    specs = (
        (54.0, 0.105, 0.012, 0.006, 0.012),
        (24.0, 0.125, 0.014, 0.006, -0.005),
        (-12.0, 0.115, 0.013, 0.006, -0.024),
    )
    wings = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        for index, (
            angle_degrees,
            length_ratio,
            width_ratio,
            depth_ratio,
            drop,
        ) in enumerate(specs):
            angle = math.radians(angle_degrees)
            root = origin + Vector(
                (sign * height * (0.008 + index * 0.002), 0.0, height * drop)
            )
            length = height * length_ratio
            tip = root + Vector(
                (
                    sign * length * math.cos(angle),
                    height * 0.010,
                    length * math.sin(angle),
                )
            )
            wings.append(
                ellipsoid_between(
                    f"Nocturne_Wing_{side}_{index:02d}",
                    root,
                    tip,
                    height * width_ratio,
                    height * depth_ratio,
                    mats["white"],
                )
            )
    return wings


def build(body, armature, mats):
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    center = (minimum + maximum) * 0.5

    def z(ratio):
        return minimum.z + height * ratio

    garments = []
    weighted = []
    rigid = []
    clearance_objects = []

    bodice, collars, front_y = _build_sewn_bodice(body, center, height, z, mats)
    garments.extend([bodice, *collars])
    weighted.extend([bodice, *collars])
    clearance_objects.extend([bodice, *collars])

    skirt = pleated_shell(
        "Nocturne_Cloth_Skirt",
        center,
        [
            (z(0.445), height * 0.148, height * 0.103, 0.0),
            (z(0.466), height * 0.143, height * 0.099, 0.0),
            (z(0.487), height * 0.137, height * 0.095, 0.0),
            (z(0.508), height * 0.129, height * 0.089, 0.0),
            (z(0.529), height * 0.121, height * 0.083, 0.0),
            (z(0.550), height * 0.114, height * 0.078, 0.0),
        ],
        mats["black"],
        segments=96,
        pleats=12,
        fold=0.080,
    )
    cloth = [bake_skirt(skirt, body)]
    frill = pleated_shell(
        "Nocturne_Cream_Hem_Frill",
        center,
        [
            (z(0.432), height * 0.154, height * 0.108, 0.0),
            (z(0.446), height * 0.151, height * 0.105, 0.0),
            (z(0.460), height * 0.147, height * 0.102, 0.0),
        ],
        mats["cream"],
        segments=96,
        pleats=12,
        fold=0.095,
    )
    waist = frustum_shell(
        "Nocturne_Waist_Band",
        center,
        [
            (z(0.540), height * 0.118, height * 0.081, 0.0),
            (z(0.552), height * 0.115, height * 0.079, 0.0),
            (z(0.564), height * 0.112, height * 0.077, 0.0),
        ],
        mats["beige"],
        segments=64,
    )
    garments.extend([skirt, frill, waist])
    weighted.extend([skirt, frill, waist])
    clearance_objects.extend([skirt, waist])

    limb_garments, limb_weighted, limb_clearance = _build_limb_accessories(
        armature, height, mats
    )
    garments.extend(limb_garments)
    weighted.extend(limb_weighted)
    clearance_objects.extend(limb_clearance)

    neck_start, neck_end = bone_segment(armature, "neck")
    neck = neck_start.lerp(neck_end, 0.36)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=height * 0.038,
        minor_radius=height * 0.003,
        location=neck,
    )
    choker = bpy.context.object
    choker.name = "Nocturne_Choker"
    finish(choker, mats["beige"])
    amber = sphere(
        "Nocturne_Amber_Charm",
        neck + Vector((0.0, -height * 0.041, -height * 0.012)),
        (height * 0.009, height * 0.006, height * 0.013),
        mats["gold"],
    )
    garments.extend([choker, amber])
    weighted.append(choker)
    clearance_objects.append(choker)
    rigid.append((amber, "chest"))

    bow = Vector((center.x, front_y - height * 0.005, z(0.650)))
    bow_left = sphere(
        "Nocturne_Bow_Loop_L",
        bow + Vector((-height * 0.019, 0.0, 0.0)),
        (height * 0.020, height * 0.005, height * 0.012),
        mats["black"],
    )
    bow_right = sphere(
        "Nocturne_Bow_Loop_R",
        bow + Vector((height * 0.019, 0.0, 0.0)),
        (height * 0.020, height * 0.005, height * 0.012),
        mats["black"],
    )
    rabbit = sphere(
        "Nocturne_Rabbit_Charm",
        bow + Vector((0.0, -height * 0.005, -height * 0.002)),
        (height * 0.010, height * 0.006, height * 0.014),
        mats["beige"],
    )
    garments.extend([bow_left, bow_right, rabbit])
    rigid.extend([(bow_left, "chest"), (bow_right, "chest"), (rabbit, "chest")])

    wings = _build_wings(armature, height, mats)
    garments.extend(wings)
    rigid.extend((wing, "chest") for wing in wings)

    tail = sphere(
        "Nocturne_Tail",
        Vector((center.x, center.y + height * 0.145, z(0.500))),
        (height * 0.024,) * 3,
        mats["brown"],
    )
    garments.append(tail)
    rigid.append((tail, "hips"))

    clearance = height * 0.011
    clearance_records = [
        enforce_body_clearance(
            obj,
            body,
            clearance,
            maximum_search=height * 0.075,
            iterations=3,
        )
        for obj in clearance_objects
    ]
    cloth[0]["clearanceAdjustments"] = clearance_records

    for obj in weighted:
        transfer_weights(obj, body, armature)
    for obj, semantic in rigid:
        rigid_weight(obj, armature, semantic)
    return garments, cloth
