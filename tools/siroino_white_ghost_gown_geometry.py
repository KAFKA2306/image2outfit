#!/usr/bin/env python3
"""Product-specific geometry for the Siroino white ghost gown.

Keep silhouette and cloth parameters here so visual-review failures can be fixed
without editing the build/evidence orchestration.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import bpy
from mathutils import Vector

import siroino_heather_hooded_geometry as heather_geometry
import siroino_strappy_knit_build as base
from tuxedo_halter_components import ellipsoid, mesh_object


@dataclass(frozen=True)
class TorsoSpec:
    z_min: float = 0.705
    z_max: float = 1.025
    half_width: float = 0.205
    cutout_z_min: float = 0.790
    cutout_height: float = 0.220
    cutout_half_width_min: float = 0.065
    cutout_half_width_extra: float = 0.070


@dataclass(frozen=True)
class SleeveSpec:
    z_min: float = 0.700
    z_max: float = 1.035
    x_min: float = 0.120
    x_max: float = 0.580
    y_max: float = 0.170


@dataclass(frozen=True)
class WristDrapeSpec:
    columns: int = 10
    rows: int = 8
    width_top: float = 0.075
    width_bottom: float = 0.205
    height: float = 0.30
    lateral_drop: float = 0.025
    fold_amplitude: float = 0.010
    hem_wave_amplitude: float = 0.018


@dataclass(frozen=True)
class HoodSpec:
    segments: int = 48
    rows: tuple[tuple[float, float, float], ...] = (
        (1.305, 0.020, 0.017),
        (1.275, 0.070, 0.055),
        (1.225, 0.105, 0.082),
        (1.165, 0.125, 0.098),
        (1.095, 0.145, 0.112),
        (1.025, 0.170, 0.132),
        (0.975, 0.190, 0.150),
    )
    scallop_amplitude: float = 0.012


@dataclass(frozen=True)
class SkirtSpec:
    profiles: tuple[tuple[float, float, float], ...] = (
        (0.755, 0.148, 0.112),
        (0.655, 0.160, 0.122),
        (0.520, 0.150, 0.112),
        (0.365, 0.138, 0.103),
        (0.235, 0.130, 0.098),
        (0.125, 0.155, 0.118),
        (0.060, 0.220, 0.170),
    )
    segments: int = 96
    seam_gap_degrees: float = 8.0
    frame_end: int = 36
    gravity_z: float = -4.5
    sewing_force_max: float = 12.0


@dataclass(frozen=True)
class GhostGownSpec:
    torso: TorsoSpec = field(default_factory=TorsoSpec)
    sleeve: SleeveSpec = field(default_factory=SleeveSpec)
    wrist_drape: WristDrapeSpec = field(default_factory=WristDrapeSpec)
    hood: HoodSpec = field(default_factory=HoodSpec)
    skirt: SkirtSpec = field(default_factory=SkirtSpec)


DEFAULT_SPEC = GhostGownSpec()


@dataclass(frozen=True)
class GarmentAssembly:
    objects: tuple[bpy.types.Object, ...]
    skirt: bpy.types.Object
    sewing_edge_count: int
    rigid_groups: dict[str, str]


def white_material() -> bpy.types.Material:
    return base.plain_material(
        "MAT_Ghost_White",
        (0.92, 0.93, 0.95, 1.0),
        roughness=0.70,
    )


def torso_predicate(center: Vector, spec: TorsoSpec) -> bool:
    if not (
        spec.z_min <= center.z <= spec.z_max
        and abs(center.x) <= spec.half_width
    ):
        return False
    if center.y <= 0.0 or center.z <= spec.cutout_z_min:
        return True
    ratio = min(
        1.0,
        max(0.0, (center.z - spec.cutout_z_min) / spec.cutout_height),
    )
    cutout_half_width = (
        spec.cutout_half_width_min
        + spec.cutout_half_width_extra * math.sin(math.pi * ratio)
    )
    return abs(center.x) >= cutout_half_width


def sleeve_predicate(center: Vector, spec: SleeveSpec) -> bool:
    return (
        spec.z_min <= center.z <= spec.z_max
        and spec.x_min <= abs(center.x) <= spec.x_max
        and abs(center.y) <= spec.y_max
    )


def rigid_weight(
    obj: bpy.types.Object,
    armature: bpy.types.Object,
    bone: str,
) -> bpy.types.Object:
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    obj.vertex_groups.clear()
    group = obj.vertex_groups.new(name=bone)
    group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
    return obj


def wrist_drape(
    side: str,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    spec: WristDrapeSpec,
) -> bpy.types.Object:
    _, wrist = heather_geometry.bone_segment(armature, f"LowerArm_{side}")
    sign = -1.0 if side == "L" else 1.0
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for row in range(spec.rows):
        v = row / (spec.rows - 1)
        width = spec.width_top + (spec.width_bottom - spec.width_top) * (v**0.8)
        center_x = wrist.x + sign * spec.lateral_drop * v
        z = wrist.z - spec.height * v
        for column in range(spec.columns + 1):
            u = column / spec.columns
            x = center_x + (u - 0.5) * 2.0 * width
            fold = spec.fold_amplitude * math.sin(u * math.tau * 2.5 + v * 1.3)
            y = wrist.y - 0.010 + fold
            lower_wave = (
                spec.hem_wave_amplitude
                * math.sin(u * math.pi * 3.0)
                * (v**4)
            )
            vertices.append((x, y, z + lower_wave))

    stride = spec.columns + 1
    for row in range(spec.rows - 1):
        for column in range(spec.columns):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))

    mesh = bpy.data.meshes.new(f"Ghost_Wrist_Drape_{side}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(f"Ghost_Wrist_Drape_{side}", mesh)
    bpy.context.collection.objects.link(obj)
    rigid_weight(obj, armature, f"Hand_{side}")
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solidify = obj.modifiers.new("Drape thickness", "SOLIDIFY")
    solidify.thickness = 0.0011
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Drape edge finish", "BEVEL")
    bevel.width = 0.00045
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def ghost_hood(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    spec: HoodSpec,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for row_index, (z, rx, ry) in enumerate(spec.rows):
        for index in range(spec.segments):
            angle = math.tau * index / spec.segments
            scallop = 0.0
            if row_index == len(spec.rows) - 1:
                scallop = spec.scallop_amplitude * (
                    0.5 + 0.5 * math.sin(angle * 6.0)
                )
            vertices.append(
                (
                    rx * math.cos(angle),
                    ry * math.sin(angle),
                    z - scallop,
                )
            )
    for row in range(len(spec.rows) - 1):
        start = row * spec.segments
        next_start = (row + 1) * spec.segments
        for index in range(spec.segments):
            nxt = (index + 1) % spec.segments
            faces.append(
                (start + index, start + nxt, next_start + nxt, next_start + index)
            )
    return mesh_object(
        "Ghost_Hood",
        vertices,
        faces,
        material,
        body,
        armature,
        thickness=0.0014,
        bevel=0.0005,
    )


def open_sewn_mermaid_skirt(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    spec: SkirtSpec,
) -> tuple[bpy.types.Object, int]:
    """Create an open center-back seam with face-less sewing edges."""
    gap = math.radians(spec.seam_gap_degrees)
    start_angle = math.pi / 2.0 + gap
    end_angle = math.pi / 2.0 + math.tau - gap
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    sewing_edges: list[tuple[int, int]] = []
    stride = spec.segments + 1

    for row, (z, rx, ry) in enumerate(spec.profiles):
        for index in range(stride):
            ratio = index / spec.segments
            angle = start_angle + (end_angle - start_angle) * ratio
            hem_fold = (
                0.003 + 0.010 * (row / (len(spec.profiles) - 1))
            ) * math.sin(angle * 6.0)
            vertices.append(
                (
                    (rx + hem_fold) * math.cos(angle),
                    (ry + hem_fold * 0.7) * math.sin(angle),
                    z,
                )
            )
        sewing_edges.append((row * stride, row * stride + spec.segments))

    for row in range(len(spec.profiles) - 1):
        a = row * stride
        b = (row + 1) * stride
        for index in range(spec.segments):
            faces.append((a + index, a + index + 1, b + index + 1, b + index))

    mesh = bpy.data.meshes.new("Ghost_Mermaid_Skirt_Mesh")
    mesh.from_pydata(vertices, sewing_edges, faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row, column = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (
                column / spec.segments,
                1.0 - row / max(1, len(spec.profiles) - 1),
            )

    obj = bpy.data.objects.new("Ghost_Mermaid_Skirt", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True
    base.transfer_nearest_body_weights(obj, body)

    pin = obj.vertex_groups.new(name="ClothPin")
    pin_vertices = list(range(2, spec.segments - 1))
    pin.add(pin_vertices, 1.0, "REPLACE")

    collision = body.modifiers.get("Outfit Collision")
    if collision is None:
        body.modifiers.new("Outfit Collision", "COLLISION")
    body.collision.thickness_outer = 0.004
    body.collision.damping = 0.5

    cloth = obj.modifiers.new("Pattern Sewing Cloth", "CLOTH")
    cloth.settings.quality = 10
    cloth.settings.mass = 0.20
    cloth.settings.tension_stiffness = 28.0
    cloth.settings.compression_stiffness = 28.0
    cloth.settings.shear_stiffness = 10.0
    cloth.settings.bending_stiffness = 0.42
    cloth.settings.air_damping = 3.0
    cloth.settings.vertex_group_mass = pin.name
    cloth.settings.pin_stiffness = 1.0
    cloth.settings.use_sewing_springs = True
    cloth.settings.sewing_force_max = spec.sewing_force_max
    cloth.collision_settings.use_collision = True
    cloth.collision_settings.collision_quality = 6
    cloth.collision_settings.distance_min = 0.003
    if hasattr(cloth.collision_settings, "use_self_collision"):
        cloth.collision_settings.use_self_collision = True
        cloth.collision_settings.self_distance_min = 0.0025
    cloth.point_cache.frame_start = 1
    cloth.point_cache.frame_end = spec.frame_end
    return obj, len(sewing_edges)


def bake_sewing(
    skirt: bpy.types.Object,
    *,
    sewing_edge_count: int,
    spec: SkirtSpec,
) -> dict[str, object]:
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = spec.frame_end
    scene.gravity = (0.0, 0.0, spec.gravity_z)
    bpy.context.view_layer.objects.active = skirt
    bpy.ops.ptcache.bake_all(bake=True)
    scene.frame_set(spec.frame_end)
    bpy.context.view_layer.update()

    bpy.ops.object.select_all(action="DESELECT")
    skirt.select_set(True)
    bpy.context.view_layer.objects.active = skirt
    bpy.ops.object.modifier_apply(modifier="Pattern Sewing Cloth")
    solidify = skirt.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0014
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    edge = skirt.modifiers.new("Finished hem", "BEVEL")
    edge.width = 0.00045
    edge.segments = 2
    bpy.ops.object.modifier_apply(modifier=edge.name)
    skirt.select_set(False)
    return {
        "object": skirt.name,
        "modifier": "Pattern Sewing Cloth",
        "frameStart": 1,
        "frameEnd": spec.frame_end,
        "cacheBaked": True,
        "useSewingSprings": True,
        "sewingForceMax": spec.sewing_force_max,
        "sewingSpringEdgeCount": sewing_edge_count,
    }


def back_laces(
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    y = 0.132
    lines = [
        [(-0.100, y, 0.855), (0.082, y, 0.800)],
        [(0.100, y, 0.855), (-0.082, y, 0.800)],
        [(-0.082, y, 0.800), (0.070, y, 0.755)],
        [(0.082, y, 0.800), (-0.070, y, 0.755)],
    ]
    return [
        base.curve_tube(
            f"Ghost_Back_Tie_{index + 1}",
            points,
            0.0042,
            material,
            armature,
            "Chest" if index < 2 else "Hips",
            resolution=3,
        )
        for index, points in enumerate(lines)
    ]


def build_garment(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    spec: GhostGownSpec = DEFAULT_SPEC,
) -> GarmentAssembly:
    white = white_material()
    black = base.plain_material(
        "MAT_Ghost_Eye",
        (0.015, 0.015, 0.018, 1.0),
        roughness=0.75,
    )
    pink = base.plain_material(
        "MAT_Ghost_Cheek",
        (0.96, 0.42, 0.55, 1.0),
        roughness=0.78,
    )

    garments: list[bpy.types.Object] = [
        base.extract_surface(
            body,
            armature,
            "Ghost_Fitted_Bodice",
            lambda center: torso_predicate(center, spec.torso),
            white,
            0.0068,
        ),
        base.extract_surface(
            body,
            armature,
            "Ghost_Long_Sleeve_L",
            lambda center: sleeve_predicate(center, spec.sleeve) and center.x < 0.0,
            white,
            0.0068,
        ),
        base.extract_surface(
            body,
            armature,
            "Ghost_Long_Sleeve_R",
            lambda center: sleeve_predicate(center, spec.sleeve) and center.x > 0.0,
            white,
            0.0068,
        ),
    ]

    skirt, sewing_edge_count = open_sewn_mermaid_skirt(
        body,
        armature,
        white,
        spec.skirt,
    )
    garments.append(skirt)
    garments.extend(
        (
            wrist_drape("L", armature, white, spec.wrist_drape),
            wrist_drape("R", armature, white, spec.wrist_drape),
            ghost_hood(body, armature, white, spec.hood),
        )
    )

    front_y = -0.160
    garments.extend(
        (
            ellipsoid(
                "Ghost_Eye_L",
                (-0.040, front_y, 1.175),
                (0.016, 0.0045, 0.030),
                black,
                body,
                armature,
            ),
            ellipsoid(
                "Ghost_Eye_R",
                (0.040, front_y, 1.175),
                (0.016, 0.0045, 0.030),
                black,
                body,
                armature,
            ),
            ellipsoid(
                "Ghost_Cheek_L",
                (-0.064, front_y - 0.001, 1.110),
                (0.013, 0.0040, 0.008),
                pink,
                body,
                armature,
            ),
            ellipsoid(
                "Ghost_Cheek_R",
                (0.064, front_y - 0.001, 1.110),
                (0.013, 0.0040, 0.008),
                pink,
                body,
                armature,
            ),
        )
    )
    garments.extend(back_laces(armature, white))

    return GarmentAssembly(
        objects=tuple(garments),
        skirt=skirt,
        sewing_edge_count=sewing_edge_count,
        rigid_groups={
            "Ghost_Wrist_Drape_L": "Hand_L",
            "Ghost_Wrist_Drape_R": "Hand_R",
        },
    )
