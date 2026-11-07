# image2outfit execution contract

This repository is a working Unity project and an auditable product pipeline. Automation must produce verifiable assets, not only documentation or status notes.

## Product neutrality

- Never assume a specific avatar, adapter, garment, or product ID.
- Resolve the target from the user request and the selected schemaVersion 2 job.
- Tracked jobs belong at `config/products/<product-id>/job.json`.
- Private or machine-local jobs belong at `Assets/_Local/Jobs/<job-id>/job.json`.
- Common workflows, tasks, tests, and global configuration must not hard-code a product ID.

## Required flow

1. Resolve the target avatar, outfit specification, source references, product ID, and deliverables.
2. Verify authoritative licensing and environment requirements.
3. Keep private sources under ignored roots such as `Assets/_Local/`, `Assets/_Vendor/`, and `Assets/_Reference/`.
4. Keep current product assets under `Assets/GenWorks/Products/<product-id>/`.
5. Keep historical snapshots only under `Assets/GenWorks/Legacy/Snapshots/`.
6. Do not commit credentials, private avatar packages, local review evidence, workflow state, trigger markers, caches, candidates, or releases.
7. Preserve Unity `.meta` files and GUIDs when moving tracked assets.
8. Build a technical candidate with `task candidate JOB=<job-path>`.
9. A successful technical build must stop at `REVIEW_REQUIRED` and must not create a customer release.
10. Bind visual, pose-penetration, and VRChat runtime evidence to the exact candidate manifest SHA-256.
11. Promote the unchanged reviewed candidate with `task release JOB=<same-job-path>`.
12. Report `GO` or `RELEASED` only when the release gate succeeds. Missing evidence, changed hashes, rights uncertainty, invalid import, critical penetration, or failed runtime validation is `NO-GO`.
13. Garment production and audit reports must include actual multiview, pose review, and runtime screenshots when required.

## Job and product boundary

`config/job.schema.v2.json` is the only source of required fields.

```text
config/products/<product-id>/
  job.json
  license.json
```

The directory name, `job.id`, `job.productRoot`, `job.productManifestPath`, and `job.licenseEvidence` must agree. Product outputs belong in `Assets/GenWorks/Products/<product-id>/`; local avatar sources and human evidence remain outside it.

## GitHub Actions

- CI uses `contents: read` for build and validation workflows.
- Generated products and evidence are uploaded as Actions artifacts.
- CI must not commit run status, trigger markers, generated model revisions, or telemetry to `main`.
- Use `Build product with hosted Blender` for tracked product jobs when hosted Blender is sufficient.
- Use self-hosted candidate/release workflows when Unity, local avatar sources, or VRChat validation is required.

## Repository hygiene

```powershell
task audit:repo
task audit:genworks
task check:python
```

`tools/audit_repository_hygiene.py` is authoritative for repository-level residue. Fix findings instead of adding one-product exceptions.

One-time migration workflows and their scripts must be deleted in the same change that completes the migration. A tracked one-time workflow that pushes to `main` is a hygiene finding, not a retained tool.

## Agent operating model

- The main agent owns judgment and direct edits. Subagents are used only for independent work that can run in parallel or for heavy research that would otherwise crowd the main context.
- Every subagent receives the documents to read, the files it may edit, and the verification command. The main agent reads the result and verifies it before accepting it.
- Completion is judged by command output or artifacts, not by an agent's self-report.
- Harness or procedure changes are accepted only after comparing the old and new versions on a fixed check set, judged by score and stability (downside and spread across items), not by a single run.
- Agents commit completed and verified changes on a working branch without asking. Caches, `__pycache__`, generated candidates, and local evidence are never committed.
- Agents merge verified work into `main`, push, upload, and publish as obligations. If a tool-side permission check denies an operation, the agent reports the denial and does not work around it.
- Agents do not delete user data without confirmation from the user.
- Automation may skip human review only where this file does not require it. Visual, pose-penetration, and runtime review evidence, and rights confirmation, remain required gates for release.

Do not claim completion for work that was not built, rendered, validated, committed, and pushed.
