# AGENTS.md — execution instructions for AI agents

This file is an operating contract for LLM-based coding agents. It is not a project introduction. Read `README.md` for the human-facing overview; use this file to decide how to inspect, change, validate, and finish work.

## Objective

Leave `main` in a more correct, reproducible, inspectable, and resumable state than you found it.

This repository is both a Unity project and an auditable Blender-to-Unity/VRChat garment-production pipeline. A document, generated file, workflow run, artifact upload, or plausible explanation is not by itself a deliverable. Preserve the latest useful checkpoint so another agent or developer can continue without reconstructing the product from scratch.

## Instruction precedence

Use this order when instructions conflict:

1. the current user request and explicit acceptance criteria;
2. machine-readable contracts, schemas, tests, and executable gates;
3. the current product job and `ProductManifest.json`;
4. this `AGENTS.md`;
5. `README.md` and product prose.

Do not silently choose between conflicting sources. Follow the higher-authority source, repair stale lower-authority prose in the same change when practical, and report any unresolved conflict.

## Sources of truth

- `config/job.schema.v2.json` — job schema.
- `config/products/<slug>/job.json` — product build, validation, evidence, and delivery contract.
- `config/products/<slug>/license.json` — rights and redistribution boundary.
- `config/genworks-layout.json` — canonical Unity-visible layout.
- `config/genworks-handoff-policy.json` — lifecycle, checkpoint, and handoff rules.
- `config/release-policy.json` — customer-release evidence contract.
- `config/toolchain-lock.json` — supported tool versions and official sources.
- `Assets/GenWorks/<slug>/ProductManifest.json` — current product state, gates, hashes, defects, and continuation point.
- `Assets/GenWorks/OutfitCatalog.json` — catalog reconciliation.
- `Taskfile.yml` and `tools/manage.py` — supported operator entry points.

Never copy mutable values such as versions, thresholds, paths, or status into new prose when an authoritative contract already owns them. Link to or summarize the contract instead.

## Start-of-task protocol

Before editing:

1. identify whether the task is repository-wide, product-specific, validation-only, or release-related;
2. inspect the latest `main`, open PRs, related branches, and concurrent work that may overlap;
3. inspect the exact files named by the user rather than inferring their state from prior messages;
4. for product work, resolve the slug, job, manifest, target avatar, current checkpoint, rejection history, latest renders, and pending gates;
5. define the intended diff and the checks that will prove it correct;
6. preserve unrelated user changes and do not open a competing branch for the same workstream when an active branch should be continued.

Do not restart a product from zero when a usable canonical checkpoint exists. Continue from the recorded state and diagnosis.

## Documentation boundary

Repository-wide prose has exactly two owners:

- `README.md` explains the project to humans: purpose, concepts, setup, common commands, layout, and where to inspect results.
- this `AGENTS.md` tells LLM agents how to operate: precedence, investigation, change discipline, validation, evidence, Git lifecycle, and reporting.

Do not put agent-only completion rules, branching policy, prompt-like instructions, or internal decision procedures in `README.md`. Do not duplicate the human quick start or broad project explanation here.

Do not create a repository-level `docs/` tree, nested `AGENTS.md`, `.github/AGENTS.md`, `Assets/GenWorks/README.md`, or another general policy file. Product-specific human guidance belongs in `Assets/GenWorks/<slug>/README.md`; machine state belongs in `ProductManifest.json` and the product job.

When guidance moves, update references and tests and remove the superseded copy in the same change.

## Canonical product layout

Each tracked outfit, including incomplete and rejected checkpoints, has one slug and one canonical workspace:

```text
config/products/<slug>/
  job.json
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
  Demo/
  Editor/
  Tests/
  Documentation/
```

Follow `config/genworks-layout.json` if this summary becomes stale.

Mandatory constraints:

- never introduce `Assets/GenWorks/Products/`, avatar-grouping directories, or another intermediate product root;
- product Prefabs are direct children of `Assets/GenWorks/<slug>/Prefab/`;
- `Assets/GenWorks/Legacy/` and repository-root product generators are forbidden;
- common automation must remain product-neutral;
- product-specific scripts or parameters are valid only when required to reproduce or continue the checkpoint and referenced by the job or manifest;
- `pyproject.toml` is the only Python dependency declaration and `uv.lock` is the resolved lock;
- preserve Unity `.meta` files and GUIDs when moving tracked assets;
- keep private or licensed avatar sources under job-approved ignored roots;
- never commit credentials, caches, temporary triggers, machine-local state, private packages, or unreviewed customer release packages;
- Actions artifacts, `Artifacts/`, `Candidates/`, and `Release/` are transport or packaging outputs, not the sole canonical work state.

## Change discipline

Make the smallest coherent change that satisfies the request and repairs the underlying generic rule.

- Prefer modifying an existing generic path over adding a parallel path.
- Fix generic defects generically; do not add a one-product bypass to satisfy a gate.
- Remove obsolete implementation and references when replacing a mechanism.
- Keep jobs, manifests, catalog entries, paths, tests, assets, and documentation consistent in the same change.
- Do not weaken a check because current data fails it. Fix the data or explicitly preserve a truthful failing status.
- Do not replace a useful checkpoint with a worse or incomplete result.
- Do not claim a tool ran, a file was inspected, or a visual defect improved unless you directly verified it.

## Product-work protocol

For garment creation, repair, or continuation:

1. resolve the exact target avatar/profile, source references, visual intent, deliverables, slug, rights boundary, and acceptance criteria;
2. inspect the current Blend, FBX, Prefabs, materials, textures, manifest, scripts, and latest visual evidence;
3. preserve the last-good checkpoint before risky generation or migration;
4. build or improve work inside the canonical product workspace;
5. export the FBX and create the required outfit and integrated Unity Prefabs;
6. configure hierarchy, armature, materials, constraints, Modular Avatar/NDMF, and other job-required components;
7. import with the locked Unity version, save, reload, and verify serialized Prefab integrity;
8. run the applicable Blender, FBX, Unity, layout, repository, and policy gates;
9. render the current candidate and inspect the images directly;
10. iterate on visible defects rather than treating render generation as success;
11. update `ProductManifest.json` with exact hashes, status, gates, defects, rejection reason, and next step;
12. commit the complete resumable checkpoint.

Use the supported entry points:

```powershell
task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
task release PRODUCT=<slug>

task audit:repo
task audit:genworks
task audit:tools
task audit:methods
task audit:research
task check:python
```

`task candidate` does not authorize release. `task release` is valid only for the unchanged reviewed candidate with every required release gate satisfied.

## Visual inspection and evidence

Garment work is not complete without current evidence bound to the exact candidate or manifest hash.

At minimum, inspect:

- front;
- back;
- left;
- right;
- three-quarter;
- combined multiview;
- required pose-review images;
- Unity or VRChat runtime screenshots when required by the job or release policy.

File existence, dimensions, hashes, CI success, or another agent's text are not visual inspection. Open the actual images. Reject or iterate when they show clipping, body penetration, extreme vertices, broken silhouette, incorrect scale, poor fit, detached parts, UV stretching, visible seams, normal defects, material errors, floating hardware, broken weights, or pose failures.

The final report for garment work must directly link the latest actual evidence. Do not say appearance improved unless the new evidence visibly supports the claim.

## Lifecycle and truthful status

Allowed statuses come from `config/genworks-handoff-policy.json`:

- `WORKING` — a tracked resumable checkpoint exists, but technical gates remain incomplete.
- `TECHNICAL_READY` — required automated technical gates pass.
- `HUMAN_REVIEW_PENDING` — technical work and evidence are ready for human visual, pose, and runtime review.
- `REJECTED` — evidence or validation failed; preserve the checkpoint, diagnosis, and continuation point.
- `RELEASED` — all automated and human release gates pass for the unchanged candidate.

Use `NO-GO` for missing evidence, changed hashes, unresolved licensing, invalid imports, incomplete Prefab configuration, critical penetration, failed runtime validation, or unacceptable visible defects.

Do not use `complete`, `finished`, `production-ready`, `GO`, or `RELEASED` unless the corresponding gates actually passed and the exact work is present on verified `main`.

## Validation selection

Run checks proportional to the diff, then run the repository contract checks expected by CI.

For documentation-only changes, at minimum verify documentation contracts and repository hygiene. For generic Python or configuration changes, run `task check:python`. For layout changes, run `task audit:genworks`. For product changes, run the product-specific candidate flow and inspect generated evidence. For release changes, run the release flow only after the human evidence contract is satisfied.

If a required local tool is unavailable, do not invent a PASS. Run every available static check, use CI where appropriate, and report the exact unverified boundary.

## Git and pull-request lifecycle

- Do not push directly to `main`.
- Use one short-lived managed branch per coherent change, or continue the existing branch for the same workstream.
- Stage and commit only intended files.
- Push the branch, open a PR, and ensure its description states what changed, why, impact, and validation.
- Merge only after required checks pass and the diff contains the intended canonical state.
- After merge, verify the resulting `main` contains the intended commit and files.
- Delete the merged, closed, or superseded branch. Do not leave stale non-`main` branches.
- Close superseded PRs with an explicit pointer to the successor.

A task is not operationally finished at commit, push, or PR creation. Finish means merged into `main`, verified there, and the work branch removed.

## GitHub Actions and automation

- `.github/` contains reusable workflows and GitHub metadata, not a second policy hierarchy.
- Use minimum required permissions; read-only jobs use `contents: read`.
- CI may upload generated products and evidence, but artifacts must not be the only resumable copy.
- Do not commit telemetry, run state, trigger markers, mutable workflow state, or one-shot migration machinery to `main`.
- Use hosted Blender only for jobs reproducible without private sources or Unity/runtime state.
- Use self-hosted execution when Unity, licensed avatars, VRChat, or local runtime validation is required.

## Failure recovery

When generation, migration, validation, or release fails:

1. preserve or restore the last-good canonical checkpoint;
2. retain any useful new evidence separately from accepted outputs;
3. record what failed, why, affected hashes/paths, and the next concrete action;
4. set a truthful lifecycle status;
5. do not overwrite an existing release or accepted candidate with a failed attempt;
6. do not delete rejected work that is needed for continuation or audit.

## Final response contract

Report only verified facts. Include:

- the effective result and truthful product/repository status;
- changed files and the behavioral difference;
- checks run and their exact outcomes;
- evidence links for visual work;
- commit, PR, merge result, and branch deletion state;
- remaining blockers or unverified boundaries.

Do not substitute a plan, confidence statement, or artifact list for proof that the requested state exists on `main`.
