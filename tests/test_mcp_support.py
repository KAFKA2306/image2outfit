from __future__ import annotations

import ast
import json
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class McpSupportTests(unittest.TestCase):
    def test_blender_assistant_is_valid_python(self) -> None:
        path = ROOT / "tools" / "blender_addons" / "image2outfit_assistant.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        self.assertIsInstance(tree, ast.Module)

    def test_background_worker_does_not_access_bpy(self) -> None:
        path = ROOT / "tools" / "blender_addons" / "image2outfit_assistant.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        worker = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_run_codex"
        )
        names = {node.id for node in ast.walk(worker) if isinstance(node, ast.Name)}
        self.assertNotIn("bpy", names)

    def test_windows_example_is_pinned_and_local_only(self) -> None:
        path = ROOT / "examples" / "mcp" / "windows-mcp.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        servers = config["mcpServers"]

        blender = servers["blender"]
        self.assertIn("blender-mcp==1.8.0", blender["args"])
        self.assertEqual(blender["env"]["BLENDER_HOST"], "localhost")
        self.assertEqual(blender["env"]["BLENDER_PORT"], "9876")
        self.assertEqual(blender["env"]["DISABLE_TELEMETRY"], "true")

        unity = servers["unityMCP"]
        self.assertEqual(unity["url"], "http://127.0.0.1:8080/mcp")

    def test_codex_example_is_valid_toml_and_pinned(self) -> None:
        path = ROOT / "examples" / "mcp" / "codex-config.toml"
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        servers = config["mcp_servers"]

        blender = servers["image2outfit-blender"]
        self.assertEqual(blender["command"], "cmd")
        self.assertIn("blender-mcp==1.8.0", blender["args"])
        self.assertEqual(blender["env"]["DISABLE_TELEMETRY"], "true")

        unity = servers["image2outfit-unity"]
        self.assertEqual(unity["url"], "http://127.0.0.1:8080/mcp")

    def test_setup_script_uses_pinned_local_launchers_and_prints_doctor(self) -> None:
        script = (ROOT / "tools" / "setup_mcp.ps1").read_text(encoding="utf-8")
        self.assertIn('$BlenderMcpVersion = "1.8.0"', script)
        self.assertIn('$BlenderMcpPython = "3.11"', script)
        self.assertIn('$UnityMcpVersion = "10.1.2"', script)
        self.assertIn('$UnityMcpUrl = "http://127.0.0.1:8080/mcp"', script)
        self.assertIn('--env "DISABLE_TELEMETRY=true"', script)
        self.assertIn('Invoke-McpDoctor | ConvertTo-Json -Depth 10', script)
        self.assertNotIn('Invoke-McpDoctor | Out-Null', script)

    def test_mcp_readme_preserves_completion_boundary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("製品の`COMPLETE`条件は変更しません", readme)
        self.assertIn("Unity 2022.3.22f1 import/save/reload", readme)
        self.assertIn("VRChat Build & Test", readme)
        self.assertIn("OUT_OF_SCOPE", readme)
        self.assertIn("task mcp:doctor", readme)


if __name__ == "__main__":
    unittest.main()
