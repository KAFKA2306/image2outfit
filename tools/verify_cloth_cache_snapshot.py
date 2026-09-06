#!/usr/bin/env python3
"""Reopen a baked Blender cloth snapshot and verify its actual point caches."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.cloth_evidence import validate_reopened_cloth_evidence
from tuxedo_halter_runtime import mesh_geometry_sha256


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--result", required=True)
    return parser.parse_args(raw)


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite_extent(obj: bpy.types.Object) -> tuple[bool, float]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        coords = [
            float(value)
            for vertex in mesh.vertices
            for value in vertex.co
        ]
        finite = bool(coords) and all(math.isfinite(value) for value in coords)
        if not finite:
            return False, 0.0
        xs = coords[0::3]
        ys = coords[1::3]
        zs = coords[2::3]
        extent = max(
            max(xs) - min(xs),
            max(ys) - min(ys),
            max(zs) - min(zs),
        )
        return True, extent
    finally:
        evaluated.to_mesh_clear()


def main() -> int:
    args = parse_args()
    report_path = Path(args.report).resolve()
    snapshot_path = Path(args.snapshot).resolve()
    result_path = Path(args.result).resolve()
    report = read_object(report_path)
    if snapshot_path != Path(bpy.data.filepath).resolve():
        raise ValueError(
            f"opened Blender file does not match requested snapshot: "
            f"{bpy.data.filepath} != {snapshot_path}"
        )

    objects = []
    for contract in report.get("contracts", []):
        name = contract["object"]
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise ValueError(f"cloth object is missing after reopen: {name}")
        modifier = obj.modifiers.get(str(contract["modifier"]))
        if modifier is None or modifier.type != "CLOTH":
            raise ValueError(f"cloth modifier is missing after reopen: {name}")
        cache = modifier.point_cache
        frames = sorted(int(frame) for frame in contract["frameMeshSha256"])
        reopened_hashes: dict[str, str] = {}
        maximum_extent = 0.0
        finite = True
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            reopened_hashes[str(frame)] = mesh_geometry_sha256(obj, evaluated=True)
            frame_finite, extent = finite_extent(obj)
            finite = finite and frame_finite
            maximum_extent = max(maximum_extent, extent)
        objects.append(
            {
                "object": name,
                "modifier": modifier.name,
                "cacheBakedActual": bool(cache.is_baked),
                "frameStart": int(cache.frame_start),
                "frameEnd": int(cache.frame_end),
                "frameMeshSha256": reopened_hashes,
                "finiteGeometry": finite,
                "maximumExtentM": maximum_extent,
            }
        )

    evidence = {
        "schemaVersion": 1,
        "productId": report["productId"],
        "candidateId": report.get("candidateId"),
        "variantId": report.get("variantId"),
        "applicability": report["applicability"],
        "cacheSnapshotSha256": sha256(snapshot_path),
        "objects": objects,
    }
    evidence["validation"] = validate_reopened_cloth_evidence(report, evidence)
    evidence["status"] = "PASS"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
