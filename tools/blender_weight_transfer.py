"""Blender Stage 09 baseline adapter for deterministic garment weight transfer.

Run with Blender, for example::

    blender --background garment.blend --python tools/blender_weight_transfer.py -- \
      --product-id example --source Body --target Garment --armature Armature \
      --output reports/weight-transfer.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.weight_transfer import (  # noqa: E402
    WeightTransferArtifact,
    WeightTransferMethod,
    WeightTransferPolicy,
    constrain_vertex_weights,
)

_MAPPING = {
    "nearest-face-interpolated": "POLYINTERP_NEAREST",
    "nearest-face": "POLY_NEAREST",
    "nearest-vertex": "NEAREST",
}


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transfer body vertex groups to garment meshes and audit them."
    )
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--source", required=True, help="Source body mesh object")
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        help="Target garment mesh object; repeat for multiple garment objects",
    )
    parser.add_argument("--armature", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mapping",
        choices=tuple(_MAPPING),
        default="nearest-face-interpolated",
    )
    parser.add_argument("--max-distance", type=float, default=0.0)
    parser.add_argument("--max-influences", type=int, default=4)
    parser.add_argument("--minimum-weight", type=float, default=1e-8)
    parser.add_argument("--normalization-tolerance", type=float, default=1e-5)
    parser.add_argument(
        "--laterality-contamination-limit",
        type=float,
        default=0.05,
    )
    parser.add_argument(
        "--laterality-axis",
        choices=("X", "Y", "Z"),
        default="X",
    )
    parser.add_argument("--laterality-center-tolerance", type=float, default=0.001)
    parser.add_argument(
        "--left-positive",
        action="store_true",
        help="Treat positive coordinates as left; default treats negative as left",
    )
    parser.add_argument(
        "--allow-unapplied-transforms",
        action="store_true",
        help="Permit non-unit scale or non-zero rotation on source/targets",
    )
    parser.add_argument(
        "--save-blend",
        type=Path,
        help="Optionally save the modified Blender file",
    )
    return parser.parse_args(argv)


def _script_argv() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _require_bpy():
    try:
        import bpy
    except ImportError as exc:  # pragma: no cover - executed only outside Blender
        raise RuntimeError(
            "blender_weight_transfer.py must run inside Blender"
        ) from exc
    return bpy


def _object(bpy, name: str, expected_type: str):
    item = bpy.data.objects.get(name)
    if item is None:
        raise ValueError(f"Blender object not found: {name}")
    if item.type != expected_type:
        raise ValueError(
            f"Blender object {name!r} must be {expected_type}, got {item.type}"
        )
    return item


def _transforms_applied(item) -> bool:
    scale_ok = all(abs(float(value) - 1.0) <= 1e-6 for value in item.scale)
    rotation_ok = all(abs(float(value)) <= 1e-6 for value in item.rotation_euler)
    return scale_ok and rotation_ok


def _mesh_hash(item) -> str:
    digest = hashlib.sha256()
    digest.update(item.name.encode("utf-8"))
    for value in item.matrix_world:
        for scalar in value:
            digest.update(format(float(scalar), ".17g").encode("ascii"))
            digest.update(b",")
    for vertex in item.data.vertices:
        digest.update(str(vertex.index).encode("ascii"))
        for scalar in vertex.co:
            digest.update(format(float(scalar), ".17g").encode("ascii"))
            digest.update(b",")
    for polygon in item.data.polygons:
        digest.update(b"|")
        for index in polygon.vertices:
            digest.update(str(int(index)).encode("ascii"))
            digest.update(b",")
    return digest.hexdigest()


def _armature_hash(armature, *, include_bind_pose: bool) -> str:
    digest = hashlib.sha256()
    digest.update(armature.name.encode("utf-8"))
    for bone in sorted(armature.data.bones, key=lambda value: value.name):
        digest.update(bone.name.encode("utf-8"))
        digest.update(b"1" if bone.use_deform else b"0")
        digest.update((bone.parent.name if bone.parent else "").encode("utf-8"))
        if include_bind_pose:
            for row in bone.matrix_local:
                for scalar in row:
                    digest.update(format(float(scalar), ".17g").encode("ascii"))
                    digest.update(b",")
    return digest.hexdigest()


def _bone_laterality(name: str) -> str:
    lowered = name.lower()
    left_tokens = (".l", "_l", "-l", "left")
    right_tokens = (".r", "_r", "-r", "right")
    if lowered.endswith(left_tokens) or "left" in lowered:
        return "left"
    if lowered.endswith(right_tokens) or "right" in lowered:
        return "right"
    return "center"


def _expected_laterality(
    target,
    *,
    axis: str,
    center_tolerance: float,
    left_positive: bool,
) -> dict[int, str]:
    axis_index = {"X": 0, "Y": 1, "Z": 2}[axis]
    expected: dict[int, str] = {}
    for vertex in target.data.vertices:
        coordinate = float(vertex.co[axis_index])
        if abs(coordinate) <= center_tolerance:
            expected[vertex.index] = "center"
            continue
        positive_side = "left" if left_positive else "right"
        negative_side = "right" if left_positive else "left"
        expected[vertex.index] = positive_side if coordinate > 0 else negative_side
    return expected


def _activate(bpy, item) -> None:
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    item.select_set(True)
    bpy.context.view_layer.objects.active = item


def _apply_data_transfer(
    bpy,
    *,
    source,
    target,
    mapping: str,
    max_distance: float,
) -> None:
    _activate(bpy, target)
    modifier = target.modifiers.new(
        name="Image2OutfitWeightTransfer",
        type="DATA_TRANSFER",
    )
    modifier.object = source
    modifier.use_vert_data = True
    modifier.data_types_verts = {"VGROUP_WEIGHTS"}
    modifier.vert_mapping = _MAPPING[mapping]
    modifier.layers_vgroup_select_src = "ALL"
    modifier.layers_vgroup_select_dst = "NAME"
    modifier.mix_mode = "REPLACE"
    modifier.mix_factor = 1.0
    if max_distance > 0.0:
        modifier.use_max_distance = True
        modifier.max_distance = max_distance
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def _read_weights(target) -> dict[int, list[tuple[str, float]]]:
    group_names = {group.index: group.name for group in target.vertex_groups}
    return {
        vertex.index: [
            (group_names[item.group], float(item.weight))
            for item in vertex.groups
            if item.group in group_names
        ]
        for vertex in target.data.vertices
    }


def _write_weights(target, weights) -> None:
    vertex_indices = [vertex.index for vertex in target.data.vertices]
    for group in target.vertex_groups:
        group.remove(vertex_indices)
    groups = {group.name: group for group in target.vertex_groups}
    for vertex_index, influences in weights.items():
        for influence in influences:
            group = groups.get(influence.bone)
            if group is None:
                group = target.vertex_groups.new(name=influence.bone)
                groups[influence.bone] = group
            group.add([vertex_index], influence.weight, "REPLACE")


def _ensure_armature_modifier(target, armature) -> None:
    for modifier in target.modifiers:
        if modifier.type == "ARMATURE" and modifier.object == armature:
            return
    modifier = target.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def execute(args: argparse.Namespace) -> dict[str, Any]:
    bpy = _require_bpy()
    if not math.isfinite(args.max_distance) or args.max_distance < 0.0:
        raise ValueError("--max-distance must be finite and non-negative")
    if (
        not math.isfinite(args.laterality_center_tolerance)
        or args.laterality_center_tolerance < 0.0
    ):
        raise ValueError(
            "--laterality-center-tolerance must be finite and non-negative"
        )

    source = _object(bpy, args.source, "MESH")
    armature = _object(bpy, args.armature, "ARMATURE")
    targets = [_object(bpy, name, "MESH") for name in args.target]
    if not source.vertex_groups:
        raise ValueError("source body mesh has no vertex groups")

    if not args.allow_unapplied_transforms:
        pending = [
            item.name
            for item in (source, armature, *targets)
            if not _transforms_applied(item)
        ]
        if pending:
            raise ValueError(
                "apply scale and rotation before weight transfer: " + ", ".join(pending)
            )

    policy = WeightTransferPolicy(
        max_influences=args.max_influences,
        minimum_weight=args.minimum_weight,
        normalization_tolerance=args.normalization_tolerance,
        laterality_contamination_limit=args.laterality_contamination_limit,
    )
    deform_bones = {bone.name for bone in armature.data.bones if bone.use_deform}
    left_bones = {name for name in deform_bones if _bone_laterality(name) == "left"}
    right_bones = {name for name in deform_bones if _bone_laterality(name) == "right"}
    armature_hash = _armature_hash(armature, include_bind_pose=False)
    bind_pose_hash = _armature_hash(armature, include_bind_pose=True)
    source_hash = _mesh_hash(source)
    artifacts: list[dict[str, Any]] = []

    for target in targets:
        target_hash = _mesh_hash(target)
        _apply_data_transfer(
            bpy,
            source=source,
            target=target,
            mapping=args.mapping,
            max_distance=args.max_distance,
        )
        result = constrain_vertex_weights(
            _read_weights(target),
            deform_bones=deform_bones,
            policy=policy,
            expected_laterality=_expected_laterality(
                target,
                axis=args.laterality_axis,
                center_tolerance=args.laterality_center_tolerance,
                left_positive=args.left_positive,
            ),
            left_bones=left_bones,
            right_bones=right_bones,
        )
        _write_weights(target, result.weights)
        _ensure_armature_modifier(target, armature)
        artifact = WeightTransferArtifact(
            source_mesh_hash=source_hash,
            target_mesh_hash=target_hash,
            armature_hash=armature_hash,
            bind_pose_hash=bind_pose_hash,
            method=WeightTransferMethod.BLENDER_DATA_TRANSFER,
            method_version=bpy.app.version_string,
            parameters={
                "mapping": args.mapping,
                "maxDistance": args.max_distance,
                "maxInfluences": args.max_influences,
                "minimumWeight": args.minimum_weight,
                "normalizationTolerance": args.normalization_tolerance,
                "lateralityContaminationLimit": (args.laterality_contamination_limit),
                "lateralityAxis": args.laterality_axis,
                "lateralityCenterTolerance": args.laterality_center_tolerance,
                "leftPositive": args.left_positive,
            },
            result=result,
        )
        artifacts.append(
            {
                "targetObject": target.name,
                "artifactDigest": artifact.digest(),
                **artifact.to_dict(),
            }
        )

    status = (
        "PASS" if all(artifact["audit"]["passed"] for artifact in artifacts) else "FAIL"
    )
    payload = {
        "schemaVersion": 1,
        "kind": "weight-transfer-batch",
        "stage": "skin-and-export",
        "productId": args.product_id,
        "status": status,
        "method": WeightTransferMethod.BLENDER_DATA_TRANSFER.value,
        "sourceObject": source.name,
        "armatureObject": armature.name,
        "artifacts": artifacts,
    }
    _write_json(args.output, payload)
    if args.save_blend:
        args.save_blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.save_blend.resolve()))
    return payload


def main() -> int:
    args = _arguments(_script_argv())
    payload = execute(args)
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
