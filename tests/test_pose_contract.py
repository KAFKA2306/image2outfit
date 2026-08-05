from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PoseContractTest(unittest.TestCase):
    def test_release_policy_is_the_only_product_pose_contract(self) -> None:
        policy = json.loads(
            (ROOT / "config/release-policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            policy["requiredPoses"],
            ["neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"],
        )
        conflicts = []
        for path in (ROOT / "config/products").glob("*/construction.json"):
            construction = json.loads(path.read_text(encoding="utf-8"))
            if "requiredPoses" in construction:
                conflicts.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], conflicts)


if __name__ == "__main__":
    unittest.main()
