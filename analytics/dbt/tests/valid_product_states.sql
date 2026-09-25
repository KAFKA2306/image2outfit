select *
from {{ ref('stg_products') }}
where product_status is null
   or product_status not in ('WORKING', 'COMPLETE', 'REJECTED')
