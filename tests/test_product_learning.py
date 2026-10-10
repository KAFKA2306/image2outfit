from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_product_learning as learning  # noqa: E402

CHAIN = ROOT / learning.FIXTURE_DIR


def _load() -> tuple[dict, dict, dict]:
    values = []
    for name in ("decision", "outcome", "retrospective"):
        values.append(json.loads((CHAIN / f"{name}.json").read_text(encoding="utf-8-sig")))
    return values[0], values[1], values[2]


class ProductLearningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.decision, self.outcome, self.retro = _load()

    def _rebound(self, outcome: dict | None = None, retro: dict | None = None) -> tuple[dict, dict, dict]:
        outcome = copy.deepcopy(outcome or self.outcome)
        retro = copy.deepcopy(retro or self.retro)
        outcome["decisionSha256"] = learning.canonical_sha256(self.decision)
        retro["decisionSha256"] = learning.canonical_sha256(self.decision)
        retro["outcomeSha256"] = learning.canonical_sha256(outcome)
        return self.decision, outcome, retro

    def test_committed_fixture_chain_is_valid(self) -> None:
        self.assertEqual(learning.validate_chain(self.decision, self.outcome, self.retro), [])

    def test_audit_passes_and_rejects_every_negative_case(self) -> None:
        result = learning.audit(ROOT)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["negativeCaseCount"], result["rejectedNegativeCaseCount"])

    def test_missing_outcome_is_not_success_or_zero(self) -> None:
        self.assertEqual(self.outcome["availability"], "NOT_OBSERVED")
        d, o, r = self._rebound()
        r["verdict"] = "VALIDATED"
        errors = learning.validate_chain(d, o, r)
        self.assertTrue(any("VALIDATED requires an observed" in item for item in errors), errors)

    def test_outcome_rejects_different_revision(self) -> None:
        outcome = copy.deepcopy(self.outcome)
        outcome["productRevision"] = "fixture-rev-002"
        d, o, r = self._rebound(outcome=outcome)
        errors = learning.validate_chain(d, o, r)
        self.assertTrue(any("productRevision differs" in item for item in errors), errors)

    def test_rewritten_decision_is_detected_by_hash(self) -> None:
        decision = copy.deepcopy(self.decision)
        decision["approvedScope"] = [*decision["approvedScope"], "rewritten"]
        errors = learning.validate_chain(decision, self.outcome, self.retro)
        self.assertTrue(any("decisionSha256 does not match" in item for item in errors), errors)

    def test_observed_outcome_with_sample_can_validate_when_quality_passes(self) -> None:
        outcome = copy.deepcopy(self.outcome)
        outcome["availability"] = "OBSERVED"
        outcome["sampleSize"] = 40
        outcome["measurements"] = [{"metric": "fixture-paid-conversion", "unit": "ratio", "value": 0.03}]
        retro = copy.deepcopy(self.retro)
        retro["verdict"] = "VALIDATED"
        d, o, r = self._rebound(outcome=outcome, retro=retro)
        self.assertEqual(learning.validate_chain(d, o, r), [])

    def test_quality_failure_is_routed_to_defect_issue(self) -> None:
        decision = copy.deepcopy(self.decision)
        decision["decisionState"] = "HOLD"
        decision["qualityEvidence"] = {"status": "FAIL", "releaseRecordSha256": None}
        retro = copy.deepcopy(self.retro)
        retro["verdict"] = "CHALLENGED"
        outcome = copy.deepcopy(self.outcome)
        outcome["decisionSha256"] = learning.canonical_sha256(decision)
        retro["decisionSha256"] = learning.canonical_sha256(decision)
        retro["outcomeSha256"] = learning.canonical_sha256(outcome)
        retro["followUps"] = [{"authority": "issue-190", "reference": "fixture-defect-1"}]
        errors = learning.validate_chain(decision, outcome, retro)
        self.assertEqual(errors, [])

    def test_personal_data_is_rejected(self) -> None:
        outcome = copy.deepcopy(self.outcome)
        outcome["provenance"]["customerEmail"] = "person@example.com"
        d, o, r = self._rebound(outcome=outcome)
        errors = learning.validate_chain(d, o, r)
        self.assertTrue(any("personal or transaction data" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
