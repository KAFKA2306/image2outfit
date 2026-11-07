select
  product_id,
  product_name,
  product_status,
  product_status_known,
  job_path,
  construction_path,
  manifest_path,
  job_sha256,
  construction_sha256,
  manifest_sha256
from {{ ref('stg_products') }}
