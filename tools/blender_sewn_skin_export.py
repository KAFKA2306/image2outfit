"""Transfer measured body weights to a sewn prototype; export no body geometry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
from blender_cloth_simulation import (
    export_settled_fbx,
    mesh_hash,
    read_json,
    repo_path,
    write_json,
)
from image2outfit.weight_transfer import constrain_vertex_weights


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _smoothstep(value):
    value = max(0.0, min(1.0, float(value)))
    return value * value * (3.0 - 2.0 * value)


def apply_pose_constrained_apron_geometry(objects, armature, pose_spec):
    """Fit the sewn front apron in sit pose and invert the frozen skin map.

    This is a deterministic source-geometry solve, not a weight change: it
    projects the front skirt/lap onto height-local evaluated under-shorts in
    the declared sit pose, smooths displacement through connected front
    panels, preserves shared external seams, then maps target positions back
    through each vertex's existing linear-blend skin transform. Height-local
    queries avoid treating a remote shorts edge as support for a lower apron
    point just because the target mesh spans that height elsewhere.
    """
    spec = pose_spec.get("poseConstrainedApronGeometry")
    if spec is None:
        return {"applied": False, "reason": "not-declared"}
    if spec.get("method") != "sit-anterior-shorts-surface-inverse-skin-v3":
        raise ValueError("Unknown pose-constrained apron geometry method")
    source_piece_ids = set(spec.get("sourcePieceIds", []))
    transition_piece_ids = set(spec.get("transitionPieceIds", []))
    left_targets = set(spec.get("leftTargetPieceIds", []))
    right_targets = set(spec.get("rightTargetPieceIds", []))
    if any("front" not in piece for piece in left_targets | right_targets):
        raise ValueError("Anterior apron target surfaces must be front shorts pieces only")
    if (not source_piece_ids or not left_targets or not right_targets
            or left_targets & right_targets):
        raise ValueError("Pose-constrained apron piece ownership is incomplete")
    numeric = (
        "minimumHeightZM", "fullBlendHeightZM", "fullBlendEndHeightZM", "waistLockHeightZM",
        "clearanceM", "minimumProjectionBlend", "maximumTargetDistanceM", "maximumCorrectionM",
        "maximumPoseCorrectionM", "maximumSkinMappingErrorM",
        "maximumSurfaceResidualM", "targetSurfaceHeightBinM",
        "maximumLocalSurfaceSupportDistanceM", "smoothness", "maximumNormalTurnDot",
    )
    if not all(math.isfinite(spec.get(key, math.nan)) for key in numeric):
        raise ValueError("Pose-constrained apron bounds must be finite")
    if (spec["minimumHeightZM"] >= spec["fullBlendHeightZM"]
            or spec["fullBlendHeightZM"] > spec["fullBlendEndHeightZM"]
            or spec["fullBlendEndHeightZM"] >= spec["waistLockHeightZM"]
            or spec["clearanceM"] <= 0
            or not 0 <= spec["minimumProjectionBlend"] < 1
            or spec["maximumTargetDistanceM"] <= 0
            or spec["maximumCorrectionM"] <= 0
            or spec["maximumPoseCorrectionM"] <= 0
            or spec["maximumSkinMappingErrorM"] <= 0
            or spec["maximumSurfaceResidualM"] <= 0
            or not 0 < spec["targetSurfaceHeightBinM"] <= spec["maximumSurfaceResidualM"]
            or not 0 < spec["maximumLocalSurfaceSupportDistanceM"] < spec["maximumTargetDistanceM"]
            or spec["smoothness"] < 0
            or not -1 < spec["maximumNormalTurnDot"] < 1
            or not isinstance(spec.get("smoothingIterations"), int)
            or not 1 <= spec["smoothingIterations"] <= 64):
        raise ValueError("Invalid pose-constrained apron bounds")
    owned_meshes = []
    for candidate in objects:
        if candidate.type != "MESH" or not candidate.data.attributes.get("canonical_piece_index"):
            continue
        candidate_attr = candidate.data.attributes["canonical_piece_index"]
        if candidate_attr.domain != "FACE":
            continue
        candidate_pieces = json.loads(candidate["canonicalPieceIds"])
        candidate_owners = [candidate_pieces[item.value] for item in candidate_attr.data]
        owned_meshes.append((candidate, candidate_pieces, candidate_owners))
    source_meshes = [item for item in owned_meshes if source_piece_ids.issubset(set(item[2]))]
    target_meshes = [
        item for item in owned_meshes
        if set(item[2]).intersection(left_targets | right_targets)
    ]
    if len(source_meshes) != 1 or not target_meshes:
        raise ValueError(
            "Pose-constrained apron requires one source mesh and evaluated shorts target meshes"
        )
    obj, pieces, face_owners = source_meshes[0]
    vertex_owners = [set() for _ in obj.data.vertices]
    for polygon, owner in zip(obj.data.polygons, face_owners):
        for index in polygon.vertices:
            vertex_owners[index].add(owner)
    neighbors = [set() for _ in obj.data.vertices]
    for edge in obj.data.edges:
        first, second = edge.vertices
        neighbors[first].add(second)
        neighbors[second].add(first)
    apron_vertices = {
        index for index, owners in enumerate(vertex_owners)
        if owners.intersection(source_piece_ids)
    }
    if not apron_vertices:
        raise ValueError("Pose-constrained apron selected no sewn vertices")

    # Carry the seated thigh trajectory through the sewn lap seam and ease it
    # into a narrow band of the neighboring front-skirt panels. Locking the
    # whole shared seam and its one-ring neighbors left the lap moving as an
    # isolated patch, which created a discontinuity exactly at the connection
    # the visual review asked us to improve. Keep the transition graph-bound
    # to the declared front panels; do not spread deformation around the skirt.
    transition_vertices = set()
    transition_ring_by_vertex = {}
    if transition_piece_ids:
        if any("front" not in piece for piece in transition_piece_ids):
            raise ValueError("Apron trajectory transitions must stay on front-skirt panels")
        seam_seeds = {
            index for index in apron_vertices
            if vertex_owners[index].intersection(transition_piece_ids)
        }
        frontier = set(seam_seeds)
        visited = set(seam_seeds)
        for ring in range(1, 3):
            next_frontier = {
                neighbor
                for index in frontier
                for neighbor in neighbors[index]
                if neighbor not in visited
                and vertex_owners[neighbor].intersection(transition_piece_ids)
                and not vertex_owners[neighbor].difference(
                    source_piece_ids | transition_piece_ids
                )
            }
            for index in next_frontier:
                transition_ring_by_vertex[index] = ring
            visited.update(next_frontier)
            frontier = next_frontier
        transition_vertices = set(transition_ring_by_vertex)
    selected = apron_vertices | transition_vertices
    selected_indices = sorted(selected)

    from genworks_product_common import reset_pose, set_pose

    def evaluated_world_vertices():
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated_obj = obj.evaluated_get(depsgraph)
        evaluated_mesh = evaluated_obj.to_mesh()
        if len(evaluated_mesh.vertices) != len(obj.data.vertices):
            evaluated_obj.to_mesh_clear()
            raise ValueError("Evaluated garment changed vertex order before apron solve")
        result = [evaluated_obj.matrix_world @ vertex.co for vertex in evaluated_mesh.vertices]
        evaluated_obj.to_mesh_clear()
        return result

    # Record the current weighted surface in each required pose. These values
    # bound the one sit-pose geometry solve in the other review poses.
    pose_names = ("neutral", "sit", "crouch")
    baseline = {}
    for name in pose_names:
        set_pose(armature, name)
        baseline[name] = evaluated_world_vertices()

    set_pose(armature, spec.get("referencePose", "sit"))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_obj = obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_obj.to_mesh()
    if len(evaluated_mesh.vertices) != len(obj.data.vertices):
        evaluated_obj.to_mesh_clear()
        raise ValueError("Evaluated source garment changed vertex order")
    world_vertices = [evaluated_obj.matrix_world @ v.co for v in evaluated_mesh.vertices]
    evaluated_mesh.calc_loop_triangles()
    pose_triangles = tuple(
        tuple(int(index) for index in triangle.vertices)
        for triangle in evaluated_mesh.loop_triangles
    )
    evaluated_obj.to_mesh_clear()
    side_triangles, target_world_vertices, target_offset = {"left": [], "right": []}, [], 0
    for target_obj, target_pieces, target_face_owners in target_meshes:
        target_eval = target_obj.evaluated_get(depsgraph)
        target_mesh = target_eval.to_mesh()
        if len(target_mesh.vertices) != len(target_obj.data.vertices):
            target_eval.to_mesh_clear()
            raise ValueError(f"Evaluated shorts target changed vertex order: {target_obj.name}")
        target_world_vertices.extend(
            target_eval.matrix_world @ vertex.co for vertex in target_mesh.vertices
        )
        target_attr = target_mesh.attributes.get("canonical_piece_index")
        if target_attr is None or target_attr.domain != "FACE":
            target_eval.to_mesh_clear()
            raise ValueError(f"Evaluated shorts target lost piece ownership: {target_obj.name}")
        target_mesh.calc_loop_triangles()
        evaluated_targets = [target_pieces[item.value] for item in target_attr.data]
        for triangle in target_mesh.loop_triangles:
            owner = evaluated_targets[triangle.polygon_index]
            if owner in left_targets:
                side_triangles["left"].append(tuple(i + target_offset for i in triangle.vertices))
            elif owner in right_targets:
                side_triangles["right"].append(tuple(i + target_offset for i in triangle.vertices))
        target_offset += len(target_mesh.vertices)
        target_eval.to_mesh_clear()
    if not side_triangles["left"] or not side_triangles["right"]:
        raise ValueError("Pose-constrained apron requires evaluated shorts triangles on both sides")
    side_target_z_ranges = {}
    for side, triangles in side_triangles.items():
        support_indices = {index for triangle in triangles for index in triangle}
        side_target_z_ranges[side] = (
            min(float(target_world_vertices[index].z) for index in support_indices),
            max(float(target_world_vertices[index].z) for index in support_indices),
        )
    target_triangles_by_height_bin = {"left": {}, "right": {}}
    for side, triangles in side_triangles.items():
        bins = target_triangles_by_height_bin[side]
        for triangle in triangles:
            low = min(float(target_world_vertices[index].z) for index in triangle)
            high = max(float(target_world_vertices[index].z) for index in triangle)
            first_bin = math.floor(low / spec["targetSurfaceHeightBinM"])
            last_bin = math.floor(high / spec["targetSurfaceHeightBinM"])
            for height_bin in range(first_bin, last_bin + 1):
                bins.setdefault(height_bin, []).append(triangle)
    side_trees = {"left": {}, "right": {}}

    def target_tree_at_height(side, height):
        height_bin = math.floor(height / spec["targetSurfaceHeightBinM"])
        if height_bin not in side_trees[side]:
            triangles = target_triangles_by_height_bin[side].get(height_bin, [])
            side_trees[side][height_bin] = (
                BVHTree.FromPolygons(target_world_vertices, triangles, all_triangles=True)
                if triangles else None
            )
        return side_trees[side][height_bin]

    left_bone = spec["leftThighBone"]
    right_bone = spec["rightThighBone"]
    if left_bone not in armature.data.bones or right_bone not in armature.data.bones:
        raise ValueError("Pose-constrained apron target thigh bones are missing")
    left_x = (armature.matrix_world @ armature.data.bones[left_bone].head_local).x
    right_x = (armature.matrix_world @ armature.data.bones[right_bone].head_local).x
    if abs(left_x - right_x) <= 1e-6:
        raise ValueError("Pose-constrained apron cannot establish bilateral thigh axis")
    center_x, left_positive = (left_x + right_x) / 2.0, left_x > right_x
    maps = {}
    for bone_name in armature.data.bones.keys():
        pose_bone = armature.pose.bones.get(bone_name)
        bone = armature.data.bones.get(bone_name)
        if pose_bone is not None and bone is not None and bone.use_deform:
            maps[bone_name] = (
                armature.matrix_world @ pose_bone.matrix
                @ bone.matrix_local.inverted()
                @ armature.matrix_world.inverted() @ obj.matrix_world
            )

    targets, target_distances, skin_errors = {}, [], []
    target_diagnostics = {}
    locked = set()
    outside_target_height_range_count = 0
    outside_target_local_height_bin_count = 0
    outside_target_local_surface_support_count = 0
    transition_blend_by_vertex = {}
    for index in selected_indices:
        point = obj.data.vertices[index].co
        if (point.z <= spec["minimumHeightZM"]
                or point.z >= spec["waistLockHeightZM"]
                or vertex_owners[index].difference(source_piece_ids | transition_piece_ids)
                or (index not in transition_vertices and any(
                    vertex_owners[neighbor].difference(source_piece_ids | transition_piece_ids)
                    for neighbor in neighbors[index]
                ))):
            locked.add(index)
            continue
        if point.z < spec["fullBlendHeightZM"]:
            blend = _smoothstep(
                (point.z - spec["minimumHeightZM"])
                / (spec["fullBlendHeightZM"] - spec["minimumHeightZM"])
            )
        elif point.z <= spec["fullBlendEndHeightZM"]:
            blend = 1.0
        else:
            blend = 1.0 - _smoothstep(
                (point.z - spec["fullBlendEndHeightZM"])
                / (spec["waistLockHeightZM"] - spec["fullBlendEndHeightZM"])
            )
        # Vertices outside the effective solve envelope receive no projection.
        # Requiring an in-range surface target for these nearly stationary
        # boundary vertices creates false failures without constraining geometry.
        if blend <= spec["minimumProjectionBlend"]:
            locked.add(index)
            continue
        if index in transition_ring_by_vertex:
            transition_blend_by_vertex[index] = blend
            continue
        side = "left" if ((obj.matrix_world @ point).x >= center_x) == left_positive else "right"
        pose_point = world_vertices[index]
        target_min_z, target_max_z = side_target_z_ranges[side]
        if pose_point.z < target_min_z or pose_point.z > target_max_z:
            # A lap hem can extend below the shorts. Outside the measured
            # vertical support of the named target surface, nearest-point
            # lookup would pull it toward an unrelated edge many centimeters
            # away and falsely fail the correspondence bound.
            locked.add(index)
            outside_target_height_range_count += 1
            continue
        local_target_tree = target_tree_at_height(side, float(pose_point.z))
        if local_target_tree is None:
            locked.add(index)
            outside_target_local_height_bin_count += 1
            continue
        result = local_target_tree.find_nearest(pose_point)
        if result is None or result[0] is None or result[1] is None:
            raise ValueError(f"Sit-pose shorts surface lookup failed at apron vertex {index}")
        location, normal, _triangle, distance = result
        if distance > spec["maximumTargetDistanceM"]:
            current_world = world_vertices[index]
            raise ValueError(
                f"Apron pose-space target exceeds bound at vertex {index}: {distance:.6f} m; "
                f"limit={spec['maximumTargetDistanceM']:.6f} m, side={side}, "
                f"blend={blend:.6f}, localPoint={tuple(round(float(value), 6) for value in point)}, "
                f"posePoint={tuple(round(float(value), 6) for value in current_world)}, "
                f"nearestTarget={tuple(round(float(value), 6) for value in location)}, "
                f"ownerPieceIds={sorted(vertex_owners[index])}"
            )
        if distance > spec["maximumLocalSurfaceSupportDistanceM"]:
            # A distant triangle in the same height band is not a valid local
            # correspondence. Keep this point unchanged and disclose the
            # unsupported count; pose and visual audits remain independent.
            locked.add(index)
            outside_target_local_surface_support_count += 1
            continue
        if normal.length < .99:
            raise ValueError(f"Invalid sit-pose shorts normal at apron vertex {index}")
        normal.normalize()
        current_world = world_vertices[index]
        if (current_world - location).dot(normal) < 0:
            normal.negate()
        target_world = location + normal * spec["clearanceM"]
        targets[index] = (target_world - current_world) * blend
        target_distances.append(float(distance))
        target_diagnostics[index] = {
            "blend": float(blend),
            "targetDistanceM": float(distance),
            "localPointM": tuple(float(value) for value in point),
            "currentPosePointM": tuple(float(value) for value in current_world),
            "surfaceTargetM": tuple(float(value) for value in target_world),
            "ownerPieceIds": sorted(vertex_owners[index]),
            "directCorrectionM": float(targets[index].length),
        }

    if not targets:
        raise ValueError("Pose-constrained apron produced no movable front-panel targets")
    # Continue the authored lap displacement through the shared seam. The
    # neighboring panel follows the lap's trajectory with a two-ring falloff;
    # it is not independently projected to the shorts, because vertices on
    # the rest of that panel are intentionally outside the thigh-projection
    # envelope.
    for ring in (1, 2):
        fade = 1.0 / 3.0 if ring == 1 else 1.0 / 12.0
        for index, vertex_ring in transition_ring_by_vertex.items():
            if vertex_ring != ring or index not in transition_blend_by_vertex:
                continue
            adjacent_targets = [
                targets[neighbor]
                for neighbor in neighbors[index]
                if neighbor in targets
            ]
            if not adjacent_targets:
                locked.add(index)
                continue
            trajectory = sum(adjacent_targets, Vector()) / len(adjacent_targets)
            targets[index] = trajectory * fade * transition_blend_by_vertex[index]
            target_diagnostics[index] = {
                "blend": float(fade * transition_blend_by_vertex[index]),
                "trajectorySource": "adjacent-lap-displacement",
                "trajectoryRing": ring,
                "localPointM": tuple(float(value) for value in obj.data.vertices[index].co),
                "currentPosePointM": tuple(float(value) for value in world_vertices[index]),
                "ownerPieceIds": sorted(vertex_owners[index]),
                "directCorrectionM": float(targets[index].length),
            }

    if not targets:
        raise ValueError("Pose-constrained apron produced no movable front-panel targets")
    # Freeze the existing skin map for every moved vertex. The transition
    # geometry inherits a source trajectory but keeps the same weight map and
    # strict mapping-error bound as the lap itself.
    for index in sorted(targets):
        point = obj.data.vertices[index].co
        current_world = world_vertices[index]
        groups_for_vertex = {
            obj.vertex_groups[group.group].name: group.weight
            for group in obj.data.vertices[index].groups
            if group.group < len(obj.vertex_groups)
        }
        mapping = Matrix(((0.0, 0.0, 0.0, 0.0),) * 4)
        for name, weight in groups_for_vertex.items():
            if name not in maps or weight <= 0:
                continue
            mapping += maps[name] * weight
        if abs(sum(groups_for_vertex.values()) - 1.0) > 1e-4 or abs(mapping.determinant()) < 1e-10:
            raise ValueError(f"Frozen skin map is incomplete or singular at apron vertex {index}")
        predicted = mapping @ Vector((*obj.data.vertices[index].co, 1.0))
        map_error = (Vector(predicted[:3]) - current_world).length
        skin_errors.append(map_error)
        if map_error > spec["maximumSkinMappingErrorM"]:
            raise ValueError(
                f"Armature inverse map diverges from evaluated sit pose at vertex {index}: {map_error:.6f} m"
            )
        maps[index] = mapping.inverted()
    displacement = {index: Vector((0, 0, 0)) for index in selected_indices}
    displacement.update(targets)
    movable = set(targets)
    strength = spec["smoothness"]
    for _ in range(spec["smoothingIterations"]):
        updated = dict(displacement)
        for index in movable:
            adjacent = [other for other in neighbors[index] if other in selected]
            if not adjacent or strength == 0:
                continue
            mean = sum((displacement[other] for other in adjacent), Vector()) / len(adjacent)
            updated[index] = (targets[index] + mean * strength) / (1.0 + strength)
        displacement = updated

    # Backtrack the whole correction field until every affected evaluated
    # triangle retains the configured orientation bound. This is a feasibility
    # step, not a gate change: the unchanged surface-residual and displacement
    # limits below still reject an underpowered safe field.
    normal_turn_limit = spec["maximumNormalTurnDot"]
    orientation_limited_vertices = set()
    for _ in range(32):
        vertices_to_reduce = set()
        for triangle in pose_triangles:
            if not set(triangle).intersection(movable):
                continue
            old = [world_vertices[index] for index in triangle]
            new = [
                world_vertices[index]
                + displacement.get(index, Vector())
                for index in triangle
            ]
            old_normal = (old[1] - old[0]).cross(old[2] - old[0])
            new_normal = (new[1] - new[0]).cross(new[2] - new[0])
            if old_normal.length < 1e-10:
                raise ValueError("Pose-constrained apron source contains a collapsed sewn triangle")
            if new_normal.length < 1e-10 or old_normal.normalized().dot(new_normal.normalized()) < normal_turn_limit:
                vertices_to_reduce.update(set(triangle).intersection(movable))
        if not vertices_to_reduce:
            break
        for index in vertices_to_reduce:
            displacement[index] *= 0.5
        orientation_limited_vertices.update(vertices_to_reduce)
    else:
        raise ValueError(
            "Pose-constrained apron cannot preserve sewn-triangle orientation "
            "within the configured normal-turn bound"
        )

    corrections = [value.length for value in displacement.values()]
    maximum_correction = max(corrections, default=0.0)
    if maximum_correction > spec["maximumCorrectionM"]:
        maximum_index = max(displacement, key=lambda index: displacement[index].length)
        diagnostic = target_diagnostics.get(maximum_index, {})
        raise ValueError(
            f"Pose-constrained apron correction {maximum_correction:.6f} m exceeds declared geometry bound {spec['maximumCorrectionM']:.6f} m at vertex {maximum_index}; "
            f"target={diagnostic.get('targetDistanceM', 'locked')} m, blend={diagnostic.get('blend', 'locked')}, "
            f"directCorrection={diagnostic.get('directCorrectionM', 'locked')} m, localPoint={diagnostic.get('localPointM', 'locked')}, "
            f"posePoint={diagnostic.get('currentPosePointM', 'locked')}, surfaceTarget={diagnostic.get('surfaceTargetM', 'locked')}, "
            f"owners={diagnostic.get('ownerPieceIds', 'locked')}"
        )
    original_sit = {
        index: world_point.copy()
        for index, world_point in enumerate(world_vertices)
    }
    for index in movable:
        if displacement[index].length <= 1e-9:
            continue
        target_world = world_vertices[index] + displacement[index]
        rest_h = maps[index] @ Vector((*target_world, 1.0))
        if abs(rest_h.w) <= 1e-9:
            raise ValueError(f"Apron inverse skin map returned a point at infinity: {index}")
        rest_local = Vector(rest_h[:3]) / rest_h.w
        obj.data.vertices[index].co = rest_local

    # Evaluate the solved geometry in all three poses. Large changes or a
    # folded triangle are treated as infeasible and are never silently kept.
    maximum_pose_delta = {name: 0.0 for name in pose_names}
    for name in pose_names:
        set_pose(armature, name)
        after = evaluated_world_vertices()
        for index in selected_indices:
            delta = (after[index] - baseline[name][index]).length
            maximum_pose_delta[name] = max(maximum_pose_delta[name], delta)
            if delta > spec["maximumPoseCorrectionM"]:
                raise ValueError(
                    f"Apron geometry solve exceeds {name} pose bound at vertex {index}: {delta:.6f} m"
                )
    set_pose(armature, "sit")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    final_obj = obj.evaluated_get(depsgraph)
    final_mesh = final_obj.to_mesh()
    final_world = [final_obj.matrix_world @ vertex.co for vertex in final_mesh.vertices]
    residual_records = []
    for index in movable:
        if index not in apron_vertices:
            continue
        side = (
            "left"
            if ((obj.matrix_world @ obj.data.vertices[index].co).x >= center_x) == left_positive
            else "right"
        )
        local_target_tree = target_tree_at_height(side, float(final_world[index].z))
        if local_target_tree is None:
            final_obj.to_mesh_clear()
            raise ValueError(
                f"Solved apron left the local shorts-surface height support at vertex {index}"
            )
        result = local_target_tree.find_nearest(final_world[index])
        if result is None or result[0] is None:
            final_obj.to_mesh_clear()
            raise ValueError(f"Solved apron has no shorts residual at vertex {index}")
        residual_records.append({
            "vertex": int(index),
            "side": side,
            "surfaceDistanceM": float(result[3]),
            "residualM": abs(float(result[3]) - spec["clearanceM"]),
            "posePointM": tuple(float(value) for value in final_world[index]),
            "nearestSurfacePointM": tuple(float(value) for value in result[0]),
            "sourcePointM": tuple(float(value) for value in obj.data.vertices[index].co),
            "ownerPieceIds": sorted(vertex_owners[index]),
            "appliedDisplacementM": float(displacement[index].length),
        })
    final_mesh.calc_loop_triangles()
    for triangle_index, triangle in enumerate(final_mesh.loop_triangles):
        if not set(triangle.vertices).intersection(movable):
            continue
        old = [original_sit[index] for index in triangle.vertices]
        new = [final_world[index] for index in triangle.vertices]
        old_normal = (old[1] - old[0]).cross(old[2] - old[0])
        new_normal = (new[1] - new[0]).cross(new[2] - new[0])
        if old_normal.length < 1e-10 or new_normal.length < 1e-10:
            final_obj.to_mesh_clear()
            raise ValueError("Pose-constrained apron solve collapsed a sewn triangle")
        turn_dot = old_normal.normalized().dot(new_normal.normalized())
        if turn_dot < spec["maximumNormalTurnDot"]:
            indices = tuple(int(index) for index in triangle.vertices)
            diagnostic = (
                f"Pose-constrained apron solve inverted sewn triangle {triangle_index} {indices}: "
                f"normalDot={turn_dot:.6f}, owners={[sorted(vertex_owners[index]) for index in indices]}, "
                f"corrections={[round(float(displacement[index].length), 6) for index in indices]}, "
                f"old={[tuple(round(float(value), 6) for value in old[i]) for i in range(3)]}, "
                f"new={[tuple(round(float(value), 6) for value in new[i]) for i in range(3)]}"
            )
            final_obj.to_mesh_clear()
            raise ValueError(diagnostic)
    final_obj.to_mesh_clear()
    reset_pose(armature)
    bpy.context.view_layer.update()
    maximum_residual = max(residual_records, key=lambda record: record["residualM"], default=None)
    if maximum_residual and maximum_residual["residualM"] > spec["maximumSurfaceResidualM"]:
        raise ValueError(
            "Pose-constrained apron could not meet the shorts-surface residual bound: "
            f"maximum={maximum_residual['residualM']:.6f} m, "
            f"limit={spec['maximumSurfaceResidualM']:.6f} m, "
            f"vertex={maximum_residual['vertex']}, side={maximum_residual['side']}, "
            f"surfaceDistance={maximum_residual['surfaceDistanceM']:.6f} m, "
            f"displacement={maximum_residual['appliedDisplacementM']:.6f} m, "
            f"posePoint={tuple(round(value, 6) for value in maximum_residual['posePointM'])}, "
            f"surfacePoint={tuple(round(value, 6) for value in maximum_residual['nearestSurfacePointM'])}, "
            f"owners={maximum_residual['ownerPieceIds']}, "
            f"orientationLimitedVertices={len(orientation_limited_vertices)}"
        )
    return {
        "applied": True,
        "method": spec["method"],
        "referencePose": spec.get("referencePose", "sit"),
        "sourcePieceIds": sorted(source_piece_ids),
        "transitionPieceIds": sorted(transition_piece_ids),
        "transitionVertexCountByRing": {
            str(ring): sum(value == ring for value in transition_ring_by_vertex.values())
            for ring in (1, 2)
        },
        "targetPieceIdsBySide": {"left": sorted(left_targets), "right": sorted(right_targets)},
        "targetSurfaceHeightRangeZM": {
            side: [float(value) for value in height_range]
            for side, height_range in side_target_z_ranges.items()
        },
        "outsideTargetHeightRangeVertexCount": outside_target_height_range_count,
        "outsideTargetLocalHeightBinVertexCount": outside_target_local_height_bin_count,
        "outsideTargetLocalSurfaceSupportVertexCount": outside_target_local_surface_support_count,
        "targetSurfaceHeightBinM": float(spec["targetSurfaceHeightBinM"]),
        "maximumLocalSurfaceSupportDistanceM": float(
            spec["maximumLocalSurfaceSupportDistanceM"]
        ),
        "movedVertexCount": sum(
            displacement[index].length > 1e-9 for index in movable
        ),
        "lockedSharedOrWaistVertexCount": len(locked),
        "maximumTargetDistanceM": max(target_distances, default=0.0),
        "maximumSkinMapErrorM": max(skin_errors, default=0.0),
        "maximumCorrectionM": max(corrections, default=0.0),
        "orientationLimitedVertexCount": len(orientation_limited_vertices),
        "maximumPoseDisplacementM": maximum_pose_delta,
        "maximumSurfaceResidualM": max(
            (record["residualM"] for record in residual_records), default=0.0
        ),
        "minimumNormalTurnDot": spec["maximumNormalTurnDot"],
        "skinWeightsChanged": False,
        "sharedExternalSeamsMoved": bool(transition_vertices),
        "grantsFitAcceptance": False,
        "grantsPoseAcceptance": False,
        "evidenceBoundary": "One bounded, sit-pose source-geometry hypothesis with frozen garment skin weights. Its target is the evaluated shorts surface; neutral/crouch displacement and triangle orientation are checked, but fit, motion, collision, appearance and release remain unverified.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    job = read_json(repo_path(args.job))
    cloth = read_json(
        repo_path(job["productRoot"] + "/Evidence/Build/cloth-simulation.json")
    )
    candidate = repo_path(cloth["candidatePath"])
    if digest(candidate) != cloth["candidateSha256"]:
        raise ValueError("cloth candidate is stale")
    if digest(repo_path(job["blendPath"])) != cloth["sourceBlendSha256"]:
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
    body_weights = [
        {
            body.vertex_groups[g.group].name: g.weight
            for g in v.groups
            if body.vertex_groups[g.group].name in bones
        }
        for v in body.data.vertices
    ]
    construction = read_json(repo_path(job["garmentPipeline"]["constructionPath"]))
    regions = construction.get("prototypeWeightRegions", [])
    region_trees = []
    profiles_by_piece = {}
    for region in regions:
        low, high = region["bodyTriangleZM"]
        if not 0 <= low < high or not region["pieceIds"]:
            raise ValueError("Invalid explicit body weight region")
        profile = region.get("weightProfile")
        if profile is not None:
            profile_piece_ids = set(profile["pieceIds"])
            if (
                profile["method"]
                not in {
                    "hip-anchored-lateral-thigh-fade-v1",
                    "hip-anchored-anterior-lateral-thigh-fade-v2",
                    "hip-anchored-anterior-bilateral-center-hem-fade-v3",
                    "hip-anchored-anterior-bilateral-center-hem-fade-capped-v4",
                    "panel-balanced-hem-thigh-follow-v5",
                    "panel-balanced-anterior-hip-apron-v6",
                }
                or not profile_piece_ids
                or not profile_piece_ids.issubset(set(region["pieceIds"]))
                or not 0
                <= profile["waistThighWeight"]
                <= profile["hemThighWeight"]
                <= 1
                or profile["centerlineHalfWidthM"] < 0
                or profile["fullSideWeightWidthM"] <= profile["centerlineHalfWidthM"]
            ):
                raise ValueError("Invalid explicit prototype weight profile")
            if profile["method"] in {
                "hip-anchored-anterior-lateral-thigh-fade-v2",
                "hip-anchored-anterior-bilateral-center-hem-fade-v3",
                "hip-anchored-anterior-bilateral-center-hem-fade-capped-v4",
                "panel-balanced-hem-thigh-follow-v5",
                "panel-balanced-anterior-hip-apron-v6",
            }:
                if (
                    not math.isfinite(profile.get("forwardCenterYM", math.nan))
                    or not math.isfinite(profile.get("forwardFadeDistanceM", math.nan))
                    or profile["forwardFadeDistanceM"] <= 0
                    or not 0 <= profile.get("forwardHemThighWeight", math.nan) <= 1
                ):
                    raise ValueError("Invalid anterior prototype weight profile")
                if (
                    profile["method"]
                    in {
                        "hip-anchored-anterior-bilateral-center-hem-fade-v3",
                        "hip-anchored-anterior-bilateral-center-hem-fade-capped-v4",
                        "panel-balanced-hem-thigh-follow-v5",
                        "panel-balanced-anterior-hip-apron-v6",
                    }
                    and not 0 <= profile.get("centerlineHemThighWeight", math.nan) <= 1
                ):
                    raise ValueError(
                        "Invalid bilateral center-hem prototype weight profile"
                    )
                if (
                    profile["method"]
                    in {
                        "hip-anchored-anterior-bilateral-center-hem-fade-capped-v4",
                        "panel-balanced-hem-thigh-follow-v5",
                        "panel-balanced-anterior-hip-apron-v6",
                    }
                    and not 0 < profile.get("maximumThighWeight", math.nan) <= 0.75
                ):
                    raise ValueError(
                        "Invalid capped center-hem prototype weight profile"
                    )
            for bone_name in (
                profile["hipBone"],
                profile["leftThighBone"],
                profile["rightThighBone"],
            ):
                if bone_name not in bones:
                    raise ValueError(
                        f"Prototype weight profile bone is missing or non-deform: {bone_name}"
                    )
            if profile["leftThighBone"] == profile["rightThighBone"]:
                raise ValueError(
                    "Prototype weight profile requires distinct left and right thigh bones"
                )
            for piece_id in profile_piece_ids:
                if piece_id in profiles_by_piece:
                    raise ValueError(
                        f"Conflicting prototype weight profiles for piece {piece_id}"
                    )
                profiles_by_piece[piece_id] = profile
        selected = [
            i
            for i, triangle in enumerate(triangles)
            if all(low <= coordinates[v].z <= high for v in triangle)
            and not any(
                name.startswith(tuple(region["excludedBoneNamePrefixes"]))
                for v in triangle
                for name, w in body_weights[v].items()
                if w > 1e-6
            )
        ]
        if not selected:
            raise ValueError("Body weight region contains no eligible triangles")
        region_trees.append(
            (
                region,
                selected,
                BVHTree.FromPolygons(
                    coordinates, [triangles[i] for i in selected], all_triangles=True
                ),
            )
        )
    objects = [
        o
        for o in bpy.context.scene.objects
        if o.type == "MESH" and o.get("prototypeRole") != "target-avatar-reference-only"
    ]
    if not objects:
        raise ValueError("cloth candidate contains no garment meshes")
    audits, distances, region_records, profile_audits = {}, [], [], {}
    trim_objects = [
        obj
        for obj in objects
        if obj.get("prototypeRole") == "unfitted-prototype-edge-trim"
    ]
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
        object_coordinates = [
            obj.matrix_world @ vertex.co for vertex in obj.data.vertices
        ]
        profile_bounds = {}
        profile_centers = {}
        profile_accumulators = {}
        active_profiles = {
            id(profile): profile
            for piece_id, profile in profiles_by_piece.items()
            if any(piece_id in owner_set for owner_set in owners)
        }
        for profile_key, profile in active_profiles.items():
            profile_piece_ids = set(profile["pieceIds"])
            selected_vertices = [
                index
                for index, owner_set in enumerate(owners)
                if owner_set.intersection(profile_piece_ids)
            ]
            if not selected_vertices:
                raise ValueError(f"Weight profile selected no vertices on {obj.name}")
            heights = [object_coordinates[index].z for index in selected_vertices]
            low, high = min(heights), max(heights)
            if not math.isfinite(low) or not math.isfinite(high) or high <= low:
                raise ValueError(
                    f"Weight profile has a collapsed vertical range on {obj.name}"
                )
            left_x = (
                armature.matrix_world
                @ armature.data.bones[profile["leftThighBone"]].head_local
            ).x
            right_x = (
                armature.matrix_world
                @ armature.data.bones[profile["rightThighBone"]].head_local
            ).x
            if (
                not math.isfinite(left_x)
                or not math.isfinite(right_x)
                or abs(left_x - right_x) <= 1e-6
            ):
                raise ValueError(
                    f"Weight profile cannot establish avatar left/right axis on {obj.name}"
                )
            profile_bounds[profile_key] = (low, high)
            profile_centers[profile_key] = ((left_x + right_x) / 2.0, left_x > right_x)
            profile_accumulators[profile_key] = {
                "profile": profile,
                "vertexCount": 0,
                "thighWeights": [],
                "centerlineVertexCount": 0,
                "leftSideVertexCount": 0,
                "rightSideVertexCount": 0,
            }
        raw = {}
        for vertex in obj.data.vertices:
            point = object_coordinates[vertex.index]
            nearest, normal, triangle_id, distance = tree.find_nearest(point)
            matching = [
                (region, ids, regional_tree)
                for region, ids, regional_tree in region_trees
                if owners[vertex.index].intersection(region["pieceIds"])
            ]
            if len(matching) > 1:
                raise ValueError("Vertex has conflicting explicit weight regions")
            if matching:
                region, regional_ids, regional_tree = matching[0]
                unbounded_id = triangle_id
                nearest, normal, regional_id, distance = regional_tree.find_nearest(
                    point
                )
                if regional_id is None:
                    raise ValueError("Regional body lookup failed")
                triangle_id = regional_ids[regional_id]
                region_records.append(
                    {
                        "object": obj.name,
                        "vertexIndex": vertex.index,
                        "pieceIds": sorted(owners[vertex.index]),
                        "bodyTriangleZM": region["bodyTriangleZM"],
                        "unboundedTriangleId": unbounded_id,
                        "selectedTriangleId": triangle_id,
                        "unboundedArmInfluence": any(
                            name.startswith(tuple(region["excludedBoneNamePrefixes"]))
                            for v in triangles[unbounded_id]
                            for name, w in body_weights[v].items()
                            if w > 1e-6
                        ),
                        "distanceM": distance,
                    }
                )
            if triangle_id is None:
                raise ValueError("body surface lookup failed")
            ids = triangles[triangle_id]
            a, b, c = [coordinates[i] for i in ids]
            bary = barycentric_transform(
                nearest,
                a,
                b,
                c,
                Vector((1, 0, 0)),
                Vector((0, 1, 0)),
                Vector((0, 0, 1)),
            )
            if min(bary) < -1e-4:
                raise ValueError("closest body point is outside its triangle")
            combined = {}
            for index, coefficient in zip(ids, bary):
                for bone, weight in body_weights[index].items():
                    combined[bone] = (
                        combined.get(bone, 0) + max(0, coefficient) * weight
                    )
            matching_profiles = [
                (key, profile)
                for key, profile in active_profiles.items()
                if owners[vertex.index].intersection(profile["pieceIds"])
            ]
            if len(matching_profiles) > 1:
                raise ValueError(
                    f"Conflicting prototype weight profiles at {obj.name}:{vertex.index}"
                )
            if matching_profiles:
                profile_key, profile = matching_profiles[0]
                low, high = profile_bounds[profile_key]
                center_x, left_is_positive_x = profile_centers[profile_key]
                height_fraction = min(1.0, max(0.0, (point.z - low) / (high - low)))
                hem_fraction = 1.0 - height_fraction
                base_thigh = (
                    profile["waistThighWeight"]
                    + (profile["hemThighWeight"] - profile["waistThighWeight"])
                    * hem_fraction
                )
                lateral = abs(point.x - center_x)
                lateral_fraction = (lateral - profile["centerlineHalfWidthM"]) / (
                    profile["fullSideWeightWidthM"] - profile["centerlineHalfWidthM"]
                )
                thigh_weight = base_thigh * _smoothstep(lateral_fraction)
                centerline_thigh_weight = 0.0
                if profile["method"] in {
                    "hip-anchored-anterior-lateral-thigh-fade-v2",
                    "hip-anchored-anterior-bilateral-center-hem-fade-v3",
                    "hip-anchored-anterior-bilateral-center-hem-fade-capped-v4",
                    "panel-balanced-hem-thigh-follow-v5",
                    "panel-balanced-anterior-hip-apron-v6",
                }:
                    forward_fraction = _smoothstep(
                        (profile["forwardCenterYM"] - point.y)
                        / profile["forwardFadeDistanceM"]
                    )
                    if profile["method"] == "panel-balanced-anterior-hip-apron-v6":
                        # Keep the skirt's anterior apron with the pelvis while
                        # the avatar's thighs lift in sit/crouch. The lateral
                        # skirt still follows the thighs; the forward target is
                        # an absolute hem weight, not an additive influence.
                        anterior_target = (
                            profile["forwardHemThighWeight"]
                            * hem_fraction
                            * _smoothstep(lateral_fraction)
                        )
                        thigh_weight += (anterior_target - thigh_weight) * forward_fraction
                    else:
                        thigh_weight += (
                            profile["forwardHemThighWeight"]
                            * hem_fraction
                            * forward_fraction
                            * _smoothstep(lateral_fraction)
                        )
                    thigh_weight = min(1.0, thigh_weight)
                    if profile["method"] in {
                        "hip-anchored-anterior-bilateral-center-hem-fade-v3",
                        "hip-anchored-anterior-bilateral-center-hem-fade-capped-v4",
                        "panel-balanced-hem-thigh-follow-v5",
                        "panel-balanced-anterior-hip-apron-v6",
                    }:
                        center_width = profile["centerlineHalfWidthM"]
                        center_fraction = 1.0 - _smoothstep(
                            lateral / center_width
                            if center_width > 0
                            else (1.0 if lateral > 0 else 0.0)
                        )
                        centerline_thigh_weight = (
                            profile["centerlineHemThighWeight"]
                            * hem_fraction
                            * forward_fraction
                            * center_fraction
                        )
                        thigh_weight = max(thigh_weight, centerline_thigh_weight)
                    if profile["method"] in {
                        "hip-anchored-anterior-bilateral-center-hem-fade-capped-v4",
                        "panel-balanced-hem-thigh-follow-v5",
                        "panel-balanced-anterior-hip-apron-v6",
                    }:
                        maximum = profile["maximumThighWeight"]
                        if thigh_weight > maximum:
                            centerline_thigh_weight *= maximum / thigh_weight
                            thigh_weight = maximum
                if point.x > center_x:
                    thigh_bone = (
                        profile["leftThighBone"]
                        if left_is_positive_x
                        else profile["rightThighBone"]
                    )
                    profile_accumulators[profile_key]["leftSideVertexCount"] += int(
                        left_is_positive_x
                    )
                    profile_accumulators[profile_key]["rightSideVertexCount"] += int(
                        not left_is_positive_x
                    )
                elif point.x < center_x:
                    thigh_bone = (
                        profile["rightThighBone"]
                        if left_is_positive_x
                        else profile["leftThighBone"]
                    )
                    profile_accumulators[profile_key]["rightSideVertexCount"] += int(
                        left_is_positive_x
                    )
                    profile_accumulators[profile_key]["leftSideVertexCount"] += int(
                        not left_is_positive_x
                    )
                else:
                    thigh_bone = profile["hipBone"]
                    profile_accumulators[profile_key]["centerlineVertexCount"] += 1
                if thigh_weight > 0:
                    if centerline_thigh_weight > 0:
                        side_weight = max(0.0, thigh_weight - centerline_thigh_weight)
                        raw[vertex.index] = [
                            (profile["hipBone"], 1.0 - thigh_weight),
                            (profile["leftThighBone"], centerline_thigh_weight / 2),
                            (profile["rightThighBone"], centerline_thigh_weight / 2),
                            (thigh_bone, side_weight),
                        ]
                    else:
                        raw[vertex.index] = [
                            (profile["hipBone"], 1.0 - thigh_weight),
                            (thigh_bone, thigh_weight),
                        ]
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
                    "centerlineHalfWidthM": accumulator["profile"][
                        "centerlineHalfWidthM"
                    ],
                    "fullSideWeightWidthM": accumulator["profile"][
                        "fullSideWeightWidthM"
                    ],
                    "waistThighWeight": accumulator["profile"]["waistThighWeight"],
                    "hemThighWeight": accumulator["profile"]["hemThighWeight"],
                    "forwardHemThighWeight": accumulator["profile"].get(
                        "forwardHemThighWeight", 0.0
                    ),
                    "maximumThighWeight": accumulator["profile"].get(
                        "maximumThighWeight"
                    ),
                    "vertexCount": accumulator["vertexCount"],
                    "centerlineVertexCount": accumulator["centerlineVertexCount"],
                    "leftSideVertexCount": accumulator["leftSideVertexCount"],
                    "rightSideVertexCount": accumulator["rightSideVertexCount"],
                    "measuredThighWeight": {
                        "minimum": min(accumulator["thighWeights"]),
                        "mean": sum(accumulator["thighWeights"])
                        / len(accumulator["thighWeights"]),
                        "maximum": max(accumulator["thighWeights"]),
                    },
                    "grantsFitAcceptance": False,
                    "evidenceBoundary": accumulator["profile"]["evidenceBoundary"],
                }
                for key, accumulator in profile_accumulators.items()
            ]
    pose_constrained_apron_evidence = apply_pose_constrained_apron_geometry(
        garment_objects,
        armature,
        read_json(repo_path(job["garmentPipeline"]["assemblyPosePath"])),
    )
    # Bind trim to the settled garment and inherit its weights, including the
    # garment's explicit regional profile. No independent body lookup for trim.
    edge_sources = {}
    for obj in garment_objects:
        source_ids = obj.data.attributes.get("canonical_sewn_vertex_index")
        # Surface motifs are skinned with the garment but are not split from
        # canonical sewn panels, so they have no sewn-vertex identity. Only
        # canonical panel meshes can supply settled edge positions for trim.
        if source_ids is None:
            continue
        pieces = json.loads(obj["canonicalPieceIds"])
        owners = [set() for _ in obj.data.vertices]
        for face, owner in zip(
            obj.data.polygons, obj.data.attributes["canonical_piece_index"].data
        ):
            for index in face.vertices:
                owners[index].add(pieces[owner.value])
        for vertex, source_id in zip(obj.data.vertices, source_ids.data):
            weights = {
                obj.vertex_groups[g.group].name: g.weight
                for g in vertex.groups
                if obj.vertex_groups[g.group].name in bones
            }
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
            first_key = (binding["first"], piece)
            second_key = (binding["second"], piece)
            if first_key not in edge_sources or second_key not in edge_sources:
                missing = [
                    key for key in (first_key, second_key) if key not in edge_sources
                ]
                raise ValueError(
                    f"Prototype trim binding references missing canonical sewn edge source: "
                    f"{obj.name} {missing}"
                )
            first, first_weights = edge_sources[first_key]
            second, second_weights = edge_sources[second_key]
            direction = second - first
            rest_direction = Vector(binding["restDirection"])
            if min(direction.length_squared, rest_direction.length_squared) <= 1e-16:
                raise ValueError(f"Collapsed trim source edge: {obj.name}")
            fraction = binding["fraction"]
            offset = rest_direction.rotation_difference(direction) @ Vector(
                binding["restOffset"]
            )
            point = first.lerp(second, fraction) + offset
            displacements.append((point - obj.matrix_world @ vertex.co).length)
            vertex.co = inverse @ point
            combined = {
                bone: (1 - fraction) * first_weights.get(bone, 0.0)
                + fraction * second_weights.get(bone, 0.0)
                for bone in first_weights.keys() | second_weights.keys()
            }
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
        trim_audits[obj.name] = {
            "method": "settled-sewn-edge-position-and-weight-interpolation",
            "vertexCount": len(bindings),
            "maximumSettlingDisplacementM": max(displacements),
            "meanSettlingDisplacementM": sum(displacements) / len(displacements),
            "grantsFitAcceptance": False,
        }
    runtime = ROOT / ".image2outfit/products" / job["id"] / "skin"
    runtime.mkdir(parents=True, exist_ok=True)
    source = runtime / "weighted-prototype.blend"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(source), check_existing=False)
    fbx = repo_path(job["fbxAssetPath"])
    export_settled_fbx(fbx, armature, objects)
    write_json(
        runtime / "skin-export-report.json",
        {
            "schemaVersion": 1,
            "productId": job["id"],
            "executionStatus": "PASS",
            "qualityDecision": "UNVERIFIED",
            "method": "nearest-body-triangle-barycentric",
            "blenderVersion": bpy.app.version_string,
            "inputCandidateSha256": digest(candidate),
            "targetSourceSha256": digest(repo_path(job["targetSourcePath"])),
            "weightedBlendPath": str(source.relative_to(ROOT)).replace("\\", "/"),
            "weightedBlendSha256": digest(source),
            "fbxSha256": digest(fbx),
            "sourceBodyMeshHash": mesh_hash(body),
            "boneCount": len(bones),
            "exportedGarmentObjects": [o.name for o in objects],
            "bodyGeometryExported": False,
            "audits": audits,
            "vertexCount": sum(len(obj.data.vertices) for obj in objects),
            "unweightedVertices": 0,
            "prototypeTrimAttachment": trim_audits,
            "poseConstrainedApronGeometry": pose_constrained_apron_evidence,
            "prototypeWeightProfiles": profile_audits,
            "bodyDistanceM": {
                "minimum": min(distances),
                "maximum": max(distances),
                "mean": sum(distances) / len(distances),
            },
            "lateralityReview": "UNASSESSED",
            "grantsFitAcceptance": False,
            "prototypeWeightRegions": regions,
            "regionalTransferRecords": region_records,
            "constructionSha256": digest(
                repo_path(job["garmentPipeline"]["constructionPath"])
            ),
            "pending": [
                "fit",
                "deformation and laterality",
                "Shape Keys",
                "appearance",
                "Unity Prefabs",
                "VRChat runtime",
            ],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
