select *
from {{ ref('stg_gates') }}
where not gate_state_known
   or normalized_gate_state is null
