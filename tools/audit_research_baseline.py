#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BASELINE_RELATIVE_PATH = Path('Assets/GenWorks/Shared/Research/2026-garment-methods.json')


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def audit(root: Path = ROOT, *, now: datetime | None = None) -> dict[str, Any]:
    root = root.resolve()
    path = root / BASELINE_RELATIVE_PATH
    errors: list[str] = []
    warnings: list[str] = []
    try:
        baseline = _read(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {'schemaVersion': 2, 'passed': False, 'path': path.relative_to(root).as_posix(), 'errors': [f'research baseline unreadable: {exc}'], 'warnings': []}

    if baseline.get('schemaVersion') != 2:
        errors.append('schemaVersion must be 2')
    if not isinstance(baseline.get('baselineId'), str) or not baseline['baselineId']:
        errors.append('baselineId is required')

    survey = baseline.get('survey') if isinstance(baseline.get('survey'), dict) else {}
    if not survey:
        errors.append('survey must be an object')
    year = survey.get('year')
    if year != 2026:
        errors.append('survey.year must be 2026')
    if not isinstance(survey.get('scope'), str) or not survey.get('scope', '').strip():
        errors.append('survey.scope is required')
    policy = survey.get('selectionPolicy') if isinstance(survey.get('selectionPolicy'), dict) else {}
    if not policy:
        errors.append('survey.selectionPolicy must be an object')
    for field in ('sourceTypes', 'inclusionCriteria', 'exclusionCriteria'):
        if not _strings(policy.get(field)):
            errors.append(f'survey.selectionPolicy.{field}')

    checked = _utc(survey.get('reviewedAt'))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    freshness = survey.get('freshnessDays')
    if checked is None:
        errors.append('survey.reviewedAt must be an ISO-8601 timestamp with timezone')
    elif checked > current:
        errors.append('survey.reviewedAt cannot be in the future')
    if not isinstance(freshness, int) or freshness <= 0:
        errors.append('survey.freshnessDays must be a positive integer')
    elif checked is not None and (current - checked).days > freshness:
        errors.append(f'research survey is stale: {(current - checked).days} days old, limit {freshness}')

    hosts = survey.get('officialSourceHosts')
    allowed_hosts = set(hosts) if _strings(hosts) else set()
    if not allowed_hosts:
        errors.append('survey.officialSourceHosts must be a non-empty string list')
    elif len(allowed_hosts) != len(hosts):
        errors.append('survey.officialSourceHosts contains duplicates')

    binding = baseline.get('ontologyBinding') if isinstance(baseline.get('ontologyBinding'), dict) else {}
    binding_fields = ('sourceClass', 'assessmentClass', 'requirementClass', 'testClass', 'evidenceClass', 'decisionClass')
    if not binding:
        errors.append('ontologyBinding must be an object')
    ontology_rel = binding.get('projectOntologyPath')
    if not isinstance(ontology_rel, str) or not ontology_rel:
        errors.append('ontologyBinding.projectOntologyPath')
    else:
        try:
            ontology_text = (root / ontology_rel).read_text(encoding='utf-8-sig')
        except OSError as exc:
            errors.append(f'ontologyBinding.projectOntologyPath unreadable: {exc}')
        else:
            for field in binding_fields:
                value = binding.get(field)
                if not isinstance(value, str) or not value:
                    errors.append(f'ontologyBinding.{field}')
                elif value not in ontology_text:
                    errors.append(f'ontologyBinding.{field} is not declared in {ontology_rel}: {value}')

    capabilities = baseline.get('capabilities') if isinstance(baseline.get('capabilities'), list) else []
    if not capabilities:
        errors.append('capabilities must be a non-empty list')
    capability_ids: set[str] = set()
    required_capabilities: set[str] = set()
    capability_kinds = {'REPRESENTATION_CAPABILITY', 'ASSEMBLY_PROCESS', 'GEOMETRY_CAPABILITY', 'QUALITY_PROPERTY', 'MATERIAL_CAPABILITY', 'DEFORMATION_CAPABILITY', 'EVALUATION_PROCESS'}
    for index, item in enumerate(capabilities):
        prefix = f'capabilities[{index}]'
        if not isinstance(item, dict):
            errors.append(prefix)
            continue
        item_id = item.get('id')
        if not isinstance(item_id, str) or not item_id:
            errors.append(f'{prefix}.id')
            continue
        if item_id in capability_ids:
            errors.append(f'duplicate capability id: {item_id}')
        capability_ids.add(item_id)
        if item.get('kind') not in capability_kinds:
            errors.append(f'{prefix}.kind')
        if not isinstance(item.get('description'), str) or not item.get('description', '').strip():
            errors.append(f'{prefix}.description')
        if not isinstance(item.get('required'), bool):
            errors.append(f'{prefix}.required must be boolean')
        elif item['required']:
            required_capabilities.add(item_id)

    publications = baseline.get('publications') if isinstance(baseline.get('publications'), list) else []
    if not publications:
        errors.append('publications must be a non-empty list')
    publication_ids: set[str] = set()
    for index, item in enumerate(publications):
        prefix = f'publications[{index}]'
        if not isinstance(item, dict):
            errors.append(prefix)
            continue
        item_id = item.get('id')
        if not isinstance(item_id, str) or not item_id:
            errors.append(f'{prefix}.id')
        elif item_id in publication_ids:
            errors.append(f'duplicate publication id: {item_id}')
        else:
            publication_ids.add(item_id)
        for field in ('title', 'venue', 'reportedClaim'):
            if not isinstance(item.get(field), str) or not item.get(field, '').strip():
                errors.append(f'{prefix}.{field}')
        if item.get('year') != year:
            errors.append(f'{prefix}.year must match survey.year')
        if item.get('publicationStatus') not in {'PEER_REVIEWED', 'PREPRINT'}:
            errors.append(f'{prefix}.publicationStatus')
        url = item.get('officialUrl')
        parsed = urlparse(url) if isinstance(url, str) else None
        if parsed is None or parsed.scheme != 'https' or parsed.hostname not in allowed_hosts:
            errors.append(f'{prefix}.officialUrl must use an approved primary-source host')

    assessments = baseline.get('methodAssessments') if isinstance(baseline.get('methodAssessments'), list) else []
    if not assessments:
        errors.append('methodAssessments must be a non-empty list')
    assessment_ids: set[str] = set()
    assessed: set[str] = set()
    covered: set[str] = set()
    production_tracks = {'ADOPT_PRINCIPLE', 'PROTOTYPE', 'BENCHMARK'}
    for index, item in enumerate(assessments):
        prefix = f'methodAssessments[{index}]'
        if not isinstance(item, dict):
            errors.append(prefix)
            continue
        item_id = item.get('id')
        if not isinstance(item_id, str) or not item_id:
            errors.append(f'{prefix}.id')
        elif item_id in assessment_ids:
            errors.append(f'duplicate assessment id: {item_id}')
        else:
            assessment_ids.add(item_id)
        publication_id = item.get('publicationId')
        if publication_id not in publication_ids:
            errors.append(f'{prefix}.publicationId references an unknown publication')
        elif publication_id in assessed:
            errors.append(f'duplicate assessment for publication: {publication_id}')
        else:
            assessed.add(publication_id)
        decision = item.get('decision')
        if decision not in production_tracks | {'WATCH'}:
            errors.append(f'{prefix}.decision')
        refs = item.get('capabilityIds')
        if not _strings(refs):
            errors.append(f'{prefix}.capabilityIds')
        else:
            unknown = set(refs) - capability_ids
            if unknown:
                errors.append(f'{prefix}.unknownCapabilities: {sorted(unknown)}')
            if decision in production_tracks:
                covered.update(refs)
        for field in ('rationale', 'decisionAuthority'):
            if not isinstance(item.get(field), str) or not item.get(field, '').strip():
                errors.append(f'{prefix}.{field}')
        if _utc(f"{item.get('decidedAt')}T00:00:00+00:00") is None:
            errors.append(f'{prefix}.decidedAt must be an ISO date')
        for field in ('implementationImplications', 'rejectionCriteria'):
            if not _strings(item.get(field)):
                errors.append(f'{prefix}.{field}')
    if publication_ids - assessed:
        errors.append('publications lack method assessments: ' + ', '.join(sorted(publication_ids - assessed)))
    if required_capabilities - covered:
        errors.append('required capabilities lack an implementation or mandatory benchmark track: ' + ', '.join(sorted(required_capabilities - covered)))

    requirements = baseline.get('productionRequirements') if isinstance(baseline.get('productionRequirements'), list) else []
    if not requirements:
        errors.append('productionRequirements must be a non-empty list')
    requirement_ids: set[str] = set()
    requirement_counts = {item_id: 0 for item_id in capability_ids}
    for index, item in enumerate(requirements):
        prefix = f'productionRequirements[{index}]'
        if not isinstance(item, dict):
            errors.append(prefix)
            continue
        item_id = item.get('id')
        if not isinstance(item_id, str) or not item_id:
            errors.append(f'{prefix}.id')
        elif item_id in requirement_ids:
            errors.append(f'duplicate requirement id: {item_id}')
        else:
            requirement_ids.add(item_id)
        capability_id = item.get('capabilityId')
        if capability_id not in capability_ids:
            errors.append(f'{prefix}.capabilityId references an unknown capability')
        else:
            requirement_counts[capability_id] += 1
        if not isinstance(item.get('statement'), str) or not item.get('statement', '').strip():
            errors.append(f'{prefix}.statement')
        if item.get('severity') not in {'BLOCKER', 'MAJOR', 'MINOR'}:
            errors.append(f'{prefix}.severity')
        if not isinstance(item.get('evidenceType'), str) or not item.get('evidenceType', '').strip():
            errors.append(f'{prefix}.evidenceType')
        if not isinstance(item.get('automatable'), bool):
            errors.append(f'{prefix}.automatable must be boolean')
        sources = item.get('derivedFrom')
        if not _strings(sources):
            errors.append(f'{prefix}.derivedFrom')
        elif set(sources) - publication_ids:
            errors.append(f'{prefix}.derivedFrom references unknown publications: {sorted(set(sources) - publication_ids)}')
    for capability_id in sorted(required_capabilities):
        if requirement_counts.get(capability_id, 0) == 0:
            errors.append(f'required capability lacks production requirements: {capability_id}')

    protocols = baseline.get('benchmarkProtocols') if isinstance(baseline.get('benchmarkProtocols'), list) else []
    if not protocols:
        errors.append('benchmarkProtocols must be a non-empty list')
    protocol_ids: set[str] = set()
    protocol_capabilities: set[str] = set()
    for index, item in enumerate(protocols):
        prefix = f'benchmarkProtocols[{index}]'
        if not isinstance(item, dict):
            errors.append(prefix)
            continue
        item_id = item.get('id')
        if not isinstance(item_id, str) or not item_id:
            errors.append(f'{prefix}.id')
        elif item_id in protocol_ids:
            errors.append(f'duplicate benchmark protocol id: {item_id}')
        else:
            protocol_ids.add(item_id)
        capability_id = item.get('capabilityId')
        if capability_id not in capability_ids:
            errors.append(f'{prefix}.capabilityId references an unknown capability')
        else:
            protocol_capabilities.add(capability_id)
        refs = item.get('requirementIds')
        if not _strings(refs):
            errors.append(f'{prefix}.requirementIds')
        elif set(refs) - requirement_ids:
            errors.append(f'{prefix}.requirementIds references unknown requirements: {sorted(set(refs) - requirement_ids)}')
        if item.get('candidateBinding') != 'candidate-manifest-sha256':
            errors.append(f'{prefix}.candidateBinding')
        if item.get('requiredOutcome') != 'PASS_OR_EXPLICIT_NO_GO':
            errors.append(f'{prefix}.requiredOutcome')
    if required_capabilities - protocol_capabilities:
        errors.append('required capabilities lack benchmark protocols: ' + ', '.join(sorted(required_capabilities - protocol_capabilities)))

    licenses = baseline.get('licenseAssessments') if isinstance(baseline.get('licenseAssessments'), list) else []
    if not licenses:
        errors.append('licenseAssessments must be a non-empty list')
    licensed: set[str] = set()
    for index, item in enumerate(licenses):
        prefix = f'licenseAssessments[{index}]'
        if not isinstance(item, dict):
            errors.append(prefix)
            continue
        publication_id = item.get('publicationId')
        if publication_id not in publication_ids:
            errors.append(f'{prefix}.publicationId references an unknown publication')
        elif publication_id in licensed:
            errors.append(f'duplicate license assessment for publication: {publication_id}')
        else:
            licensed.add(publication_id)
        if item.get('codeAvailability') not in {'UNKNOWN', 'UNAVAILABLE', 'AVAILABLE'}:
            errors.append(f'{prefix}.codeAvailability')
        if item.get('reuseDecision') not in {'DO_NOT_REUSE', 'REIMPLEMENT_IDEA_ONLY', 'REUSE'}:
            errors.append(f'{prefix}.reuseDecision')
        if not isinstance(item.get('reason'), str) or not item.get('reason', '').strip():
            errors.append(f'{prefix}.reason')
        if item.get('reuseDecision') == 'REUSE':
            if item.get('codeAvailability') != 'AVAILABLE':
                errors.append(f'{prefix}: REUSE requires codeAvailability AVAILABLE')
            url = item.get('officialCodeUrl')
            if not isinstance(url, str) or urlparse(url).scheme != 'https':
                errors.append(f'{prefix}.officialCodeUrl is required for REUSE')
            if item.get('declaredLicense') in {None, '', 'UNVERIFIED'}:
                errors.append(f'{prefix}.declaredLicense must be verified for REUSE')
            if _utc(item.get('licenseVerifiedAt')) is None:
                errors.append(f'{prefix}.licenseVerifiedAt is required for REUSE')
            if item.get('commercialUseAssessment') == 'UNASSESSED':
                errors.append(f'{prefix}.commercialUseAssessment is required for REUSE')
    if publication_ids - licensed:
        errors.append('publications lack license assessments: ' + ', '.join(sorted(publication_ids - licensed)))

    reuse = baseline.get('reusePolicy') if isinstance(baseline.get('reusePolicy'), dict) else {}
    if not reuse:
        errors.append('reusePolicy must be an object')
    if reuse.get('paperIdeasMayBeReimplemented') is not True:
        errors.append('reusePolicy.paperIdeasMayBeReimplemented must be true')
    if reuse.get('paperCodeOrModelsMayBeCopiedWithoutVerifiedLicense') is not False:
        errors.append('reusePolicy.paperCodeOrModelsMayBeCopiedWithoutVerifiedLicense must be false')
    if reuse.get('commercialReleaseRequiresIndependentLicenseReview') is not True:
        errors.append('reusePolicy.commercialReleaseRequiresIndependentLicenseReview must be true')

    return {
        'schemaVersion': 2,
        'passed': not errors,
        'path': path.relative_to(root).as_posix(),
        'baselineId': baseline.get('baselineId'),
        'surveyYear': year,
        'reviewedAt': survey.get('reviewedAt'),
        'publicationCount': len(publications),
        'methodCount': len(publications),
        'assessmentCount': len(assessments),
        'requirementCount': len(requirements),
        'requiredCapabilities': sorted(required_capabilities),
        'productionCoverage': sorted(covered),
        'errors': errors,
        'warnings': warnings,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
