# AGENTS.md — execution instructions for AI agents

This file is the operating contract for LLM-based coding agents. Read `README.md` for the human-facing explanation. Use this file to decide how to inspect, change, validate, publish, and finish work.

## Objective

Leave verified `main` in a more correct, reproducible, inspectable, and resumable state than you found it.

A generated file, workflow artifact, plausible explanation, or passing syntax check is not a product result. Garment work requires an editable checkpoint, current technical evidence, current visual evidence, and a truthful lifecycle state.

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
- `config/genworks-handoff-policy.json` — repository merge, checkpoint, technical-ready, and release boundary.
- `config/release-policy.json` — required views, required poses, evidence kinds, metrics, and release thresholds.
- `Assets/GenWorks/<slug>/ProductManifest.json` — current state, gates, defects, hashes, and continuation point.
- `tools/production_contract.py` — shared job, construction, product-state, and hashed-artifact validation.
- `tools/workspace_transaction.py` — last-good protection for canonical product workspaces.
- `tools/runtime_transaction.py` — last-good protection for derived candidate and release directories.
- `tools/customer_quality.py` — the only human/customer release validator.
- `tools/release_packager.py` — release packaging with raw evidence and hashes.
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

1. classify the task as repository-wide, product-specific, validation-only, or release-related;
2. inspect current `main`, open PRs, branches, the exact requested files, and overlapping work;
3. for product work, resolve the slug, job, construction contract, target avatar, manifest, last-good checkpoint, latest renders, current defects, and pending gates;
4. define the smallest coherent diff and the checks that will prove it;
5. preserve unrelated work and continue an existing workstream branch instead of creating a competing one.

Do not restart from zero when a useful canonical checkpoint exists.

## Change discipline

- Fix generic defects generically. Do not add a one-product bypass.
- Prefer one owner over synchronization between duplicate mechanisms.
- Remove superseded code and references when replacing a mechanism.
- Keep jobs, construction contracts, manifests, assets, tests, policies, and documentation consistent in the same change.
- Do not weaken a gate because current data fails it.
- Do not replace a useful checkpoint with a failed or incomplete result.
- Do not claim that a tool ran, an image was inspected, or a defect improved without direct verification.

## Candidate workflow

Use:

```powershell
task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
```

The full candidate workflow must:

1. fully validate the closed job schema and construction schema;
2. bind the declared construction profile to current policy and research coverage;
3. snapshot the canonical `Assets/GenWorks/<slug>/` workspace before generation;
4. protect previous derived candidate and release state;
5. run Blender, FBX, Unity import/save/reload, Modular Avatar／NDMF, preview, and applicable technical checks when those tools are available;
6. reject explicit technical `FAIL` or fit-audit failure recorded in `ProductManifest.json`;
7. verify every required view and every policy-required pose;
8. reject duplicate pose images used as evidence for multiple poses;
9. bind inputs, generated files, research baseline, construction contract, and pose files to the candidate manifest by SHA-256;
10. restore the last-good canonical workspace and previous candidate when any required stage fails.

A candidate result is `REVIEW_REQUIRED`, not release approval.

## Repository merge boundary

Repository merge and customer release are separate gates.

A garment checkpoint may be merged to `main` without Unity when every item in `requiredMergeCheckpointGates` from `config/genworks-handoff-policy.json` is verified. The checkpoint must include the editable Blender source, FBX, declared Unity Prefab assets, current five-view evidence, required pose evidence, and the recorded research trial. It must remain truthfully marked `WORKING`, and Unity, Modular Avatar／NDMF, VRChat runtime, and human runtime review must remain explicitly pending.

Missing Unity is therefore not a repository-merge blocker. It is a blocker for `TECHNICAL_READY`, `HUMAN_REVIEW_PENDING`, `GO`, `RELEASED`, customer delivery, and any claim that the Prefab works in Unity or VRChat.

Do not merge when a pre-Unity gate fails, current renders visibly fail the requested checkpoint acceptance criteria, evidence is stale or missing, or the canonical workspace would regress. Do not invent Unity results merely to advance lifecycle status.

## Human evidence and release workflow

Use:

```powershell
task release PRODUCT=<slug>
```

Release uses `tools/customer_quality.py` once. Do not call or recreate a legacy release validator.

Every human evidence document must:

- match the exact candidate manifest SHA-256;
- be checked after candidate creation;
- identify a human reviewer;
- include an auditable GitHub PR review URL in `reviewerReference`;
- list the exact candidate assets inspected;
- record defects with severity, status, description, and evidence paths;
- satisfy the visual, pose penetration, or VRChat runtime contract in `release-policy.json`.

Commercial evidence must contain a structured tool identity and command, metrics, notes, and source artifacts represented as `{path, sha256}`. Each source artifact hash must be present in the candidate manifest.

The release package must include:

- the unchanged candidate;
- raw human evidence JSON;
- the runtime screenshot referenced by the runtime review;
- commercial evidence JSON;
- validated evidence summaries;
- release manifest and SHA-256 values;
- the distribution ZIP.

Do not use `GO`, `RELEASED`, `complete`, or `production-ready` unless the exact candidate passes every required technical, commercial, human, and runtime contract.

## Visual inspection

Garment checkpoint work is not mergeable without opening the current pre-Unity evidence:

- front;
- back;
- left;
- right;
- three-quarter;
- combined multiview;
- every required pose.

Unity or VRChat runtime screenshots are additionally required for technical-ready and release states, but not for a truthfully labelled pre-Unity `WORKING` merge.

File existence, dimensions, hashes, CI success, or another agent's text is not visual inspection. Reject or iterate on body penetration, clipping, detached geometry, wrong scale, broken silhouette, extreme vertices, UV stretching, visible seams, normal errors, material defects, floating hardware, broken weights, pose failure, or runtime failure.

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

For product changes, run every available pre-Unity build and evidence check and inspect the generated images. Run the full product candidate workflow when Unity is available. For release changes, test both rejection and successful packaging paths.

If Blender, Unity, a private avatar, or VRChat runtime is unavailable, report the exact unverified boundary. Never invent a PASS. Unity absence does not block a `WORKING` merge when the machine-readable pre-Unity merge contract passes.

## GitHub Actions

Read-only workflow jobs use `contents: read`. Request write permissions only for the narrow mutation that requires them. CI artifacts may carry reports and generated candidates, but they are not the sole resumable checkpoint.

## Failure recovery

On generation, migration, validation, or release failure:

1. restore the last-good canonical workspace;
2. restore the previous valid candidate or release;
3. retain useful failed-run diagnostics separately;
4. record the failing stage, affected hashes, defects, and next concrete action;
5. keep the lifecycle status truthful;
6. do not delete rejected work required for continuation or audit.

## Git and pull-request lifecycle

- Do not push directly to `main`.
- Use one short-lived branch per coherent change, or continue the current branch for the same workstream.
- Commit only intended files.
- Push the branch and open a PR describing root cause, behavior change, impact, and validation.
- A truthfully labelled `WORKING` garment checkpoint may merge after the pre-Unity merge contract passes; Unity is required only for later lifecycle states and release.
- Merge only after the required gates for the claimed lifecycle state pass and the intended canonical state is present.
- Verify the resulting `main` contains the merged change.
- Delete the merged, closed, or superseded branch.
- Close superseded PRs with an explicit successor link.

Commit, push, or PR creation is not completion. Completion of repository integration means merged into verified `main` and the work branch removed. Product release remains a separate later condition.

## Final response contract

Report only verified facts:

- effective repository or product status;
- changed behavior and principal files;
- exact checks and outcomes;
- evidence links for visual work;
- commit, PR, merge, and branch-deletion state;
- remaining blockers or unverified boundaries.

Do not substitute confidence, plans, artifact inventories, or workflow claims for proof on `main`.
