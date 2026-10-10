select
  product_id,
  run_id,
  gate_family || ':' || gate_name as gate_id,
  gate_state,
  normalized_gate_state,
  gate_state_known,
  gate_state_policy_path,
  gate_state_policy_sha256,
  manifest_path,
  manifest_sha256
from {{ ref('stg_gates') }}
