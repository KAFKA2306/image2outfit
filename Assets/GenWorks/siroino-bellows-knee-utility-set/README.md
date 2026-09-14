# Bellows Knee Utility Set

Manufacturing workline: #553.

This workspace owns one Siroino-first VRChat outfit: cropped collarless utility vest, fitted inner, and tapered trousers with paired articulated Bellows Knee Gussets.

## Current evidence

- manufacturing reference: `References/bellows-knee-utility-set-manufacturing-sheet.svg`
- canonical job: `config/products/siroino-bellows-knee-utility-set/job.json`
- construction: `config/products/siroino-bellows-knee-utility-set/construction.json`
- pattern decomposition: `Source/Patterns/pattern-spec.json`
- structural OBJ/MTL prototype: `Source/Prototype/`
- exact prototype evidence: `Evidence/Prototype/structural-validation.json`

The structural checkpoint proves only the tracked prototype geometry, UV0, material separation and named Hero groups. Blender fit, deformation/weight quality, editable `.blend`, FBX, five-view/pose rendering, Unity, Modular Avatar, NDMF and VRChat runtime stay `UNVERIFIED` until those exact stages execute and retain evidence.

The job intentionally reuses `tools/generic_structural_garment_product.py` from the existing #550 workline. Do not add a Bellows-specific builder or a second pipeline authority.
