from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SRC = ROOT / "src"
for path in (TOOLS, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pipeline_source_fingerprint as source_fingerprint
import run_garment_pipeline as runner


class PipelineRequestSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.minimal = {
            "schemaVersion": 1,
            "productId": "demo-product",
            "targetAvatar": "DemoAvatar",
            "sourceReference": "private-reference://sha256/demo",
        }

    def assert_valid(self, value: dict[str, object]) -> None:
        runner._validate_request(value)

    def assert_invalid(self, value: dict[str, object], fragment: str) -> None:
        with self.assertRaisesRegex(ValueError, fragment):
            runner._validate_request(value)

    def test_all_tracked_requests_match_canonical_schema(self) -> None:
        requests = sorted((ROOT / "config" / "pipeline" / "requests").glob("*.json"))
        self.assertTrue(requests)
        for path in requests:
            with self.subTest(path=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assert_valid(value)

    def test_minimal_request_is_valid(self) -> None:
        self.assert_valid(self.minimal)

    def test_schema_version_must_equal_one(self) -> None:
        value = copy.deepcopy(self.minimal)
        value["schemaVersion"] = 2
        self.assert_invalid(value, "schemaVersion")

    def test_required_identity_is_required(self) -> None:
        for key in ("productId", "targetAvatar", "sourceReference"):
            value = copy.deepcopy(self.minimal)
            del value[key]
            with self.subTest(key=key):
                self.assert_invalid(value, key)

    def test_identity_values_must_be_non_empty_strings(self) -> None:
        for key, invalid in (
            ("productId", 1),
            ("targetAvatar", []),
            ("sourceReference", ""),
        ):
            value = copy.deepcopy(self.minimal)
            value[key] = invalid
            with self.subTest(key=key, invalid=invalid):
                self.assert_invalid(value, key)

    def test_variables_must_be_an_object(self) -> None:
        value = copy.deepcopy(self.minimal)
        value["variables"] = []
        self.assert_invalid(value, "variables")

    def test_stage_binding_requires_non_empty_command_and_result_path(self) -> None:
        valid = copy.deepcopy(self.minimal)
        valid["stageBindings"] = {
            "any-stage": {
                "command": ["python", "tool.py"],
                "resultPath": ".image2outfit/result.json",
            }
        }
        self.assert_valid(valid)

        empty_command = copy.deepcopy(valid)
        empty_command["stageBindings"]["any-stage"]["command"] = []
        self.assert_invalid(empty_command, "command")

        missing_result = copy.deepcopy(valid)
        del missing_result["stageBindings"]["any-stage"]["resultPath"]
        self.assert_invalid(missing_result, "resultPath")

    def test_stage_binding_command_items_must_be_non_empty_strings(self) -> None:
        value = copy.deepcopy(self.minimal)
        value["stageBindings"] = {
            "any-stage": {
                "command": ["python", ""],
                "resultPath": ".image2outfit/result.json",
            }
        }
        self.assert_invalid(value, "command")

    def test_tool_requirements_values_must_be_unique_string_lists(self) -> None:
        valid = copy.deepcopy(self.minimal)
        valid["toolRequirements"] = {"any-stage": ["cloth", "deterministic"]}
        self.assert_valid(valid)

        wrong_shape = copy.deepcopy(valid)
        wrong_shape["toolRequirements"] = {"any-stage": "cloth"}
        self.assert_invalid(wrong_shape, "toolRequirements")

        duplicate = copy.deepcopy(valid)
        duplicate["toolRequirements"] = {"any-stage": ["cloth", "cloth"]}
        self.assert_invalid(duplicate, "unique")

    def test_tool_pins_values_must_be_non_empty_strings(self) -> None:
        valid = copy.deepcopy(self.minimal)
        valid["toolPins"] = {"any-stage": "tool-a"}
        self.assert_valid(valid)

        invalid = copy.deepcopy(valid)
        invalid["toolPins"] = {"any-stage": {"tool": "tool-a"}}
        self.assert_invalid(invalid, "toolPins")

    def test_optional_scalar_fields_keep_existing_types(self) -> None:
        valid = copy.deepcopy(self.minimal)
        valid.update(
            {
                "revisionId": "",
                "runId": "run-1",
                "profilePath": "config/pipeline-profiles/garment-reconstruction-v1.json",
            }
        )
        self.assert_valid(valid)

        for key, invalid in (("revisionId", 1), ("runId", 1), ("profilePath", [])):
            value = copy.deepcopy(valid)
            value[key] = invalid
            with self.subTest(key=key):
                self.assert_invalid(value, key)

    def test_run_id_and_profile_path_reject_empty_strings(self) -> None:
        for key in ("runId", "profilePath"):
            value = copy.deepcopy(self.minimal)
            value[key] = ""
            with self.subTest(key=key):
                self.assert_invalid(value, key)

    def test_unknown_top_level_fields_fail_closed(self) -> None:
        value = copy.deepcopy(self.minimal)
        value["unexpected"] = True
        self.assert_invalid(value, "unexpected")

    def test_stage_name_semantics_remain_outside_request_schema(self) -> None:
        value = copy.deepcopy(self.minimal)
        value["stageBindings"] = {
            "not-a-canonical-stage": {
                "command": ["python", "tool.py"],
                "resultPath": ".image2outfit/result.json",
            }
        }
        self.assert_valid(value)

    def test_invalid_request_fails_before_profile_fingerprint_or_registry(self) -> None:
        value = copy.deepcopy(self.minimal)
        value["productId"] = 123
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            request_path = Path(directory) / "invalid-request.json"
            request_path.write_text(json.dumps(value), encoding="utf-8")
            args = argparse.Namespace(
                request=request_path,
                profile=None,
                engine="deterministic",
                execute=False,
                output=None,
                resume_state=None,
                checkpoint_output=None,
                audit_root=Path(".image2outfit/audit"),
            )
            with (
                mock.patch.object(runner, "parse_args", return_value=args),
                mock.patch.object(runner, "load_profile") as load_profile,
                mock.patch.object(
                    runner, "pipeline_source_fingerprint"
                ) as fingerprint,
                mock.patch.object(runner, "build_registry") as build_registry,
            ):
                with self.assertRaisesRegex(ValueError, "invalid pipeline request"):
                    runner.main()
                load_profile.assert_not_called()
                fingerprint.assert_not_called()
                build_registry.assert_not_called()

    def test_request_schema_bytes_change_pipeline_source_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "src/image2outfit/source.py": "pass\n",
                "tools/tool.py": "pass\n",
                "config/products/demo/job.json": "{}\n",
                "config/pipeline/request.json": "{}\n",
                "config/pipeline/profile.json": "{}\n",
                "config/pipeline/pipeline-request.schema.v1.json": "{}\n",
                "config/pipeline/visual-quality-defaults.v1.json": "{}\n",
                "config/toolchain-lock.json": "{}\n",
                "pyproject.toml": "[project]\nname='demo'\n",
                "uv.lock": "version = 1\n",
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            request_path = root / "config/pipeline/request.json"
            profile_path = root / "config/pipeline/profile.json"
            before = source_fingerprint.pipeline_source_fingerprint(
                root,
                product_id="demo",
                request_path=request_path,
                profile_path=profile_path,
            )
            schema_path = root / "config/pipeline/pipeline-request.schema.v1.json"
            schema_path.write_text('{"type":"object"}\n', encoding="utf-8")
            after = source_fingerprint.pipeline_source_fingerprint(
                root,
                product_id="demo",
                request_path=request_path,
                profile_path=profile_path,
            )
            self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
