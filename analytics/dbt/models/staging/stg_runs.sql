select *
from read_json_auto(
  '{{ var("runs_path") }}',
  format = 'newline_delimited'
)
