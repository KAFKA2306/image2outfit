#!/usr/bin/env python3
"""Build the Siroino _Large lace-halter from the exact tracked body surface.

The historical encoded product source still owns delivery/reporting behavior,
but its original garment geometry was visibly detached from the avatar. This
loader replaces only ``create_garment`` with a body-derived implementation:
every fabric panel is extracted from the baked ``_Large`` surface and every
trim receives nearest-body weights.
"""
from __future__ import annotations

import base64
import math
import sys
import zlib
from pathlib import Path

import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_strappy_knit_build as _base


def _front_point(
    body: bpy.types.Object,
    x: float,
    z: float,
    offset: float = 0.0065,
) -> tuple[float, float, float]:
    return (x, _base.body_front_y(body, x, z) - offset, z)


def _surface_path(
    body: bpy.types.Object,
    coordinates: list[tuple[float, float]],
    offset: float = 0.0065,
) -> list[tuple[float, float, float]]:
    return [_front_point(body, x, z, offset) for x, z in coordinates]


def _curve(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    coordinates: list[tuple[float, float]],
    radius: float,
    group: str,
    *,
    cyclic: bool = False,
) -> bpy.types.Object:
    return _base.curve_tube(
        name,
        _surface_path(body, coordinates),
        radius,
        material,
        armature,
        group,
        cyclic=cyclic,
        resolution=3,
    )


def _surface_flower(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    center_x: float,
    center_z: float,
    scale: float,
) -> list[bpy.types.Object]:
    pieces: list[bpy.types.Object] = []
    for petal in range(6):
        angle = math.tau * petal / 6.0
        radial_x = math.cos(angle) * scale * 0.82
        radial_z = math.sin(angle) * scale * 0.82
        points: list[tuple[float, float]] = []
        for segment in range(25):
            phase = math.tau * segment / 24.0
            local_x = scale * 0.42 * math.cos(phase)
            local_z = scale * 0.85 * math.sin(phase)
            x = center_x + radial_x + local_x * math.cos(angle) - local_z * math.sin(angle)
            z = center_z + radial_z + local_x * math.sin(angle) + local_z * math.cos(angle)
            points.append((x, z))
        pieces.append(
            _curve(
                f"{name}_Petal_{petal}",
                body,
                armature,
                material,
                points,
                scale * 0.105,
                "Hips" if center_z < 0.78 else "Chest",
                cyclic=True,
            )
        )
    center_points = [
        (
            center_x + scale * 0.34 * math.cos(math.tau * index / 32.0),
            center_z + scale * 0.34 * math.sin(math.tau * index / 32.0),
        )
        for index in range(32)
    ]
    pieces.append(
        _curve(
            f"{name}_Center",
            body,
            armature,
            material,
            center_points,
            scale * 0.12,
            "Hips" if center_z < 0.78 else "Chest",
            cyclic=True,
        )
    )
    return pieces


def _create_garment(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    materials,
) -> list[bpy.types.Object]:
    glossy, sheer, lace, metal = materials

    def halter_wings(coordinate: Vector) -> bool:
        if coordinate.y >= -0.002 or not 0.795 <= coordinate.z <= 1.018:
            return False
        t = (coordinate.z - 0.795) / (1.018 - 0.795)
        outer = 0.143 - 0.041 * t + 0.010 * math.sin(math.pi * t)
        inner = 0.018 + 0.024 * t
        return inner <= abs(coordinate.x) <= outer

    wings = _base.extract_surface(
        body,
        armature,
        "Glossy_Keyhole_Halter_Wings",
        halter_wings,
        glossy,
        0.0060,
    )

    def sheer_torso(coordinate: Vector) -> bool:
        if coordinate.y >= -0.002:
            return False
        center_inset = (
            0.815 <= coordinate.z <= 0.990
            and abs(coordinate.x) <= 0.036 + 0.012 * (0.990 - coordinate.z) / 0.175
        )
        underbust = (
            0.665 <= coordinate.z < 0.825
            and abs(coordinate.x) <= 0.112 + 0.020 * (coordinate.z - 0.665) / 0.160
        )
        return center_inset or underbust

    torso = _base.extract_surface(
        body,
        armature,
        "Sheer_Fitted_Torso",
        sheer_torso,
        sheer,
        0.0072,
    )

    def highcut_base(coordinate: Vector) -> bool:
        z = coordinate.z
        if coordinate.y < 0.0:
            if not 0.555 <= z <= 0.755:
                return False
            width = min(0.142, 0.030 + (z - 0.555) * 0.62)
            return abs(coordinate.x) <= width
        if not 0.595 <= z <= 0.755:
            return False
        width = 0.068 + (z - 0.595) * 0.42
        return abs(coordinate.x) <= min(width, 0.132)

    highcut = _base.extract_surface(
        body,
        armature,
        "Glossy_Highcut_Front",
        highcut_base,
        glossy,
        0.0052,
    )

    def sheer_skirt(coordinate: Vector) -> bool:
        z = coordinate.z
        if not 0.405 <= z <= 0.710:
            return False
        outer = min(0.155, 0.095 + (z - 0.405) * 0.24)
        if abs(coordinate.x) > outer:
            return False
        if z >= 0.565:
            return True
        return abs(coordinate.x) >= 0.030 + (0.565 - z) * 0.10

    skirt = _base.extract_surface(
        body,
        armature,
        "Long_Sheer_Front_Panel",
        sheer_skirt,
        sheer,
        0.0080,
    )

    collar_parts = []
    for index, z in enumerate((1.027, 1.047)):
        collar_parts.append(
            _base.curve_tube(
                f"Collar_Rail_{index}",
                _base.surface_cross_section_loop(body, z, -0.048, 0.048, 0.0055, 30),
                0.0021,
                glossy,
                armature,
                "Neck",
                cyclic=True,
                resolution=3,
            )
        )
    collar = _base.join_objects("Glossy_High_Collar", collar_parts)
    _base.transfer_nearest_body_weights(collar, body)

    strap_parts: list[bpy.types.Object] = []
    for sign in (-1.0, 1.0):
        strap_parts.append(
            _curve(
                f"Halter_Outer_{int(sign)}",
                body,
                armature,
                lace,
                [
                    (sign * 0.118, 0.825),
                    (sign * 0.124, 0.875),
                    (sign * 0.105, 0.925),
                    (sign * 0.072, 0.980),
                    (sign * 0.039, 1.032),
                ],
                0.0017,
                "Chest",
            )
        )
        strap_parts.append(
            _curve(
                f"Halter_Inner_{int(sign)}",
                body,
                armature,
                lace,
                [
                    (sign * 0.048, 0.815),
                    (sign * 0.044, 0.865),
                    (sign * 0.040, 0.915),
                    (sign * 0.034, 0.970),
                    (sign * 0.028, 1.028),
                ],
                0.00135,
                "Chest",
            )
        )
    for name, z, radius, group in (
        ("Underbust_Lace_Band", 0.792, 0.00145, "Chest"),
        ("Waist_Lace_Band", 0.718, 0.00155, "Hips"),
    ):
        strap_parts.append(
            _base.curve_tube(
                name,
                _base.surface_cross_section_loop(body, z, -0.143, 0.143, 0.0065, 44),
                radius,
                lace,
                armature,
                group,
                cyclic=True,
                resolution=3,
            )
        )
    straps = _base.join_objects("Lace_And_Halter_Straps", strap_parts)
    _base.transfer_nearest_body_weights(straps, body)

    eyelet_parts: list[bpy.types.Object] = []
    for row, z in enumerate((0.925, 0.875)):
        for sign in (-1.0, 1.0):
            x = sign * (0.031 + row * 0.005)
            location = _front_point(body, x, z, 0.0090)
            eyelet_parts.append(
                _base.torus(
                    f"Eyelet_{row}_{int(sign)}",
                    location,
                    0.0024,
                    0.00055,
                    metal,
                    armature,
                    "Chest",
                )
            )
    eyelets = _base.join_objects("Dark_Eyelets", eyelet_parts)
    _base.transfer_nearest_body_weights(eyelets, body)

    applique_parts: list[bpy.types.Object] = []
    for index, (x, z, scale) in enumerate(
        (
            (0.0, 0.765, 0.012),
            (-0.068, 0.665, 0.014),
            (0.068, 0.665, 0.014),
            (0.0, 0.585, 0.015),
            (-0.058, 0.500, 0.013),
            (0.058, 0.500, 0.013),
        )
    ):
        applique_parts.extend(
            _surface_flower(
                f"Lace_Rosette_{index}", body, armature, lace, x, z, scale
            )
        )
    for sign in (-1.0, 1.0):
        vine = []
        for index in range(28):
            t = index / 27.0
            z = 0.455 + 0.330 * t
            x = sign * (0.038 + 0.008 * math.sin(t * math.tau * 1.5))
            vine.append((x, z))
        applique_parts.append(
            _curve(
                f"Lace_Vine_{int(sign)}",
                body,
                armature,
                lace,
                vine,
                0.00135,
                "Hips",
            )
        )
    applique = _base.join_objects("Lace_Applique", applique_parts)
    _base.transfer_nearest_body_weights(applique, body)

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
