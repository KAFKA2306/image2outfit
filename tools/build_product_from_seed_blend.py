#!/usr/bin/env python3
"""Build a product from a tracked armature seed and compact body snapshot.

The tracked Blender seed supplies the official Siroino armature. A compact,
quantized snapshot supplies the CC0 Siroino body with the requested Large
shape keys already baked, including vertex groups and normalized weights.
Unity integration remains a separate self-hosted gate.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import runpy
import struct
import sys
import zlib
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import bpy

ROOT = TOOLS_DIR.parent


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--seed-config")
    return parser.parse_args(raw)


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def select_seed_armature() -> bpy.types.Object:
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError("The tracked seed contains no armature")
    return max(armatures, key=lambda obj: len(obj.data.bones))


def load_snapshot(metadata_path: Path) -> tuple[dict, bytes]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    encoding = metadata.get("encoding")
    if not isinstance(encoding, dict) or encoding.get("container") != "zlib+base85":
        raise ValueError("Unsupported body snapshot encoding")
    parts = encoding.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("Body snapshot parts are missing")
    payload = "".join(repo_path(value).read_text(encoding="ascii").strip() for value in parts)
    if len(payload) != int(encoding.get("base85Length", -1)):
        raise RuntimeError("Body snapshot base85 length does not match metadata")
    compressed = base64.b85decode(payload.encode("ascii"))
    compressed_hash = hashlib.sha256(compressed).hexdigest()
    if compressed_hash != encoding.get("compressedSha256"):
        raise RuntimeError("Body snapshot compressed hash mismatch")
    raw = zlib.decompress(compressed)
    raw_hash = hashlib.sha256(raw).hexdigest()
    if raw_hash != encoding.get("rawSha256"):
        raise RuntimeError("Body snapshot raw hash mismatch")
    return metadata, raw


def reconstruct_body(
    armature: bpy.types.Object,
    metadata: dict,
    raw: bytes,
) -> bpy.types.Object:
    cursor = 0
    magic = raw[cursor : cursor + 8]
    cursor += 8
    if magic != b"SIROLG01":
        raise RuntimeError(f"Unexpected body snapshot magic: {magic!r}")
    vertex_count, triangle_count, group_count = struct.unpack_from("<III", raw, cursor)
    cursor += 12
    minimum = struct.unpack_from("<3f", raw, cursor)
    cursor += 12
    maximum = struct.unpack_from("<3f", raw, cursor)
    cursor += 12
    expected_mesh = metadata.get("mesh", {})
    if vertex_count != int(expected_mesh.get("vertices", -1)):
        raise RuntimeError("Body snapshot vertex count mismatch")
    if triangle_count != int(expected_mesh.get("triangles", -1)):
        raise RuntimeError("Body snapshot triangle count mismatch")
    groups = expected_mesh.get("vertexGroups")
    if not isinstance(groups, list) or len(groups) != group_count:
        raise RuntimeError("Body snapshot vertex group count mismatch")

    positions_q = struct.unpack_from(f"<{vertex_count * 3}H", raw, cursor)
    cursor += vertex_count * 3 * 2
    triangles_q = struct.unpack_from(f"<{triangle_count * 3}H", raw, cursor)
    cursor += triangle_count * 3 * 2
    bone_indices = raw[cursor : cursor + vertex_count * 4]
    cursor += vertex_count * 4
    bone_weights = struct.unpack_from(f"<{vertex_count * 4}H", raw, cursor)
    cursor += vertex_count * 4 * 2
    if cursor != len(raw):
        raise RuntimeError("Body snapshot contains trailing or missing bytes")

    spans = tuple(maximum[i] - minimum[i] for i in range(3))
    vertices = [
        (
            minimum[0] + spans[0] * positions_q[index * 3] / 65535.0,
            minimum[1] + spans[1] * positions_q[index * 3 + 1] / 65535.0,
            minimum[2] + spans[2] * positions_q[index * 3 + 2] / 65535.0,
        )
        for index in range(vertex_count)
    ]
    triangles = [
        (
            triangles_q[index * 3],
            triangles_q[index * 3 + 1],
            triangles_q[index * 3 + 2],
        )
        for index in range(triangle_count)
    ]

    mesh = bpy.data.meshes.new("SiroinoSotai_PC_LargeBaked_Mesh")
    mesh.from_pydata(vertices, [], triangles)
    mesh.update(calc_edges=True)
    body = bpy.data.objects.new("SiroinoSotai_PC", mesh)
    bpy.context.collection.objects.link(body)
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    missing_bones = [name for name in groups if armature.data.bones.get(name) is None]
    if missing_bones:
        raise RuntimeError(
            "Seed armature is missing body vertex-group bones: " + ", ".join(missing_bones)
        )
    vertex_groups = [body.vertex_groups.new(name=name) for name in groups]
    for vertex_index in range(vertex_count):
        for influence in range(4):
            offset = vertex_index * 4 + influence
            group_index = bone_indices[offset]
            quantized_weight = bone_weights[offset]
            if group_index == 255 or quantized_weight == 0:
                continue
            vertex_groups[group_index].add(
                [vertex_index], quantized_weight / 65535.0, "REPLACE"
            )

    body.parent = armature
    modifier = body.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True

    material = bpy.data.materials.new("MAT_Siroino_Large_Validation_Skin")
    material.use_nodes = True
    shader = next(
        node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
    )
    shader.inputs["Base Color"].default_value = (0.91, 0.72, 0.65, 1.0)
    shader.inputs["Roughness"].default_value = 0.58
    shader.inputs["Subsurface Weight"].default_value = 0.045
    mesh.materials.append(material)
    return body


def export_seed_target(body: bpy.types.Object, armature: bpy.types.Object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    body.hide_set(False)
    body.hide_render = False
    armature.hide_set(False)
    body.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(output),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        bake_space_transform=False,
        use_mesh_modifiers=False,
        mesh_smooth_type="FACE",
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        use_armature_deform_only=False,
        bake_anim=False,
        path_mode="AUTO",
        embed_textures=False,
    )
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError(f"temporary target FBX was not exported: {output}")


def main() -> int:
    args = parse_args()
    tracked_job = Path(args.job).resolve()
    seed_config_path = (
        Path(args.seed_config).resolve()
        if args.seed_config
        else tracked_job.parent / "hosted-seed.json"
    )
    job = json.loads(tracked_job.read_text(encoding="utf-8-sig"))
    seed_config = json.loads(seed_config_path.read_text(encoding="utf-8-sig"))
    seed_value = seed_config.get("targetSeedBlendPath")
    snapshot_value = seed_config.get("bodySnapshotMetadata")
    if not isinstance(seed_value, str) or not seed_value:
        raise ValueError("seed config targetSeedBlendPath is required")
    if not isinstance(snapshot_value, str) or not snapshot_value:
        raise ValueError("seed config bodySnapshotMetadata is required")
    seed = repo_path(seed_value)
    snapshot_path = repo_path(snapshot_value)
    if not seed.is_file():
        raise FileNotFoundError(f"tracked armature seed blend not found: {seed_value}")
    if not snapshot_path.is_file():
        raise FileNotFoundError(f"body snapshot metadata not found: {snapshot_value}")

    bpy.ops.wm.open_mainfile(filepath=str(seed))
    armature = select_seed_armature()
    armature.name = "SiroinoSotai_Armature"
    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    metadata, raw = load_snapshot(snapshot_path)
    body = reconstruct_body(armature, metadata, raw)

    artifact_dir = repo_path(job["artifactDir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    temporary_fbx = artifact_dir / "seed-target" / "SiroinoSotai_LargeBaked.fbx"
    export_seed_target(body, armature, temporary_fbx)

    materialized_job = dict(job)
    materialized_job["targetSourcePath"] = relative(temporary_fbx)
    materialized_job["targetAvatarAssetPath"] = "hosted-snapshot://Siroino_Large"
    materialized_job["bodyProfileAlreadyBaked"] = True
    materialized_job["resolvedTarget"] = {
        "strategy": "tracked-armature-plus-compact-body-snapshot",
        "profile": metadata["profile"]["name"],
        "shapeKeys": metadata["profile"]["shapeKeys"],
        "sourceBlendSha256": metadata["source"]["sha256"],
        "sourceObject": metadata["source"]["object"],
        "bodySnapshot": snapshot_value,
        "armatureSeed": seed_value,
        "sourceFbx": relative(temporary_fbx),
        "mesh": metadata["mesh"],
        "unityIntegration": "PENDING_SELF_HOSTED",
    }
    materialized_path = artifact_dir / "hosted-job.json"
    materialized_path.write_text(
        json.dumps(materialized_job, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "hosted-target-evidence.json").write_text(
        json.dumps(materialized_job["resolvedTarget"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    build_script_value = job.get("productBuildScript")
    if not isinstance(build_script_value, str) or not build_script_value:
        raise ValueError("job.productBuildScript is required for hosted snapshot builds")
    build_script = repo_path(build_script_value)
    if not build_script.is_file():
        raise FileNotFoundError(f"product build script not found: {build_script_value}")
    sys.argv = [str(build_script), "--", "--job", str(materialized_path)]
    try:
        runpy.run_path(str(build_script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
