from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import audit_render_evidence_metadata as metadata_audit


class RenderEvidenceMetadataTests(unittest.TestCase):
    def _artifact(self, root: Path, product: str = "example", name: str = "front.png") -> Path:
        artifact = root / f"Assets/GenWorks/{product}/Previews/{name}"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"png-placeholder")
        return artifact

    def _metadata(self, artifact: Path, root: Path) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "kind": "image2outfit-render-evidence-metadata",
            "artifactPath": artifact.relative_to(root).as_posix(),
            "generatorRevision": "render-loop-v1",
            "sourceCommit": "a" * 40,
            "camera": {
                "name": "Camera",
                "type": "ORTHO",
                "location": [0.0, -2.55, 0.7],
                "rotationEulerRadians": [1.2, 0.0, 0.0],
                "lensMm": 72.0,
                "orthoScale": 1.3,
            },
            "render": {
                "engine": "CYCLES",
                "resolutionX": 1024,
                "resolutionY": 1024,
                "resolutionPercentage": 100,
            },
        }

    def _write_sidecar(self, artifact: Path, root: Path) -> None:
        artifact.with_name(artifact.name + ".render.json").write_text(
            json.dumps(self._metadata(artifact, root)), encoding="utf-8"
        )

    def test_missing_sidecar_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = self._artifact(root)
            self.assertEqual(
                metadata_audit.validate_sidecar(artifact, root),
                ["missing render metadata: Assets/GenWorks/example/Previews/front.png"],
            )

    def test_valid_sidecar_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = self._artifact(root)
            self._write_sidecar(artifact, root)
            self.assertEqual(metadata_audit.validate_sidecar(artifact, root), [])

    def test_camera_pose_and_generator_revision_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = self._artifact(root)
            metadata = self._metadata(artifact, root)
            metadata["generatorRevision"] = ""
            metadata["camera"] = {}
            sidecar = artifact.with_name(artifact.name + ".render.json")
            sidecar.write_text(json.dumps(metadata), encoding="utf-8")
            errors = metadata_audit.validate_sidecar(artifact, root)
            self.assertTrue(
                any("generatorRevision is required" in item for item in errors)
            )
            self.assertTrue(any("camera.location" in item for item in errors))
            self.assertTrue(
                any("camera.rotationEulerRadians" in item for item in errors)
            )

    def test_legacy_product_without_sidecars_is_not_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._artifact(root, product="legacy")
            self.assertEqual(metadata_audit.audit(root), [])

    def test_migrated_product_requires_sidecars_for_every_png(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            front = self._artifact(root, product="migrated", name="front.png")
            self._write_sidecar(front, root)
            self._artifact(root, product="migrated", name="back.png")
            self.assertEqual(
                metadata_audit.audit(root),
                ["missing render metadata: Assets/GenWorks/migrated/Previews/back.png"],
            )


if __name__ == "__main__":
    unittest.main()
