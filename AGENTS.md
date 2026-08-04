# AGENTS.md — execution instructions for AI agents

This file is the operating contract for LLM-based coding agents. Read `README.md` for the human-facing explanation. Use this file to decide how to inspect, change, validate, publish, and finish work.

## Objective

Leave verified `main` in a more correct, reproducible, inspectable, and resumable state than you found it.

A generated file, workflow artifact, plausible explanation, or passing syntax check is not a product result. Garment work requires an editable checkpoint, current technical evidence, current visual evidence, and a truthful lifecycle state.

For repository completion, the supported boundary ends at Blender generation, topology validation, rendered five-view inspection, rendered six-pose fit/intersection inspection, FBX generation, and declared Prefab asset presence. Unity import/save/reload, Modular Avatar／NDMF validation, VRChat Build & Test, and VRChat runtime human review are external downstream activities and are outside the agent workstream scope. They do not block repository completion, merge, or branch cleanup and must not be reported as pending repository blockers.

## Instruction precedence

Use this order when instructions conflict:

1. the current user request and explicit acceptance criteria;
2. executable schemas, policies, tests, and gates;
3. the current product job, construction contract, and `ProductManifest.json`;
4. this `AGENTS.md`;
5. `README.md` and product prose.

Do not silently select a lower-authority source. Repair stale prose or contracts in the same coherent change when possible.

## Contract ownership

Mutable decisions have one owner.

- `config/products/<slug>/job.json` — product identity, inputs, canonical outputs, delivery files, and evidence locations.
- `config/job.schema.v2.json` — allowed job fields and types. Unknown job fields are errors.
- `config/products/<slug>/construction.json` — the construction profile explicitly adopted by the product.
- `config/products/construction.schema.v1.json` — allowed construction-contract fields and types.
- `config/genworks-handoff-policy.json` — repository completion, merge, checkpoint, and external downstream boundary.
- `config/release-policy.json` — required views, required poses, evidence kinds, metrics, and optional downstream release thresholds.
- `Assets/GenWorks/<slug>/ProductManifest.json` — current state, gates, defects, hashes, and continuation point.
- `tools/production_contract.py` — shared job, construction, product-state, and hashed-artifact validation.
- `tools/workspace_transaction.py` — last-good protection for canonical product workspaces.
- `tools/runtime_transaction.py` — last-good protection for derived candidate and release directories.
- `tools/customer_quality.py` — the downstream human/customer release validator.
- `tools/release_packager.py` — downstream release packaging with raw evidence and hashes.
- `Taskfile.yml` and `tools/manage.py` — supported operator entry points.

Do not create a second pose list, a second release validator, a second product root, or prose-owned thresholds. `construction.json` declares a selected profile; it is not evidence that an algorithm automatically selected the profile.

## Canonical product layout

Each tracked product has one slug and one canonical workspace:

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
  Evidence/Commercial/
  Demo/
  Editor/
  Tests/
  Documentation/
```

Mandatory constraints:

- never introduce `Assets/GenWorks/Products/`, avatar-grouping directories, `Legacy/`, or another intermediate product root;
- product Prefabs are direct children of `Assets/GenWorks/<slug>/Prefab/`;
- required poses come only from `config/release-policy.json` and use `Previews/Poses/<pose>.png`;
- product jobs must not configure runtime output directories;
- local reports, candidates, and releases belong only under `.image2outfit/products/<slug>/{reports,candidate,release}`;
- previous `Artifacts/`, `Candidates/`, and `Release/` roots are forbidden;
- preserve Unity `.meta` files and GUIDs when moving tracked assets;
- private or licensed avatar assets remain under ignored, job-approved roots;
- never commit credentials, caches, machine state, private packages, or unreviewed customer release archives.

## Start-of-task protocol

Before editing:

1. classify the task as repository-wide, product-specific, validation-only, or downstream release-related;
2. inspect current `main`, open PRs, branches, the exact requested files, and overlapping work;
3. for product work, resolve the slug, job, construction contract, target avatar, manifest, last-good checkpoint, latest renders, current defects, and in-scope pending gates;
4. define the smallest coherent diff and the checks that will prove it;
5. preserve unrelated work and continue an existing workstream branch instead of creating a competing one.

Do not restart from zero when a useful canonical checkpoint exists.

## Change discipline

- Fix generic defects generically. Do not add a one-product bypass.
- Prefer one owner over synchronization between duplicate mechanisms.
- Remove superseded code and references when replacing a mechanism.
- Keep jobs, construction contracts, manifests, assets, tests, policies, and documentation consistent in the same change.
- Do not weaken an in-scope gate because current data fails it.
- Do not replace a useful checkpoint with a failed or incomplete result.
- Do not claim that a tool ran, an image was inspected, or a defect improved without direct verification.

## Repository candidate workflow

Use:

```powershell
task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
```

The repository candidate workflow must:

1. fully validate the closed job schema and construction schema;
2. bind the declared construction profile to current policy and research coverage;
3. snapshot the canonical `Assets/GenWorks/<slug>/` workspace before generation;
4. protect previous derived candidate state;
5. run Blender generation, final save, FBX generation, current five-view rendering, current required-pose rendering, topology checks, and applicable fit/intersection checks;
6. reject explicit technical `FAIL` or fit-audit failure recorded in `ProductManifest.json`;
7. verify every required view and every policy-required pose;
8. reject duplicate pose images used as evidence for multiple poses;
9. bind inputs, generated files, research baseline, construction contract, and pose files to the candidate manifest by SHA-256;
10. restore the last-good canonical workspace and previous candidate when any in-scope stage fails.

Unity import/save/reload, Modular Avatar／NDMF validation, VRChat Build & Test, and VRChat runtime human review are not steps in repository candidate completion. Existing downstream tooling may remain available for an explicitly separate external workflow, but agents must not wait for it or use its absence to block merge.

## Repository completion and merge boundary

Repository completion and downstream customer release are separate concepts.

A garment checkpoint is complete and mergeable when every item in `requiredMergeCheckpointGates` and `repositoryCompletionBoundary.includedStages` from `config/genworks-handoff-policy.json` is verified. The checkpoint must include the editable Blender source, FBX, declared Prefab assets, current five-view evidence, required pose evidence, fit/topology evidence, and the recorded research trial.

The following are explicitly external and out of scope:

- Unity import/save/reload;
- Modular Avatar／NDMF validation;
- VRChat Build & Test;
- VRChat runtime human review.

Their absence is not a repository blocker, not an incomplete item, and not a reason to retain a completed branch. Do not list them under remaining gates or unresolved blockers. Do not invent results for them.

Do not merge when an in-scope Blender/topology/render/pose gate fails, current renders visibly fail the requested acceptance criteria, evidence is stale or missing, or the canonical workspace would regress.

## Optional external release workflow

The repository contains release tooling for downstream operators. Use it only when the user explicitly requests that separate external workflow and the required environment and human evidence are actually available.

Never imply that repository completion requires an external release. Never use `RELEASED`, customer-delivery, Unity-compatible, Modular Avatar-validated, NDMF-validated, or VRChat-runtime-validated claims without direct external evidence.

## Visual inspection

Garment checkpoint work is not mergeable without opening the current in-scope evidence:

- front;
- back;
- left;
- right;
- three-quarter;
- combined multiview;
- every required pose.

File existence, dimensions, hashes, CI success, or another agent's text is not visual inspection. Reject or iterate on body penetration, clipping, detached geometry, wrong scale, broken silhouette, extreme vertices, UV stretching, visible seams, normal errors, material defects, floating hardware, broken weights, or pose failure.

Unity or VRChat runtime screenshots are outside the repository completion boundary and are not required.

## Validation

Run checks proportional to the diff and then the repository contract checks:

```powershell
task audit:repo
task audit:runtime
task audit:genworks
task audit:tools
task audit:methods
task audit:research
task check:python
```

For product changes, run every available in-scope Blender build and evidence check and inspect the generated images. External Unity or VRChat checks are run only in a separately requested downstream workflow.

If Blender or the required private avatar is unavailable, report the exact unverified in-scope boundary. Do not report unavailable Unity, Modular Avatar／NDMF, VRChat Build & Test, or runtime human review as repository blockers.

## GitHub Actions

Read-only workflow jobs use `contents: read`. Request write permissions only for the narrow mutation that requires them. CI artifacts may carry reports and generated candidates, but they are not the sole resumable checkpoint.

## Failure recovery

On generation, migration, or validation failure:

1. restore the last-good canonical workspace;
2. restore the previous valid candidate state;
3. retain useful failed-run diagnostics separately;
4. record the failing in-scope stage, affected hashes, defects, and next concrete action;
5. keep the lifecycle status truthful;
6. do not delete rejected work required for continuation or audit.

## Git and pull-request lifecycle

- Do not push directly to `main`.
- Use one short-lived branch per coherent change, or continue the current branch for the same workstream.
- Commit only intended files.
- Push the branch and open a PR describing root cause, behavior change, impact, and validation.
- Merge after the Blender/topology/five-view/six-pose repository completion contract passes.
- Do not wait for Unity import/save/reload, Modular Avatar／NDMF, VRChat Build & Test, or VRChat runtime human review.
- Verify the resulting `main` contains the merged change.
- Delete the merged, closed, or superseded branch.
- Close superseded PRs with an explicit successor link.

Commit, push, or PR creation is not completion. Completion of repository integration means merged into verified `main` and the work branch removed after all in-scope gates pass.

## Final response contract

Report only verified facts:

- effective repository or product status;
- changed behavior and principal files;
- exact in-scope checks and outcomes;
- evidence links for visual work;
- commit, PR, merge, and branch-deletion state;
- remaining in-scope blockers or unverified boundaries.

Do not list Unity import/save/reload, Modular Avatar／NDMF, VRChat Build & Test, or VRChat runtime human review as pending work, blockers, or unfinished items. Do not substitute confidence, plans, artifact inventories, or workflow claims for proof on `main`.
