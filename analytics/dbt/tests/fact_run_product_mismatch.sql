select f.product_id, f.run_id, r.product_id as run_product_id
from {{ ref('fct_gate_observation') }} f
join {{ ref('dim_run') }} r using (run_id)
where f.product_id <> r.product_id
