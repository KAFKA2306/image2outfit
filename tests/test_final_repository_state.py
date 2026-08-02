from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_repository_hygiene  # noqa: E402


class FinalRepositoryStateTest(unittest.TestCase):
    def test_full_repository_hygiene_passes(self) -> None:
        result = audit_repository_hygiene.audit(ROOT)
        self.assertTrue(result["passed"], result["findings"])
        self.assertEqual(result["findingCount"], 0)

    def test_every_tracked_product_has_namespaced_contracts(self) -> None:
        products = ROOT / "config" / "products"
        product_dirs = sorted(path for path in products.iterdir() if path.is_dir())
        self.assertGreaterEqual(len(product_dirs), 2)
        for product_dir in product_dirs:
            job_path = product_dir / "job.json"
            license_path = product_dir / "license.json"
            self.assertTrue(job_path.is_file(), job_path)
            self.assertTrue(license_path.is_file(), license_path)
            job = json.loads(job_path.read_text(encoding="utf-8-sig"))
            product_id = product_dir.name
            self.assertEqual(job["id"], product_id)
            self.assertEqual(
                job["productRoot"],
                f"Assets/GenWorks/Products/{product_id}",
            )
            self.assertEqual(
                job["licenseEvidence"],
                f"config/products/{product_id}/license.json",
            )

    def test_runtime_state_is_not_tracked(self) -> None:
        self.assertFalse((ROOT / ".github" / "run").exists())
        self.assertFalse((ROOT / ".github" / "status").exists())


if __name__ == "__main__":
    unittest.main()
