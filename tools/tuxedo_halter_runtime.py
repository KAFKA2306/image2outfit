#!/usr/bin/env python3
"""Cloth, pose, cleanup, and Unity declaration helpers for tuxedo halter."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from pathlib import Path

import bmesh
import bpy

import genworks_product_common as g


def mesh_geometry_sha256(
    obj: bpy.types.Object,
    *,
    evaluated: bool = False,
) -> str:
    if obj.type != "MESH":
        raise ValueError(f"mesh hash requires a mesh object: {obj.name}")
    evaluated_object = None
    mesh = obj.data
    if evaluated:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated_object = obj.evaluated_get(depsgraph)
        mesh = evaluated_object.to_mesh()
    try:
        payload = {
            "vertices": [
                [round(float(value), 7) for value in vertex.co]
                for vertex in mesh.vertices
            ],
            "polygons": [list(polygon.vertices) for polygon in mesh.polygons],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
    finally:
        if evaluated_object is not None:
            evaluated_object.to_mesh_clear()


def combined_geometry_sha256(objects: list[bpy.types.Object]) -> str:
    records = [
        {
            "object": obj.name,
            "meshSha256": mesh_geometry_sha256(obj),
        }
        for obj in sorted(objects, key=lambda item: item.name)
        if obj.type == "MESH"
    ]
    encoded = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cloth_cache_state(obj: bpy.types.Object, modifier_name: str) -> dict[str, object]:
    modifier = obj.modifiers.get(modifier_name)
    if modifier is None or modifier.type != "CLOTH":
        raise ValueError(f"cloth modifier is missing: {obj.name}/{modifier_name}")
    cache = modifier.point_cache
    return {
        "object": obj.name,
        "modifier": modifier.name,
        "cacheBakedActual": bool(cache.is_baked),
        "frameStart": int(cache.frame_start),
        "frameEnd": int(cache.frame_end),
        "cacheInfo": str(cache.info or ""),
    }


def configure_cloth(
    skirt: bpy.types.Object,
    body: bpy.types.Object,
    pin_vertices: list[int],
    *,
    frame_end: int,
) -> dict[str, object]:
    collision = body.modifiers.get("Outfit Collision")
    if collision is None:
        body.modifiers.new("Outfit Collision", "COLLISION")
    body.collision.thickness_outer = 0.004
    body.collision.damping = 0.5

    pin = skirt.vertex_groups.new(name="ClothPin")
    pin.add(pin_vertices, 1.0, "REPLACE")
    cloth = skirt.modifiers.new("Reference Cloth", "CLOTH")
    bpy.ops.object.select_all(action="DESELECT")
    skirt.select_set(True)
    bpy.context.view_layer.objects.active = skirt
    while skirt.modifiers.find(cloth.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=cloth.name)
    skirt.select_set(False)
    cloth.settings.quality = 8
    cloth.settings.mass = 0.18
    cloth.settings.tension_stiffness = 22.0
    cloth.settings.compression_stiffness = 22.0
    cloth.settings.shear_stiffness = 9.0
    cloth.settings.bending_stiffness = 0.38
    cloth.settings.air_damping = 3.0
    cloth.settings.vertex_group_mass = pin.name
    cloth.settings.pin_stiffness = 1.0
    cloth.collision_settings.use_collision = True
    cloth.collision_settings.collision_quality = 5
    cloth.collision_settings.distance_min = 0.003
    cloth.point_cache.frame_start = 1
    cloth.point_cache.frame_end = frame_end
    cloth.point_cache.use_disk_cache = True
    return {
        "object": skirt.name,
        "modifier": cloth.name,
        "pinVertexCount": len(pin_vertices),
        "frameStart": 1,
        "frameEnd": frame_end,
    }


def normalize_bone_weights(
    objects: list[bpy.types.Object],
    armature: bpy.types.Object,
    *,
    rigid_groups: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Remove helper groups, retain four deform bones, and normalize exactly."""
    rigid_groups = dict(rigid_groups or {})
    deform_bones = {bone.name for bone in armature.data.bones if bone.use_deform}
    report: dict[str, object] = {
        "objects": 0,
        "vertices": 0,
        "rigidObjects": [],
        "fallbackVertices": 0,
        "maximumInfluences": 0,
    }
    for obj in objects:
        if obj.type != "MESH":
            continue
        report["objects"] += 1
        report["vertices"] += len(obj.data.vertices)
        rigid = rigid_groups.get(obj.name)
        if rigid:
            obj.vertex_groups.clear()
            group = obj.vertex_groups.new(name=rigid)
            group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
            report["rigidObjects"].append({"object": obj.name, "bone": rigid})
            report["maximumInfluences"] = max(report["maximumInfluences"], 1)
            continue

        names = {group.index: group.name for group in obj.vertex_groups}
        assignments: list[list[tuple[str, float]]] = []
        used_names: set[str] = set()
        for vertex in obj.data.vertices:
            weighted = [
                (names[item.group], float(item.weight))
                for item in vertex.groups
                if names.get(item.group) in deform_bones and item.weight > 1e-8
            ]
            weighted.sort(key=lambda item: item[1], reverse=True)
            weighted = weighted[:4]
            if not weighted:
                world_z = (obj.matrix_world @ vertex.co).z
                fallback = "Chest" if world_z > 0.86 else "Hips"
                weighted = [(fallback, 1.0)]
                report["fallbackVertices"] += 1
            total = sum(weight for _, weight in weighted)
            normalized = [(name, weight / total) for name, weight in weighted]
            assignments.append(normalized)
            used_names.update(name for name, _ in normalized)
            report["maximumInfluences"] = max(
                report["maximumInfluences"], len(normalized)
            )

        obj.vertex_groups.clear()
        new_indices = {
            name: obj.vertex_groups.new(name=name).index for name in sorted(used_names)
        }
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        deform_layer = bm.verts.layers.deform.verify()
        for vertex in bm.verts:
            deform = vertex[deform_layer]
            deform.clear()
            for name, weight in assignments[vertex.index]:
                deform[new_indices[name]] = weight
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)
    return report


def render_prone_pose(
    armature: bpy.types.Object,
    camera: bpy.types.Object,
    output: Path,
) -> Path:
    """Render a truly horizontal body orientation, then restore object state."""
    g.configure_render(1024)
    g.reset_pose(armature)
    original_location = armature.location.copy()
    original_rotation = armature.rotation_euler.copy()
    original_mode = armature.rotation_mode
    g.rotate(armature, "UpperArm_L", (-15, 0, -28))
    g.rotate(armature, "UpperArm_R", (-15, 0, 28))
    g.rotate(armature, "LowerArm_L", (0, 0, -12))
    g.rotate(armature, "LowerArm_R", (0, 0, 12))
    g.rotate(armature, "UpperLeg_L", (-5, 0, -3))
    g.rotate(armature, "UpperLeg_R", (5, 0, 3))
    armature.rotation_mode = "XYZ"
    armature.rotation_euler = (0.0, math.radians(90.0), 0.0)
    armature.location = (-0.52, 0.0, 0.64)
    bpy.context.view_layer.update()
    camera.data.ortho_scale = 1.55
    g.point_camera(camera, (0.0, -2.75, 0.64), target=(0.0, 0.0, 0.64))
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    armature.location = original_location
    armature.rotation_mode = original_mode
    armature.rotation_euler = original_rotation
    g.reset_pose(armature)
    bpy.context.view_layer.update()
    camera.data.ortho_scale = 1.30
    return output


def clean_meshes(objects: list[bpy.types.Object]) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-7, edges=list(bm.edges))
        loose = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        if bm.faces:
            bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)


def write_prefabs(
    fbx: Path,
    outfit_prefab: Path,
    integrated_prefab: Path,
    name: str,
) -> list[Path]:
    fbx_guid = uuid.uuid4().hex
    outputs: list[Path] = []
    fbx_meta = fbx.with_suffix(fbx.suffix + ".meta")
    fbx_meta.write_text(
        f"""fileFormatVersion: 2
guid: {fbx_guid}
ModelImporter:
  serializedVersion: 22200
  materials:
    materialImportMode: 1
  meshes:
    globalScale: 1
    meshCompression: 0
    importBlendShapes: 1
    weldVertices: 1
    preserveHierarchy: 1
    maxBonesPerVertex: 4
    minBoneWeight: 0.001
  importAnimation: 0
  animationType: 2
  userData: image2outfit tuxedo halter layered dress
""",
        encoding="utf-8",
    )
    outputs.append(fbx_meta)
    for path, object_name in (
        (outfit_prefab, name),
        (integrated_prefab, f"Siroino _Large + {name}"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1001 &1001000000000000
PrefabInstance:
  m_ObjectHideFlags: 0
  serializedVersion: 2
  m_Modification:
    serializedVersion: 3
    m_TransformParent: {{fileID: 0}}
    m_Modifications:
    - target: {{fileID: 100000, guid: {fbx_guid}, type: 3}}
      propertyPath: m_Name
      value: {object_name}
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
    m_RemovedGameObjects: []
    m_AddedGameObjects: []
    m_AddedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {fbx_guid}, type: 3}}
""",
            encoding="utf-8",
        )
        meta = path.with_suffix(path.suffix + ".meta")
        meta.write_text(
            f"""fileFormatVersion: 2
guid: {uuid.uuid4().hex}
PrefabImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
""",
            encoding="utf-8",
        )
        outputs.extend([path, meta])
    return outputs
