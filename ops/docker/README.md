# Python / Docker batch execution

The batch layer does not introduce a second garment pipeline. It only schedules the existing canonical per-product wrapper:

```text
config/batch/*.json
  -> tools/manage.py batch run
  -> tools/batch_execution.py
  -> tools/run_product_execution.py
  -> existing pipeline checkpoint + audit bundle
```

## Why this is resumable

Each product already owns its checkpoint at:

```text
.image2outfit/products/<product>/reports/pipeline-state.json
```

and its scheduler projection at:

```text
.image2outfit/products/<product>/reports/product-execution-state.json
```

Running the same batch again does not create a parallel retry database. The canonical product executor reuses a matching terminal `EXECUTED` checkpoint and resumes a failed checkpoint at the first unfinished stage.

The batch is intentionally serialized with `maxConcurrency: 1`. One failed product does not stop observation/execution of later products.

## Native Python entrypoints

```powershell
task batch:status
task batch:run
```

Override the tracked manifest when needed:

```powershell
task batch:run BATCH=config/batch/tracked-requests.json
```

Exit status:

- `0`: every product execution reached `SUCCEEDED`
- `2`: no execution failure remains, but direct visual review is required
- `1`: at least one product is `FAILED`, `BLOCKED`, or has no usable execution state

These are scheduler states only. They do not mean the product is `COMPLETE` or releasable.

## Docker coordinator

The Docker image is deliberately thin. The repository is bind-mounted so the container uses the same tracked requests and the same Git-ignored `.image2outfit` checkpoints as native execution.

```bash
docker compose -f ops/docker/compose.batch.yml run --rm batch \
  python tools/manage.py batch status \
  --manifest config/batch/tracked-requests.json
```

To execute/resume:

```bash
docker compose -f ops/docker/compose.batch.yml run --rm batch \
  python tools/manage.py batch run \
  --manifest config/batch/tracked-requests.json
```

Python-only stages can run in the coordinator. A Blender-dependent stage remains a real external boundary unless the pinned Blender 4.4.3 Linux executable and all required private inputs are explicitly made available inside the container. The batch runner never fabricates PASS for missing Blender, Unity, visual-review, or private-reference evidence.
