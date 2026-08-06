#!/usr/bin/env python3
"""Direct-review corrective build for the black-cat outfit."""

from __future__ import annotations

import math
from collections.abc import Callable

import bpy
from mathutils import Vector

import siroino_black_cat_bondage_geometry as geometry
import siroino_black_cat_bondage_v2_product as v2

_ORIGINAL = v2.apply_shape_corrections


def remove_objects(
    objects: list[bpy.types.Object],
    predicate: Callable[[bpy.types.Object], bool],
) -> None:
    """Remove obsolete generated objects from both the scene and build list."""
    for obj in list(objects):
        if not predicate(obj):
            continue
        objects.remove(obj)
        bpy.data.objects.remove(obj, do_unlink=True)


def raw_mesh(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
    *,
    bevel: float = 0.001,
) -> bpy.types.Object:
    """Create a closed accessory mesh without a Solidify modifier."""
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    if bevel:
        modifier = obj.modifiers.new("Accessory Bevel", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
    return obj


def fitted_corset_half(
    name: str,
    angles: list[float],
    material: bpy.types.Material,
) -> bpy.types.Object:
    """Build one body-following half of the corset with a front lacing gap."""
    rows = 10
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows + 1):
        t = row / rows
        radius_x = 0.150 + 0.018 * math.sin(math.pi * t) - 0.004 * t
        radius_y = 0.080 + 0.016 * math.sin(math.pi * t)
        for theta in angles:
            frontness = max(0.0, -math.sin(theta))
            cup_peak = math.exp(-((abs(math.cos(theta)) - 0.48) / 0.34) ** 2)
            top = 1.012 + 0.052 * frontness * cup_peak
            z = 0.748 + (top - 0.748) * t
            x = radius_x * math.cos(theta)
            y = radius_y * math.sin(theta)
            vertices.append((x, y, z))
    stride = len(angles)
    for row in range(rows):
        for column in range(stride - 1):
            a = row * stride + column
            faces.append((a, a + 1, a + 1 + stride, a + stride))
    obj = geometry.mesh(name, vertices, faces, material, thickness=0.0025)
    obj["construction"] = "fitted-elliptical-half-shell"
    return obj


def rebuild_corset(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
    fabric: bpy.types.Material,
) -> None:
    """Replace the planar box torso with two curved fitted shells."""
    remove_objects(
        objects,
        lambda obj: obj.name.startswith("Corset_Front_")
        or obj.name in {
            "Corset_Back",
            "Corset_Top_Binding",
            "Corset_Bottom_Binding",
        }
        or obj.name.startswith("Bust_Cup_"),
    )
    gap = 0.18
    columns = 20
    right_angles = [
        -math.pi / 2.0 + gap
        + (math.pi - gap) * column / columns
        for column in range(columns + 1)
    ]
    left_angles = [
        math.pi / 2.0
        + (math.pi - gap) * column / columns
        for column in range(columns + 1)
    ]
    objects.extend(
        [
            fitted_corset_half("Corset_Shell_R", right_angles, leather),
            fitted_corset_half("Corset_Shell_L", left_angles, leather),
        ]
    )
    bottom = geometry.torus(
        "Corset_Bottom_Binding",
        (0.0, 0.0, 0.755),
        0.151,
        0.006,
        fabric,
        (0.0, 0.0, 0.0),
    )
    bottom.scale.y = 0.58
    objects.append(bottom)

    for obj in objects:
        if obj.name.startswith("Eyelet_"):
            obj.location.y += 0.022
        elif obj.name.startswith("Lace_") and obj.type == "MESH":
            for vertex in obj.data.vertices:
                vertex.co.y += 0.022


def gauntlet(
    name: str,
    sign: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    """Build a tapered tubular gauntlet aligned to a horizontal forearm."""
    rings = 8
    segments = 14
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for ring in range(rings):
        t = ring / (rings - 1)
        x = sign * (0.355 + 0.215 * t)
        radius_y = 0.034 - 0.007 * t
        radius_z = 0.043 - 0.009 * t
        for segment in range(segments):
            angle = math.tau * segment / segments
            vertices.append(
                (
                    x,
                    -0.004 + math.cos(angle) * radius_y,
                    0.995 + math.sin(angle) * radius_z,
                )
            )
    for ring in range(rings - 1):
        current = ring * segments
        following = (ring + 1) * segments
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            faces.append(
                (
                    current + segment,
                    current + next_segment,
                    following + next_segment,
                    following + segment,
                )
            )
    faces.append(tuple(reversed(tuple(range(segments)))))
    faces.append(tuple(range((rings - 1) * segments, rings * segments)))
    obj = raw_mesh(name, vertices, faces, material, bevel=0.0015)
    obj["construction"] = "tapered-forearm-tube"
    return obj


def rebuild_armwear(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
    fabric: bpy.types.Material,
    metal: bpy.types.Material,
) -> None:
    """Replace box gauntlets with fitted tubes and bounded strap rings."""
    remove_objects(objects, lambda obj: obj.name.startswith("Gauntlet"))
    for obj in objects:
        if obj.name.startswith("UpperArm_Band_"):
            obj.scale *= 0.72
    for sign, side in ((-1.0, "L"), (1.0, "R")):
        objects.append(gauntlet(f"Gauntlet_{side}", sign, leather))
        for index, absolute_x in enumerate((0.375, 0.435, 0.495, 0.555)):
            band = geometry.torus(
                f"Gauntlet_Strap_{side}_{index}",
                (sign * absolute_x, -0.004, 0.995),
                0.037 - 0.002 * index,
                0.0032,
                fabric,
                (0.0, math.pi / 2.0, 0.0),
            )
            objects.append(band)
        buckle = geometry.torus(
            f"Gauntlet_Ring_{side}",
            (sign * 0.470, -0.038, 0.995),
            0.010,
            0.0024,
            metal,
            (0.0, math.pi / 2.0, 0.0),
        )
        objects.append(buckle)


def body_head_anchor() -> tuple[float, float, float]:
    """Derive the head-top anchor from the imported avatar mesh."""
    candidates = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("image2outfitRole") == "target-avatar"
    ]
    if not candidates:
        raise RuntimeError("target avatar mesh is unavailable for headpiece placement")
    body = max(candidates, key=lambda obj: len(obj.data.vertices))
    coordinates = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    maximum_z = max(point.z for point in coordinates)
    top = [point for point in coordinates if point.z >= maximum_z - 0.10]
    center_x = sum(point.x for point in top) / len(top)
    center_y = sum(point.y for point in top) / len(top)
    return center_x, center_y, maximum_z


def rebuild_headpiece(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
    fabric: bpy.types.Material,
) -> None:
    """Anchor the cat ears directly to the measured head top."""
    remove_objects(objects, lambda obj: obj.name.startswith("CatEar_"))
    center_x, center_y, head_top = body_head_anchor()
    base_z = head_top - 0.006
    headband = geometry.torus(
        "CatEar_Headband",
        (center_x, center_y, base_z - 0.010),
        0.070,
        0.0055,
        leather,
        (0.0, 0.0, 0.0),
    )
    headband.scale.y = 0.76
    objects.append(headband)
    for sign, side in ((-1.0, "L"), (1.0, "R")):
        center = center_x + sign * 0.042
        outer = [
            (center - 0.035, center_y - 0.010, base_z),
            (center + 0.035, center_y - 0.010, base_z),
            (center, center_y - 0.006, base_z + 0.085),
        ]
        inner = [
            (center - 0.022, center_y - 0.014, base_z + 0.010),
            (center + 0.022, center_y - 0.014, base_z + 0.010),
            (center, center_y - 0.011, base_z + 0.062),
        ]
        objects.extend(
            [
                geometry.mesh(
                    f"CatEar_Outer_{side}",
                    outer,
                    [(0, 1, 2)],
                    leather,
                    thickness=0.0025,
                ),
                geometry.mesh(
                    f"CatEar_Inner_{side}",
                    inner,
                    [(0, 1, 2)],
                    fabric,
                    thickness=0.0015,
                ),
            ]
        )


def rebuild_garters(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
    metal: bpy.types.Material,
) -> None:
    """Replace oversized arrow-like garters with fitted bands and side chains."""
    remove_objects(
        objects,
        lambda obj: obj.name.startswith("Thigh_Garter_")
        or obj.name.startswith("Thigh_Chain_"),
    )
    for sign, side in ((-1.0, "L"), (1.0, "R")):
        garter = geometry.torus(
            f"Thigh_Garter_{side}",
            (sign * 0.073, 0.0, 0.455),
            0.047,
            0.006,
            leather,
            (0.0, 0.0, 0.0),
        )
        garter.scale.y = 0.74
        curve = geometry.line(
            f"Thigh_Chain_{side}",
            [
                (sign * 0.145, -0.165, 0.682),
                (sign * 0.125, -0.115, 0.570),
                (sign * 0.095, -0.045, 0.475),
            ],
            0.002,
            metal,
        )
        chain = v2.convert_curves([curve])[0]
        objects.extend([garter, chain])


def corrected_shape(objects: list[bpy.types.Object]) -> None:
    """Apply measured, direct-review corrections to all failed components."""
    _ORIGINAL(objects)
    leather = bpy.data.materials.get("BCB_FauxLeather")
    fabric = bpy.data.materials.get("BCB_MatteFabric")
    metal = bpy.data.materials.get("BCB_DarkMetal")
    if leather is None or fabric is None or metal is None:
        raise RuntimeError("black-cat materials are unavailable")
    rebuild_corset(objects, leather, fabric)
    rebuild_armwear(objects, leather, fabric, metal)
    rebuild_headpiece(objects, leather, fabric)
    rebuild_garters(objects, leather, metal)
    bpy.context.view_layer.update()


v2.apply_shape_corrections = corrected_shape


def main() -> int:
    """Run the corrected production build."""
    return v2.main()


if __name__ == "__main__":
    raise SystemExit(main())
