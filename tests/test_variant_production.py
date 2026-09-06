from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.variant_production import (
    materialize_all_variants,
    materialize_variant,
)

PRODUCT_ID = "siroino-tuxedo-halter-dress-large"


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


class ProductionVariantTests(unittest.TestCase):
    def fixtures(self) -> tuple[dict, dict, dict, dict]:
        product = ROOT / "config" / "products" / PRODUCT_ID
        return (
            read_json(product / "job.json"),
            read_json(ROOT / "config" / "pipeline" / "requests" / f"{PRODUCT_ID}.json"),
            read_json(product / "material-recipe.json"),
            read_json(product / "production-variants.json"),
        )

    def test_color_and_size_materialize_into_isolated_candidates(self) -> None:
        job, request, material, recipe = self.fixtures()
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            runtime_root = Path(tmp)
            items = materialize_all_variants(
                runtime_root,
                base_job=job,
                base_request=request,
                base_material_recipe=material,
                production_recipe=recipe,
                workspace_id="unit-a",
            )

            by_id = {item["variantId"]: item for item in items}
            self.assertEqual(
                {"baseline", "black-black", "compact-large", "invalid-zero-bib"},
                set(by_id),
            )
            self.assertEqual(
                by_id["baseline"]["variantContract"]["geometryInputFingerprint"],
                by_id["black-black"]["variantContract"]["geometryInputFingerprint"],
            )
            self.assertNotEqual(
                by_id["baseline"]["variantContract"]["geometryInputFingerprint"],
                by_id["compact-large"]["variantContract"]["geometryInputFingerprint"],
            )
            self.assertNotEqual(
                by_id["baseline"]["variantContract"]["materialRecipeSha256"],
                by_id["black-black"]["variantContract"]["materialRecipeSha256"],
            )

            roots = {read_json(item["jobPath"])["productRoot"] for item in items}
            self.assertEqual(4, len(roots))
            for item in items:
                derived_job = read_json(item["jobPath"])
                derived_request = read_json(item["requestPath"])
                self.assertEqual(PRODUCT_ID, derived_job["id"])
                self.assertEqual(PRODUCT_ID, derived_request["productId"])
                self.assertEqual(item["candidateId"], derived_job["candidateId"])
                self.assertTrue(
                    derived_job["variantRuntimeRoot"].startswith(
                        f".image2outfit/products/{PRODUCT_ID}/variants/"
                    )
                )
                build_result_path = derived_request["stageBindings"]["build-blender"][
                    "resultPath"
                ]
                self.assertIn(item["candidateId"], build_result_path)
                self.assertNotIn("/stages/stages/", build_result_path)
                build_command = " ".join(
                    derived_request["stageBindings"]["build-blender"]["command"]
                )
                self.assertNotIn("/stages/stages/", build_command)
                self.assertIn(
                    "variantFingerprint",
                    derived_request["variables"],
                )

    def test_color_does_not_invalidate_initialize_but_size_does(self) -> None:
        job, request, material, recipe = self.fixtures()
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            runtime_root = Path(tmp)
            color = materialize_variant(
                runtime_root,
                base_job=job,
                base_request=request,
                base_material_recipe=material,
                production_recipe=recipe,
                variant_id="black-black",
                workspace_id="unit-color",
            )
            size = materialize_variant(
                runtime_root,
                base_job=job,
                base_request=request,
                base_material_recipe=material,
                production_recipe=recipe,
                variant_id="compact-large",
                workspace_id="unit-size",
            )

            self.assertNotIn(
                "initialize-3d",
                color["variantContract"]["requiredRevalidation"],
            )
            self.assertIn(
                "initialize-3d",
                size["variantContract"]["requiredRevalidation"],
            )
            self.assertIn(
                "render-evidence",
                color["variantContract"]["requiredRevalidation"],
            )
            self.assertIn(
                "render-evidence",
                size["variantContract"]["requiredRevalidation"],
            )

    def test_invalid_variant_cannot_escape_workspace(self) -> None:
        job, request, material, recipe = self.fixtures()
        bad = json.loads(json.dumps(recipe))
        bad["variants"][0]["id"] = "../escape"
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            with self.assertRaisesRegex(ValueError, "variant id"):
                materialize_all_variants(
                    Path(tmp),
                    base_job=job,
                    base_request=request,
                    base_material_recipe=material,
                    production_recipe=bad,
                    workspace_id="unit-bad",
                )


if __name__ == "__main__":
    unittest.main()
