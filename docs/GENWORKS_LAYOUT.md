# GenWorks asset layout

`Assets/GenWorks` is the canonical Unity-visible root for every image2outfit product and preserved inspection asset. The layout separates customer-facing files, developer sources, integration proofs, legacy snapshots, and shared tooling while keeping licensed avatar files outside the distributable product tree.

## Canonical structure

```text
Assets/GenWorks/
  Products/
    <product-id>/
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
    Snapshots/
      LegacyManifest.json
      <historical snapshots>/
```

A current product must remain self-contained under its own root. Shared assets are allowed only when they are genuinely reused by multiple products and have a stable compatibility contract.

Project-owned Unity Editor tooling belongs in `Assets/GenWorks/Shared/Editor/`. The repository-root Unity folder `Assets/Editor/` is forbidden so that image2outfit code has one canonical maintenance location. Moving an existing editor script must preserve its `.meta` file and GUID.

`Assets/GenWorks/Legacy/Snapshots/` is the only Unity-visible historical snapshot root. Repository-root `Published/` and `Assets/GenWorks/Legacy/Published/` are deprecated and forbidden. Legacy snapshots are not current products, do not receive a `ProductManifest.json`, and cannot be promoted automatically to a customer release.

## Product configuration

Every tracked product has a matching configuration directory outside Unity assets.

```text
config/products/<product-id>/
  job.json
  license.json
```

The directory name, `job.json` ID, `Assets/GenWorks/Products/<product-id>` root, product manifest path, and license evidence path must agree. Product-specific JSON files are forbidden directly under `config/`.

## Unity inspection

Open `GenWorks > Product Catalog` in Unity. The window reads each current product `ProductManifest.json`, shows the product state and target adapter, validates that paths remain inside the product root, and provides direct buttons for:

- outfit Prefab
- target-avatar integrated Prefab
- representative preview
- demo scene
- installation or product documentation
- product folder and manifest

Historical snapshots are inspected directly under `Assets/GenWorks/Legacy/Snapshots/`. This keeps them available to Unity without presenting them as saleable products.

## Existing jobs and assets

Run a dry-run first:

```powershell
task maintenance:migrate:genworks
```

Apply the migration after reviewing the JSON plan:

```powershell
task maintenance:migrate:genworks:apply
```

The migration scans `Assets/_Local/Jobs/**/job.json`, moves existing generated deliverables into the corresponding product root, moves Unity `.meta` files together with assets to preserve GUIDs, rewrites job paths, and creates a product manifest. Private avatar sources and license evidence are not moved.

Historical snapshot files formerly stored under the two deprecated Published paths are retained under `Assets/GenWorks/Legacy/Snapshots/`. Existing file blobs and committed Unity `.meta` files are retained so historical evidence and asset GUIDs are not rewritten merely because the directory changed.

## Audit

```powershell
task audit:repo
task audit:genworks
```

`tools/audit_repository_hygiene.py` rejects committed workflow state, self-mutating workflows, product-specific global configuration, and hard-coded product workflows or tasks. `tools/audit_genworks_layout.py` validates manifest identity, product-root containment, duplicate product IDs, missing referenced assets, forbidden asset roots, and production-like assets outside the canonical root. The machine-readable layout contract is `config/genworks-layout.json`.

## Distribution boundary

The canonical private roots stay outside product roots and must not enter a customer package:

```text
Assets/_Local/
Assets/_Vendor/
Assets/_Reference/
```

Target-avatar integration Prefabs may reference local avatar assets for developer verification, but the release allowlist must contain only the outfit product files that the customer is permitted to receive. Legacy snapshots remain evidence-only until they are rebuilt as a current product and pass all mandatory review and runtime gates.
