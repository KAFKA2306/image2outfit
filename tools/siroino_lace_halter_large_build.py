#!/usr/bin/env python3
"""Build the Siroino _Large lace-halter from the exact tracked body surface.

The encoded product source remains the reproducible delivery/reporting shell,
but every visible garment object is rebuilt from the baked ``_Large`` body.
No free-standing curves, rails, torus hardware, or rigid banner panels are
used: collars, straps, bands, eyelets, and lace decoration are all weighted
surface extracts, eliminating the floating geometry rejected in prior reviews.
"""
from __future__ import annotations

import base64
import math
import sys
import zlib
from pathlib import Path
from typing import Callable

import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_strappy_knit_build as _base

Predicate = Callable[[Vector], bool]


def _surface(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    predicate: Predicate,
    material: bpy.types.Material,
    offset: float,
) -> bpy.types.Object:
    """Extract one fitted, armature-weighted garment surface."""
    obj = _base.extract_surface(
        body,
        armature,
        name,
        predicate,
        material,
        offset,
    )
    if not obj.data.vertices or not obj.data.polygons:
        raise RuntimeError(f"surface mask produced an empty garment: {name}")
    return obj


def _joined_surface(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    masks: list[tuple[str, Predicate]],
    material: bpy.types.Material,
    offset: float,
) -> bpy.types.Object:
    parts = [
        _surface(body, armature, part_name, predicate, material, offset)
        for part_name, predicate in masks
    ]
    joined = _base.join_objects(name, parts)
    _base.transfer_nearest_body_weights(joined, body)
    return joined


def _create_garment(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    materials,
) -> list[bpy.types.Object]:
    glossy, sheer, lace, metal = materials

    def front(coordinate: Vector) -> bool:
        return coordinate.y < -0.002

    def halter_wings(coordinate: Vector) -> bool:
        if not front(coordinate) or not 0.795 <= coordinate.z <= 1.018:
            return False
        progress = (coordinate.z - 0.795) / 0.223
        outer = 0.143 - 0.041 * progress + 0.010 * math.sin(math.pi * progress)
        inner = 0.018 + 0.024 * progress
        return inner <= abs(coordinate.x) <= outer

    wings = _surface(
        body,
        armature,
        "Glossy_Keyhole_Halter_Wings",
        halter_wings,
        glossy,
        0.0060,
    )

    def sheer_torso(coordinate: Vector) -> bool:
        if not front(coordinate):
            return False
        center_inset = (
            0.815 <= coordinate.z <= 0.990
            and abs(coordinate.x)
            <= 0.040 + 0.015 * (0.990 - coordinate.z) / 0.175
        )
        underbust = (
            0.665 <= coordinate.z < 0.825
            and abs(coordinate.x)
            <= 0.118 + 0.018 * (coordinate.z - 0.665) / 0.160
        )
        return center_inset or underbust

    torso = _surface(
        body,
        armature,
        "Sheer_Fitted_Torso",
        sheer_torso,
        sheer,
        0.0070,
    )

    def highcut_base(coordinate: Vector) -> bool:
        z = coordinate.z
        if not 0.555 <= z <= 0.755:
            return False
        if front(coordinate):
            width = min(0.145, 0.034 + (z - 0.555) * 0.62)
        else:
            width = min(0.138, 0.072 + (z - 0.555) * 0.40)
        return abs(coordinate.x) <= width

    highcut = _surface(
        body,
        armature,
        "Glossy_Highcut_Front",
        highcut_base,
        glossy,
        0.0052,
    )

    def collar_band(coordinate: Vector) -> bool:
        return 1.020 <= coordinate.z <= 1.052 and abs(coordinate.x) <= 0.070

    collar = _surface(
        body,
        armature,
        "Glossy_High_Collar",
        collar_band,
        glossy,
        0.0055,
    )

    def fitted_front_panel(coordinate: Vector) -> bool:
        if not front(coordinate) or not 0.405 <= coordinate.z <= 0.700:
            return False
        progress = (coordinate.z - 0.405) / 0.295
        outer = 0.088 + 0.052 * progress
        return abs(coordinate.x) <= outer

    skirt = _surface(
        body,
        armature,
        "Long_Sheer_Front_Panel",
        fitted_front_panel,
        sheer,
        0.0080,
    )

    def halter_trim(coordinate: Vector) -> bool:
        if not front(coordinate) or not 0.805 <= coordinate.z <= 1.030:
            return False
        progress = (coordinate.z - 0.805) / 0.225
        x = abs(coordinate.x)
        outer_center = 0.124 - 0.086 * progress
        inner_center = 0.052 - 0.021 * progress
        return (
            abs(x - outer_center) <= 0.0065
            or abs(x - inner_center) <= 0.0050
        )

    def underbust_band(coordinate: Vector) -> bool:
        return 0.782 <= coordinate.z <= 0.798 and abs(coordinate.x) <= 0.150

    def waist_band(coordinate: Vector) -> bool:
        return 0.706 <= coordinate.z <= 0.725 and abs(coordinate.x) <= 0.155

    straps = _joined_surface(
        body,
        armature,
        "Lace_And_Halter_Straps",
        [
            ("Lace_Halter_Surface", halter_trim),
            ("Lace_Underbust_Surface", underbust_band),
            ("Lace_Waist_Surface", waist_band),
        ],
        lace,
        0.0085,
    )

    eyelet_centers = (
        (-0.036, 0.925),
        (0.036, 0.925),
        (-0.041, 0.875),
        (0.041, 0.875),
    )

    def fitted_eyelets(coordinate: Vector) -> bool:
        if not front(coordinate):
            return False
        return any(
            (coordinate.x - center_x) ** 2 + (coordinate.z - center_z) ** 2
            <= 0.0075**2
            for center_x, center_z in eyelet_centers
        )

    eyelets = _surface(
        body,
        armature,
        "Dark_Eyelets",
        fitted_eyelets,
        metal,
        0.0105,
    )

    rosettes = (
        (0.000, 0.765, 0.017),
        (-0.066, 0.665, 0.019),
        (0.066, 0.665, 0.019),
        (0.000, 0.585, 0.020),
        (-0.055, 0.500, 0.018),
        (0.055, 0.500, 0.018),
    )

    def fitted_applique(coordinate: Vector) -> bool:
        if not front(coordinate) or not 0.455 <= coordinate.z <= 0.790:
            return False
        progress = (coordinate.z - 0.455) / 0.335
        vine_center = 0.040 + 0.009 * math.sin(progress * math.tau * 1.5)
        on_vine = abs(abs(coordinate.x) - vine_center) <= 0.0065
        on_center_vine = abs(coordinate.x) <= 0.0060
        on_rosette = any(
            (coordinate.x - center_x) ** 2 + (coordinate.z - center_z) ** 2
            <= radius**2
            for center_x, center_z, radius in rosettes
        )
        return on_vine or on_center_vine or on_rosette

    applique = _surface(
        body,
        armature,
        "Lace_Applique",
        fitted_applique,
        lace,
        0.0100,
    )

    return [
        wings,
        torso,
        highcut,
        collar,
        skirt,
        straps,
        eyelets,
        applique,
    ]


source_root = TOOLS / "product_sources" / "siroino_lace_halter_large"
parts = sorted(source_root.glob("part-*.b85"))
if not parts:
    raise FileNotFoundError(f"missing product builder source: {source_root}")
payload = "".join(path.read_text(encoding="ascii").strip() for path in parts)
source = zlib.decompress(base64.b85decode(payload.encode("ascii"))).decode("utf-8")

legacy_signature = "def create_garment(body, armature, materials):"
if legacy_signature not in source:
    raise RuntimeError("encoded product source no longer exposes create_garment")
source = source.replace(
    legacy_signature,
    "def legacy_create_garment(body, armature, materials):",
    1,
)
create_garment = _create_garment

replacements = {
    '"status": "HUMAN_REVIEW_PENDING"': '"status": "WORKING"',
    '"humanVisualReview": "PASS"': '"humanVisualReview": "PENDING"',
    '"humanPoseReview": "PASS"': '"humanPoseReview": "PENDING"',
    '"finalDecision": "TECHNICAL_PASS_VISUAL_PASS_RUNTIME_REVIEW_REQUIRED"': (
        '"finalDecision": "BLENDER_PASS_HUMAN_AND_UNITY_REVIEW_REQUIRED"'
    ),
    'Siroino _Large shape-key profile baked from private source': (
        'Siroino _Large shape-key profile baked from tracked source'
    ),
    'The exact private target is resolved generically by the self-hosted pipeline;': (
        'The exact tracked target is resolved deterministically by the product pipeline;'
    ),
    'The five-view and six-pose renders are regenerated from the tracked Blender source.': (
        'The five-view and seven-pose review renders are regenerated from the tracked Blender source.'
    ),
}
for old, new in replacements.items():
    if old not in source:
        raise RuntimeError(f"expected product-source contract missing: {old}")
    source = source.replace(old, new)

exec(compile(source, __file__, "exec"), globals(), globals())
