# Moonlit Suspension Parka Set

Issue: #549

Single-outfit manufacturing workline for Siroino. The locked product is an oversized short tech parka, fitted inner, utility shorts, and two long bounded Suspension Rails. The reference image is preserved under `References/` and is manufacturing input, not completion evidence.

Current tracked structural prototype: 64 vertices / 64 UV coordinates / 16 polygon faces / 16 named groups / 4 material roles. Hero geometry is `suspension_rail_L`, `suspension_rail_R`, `rail_anchor_L`, and `rail_anchor_R`.

The canonical job is `config/products/siroino-moonlit-tech-parka-outfit/job.json`. It uses the existing `tools/run_product_build.py` launcher and delegates to the reusable `tools/generic_structural_garment_product.py` builder. That builder imports the tracked prototype and the real target FBX, transfers body weights by nearest-face interpolation, adds bounded shell thickness, saves an editable blend, exports FBX, and writes Blender evidence. Fit/render/Unity/VRChat remain UNVERIFIED until their actual runtime gates execute.

Do not replace this product with another SKU when a runtime layer fails. Resume from the evidence recorded in Issue #549.
