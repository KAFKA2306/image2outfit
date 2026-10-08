from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
for path in (SRC, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_garment_pipeline as runner
from image2outfit.pipeline import (
    ExecutionMode,
    new_pipeline_state,
    resume_pipeline_state,
)
from pipeline_source_fingerprint import pipeline_source_fingerprint


class PipelineStateSchemaTests(unittest.TestCase):
    def state(self) -> dict[str, object]:
        return new_pipeline_state(
            product_id="schema-fixture",
            target_avatar="avatar",
            source_reference="reference.png",
            execution_mode=ExecutionMode.PLAN,
            run_id="run-one",
        )

    def assert_valid(self, state: dict[str, object]) -> None:
        runner._validate_persisted_pipeline_state(state)

    def assert_invalid(self, state: dict[str, object], fragment: str) -> None:
        with self.assertRaisesRegex(ValueError, fragment):
            runner._validate_persisted_pipeline_state(state)

    def test_canonical_state_shapes_pass_shared_validator(self) -> None:
        fresh = self.state()
        self.assert_valid(fresh)

        one_stage = copy.deepcopy(fresh)
        one_stage["status"] = "PLANNING"
        one_stage["current_stage"] = "ingest-reference"
        one_stage["completed_stages"] = ["ingest-reference"]
        one_stage["outputs"] = {"ingest-reference": {"mode": "planned"}}
        self.assert_valid(one_stage)

        failed = copy.deepcopy(fresh)
        failed["status"] = "FAILED"
        failed["current_stage"] = "ingest-reference"
        failed["errors"] = ["ingest-reference: fixture failure"]
        failed["outputs"] = {
            "ingest-reference": {"mode": "failed", "error": "fixture failure"}
        }
        self.assert_valid(failed)

        resumed = resume_pipeline_state(one_stage, run_id="run-two")
        self.assert_valid(resumed)

    def test_schema_rejects_wrong_version_missing_identity_and_wrong_types(
        self,
    ) -> None:
        wrong_version = self.state()
        wrong_version["schema_version"] = 2
        self.assert_invalid(wrong_version, "schema_version")

        missing_run = self.state()
        del missing_run["run_id"]
        self.assert_invalid(missing_run, "run_id")

        wrong_outputs = self.state()
        wrong_outputs["outputs"] = []
        self.assert_invalid(wrong_outputs, "outputs")

        wrong_completed = self.state()
        wrong_completed["completed_stages"] = "ingest-reference"
        self.assert_invalid(wrong_completed, "completed_stages")

    def test_checkpoint_writer_fails_before_replacing_last_good_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "checkpoint.json"
            good = self.state()
            runner._write_pipeline_state_atomic(path, good)
            before = path.read_bytes()

            broken = copy.deepcopy(good)
            broken["outputs"] = []
            with self.assertRaisesRegex(ValueError, "schema validation"):
                runner._write_pipeline_state_atomic(path, broken)

            self.assertEqual(before, path.read_bytes())

    def test_resume_reader_rejects_malformed_state_before_adapter_registry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            work = Path(temp_dir)
            request_path = work / "request.json"
            resume_path = work / "resume.json"
            request_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "productId": "schema-fixture",
                        "targetAvatar": "avatar",
                        "sourceReference": "reference.png",
                    }
                ),
                encoding="utf-8",
            )
            broken = self.state()
            del broken["run_id"]
            resume_path.write_text(json.dumps(broken), encoding="utf-8")
            args = argparse.Namespace(
                request=request_path,
                profile=None,
                engine="deterministic",
                execute=False,
                output=None,
                resume_state=resume_path,
                checkpoint_output=None,
                audit_root=work / "audit",
            )
            with (
                patch.object(runner, "parse_args", return_value=args),
                patch.object(
                    runner,
                    "load_profile",
                    return_value={"profileId": "garment-reconstruction-v1"},
                ),
                patch.object(
                    runner, "pipeline_source_fingerprint", return_value="a" * 64
                ),
                patch.object(runner, "build_registry") as build_registry,
                self.assertRaisesRegex(ValueError, "run_id"),
            ):
                runner.main()
            build_registry.assert_not_called()

    def test_pipeline_schema_bytes_participate_in_source_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {
                "src/image2outfit/dummy.py": "pass\n",
                "tools/dummy.py": "pass\n",
                "config/products/schema-fixture/job.json": "{}\n",
                "config/products/schema-fixture/request.json": "{}\n",
                "config/pipeline-profiles/profile.json": "{}\n",
                "config/pipeline/visual-quality-defaults.v1.json": "{}\n",
                "config/pipeline/pipeline-state.schema.v1.json": '{"version":1}\n',
                "config/toolchain-lock.json": "{}\n",
                "pyproject.toml": "[project]\nname='fixture'\n",
                "uv.lock": "fixture\n",
            }
            for relative, content in paths.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            request_path = root / "config/products/schema-fixture/request.json"
            profile_path = root / "config/pipeline-profiles/profile.json"
            before = pipeline_source_fingerprint(
                root,
                product_id="schema-fixture",
                request_path=request_path,
                profile_path=profile_path,
            )
            schema_path = root / "config/pipeline/pipeline-state.schema.v1.json"
            schema_path.write_text('{"version":2}\n', encoding="utf-8")
            after = pipeline_source_fingerprint(
                root,
                product_id="schema-fixture",
                request_path=request_path,
                profile_path=profile_path,
            )
            self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
