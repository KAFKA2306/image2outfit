#!/usr/bin/env python3
"""Siroino Wide Cargo production entrypoint using panel-derived contours."""

from __future__ import annotations

import math

import siroino_wide_cargo_baseline as baseline


def _panel_contour_points(
    *,
    centre_x: float,
    half_width: float,
    z: float,
    count: int,
) -> list[tuple[float, float, float]]:
    """Build front/back panel curves that meet at outseam and inseam."""
    if count < 8 or count % 4 != 0:
        raise ValueError("Wide Cargo panel contour needs a multiple of four points")

    front_depth = baseline._profile_value(z, baseline.FRONT_DEPTH)
    rear_depth = baseline._profile_value(z, baseline.REAR_DEPTH)
    exponent = 0.72
    points = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        cosine = math.cos(angle)
        sine = math.sin(angle)
        x = centre_x + half_width * math.copysign(abs(cosine) ** exponent, cosine)
        depth = rear_depth if sine >= 0.0 else front_depth
        y = depth * math.copysign(abs(sine) ** exponent, sine)
        points.append((x, y, z))
    return points


def main() -> int:
    baseline._circumferential_points = _panel_contour_points
    return baseline.main()


if __name__ == "__main__":
    raise SystemExit(main())
