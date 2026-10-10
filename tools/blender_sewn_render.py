"""Render the actual weighted prototype and imported target for direct review."""
import argparse
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
from genworks_product_common import pastel_studio, point_camera, configure_render, reset_pose, set_pose


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
        evidence[name] = {"headWorldM": list(head), "tailWorldM": list(tail),
                          "directionWorld": list(direction), "pointsUp": True}
    return evidence


def _piece_surface_tree(objects, depsgraph, piece_ids):
    """Build a posed-world BVH from only faces owned by the requested panels."""
    vertices = []
    polygons = []
    included_faces = 0
    for obj in objects:
        if obj.type != "MESH" or obj.get("prototypeRole") != "weighted-unfit-sewn-prototype":
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
            offset = len(vertices)
            vertices.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
            for polygon, owner in zip(mesh.polygons, ownership.data):
                if owner.value < 0 or owner.value >= len(pieces):
                    raise ValueError(f"Invalid sewn face owner on {obj.name}")
                if pieces[owner.value] not in piece_ids:
                    continue
                polygons.append(tuple(offset + index for index in polygon.vertices))
                included_faces += 1
        finally:
            evaluated.to_mesh_clear()
    if not polygons:
        raise ValueError(f"No evaluated faces found for canonical pieces: {sorted(piece_ids)}")
    return BVHTree.FromPolygons(vertices, polygons, all_triangles=True), included_faces


def _body_surface_samples(body, depsgraph, armature):
    """Sample body triangles and classify by deformation weights, never world Z."""
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        group_names = {group.index: group.name for group in body.vertex_groups}
        weights = []
        for vertex in body.data.vertices:
            weights.append({
                group_names[item.group]: float(item.weight)
                for item in vertex.groups
                if item.group in group_names
            })
        normal_matrix = evaluated.matrix_world.to_3x3().inverted().transposed()
        pose_samples = {"pelvis-posterior": [], "upper-thigh-left": [], "upper-thigh-right": []}
        for triangle in mesh.loop_triangles:
            ids = triangle.vertices
            if any(index >= len(body.data.vertices) for index in ids):
                raise ValueError("Evaluated avatar surface changed vertex correspondence")
            world = [evaluated.matrix_world @ mesh.vertices[index].co for index in ids]
            center = (world[0] + world[1] + world[2]) / 3.0
            normal = (normal_matrix @ triangle.normal).normalized()
            averaged = {
                name: sum(weights[index].get(name, 0.0) for index in ids) / 3.0
                for name in ("Hips", "UpperLeg_L", "UpperLeg_R")
            }
            if averaged["Hips"] >= 0.5 and normal.y >= 0.15:
                pose_samples["pelvis-posterior"].append((int(triangle.index), center, normal))
            if averaged["UpperLeg_L"] >= 0.55:
                pose_samples["upper-thigh-left"].append((int(triangle.index), center, normal))
            if averaged["UpperLeg_R"] >= 0.55:
                pose_samples["upper-thigh-right"].append((int(triangle.index), center, normal))
        return pose_samples
    finally:
        evaluated.to_mesh_clear()


def measure_pose_coverage(body, objects, depsgraph, armature):
    """Measure matched-pose body surface hits against shorts and skirt surfaces."""
    shorts_ids = {
        "shorts-front-left", "shorts-front-right", "shorts-back-left", "shorts-back-right"
    }
    skirt_ids = {"overskirt-front", "overskirt-back"}
    samples = _body_surface_samples(body, depsgraph, armature)
    layers = {
        "under-shorts": _piece_surface_tree(objects, depsgraph, shorts_ids),
        "overskirt": _piece_surface_tree(objects, depsgraph, skirt_ids),
    }
    body.data.calc_loop_triangles()
    result = {"surfaceCoordinateMethod": "posed-avatar-triangle-centroids; deformation-weight anatomical zones; outward-normal ray into matching-pose canonical garment faces",
              "bodySurfaceTriangleCount": len(body.data.loop_triangles),
              "zoneSelection": {"pelvisPosterior": "mean Hips vertex-group weight >= 0.50 and posed surface normal world-Y >= 0.15", "leftThigh": "mean UpperLeg_L vertex-group weight >= 0.55", "rightThigh": "mean UpperLeg_R vertex-group weight >= 0.55"},
              "ray": {"originOffsetM": 0.0005, "maximumDistanceM": 0.25, "direction": "posed avatar surface normal"},
              "layers": {name: {"canonicalPieceIds": sorted(shorts_ids if name == "under-shorts" else skirt_ids),
                                "evaluatedGarmentFaceCount": face_count}
                         for name, (_tree, face_count) in layers.items()},
              "zones": {}}
    for zone, zone_samples in samples.items():
        result["zones"][zone] = {"sampleCount": len(zone_samples), "layers": {}}
        sample_ids_sha = hashlib.sha256(
            ",".join(str(triangle) for triangle, _center, _normal in zone_samples).encode("ascii")
        ).hexdigest()
        for layer_name, (tree, _face_count) in layers.items():
            hits = []
            for body_triangle, center, normal in zone_samples:
                location, _hit_normal, _face_index, distance = tree.ray_cast(
                    center + normal * 0.0005, normal, 0.25
                )
                if location is not None and distance is not None and distance >= 0:
                    hits.append((body_triangle, float(distance)))
            distances = sorted(distance for _triangle, distance in hits)
            result["zones"][zone]["layers"][layer_name] = {
                "coveredSampleCount": len(hits),
                "coverageFraction": (len(hits) / len(zone_samples)) if zone_samples else None,
                "surfaceGapM": ({
                    "minimum": distances[0],
                    "median": distances[len(distances) // 2],
                    "p95": distances[min(len(distances) - 1, int((len(distances) - 1) * 0.95))],
                    "maximum": distances[-1],
                } if distances else None),
                "sampleTriangleIdsSha256": sample_ids_sha,
                "coveredTriangleIdsSha256": hashlib.sha256(
                    ",".join(str(triangle) for triangle, _distance in hits).encode("ascii")
                ).hexdigest(),
            }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    job = read_json(repo_path(args.job))
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
    required = {"Hips", "UpperArm_L", "UpperArm_R", "LowerArm_L", "LowerArm_R",
                "UpperLeg_L", "UpperLeg_R", "LowerLeg_L", "LowerLeg_R"}
    if not required <= set(armature.pose.bones.keys()):
        raise ValueError("required pose bones are absent")
    body_objects = [obj for obj in bpy.context.scene.objects
                    if obj.type == "MESH" and obj.get("prototypeRole") == "target-avatar-reference-only"]
    if len(body_objects) != 1:
        raise ValueError("pose coverage requires exactly one explicit target avatar mesh")
    body = body_objects[0]
    floor, camera = pastel_studio()
    configure_render(1024)
    bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    floor.hide_render = True
    views = {"front": (0, -1, 0), "back": (0, 1, 0), "left": (1, 0, 0),
             "right": (-1, 0, 0), "three-quarter": (0.7, -0.7, 0)}
    records = []
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
            pose_coverage = (measure_pose_coverage(body, bpy.context.scene.objects, deps, armature)
                             if kind == "pose" and name in {"neutral", "crouch", "sit"} else None)
            points = [obj.evaluated_get(deps).matrix_world @ Vector(corner)
                      for obj in bpy.context.scene.objects if obj.type == "MESH" and obj != floor
                      for corner in obj.evaluated_get(deps).bound_box]
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
            records.append({"kind": kind, "name": name, "path": value, "sha256": digest(output),
                            "poseMeasurements": pose_measurements,
                            "poseCoverageDiagnostic": pose_coverage,
                            "boneRotationsQuaternion": {b.name: list(b.rotation_quaternion)
                                                        for b in armature.pose.bones if b.rotation_mode == "QUATERNION"},
                            "boneRotationsRadians": {b.name: list(b.rotation_euler) for b in armature.pose.bones
                                                     if any(abs(x) > 1e-9 for x in b.rotation_euler)}})
    render_report = {
        "schemaVersion": 1, "productId": job["id"], "sourcePath": skin["weightedBlendPath"],
        "sourceSha256": digest(source), "blenderVersion": bpy.app.version_string,
        "engine": bpy.context.scene.render.engine, "records": records,
        "qualityDecision": "UNVERIFIED", "grantsVisualAcceptance": False,
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
    write_json(repo_path(job["productRoot"] + "/Evidence/Build/pose-coverage-diagnostic.json"), coverage_evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
