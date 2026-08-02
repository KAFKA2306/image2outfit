# GitHub automation

This directory contains durable repository automation only. Temporary run state, one-shot migrations, and historical product-specific generators must not be committed here.

## Product pipeline workflows

- `workflows/e2e-self-hosted.yml`: generic schemaVersion 2 candidate build for a local job file.
- `workflows/siroino-wide-cargo-hosted.yml`: Blender modeling and preview generation for the current Siroino product.
- `workflows/siroino-wide-cargo-self-hosted.yml`: Unity, Modular Avatar, VRChat Build & Test, runtime capture, and candidate evidence.
- `workflows/siroino-wide-cargo-release.yml`: promotion of an unchanged reviewed candidate after all human evidence gates pass.

These workflows are started through `workflow_dispatch`. Do not add marker files under `.github/run/` merely to trigger a workflow.

## Repository policy

- GitHub Actions run state belongs in the Actions UI and uploaded artifacts, not committed JSON files.
- One-shot migrations are removed after completion. Their reusable implementation remains under `tools/` and `Taskfile.yml`.
- Historical assets under `Assets/GenWorks/Legacy/Snapshots/` are not active products and do not require permanent product-specific workflows.
- Generated customer-facing assets may be committed only by the active product pipeline after its technical gates pass.
- Workflow changes must preserve the candidate/review/release boundary defined by `tools/release_gate.py`.
