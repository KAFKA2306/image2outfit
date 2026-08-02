from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationContractTests(unittest.TestCase):
    def test_root_documents_are_present(self) -> None:
        self.assertTrue((ROOT / "README.md").is_file())
        self.assertTrue((ROOT / "AGENTS.md").is_file())

    def test_repository_level_docs_tree_is_absent(self) -> None:
        self.assertFalse(
            (ROOT / "docs").exists(),
            "Repository-wide guidance belongs in root README.md or AGENTS.md",
        )

    def test_no_nested_agent_contract_exists(self) -> None:
        nested = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("AGENTS.md")
            if path != ROOT / "AGENTS.md"
        )
        self.assertEqual(
            [],
            nested,
            f"Nested agent contracts duplicate root AGENTS.md: {nested}",
        )

    def test_root_documents_do_not_link_deleted_management_docs(self) -> None:
        forbidden = (
            "docs/GENWORKS_LAYOUT.md",
            "docs/TOOLCHAIN.md",
            ".github/AGENTS.md",
        )
        violations: list[str] = []
        for path in (ROOT / "README.md", ROOT / "AGENTS.md"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if f"]({token})" in text:
                    violations.append(f"{path.name}: {token}")
        self.assertEqual([], violations, f"Deleted document links remain: {violations}")

    def test_root_documents_define_one_internal_runtime_layout(self) -> None:
        pattern = ".image2outfit/products/<slug>/{reports,candidate,release}"
        for path in (ROOT / "README.md", ROOT / "AGENTS.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn(pattern, text, path.name)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("以前の `Artifacts/`、`Candidates/`、`Release/` は使用しません", readme)


if __name__ == "__main__":
    unittest.main()
