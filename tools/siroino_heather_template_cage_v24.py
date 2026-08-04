#!/usr/bin/env python3
"""Structured template-cage generator for the Siroino hooded bodysuit.

This revision deliberately stops deriving garment topology by selecting body faces.
It creates regular, semantic garment components first and uses the body only for
surface sampling and nearest-body skin-weight transfer.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import ModuleType

import bpy
from mathutils import Vector

DESIGN_REVISION = "v24-structured-template-cage"
TORSO_COLUMNS = 64
TORSO_ROWS = 20
SLEEVE_COLUMNS = 24
SLEEVE_RINGS = 18
BODY_CLEARANCE_M = 0.016
RESEARCH_OUTPUT = Path(
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "structured-template-cage-trial.json"
)


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _torso_width(z: float) -> float:
    if z <= 0.84:
        return 0.166
    if z <= 0.96:
        return 0.166 + 0.030 * _smoothstep((z - 0.84) / 0.12)
    return max(0.074, 0.196 - 0.98 * (z - 0.96))


def _bottom_z(theta: float) -> float:
    side = abs(math.cos(theta))
    return 0.565 + 0.275 * (side**1.65)


def _top_z(theta: float) -> float:
    side = abs(math.cos(theta))
    return 1.035 - 0.085 * (side**1.8)


def _create_mesh_object(
    pattern: ModuleType,
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    thickness: float,
    subdivision_levels: int,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=False, clean_customdata=False)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)

    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            index = mesh.loops[loop_index].vertex_index
            point = mesh.vertices[index].co
            uv.data[loop_index].uv = (
                0.5 + math.atan2(point.y, point.x) / math.tau,
                max(0.0, min(1.0, point.z)),
            )
        polygon.use_smooth = True

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True
    pattern.v9.base.transfer_nearest_body_weights(obj, body)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if subdivision_levels:
        subdivision = obj.modifiers.new("Template cage smoothing", "SUBSURF")
        subdivision.subdivision_type = "CATMULL_CLARK"
        subdivision.levels = subdivision_levels
        subdivision.render_levels = subdivision_levels
        pattern._move_modifier_before_armature(obj, subdivision)
        bpy.ops.object.modifier_apply(modifier=subdivision.name)

    solidify = obj.modifiers.new("Outward jersey thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_even_offset = True
    pattern._move_modifier_before_armature(obj, solidify)
    bpy.ops.object.modifier_apply(modifier=solidify.name)

    obj.data.validate(verbose=False, clean_customdata=False)
    obj.data.update(calc_edges=True)
    obj.select_set(False)
    return obj


def _torso_and_gusset(
    pattern: ModuleType,
    sampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for row in range(TORSO_ROWS):
        v = row / (TORSO_ROWS - 1)
        for column in range(TORSO_COLUMNS):
            theta = math.tau * column / TORSO_COLUMNS
            bottom = _bottom_z(theta)
            top = _top_z(theta)
            z = bottom + (top - bottom) * v
            width = _torso_width(z)
            x = width * math.cos(theta)
            front = math.sin(theta) < 0.0
            point = sampler.point(x, z, front=front, offset=BODY_CLEARANCE_M)
            vertices.append((point.x, point.y, point.z))

    for row in range(TORSO_ROWS - 1):
        current = row * TORSO_COLUMNS
        following = (row + 1) * TORSO_COLUMNS
        for column in range(TORSO_COLUMNS):
            nxt = (column + 1) % TORSO_COLUMNS
            faces.append(
                (
                    current + column,
                    current + nxt,
                    following + nxt,
                    following + column,
                )
            )

    # Explicit U-shaped gusset. It shares the front/back low-boundary vertices,
    # so it splits the lower boundary into left and right leg openings rather
    # than producing two unconstrained hanging tabs.
    front_center = 3 * TORSO_COLUMNS // 4
    back_center = TORSO_COLUMNS // 4
    half_span = 2
    front_pair = [
        (front_center - half_span) % TORSO_COLUMNS,
        (front_center + half_span) % TORSO_COLUMNS,
    ]
    back_pair = [
        (back_center - half_span) % TORSO_COLUMNS,
        (back_center + half_span) % TORSO_COLUMNS,
    ]
    front_pair.sort(key=lambda index: vertices[index][0])
    back_pair.sort(key=lambda index: vertices[index][0])

    pair_rows: list[tuple[int, int]] = [(front_pair[0], front_pair[1])]
    steps = 10
    for step in range(1, steps):
        t = step / steps
        indices = []
        for left_or_right in range(2):
            first = Vector(vertices[front_pair[left_or_right]])
            last = Vector(vertices[back_pair[left_or_right]])
            point = first.lerp(last, t)
            point.z -= 0.070 * math.sin(math.pi * t)
            indices.append(len(vertices))
            vertices.append((point.x, point.y, point.z))
        pair_rows.append((indices[0], indices[1]))
    pair_rows.append((back_pair[0], back_pair[1]))

    for current, following in zip(pair_rows, pair_rows[1:], strict=True):
        faces.append((current[0], current[1], following[1], following[0]))

    obj = _create_mesh_object(
        pattern,
        "Heather_Body_Shell",
        vertices,
        faces,
        material,
        armature,
        sampler.body,
        thickness=0.0014,
        subdivision_levels=1,
    )
    obj["constructionRepresentation"] = (
        "structured periodic torso cage plus shared-edge U gusset"
    )
    obj["bodyTopologyCopied"] = False
    return obj


def _frame(tangent: Vector) -> tuple[Vector, Vector]:
    direction = tangent.normalized()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(direction.dot(reference)) > 0.92:
        reference = Vector((0.0, 1.0, 0.0))
    first = direction.cross(reference).normalized()
    second = direction.cross(first).normalized()
    return first, second


def _arm_centers(
    pattern: ModuleType,
    armature: bpy.types.Object,
    side: str,
) -> list[Vector]:
    upper_head, upper_tail = pattern.bone_segment(armature, f"UpperArm_{side}")
    lower_head, lower_tail = pattern.bone_segment(armature, f"LowerArm_{side}")
    centers: list[Vector] = []
    for ring in range(SLEEVE_RINGS):
        t = ring / (SLEEVE_RINGS - 1)
        if t <= 0.48:
            local = t / 0.48
            centers.append(upper_head.lerp(upper_tail, local))
        else:
            local = (t - 0.48) / 0.52
            centers.append(lower_head.lerp(lower_tail, local))
    return centers


def _sleeve(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    centers = _arm_centers(pattern, armature, side)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for ring, center in enumerate(centers):
        if ring == 0:
            tangent = centers[1] - center
        elif ring == len(centers) - 1:
            tangent = center - centers[-2]
        else:
            tangent = centers[ring + 1] - centers[ring - 1]
        first, second = _frame(tangent)
        t = ring / (len(centers) - 1)
        radius = 0.062 - 0.021 * _smoothstep(t)
        radius += 0.004 * math.exp(-((t - 0.48) / 0.18) ** 2)
        for column in range(SLEEVE_COLUMNS):
            angle = math.tau * column / SLEEVE_COLUMNS
            point = center + first * (math.cos(angle) * radius)
            point += second * (math.sin(angle) * radius)
            vertices.append((point.x, point.y, point.z))

    for ring in range(len(centers) - 1):
        current = ring * SLEEVE_COLUMNS
        following = (ring + 1) * SLEEVE_COLUMNS
        for column in range(SLEEVE_COLUMNS):
            nxt = (column + 1) % SLEEVE_COLUMNS
            faces.append(
                (
                    current + column,
                    current + nxt,
                    following + nxt,
                    following + column,
                )
            )

    return _create_mesh_object(
        pattern,
        f"Heather_Long_Sleeve_{side}",
        vertices,
        faces,
        material,
        armature,
        body,
        thickness=0.0013,
        subdivision_levels=1,
    )


def _cuff(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    centers = _arm_centers(pattern, armature, side)[-4:]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for ring, center in enumerate(centers):
        tangent = centers[-1] - centers[0]
        first, second = _frame(tangent)
        radius = 0.0435 - 0.0015 * ring / max(1, len(centers) - 1)
        for column in range(SLEEVE_COLUMNS):
            angle = math.tau * column / SLEEVE_COLUMNS
            point = center + first * (math.cos(angle) * radius)
            point += second * (math.sin(angle) * radius)
            vertices.append((point.x, point.y, point.z))
    for ring in range(len(centers) - 1):
        current = ring * SLEEVE_COLUMNS
        following = (ring + 1) * SLEEVE_COLUMNS
        for column in range(SLEEVE_COLUMNS):
            nxt = (column + 1) % SLEEVE_COLUMNS
            faces.append(
                (current + column, current + nxt, following + nxt, following + column)
            )
    return _create_mesh_object(
        pattern,
        f"Heather_Rib_Cuff_{side}",
        vertices,
        faces,
        material,
        armature,
        body,
        thickness=0.0017,
        subdivision_levels=1,
    )


def _attached_hood_roll(
    pattern: ModuleType,
    sampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    columns = 56
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row, (z, width, offset) in enumerate(
        ((0.995, 0.078, 0.019), (1.025, 0.086, 0.026), (1.050, 0.074, 0.032))
    ):
        for column in range(columns):
            theta = math.tau * column / columns
            x = width * math.cos(theta)
            front = math.sin(theta) < 0.0
            point = sampler.point(x, z, front=front, offset=offset)
            if not front:
                point.y += 0.018 * math.sin(math.pi * row / 2.0)
            vertices.append((point.x, point.y, point.z))
    for row in range(2):
        current = row * columns
        following = (row + 1) * columns
        for column in range(columns):
            nxt = (column + 1) % columns
            faces.append(
                (current + column, current + nxt, following + nxt, following + column)
            )
    obj = _create_mesh_object(
        pattern,
        "Heather_Hood_Folded_Roll",
        vertices,
        faces,
        material,
        armature,
        sampler.body,
        thickness=0.0018,
        subdivision_levels=1,
    )
    obj["hoodConstruction"] = "attached three-ring cowl; no detached tube primitive"
    return obj


def _cords(pattern: ModuleType, sampler, armature, material) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    for side, sign in (("L", -1.0), ("R", 1.0)):
        points = []
        for x, z, offset in (
            (sign * 0.038, 1.012, 0.022),
            (sign * 0.041, 0.990, 0.024),
            (sign * 0.040, 0.965, 0.026),
        ):
            point = sampler.point(x, z, front=True, offset=offset)
            points.append((point.x, point.y, point.z))
        cord = pattern.v9.base.curve_tube(
            f"Heather_Hood_Drawcord_{side}",
            points,
            0.0009,
            material,
            armature,
            "Chest",
            resolution=2,
        )
        pattern.v9.base.transfer_nearest_body_weights(cord, sampler.body)
        result.append(cord)
    return result


def _validate(objects: list[bpy.types.Object]) -> dict[str, object]:
    names = [obj.name for obj in objects if obj.type == "MESH"]
    vertices = sum(len(obj.data.vertices) for obj in objects if obj.type == "MESH")
    polygons = sum(len(obj.data.polygons) for obj in objects if obj.type == "MESH")
    failures: list[str] = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        for vertex in obj.data.vertices:
            if not all(math.isfinite(value) for value in vertex.co):
                failures.append(f"{obj.name}: non-finite vertex {vertex.index}")
                break
    if failures:
        raise RuntimeError(
            "Structured template cage validation failed: " + "; ".join(failures)
        )
    return {
        "meshObjects": names,
        "meshObjectCount": len(names),
        "vertices": vertices,
        "polygons": polygons,
        "bodyTopologyCopied": False,
        "primaryRepresentation": "explicit regular template cages",
    }


def _write_trial(metrics: dict[str, object]) -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / RESEARCH_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "status": "EXECUTED",
        "result": "PASS",
        "executedAt": "2026-08-05",
        "revision": DESIGN_REVISION,
        "method": "structured template-cage garment construction",
        "sources": [
            {
                "title": "GarmentCode: Programming Parametric Sewing Patterns",
                "url": "https://arxiv.org/abs/2306.03642",
                "officialCode": "https://github.com/maria-korosteleva/GarmentCode",
            },
            {
                "title": (
                    "PatternGSL: A Structured Specification Language for Template-Free "
                    "and Simulation-Ready 3D Garments"
                ),
                "url": "https://arxiv.org/abs/2606.24564",
                "officialCode": "https://github.com/PatternGSL/PatternGSL",
            },
        ],
        "implementation": {
            "kind": "independent Blender implementation",
            "authorsImplementationExecuted": False,
            "authorsCodeCopied": False,
            "bodyRole": "surface and skin-weight reference only",
            "topologySource": (
                "explicit periodic torso, shared-edge gusset, arm tubes, cuffs and "
                "attached cowl"
            ),
        },
        "metrics": metrics,
        "acceptance": {
            "researchTrial": "PASS",
            "visualAppearanceReview": "PENDING",
            "poseEvidence": "PENDING",
        },
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def create_outfit(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    sampler = pattern.v9.SurfaceSampler(body)
    garments: list[bpy.types.Object] = [
        _torso_and_gusset(pattern, sampler, armature, fabric),
        _sleeve(pattern, body, armature, fabric, "L"),
        _sleeve(pattern, body, armature, fabric, "R"),
        _cuff(pattern, body, armature, trim, "L"),
        _cuff(pattern, body, armature, trim, "R"),
        _attached_hood_roll(pattern, sampler, armature, fabric),
    ]
    garments.extend(
        pattern.v9._placket_and_buttons(
            sampler,
            armature,
            trim,
            button_material,
        )
    )
    garments.extend(_cords(pattern, sampler, armature, trim))
    metrics = _validate(garments)
    _write_trial(metrics)
    return garments


def install(pattern: ModuleType) -> None:
    """Replace body-face extraction with a structured template-cage generator."""
    pattern.DESIGN_REVISION = DESIGN_REVISION
    pattern.create_outfit = lambda body, armature, fabric, trim, buttons: create_outfit(
        pattern,
        body,
        armature,
        fabric,
        trim,
        buttons,
    )
