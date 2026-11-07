from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.weight_transfer import (
    BoneInfluence,
    WeightTransferArtifact,
    WeightTransferMethod,
    WeightTransferPolicy,
    constrain_vertex_weights,
)


class WeightTransferTests(unittest.TestCase):
    def test_prunes_merges_and_normalizes_deterministically(self) -> None:
        result = constrain_vertex_weights(
            {
                0: [
                    ("Spine", 0.2),
                    ("Hips", 0.3),
                    ("Spine", 0.1),
                    ("Chest", 0.15),
                    ("Neck", 0.1),
                    ("Head", 0.05),
                ]
            },
            deform_bones={"Hips", "Spine", "Chest", "Neck", "Head"},
            policy=WeightTransferPolicy(max_influences=4),
        )

        influences = result.weights[0]
        self.assertEqual(
            [item.bone for item in influences],
            ["Hips", "Spine", "Chest", "Neck"],
        )
        self.assertAlmostEqual(sum(item.weight for item in influences), 1.0)
        self.assertEqual(result.audit.over_limit_vertices, (0,))
        self.assertAlmostEqual(result.audit.maximum_discarded_weight, 0.05)
        self.assertTrue(result.audit.passed)

    def test_reports_rejected_groups_and_zero_weight_vertices(self) -> None:
        result = constrain_vertex_weights(
            {0: [("Helper", 1.0)], 1: [("Hips", 1.0)]},
            deform_bones={"Hips"},
        )

        self.assertEqual(result.audit.zero_weight_vertices, (0,))
        self.assertEqual(result.audit.rejected_bone_groups, ("Helper",))
        self.assertFalse(result.audit.passed)
        self.assertEqual(result.audit.influence_histogram, {0: 1, 1: 1})

    def test_flags_only_opposite_weights_for_lateral_vertices(self) -> None:
        result = constrain_vertex_weights(
            {
                0: [("UpperLeg.L", 0.8), ("UpperLeg.R", 0.2)],
                1: [("UpperLeg.L", 0.5), ("UpperLeg.R", 0.5)],
                2: [("UpperLeg.L", 0.98), ("UpperLeg.R", 0.02)],
            },
            deform_bones={"UpperLeg.L", "UpperLeg.R"},
            expected_laterality={0: "left", 1: "center", 2: "left"},
            left_bones={"UpperLeg.L"},
            right_bones={"UpperLeg.R"},
        )

        self.assertEqual(
            result.audit.laterality_contamination_vertices,
            (0,),
        )
        self.assertFalse(result.audit.passed)

    def test_artifact_digest_is_stable(self) -> None:
        result = constrain_vertex_weights(
            {0: [BoneInfluence("Hips", 1.0)]},
            deform_bones={"Hips"},
        )
        digest = "a" * 64
        artifact = WeightTransferArtifact(
            source_mesh_hash=digest,
            target_mesh_hash=digest,
            armature_hash=digest,
            bind_pose_hash=digest,
            method=WeightTransferMethod.BLENDER_DATA_TRANSFER,
            method_version="4.4.3",
            parameters={"mapping": "nearest-face-interpolated"},
            result=result,
        )

        self.assertEqual(artifact.digest(), artifact.digest())
        self.assertEqual(artifact.to_dict()["stage"], "skin-and-export")
        self.assertEqual(
            artifact.to_dict()["vertexGroupHash"],
            result.audit.vertex_group_hash,
        )

    def test_rejects_negative_weights(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            constrain_vertex_weights(
                {0: [("Hips", -0.1)]},
                deform_bones={"Hips"},
            )


if __name__ == "__main__":
    unittest.main()
