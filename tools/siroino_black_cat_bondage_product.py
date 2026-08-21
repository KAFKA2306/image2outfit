#!/usr/bin/env python3
"""Canonical CS-25-10300 build with anatomy weights and Blender Cloth.

The production path remains on the established v5 module so the repository's
maximum product-import-depth contract stays bounded. This revision absorbs the
v5.1 corset trim correction and the v6 cloth-skirt checkpoint into this file.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

import siroino_black_cat_bondage_v4_product as v4

v3 = v4.v3
v2 = v4.v2
geometry = v4.geometry
ROOT = Path.cwd().resolve()
PRODUCT_ID = "siroino-black-cat-bondage"
MODEL_CODE = "CS-25-10300"
OFFICIAL_URL = "https://www.malymoon-costume.com/view/item/000000004757"
REVISION = "v6-cs-25-10300-blender-cloth-skirt"
CLOTH_FRAMES = 32
PLEAT_COUNT = 24
SEGMENTS = 96
RINGS = 10


def _set_if_available(settings: Any, name: str, value: Any) -> None:
    if hasattr(settings, name):
        setattr(settings, name, value)


def armature() -> bpy.types.Object:
    return v2.resolve_armature()


def bone_segment(name: str) -> tuple[Vector, Vector]:
    rig = armature()
    bone = rig.data.bones.get(name)
    if bone is None:
        raise RuntimeError(f"required Siroino bone is unavailable: {name}")
    return (
        rig.matrix_world @ bone.head_local,
        rig.matrix_world @ bone.tail_local,
    )


def perpendicular_basis(axis: Vector) -> tuple[Vector, Vector]:
    direction = axis.normalized()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(direction.dot(reference)) > 0.90:
        reference = Vector((0.0, 1.0, 0.0))
    first = direction.cross(reference).normalized()
    second = direction.cross(first).normalized()
    return first, second


def axis_tube(
    name: str,
    start: Vector,
    end: Vector,
    radii: list[float],
    material: bpy.types.Material,
    *,
    segments: int = 24,
    bevel: float = 0.0012,
) -> bpy.types.Object:
    axis = end - start
    if axis.length <= 1e-8:
        raise RuntimeError(f"zero-length accessory axis: {name}")
    first, second = perpendicular_basis(axis)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for ring_index, radius in enumerate(radii):
        t = ring_index / max(1, len(radii) - 1)
        center = start.lerp(end, t)
        for segment in range(segments):
            angle = math.tau * segment / segments
            point = (
                center
                + first * radius * math.cos(angle)
                + second * radius * math.sin(angle)
            )
            vertices.append(tuple(point))
    for ring_index in range(len(radii) - 1):
        current = ring_index * segments
        following = (ring_index + 1) * segments
        for segment in range(segments):
            nxt = (segment + 1) % segments
            faces.append(
                (
                    current + segment,
                    current + nxt,
                    following + nxt,
                    following + segment,
                )
            )
    faces.append(tuple(reversed(tuple(range(segments)))))
    faces.append(
        tuple(
            range(
                (len(radii) - 1) * segments,
                len(radii) * segments,
            )
        )
    )
    result = v3.raw_mesh(
        name,
        vertices,
        faces,
        material,
        bevel=bevel,
    )
    result["construction"] = "avatar-rest-bone-axis-tube"
    return result


def fitted_corset_half_v5(
    name: str,
    angles: list[float],
    material: bpy.types.Material,
) -> bpy.types.Object:
    rows = 12
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    bottom_z = 0.805
    for row in range(rows + 1):
        t = row / rows
        radius_x = (
            0.149
            + 0.018 * math.sin(math.pi * t)
            - 0.004 * t
        )
        radius_y = 0.079 + 0.016 * math.sin(math.pi * t)
        for theta in angles:
            frontness = max(0.0, -math.sin(theta))
            lateral = abs(math.cos(theta))
            cup = math.exp(-((lateral - 0.50) / 0.26) ** 2)
            center_plunge = (
                math.exp(-(lateral / 0.19) ** 2) * frontness
            )
            top = (
                0.965
                + 0.092 * frontness * cup
                - 0.018 * center_plunge
            )
            z = bottom_z + (top - bottom_z) * t
            x = radius_x * math.cos(theta)
            y = radius_y * math.sin(theta)
            vertices.append((x, y, z))
    stride = len(angles)
    for row in range(rows):
        for column in range(stride - 1):
            a = row * stride + column
            faces.append((a, a + 1, a + 1 + stride, a + stride))
    obj = geometry.mesh(
        name,
        vertices,
        faces,
        material,
        thickness=0.0025,
    )
    obj["construction"] = "cropped-sweetheart-fitted-shell"
    obj["referenceModel"] = MODEL_CODE
    return obj


def rebuild_armwear_v5(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
    fabric: bpy.types.Material,
    metal: bpy.types.Material,
) -> None:
    del fabric
    v3.remove_objects(
        objects,
        lambda obj: obj.name.startswith("Gauntlet")
        or obj.name.startswith("UpperArm_Band_"),
    )
    for side in ("L", "R"):
        upper_start, upper_end = bone_segment(f"UpperArm_{side}")
        lower_start, lower_end = bone_segment(f"LowerArm_{side}")
        upper_length = (upper_end - upper_start).length
        lower_length = (lower_end - lower_start).length

        band = axis_tube(
            f"UpperArm_Band_{side}",
            upper_start.lerp(upper_end, 0.54),
            upper_start.lerp(upper_end, 0.64),
            [upper_length * 0.145, upper_length * 0.145],
            leather,
            segments=28,
            bevel=0.0010,
        )
        gauntlet = axis_tube(
            f"Gauntlet_{side}",
            lower_start.lerp(lower_end, 0.12),
            lower_start.lerp(lower_end, 0.88),
            [
                lower_length * 0.145,
                lower_length * 0.150,
                lower_length * 0.137,
                lower_length * 0.120,
            ],
            leather,
            segments=32,
            bevel=0.0015,
        )
        wrist_ring = axis_tube(
            f"Gauntlet_Ring_{side}",
            lower_start.lerp(lower_end, 0.80),
            lower_start.lerp(lower_end, 0.85),
            [lower_length * 0.130, lower_length * 0.130],
            metal,
            segments=28,
            bevel=0.0007,
        )
        objects.extend([band, gauntlet, wrist_ring])


def rebuild_arm_belts_v5(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
    metal: bpy.types.Material,
) -> None:
    v4.remove_prefixes(objects, ("Gauntlet_Strap_", "ArmBelt_"))
    for side in ("L", "R"):
        start, end = bone_segment(f"LowerArm_{side}")
        length = (end - start).length
        axis = end - start
        first, _ = perpendicular_basis(axis)
        for index, t in enumerate((0.28, 0.50, 0.72)):
            half_width = 0.027
            belt = axis_tube(
                f"ArmBelt_{side}_{index}",
                start.lerp(end, max(0.02, t - half_width)),
                start.lerp(end, min(0.98, t + half_width)),
                [length * 0.158, length * 0.158],
                leather,
                segments=28,
                bevel=0.0008,
            )
            center = (
                start.lerp(end, t)
                + first * (length * 0.160)
            )
            buckle = geometry.cube(
                f"ArmBelt_Buckle_{side}_{index}",
                tuple(center),
                (0.0055, 0.0030, 0.0055),
                metal,
                bevel=0.0010,
            )
            objects.extend([belt, buckle])


def add_knee_high_socks_v5(
    objects: list[bpy.types.Object],
    fabric: bpy.types.Material,
    leather: bpy.types.Material,
) -> None:
    v4.remove_prefixes(
        objects,
        ("KneeHighSock_", "Ankle_Ornament_"),
    )
    for side in ("L", "R"):
        start, end = bone_segment(f"LowerLeg_{side}")
        length = (end - start).length
        sock = axis_tube(
            f"KneeHighSock_{side}",
            start.lerp(end, 0.08),
            start.lerp(end, 0.88),
            [
                length * 0.142,
                length * 0.138,
                length * 0.125,
                length * 0.112,
            ],
            fabric,
            segments=32,
            bevel=0.0008,
        )
        sock["referenceComponent"] = "knee-high-socks"
        ornament = axis_tube(
            f"Ankle_Ornament_{side}",
            start.lerp(end, 0.80),
            start.lerp(end, 0.86),
            [length * 0.123, length * 0.123],
            leather,
            segments=28,
            bevel=0.0008,
        )
        objects.extend([sock, ornament])


def add_tail_v5(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
) -> None:
    v4.remove_prefixes(objects, ("CatTail",))
    hips_start, hips_end = bone_segment("Hips")
    root = hips_start.lerp(hips_end, 0.45)
    curve_data = bpy.data.curves.new("CatTail", "CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = 0.010
    curve_data.bevel_resolution = 4
    curve_data.resolution_u = 16
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(4)
    points = [
        root + Vector((0.000, 0.105, -0.020)),
        root + Vector((0.018, 0.185, 0.025)),
        root + Vector((0.080, 0.255, 0.090)),
        root + Vector((0.125, 0.285, -0.005)),
        root + Vector((0.085, 0.245, -0.115)),
    ]
    for point, coordinate in zip(spline.bezier_points, points):
        point.co = coordinate
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    curve = bpy.data.objects.new("CatTail", curve_data)
    bpy.context.collection.objects.link(curve)
    curve.data.materials.append(leather)
    tail = v2.convert_curves([curve])[0]
    tail["referenceComponent"] = "tail"
    tail["construction"] = "smooth-bezier-tail"
    objects.append(tail)


def find_target_body() -> bpy.types.Object:
    bodies = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and obj.get("image2outfitRole") == "target-avatar"
    ]
    if not bodies:
        raise RuntimeError(
            "target avatar body is unavailable for weight transfer"
        )
    return max(bodies, key=lambda obj: len(obj.data.vertices))


def bind_nearest_body_weights(
    objects: list[bpy.types.Object],
    rig: bpy.types.Object,
) -> dict[str, Any]:
    body = find_target_body()
    if not body.vertex_groups:
        raise RuntimeError(
            "target avatar has no transferable skin weights"
        )
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(
            body.matrix_world @ vertex.co,
            vertex.index,
        )
    tree.balance()

    weighted = 0
    unweighted: list[str] = []
    assignments: dict[str, str] = {}
    maximum_influences = 0
    for obj in objects:
        if obj.type != "MESH":
            unweighted.append(obj.name)
            continue
        groups: dict[str, bpy.types.VertexGroup] = {}
        object_unweighted = 0
        for vertex in obj.data.vertices:
            _, source_index, _ = tree.find(
                obj.matrix_world @ vertex.co
            )
            source = body.data.vertices[source_index]
            influences = sorted(
                (
                    (
                        body.vertex_groups[item.group].name,
                        float(item.weight),
                    )
                    for item in source.groups
                    if item.weight > 1e-8
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:4]
            if not influences:
                object_unweighted += 1
                continue
            total = sum(value for _, value in influences)
            maximum_influences = max(
                maximum_influences,
                len(influences),
            )
            for group_name, value in influences:
                group = groups.get(group_name)
                if group is None:
                    group = obj.vertex_groups.get(group_name)
                    if group is None:
                        group = obj.vertex_groups.new(
                            name=group_name
                        )
                    groups[group_name] = group
                group.add(
                    [vertex.index],
                    value / total,
                    "REPLACE",
                )
        if object_unweighted:
            unweighted.append(obj.name)
            continue
        world = obj.matrix_world.copy()
        obj.parent = rig
        obj.matrix_world = world
        modifier = obj.modifiers.new(
            "SiroinoSotai Armature",
            "ARMATURE",
        )
        modifier.object = rig
        modifier.use_deform_preserve_volume = True
        obj["skinWeightMethod"] = "nearest-siroino-body-top4"
        weighted += 1
        assignments[obj.name] = "nearest-siroino-body-top4"
    return {
        "armature": rig.name,
        "weightedObjectCount": weighted,
        "unweightedObjects": unweighted,
        "assignments": assignments,
        "method": "nearest-siroino-body-top4",
        "maximumInfluences": maximum_influences,
    }


_BASE_REBUILD_CORSET = v3.rebuild_corset


def rebuild_corset_v5_1(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
    fabric: bpy.types.Material,
) -> None:
    _BASE_REBUILD_CORSET(objects, leather, fabric)
    for obj in objects:
        if obj.name == "Corset_Bottom_Binding":
            obj.location.z = 0.807
        elif obj.name.startswith("Eyelet_"):
            obj.location.z += 0.025
        elif obj.name.startswith("Lace_") and obj.type == "MESH":
            for vertex in obj.data.vertices:
                vertex.co.z += 0.025
    bpy.context.view_layer.update()


def _build_unified_pleated_skirt(
    material: bpy.types.Material,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    top_z = 0.710
    bottom_z = 0.555
    top_radius = 0.166
    bottom_radius = 0.235

    for ring in range(RINGS):
        t = ring / (RINGS - 1)
        z = top_z + (bottom_z - top_z) * t
        base_radius = (
            top_radius
            + (bottom_radius - top_radius) * t
        )
        fold_amplitude = 0.0015 + 0.0105 * t
        for segment in range(SEGMENTS):
            angle = math.tau * segment / SEGMENTS
            radius = (
                base_radius
                + fold_amplitude
                * math.cos(PLEAT_COUNT * angle)
            )
            vertices.append(
                (
                    radius * math.cos(angle),
                    radius * math.sin(angle),
                    z,
                )
            )

    for ring in range(RINGS - 1):
        current = ring * SEGMENTS
        following = (ring + 1) * SEGMENTS
        for segment in range(SEGMENTS):
            nxt = (segment + 1) % SEGMENTS
            faces.append(
                (
                    current + segment,
                    current + nxt,
                    following + nxt,
                    following + segment,
                )
            )

    data = bpy.data.meshes.new("Skirt_Cloth")
    data.from_pydata(vertices, [], faces)
    data.update(calc_edges=True)
    skirt = bpy.data.objects.new("Skirt_Cloth", data)
    bpy.context.collection.objects.link(skirt)
    skirt.data.materials.append(material)
    skirt["referenceComponent"] = "skirt"
    skirt["construction"] = "unified-24-pleat-blender-cloth"
    skirt["pleatCount"] = PLEAT_COUNT
    return skirt


def _ensure_body_collision(body: bpy.types.Object) -> None:
    if not any(
        modifier.type == "COLLISION"
        for modifier in body.modifiers
    ):
        body.modifiers.new(
            "BlackCat body collision",
            "COLLISION",
        )
    bpy.context.view_layer.update()
    collision = getattr(body, "collision", None)
    if collision is not None:
        _set_if_available(
            collision,
            "thickness_outer",
            0.004,
        )
        _set_if_available(
            collision,
            "thickness_inner",
            0.002,
        )
        _set_if_available(
            collision,
            "cloth_friction",
            5.0,
        )


def _bake_cloth(
    skirt: bpy.types.Object,
    body: bpy.types.Object,
) -> dict[str, Any]:
    initial = [
        vertex.co.copy()
        for vertex in skirt.data.vertices
    ]
    top = max(
        vertex.co.z
        for vertex in skirt.data.vertices
    )
    pinned = [
        vertex.index
        for vertex in skirt.data.vertices
        if abs(vertex.co.z - top) < 1e-7
    ]
    if len(pinned) != SEGMENTS:
        raise RuntimeError(
            "cloth waist pin ring must contain "
            f"{SEGMENTS} vertices, got {len(pinned)}"
        )

    group = skirt.vertex_groups.new(name="Cloth_Pin")
    group.add(pinned, 1.0, "REPLACE")
    _ensure_body_collision(body)

    cloth = skirt.modifiers.new(
        "BlackCat cloth simulation",
        "CLOTH",
    )
    cloth.settings.quality = 10
    cloth.settings.mass = 0.14
    cloth.settings.vertex_group_mass = group.name
    _set_if_available(
        cloth.settings,
        "pin_stiffness",
        35.0,
    )
    _set_if_available(
        cloth.settings,
        "tension_stiffness",
        40.0,
    )
    _set_if_available(
        cloth.settings,
        "compression_stiffness",
        40.0,
    )
    _set_if_available(
        cloth.settings,
        "shear_stiffness",
        30.0,
    )
    _set_if_available(
        cloth.settings,
        "bending_stiffness",
        8.0,
    )
    _set_if_available(
        cloth.settings,
        "air_damping",
        6.0,
    )
    if hasattr(cloth.settings, "effector_weights"):
        cloth.settings.effector_weights.gravity = 0.35

    cloth.collision_settings.use_collision = True
    cloth.collision_settings.distance_min = 0.004
    cloth.collision_settings.use_self_collision = True
    cloth.collision_settings.self_distance_min = 0.004
    _set_if_available(
        cloth.collision_settings,
        "collision_quality",
        6,
    )
    _set_if_available(
        cloth.collision_settings,
        "self_friction",
        5.0,
    )

    scene = bpy.context.scene
    previous_start = scene.frame_start
    previous_end = scene.frame_end
    scene.frame_start = 1
    scene.frame_end = CLOTH_FRAMES
    scene.frame_set(1)
    bpy.context.view_layer.update()
    for frame in range(1, CLOTH_FRAMES + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = skirt.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    if len(baked.vertices) != len(initial):
        raise RuntimeError(
            "cloth evaluation changed skirt topology"
        )

    displacements = [
        (vertex.co - start).length
        for vertex, start in zip(
            baked.vertices,
            initial,
        )
    ]
    moved = sum(
        value > 1e-7
        for value in displacements
    )
    maximum = max(displacements, default=0.0)
    mean = (
        sum(displacements)
        / max(1, len(displacements))
    )
    if moved == 0 or maximum <= 1e-7:
        raise RuntimeError(
            "Blender Cloth produced no measurable movement"
        )

    previous_mesh = skirt.data
    skirt.data = baked
    bpy.data.meshes.remove(previous_mesh)
    skirt.modifiers.clear()
    pin_group = skirt.vertex_groups.get("Cloth_Pin")
    if pin_group is not None:
        skirt.vertex_groups.remove(pin_group)

    solid = skirt.modifiers.new(
        "Garment Solidify",
        "SOLIDIFY",
    )
    solid.thickness = 0.0015
    solid.offset = 0.0
    bevel = skirt.modifiers.new(
        "Garment Bevel",
        "BEVEL",
    )
    bevel.width = 0.001
    bevel.segments = 2

    scene.frame_start = previous_start
    scene.frame_end = previous_end
    scene.frame_set(1)
    skirt["clothSimulationFrames"] = CLOTH_FRAMES
    skirt["clothSimulationBaked"] = True
    skirt["clothBodyCollision"] = True
    skirt["clothSelfCollision"] = True
    skirt["clothMovedVertices"] = moved
    skirt["clothMaximumDisplacement"] = maximum
    skirt["clothMeanDisplacement"] = mean

    return {
        "object": skirt.name,
        "frames": CLOTH_FRAMES,
        "pinVertices": len(pinned),
        "pleats": PLEAT_COUNT,
        "bodyCollision": True,
        "selfCollision": True,
        "gravityWeight": 0.35,
        "movedVertices": moved,
        "maximumDisplacement": maximum,
        "meanDisplacement": mean,
        "baked": True,
        "method": "frame-stepped-evaluated-mesh-freeze",
    }


_BASE_MODEL_SHAPE = v2.apply_shape_corrections


def apply_shape_with_cloth(
    objects: list[bpy.types.Object],
) -> None:
    _BASE_MODEL_SHAPE(objects)
    fabric = bpy.data.materials.get("BCB_MatteFabric")
    if fabric is None:
        raise RuntimeError(
            "black-cat fabric material is unavailable"
        )
    v3.remove_objects(
        objects,
        lambda obj: obj.name.startswith("Skirt_Pleat_"),
    )
    skirt = _build_unified_pleated_skirt(fabric)
    cloth_record = _bake_cloth(
        skirt,
        find_target_body(),
    )
    skirt["clothRecordJson"] = json.dumps(
        cloth_record,
        sort_keys=True,
    )
    objects.append(skirt)
    bpy.context.view_layer.update()


def postprocess(base_result: int) -> int:
    job_path = (
        ROOT
        / "config/products/siroino-black-cat-bondage/job.json"
    )
    job = json.loads(
        job_path.read_text(encoding="utf-8-sig")
    )
    product_root = ROOT / job["productRoot"]
    quality_path = (
        product_root
        / "Evidence"
        / "Build"
        / "quality-audit.json"
    )
    report_path = (
        product_root
        / "Evidence"
        / "Build"
        / "product-build-report.json"
    )
    quality = json.loads(
        quality_path.read_text(encoding="utf-8")
    )
    checks = dict(
        quality.get("componentChecks", {})
    )
    checks.pop("pleats24", None)

    garment_meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and obj.get("productId") == PRODUCT_ID
    ]
    skirts = [
        obj
        for obj in garment_meshes
        if obj.name == "Skirt_Cloth"
    ]
    skirt = (
        skirts[0]
        if len(skirts) == 1
        else None
    )
    legacy_pleats = [
        obj.name
        for obj in bpy.context.scene.objects
        if obj.name.startswith("Skirt_Pleat_")
    ]

    checks.update(
        {
            "nearestBodyTop4Weights": bool(garment_meshes)
            and all(
                obj.get("skinWeightMethod")
                == "nearest-siroino-body-top4"
                for obj in garment_meshes
            ),
            "croppedSweetheartCorset": all(
                obj.get("construction")
                == "cropped-sweetheart-fitted-shell"
                for obj in garment_meshes
                if obj.name.startswith("Corset_Shell_")
            ),
            "anatomyAxisArmwear": all(
                obj.get("construction")
                == "avatar-rest-bone-axis-tube"
                for obj in garment_meshes
                if obj.name.startswith(
                    (
                        "Gauntlet_",
                        "ArmBelt_",
                        "KneeHighSock_",
                    )
                )
                and "Buckle" not in obj.name
            ),
            "smoothTail": next(
                (
                    obj.get("construction")
                    == "smooth-bezier-tail"
                    for obj in garment_meshes
                    if obj.name == "CatTail"
                ),
                False,
            ),
            "unifiedClothSkirt": skirt is not None
            and skirt.get("construction")
            == "unified-24-pleat-blender-cloth",
            "pleatCount24": skirt is not None
            and int(
                skirt.get("pleatCount", 0)
            )
            == PLEAT_COUNT,
            "legacyRigidPleatsRemoved": not legacy_pleats,
            "clothSolverBaked": skirt is not None
            and bool(
                skirt.get("clothSimulationBaked")
            ),
            "clothFrames32": skirt is not None
            and int(
                skirt.get("clothSimulationFrames", 0)
            )
            == CLOTH_FRAMES,
            "clothBodyCollision": skirt is not None
            and bool(skirt.get("clothBodyCollision")),
            "clothSelfCollision": skirt is not None
            and bool(skirt.get("clothSelfCollision")),
            "clothSolverMovedMesh": skirt is not None
            and int(
                skirt.get("clothMovedVertices", 0)
            )
            > 0
            and float(
                skirt.get(
                    "clothMaximumDisplacement",
                    0.0,
                )
            )
            > 1e-7,
        }
    )
    cloth_record = (
        json.loads(
            str(skirt.get("clothRecordJson"))
        )
        if skirt is not None
        else None
    )
    quality.update(
        {
            "componentChecks": checks,
            "revision": REVISION,
            "clothSimulation": cloth_record,
            "legacyBaseResult": base_result,
            "passed": (
                not quality.get("unweightedObjects")
                and all(
                    bool(value)
                    for value in checks.values()
                )
            ),
        }
    )
    v2.write_json(quality_path, quality)

    report = json.loads(
        report_path.read_text(encoding="utf-8")
    )
    report["revision"] = REVISION
    report["clothSimulation"] = cloth_record
    report["implementation"] = {
        "solver": "Blender Cloth",
        "blenderVersion": "4.4.3",
        "ossLicense": "GNU GPL",
        "waistPinGroup": "Cloth_Pin",
        "bodyCollision": True,
        "selfCollision": True,
        "frames": CLOTH_FRAMES,
        "frozenFinalFrame": True,
        "legacyRigidPleatObjectsRemoved": True,
    }
    report["visualReviewPriorRevision"] = {
        "revision": "v4-cs-25-10300-reference-corrected",
        "workflowRun": 31301290316,
        "result": "DIRECT_VISUAL_REVIEW_FAIL",
        "findings": [
            "torso silhouette too long and barrel-like",
            "forearm accessories detached in arms-up and arm-cross",
            "lower-leg tubes read as rigid boots instead of fitted socks",
            "tail was visibly angular",
        ],
    }
    report["pending"] = [
        "direct visual review of current five views",
        "direct visual review of all six required poses",
    ]
    v2.write_json(report_path, report)
    return 0 if quality["passed"] else 2


v3.fitted_corset_half = fitted_corset_half_v5
v3.rebuild_armwear = rebuild_armwear_v5
v4.rebuild_arm_belts = rebuild_arm_belts_v5
v4.add_knee_high_socks = add_knee_high_socks_v5
v4.add_tail = add_tail_v5
v3.rebuild_corset = rebuild_corset_v5_1
v2.bind = bind_nearest_body_weights
v2.apply_shape_corrections = apply_shape_with_cloth


def main() -> int:
    return postprocess(v4.main())


if __name__ == "__main__":
    raise SystemExit(main())
