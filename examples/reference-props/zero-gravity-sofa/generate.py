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

    field = rounded_box(0.0, 0.0, 0.145, 0.56, 0.57, 0.16, 0.12)
    field = smin(
        field,
        ellipsoid(0.0, -0.07, 0.205, 0.43, 0.39, 0.135),
        0.055,
    )
    field = smin(
        field,
        ellipsoid(0.0, -0.455, 0.285, 0.575, 0.19, 0.18),
        0.055,
    )
    for side in (-1.0, 1.0):
        field = smin(
            field,
            rounded_box(0.47 * side, -0.12, 0.305, 0.14, 0.42, 0.18, 0.105),
            0.055,
        )
        rear_z = 0.405 if side < 0 else 0.365
        rear_rz = 0.24 if side < 0 else 0.20
        field = smin(
            field,
            ellipsoid(0.46 * side, 0.23, rear_z, 0.20, 0.31, rear_rz),
            0.070,
        )
    field = smin(
        field,
        rounded_box(0.0, 0.405, 0.395, 0.51, 0.22, 0.27, 0.14, rx_deg=-8.0),
        0.065,
    )
    field = smin(
        field,
        ellipsoid(-0.23, 0.40, 0.590, 0.30, 0.22, 0.265),
        0.065,
    )
    field = smin(
        field,
        ellipsoid(0.30, 0.39, 0.495, 0.28, 0.23, 0.175),
        0.065,
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
    seat = np.exp(-((x / 0.355) ** 4 + ((y + 0.085) / 0.31) ** 4))
    height_mask = np.clip((z - 0.15) / 0.17, 0.0, 1.0)
    rear_guard = 1.0 - np.clip((y - 0.13) / 0.19, 0.0, 1.0)
    z -= 0.115 * seat * height_mask * rear_guard

    crest = np.exp(-((x / 0.21) ** 2 + ((y - 0.41) / 0.17) ** 2)) * np.clip(
        (z - 0.43) / 0.16, 0.0, 1.0
    )
    z -= 0.045 * crest

    asym = np.exp(-(((x + 0.20) / 0.30) ** 2 + ((y - 0.35) / 0.28) ** 2)) * np.clip(
        (z - 0.35) / 0.25, 0.0, 1.0
    )
    z += 0.010 * asym

    ripple = 0.0032 * np.sin(13.0 * x + 2.7 * y) + 0.0020 * np.sin(9.0 * y - 2.4 * x)
    z += ripple * np.clip((z - 0.19) / 0.28, 0.0, 1.0)


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
        baseColorFactor=[30, 29, 28, 255],
        metallicFactor=0.0,
        roughnessFactor=0.34,
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
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
