#!/usr/bin/env python3
"""Stable product entrypoint for the current Siroino Wide Cargo implementation."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_parametric_v36 as implementation


def main() -> int:
    implementation.clear_stale_evidence()
    implementation.build.main()
    result = implementation.audit()
    implementation.record(result)
    implementation.base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"Wide Cargo audit failed: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
