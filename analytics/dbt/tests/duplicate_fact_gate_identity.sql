select product_id, run_id, gate_id, count(*) as row_count
from {{ ref('fct_gate_observation') }}
group by product_id, run_id, gate_id
having count(*) > 1
