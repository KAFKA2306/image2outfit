# GenWorks asset layout

`Assets/GenWorks` is the canonical Unity-visible root for every image2outfit product and preserved inspection asset. The layout separates customer-facing files, developer sources, integration proofs, legacy snapshots, and shared tooling while keeping licensed avatar files outside the distributable product tree.

## Canonical structure

```text
Assets/GenWorks/
  Products/
    <product-slug>/
      ProductManifest.json
      README.md
      Source/Blender/
      Models/
      Textures/
      Materials/
      Prefabs/
        Outfit/
        Integrated/<target-avatar>/
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
  Legacy/
    Published/
      LegacyManifest.json
      <historical snapshots>/
```

A current product must remain self-contained under its own root. Shared assets are allowed only when they are genuinely reused by multiple products and have a stable compatibility contract.

`Assets/GenWorks/Legacy/Published/` is intentionally Unity-visible so developers can inspect historical FBX, Prefab, textures, previews, and audit evidence without leaving the Project window. Legacy snapshots are not current products, do not receive a `ProductManifest.json`, and cannot be promoted automatically to a customer release.

## Unity inspection

Open `GenWorks > Product Catalog` in Unity. The window reads each current product `ProductManifest.json`, shows the product state and target adapter, validates that paths remain inside the product root, and provides direct buttons for:

- outfit Prefab
- target-avatar integrated Prefab
- representative preview
- demo scene
- installation or product documentation
- product folder and manifest

Historical snapshots are inspected directly under `Assets/GenWorks/Legacy/Published/`. This keeps them available to Unity without presenting them as saleable products.

## Existing jobs and assets

Run a dry-run first:

```powershell
task migrate:genworks
```

Apply the migration after reviewing the JSON plan:

```powershell
task migrate:genworks:apply
```

The migration scans `Assets/_Local/Jobs/**/job.json`, moves existing generated deliverables into the corresponding product root, moves Unity `.meta` files together with assets to preserve GUIDs, rewrites job paths, and creates a product manifest. Private avatar sources and license evidence are not moved.

The former repository-root `Published/` snapshot tree is preserved under `Assets/GenWorks/Legacy/Published/`. Existing file blobs and committed Unity `.meta` files are retained so historical evidence and asset GUIDs are not rewritten merely because the directory changed.

## Audit

```powershell
task audit:genworks
```

`tools/audit_genworks_layout.py` validates manifest identity, product-root containment, duplicate product IDs, missing referenced assets, and production-like assets that still live outside the canonical root. The machine-readable contract is `config/genworks-layout.json`.

## Distribution boundary

The following stay outside product roots and must not enter a customer package:

```text
Assets/_Local/
Assets/_Vendor/
Assets/PochibyKT/
Assets/HAOLAN_Quest/
```

Target-avatar integration Prefabs may reference local avatar assets for developer verification, but the release allowlist must contain only the outfit product files that the customer is permitted to receive. Legacy snapshots remain evidence-only until they are rebuilt as a current product and pass all mandatory review and runtime gates.
