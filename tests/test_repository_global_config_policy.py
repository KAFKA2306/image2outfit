from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import audit_repository_hygiene  # noqa: E402


class RepositoryGlobalConfigPolicyTests(unittest.TestCase):
    def test_pr_merge_policy_is_an_explicit_repository_config(self) -> None:
        self.assertIn(
            "pr-merge-policy.json",
            audit_repository_hygiene.GLOBAL_CONFIG_FILES,
        )

    def test_unknown_global_config_remains_rejected_by_default(self) -> None:
        self.assertNotIn(
            "unexpected-product-config.json",
            audit_repository_hygiene.GLOBAL_CONFIG_FILES,
        )


if __name__ == "__main__":
    unittest.main()
