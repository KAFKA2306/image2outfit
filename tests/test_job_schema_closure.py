from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class JobSchemaClosureTest(unittest.TestCase):
    def test_every_tracked_job_uses_only_declared_fields(self) -> None:
        schema = json.loads(
            (ROOT / "config/job.schema.v2.json").read_text(encoding="utf-8")
        )
        self.assertIs(schema["additionalProperties"], False)
        allowed = set(schema["properties"])
        violations = {}
        for path in (ROOT / "config/products").glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8-sig"))
            unknown = sorted(set(job) - allowed)
            if unknown:
                violations[path.parent.name] = unknown
        self.assertEqual({}, violations)


if __name__ == "__main__":
    unittest.main()
