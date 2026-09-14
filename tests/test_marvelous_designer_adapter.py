from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from image2outfit.marvelous_designer import (
    MarvelousDesignerContractError,
    build_request,
    edge_segments,
    request_sha256,
)


class MarvelousDesignerAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = {
            "id": "fixture",
            "adapterId": "avatar-v1",
            "productRoot": "Assets/GenWorks/fixture",
            "targetSourcePath": "Assets/Avatar/avatar.fbx",
        }
        self.pattern = {
            "productId": "fixture",
            "units": "meter",
            "pieces": [
                {
                    "pieceId": "front",
                    "partId": "body",
                    "boundary": [[0, 0], [0.1, 0], [0.1, 0.2], [0, 0.2]],
                    "grainAngleDegrees": 90,
                    "edges": [
                        {
                            "edgeId": "right",
                            "startVertex": 1,
                            "endVertex": 2,
                            "role": "seam",
                        },
                        {
                            "edgeId": "top",
                            "startVertex": 2,
                            "endVertex": 3,
                            "role": "seam",
                        },
                    ],
                },
                {
                    "pieceId": "back",
                    "partId": "body",
                    "boundary": [
                        [0, 0],
                        [0.1, 0],
                        [0.1, 0.2],
                        [0, 0.2],
                        [-0.02, 0.1],
                    ],
                    "grainAngleDegrees": 90,
                    "edges": [
                        {
                            "edgeId": "left",
                            "startVertex": 3,
                            "endVertex": 2,
                            "role": "seam",
                        },
                    ],
                },
            ],
        }
        self.stitches = {
            "productId": "fixture",
            "stitches": [
                {
                    "stitchId": "side",
                    "first": {"pieceId": "front", "edgeId": "top"},
                    "second": {"pieceId": "back", "edgeId": "left"},
                    "type": "plain",
                    "easingRatio": 1.0,
                    "direction": "reversed",
                }
            ],
        }
        self.materials = {
            "mapSets": {
                "cloth": {
                    "provenance": {"source": "generated"},
                    "files": {
                        "baseColor": "Assets/GenWorks/fixture/Textures/cloth_base.png",
                        "normal": "Assets/GenWorks/fixture/Textures/cloth_normal.png",
                        "roughness": "Assets/GenWorks/fixture/Textures/cloth_roughness.png",
                    },
                }
            },
            "materials": {
                "shell": {
                    "materialName": "Shell",
                    "mapSet": "cloth",
                    "regions": ["body"],
                    "alpha": 1,
                    "metallic": 0,
                }
            },
        }

    def test_edge_maps_shortest_arc(self) -> None:
        piece = copy.deepcopy(self.pattern["pieces"][0])
        piece["boundary"] = [
            [0, 0],
            [0.05, 0],
            [0.1, 0],
            [0.1, 0.2],
            [0, 0.2],
        ]
        edge = {"edgeId": "two-lines", "startVertex": 0, "endVertex": 2}
        segments = edge_segments(piece, edge)
        self.assertEqual([item["lineIndex"] for item in segments], [0, 1])

    def test_equal_arc_is_rejected_for_untyped_boundary(self) -> None:
        piece = self.pattern["pieces"][0]
        with self.assertRaisesRegex(MarvelousDesignerContractError, "ambiguous"):
            edge_segments(piece, {"edgeId": "half", "startVertex": 0, "endVertex": 2})

    def test_equal_arc_attachment_maps_to_internal_shape(self) -> None:
        pattern = copy.deepcopy(self.pattern)
        pattern["pieces"][0]["edges"] = [
            {
                "edgeId": "center-attach",
                "startVertex": 0,
                "endVertex": 2,
                "role": "attachment",
            }
        ]
        stitches = {
            "productId": "fixture",
            "stitches": [
                {
                    "stitchId": "attach",
                    "first": {"pieceId": "back", "edgeId": "left"},
                    "second": {"pieceId": "front", "edgeId": "center-attach"},
                    "direction": "not-applicable",
                    "easingRatio": 1.0,
                }
            ],
        }
        request = build_request(
            job=self.job,
            pattern=pattern,
            stitch_graph=stitches,
            material_recipe=self.materials,
        )
        front = next(item for item in request["patterns"] if item["pieceId"] == "front")
        self.assertEqual(len(front["internalLines"]), 1)
        self.assertEqual(front["internalLines"][0]["edgeId"], "center-attach")
        endpoint = request["stitches"][0]["segments"][0]["second"]
        self.assertEqual(endpoint["kind"], "internal")
        self.assertEqual(endpoint["internalEdgeId"], "center-attach")

    def test_request_is_deterministic_and_converts_to_mm(self) -> None:
        pattern = copy.deepcopy(self.pattern)
        pattern["pieces"][0]["boundary"] = [
            [0, 0],
            [0.1, 0],
            [0.1, 0.2],
            [0.04, 0.22],
            [0, 0.2],
        ]
        pattern["pieces"][0]["edges"] = [
            {"edgeId": "top", "startVertex": 2, "endVertex": 3, "role": "seam"}
        ]
        request_a = build_request(
            job=self.job,
            pattern=pattern,
            stitch_graph=self.stitches,
            material_recipe=self.materials,
        )
        request_b = build_request(
            job=self.job,
            pattern=pattern,
            stitch_graph=self.stitches,
            material_recipe=self.materials,
        )
        self.assertEqual(request_a, request_b)
        self.assertEqual(request_a["patterns"][0]["pointsMm"][1], [100.0, 0.0, 0])
        self.assertEqual(
            request_a["requestSha256"],
            request_sha256(
                {key: value for key, value in request_a.items() if key != "requestSha256"}
            ),
        )
        self.assertEqual(request_a["arrangement"]["status"], "UNVERIFIED")
        self.assertEqual(request_a["materials"]["status"], "BOUND")
        self.assertTrue(request_a["completionPolicy"]["mdExecutionIsNotProductPass"])

    def test_stitch_segment_count_mismatch_fails_closed(self) -> None:
        pattern = copy.deepcopy(self.pattern)
        pattern["pieces"][0]["boundary"] = [
            [0, 0],
            [0.05, 0],
            [0.1, 0],
            [0.1, 0.2],
            [0, 0.2],
        ]
        pattern["pieces"][0]["edges"] = [
            {"edgeId": "top", "startVertex": 0, "endVertex": 2, "role": "seam"}
        ]
        with self.assertRaisesRegex(
            MarvelousDesignerContractError, "explicit edge subdivision"
        ):
            build_request(
                job=self.job,
                pattern=pattern,
                stitch_graph=self.stitches,
                material_recipe=self.materials,
            )

    def test_material_provenance_and_assignment_are_preserved(self) -> None:
        pattern = copy.deepcopy(self.pattern)
        pattern["pieces"][0]["boundary"] = [
            [0, 0],
            [0.1, 0],
            [0.1, 0.2],
            [0.04, 0.22],
            [0, 0.2],
        ]
        pattern["pieces"][0]["edges"] = [
            {"edgeId": "top", "startVertex": 2, "endVertex": 3, "role": "seam"}
        ]
        request = build_request(
            job=self.job,
            pattern=pattern,
            stitch_graph=self.stitches,
            material_recipe=self.materials,
        )
        material = request["materials"]["definitions"][0]
        self.assertEqual(material["patterns"], ["back", "front"])
        self.assertEqual(material["textureProvenance"], {"source": "generated"})
        self.assertEqual(request["materials"]["unassignedPatterns"], [])
        self.assertEqual(request["materials"]["status"], "BOUND")

    def test_unrealized_texture_intent_stays_unverified(self) -> None:
        materials = copy.deepcopy(self.materials)
        del materials["mapSets"]["cloth"]["files"]
        request = build_request(
            job=self.job,
            pattern=self.pattern,
            stitch_graph=self.stitches,
            material_recipe=materials,
        )
        self.assertEqual(request["materials"]["status"], "UNVERIFIED")
        definition = request["materials"]["definitions"][0]
        self.assertEqual(definition["realizationStatus"], "UNVERIFIED")
        self.assertNotIn("textures", definition)

    def test_existing_siroino_fixture_prepares_internal_seam_request(self) -> None:
        root = Path(__file__).resolve().parents[1]
        product = root / "config" / "products" / "siroino-tuxedo-halter-dress-large"
        if not product.is_dir():
            self.skipTest("repository fixture not available")
        job = json.loads((product / "job.json").read_text(encoding="utf-8"))
        pattern = json.loads((product / "pattern-draft.json").read_text(encoding="utf-8"))
        stitches = json.loads((product / "stitch-graph.json").read_text(encoding="utf-8"))
        materials = json.loads((product / "material-recipe.json").read_text(encoding="utf-8"))
        request = build_request(
            job=job,
            pattern=pattern,
            stitch_graph=stitches,
            material_recipe=materials,
        )
        self.assertEqual(request["productId"], "siroino-tuxedo-halter-dress-large")
        self.assertEqual(request["arrangement"]["status"], "UNVERIFIED")
        self.assertEqual(request["materials"]["status"], "UNVERIFIED")
        self.assertGreater(len(request["patterns"]), 0)
        self.assertGreater(len(request["stitches"]), 0)
        ruffle = next(
            stitch for stitch in request["stitches"] if stitch["stitchId"] == "ruffle-to-bib"
        )
        self.assertEqual(ruffle["segments"][0]["second"]["kind"], "internal")
        self.assertEqual(
            ruffle["segments"][0]["second"]["internalEdgeId"], "centerline"
        )

    def test_identity_mismatch_is_rejected(self) -> None:
        pattern = copy.deepcopy(self.pattern)
        pattern["productId"] = "other"
        with self.assertRaisesRegex(MarvelousDesignerContractError, "identity mismatch"):
            build_request(job=self.job, pattern=pattern, stitch_graph=self.stitches)


if __name__ == "__main__":
    unittest.main()
