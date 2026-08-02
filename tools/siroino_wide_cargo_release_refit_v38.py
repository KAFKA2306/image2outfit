#!/usr/bin/env python3
"""Final reviewed v37 geometry with the calibrated edge-span guard."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v37 as v37

build = v37.build
base = v37.base


def audit() -> dict[str, object]:
    report = v37.audit()
    checks = report["checks"]
    metrics = checks["metrics"]
    checks["spikeGuardPassed"] = (
        float(metrics["maximumEdgeLength"]) <= 0.155
        and float(metrics["maximumEdgeZSpan"]) <= 0.125
    )
    required = [
        "singleMeshObjectPassed",
        "finiteCoordinatesPassed",
        "topologyPassed",
        "sourceFaceIndependencePassed",
        "spikeGuardPassed",
        "uvPassed",
        "materialSeparationPassed",
        "shapeKeyIsolationPassed",
        "weightingPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "fittedSeatPassed",
        "innerThighCoveragePassed",
        "straightWideProfilePassed",
        "waistCoveragePassed",
        "frontCentreCoveragePassed",
        "rearCentreCoveragePassed",
        "continuousCentreLevelsPassed",
        "panelFreeTransitionPassed",
    ]
    report["passed"] = all(bool(checks[name]) for name in required)
    return report


def record(report: dict[str, object]) -> None:
    v37.record(report)
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["designRevision"] = "v38-reviewed-converged-crotch"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v38 final garment audit failed: {result}")
    raise SystemExit(0)
