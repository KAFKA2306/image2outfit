select product_id, run_id, gate_family, gate_name, count(*) as row_count
from {{ ref('stg_gates') }}
group by product_id, run_id, gate_family, gate_name
having count(*) > 1
