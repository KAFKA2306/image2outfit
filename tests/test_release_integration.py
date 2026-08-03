from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import production_gate_core  # noqa: E402
import release_gate  # noqa: E402
import release_orchestrator  # noqa: E402


class ReleaseIntegrationTest(unittest.TestCase):
    def test_imported_release_route_has_one_validator(self) -> None:
        self.assertIs(
            production_gate_core._run_release,
            release_orchestrator._run_release,
        )
        self.assertFalse(hasattr(release_gate, "evidence_gate"))
        self.assertFalse(hasattr(release_gate, "run_release"))

    def test_direct_legacy_release_is_disabled(self) -> None:
        source = (TOOLS / "release_gate.py").read_text(encoding="utf-8")
        self.assertIn("direct release_gate release is disabled", source)
        self.assertIn("tools/production_gate.py", source)


if __name__ == "__main__":
    unittest.main()
