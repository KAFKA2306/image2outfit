#!/usr/bin/env python3
"""Blender entrypoint for the rear-safe Siroino Wide Cargo v24 build."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v24 as impl


if __name__ == "__main__":
    impl.build.main()
    result = impl.audit()
    impl.record(result)
    impl.base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"v24 rear coverage audit failed: {result}")
    raise SystemExit(0)
