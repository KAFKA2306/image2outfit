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

    def test_latest_is_published_only_after_bundle_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_audit_bundle(
                self._state("good"),
                audit_root=root,
                canonical_stages=["pattern"],
            )
            latest = root / "demo" / "latest.json"
            before = latest.read_bytes()

            with patch(
                "image2outfit.audit.verify_audit_bundle",
                side_effect=ValueError("bad bundle"),
            ):
                with self.assertRaisesRegex(ValueError, "bad bundle"):
                    write_audit_bundle(
                        self._state("bad"),
                        audit_root=root,
                        canonical_stages=["pattern"],
                    )

            self.assertEqual(latest.read_bytes(), before)
            self.assertTrue((root / "demo" / "bad" / "manifest.json").is_file())

    def test_verified_latest_pointer_rejects_manifest_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_audit_bundle(
                self._state("run-1"),
                audit_root=root,
                canonical_stages=["pattern"],
            )
            self.assertEqual(
                verify_latest_audit_pointer(root, "demo")["runId"], "run-1"
            )

            manifest = root / "demo" / "run-1" / "manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["finalStatus"] = "EXECUTED"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifestSha256 mismatch"):
                verify_latest_audit_pointer(root, "demo")

    def test_verified_latest_pointer_rejects_cross_product_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_audit_bundle(
                self._state("a-run", "a"),
                audit_root=root,
                canonical_stages=["pattern"],
            )
            write_audit_bundle(
                self._state("b-run", "b"),
                audit_root=root,
                canonical_stages=["pattern"],
            )
            latest = root / "a" / "latest.json"
            pointer = json.loads(latest.read_text(encoding="utf-8"))
            pointer["manifestPath"] = "b/b-run/manifest.json"
            latest.write_text(json.dumps(pointer), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "product namespace"):
                verify_latest_audit_pointer(root, "a")


if __name__ == "__main__":
    unittest.main()
