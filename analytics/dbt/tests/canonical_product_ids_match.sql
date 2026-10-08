select *
from {{ ref('stg_products') }}
where job_product_id is null
   or job_product_id <> product_id
   or construction_product_id is null
   or construction_product_id <> product_id
   or manifest_product_id is null
   or manifest_product_id <> product_id
