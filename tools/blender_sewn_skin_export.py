"""Transfer measured body weights to a sewn prototype; export no body geometry."""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
from blender_cloth_simulation import export_settled_fbx, mesh_hash, read_json, repo_path, write_json
from image2outfit.weight_transfer import constrain_vertex_weights


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _smoothstep(value):
    value = max(0.0, min(1.0, float(value)))
    return value * value * (3.0 - 2.0 * value)


def _interior_taper(obj, profile):
    experiment = profile.get("interiorThighBoostExperiment")
    if experiment is None:
        return None
    piece_ids = json.loads(obj.get("canonicalPieceIds", "[]"))
    if not piece_ids:
        raise ValueError("Interior weight experiment requires canonical piece IDs")
    piece_attribute = obj.data.attributes.get("canonical_piece_index")
    sewn_attribute = obj.data.attributes.get("canonical_sewn_vertex_index")
    if piece_attribute is None or sewn_attribute is None:
        raise ValueError("Interior weight experiment requires canonical face and sewn vertex IDs")
    if piece_attribute.domain != "FACE" or piece_attribute.data_type != "INT":
        raise ValueError("canonical_piece_index must be an integer face attribute")
    if sewn_attribute.domain != "POINT" or sewn_attribute.data_type != "INT":
        raise ValueError("canonical_sewn_vertex_index must be an integer point attribute")
    target_id = experiment["pieceId"]
    neighbor_ids = set(experiment["neighborPieceIds"])
    if target_id not in piece_ids or not neighbor_ids.issubset(set(piece_ids)):
        raise ValueError("Interior weight experiment references an unknown sewn piece")

    vertices_by_piece = {piece_id: set() for piece_id in piece_ids}
    for face, owner in zip(obj.data.polygons, piece_attribute.data):
        vertices_by_piece[piece_ids[owner.value]].update(face.vertices)
    target_vertices = vertices_by_piece[target_id]
    sewn_ids_by_piece = {
        piece_id: {
            int(sewn_attribute.data[index].value)
            for index in indices
            if int(sewn_attribute.data[index].value) >= 0
        }
        for piece_id, indices in vertices_by_piece.items()
    }
    shared_sewn_ids = set().union(*(
        sewn_ids_by_piece[target_id] & sewn_ids_by_piece[neighbor]
        for neighbor in neighbor_ids
    ))
    boundary_vertices = {
        index for index in target_vertices
        if int(sewn_attribute.data[index].value) in shared_sewn_ids
    }
    interior_vertices = target_vertices - boundary_vertices
    if (len(boundary_vertices) != experiment["expectedBoundaryVertexCount"]
            or len(interior_vertices) != experiment["expectedInteriorVertexCount"]):
        raise ValueError(
            "Interior weight experiment topology changed: "
            f"boundary={len(boundary_vertices)} interior={len(interior_vertices)}"
        )
    adjacency = {index: set() for index in target_vertices}
    for edge in obj.data.edges:
        first, second = edge.vertices
        if first in target_vertices and second in target_vertices:
            adjacency[first].add(second)
            adjacency[second].add(first)
    rings = {index: 0 for index in boundary_vertices}
    queue = deque(sorted(boundary_vertices))
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor not in rings:
                rings[neighbor] = rings[current] + 1
                queue.append(neighbor)
    if set(rings) != target_vertices:
        raise ValueError("Interior weight experiment found disconnected wrap vertices")
    taper_rings = int(experiment["taperEdgeRings"])
    factors = {
        index: _smoothstep(min(1.0, rings[index] / taper_rings))
        for index in target_vertices
    }
    return {
        "targetPieceId": target_id,
        "targetVertices": target_vertices,
        "boundaryVertices": boundary_vertices,
        "interiorVertices": interior_vertices,
        "ringDistance": rings,
        "fadeFactor": factors,
        "config": experiment,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    job = read_json(repo_path(args.job))
    cloth = read_json(repo_path(job["productRoot"] + "/Evidence/Build/cloth-simulation.json"))
    candidate = repo_path(cloth["candidatePath"])
    if digest(candidate) != cloth["candidateSha256"]:
        raise ValueError("cloth candidate is stale")
    manufacturing_blend = job.get("manufacturingBlendPath", job["blendPath"])
    if digest(repo_path(manufacturing_blend)) != cloth["sourceBlendSha256"]:
        raise ValueError("cloth source binding is stale")
    bpy.ops.wm.open_mainfile(filepath=str(candidate), load_ui=False)
    if len(cloth["collisionObjects"]) != 1:
        raise ValueError("weight transfer requires one explicit target body")
    body = bpy.data.objects[cloth["collisionObjects"][0]]
    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if len(armatures) != 1:
        raise ValueError("weight transfer requires one imported target armature")
    armature = armatures[0]
    bones = {b.name for b in armature.data.bones if b.use_deform}
    body.data.calc_loop_triangles()
    triangles = [tuple(t.vertices) for t in body.data.loop_triangles]
    coordinates = [body.matrix_world @ v.co for v in body.data.vertices]
    tree = BVHTree.FromPolygons(coordinates, triangles, all_triangles=True)
    body_weights = [{body.vertex_groups[g.group].name: g.weight for g in v.groups
                    if body.vertex_groups[g.group].name in bones} for v in body.data.vertices]
    construction = read_json(repo_path(job["garmentPipeline"]["constructionPath"]))
    regions = construction.get("prototypeWeightRegions", [])
    region_trees = []
    profiles_by_piece = {}
    for region in regions:
        low, high = region["bodyTriangleZM"]
        if not 0 <= low < high or not region["pieceIds"]:
            raise ValueError("Invalid explicit body weight region")
        profiles = region.get("weightProfiles")
        if profiles is None:
            profile = region.get("weightProfile")
            profiles = [profile] if profile is not None else []
        if not isinstance(profiles, list):
            raise ValueError("Explicit prototype weight profiles must be a list")
        for profile in profiles:
            profile_piece_ids = set(profile["pieceIds"])
            if (profile["method"] != "hip-anchored-lateral-thigh-fade-v1"
                    or not profile_piece_ids
                    or not profile_piece_ids.issubset(set(region["pieceIds"]))
                    or not 0 <= profile["waistThighWeight"] <= profile["hemThighWeight"] <= 1
                    or profile["centerlineHalfWidthM"] < 0
                    or profile["fullSideWeightWidthM"] <= profile["centerlineHalfWidthM"]):
                raise ValueError("Invalid explicit prototype weight profile")
            for bone_name in (profile["hipBone"], profile["leftThighBone"], profile["rightThighBone"]):
                if bone_name not in bones:
                    raise ValueError(f"Prototype weight profile bone is missing or non-deform: {bone_name}")
            if profile["leftThighBone"] == profile["rightThighBone"]:
                raise ValueError("Prototype weight profile requires distinct left and right thigh bones")
            experiment = profile.get("interiorThighBoostExperiment")
            if experiment is not None:
                if (experiment.get("method") != "sewn-boundary-geodesic-fade-v1"
                        or experiment.get("pieceId") not in profile_piece_ids
                        or not experiment.get("neighborPieceIds")
                        or experiment["pieceId"] in experiment["neighborPieceIds"]
                        or not set(experiment["neighborPieceIds"]).issubset(profile_piece_ids)
                        or not 0 < experiment["boostWeight"] <= 0.25
                        or not 0 <= experiment["maximumThighWeight"] <= 0.65
                        or experiment["taperEdgeRings"] < 1
                        or experiment["expectedBoundaryVertexCount"] < 1
                        or experiment["expectedInteriorVertexCount"] < 1):
                    raise ValueError("Invalid sewn-boundary-preserving thigh-weight experiment")
            for piece_id in profile_piece_ids:
                if piece_id in profiles_by_piece:
                    raise ValueError(f"Conflicting prototype weight profiles for piece {piece_id}")
                profiles_by_piece[piece_id] = profile
        selected = [i for i, triangle in enumerate(triangles)
                    if all(low <= coordinates[v].z <= high for v in triangle)
                    and not any(name.startswith(tuple(region["excludedBoneNamePrefixes"]))
                                for v in triangle for name, w in body_weights[v].items() if w > 1e-6)]
        if not selected:
            raise ValueError("Body weight region contains no eligible triangles")
        region_trees.append((region, selected, BVHTree.FromPolygons(
            coordinates, [triangles[i] for i in selected], all_triangles=True)))
    objects = [o for o in bpy.context.scene.objects if o.type == "MESH"
               and o.get("prototypeRole") != "target-avatar-reference-only"]
    if not objects:
        raise ValueError("cloth candidate contains no garment meshes")
    audits, distances, region_records, profile_audits = {}, [], [], {}
    trim_objects = [obj for obj in objects if obj.get("prototypeRole") == "unfitted-prototype-edge-trim"]
    garment_objects = [obj for obj in objects if obj not in trim_objects]
    for obj in garment_objects:
        pieces = json.loads(obj["canonicalPieceIds"])
        attribute = obj.data.attributes.get("canonical_piece_index")
        if attribute is None:
            raise ValueError("Cloth candidate lost canonical face ownership")
        owners = [set() for _ in obj.data.vertices]
        for face, owner in zip(obj.data.polygons, attribute.data):
            for index in face.vertices:
                owners[index].add(pieces[owner.value])
        object_coordinates = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        profile_bounds = {}
        profile_centers = {}
        profile_accumulators = {}
        active_profiles = {id(profile): profile for piece_id, profile in profiles_by_piece.items()
                           if any(piece_id in owner_set for owner_set in owners)}
        interior_tapers = {
            profile_key: _interior_taper(obj, profile)
            for profile_key, profile in active_profiles.items()
            if profile.get("interiorThighBoostExperiment") is not None
        }
        for profile_key, profile in active_profiles.items():
            profile_piece_ids = set(profile["pieceIds"])
            selected_vertices = [index for index, owner_set in enumerate(owners)
                                 if owner_set.intersection(profile_piece_ids)]
            if not selected_vertices:
                raise ValueError(f"Weight profile selected no vertices on {obj.name}")
            heights = [object_coordinates[index].z for index in selected_vertices]
            low, high = min(heights), max(heights)
            if not math.isfinite(low) or not math.isfinite(high) or high <= low:
                raise ValueError(f"Weight profile has a collapsed vertical range on {obj.name}")
            left_x = (armature.matrix_world @ armature.data.bones[profile["leftThighBone"]].head_local).x
            right_x = (armature.matrix_world @ armature.data.bones[profile["rightThighBone"]].head_local).x
            if not math.isfinite(left_x) or not math.isfinite(right_x) or abs(left_x-right_x) <= 1e-6:
                raise ValueError(f"Weight profile cannot establish avatar left/right axis on {obj.name}")
            profile_bounds[profile_key] = (low, high)
            profile_centers[profile_key] = ((left_x + right_x) / 2.0, left_x > right_x)
            profile_accumulators[profile_key] = {
                "profile": profile,
                "vertexCount": 0,
                "thighWeights": [],
                "centerlineVertexCount": 0,
                "leftSideVertexCount": 0,
                "rightSideVertexCount": 0,
                "interiorBoostRecords": [],
            }
        raw = {}
        for vertex in obj.data.vertices:
            point = object_coordinates[vertex.index]
            nearest, normal, triangle_id, distance = tree.find_nearest(point)
            matching = [(region, ids, regional_tree) for region, ids, regional_tree in region_trees
                        if owners[vertex.index].intersection(region["pieceIds"])]
            if len(matching) > 1:
                raise ValueError("Vertex has conflicting explicit weight regions")
            if matching:
                region, regional_ids, regional_tree = matching[0]
                unbounded_id = triangle_id
                nearest, normal, regional_id, distance = regional_tree.find_nearest(point)
                if regional_id is None:
                    raise ValueError("Regional body lookup failed")
                triangle_id = regional_ids[regional_id]
                region_records.append({"object": obj.name, "vertexIndex": vertex.index,
                    "pieceIds": sorted(owners[vertex.index]), "bodyTriangleZM": region["bodyTriangleZM"],
                    "unboundedTriangleId": unbounded_id, "selectedTriangleId": triangle_id,
                    "unboundedArmInfluence": any(name.startswith(tuple(region["excludedBoneNamePrefixes"]))
                        for v in triangles[unbounded_id] for name, w in body_weights[v].items() if w > 1e-6),
                    "distanceM": distance})
            if triangle_id is None:
                raise ValueError("body surface lookup failed")
            ids = triangles[triangle_id]
            a, b, c = [coordinates[i] for i in ids]
            bary = barycentric_transform(nearest, a, b, c,
                                         Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
            if min(bary) < -1e-4:
                raise ValueError("closest body point is outside its triangle")
            combined = {}
            for index, coefficient in zip(ids, bary):
                for bone, weight in body_weights[index].items():
                    combined[bone] = combined.get(bone, 0) + max(0, coefficient) * weight
            matching_profiles = [(key, profile) for key, profile in active_profiles.items()
                                 if owners[vertex.index].intersection(profile["pieceIds"])]
            if len(matching_profiles) > 1:
                raise ValueError(f"Conflicting prototype weight profiles at {obj.name}:{vertex.index}")
            if matching_profiles:
                profile_key, profile = matching_profiles[0]
                low, high = profile_bounds[profile_key]
                center_x, left_is_positive_x = profile_centers[profile_key]
                height_fraction = min(1.0, max(0.0, (point.z-low)/(high-low)))
                hem_fraction = 1.0-height_fraction
                base_thigh = (profile["waistThighWeight"]
                              + (profile["hemThighWeight"]-profile["waistThighWeight"])*hem_fraction)
                lateral = abs(point.x-center_x)
                lateral_fraction = ((lateral-profile["centerlineHalfWidthM"])
                                    / (profile["fullSideWeightWidthM"]-profile["centerlineHalfWidthM"]))
                thigh_weight = base_thigh * _smoothstep(lateral_fraction)
                if point.x > center_x:
                    thigh_bone = profile["leftThighBone"] if left_is_positive_x else profile["rightThighBone"]
                    profile_accumulators[profile_key]["leftSideVertexCount"] += int(left_is_positive_x)
                    profile_accumulators[profile_key]["rightSideVertexCount"] += int(not left_is_positive_x)
                elif point.x < center_x:
                    thigh_bone = profile["rightThighBone"] if left_is_positive_x else profile["leftThighBone"]
                    profile_accumulators[profile_key]["rightSideVertexCount"] += int(left_is_positive_x)
                    profile_accumulators[profile_key]["leftSideVertexCount"] += int(not left_is_positive_x)
                else:
                    thigh_bone = profile["hipBone"]
                    profile_accumulators[profile_key]["centerlineVertexCount"] += 1
                taper = interior_tapers.get(profile_key)
                if (taper is not None
                        and vertex.index in taper["targetVertices"]):
                    baseline_thigh_weight = thigh_weight
                    boost = (taper["config"]["boostWeight"]
                             * taper["fadeFactor"][vertex.index])
                    thigh_weight = min(
                        taper["config"]["maximumThighWeight"],
                        thigh_weight + boost,
                    )
                    profile_accumulators[profile_key]["interiorBoostRecords"].append({
                        "vertexIndex": vertex.index,
                        "isSharedBoundary": vertex.index in taper["boundaryVertices"],
                        "ringDistance": taper["ringDistance"][vertex.index],
                        "fadeFactor": taper["fadeFactor"][vertex.index],
                        "baselineThighWeight": baseline_thigh_weight,
                        "candidateThighWeight": thigh_weight,
                    })
                if thigh_weight > 0:
                    raw[vertex.index] = [(profile["hipBone"], 1.0-thigh_weight), (thigh_bone, thigh_weight)]
                else:
                    raw[vertex.index] = [(profile["hipBone"], 1.0)]
                profile_accumulators[profile_key]["vertexCount"] += 1
                profile_accumulators[profile_key]["thighWeights"].append(thigh_weight)
            else:
                raw[vertex.index] = list(combined.items())
            distances.append(float(distance))
        constrained = constrain_vertex_weights(raw, deform_bones=bones)
        if constrained.audit.zero_weight_vertices:
            raise ValueError(f"unweighted target vertices in {obj.name}")
        for group in list(obj.vertex_groups):
            obj.vertex_groups.remove(group)
        groups = {bone: obj.vertex_groups.new(name=bone) for bone in bones}
        for index, influences in constrained.weights.items():
            for influence in influences:
                groups[influence.bone].add([index], influence.weight, "REPLACE")
        modifier = obj.modifiers.new("Target Avatar Deform", "ARMATURE")
        modifier.object = armature
        obj["prototypeRole"] = "weighted-unfit-sewn-prototype"
        audits[obj.name] = constrained.audit.to_dict()
        if profile_accumulators:
            profile_audits[obj.name] = [
                {
                    "method": accumulator["profile"]["method"],
                    "pieceIds": accumulator["profile"]["pieceIds"],
                    "measuredMeshZRangeM": list(profile_bounds[key]),
                    "centerlineHalfWidthM": accumulator["profile"]["centerlineHalfWidthM"],
                    "fullSideWeightWidthM": accumulator["profile"]["fullSideWeightWidthM"],
                    "waistThighWeight": accumulator["profile"]["waistThighWeight"],
                    "hemThighWeight": accumulator["profile"]["hemThighWeight"],
                    "vertexCount": accumulator["vertexCount"],
                    "centerlineVertexCount": accumulator["centerlineVertexCount"],
                    "leftSideVertexCount": accumulator["leftSideVertexCount"],
                    "rightSideVertexCount": accumulator["rightSideVertexCount"],
                    "measuredThighWeight": {
                        "minimum": min(accumulator["thighWeights"]),
                        "mean": sum(accumulator["thighWeights"])/len(accumulator["thighWeights"]),
                        "maximum": max(accumulator["thighWeights"]),
                    },
                    "interiorThighBoostExperiment": (
                        {
                            **dict(interior_tapers[key]["config"]),
                            "sharedBoundaryVertexCount": len(interior_tapers[key]["boundaryVertices"]),
                            "interiorVertexCount": len(interior_tapers[key]["interiorVertices"]),
                            "changedInteriorVertexCount": sum(
                                record["candidateThighWeight"] > record["baselineThighWeight"] + 1e-12
                                for record in accumulator["interiorBoostRecords"]
                                if not record["isSharedBoundary"]
                            ),
                            "boundaryVertexCountWithExactBaselineWeight": sum(
                                record["isSharedBoundary"]
                                and record["candidateThighWeight"] == record["baselineThighWeight"]
                                for record in accumulator["interiorBoostRecords"]
                            ),
                            "baselineInteriorMeanThighWeight": (
                                sum(record["baselineThighWeight"] for record in accumulator["interiorBoostRecords"]
                                    if not record["isSharedBoundary"])
                                / len(interior_tapers[key]["interiorVertices"])
                            ),
                            "candidateInteriorMeanThighWeight": (
                                sum(record["candidateThighWeight"] for record in accumulator["interiorBoostRecords"]
                                    if not record["isSharedBoundary"])
                                / len(interior_tapers[key]["interiorVertices"])
                            ),
                            "taperRingDistance": {
                                "minimum": min(record["ringDistance"] for record in accumulator["interiorBoostRecords"]),
                                "maximum": max(record["ringDistance"] for record in accumulator["interiorBoostRecords"]),
                                "fullBoostVertexCount": sum(
                                    record["fadeFactor"] >= 1.0
                                    for record in accumulator["interiorBoostRecords"]
                                ),
                            },
                            "grantsFitAcceptance": False,
                        }
                        if key in interior_tapers else None
                    ),
                    "grantsFitAcceptance": False,
                    "evidenceBoundary": accumulator["profile"]["evidenceBoundary"],
                }
                for key, accumulator in profile_accumulators.items()
            ]
    # Bind trim to the settled garment and inherit its weights, including the
    # garment's explicit regional profile. No independent body lookup for trim.
    edge_sources = {}
    for obj in garment_objects:
        source_ids = obj.data.attributes.get("canonical_sewn_vertex_index")
        if trim_objects and source_ids is None:
            raise ValueError(f"Settled garment lost sewn vertex identity: {obj.name}")
        if source_ids is None:
            continue
        pieces = json.loads(obj["canonicalPieceIds"])
        owners = [set() for _ in obj.data.vertices]
        for face, owner in zip(obj.data.polygons, obj.data.attributes["canonical_piece_index"].data):
            for index in face.vertices:
                owners[index].add(pieces[owner.value])
        for vertex, source_id in zip(obj.data.vertices, source_ids.data):
            weights = {obj.vertex_groups[g.group].name: g.weight for g in vertex.groups
                       if obj.vertex_groups[g.group].name in bones}
            for piece in owners[vertex.index]:
                key = (source_id.value, piece)
                if key in edge_sources:
                    raise ValueError(f"Ambiguous sewn edge source: {key}")
                edge_sources[key] = (obj.matrix_world @ vertex.co, weights)
    trim_audits = {}
    for obj in trim_objects:
        bindings = json.loads(obj["prototypeTrimBindings"])
        piece = obj["prototypeTrimPieceId"]
        if len(bindings) != len(obj.data.vertices):
            raise ValueError(f"Trim binding count changed: {obj.name}")
        raw, displacements = {}, []
        inverse = obj.matrix_world.inverted()
        for vertex, binding in zip(obj.data.vertices, bindings):
            first, first_weights = edge_sources[(binding["first"], piece)]
            second, second_weights = edge_sources[(binding["second"], piece)]
            direction = second-first
            rest_direction = Vector(binding["restDirection"])
            if min(direction.length_squared, rest_direction.length_squared) <= 1e-16:
                raise ValueError(f"Collapsed trim source edge: {obj.name}")
            fraction = binding["fraction"]
            offset = rest_direction.rotation_difference(direction) @ Vector(binding["restOffset"])
            point = first.lerp(second, fraction) + offset
            displacements.append((point - obj.matrix_world @ vertex.co).length)
            vertex.co = inverse @ point
            combined = {bone: (1-fraction)*first_weights.get(bone, 0.0)
                        + fraction*second_weights.get(bone, 0.0)
                        for bone in first_weights.keys() | second_weights.keys()}
            raw[vertex.index] = list(combined.items())
        constrained = constrain_vertex_weights(raw, deform_bones=bones)
        if constrained.audit.zero_weight_vertices:
            raise ValueError(f"Trim inherited zero weights: {obj.name}")
        for group in list(obj.vertex_groups):
            obj.vertex_groups.remove(group)
        groups = {bone: obj.vertex_groups.new(name=bone) for bone in bones}
        for index, influences in constrained.weights.items():
            for influence in influences:
                groups[influence.bone].add([index], influence.weight, "REPLACE")
        modifier = obj.modifiers.new("Target Avatar Deform", "ARMATURE")
        modifier.object = armature
        obj["prototypeRole"] = "weighted-unfit-sewn-prototype"
        audits[obj.name] = constrained.audit.to_dict()
        trim_audits[obj.name] = {"method": "settled-sewn-edge-position-and-weight-interpolation",
            "vertexCount": len(bindings), "maximumSettlingDisplacementM": max(displacements),
            "meanSettlingDisplacementM": sum(displacements)/len(displacements),
            "grantsFitAcceptance": False}
    runtime = ROOT / ".image2outfit/products" / job["id"] / "skin"
    runtime.mkdir(parents=True, exist_ok=True)
    source = runtime / "weighted-prototype.blend"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(source), check_existing=False)
    fbx = repo_path(job["fbxAssetPath"])
    export_settled_fbx(fbx, armature, objects)
    write_json(runtime / "skin-export-report.json", {
        "schemaVersion": 1, "productId": job["id"], "executionStatus": "PASS",
        "qualityDecision": "UNVERIFIED", "method": "nearest-body-triangle-barycentric",
        "blenderVersion": bpy.app.version_string, "inputCandidateSha256": digest(candidate),
        "targetSourceSha256": digest(repo_path(job["targetSourcePath"])),
        "weightedBlendPath": str(source.relative_to(ROOT)).replace("\\", "/"),
        "weightedBlendSha256": digest(source), "fbxSha256": digest(fbx),
        "sourceBodyMeshHash": mesh_hash(body), "boneCount": len(bones),
        "exportedGarmentObjects": [o.name for o in objects], "bodyGeometryExported": False,
        "audits": audits, "vertexCount": sum(len(obj.data.vertices) for obj in objects), "unweightedVertices": 0,
        "prototypeTrimAttachment": trim_audits,
        "prototypeWeightProfiles": profile_audits,
        "bodyDistanceM": {"minimum": min(distances), "maximum": max(distances),
                          "mean": sum(distances) / len(distances)},
        "lateralityReview": "UNASSESSED", "grantsFitAcceptance": False,
        "prototypeWeightRegions": regions, "regionalTransferRecords": region_records,
        "constructionSha256": digest(repo_path(job["garmentPipeline"]["constructionPath"])),
        "pending": ["fit", "deformation and laterality", "Shape Keys", "appearance", "Unity Prefabs", "VRChat runtime"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
