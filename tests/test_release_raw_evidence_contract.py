from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseRawEvidenceContractTest(unittest.TestCase):
    def test_packager_copies_raw_evidence_before_manifesting_release(self) -> None:
        source = (ROOT / "tools/release_packager.py").read_text(encoding="utf-8")
        human = source.index('package / "Evidence" / "Human"')
        commercial = source.index('package / "Evidence" / "Commercial"')
        release_manifest = source.index('release / "release-manifest.json"')
        self.assertLess(human, release_manifest)
        self.assertLess(commercial, release_manifest)


if __name__ == "__main__":
    unittest.main()
