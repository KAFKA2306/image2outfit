select *
from read_json_auto(
  '{{ var("gates_path") }}',
  format = 'newline_delimited'
)
