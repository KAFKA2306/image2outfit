# AGENTS.md — execution instructions for AI agents

This file is the operating contract for LLM-based coding agents. Read `README.md` for the human-facing explanation.

## Objective

Leave verified `main` in a more correct, reproducible, inspectable, and resumable state than you found it.

A generated file, plausible explanation, CI success, or image inventory is not a garment result. Product completion requires current editable assets, current SiroinoSotai_PC renders, direct visual inspection, and a truthful lifecycle state.

## Instruction precedence

1. current user request and explicit acceptance criteria;
2. executable schemas, policies, tests, and gates;
3. current product job, construction contract, and `ProductManifest.json`;
4. this file;
5. README and product prose.

Repair stale lower-authority documents in the same coherent change.

## Contract ownership

- `config/products/<slug>/job.json` — identity, inputs, canonical outputs, delivery files, evidence paths.
- `config/job.schema.v2.json` — allowed job fields and types.
- `config/products/<slug>/construction.json` — adopted construction profile.
- `config/products/construction.schema.v1.json` — construction-contract schema.
- `config/genworks-handoff-policy.json` — project scope and completion boundary.
- `config/release-policy.json` — required views, poses, and visual evidence definitions.
- `Assets/GenWorks/<slug>/ProductManifest.json` — current state, gates, defects, hashes, and continuation point.
- `tools/production_contract.py` — shared contract validation.
- `tools/workspace_transaction.py` — last-good workspace protection.
- `Taskfile.yml` and `tools/manage.py` — supported operator entry points.

Do not create duplicate pose lists, product roots, lifecycle validators, or prose-owned thresholds.

## Canonical product layout

```text
config/products/<slug>/
  job.json
  construction.json
  license.json

Assets/GenWorks/<slug>/
  ProductManifest.json
  README.md
  Source/
  Models/
  Textures/
  Materials/
  Prefab/
  Previews/
    front.png
    back.png
    left.png
    right.png
    three-quarter.png
    Poses/
  Research/
  Tests/
  Documentation/
```

Mandatory constraints:

- no `Assets/GenWorks/Products/`, `Legacy/`, or alternate product roots;
- Prefabs are direct children of `Assets/GenWorks/<slug>/Prefab/`;
- required poses come only from `config/release-policy.json`;
- private avatar assets remain under ignored, job-approved roots;
- preserve Unity `.meta` files and GUIDs for tracked assets;
- do not commit credentials, caches, private packages, or machine state.

## Start-of-task protocol

Before editing:

1. classify the task;
2. inspect current `main`, open PRs, branches, exact files, and overlapping work;
3. resolve the product slug, target avatar, manifest, last-good checkpoint, latest renders, defects, and in-scope gates;
4. define the smallest coherent diff and checks;
5. continue an existing workstream rather than creating a competing one.

Do not restart from zero when a useful canonical checkpoint exists.

## Change discipline

- Fix generic defects generically.
- Prefer one owner over synchronized duplicates.
- Remove superseded code and references.
- Keep jobs, contracts, manifests, assets, tests, policy, and docs consistent.
- Do not weaken rendered quality because current data fails it.
- Do not replace a useful checkpoint with a worse result.
- Do not claim a tool ran or an image improved without direct verification.

## In-scope build workflow

Use:

```powershell
task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
```

The build workflow must:

1. validate the closed job and construction schemas;
2. protect the last-good canonical workspace;
3. run Blender with SiroinoSotai_PC as the target body;
4. produce editable source and FBX;
5. preserve declared Prefab assets and metadata without claiming Unity validation;
6. generate current front, back, left, right, three-quarter, multiview, and required-pose renders;
7. record the 2026 research trial and comparison evidence;
8. bind generated files and evidence by SHA-256 where the current contract requires it;
9. open and inspect the actual images;
10. restore last-good state when generation or visible quality fails.

## Completion boundary

The project completion state is `COMPLETE`. The sole machine-readable definition is `requiredCompletionGates` in `config/genworks-handoff-policy.json`.

Completion requires:

- `blender: PASS`;
- `editableSource: PASS`;
- `fbx: PASS`;
- `prefabDeclared: PASS`;
- `fiveViewEvidence: PASS`;
- `poseEvidence: PASS`;
- `visualAppearanceReview: PASS`;
- `researchTrial: PASS`.

`visualAppearanceReview` may be performed by ChatGPT only when it directly opens the current artifact images. It must reject body penetration, clipping, detached geometry, wrong scale, broken silhouette, extreme vertices, floating parts, asymmetric failures, UV or normal defects, material failures, and pose breakage.

A product may remain `WORKING` when useful progress is mergeable but any completion gate is missing or failing. A visibly rejected garment cannot be `COMPLETE`.

## Permanently out of scope

The following are not requested, awaited, or used as completion blockers:

- Unity 2022.3.22f1 import/save/reload;
- Modular Avatar／NDMF execution;
- VRChat Build & Test;
- VRChat runtime validation;
- human runtime visual review.

Their `FAIL`, `NOT_RUN`, missing environment, or missing screenshot states are `OUT_OF_SCOPE`. They must not create completion blockers.

Never convert an out-of-scope result into a false PASS. Without external evidence, do not claim that the Prefab was imported successfully, that Modular Avatar／NDMF ran, or that the garment works in VRChat. `COMPLETE` means the repository's rendered garment deliverable is complete, not externally verified runtime compatibility.

Legacy runtime, customer-quality, and release-packaging utilities may remain for an external operator, but they are optional extensions outside the ChatGPT garment-production scope.

## Visual inspection

Completion requires opening:

- front;
- back;
- left;
- right;
- three-quarter;
- combined multiview;
- every required pose.

File existence, dimensions, hashes, CI success, or another agent's text is not visual inspection. Record `visualAppearanceReview` as PASS or FAIL with inspected paths and concise findings.

## Validation

Run checks proportional to the diff and repository contract checks:

```powershell
task audit:repo
task audit:runtime
task audit:genworks
task audit:tools
task audit:methods
task audit:research
task check:python
```

`audit:runtime` may inspect stored metadata, but must not require Unity or VRChat executables and must treat policy-listed runtime gates as out of scope.

If Blender or the private target avatar is unavailable, report the exact boundary and do not claim completion. Unity or VRChat unavailability is expected and is not a blocker.

## Failure recovery

On failure:

1. restore the last-good canonical workspace;
2. retain useful diagnostics separately;
3. record the failing stage, hashes, visible defects, and next action;
4. keep the lifecycle state truthful;
5. preserve rejected work needed for continuation or audit.

## Git and pull-request lifecycle

- Do not push directly to `main`.
- Use one short-lived branch per coherent change.
- Commit only intended files.
- Open a PR describing root cause, behavior change, impact, and validation.
- Merge a `COMPLETE` product only after all required completion gates pass.
- A truthful `WORKING` checkpoint may merge when explicitly intended and non-regressive.
- Verify resulting `main`.
- Delete merged, closed, or superseded branches.
- Close superseded PRs with an explicit successor link.

Completion means the rendered product is `COMPLETE`, merged into verified `main`, and the work branch is removed.

## Final response contract

Report only verified facts:

- effective product state;
- changed behavior and principal files;
- exact checks and outcomes;
- current visual evidence links;
- commit, PR, merge, and branch-deletion state;
- remaining in-scope blockers;
- out-of-scope runtime items only as `OUT_OF_SCOPE`, never as unfinished work.
