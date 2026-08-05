from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_repository_hygiene  # noqa: E402


class RepositoryHygieneTest(unittest.TestCase):
    def test_repository_has_no_committed_operational_residue(self) -> None:
        result = audit_repository_hygiene.audit(ROOT)
        self.assertTrue(
            result["passed"],
            "\n".join(
                f"{item['code']}: {item['path']} — {item['message']}"
                for item in result["findings"]
            ),
        )

    def test_ref_only_branch_cleanup_is_allowed(self) -> None:
        workflow = Path("branch-hygiene.yml")
        source = """
permissions:
  contents: write
steps:
  - uses: actions/github-script@v7
    with:
      script: |
        const protectedBranches = new Set(['main']);
        await github.rest.git.deleteRef({ref: `heads/${branch}`});
""".lower()
        self.assertTrue(
            audit_repository_hygiene.is_ref_only_branch_hygiene(workflow, source)
        )

    def test_branch_cleanup_with_checkout_is_rejected(self) -> None:
        workflow = Path("branch-hygiene.yml")
        source = """
permissions:
  contents: write
steps:
  - uses: actions/checkout@v4
  - uses: actions/github-script@v7
    with:
      script: |
        const protectedBranches = new Set(['main']);
        await github.rest.git.deleteRef({ref: `heads/${branch}`});
""".lower()
        self.assertFalse(
            audit_repository_hygiene.is_ref_only_branch_hygiene(workflow, source)
        )

    def test_branch_cleanup_with_content_update_is_rejected(self) -> None:
        workflow = Path("branch-hygiene.yml")
        source = """
permissions:
  contents: write
steps:
  - uses: actions/github-script@v7
    with:
      script: |
        const protectedBranches = new Set(['main']);
        await github.rest.git.deleteRef({ref: `heads/${branch}`});
        await github.rest.repos.createOrUpdateFileContents({path: 'state.json'});
""".lower()
        self.assertFalse(
            audit_repository_hygiene.is_ref_only_branch_hygiene(workflow, source)
        )

    def test_unrelated_write_workflow_is_rejected(self) -> None:
        workflow = Path("publish.yml")
        source = """
permissions:
  contents: write
steps:
  - uses: actions/github-script@v7
    with:
      script: |
        const protectedBranches = new Set(['main']);
        await github.rest.git.deleteRef({ref: `heads/${branch}`});
""".lower()
        self.assertFalse(
            audit_repository_hygiene.is_ref_only_branch_hygiene(workflow, source)
        )


if __name__ == "__main__":
    unittest.main()
