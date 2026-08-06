#!/usr/bin/env python3
"""Stable product entrypoint and shared geometry primitives for black-cat outfit."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import bpy

PRODUCT_ID = "siroino-black-cat-bondage"


def path(value: str) -> Path:
    """Resolve a repository-relative path."""
    return (Path.cwd() / value).resolve()


def clean() -> None:
    """Remove all scene objects before a deterministic build."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def mat(
    name: str,
    rgba: tuple[float, float, float, float],
    metallic: float = 0.0,
    roughness: float = 0.4,
) -> bpy.types.Material:
    """Create one Principled BSDF material."""
    value = bpy.data.materials.new(name)
    value.use_nodes = True
    bsdf = value.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return value


def mesh(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
    thickness: float = 0.002,
) -> bpy.types.Object:
    """Create a panel mesh with bounded thickness and edge rounding."""
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    solid = obj.modifiers.new("Garment Solidify", "SOLIDIFY")
    solid.thickness = thickness
    solid.offset = 0.0
    bevel = obj.modifiers.new("Garment Bevel", "BEVEL")
    bevel.width = 0.001
    bevel.segments = 2
    return obj


def cube(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    bevel: float = 0.002,
) -> bpy.types.Object:
    """Create one rounded rigid garment element."""
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    if bevel:
        modifier = obj.modifiers.new("Edge Bevel", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
    return obj


def torus(
    name: str,
    location: tuple[float, float, float],
    major: float,
    minor: float,
    material: bpy.types.Material,
    rotation: tuple[float, float, float] = (math.pi / 2.0, 0.0, 0.0),
) -> bpy.types.Object:
    """Create a ring, strap, or band."""
    bpy.ops.mesh.primitive_torus_add(
        major_radius=major,
        minor_radius=minor,
        major_segments=32,
        minor_segments=8,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def line(
    name: str,
    points: list[tuple[float, float, float]],
    radius: float,
    material: bpy.types.Material,
    *,
    cyclic: bool = False,
) -> bpy.types.Object:
    """Create a bevelled curve used for lacing, harnesses, and chains."""
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = radius
    data.bevel_resolution = 2
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for target, value in zip(spline.points, points, strict=True):
        target.co = (*value, 1.0)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def import_avatar(job: dict[str, Any]) -> list[str]:
    """Import the canonical SiroinoSotai_PC FBX."""
    source = path(str(job["targetSourcePath"]))
    if not source.is_file():
        raise FileNotFoundError(f"target avatar source is missing: {source}")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True)
    imported = [obj for obj in bpy.data.objects if obj not in before]
    for obj in imported:
        obj["image2outfitRole"] = "target-avatar"
    return [obj.name for obj in imported]


def build(
    leather: bpy.types.Material,
    fabric: bpy.types.Material,
    metal: bpy.types.Material,
) -> list[bpy.types.Object]:
    """Build the full 101-object black-cat garment assembly."""
    result: list[bpy.types.Object] = []
    edges = (-0.165, -0.095, -0.035, 0.035, 0.095, 0.165)
    for index, (x0, x1) in enumerate(zip(edges, edges[1:], strict=True)):
        center_x = (x0 + x1) / 2.0
        y = -0.092 - 0.030 * (1.0 - abs(center_x) / 0.165)
        z0 = 0.760 + 0.020 * abs(center_x) / 0.165
        z1 = 1.005 - 0.055 * abs(center_x) / 0.165
        result.append(
            mesh(
                f"Corset_Front_{index:02d}",
                [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)],
                [(0, 1, 2, 3)],
                leather,
            )
        )
    result.extend(
        [
            cube("Corset_Back", (0.0, 0.092, 0.875), (0.158, 0.012, 0.112), leather),
            cube(
                "Corset_Top_Binding",
                (0.0, -0.112, 1.002),
                (0.170, 0.009, 0.009),
                fabric,
            ),
            cube(
                "Corset_Bottom_Binding",
                (0.0, -0.112, 0.762),
                (0.170, 0.009, 0.009),
                fabric,
            ),
        ]
    )
    for sign, side in ((-1.0, "L"), (1.0, "R")):
        result.append(
            mesh(
                f"Bust_Cup_{side}",
                [
                    (sign * 0.020, -0.126, 0.935),
                    (sign * 0.148, -0.102, 0.930),
                    (sign * 0.128, -0.112, 1.045),
                    (sign * 0.045, -0.132, 1.060),
                ],
                [(0, 1, 2, 3)],
                leather,
            )
        )
        result.append(
            line(
                f"Shoulder_Strap_{side}",
                [
                    (sign * 0.085, -0.110, 1.030),
                    (sign * 0.130, -0.015, 1.115),
                    (sign * 0.100, 0.080, 1.020),
                ],
                0.007,
                leather,
            )
        )
        result.append(
            line(
                f"Chest_Harness_{side}",
                [
                    (0.0, -0.073, 1.120),
                    (sign * 0.085, -0.125, 1.020),
                    (sign * 0.145, -0.100, 0.955),
                ],
                0.005,
                leather,
            )
        )

    eyelet_z = [0.785 + index * 0.036 for index in range(7)]
    for row, z in enumerate(eyelet_z):
        for sign, side in ((-1.0, "L"), (1.0, "R")):
            result.append(
                torus(
                    f"Eyelet_{side}_{row:02d}",
                    (sign * 0.023, -0.132, z),
                    0.008,
                    0.0018,
                    metal,
                )
            )
    for row, (z0, z1) in enumerate(zip(eyelet_z, eyelet_z[1:], strict=True)):
        result.append(
            line(
                f"Lace_A_{row:02d}",
                [(-0.023, -0.136, z0), (0.023, -0.136, z1)],
                0.0022,
                leather,
            )
        )
        result.append(
            line(
                f"Lace_B_{row:02d}",
                [(0.023, -0.137, z0), (-0.023, -0.137, z1)],
                0.0022,
                leather,
            )
        )

    result.extend(
        [
            torus("Choker", (0.0, -0.002, 1.145), 0.057, 0.008, leather, (0.0, 0.0, 0.0)),
            torus("Choker_Ring", (0.0, -0.066, 1.120), 0.015, 0.003, metal),
            torus("Waist_Belt", (0.0, 0.0, 0.720), 0.175, 0.010, leather, (0.0, 0.0, 0.0)),
        ]
    )

    count = 24
    top_radius = 0.166
    bottom_radius = 0.235
    for index in range(count):
        angle0 = math.tau * index / count
        angle1 = math.tau * (index + 1) / count
        ridge = 0.010 if index % 2 == 0 else -0.006
        vertices = [
            (top_radius * math.cos(angle0), top_radius * math.sin(angle0), 0.710),
            (top_radius * math.cos(angle1), top_radius * math.sin(angle1), 0.710),
            (
                (bottom_radius + ridge) * math.cos(angle1),
                (bottom_radius + ridge) * math.sin(angle1),
                0.555,
            ),
            (
                (bottom_radius + ridge) * math.cos(angle0),
                (bottom_radius + ridge) * math.sin(angle0),
                0.555,
            ),
        ]
        result.append(
            mesh(f"Skirt_Pleat_{index:02d}", vertices, [(0, 1, 2, 3)], fabric, 0.0015)
        )

    ring_x = (-0.135, -0.080, -0.025, 0.030, 0.085, 0.140)
    for index, x in enumerate(ring_x):
        result.append(torus(f"Waist_Ring_{index:02d}", (x, -0.183, 0.700), 0.022, 0.0035, metal))
        if index < len(ring_x) - 1:
            next_x = ring_x[index + 1]
            result.append(
                line(
                    f"Waist_Chain_{index:02d}",
                    [
                        (x, -0.187, 0.680),
                        ((x + next_x) / 2.0, -0.192, 0.645),
                        (next_x, -0.187, 0.680),
                    ],
                    0.002,
                    metal,
                )
            )

    for sign, side in ((-1.0, "L"), (1.0, "R")):
        x = sign * 0.275
        result.extend(
            [
                torus(
                    f"UpperArm_Band_{side}",
                    (x, 0.0, 0.995),
                    0.050,
                    0.010,
                    leather,
                    (0.0, math.pi / 2.0, 0.0),
                ),
                cube(
                    f"Gauntlet_{side}",
                    (x, -0.005, 0.800),
                    (0.046, 0.035, 0.145),
                    leather,
                    bevel=0.009,
                ),
                torus(f"Gauntlet_Ring_{side}", (x, -0.045, 0.805), 0.013, 0.003, metal),
                torus(
                    f"Thigh_Garter_{side}",
                    (sign * 0.115, 0.0, 0.445),
                    0.082,
                    0.008,
                    leather,
                    (0.0, math.pi / 2.0, 0.0),
                ),
                line(
                    f"Thigh_Chain_{side}",
                    [
                        (sign * 0.150, -0.030, 0.510),
                        (sign * 0.185, -0.090, 0.470),
                        (sign * 0.150, -0.090, 0.420),
                    ],
                    0.002,
                    metal,
                ),
            ]
        )
        for index, z in enumerate((0.710, 0.770, 0.835, 0.900)):
            result.append(
                torus(
                    f"Gauntlet_Strap_{side}_{index}",
                    (x, -0.004, z),
                    0.050,
                    0.004,
                    fabric,
                    (0.0, math.pi / 2.0, 0.0),
                )
            )

    result.append(
        torus("CatEar_Headband", (0.0, 0.0, 1.455), 0.115, 0.008, leather, (0.0, 0.0, 0.0))
    )
    for sign, side in ((-1.0, "L"), (1.0, "R")):
        x = sign * 0.065
        outer = [
            (x - sign * 0.055, -0.015, 1.455),
            (x + sign * 0.055, -0.015, 1.455),
            (x, -0.010, 1.575),
        ]
        inner = [
            (x - sign * 0.035, -0.020, 1.468),
            (x + sign * 0.035, -0.020, 1.468),
            (x, -0.018, 1.545),
        ]
        result.extend(
            [
                mesh(f"CatEar_Outer_{side}", outer, [(0, 1, 2)], leather, 0.003),
                mesh(f"CatEar_Inner_{side}", inner, [(0, 1, 2)], fabric, 0.0015),
            ]
        )
    return result


def main() -> int:
    """Execute the latest implementation behind the stable public filename."""
    from siroino_black_cat_bondage_v3_product import main as final_main

    return final_main()


if __name__ == "__main__":
    raise SystemExit(main())
