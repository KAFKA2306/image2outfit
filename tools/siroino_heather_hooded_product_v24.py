#!/usr/bin/env python3
"""v24 product entrypoint with post-LoBoFit surface repair."""

from __future__ import annotations

import siroino_heather_hooded_product as base
import siroino_heather_smooth_surface_repair as repair

repair.install(base.pattern)
base.DESIGN_REVISION = base.pattern.DESIGN_REVISION


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
