#!/usr/bin/env python3
"""Cloth, pose, cleanup, and Unity declaration helpers for tuxedo halter."""

from __future__ import annotations

import uuid
from pathlib import Path

import bmesh
import bpy

import genworks_product_common as g


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
    cloth.settings.quality = 6
    cloth.settings.mass = 0.22
    cloth.settings.tension_stiffness = 18.0
    cloth.settings.compression_stiffness = 18.0
    cloth.settings.shear_stiffness = 7.0
    cloth.settings.bending_stiffness = 0.55
    cloth.settings.air_damping = 2.0
    cloth.settings.vertex_group_mass = pin.name
    cloth.settings.pin_stiffness = 0.95
    cloth.collision_settings.use_collision = True
    cloth.collision_settings.collision_quality = 4
    cloth.collision_settings.distance_min = 0.003
    cloth.point_cache.frame_start = 1
    cloth.point_cache.frame_end = frame_end
    return {
        "object": skirt.name,
        "modifier": cloth.name,
        "pinVertexCount": len(pin_vertices),
        "frameStart": 1,
        "frameEnd": frame_end,
    }


def render_prone_pose(
    armature: bpy.types.Object,
    camera: bpy.types.Object,
    output: Path,
) -> Path:
    g.configure_render(1024)
    g.reset_pose(armature)
    g.rotate(armature, "Hips", (0, 88, 0))
    g.rotate(armature, "UpperArm_L", (-18, 0, -32))
    g.rotate(armature, "UpperArm_R", (-18, 0, 32))
    g.rotate(armature, "LowerArm_L", (0, 0, -18))
    g.rotate(armature, "LowerArm_R", (0, 0, 18))
    g.rotate(armature, "UpperLeg_L", (-8, 0, -5))
    g.rotate(armature, "UpperLeg_R", (8, 0, 5))
    camera.data.ortho_scale = 1.55
    g.point_camera(camera, (0.0, -2.75, 0.68), target=(0.0, 0.0, 0.64))
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    g.reset_pose(armature)
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
