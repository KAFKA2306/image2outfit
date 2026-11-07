select *
from {{ ref('stg_products') }}
where not product_status_known
