"""Reusable domain and orchestration core for image2outfit."""

from .domain import (
    BodyRegion,
    ConstructionRole,
    FitProfile,
    GarmentPart,
    GarmentPartKind,
    GarmentSpecification,
    LayerPosition,
    MaterialBehavior,
    PatternPiece,
    Stitch,
    StitchEdge,
)
from .pipeline import PIPELINE_STAGES, PipelineStage, new_pipeline_state, run_pipeline

__all__ = [
    "BodyRegion",
    "ConstructionRole",
    "FitProfile",
    "GarmentPart",
    "GarmentPartKind",
    "GarmentSpecification",
    "LayerPosition",
    "MaterialBehavior",
    "PatternPiece",
    "PIPELINE_STAGES",
    "PipelineStage",
    "Stitch",
    "StitchEdge",
    "new_pipeline_state",
    "run_pipeline",
]
