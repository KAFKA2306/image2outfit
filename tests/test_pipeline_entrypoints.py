from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = (
    ROOT / "tools/run_garment_pipeline.py",
    ROOT / "tools/audit_src_architecture.py",
    ROOT / "tools/pipeline_stage_adapters.py",
    ROOT / "tools/run_blender_stage.py",
)


class PipelineEntrypointTests(unittest.TestCase):
    def test_entrypoints_are_tracked_as_plain_python(self) -> None:
        for path in ENTRYPOINTS:
            self.assertTrue(path.is_file(), str(path))
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
