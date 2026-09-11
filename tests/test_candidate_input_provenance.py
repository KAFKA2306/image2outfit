from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import candidate_manifest  # noqa: E402


class CandidateInputProvenanceTest(unittest.TestCase):
    def test_verifier_requires_exact_input_key_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "candidate"
            candidate.mkdir()
            job = {"id": "product", "adapterId": "adapter"}
            base = {
                "schemaVersion": 2,
                "kind": "image2outfit-candidate",
                "jobId": "product",
                "adapterId": "adapter",
                "sourceCommit": "local",
                "files": [],
            }
            expected = {"job": "aaa", "executionSource": "bbb"}
            cases = [
                ({"job": "aaa", "executionSource": "bbb"}, None),
                ({"job": "aaa"}, "candidate inputs missing: executionSource"),
                ({}, "candidate inputs missing:"),
                (
                    {"job": "aaa", "executionSource": "bbb", "unknown": "ccc"},
                    "candidate inputs unexpected: unknown",
                ),
                (
                    {"job": "changed", "executionSource": "bbb"},
                    "candidate input changed: job",
                ),
            ]
            with patch.object(candidate_manifest, "inputs", return_value=expected):
                for reported, expected_error in cases:
                    data = dict(base, inputHashes=reported)
                    errors = candidate_manifest.verify_candidate(
                        Path("job.json"), job, candidate, data
                    )
                    if expected_error is None:
                        self.assertFalse(
                            any(error.startswith("candidate input") for error in errors),
                            errors,
                        )
                    else:
                        self.assertTrue(
                            any(expected_error in error for error in errors), errors
                        )

    def test_execution_source_fingerprint_tracks_source_closure_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper = root / "tools/shared_helper.py"
            construction = root / "config/products/wide-cargo/construction.json"
            pattern = (
                root
                / "Assets/GenWorks/wide-cargo/Source/Patterns/pattern-spec.json"
            )
            generated = (
                root
                / ".image2outfit/products/wide-cargo/candidate/candidate-manifest.json"
            )
            for file, content in (
                (helper, "VALUE = 1\n"),
                (construction, '{"method": "baseline"}\n'),
                (pattern, '{"waist": 1}\n'),
                (generated, '{"generated": 1}\n'),
            ):
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content, encoding="utf-8")

            job = {"id": "wide-cargo"}
            with patch.object(candidate_manifest, "ROOT", root):
                baseline = candidate_manifest.execution_source_fingerprint(job)

                pattern.write_text('{"waist": 2}\n', encoding="utf-8")
                pattern_changed = candidate_manifest.execution_source_fingerprint(job)
                self.assertNotEqual(baseline, pattern_changed)

                helper.write_text("VALUE = 2\n", encoding="utf-8")
                code_changed = candidate_manifest.execution_source_fingerprint(job)
                self.assertNotEqual(pattern_changed, code_changed)

                construction.write_text(
                    '{"method": "changed"}\n', encoding="utf-8"
                )
                construction_changed = candidate_manifest.execution_source_fingerprint(job)
                self.assertNotEqual(code_changed, construction_changed)

                generated.write_text('{"generated": 2}\n', encoding="utf-8")
                self.assertEqual(
                    construction_changed,
                    candidate_manifest.execution_source_fingerprint(job),
                )


if __name__ == "__main__":
    unittest.main()
