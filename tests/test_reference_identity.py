from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.identity import (
    IdentityClaim,
    IdentityEvidence,
    IdentityField,
    IdentityStatus,
    ReferenceIdentityManifest,
    load_reference_identity,
    make_identity_history_event,
)

SOURCE_REFERENCE = "private-reference://sha256/" + "a" * 64


def identity_fixture(
    overrides: dict[
        IdentityField,
        tuple[IdentityStatus, str | None, tuple[str, ...], str],
    ]
    | None = None,
) -> ReferenceIdentityManifest:
    overrides = overrides or {}
    evidence = IdentityEvidence(
        evidence_id="official-page",
        evidence_type="official-product-page",
        source_reference="https://example.invalid/product",
        captured_at="2026-08-06T08:00:00+09:00",
        extraction_method="direct-inspection",
        reviewer_role="identity-auditor",
    )
    claims: list[IdentityClaim] = []
    events = []
    previous = "0" * 64
    for sequence, field in enumerate(IdentityField, start=1):
        status, value, evidence_ids, reason = overrides.get(
            field,
            (
                IdentityStatus.UNVERIFIED,
                None,
                (),
                "No primary-source identity evidence is available.",
            ),
        )
        claims.append(IdentityClaim(field, status, value, reason, evidence_ids))
        event = make_identity_history_event(
            sequence=sequence,
            field=field,
            status=status,
            value=value,
            reason=reason,
            evidence_ids=evidence_ids,
            actor_role="identity-auditor",
            recorded_at="2026-08-06T08:00:00+09:00",
            previous_digest=previous,
        )
        events.append(event)
        previous = event.event_digest
    return ReferenceIdentityManifest(
        product_id="internal-product",
        source_reference=SOURCE_REFERENCE,
        claims=tuple(claims),
        evidence=(evidence,),
        history=tuple(events),
    )


class ReferenceIdentityTests(unittest.TestCase):
    def test_unverified_market_identifiers_remain_empty(self) -> None:
        manifest = identity_fixture()
        self.assertEqual({}, manifest.verified_market_identifiers)
        self.assertEqual(12, manifest.status_summary["UNVERIFIED"])
        restored = ReferenceIdentityManifest.from_mapping(manifest.to_mapping())
        self.assertEqual(manifest.manifest_digest, restored.manifest_digest)

    def test_verified_gtin_and_jan_require_valid_check_digits(self) -> None:
        manifest = identity_fixture(
            {
                IdentityField.GTIN: (
                    IdentityStatus.VERIFIED,
                    "4006381333931",
                    ("official-page",),
                    "The official page displays the assigned GTIN.",
                ),
                IdentityField.JAN: (
                    IdentityStatus.VERIFIED,
                    "4006381333931",
                    ("official-page",),
                    "The official page displays the assigned JAN.",
                ),
            }
        )
        self.assertEqual(
            "4006381333931",
            manifest.verified_market_identifiers["gtin"],
        )
        with self.assertRaisesRegex(ValueError, "GTIN"):
            identity_fixture(
                {
                    IdentityField.GTIN: (
                        IdentityStatus.CANDIDATE,
                        "4006381333932",
                        ("official-page",),
                        "Unverified candidate.",
                    )
                }
            )

    def test_internal_product_id_cannot_be_promoted_as_model_or_sku(self) -> None:
        for field in (IdentityField.MODEL_NUMBER, IdentityField.SELLER_SKU):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "internal product_id"),
            ):
                identity_fixture(
                    {
                        field: (
                            IdentityStatus.CANDIDATE,
                            "internal-product",
                            ("official-page",),
                            "An unsafe slug-derived candidate.",
                        )
                    }
                )

    def test_history_chain_detects_mutation(self) -> None:
        manifest = identity_fixture()
        events = list(manifest.history)
        events[1] = dataclasses.replace(events[1], reason="mutated")
        with self.assertRaisesRegex(ValueError, "event digest"):
            dataclasses.replace(manifest, history=tuple(events))

    def test_rejected_candidate_is_retained_but_not_promoted(self) -> None:
        manifest = identity_fixture(
            {
                IdentityField.SELLER_SKU: (
                    IdentityStatus.REJECTED,
                    "LOOKALIKE-01",
                    ("official-page",),
                    "The candidate listing has a different garment structure.",
                )
            }
        )
        self.assertEqual({}, manifest.verified_market_identifiers)
        self.assertIn("LOOKALIKE-01", json.dumps(manifest.to_mapping()))

    def test_tracked_product_manifest_is_valid_and_unverified(self) -> None:
        path = (
            ROOT
            / "config"
            / "products"
            / "siroino-tuxedo-halter-dress-large"
            / "reference-identity.json"
        )
        manifest = load_reference_identity(path)
        self.assertEqual(
            "siroino-tuxedo-halter-dress-large",
            manifest.product_id,
        )
        self.assertEqual({}, manifest.verified_market_identifiers)
        self.assertEqual(12, manifest.status_summary["UNVERIFIED"])


if __name__ == "__main__":
    unittest.main()
