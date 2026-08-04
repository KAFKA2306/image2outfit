#!/usr/bin/env python3
"""v20 product entrypoint for semantic five-opening topology."""

from __future__ import annotations

import siroino_heather_hooded_pattern_v14 as pattern
import siroino_heather_hooded_product as product

product.pattern = pattern
product.DESIGN_REVISION = pattern.DESIGN_REVISION
product.REJECTED_REVISIONS.append(
    {
        "revision": "v19-topology-healed-weighted-shell",
        "reason": (
            "hosted Blender completed and restored three complement components, "
            "but actual five-view evidence showed a shirt-like lower hem instead of "
            "two high-cut leg openings, hip fins and a body-intersecting rolled hood; "
            "all six evaluated poses failed, including 3066 shell overlap pairs in "
            "arms-up and 2155 in prone"
        ),
    }
)


def main() -> int:
    return product.main()


if __name__ == "__main__":
    raise SystemExit(main())
