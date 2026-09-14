#!/usr/bin/env python3
"""Canonical structural and stage-order validation for pipeline profile v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contract_io import validate_schema_file
from image2outfit.pipeline import PIPELINE_STAGES

ROOT = Path(__file__).resolve().parents[1]
PROFILE_SCHEMA = ROOT / "config/pipeline/pipeline-profile.schema.v1.json"


def _valid_evidence_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def load_profile(path: Path) -> dict[str, Any]:
    """Load a profile through structural schema validation, then semantic checks."""
    profile = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_schema_file(profile, PROFILE_SCHEMA, "pipeline profile")
    if errors:
        raise ValueError("invalid pipeline profile: " + "; ".join(errors))

    declared = profile["stages"]
    names = [item["stage"] for item in declared]
    expected = [stage.value for stage in PIPELINE_STAGES]
    if names != expected:
        raise ValueError("pipeline profile stages do not match the canonical order")

    for item in declared:
        if not _valid_evidence_count(item["minimumEvidenceCount"]):
            raise ValueError(
                f"stage {item['stage']!r} minimumEvidenceCount must be a non-negative integer"
            )
        if "tools" not in item and "toolName" not in item:
            raise ValueError(f"stage {item['stage']!r} must declare toolName or tools")
        if "tools" in item:
            tool_names = [tool["toolName"] for tool in item["tools"]]
            if len(tool_names) != len(set(tool_names)):
                raise ValueError(f"stage {item['stage']!r} declares duplicate tool names")
            for tool in item["tools"]:
                count = tool.get("minimumEvidenceCount", item["minimumEvidenceCount"])
                if not _valid_evidence_count(count):
                    raise ValueError(
                        f"tool {tool['toolName']!r} minimumEvidenceCount must be a non-negative integer"
                    )
    return profile
