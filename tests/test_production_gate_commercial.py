from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import production_gate  # noqa: E402
import runtime_paths  # noqa: E402


class ProductionGateCommercialTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[dict, dict]:
        (root / "config" / "products" / "demo").mkdir(parents=True)
        (root / "config" / "release-policy.json").write_text(
            json.dumps({"schemaVersion": 1, "commercialMethodPolicy": {}}) + "\n",
            encoding="utf-8",
        )
        (root / "config" / "products" / "demo" / "construction.json").write_text(
            json.dumps({"schemaVersion": 1, "profile": "loose-layered"}) + "\n",
            encoding="utf-8",
        )
        job = {
            "id": "demo",
            "adapterId": "demo-v1",
            "buildScript": "tools/demo_product.py",
        }
        selection = {
            "schemaVersion": 1,
            "passed": True,
            "productId": "demo",
            "commercialProfile": "commercial-v1",
            "constructionProfile": "loose-layered",
            "constructionPath": "config/products/demo/construction.json",
            "requiredCapabilities": ["layering-collision", "dynamic-evaluation"],
            "requiredCommercialEvidence": [
                "penetration-report",
                "runtime-performance",
                "motion-review",
            ],
            "errors": [],
        }
        return job, selection

    def test_candidate_manifest_binds_method_and_policy_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job, selection = self._fixture(root)
            manifest = runtime_paths.for_job(root, job).candidate / "candidate-manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"schemaVersion": 2, "jobId": "demo"}) + "\n",
                encoding="utf-8",
            )

            binding = production_gate._bind_method_to_candidate(job, selection, root)
            saved = json.loads(manifest.read_text(encoding="utf-8"))

            self.assertEqual(saved["constructionMethod"], binding)
            self.assertEqual(binding["constructionProfile"], "loose-layered")
            self.assertEqual(len(binding["constructionSha256"]), 64)
            self.assertEqual(len(binding["releasePolicySha256"]), 64)

    def test_policy_or_construction_change_invalidates_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job, selection = self._fixture(root)
            manifest_path = (
                runtime_paths.for_job(root, job).candidate / "candidate-manifest.json"
            )
            manifest_path.parent.mkdir(parents=True)
            binding = production_gate._binding_snapshot(job, selection, root)
            manifest = {"schemaVersion": 2, "constructionMethod": binding}

            construction = root / selection["constructionPath"]
            construction.write_text(
                json.dumps({"schemaVersion": 1, "profile": "panel-sewn"}) + "\n",
                encoding="utf-8",
            )
            errors = production_gate._bound_method_errors(
                job, selection, manifest, root
            )

            self.assertTrue(
                any("constructionSha256" in value for value in errors), errors
            )

    def test_failed_commercial_evidence_never_calls_release_core(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job, selection = self._fixture(root)
            paths = runtime_paths.for_job(root, job)
            manifest_path = paths.candidate / "candidate-manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "constructionMethod": production_gate._binding_snapshot(
                            job, selection, root
                        ),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            commercial = {
                "schemaVersion": 1,
                "passed": False,
                "candidateManifestSha256": "0" * 64,
                "errors": ["runtime-performance: evidence unreadable"],
            }

            with (
                mock.patch.object(
                    production_gate.method_selection,
                    "select",
                    return_value=selection,
                ),
                mock.patch.object(
                    production_gate.method_selection,
                    "validate_commercial_evidence",
                    return_value=commercial,
                ),
                mock.patch.object(production_gate.core, "_run_release") as runner,
            ):
                result = production_gate._run_release(
                    Path("config/products/demo/job.json"), job, {}, root
                )

            self.assertEqual(result, 2)
            runner.assert_not_called()
            report = json.loads(
                (paths.reports / "commercial-method-quality.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
