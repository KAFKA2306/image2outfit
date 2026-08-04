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
from .execution import StageExecutionBinding, expand_command_template
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
    "StageExecutionBinding",
    "StitchEdge",
    "expand_command_template",
    "new_pipeline_state",
    "run_pipeline",
]
