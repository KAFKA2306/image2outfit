from __future__ import annotations

import json
import unittest

from image2outfit.hypothesis_contracts import validate_hypothesis_set
from image2outfit.tripo_adapter import (
    build_hypothesis_set,
    build_multiview_task,
    build_provenance,
    validate_multiview_request,
)


class TripoAdapterContractTests(unittest.TestCase):
    def request(self) -> dict:
        digest = "a" * 64
        return {
            "schemaVersion": 1,
            "productId": "demo",
            "blueprintPath": ".image2outfit/products/demo/blueprint.json",
            "targetAvatarAuthorityPath": ".image2outfit/products/demo/authority.json",
            "modelVersion": "P1-20260311",
            "faceLimit": 4000,
            "texture": False,
            "pbr": False,
            "modelSeed": 123,
            "views": {
                "front": {
                    "sha256": digest,
                    "file": {"type": "png", "file_token": "front-private-token"},
                },
                "left": {
                    "sha256": "b" * 64,
                    "file": {"type": "png", "url": "https://example.invalid/left.png"},
                },
                "back": {
                    "sha256": "c" * 64,
                    "file": {
                        "type": "png",
                        "object": {"bucket": "tripo-data", "key": "private-key"},
                    },
                },
            },
        }

    def test_multiview_payload_has_four_ordered_slots_and_no_hashes(self) -> None:
        request = validate_multiview_request(self.request())
        task = build_multiview_task(request)
        self.assertEqual(task["type"], "multiview_to_model")
        self.assertEqual(len(task["files"]), 4)
        self.assertEqual(task["files"][0]["file_token"], "front-private-token")
        self.assertEqual(task["files"][1]["url"], "https://example.invalid/left.png")
        self.assertEqual(task["files"][2]["object"]["key"], "private-key")
        self.assertEqual(task["files"][3], {})
        self.assertNotIn("sha256", json.dumps(task))
        self.assertNotIn("quad", task)

    def test_front_and_at_least_two_views_are_required(self) -> None:
        request = self.request()
        request["views"].pop("front")
        with self.assertRaisesRegex(ValueError, "front view"):
            validate_multiview_request(request)

        request = self.request()
        request["views"] = {"front": request["views"]["front"]}
        with self.assertRaisesRegex(ValueError, "at least two"):
            validate_multiview_request(request)

    def test_private_input_references_are_not_persisted_in_provenance(self) -> None:
        request = validate_multiview_request(self.request())
        provenance = build_provenance(
            request=request,
            blueprint_sha256="d" * 64,
            authority_sha256="e" * 64,
            task_id="task-1",
            artifact_sha256="f" * 64,
            elapsed_seconds=12.5,
            api_data={
                "status": "success",
                "progress": 100,
                "consumed_credit": 3.0,
                "output": {"topology": "quad", "riggable": True},
            },
        )
        serialized = json.dumps(provenance)
        self.assertNotIn("front-private-token", serialized)
        self.assertNotIn("example.invalid", serialized)
        self.assertNotIn("private-key", serialized)
        self.assertFalse(provenance["quadRequestedDuringGeneration"])
        self.assertEqual(provenance["inputSha256"]["front"], "a" * 64)

    def test_external_hypothesis_remains_noncanonical_and_fail_closed(self) -> None:
        payload = build_hypothesis_set(
            product_id="demo",
            blueprint_sha256="a" * 64,
            authority_sha256="b" * 64,
            task_id="task-1",
            model_version="P1-20260311",
            artifact_sha256="c" * 64,
        )
        summary = validate_hypothesis_set(
            payload,
            expected_product_id="demo",
            expected_blueprint_sha256="a" * 64,
        )
        self.assertEqual(summary["externalHypothesisCount"], 1)
        self.assertFalse(payload["hypotheses"][0]["canonicalSource"])
        self.assertFalse(payload["silentFallbackUsed"])

    def test_face_limit_is_bounded(self) -> None:
        request = self.request()
        request["faceLimit"] = 20001
        with self.assertRaisesRegex(ValueError, "faceLimit"):
            validate_multiview_request(request)


if __name__ == "__main__":
    unittest.main()
