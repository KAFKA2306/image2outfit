"""Candidate builds must read canonical contracts even from runtime job copies."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
SCRIPT = TOOLS / "generic_structural_garment_product.py"
SPEC = importlib.util.spec_from_file_location(
    "generic_structural_garment_product", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
FAKE_BPY = types.ModuleType("bpy")
FAKE_BPY.ops = types.SimpleNamespace(
    wm=types.SimpleNamespace(read_factory_settings=lambda **_kwargs: None)
)
with patch.dict(sys.modules, {"bpy": FAKE_BPY}):
    BUILDER = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(BUILDER)


class _ReachedBlenderStage(Exception):
    """Sentinel: contract loading passed before licensed avatar import."""


class PanelSewnContractPathTests(unittest.TestCase):
    def test_materialized_runtime_job_uses_canonical_construction_and_pattern(
        self,
    ) -> None:
        product = "siroino-arc-latch-cocoon-bomber-set"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "config" / "products" / product
            canonical.mkdir(parents=True)
            (canonical / "construction.json").write_text(
                json.dumps({"productId": product, "profile": "panel-sewn"}),
                encoding="utf-8",
            )
            (canonical / "pattern-draft.json").write_text(
                json.dumps({"productId": product}), encoding="utf-8"
            )
            runtime = root / ".image2outfit" / "products" / product
            runtime.mkdir(parents=True)
            job_path = runtime / "job.json"
            job_path.write_text(
                json.dumps({"schemaVersion": 2, "id": product}), encoding="utf-8"
            )
            self.assertFalse((runtime / "construction.json").exists())
            self.assertFalse((runtime / "pattern-draft.json").exists())

            argv = ["blender", "--", "--job", str(job_path)]
            with (
                patch.object(BUILDER, "ROOT", root),
                patch.object(
                    BUILDER, "import_target_armature", side_effect=_ReachedBlenderStage
                ),
                patch.object(sys, "argv", argv),
            ):
                with self.assertRaises(_ReachedBlenderStage):
                    BUILDER.main()


if __name__ == "__main__":
    unittest.main()
