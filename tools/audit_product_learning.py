#!/usr/bin/env python3
"""Validate product-learning decision, outcome, and retrospective records.

Three records stay separate and append-only:

- decision: the launch/hold/reject/retire call with its decision-time evidence and hypothesis
- outcome: what was observed afterwards for the same immutable revision; missing data is
  NOT_OBSERVED (never success, failure, or zero) and small samples are INCONCLUSIVE
- retrospective: a narrow verdict appended on top of the decision and outcome

The outcome and retrospective bind to the decision by canonical SHA-256, so a rewritten
decision is detected instead of silently merged. Quality findings are routed to #190 and
corrective trials to #408; this module never duplicates those authorities.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path("contracts/product-learning/fixtures/chain")
SCHEMA_VERSION = 1
PRODUCT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

DECISION_STATES = {"LAUNCH", "HOLD", "REJECT", "RETIRE"}
QUALITY_STATUSES = {"PASS", "FAIL", "NOT_EVALUATED"}
DIRECTIONS = {"increase", "decrease", "maintain"}
AVAILABILITY = {"NOT_OBSERVED", "INCONCLUSIVE", "OBSERVED"}
VERDICTS = {"VALIDATED", "CHALLENGED", "INCONCLUSIVE"}
DEFECT_AUTHORITY = "issue-190"
FOLLOW_UP_AUTHORITIES = {DEFECT_AUTHORITY, "issue-408"}
# Normalized key fragments (lowercase, alphanumerics only) that mark personal or transaction data.
PII_KEY_TOKENS = (
    "email",
    "phone",
    "address",
    "buyer",
    "customer",
    "ipaddress",
    "creditcard",
    "cardnumber",
    "transaction",
    "postalcode",
    "firstname",
    "lastname",
    "fullname",
    "username",
)


def canonical_sha256(record: dict[str, Any]) -> str:
    text = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256.match(value))


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _strings(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_nonempty(item) for item in value)
    )


def _pii_paths(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            where = f"{path}.{key}" if path else str(key)
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(token in normalized for token in PII_KEY_TOKENS):
                found.append(where)
            found.extend(_pii_paths(child, where))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_pii_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str) and EMAIL.search(value):
        found.append(path or "<root>")
    return found


def _header(record: dict[str, Any], kind: str, errors: list[str]) -> None:
    if record.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")
    if record.get("recordKind") != kind:
        errors.append(f"recordKind must be {kind}")
    product_id = record.get("productId")
    if not isinstance(product_id, str) or not PRODUCT_ID.match(product_id):
        errors.append("productId is invalid")
    if not _nonempty(record.get("productRevision")):
        errors.append("productRevision is required")
    if not _sha(record.get("candidateManifestSha256")):
        errors.append("candidateManifestSha256 must be a SHA-256 hex digest")
    for path in _pii_paths(record):
        errors.append(f"personal or transaction data is not allowed: {path}")


def validate_decision(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _header(record, "product-learning-decision", errors)
    if not _nonempty(record.get("decisionId")):
        errors.append("decisionId is required")
    decided = _utc(record.get("decidedAt"))
    if decided is None:
        errors.append("decidedAt must be an ISO-8601 timestamp with timezone")
    state = record.get("decisionState")
    if state not in DECISION_STATES:
        errors.append("decisionState is not allowed")
    if not _strings(record.get("approvedScope")):
        errors.append("approvedScope must be a non-empty string list")
    if not _strings(record.get("limitations")):
        errors.append("limitations must be a non-empty string list")
    if not _strings(record.get("unknowns"), allow_empty=True):
        errors.append("unknowns must be a string list")

    quality = record.get("qualityEvidence")
    quality = quality if isinstance(quality, dict) else {}
    status = quality.get("status")
    if status not in QUALITY_STATUSES:
        errors.append("qualityEvidence.status is not allowed")
    release_sha = quality.get("releaseRecordSha256")
    if release_sha is not None and not _sha(release_sha):
        errors.append("qualityEvidence.releaseRecordSha256 must be SHA-256 or null")
    if state == "LAUNCH" and (status != "PASS" or not _sha(release_sha)):
        errors.append("LAUNCH requires PASS quality evidence bound to a release record")

    spec = record.get("qualitySpec")
    if (
        not isinstance(spec, dict)
        or not _nonempty(spec.get("id"))
        or not _sha(spec.get("sha256"))
    ):
        errors.append("qualitySpec needs id and SHA-256 identity")

    hypothesis = record.get("hypothesis")
    hypothesis = hypothesis if isinstance(hypothesis, dict) else {}
    if not _nonempty(hypothesis.get("statement")):
        errors.append("hypothesis.statement is required")
    signal = hypothesis.get("expectedSignal")
    signal = signal if isinstance(signal, dict) else {}
    if not _nonempty(signal.get("metric")) or signal.get("direction") not in DIRECTIONS:
        errors.append("hypothesis.expectedSignal needs metric and a direction")
    threshold = signal.get("threshold")
    if threshold is not None and not _finite(threshold):
        errors.append("hypothesis.expectedSignal.threshold must be numeric or null")
    window = hypothesis.get("evaluationWindow")
    window = window if isinstance(window, dict) else {}
    start, end = _utc(window.get("start")), _utc(window.get("end"))
    if start is None or end is None or start >= end:
        errors.append("hypothesis.evaluationWindow must be a valid UTC window")
    elif decided is not None and start < decided:
        errors.append("hypothesis.evaluationWindow cannot start before decidedAt")
    if not _strings(hypothesis.get("criteria")):
        errors.append("hypothesis.criteria must be a non-empty string list")

    sources = record.get("metricSources")
    if (
        not isinstance(sources, list)
        or not sources
        or not all(
            isinstance(item, dict)
            and _nonempty(item.get("id"))
            and _nonempty(item.get("reference"))
            for item in sources
        )
    ):
        errors.append("metricSources needs at least one id/reference pair")
    return errors


def validate_outcome(record: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _header(record, "product-learning-outcome", errors)
    if not _nonempty(record.get("outcomeId")):
        errors.append("outcomeId is required")
    if record.get("decisionId") != decision.get("decisionId"):
        errors.append("decisionId does not match the decision record")
    if record.get("decisionSha256") != canonical_sha256(decision):
        errors.append(
            "decisionSha256 does not match the decision (rewritten or wrong decision)"
        )
    for field in ("productId", "productRevision", "candidateManifestSha256"):
        if record.get(field) != decision.get(field):
            errors.append(
                f"{field} differs from the decision; cross-revision outcomes are not merged"
            )

    period = record.get("observationPeriod")
    period = period if isinstance(period, dict) else {}
    start, end = _utc(period.get("start")), _utc(period.get("end"))
    if start is None or end is None or start >= end:
        errors.append("observationPeriod must be a valid UTC window")
    decided = _utc(decision.get("decidedAt"))
    if start is not None and decided is not None and start < decided:
        errors.append("observationPeriod cannot start before the decision")
    if _utc(record.get("dataAsOf")) is None:
        errors.append("dataAsOf must be an ISO-8601 UTC timestamp")

    availability = record.get("availability")
    if availability not in AVAILABILITY:
        errors.append("availability is not allowed")
    measurements = record.get("measurements")
    if not isinstance(measurements, list):
        errors.append("measurements must be a list")
        measurements = []
    sample = record.get("sampleSize")
    if not isinstance(sample, int) or isinstance(sample, bool) or sample < 0:
        errors.append("sampleSize must be a non-negative integer")
        sample = -1
    if availability == "OBSERVED" and (not measurements or sample < 1):
        errors.append("OBSERVED requires at least one measurement and a sample")
    if availability == "NOT_OBSERVED" and (measurements or sample != 0):
        errors.append(
            "NOT_OBSERVED cannot carry measurements or a sample; missing is not zero"
        )
    for index, item in enumerate(measurements):
        if (
            not isinstance(item, dict)
            or not _nonempty(item.get("metric"))
            or not _nonempty(item.get("unit"))
            or not _finite(item.get("value"))
        ):
            errors.append(
                f"measurements[{index}] needs metric, unit, and a finite numeric value"
            )

    defects = record.get("defectReferences")
    if not isinstance(defects, list) or not all(
        isinstance(item, dict)
        and _nonempty(item.get("defectId"))
        and item.get("authority") == DEFECT_AUTHORITY
        for item in defects
    ):
        errors.append(
            f"defectReferences must be a list of {DEFECT_AUTHORITY} references"
        )

    provenance = record.get("provenance")
    if (
        not isinstance(provenance, dict)
        or not _nonempty(provenance.get("source"))
        or not _nonempty(provenance.get("reference"))
    ):
        errors.append("provenance needs source and reference")
    return errors


def validate_retrospective(
    record: dict[str, Any], decision: dict[str, Any], outcome: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    _header(record, "product-learning-retrospective", errors)
    if not _nonempty(record.get("retrospectiveId")):
        errors.append("retrospectiveId is required")
    if record.get("decisionId") != decision.get("decisionId"):
        errors.append("decisionId does not match the decision record")
    if record.get("decisionSha256") != canonical_sha256(decision):
        errors.append("decisionSha256 does not match the decision")
    if record.get("outcomeId") != outcome.get("outcomeId"):
        errors.append("outcomeId does not match the outcome record")
    if record.get("outcomeSha256") != canonical_sha256(outcome):
        errors.append("outcomeSha256 does not match the outcome")
    for field in ("productId", "productRevision", "candidateManifestSha256"):
        if record.get(field) != decision.get(field) or outcome.get(
            field
        ) != decision.get(field):
            errors.append(
                f"{field} is not identical across decision, outcome, and retrospective"
            )

    reviewed = _utc(record.get("reviewedAt"))
    if reviewed is None:
        errors.append("reviewedAt must be an ISO-8601 UTC timestamp")
    elif (
        data_as_of := _utc(outcome.get("dataAsOf"))
    ) is not None and reviewed < data_as_of:
        errors.append("reviewedAt cannot precede the outcome dataAsOf")
    if not _nonempty(record.get("summary")):
        errors.append("summary is required")

    verdict = record.get("verdict")
    if verdict not in VERDICTS:
        errors.append("verdict is not allowed")
    availability = outcome.get("availability")
    quality = (decision.get("qualityEvidence") or {}).get("status")
    if verdict == "VALIDATED":
        if availability != "OBSERVED":
            errors.append(
                "VALIDATED requires an observed customer outcome; unobserved is not validated"
            )
        if quality != "PASS":
            errors.append(
                "VALIDATED requires PASS quality evidence; value cannot promote a failed gate"
            )
    if verdict == "CHALLENGED" and availability != "OBSERVED" and quality != "FAIL":
        errors.append(
            "CHALLENGED requires an observed outcome or failed quality evidence"
        )

    follow_ups = record.get("followUps")
    if not isinstance(follow_ups, list) or not all(
        isinstance(item, dict)
        and item.get("authority") in FOLLOW_UP_AUTHORITIES
        and _nonempty(item.get("reference"))
        for item in follow_ups
    ):
        errors.append(
            "followUps must reference issue-190 or issue-408 with a reference"
        )
        follow_ups = []
    if quality == "FAIL" and not any(
        item.get("authority") == DEFECT_AUTHORITY for item in follow_ups
    ):
        errors.append("failed quality evidence must be routed to issue-190")
    return errors


def validate_chain(
    decision: dict[str, Any], outcome: dict[str, Any], retrospective: dict[str, Any]
) -> list[str]:
    errors = [f"decision: {item}" for item in validate_decision(decision)]
    errors += [f"outcome: {item}" for item in validate_outcome(outcome, decision)]
    errors += [
        f"retrospective: {item}"
        for item in validate_retrospective(retrospective, decision, outcome)
    ]
    return errors


def _rebind(
    decision: dict[str, Any], outcome: dict[str, Any], retrospective: dict[str, Any]
) -> None:
    outcome["decisionSha256"] = canonical_sha256(decision)
    retrospective["decisionSha256"] = canonical_sha256(decision)
    retrospective["outcomeSha256"] = canonical_sha256(outcome)


def _observed(outcome: dict[str, Any]) -> None:
    outcome["availability"] = "OBSERVED"
    outcome["sampleSize"] = 12
    outcome["measurements"] = [
        {"metric": "fixture-paid-conversion", "unit": "ratio", "value": 0.03}
    ]


def _negative_cases(
    decision: dict[str, Any], outcome: dict[str, Any], retrospective: dict[str, Any]
) -> list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Mutations that must each be rejected.

    Hashes are rebound after a mutation so each case exercises its own rule, except the
    rewrite case, which must fail on the stale decision hash alone.
    """

    def case(name: str, mutate, *, rebind: bool = True) -> tuple[str, dict, dict, dict]:
        d, o, r = (
            copy.deepcopy(decision),
            copy.deepcopy(outcome),
            copy.deepcopy(retrospective),
        )
        mutate(d, o, r)
        if rebind:
            _rebind(d, o, r)
        return name, d, o, r

    def rewritten(d, o, r):
        d["approvedScope"] = [
            *d["approvedScope"],
            "added after the outcome was recorded",
        ]

    def revision_mismatch(d, o, r):
        o["productRevision"] = "fixture-rev-002"

    def not_observed_as_zero(d, o, r):
        o["measurements"] = [
            {"metric": "fixture-paid-conversion", "unit": "ratio", "value": 0}
        ]

    def validated_without_observation(d, o, r):
        r["verdict"] = "VALIDATED"

    def validated_on_failed_quality(d, o, r):
        d["decisionState"] = "HOLD"
        d["qualityEvidence"] = {"status": "FAIL", "releaseRecordSha256": None}
        _observed(o)
        r["verdict"] = "VALIDATED"

    def challenged_without_defect_route(d, o, r):
        d["decisionState"] = "HOLD"
        d["qualityEvidence"] = {"status": "FAIL", "releaseRecordSha256": None}
        r["verdict"] = "CHALLENGED"

    def launch_without_quality(d, o, r):
        d["qualityEvidence"] = {"status": "NOT_EVALUATED", "releaseRecordSha256": None}

    def outcome_before_decision(d, o, r):
        o["observationPeriod"] = {
            "start": "2026-09-30T00:00:00Z",
            "end": "2026-10-05T00:00:00Z",
        }

    def personal_data(d, o, r):
        o["provenance"] = {
            "source": "fixture",
            "reference": "buyer contact list",
            "buyerEmail": "x@example.com",
        }

    return [
        case("decision rewritten without rebinding", rewritten, rebind=False),
        case("outcome from a different revision", revision_mismatch),
        case("missing outcome recorded as zero", not_observed_as_zero),
        case("validated without observed outcome", validated_without_observation),
        case("value promoted over failed quality", validated_on_failed_quality),
        case(
            "challenged failed quality without issue-190 route",
            challenged_without_defect_route,
        ),
        case("launch without passing quality", launch_without_quality),
        case("outcome observed before decision", outcome_before_decision),
        case("personal data in provenance", personal_data),
    ]


def _load_fixture_chain(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base = root / FIXTURE_DIR
    names = ("decision", "outcome", "retrospective")
    records = []
    for name in names:
        value = json.loads((base / f"{name}.json").read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError(f"{name} fixture must be a JSON object")
        records.append(value)
    return records[0], records[1], records[2]


def audit(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    try:
        decision, outcome, retrospective = _load_fixture_chain(root)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "passed": False,
            "errors": [f"fixture chain unreadable: {exc}"],
        }

    errors += validate_chain(decision, outcome, retrospective)

    unexpectedly_accepted: list[str] = []
    cases = _negative_cases(decision, outcome, retrospective)
    for name, d, o, r in cases:
        if not validate_chain(d, o, r):
            unexpectedly_accepted.append(name)
    errors += [f"negative case accepted: {name}" for name in unexpectedly_accepted]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "passed": not errors,
        "fixtureChain": FIXTURE_DIR.as_posix(),
        "decisionId": decision.get("decisionId"),
        "decisionState": decision.get("decisionState"),
        "outcomeAvailability": outcome.get("availability"),
        "retrospectiveVerdict": retrospective.get("verdict"),
        "negativeCaseCount": len(cases),
        "rejectedNegativeCaseCount": len(cases) - len(unexpectedly_accepted),
        "errors": errors,
        "warnings": [],
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
