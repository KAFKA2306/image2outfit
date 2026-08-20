#!/usr/bin/env python3
"""Run the existing review console with improvement-loop evidence projected into it."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit import improvement  # noqa: E402
import review_console  # noqa: E402

_ORIGINAL_COLLECT_PRODUCT = review_console.collect_product


def collect_product_with_improvement(
    root: Path,
    workspace: Path,
    output_dir: Path,
    required_views: list[str],
    required_poses: list[str],
) -> review_console.Product:
    product = _ORIGINAL_COLLECT_PRODUCT(
        root,
        workspace,
        output_dir,
        required_views,
        required_poses,
    )
    projection = improvement.review_projection(root, workspace.name)
    if projection["status"] == "NOT_RUN" and projection["iterationCount"] == 0:
        return product

    blockers = list(product.blockers)
    next_action = str(projection.get("nextAction") or "NOT_RUN")
    capability = str(projection.get("missingCapability") or "unknown")
    selected = str(projection.get("selectedMethod") or "none")
    if next_action not in {"NONE", "NOT_RUN"}:
        blockers.append(
            {
                "severity": "IMPROVEMENT",
                "message": (
                    f"{capability} · {next_action}"
                    + (f" · {selected}" if selected != "none" else "")
                ),
            }
        )

    gates = list(product.gates)
    gates.append(
        review_console.Gate(
            name="improvement:next-action",
            status="PASS" if next_action in {"NONE", "NOT_RUN"} else "PENDING",
            detail=f"{capability}; selected={selected}",
            href=None,
        )
    )
    last_decision = projection.get("lastDecision")
    if last_decision:
        gates.append(
            review_console.Gate(
                name="improvement:last-decision",
                status="PASS" if last_decision == "ADOPT" else str(last_decision),
                detail=f"iterations={projection['iterationCount']}",
                href=None,
            )
        )

    evidence = list(product.evidence)
    for label, path_text in (
        ("Improvement plan", projection.get("planPath")),
        ("Improvement iteration", projection.get("lastRecord")),
    ):
        if not path_text:
            continue
        target = root / str(path_text)
        evidence.append(
            review_console.Evidence(
                label=label,
                status="PASS" if target.is_file() else "MISSING",
                href=(
                    review_console.relative_href(target, output_dir)
                    if target.is_file()
                    else None
                ),
                sha256=review_console.digest(target) if target.is_file() else None,
            )
        )

    return replace(
        product,
        blocker_count=len(blockers),
        blockers=blockers,
        resume_point=(
            next_action
            if next_action not in {"NONE", "NOT_RUN"}
            else product.resume_point
        ),
        gates=gates,
        evidence=evidence,
    )


def main() -> int:
    review_console.collect_product = collect_product_with_improvement
    return review_console.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
