select
  p.product_id,
  p.product_name,
  p.product_status,
  r.run_id,
  r.generated_at,
  r.design_revision,
  count(g.gate_name) as gate_count,
  sum(case when g.gate_state = 'PASS' then 1 else 0 end) as pass_gate_count,
  sum(case when g.gate_state = 'FAIL' then 1 else 0 end) as fail_gate_count,
  sum(case when g.gate_state = 'UNVERIFIED' then 1 else 0 end)
    as unverified_gate_count,
  sum(case when g.gate_state = 'PENDING' then 1 else 0 end)
    as pending_gate_count
from {{ ref('stg_products') }} p
left join {{ ref('stg_runs') }} r using (product_id)
left join {{ ref('stg_gates') }} g using (product_id, run_id)
group by
  p.product_id,
  p.product_name,
  p.product_status,
  r.run_id,
  r.generated_at,
  r.design_revision
