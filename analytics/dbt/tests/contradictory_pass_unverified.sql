select
  a.product_id,
  a.run_id,
  a.gate_name,
  a.gate_family as pass_family,
  b.gate_family as contradictory_family
from {{ ref('stg_gates') }} a
join {{ ref('stg_gates') }} b
  on a.product_id = b.product_id
 and a.run_id = b.run_id
 and a.gate_name = b.gate_name
 and a.gate_family < b.gate_family
where (
  a.gate_state = 'PASS'
  and b.gate_state in ('UNVERIFIED', 'PENDING')
) or (
  b.gate_state = 'PASS'
  and a.gate_state in ('UNVERIFIED', 'PENDING')
)
