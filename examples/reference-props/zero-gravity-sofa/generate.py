#!/usr/bin/env python3
"""Generate a static 0-Gravity XXXL sofa reference mesh."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import trimesh

TARGET_EXTENTS = np.array([1.12, 1.14, 0.65], dtype=np.float64)


def smin(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1.0 - h) + a * h - k * h * (1.0 - h)


def sofa_sdf(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    def rounded_box(cx, cy, cz, hx, hy, hz, radius, rx_deg=0.0):
        px = x - cx
        py = y - cy
        pz = z - cz
        if rx_deg:
            a = math.radians(rx_deg)
            ca, sa = math.cos(a), math.sin(a)
            py, pz = ca * py + sa * pz, -sa * py + ca * pz
        bx = max(hx - radius, 1e-5)
        by = max(hy - radius, 1e-5)
        bz = max(hz - radius, 1e-5)
        qx, qy, qz = np.abs(px) - bx, np.abs(py) - by, np.abs(pz) - bz
        ox = np.maximum(qx, 0.0)
        oy = np.maximum(qy, 0.0)
        oz = np.maximum(qz, 0.0)
        return (
            np.sqrt(ox * ox + oy * oy + oz * oz)
            + np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0.0)
            - radius
        )

    def ellipsoid(cx, cy, cz, rx, ry, rz):
        px, py, pz = (x - cx) / rx, (y - cy) / ry, (z - cz) / rz
        return (np.sqrt(px * px + py * py + pz * pz) - 1.0) * min(rx, ry, rz)

    def superellipsoid(cx, cy, cz, rx, ry, rz, power=1.65):
        px = np.abs((x - cx) / rx)
        py = np.abs((y - cy) / ry)
        pz = np.abs((z - cz) / rz)
        norm = (px**power + py**power + pz**power) ** (1.0 / power)
        return (norm - 1.0) * min(rx, ry, rz)

    field = rounded_box(0.0, -0.015, 0.135, 0.56, 0.57, 0.145, 0.105)
    field = smin(
        field,
        ellipsoid(0.0, -0.08, 0.205, 0.46, 0.42, 0.125),
        0.050,
    )
    field = smin(
        field,
        ellipsoid(0.0, -0.455, 0.215, 0.575, 0.165, 0.130),
        0.045,
    )

    for side in (-1.0, 1.0):
        field = smin(
            field,
            rounded_box(0.49 * side, -0.115, 0.245, 0.12, 0.42, 0.130, 0.090),
            0.050,
        )

    ridge_x = (-0.46, -0.34, -0.20, -0.04, 0.14, 0.31, 0.46)
    ridge_z = (0.610, 0.575, 0.525, 0.485, 0.450, 0.420, 0.400)
    ridge_rz = (0.280, 0.255, 0.225, 0.200, 0.180, 0.160, 0.145)
    ridge_rx = (0.16, 0.18, 0.20, 0.22, 0.21, 0.19, 0.16)
    for cx, cz, rz, rx in zip(ridge_x, ridge_z, ridge_rz, ridge_rx):
        primitive = (
            superellipsoid(cx, 0.395, cz, rx, 0.22, rz, power=1.55)
            if cx <= -0.20
            else ellipsoid(cx, 0.395, cz, rx, 0.22, rz)
        )
        field = smin(field, primitive, 0.045)

    field = smin(
        field,
        rounded_box(0.0, 0.300, 0.335, 0.50, 0.20, 0.16, 0.11, rx_deg=-10.0),
        0.050,
    )
    return field


TETS = np.array(
    [
        [0, 1, 2, 6],
        [0, 2, 3, 6],
        [0, 3, 7, 6],
        [0, 7, 4, 6],
        [0, 4, 5, 6],
        [0, 5, 1, 6],
    ],
    dtype=np.int8,
)
CORNERS = np.array(
    [
        [0, 0, 0],
        [1, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
        [0, 0, 1],
        [1, 0, 1],
        [1, 1, 1],
        [0, 1, 1],
    ],
    dtype=np.int8,
)
TET_EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def polygonize_tet(points: np.ndarray, values: np.ndarray) -> list[np.ndarray]:
    intersections: list[np.ndarray] = []
    for a, b in TET_EDGES:
        va, vb = float(values[a]), float(values[b])
        if (va < 0.0) == (vb < 0.0):
            continue
        t = va / (va - vb)
        intersections.append(points[a] + t * (points[b] - points[a]))
    if len(intersections) < 3:
        return []
    polygon = np.asarray(intersections, dtype=np.float64)
    if len(polygon) == 3:
        return [polygon]

    center = polygon.mean(axis=0)
    centered = polygon - center
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    u, v = vh[0], vh[1]
    angles = np.arctan2(centered @ v, centered @ u)
    polygon = polygon[np.argsort(angles)]
    return [polygon[[0, 1, 2]], polygon[[0, 2, 3]]]


def marching_tetrahedra(
    field: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray,
) -> trimesh.Trimesh:
    corners = [
        field[:-1, :-1, :-1],
        field[1:, :-1, :-1],
        field[1:, 1:, :-1],
        field[:-1, 1:, :-1],
        field[:-1, :-1, 1:],
        field[1:, :-1, 1:],
        field[1:, 1:, 1:],
        field[:-1, 1:, 1:],
    ]
    mn = np.minimum.reduce(corners)
    mx = np.maximum.reduce(corners)
    active = np.argwhere((mn <= 0.0) & (mx >= 0.0))

    vertices: list[np.ndarray] = []
    faces: list[tuple[int, int, int]] = []
    for i, j, k in active:
        cube_idx = CORNERS + np.array([i, j, k], dtype=np.int64)
        cube_points = np.column_stack(
            (
                xs[cube_idx[:, 0]],
                ys[cube_idx[:, 1]],
                zs[cube_idx[:, 2]],
            )
        )
        cube_values = field[cube_idx[:, 0], cube_idx[:, 1], cube_idx[:, 2]]
        for tet in TETS:
            for tri in polygonize_tet(cube_points[tet], cube_values[tet]):
                base = len(vertices)
                vertices.extend(tri)
                faces.append((base, base + 1, base + 2))

    mesh = trimesh.Trimesh(
        np.asarray(vertices),
        np.asarray(faces),
        process=True,
    )
    mesh.merge_vertices()
    trimesh.repair.fix_normals(mesh)
    return mesh


def sculpt(mesh: trimesh.Trimesh) -> None:
    points = mesh.vertices
    x, y, z = points[:, 0], points[:, 1], points[:, 2]

    seat = np.exp(-((x / 0.445) ** 6 + ((y + 0.045) / 0.35) ** 6))
    height_mask = np.clip((z - 0.13) / 0.18, 0.0, 1.0)
    rear_guard = 1.0 - np.clip((y - 0.16) / 0.19, 0.0, 1.0)
    z -= 0.145 * seat * height_mask * rear_guard

    seat_back = np.exp(-((y - 0.145) / 0.055) ** 2) * np.exp(-(x / 0.44) ** 8)
    z -= 0.030 * seat_back * np.clip((z - 0.21) / 0.18, 0.0, 1.0)

    center_slouch = np.exp(-((x / 0.24) ** 2 + ((y - 0.375) / 0.18) ** 2))
    z -= 0.052 * center_slouch * np.clip((z - 0.31) / 0.26, 0.0, 1.0)

    left_peak = np.exp(
        -(((x + 0.46) / 0.15) ** 2 + ((y - 0.395) / 0.16) ** 2)
    )
    z += 0.022 * left_peak * np.clip((z - 0.36) / 0.22, 0.0, 1.0)

    right_drop = np.exp(
        -(((x - 0.30) / 0.23) ** 2 + ((y - 0.39) / 0.20) ** 2)
    )
    z -= 0.030 * right_drop * np.clip((z - 0.33) / 0.20, 0.0, 1.0)

    back_mask = np.clip((y - 0.07) / 0.20, 0.0, 1.0) * np.clip(
        (z - 0.24) / 0.25, 0.0, 1.0
    )
    for slope, offset, amplitude, width in (
        (-1.50, -0.13, 0.011, 0.027),
        (-0.95, -0.08, 0.009, 0.024),
        (-0.45, -0.03, 0.012, 0.026),
        (0.10, 0.01, 0.010, 0.024),
        (0.72, 0.06, 0.010, 0.026),
        (1.32, 0.12, 0.008, 0.028),
    ):
        line = x - slope * (y - 0.15) - offset
        z -= amplitude * np.exp(-(line / width) ** 2) * back_mask

    front_curve = -0.405 + 0.040 * (x / 0.50) ** 2
    front_seam = np.exp(-((y - front_curve) / 0.012) ** 2)
    front_seam *= np.exp(-(x / 0.53) ** 10)
    z -= 0.0065 * front_seam * np.clip((z - 0.15) / 0.12, 0.0, 1.0)

    side_mask = np.exp(-((np.abs(x) - 0.49) / 0.018) ** 2)
    side_mask *= np.clip((0.34 - y) / 0.32, 0.0, 1.0)
    x -= np.sign(x) * 0.0045 * side_mask * np.clip((z - 0.12) / 0.20, 0.0, 1.0)

    corner = np.exp(-((np.abs(x) - 0.43) / 0.11) ** 2)
    corner *= np.exp(-((y + 0.34) / 0.17) ** 2)
    wrinkle = 0.0038 * np.sin(28.0 * y + 8.0 * np.abs(x)) + 0.0022 * np.sin(
        21.0 * x - 5.0 * y
    )
    z += wrinkle * corner * np.clip((z - 0.15) / 0.18, 0.0, 1.0)

    broad = 0.0018 * np.sin(11.0 * x + 2.3 * y) + 0.0012 * np.sin(
        8.0 * y - 1.8 * x
    )
    z += broad * np.clip((z - 0.20) / 0.30, 0.0, 1.0)


def build(resolution: int) -> trimesh.Trimesh:
    nx = resolution
    ny = int(round(resolution * 1.03))
    nz = max(18, int(round(resolution * 0.81)))
    xs = np.linspace(-0.92, 0.92, nx)
    ys = np.linspace(-0.93, 0.93, ny)
    zs = np.linspace(-0.22, 0.96, nz)
    x, y, z = np.meshgrid(xs, ys, zs, indexing="ij")
    field = sofa_sdf(x, y, z)
    mesh = marching_tetrahedra(field, xs, ys, zs)
    sculpt(mesh)

    mesh.vertices *= TARGET_EXTENTS / mesh.extents
    mesh.vertices[:, 2] -= mesh.bounds[0, 2]
    trimesh.repair.fix_normals(mesh)
    material = trimesh.visual.material.PBRMaterial(
        name="Black_PU_PVC",
        baseColorFactor=[27, 27, 26, 255],
        metallicFactor=0.0,
        roughnessFactor=0.38,
    )
    mesh.visual = trimesh.visual.TextureVisuals(material=material)
    return mesh


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("zero_gravity_sofa_black.glb"),
    )
    parser.add_argument("--resolution", type=int, default=54)
    args = parser.parse_args()
    if args.resolution < 18:
        parser.error("--resolution must be >= 18")

    mesh = build(args.resolution)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(args.output)
    payload = args.output.read_bytes()
    report = {
        "dimensionsM": [round(float(v), 6) for v in mesh.extents],
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "windingConsistent": bool(mesh.is_winding_consistent),
        "components": int(len(mesh.split(only_watertight=False))),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
