"""Contracts for hypothesis trees under single-image ambiguity.

A single front image does not determine the back structure, pattern, seams,
material, or styling. Every candidate is kept as a hypothesis node with its own
prior, confidence, unknown fields, and artifact hashes. The search is bounded by
a beam, and a hypothesis is selected only when visual review passes. Otherwise
the comparison stays in the WORKING state instead of fixing one reading early.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from image2outfit.hypothesis_contracts import (
    _mapping,
    _sha256,
    _string,
    _unique_strings,
    stable_sha256,
)

FACETS = frozenset({"decomposition", "pattern", "seam", "material", "styling"})
EVIDENCE_KINDS = ("simulation", "render", "fit")
EVIDENCE_STATUSES = frozenset({"PASS", "FAIL", "NOT_ASSESSABLE"})
VISUAL_DECISIONS = frozenset({"PASS", "REVISE", "REJECT", "NOT_ASSESSABLE"})


def _unit_interval(value: object, *, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        raise ValueError(f"{label} must be a finite number in [0, 1]")
    return float(value)


def validate_hypothesis_tree(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
    expected_blueprint_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate hypothesis nodes, their parent links, and artifact hash separation."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("hypothesis tree schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("hypothesis tree product identity mismatch")
    blueprint_sha = _sha256(
        payload.get("blueprintSha256"), label="tree.blueprintSha256"
    )
    if (
        expected_blueprint_sha256 is not None
        and blueprint_sha != expected_blueprint_sha256
    ):
        raise ValueError("hypothesis tree blueprint hash mismatch")
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("hypothesis tree requires at least one node")

    nodes: dict[str, dict[str, Any]] = {}
    artifact_owner: dict[str, str] = {}
    for index, raw in enumerate(raw_nodes):
        item = _mapping(raw, label=f"nodes[{index}]")
        hypothesis_id = _string(
            item.get("hypothesisId"), label=f"nodes[{index}].hypothesisId"
        )
        if hypothesis_id in nodes:
            raise ValueError(f"duplicate hypothesisId: {hypothesis_id}")
        facet = item.get("facet")
        if facet not in FACETS:
            raise ValueError(f"nodes[{index}].facet is invalid")
        parent_id = item.get("parentId")
        if parent_id is not None:
            parent_id = _string(parent_id, label=f"nodes[{index}].parentId")
        artifacts = _mapping(item.get("artifacts"), label=f"nodes[{index}].artifacts")
        if not artifacts:
            raise ValueError(f"nodes[{index}].artifacts must not be empty")
        artifact_hashes: dict[str, str] = {}
        for kind in sorted(artifacts):
            _string(kind, label=f"nodes[{index}].artifacts kind")
            digest = _sha256(artifacts[kind], label=f"nodes[{index}].artifacts.{kind}")
            owner = artifact_owner.get(digest)
            if owner is not None and owner != hypothesis_id:
                raise ValueError(
                    f"artifact hash is shared by hypotheses {owner} and {hypothesis_id}"
                )
            artifact_owner[digest] = hypothesis_id
            artifact_hashes[kind] = digest
        nodes[hypothesis_id] = {
            "hypothesisId": hypothesis_id,
            "facet": facet,
            "parentId": parent_id,
            "prior": _unit_interval(item.get("prior"), label=f"nodes[{index}].prior"),
            "confidence": _unit_interval(
                item.get("confidence"), label=f"nodes[{index}].confidence"
            ),
            "observationRefs": _unique_strings(
                item.get("observationRefs", []),
                label=f"nodes[{index}].observationRefs",
            ),
            "unknownFields": _unique_strings(
                item.get("unknownFields", []),
                label=f"nodes[{index}].unknownFields",
            ),
            "artifacts": artifact_hashes,
        }

    for hypothesis_id, node in nodes.items():
        parent_id = node["parentId"]
        if parent_id is not None and parent_id not in nodes:
            raise ValueError(f"{hypothesis_id} references missing parent {parent_id}")
    for hypothesis_id in nodes:
        seen: set[str] = set()
        cursor: str | None = hypothesis_id
        while cursor is not None:
            if cursor in seen:
                raise ValueError("hypothesis tree contains a cycle")
            seen.add(cursor)
            cursor = nodes[cursor]["parentId"]

    facet_counts = {facet: 0 for facet in sorted(FACETS)}
    for node in nodes.values():
        facet_counts[str(node["facet"])] += 1
    return {
        "nodeCount": len(nodes),
        "facetCounts": facet_counts,
        "rootIds": sorted(
            hid for hid, node in nodes.items() if node["parentId"] is None
        ),
        "nodes": list(nodes.values()),
        "treeSha256": stable_sha256(payload),
        "isEvidence": False,
    }


def _beam_decisions(
    nodes: Sequence[Mapping[str, Any]], width: int
) -> dict[str, tuple[str, str | None]]:
    by_facet: dict[str, list[Mapping[str, Any]]] = {}
    for node in nodes:
        by_facet.setdefault(str(node["facet"]), []).append(node)
    decisions: dict[str, tuple[str, str | None]] = {}
    for items in by_facet.values():
        ranked = sorted(
            items,
            key=lambda n: (
                -float(n["prior"]),
                -float(n["confidence"]),
                str(n["hypothesisId"]),
            ),
        )
        for rank, node in enumerate(ranked, start=1):
            if rank <= width:
                decisions[str(node["hypothesisId"])] = ("KEPT", None)
            else:
                decisions[str(node["hypothesisId"])] = (
                    "PRUNED",
                    f"beam-rank-{rank}-exceeds-width-{width}",
                )
    parents = {str(node["hypothesisId"]): node["parentId"] for node in nodes}
    changed = True
    while changed:
        changed = False
        for hypothesis_id, parent_id in parents.items():
            if (
                decisions[hypothesis_id][0] == "KEPT"
                and parent_id is not None
                and decisions[str(parent_id)][0] == "PRUNED"
            ):
                decisions[hypothesis_id] = ("PRUNED", f"parent-pruned:{parent_id}")
                changed = True
    return decisions


def _combination_count(
    nodes: Sequence[Mapping[str, Any]], decisions: Mapping[str, tuple[str, str | None]]
) -> int:
    kept_by_facet: dict[str, int] = {}
    for node in nodes:
        if decisions[str(node["hypothesisId"])][0] == "KEPT":
            facet = str(node["facet"])
            kept_by_facet[facet] = kept_by_facet.get(facet, 0) + 1
    return math.prod(kept_by_facet.values())


def plan_beam(
    nodes: Sequence[Mapping[str, Any]],
    *,
    beam_width: int,
    max_combinations: int,
) -> dict[str, Any]:
    """Keep the top prior-ranked hypotheses per facet within a combination budget.

    Nodes whose parent is pruned are pruned as well. The width is reduced
    deterministically until the product of kept counts per facet fits the budget.
    At width 1 each facet keeps at most one node, so the product is at most 1 and
    any positive budget is met.
    """
    for label, value in (
        ("beam_width", beam_width),
        ("max_combinations", max_combinations),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{label} must be a positive integer")

    width = beam_width
    decisions = _beam_decisions(nodes, width)
    combinations = _combination_count(nodes, decisions)
    while combinations > max_combinations:
        width -= 1
        decisions = _beam_decisions(nodes, width)
        combinations = _combination_count(nodes, decisions)

    summary = {
        "beamWidth": width,
        "maxCombinations": max_combinations,
        "combinationCount": combinations,
        "kept": sorted(hid for hid, (state, _) in decisions.items() if state == "KEPT"),
        "pruned": {
            hid: reason
            for hid, (state, reason) in sorted(decisions.items())
            if state == "PRUNED" and reason is not None
        },
    }
    return {**summary, "planSha256": stable_sha256(summary)}


def _score_mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _evaluate_candidate(
    node: Mapping[str, Any], evaluation: Mapping[str, Any] | None
) -> dict[str, Any]:
    hypothesis_id = str(node["hypothesisId"])
    evidence = _mapping(
        (evaluation or {}).get("evidence", {}), label=f"{hypothesis_id}.evidence"
    )
    reject_reasons: list[str] = []
    scores: list[float] = []
    for kind in EVIDENCE_KINDS:
        entry = _mapping(
            evidence.get(kind, {"status": "NOT_ASSESSABLE"}),
            label=f"{hypothesis_id}.evidence.{kind}",
        )
        status = entry.get("status")
        if status not in EVIDENCE_STATUSES:
            raise ValueError(f"{hypothesis_id}.evidence.{kind}.status is invalid")
        if status == "FAIL":
            reject_reasons.append(f"{kind}:FAIL")
        if entry.get("score") is not None:
            scores.append(
                _unit_interval(entry["score"], label=f"{hypothesis_id}.{kind}.score")
            )
    visual_entry = _mapping(
        evidence.get("visualReview", {"decision": "NOT_ASSESSABLE"}),
        label=f"{hypothesis_id}.evidence.visualReview",
    )
    decision = visual_entry.get("decision")
    if decision not in VISUAL_DECISIONS:
        raise ValueError(f"{hypothesis_id}.evidence.visualReview.decision is invalid")
    if decision == "REJECT":
        reject_reasons.append("visualReview:REJECT")

    if reject_reasons:
        status = "REJECTED"
        reasons = reject_reasons
    elif decision != "PASS":
        status = "UNVERIFIED"
        reasons = [f"visual-review-not-pass:{decision}"]
    else:
        status = "PASSED"
        reasons = []
    return {
        "hypothesisId": hypothesis_id,
        "status": status,
        "score": _score_mean(scores),
        "reasons": reasons,
        "unknownFields": list(node["unknownFields"]),
        "artifactSha256": sorted(node["artifacts"].values()),
    }


def compare_facet(
    nodes: Sequence[Mapping[str, Any]],
    evaluations: Sequence[Mapping[str, Any]],
    *,
    facet: str,
    min_candidates: int = 3,
    min_score_margin: float = 0.05,
) -> dict[str, Any]:
    """Compare the hypotheses of one facet using evidence and visual review.

    A hypothesis is selected only when it passed visual review and no evidence
    failed. A higher score alone never replaces visual review. Missing evidence,
    ties, and scores within the margin keep the state at WORKING, and the reasons
    for every rejection are recorded.
    """
    if facet not in FACETS:
        raise ValueError("comparison facet is invalid")
    if (
        isinstance(min_candidates, bool)
        or not isinstance(min_candidates, int)
        or min_candidates < 1
    ):
        raise ValueError("min_candidates must be a positive integer")
    margin = _unit_interval(min_score_margin, label="min_score_margin")

    candidates = [node for node in nodes if node["facet"] == facet]
    if len(candidates) < min_candidates:
        raise ValueError(
            f"facet {facet} needs at least {min_candidates} comparable hypotheses"
        )
    candidate_ids = {str(node["hypothesisId"]) for node in candidates}

    evaluation_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(evaluations):
        item = _mapping(raw, label=f"evaluations[{index}]")
        hypothesis_id = _string(
            item.get("hypothesisId"), label=f"evaluations[{index}].hypothesisId"
        )
        if hypothesis_id not in candidate_ids:
            raise ValueError(
                f"evaluation references unknown {facet} hypothesis {hypothesis_id}"
            )
        if hypothesis_id in evaluation_by_id:
            raise ValueError(f"duplicate evaluation for {hypothesis_id}")
        evaluation_by_id[hypothesis_id] = item

    results = sorted(
        (
            _evaluate_candidate(node, evaluation_by_id.get(str(node["hypothesisId"])))
            for node in candidates
        ),
        key=lambda r: r["hypothesisId"],
    )
    passed = sorted(
        (r for r in results if r["status"] == "PASSED"),
        key=lambda r: (
            -(r["score"] if r["score"] is not None else -1.0),
            r["hypothesisId"],
        ),
    )
    if not passed:
        state, selected, reason = (
            "WORKING",
            None,
            "no hypothesis has visual-review PASS",
        )
    elif len(passed) == 1:
        state, selected, reason = (
            "SELECTED",
            passed[0]["hypothesisId"],
            "only visual-review PASS",
        )
    else:
        top, second = passed[0], passed[1]
        if top["score"] is None or second["score"] is None:
            state, selected, reason = (
                "WORKING",
                None,
                "multiple PASS without numeric scores",
            )
        elif top["score"] - second["score"] < margin:
            state, selected, reason = "WORKING", None, "top scores within margin"
        else:
            state, selected, reason = (
                "SELECTED",
                top["hypothesisId"],
                "visual-review PASS with clear score lead",
            )

    unresolved = sorted(
        {field for result in results for field in result["unknownFields"]}
    )
    rejected = {
        r["hypothesisId"]: r["reasons"] for r in results if r["status"] == "REJECTED"
    }
    summary = {
        "facet": facet,
        "state": state,
        "selectedHypothesisId": selected,
        "selectionReason": reason,
        "candidateCount": len(candidates),
        "candidates": results,
        "rejectedReasons": rejected,
        "unresolvedUnknownFields": unresolved,
        "minScoreMargin": margin,
        "bestScoreReplacesVisualReview": False,
    }
    return {**summary, "comparisonSha256": stable_sha256(summary)}
