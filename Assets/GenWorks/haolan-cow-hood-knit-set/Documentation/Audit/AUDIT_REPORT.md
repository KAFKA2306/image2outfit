# HAOLAN Cow Hood Knit Set v1.2 — Visual and Product Audit

## Decision

**NO-GO for customer/product release.**

The generated static asset reproduces the requested design language: cow-print cat hood, cropped knit top, sheer cut-out bodysuit, detached bell sleeves, pleated mini skirt, collar/heart hardware, and a soft tail. The committed WebP is an actual render of the generated geometry fitted to the audited HAOLAN-derived fit profile, not a concept illustration.

The asset is not yet allowed to be described as a finished HAOLAN product because this execution environment cannot run Unity 2022.3.22f1, VRChat SDK Build & Test, or animated in-headset review.

## Static visual audit

| Gate | Result | Evidence |
|---|---:|---|
| Overall silhouette matches reference | PASS | Four-view actual-mesh WebP |
| Cat hood and ear silhouette | PASS | Hood clears the static head/hair envelope in the audit render |
| Cow-print material separation | PASS | Procedural albedo/normal/roughness textures included |
| Sheer center bodysuit and side cut-outs | PASS | Separate alpha material and open side topology |
| Detached oversized sleeve silhouette | PASS | Bell sleeves, fuzzy upper cuffs, ribbed wrist cuffs |
| Pleated mini-skirt silhouette | PASS | 16-fold radial pleat profile |
| Static T-pose fit | PASS WITH WARNINGS | Parametric clearance and nearest-vertex metrics in `audit.json` |
| Animated clipping | NOT RUN | Unity/VRChat required |
| Hair/hood production compatibility | NOT RUN | Hair hide/mask or alternate hood variant must be validated |
| Product-level release | **NO-GO** | Runtime gates remain open |

## Geometry

- Mesh objects: 24
- Vertices: 18,394
- Triangles: 34,778
- Materials: 5
- HAOLAN-compatible bones included: 16
- Maximum bone influences: 3

## Required release gates

1. Import into Unity 2022.3.22f1 and confirm all 19 skinned meshes, materials, and external textures resolve.
2. Install on `HAOLAN_Lowpoly Variant.prefab`; confirm armature merge and bone binding after save/reload.
3. Test elbows, wrists, shoulders, spine bend, hip flexion, seated pose, and full-body crouch for clipping.
4. Decide hood hair handling: compatible hair presets, hair hide blend shape, or hood-off toggle.
5. Run VRChat SDK Build & Test and inspect alpha sorting, mipmaps, outline/shader behavior, and Quest fallback.
6. Capture Unity Game View and in-headset evidence. Only then change `decision` to `GO`.

## Rights boundary

The licensed HAOLAN source files are not included. The committed FBX is original parametric garment geometry fitted from measurements and uses compatible bone names/bind data. Credit the HAOLAN creator as required by the avatar terms: **かなﾘぁさんち / HAOLAN**.
