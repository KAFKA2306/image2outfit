# Pivot Hinge Dolman Set

Owned manufacturing workline: #551.

## Current artifacts
- Manufacturing reference: `References/pivot-hinge-dolman-manufacturing-sheet.svg`
- Pattern decomposition: `Source/Patterns/pattern-spec.json`
- Structural OBJ/MTL: `Source/Prototype/`
- Prototype evidence: `Evidence/Prototype/structural-validation.json`
- Canonical contracts: `config/products/siroino-pivot-hinge-dolman-set/`

## Hero Detail
Paired articulated elbow geometry: `hinge_gusset_L/R` and `hinge_facing_L/R`. These groups must survive the Blender build as real geometry and remain visually identifiable in render evidence.

## Evidence boundary
The tracked structural prototype is not Blender fit, rig/weight, render, Unity, Modular Avatar/NDMF, or VRChat evidence. Those layers remain `UNVERIFIED` until the corresponding runtime actually executes.

## Dependency / restart
This branch is stacked on the active shared-builder workline in PR #550 so it reuses `tools/generic_structural_garment_product.py` instead of adding a product-specific builder. Restart from `config/products/siroino-pivot-hinge-dolman-set/job.json`; once the shared builder is accepted on main, rebase/retarget and run the canonical candidate/Hosted Blender path for this exact product.
