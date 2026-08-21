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
    project_to_body(bodice, body, height * 0.016)
    add_outward_thickness(bodice, height * 0.0030)
    triangulate(bodice)

    front_y = center.y - height * 0.105
    front_inset = panel(
        "Nocturne_Bodice_Front_Inset",
        [
            (center.x - height * 0.070, front_y, z(0.535)),
            (center.x + height * 0.070, front_y, z(0.535)),
            (center.x + height * 0.062, front_y, z(0.686)),
            (center.x - height * 0.062, front_y, z(0.686)),
        ],
        mats["black"],
        height * 0.0028,
    )
    v_left = panel(
        "Nocturne_Bodice_V_L",
        [
            (center.x - height * 0.060, front_y, z(0.675)),
            (center.x - height * 0.080, front_y, z(0.748)),
            (center.x - height * 0.050, front_y, z(0.775)),
            (center.x - height * 0.006, front_y, z(0.690)),
        ],
        mats["black"],
        height * 0.0028,
    )
    v_right = panel(
        "Nocturne_Bodice_V_R",
        [
            (center.x + height * 0.006, front_y, z(0.690)),
            (center.x + height * 0.050, front_y, z(0.775)),
            (center.x + height * 0.080, front_y, z(0.748)),
            (center.x + height * 0.060, front_y, z(0.675)),
        ],
        mats["black"],
        height * 0.0028,
    )
    collar_left = panel(
        "Nocturne_Sailor_Collar_L",
        [
            (center.x - height * 0.008, front_y, z(0.694)),
            (center.x - height * 0.048, front_y, z(0.768)),
            (center.x - height * 0.074, front_y, z(0.754)),
            (center.x - height * 0.021, front_y, z(0.680)),
        ],
        mats["beige"],
        height * 0.0018,
    )
    collar_right = panel(
        "Nocturne_Sailor_Collar_R",
        [
            (center.x + height * 0.021, front_y, z(0.680)),
            (center.x + height * 0.074, front_y, z(0.754)),
            (center.x + height * 0.048, front_y, z(0.768)),
            (center.x + height * 0.008, front_y, z(0.694)),
        ],
        mats["beige"],
        height * 0.0018,
    )
    overlays = [front_inset, v_left, v_right, collar_left, collar_right]
    for overlay in overlays:
        project_to_body(overlay, body, height * 0.019)
    return bodice, overlays, front_y


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
            upper_start + upper_axis * 0.08,
            upper_start + upper_axis * 0.30,
            [height * 0.017, height * 0.022, height * 0.023, height * 0.019],
            mats["black"],
            segments=36,
        )
        warmer = axis_shell(
            f"Nocturne_Detached_Arm_Warmer_{side}",
            lower_start.lerp(lower_end, 0.14),
            lower_start.lerp(lower_end, 0.78),
            [height * 0.017, height * 0.020, height * 0.020, height * 0.017],
            mats["black"],
            segments=36,
        )
        cuff = axis_shell(
            f"Nocturne_Lace_Cuff_{side}",
            lower_start.lerp(lower_end, 0.72),
            lower_start.lerp(lower_end, 0.90),
            [height * 0.020, height * 0.022, height * 0.019],
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
            lower_start.lerp(lower_end, 0.20),
            lower_start.lerp(lower_end, 0.72),
            [height * 0.024, height * 0.028, height * 0.028, height * 0.023],
            mats["beige"],
            segments=36,
        )
        shoe = sphere(
            f"Nocturne_Shoe_{side}",
            foot_start.lerp(foot_end, 0.58)
            + Vector((0.0, -height * 0.014, -height * 0.006)),
            (height * 0.031, height * 0.047, height * 0.019),
            mats["brown"],
        )
        garments.extend([warmer, shoe])
        weighted.extend([warmer, shoe])
        clearance.extend([warmer, shoe])
    return garments, weighted, clearance


def _build_wings(armature, height, mats):
    chest_start, chest_end = bone_segment(armature, "chest")
    anchor = chest_start.lerp(chest_end, 0.58) + Vector(
        (0.0, height * 0.112, height * 0.004)
    )
    specs = (
        (66.0, 0.135, 0.011, 0.005, 0.020),
        (46.0, 0.155, 0.012, 0.0055, 0.008),
        (27.0, 0.150, 0.0125, 0.0055, -0.006),
        (10.0, 0.125, 0.011, 0.005, -0.020),
    )
    wings = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        side_origin = anchor + Vector((sign * height * 0.040, 0.0, 0.0))
        for index, (
            angle_degrees,
            length_ratio,
            width_ratio,
            depth_ratio,
            drop,
        ) in enumerate(specs):
            angle = math.radians(angle_degrees)
            root = side_origin + Vector(
                (
                    sign * height * (0.004 + index * 0.004),
                    index * height * 0.002,
                    height * drop,
                )
            )
            length = height * length_ratio
            tip = root + Vector(
                (
                    sign * length * math.cos(angle),
                    height * (0.010 + index * 0.002),
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

    bodice, bodice_overlays, front_y = _build_sewn_bodice(
        body, center, height, z, mats
    )
    garments.extend([bodice, *bodice_overlays])
    weighted.extend([bodice, *bodice_overlays])
    clearance_objects.extend([bodice, *bodice_overlays])

    skirt = pleated_shell(
        "Nocturne_Cloth_Skirt",
        center,
        [
            (z(0.430), height * 0.166, height * 0.094, 0.0),
            (z(0.455), height * 0.154, height * 0.090, 0.0),
            (z(0.480), height * 0.142, height * 0.086, 0.0),
            (z(0.505), height * 0.130, height * 0.082, 0.0),
            (z(0.530), height * 0.120, height * 0.078, 0.0),
            (z(0.550), height * 0.112, height * 0.075, 0.0),
        ],
        mats["black"],
        segments=96,
        pleats=12,
        fold=0.045,
    )
    cloth = [bake_skirt(skirt, body)]
    frill = pleated_shell(
        "Nocturne_Cream_Hem_Frill",
        center,
        [
            (z(0.416), height * 0.172, height * 0.096, 0.0),
            (z(0.431), height * 0.168, height * 0.094, 0.0),
            (z(0.446), height * 0.161, height * 0.092, 0.0),
        ],
        mats["cream"],
        segments=96,
        pleats=12,
        fold=0.050,
    )
    waist = frustum_shell(
        "Nocturne_Waist_Band",
        center,
        [
            (z(0.540), height * 0.119, height * 0.080, 0.0),
            (z(0.552), height * 0.116, height * 0.078, 0.0),
            (z(0.564), height * 0.113, height * 0.076, 0.0),
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

    bow = Vector((center.x, front_y - height * 0.006, z(0.648)))
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

    clearance = height * 0.014
    clearance_records = [
        enforce_body_clearance(
            obj,
            body,
            clearance,
            maximum_search=height * 0.090,
            iterations=4,
        )
        for obj in clearance_objects
    ]
    cloth[0]["clearanceAdjustments"] = clearance_records

    for obj in weighted:
        transfer_weights(obj, body, armature)
    for obj, semantic in rigid:
        rigid_weight(obj, armature, semantic)
    return garments, cloth
