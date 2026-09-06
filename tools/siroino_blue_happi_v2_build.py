#!/usr/bin/env python3
"""Second visual iteration for the SiroinoSotai_PC blue happi."""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

import genworks_product_common as g
import siroino_blue_happi_build as v1
import siroino_strappy_knit_build as base
from tuxedo_halter_runtime import normalize_bone_weights as canonical_normalize

PRODUCT_ID = "siroino-blue-happi"
BODY_NAMES = {"Happi_Back_Body", "Happi_Front_Left", "Happi_Front_Right"}
SLEEVE_NAMES = {"Happi_Sleeve_Left", "Happi_Sleeve_Right"}
Z_BOTTOM = 0.605
Z_NECK = 1.018
INNER_FRONT_X = 0.050
BAND_INNER_X = 0.025
BAND_OUTER_X = 0.050


def body_dimensions(t: float) -> tuple[float, float]:
    """Return a loose shell close enough to read as clothing, not a rigid box."""
    width = 0.154 * (1.0 - t) + 0.149 * t
    depth = 0.093 * (1.0 - t) + 0.087 * t
    return width, depth


def back_top(side_ratio: float) -> float:
    return 1.030 - 0.052 * side_ratio**1.65


def front_top(outward_ratio: float) -> float:
    return Z_NECK - 0.044 * outward_ratio**1.45


def create_back_panel(material: bpy.types.Material) -> bpy.types.Object:
    rows = 16
    columns = 16
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows + 1):
        t = row / rows
        width, depth = body_dimensions(t)
        for column in range(columns + 1):
            u = column / columns
            x = -width + 2.0 * width * u
            side = abs(2.0 * u - 1.0)
            top = back_top(side)
            z = Z_BOTTOM + (top - Z_BOTTOM) * t
            y = depth * (1.0 - 0.16 * side * side)
            vertices.append((x, y, z))
    stride = columns + 1
    for row in range(rows):
        for column in range(columns):
            a = row * stride + column
            faces.append((a, a + 1, a + 1 + stride, a + stride))
    return v1.mesh_object("Happi_Back_Body", vertices, faces, material)


def create_front_panel(
    name: str,
    sign: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    rows = 16
    columns = 12
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows + 1):
        t = row / rows
        width, depth = body_dimensions(t)
        for column in range(columns + 1):
            u = column / columns
            magnitude = INNER_FRONT_X + (width - INNER_FRONT_X) * u
            x = sign * magnitude
            angle = -math.pi / 2.0 + math.pi * 0.92 * u
            y = depth * math.sin(angle)
            top = front_top(u)
            z = Z_BOTTOM + (top - Z_BOTTOM) * t
            vertices.append((x, y, z))
    stride = columns + 1
    for row in range(rows):
        for column in range(columns):
            a = row * stride + column
            face = (a, a + 1, a + 1 + stride, a + stride)
            faces.append(face if sign > 0 else tuple(reversed(face)))
    return v1.mesh_object(name, vertices, faces, material)


def sleeve_chain(
    armature: bpy.types.Object,
    side: str,
) -> tuple[list[Vector], str, str]:
    upper_name = f"UpperArm_{side}"
    lower_name = f"LowerArm_{side}"
    upper = armature.data.bones.get(upper_name)
    lower = armature.data.bones.get(lower_name)
    if upper is None or lower is None:
        raise RuntimeError(f"required sleeve chain missing: {upper_name}, {lower_name}")
    upper_head = armature.matrix_world @ upper.head_local
    upper_tail = armature.matrix_world @ upper.tail_local
    lower_head = armature.matrix_world @ lower.head_local
    lower_tail = armature.matrix_world @ lower.tail_local
    cuff = lower_head.lerp(lower_tail, 0.78)
    upper_axis = upper_tail - upper_head
    points = [
        upper_head - upper_axis * 0.06,
        upper_head.lerp(upper_tail, 0.22),
        upper_head.lerp(upper_tail, 0.50),
        upper_head.lerp(upper_tail, 0.80),
        upper_tail.lerp(lower_head, 0.50),
        lower_head.lerp(cuff, 0.25),
        lower_head.lerp(cuff, 0.50),
        lower_head.lerp(cuff, 0.75),
        cuff,
    ]
    return points, upper_name, lower_name


def create_sleeve(
    name: str,
    bone_name: str,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    side = "L" if bone_name.endswith("_L") else "R"
    points, upper_name, lower_name = sleeve_chain(armature, side)
    segments = 8
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for ring, center in enumerate(points):
        t = ring / (len(points) - 1)
        previous = points[max(0, ring - 1)]
        following = points[min(len(points) - 1, ring + 1)]
        tangent = (following - previous).normalized()
        front = Vector((0.0, -1.0, 0.0))
        vertical = tangent.cross(front)
        if vertical.length < 1e-6:
            front = Vector((0.0, 0.0, 1.0))
            vertical = tangent.cross(front)
        vertical.normalize()
        front = vertical.cross(tangent).normalized()
        shoulder_ease = min(1.0, t / 0.30)
        shoulder_bulge = math.sin(math.pi * shoulder_ease) if t <= 0.30 else 0.0
        half_height = 0.061 + 0.007 * shoulder_bulge - 0.008 * t
        half_depth = 0.043 + 0.004 * shoulder_bulge - 0.003 * t
        for segment in range(segments):
            angle = math.tau * segment / segments
            offset = vertical * (math.cos(angle) * half_height) + front * (
                math.sin(angle) * half_depth
            )
            vertices.append(tuple(center + offset))
    for ring in range(len(points) - 1):
        a = ring * segments
        b = (ring + 1) * segments
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            faces.append((a + segment, a + next_segment, b + next_segment, b + segment))
    obj = v1.mesh_object(name, vertices, faces, material)
    obj["happiUpperBone"] = upper_name
    obj["happiLowerBone"] = lower_name
    obj["happiRingCount"] = len(points)
    obj["happiRingSegments"] = segments
    v1.add_surface_finish(obj, thickness=0.0018, bevel_width=0.0008)
    return obj


def create_front_band(
    name: str,
    sign: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    rows = 16
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows + 1):
        t = row / rows
        _, depth = body_dimensions(t)
        z = Z_BOTTOM + (Z_NECK - Z_BOTTOM) * t
        y = -depth - 0.006
        vertices.extend(
            (
                (sign * BAND_INNER_X, y, z),
                (sign * BAND_OUTER_X, y, z),
            )
        )
    for row in range(rows):
        a = row * 2
        face = (a, a + 1, a + 3, a + 2)
        faces.append(face if sign > 0 else tuple(reversed(face)))
    obj = v1.mesh_object(name, vertices, faces, material)
    v1.add_surface_finish(obj, thickness=0.0022, bevel_width=0.0008)
    return obj


def create_collar_bridge(material: bpy.types.Material) -> bpy.types.Object:
    _, top_depth = body_dimensions(1.0)
    centerline = [
        Vector((-0.0375, -top_depth - 0.006, Z_NECK)),
        Vector((-0.052, -0.030, 1.030)),
        Vector((-0.046, 0.030, 1.040)),
        Vector((0.000, 0.052, 1.044)),
        Vector((0.046, 0.030, 1.040)),
        Vector((0.052, -0.030, 1.030)),
        Vector((0.0375, -top_depth - 0.006, Z_NECK)),
    ]
    half_width = 0.0125
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for index, point in enumerate(centerline):
        previous = centerline[max(0, index - 1)]
        following = centerline[min(len(centerline) - 1, index + 1)]
        tangent = (following - previous).normalized()
        normal = Vector((-tangent.y, tangent.x, 0.0)).normalized()
        vertices.extend(
            (tuple(point + normal * half_width), tuple(point - normal * half_width))
        )
    for index in range(len(centerline) - 1):
        a = index * 2
        faces.append((a, a + 1, a + 3, a + 2))
    obj = v1.mesh_object("Happi_Collar_Back", vertices, faces, material)
    v1.add_surface_finish(obj, thickness=0.0022, bevel_width=0.0008)
    return obj


def sleeve_root_contract(
    armature: bpy.types.Object,
) -> dict[str, object]:
    result: dict[str, object] = {}
    passed = True
    for side in ("L", "R"):
        obj = bpy.data.objects.get(f"Happi_Sleeve_{'Left' if side == 'L' else 'Right'}")
        bone = armature.data.bones.get(f"UpperArm_{side}")
        if obj is None or bone is None:
            result[side] = {
                "passed": False,
                "reason": "missing sleeve or upper-arm bone",
            }
            passed = False
            continue
        segments = int(obj.get("happiRingSegments", 0))
        if segments <= 0 or len(obj.data.vertices) < segments:
            result[side] = {"passed": False, "reason": "invalid sleeve root ring"}
            passed = False
            continue
        root_points = [
            obj.matrix_world @ obj.data.vertices[index].co for index in range(segments)
        ]
        center = sum(root_points, Vector()) / segments
        head = armature.matrix_world @ bone.head_local
        radius = max((point - center).length for point in root_points)
        center_offset = (center - head).length
        overlap_margin = radius - center_offset
        side_pass = overlap_margin >= 0.010
        passed = passed and side_pass
        result[side] = {
            "rootRadiusM": radius,
            "rootCenterToShoulderM": center_offset,
            "overlapMarginM": overlap_margin,
            "requiredMinimumOverlapMarginM": 0.010,
            "passed": side_pass,
        }
    return {"passed": passed, "sides": result}


def configure_cloth(
    panels: list[bpy.types.Object],
    body: bpy.types.Object,
    frame_end: int,
) -> list[dict[str, object]]:
    if body.modifiers.get("Happi Collision") is None:
        body.modifiers.new("Happi Collision", "COLLISION")
    body.collision.thickness_outer = 0.004
    body.collision.damping = 0.55
    contracts: list[dict[str, object]] = []
    for panel in panels:
        coordinates = [panel.matrix_world @ vertex.co for vertex in panel.data.vertices]
        selected = [
            vertex.index
            for vertex, coordinate in zip(panel.data.vertices, coordinates)
            if coordinate.z > 0.965
            or (panel.name.startswith("Happi_Front") and abs(coordinate.x) <= 0.055)
        ]
        pin = panel.vertex_groups.new(name="HappiClothPin")
        pin.add(selected, 1.0, "REPLACE")
        cloth = panel.modifiers.new("Happi Cloth", "CLOTH")
        cloth.settings.quality = 6
        cloth.settings.mass = 0.20
        cloth.settings.tension_stiffness = 42.0
        cloth.settings.compression_stiffness = 40.0
        cloth.settings.shear_stiffness = 18.0
        cloth.settings.bending_stiffness = 2.2
        cloth.settings.air_damping = 5.0
        cloth.settings.vertex_group_mass = pin.name
        cloth.settings.pin_stiffness = 1.0
        cloth.collision_settings.use_collision = True
        cloth.collision_settings.collision_quality = 4
        cloth.collision_settings.distance_min = 0.004
        cloth.point_cache.frame_start = 1
        cloth.point_cache.frame_end = frame_end
        contracts.append(
            {
                "object": panel.name,
                "modifier": cloth.name,
                "pinVertexCount": len(selected),
                "frameStart": 1,
                "frameEnd": frame_end,
            }
        )
    bpy.ops.object.select_all(action="DESELECT")
    panels[0].select_set(True)
    bpy.context.view_layer.objects.active = panels[0]
    bpy.ops.ptcache.bake_all(bake=True)
    bpy.context.scene.frame_set(frame_end)
    bpy.context.view_layer.update()
    for panel in panels:
        bpy.ops.object.select_all(action="DESELECT")
        panel.select_set(True)
        bpy.context.view_layer.objects.active = panel
        modifier = panel.modifiers.get("Happi Cloth")
        if modifier is not None:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        panel.select_set(False)
    return contracts


def sleeve_weights(obj: bpy.types.Object, armature: bpy.types.Object) -> None:
    upper_name = str(obj["happiUpperBone"])
    lower_name = str(obj["happiLowerBone"])
    rings = int(obj["happiRingCount"])
    segments = int(obj["happiRingSegments"])
    obj.parent = armature
    modifier = obj.modifiers.get("SiroinoSotai Armature")
    if modifier is None:
        modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    upper = obj.vertex_groups.get(upper_name) or obj.vertex_groups.new(name=upper_name)
    lower = obj.vertex_groups.get(lower_name) or obj.vertex_groups.new(name=lower_name)
    for ring in range(rings):
        t = ring / (rings - 1)
        lower_weight = max(0.0, min(1.0, (t - 0.40) / 0.22))
        upper_weight = 1.0 - lower_weight
        indices = list(range(ring * segments, (ring + 1) * segments))
        if upper_weight > 0.0:
            upper.add(indices, upper_weight, "REPLACE")
        if lower_weight > 0.0:
            lower.add(indices, lower_weight, "REPLACE")


_original_rigid_mesh_weight = base.rigid_mesh_weight
_original_improve_clearance = g.improve_clearance


def patched_rigid_mesh_weight(
    obj: bpy.types.Object,
    armature: bpy.types.Object,
    bone_name: str,
) -> None:
    if obj.name in SLEEVE_NAMES:
        sleeve_weights(obj, armature)
        return
    _original_rigid_mesh_weight(obj, armature, bone_name)


def patched_normalize(
    objects: list[bpy.types.Object],
    armature: bpy.types.Object,
    *,
    rigid_groups: dict[str, str],
) -> dict[str, object]:
    non_sleeve_rigid = {
        name: bone for name, bone in rigid_groups.items() if name not in SLEEVE_NAMES
    }
    return canonical_normalize(
        objects,
        armature,
        rigid_groups=non_sleeve_rigid,
    )


def patched_improve_clearance(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
    *,
    targets: tuple[float, ...],
    movable,
):
    del targets, movable
    return _original_improve_clearance(
        body,
        garments,
        targets=(0.008, 0.012, 0.015),
        movable=lambda obj: obj.name in BODY_NAMES | SLEEVE_NAMES,
    )


def postprocess(job: dict, result: int) -> int:
    product_root = v1.repo_path(job["productRoot"])
    evidence_dir = product_root / "Evidence" / "Build"
    report_path = evidence_dir / "product-build-report.json"
    quality_path = evidence_dir / "quality-audit.json"
    manifest_path = v1.repo_path(job["productManifestPath"])

    report = v1.read_json(report_path)
    clearance = float(report["clearanceRefinement"][-1]["clearance"]["p01"])
    mean_clearance = float(report["clearanceRefinement"][-1]["clearance"]["mean"])
    front_opening = float(report["frontOpeningM"])
    root_contract = sleeve_root_contract(bpy.data.objects["SiroinoSotai_Armature"])
    fit_pass = (
        0.006 <= clearance <= 0.035
        and mean_clearance <= 0.050
        and 0.025 <= front_opening <= 0.090
        and root_contract["passed"]
    )
    report["passed"] = bool(report["passed"] and fit_pass)
    report["silhouetteRevision"] = "v2-shaped-shell-long-sleeve"
    report["fitEnvelope"] = {
        "clearanceP01M": clearance,
        "meanClearanceM": mean_clearance,
        "frontOpeningM": front_opening,
        "required": {
            "clearanceP01M": [0.006, 0.035],
            "maximumMeanClearanceM": 0.050,
            "frontOpeningM": [0.025, 0.090],
        },
        "status": "PASS" if fit_pass else "FAIL",
        "sleeveRootContract": root_contract,
    }
    report["notes"] = [
        "The body uses curved front and back panels with sloped shoulder seams.",
        "Sleeves overlap the shoulder seam at the root, then taper through upper-arm/lower-arm blended weights.",
        "The collar bridge shares the chest frame with the front bands to stay connected.",
        "The fit gate rejects both body penetration and an oversized rigid box.",
        "No manufacturer, product code, text, or crest is asserted.",
        "Silhouette and styling remain pending direct inspection of current images.",
    ]
    v1.write_json(report_path, report)

    quality = v1.read_json(quality_path)
    for axis in quality["axes"]:
        if axis["axis"] == "fit":
            axis["status"] = "PASS" if fit_pass else "FAIL"
            axis["evidence"] = report["fitEnvelope"]
    quality["technicalAxesPassed"] = all(
        axis["status"] == "PASS"
        for axis in quality["axes"]
        if axis["axis"] not in {"silhouette", "styling-fidelity"}
    )
    v1.write_json(quality_path, quality)

    manifest = v1.read_json(manifest_path)
    manifest["status"] = "WORKING" if report["passed"] else "REJECTED"
    manifest["technicalGates"]["blender"] = "PASS" if report["passed"] else "FAIL"
    manifest["technicalGates"]["tenAxisAudit"] = "WORKING"
    v1.write_json(manifest_path, manifest)

    readme = product_root / "README.md"
    readme.write_text(
        f"""# {job["productName"]}

Product ID: `{PRODUCT_ID}`  
State: **{manifest["status"]}**  
Target: **SiroinoSotai_PC**

The private source is bound only as `{manifest["sourceReference"]}`; the original
image is not redistributed.

## Generated construction

- curved separate back, left-front, and right-front panels
- sloped shoulder seams without a horizontal box top
- long loose sleeves with upper-arm/lower-arm blended weights
- two straight front bands and one continuous neck bridge
- baked Blender Cloth settling for the three body panels

## Current boundary

Technical evidence is recorded in `{manifest["outputs"]["buildReport"]}`. The fit
envelope also rejects excessive body clearance, not only penetration. Silhouette
and styling stay pending until the current five-view and six-pose images are
opened directly; metrics alone cannot make this product COMPLETE.

Unity import, Modular Avatar, NDMF, VRChat Build & Test, and runtime inspection
remain OUT_OF_SCOPE unless separately evidenced.
""",
        encoding="utf-8",
    )

    hashes = product_root / "SOURCE_HASHES.txt"
    rewritten: list[str] = []
    if hashes.is_file():
        for line in hashes.read_text(encoding="utf-8").splitlines():
            if "  " not in line:
                continue
            _, relative = line.split("  ", 1)
            candidate = product_root / relative
            if candidate.is_file():
                rewritten.append(f"{base.sha256(candidate)}  {relative}")
    hashes.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    return 0 if report["passed"] and quality["technicalAxesPassed"] else 2


def install_iteration() -> None:
    v1.body_dimensions = body_dimensions
    v1.create_back_panel = create_back_panel
    v1.create_front_panel = create_front_panel
    v1.create_sleeve = create_sleeve
    v1.create_front_band = create_front_band
    v1.create_collar_bridge = create_collar_bridge
    v1.configure_cloth = configure_cloth
    base.rigid_mesh_weight = patched_rigid_mesh_weight
    v1.normalize_bone_weights = patched_normalize
    g.improve_clearance = patched_improve_clearance


def main() -> int:
    install_iteration()
    args = v1.parse_args()
    job = v1.read_json(v1.repo_path(args.job))
    result = v1.main()
    return postprocess(job, result)


if __name__ == "__main__":
    raise SystemExit(main())
