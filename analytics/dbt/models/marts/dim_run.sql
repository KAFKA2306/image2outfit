select
  run_id,
  product_id,
  generated_at,
  design_revision,
  run_status,
  manifest_path,
  manifest_sha256
from {{ ref('stg_runs') }}
