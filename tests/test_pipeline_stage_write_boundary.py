from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.execution import StageResultRequirement
from image2outfit.pipeline import PipelineStage
from pipeline_stage_adapters import CommandStageAdapter
from repository_write_boundary import UndeclaredOutputWriteError


class PipelineStageWriteBoundaryTests(unittest.TestCase):
    def _repo(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
        (root / ".gitignore").write_text(".image2outfit/\n", encoding="utf-8")
        (root / "protected.txt").write_text("last-good\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore", "protected.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        return temporary

    def _script(self, root: Path, mutation: str = "") -> Path:
        script = root / "stage.py"
        script.write_text(
            textwrap.dedent(
                f"""
                import hashlib
                import json
                from pathlib import Path

                root = Path.cwd()
                evidence = root / '.image2outfit/products/test-garment/evidence.txt'
                evidence.parent.mkdir(parents=True, exist_ok=True)
                evidence.write_text('evidence\\n', encoding='utf-8')
                {mutation}
                result = root / '.image2outfit/results/ingest.json'
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text(json.dumps({{
                    'schemaVersion': 1,
                    'stage': 'ingest-reference',
                    'productId': 'test-garment',
                    'status': 'PASS',
                    'evidence': [{{
                        'path': '.image2outfit/products/test-garment/evidence.txt',
                        'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    }}],
                }}), encoding='utf-8')
                """
            ),
            encoding="utf-8",
        )
        return script

    def _adapter(self, script: Path) -> CommandStageAdapter:
        return CommandStageAdapter(
            stage=PipelineStage.INGEST_REFERENCE,
            tool_name="fixture",
            purpose="fixture",
            command=(sys.executable, str(script)),
            result_path=".image2outfit/results/ingest.json",
            execute=True,
            required_in_execute=True,
            result_requirement=StageResultRequirement(minimum_evidence_count=1),
        )

    def test_declared_evidence_write_passes(self) -> None:
        with self._repo() as name:
            root = Path(name)
            script = self._script(root)
            with patch("pipeline_stage_adapters.ROOT", root):
                result = self._adapter(script)({"product_id": "test-garment"})
            self.assertEqual(result["mode"], "executed")
            self.assertEqual(
                result["changedPaths"],
                [".image2outfit/products/test-garment/evidence.txt"],
            )

    def test_tracked_undeclared_write_fails_and_rolls_back(self) -> None:
        with self._repo() as name:
            root = Path(name)
            script = self._script(
                root,
                "(root / 'protected.txt').write_text('corrupt\\n', encoding='utf-8')",
            )
            with patch("pipeline_stage_adapters.ROOT", root):
                with self.assertRaises(UndeclaredOutputWriteError) as context:
                    self._adapter(script)({"product_id": "test-garment"})
            self.assertEqual(context.exception.failure_code, "UNDECLARED_OUTPUT_WRITE")
            self.assertEqual(context.exception.affected_paths, ("protected.txt",))
            self.assertEqual((root / "protected.txt").read_text(encoding="utf-8"), "last-good\n")
            self.assertFalse(root.joinpath(".image2outfit/products/test-garment/evidence.txt").exists())

    def test_other_product_write_fails_and_restores_bytes(self) -> None:
        with self._repo() as name:
            root = Path(name)
            other = root / ".image2outfit/products/other-product/ProductManifest.json"
            other.parent.mkdir(parents=True, exist_ok=True)
            other.write_text('{"state":"last-good"}\n', encoding="utf-8")
            script = self._script(
                root,
                "(root / '.image2outfit/products/other-product/ProductManifest.json').write_text('{\\\"state\\\":\\\"corrupt\\\"}\\n', encoding='utf-8')",
            )
            with patch("pipeline_stage_adapters.ROOT", root):
                with self.assertRaises(UndeclaredOutputWriteError) as context:
                    self._adapter(script)({"product_id": "test-garment"})
            self.assertEqual(
                context.exception.affected_paths,
                (".image2outfit/products/other-product/ProductManifest.json",),
            )
            self.assertEqual(other.read_text(encoding="utf-8"), '{"state":"last-good"}\n')

    def test_dirty_before_is_not_a_violation_when_stage_leaves_it_unchanged(self) -> None:
        with self._repo() as name:
            root = Path(name)
            protected = root / "protected.txt"
            protected.write_text("preexisting-dirty\n", encoding="utf-8")
            script = self._script(root)
            with patch("pipeline_stage_adapters.ROOT", root):
                result = self._adapter(script)({"product_id": "test-garment"})
            self.assertEqual(result["mode"], "executed")
            self.assertEqual(protected.read_text(encoding="utf-8"), "preexisting-dirty\n")

    def test_evidence_symlink_escape_is_rejected_and_workspace_is_rolled_back(self) -> None:
        with self._repo() as name:
            root = Path(name)
            outside = root.parent / f"{root.name}-outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            script = root / "stage.py"
            script.write_text(
                textwrap.dedent(
                    f"""
                    import hashlib
                    import json
                    from pathlib import Path
                    root = Path.cwd()
                    evidence = root / '.image2outfit/products/test-garment/evidence.txt'
                    evidence.parent.mkdir(parents=True, exist_ok=True)
                    evidence.symlink_to({str(outside)!r})
                    result = root / '.image2outfit/results/ingest.json'
                    result.parent.mkdir(parents=True, exist_ok=True)
                    result.write_text(json.dumps({{
                        'schemaVersion': 1,
                        'stage': 'ingest-reference',
                        'productId': 'test-garment',
                        'status': 'PASS',
                        'evidence': [{{
                            'path': '.image2outfit/products/test-garment/evidence.txt',
                            'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                        }}],
                    }}), encoding='utf-8')
                    """
                ),
                encoding="utf-8",
            )
            try:
                with patch("pipeline_stage_adapters.ROOT", root):
                    with self.assertRaisesRegex(ValueError, "escapes repository"):
                        self._adapter(script)({"product_id": "test-garment"})
                self.assertFalse(root.joinpath(".image2outfit/products/test-garment/evidence.txt").exists())
                self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")
            finally:
                outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
