from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
import sys

sys.path.insert(0, str(TOOLS))

import blender_python_env  # noqa: E402
import technical_candidate  # noqa: E402


class HostedPoseRenderTests(unittest.TestCase):
    def test_hosted_pose_script_is_run_and_required_outputs_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "tools" / "poses.py"
            blend = root / "Assets" / "Product" / "outfit.blend"
            pose_root = root / "Assets" / "Product" / "Previews" / "Poses"
            script.parent.mkdir(parents=True)
            blend.parent.mkdir(parents=True)
            script.write_text("# test\n", encoding="utf-8")
            blend.write_bytes(b"blend")
            required = ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone")
            for pose in required:
                pose_path = pose_root / f"{pose}.png"
                pose_path.parent.mkdir(parents=True, exist_ok=True)
                pose_path.write_bytes(b"png")

            job = {
                "hostedPoseScript": "tools/poses.py",
                "blendPath": "Assets/Product/outfit.blend",
                "productRoot": "Assets/Product",
            }
            policy = {"requiredPoses": list(required)}
            prepared = blender_python_env.PreparedEnvironment(
                command_prefix=["blender", "--python-use-system-env"],
                environment={},
                report={},
            )

            with (
                patch.object(technical_candidate.candidate_contract, "ROOT", root),
                patch.object(technical_candidate, "run_command", return_value=0) as run,
            ):
                result = technical_candidate.run_hosted_pose_render(
                    root / "job.json", job, policy, prepared, root / "reports"
                )

            self.assertTrue(result["passed"])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["missingPoses"], [])
            command = run.call_args.args[0]
            self.assertIn(str(script), command)
            self.assertIn(str(blend), command)
            self.assertIn("--job", command)

    def test_unconfigured_hosted_pose_is_explicitly_not_requested(self) -> None:
        prepared = blender_python_env.PreparedEnvironment([], {}, {})
        result = technical_candidate.run_hosted_pose_render(
            Path("job.json"),
            {},
            {"requiredPoses": ["neutral"]},
            prepared,
            Path("reports"),
        )
        self.assertEqual(result, {"passed": True, "status": "NOT_REQUESTED"})


class SkinBindingSummaryTests(unittest.TestCase):
    def test_mesh_without_vertex_groups_is_unrigged_mesh_only_output(self) -> None:
        summary = technical_candidate.skin_binding_summary(
            [{"name": "TripoSG_Raw", "hasVertexGroups": False, "armatureTargets": []}]
        )
        self.assertEqual(summary["riggingState"], "UNRIGGED")
        self.assertEqual(summary["unriggedMeshObjects"], ["TripoSG_Raw"])

    def test_vertex_groups_without_armature_modifier_are_not_bound(self) -> None:
        summary = technical_candidate.skin_binding_summary(
            [{"name": "Garment", "hasVertexGroups": True, "armatureTargets": []}]
        )
        self.assertEqual(summary["riggingState"], "UNRIGGED")
        self.assertEqual(summary["unriggedMeshObjects"], ["Garment"])

    def test_one_unbound_mesh_makes_the_whole_scene_unrigged(self) -> None:
        summary = technical_candidate.skin_binding_summary(
            [
                {
                    "name": "Body",
                    "hasVertexGroups": True,
                    "armatureTargets": ["Armature"],
                },
                {"name": "Raw", "hasVertexGroups": False, "armatureTargets": []},
            ]
        )
        self.assertEqual(summary["riggingState"], "UNRIGGED")
        self.assertEqual(summary["unriggedMeshObjects"], ["Raw"])

    def test_fully_bound_meshes_are_rigged(self) -> None:
        summary = technical_candidate.skin_binding_summary(
            [
                {
                    "name": "Body",
                    "hasVertexGroups": True,
                    "armatureTargets": ["Armature"],
                },
                {
                    "name": "Garment",
                    "hasVertexGroups": True,
                    "armatureTargets": ["Armature"],
                },
            ]
        )
        self.assertEqual(summary["riggingState"], "RIGGED")
        self.assertEqual(summary["unriggedMeshObjects"], [])

    def test_empty_scene_is_not_reported_as_rigged(self) -> None:
        summary = technical_candidate.skin_binding_summary([])
        self.assertEqual(summary["riggingState"], "UNRIGGED")


if __name__ == "__main__":
    unittest.main()
