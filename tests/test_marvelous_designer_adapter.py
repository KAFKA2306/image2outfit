from __future__ import annotations

import copy
import unittest

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
                        {"edgeId": "right", "startVertex": 1, "endVertex": 2},
                        {"edgeId": "top", "startVertex": 2, "endVertex": 3},
                    ],
                },
                {
                    "pieceId": "back",
                    "partId": "body",
                    "boundary": [[0, 0], [0.1, 0], [0.1, 0.2], [0, 0.2], [-0.02, 0.1]],
                    "grainAngleDegrees": 90,
                    "edges": [
                        {"edgeId": "left", "startVertex": 3, "endVertex": 2},
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
            "mapSets": {"cloth": {"provenance": {"source": "generated"}}},
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
        piece["boundary"] = [[0, 0], [0.05, 0], [0.1, 0], [0.1, 0.2], [0, 0.2]]
        edge = {"edgeId": "two-lines", "startVertex": 0, "endVertex": 2}
        segments = edge_segments(piece, edge)
        self.assertEqual([item["lineIndex"] for item in segments], [0, 1])

    def test_equal_arc_is_rejected(self) -> None:
        piece = self.pattern["pieces"][0]
        with self.assertRaisesRegex(MarvelousDesignerContractError, "ambiguous"):
            edge_segments(piece, {"edgeId": "half", "startVertex": 0, "endVertex": 2})

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
            {"edgeId": "top", "startVertex": 2, "endVertex": 3}
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
            {"edgeId": "top", "startVertex": 0, "endVertex": 2}
        ]
        with self.assertRaisesRegex(MarvelousDesignerContractError, "explicit edge subdivision"):
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
            {"edgeId": "top", "startVertex": 2, "endVertex": 3}
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

    def test_identity_mismatch_is_rejected(self) -> None:
        pattern = copy.deepcopy(self.pattern)
        pattern["productId"] = "other"
        with self.assertRaisesRegex(MarvelousDesignerContractError, "identity mismatch"):
            build_request(job=self.job, pattern=pattern, stitch_graph=self.stitches)


if __name__ == "__main__":
    unittest.main()
