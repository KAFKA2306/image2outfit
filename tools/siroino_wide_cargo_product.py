#!/usr/bin/env python3
"""Stable product entrypoint for the current Siroino Wide Cargo implementation."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

IMPLEMENTATION_PATH = ROOT / "tools/siroino_wide_cargo_current.py"


def load_implementation() -> ModuleType:
    if not IMPLEMENTATION_PATH.is_file():
        raise FileNotFoundError(
            f"Wide Cargo implementation missing: {IMPLEMENTATION_PATH}"
        )
    name = "siroino_wide_cargo_current"
    spec = importlib.util.spec_from_file_location(name, IMPLEMENTATION_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(
            f"cannot load Wide Cargo implementation: {IMPLEMENTATION_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    implementation = load_implementation()
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
