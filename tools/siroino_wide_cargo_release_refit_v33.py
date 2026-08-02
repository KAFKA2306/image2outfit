#!/usr/bin/env python3
"""Execute the v32 visual refit without duplicate profile application."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v32 as v32


def create_outfit(body, armature, fabric, strap, metal):
    del metal
    pants = v32.build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        v32.previous.pants_surface,
        fabric,
        0.011,
    )
    v32.fit_waist_and_drape(pants)
    v32.build.clean_topology(pants)
    flattened = v32.flatten_hem_boundaries(pants)
    subdivided = v32.subdivide_long_interior_edges(pants)
    v32.unwrap_uv(pants)
    v32.assign_materials(pants, fabric, strap)
    pants["flattened_hem_boundaries"] = flattened
    pants["subdivided_long_interior_edges"] = subdivided
    pants["removed_stretched_faces"] = 0
    return [pants]


v32.build.create_outfit = create_outfit


if __name__ == "__main__":
    v32.clear_stale_render_evidence()
    v32.build.main()
    result = v32.audit()
    v32.record(result)
    v32.base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v33 single-profile visual audit failed: {result}")
    raise SystemExit(0)
