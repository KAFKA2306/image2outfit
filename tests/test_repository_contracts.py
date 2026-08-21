from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import release_gate as gate  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class RepositoryContractTest(unittest.TestCase):
    def test_single_documentation_authority(self) -> None:
        documents = (ROOT / "README.md", ROOT / "AGENTS.md")
        for path in documents:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"Missing root document: {path.name}")

        self.assertFalse(
            (ROOT / "docs").exists(),
            "Repository-wide guidance belongs in root README.md or AGENTS.md",
        )
        nested_agents = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("AGENTS.md")
            if path != ROOT / "AGENTS.md"
        )
        self.assertEqual([], nested_agents)

        text_by_path = {path: path.read_text(encoding="utf-8") for path in documents}
        combined = "\n".join(text_by_path.values())
        for required in (
            "config/products/<slug>/",
            "Assets/GenWorks/<slug>/",
            "task audit:all",
            "task check:python",
            ".image2outfit/products/<slug>/{reports,candidate,release}",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

        for obsolete_root in ("Artifacts", "Candidates", "Release"):
            with self.subTest(obsolete_root=obsolete_root):
                self.assertFalse(
                    (ROOT / obsolete_root).exists(),
                    f"Deprecated root workspace must stay absent: {obsolete_root}/",
                )

        for forbidden in (
            "docs/GENWORKS_LAYOUT.md",
            "docs/TOOLCHAIN.md",
            ".github/AGENTS.md",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(
                    any(f"]({forbidden})" in text for text in text_by_path.values())
                )

    def test_deprecated_paths_and_workflows_are_absent(self) -> None:
        for path in (
            ROOT / "Assets" / "GenWorks" / "Legacy",
            ROOT / ".github" / "run",
            ROOT / ".github" / "status",
            ROOT / "tools" / "audit_snapshot.py",
            ROOT / "tools" / "package_snapshot.py",
        ):
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertFalse(path.exists())

        published = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_dir() and path.name.casefold() == "published"
        )
        self.assertEqual([], published)

        workflows = ROOT / ".github" / "workflows"
        self.assertTrue((workflows / "build-product-hosted.yml").is_file())
        for obsolete in (
            "siroino-wide-cargo-hosted.yml",
            "siroino-wide-cargo-self-hosted.yml",
            "siroino-wide-cargo-release.yml",
            "siroino-cyber-kawaii-large.yml",
            "genworks-siroino-render-loop.yml",
        ):
            with self.subTest(obsolete=obsolete):
                self.assertFalse((workflows / obsolete).exists())

    def test_layout_and_snapshot_contracts_are_canonical(self) -> None:
        policy = read_json(ROOT / "config" / "genworks-handoff-policy.json")
        self.assertEqual(policy["canonicalRoot"], "Assets/GenWorks")
        self.assertEqual(policy["localRuntimeRoot"], ".image2outfit")
        self.assertEqual(policy["workspaceSnapshotSchemaVersion"], 1)
        self.assertEqual(
            policy["workspaceSnapshotTool"], "tools/workspace_transaction.py"
        )

    def test_release_and_handoff_policies_are_current(self) -> None:
        handoff = read_json(ROOT / "config" / "genworks-handoff-policy.json")
        release = read_json(ROOT / "config" / "release-policy.json")
        self.assertEqual(handoff["schemaVersion"], 3)
        self.assertEqual(release["schemaVersion"], 3)
        self.assertIn("visualAppearanceReview", handoff["requiredCompletionGates"])
        self.assertIn("researchTrial", handoff["requiredCompletionGates"])

    def test_schemas_are_closed_and_authoritative(self) -> None:
        for relative in (
            "config/job.schema.v2.json",
            "config/products/construction.schema.v1.json",
            "config/pipeline/stage-result.schema.v1.json",
            "config/pipeline/stage-audit-record.schema.v1.json",
            "config/pipeline/run-audit-manifest.schema.v1.json",
        ):
            schema = read_json(ROOT / relative)
            with self.subTest(relative=relative):
                self.assertEqual(schema.get("additionalProperties"), False)

    def test_every_product_has_a_verifiable_canonical_handoff(self) -> None:
        products_root = ROOT / "config" / "products"
        product_ids = sorted(
            path.name
            for path in products_root.iterdir()
            if path.is_dir() and (path / "job.json").is_file()
        )
        self.assertGreater(len(product_ids), 0)
        for product_id in product_ids:
            with self.subTest(product_id=product_id):
                job = read_json(products_root / product_id / "job.json")
                self.assertEqual(job["id"], product_id)
                manifest_path = ROOT / "Assets" / "GenWorks" / product_id / "ProductManifest.json"
                self.assertTrue(manifest_path.is_file())
                manifest = read_json(manifest_path)
                self.assertEqual(manifest["productId"], product_id)

    def test_unity_adapter_and_release_boundary_remain_current(self) -> None:
        handoff = read_json(ROOT / "config" / "genworks-handoff-policy.json")
        self.assertIn("unityImport", handoff["outOfScope"])
        self.assertIn("vrchatRuntime", handoff["outOfScope"])
        with self.assertRaises(SystemExit):
            gate.main(["release", "--job", "missing.json"])


if __name__ == "__main__":
    unittest.main()
