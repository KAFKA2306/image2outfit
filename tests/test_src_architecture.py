from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.architecture import audit_src_boundaries


class SrcArchitectureTests(unittest.TestCase):
    def test_src_does_not_import_blender_or_tools(self) -> None:
        self.assertEqual(audit_src_boundaries(ROOT), ())
