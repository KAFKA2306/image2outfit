from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.material import CalibrationStatus  # noqa: E402
from image2outfit.knowledge_base import (  # noqa: E402
    DefectCase,
    EvidenceRef,
    TrialRecord,
    check_material_references,
    defect_from_feedback,
    fabric_promotion_blockers,
    load_fabric_library_for,
    load_knowledge_base,
    promotable_fabric_ids,
    recurrence_summary,
    recurring_categories,
    verify_evidence,
)

FIXTURE = ROOT / "config" / "knowledge" / "knowledge-base.fixture.v1.json"
SHA = "a" * 64


def _evidence() -> tuple[EvidenceRef, ...]:
    return (EvidenceRef(path="config/x.json", sha256=SHA),)


class FabricPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.materials = load_fabric_library_for(load_knowledge_base(FIXTURE), ROOT)

    def test_measured_open_licensed_presets_are_promotable(self) -> None:
        self.assertEqual(6, len(promotable_fabric_ids(self.materials)))
        for spec in self.materials:
            self.assertEqual((), fabric_promotion_blockers(spec))

    def test_unknown_license_is_never_promoted(self) -> None:
        spec = replace(self.materials[0], source_license="UNKNOWN")
        self.assertIn("license-not-promotable:UNKNOWN", fabric_promotion_blockers(spec))
        self.assertNotIn(spec.material_id, promotable_fabric_ids((spec,)))

    def test_estimated_calibration_is_never_promoted(self) -> None:
        spec = replace(
            self.materials[0], calibration_status=CalibrationStatus.ESTIMATED
        )
        self.assertIn(
            "calibration-not-measured:estimated",
            fabric_promotion_blockers(spec),
        )


class KnowledgeLoadTests(unittest.TestCase):
    def test_fixture_loads_with_defects_trials_and_fabric_references(self) -> None:
        knowledge = load_knowledge_base(FIXTURE)
        self.assertEqual(2, len(knowledge.defects))
        self.assertEqual(2, len(knowledge.trials))
        materials = load_fabric_library_for(knowledge, ROOT)
        check_material_references(knowledge, materials)

    def test_fixture_evidence_hashes_match_current_files(self) -> None:
        verify_evidence(load_knowledge_base(FIXTURE), ROOT)

    def test_fixture_records_are_excluded_from_production_projections(self) -> None:
        knowledge = load_knowledge_base(FIXTURE)
        self.assertEqual((), knowledge.production_defects())
        self.assertEqual((), knowledge.production_trials())

    def test_unknown_material_reference_is_rejected(self) -> None:
        knowledge = load_knowledge_base(FIXTURE)
        trial = replace(knowledge.trials[0], material_ids=("missing-material",))
        broken = replace(knowledge, trials=(trial,))
        materials = load_fabric_library_for(knowledge, ROOT)
        with self.assertRaisesRegex(ValueError, "unknown materials"):
            check_material_references(broken, materials)

    def test_evidence_hash_mismatch_is_rejected(self) -> None:
        knowledge = load_knowledge_base(FIXTURE)
        defect = replace(
            knowledge.defects[0],
            evidence=(
                EvidenceRef(
                    path=knowledge.defects[0].evidence[0].path, sha256="b" * 64
                ),
            ),
        )
        broken = replace(knowledge, defects=(defect,))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_evidence(broken, ROOT)


class RecordValidationTests(unittest.TestCase):
    def test_evidence_path_must_be_repository_relative(self) -> None:
        for path in ("/abs/x.json", "../x.json", "a\\b.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                EvidenceRef(path=path, sha256=SHA)

    def test_evidence_sha256_must_be_lowercase_hex(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceRef(path="x.json", sha256="A" * 64)

    def test_rejected_trial_requires_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "rejection_reason"):
            TrialRecord(
                trial_id="t1",
                product_slug="siroino-x",
                revision="r1",
                change="c",
                decision="rejected",
                applies_when=("a",),
                not_applicable_when=("b",),
                evidence=_evidence(),
            )

    def test_accepted_trial_must_not_carry_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not carry"):
            TrialRecord(
                trial_id="t1",
                product_slug="siroino-x",
                revision="r1",
                change="c",
                decision="accepted",
                applies_when=("a",),
                not_applicable_when=("b",),
                evidence=_evidence(),
                rejection_reason="oops",
            )

    def test_trial_requires_applicability_and_non_applicability(self) -> None:
        with self.assertRaisesRegex(ValueError, "applies_when"):
            TrialRecord(
                trial_id="t1",
                product_slug="siroino-x",
                revision="r1",
                change="c",
                decision="accepted",
                applies_when=(),
                not_applicable_when=("b",),
                evidence=_evidence(),
            )
        with self.assertRaisesRegex(ValueError, "not_applicable_when"):
            TrialRecord(
                trial_id="t1",
                product_slug="siroino-x",
                revision="r1",
                change="c",
                decision="accepted",
                applies_when=("a",),
                not_applicable_when=(),
                evidence=_evidence(),
            )

    def test_product_slug_must_be_lowercase_slug(self) -> None:
        with self.assertRaisesRegex(ValueError, "slug"):
            DefectCase(
                defect_id="d1",
                product_slug="Siroino Bad",
                revision="r1",
                category="fit-tension",
                severity="minor",
                source_kind="internal-audit",
                summary="s",
                evidence=_evidence(),
            )

    def test_fixture_source_kind_requires_fixture_flag(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixture=true"):
            DefectCase(
                defect_id="d1",
                product_slug="siroino-x",
                revision="r1",
                category="fit-tension",
                severity="minor",
                source_kind="fixture",
                summary="s",
                evidence=_evidence(),
                fixture=False,
            )


class FeedbackConversionTests(unittest.TestCase):
    def _feedback(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "feedbackId": "fb-1",
            "productSlug": "siroino-x",
            "revision": "r2",
            "category": "fit-tension",
            "severity": "major",
            "sourceKind": "customer-feedback",
            "summary": "shoulder pulls",
            "evidence": [{"path": "config/x.json", "sha256": SHA}],
            "trackingRef": "https://github.com/KAFKA2306/image2outfit/issues/171",
        }
        base.update(overrides)
        return base

    def test_feedback_converts_to_traceable_defect(self) -> None:
        defect = defect_from_feedback(self._feedback())
        self.assertEqual("fb-1", defect.defect_id)
        self.assertEqual("customer-feedback", defect.source_kind)
        self.assertIsNotNone(defect.tracking_ref)

    def test_feedback_without_tracking_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "tracking_ref"):
            defect_from_feedback(self._feedback(trackingRef="  "))

    def test_feedback_with_unknown_source_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "sourceKind"):
            defect_from_feedback(self._feedback(sourceKind="rumor"))


class RecurrenceTests(unittest.TestCase):
    def _defect(
        self, defect_id: str, product: str, category: str, revision: str = "r1"
    ) -> DefectCase:
        return DefectCase(
            defect_id=defect_id,
            product_slug=product,
            revision=revision,
            category=category,
            severity="minor",
            source_kind="internal-audit",
            summary="s",
            evidence=_evidence(),
        )

    def test_summary_counts_products_and_revisions_deterministically(self) -> None:
        defects = (
            self._defect("a", "siroino-b", "fit-tension", "r2"),
            self._defect("b", "siroino-a", "fit-tension", "r1"),
            self._defect("c", "siroino-a", "seam-gap"),
        )
        summary = recurrence_summary(defects)
        self.assertEqual(["fit-tension", "seam-gap"], list(summary))
        self.assertEqual(2, summary["fit-tension"]["count"])
        self.assertEqual(["siroino-a", "siroino-b"], summary["fit-tension"]["products"])
        self.assertEqual(["r1", "r2"], summary["fit-tension"]["revisions"])

    def test_recurring_requires_multiple_products(self) -> None:
        defects = (
            self._defect("a", "siroino-a", "seam-gap"),
            self._defect("b", "siroino-a", "seam-gap"),
            self._defect("c", "siroino-b", "fit-tension"),
            self._defect("d", "siroino-c", "fit-tension"),
        )
        self.assertEqual(("fit-tension",), recurring_categories(defects))


if __name__ == "__main__":
    unittest.main()
