from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HygieneDocumentationTest(unittest.TestCase):
    def test_documentation_matches_enforced_boundaries(self) -> None:
        text = (ROOT / "docs" / "REPOSITORY_HYGIENE.md").read_text(encoding="utf-8")
        for required in (
            "config/products/<product-id>/",
            "Assets/GenWorks/",
            "contents: write",
            "task audit:repo",
        ):
            self.assertIn(required, text)

    def test_only_generic_hosted_build_workflow_remains(self) -> None:
        workflows = ROOT / ".github" / "workflows"
        generic = workflows / "build-product-hosted.yml"
        self.assertTrue(generic.is_file())
        self.assertIn("job_path", generic.read_text(encoding="utf-8"))
        for obsolete in (
            "siroino-wide-cargo-hosted.yml",
            "siroino-wide-cargo-self-hosted.yml",
            "siroino-wide-cargo-release.yml",
            "siroino-cyber-kawaii-large.yml",
            "genworks-siroino-render-loop.yml",
            "render-validation.yml",
        ):
            self.assertFalse((workflows / obsolete).exists(), obsolete)

    def test_runtime_state_directories_are_not_committed(self) -> None:
        self.assertFalse((ROOT / ".github" / "run").exists())
        self.assertFalse((ROOT / ".github" / "status").exists())


if __name__ == "__main__":
    unittest.main()
