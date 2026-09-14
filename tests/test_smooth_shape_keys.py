from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT = TOOLS / "smooth_shape_keys.py"
sys.path.insert(0, str(TOOLS))

import contract_io  # noqa: E402

SPEC = importlib.util.spec_from_file_location("smooth_shape_keys", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def state(
    target: tuple[float, float, float] = (1.0, 0.0, 0.0),
    other: tuple[float, float, float] = (0.0, 1.0, 0.0),
    *,
    extra: bool = False,
) -> dict[str, object]:
    keys = {
        "Basis": ((0.0, 0.0, 0.0),),
        "Corrective": (target,),
        "Other": (other,),
    }
    if extra:
        keys["Corrective_backup"] = (target,)
    return {
        "Garment": {
            "topology": (1, 0, 0),
            "materials": ("Mat",),
            "uv": (),
            "weights": ((),),
            "keys": keys,
        }
    }


class SmoothShapeKeysTests(unittest.TestCase):
    def test_bpy_is_not_imported_at_module_scope(self) -> None:
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        self.assertNotIn("bpy", imports)

    def test_required_contract_needs_exact_api(self) -> None:
        errors = MODULE._contract_errors(
            {
                "provider": MODULE.PROVIDER,
                "applicability": "REQUIRED",
                "reason": "corrective cleanup",
                "targets": ["Garment:Corrective"],
                "module": "",
                "operator": "guessed operator",
                "invocation": "ACTIVE_KEY",
                "properties": {},
            }
        )
        self.assertIn(
            "module is required when applicability is REQUIRED", errors
        )
        self.assertIn("operator must be an exact Blender operator id", errors)

    def test_schema_requires_exact_api_when_required(self) -> None:
        schema = ROOT / "config" / "products" / "construction.schema.v1.json"
        contract = {
            "schemaVersion": 1,
            "productId": "test-product",
            "profile": "fitted",
            "shapeKeyPostprocess": {
                "provider": MODULE.PROVIDER,
                "applicability": "REQUIRED",
                "reason": "corrective cleanup",
            },
        }
        errors = contract_io.validate_schema_file(contract, schema, "construction")
        for field in ("module", "operator", "invocation", "targets", "properties"):
            with self.subTest(field=field):
                self.assertTrue(
                    any(f"shapeKeyPostprocess.{field} is required" in item for item in errors),
                    errors,
                )

    def test_schema_allows_explicit_not_required(self) -> None:
        schema = ROOT / "config" / "products" / "construction.schema.v1.json"
        contract = {
            "schemaVersion": 1,
            "productId": "test-product",
            "profile": "fitted",
            "shapeKeyPostprocess": {
                "provider": MODULE.PROVIDER,
                "applicability": "NOT_REQUIRED",
                "reason": "product contains no corrective shape keys",
            },
        }
        self.assertEqual(
            [],
            contract_io.validate_schema_file(contract, schema, "construction"),
        )

    def test_non_target_change_blocks(self) -> None:
        before = state()
        after = state(other=(0.0, 2.0, 0.0))
        errors, _ = MODULE._validate(
            before,
            after,
            {"Garment:Corrective"},
            allow_extra_keys=False,
        )
        self.assertTrue(
            any("non-target shape key changed" in item for item in errors)
        )

    def test_basis_change_blocks(self) -> None:
        before = state()
        after = state()
        after["Garment"]["keys"]["Basis"] = ((0.1, 0.0, 0.0),)
        errors, _ = MODULE._validate(
            before,
            after,
            {"Garment:Corrective"},
            allow_extra_keys=False,
        )
        self.assertTrue(any("Basis changed" in item for item in errors))

    def test_backup_allowed_before_cleanup_but_not_after(self) -> None:
        before = state()
        after = state(target=(1.1, 0.0, 0.0), extra=True)
        errors, metrics = MODULE._validate(
            before,
            after,
            {"Garment:Corrective"},
            allow_extra_keys=True,
        )
        self.assertEqual([], errors)
        self.assertEqual(1, metrics["changedTargetCount"])
        errors, _ = MODULE._validate(
            before,
            after,
            {"Garment:Corrective"},
            allow_extra_keys=False,
        )
        self.assertTrue(
            any("backup/extra shape keys remain" in item for item in errors)
        )


if __name__ == "__main__":
    unittest.main()
