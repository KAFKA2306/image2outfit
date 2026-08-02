# Repository hygiene

The repository uses four durable boundaries:

1. Shared contracts under `config/`.
2. Tracked product definitions under `config/products/<product-id>/`.
3. Unity-visible product and shared assets under `Assets/GenWorks/`.
4. Private sources and human evidence under ignored local, vendor, or reference roots.

GitHub Actions may build, audit, and upload artifacts. Build and validation workflows use `contents: read`; `contents: write` is forbidden for those workflows. They must not push generated assets, trigger files, telemetry, or run-state JSON directly to `main`.

Run the repository-level audit with:

```powershell
task audit:repo
```

The audit rejects committed `.github/run` or `.github/status` files, self-mutating workflows, product-specific JSON in global config, mismatched product boundaries, and hard-coded product workflows or tasks.

Add a product by creating `config/products/<product-id>/job.json` and `license.json`, not by cloning a product-specific workflow.
