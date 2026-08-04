from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_repository_hygiene  # noqa: E402


class RepositoryHygieneTest(unittest.TestCase):
    @staticmethod
    def evaluate(workflow: str, source: str) -> bool:
        return audit_repository_hygiene.is_ref_only_branch_hygiene(
            Path(workflow),
            source.lower(),
        )

    def test_ref_only_branch_cleanup_is_allowed(self) -> None:
        source = """
permissions:
  contents: write
steps:
  - uses: actions/github-script@v7
    with:
      script: |
        const protectedBranches = new Set(['main']);
        await github.rest.git.deleteRef({ref: `heads/${branch}`});
"""
        self.assertTrue(self.evaluate("branch-hygiene.yml", source))

    def test_mutating_and_unrelated_workflows_are_rejected(self) -> None:
        cases = {
            "checkout": (
                "branch-hygiene.yml",
                """
permissions:
  contents: write
steps:
  - uses: actions/checkout@v4
  - uses: actions/github-script@v7
    with:
      script: |
        const protectedBranches = new Set(['main']);
        await github.rest.git.deleteRef({ref: `heads/${branch}`});
""",
            ),
            "content-update": (
                "branch-hygiene.yml",
                """
permissions:
  contents: write
steps:
  - uses: actions/github-script@v7
    with:
      script: |
        const protectedBranches = new Set(['main']);
        await github.rest.git.deleteRef({ref: `heads/${branch}`});
        await github.rest.repos.createOrUpdateFileContents({path: 'state.json'});
""",
            ),
            "unrelated-workflow": (
                "publish.yml",
                """
permissions:
  contents: write
steps:
  - uses: actions/github-script@v7
    with:
      script: |
        const protectedBranches = new Set(['main']);
        await github.rest.git.deleteRef({ref: `heads/${branch}`});
""",
            ),
        }
        for name, (workflow, source) in cases.items():
            with self.subTest(case=name):
                self.assertFalse(self.evaluate(workflow, source))


if __name__ == "__main__":
    unittest.main()
