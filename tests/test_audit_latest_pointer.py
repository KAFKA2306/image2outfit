import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from image2outfit.audit import make_stage_record, verify_latest_audit_pointer, write_audit_bundle


class AuditLatestPointerTests(unittest.TestCase):
    def _state(self, run_id: str) -> dict:
        output = {"resultPath": "result.json", "result": {"evidence": []}}
        record = make_stage_record(
            run_id=run_id,
            product_id="demo",
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
            "product_id": "demo",
            "profile_id": "fixture",
            "execution_mode": "execute",
            "status": "FAILED",
            "stage_records": [record],
        }

    def test_latest_pointer_resolves_verified_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_audit_bundle(
                self._state("run-1"),
                audit_root=root,
                canonical_stages=["pattern"],
            )

            pointer = verify_latest_audit_pointer(root, "demo")

            self.assertEqual(pointer["runId"], "run-1")
            self.assertEqual(pointer["productId"], "demo")

    def test_failed_new_run_does_not_move_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_audit_bundle(
                self._state("good"),
                audit_root=root,
                canonical_stages=["pattern"],
            )
            latest = root / "demo" / "latest.json"
            before = json.loads(latest.read_text(encoding="utf-8"))

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

            after = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(after, before)
            self.assertEqual(after["runId"], "good")


if __name__ == "__main__":
    unittest.main()
