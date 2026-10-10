select distinct
  gate_family || ':' || gate_name as gate_id,
  gate_family,
  gate_name
from {{ ref('stg_gates') }}
