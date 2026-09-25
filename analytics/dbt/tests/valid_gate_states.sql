select *
from {{ ref('stg_gates') }}
where gate_state not in (
  'PASS',
  'FAIL',
  'PENDING',
  'UNVERIFIED',
  'OUT_OF_SCOPE',
  'VERIFIED',
  'REJECTED',
  'SKIPPED',
  'NOT_APPLICABLE'
)
