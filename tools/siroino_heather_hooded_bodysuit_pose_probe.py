#!/usr/bin/env python3
"""Run the required pose audit with measured spatial diagnostics enabled."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import bpy
from mathutils.bvhtree import BVHTree

if TYPE_CHECKING:
    import siroino_heather_geometry_probe
    import siroino_heather_hooded_bodysuit_pose

ROOT = Path(__file__).resolve().parents[1]


def _load_local_module(name: str, filename: str) -> ModuleType:
    """Load one sibling module by verified path instead of ambient sys.path state."""
    path = TOOLS / filename
    if not path.is_file():
        raise RuntimeError(f"Required local pose module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create an import specification for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_local_module(
    "siroino_heather_geometry_probe",
    "siroino_heather_geometry_probe.py",
)
pose = _load_local_module(
    "siroino_heather_hooded_bodysuit_pose",
    "siroino_heather_hooded_bodysuit_pose.py",
)
_ORIGINAL_AUDIT = pose.audit_intersections


def audit_intersections(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
) -> dict:
    result = _ORIGINAL_AUDIT(body, garments)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    body_tree = BVHTree.FromObject(body, depsgraph, deform=True, cage=False)
    if body_tree is None:
        raise RuntimeError("Geometry probe could not construct the body BVH")

    by_name = {item["object"]: item for item in result["objects"]}
    for garment in garments:
        tree = BVHTree.FromObject(garment, depsgraph, deform=True, cage=False)
        overlaps = [] if tree is None else body_tree.overlap(tree)
        by_name[garment.name]["geometryDiagnostics"] = probe.overlap_diagnostics(
            garment,
            overlaps,
            armature,
            depsgraph,
        )
    result["diagnosticMethod"] = (
        "Root-local evaluated polygon centers, dominant skin weights and 5 cm "
        "overlap-pair voxels derived from the same Blender BVH overlap pairs"
    )
    return result


def write_static_diagnostics(job: dict) -> Path:
    root = ROOT / job["productRoot"]
    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    garments = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and obj != body
        and any(
            modifier.type == "ARMATURE" and modifier.object == armature
            for modifier in obj.modifiers
        )
    ]
    fit_audit_path = root / "Tests" / "fit-audit.json"
    fit_audit = json.loads(fit_audit_path.read_text(encoding="utf-8"))
    diagnostic = {
        "schemaVersion": 1,
        "designRevision": job["buildRevision"],
        "target": "SiroinoSotai_PC",
        "static": probe.static_geometry_diagnostics(body, garments, armature),
        "poses": {
            pose_name: {
                item["object"]: item.get("geometryDiagnostics")
                for item in pose_result["objects"]
                if item.get("geometryDiagnostics") is not None
            }
            for pose_name, pose_result in fit_audit["poses"].items()
        },
    }
    path = root / "Tests" / "geometry-diagnostics.json"
    path.write_text(
        json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    options = pose.args()
    job = json.loads(Path(options.job).read_text(encoding="utf-8-sig"))
    pose.audit_intersections = audit_intersections
    result = pose.main()
    diagnostic_path = write_static_diagnostics(job)
    print(json.dumps({"geometryDiagnostics": str(diagnostic_path)}, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
