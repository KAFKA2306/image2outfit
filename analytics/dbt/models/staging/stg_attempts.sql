-- Explicit columns so an empty attempts.jsonl (no local attempt history, as in
-- a clean CI checkout) yields zero rows instead of a schema-inference error.
select *
from read_json(
  '{{ var("attempts_path") }}',
  format = 'newline_delimited',
  columns = {
    'attempt_id': 'VARCHAR',
    'product_id': 'VARCHAR',
    'attempt_name': 'VARCHAR',
    'stage_name': 'VARCHAR',
    'attempt_stamp': 'VARCHAR',
    'attempt_path': 'VARCHAR',
    'file_count': 'BIGINT',
    'attempt_sha256': 'VARCHAR'
  }
)
