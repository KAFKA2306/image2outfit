#!/usr/bin/env python3
"""Generic sewn-panel geometry builder.

This module owns the topology rules for sewn garment panels: seam-boundary
vertices, panel rows between seam boundaries, row orientation, bridging of
consecutive rows into faces, and fan-triangulated closed panels. Product
layers supply typed section and component data derived from a pattern source.
They must not create vertices or faces themselves.

The module has no Blender dependency. ``mesh`` is any object exposing
``vertices``, ``faces`` and ``add_ring`` (see ``MeshBuilder`` below).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, Union

Point = tuple[float, float, float]
DepthProfile = tuple[tuple[float, float], ...]

# Left/right side names paired with their signed x direction.
SIDES: tuple[tuple[str, float], ...] = (("left", -1.0), ("right", 1.0))
PANEL_IDS: tuple[str, ...] = (
    "front-left",
    "front-right",
    "back-left",
    "back-right",
)
AXIS_TOLERANCE = 1e-12


class PanelBuildError(ValueError):
    """Section or component data cannot form a consistent panel graph."""


class MeshBuilder:
    """Minimal mesh container used when no host mesh type is supplied."""

    def __init__(self) -> None:
        self.vertices: list[Point] = []
        self.faces: list[tuple[int, ...]] = []

    def add_ring(self, points: Sequence[Point]) -> list[int]:
        start = len(self.vertices)
        self.vertices.extend(points)
        return list(range(start, start + len(points)))


@dataclass(frozen=True)
class CentreInner:
    """Inner seam points on the garment centre line.

    The front inner point is ``(0, front_y, z)`` and the back inner point is
    ``(0, back_y, z)``. When both lie on the axis they are one sewn vertex
    shared by all four panels.
    """

    front_y: float
    back_y: float


@dataclass(frozen=True)
class SideInner:
    """A per-side inner seam point at ``(side * x, 0, z)``.

    Front and back panels of that side end on the same vertex.
    """

    x: float


InnerSpec = Union[CentreInner, SideInner]


@dataclass(frozen=True)
class SewnSection:
    """One constant-z cross-section of a sewn garment.

    Each side has an outer seam-boundary vertex at ``(side * outer_x, 0, z)``.
    ``inner`` decides where the front and back panel rows terminate.
    """

    z: float
    outer_x: float
    inner: InnerSpec


@dataclass(frozen=True)
class FanPanel:
    """A closed rounded-rectangle panel on one side, fan-triangulated.

    ``x_base`` is the signed-side offset from the centre line. ``y_half`` and
    the ``z_min``/``z_max`` range define the outline. ``corner_radius`` rounds
    the four corners and ``bulge`` controls the outward offset of the outline.
    """

    x_base: float
    y_half: float
    z_min: float
    z_max: float
    corner_radius: float
    bulge: float = 0.003


def smoothstep(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)


def profile_value(z: float, points: DepthProfile) -> float:
    """Evaluate a smoothstep-interpolated ``(z, value)`` profile at ``z``."""
    if len(points) < 2:
        raise PanelBuildError("profile needs at least two points")
    if z <= points[0][0]:
        return points[0][1]
    if z >= points[-1][0]:
        return points[-1][1]
    for (z0, value0), (z1, value1) in zip(points, points[1:]):
        if z <= z1:
            t = smoothstep((z - z0) / (z1 - z0))
            return value0 + (value1 - value0) * t
    raise PanelBuildError(f"profile interpolation failed at z={z}")


def interpolate_width(
    z: float,
    *,
    z0: float,
    width0: float,
    z1: float,
    width1: float,
) -> float:
    if z1 <= z0:
        raise PanelBuildError("width interpolation requires increasing z")
    t = min(1.0, max(0.0, (z - z0) / (z1 - z0)))
    return width0 + (width1 - width0) * smoothstep(t)


def _oriented_row(canonical: list[int], *, side: float, front: bool) -> list[int]:
    """Orient a panel row so generated face normals point outward."""
    if front:
        return canonical if side < 0.0 else list(reversed(canonical))
    return list(reversed(canonical)) if side < 0.0 else canonical


class SewnGarmentBuilder:
    """Builds four sewn panels (front/back x left/right) from sections.

    Sections must be added in ascending ``z`` order. ``bridge_panels`` joins
    consecutive rows of each panel into quads. ``add_fan_panel`` appends closed
    component panels such as pockets.
    """

    def __init__(
        self,
        mesh,
        *,
        front_depth: DepthProfile,
        rear_depth: DepthProfile,
        samples: int = 17,
    ) -> None:
        if samples < 3:
            raise PanelBuildError("a sewn panel row needs at least three samples")
        self.mesh = mesh
        self.front_depth = front_depth
        self.rear_depth = rear_depth
        self.samples = samples
        self.panel_rows: dict[str, list[list[int]]] = {
            panel_id: [] for panel_id in PANEL_IDS
        }
        self._last_z: float | None = None

    def add_vertex(self, point: Point) -> int:
        index = len(self.mesh.vertices)
        self.mesh.vertices.append(point)
        return index

    def add_section(self, section: SewnSection) -> None:
        z = section.z
        if self._last_z is not None and z <= self._last_z:
            raise PanelBuildError(
                f"sections must have increasing z: {z} after {self._last_z}"
            )
        self._last_z = z
        front_depth = profile_value(z, self.front_depth)
        rear_depth = profile_value(z, self.rear_depth)

        shared: tuple[int, int] | None = None
        if isinstance(section.inner, CentreInner):
            shared = self._centre_vertices(z, section.inner)

        for side_name, side in SIDES:
            outer_point = (side * section.outer_x, 0.0, z)
            outer_index = self.add_vertex(outer_point)

            if isinstance(section.inner, SideInner):
                inner_point = (side * section.inner.x, 0.0, z)
                inner_index = self.add_vertex(inner_point)
                front_inner = (inner_index, inner_point)
                back_inner = (inner_index, inner_point)
            else:
                assert shared is not None
                front_index, back_index = shared
                front_inner = (
                    front_index,
                    (0.0, section.inner.front_y, z),
                )
                back_inner = (
                    back_index,
                    (0.0, section.inner.back_y, z),
                )

            front = self._curve(
                outer_index,
                outer_point,
                front_inner[0],
                front_inner[1],
                depth=front_depth,
                front=True,
            )
            back = self._curve(
                outer_index,
                outer_point,
                back_inner[0],
                back_inner[1],
                depth=rear_depth,
                front=False,
            )
            self.panel_rows[f"front-{side_name}"].append(
                _oriented_row(front, side=side, front=True)
            )
            self.panel_rows[f"back-{side_name}"].append(
                _oriented_row(back, side=side, front=False)
            )

    def _centre_vertices(self, z: float, inner: CentreInner) -> tuple[int, int]:
        if abs(inner.front_y) <= AXIS_TOLERANCE and abs(inner.back_y) <= AXIS_TOLERANCE:
            index = self.add_vertex((0.0, 0.0, z))
            return index, index
        front_index = self.add_vertex((0.0, inner.front_y, z))
        back_index = self.add_vertex((0.0, inner.back_y, z))
        return front_index, back_index

    def _curve(
        self,
        outer_index: int,
        outer_point: Point,
        inner_index: int,
        inner_point: Point,
        *,
        depth: float,
        front: bool,
    ) -> list[int]:
        """Create one panel row between a seam-boundary pair of vertices."""
        sign = -1.0 if front else 1.0
        endpoint_depth = abs(inner_point[1])
        depth_blend = min(1.0, endpoint_depth / max(depth, 1e-6))
        row = [outer_index]
        for sample in range(1, self.samples - 1):
            t = sample / (self.samples - 1)
            midpoint_x = (outer_point[0] + inner_point[0]) * 0.5
            half_width_x = (outer_point[0] - inner_point[0]) * 0.5
            half_ellipse_x = midpoint_x + half_width_x * math.cos(math.pi * t)
            quarter_ellipse_x = inner_point[0] + (
                outer_point[0] - inner_point[0]
            ) * math.cos(math.pi * 0.5 * t)
            x = half_ellipse_x + (quarter_ellipse_x - half_ellipse_x) * depth_blend
            z = outer_point[2] + (inner_point[2] - outer_point[2]) * t
            free_bulge = sign * depth * (1.0 - depth_blend) * math.sin(math.pi * t)
            sewn_rise = inner_point[1] * math.sin(math.pi * 0.5 * t)
            row.append(self.add_vertex((x, free_bulge + sewn_rise, z)))
        row.append(inner_index)
        return row

    def bridge_panels(self) -> None:
        """Join consecutive rows of every panel into quad faces."""
        for panel_id in PANEL_IDS:
            rows = self.panel_rows[panel_id]
            for lower, upper in zip(rows, rows[1:]):
                _bridge_chains(self.mesh, lower, upper)

    def add_fan_panel(self, panel: FanPanel, *, side: float) -> None:
        """Append a closed rounded-rectangle panel on ``side`` (-1 or +1)."""
        if abs(side) != 1.0:
            raise PanelBuildError("fan panel side must be -1 or +1")
        if panel.y_half <= 0.0 or panel.z_max <= panel.z_min:
            raise PanelBuildError("fan panel outline is degenerate")
        if (
            not 0.0
            <= panel.corner_radius
            < min(panel.y_half, panel.z_max - panel.z_min)
        ):
            raise PanelBuildError("fan panel corner radius is out of range")
        y0 = -panel.y_half
        y1 = panel.y_half
        z0 = panel.z_min
        z1 = panel.z_max
        radius = panel.corner_radius
        yz = [
            (y0 + radius, z0),
            (y1 - radius, z0),
            (y1, z0 + radius),
            (y1, z1 - radius),
            (y1 - radius, z1),
            (y0 + radius, z1),
            (y0, z1 - radius),
            (y0, z0 + radius),
        ]
        points = []
        for y, z in yz:
            y_ratio = min(1.0, abs(y) / panel.y_half)
            z_ratio = min(1.0, abs(z - (z0 + z1) * 0.5) / ((z1 - z0) * 0.5))
            bulge = panel.bulge * (1.0 - 0.45 * y_ratio**2) * (1.0 - 0.30 * z_ratio**2)
            points.append((side * (panel.x_base + bulge), y, z))
        ring = self.mesh.add_ring(points)
        centre = self.mesh.add_ring(
            [(side * (panel.x_base + panel.bulge), 0.0, (z0 + z1) * 0.5)]
        )[0]
        oriented = ring if side > 0 else list(reversed(ring))
        _triangulate_fan(self.mesh, oriented, centre)


def _bridge_chains(mesh, first: list[int], second: list[int]) -> None:
    if len(first) != len(second):
        raise PanelBuildError("panel rows have different sample counts")
    for index in range(len(first) - 1):
        mesh.faces.append(
            (first[index], first[index + 1], second[index + 1], second[index])
        )


def _triangulate_fan(mesh, ring: list[int], centre: int) -> None:
    for index in range(len(ring)):
        next_index = (index + 1) % len(ring)
        mesh.faces.append((centre, ring[index], ring[next_index]))
