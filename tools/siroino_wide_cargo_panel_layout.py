#!/usr/bin/env python3
"""Pattern-driven Wide Cargo panel layout for the generic sewn-panel builder.

This module reads the canonical Wide Cargo pattern source, validates its seam
and boundary contract, and maps the baseline rows to typed sections. Vertex and
face construction is delegated to ``garment_panel_builder``. It has no Blender
dependency so it can be verified without a Blender runtime.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from garment_panel_builder import (  # noqa: E402
    CentreInner,
    FanPanel,
    MeshBuilder,
    PanelBuildError,
    SewnGarmentBuilder,
    SewnSection,
    SideInner,
    interpolate_width,
    profile_value,
)

ROOT = Path(__file__).resolve().parents[1]
PATTERN_SPEC_PATH = (
    ROOT / "Assets/GenWorks/siroino-wide-cargo/Source/Patterns/pattern-spec.json"
)
PRODUCT_ID = "siroino-wide-cargo"
PANEL_SAMPLES = 17

# Side pocket component parameters, in metres. Both sides use the same outline.
POCKET_PANELS: tuple[FanPanel, ...] = (
    FanPanel(
        x_base=0.1815,
        y_half=0.032,
        z_min=0.475,
        z_max=0.555,
        corner_radius=0.012,
    ),
)
POCKET_SIDES: tuple[float, ...] = (-1.0, 1.0)


def _numeric_rows(
    value: object, width: int, label: str
) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Wide Cargo pattern data has no {label}")
    rows = []
    for row in value:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError(f"Wide Cargo pattern data has invalid {label} row: {row}")
        if not all(isinstance(item, (int, float)) for item in row):
            raise ValueError(
                f"Wide Cargo pattern data has non-numeric {label} row: {row}"
            )
        rows.append(tuple(float(item) for item in row))
    return tuple(rows)


def _pattern_reference(
    value: object,
    panel_boundaries: dict[str, set[str]],
    label: str,
) -> str:
    if not isinstance(value, str) or value.count(":") != 1:
        raise ValueError(f"Wide Cargo pattern data has invalid {label}: {value}")
    panel_id, boundary = value.split(":", 1)
    if panel_id not in panel_boundaries:
        raise ValueError(f"Wide Cargo {label} references unknown panel: {value}")
    if boundary not in panel_boundaries[panel_id]:
        raise ValueError(f"Wide Cargo {label} references unknown boundary: {value}")
    return value


def _validate_pattern_connectivity(document: dict[str, object]) -> None:
    acceptance = document.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("Wide Cargo pattern source has no acceptance contract")

    panels = document.get("panels")
    if not isinstance(panels, list):
        raise ValueError("Wide Cargo pattern source has no panels")
    panel_count = acceptance.get("panelCount")
    if not isinstance(panel_count, int) or len(panels) != panel_count:
        raise ValueError("Wide Cargo panel count does not match acceptance contract")

    panel_boundaries: dict[str, set[str]] = {}
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError(f"Wide Cargo pattern data has invalid panel: {panel}")
        panel_id = panel.get("id")
        boundaries = panel.get("boundaries")
        if not isinstance(panel_id, str) or not panel_id:
            raise ValueError(
                f"Wide Cargo pattern data has invalid panel id: {panel_id}"
            )
        if panel_id in panel_boundaries:
            raise ValueError(
                f"Wide Cargo pattern data has duplicate panel id: {panel_id}"
            )
        if (
            not isinstance(boundaries, list)
            or not boundaries
            or not all(
                isinstance(boundary, str) and boundary for boundary in boundaries
            )
            or len(set(boundaries)) != len(boundaries)
        ):
            raise ValueError(f"Wide Cargo panel has invalid boundaries: {panel_id}")
        panel_boundaries[panel_id] = set(boundaries)

    seam_pairs = document.get("seamPairs")
    if not isinstance(seam_pairs, list):
        raise ValueError("Wide Cargo pattern source has no seamPairs")
    seam_pair_count = acceptance.get("seamPairCount")
    if not isinstance(seam_pair_count, int) or len(seam_pairs) != seam_pair_count:
        raise ValueError(
            "Wide Cargo seam pair count does not match acceptance contract"
        )

    seam_references: set[str] = set()
    for pair in seam_pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"Wide Cargo pattern data has invalid seam pair: {pair}")
        first = _pattern_reference(pair[0], panel_boundaries, "seam")
        second = _pattern_reference(pair[1], panel_boundaries, "seam")
        if first == second:
            raise ValueError(f"Wide Cargo seam cannot reference itself: {first}")
        for reference in (first, second):
            if reference in seam_references:
                raise ValueError(
                    f"Wide Cargo boundary appears in more than one seam: {reference}"
                )
            seam_references.add(reference)

    open_boundaries = document.get("openBoundaries")
    if not isinstance(open_boundaries, list):
        raise ValueError("Wide Cargo pattern source has no openBoundaries")
    open_references = {
        _pattern_reference(value, panel_boundaries, "open boundary")
        for value in open_boundaries
    }
    if len(open_references) != len(open_boundaries):
        raise ValueError("Wide Cargo pattern source has duplicate open boundaries")
    overlap = seam_references & open_references
    if overlap:
        raise ValueError(
            f"Wide Cargo boundaries cannot be both sewn and open: {sorted(overlap)}"
        )

    declared_references = {
        f"{panel_id}:{boundary}"
        for panel_id, boundaries in panel_boundaries.items()
        for boundary in boundaries
    }
    accounted_references = seam_references | open_references
    if declared_references != accounted_references:
        missing = sorted(declared_references - accounted_references)
        extra = sorted(accounted_references - declared_references)
        raise ValueError(
            "Wide Cargo pattern boundaries are not fully accounted for: "
            f"missing={missing}, extra={extra}"
        )

    if acceptance.get("allSeamReferencesMustExist") is not True:
        raise ValueError("Wide Cargo acceptance must require valid seam references")
    if acceptance.get("waistAndHemRemainOpen") is not True:
        raise ValueError("Wide Cargo acceptance must require open waist and hem")
    required_open = {
        f"{panel_id}:{boundary}"
        for panel_id, boundaries in panel_boundaries.items()
        for boundary in ("waist", "hem")
        if boundary in boundaries
    }
    if required_open != open_references:
        raise ValueError("Wide Cargo open boundaries must be exactly waist and hem")


def parse_pattern_baseline(document: dict[str, object]) -> dict[str, object]:
    """Validate a decoded Wide Cargo pattern source and return its baseline."""
    if document.get("productId") != PRODUCT_ID:
        raise ValueError("Wide Cargo pattern source has the wrong productId")
    if document.get("units") != "m":
        raise ValueError("Wide Cargo pattern source must use metres")
    source = document.get("source")
    if not isinstance(source, dict) or source.get("baselineDesignRevision") != (
        "v74-centre-crotch-seam"
    ):
        raise ValueError("Wide Cargo pattern source baseline revision is not v74")
    _validate_pattern_connectivity(document)
    baseline = document.get("baselineGeometry")
    if not isinstance(baseline, dict):
        raise ValueError("Wide Cargo pattern source has no baselineGeometry")
    back_rise = _numeric_rows(baseline.get("backRise"), 2, "backRise")
    front_rise = _numeric_rows(baseline.get("frontRise"), 2, "frontRise")
    if len(back_rise) != len(front_rise):
        raise ValueError("Wide Cargo frontRise and backRise point counts differ")
    if back_rise[-1] != front_rise[0]:
        raise ValueError("Wide Cargo frontRise and backRise do not share centre point")
    outseam = _numeric_rows(baseline.get("outseam"), 2, "outseam")
    inseam = _numeric_rows(baseline.get("inseam"), 2, "inseam")
    if len(outseam) != len(inseam):
        raise ValueError("Wide Cargo outseam and inseam point counts differ")
    leg_boundary_rows = []
    for outside, inside in zip(outseam, inseam):
        outer, outer_z = outside
        inner, inner_z = inside
        if outer_z != inner_z:
            raise ValueError("Wide Cargo outseam and inseam levels differ")
        if outer <= inner:
            raise ValueError("Wide Cargo outseam must stay outside inseam")
        leg_boundary_rows.append((outer_z, outer, inner))
    return {
        "frontDepthProfile": _numeric_rows(
            baseline.get("frontDepthProfile"), 2, "frontDepthProfile"
        ),
        "rearDepthProfile": _numeric_rows(
            baseline.get("rearDepthProfile"), 2, "rearDepthProfile"
        ),
        "legBoundaryRows": tuple(leg_boundary_rows),
        "upperRows": _numeric_rows(baseline.get("upperRows"), 2, "upperRows"),
        "backRise": back_rise,
        "frontRise": front_rise,
        "crotchCentre": back_rise + front_rise[1:],
    }


def load_pattern_baseline(path: Path = PATTERN_SPEC_PATH) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"Wide Cargo pattern source is missing: {path}")
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    return parse_pattern_baseline(document)


def build_wide_cargo_panels(
    mesh,
    baseline: dict[str, object],
    samples: int = PANEL_SAMPLES,
):
    """Build the four sewn trouser panels and side pockets into ``mesh``.

    ``baseline`` is the output of ``parse_pattern_baseline``. Every topology
    decision here is a row-selection rule; vertices and faces come from the
    generic builder.
    """
    front_profile = baseline["frontDepthProfile"]
    rear_profile = baseline["rearDepthProfile"]
    leg_rows = baseline["legBoundaryRows"]
    upper_rows = baseline["upperRows"]
    back_rise = baseline["backRise"]
    front_rise = baseline["frontRise"]

    builder = SewnGarmentBuilder(
        mesh,
        front_depth=front_profile,
        rear_depth=rear_profile,
        samples=samples,
    )

    # Below the crotch, front/back panels share the outseam and inseam exactly.
    # The last leg row is replaced by the rise construction below.
    for z, outer, inner in leg_rows[:-1]:
        builder.add_section(SewnSection(z=z, outer_x=outer, inner=SideInner(inner)))

    rise_start_z = front_rise[0][1]
    rise_end_z = front_rise[-1][1]
    lower_outer = leg_rows[-1][1]
    upper_width_at_end = profile_value(rise_end_z, upper_rows)
    for (front_y, front_z), (back_y, back_z) in zip(front_rise, reversed(back_rise)):
        if abs(front_z - back_z) > 1e-9:
            raise PanelBuildError("Wide Cargo front/back rise levels differ")
        half_width = interpolate_width(
            front_z,
            z0=rise_start_z,
            width0=lower_outer,
            z1=rise_end_z,
            width1=upper_width_at_end,
        )
        # Front and back centre points meet at one sewn vertex at the crotch
        # root; the builder performs that sharing.
        builder.add_section(
            SewnSection(
                z=front_z,
                outer_x=half_width,
                inner=CentreInner(front_y=front_y, back_y=back_y),
            )
        )

    # Continue the same four sewn panels from the completed rise to the waist.
    for z, half_width in upper_rows:
        if z <= rise_end_z:
            continue
        front_depth = profile_value(z, front_profile)
        rear_depth = profile_value(z, rear_profile)
        builder.add_section(
            SewnSection(
                z=z,
                outer_x=half_width,
                inner=CentreInner(front_y=-front_depth, back_y=rear_depth),
            )
        )

    builder.bridge_panels()
    for panel in POCKET_PANELS:
        for side in POCKET_SIDES:
            builder.add_fan_panel(panel, side=side)
    return mesh


def build_wide_cargo_mesh(baseline: dict[str, object] | None = None):
    """Convenience wrapper returning a fresh pure-Python mesh."""
    return build_wide_cargo_panels(
        MeshBuilder(),
        baseline if baseline is not None else load_pattern_baseline(),
    )
