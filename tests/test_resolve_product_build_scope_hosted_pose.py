from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import resolve_product_build_scope as scope


class HostedPoseBuildScopeTests(unittest.TestCase):
    def test_hosted_pose_script_change_selects_owning_product(self) -> None:
        selected, reason = scope.select_job(
            ["tools/siroino_lace_halter_large_refine_v2.py"],
            ROOT,
            include_pipeline_request=True,
        )
        self.assertEqual(reason, "selected")
        self.assertEqual(
            selected,
            "config/products/siroino-lace-halter-large/job.json",
        )

    def test_build_script_change_still_selects_owning_product(self) -> None:
        selected, reason = scope.select_job(
            ["tools/siroino_tuxedo_halter_dress_large_build.py"],
            ROOT,
            include_pipeline_request=True,
        )
        self.assertEqual(reason, "selected")
        self.assertEqual(
            selected,
            "config/products/siroino-tuxedo-halter-dress-large/job.json",
        )


if __name__ == "__main__":
    unittest.main()
