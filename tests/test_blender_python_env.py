from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
sys.path.insert(0, str(TOOLS))

import blender_python_env


class BlenderPythonEnvironmentTest(unittest.TestCase):
    def test_blender_command_enables_python_environment(self) -> None:
        command = blender_python_env.blender_command(
            "blender", ["--background", "--python", "build.py"]
        )
        self.assertEqual(command[0:2], ["blender", "--python-use-system-env"])

    def test_dependency_target_is_first_on_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.dict(os.environ, {"PYTHONPATH": "existing"}, clear=True):
                environment = blender_python_env.dependency_environment(target)
        self.assertEqual(
            environment["PYTHONPATH"], str(target) + os.pathsep + "existing"
        )

    def test_marked_json_rejects_unverified_output(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "did not contain"):
            blender_python_env._marked_json("Blender quit", "EXPECTED=")

    def test_bundled_python_requires_existing_interpreter(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(FileNotFoundError, "bundled Python"),
        ):
            blender_python_env.bundled_python(directory, "3.11.11")


    def test_prepare_installs_locked_transitive_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "pyproject.toml").write_text(
                '[project]\ndependencies = ["jsonschema==4.26.0", "Pillow==12.3.0"]\n',
                encoding="utf-8",
            )
            (root / "uv.lock").write_text("locked dependency graph", encoding="utf-8")
            (root / "config" / "toolchain-lock.json").write_text(
                '{"blender":{"version":"4.4.3","python":{"version":"3.11.11",'
                '"dependencyGroup":"project","packages":{"jsonschema":'
                '{"version":"4.26.0","importName":"jsonschema"},'
                '"Pillow":{"version":"12.3.0","importName":"PIL"}}}}}',
                encoding="utf-8",
            )
            runtime = {
                "blenderVersion": "4.4.3",
                "pythonVersion": "3.11.11",
                "pythonPrefix": directory,
            }
            with (
                patch.object(blender_python_env, "probe_runtime", return_value=runtime),
                patch.object(
                    blender_python_env,
                    "bundled_python",
                    return_value=root / "python",
                ),
                patch.object(
                    blender_python_env,
                    "_verify_packages",
                    return_value={"jsonschema": "4.26.0", "Pillow": "12.3.0"},
                ),
                patch.object(blender_python_env.shutil, "which", return_value="uv"),
                patch.object(blender_python_env, "_run") as run,
            ):
                blender_python_env.prepare("blender", root=root)
            commands = [call.args[0] for call in run.call_args_list]
            export, install = commands
            self.assertEqual(export[:3], ["uv", "export", "--frozen"])
            self.assertIn("--no-default-groups", export)
            self.assertIn("--no-emit-project", export)
            self.assertIn("--require-hashes", install)
            self.assertIn("--no-deps", install)
            self.assertEqual(install[install.index("-r") + 1], export[-1])
            self.assertNotIn("jsonschema==4.26.0", install)
            stamp = blender_python_env.read_json(
                root / ".image2outfit" / "blender-python"
                / "image2outfit-environment.json"
            )
            self.assertEqual(
                stamp["uvLockSha256"], blender_python_env.sha256(root / "uv.lock")
            )

if __name__ == "__main__":
    unittest.main()
