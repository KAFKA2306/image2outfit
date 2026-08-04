from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.architecture import FORBIDDEN_SRC_IMPORT_ROOTS


class ArchitecturePolicyTests(unittest.TestCase):
    def test_machine_policy_matches_core_boundary(self) -> None:
        policy = json.loads(
            (ROOT / "config/architecture-policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(policy["dependencyDirection"], "tools-to-src-only")
        self.assertEqual(
            set(policy["forbiddenCoreImports"]), set(FORBIDDEN_SRC_IMPORT_ROOTS)
        )
