"""Canonical knowledge records for fabric promotion, defects, and trials.

The records here reference existing canonical evidence by repository-relative
path and SHA-256. They never become a second source of truth for product state,
and a record without an open license, a measured calibration, or a verifiable
tracking link cannot be promoted to a production preset.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from image2outfit.material import CalibrationStatus, MaterialSpec, load_material_library

SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

PROMOTABLE_LICENSES = frozenset(
    {"CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "MIT", "Apache-2.0"}
)
PROMOTABLE_CALIBRATIONS = frozenset(
    {CalibrationStatus.MEASURED, CalibrationStatus.MEASURED_AND_CONVERTED}
)

DEFECT_SEVERITIES = frozenset({"blocker", "major", "minor"})
DEFECT_SOURCE_KINDS = frozenset(
    {"customer-feedback", "human-review", "internal-audit", "fixture"}
)
TRIAL_DECISIONS = frozenset({"accepted", "rejected"})
# Feedback must stay traceable to an existing correction issue or trial.
SOURCE_KINDS_REQUIRING_TRACKING = frozenset({"customer-feedback", "human-review"})


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.path or self.path.startswith(("/", "..")) or "\\" in self.path:
            raise ValueError("evidence path must be a repository-relative POSIX path")
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError(f"evidence sha256 is malformed for {self.path}")


@dataclass(frozen=True, slots=True)
class DefectCase:
    defect_id: str
    product_slug: str
    revision: str
    category: str
    severity: str
    source_kind: str
    summary: str
    evidence: tuple[EvidenceRef, ...]
    tracking_ref: str | None = None
    fixture: bool = False

    def __post_init__(self) -> None:
        _require_text(
            {
                "defect_id": self.defect_id,
                "revision": self.revision,
                "category": self.category,
                "summary": self.summary,
            }
        )
        _require_slug(self.product_slug)
        if self.severity not in DEFECT_SEVERITIES:
            raise ValueError(f"unknown defect severity: {self.severity}")
        if self.source_kind not in DEFECT_SOURCE_KINDS:
            raise ValueError(f"unknown defect source_kind: {self.source_kind}")
        if (
            self.source_kind in SOURCE_KINDS_REQUIRING_TRACKING
            and not self.tracking_ref
        ):
            raise ValueError(
                f"{self.source_kind} defect {self.defect_id} needs a tracking_ref"
            )
        if self.source_kind == "fixture" and not self.fixture:
            raise ValueError("fixture source_kind must set fixture=true")
        if not self.evidence:
            raise ValueError(f"defect {self.defect_id} needs evidence")


@dataclass(frozen=True, slots=True)
class TrialRecord:
    trial_id: str
    product_slug: str
    revision: str
    change: str
    decision: str
    applies_when: tuple[str, ...]
    not_applicable_when: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    material_ids: tuple[str, ...] = ()
    rejection_reason: str | None = None
    fixture: bool = False

    def __post_init__(self) -> None:
        _require_text(
            {
                "trial_id": self.trial_id,
                "revision": self.revision,
                "change": self.change,
            }
        )
        _require_slug(self.product_slug)
        if self.decision not in TRIAL_DECISIONS:
            raise ValueError(f"unknown trial decision: {self.decision}")
        if not self.applies_when:
            raise ValueError(f"trial {self.trial_id} must state applies_when")
        if not self.not_applicable_when:
            raise ValueError(f"trial {self.trial_id} must state not_applicable_when")
        if self.decision == "rejected" and not (self.rejection_reason or "").strip():
            raise ValueError(f"rejected trial {self.trial_id} needs a rejection_reason")
        if self.decision == "accepted" and self.rejection_reason:
            raise ValueError(f"accepted trial {self.trial_id} must not carry a reason")
        if not self.evidence:
            raise ValueError(f"trial {self.trial_id} needs evidence")


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    fabric_library_path: str
    defects: tuple[DefectCase, ...] = field(default_factory=tuple)
    trials: tuple[TrialRecord, ...] = field(default_factory=tuple)

    def production_defects(self) -> tuple[DefectCase, ...]:
        return tuple(item for item in self.defects if not item.fixture)

    def production_trials(self) -> tuple[TrialRecord, ...]:
        return tuple(item for item in self.trials if not item.fixture)


def fabric_promotion_blockers(spec: MaterialSpec) -> tuple[str, ...]:
    """Return why a fabric preset must not be promoted to production (empty if promotable)."""
    blockers: list[str] = []
    if spec.source_license not in PROMOTABLE_LICENSES:
        blockers.append(f"license-not-promotable:{spec.source_license}")
    if spec.calibration_status not in PROMOTABLE_CALIBRATIONS:
        blockers.append(f"calibration-not-measured:{spec.calibration_status.value}")
    if not spec.source_url.startswith("https://"):
        blockers.append("source-url-not-https")
    if not spec.solver_mappings:
        blockers.append("no-solver-mapping")
    return tuple(blockers)


def promotable_fabric_ids(materials: tuple[MaterialSpec, ...]) -> tuple[str, ...]:
    return tuple(
        item.material_id for item in materials if not fabric_promotion_blockers(item)
    )


def defect_from_feedback(record: Mapping[str, Any]) -> DefectCase:
    """Convert one raw customer or human-review feedback mapping into a DefectCase.

    The feedback must already name the revision it observed and an existing
    tracking reference; a feedback without that link is rejected rather than
    recorded as an untraceable defect.
    """
    source_kind = str(record.get("sourceKind", ""))
    if source_kind not in SOURCE_KINDS_REQUIRING_TRACKING:
        raise ValueError(
            "feedback sourceKind must be customer-feedback or human-review"
        )
    return DefectCase(
        defect_id=str(record["feedbackId"]),
        product_slug=str(record["productSlug"]),
        revision=str(record["revision"]),
        category=str(record["category"]),
        severity=str(record["severity"]),
        source_kind=source_kind,
        summary=str(record["summary"]),
        evidence=tuple(_evidence(item) for item in record.get("evidence", [])),
        tracking_ref=_optional_text(record.get("trackingRef")),
        fixture=bool(record.get("fixture", False)),
    )


def recurrence_summary(defects: tuple[DefectCase, ...]) -> dict[str, dict[str, Any]]:
    """Count defect categories across products and revisions, sorted for determinism."""
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "products": set(), "revisions": set()}
    )
    for item in defects:
        entry = grouped[item.category]
        entry["count"] += 1
        entry["products"].add(item.product_slug)
        entry["revisions"].add(item.revision)
    return {
        category: {
            "count": value["count"],
            "products": sorted(value["products"]),
            "revisions": sorted(value["revisions"]),
        }
        for category, value in sorted(grouped.items())
    }


def recurring_categories(
    defects: tuple[DefectCase, ...], *, min_products: int = 2
) -> tuple[str, ...]:
    summary = recurrence_summary(defects)
    return tuple(
        category
        for category, value in summary.items()
        if len(value["products"]) >= min_products
    )


def verify_evidence(knowledge: KnowledgeBase, root: Path) -> None:
    """Check each referenced evidence file exists and its SHA-256 still matches."""
    refs: list[EvidenceRef] = []
    for defect in knowledge.defects:
        refs.extend(defect.evidence)
    for trial in knowledge.trials:
        refs.extend(trial.evidence)
    for ref in refs:
        path = root / ref.path
        if not path.is_file():
            raise FileNotFoundError(f"evidence file is missing: {ref.path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != ref.sha256:
            raise ValueError(f"evidence hash mismatch: {ref.path}")


def load_knowledge_base(path: str | Path) -> KnowledgeBase:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported knowledge base schemaVersion")
    fabric_library_path = str(payload["fabricLibrary"])
    defects = tuple(_defect(item) for item in payload.get("defects", []))
    trials = tuple(_trial(item) for item in payload.get("trials", []))
    ids = [item.defect_id for item in defects] + [item.trial_id for item in trials]
    if len(ids) != len(set(ids)):
        raise ValueError("knowledge base record IDs must be unique")
    return KnowledgeBase(
        fabric_library_path=fabric_library_path,
        defects=defects,
        trials=trials,
    )


def check_material_references(
    knowledge: KnowledgeBase, materials: tuple[MaterialSpec, ...]
) -> None:
    known = {item.material_id for item in materials}
    for trial in knowledge.trials:
        missing = sorted(set(trial.material_ids) - known)
        if missing:
            raise ValueError(
                f"trial {trial.trial_id} references unknown materials: {missing}"
            )


def load_fabric_library_for(
    knowledge: KnowledgeBase, root: Path
) -> tuple[MaterialSpec, ...]:
    return load_material_library(root / knowledge.fabric_library_path)


def _defect(item: Mapping[str, Any]) -> DefectCase:
    return DefectCase(
        defect_id=str(item["defectId"]),
        product_slug=str(item["productSlug"]),
        revision=str(item["revision"]),
        category=str(item["category"]),
        severity=str(item["severity"]),
        source_kind=str(item["sourceKind"]),
        summary=str(item["summary"]),
        evidence=tuple(_evidence(ev) for ev in item["evidence"]),
        tracking_ref=_optional_text(item.get("trackingRef")),
        fixture=bool(item.get("fixture", False)),
    )


def _trial(item: Mapping[str, Any]) -> TrialRecord:
    return TrialRecord(
        trial_id=str(item["trialId"]),
        product_slug=str(item["productSlug"]),
        revision=str(item["revision"]),
        change=str(item["change"]),
        decision=str(item["decision"]),
        applies_when=tuple(str(v) for v in item["appliesWhen"]),
        not_applicable_when=tuple(str(v) for v in item["notApplicableWhen"]),
        evidence=tuple(_evidence(ev) for ev in item["evidence"]),
        material_ids=tuple(str(v) for v in item.get("materialIds", [])),
        rejection_reason=_optional_text(item.get("rejectionReason")),
        fixture=bool(item.get("fixture", False)),
    )


def _evidence(item: Mapping[str, Any]) -> EvidenceRef:
    return EvidenceRef(path=str(item["path"]), sha256=str(item["sha256"]))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_text(values: Mapping[str, str]) -> None:
    for label, value in values.items():
        if not value or not value.strip():
            raise ValueError(f"{label} is required")


def _require_slug(value: str) -> None:
    if not SLUG_PATTERN.fullmatch(value):
        raise ValueError(f"product_slug must be a lowercase slug: {value!r}")
