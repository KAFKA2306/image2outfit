from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from contract_io import validate_json_schema
from image2outfit.failure_contract import (
    ERROR_CODES,
    PHASES,
    failed_state_descriptor,
    failure_descriptor,
)

RUNNER = ROOT / "tools" / "run_garment_pipeline.py"
SCHEMA = ROOT / "config" / "pipeline" / "failure.schema.v1.json"


def _valid_request() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "productId": "siroino-blue-happi",
        "targetAvatar": "SiroinoSotai_PC",
        "sourceReference": "private-reference://sha256/failure-contract-test",
    }


def _load_runner():
    spec = importlib.util.spec_from_file_location("pipeline_failure_runner", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PipelineFailureContractTests(unittest.TestCase):
    def test_schema_and_runtime_enums_are_identical(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(tuple(schema["properties"]["errorCode"]["enum"]), ERROR_CODES)
        self.assertEqual(tuple(schema["properties"]["phase"]["enum"]), PHASES)
        sample = failure_descriptor("INVALID_PIPELINE_INPUT", "request", "bad request")
        self.assertEqual(validate_json_schema(sample, schema), [])

    def test_malformed_request_is_json_failure_and_output_matches_stdout(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base = Path(directory)
            request = base / "request.json"
            output = base / "failure.json"
            request.write_text("{not-json", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--request",
                    str(request),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stderr, "")
            self.assertEqual(output.read_text(encoding="utf-8"), completed.stdout)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "FAILED")
            self.assertEqual(payload["failure"]["errorCode"], "INVALID_PIPELINE_INPUT")
            self.assertEqual(payload["failure"]["phase"], "request")
            self.assertNotIn("Traceback", completed.stdout)

    def test_invalid_resume_boundary_is_stable_failure(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base = Path(directory)
            request = base / "request.json"
            resume = base / "resume.json"
            request.write_text(json.dumps(_valid_request()), encoding="utf-8")
            resume.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--request",
                    str(request),
                    "--resume-state",
                    str(resume),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["failure"]["errorCode"], "INVALID_RESUME_STATE")
            self.assertEqual(payload["failure"]["phase"], "resume")
            self.assertNotIn("Traceback", completed.stderr)

    def test_unavailable_optional_engine_has_stable_error_code(self) -> None:
        runner = _load_runner()
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            request = Path(directory) / "request.json"
            request.write_text(json.dumps(_valid_request()), encoding="utf-8")
            stdout = io.StringIO()
            argv = [str(RUNNER), "--request", str(request), "--engine", "langchain"]
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    runner,
                    "run_langchain",
                    side_effect=RuntimeError("LangChain Core is not installed"),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                code = runner.main()
            self.assertEqual(code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(
                payload["failure"]["errorCode"], "PIPELINE_ENGINE_UNAVAILABLE"
            )
            self.assertEqual(payload["failure"]["phase"], "pipeline")

    def test_stage_failure_exposes_stable_domain_cause_without_exception_class(
        self,
    ) -> None:
        descriptor = failed_state_descriptor(
            {
                "status": "FAILED",
                "current_stage": "draft-patterns",
                "outputs": {
                    "draft-patterns": {
                        "mode": "failed",
                        "error": "adapter rejected invalid pattern topology",
                        "errorType": "RuntimeError",
                    }
                },
            }
        )
        self.assertEqual(descriptor["errorCode"], "PIPELINE_EXECUTION_FAILED")
        self.assertEqual(descriptor["phase"], "pipeline")
        self.assertEqual(descriptor["stage"], "draft-patterns")
        self.assertEqual(descriptor["causeCode"], "STAGE_EXECUTION_FAILED")
        self.assertNotIn("errorType", descriptor)
        self.assertNotIn("RuntimeError", descriptor.values())


if __name__ == "__main__":
    unittest.main()
