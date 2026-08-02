# image2outfit execution contract

This repository is both a working Unity project and an auditable, resumable garment-production pipeline. Agents must leave the repository in a state that another agent or developer can continue without reconstructing the product from scratch. Documentation, workflow success, or artifact existence alone is never a deliverable.

## Authority and scope

- The user request defines the product goal, target avatar, visual intent, and required deliverables.
- `config/job.schema.v2.json` defines the job contract.
- `config/genworks-handoff-policy.json` defines lifecycle and handoff requirements.
- `config/products/<slug>/job.json` and `license.json` define each tracked product.
- `Assets/GenWorks/OutfitCatalog.json` must reconcile configured products with their canonical workspaces.
- Common automation must remain product-neutral. Product-specific implementation needed to reproduce or continue a checkpoint is valid repository state when it is referenced by the job or manifest; do not delete it merely because it is product-specific.

## Canonical product workspace

Every active tracked outfit uses exactly one slug and one canonical root:

```text
config/products/<slug>/
  job.json
  license.json

Assets/GenWorks/<slug>/
  ProductManifest.json
  README.md
  Source/Blender/*.blend
  Models/*.fbx
  Prefab/*.prefab
  Materials/*
  Textures/*
  Previews/*
```

Rules:

- Do not introduce `Assets/GenWorks/Products/` or another intermediate product directory.
- Product Prefabs must be direct children of `Assets/GenWorks/<slug>/Prefab/`.
- `job.id`, the config directory name, `job.productRoot`, `job.productManifestPath`, `job.licenseEvidence`, delivery assets, and manifest product identity must agree.
- Preserve Unity `.meta` files and GUIDs when moving or replacing tracked assets.
- Keep private or licensed avatar sources under ignored roots such as `Assets/_Local/`, `Assets/_Vendor/`, `Assets/_Reference/`, or the job-declared private source roots.
- Never commit credentials, private avatar packages, caches, temporary trigger files, machine-local runtime state, or unreviewed customer release packages.
- Actions artifacts, `Artifacts/`, `Candidates/`, and `Release/` are transport or packaging outputs. They are not the canonical resumable work state.

## Resumable handoff is mandatory

The canonical workspace must always contain the latest useful, reproducible checkpoint, including work that is incomplete or rejected. A checkpoint normally includes:

- the editable Blender source;
- the exported FBX;
- materials and textures;
- the outfit Prefab;
- the avatar-integrated Prefab when required;
- the latest actual five-view and pose-review renders;
- `ProductManifest.json` with current status, exact gates, hashes, known defects, rejection reason, and next continuation step;
- every product-specific script or parameter required to reproduce the current state, referenced from the job or manifest.

Do not restart from zero when a checkpoint exists. Continue from the canonical workspace and the recorded diagnosis. Do not replace a usable checkpoint with a worse or incomplete one. When an iteration fails, retain the latest useful assets and record what failed, why it failed, and what must be tried next.

## Required production flow

1. Resolve the exact target avatar/profile, outfit specification, source references, slug, deliverables, and acceptance criteria.
2. Verify licensing and environment requirements from authoritative sources.
3. Inspect the existing canonical checkpoint and prior rejection history before generating anything.
4. Build or improve the garment in the canonical workspace rather than in an ephemeral branch-only or artifact-only location.
5. Export the FBX and create the required Unity Prefabs with materials, hierarchy, armature, constraints, and Modular Avatar or NDMF configuration where applicable.
6. Import the assets in the intended Unity version, save them, reload them, and verify serialized Prefab integrity.
7. Run the automated Blender, FBX, Unity import, Prefab serialization/reload, Modular Avatar, layout, and repository gates.
8. Render and inspect the actual product. Iterate on visible defects instead of treating render generation as success.
9. Update the manifest and commit the complete resumable checkpoint.
10. Stop at `HUMAN_REVIEW_PENDING` until the human visual, pose, and runtime review gates pass.
11. Promote the unchanged reviewed candidate with `task release JOB=<same-job-path>` only after every release gate passes.

Use:

```powershell
task candidate JOB=config/products/<slug>/job.json
task release JOB=config/products/<slug>/job.json
task audit:repo
task audit:genworks
task check:python
```

## Visual evidence and quality loop

Garment work is not complete without current visual evidence bound to the exact candidate or manifest hash.

Required evidence:

- front;
- back;
- left;
- right;
- three-quarter;
- combined multiview;
- pose-review views covering the required motions;
- Unity or VRChat runtime screenshots when the applicable gate requires them.

Agents must inspect the images themselves. File existence, image dimensions, CI success, or another agent's textual claim is insufficient. Reject and iterate when evidence shows clipping, body penetration, extreme vertices, broken silhouette, incorrect scale, poor fit, detached parts, UV stretching, visible seams, normal defects, material errors, floating hardware, broken weights, or pose failures.

The final chat report for garment production or audit must show or directly link the latest actual renders. Do not claim that appearance improved unless the new evidence visibly demonstrates the improvement.

## Lifecycle and completion language

Allowed product statuses are defined by `config/genworks-handoff-policy.json`.

- `WORKING`: a resumable tracked checkpoint exists, but technical gates are incomplete.
- `TECHNICAL_READY`: all required automated technical gates pass.
- `HUMAN_REVIEW_PENDING`: technical work, Unity configuration, and required evidence are ready for final human inspection.
- `REJECTED`: evidence or validation failed; preserve the checkpoint and diagnosis.
- `RELEASED`: all automated and human release gates pass for the unchanged candidate.

Report `NO-GO` for missing evidence, changed hashes, unresolved licensing, invalid imports, incomplete Prefab configuration, critical penetration, failed runtime validation, or visible unacceptable defects. Report `GO` or `RELEASED` only when the corresponding gate actually succeeds.

Do not use "complete", "finished", "production-ready", or equivalent language unless the work has been built, visually inspected, validated, committed, pushed, merged into `main`, verified on the resulting `main`, and accompanied by the latest renders. `HUMAN_REVIEW_PENDING` is not `RELEASED`.

## Git and pull-request lifecycle

- Continue an existing product checkpoint instead of opening unrelated rebuild branches.
- Use one short-lived branch per coherent change when a branch is needed.
- Keep commits scoped and include the assets, manifest, configuration, tests, and evidence required for the same checkpoint.
- A PR may be automatically merged only after its required checks and evidence gates pass and the diff contains the intended canonical state.
- Close superseded PRs with an explicit continuation pointer.
- Delete every non-`main` branch immediately after merge, closure, or supersession. Stale work branches are repository residue.
- Before reporting completion, verify that `main` contains the intended commit and that no unnecessary branch remains.

## GitHub Actions and automation

- Build and validation workflows should use the minimum required permissions; read-only workflows use `contents: read`.
- CI may upload generated products and evidence as artifacts, but artifacts must never be the only copy of resumable work.
- CI must not commit telemetry, run status, trigger markers, or mutable workflow state to `main`.
- Do not retain self-mutating or one-shot migration machinery after its validated purpose is complete.
- Hosted Blender workflows are suitable only when they can reproduce the declared job. Use self-hosted execution when Unity, private avatar sources, VRChat, or local runtime validation is required.
- Fix generic tooling and policy defects generically. Do not add one-product exceptions to bypass repository or quality gates.

## Repository hygiene

`tools/audit_repository_hygiene.py` is authoritative for repository residue, and `tools/audit_genworks_layout.py` is authoritative for the canonical product layout. Fix their findings rather than weakening them.

The repository must remain understandable from `main`: canonical product work under `Assets/GenWorks/<slug>/`, declared jobs under `config/products/<slug>/`, no hidden artifact-only handoff, no lost intermediate work, no false completion claim, and no abandoned branch.
