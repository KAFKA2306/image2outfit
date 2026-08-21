"""Fixed research fixtures and direct baseline-versus-candidate adoption rules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class MetricDirection(StrEnum):
    LOWER_IS_BETTER = "lower-is-better"
    HIGHER_IS_BETTER = "higher-is-better"


class AdoptionStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class ResearchFixture:
    fixture_id: str
    description: str
    required_stages: tuple[str, ...]
    required_metric_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkMetric:
    metric_id: str
    value: float
    direction: MetricDirection = MetricDirection.LOWER_IS_BETTER
    tolerance: float = 0.0

    def __post_init__(self) -> None:
        if not self.metric_id.strip():
            raise ValueError("benchmark metric_id is required")
        if not math.isfinite(self.value):
            raise ValueError("benchmark metric value must be finite")
        if not math.isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("benchmark metric tolerance must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    fixture_id: str
    method_id: str
    metrics: tuple[BenchmarkMetric, ...]
    reproducible: bool

    def __post_init__(self) -> None:
        if not self.fixture_id.strip() or not self.method_id.strip():
            raise ValueError("benchmark run identity fields are required")
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("benchmark metric IDs must be unique")

    @property
    def metric_map(self) -> dict[str, BenchmarkMetric]:
        return {metric.metric_id: metric for metric in self.metrics}


@dataclass(frozen=True, slots=True)
class BenchmarkDecision:
    status: AdoptionStatus
    improved_metric_ids: tuple[str, ...]
    regressed_metric_ids: tuple[str, ...]
    reasons: tuple[str, ...]


DIRECT_METRIC_IDS = (
    "pattern-geometry-defects",
    "seam-mismatch-ratio",
    "silhouette-error",
    "body-penetration-count",
    "self-intersection-count",
    "inter-layer-intersection-count",
    "stage-runtime-seconds",
    "manual-intervention-count",
)

CANONICAL_RESEARCH_FIXTURES = (
    ResearchFixture(
        fixture_id="tight-fitted-top",
        description="Tight or fitted upper-body garment with fit-sensitive seams.",
        required_stages=("draft-patterns", "infer-stitches", "simulate-cloth"),
        required_metric_ids=DIRECT_METRIC_IDS,
    ),
    ResearchFixture(
        fixture_id="loose-pleated-skirt",
        description="Loose or pleated lower-body garment with dynamic cloth behavior.",
        required_stages=("draft-patterns", "infer-stitches", "simulate-cloth"),
        required_metric_ids=DIRECT_METRIC_IDS,
    ),
    ResearchFixture(
        fixture_id="layered-outfit-with-trim",
        description="Layered garment with trim and explicit inter-layer collision risk.",
        required_stages=("draft-patterns", "infer-stitches", "simulate-cloth"),
        required_metric_ids=DIRECT_METRIC_IDS,
    ),
)


def fixture_by_id(fixture_id: str) -> ResearchFixture:
    for fixture in CANONICAL_RESEARCH_FIXTURES:
        if fixture.fixture_id == fixture_id:
            return fixture
    raise KeyError(f"unknown research fixture: {fixture_id}")


def compare_benchmark_runs(
    baseline: BenchmarkRun,
    candidate: BenchmarkRun,
) -> BenchmarkDecision:
    """Decide whether a candidate can replace a baseline on one fixed fixture.

    Adoption is deliberately strict: both runs must cover the fixture's direct metrics,
    directions must agree, the candidate must be reproducible, no metric may regress
    beyond its declared tolerance, and at least one direct metric must improve.
    """

    if baseline.fixture_id != candidate.fixture_id:
        raise ValueError("benchmark runs must use the same fixed fixture")

    fixture = fixture_by_id(baseline.fixture_id)
    baseline_metrics = baseline.metric_map
    candidate_metrics = candidate.metric_map
    missing = tuple(
        metric_id
        for metric_id in fixture.required_metric_ids
        if metric_id not in baseline_metrics or metric_id not in candidate_metrics
    )
    if missing:
        return BenchmarkDecision(
            status=AdoptionStatus.INCOMPLETE,
            improved_metric_ids=(),
            regressed_metric_ids=(),
            reasons=(f"missing required metrics: {', '.join(missing)}",),
        )

    improved: list[str] = []
    regressed: list[str] = []
    for metric_id in fixture.required_metric_ids:
        baseline_metric = baseline_metrics[metric_id]
        candidate_metric = candidate_metrics[metric_id]
        if baseline_metric.direction != candidate_metric.direction:
            raise ValueError(f"metric direction mismatch for {metric_id}")
        tolerance = max(baseline_metric.tolerance, candidate_metric.tolerance)
        delta = candidate_metric.value - baseline_metric.value
        if candidate_metric.direction is MetricDirection.LOWER_IS_BETTER:
            if delta < -tolerance:
                improved.append(metric_id)
            elif delta > tolerance:
                regressed.append(metric_id)
        else:
            if delta > tolerance:
                improved.append(metric_id)
            elif delta < -tolerance:
                regressed.append(metric_id)

    reasons: list[str] = []
    if not candidate.reproducible:
        reasons.append("candidate is not reproducible")
    if regressed:
        reasons.append("required direct metrics regressed")
    if not improved:
        reasons.append("no required direct metric improved")

    status = AdoptionStatus.ACCEPTED if not reasons else AdoptionStatus.REJECTED
    return BenchmarkDecision(
        status=status,
        improved_metric_ids=tuple(improved),
        regressed_metric_ids=tuple(regressed),
        reasons=tuple(reasons),
    )
