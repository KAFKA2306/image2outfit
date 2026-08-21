from __future__ import annotations

import pytest

from image2outfit.skinning import (
    VertexWeight,
    WeightTransferArtifact,
    WeightTransferMethod,
    detect_left_right_contamination,
    influence_histogram,
    repair_vertex_weights,
    vertex_group_digest,
)


def test_repair_vertex_weights_prunes_normalizes_and_rejects_non_deform_bones() -> None:
    result = repair_vertex_weights(
        [
            [
                VertexWeight("Arm.L", 0.4),
                VertexWeight("Chest", 0.3),
                VertexWeight("Spine", 0.2),
                VertexWeight("Hips", 0.1),
                VertexWeight("Neck", 0.05),
                VertexWeight("Helper", 0.7),
            ],
            [VertexWeight("Helper", 1.0)],
        ],
        deform_bones={"Arm.L", "Chest", "Spine", "Hips", "Neck"},
    )

    assert len(result.weights[0]) == 4
    assert sum(item.weight for item in result.weights[0]) == pytest.approx(1.0)
    assert result.zero_weight_vertices == (1,)
    assert result.non_normalized_vertices == ()
    assert result.rejected_bone_groups == ("Helper",)


def test_left_right_contamination_is_reported_per_vertex() -> None:
    vertices = [
        (VertexWeight("Arm.R", 1.0),),
        (VertexWeight("Arm.R", 1.0),),
        (VertexWeight("Spine", 1.0),),
    ]

    assert detect_left_right_contamination(
        vertices,
        vertex_sides=("left", "right", "center"),
        center_bones={"Spine"},
    ) == (0,)


def test_digest_and_histogram_are_deterministic() -> None:
    vertices = (
        (VertexWeight("Chest", 0.75), VertexWeight("Spine", 0.25)),
        (VertexWeight("Hips", 1.0),),
    )

    assert vertex_group_digest(vertices) == vertex_group_digest(vertices)
    assert influence_histogram(vertices) == {2: 1, 1: 1}


def test_artifact_release_gate_rejects_weight_defects() -> None:
    artifact = WeightTransferArtifact(
        source_mesh_hash="source",
        target_mesh_hash="target",
        armature_hash="armature",
        bind_pose_hash="bind",
        method=WeightTransferMethod.BLENDER_DATA_TRANSFER,
        method_version="4.4.3",
        parameters={"mapping": "nearest-face-interpolated"},
        vertex_group_hash="weights",
        influence_histogram={1: 10, 4: 20},
        zero_weight_vertices=(),
        non_normalized_vertices=(),
        left_right_contamination=(),
        rejected_bone_groups=(),
        pose_evidence={"neutral": "neutral.webp"},
        metrics={"weightLaplacianEnergy": 0.1},
    )

    assert artifact.release_ready

    contaminated = WeightTransferArtifact(
        source_mesh_hash="source",
        target_mesh_hash="target",
        armature_hash="armature",
        bind_pose_hash="bind",
        method=WeightTransferMethod.BLENDER_DATA_TRANSFER,
        method_version="4.4.3",
        parameters={},
        vertex_group_hash="weights",
        influence_histogram={4: 1},
        zero_weight_vertices=(),
        non_normalized_vertices=(),
        left_right_contamination=(4,),
        rejected_bone_groups=(),
        pose_evidence={},
        metrics={},
    )

    assert not contaminated.release_ready
