from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import production_contract as contract  # noqa: E402


class UnityReadyOutfitContractTest(unittest.TestCase):
    def test_wide_cargo_declares_real_multi_material_product_contract(self) -> None:
        job_path = ROOT / "config/products/siroino-wide-cargo/job.json"
        schema_path = ROOT / "config/job.schema.v2.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(
            contract.validate_schema_file(job, schema_path, "siroino-wide-cargo"),
            [],
        )

        unity_ready = job["unityReady"]
        roles = {
            item["material"]: item["role"] for item in unity_ready["materialRoles"]
        }
        self.assertGreaterEqual(unity_ready["minimumDistinctMaterials"], 2)
        self.assertEqual(
            roles,
            {
                "MAT_Black_Cargo_Fabric": "fabric",
                "MAT_Black_Cargo_Straps": "trim",
                "MAT_Brushed_Gunmetal": "metal",
            },
        )

        delivery = set(job["deliveryAssets"])
        for material in roles:
            asset = f"Assets/GenWorks/siroino-wide-cargo/Materials/{material}.mat"
            self.assertIn(asset, delivery)
            self.assertIn(asset + ".meta", delivery)


if __name__ == "__main__":
    unittest.main()
