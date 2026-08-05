from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.decomposition import (
    DecompositionHypothesis,
    GarmentDecomposition,
    ObservationState,
    PartObservation,
    PartRelation,
    PartRelationKind,
)
from image2outfit.domain import (
    BodyRegion,
    ConstructionRole,
    GarmentLocation,
    GarmentPartKind,
    Laterality,
    LayerPosition,
    SurfaceOrientation,
)
from image2outfit.execution import StageResultRequirement, validate_stage_result
from image2outfit.normalization import (
    CameraExtrinsics,
    CameraIntrinsics,
    CameraUncertainty,
    LandmarkObservation,
    NormalizedReferenceSet,
    NormalizedView,
    OcclusionMask,
    Transform2D,
)
from image2outfit.reference import (
    ImageTransform,
    ReferenceAsset,
    ReferenceAssetKind,
    ReferenceSet,
    ReferenceView,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def reference_fixture(
    original_sha256: str = HASH_A,
    derived_sha256: str = HASH_B,
) -> ReferenceSet:
    original = ReferenceAsset(
        asset_id="source-front",
        garment_id="test-garment",
        view_id="front-view",
        view=ReferenceView.FRONT,
        kind=ReferenceAssetKind.ORIGINAL,
        path="references/source-front.png",
        sha256=original_sha256,
        acquired_at="2026-08-05T19:00:00+09:00",
        license_note="user-provided reference",
        usage_note="garment reconstruction evidence",
        source_url="https://example.invalid/reference.png",
        unknown_fields=("back-construction", "fabric-friction"),
    )
    derived = ReferenceAsset(
        asset_id="cropped-front",
        garment_id="test-garment",
        view_id="front-view-crop",
        view=ReferenceView.FRONT,
        kind=ReferenceAssetKind.DERIVED,
        path="references/cropped-front.png",
        sha256=derived_sha256,
        acquired_at="2026-08-05T19:01:00+09:00",
        license_note="inherits source license",
        usage_note="normalized crop input",
        parent_asset_id="source-front",
        transforms=(
            ImageTransform(
                operation="crop",
                parameters={"x": 10, "y": 20, "width": 300, "height": 500},
            ),
        ),
    )
    return ReferenceSet(
        reference_set_id="test-reference-set",
        garment_id="test-garment",
        assets=(original, derived),
        extensions={"image2outfit.capture": {"device": "unknown"}},
    )


def normalized_fixture() -> NormalizedReferenceSet:
    transform = Transform2D(
        forward=((2.0, 0.0, 4.0), (0.0, 2.0, 6.0), (0.0, 0.0, 1.0)),
        inverse=((0.5, 0.0, -2.0), (0.0, 0.5, -3.0), (0.0, 0.0, 1.0)),
    )
    source = (12.0, 20.0)
    normalized = transform.normalize(source)
    view = NormalizedView(
        normalized_view_id="normalized-front",
        source_asset_id="cropped-front",
        transform=transform,
        intrinsics=CameraIntrinsics(1000.0, 1000.0, 512.0, 512.0),
        extrinsics=CameraExtrinsics(IDENTITY, (0.0, 0.0, 1500.0)),
        uncertainty=CameraUncertainty(2.0, 1.0, 3.0, 0.5),
        landmarks=(
            LandmarkObservation(
                landmark_id="left-shoulder-front",
                source_point_px=source,
                normalized_point_px=normalized,
                confidence=0.95,
                occluded=False,
            ),
            LandmarkObservation(
                landmark_id="right-wrist-front",
                source_point_px=(30.0, 40.0),
                normalized_point_px=transform.normalize((30.0, 40.0)),
                confidence=0.2,
                occluded=True,
            ),
        ),
        occlusion_masks=(
            OcclusionMask(
                mask_id="hair-mask",
                path="evidence/hair-mask.png",
                sha256=HASH_A,
                occluder="hair",
            ),
        ),
        pose_id="reference-pose",
        mirrored=False,
    )
    return NormalizedReferenceSet(
        normalized_set_id="normalized-reference-set",
        reference_set_id="test-reference-set",
        garment_id="test-garment",
        views=(view,),
    )


class ReferenceSetTests(unittest.TestCase):
    def test_files_are_rehashed_and_stage_evidence_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_path = root / "references/source-front.png"
            derived_path = root / "references/cropped-front.png"
            original_path.parent.mkdir(parents=True)
            original_path.write_bytes(b"original")
            derived_path.write_bytes(b"derived")
            original_hash = hashlib.sha256(original_path.read_bytes()).hexdigest()
            derived_hash = hashlib.sha256(derived_path.read_bytes()).hexdigest()
            references = reference_fixture(original_hash, derived_hash)
            references.verify_files(root)
            payload = validate_stage_result(
                {
                    "schemaVersion": 1,
                    "stage": "ingest-reference",
                    "productId": "test-garment",
                    "status": "PASS",
                    "evidence": references.stage_result_evidence(),
                },
                expected_stage="ingest-reference",
                expected_product_id="test-garment",
                requirement=StageResultRequirement(minimum_evidence_count=2),
            )
            self.assertEqual(2, len(payload["evidence"]))
            self.assertEqual(
                ("back-construction", "fabric-friction"),
                references.unknown_fields,
            )
            original_path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                references.verify_files(root)

    def test_url_without_original_file_contract_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_url"):
            ReferenceAsset(
                asset_id="source-front",
                garment_id="test-garment",
                view_id="front-view",
                view=ReferenceView.FRONT,
                kind=ReferenceAssetKind.ORIGINAL,
                path="references/source-front.png",
                sha256=HASH_A,
                acquired_at="2026-08-05T19:00:00+09:00",
                license_note="license",
                usage_note="usage",
            )


class NormalizedReferenceSetTests(unittest.TestCase):
    def test_reprojection_uncertainty_and_source_identity_are_deterministic(
        self,
    ) -> None:
        references = reference_fixture()
        normalized = normalized_fixture()
        normalized.validate_sources(references)
        view = normalized.views[0]
        self.assertAlmostEqual(0.0, view.reprojection_error_px)
        self.assertGreater(view.pattern_scale_uncertainty_mm(1500.0), 3.0)
        normalized.reject_mirror_ambiguity({"cropped-front": False})
        with self.assertRaisesRegex(ValueError, "mirror state mismatch"):
            normalized.reject_mirror_ambiguity({"cropped-front": True})


class GarmentDecompositionTests(unittest.TestCase):
    def test_structural_parts_preserve_asymmetry_and_multiple_hypotheses(self) -> None:
        left_pocket = PartObservation(
            part_id="left-cargo-pocket",
            kind=GarmentPartKind.TRIM,
            locations=(
                GarmentLocation(
                    BodyRegion.UPPER_LEG,
                    Laterality.LEFT,
                    SurfaceOrientation.OUTER,
                ),
            ),
            construction_role=ConstructionRole.ACCESSORY,
            layer=LayerPosition.ATTACHED,
            state=ObservationState.VISIBLE,
            confidence=0.95,
            source_view_ids=("normalized-front",),
            mask_references=("masks/left-pocket.png",),
            extension_kind="image2outfit.pocket",
        )
        waistband = PartObservation(
            part_id="waistband",
            kind=GarmentPartKind.WAISTBAND,
            locations=(
                GarmentLocation(
                    BodyRegion.WAIST,
                    Laterality.BILATERAL,
                    SurfaceOrientation.FRONT,
                ),
            ),
            construction_role=ConstructionRole.STRUCTURAL_PANEL,
            layer=LayerPosition.OUTER,
            state=ObservationState.INFERRED,
            confidence=0.6,
            source_view_ids=("normalized-front",),
        )
        base = DecompositionHypothesis(
            hypothesis_id="visible-structure",
            parts=(left_pocket, waistband),
            relations=(
                PartRelation(
                    relation_id="pocket-attached-waist",
                    kind=PartRelationKind.CONNECTED_TO,
                    source_part_id="left-cargo-pocket",
                    target_part_id="waistband",
                    confidence=0.7,
                    source_view_ids=("normalized-front",),
                ),
            ),
            confidence=0.8,
            extensions={"image2outfit.detector": {"model": "fixture"}},
        )
        alternative = DecompositionHypothesis(
            hypothesis_id="hidden-right-pocket",
            parent_hypothesis_id="visible-structure",
            parts=(
                left_pocket,
                waistband,
                PartObservation(
                    part_id="right-cargo-pocket",
                    kind=GarmentPartKind.TRIM,
                    locations=(
                        GarmentLocation(
                            BodyRegion.UPPER_LEG,
                            Laterality.RIGHT,
                            SurfaceOrientation.OUTER,
                        ),
                    ),
                    construction_role=ConstructionRole.ACCESSORY,
                    layer=LayerPosition.ATTACHED,
                    state=ObservationState.OCCLUDED,
                    confidence=0.35,
                    source_view_ids=("normalized-front",),
                    extension_kind="image2outfit.pocket",
                ),
            ),
            relations=base.relations,
            confidence=0.4,
        )
        decomposition = GarmentDecomposition(
            decomposition_id="decomposition-set",
            normalized_set_id="normalized-reference-set",
            garment_id="test-garment",
            hypotheses=(base, alternative),
        )
        decomposition.validate_sources(normalized_fixture())
        self.assertEqual(("left-cargo-pocket",), base.asymmetric_part_ids)
        self.assertEqual(
            "visible-structure",
            decomposition.ranked_hypotheses()[0].hypothesis_id,
        )

    def test_non_namespaced_extension_is_rejected(self) -> None:
        part = PartObservation(
            part_id="unknown-trim",
            kind=GarmentPartKind.TRIM,
            locations=(
                GarmentLocation(
                    BodyRegion.CHEST,
                    Laterality.CENTER,
                    SurfaceOrientation.FRONT,
                ),
            ),
            construction_role=ConstructionRole.TRIM,
            layer=LayerPosition.ATTACHED,
            state=ObservationState.INFERRED,
            confidence=0.2,
            source_view_ids=("normalized-front",),
        )
        with self.assertRaisesRegex(ValueError, "namespaced"):
            DecompositionHypothesis(
                hypothesis_id="invalid-extension",
                parts=(part,),
                relations=(),
                confidence=0.2,
                extensions={"custom": {}},
            )


if __name__ == "__main__":
    unittest.main()
