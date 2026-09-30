# Latchfold Wrap Shirt Set

Technical manufacturing checkpoint for Issue #537.

The locked outfit is a cropped asymmetric wrap shirt, fitted inner top and high-waist tapered trousers for Siroino. Product identity is the three real `latch_A` / `latch_B` / `latch_C` fold shells and their three independently named facings along the front wrap edge.

## Current evidence

- Manufacturing reference: `References/latchfold-wrap-shirt-set-manufacturing-sheet.svg`
- Construction authority: `config/products/siroino-latchfold-wrap-shirt-set/construction.json`
- Siroino license evidence: `config/products/siroino-latchfold-wrap-shirt-set/license.json`
- Pattern decomposition: `Pattern/latchfold-wrap-shirt-set-pattern.json`
- Structural prototype: `Prototype/latchfold-wrap-shirt-set-prototype.obj`
- Prototype materials: `Prototype/latchfold-wrap-shirt-set-prototype.mtl`
- Hash-bound validation: `Evidence/prototype-validation.json`

The structural OBJ checkpoint has 76 vertices, 76 UV coordinates, 19 polygon faces, 19 named groups, four semantic material roles, six Hero groups and zero degenerate faces. Its SHA-256 is `3a17dc6168fcd593b99569de4a091bbd7af8f1a10b051bcbc0b753160ff3e76c`.

## Verification boundary

PASS currently means only the persisted manufacturing image, construction/license contracts, pattern decomposition, UV-bearing structural prototype, named Hero geometry and exact-hash prototype validation.

`job.json`, Blender fit/build, rig/weight, editable blend, FBX, five-view render, six required poses, Unity integration, Modular Avatar/NDMF and VRChat runtime remain UNVERIFIED. Current main exposes generic orchestration (`run_garment_pipeline.py`, `run_product_build.py`, `run_product_execution.py`) but the inspected executable builders are garment-specific. Do not bind this product to an unrelated product builder or add a second one-off authority merely to make the pipeline green.

Resume by proving a reusable repository-owned build entrypoint appropriate for this panel set, then create the canonical schema-valid product job and execute the exact candidate.
