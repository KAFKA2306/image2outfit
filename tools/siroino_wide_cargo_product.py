#!/usr/bin/env python3
"""Stable product entrypoint for Siroino Wide Cargo."""
from __future__ import annotations

import runpy


if __name__ == "__main__":
    runpy.run_module("siroino_wide_cargo_release_refit_v23", run_name="__main__")
