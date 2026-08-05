"""Typed artifact dependency graph for the canonical 13-stage pipeline."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Iterable

from .pipeline import PipelineStage

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_repo_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("artifact_path must be a repository-relative POSIX path")


class ArtifactKind(StrEnum):
    REFERENCE_SET = "reference-set"
    NORMALIZED_REFERENCE_SET = "normalized-reference-set"
    GARMENT_DECOMPOSITION = "garment-decomposition"
    PATTERN_HYPOTHESES = "pattern-hypotheses"
    SEAM_HYPOTHESES = "seam-hypotheses"
    ARRANGEMENT_PLAN = "arrangement-plan"
    BLENDER_SOURCE = "blender-source"
    CLOTH_SOLUTION = "cloth-solution"
    EXPORT_BUNDLE = "export-bundle"
    RENDER_EVIDENCE = "render-evidence"
    GEOMETRY_AUDIT = "geometry-audit"
    VISUAL_REVIEW = "visual-review"
    CANDIDATE_DECISION = "candidate-decision"


class GarmentSectionName(StrEnum):
    AVATAR = "avatar"
    CONSTRUCTION = "construction"
    FIT = "fit"
    MATERIALS = "materials"
    STYLING = "styling"
    QUALITY = "quality"
    PROVENANCE = "provenance"


@dataclass(frozen=True, slots=True)
class StageContract:
    stage: PipelineStage
    consumes: tuple[ArtifactKind, ...]
    produces: ArtifactKind
    invalidated_by: frozenset[GarmentSectionName]


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    kind: ArtifactKind
    producer_stage: PipelineStage
    garment_id: str
    hypothesis_id: str
    candidate_id: str
    avatar_sha256: str
    content_sha256: str
    artifact_path: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("artifact schema_version must be positive")
        _require_repo_relative_path(self.artifact_path)
        for label, value in (
            ("avatar_sha256", self.avatar_sha256),
            ("content_sha256", self.content_sha256),
        ):
            if not _SHA256.fullmatch(value):
                raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        for label, value in (
            ("garment_id", self.garment_id),
            ("hypothesis_id", self.hypothesis_id),
            ("candidate_id", self.candidate_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")

    def verify_content(self, repository_root: str | Path) -> None:
        path = Path(repository_root) / self.artifact_path
        if not path.is_file():
            raise ValueError(f"artifact file does not exist: {self.artifact_path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != self.content_sha256:
            raise ValueError(
                f"artifact hash mismatch for {self.artifact_path}: "
                f"{actual} != {self.content_sha256}"
            )


CANONICAL_STAGE_CONTRACTS = (
    StageContract(
        PipelineStage.INGEST_REFERENCE,
        (),
        ArtifactKind.REFERENCE_SET,
        frozenset({GarmentSectionName.PROVENANCE}),
    ),
    StageContract(
        PipelineStage.NORMALIZE_VIEW,
        (ArtifactKind.REFERENCE_SET,),
        ArtifactKind.NORMALIZED_REFERENCE_SET,
        frozenset({GarmentSectionName.AVATAR, GarmentSectionName.PROVENANCE}),
    ),
    StageContract(
        PipelineStage.DECOMPOSE_GARMENT,
        (ArtifactKind.NORMALIZED_REFERENCE_SET,),
        ArtifactKind.GARMENT_DECOMPOSITION,
        frozenset({GarmentSectionName.CONSTRUCTION, GarmentSectionName.PROVENANCE}),
    ),
    StageContract(
        PipelineStage.DRAFT_PATTERNS,
        (ArtifactKind.GARMENT_DECOMPOSITION,),
        ArtifactKind.PATTERN_HYPOTHESES,
        frozenset(
            {
                GarmentSectionName.AVATAR,
                GarmentSectionName.CONSTRUCTION,
                GarmentSectionName.FIT,
            }
        ),
    ),
    StageContract(
        PipelineStage.INFER_STITCHES,
        (ArtifactKind.PATTERN_HYPOTHESES,),
        ArtifactKind.SEAM_HYPOTHESES,
        frozenset({GarmentSectionName.CONSTRUCTION}),
    ),
    StageContract(
        PipelineStage.INITIALIZE_3D,
        (ArtifactKind.SEAM_HYPOTHESES,),
        ArtifactKind.ARRANGEMENT_PLAN,
        frozenset(
            {
                GarmentSectionName.AVATAR,
                GarmentSectionName.CONSTRUCTION,
                GarmentSectionName.FIT,
                GarmentSectionName.STYLING,
            }
        ),
    ),
    StageContract(
        PipelineStage.BUILD_BLENDER,
        (ArtifactKind.ARRANGEMENT_PLAN,),
        ArtifactKind.BLENDER_SOURCE,
        frozenset(
            {
                GarmentSectionName.CONSTRUCTION,
                GarmentSectionName.MATERIALS,
                GarmentSectionName.STYLING,
            }
        ),
    ),
    StageContract(
        PipelineStage.SIMULATE_CLOTH,
        (ArtifactKind.BLENDER_SOURCE,),
        ArtifactKind.CLOTH_SOLUTION,
        frozenset(
            {
                GarmentSectionName.AVATAR,
                GarmentSectionName.CONSTRUCTION,
                GarmentSectionName.FIT,
                GarmentSectionName.MATERIALS,
                GarmentSectionName.STYLING,
            }
        ),
    ),
    StageContract(
        PipelineStage.SKIN_AND_EXPORT,
        (ArtifactKind.CLOTH_SOLUTION,),
        ArtifactKind.EXPORT_BUNDLE,
        frozenset({GarmentSectionName.AVATAR, GarmentSectionName.FIT}),
    ),
    StageContract(
        PipelineStage.RENDER_EVIDENCE,
        (ArtifactKind.EXPORT_BUNDLE,),
        ArtifactKind.RENDER_EVIDENCE,
        frozenset(
            {
                GarmentSectionName.MATERIALS,
                GarmentSectionName.STYLING,
                GarmentSectionName.QUALITY,
            }
        ),
    ),
    StageContract(
        PipelineStage.AUDIT_GEOMETRY,
        (ArtifactKind.EXPORT_BUNDLE, ArtifactKind.RENDER_EVIDENCE),
        ArtifactKind.GEOMETRY_AUDIT,
        frozenset(
            {
                GarmentSectionName.AVATAR,
                GarmentSectionName.CONSTRUCTION,
                GarmentSectionName.FIT,
                GarmentSectionName.MATERIALS,
                GarmentSectionName.STYLING,
                GarmentSectionName.QUALITY,
            }
        ),
    ),
    StageContract(
        PipelineStage.VISUAL_REVIEW,
        (ArtifactKind.RENDER_EVIDENCE, ArtifactKind.GEOMETRY_AUDIT),
        ArtifactKind.VISUAL_REVIEW,
        frozenset({GarmentSectionName.QUALITY}),
    ),
    StageContract(
        PipelineStage.FINALIZE_CANDIDATE,
        (ArtifactKind.GEOMETRY_AUDIT, ArtifactKind.VISUAL_REVIEW),
        ArtifactKind.CANDIDATE_DECISION,
        frozenset({GarmentSectionName.QUALITY}),
    ),
)


class PipelineArtifactDAG:
    def __init__(
        self, contracts: tuple[StageContract, ...] = CANONICAL_STAGE_CONTRACTS
    ):
        self.contracts = contracts
        self._validate()
        self._index = {
            contract.stage: index for index, contract in enumerate(contracts)
        }
        self._producer = {contract.produces: contract.stage for contract in contracts}

    def _validate(self) -> None:
        stages = [contract.stage for contract in self.contracts]
        if stages != list(PipelineStage):
            raise ValueError("contracts must preserve the canonical 13-stage order")
        products = [contract.produces for contract in self.contracts]
        if len(products) != len(set(products)):
            raise ValueError("each artifact kind must have exactly one producer")
        produced: set[ArtifactKind] = set()
        for contract in self.contracts:
            missing = set(contract.consumes).difference(produced)
            if missing:
                raise ValueError(
                    f"stage {contract.stage.value} consumes artifacts before production: "
                    f"{sorted(item.value for item in missing)}"
                )
            produced.add(contract.produces)

    def contract(self, stage: PipelineStage | str) -> StageContract:
        resolved = PipelineStage(stage)
        return self.contracts[self._index[resolved]]

    def validate_inputs(
        self,
        stage: PipelineStage | str,
        artifacts: Iterable[ArtifactRef],
        *,
        garment_id: str,
        hypothesis_id: str,
        candidate_id: str,
        avatar_sha256: str,
    ) -> None:
        contract = self.contract(stage)
        by_kind = {artifact.kind: artifact for artifact in artifacts}
        missing = set(contract.consumes).difference(by_kind)
        if missing:
            raise ValueError(
                f"stage {contract.stage.value} is missing inputs: "
                f"{sorted(item.value for item in missing)}"
            )
        for kind in contract.consumes:
            artifact = by_kind[kind]
            expected_stage = self._producer[kind]
            if artifact.producer_stage is not expected_stage:
                raise ValueError(f"artifact {kind.value} declares the wrong producer")
            for label, actual, expected in (
                ("garment_id", artifact.garment_id, garment_id),
                ("hypothesis_id", artifact.hypothesis_id, hypothesis_id),
                ("candidate_id", artifact.candidate_id, candidate_id),
                ("avatar_sha256", artifact.avatar_sha256, avatar_sha256),
            ):
                if actual != expected:
                    raise ValueError(
                        f"artifact {kind.value} {label} mismatch: "
                        f"{actual!r} != {expected!r}"
                    )

    def dirty_stages(
        self, changed_sections: Iterable[GarmentSectionName | str]
    ) -> tuple[PipelineStage, ...]:
        changed = {GarmentSectionName(section) for section in changed_sections}
        direct = [
            index
            for index, contract in enumerate(self.contracts)
            if contract.invalidated_by.intersection(changed)
        ]
        if not direct:
            return ()
        first = min(direct)
        return tuple(contract.stage for contract in self.contracts[first:])

    def execution_plan(
        self, changed_sections: Iterable[GarmentSectionName | str]
    ) -> dict[str, object]:
        changed = sorted(
            {GarmentSectionName(section).value for section in changed_sections}
        )
        stages = self.dirty_stages(changed)
        return {
            "schemaVersion": 1,
            "changedSections": changed,
            "stages": [stage.value for stage in stages],
            "contracts": [
                {
                    "stage": contract.stage.value,
                    "consumes": [item.value for item in contract.consumes],
                    "produces": contract.produces.value,
                }
                for contract in self.contracts
                if contract.stage in stages
            ],
        }
