"""Primary-source research principles crystallized as implementation rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResearchPrinciple:
    principle_id: str
    title: str
    paper_url: str
    published_date: str
    implementation_rule: str
    boundary: str


PATTERN_FIRST = ResearchPrinciple(
    principle_id="pattern-first-structured-garment",
    title=(
        "PatternGSL: A Structured Specification Language for Template-Free and "
        "Simulation-Ready 3D Garments"
    ),
    paper_url="https://arxiv.org/abs/2606.24564",
    published_date="2026-06-23",
    implementation_rule=(
        "Represent panel boundaries, parameterized seams, and stitch topology as "
        "explicit intermediate data before Blender mesh generation."
    ),
    boundary=(
        "Representation principle only; author code, model, and dataset are not "
        "copied."
    ),
)

GEOMETRIC_STITCH_GRAPH = ResearchPrinciple(
    principle_id="geometry-first-stitch-graph",
    title=(
        "AutoSew: A Geometric Approach to Stitching Prediction with Graph Neural "
        "Networks"
    ),
    paper_url="https://arxiv.org/abs/2602.22052",
    published_date="2026-02-25",
    implementation_rule=(
        "Treat sewing as a graph over pattern edges, including one-to-many and "
        "many-to-one connections, rather than implicit panel-name conventions."
    ),
    boundary=(
        "Data-contract principle only; trained weights and author implementation "
        "are not copied."
    ),
)

POSE_NORMALIZED_PATTERN_RECOVERY = ResearchPrinciple(
    principle_id="pose-normalized-pattern-recovery",
    title=(
        "DressWild: Feed-Forward Pose-Agnostic Garment Sewing Pattern Generation "
        "from In-the-Wild Images"
    ),
    paper_url="https://arxiv.org/abs/2602.16502",
    published_date="2026-02-18",
    implementation_rule=(
        "Separate pose and viewpoint normalization from garment-part inference and "
        "pattern drafting so each stage can be replaced and evaluated independently."
    ),
    boundary=(
        "Pipeline decomposition principle only; author model is not executed or "
        "copied."
    ),
)

PATTERN_COORDINATE_MAPPING = ResearchPrinciple(
    principle_id="pattern-coordinate-mapping",
    title=(
        "Single View Garment Reconstruction Using Diffusion Mapping Via Pattern "
        "Coordinates"
    ),
    paper_url="https://arxiv.org/abs/2504.08353",
    published_date="2025-04-11",
    implementation_rule=(
        "Preserve correspondence identifiers between image evidence, two-dimensional "
        "pattern coordinates, and three-dimensional garment geometry."
    ),
    boundary=(
        "Correspondence principle only; author model and data are not copied."
    ),
)

DEFAULT_RESEARCH_PRINCIPLES = (
    PATTERN_FIRST,
    GEOMETRIC_STITCH_GRAPH,
    POSE_NORMALIZED_PATTERN_RECOVERY,
    PATTERN_COORDINATE_MAPPING,
)
