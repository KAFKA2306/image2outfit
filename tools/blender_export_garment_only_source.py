#!/usr/bin/env python3
"""Write a garment-only editable Blender source from a weighted prototype.

The input may contain the target avatar as a temporary measurement/weighting
reference. The exported source retains only weighted garment meshes and named
vertex groups, removing avatar geometry, rig objects, and linked image assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
GARMENT_ROLES = {"weighted-unfit-sewn-prototype"}
PRIVATE_ROLE = "target-avatar-reference-only"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_path(value: str) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {value}")
    return resolved


def require_local_workline(path: Path, product_id: str, label: str) -> None:
    workline = (ROOT / ".image2outfit" / "products" / product_id / "workline").resolve()
    if path != workline and workline not in path.parents:
        raise ValueError(f"{label} must remain in the product's local workline: {path}")


def require_product_source(path: Path, product_id: str, label: str) -> None:
    source_root = (ROOT / "Assets" / "GenWorks" / product_id / "Source" / "Blender").resolve()
    if path.parent != source_root or path.suffix.lower() != ".blend":
        raise ValueError(f"{label} must be one .blend directly under {source_root}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--allow-product-source-output", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])

    source = repo_path(args.source)
    output = repo_path(args.output)
    report_path = repo_path(args.report)
    if args.allow_product_source_output:
        require_product_source(output, args.product_id, "output")
    else:
        require_local_workline(output, args.product_id, "output")
    require_local_workline(report_path, args.product_id, "report")
    if not source.is_file():
        raise FileNotFoundError(f"weighted garment source is missing: {args.source}")
    if source == output or source == report_path or output == report_path:
        raise ValueError("source, output, and report paths must be distinct")

    source_hash = sha256(source)
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    # Inspect every datablock object, not just the active scene: hidden or
    # alternate-scene avatar objects must not survive in the saved project.
    scene_objects = list(bpy.data.objects)
    garment_meshes = [
        obj
        for obj in scene_objects
        if obj.type == "MESH" and obj.get("prototypeRole") in GARMENT_ROLES
    ]
    reference_meshes = [
        obj
        for obj in scene_objects
        if obj.type == "MESH" and obj.get("prototypeRole") == PRIVATE_ROLE
    ]
    unknown_meshes = [
        obj
        for obj in scene_objects
        if obj.type == "MESH" and obj.get("prototypeRole") not in GARMENT_ROLES | {PRIVATE_ROLE}
    ]
    if not garment_meshes:
        raise ValueError("no weighted garment meshes matched the allowlisted role")
    if not reference_meshes:
        raise ValueError("input did not contain the declared target-avatar reference mesh")
    if unknown_meshes:
        raise ValueError(
            "refusing to export unclassified mesh objects: "
            + ", ".join(obj.name for obj in unknown_meshes)
        )

    garment_names = sorted(obj.name for obj in garment_meshes)
    removed_names = sorted(obj.name for obj in reference_meshes)
    removed_object_count = sum(1 for obj in scene_objects if obj not in garment_meshes)
    for obj in scene_objects:
        if obj not in garment_meshes:
            bpy.data.objects.remove(obj, do_unlink=True)

    # Retain named vertex groups (the exported weights) but remove links to the
    # private avatar rig. Customers bind the garment to their own licensed rig.
    for obj in garment_meshes:
        for modifier in list(obj.modifiers):
            if modifier.type == "ARMATURE":
                obj.modifiers.remove(modifier)

    # Removing a Blender object can leave its mesh datablock orphaned. Purge all
    # unused mesh datablocks before saving, then verify the saved file itself.
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    remaining_meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    remaining_non_meshes = [obj.name for obj in bpy.data.objects if obj.type != "MESH"]
    if (
        len(remaining_meshes) != len(garment_meshes)
        or remaining_non_meshes
        or any(obj.get("prototypeRole") not in GARMENT_ROLES for obj in remaining_meshes)
    ):
        raise ValueError("garment-only source validation failed after reference removal")

    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    if not output.is_file():
        raise FileNotFoundError("Blender did not write the garment-only source")

    bpy.ops.wm.open_mainfile(filepath=str(output), load_ui=False)
    saved_scene_meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    saved_non_garment_objects = [obj.name for obj in bpy.data.objects if obj.type != "MESH"]
    saved_orphan_meshes = [mesh.name for mesh in bpy.data.meshes if mesh.users == 0]
    saved_referenced_images = [
        image.name for image in bpy.data.images if image.name != "Render Result"
    ]
    saved_libraries = [library.filepath for library in bpy.data.libraries]
    saved_armature_datablocks = len(bpy.data.armatures)
    saved_weight_assignments = sum(
        len(vertex.groups)
        for obj in saved_scene_meshes
        for vertex in obj.data.vertices
    )
    saved_private_meshes = [
        obj.name
        for obj in saved_scene_meshes
        if obj.get("prototypeRole") == PRIVATE_ROLE
    ]
    if (
        len(saved_scene_meshes) != len(garment_names)
        or saved_orphan_meshes
        or saved_private_meshes
        or saved_non_garment_objects
        or saved_referenced_images
        or saved_libraries
        or saved_armature_datablocks
        or saved_weight_assignments == 0
        or any(obj.get("prototypeRole") not in GARMENT_ROLES for obj in saved_scene_meshes)
        or any(modifier.type == "ARMATURE" for obj in saved_scene_meshes for modifier in obj.modifiers)
        or any(not obj.vertex_groups for obj in saved_scene_meshes)
    ):
        raise ValueError(
            "saved garment-only source failed reopen validation: "
            f"meshes={len(saved_scene_meshes)}, orphanMeshData={saved_orphan_meshes}, "
            f"avatarMeshes={saved_private_meshes}, "
            f"otherObjects={saved_non_garment_objects}, "
            f"referencedImages={saved_referenced_images}, libraries={saved_libraries}, "
            f"armatureData={saved_armature_datablocks}"
        )

    report = {
        "schemaVersion": 1,
        "productId": args.product_id,
        "status": "GARMENT_ONLY_SOURCE_WRITTEN",
        "inputPath": source.relative_to(ROOT).as_posix(),
        "inputSha256": source_hash,
        "outputPath": output.relative_to(ROOT).as_posix(),
        "outputSha256": sha256(output),
        "garmentMeshCount": len(saved_scene_meshes),
        "garmentObjectNames": garment_names,
        "removedAvatarReferenceMeshCount": len(reference_meshes),
        "removedAvatarReferenceMeshNames": removed_names,
        "removedNonGarmentObjectCount": removed_object_count - len(reference_meshes),
        "remainingMeshRoles": sorted({str(obj.get("prototypeRole")) for obj in saved_scene_meshes}),
        "savedOrphanMeshDatablocks": saved_orphan_meshes,
        "savedArmatureCount": 0,
        "savedArmatureDatablockCount": saved_armature_datablocks,
        "savedVertexWeightAssignments": saved_weight_assignments,
        "garmentVertexGroupsRetained": True,
        "avatarRigBindingRemoved": True,
        "containsAvatarReferenceGeometry": False,
        "containsReferencedImageAssets": False,
        "containsLinkedLibraries": False,
        "grantsQualityAcceptance": False,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
