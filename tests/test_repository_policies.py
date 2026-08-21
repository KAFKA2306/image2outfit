from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TOOLS))

import audit_runtime_layout  # noqa: E402
from image2outfit.architecture import (  # noqa: E402
    FORBIDDEN_SRC_IMPORT_ROOTS,
    audit_src_boundaries,
)

ENTRYPOINTS = (
    TOOLS / "run_garment_pipeline.py",
    TOOLS / "audit_src_architecture.py",
    TOOLS / "pipeline_stage_adapters.py",
    TOOLS / "run_blender_stage.py",
)


class ArchitecturePolicyTests(unittest.TestCase):
    def test_machine_policy_matches_core_boundary(self) -> None:
        policy = json.loads(
            (ROOT / "config/pipeline/architecture-policy.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(policy["dependencyDirection"], "tools-to-src-only")
        self.assertEqual(
            set(policy["forbiddenCoreImports"]), set(FORBIDDEN_SRC_IMPORT_ROOTS)
        )

    def test_src_does_not_import_blender_or_tools(self) -> None:
        self.assertEqual(audit_src_boundaries(ROOT), ())


class RepositoryLayoutPolicyTests(unittest.TestCase):
    def test_entrypoints_are_tracked_as_plain_python(self) -> None:
        for path in ENTRYPOINTS:
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), str(path))
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_no_job_uses_removed_products_intermediate_root(self) -> None:
        violations = []
        for path in (ROOT / "config/products").glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8-sig"))
            if "/Products/" in str(job.get("productRoot", "")):
                violations.append(path.parent.name)
        self.assertEqual([], violations)

    def test_repository_uses_single_internal_runtime_layout(self) -> None:
        result = audit_runtime_layout.audit(ROOT)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(
            result["runtimePattern"],
            ".image2outfit/products/<product-id>/{reports,candidate,release}",
        )

    def test_python_tasks_cover_every_reusable_source_root(self) -> None:
        taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
        for command in (
            "python -m compileall -q src tools tests",
            "ruff check --ignore S102 src tools tests",
            "ruff format src tools tests",
            "python tools/manage.py audit all",
            "python -m unittest discover -s tests -v",
        ):
            with self.subTest(command=command):
                self.assertIn(command, taskfile)


class ReleasePolicyTests(unittest.TestCase):
    def test_only_customer_quality_defines_human_release_validation(self) -> None:
        definitions = []
        for path in TOOLS.glob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            if "def evidence_gate(" in source:
                definitions.append(path.name)
        self.assertEqual([], definitions)
        policy = (ROOT / "config/release-policy.json").read_text(encoding="utf-8")
        self.assertIn('"singleReleaseValidator": "tools/customer_quality.py"', policy)


class CandidateOrchestratorPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (TOOLS / "candidate_orchestrator.py").read_text(encoding="utf-8")

    def test_candidate_orchestrator_checks_manifest_before_commit(self) -> None:
        state_check = self.source.index("contract.product_state_errors")
        candidate_commit = self.source.index("candidate_tx.commit")
        workspace_commit = self.source.index("workspace_tx.commit")
        self.assertLess(state_check, candidate_commit)
        self.assertLess(state_check, workspace_commit)

    def test_workspace_snapshot_wraps_generation(self) -> None:
        begin = self.source.index("workspace_tx.begin")
        build = self.source.index("legacy.run_candidate")
        rollback = self.source.index("workspace_tx.rollback")
        self.assertLess(begin, build)
        self.assertLess(build, rollback)
