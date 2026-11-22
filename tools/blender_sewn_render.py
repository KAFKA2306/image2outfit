"""Render the actual weighted prototype and imported target for direct review."""

import argparse
import array
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from blender_cloth_simulation import read_json, repo_path, write_json
from genworks_product_common import (
    pastel_studio,
    point_camera,
    configure_render,
    reset_pose,
    set_pose,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raise_arms_world_up(armature):
    """Resolve the imported rig's local axes instead of guessing Euler angles."""
    evidence = {}
    for name in ("UpperArm_L", "UpperArm_R"):
        bone = armature.pose.bones[name]
        rest_world = armature.matrix_world @ bone.matrix
        local_up = (rest_world.to_3x3().inverted() @ Vector((0, 0, 1))).normalized()
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = Vector((0, 1, 0)).rotation_difference(local_up)
        bpy.context.view_layer.update()
        head = armature.matrix_world @ bone.head
        tail = armature.matrix_world @ bone.tail
        direction = (tail - head).normalized()
        if direction.z < 0.98:
            raise ValueError(f"arms-up world-axis check failed for {name}: {direction}")
        evidence[name] = {
            "headWorldM": list(head),
            "tailWorldM": list(tail),
            "directionWorld": list(direction),
            "pointsUp": True,
        }
    return evidence


def _component_category(piece_id):
    if piece_id.startswith("shorts-"):
        return "shorts"
    if piece_id.startswith("overskirt-front-lap-"):
        return "front-lap"
    if piece_id.startswith("overskirt-"):
        return "overskirt"
    return "other-garment"


def _component_id_materials():
    colors = {
        "shorts": (0.0, 1.0, 1.0, 1.0),
        "front-lap": (1.0, 0.0, 0.0, 1.0),
        "overskirt": (0.0, 0.15, 1.0, 1.0),
        "other-garment": (1.0, 0.0, 1.0, 1.0),
        "avatar": (0.0, 1.0, 0.0, 1.0),
    }
    materials = {}
    for category, color in colors.items():
        material = bpy.data.materials.new(f"__component_id_{category}")
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = color
        output = nodes.new("ShaderNodeOutputMaterial")
        material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
        materials[category] = material
    return materials


def _enable_component_id_materials(objects, scene):
    """Temporarily assign solid semantic colors to the actual evaluated garment mesh."""
    materials = _component_id_materials()
    snapshots = []
    for obj in objects:
        if obj.type != "MESH" or obj == bpy.context.scene.camera:
            continue
        mesh = obj.data
        original_materials = list(mesh.materials)
        original_indices = [polygon.material_index for polygon in mesh.polygons]
        snapshots.append((obj, mesh, original_materials, original_indices))
        if obj.get("prototypeRole") == "target-avatar-reference-only":
            category_indices = ["avatar"] * len(mesh.polygons)
        elif obj.get("prototypeRole") == "weighted-unfit-sewn-prototype":
            try:
                piece_ids = json.loads(obj["canonicalPieceIds"])
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError(f"component-ID render lacks piece ownership on {obj.name}") from error
            ownership = mesh.attributes.get("canonical_piece_index")
            if ownership is None or ownership.domain != "FACE" or len(ownership.data) != len(mesh.polygons):
                raise ValueError(f"component-ID render lacks face ownership on {obj.name}")
            category_indices = []
            for face_owner in ownership.data:
                if face_owner.value < 0 or face_owner.value >= len(piece_ids):
                    raise ValueError(f"component-ID render found invalid face ownership on {obj.name}")
                category_indices.append(_component_category(piece_ids[face_owner.value]))
        else:
            category_indices = ["other-garment"] * len(mesh.polygons)

        mesh.materials.clear()
        category_order = list(materials)
        for category in category_order:
            mesh.materials.append(materials[category])
        category_slots = {category: index for index, category in enumerate(category_order)}
        for polygon, category in zip(mesh.polygons, category_indices):
            polygon.material_index = category_slots[category]

    original_scene = {
        "viewTransform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "gamma": scene.view_settings.gamma,
        "world": scene.world,
        "worldUseNodes": scene.world.use_nodes if scene.world else None,
        "worldColor": tuple(scene.world.color) if scene.world else None,
        "worldBackgroundColor": None,
        "worldBackgroundStrength": None,
    }
    if scene.world and scene.world.use_nodes:
        background = next(
            (node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND"),
            None,
        )
        if background:
            original_scene["worldBackgroundColor"] = tuple(background.inputs["Color"].default_value)
            original_scene["worldBackgroundStrength"] = background.inputs["Strength"].default_value
            background.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            background.inputs["Strength"].default_value = 0.0
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    if scene.world and not scene.world.use_nodes:
        scene.world.color = (0.0, 0.0, 0.0)
    return snapshots, original_scene


def _restore_component_id_materials(snapshots, original_scene, scene):
    for _obj, mesh, original_materials, original_indices in snapshots:
        mesh.materials.clear()
        for material in original_materials:
            mesh.materials.append(material)
        for polygon, material_index in zip(mesh.polygons, original_indices):
            polygon.material_index = material_index
    scene.view_settings.view_transform = original_scene["viewTransform"]
    scene.view_settings.look = original_scene["look"]
    scene.view_settings.exposure = original_scene["exposure"]
    scene.view_settings.gamma = original_scene["gamma"]
    scene.world = original_scene["world"]
    if scene.world:
        scene.world.use_nodes = original_scene["worldUseNodes"]
        scene.world.color = original_scene["worldColor"]
        if scene.world.use_nodes and original_scene["worldBackgroundColor"] is not None:
            background = next(
                (node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND"),
                None,
            )
            if background:
                background.inputs["Color"].default_value = original_scene["worldBackgroundColor"]
                background.inputs["Strength"].default_value = original_scene["worldBackgroundStrength"]


def _count_component_pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    width, height = map(int, image.size)
    if width <= 0 or height <= 0:
        bpy.data.images.remove(image)
        raise ValueError("component-ID PNG has invalid dimensions")
    pixels = array.array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(pixels)
    counts = {"shorts": 0, "front-lap": 0, "overskirt": 0, "other-garment": 0, "avatar": 0}
    for offset in range(0, len(pixels), 4):
        r, g, b = pixels[offset], pixels[offset + 1], pixels[offset + 2]
        channel = max(range(3), key=(r, g, b).__getitem__)
        maximum = (r, g, b)[channel]
        if maximum < 0.05:
            continue
        if channel == 0:
            counts["front-lap" if g < 0.20 and b < 0.20 else "other-garment"] += 1
        elif channel == 1:
            counts["shorts" if r < 0.20 and b > 0.20 else "avatar"] += 1
        else:
            counts["overskirt"] += 1
    bpy.data.images.remove(image)
    return width, height, counts


def render_component_id(objects, scene, output, expected_source_sha256):
    """Render the current pose with face-owner color IDs and count visible category pixels."""
    snapshots, original_scene = _enable_component_id_materials(objects, scene)
    try:
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        width, height, counts = _count_component_pixels(output)
        return {
            "path": str(output),
            "sha256": digest(output),
            "sourceSha256": expected_source_sha256,
            "width": width,
            "height": height,
            "visibleProjectedPixels": counts,
            "shortsOnlyProjectedPixelCount": counts["shorts"],
            "evidenceBoundary": "Color-ID pixels are rendered from canonical face ownership on the current weighted prototype, with depth occlusion from the avatar and all garment components. Counts are projected visible pixels at the declared orthographic pose camera; they do not establish fit, pressure, collision, appearance acceptance, runtime, or release.",
        }
    finally:
        _restore_component_id_materials(snapshots, original_scene, scene)


def _piece_surface_tree(objects, depsgraph, piece_ids):
    """Build a posed-world BVH from only faces owned by the requested panels."""
    vertices = []
    polygons = []
    face_owners = []
    included_faces = 0
    for obj in objects:
        if (
            obj.type != "MESH"
            or obj.get("prototypeRole") != "weighted-unfit-sewn-prototype"
        ):
            continue
        try:
            pieces = json.loads(obj["canonicalPieceIds"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            ownership = mesh.attributes.get("canonical_piece_index")
            if ownership is None:
                continue
            mesh.calc_loop_triangles()
            offset = len(vertices)
            vertices.extend(
                evaluated.matrix_world @ vertex.co for vertex in mesh.vertices
            )
            for triangle in mesh.loop_triangles:
                owner = ownership.data[triangle.polygon_index]
                if owner.value < 0 or owner.value >= len(pieces):
                    raise ValueError(f"Invalid sewn face owner on {obj.name}")
                if pieces[owner.value] not in piece_ids:
                    continue
                polygons.append(tuple(offset + index for index in triangle.vertices))
                face_owners.append(
                    {
                        "object": obj.name,
                        "pieceId": pieces[owner.value],
                        "sourcePolygonIndex": int(triangle.polygon_index),
                        "sourceTriangleIndex": int(triangle.index),
                    }
                )
                included_faces += 1
        finally:
            evaluated.to_mesh_clear()
    if not polygons:
        raise ValueError(
            f"No evaluated faces found for canonical pieces: {sorted(piece_ids)}"
        )
    return (
        BVHTree.FromPolygons(vertices, polygons, all_triangles=True),
        included_faces,
        face_owners,
    )


def _body_surface_samples(body, depsgraph, armature, diagnostic):
    """Bind pose samples to rest-triangle IDs and explicit front-thigh criteria."""
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        body.data.calc_loop_triangles()
        group_names = {group.index: group.name for group in body.vertex_groups}
        weights = []
        for vertex in body.data.vertices:
            weights.append(
                {
                    group_names[item.group]: float(item.weight)
                    for item in vertex.groups
                    if item.group in group_names
                }
            )
        normal_matrix = evaluated.matrix_world.to_3x3().inverted().transposed()
        pose_samples = {
            "pelvis-posterior": [],
            "upper-thigh-left": [],
            "upper-thigh-right": [],
        }
        front_thigh_samples = {"left": [], "right": []}
        rest_triangles = body.data.loop_triangles
        if len(mesh.loop_triangles) != len(rest_triangles):
            raise ValueError("Evaluated avatar triangle count changed across pose")
        anterior = Vector(diagnostic["anteriorDirectionWorld"])
        if anterior.length_squared < 1e-12:
            raise ValueError("Configured anterior direction must be non-zero")
        anterior.normalize()
        min_front_dot = float(diagnostic["minimumAnteriorNormalDot"])
        longitudinal_min, longitudinal_max = diagnostic["longitudinalBoneRange"]
        armature_to_world = armature.matrix_world
        bone_segments = {}
        for side in ("left", "right"):
            bone_name = diagnostic["thighBoneBySide"][side]
            if bone_name not in group_names.values():
                raise ValueError(f"Pose coverage requires body weight group {bone_name}")
            bone = armature.data.bones.get(bone_name)
            if bone is None:
                raise ValueError(f"Pose coverage requires rest bone {bone_name}")
            start = armature_to_world @ bone.head_local
            end = armature_to_world @ bone.tail_local
            axis = end - start
            if axis.length_squared < 1e-12:
                raise ValueError(f"Rest thigh bone has zero length: {bone_name}")
            bone_segments[side] = (start, axis, axis.length_squared)
        for triangle in mesh.loop_triangles:
            ids = triangle.vertices
            rest_triangle = rest_triangles[triangle.index]
            if tuple(ids) != tuple(rest_triangle.vertices):
                raise ValueError("Evaluated avatar triangle IDs changed across pose")
            if any(index >= len(body.data.vertices) for index in ids):
                raise ValueError(
                    "Evaluated avatar surface changed vertex correspondence"
                )
            world = [evaluated.matrix_world @ mesh.vertices[index].co for index in ids]
            center = (world[0] + world[1] + world[2]) / 3.0
            normal = (normal_matrix @ triangle.normal).normalized()
            averaged = {
                name: sum(weights[index].get(name, 0.0) for index in ids) / 3.0
                for name in ("Hips", "UpperLeg_L", "UpperLeg_R")
            }
            if averaged["Hips"] >= 0.5 and normal.y >= 0.15:
                pose_samples["pelvis-posterior"].append(
                    (int(triangle.index), center, normal)
                )
            if averaged["UpperLeg_L"] >= 0.55:
                pose_samples["upper-thigh-left"].append(
                    (int(triangle.index), center, normal)
                )
            if averaged["UpperLeg_R"] >= 0.55:
                pose_samples["upper-thigh-right"].append(
                    (int(triangle.index), center, normal)
                )
            rest_world = [
                body.matrix_world @ body.data.vertices[index].co for index in ids
            ]
            rest_center = (rest_world[0] + rest_world[1] + rest_world[2]) / 3.0
            rest_normal = (
                body.matrix_world.to_3x3().inverted().transposed()
                @ rest_triangle.normal
            ).normalized()
            if rest_normal.dot(anterior) < min_front_dot:
                continue
            for side in ("left", "right"):
                weight_name = diagnostic["thighBoneBySide"][side]
                if averaged[weight_name] < 0.55:
                    continue
                start, axis, axis_length_squared = bone_segments[side]
                longitudinal = (rest_center - start).dot(axis) / axis_length_squared
                if longitudinal_min <= longitudinal <= longitudinal_max:
                    front_thigh_samples[side].append(
                        (int(triangle.index), center, normal, float(longitudinal))
                    )
        return pose_samples, front_thigh_samples
    finally:
        evaluated.to_mesh_clear()


def measure_shared_seam_pose_continuity(objects, depsgraph, expected_sewn_objects):
    """Measure evaluated gaps between skinned copies of canonical seam points."""
    references = {}
    missing_expected = set(expected_sewn_objects)
    excluded_noncanonical = 0
    for obj in objects:
        if (
            obj.type != "MESH"
            or obj.get("prototypeRole") != "weighted-unfit-sewn-prototype"
        ):
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            attribute = mesh.attributes.get("canonical_sewn_vertex_index")
            if attribute is None:
                if obj.name in missing_expected:
                    raise ValueError(
                        f"Expected canonical sewn object lost seam provenance: {obj.name}"
                    )
                excluded_noncanonical += 1
                continue
            if len(attribute.data) != len(mesh.vertices):
                raise ValueError(
                    f"Evaluated garment lost canonical seam provenance: {obj.name}"
                )
            missing_expected.discard(obj.name)
            for vertex, source in zip(mesh.vertices, attribute.data):
                references.setdefault(int(source.value), []).append(
                    (obj.name, evaluated.matrix_world @ vertex.co)
                )
        finally:
            evaluated.to_mesh_clear()
    if missing_expected:
        raise ValueError(
            "Required canonical sewn objects are absent from pose seam audit: "
            + ", ".join(sorted(missing_expected))
        )
    seams = [
        copies
        for copies in references.values()
        if len({name for name, _point in copies}) > 1
    ]
    return {
        "method": "evaluated-canonical-seam-position-gap-v1",
        "sharedCanonicalVertexCount": len(seams),
        "excludedNoncanonicalObjectCount": excluded_noncanonical,
        "maximumPairwiseGapM": max(
            (
                max(
                    (copies[first][1] - copies[second][1]).length
                    for first in range(len(copies))
                    for second in range(first + 1, len(copies))
                )
                for copies in seams
            ),
            default=0.0,
        ),
        "grantsFitAcceptance": False,
    }


def measure_pose_coverage(
    body, objects, depsgraph, armature, shorts_ids, skirt_ids, piece_group_source,
    front_lap_diagnostic,
):
    """Measure matched-pose body surface hits against shorts and skirt surfaces."""
    samples, front_thigh_samples = _body_surface_samples(
        body, depsgraph, armature, front_lap_diagnostic
    )
    lap_ids = front_lap_diagnostic["frontLapPieceIdsBySide"]
    layers = {
        "under-shorts": _piece_surface_tree(objects, depsgraph, shorts_ids),
        "overskirt": _piece_surface_tree(objects, depsgraph, skirt_ids),
        "front-lap-left": _piece_surface_tree(objects, depsgraph, set(lap_ids["left"])),
        "front-lap-right": _piece_surface_tree(objects, depsgraph, set(lap_ids["right"])),
        "front-lap-union": _piece_surface_tree(
            objects, depsgraph, set(lap_ids["left"]) | set(lap_ids["right"])
        ),
    }
    layer_piece_ids = {
        "under-shorts": shorts_ids,
        "overskirt": skirt_ids,
        "front-lap-left": set(lap_ids["left"]),
        "front-lap-right": set(lap_ids["right"]),
        "front-lap-union": set(lap_ids["left"]) | set(lap_ids["right"]),
    }
    body.data.calc_loop_triangles()
    result = {
        "surfaceCoordinateMethod": "posed-avatar-triangle-centroids; deformation-weight anatomical zones; outward-normal ray into matching-pose canonical garment faces",
        "pieceGroupSource": piece_group_source,
        "bodySurfaceTriangleCount": len(body.data.loop_triangles),
        "zoneSelection": {
            "pelvisPosterior": "mean Hips vertex-group weight >= 0.50 and posed surface normal world-Y >= 0.15",
            "leftThigh": "mean UpperLeg_L vertex-group weight >= 0.55",
            "rightThigh": "mean UpperLeg_R vertex-group weight >= 0.55",
            "frontThigh": {
                "weightThreshold": 0.55,
                "restSurfaceNormalDotWithAnteriorDirectionMinimum": front_lap_diagnostic["minimumAnteriorNormalDot"],
                "anteriorDirectionWorld": front_lap_diagnostic["anteriorDirectionWorld"],
                "restBoneLongitudinalFraction": front_lap_diagnostic["longitudinalBoneRange"],
                "restThighBoneBySide": front_lap_diagnostic["thighBoneBySide"],
                "triangleIDsBoundToRestTopology": True,
            },
        },
        "ray": {
            "originOffsetM": 0.0005,
            "maximumDistanceM": 0.25,
            "direction": "posed avatar surface normal",
        },
        "layers": {
            name: {
                "canonicalPieceIds": sorted(layer_piece_ids[name]),
                "evaluatedGarmentFaceCount": face_count,
            }
            for name, (_tree, face_count, _owners) in layers.items()
        },
        "zones": {},
        "frontLapToFrontThigh": {
            "method": front_lap_diagnostic["method"],
            "nearDistanceDiagnosticM": front_lap_diagnostic["nearDistanceDiagnosticM"],
            "originOffsetSensitivityM": front_lap_diagnostic["originOffsetSensitivityM"],
            "combinations": {},
            "evidenceBoundary": front_lap_diagnostic["evidenceBoundary"],
        },
    }
    for zone, zone_samples in samples.items():
        result["zones"][zone] = {"sampleCount": len(zone_samples), "layers": {}}
        sample_ids_sha = hashlib.sha256(
            ",".join(
                str(triangle) for triangle, _center, _normal in zone_samples
            ).encode("ascii")
        ).hexdigest()
        for layer_name, (tree, _face_count, face_owners) in layers.items():
            hits = []
            for body_triangle, center, normal in zone_samples:
                location, _hit_normal, _face_index, distance = tree.ray_cast(
                    center + normal * 0.0005, normal, 0.25
                )
                if location is not None and distance is not None and distance >= 0:
                    hit_owner = face_owners[_face_index]
                    hits.append((body_triangle, float(distance), hit_owner))
            distances = sorted(distance for _triangle, distance, _owner in hits)
            result["zones"][zone]["layers"][layer_name] = {
                "coveredSampleCount": len(hits),
                "coverageFraction": (len(hits) / len(zone_samples))
                if zone_samples
                else None,
                "surfaceGapM": (
                    {
                        "minimum": distances[0],
                        "median": distances[len(distances) // 2],
                        "p95": distances[
                            min(len(distances) - 1, int((len(distances) - 1) * 0.95))
                        ],
                        "maximum": distances[-1],
                    }
                    if distances
                    else None
                ),
                "sampleTriangleIdsSha256": sample_ids_sha,
                "coveredTriangleIdsSha256": hashlib.sha256(
                    ",".join(str(triangle) for triangle, _distance, _owner in hits).encode(
                        "ascii"
                    )
                ).hexdigest(),
            }
    for lap_side, thigh_side in (
        ("left", "left"),
        ("left", "right"),
        ("right", "left"),
        ("right", "right"),
    ):
        zone_samples = front_thigh_samples[thigh_side]
        layer_name = f"front-lap-{lap_side}"
        tree, _face_count, face_owners = layers[layer_name]
        hits = []
        for body_triangle, center, normal, longitudinal in zone_samples:
            location, _hit_normal, face_index, distance = tree.ray_cast(
                center + normal * 0.0005, normal, 0.25
            )
            if location is not None and distance is not None and distance >= 0:
                hits.append(
                    (
                        body_triangle,
                        float(distance),
                        face_owners[face_index],
                        longitudinal,
                    )
                )
        distances = sorted(hit[1] + 0.0005 for hit in hits)
        triangle_ids = [int(item[0]) for item in zone_samples]
        hit_ids = [hit[0] for hit in hits]
        near_count = sum(
            distance <= front_lap_diagnostic["nearDistanceDiagnosticM"]
            for distance in distances
        )
        sensitivity_offset = float(front_lap_diagnostic["originOffsetSensitivityM"])
        sensitivity_hits = 0
        sensitivity_near = 0
        for _body_triangle, center, normal, _longitudinal in zone_samples:
            location, _hit_normal, _face_index, distance = tree.ray_cast(
                center + normal * sensitivity_offset, normal, 0.25
            )
            if location is not None and distance is not None and distance >= 0:
                sensitivity_hits += 1
                if (
                    distance + sensitivity_offset
                    <= front_lap_diagnostic["nearDistanceDiagnosticM"]
                ):
                    sensitivity_near += 1
        key = f"{lap_side}-lap-to-{thigh_side}-front-thigh"
        result["frontLapToFrontThigh"]["combinations"][key] = {
            "frontLapPieceIds": sorted(lap_ids[lap_side]),
            "sampledBodyTriangleCount": len(zone_samples),
            "sampledBodyTriangleIdsSha256": hashlib.sha256(
                ",".join(map(str, triangle_ids)).encode("ascii")
            ).hexdigest(),
            "hitBodyTriangleCountWithinMaximumRayM": len(hits),
            "hitBodyTriangleIdsSha256": hashlib.sha256(
                ",".join(map(str, hit_ids)).encode("ascii")
            ).hexdigest(),
            "nearestGarmentFaces": [
                {"bodyTriangleId": hit[0], "gapM": hit[1] + 0.0005, **hit[2]}
                for hit in sorted(hits, key=lambda item: item[1])[:20]
            ],
            "gapM": (
                {
                    "minimum": distances[0],
                    "median": distances[len(distances) // 2],
                    "p95": distances[
                        min(len(distances) - 1, int((len(distances) - 1) * 0.95))
                    ],
                    "maximum": distances[-1],
                }
                if distances
                else None
            ),
            "withinNearDistanceDiagnosticCount": near_count,
            "nearDistanceFractionDiagnosticOnly": (
                near_count / len(zone_samples) if zone_samples else None
            ),
            "originOffsetSensitivity": {
                "offsetM": sensitivity_offset,
                "hitBodyTriangleCountWithinMaximumRayM": sensitivity_hits,
                "withinNearDistanceDiagnosticCount": sensitivity_near,
                "boundary": "Offset sensitivity only; compare with the primary 0.5 mm ray and do not interpret either as a fit or acceptance threshold.",
            },
            "maximumRayM": 0.25,
            "originOffsetM": 0.0005,
        }
    union_samples = front_thigh_samples["left"] + front_thigh_samples["right"]
    union_tree, _union_face_count, union_owners = layers["front-lap-union"]
    union_hits = []
    for body_triangle, center, normal, longitudinal in union_samples:
        location, _hit_normal, face_index, distance = union_tree.ray_cast(
            center + normal * 0.0005, normal, 0.25
        )
        if location is not None and distance is not None and distance >= 0:
            union_hits.append((body_triangle, float(distance), union_owners[face_index]))
    unique_triangle_ids = sorted({item[0] for item in union_samples})
    unique_hit_ids = sorted({item[0] for item in union_hits})
    result["frontLapToFrontThigh"]["unionNoDoubleCount"] = {
        "sampledUniqueBodyTriangleCount": len(unique_triangle_ids),
        "hitUniqueBodyTriangleCount": len(unique_hit_ids),
        "hitUnionFraction": (
            len(unique_hit_ids) / len(unique_triangle_ids)
            if unique_triangle_ids
            else None
        ),
        "sampledUniqueBodyTriangleIdsSha256": hashlib.sha256(
            ",".join(map(str, unique_triangle_ids)).encode("ascii")
        ).hexdigest(),
        "hitUniqueBodyTriangleIdsSha256": hashlib.sha256(
            ",".join(map(str, unique_hit_ids)).encode("ascii")
        ).hexdigest(),
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--component-id-dir")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    job = read_json(repo_path(args.job))
    construction_path = job["garmentPipeline"]["constructionPath"]
    construction = read_json(repo_path(construction_path))
    components = construction.get("requiredPatternComponents", [])
    shorts_components = [
        item for item in components if item.get("componentId") == "fitted-under-shorts"
    ]
    cloth = construction.get("clothSimulation", {})
    groups = cloth.get("prototypePanelGroups", {})
    skirt_ids = set(groups.get("pleated-overskirt", []))
    front_follow_ids = set(groups.get("pleated-overskirt-front-follow", []))
    skirt_group_ids = ["pleated-overskirt"] + (
        ["pleated-overskirt-front-follow"] if front_follow_ids else []
    )
    coverage_component = (
        "front-articulated-coverage"
        if "front-articulated-coverage" in groups
        else None
    )
    coverage_ids = set(groups.get(coverage_component, [])) if coverage_component else set()
    skirt_ids.update(coverage_ids)
    skirt_ids.update(front_follow_ids)
    front_lap_diagnostic = cloth.get("prototypePoseCoverageDiagnostic")
    if not isinstance(front_lap_diagnostic, dict):
        raise ValueError("pose coverage requires an explicit prototypePoseCoverageDiagnostic contract")
    front_lap_ids = front_lap_diagnostic.get("frontLapPieceIdsBySide", {})
    if any(not front_lap_ids.get(side) for side in ("left", "right")):
        raise ValueError("front-lap diagnostic requires explicit left and right panel IDs")
    longitudinal_range = front_lap_diagnostic.get("longitudinalBoneRange", [])
    if (
        len(longitudinal_range) != 2
        or not 0 <= longitudinal_range[0] < longitudinal_range[1] <= 1
    ):
        raise ValueError("front-lap diagnostic requires an ordered rest-bone interval")
    for side in ("left", "right"):
        if not set(front_lap_ids[side]) <= skirt_ids:
            raise ValueError(f"{side} front-lap pieces are not all in the configured overskirt group")
    if (
        len(shorts_components) != 1
        or not shorts_components[0].get("requiredPieceIds")
        or not skirt_ids
    ):
        raise ValueError(
            "pose coverage requires canonical fitted-under-shorts and pleated-overskirt piece groups"
        )
    shorts_ids = set(shorts_components[0]["requiredPieceIds"])
    assembly_pose = read_json(
        repo_path(job["garmentPipeline"]["assemblyPosePath"])
    )
    thigh_shell = assembly_pose.get("thighSurfaceShell", {})
    thigh_shell_piece_ids = thigh_shell.get("pieceIds", {})
    if thigh_shell_piece_ids:
        shell_piece_ids = set(thigh_shell_piece_ids.values())
        if len(shell_piece_ids) != len(thigh_shell_piece_ids) or not all(
            isinstance(piece_id, str) and piece_id for piece_id in shell_piece_ids
        ):
            raise ValueError("thigh surface shell piece IDs must be unique non-empty strings")
        shorts_ids.update(shell_piece_ids)
    piece_group_source = {
        "constructionPath": construction_path,
        "constructionSha256": digest(repo_path(construction_path)),
        "shortsComponentId": "fitted-under-shorts",
        "shortsPieceIds": sorted(shorts_ids),
        "thighSurfaceShellPieceIds": sorted(thigh_shell_piece_ids.values()),
        "assemblyPoseSha256": digest(
            repo_path(job["garmentPipeline"]["assemblyPosePath"])
        ),
        "skirtPanelGroupIds": skirt_group_ids,
        "skirtPieceIds": sorted(skirt_ids),
        "frontLapPoseCoverageDiagnostic": front_lap_diagnostic,
        "separatelySimulatedCoverageComponentId": coverage_component,
        "separatelySimulatedCoveragePieceIds": sorted(coverage_ids),
    }
    runtime = ROOT / ".image2outfit/products" / job["id"]
    skin = read_json(runtime / "skin/skin-export-report.json")
    source = repo_path(skin["weightedBlendPath"])
    if digest(source) != skin["weightedBlendSha256"]:
        raise ValueError("weighted render source is stale")
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise ValueError("render requires one target armature")
    armature = armatures[0]
    # Cloth cache prototypes can save their collider pose sweep on this armature.
    # These product renders are explicit pose snapshots; a retained action would
    # override set_pose() and make every requested pose render at the cached pose.
    armature.animation_data_clear()
    required = {
        "Hips",
        "UpperArm_L",
        "UpperArm_R",
        "LowerArm_L",
        "LowerArm_R",
        "UpperLeg_L",
        "UpperLeg_R",
        "LowerLeg_L",
        "LowerLeg_R",
    }
    if not required <= set(armature.pose.bones.keys()):
        raise ValueError("required pose bones are absent")
    body_objects = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and obj.get("prototypeRole") == "target-avatar-reference-only"
    ]
    if len(body_objects) != 1:
        raise ValueError(
            "pose coverage requires exactly one explicit target avatar mesh"
        )
    body = body_objects[0]
    floor, camera = pastel_studio()
    configure_render(1024)
    bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    floor.hide_render = True
    views = {
        "front": (0, -1, 0),
        "back": (0, 1, 0),
        "left": (1, 0, 0),
        "right": (-1, 0, 0),
        "three-quarter": (0.7, -0.7, 0),
    }
    records = []
    component_id_records = []
    for kind, outputs in (("view", job["previewPaths"]), ("pose", job["posePaths"])):
        for name, value in outputs.items():
            reset_pose(armature)
            pose_measurements = {}
            if kind == "pose":
                if name == "prone":
                    armature.pose.bones["Hips"].rotation_euler.x = math.pi / 2
                    bpy.context.view_layer.update()
                elif name == "arms-up":
                    pose_measurements = raise_arms_world_up(armature)
                elif name in {"neutral", "arm-cross", "crouch", "sit"}:
                    set_pose(armature, name)
                else:
                    raise ValueError(f"unknown render pose: {name}")
            deps = bpy.context.evaluated_depsgraph_get()
            pose_coverage = (
                measure_pose_coverage(
                    body,
                    bpy.context.scene.objects,
                    deps,
                    armature,
                    shorts_ids,
                    skirt_ids,
                    piece_group_source,
                    front_lap_diagnostic,
                )
                if kind == "pose" and name in {"neutral", "crouch", "sit"}
                else None
            )
            if pose_coverage is not None:
                pose_coverage["sharedSeamContinuity"] = (
                    measure_shared_seam_pose_continuity(
                        bpy.context.scene.objects,
                        deps,
                        set(groups) | {job["id"] + "-static"},
                    )
                )
            points = [
                obj.evaluated_get(deps).matrix_world @ Vector(corner)
                for obj in bpy.context.scene.objects
                if obj.type == "MESH" and obj != floor
                for corner in obj.evaluated_get(deps).bound_box
            ]
            lower = Vector(tuple(min(p[a] for p in points) for a in range(3)))
            upper = Vector(tuple(max(p[a] for p in points) for a in range(3)))
            centre = (lower + upper) / 2
            span = (upper - lower).length
            camera.data.ortho_scale = span * 1.12
            direction = Vector(views[name] if kind == "view" else (0.7, -0.7, 0.12))
            point_camera(camera, tuple(centre + direction * 3), tuple(centre))
            output = repo_path(value)
            output.parent.mkdir(parents=True, exist_ok=True)
            bpy.context.scene.render.filepath = str(output)
            bpy.ops.render.render(write_still=True)
            if args.component_id_dir and kind == "pose" and name in {"crouch", "sit"}:
                component_dir = Path(args.component_id_dir)
                if not component_dir.is_absolute():
                    component_dir = ROOT / component_dir
                component_output = component_dir / f"{name}.png"
                component_output.parent.mkdir(parents=True, exist_ok=True)
                component_record = render_component_id(
                    bpy.context.scene.objects,
                    bpy.context.scene,
                    component_output,
                    digest(source),
                )
                component_record.update({"kind": "pose", "name": name})
                component_id_records.append(component_record)
            records.append(
                {
                    "kind": kind,
                    "name": name,
                    "path": value,
                    "sha256": digest(output),
                    "poseMeasurements": pose_measurements,
                    "poseCoverageDiagnostic": pose_coverage,
                    "boneRotationsQuaternion": {
                        b.name: list(b.rotation_quaternion)
                        for b in armature.pose.bones
                        if b.rotation_mode == "QUATERNION"
                    },
                    "boneRotationsRadians": {
                        b.name: list(b.rotation_euler)
                        for b in armature.pose.bones
                        if any(abs(x) > 1e-9 for x in b.rotation_euler)
                    },
                }
            )
    render_report = {
        "schemaVersion": 1,
        "productId": job["id"],
        "sourcePath": skin["weightedBlendPath"],
        "sourceSha256": digest(source),
        "blenderVersion": bpy.app.version_string,
        "engine": bpy.context.scene.render.engine,
        "records": records,
        "componentIdDiagnostics": component_id_records,
        "qualityDecision": "UNVERIFIED",
        "grantsVisualAcceptance": False,
        "evidenceBoundary": "Actual neutral prototype and diagnostic bone poses; no fit, runtime, or appearance acceptance.",
    }
    write_json(runtime / "reports/weighted-render.json", render_report)
    coverage_evidence = {
        "schemaVersion": 1,
        "productId": job["id"],
        "method": "same-pose-body-surface-ray-coverage-v1",
        "source": {
            "weightedBlendPath": skin["weightedBlendPath"],
            "weightedBlendSha256": digest(source),
            "targetAvatarSha256": skin["targetSourceSha256"],
        },
        "poses": {
            record["name"]: {
                "renderPath": record["path"],
                "renderSha256": record["sha256"],
                "boneRotationsRadians": record["boneRotationsRadians"],
                "measurement": record["poseCoverageDiagnostic"],
            }
            for record in records
            if record["kind"] == "pose" and record["poseCoverageDiagnostic"] is not None
        },
        "qualityDecision": "UNVERIFIED",
        "grantsFitAcceptance": False,
        "grantsVisualAcceptance": False,
        "evidenceBoundary": "Pose-matched avatar triangle samples are ray-projected along their evaluated surface normals onto canonical shorts and overskirt faces. This geometric coverage diagnostic does not measure pressure, material stretch, collision response, Shape Keys, visual quality, or VRChat runtime fit and cannot pass a quality gate.",
    }
    write_json(
        repo_path(job["productRoot"] + "/Evidence/Build/pose-coverage-diagnostic.json"),
        coverage_evidence,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
