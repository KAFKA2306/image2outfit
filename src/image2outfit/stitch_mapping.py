"""Canonical endpoint correspondence for paired garment seam edges."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ENDPOINT_MAPPINGS = frozenset({"start-to-start", "start-to-end"})


def resolve_endpoint_mapping(stitch: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve endpoint pairing separately from the flat-edge direction audit.

    Older stitch graphs did not carry an endpointMapping field. Keep their
    historical export behavior: same-directed edges pair start-to-start,
    reversed edges pair start-to-end, and not-applicable edges use
    GarmentCode BoxMesh's default start-to-end pairing.
    """
    if "endpointMapping" in stitch:
        mapping = stitch.get("endpointMapping")
        if not isinstance(mapping, str) or mapping not in ENDPOINT_MAPPINGS:
            raise ValueError(
                "endpointMapping must be start-to-start or start-to-end"
            )
        return str(mapping), "explicit"

    direction = stitch.get("direction")
    if direction == "same":
        return "start-to-start", "legacy-direction"
    if direction == "reversed":
        return "start-to-end", "legacy-direction"
    if direction == "not-applicable":
        return "start-to-end", "garmentcode-default"
    raise ValueError(
        "a stitch without endpointMapping requires a valid legacy direction"
    )
