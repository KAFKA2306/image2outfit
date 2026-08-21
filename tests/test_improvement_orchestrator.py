from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit import improvement
import improvement_loop


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class ImprovementOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.product = "dress"
        self.methods = {
            "capabilities": [
                {"id": "structured-patterns"},
                {"id": "runtime-deformation"},
            ],
            "publications": [],
            "methodAssessments": [],
            "licenseAssessments": [],
        }
        self.oss = {"implementationCandidates": []}
        self.write_registries()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_registries(self) -> None:
        write(self.root / improvement.METHODS_PATH, self.methods)
        write(self.root / improvement.OSS_PATH, self.oss)

    def quality(self, aspect: str) -> None:
        write(
            self.root / improvement.QUALITY_REPORT.format(product=self.product),
            {
                "candidateManifestSha256": "a" * 64,
                "evidence": {
                    "qualitySpec": {
                        "defects": [
                            {
                                "aspect": aspect,
                                "code": "REFERENCE_MISMATCH",
                                "recommendedReturnStage": "draft-patterns",
                            }
                        ]
                    }
                },
            },
        )

    def test_missing_candidate_waits_for_external_research_with_request(self) -> None:
        self.quality("skinning")
        result = improvement_loop.advance(self.root, self.product)
        self.assertEqual(result["status"], "WAITING_FOR_EXTERNAL_RESEARCH")
        request = (
            self.root
            / improvement.RESEARCH_REQUEST_PATH.format(product=self.product)
        )
        self.assertTrue(request.is_file())
        self.assertEqual(
            improvement.read_json(request)["missingCapability"],
            "runtime-deformation",
        )

    def test_research_result_must_match_current_request_digest(self) -> None:
        self.quality("skinning")
        first = improvement_loop.advance(self.root, self.product)
        result_path = (
            improvement_loop.reports_dir(self.root, self.product)
            / improvement_loop.RESEARCH_RESULT
        )
        write(
            result_path,
            {
                "schemaVersion": 1,
                "requestDigest": "wrong",
                "candidates": [],
            },
        )
        self.assertEqual(first["status"], "WAITING_FOR_EXTERNAL_RESEARCH")
        with self.assertRaisesRegex(improvement_loop.LoopError, "requestDigest"):
            improvement_loop.advance(self.root, self.product)

    def test_verified_research_candidate_resumes_to_binding_boundary(self) -> None:
        self.quality("skinning")
        first = improvement_loop.advance(self.root, self.product)
        request_digest = first["plan"]["researchRequest"]["requestDigest"]
        result_path = (
            improvement_loop.reports_dir(self.root, self.product)
            / improvement_loop.RESEARCH_RESULT
        )
        write(
            result_path,
            {
                "schemaVersion": 1,
                "requestDigest": request_digest,
                "candidates": [
                    {
                        "canonicalName": "Measured Deformation Tool",
                        "primaryUrls": ["https://example.test/tool"],
                        "checkedAt": "2026-08-21T00:00:00Z",
                        "licenseStatus": "VERIFIED",
                        "license": "MIT",
                    }
                ],
            },
        )
        second = improvement_loop.advance(self.root, self.product)
        self.assertEqual(second["status"], "WAITING_FOR_EXPERIMENT_BINDING")
        self.assertEqual(
            second["selectedMethod"]["canonicalName"],
            "Measured Deformation Tool",
        )

    def test_bound_experiment_records_measured_rejection_and_history(self) -> None:
        self.quality("silhouette")
        baseline_code = (
            "import json,pathlib; "
            "pathlib.Path('baseline.json').write_text(json.dumps({'status':'PASS'}))"
        )
        candidate_code = (
            "import json,pathlib; "
            "pathlib.Path('candidate.json').write_text(json.dumps({"
            "'status':'PASS','comparison':{'eligibleForAdoption':False,"
            "'reproducible':True,'regressions':[]}}))"
        )
        self.oss = {
            "implementationCandidates": [
                {
                    "id": "pattern-tool",
                    "name": "Pattern Tool",
                    "category": "PARAMETRIC_SEWING_PATTERN",
                    "officialUrl": "https://example.test/pattern-tool",
                    "codeLicense": "MIT",
                    "decision": "ADOPT_NOW",
                    "integrationBoundary": "draft-patterns",
                    "experimentBinding": {
                        "baseline": {
                            "id": "baseline",
                            "command": [sys.executable, "-c", baseline_code],
                            "resultPath": "baseline.json",
                        },
                        "candidate": {
                            "id": "candidate",
                            "command": [sys.executable, "-c", candidate_code],
                            "resultPath": "candidate.json",
                        },
                        "evaluation": {
                            "views": ["front"],
                            "poses": [],
                            "qualitySpec": "quality-spec.v1",
                        },
                        "productionIntegrationPoint": "draft-patterns",
                    },
                }
            ]
        }
        self.write_registries()

        result = improvement_loop.advance(self.root, self.product)

        self.assertEqual(result["status"], "ITERATION_RECORDED")
        self.assertEqual(result["decision"], "KEEP_BENCHMARK")
        history = improvement.load_iteration_records(self.root, self.product)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["decision"], "KEEP_BENCHMARK")
        self.assertEqual(
            history[0]["methodsTried"][0]["candidateId"],
            "pattern-tool",
        )


if __name__ == "__main__":
    unittest.main()
