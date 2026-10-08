from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pipeline_profile_contract import load_profile


class PipelineProfileContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_path = ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json"
        self.profile = json.loads(self.profile_path.read_text(encoding="utf-8"))

    def _assert_rejected(self, profile: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_profile(path)

    def test_all_tracked_profiles_validate(self) -> None:
        paths = sorted((ROOT / "config/pipeline-profiles").glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                loaded = load_profile(path)
                self.assertEqual(loaded["schemaVersion"], 1)

    def test_unknown_top_level_key_is_rejected(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile["typoField"] = True
        self._assert_rejected(profile)

    def test_wrong_stage_field_type_is_rejected(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile["stages"][0]["requiredInExecute"] = "yes"
        self._assert_rejected(profile)

    def test_negative_evidence_count_is_rejected(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile["stages"][0]["minimumEvidenceCount"] = -1
        self._assert_rejected(profile)


if __name__ == "__main__":
    unittest.main()
