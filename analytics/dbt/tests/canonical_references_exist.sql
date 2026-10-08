select *
from {{ ref('stg_products') }}
where not job_exists
   or not construction_exists
   or not manifest_exists
