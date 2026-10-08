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


if __name__ == "__main__":
    unittest.main()
