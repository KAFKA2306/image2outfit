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
import review_console


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
        self.assertEqual(result["candidates"][0]["capabilityId"], "structured-patterns")
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
        baseline = improvement.run_experiment_method(self.root, manifest, "baseline")
        candidate = improvement.run_experiment_method(self.root, manifest, "candidate")
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
        result = improvement.run_experiment_method(self.root, manifest, "candidate")
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
        self.quality_report("dress", [{"aspect": "silhouette", "code": "BAD"}])
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

    def test_plan_generates_research_request_only_when_registry_has_no_candidate(
        self,
    ) -> None:
        self.quality_report("dress", [{"aspect": "skinning", "code": "POSE_FAIL"}])
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

    def executable_pattern_candidate(
        self,
        *,
        comparison: dict | None,
    ) -> dict:
        baseline_code = (
            "import json,pathlib; "
            "pathlib.Path('baseline.json').write_text(json.dumps({'status':'PASS'}))"
        )
        result = {"status": "PASS"}
        if comparison is not None:
            result["comparison"] = comparison
        candidate_code = (
            "import json,pathlib; "
            f"pathlib.Path('candidate.json').write_text(json.dumps({result!r}))"
        )
        return {
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

    def use_pattern_candidate(self, *, comparison: dict | None) -> None:
        self.oss = {
            "implementationCandidates": [
                self.executable_pattern_candidate(comparison=comparison)
            ]
        }
        self.write_registries()

    def test_missing_candidate_waits_for_external_research_with_request(self) -> None:
        self.quality("skinning")
        result = improvement_loop.advance(self.root, self.product)
        self.assertEqual(result["status"], "WAITING_FOR_EXTERNAL_RESEARCH")
        request = self.root / improvement.RESEARCH_REQUEST_PATH.format(
            product=self.product
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
        self.use_pattern_candidate(
            comparison={
                "eligibleForAdoption": False,
                "reproducible": True,
                "regressions": [],
            }
        )
        result = improvement_loop.advance(self.root, self.product)
        self.assertEqual(result["status"], "ITERATION_RECORDED")
        self.assertEqual(result["decision"], "KEEP_BENCHMARK")
        history = improvement.load_iteration_records(self.root, self.product)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["decision"], "KEEP_BENCHMARK")
        self.assertEqual(history[0]["methodsTried"][0]["candidateId"], "pattern-tool")

    def test_waiting_comparison_resumes_from_digest_bound_artifact(self) -> None:
        self.quality("silhouette")
        self.use_pattern_candidate(comparison=None)
        first = improvement_loop.advance(self.root, self.product)
        self.assertEqual(first["status"], "WAITING_FOR_COMPARISON")
        summary_path = (
            improvement_loop.reports_dir(self.root, self.product)
            / improvement_loop.EXPERIMENT_SUMMARY
        )
        summary = improvement.read_json(summary_path)
        comparison_path = (
            improvement_loop.reports_dir(self.root, self.product)
            / improvement_loop.EXPERIMENT_COMPARISON
        )
        write(
            comparison_path,
            {
                "schemaVersion": 1,
                "summaryDigest": summary["summaryDigest"],
                "candidateMethod": "candidate",
                "comparison": {
                    "eligibleForAdoption": False,
                    "reproducible": True,
                    "regressions": [],
                },
            },
        )
        second = improvement_loop.advance(self.root, self.product)
        self.assertEqual(second["status"], "ITERATION_RECORDED")
        self.assertEqual(second["decision"], "KEEP_BENCHMARK")
        self.assertEqual(
            len(improvement.load_iteration_records(self.root, self.product)), 1
        )

    def test_stale_comparison_digest_is_rejected(self) -> None:
        self.quality("silhouette")
        self.use_pattern_candidate(comparison=None)
        first = improvement_loop.advance(self.root, self.product)
        self.assertEqual(first["status"], "WAITING_FOR_COMPARISON")
        comparison_path = (
            improvement_loop.reports_dir(self.root, self.product)
            / improvement_loop.EXPERIMENT_COMPARISON
        )
        write(
            comparison_path,
            {
                "schemaVersion": 1,
                "summaryDigest": "stale",
                "candidateMethod": "candidate",
                "comparison": {
                    "eligibleForAdoption": False,
                    "reproducible": True,
                    "regressions": [],
                },
            },
        )
        with self.assertRaisesRegex(improvement_loop.LoopError, "summaryDigest"):
            improvement_loop.advance(self.root, self.product)

    def test_adoption_resumes_after_apply_binding_and_does_not_reapply(self) -> None:
        self.quality("silhouette")
        self.use_pattern_candidate(
            comparison={
                "eligibleForAdoption": True,
                "reproducible": True,
                "regressions": [],
            }
        )
        first = improvement_loop.advance(self.root, self.product, regenerate=lambda: 0)
        self.assertEqual(first["status"], "WAITING_FOR_PRODUCTION_INTEGRATION")

        marker = self.root / "applied.txt"
        apply_code = (
            "from pathlib import Path; "
            "p=Path('applied.txt'); "
            "p.write_text((p.read_text() if p.exists() else '')+'applied\\n')"
        )
        binding_path = (
            improvement_loop.reports_dir(self.root, self.product)
            / improvement_loop.EXPERIMENT_BINDING
        )
        write(
            binding_path,
            {
                "candidateId": "pattern-tool",
                "capability": "structured-patterns",
                "applyCommand": [sys.executable, "-c", apply_code],
            },
        )
        second = improvement_loop.advance(self.root, self.product, regenerate=lambda: 0)
        self.assertEqual(second["status"], "WAITING_FOR_REEVALUATION")
        self.assertEqual(marker.read_text(), "applied\n")
        history = improvement.load_iteration_records(self.root, self.product)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["decision"], "ADOPT")

        third = improvement_loop.advance(self.root, self.product, regenerate=lambda: 0)
        self.assertEqual(third["status"], "WAITING_FOR_REEVALUATION")
        self.assertEqual(marker.read_text(), "applied\n")


class ImprovementReviewProjectionTests(unittest.TestCase):
    def test_canonical_review_console_receives_improvement_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            product = "example"
            workspace = root / "Assets" / "GenWorks" / product
            workspace.mkdir(parents=True)
            (workspace / "ProductManifest.json").write_text(
                json.dumps({"status": "WORKING"}),
                encoding="utf-8",
            )
            plan = {
                "schemaVersion": 1,
                "productId": product,
                "candidateHash": "a" * 64,
                "status": "WAITING",
                "missingCapability": "structured-patterns",
                "selectedMethod": {"candidateId": "pattern-tool"},
                "nextAction": "WAITING_FOR_EXPERIMENT_BINDING",
                "createdAt": "2026-08-20T00:00:00Z",
            }
            plan["planDigest"] = improvement.digest_value(plan)
            improvement.persist_plan(root, product, plan)
            output = root / ".image2outfit" / "review-console"
            output.mkdir(parents=True)

            projected = review_console.collect_product(
                root,
                workspace,
                output,
                ["front"],
                [],
            )

            self.assertEqual(projected.resume_point, "WAITING_FOR_EXPERIMENT_BINDING")
            self.assertTrue(
                any(row["severity"] == "IMPROVEMENT" for row in projected.blockers)
            )
            self.assertTrue(
                any(gate.name == "improvement:next-action" for gate in projected.gates)
            )
            self.assertTrue(
                any(
                    evidence.label == "Improvement plan"
                    for evidence in projected.evidence
                )
            )


if __name__ == "__main__":
    unittest.main()
