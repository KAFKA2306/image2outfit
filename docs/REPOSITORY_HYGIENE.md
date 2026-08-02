# Repository hygiene

The repository is split into four durable boundaries:

1. Shared contracts under `config/`.
2. Tracked product definitions under `config/products/<product-id>/`.
3. Unity-visible product and shared assets under `Assets/GenWorks/`.
4. Private sources and human evidence under ignored local/vendor/reference roots.

GitHub Actions may build, audit, and upload artifacts. Build workflows must not push generated assets, trigger files, telemetry, or run-state JSON directly to `main`.

Run the repository-level audit with:

```powershell
task audit:repo
```

The audit rejects:

- committed `.github/run` or `.github/status` directories
- workflows with `contents: write` or `git push`
- product-specific JSON files directly under `config/`
- mismatched product IDs, roots, manifests, or license paths
- hard-coded product IDs in shared workflows or Taskfile tasks
- missing ignored-runtime-state rules

The policy is product-neutral. Add new products by creating `config/products/<product-id>/job.json` and `license.json`, not by cloning a product-specific workflow.
