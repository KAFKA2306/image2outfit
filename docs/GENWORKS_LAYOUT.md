# GenWorks asset layout

`Assets/GenWorks` is the canonical Unity-visible root for every current product, shared Unity tool, and preserved inspection snapshot.

```text
Assets/GenWorks/
  Products/<product-id>/
    ProductManifest.json
    README.md
    Source/Blender/
    Models/
    Textures/
    Materials/
    Prefabs/Outfit/
    Prefabs/Integrated/<target-avatar>/
    Previews/
    Demo/
    Editor/
    Tests/
    Documentation/
  Shared/
    Editor/
    Materials/
    Shaders/
    Templates/
    Validation/
  Legacy/Snapshots/
```

Current products remain self-contained under their product root. Shared assets are permitted only when genuinely reused. Project-owned Unity Editor tooling belongs in `Assets/GenWorks/Shared/Editor/`; repository-root `Assets/Editor/` is forbidden.

`Assets/GenWorks/Legacy/Snapshots/` is the only Unity-visible historical root. Deprecated publication-style snapshot roots are forbidden. Legacy snapshots are evidence-only and cannot be promoted automatically.

## Product configuration

```text
config/products/<product-id>/
  job.json
  license.json
```

The directory name, `job.id`, `job.productRoot`, `job.productManifestPath`, and `job.licenseEvidence` must agree. Product-specific JSON files are forbidden directly under `config/`.

## Inspection and maintenance

Open `GenWorks > Product Catalog` in Unity to inspect current products.

```powershell
task audit:repo
task audit:genworks
task maintenance:migrate:genworks
task maintenance:migrate:genworks:apply
task audit:snapshot SNAPSHOT=<snapshot-path> SOURCE=<local-source-path>
task package:snapshot SNAPSHOT=<snapshot-path>
```

`tools/audit_repository_hygiene.py` rejects committed workflow state, self-mutating workflows, product-specific global configuration, and hard-coded product workflows or tasks. `tools/audit_genworks_layout.py` validates manifest identity, product containment, duplicate IDs, missing assets, forbidden roots, and production assets outside the canonical root.

## Distribution boundary

Private or licensed sources remain outside product roots:

```text
Assets/_Local/
Assets/_Vendor/
Assets/_Reference/
```

Integration Prefabs may reference local assets for developer verification, but release allowlists contain only files the customer is permitted to receive.
