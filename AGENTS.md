# image2outfit execution contract

This repository is a working Unity project and an auditable product pipeline. Repository automation must produce verifiable assets, not only documentation or status notes.

## Product neutrality

- Never assume a specific avatar, adapter, garment, or product ID.
- Resolve the target from the user request and the selected schemaVersion 2 job.
- A tracked product job belongs at `config/products/<product-id>/job.json`.
- A private or machine-local job belongs at `Assets/_Local/Jobs/<job-id>/job.json`.
- Common workflows, Taskfile tasks, tests, and global configuration must not hard-code a product ID.

## Required flow

1. Resolve the target avatar, outfit specification, source references, product ID, and requested deliverables.
2. Verify the authoritative avatar page, license, supported Unity/SDK versions, and required shaders. Store only evidence needed for the audit.
3. Keep private or licensed source files under ignored roots such as:
   - `Assets/_Local/`
   - `Assets/_Vendor/`
   - `Assets/_Reference/`
4. Keep current product assets under:
   - `Assets/GenWorks/Products/<product-id>/`
5. Keep historical, non-release snapshots only under:
   - `Assets/GenWorks/Legacy/Snapshots/`
6. Do not commit credentials, private avatar packages, local review evidence, workflow status snapshots, trigger marker files, caches, candidates, or releases.
7. Reusable product assets and source generators may be tracked when their license permits redistribution. Preserve Unity `.meta` files and GUIDs when moving tracked assets.
8. Build a technical candidate with:
   - `task candidate JOB=config/products/<product-id>/job.json`, or
   - `task candidate JOB=Assets/_Local/Jobs/<job-id>/job.json`
9. A successful technical build must stop at `REVIEW_REQUIRED`. It must not create a customer release.
10. Bind visual, pose-penetration, and VRChat runtime evidence to the exact candidate manifest SHA-256.
11. Promote the unchanged reviewed candidate with:
   - `task release JOB=<same-job-path>`
12. Report `GO` or `RELEASED` only when the release gate succeeds. Missing evidence, changed hashes, rights uncertainty, invalid import, critical penetration, or failed runtime validation is `NO-GO`.
13. Every garment production or audit report must include the actual rendered appearance: multiview, pose review, and runtime screenshot when required. Do not report visual acceptance without the image evidence.

## job.json

`config/job.schema.v2.json` is the only source of required fields. Do not duplicate a separate schema in instructions or workflows.

A tracked product configuration has this boundary:

```text
config/products/<product-id>/
  job.json
  license.json
```

The following values must agree:

- directory name
- `job.id`
- `job.productRoot`
- `job.productManifestPath`
- `job.licenseEvidence`

Product outputs belong in `Assets/GenWorks/Products/<product-id>/`. Local avatar sources and human evidence must remain outside that product root.

## GitHub Actions

- CI must use `contents: read` unless a reviewed repository-change workflow explicitly requires otherwise.
- CI must upload generated products and evidence as Actions artifacts.
- CI must not commit run status, query results, trigger markers, generated model revisions, or telemetry to `main`.
- Use `Build product with hosted Blender` for a tracked product job when GitHub-hosted Blender generation is sufficient.
- Use the self-hosted candidate and release workflows when Unity, local avatar sources, or VRChat validation is required.

## Repository hygiene

Run before publishing changes:

```powershell
task audit:repo
task audit:genworks
task check:python
```

`tools/audit_repository_hygiene.py` is authoritative for repository-level residue. Fix findings instead of adding exceptions for one product.

## Final response

When repository code changes, report:

- decision and current gate state
- actual render evidence paths when visual work is involved
- affected product/job paths
- validation results
- commit and pull request

Do not claim completion for work that was not built, rendered, validated, committed, and pushed.
