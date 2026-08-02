# GitHub automation

`.github/` contains reusable repository automation and its operating documentation. GitHub Actions is the execution log and evidence transport; it is **not** the canonical storage location for product work.

## Canonical work state

The canonical, resumable state of every product is tracked under:

`Assets/GenWorks/<product-id>/`

A run must not leave the only usable result inside an Actions artifact. Before work is handed to another agent or person, the product workspace must contain the latest reproducible checkpoint, including all applicable files below:

- product manifest and implementation notes
- Blender source and product-specific source/generator entry point
- FBX, textures, materials, and metadata
- outfit Prefab
- integrated target-avatar Prefab
- Unity component and serialized settings required by the product, including Modular Avatar/NDMF, constraints, PhysBones, colliders, materials, menus, parameters, or animation assets when applicable
- demo/test scene or automated Unity verification entry point
- five-view renders, pose renders, and technical audit evidence

Temporary caches, private avatar packages, credentials, and machine-local paths remain under ignored local/vendor roots. They must not be copied into the tracked product workspace.

## State boundary

Product manifests use an explicit lifecycle:

1. `WORKING` — tracked and resumable, but one or more automated gates are incomplete.
2. `TECHNICAL_READY` — Blender generation, FBX validation, Unity import/save/reload, Prefab serialization, required Unity component setup, and automated integration checks have passed.
3. `HUMAN_REVIEW_PENDING` — technically complete and awaiting final visual, pose, and VRChat runtime inspection.
4. `RELEASED` — the exact unchanged technical checkpoint has passed the required human reviews and release gate.
5. `REJECTED` — retained as a diagnosable checkpoint with the rejection reason; it is not silently discarded or rebuilt from zero.

Final human Unity/VRChat review is the release boundary. It is not a reason to omit the Prefab, integrated Prefab, Unity settings, or other resumable technical work from `Assets/GenWorks`.

## Product pipeline workflows

- `workflows/build-product-hosted.yml`: generic Blender generation and render evidence for a product job.
- `workflows/build-product-self-hosted.yml`: generic private-target, Unity, Modular Avatar/NDMF, Prefab, and candidate verification.
- release-policy workflows: promote an unchanged `HUMAN_REVIEW_PENDING` checkpoint only after hash-bound human evidence passes.

Workflows may upload logs and candidate bundles, but they do not replace the tracked GenWorks checkpoint. A successful technical run is committed through the normal branch/PR process, not by a self-mutating workflow.

## Repository policy

- GitHub Actions runtime state belongs in the Actions UI and uploaded logs, not `.github/run/` or `.github/status/`.
- One-shot orchestration is removed after use; reusable implementation remains in generic tooling or the owning product workspace.
- Generic orchestration belongs in `.github/workflows/`; product-specific build logic belongs with the product source or a clearly referenced product entry point.
- Do not start a new product branch from zero when a tracked `WORKING`, `TECHNICAL_READY`, or `REJECTED` checkpoint exists. Read the manifest, inspect the latest Prefabs and renders, and continue from that exact state.
- `TECHNICAL_READY` cannot be claimed while Unity import, Prefab serialization/reload, or required Unity component setup is pending.
- `RELEASED` cannot be claimed until the final human visual, pose, and VRChat runtime reviews pass for the unchanged candidate hash.
