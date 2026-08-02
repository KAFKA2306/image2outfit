from __future__ import annotations

import ast
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

    def test_runtime_probe_expression_is_valid_python(self) -> None:
        expression = blender_python_env.runtime_probe_expression()
        ast.parse(expression)
        self.assertIn(blender_python_env.PROBE_MARKER, expression)
        self.assertIn("'pythonPrefix':sys.prefix", expression)

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


if __name__ == "__main__":
    unittest.main()
