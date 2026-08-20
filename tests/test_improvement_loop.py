from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit import improvement


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class ImprovementLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write(
            self.root / improvement.METHODS_PATH,
            {
                "capabilities": [
                    {"id": "structured-patterns"},
                    {"id": "runtime-deformation"},
                    {"id": "pbr-texture"},
                ],
                "publications": [
                    {
                        "id": "paper",
                        "title": "Paper",
                        "year": 2026,
                        "officialUrl": "https://example.test/paper",
                    }
                ],
                "methodAssessments": [
                    {
                        "id": "assessment:paper",
                        "publicationId": "paper",
                        "decision": "BENCHMARK",
                        "capabilityIds": ["structured-patterns"],
                    }
                ],
                "licenseAssessments": [
                    {"publicationId": "paper", "declaredLicense": "MIT"}
                ],
            },
        )
        write(
            self.root / improvement.OSS_PATH,
            {
                "implementationCandidates": [
                    {
                        "id": "pattern-tool",
                        "name": "Pattern Tool",
                        "category": "PARAMETRIC_SEWING_PATTERN",
                        "officialUrl": "https://github.com/example/pattern-tool",
                        "codeLicense": "MIT",
                        "decision": "ADOPT_NOW",
                    },
                    {
                        "id": "watch",
                        "name": "Watch",
                        "category": "PARAMETRIC_SEWING_PATTERN",
                        "officialUrl": "https://github.com/example/watch",
                        "codeLicense": "MIT",
                        "decision": "WATCH_RELEASE",
                    },
                ]
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def quality_report(self, product: str, defects: list[dict]) -> None:
        write(
            self.root / improvement.QUALITY_REPORT.format(product=product),
            {
                "candidateManifestSha256": "a" * 64,
                "evidence": {"qualitySpec": {"defects": defects}},
            },
        )

    def test_defect_maps_to_capability_without_using_return_stage(self) -> None:
        result = improvement.capabilities_for_finding(
            {
                "aspect": "silhouette",
                "recommendedReturnStage": "build-blender",
                "evidence": [{"sha256": "b" * 64}],
            }
        )
        self.assertEqual(
            result["candidates"][0]["capabilityId"], "structured-patterns"
        )
        self.assertEqual(result["returnStage"], "build-blender")
        self.assertEqual(result["evidenceHashes"], ["b" * 64])

    def test_implemented_capability_is_distinct_from_capability_gap(self) -> None:
        result = improvement.capabilities_for_finding(
            {"aspect": "skinning"},
            implemented_capabilities={"runtime-deformation"},
        )
        self.assertEqual(
            result["candidates"][0]["classification"], "IMPLEMENTATION_DEFECT"
        )

    def test_existing_registry_is_used_before_external_research(self) -> None:
        index = improvement.load_research_index(self.root)
        rows = improvement.existing_candidates(index, "structured-patterns")
        self.assertEqual(rows[0]["candidateId"], "pattern-tool")
        self.assertNotIn("watch", {row["candidateId"] for row in rows})

    def test_rejected_exact_method_is_not_reproposed(self) -> None:
        index = improvement.load_research_index(self.root)
        row = improvement.existing_candidates(index, "structured-patterns")[0]
        rows = improvement.existing_candidates(
            index,
            "structured-patterns",
            rejected_method_keys={improvement.candidate_method_key(row)},
        )
        self.assertNotIn("pattern-tool", {item["candidateId"] for item in rows})

    def test_research_request_keeps_failure_context(self) -> None:
        request = improvement.make_research_request(
            product_id="dress",
            candidate_hash="a" * 64,
            finding={"aspect": "skinning", "code": "POSE_FAIL", "pose": "sit"},
            capability_id="runtime-deformation",
            attempted_methods=[{"candidateId": "old"}],
        )
        self.assertEqual(request["missingCapability"], "runtime-deformation")
        self.assertEqual(request["defect"]["pose"], "sit")
        self.assertEqual(len(request["requestDigest"]), 64)

    def test_experiment_runner_requires_structured_pass_result(self) -> None:
        manifest = {
            "schemaVersion": 1,
            "productId": "dress",
            "fixtureId": "fixture",
            "capability": "structured-patterns",
            "inputCandidateHash": "a" * 64,
            "evaluation": {
                "views": ["front"],
                "poses": [],
                "qualitySpec": "v1",
            },
            "methods": [
                {
                    "id": "baseline",
                    "role": "baseline",
                    "command": [
                        sys.executable,
                        "-c",
                        "import json,pathlib; p=pathlib.Path('baseline.json'); p.write_text(json.dumps({'status':'PASS'}))",
                    ],
                    "resultPath": "baseline.json",
                },
                {
                    "id": "candidate",
                    "role": "candidate",
                    "command": [
                        sys.executable,
                        "-c",
                        "import json,pathlib; p=pathlib.Path('candidate.json'); p.write_text(json.dumps({'status':'PASS'}))",
                    ],
                    "resultPath": "candidate.json",
                },
            ],
        }
        self.assertEqual(
            improvement.experiment_matrix(manifest), ["baseline", "candidate"]
        )
        baseline = improvement.run_experiment_method(
            self.root, manifest, "baseline"
        )
        candidate = improvement.run_experiment_method(
            self.root, manifest, "candidate"
        )
        self.assertEqual(baseline["status"], "PASS")
        self.assertEqual(candidate["status"], "PASS")
        summary = improvement.aggregate_experiment_results(self.root, manifest)
        self.assertTrue(summary["allRecorded"])

    def test_unbound_method_is_explicit_not_success(self) -> None:
        manifest = {
            "schemaVersion": 1,
            "productId": "dress",
            "fixtureId": "fixture",
            "capability": "structured-patterns",
            "inputCandidateHash": "a" * 64,
            "evaluation": {"views": [], "poses": [], "qualitySpec": "v1"},
            "methods": [
                {"id": "baseline", "role": "baseline"},
                {"id": "candidate", "role": "candidate"},
            ],
        }
        result = improvement.run_experiment_method(
            self.root, manifest, "candidate"
        )
        self.assertEqual(result["status"], "UNBOUND")

    def test_adoption_requires_measured_eligibility_and_license(self) -> None:
        adopted = improvement.make_adoption_decision(
            capability_id="structured-patterns",
            baseline={"methodId": "baseline"},
            candidate={
                "methodId": "candidate",
                "status": "PASS",
                "manifestDigest": "m",
            },
            comparison={
                "eligibleForAdoption": True,
                "reproducible": True,
                "regressions": [],
            },
            license_status="VERIFIED",
            integration_point="draft-patterns",
        )
        self.assertEqual(adopted["decision"], "ADOPT")
        rejected = improvement.make_adoption_decision(
            capability_id="structured-patterns",
            baseline={"methodId": "baseline"},
            candidate={
                "methodId": "candidate",
                "status": "PASS",
                "manifestDigest": "m",
            },
            comparison={
                "eligibleForAdoption": True,
                "reproducible": True,
                "regressions": [],
            },
            license_status="UNVERIFIED",
            integration_point="draft-patterns",
        )
        self.assertEqual(rejected["decision"], "REJECT")

    def test_history_reuse_precedes_registry_search(self) -> None:
        self.quality_report(
            "dress", [{"aspect": "silhouette", "code": "BAD"}]
        )
        improvement.append_iteration_record(
            self.root,
            "dress",
            {
                "missingCapability": "structured-patterns",
                "context": {"defectClass": "silhouette"},
                "methodsTried": [{"candidateId": "measured-method"}],
                "decision": "ADOPT",
            },
        )
        plan = improvement.plan_improvement(self.root, "dress")
        self.assertEqual(plan["nextAction"], "REUSE_MEASURED_METHOD")
        self.assertEqual(plan["selectedMethod"]["candidateId"], "measured-method")

    def test_plan_generates_research_request_only_when_registry_has_no_candidate(self) -> None:
        self.quality_report(
            "dress", [{"aspect": "skinning", "code": "POSE_FAIL"}]
        )
        plan = improvement.plan_improvement(self.root, "dress")
        self.assertEqual(plan["nextAction"], "RESEARCH_REQUIRED")
        self.assertEqual(
            plan["researchRequest"]["missingCapability"], "runtime-deformation"
        )

    def test_tracked_plan_is_reviewable_but_not_counted_as_iteration(self) -> None:
        plan = {
            "schemaVersion": 1,
            "productId": "dress",
            "status": "ACTIONABLE",
            "nextAction": "RUN_EXPERIMENT",
            "missingCapability": "structured-patterns",
            "selectedMethod": {"candidateId": "pattern-tool"},
        }
        improvement.persist_plan(self.root, "dress", plan)
        projection = improvement.review_projection(self.root, "dress")
        self.assertEqual(projection["nextAction"], "RUN_EXPERIMENT")
        self.assertEqual(projection["iterationCount"], 0)


if __name__ == "__main__":
    unittest.main()
