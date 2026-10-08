from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.audit import verify_audit_bundle, write_audit_bundle
from image2outfit.audit_schema import load_audit_schemas, load_schema, resolve_schema_path
from image2outfit.pipeline import PIPELINE_STAGES, new_pipeline_state, run_pipeline
from image2outfit.tooling import ToolDescriptor, ToolRegistry

PROFILE = ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json"
CANONICAL_STAGES = [stage.value for stage in PIPELINE_STAGES]


class AuditSchemaRuntimeTests(unittest.TestCase):
    @staticmethod
    def _schemas():
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        _, record_schema, _, manifest_schema = load_audit_schemas(
            ROOT, profile["auditContract"]
        )
        return record_schema, manifest_schema

    @staticmethod
    def _result():
        registry = ToolRegistry()
        for stage in PIPELINE_STAGES:
            registry.register(
                stage,
                lambda state, stage_name=stage.value: {
                    "mode": "planned",
                    "stage": stage_name,
                    "productId": state["product_id"],
                },
                ToolDescriptor(
                    tool_name=f"test-{stage.value}",
                    purpose=f"test {stage.value}",
                    output_contract=f"pipeline-output/{stage.value}.json",
                ),
            )
        return run_pipeline(
            new_pipeline_state(
                product_id="audit-schema-runtime",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/audit-schema-runtime",
                run_id="audit-schema-runtime-001",
            ),
            registry,
        )

    def test_profile_declared_schemas_resolve_inside_repository(self) -> None:
        record_schema, manifest_schema = self._schemas()
        self.assertEqual(record_schema["properties"]["status"]["enum"], ["PLANNED", "PASS", "FAILED"])
        self.assertEqual(manifest_schema["properties"]["finalStatus"]["enum"], ["PLANNED", "EXECUTED", "FAILED"])
        with self.assertRaisesRegex(ValueError, "escapes repository"):
            resolve_schema_path(ROOT, "../outside.json", label="audit schema")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_schema_path(ROOT, "config/pipeline/missing.schema.json", label="audit schema")

    def test_unsupported_schema_version_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema.json"
            path.write_text(json.dumps({"$schema": "draft-07", "type": "object"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported JSON Schema version"):
                load_schema(path, label="audit schema")

    def test_invalid_stage_record_is_rejected_before_audit_write(self) -> None:
        record_schema, manifest_schema = self._schemas()
        result = self._result()
        result["stage_records"][0]["unexpectedField"] = True
        with TemporaryDirectory() as temporary:
            audit_root = Path(temporary) / "audit"
            with self.assertRaisesRegex(ValueError, "unexpectedField is not allowed"):
                write_audit_bundle(
                    result,
                    audit_root=audit_root,
                    canonical_stages=CANONICAL_STAGES,
                    record_schema=record_schema,
                    manifest_schema=manifest_schema,
                )
            self.assertFalse(audit_root.exists())

    def test_verifier_rejects_schema_invalid_manifest(self) -> None:
        record_schema, manifest_schema = self._schemas()
        with TemporaryDirectory() as temporary:
            bundle = write_audit_bundle(
                self._result(),
                audit_root=Path(temporary) / "audit",
                canonical_stages=CANONICAL_STAGES,
                record_schema=record_schema,
                manifest_schema=manifest_schema,
            )
            run_root = Path(bundle["root"])
            manifest_path = run_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["finalStatus"] = "MAYBE"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finalStatus must be one of"):
                verify_audit_bundle(
                    run_root,
                    record_schema=record_schema,
                    manifest_schema=manifest_schema,
                )


if __name__ == "__main__":
    unittest.main()
