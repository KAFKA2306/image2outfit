"""Deterministic avatar measurements, landmarks, poses, and arrangement volumes."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .domain import BodyRegion, Laterality, SurfaceOrientation

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
Vec3 = tuple[float, float, float]


def _identifier(value: str, label: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be kebab-case: {value!r}")


def _point(value: Vec3, label: str) -> None:
    if len(value) != 3 or any(not math.isfinite(item) for item in value):
        raise ValueError(f"{label} must contain three finite coordinates")


def _distance(first: Vec3, second: Vec3) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(first, second)))


@dataclass(frozen=True, slots=True)
class ShapeKeyState:
    name: str
    value: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("shape key name is required")
        if not math.isfinite(self.value):
            raise ValueError("shape key value must be finite")


@dataclass(frozen=True, slots=True)
class AvatarLandmark:
    landmark_id: str
    body_region: BodyRegion
    laterality: Laterality
    surface: SurfaceOrientation
    vertex_index: int
    position_mm: Vec3

    def __post_init__(self) -> None:
        _identifier(self.landmark_id, "landmark_id")
        if self.vertex_index < 0:
            raise ValueError("landmark vertex_index must be non-negative")
        _point(self.position_mm, "landmark position_mm")


@dataclass(frozen=True, slots=True)
class AvatarMeasurement:
    measurement_id: str
    value_mm: float
    method: str
    vertex_path: tuple[int, ...]

    def __post_init__(self) -> None:
        _identifier(self.measurement_id, "measurement_id")
        if not math.isfinite(self.value_mm) or self.value_mm <= 0:
            raise ValueError("measurement value_mm must be finite and positive")
        if len(self.vertex_path) < 2 or any(index < 0 for index in self.vertex_path):
            raise ValueError("measurement vertex_path requires two or more vertices")
        if not self.method.strip():
            raise ValueError("measurement method is required")


@dataclass(frozen=True, slots=True)
class PoseLandmarkState:
    pose_id: str
    landmark_positions_mm: Mapping[str, Vec3]

    def __post_init__(self) -> None:
        _identifier(self.pose_id, "pose_id")
        if not self.landmark_positions_mm:
            raise ValueError("pose landmark positions are required")
        for landmark_id, position in self.landmark_positions_mm.items():
            _identifier(landmark_id, "pose landmark_id")
            _point(position, f"pose {self.pose_id} landmark {landmark_id}")


@dataclass(frozen=True, slots=True)
class ArrangementVolume:
    volume_id: str
    body_region: BodyRegion
    laterality: Laterality
    minimum_mm: Vec3
    maximum_mm: Vec3
    landmark_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.volume_id, "volume_id")
        _point(self.minimum_mm, "arrangement minimum_mm")
        _point(self.maximum_mm, "arrangement maximum_mm")
        if any(low >= high for low, high in zip(self.minimum_mm, self.maximum_mm)):
            raise ValueError("arrangement volume bounds must have positive extent")
        if not self.landmark_ids:
            raise ValueError("arrangement volume requires landmark IDs")


@dataclass(frozen=True, slots=True)
class AvatarSpec:
    avatar_id: str
    mesh_sha256: str
    shape_keys: tuple[ShapeKeyState, ...]
    measurements: tuple[AvatarMeasurement, ...]
    landmarks: tuple[AvatarLandmark, ...]
    poses: tuple[PoseLandmarkState, ...]
    arrangement_volumes: tuple[ArrangementVolume, ...]
    schema_version: int = 1
    unit: str = "millimetre"
    coordinate_system: str = "right-handed-z-up"

    def __post_init__(self) -> None:
        _identifier(self.avatar_id, "avatar_id")
        if not _SHA256.fullmatch(self.mesh_sha256):
            raise ValueError("mesh_sha256 must be a lowercase SHA-256 digest")
        if self.schema_version != 1:
            raise ValueError("unsupported AvatarSpec schema_version")
        if self.unit != "millimetre":
            raise ValueError("AvatarSpec unit must be millimetre")
        if self.coordinate_system != "right-handed-z-up":
            raise ValueError("AvatarSpec coordinate system must be right-handed-z-up")
        for label, values in (
            ("shape key", [item.name for item in self.shape_keys]),
            ("measurement", [item.measurement_id for item in self.measurements]),
            ("landmark", [item.landmark_id for item in self.landmarks]),
            ("pose", [item.pose_id for item in self.poses]),
            (
                "arrangement volume",
                [item.volume_id for item in self.arrangement_volumes],
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} identifiers are not allowed")
        landmark_ids = {item.landmark_id for item in self.landmarks}
        for pose in self.poses:
            if set(pose.landmark_positions_mm) != landmark_ids:
                raise ValueError(
                    f"pose {pose.pose_id!r} must contain exactly the canonical landmarks"
                )
        for volume in self.arrangement_volumes:
            unknown = sorted(set(volume.landmark_ids).difference(landmark_ids))
            if unknown:
                raise ValueError(
                    f"arrangement volume {volume.volume_id!r} references unknown landmarks: {unknown}"
                )

    def landmark_displacements_mm(self, pose_id: str) -> dict[str, Vec3]:
        neutral = {item.landmark_id: item.position_mm for item in self.landmarks}
        pose = next((item for item in self.poses if item.pose_id == pose_id), None)
        if pose is None:
            raise KeyError(pose_id)
        return {
            landmark_id: tuple(
                posed - base
                for posed, base in zip(position, neutral[landmark_id], strict=True)
            )
            for landmark_id, position in sorted(pose.landmark_positions_mm.items())
        }

    def fingerprint(self) -> str:
        payload = {
            "avatarId": self.avatar_id,
            "meshSha256": self.mesh_sha256,
            "shapeKeys": [(item.name, item.value) for item in self.shape_keys],
            "measurements": [
                (item.measurement_id, item.value_mm, item.method, item.vertex_path)
                for item in self.measurements
            ],
            "landmarks": [
                (
                    item.landmark_id,
                    item.body_region.value,
                    item.laterality.value,
                    item.surface.value,
                    item.vertex_index,
                    item.position_mm,
                )
                for item in self.landmarks
            ],
            "poses": [
                (item.pose_id, sorted(item.landmark_positions_mm.items()))
                for item in self.poses
            ],
            "volumes": [
                (
                    item.volume_id,
                    item.body_region.value,
                    item.laterality.value,
                    item.minimum_mm,
                    item.maximum_mm,
                    item.landmark_ids,
                )
                for item in self.arrangement_volumes
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def derive_avatar_spec(
    *,
    avatar_id: str,
    mesh_sha256: str,
    neutral_vertices_mm: Sequence[Vec3],
    landmark_definitions: Mapping[
        str, tuple[BodyRegion, Laterality, SurfaceOrientation, int]
    ],
    measurement_paths: Mapping[str, Sequence[int]],
    posed_vertices_mm: Mapping[str, Sequence[Vec3]],
    shape_keys: Mapping[str, float] | None = None,
    arrangement_padding_mm: float = 10.0,
) -> AvatarSpec:
    """Derive a deterministic spec from an immutable mesh and vertex definitions."""
    if not neutral_vertices_mm:
        raise ValueError("neutral vertices are required")
    if not math.isfinite(arrangement_padding_mm) or arrangement_padding_mm < 0:
        raise ValueError("arrangement_padding_mm must be finite and non-negative")
    for index, vertex in enumerate(neutral_vertices_mm):
        _point(vertex, f"neutral vertex {index}")
    vertex_count = len(neutral_vertices_mm)
    landmarks: list[AvatarLandmark] = []
    for landmark_id, definition in sorted(landmark_definitions.items()):
        region, laterality, surface, vertex_index = definition
        if vertex_index < 0 or vertex_index >= vertex_count:
            raise ValueError(f"landmark {landmark_id!r} exceeds neutral vertex count")
        landmarks.append(
            AvatarLandmark(
                landmark_id=landmark_id,
                body_region=region,
                laterality=laterality,
                surface=surface,
                vertex_index=vertex_index,
                position_mm=neutral_vertices_mm[vertex_index],
            )
        )
    measurements: list[AvatarMeasurement] = []
    for measurement_id, raw_path in sorted(measurement_paths.items()):
        path = tuple(raw_path)
        if any(index < 0 or index >= vertex_count for index in path):
            raise ValueError(f"measurement {measurement_id!r} exceeds vertex count")
        value = sum(
            _distance(neutral_vertices_mm[first], neutral_vertices_mm[second])
            for first, second in zip(path, path[1:])
        )
        measurements.append(
            AvatarMeasurement(
                measurement_id=measurement_id,
                value_mm=value,
                method="mesh-polyline",
                vertex_path=path,
            )
        )
    poses: list[PoseLandmarkState] = []
    for pose_id, vertices in sorted(posed_vertices_mm.items()):
        if len(vertices) != vertex_count:
            raise ValueError(f"pose {pose_id!r} vertex count differs from neutral mesh")
        positions = {
            item.landmark_id: vertices[item.vertex_index] for item in landmarks
        }
        poses.append(
            PoseLandmarkState(pose_id=pose_id, landmark_positions_mm=positions)
        )
    grouped: dict[tuple[BodyRegion, Laterality], list[AvatarLandmark]] = {}
    for landmark in landmarks:
        grouped.setdefault((landmark.body_region, landmark.laterality), []).append(
            landmark
        )
    volumes = []
    for (region, laterality), items in sorted(
        grouped.items(), key=lambda item: (item[0][0].value, item[0][1].value)
    ):
        coordinates = list(zip(*(item.position_mm for item in items), strict=True))
        volumes.append(
            ArrangementVolume(
                volume_id=f"{region.value}-{laterality.value}",
                body_region=region,
                laterality=laterality,
                minimum_mm=tuple(
                    min(axis) - arrangement_padding_mm for axis in coordinates
                ),
                maximum_mm=tuple(
                    max(axis) + arrangement_padding_mm for axis in coordinates
                ),
                landmark_ids=tuple(item.landmark_id for item in items),
            )
        )
    return AvatarSpec(
        avatar_id=avatar_id,
        mesh_sha256=mesh_sha256,
        shape_keys=tuple(
            ShapeKeyState(name=name, value=value)
            for name, value in sorted((shape_keys or {}).items())
        ),
        measurements=tuple(measurements),
        landmarks=tuple(landmarks),
        poses=tuple(poses),
        arrangement_volumes=tuple(volumes),
    )
