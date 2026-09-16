import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from image2outfit.audit import (
    make_stage_record,
    verify_latest_audit_pointer,
    write_audit_bundle,
)


class AuditLatestPointerTests(unittest.TestCase):
    def _state(self, run_id: str, product_id: str = "demo") -> dict:
        output = {"resultPath": "result.json", "result": {"evidence": []}}
        record = make_stage_record(
            run_id=run_id,
            product_id=product_id,
            sequence=1,
            stage="pattern",
            requested_mode="execute",
            outcome_mode="execute",
            status="FAIL",
            tool_name="fixture",
            purpose="test",
            output_contract="fixture-v1",
            input_snapshot={},
            output=output,
            started_at="2026-09-13T00:00:00Z",
            finished_at="2026-09-13T00:00:01Z",
        )
        return {
            "run_id": run_id,
            "product_id": product_id,
            "profile_id": "fixture",
            "execution_mode": "execute",
            "status": "FAILED",
            "stage_records": [record],
        }

    def _write(
        self, root: Path, run_id: str = "run-1", product_id: str = "demo"
    ) -> Path:
        write_audit_bundle(
            self._state(run_id, product_id),
            audit_root=root,
            canonical_stages=["pattern"],
        )
        return root / product_id / "latest.json"

    def _mutate_pointer(self, latest: Path, **changes: object) -> None:
        pointer = json.loads(latest.read_text(encoding="utf-8"))
        pointer.update(changes)
        latest.write_text(json.dumps(pointer), encoding="utf-8")

    def test_valid_latest_pointer_resolves_verified_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root)
            pointer = verify_latest_audit_pointer(root, "demo")
            self.assertEqual(pointer["runId"], "run-1")
            self.assertEqual(pointer["productId"], "demo")

    def test_existing_latest_is_preserved_when_new_bundle_verification_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = self._write(root, "good")
            before = latest.read_bytes()

            with patch(
                "image2outfit.audit.verify_audit_bundle",
                side_effect=ValueError("bad bundle"),
            ):
                with self.assertRaisesRegex(ValueError, "bad bundle"):
                    self._write(root, "bad")

            self.assertEqual(latest.read_bytes(), before)
            self.assertTrue((root / "demo" / "bad" / "manifest.json").is_file())

    def test_first_failed_run_does_not_create_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch(
                "image2outfit.audit.verify_audit_bundle",
                side_effect=ValueError("bad bundle"),
            ):
                with self.assertRaisesRegex(ValueError, "bad bundle"):
                    self._write(root, "bad")
            self.assertFalse((root / "demo" / "latest.json").exists())

    def test_manifest_hash_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = self._write(root)
            self._mutate_pointer(latest, manifestSha256="0" * 64)
            with self.assertRaisesRegex(ValueError, "manifestSha256 mismatch"):
                verify_latest_audit_pointer(root, "demo")

    def test_manifest_file_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root)
            manifest = root / "demo" / "run-1" / "manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["finalStatus"] = "EXECUTED"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifestSha256 mismatch"):
                verify_latest_audit_pointer(root, "demo")

    def test_pointer_identity_mismatches_are_rejected(self) -> None:
        cases = (
            ("runId", "other", "runId mismatch"),
            ("productId", "other", "productId mismatch"),
            ("finalStatus", "EXECUTED", "finalStatus mismatch"),
        )
        for field, value, message in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                latest = self._write(root)
                self._mutate_pointer(latest, **{field: value})
                with self.assertRaisesRegex(ValueError, message):
                    verify_latest_audit_pointer(root, "demo")

    def test_cross_product_and_path_escape_targets_are_rejected(self) -> None:
        cases = (
            "b/b-run/manifest.json",
            "../outside/manifest.json",
            "/tmp/manifest.json",
        )
        for target in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._write(root, "a-run", "a")
                self._write(root, "b-run", "b")
                latest = root / "a" / "latest.json"
                self._mutate_pointer(latest, manifestPath=target)
                with self.assertRaises(ValueError):
                    verify_latest_audit_pointer(root, "a")

    def test_target_stage_tamper_is_rejected_through_bundle_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = self._write(root)
            pointer = json.loads(latest.read_text(encoding="utf-8"))
            stage = root / "demo" / "run-1" / "stages" / "001-pattern.json"
            stage.write_text(
                stage.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "stage file hash mismatch"):
                verify_latest_audit_pointer(root, "demo")
            self.assertEqual(
                json.loads(latest.read_text(encoding="utf-8"))["runId"], pointer["runId"]
            )

    def test_latest_replacement_is_parseable_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = self._write(root, "run-1")
            self._write(root, "run-2")
            self.assertEqual(
                json.loads(latest.read_text(encoding="utf-8"))["runId"], "run-2"
            )
            self.assertEqual(list(latest.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
