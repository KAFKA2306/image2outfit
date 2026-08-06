#!/usr/bin/env python3
"""Canonical stable entrypoint for the SiroinoSotai_PC blue happi build."""

from __future__ import annotations

from siroino_blue_happi_v2_build import main

# Product jobs bind only to this unversioned entrypoint; iterations remain internal.


if __name__ == "__main__":
    raise SystemExit(main())
