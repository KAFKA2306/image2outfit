from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import release_gate as gate  # noqa: E402


class ConfigContractTest(unittest.TestCase):
    def test_obsolete_job_templates_are_removed(self) -> None:
        templates = sorted((ROOT / "config").glob("*.template.json"))
        self.assertEqual(templates, [])
        self.assertFalse((ROOT / "config" / "haolan-job.template.json").exists())

    def test_release_policy_has_no_unused_primary_adapter(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "release-policy.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("primaryAdapterId", policy)
        self.assertIn("haolan-v1.6", policy["blockedReleaseAdapterIds"])

    def test_job_schema_is_the_required_field_source(self) -> None:
        schema = json.loads(
            (ROOT / "config" / "job.schema.v2.json").read_text(encoding="utf-8")
        )
        self.assertEqual(tuple(schema["required"]), gate.required_job_fields())
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 2)

    def test_unity_pipeline_uses_the_genworks_canonical_path(self) -> None:
        expected = (
            ROOT
            / "Assets"
            / "GenWorks"
            / "Shared"
            / "Editor"
            / "Image2OutfitPipeline.cs"
        )
        self.assertEqual(gate.UNITY_PIPELINE_PATH, expected)
        self.assertTrue(expected.is_file())
        self.assertFalse((ROOT / "Assets" / "Editor").exists())


if __name__ == "__main__":
    unittest.main()
