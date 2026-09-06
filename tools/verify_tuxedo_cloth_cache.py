#!/usr/bin/env python3
"""Reopen a baked cloth blend and verify persisted cache geometry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

from tuxedo_halter_runtime import cloth_cache_state, mesh_geometry_sha256


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True)
    parser.add_argument("--result", required=True)
    return parser.parse_args(raw)


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def main() -> int:
    args = parse_args()
    expected_path = Path(args.expected).resolve()
    result_path = Path(args.result).resolve()
    expected = read_json(expected_path)
    scene = bpy.context.scene
    verified: dict[str, object] = {}

    objects = expected.get("objects")
    if not isinstance(objects, dict) or not objects:
        raise ValueError("expected cloth objects are missing")

    for object_name, raw in objects.items():
        if not isinstance(object_name, str) or not isinstance(raw, dict):
            raise ValueError("expected cloth object entry is invalid")
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            raise RuntimeError(f"reopened cloth object is missing: {object_name}")
        modifier_name = str(raw.get("modifier", "Reference Cloth"))
        cache = cloth_cache_state(obj, modifier_name)
        if cache["cacheBakedActual"] is not True:
            raise RuntimeError(f"reopened cloth cache is not baked: {object_name}")

        raw_frames = raw.get("frames")
        if not isinstance(raw_frames, dict) or not raw_frames:
            raise ValueError(f"expected frame hashes are missing: {object_name}")
        frame_results: dict[str, object] = {}
        for label, frame_record in raw_frames.items():
            if not isinstance(frame_record, dict):
                raise ValueError(f"invalid frame record: {object_name}/{label}")
            frame = int(frame_record["frame"])
            expected_hash = str(frame_record["sha256"])
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            actual_hash = mesh_geometry_sha256(obj, evaluated=True)
            if actual_hash != expected_hash:
                raise RuntimeError(
                    "reopened cloth geometry mismatch: "
                    f"{object_name}/{label} {actual_hash} != {expected_hash}"
                )
            frame_results[str(label)] = {
                "frame": frame,
                "sha256": actual_hash,
            }

        verified[object_name] = {
            "cache": cache,
            "frames": frame_results,
        }

    result = {
        "schemaVersion": 1,
        "status": "PASS",
        "blend": bpy.data.filepath,
        "objects": verified,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
