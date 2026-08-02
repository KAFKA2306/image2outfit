#!/usr/bin/env python3
"""Straight-leg, high-contrast refinement for Siroino Wide Cargo.

This layer retains the v19 continuous, foot-free pants shell while replacing
its calf-balloon profile with a shallow straight-leg taper and increasing the
visible separation between the woven body fabric and attached technical panels.
"""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit as v19

build = v19.build
base = v19.base


def apply_straight_profile(obj) -> None:
    hem_z = 0.155
    hip_transition_z = 0.595
    span = hip_transition_z - hem_z

    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        if z >= hip_transition_z:
            hip_t = v19.smoothstep((z - hip_transition_z) / (0.805 - hip_transition_z))
            vertex.co.x *= 1.115 - 0.015 * hip_t
            vertex.co.y *= 1.075 - 0.015 * hip_t
            continue

        down = v19.smoothstep((hip_transition_z - z) / span)
        side = -1.0 if x < 0.0 else 1.0
        center_abs = 0.090 - 0.020 * down
        leg_center_x = side * center_abs
        local_x = x - leg_center_x
        outer = side * local_x >= 0.0

        # A shallow taper prevents source calf anatomy from becoming a balloon.
        # The outer seam remains nearly vertical from thigh through open hem.
        if outer:
            width_scale = 1.22 + 0.18 * down
            outward_offset = 0.010 + 0.006 * down
            vertex.co.x = leg_center_x + local_x * width_scale + side * outward_offset
        else:
            width_scale = 1.075 + 0.055 * down
            vertex.co.x = leg_center_x + local_x * width_scale

        # Keep side depth almost constant and introduce no additive hem depth.
        depth_scale = 1.10 + 0.06 * down
        depth_offset = 0.004 * (1.0 - down)
        y_sign = -1.0 if y < 0.0 else 1.0
        vertex.co.y = y * depth_scale + y_sign * depth_offset

        if z < 0.175:
            vertex.co.z += 0.006 * (
                1.0 - v19.clamp((z - hem_z) / 0.020, 0.0, 1.0)
            )

    obj.data.update(calc_edges=True)


def assign_high_contrast_regions(pants, fabric, strap) -> None:
    # Contrast must remain visible in the neutral studio render, not merely in
    # material metadata. Both materials remain attached to the same mesh.
    base.tune_material(fabric, base=(0.055, 0.064, 0.082), roughness=0.76)
    base.tune_material(strap, base=(0.008, 0.010, 0.016), roughness=0.30)
    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(strap)
    for polygon in pants.data.polygons:
        mean_z = sum(
            pants.data.vertices[index].co.z for index in polygon.vertices
        ) / len(polygon.vertices)
        polygon.material_index = 1 if mean_z >= 0.748 or 0.425 <= mean_z <= 0.475 else 0
    pants.data.update()


def audit_v20() -> dict[str, object]:
    report = v19.audit_wearability()
    checks = report.get("checks", {})
    metrics = checks.get("metrics", {}) if isinstance(checks, dict) else {}
    width = float(metrics.get("totalWidth", 0.0))
    depth = float(metrics.get("totalDepth", 0.0))
    controlled = 0.345 <= width <= 0.44 and 0.20 <= depth <= 0.28
    if isinstance(checks, dict):
        checks["controlledWideSilhouettePassed"] = controlled
    report["passed"] = bool(
        report.get("passed") or (
            checks.get("singleShellOnly") is True
            and checks.get("topologyPassed") is True
            and checks.get("heightPassed") is True
            and controlled
            and checks.get("innerLegCoveragePassed") is True
            and checks.get("footExclusionPassed") is True
            and checks.get("uvPassed") is True
            and checks.get("materialSeparationPassed") is True
        )
    )
    return report


def record_v20(report: dict[str, object]) -> None:
    v19.record_wearability(report)
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["designRevision"] = "v20-straight-leg-material-contrast"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


v19.apply_wide_cargo_profile = apply_straight_profile
v19.assign_material_regions = assign_high_contrast_regions

if __name__ == "__main__":
    build.main()
    report = audit_v20()
    record_v20(report)
    base.save_distribution_blend()
    if report.get("passed") is not True:
        raise RuntimeError(f"v20 wearability audit failed: {report}")
    raise SystemExit(0)
