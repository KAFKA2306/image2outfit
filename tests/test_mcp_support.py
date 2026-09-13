from __future__ import annotations

import ast
import json
import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from mcp_assistant_control import AssistantStatus, classify_process_outcome  # noqa: E402


class McpSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.toolchain = json.loads(
            (ROOT / "config" / "toolchain-lock.json").read_text(encoding="utf-8")
        )
        cls.contract = cls.toolchain["authoringAdapters"]

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

    def test_assistant_exposes_cancel_action(self) -> None:
        source = (
            ROOT / "tools" / "blender_addons" / "image2outfit_assistant.py"
        ).read_text(encoding="utf-8")
        self.assertIn("IMAGE2OUTFIT_OT_cancel_codex", source)
        self.assertIn("process.terminate()", source)

    def test_control_harness_distinguishes_all_outcomes(self) -> None:
        success = classify_process_outcome(0, "ok")
        cancelled = classify_process_outcome(143, cancelled=True)
        failure = classify_process_outcome(2, stderr="bad")
        unavailable = classify_process_outcome(None, unavailable_reason="missing")

        self.assertEqual(success.status, AssistantStatus.COMPLETED)
        self.assertEqual(cancelled.status, AssistantStatus.CANCELLED)
        self.assertEqual(failure.status, AssistantStatus.FAILED)
        self.assertEqual(unavailable.status, AssistantStatus.UNAVAILABLE)
        self.assertIn("bad", failure.content)
        self.assertEqual(unavailable.content, "missing")

    def test_authoring_contract_is_optional_loopback_only_and_pinned(self) -> None:
        contract = self.contract
        blender = contract["blenderMcp"]
        unity = contract["unityMcp"]
        self.assertFalse(contract["affectsProductCompletion"])
        self.assertTrue(contract["security"]["loopbackOnly"])
        self.assertFalse(contract["security"]["trackedSecretsAllowed"])
        self.assertFalse(contract["security"]["unattendedApprovalBypassAllowed"])
        self.assertFalse(
            contract["security"]["externalBlenderIntegrationsEnabledByDefault"]
        )
        self.assertEqual(
            contract["doctorStates"],
            ["CONFIGURED", "REACHABLE", "UNAVAILABLE", "UNVERIFIED"],
        )
        self.assertEqual(blender["commit"], "3ab892510cc0e5435ba5e611c01fb1021fbde8de")
        self.assertEqual(
            blender["addonGitBlobSha1"],
            "0a93c497693193f16bbd291499a760b3ebce09fb",
        )
        self.assertIn(blender["host"], {"localhost", "127.0.0.1", "::1"})
        self.assertEqual(unity["host"], "127.0.0.1")
        self.assertTrue(unity["url"].startswith("http://127.0.0.1:"))
        project_version = (ROOT / unity["projectVersionSource"]).read_text(
            encoding="utf-8"
        )
        self.assertIn(
            f"m_EditorVersion: {self.toolchain['unity']['version']}", project_version
        )

    def test_windows_example_matches_canonical_contract(self) -> None:
        config = json.loads(
            (ROOT / "examples" / "mcp" / "windows-mcp.json").read_text(encoding="utf-8")
        )
        servers = config["mcpServers"]
        expected_blender = self.contract["blenderMcp"]
        expected_unity = self.contract["unityMcp"]
        blender = servers["blender"]
        self.assertIn(f"blender-mcp=={expected_blender['version']}", blender["args"])
        self.assertEqual(blender["env"]["BLENDER_HOST"], expected_blender["host"])
        self.assertEqual(blender["env"]["BLENDER_PORT"], str(expected_blender["port"]))
        self.assertEqual(blender["env"]["DISABLE_TELEMETRY"], "true")
        self.assertEqual(servers["unityMCP"]["url"], expected_unity["url"])

    def test_codex_example_matches_canonical_contract(self) -> None:
        config = tomllib.loads(
            (ROOT / "examples" / "mcp" / "codex-config.toml").read_text(
                encoding="utf-8"
            )
        )
        servers = config["mcp_servers"]
        expected_blender = self.contract["blenderMcp"]
        expected_unity = self.contract["unityMcp"]
        blender = servers[expected_blender["serverName"]]
        self.assertEqual(blender["command"], "cmd")
        self.assertIn(f"blender-mcp=={expected_blender['version']}", blender["args"])
        self.assertEqual(blender["env"]["DISABLE_TELEMETRY"], "true")
        unity = servers[expected_unity["serverName"]]
        self.assertEqual(unity["url"], expected_unity["url"])

    def test_setup_verifies_identity_and_four_state_doctor(self) -> None:
        script = (ROOT / "tools" / "setup_mcp.ps1").read_text(encoding="utf-8")
        self.assertIn("config\\toolchain-lock.json", script)
        self.assertIn("$Toolchain.authoringAdapters", script)
        self.assertIn("Get-GitBlobSha1", script)
        self.assertIn("addonGitBlobSha1", script)
        self.assertIn("Pinned Blender MCP addon identity mismatch", script)
        self.assertIn("Resolve-DoctorState", script)
        for state in self.contract["doctorStates"]:
            self.assertIn(f'return "{state}"', script)
        self.assertIn("mutatesProductState = $false", script)
        self.assertIn(
            "MCP contract violates the loopback-only security boundary", script
        )

    def test_local_state_and_secret_patterns_are_excluded_from_git(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/.image2outfit/", ignore)
        self.assertIn(".env.*", ignore)
        self.assertIn("*.key", ignore)
        self.assertIn("*.pem", ignore)

    def test_existing_completion_gates_are_unchanged(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "genworks-handoff-policy.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            policy["requiredCompletionGates"],
            [
                "blender",
                "editableSource",
                "fbx",
                "prefabDeclared",
                "fiveViewEvidence",
                "poseEvidence",
                "visualAppearanceReview",
            ],
        )
        self.assertIn("unityImport", policy["outOfScopeGates"])
        self.assertIn("vrchatRuntime", policy["outOfScopeGates"])

    def test_mcp_readme_preserves_completion_boundary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("製品の`COMPLETE`条件は変更しません", readme)
        self.assertIn("Unity 2022.3.22f1 import/save/reload", readme)
        self.assertIn("VRChat Build & Test", readme)
        self.assertIn("OUT_OF_SCOPE", readme)
        self.assertIn("task mcp:doctor", readme)


if __name__ == "__main__":
    unittest.main()
